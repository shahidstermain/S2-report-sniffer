import * as vscode from "vscode";
import { augmentUriForEmbeddedUi, resolveUiUri } from "./hostContext";

function getBackendUri(): vscode.Uri {
  const config = vscode.workspace.getConfiguration("s2ReportSniffer");
  const backendUrl = config.get<string>("backendUrl", "http://127.0.0.1:8000/ui/");
  return vscode.Uri.parse(backendUrl, true);
}

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("s2ReportSniffer.open", async () => {
      const raw = getBackendUri();
      const uri = await resolveUiUri(augmentUriForEmbeddedUi(raw));
      try {
        await vscode.commands.executeCommand("simpleBrowser.show", uri);
      } catch {
        await vscode.env.openExternal(uri);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("s2ReportSniffer.openExternal", async () => {
      const raw = getBackendUri();
      const uri = await resolveUiUri(augmentUriForEmbeddedUi(raw));
      await vscode.env.openExternal(uri);
    })
  );
}

export function deactivate(): void {}
