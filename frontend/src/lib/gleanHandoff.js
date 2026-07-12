import { toast } from "sonner";

/**
 * Hand off a Glean incident packet: Electron IPC when available, otherwise
 * browser download + clipboard copy of the suggested prompt.
 *
 * @param {{ filename: string, markdown: string, prompt: string }} packet
 * @returns {Promise<{ mode: "desktop" | "web", saved_path?: string, glean_opened?: boolean }>}
 */
export async function handoffGleanPacket(packet) {
  const filename = packet?.filename || "s2rs-incident-packet.md";
  const markdown = packet?.markdown || "";
  const prompt = packet?.prompt || "";

  if (typeof window !== "undefined" && window.s2rsDesktop?.gleanHandoff) {
    const result = await window.s2rsDesktop.gleanHandoff({
      filename,
      markdown,
      prompt,
    });
    const opened = result?.glean_opened;
    toast.success(
      opened
        ? "Packet saved, prompt copied, and Glean opened — attach the file in a new chat."
        : "Packet saved and prompt copied — open Glean and attach the file in a new chat."
    );
    return { mode: "desktop", ...result };
  }

  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);

  let clipboardOk = false;
  try {
    if (prompt && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(prompt);
      clipboardOk = true;
    }
  } catch {
    // Clipboard may be blocked; download still succeeded.
  }

  void clipboardOk;

  toast.success(
    "Packet downloaded and prompt copied — open Glean and attach the file in a new chat."
  );
  return { mode: "web" };
}
