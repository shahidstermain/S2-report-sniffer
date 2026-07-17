const { contextBridge, ipcRenderer } = require("electron");

function subscribe(channel, callback) {
  const handler = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

contextBridge.exposeInMainWorld("s2rsDesktop", {
  gleanHandoff: (payload) => ipcRenderer.invoke("s2rs:glean-handoff", payload),
  clipboardWriteText: (text) => ipcRenderer.invoke("s2rs:clipboard-write", text),
  clipboardReadText: () => ipcRenderer.invoke("s2rs:clipboard-read"),
  updater: {
    checkForUpdates: () => ipcRenderer.invoke("s2rs:updater:check"),
    downloadUpdate: () => ipcRenderer.invoke("s2rs:updater:download"),
    installUpdate: () => ipcRenderer.invoke("s2rs:updater:install"),
    getAutoUpdateEnabled: () => ipcRenderer.invoke("s2rs:updater:get-enabled"),
    setAutoUpdateEnabled: (enabled) => ipcRenderer.invoke("s2rs:updater:set-enabled", enabled),
    onChecking: (callback) => subscribe("s2rs:updater:checking", callback),
    onUpdateAvailable: (callback) => subscribe("s2rs:updater:available", callback),
    onUpdateNotAvailable: (callback) => subscribe("s2rs:updater:not-available", callback),
    onUpdateProgress: (callback) => subscribe("s2rs:updater:progress", callback),
    onUpdateDownloaded: (callback) => subscribe("s2rs:updater:downloaded", callback),
    onUpdateError: (callback) => subscribe("s2rs:updater:error", callback),
  },
});
