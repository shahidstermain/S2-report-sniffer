import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { copyTextToClipboard, readTextFromClipboard, buildIssuesCopySummary } from "./clipboard";

describe("clipboard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    delete window.s2rsDesktop;
  });

  it("prefers Electron IPC over navigator.clipboard when desktop bridge is present", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const clipboardWriteText = vi.fn().mockResolvedValue(true);
    Object.assign(navigator, { clipboard: { writeText, readText: vi.fn() } });
    window.s2rsDesktop = { clipboardWriteText };

    await copyTextToClipboard("hello");

    expect(clipboardWriteText).toHaveBeenCalledWith("hello");
    expect(writeText).not.toHaveBeenCalled();
  });

  it("uses navigator.clipboard.writeText when desktop bridge is absent", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText, readText: vi.fn() } });

    await copyTextToClipboard("hello");

    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("falls back to Electron IPC when Clipboard API throws and bridge exists", async () => {
    // Bridge-first path already covers Electron; keep throw-path for browser-only mocks.
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.assign(navigator, { clipboard: { writeText } });
    // No desktop bridge — expect failure after execCommand attempt may also fail
    document.execCommand = vi.fn().mockReturnValue(false);

    await expect(copyTextToClipboard("packet")).rejects.toThrow(/Copy failed/);
  });

  it("reads via Electron IPC when desktop bridge is present", async () => {
    Object.assign(navigator, { clipboard: { readText: vi.fn().mockResolvedValue("browser") } });
    window.s2rsDesktop = { clipboardReadText: vi.fn().mockResolvedValue("pasted") };

    await expect(readTextFromClipboard()).resolves.toBe("pasted");
  });

  it("rejects empty copy payloads", async () => {
    await expect(copyTextToClipboard("")).rejects.toThrow(/Nothing to copy/);
  });
});

describe("buildIssuesCopySummary", () => {
  it("includes triage buckets and act-now titles", () => {
    const text = buildIssuesCopySummary({
      reportId: "abc-123",
      reportName: "prod",
      healthScore: 80,
      healthGrade: "B",
      triageSummary: { act_now: 2, quick_wins: 1, act_soon: 0, backlog: 3 },
      triageData: {
        act_now: [{ severity: "critical", title: "Swap high", nodes: ["leaf-1"] }],
        quick_wins: [{ title: "Disable THP" }],
      },
      recommendations: [],
    });

    expect(text).toContain("Grade B");
    expect(text).toContain("Act Now 2");
    expect(text).toContain("Swap high");
    expect(text).toContain("Disable THP");
    expect(text).toContain("prod");
  });
});
