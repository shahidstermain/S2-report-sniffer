const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("s2rsDesktop", {
  gleanHandoff: (payload) => ipcRenderer.invoke("s2rs:glean-handoff", payload),
});
