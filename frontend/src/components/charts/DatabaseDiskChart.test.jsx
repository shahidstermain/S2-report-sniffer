import { describe, expect, test } from "vitest";

import { buildDatabaseDiskChartData } from "./DatabaseDiskChart";

describe("buildDatabaseDiskChartData", () => {
  test("reads database disk rows from the overview storage contract", () => {
    const data = buildDatabaseDiskChartData([
      {
        DATABASE_NAME: "orders",
        TOTAL_DISK_USAGE_GB: "12.5",
        PARTITION_COUNT: "32",
      },
    ]);

    expect(data).toEqual([
      {
        name: "orders",
        Database: "orders",
        _bytes: 12.5 * 1024 * 1024 * 1024,
        Partitions: "32",
      },
    ]);
  });
});
