const { app, BrowserWindow, Menu, dialog, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const net = require("net");
const log = require("electron-log");

let backendProcess = null;

const LOG_DIR = path.join(app.getPath("userData"), "logs");
const LOG_FILE = path.join(LOG_DIR, "s2rs-startup.log");
const MAX_LOG_LINES = 5000;

function ensureLogDir() {
  try {
    if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
  } catch (e) {
    console.error("[S2RS] Cannot create log dir:", e);
  }
}

function writeLog(level, component, message, data = null) {
  ensureLogDir();
  const ts = new Date().toISOString();
  const entry = {
    ts,
    level,
    component,
    message,
    ...(data ? { data } : {}),
  };
  const line = JSON.stringify(entry) + "\n";
  try {
    fs.appendFileSync(LOG_FILE, line);
    // Rotate: keep last MAX_LOG_LINES
    const content = fs.readFileSync(LOG_FILE, "utf8");
    const lines = content.split("\n").filter(Boolean);
    if (lines.length > MAX_LOG_LINES) {
      fs.writeFileSync(LOG_FILE, lines.slice(-MAX_LOG_LINES).join("\n") + "\n");
    }
  } catch (e) {
    console.error("[S2RS] Log write failed:", e);
  }
  const prefix = `[${ts}] [${level}] [${component}]`;
  if (level === "ERROR") {
    console.error(prefix, message, data || "");
  } else {
    console.log(prefix, message, data || "");
  }
}

function logInfo(component, message, data)  { writeLog("INFO",  component, message, data); }
function logWarn(component, message, data) { writeLog("WARN",  component, message, data); }
function logError(component, message, data) { writeLog("ERROR", component, message, data); }
function logDebug(component, message, data) { writeLog("DEBUG", component, message, data); }

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", (e) => {
      logError("NET", "getFreePort failed", { error: e.message });
      reject(e);
    });
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => {
        logInfo("NET", `Port selected: ${port}`, { port });
        resolve(port);
      });
    });
  });
}

async function waitForHealthy(baseUrl, timeoutMs) {
  const start = Date.now();
  const url = new URL(baseUrl);
  const host = url.hostname;
  const port = parseInt(url.port || (url.protocol === "https:" ? 443 : 80), 10);
  logInfo("BACKEND", `Waiting for backend to bind port ${port} (timeout ${timeoutMs}ms)`);

  while (Date.now() - start < timeoutMs) {
    const healthy = await new Promise((resolve) => {
      const sock = net.connect(port, host, () => {
        sock.once("end", () => {});
        sock.destroy();
        resolve(true);
      });
      sock.on("error", () => { resolve(false); });
      sock.setTimeout(500, () => { try { sock.destroy(); } catch(_) {} resolve(false); });
    });

    if (healthy) {
      logInfo("BACKEND", `Backend port ${port} is open`, { host, port, elapsedMs: Date.now() - start });
      return true;
    }
    await new Promise((r) => setTimeout(r, 500));
  }

  logError("BACKEND", "Backend port never opened", { timeout: timeoutMs, host, port });
  return false;
}

