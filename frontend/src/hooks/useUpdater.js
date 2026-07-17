import { useCallback, useEffect, useState } from "react";

const initialState = {
  status: "idle",
  version: null,
  releaseNotes: null,
  downloadPercent: 0,
  error: null,
};

function updaterBridge() {
  return typeof window !== "undefined" ? window.s2rsDesktop?.updater : undefined;
}

export function useUpdater() {
  const [state, setState] = useState(initialState);

  useEffect(() => {
    const updater = updaterBridge();
    if (!updater) return undefined;
    const cleanups = [
      updater.onChecking(() => setState((current) => ({ ...current, status: "checking", error: null }))),
      updater.onUpdateAvailable((info) => {
        if (localStorage.getItem("s2rs:update-dismissed") === info.version) return;
        setState({ ...initialState, status: "available", version: info.version, releaseNotes: info.releaseNotes });
      }),
      updater.onUpdateProgress((progress) => setState((current) => ({
        ...current,
        status: "downloading",
        downloadPercent: progress.percent,
      }))),
      updater.onUpdateDownloaded((info) => setState((current) => ({
        ...current,
        status: "ready",
        version: info.version || current.version,
        releaseNotes: info.releaseNotes || current.releaseNotes,
        downloadPercent: 100,
      }))),
      updater.onUpdateNotAvailable(() => setState((current) => ({ ...current, status: "up-to-date" }))),
      updater.onUpdateError((error) => setState((current) => ({
        ...current,
        status: "error",
        error: error?.message || String(error || "Update failed"),
      }))),
    ];
    return () => cleanups.forEach((cleanup) => cleanup?.());
  }, []);

  const checkNow = useCallback(() => updaterBridge()?.checkForUpdates(), []);
  const download = useCallback(() => updaterBridge()?.downloadUpdate(), []);
  const install = useCallback(() => updaterBridge()?.installUpdate(), []);
  const dismiss = useCallback(() => {
    if (state.version) localStorage.setItem("s2rs:update-dismissed", state.version);
    setState(initialState);
  }, [state.version]);

  return { ...state, available: Boolean(updaterBridge()), checkNow, download, install, dismiss };
}
