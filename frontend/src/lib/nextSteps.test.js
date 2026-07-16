import { describe, expect, test } from "vitest";
import { buildSuggestedNextSteps, humanizeCheckerId } from "./nextSteps";

describe("nextSteps", () => {
  test("humanizeCheckerId splits camelCase", () => {
    expect(humanizeCheckerId("runawayQueries")).toBe("Runaway Queries");
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
    expect(steps[0].action.toLowerCase()).toContain("sync");
  });
});
