import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";
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
    expect(normalizeTerminology("Trace Log errors")).toBe("tracelog errors");
    expect(normalizeTerminology("Recommendations tab")).toBe("Issues tab");
    expect(normalizeTerminology("primary and secondary partitions")).toBe(
      "master and replica partitions"
    );
  });

  test("passes through non-string values", () => {
    expect(normalizeTerminology(null)).toBeNull();
    expect(normalizeTerminology(42)).toBe(42);
    expect(TERMINOLOGY_RULE_COUNT).toBeGreaterThan(10);
  });

  test("keeps legacy terminology out of frontend presentation source", () => {
    const sourceRoot = path.resolve(process.cwd(), "src");
    const excluded = new Set([
      path.resolve(sourceRoot, "lib/terminology.js"),
      path.resolve(sourceRoot, "lib/nextSteps.js"),
    ]);
    const forbidden = [
      /diagnostics? bundles?/i,
      /support bundles?/i,
      /report bundles?/i,
      /\bbundle\b/i,
      /runaway quer(?:y|ies)/i,
      /slow queries/i,
      /trace logs?/i,
      /process list/i,
      /primary partitions?/i,
      /secondary partitions?/i,
      /recommendations tab/i,
      /\blog explorer\b/i,
    ];
    const violations = [];

    const visit = (directory) => {
      for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const file = path.join(directory, entry.name);
        if (entry.isDirectory()) visit(file);
        else if (/\.(?:jsx?|tsx?)$/.test(entry.name) && !/\.(?:test|spec)\./.test(entry.name) && !excluded.has(file)) {
          const text = fs.readFileSync(file, "utf8");
          for (const pattern of forbidden) {
            if (pattern.test(text)) violations.push(`${path.relative(sourceRoot, file)}: ${pattern}`);
          }
        }
      }
    };

    visit(sourceRoot);
    expect(violations).toEqual([]);
  });
});
