import { describe, expect, it } from "vitest";
import { loadGuidedPreference, saveGuidedPreference } from "./guidedModeStorage";


describe("guided mode storage", () => {
  it("degrades when accessing localStorage throws", () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("Storage blocked", "SecurityError");
      },
    });

    try {
      expect(loadGuidedPreference("explainPage", false)).toBe(false);
      expect(() => saveGuidedPreference("explainPage", true)).not.toThrow();
    } finally {
      if (original) {
        Object.defineProperty(window, "localStorage", original);
      } else {
        delete window.localStorage;
      }
    }
  });
});
