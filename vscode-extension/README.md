# S2 Report Sniffer — VS Code extension

This extension is a **launcher** for the existing local web UI. It does not bundle the React app; it opens the URL served by your FastAPI backend (by default `http://127.0.0.1:8000/ui/`).

## Prerequisites

The **FastAPI backend must be running** and serving the UI at `/ui/` (for example after `frontend` is built, or per your deployment). From the repo root, typical dev commands are documented in the parent folder’s `README.md` and `AGENTS.md`, for example:

```bash
cd backend && uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

## Configuration

| Setting | Description | Default |
|--------|-------------|---------|
| `s2ReportSniffer.backendUrl` | Full URL to the FastAPI-served UI | `http://127.0.0.1:8000/ui/` |

Open **Settings**, search for **S2 Report Sniffer**, or edit `settings.json`:

```json
{
  "s2ReportSniffer.backendUrl": "http://127.0.0.1:8000/ui/"
}
```

## Commands

- **S2 Report Sniffer: Open UI** — Opens the configured URL in the built-in Simple Browser when available; otherwise opens your default external browser.
- **S2 Report Sniffer: Open UI in External Browser** — Always uses the system browser.

Both commands append short query parameters the web app reads once at startup (then removes them with `history.replaceState`):

| Parameter | Value | Purpose |
|-----------|--------|---------|
| `s2rs_host` | `vscode` | Enables VS Code–aligned surfaces in the React app (`data-s2rs-host` on `<html>`). |
| `s2rs_theme` | `light` \| `dark` \| `hcLight` \| `hcDark` | Mirrors `ColorThemeKind` so the UI can match the editor theme without a webview `postMessage` bridge. |

The extension also runs `vscode.env.asExternalUri` so loopback URLs resolve correctly under **Remote-SSH** / dev containers when VS Code rewrites ports.

> **Note:** A marketplace id `clusterlens.clusterlens` was not reachable from here (404), so this launcher does not copy that extension’s code. The patterns above (host flag + editor theme + `asExternalUri`) are the same family of techniques many in-editor web dashboards use when they are not implemented as a full custom webview extension.

## Install from a VSIX

1. Build the extension:

   ```bash
   cd vscode-extension
   npm install
   npm run compile
   npm run package
   ```

   (`npm run package` runs `vsce package --no-dependencies`. You can use `npx @vscode/vsce package` instead if you prefer.)

2. In VS Code: **Extensions** view → `...` menu → **Install from VSIX...** → choose the generated `.vsix` file.

Alternatively install `vsce` globally (`npm i -g @vscode/vsce`) and run `vsce package` instead of `npx @vscode/vsce package`.

## Development

```bash
npm install
npm run compile
```

Press **F5** in this folder to launch an **Extension Development Host** with the extension loaded.
