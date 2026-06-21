import { afterEach, describe, expect, test, vi } from "vitest";

describe("API base URL resolution", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
    window.history.replaceState(null, "", "/");
  });

  test("uses same-origin API for integrated /ui paths even when VITE_BACKEND_URL is set", async () => {
    vi.stubEnv("VITE_BACKEND_URL", "http://backend.example.test");
    window.history.replaceState(null, "", "/ui/report/123");

    const { resolveApiBase } = await import("./api");

    expect(resolveApiBase()).toBe("/api");
  });

  test("uses VITE_BACKEND_URL outside integrated /ui paths", async () => {
    vi.stubEnv("VITE_BACKEND_URL", "http://backend.example.test");
    window.history.replaceState(null, "", "/report/123");

    const { resolveApiBase } = await import("./api");

    expect(resolveApiBase()).toBe("http://backend.example.test/api");
  });
});
