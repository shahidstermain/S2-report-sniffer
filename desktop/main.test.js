const test = require("node:test");
const assert = require("node:assert/strict");
const EventEmitter = require("node:events");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");
const { spawn } = require("node:child_process");

function loadMainWithElectronMock() {
  const tmpUserData = fs.mkdtempSync(path.join(os.tmpdir(), "s2rs-desktop-test-"));
  const appEmitter = new EventEmitter();
  const exitCalls = [];
  appEmitter.getPath = (name) => (name === "downloads" ? tmpUserData : tmpUserData);
  appEmitter.getVersion = () => "1.2.17";
  appEmitter.isPackaged = false;
  appEmitter.isReady = () => true;
  appEmitter.name = "S2 Report Sniffer";
  appEmitter.whenReady = () => new Promise(() => {});
  appEmitter.quit = () => {};
  appEmitter.exit = (code) => {
    exitCalls.push(code);
  };

  const electronMock = {
    app: appEmitter,
    BrowserWindow: class {
      static getAllWindows() {
        return [];
      }
    },
    Menu: {
      buildFromTemplate: () => ({ popup: () => {} }),
      setApplicationMenu: () => {},
    },
    dialog: { showErrorBox: () => {}, showOpenDialog: async () => ({ canceled: true }) },
    shell: { openExternal: async () => {}, openPath: async () => "", showItemInFolder: () => {} },
    ipcMain: { handle: () => {} },
    clipboard: { writeText: () => {}, readText: () => "" },
  };

  const origLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === "electron") return electronMock;
    if (request === "electron-log") return {};
    if (request === "electron-updater") return { autoUpdater: new EventEmitter() };
    return origLoad.call(this, request, parent, isMain);
  };

  const mainPath = require.resolve("./main.js");
  delete require.cache[mainPath];
  let loaded;
  try {
    loaded = require("./main.js");
  } finally {
    Module._load = origLoad;
  }

  return { main: loaded, appEmitter, exitCalls, tmpUserData };
}

test("waitForHealthy aborts immediately when backend process exits early", async () => {
  const { main, tmpUserData } = loadMainWithElectronMock();
  try {
    const proc = spawn(process.execPath, ["-e", "setTimeout(() => process.exit(1), 50);"], {
      stdio: "ignore",
    });

    const started = Date.now();
    const healthy = await main.waitForHealthy("http://127.0.0.1:59999", 20000, proc);
    const elapsedMs = Date.now() - started;

    assert.equal(healthy, false);
    assert.ok(elapsedMs < 2000, `expected early abort (<2000ms), took ${elapsedMs}ms`);
    assert.equal(main.formatBackendExit(proc), "code 1");
  } finally {
    fs.rmSync(tmpUserData, { recursive: true, force: true });
  }
});

test("before-quit prevents default on repeated quit events until stopBackend completes", async () => {
  const { main, appEmitter, exitCalls, tmpUserData } = loadMainWithElectronMock();
  let child = null;
  try {
    // Spawn a process that takes 250ms to exit on SIGTERM so the second
    // before-quit definitely fires while stopBackend() is still awaiting exit.
    child = spawn(
      process.execPath,
      [
        "-e",
        "process.on('SIGTERM', () => setTimeout(() => process.exit(0), 250)); console.log('ready'); setInterval(() => {}, 1000);",
      ],
      { stdio: ["ignore", "pipe", "ignore"], detached: process.platform !== "win32" }
    );
    await new Promise((resolve) => {
      child.stdout.once("data", () => resolve());
    });
    main._setTestState({
      backendProcess: child,
      backendPort: null,
      isQuitting: false,
      readyToExit: false,
    });

    let firstPrevented = false;
    appEmitter.emit("before-quit", {
      preventDefault: () => {
        firstPrevented = true;
      },
    });
    assert.equal(firstPrevented, true);
    assert.equal(exitCalls.length, 0);

    // Second quit trigger while stopBackend() is waiting on BACKEND_SHUTDOWN_TIMEOUT_MS
    let secondPrevented = false;
    appEmitter.emit("before-quit", {
      preventDefault: () => {
        secondPrevented = true;
      },
    });
    assert.equal(secondPrevented, true);
    assert.equal(exitCalls.length, 0, "app.exit must not fire before stopBackend finishes");

    // Wait for stopBackend() shutdown flow to terminate the child and call app.exit(0)
    const deadline = Date.now() + 15000;
    while (exitCalls.length === 0 && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 100));
    }
    assert.deepEqual(exitCalls, [0]);
  } finally {
    if (child && child.exitCode === null) {
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch (_) {}
    }
    fs.rmSync(tmpUserData, { recursive: true, force: true });
  }
});

test("stopBackend kills detached process group including child processes on POSIX", { skip: process.platform === "win32" }, async () => {
  const { main, tmpUserData } = loadMainWithElectronMock();
  const pidFile = path.join(tmpUserData, "grandchild.pid");
  let proc = null;
  let grandchildPid = null;
  try {
    const script = `
      const fs = require('fs');
      const { spawn } = require('child_process');
      const gc = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
      fs.writeFileSync(${JSON.stringify(pidFile)}, String(gc.pid));
      setInterval(() => {}, 1000);
    `;
    proc = spawn(process.execPath, ["-e", script], {
      stdio: "ignore",
      detached: true,
    });

    const deadline = Date.now() + 5000;
    while (!fs.existsSync(pidFile) && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 50));
    }
    grandchildPid = Number(fs.readFileSync(pidFile, "utf8").trim());
    assert.ok(Number.isInteger(grandchildPid) && grandchildPid > 0);

    main._setTestState({
      backendProcess: proc,
      backendPort: null,
      isQuitting: false,
      readyToExit: false,
    });

    await main.stopBackend({ force: true });

    // Brief yield for OS process reaping
    await new Promise((r) => setTimeout(r, 150));

    let grandchildAlive = true;
    try {
      process.kill(grandchildPid, 0);
    } catch (e) {
      if (e.code === "ESRCH") grandchildAlive = false;
    }
    assert.equal(grandchildAlive, false, "grandchild process should have been killed with the process group");
  } finally {
    if (grandchildPid) {
      try { process.kill(grandchildPid, "SIGKILL"); } catch (_) {}
    }
    if (proc && proc.pid) {
      try { process.kill(-proc.pid, "SIGKILL"); } catch (_) {}
    }
    fs.rmSync(tmpUserData, { recursive: true, force: true });
  }
});
