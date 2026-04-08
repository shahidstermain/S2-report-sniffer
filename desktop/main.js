const { app, BrowserWindow, Menu, dialog, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const net = require("net");
const log = require("electron-log");

let backendProcess = null;

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

async function waitForHealthy(baseUrl, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${baseUrl}/api/health`);
      if (res.ok) return true;
    } catch (e) {
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

function startBackend(port) {
  const resources = process.resourcesPath;
  const backendDir = path.join(resources, "backend");
  const uiDir = path.join(resources, "ui");

  const exeName =
    process.platform === "win32"
      ? "s2rs-backend.exe"
      : "s2rs-backend";
  const exePath = path.join(backendDir, exeName);

  const env = {
    ...process.env,
    S2RS_HOST: "127.0.0.1",
    S2RS_PORT: String(port),
    S2RS_UI_DIR: uiDir,
    STORAGE_BACKEND: "local",
  };

  backendProcess = spawn(exePath, [], {
    env,
    stdio: "pipe",
    windowsHide: true,
  });

  backendProcess.stdout.on("data", (d) => log.info(d.toString().trim()));
  backendProcess.stderr.on("data", (d) => log.error(d.toString().trim()));
  backendProcess.on("exit", (code) => log.info(`backend exited ${code}`));
}

async function createWindow(port) {
  const baseUrl = `http://127.0.0.1:${port}`;
  const ok = await waitForHealthy(baseUrl, 15000);
  if (!ok) {
    throw new Error("Backend did not become healthy");
  }

  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  await win.loadURL(`${baseUrl}/ui/`);
}

async function bootstrap() {
  const port = await getFreePort();
  startBackend(port);
  await createWindow(port);
}

function installUpdatePackage() {
  dialog
    .showOpenDialog({
      title: "Select Update Package",
      properties: ["openFile"],
    })
    .then((result) => {
      if (result.canceled) return;
      const fp = result.filePaths && result.filePaths[0];
      if (!fp) return;
      shell.openPath(fp);
    })
    .catch((e) => {
      log.error(e);
    });
}

function setupMenu() {
  const template = [
    {
      label: "File",
      submenu: [
        { label: "Install Update Package", click: installUpdatePackage },
        { role: "quit" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(() => {
  setupMenu();
  bootstrap().catch((e) => {
    log.error(e);
    app.quit();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  try {
    if (backendProcess) backendProcess.kill();
  } catch (e) {
  }
});
