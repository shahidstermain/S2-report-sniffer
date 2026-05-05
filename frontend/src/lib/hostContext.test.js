import { describe, it, expect, afterEach, vi } from "vitest";
import { initHostContext, publicAsset, isVsCodeHost } from "./hostContext";

describe("hostContext", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("publicAsset resolves under Vite BASE_URL", () => {
    const out = publicAsset("singlestore-logo-white.svg");
    expect(out).toContain("singlestore-logo-white.svg");
    expect(out.startsWith("/")).toBe(true);
  });

  it("initHostContext sets vscode host and strips query", () => {
    const replaceState = vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
    delete window.location;
    window.location = new URL("http://localhost:3000/?s2rs_host=vscode&s2rs_theme=dark");

    initHostContext();

    expect(document.documentElement.getAttribute("data-s2rs-host")).toBe("vscode");
    expect(document.documentElement.getAttribute("data-s2rs-vscode-theme")).toBe("dark");
    expect(isVsCodeHost()).toBe(true);
    expect(replaceState).toHaveBeenCalled();
    replaceState.mockRestore();
  });

  it("initHostContext is no-op without vscode host param", () => {
    delete window.location;
    window.location = new URL("http://localhost:3000/");
    document.documentElement.removeAttribute("data-s2rs-host");

    initHostContext();

    expect(document.documentElement.getAttribute("data-s2rs-host")).toBeNull();
  });
});
