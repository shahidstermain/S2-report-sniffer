import { describe, expect, test } from "vitest";
import {
  buildSuggestedNextSteps,
  humanizeCheckerId,
  humanizeTraceType,
  normalizeFindingTitle,
} from "./nextSteps";

describe("nextSteps", () => {
  test("maps stable checker IDs to documentation-aligned labels", () => {
    expect(humanizeCheckerId("runawayQueries")).toBe("Long-Running Queries");
    expect(humanizeCheckerId("slowQueries")).toBe(
      "Queries Exceeding the Sniffer Elapsed-Time Threshold"
    );
  });

  test("maps stable trace types to user-facing terminology", () => {
    expect(humanizeTraceType("runaway")).toBe("Long-running");
    expect(humanizeTraceType("runaway_query")).toBe("Long-running query");
    expect(humanizeTraceType("slow")).toBe("Query exceeding the Sniffer threshold");
    expect(humanizeTraceType("lock_wait")).toBe("Lock wait");
  });

  test("normalizes legacy runaway wording", () => {
    expect(normalizeFindingTitle("Runaway queries detected (151)", "runawayQueries")).toBe(
      "Long-running queries detected (151)"
    );
  });

  test("buildSuggestedNextSteps ranks critical findings first", () => {
    const steps = buildSuggestedNextSteps([
      { checker_id: "slowQueries", severity: "warning", title: "Slow queries" },
      { checker_id: "tracelogOOM", severity: "critical", title: "OOM kills" },
    ]);
    expect(steps[0].findingId).toBe("tracelogOOM");
    expect(steps[0].priority).toBe(1);
    expect(steps[0].action.toLowerCase()).toContain("oom");
  });

  test("maps async transition findings to replication lag guidance", () => {
    const steps = buildSuggestedNextSteps([
      { checker_id: "asyncTransitionDetected", severity: "critical", title: "Async transition" },
    ]);
    expect(steps[0].findingType).toBe("replication_lag");
    expect(steps[0].action.toLowerCase()).toContain("synchronous-to-asynchronous");
  });
});