function startBackend(port) {
  const resources = process.resourcesPath || app.getAppPath();
  const backendDir = path.join(resources, "backend");
  const uiDir = path.join(resources, "ui");

  const exeName = process.platform === "win32" ? "s2rs-backend.exe" : "s2rs-backend";
  const exePath = path.join(backendDir, exeName);

  logInfo("BACKEND", "Checking backend binary", { exePath, resources, backendDir });

  // Verify binary exists and is executable
  if (!fs.existsSync(exePath)) {
    logError("BACKEND", "Backend binary not found!", { exePath, backendDir });
    // List what IS in the backend directory
    let contents = [];
    try { contents = fs.readdirSync(backendDir); } catch (e) {}
    logError("BACKEND", "Backend dir contents", { contents, backendDir });
    throw new Error(`Backend binary not found: ${exePath}`);
  }

  const stat = fs.statSync(exePath);
  logInfo("BACKEND", "Binary stat", {
    size: stat.size,
    mode: stat.mode.toString(8),
    isFile: stat.isFile(),
  });

  if (!(stat.mode & 0o100)) {
    logWarn("BACKEND", "Binary lacks execute permission — patching", {
      mode: stat.mode.toString(8),
    });
    try {
      fs.chmodSync(exePath, 0o755);
      logInfo("BACKEND", "Binary chmod 755 applied");
    } catch (e) {
      logError("BACKEND", "Failed to chmod binary", { error: e.message });
    }
  }

  const env = {
    ...process.env,
    PYI_TMPDIR: require("os").tmpdir(),
    S2RS_HOST: "127.0.0.1",
    S2RS_PORT: String(port),
    S2RS_UI_DIR: uiDir,
    STORAGE_BACKEND: "local",
    S2RS_ENVIRONMENT: app.isPackaged ? "production" : "development",
    S2RS_LOG_LEVEL: "info",
  };

  logInfo("BACKEND", `Spawning backend process`, { exePath, env: { ...env, PATH: "[redacted]" } });

  backendProcess = spawn(exePath, [], {
    env,
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });

  let stderrBuffer = "";
  backendProcess.stdout.on("data", (d) => {
    const lines = d.toString().trim().split("\n");
    lines.forEach((l) => { if (l) logInfo("BACKEND_STDOUT", l); });
  });
  backendProcess.stderr.on("data", (d) => {
    stderrBuffer += d.toString();
  });
  backendProcess.on("exit", (code, signal) => {
    logInfo("BACKEND", `Backend exited`, { code, signal });
    if (stderrBuffer) {
      logWarn("BACKEND_STDERR", "Backend stderr on exit", { stderr: stderrBuffer.trim() });
      stderrBuffer = "";
    }
  });
  backendProcess.on("error", (e) => {
    logError("BACKEND", "Backend spawn error", { error: e.message, code: e.code });
  });

  // Log env vars that matter (redact sensitive)
  logInfo("BACKEND", "Backend started with env", {
    S2RS_HOST: env.S2RS_HOST,
    S2RS_PORT: env.S2RS_PORT,
    STORAGE_BACKEND: env.STORAGE_BACKEND,
    packaged: app.isPackaged,
  });

  return port;
}

async function createWindow(port) {
  const baseUrl = `http://127.0.0.1:${port}`;
  logInfo("UI", "Creating BrowserWindow");

  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webviewTag: false,
      devTools: !app.isPackaged,
    },
  });

  logInfo("UI", "BrowserWindow created", { width: 1280, height: 800 });

  win.webContents.on("will-navigate", (event, url) => {
    try {
      const parsed = new URL(url);
      if (parsed.origin !== `http://127.0.0.1:${port}`) {
        logWarn("NAV", "External navigation blocked", { url });
        event.preventDefault();
        if (parsed.protocol === "https:" || parsed.protocol === "http:") {
          shell.openExternal(url);
        }
      }
    } catch {
      event.preventDefault();
      logWarn("NAV", "Navigation blocked (parse error)", { url });
    }
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "https:" || parsed.protocol === "http:") {
        if (parsed.origin !== `http://127.0.0.1:${port}`) {
          logInfo("WINDOW_OPEN", "Opening external URL", { url });
          shell.openExternal(url);
        }
      } else {
        logWarn("WINDOW_OPEN", "Blocked non-http(s) URL", { url, protocol: parsed.protocol });
      }
    } catch {
      logWarn("WINDOW_OPEN", "Blocked unknown URL", { url });
    }
    return { action: "deny" };
  });

  win.webContents.on("did-fail-load", (event, errorCode, errorDescription) => {
    logError("UI", "Page failed to load", { errorCode, errorDescription });
  });

  win.webContents.on("render-process-gone", (event, details) => {
    logError("UI", "Renderer process gone", details);
  });

  win.webContents.on("crashed", () => {
    logError("UI", "Renderer crashed!");
  });

  const loadUrl = `${baseUrl}/ui/`;
  logInfo("UI", `Loading URL: ${loadUrl}`);

  const healthy = await waitForHealthy(baseUrl, 40000);
  if (!healthy) {
    logError("UI", "Cannot load UI — backend health check failed", { baseUrl });
    throw new Error(`Backend never became healthy at ${baseUrl}`);
  }

  await win.loadURL(loadUrl);
  logInfo("UI", "UI loaded successfully");
}

