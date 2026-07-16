const { app, BrowserWindow, Menu, dialog, shell, ipcMain, clipboard } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const net = require("net");
const log = require("electron-log");
const { autoUpdater } = require("electron-updater");

let backendProcess = null;
let backendPort = null;
let mainWindow = null;
let isQuitting = false;
let backendShutdownPromise = null;

const BACKEND_SHUTDOWN_TIMEOUT_MS = 8000;
const BACKEND_FORCE_KILL_DELAY_MS = 2000;

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
    S2RS_ENABLE_CLOUD_EXTENSIONS: "1",
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

async function requestBackendShutdown(port) {
  if (!port) return false;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const response = await fetch(`http://127.0.0.1:${port}/api/shutdown`, {
      method: "POST",
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return response.ok;
  } catch (e) {
    logWarn("BACKEND", "Graceful shutdown request failed", { error: e.message });
    return false;
  }
}

function waitForBackendExit(proc, timeoutMs) {
  return new Promise((resolve) => {
    if (!proc || proc.exitCode !== null) {
      resolve(true);
      return;
    }
    const timer = setTimeout(() => resolve(false), timeoutMs);
    proc.once("exit", () => {
      clearTimeout(timer);
      resolve(true);
    });
  });
}

async function stopBackend({ force = false } = {}) {
  if (backendShutdownPromise) {
    return backendShutdownPromise;
  }

  backendShutdownPromise = (async () => {
    const proc = backendProcess;
    if (!proc || proc.exitCode !== null) {
      backendProcess = null;
      return;
    }

    logInfo("BACKEND", "Stopping backend process", { pid: proc.pid, port: backendPort });

    if (!force && backendPort) {
      await requestBackendShutdown(backendPort);
    }

    let exited = await waitForBackendExit(proc, BACKEND_SHUTDOWN_TIMEOUT_MS);
    if (!exited && proc.exitCode === null) {
      logWarn("BACKEND", "Backend did not exit in time — sending SIGTERM");
      try {
        if (process.platform === "win32") {
          proc.kill();
        } else {
          proc.kill("SIGTERM");
        }
      } catch (e) {
        logWarn("BACKEND", "Failed to send SIGTERM", { error: e.message });
      }
      exited = await waitForBackendExit(proc, BACKEND_FORCE_KILL_DELAY_MS);
    }

    if (!exited && proc.exitCode === null) {
      logWarn("BACKEND", "Force-killing backend process");
      try {
        proc.kill("SIGKILL");
      } catch (e) {
        logWarn("BACKEND", "Failed to force-kill backend", { error: e.message });
      }
      await waitForBackendExit(proc, 1000);
    }

    backendProcess = null;
    logInfo("BACKEND", "Backend stopped");
  })();

  try {
    await backendShutdownPromise;
  } finally {
    backendShutdownPromise = null;
  }
}

async function createWindow(port) {
  const baseUrl = `http://127.0.0.1:${port}`;
  logInfo("UI", "Creating BrowserWindow");

  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webviewTag: false,
      devTools: !app.isPackaged,
    },
  });

  attachContextMenu(win);
  logInfo("UI", "BrowserWindow created", { width: 1280, height: 800 });

  // Sandboxed Chromium often blocks Clipboard API; allow sanitized write/read
  // as a belt-and-suspenders complement to the s2rs:clipboard-* IPC bridge.
  win.webContents.session.setPermissionRequestHandler((_wc, permission, callback) => {
    if (
      permission === "clipboard-sanitized-write" ||
      permission === "clipboard-read"
    ) {
      callback(true);
      return;
    }
    callback(false);
  });

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
  mainWindow = win;
  win.on("closed", () => {
    if (mainWindow === win) {
      mainWindow = null;
    }
  });
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
  backendPort = port;
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

function sanitizeGleanFilename(name) {
  const base = path.basename(String(name || "s2rs-incident-packet.md"));
  const cleaned = base.replace(/[^a-zA-Z0-9._-]/g, "_");
  if (!cleaned || cleaned === "." || cleaned === "..") {
    return "s2rs-incident-packet.md";
  }
  return cleaned.endsWith(".md") ? cleaned : `${cleaned}.md`;
}

function openGleanApp() {
  return new Promise((resolve) => {
    if (process.platform === "darwin") {
      const child = spawn("open", ["-a", "Glean"], { stdio: "ignore" });
      child.on("error", () => resolve(false));
      child.on("exit", (code) => resolve(code === 0));
      return;
    }
    shell
      .openExternal("https://app.glean.com/chat")
      .then(() => resolve(true))
      .catch(() => resolve(false));
  });
}

function setupGleanHandoffIpc() {
  ipcMain.handle("s2rs:glean-handoff", async (_event, payload = {}) => {
    const filename = sanitizeGleanFilename(payload.filename);
    const markdown = String(payload.markdown || "");
    const prompt = String(payload.prompt || "");
    const downloads = app.getPath("downloads");
    const target = path.join(downloads, filename);

    await fs.promises.writeFile(target, markdown, "utf8");
    if (prompt) {
      clipboard.writeText(prompt);
    }
    shell.showItemInFolder(target);

    let gleanOpened = await openGleanApp();
    if (!gleanOpened) {
      try {
        await shell.openExternal("https://app.glean.com/chat");
        gleanOpened = true;
      } catch (err) {
        logWarn("GLEAN", "Failed to open Glean web fallback", { error: err.message });
        gleanOpened = false;
      }
    }

    logInfo("GLEAN", "Handoff complete", { target, gleanOpened });
    return { saved_path: target, glean_opened: gleanOpened };
  });
}

