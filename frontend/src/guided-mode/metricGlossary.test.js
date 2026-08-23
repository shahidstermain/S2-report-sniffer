import { describe, expect, it } from "vitest";
import { glossaryForPage, getMetricById } from "./metricGlossary";
import { availableTourSteps, pageKeyFromPath, tourForPath } from "./tourRegistry";

describe("guided mode glossary", () => {
  it("returns focused glossary entries for page contexts", () => {
    expect(getMetricById("cluster.health")?.basis).toBe("Sniffer heuristic");
    expect(glossaryForPage("queries").some((item) => item.id === "queries.long_running")).toBe(true);
    expect(glossaryForPage("log-search").every((item) => item.id.includes("logs"))).toBe(true);
    expect(glossaryForPage("disk-intelligence").map((item) => item.id)).toEqual(
      expect.arrayContaining([
        "overview.disk",
        "disk.mount_usage",
        "disk.non_table_overhead",
        "disk.reclaimable",
        "disk.table_storage",
      ]),
    );
  });

  it("selects tours and page keys from routes", () => {
    expect(pageKeyFromPath("/report/111/queries")).toBe("queries");
    expect(pageKeyFromPath("/")).toBe("reports");
    expect(tourForPath("/").some((step) => step.target === "demo.launch")).toBe(true);
    expect(tourForPath("/report/111/overview").some((step) => step.tabId === "log-search")).toBe(true);
  });

  it("removes tour steps for unavailable report tabs", () => {
    const steps = availableTourSteps(
      tourForPath("/report/111/overview"),
      (tabId) => tabId !== "disk-intelligence",
    );

    expect(steps.some((step) => step.tabId === "disk-intelligence")).toBe(false);
    expect(steps.some((step) => step.tabId === "queries")).toBe(true);
  });
});
