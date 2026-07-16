import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { handoffGleanPacket } from "./gleanHandoff";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("handoffGleanPacket", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    delete window.s2rsDesktop;
  });

  afterEach(() => {
    delete window.s2rsDesktop;
  });

  it("uses Electron bridge when available", async () => {
    window.s2rsDesktop = {
      gleanHandoff: vi.fn().mockResolvedValue({ saved_path: "/tmp/x.md", glean_opened: true }),
    };
    const result = await handoffGleanPacket({
      filename: "packet.md",
      markdown: "# hi",
      prompt: "analyze",
    });
    expect(window.s2rsDesktop.gleanHandoff).toHaveBeenCalled();
    expect(result.mode).toBe("desktop");
    expect(result.glean_opened).toBe(true);
  });

  it("downloads a blob and copies the prompt in the browser", async () => {
    const { toast } = await import("sonner");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const click = vi.fn();
    const createElement = vi.spyOn(document, "createElement").mockReturnValue({
      href: "",
      download: "",
      click,
    });
    const createObjectURL = vi.fn().mockReturnValue("blob:mock");
    const revokeObjectURL = vi.fn();
    global.URL.createObjectURL = createObjectURL;
    global.URL.revokeObjectURL = revokeObjectURL;

    const result = await handoffGleanPacket({
      filename: "packet.md",
      markdown: "# hi",
      prompt: "analyze this",
    });

    expect(result.mode).toBe("web");
    expect(result.clipboard_ok).toBe(true);
    expect(click).toHaveBeenCalled();
    expect(writeText).toHaveBeenCalledWith("analyze this");
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("prompt copied")
    );
    createElement.mockRestore();
  });

  it("still downloads when clipboard copy fails", async () => {
    const { toast } = await import("sonner");
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    document.execCommand = vi.fn().mockReturnValue(false);
    const click = vi.fn();
    vi.spyOn(document, "createElement").mockReturnValue({
      href: "",
      download: "",
      click,
    });
    global.URL.createObjectURL = vi.fn().mockReturnValue("blob:mock");
    global.URL.revokeObjectURL = vi.fn();

    const result = await handoffGleanPacket({
      filename: "packet.md",
      markdown: "# hi",
      prompt: "analyze this",
    });

    expect(result.mode).toBe("web");
    expect(result.clipboard_ok).toBe(false);
    const msg = toast.success.mock.calls.at(-1)?.[0] || "";
    expect(msg).toContain("Packet downloaded");
    expect(msg).not.toContain("prompt copied");
  });
});
