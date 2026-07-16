/**
 * Clipboard helpers — work in browser, Electron (IPC fallback), and legacy execCommand.
 */

export async function copyTextToClipboard(text) {
  const value = String(text ?? "");
  if (!value) {
    throw new Error("Nothing to copy");
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // Clipboard API may be blocked in sandboxed Electron or non-secure contexts.
  }

  if (typeof window !== "undefined" && window.s2rsDesktop?.clipboardWriteText) {
    await window.s2rsDesktop.clipboardWriteText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!ok) {
    throw new Error("Copy failed");
  }
}

export async function readTextFromClipboard() {
  try {
    if (navigator.clipboard?.readText) {
      return await navigator.clipboard.readText();
    }
  } catch {
    // Fall through to Electron IPC when available.
  }

  if (typeof window !== "undefined" && window.s2rsDesktop?.clipboardReadText) {
    return await window.s2rsDesktop.clipboardReadText();
  }

  throw new Error("Clipboard read unavailable");
}

/** @deprecated Use copyTextToClipboard */
export const writeClipboardText = copyTextToClipboard;