function setupClipboardIpc() {
  ipcMain.handle("s2rs:clipboard-write", (_event, text) => {
    clipboard.writeText(String(text ?? ""));
    return true;
  });
  ipcMain.handle("s2rs:clipboard-read", () => clipboard.readText());
}

function attachContextMenu(win) {
  win.webContents.on("context-menu", (_event, params) => {
    const template = [
      { role: "cut", enabled: params.editFlags.canCut },
      { role: "copy", enabled: params.editFlags.canCopy },
      { role: "paste", enabled: params.editFlags.canPaste },
      { type: "separator" },
      { role: "selectAll", enabled: params.editFlags.canSelectAll },
    ];
    Menu.buildFromTemplate(template).popup({ window: win });
  });
}

function setupMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: "about" },
              { type: "separator" },
              { role: "services" },
              { type: "separator" },
              { role: "hide" },
              { role: "hideOthers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]
      : []),
    {
      label: "File",
      submenu: [
        { label: "Install Update Package", click: installUpdatePackage },
        { type: "separator" },
        { label: "Show Log File", click: showOpenLogFile },
        { type: "separator" },
        isMac ? { role: "close" } : { role: "quit" },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        ...(isMac ? [{ role: "pasteAndMatchStyle" }, { role: "delete" }] : []),
        { type: "separator" },
        { role: "selectAll" },
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

function handleProcessSignal(signal) {
  logInfo("APP", `Received ${signal}`);
  if (!isQuitting) {
    app.quit();
  }
}

process.on("SIGTERM", () => handleProcessSignal("SIGTERM"));
process.on("SIGINT", () => handleProcessSignal("SIGINT"));

app.whenReady().then(() => {
  logInfo("APP", "Electron app ready", {
    version: app.getVersion(),
    args: process.argv,
  });

  setupMenu();
  setupGleanHandoffIpc();
  setupClipboardIpc();

  // ── Auto-updater setup ──────────────────────────────────────────────
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on("checking-for-update", () => {
    logInfo("UPDATER", "Checking for updates...");
  });

  autoUpdater.on("update-available", (info) => {
    logInfo("UPDATER", "Update available", { version: info.version });
    dialog.showMessageBox({
      type: "info",
      title: "Update Available",
      message: `Version ${info.version} is available. Download now?`,
      buttons: ["Download", "Later"],
    }).then(({ response }) => {
      if (response === 0) {
        logInfo("UPDATER", "User chose to download update");
        autoUpdater.downloadUpdate();
      }
    });
  });

  autoUpdater.on("update-not-available", (info) => {
    logInfo("UPDATER", "No update available", { version: info.version });
  });

  autoUpdater.on("download-progress", (progress) => {
    logInfo("UPDATER", "Download progress", {
      percent: Math.round(progress.percent),
      transferred: progress.transferred,
      total: progress.total,
    });
  });

  autoUpdater.on("update-downloaded", (info) => {
    logInfo("UPDATER", "Update downloaded", { version: info.version });
    dialog.showMessageBox({
      type: "info",
      title: "Update Ready",
      message: `Version ${info.version} has been downloaded. Restart now to install it?`,
      buttons: ["Restart and Install", "Later"],
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.quitAndInstall();
      }
    });
  });

  autoUpdater.on("error", (err) => {
    logError("UPDATER", "Update error", { error: err.message });
  });

  // Preserve the app's offline-first contract. Packaged builds only contact
  // the configured update provider when the operator explicitly opts in.
  const autoUpdateEnabled = ["1", "true", "yes", "on"].includes(
    String(process.env.S2RS_ENABLE_AUTO_UPDATE || "").trim().toLowerCase()
  );
  if (app.isPackaged && autoUpdateEnabled) {
    autoUpdater.checkForUpdates().catch((e) => {
      logWarn("UPDATER", "Update check failed", { error: e.message });
    });
  } else if (app.isPackaged) {
    logInfo("UPDATER", "Automatic update check disabled (set S2RS_ENABLE_AUTO_UPDATE=1 to enable)");
  } else {
    logInfo("UPDATER", "Skipping update check in development mode");
  }

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

app.on("before-quit", (event) => {
  if (isQuitting) {
    return;
  }
  event.preventDefault();
  isQuitting = true;
  logInfo("APP", "before-quit — initiating graceful shutdown");

  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.close();
  }

  stopBackend()
    .catch((e) => {
      logWarn("APP", "Graceful backend shutdown failed", { error: e.message });
    })
    .finally(() => {
      app.exit(0);
    });
});

app.on("window-all-closed", () => {
  logInfo("APP", "All windows closed");
  if (process.platform === "darwin") {
    stopBackend().catch((e) => {
      logWarn("APP", "Failed to stop backend after window close", { error: e.message });
    });
    return;
  }
  app.quit();
});

app.on("activate", () => {
  logInfo("APP", "App activated");
  if (BrowserWindow.getAllWindows().length === 0) {
    bootstrap().catch((e) => logError("APP", "Re-activate bootstrap failed", { error: e.message }));
  }
});

app.on("will-quit", () => {
  logInfo("APP", "App will quit");
});

app.on("quit", () => {
  logInfo("APP", "App quit");
});
