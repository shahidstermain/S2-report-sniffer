import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTheme } from "./useTheme";

describe("useTheme", () => {
  let dark = false;
  let listener: (() => void) | undefined;
  let values: Map<string, string>;

  beforeEach(() => {
    values = new Map();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        clear: () => values.clear(),
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    });
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => ({
        get matches() { return dark; },
        addEventListener: (_event: string, callback: () => void) => { listener = callback; },
        removeEventListener: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    listener = undefined;
  });

  it("follows system preference and persists an explicit theme cycle", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("system");
    expect(document.documentElement).not.toHaveClass("dark");

    dark = true;
    act(() => listener?.());
    expect(document.documentElement).toHaveClass("dark");

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("light");
    expect(window.localStorage.getItem("s2rs.theme")).toBe("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });
});
