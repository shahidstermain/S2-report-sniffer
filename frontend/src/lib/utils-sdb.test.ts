import { describe, expect, it } from "vitest";
import {
  formatUptime,
  getHealthBucket,
  getHealthGrade,
  getHealthScore,
} from "./utils-sdb";

describe("utils-sdb health helpers", () => {
  it("derives grade from numeric score when present (ignores stale stored grade)", () => {
    expect(getHealthGrade({ health_score: 95, health_grade: "B" })).toBe("A");
    expect(getHealthGrade({ health_score: 95 })).toBe("A");
    expect(getHealthGrade({ health_score: 74, health_grade: "A" })).toBe("C");
  });

  it("keeps explicit health_grade only when score is missing", () => {
    expect(getHealthGrade({ health_grade: "c" })).toBe("C");
    expect(getHealthGrade({ health_score: "not-a-number", health_grade: "D" })).toBe("D");
    expect(getHealthGrade({})).toBeNull();
  });

  it("classifies bucket from score-derived grade, with legacy string path", () => {
    expect(getHealthBucket({ health_score: "healthy" })).toBe("healthy");
    expect(getHealthBucket({ health_score: "warning" })).toBe("warning");
    expect(getHealthBucket({ health_score: "critical" })).toBe("critical");
    expect(getHealthBucket({ health_grade: "A" })).toBe("healthy");
    expect(getHealthBucket({ health_grade: "D" })).toBe("warning");
    expect(getHealthBucket({ health_grade: "F" })).toBe("critical");
    expect(getHealthBucket({ health_score: 95 })).toBe("healthy");
    expect(getHealthBucket({ health_score: 74 })).toBe("warning");
    expect(getHealthBucket({ health_score: 50 })).toBe("critical");
  });

  it("normalizes numeric health scores", () => {
    expect(getHealthScore(74.6)).toBe(75);
    expect(getHealthScore("not-a-number")).toBeNull();
  });
});

describe("formatUptime", () => {
  it("treats only null/undefined/NaN as missing, not zero", () => {
    expect(formatUptime(0)).toBe("0h 0m");
    expect(formatUptime(null)).toBe("—");
    expect(formatUptime(undefined)).toBe("—");
    expect(formatUptime(Number.NaN)).toBe("—");
    expect(formatUptime(3661)).toBe("1h 1m");
  });
});
