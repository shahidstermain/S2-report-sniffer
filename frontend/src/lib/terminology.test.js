import { describe, expect, test } from "vitest";
import { normalizeTerminology, TERMINOLOGY_RULE_COUNT } from "./terminology";

describe("normalizeTerminology", () => {
  test("normalizes Cluster Report terminology", () => {
    expect(normalizeTerminology("Upload a SingleStore diagnostic bundle")).toBe(
      "Upload a SingleStore Cluster Report"
    );
    expect(normalizeTerminology("Compare diagnostic snapshots")).toBe(
      "Compare Cluster Reports"
    );
    expect(normalizeTerminology("No support bundles found")).toBe(
      "No Cluster Reports found"
    );
  });

  test("normalizes query terminology without changing stable identifiers", () => {
    expect(normalizeTerminology("Runaway Queries detected")).toBe(
      "Long-Running Queries detected"
    );
    expect(normalizeTerminology("Slow Queries")).toBe(
      "Queries Above the Sniffer Elapsed-Time Threshold"
    );
    expect(normalizeTerminology("runawayQueries")).toBe("runawayQueries");
    expect(normalizeTerminology("runaway_queries")).toBe("runaway_queries");
  });

  test("normalizes health and processlist labels idempotently", () => {
    expect(normalizeTerminology("Health Score")).toBe("Cluster Health Score");
    expect(normalizeTerminology("Cluster Health Score")).toBe("Cluster Health Score");
    expect(normalizeTerminology("Process List")).toBe("Processlist");
  });

  test("passes through non-string values", () => {
    expect(normalizeTerminology(null)).toBeNull();
    expect(normalizeTerminology(42)).toBe(42);
    expect(TERMINOLOGY_RULE_COUNT).toBeGreaterThan(10);
  });
});
