import { describe, expect, it } from "vitest";
import { glossaryForPage, getMetricById } from "./metricGlossary";
import { pageKeyFromPath, tourForPath } from "./tourRegistry";

describe("guided mode glossary", () => {
  it("returns focused glossary entries for page contexts", () => {
    expect(getMetricById("cluster.health")?.basis).toBe("Sniffer heuristic");
    expect(glossaryForPage("queries").some((item) => item.id === "queries.long_running")).toBe(true);
    expect(glossaryForPage("log-search").every((item) => item.id.includes("logs"))).toBe(true);
  });

  it("selects tours and page keys from routes", () => {
    expect(pageKeyFromPath("/report/111/queries")).toBe("queries");
    expect(pageKeyFromPath("/")).toBe("reports");
    expect(tourForPath("/").some((step) => step.target === "demo.launch")).toBe(true);
    expect(tourForPath("/report/111/overview").some((step) => step.tabId === "log-search")).toBe(true);
  });
});
