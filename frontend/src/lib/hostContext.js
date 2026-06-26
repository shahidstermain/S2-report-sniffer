/**
 * Detects when the UI was opened from the S2 Report Sniffer VS Code extension
 * (query params) and applies host hints before React mounts.
 *
 * Params (stripped from the URL after read via replaceState):
 * - s2rs_host=vscode
 * - s2rs_theme= light | dark | hcLight | hcDark  (set by extension from ColorThemeKind)
 */

export const S2RS_HOST_QUERY = "s2rs_host";
export const S2RS_THEME_QUERY = "s2rs_theme";

/** Vite `public/` asset path that works for dev (`/`) and prod (`/ui/`). */
export function publicAsset(relativePath) {
  const trimmed = String(relativePath || "").replace(/^\//, "");
  const base = import.meta.env.BASE_URL || "/";
  const normalized = base.endsWith("/") ? base : `${base}/`;
  return `${normalized}${trimmed}`;
}

export function isVsCodeHost() {
  if (typeof document === "undefined") return false;
  return document.documentElement.getAttribute("data-s2rs-host") === "vscode";
}

function applyThemeFromHost(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "hcLight") {
    root.classList.remove("dark");
    root.setAttribute("data-theme", "light");
  } else {
    root.classList.add("dark");
    root.setAttribute("data-theme", "dark");
  }
  try {
    window.localStorage.setItem("s2rs.theme", theme === "light" || theme === "hcLight" ? "light" : "dark");
  } catch {
    /* ignore */
  }
}

/**
 * Call once at startup (before React). Idempotent.
 */
export function initHostContext() {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  try {
    const url = new URL(window.location.href);
    const host = url.searchParams.get(S2RS_HOST_QUERY);
    if (host !== "vscode") return;

    const root = document.documentElement;
    root.setAttribute("data-s2rs-host", "vscode");

    const theme = url.searchParams.get(S2RS_THEME_QUERY);
    const normalized =
      theme === "light" || theme === "dark" || theme === "hcLight" || theme === "hcDark"
        ? theme
        : "dark";
    root.setAttribute("data-s2rs-vscode-theme", normalized);
    applyThemeFromHost(normalized);

    url.searchParams.delete(S2RS_HOST_QUERY);
    url.searchParams.delete(S2RS_THEME_QUERY);
    const next = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(window.history.state, "", next);
  } catch {
    /* malformed URL or restricted history */
  }
}
