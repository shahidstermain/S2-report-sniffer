import { describe, expect, test } from "vitest";

import { buildLogSeverityChartData } from "./LogSeverityChart";

describe("buildLogSeverityChartData", () => {
  test("reads nested severity_counts from the overview log summary", () => {
    const data = buildLogSeverityChartData({
      total: 17,
      severity_counts: {
        ERROR: 2,
        WARN: 5,
        INFO: 10,
      },
    });

    expect(data).toEqual([
      { name: "Error", value: 2, total: 17 },
      { name: "Warn", value: 5, total: 17 },
      { name: "Info", value: 10, total: 17 },
    ]);
  });
});
