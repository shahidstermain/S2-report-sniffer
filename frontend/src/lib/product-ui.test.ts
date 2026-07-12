import { describe, expect, test } from "vitest";
import { firstAvailableTab, tabState } from "./product-ui";

describe("product UI capability routing", () => {
  test("routes sparse reports to the first available diagnostic tab", () => {
    const capabilities = {
      features: {
        overview: { available: false, reason: "Missing cluster overview" },
        nodes: { available: false, reason: "Missing node inventory" },
        logs: { available: true, reason: "Available" },
      },
    };
    expect(firstAvailableTab(["overview", "nodes", "logs"], capabilities)).toBe("logs");
    expect(tabState("overview", capabilities)).toEqual({ available: false, reason: "Missing cluster overview" });
  });

  test("keeps optional tabs enabled when capability metadata does not mention them", () => {
    expect(tabState("glean", { features: {} })).toEqual({ available: true, reason: "Available" });
  });
});