async function bootstrap() {
  logInfo("APP", "Bootstrap starting", {
    version: app.getVersion(),
    platform: process.platform,
    arch: process.arch,
    resourcesPath: process.resourcesPath,
    packaged: app.isPackaged,
  });

  const port = await getFreePort();
  startBackend(port);

  try {
    await createWindow(port);
  } catch (e) {
    logError("APP", "Bootstrap failed", { error: e.message, stack: e.stack });
    throw e;
  }

  logInfo("APP", "Bootstrap complete");
}

function installUpdatePackage() {
  logInfo("MENU", "Opening update package dialog");
  dialog
    .showOpenDialog({
      title: "Select Update Package",
      properties: ["openFile"],
    })
    .then((result) => {
      if (result.canceled) return;
      const fp = result.filePaths && result.filePaths[0];
      if (!fp) return;
      logInfo("MENU", "Opening update package", { fp });
      shell.openPath(fp);
    })
    .catch((e) => {
      logError("MENU", "Install update dialog error", { error: e.message });
    });
}

function showOpenLogFile() {
  ensureLogDir();
  logInfo("MENU", "Opening log file", { LOG_FILE });
  shell.showItemInFolder(LOG_FILE);
}

function setupMenu() {
  const template = [
    {
      label: "File",
      submenu: [
        { label: "Install Update Package", click: installUpdatePackage },
        { type: "separator" },
        { label: "Show Log File", click: showOpenLogFile },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "toggleDevTools" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ── Global exception handlers ────────────────────────────────────────────

process.on("uncaughtException", (e) => {
  logError("PROCESS", "Uncaught exception", { error: e.message, stack: e.stack });
  if (app.isReady()) {
    dialog.showErrorBox("S2 Report Sniffer — Error", e.message);
  }
});

process.on("unhandledRejection", (reason) => {
  const msg = reason instanceof Error ? reason.message : String(reason);
  const stack = reason instanceof Error ? reason.stack : null;
  logError("PROCESS", "Unhandled rejection", { reason: msg, stack });
});

// ── App lifecycle ──────────────────────────────────────────────────────────

app.whenReady().then(() => {
  logInfo("APP", "Electron app ready", {
    version: app.getVersion(),
    args: process.argv,
  });

  setupMenu();

  bootstrap().catch((e) => {
    logError("APP", "Bootstrap error", { error: e.message, stack: e.stack });
    if (app.isReady()) {
      dialog.showErrorBox(
        "S2 Report Sniffer — Startup Failed",
        `The app could not start:\n\n${e.message}\n\nCheck the log file for details.`
      );
    }
    app.quit();
  });
});

app.on("window-all-closed", () => {
  logInfo("APP", "All windows closed");
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  logInfo("APP", "App activated");
  if (BrowserWindow.getAllWindows().length === 0) {
    bootstrap().catch((e) => logError("APP", "Re-activate bootstrap failed", { error: e.message }));
  }
});

app.on("will-quit", () => {
  logInfo("APP", "App will quit");
  if (backendProcess) {
    try {
      backendProcess.kill();
      logInfo("APP", "Backend process killed");
    } catch (e) {
      logWarn("APP", "Failed to kill backend", { error: e.message });
    }
  }
});

app.on("quit", () => {
  logInfo("APP", "App quit");
});