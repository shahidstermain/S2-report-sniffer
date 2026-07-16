import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { copyTextToClipboard, readTextFromClipboard } from "./clipboard";

describe("clipboard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    delete window.s2rsDesktop;
  });

  it("uses navigator.clipboard.writeText when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText, readText: vi.fn() } });

    await copyTextToClipboard("hello");

    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("falls back to Electron IPC when Clipboard API throws", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const clipboardWriteText = vi.fn().mockResolvedValue(true);
    Object.assign(navigator, { clipboard: { writeText } });
    window.s2rsDesktop = { clipboardWriteText };

    await copyTextToClipboard("packet");

    expect(clipboardWriteText).toHaveBeenCalledWith("packet");
  });

  it("reads via Electron IPC when navigator.clipboard.readText is unavailable", async () => {
    Object.assign(navigator, { clipboard: {} });
    window.s2rsDesktop = { clipboardReadText: vi.fn().mockResolvedValue("pasted") };

    await expect(readTextFromClipboard()).resolves.toBe("pasted");
  });

  it("rejects empty copy payloads", async () => {
    await expect(copyTextToClipboard("")).rejects.toThrow(/Nothing to copy/);
  });
});
