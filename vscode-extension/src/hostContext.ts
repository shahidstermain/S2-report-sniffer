import * as vscode from "vscode";

/** Must stay in sync with `frontend/src/lib/hostContext.js` */
export const S2RS_HOST_QUERY = "s2rs_host";
export const S2RS_THEME_QUERY = "s2rs_theme";

export function vscodeThemeQueryValue(): string {
  const k = vscode.window.activeColorTheme.kind;
  if (k === vscode.ColorThemeKind.Light) return "light";
  if (k === vscode.ColorThemeKind.HighContrastLight) return "hcLight";
  if (k === vscode.ColorThemeKind.HighContrast) {
    return "hcDark";
  }
  return "dark";
}

/** Adds host + editor theme so the web app can match VS Code chrome without a webview postMessage bridge. */
export function augmentUriForEmbeddedUi(uri: vscode.Uri): vscode.Uri {
  const q = new URLSearchParams(uri.query || "");
  q.set(S2RS_HOST_QUERY, "vscode");
  q.set(S2RS_THEME_QUERY, vscodeThemeQueryValue());
  return uri.with({ query: q.toString() });
}

/**
 * Resolves loopback for Remote-SSH / Codespaces: `asExternalUri` rewrites when needed.
 */
export async function resolveUiUri(uri: vscode.Uri): Promise<vscode.Uri> {
  try {
    return await vscode.env.asExternalUri(uri);
  } catch {
    return uri;
  }
}
