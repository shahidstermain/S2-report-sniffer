import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DatabaseDiskChart, { buildDatabaseDiskChartData } from "./DatabaseDiskChart";

describe("DatabaseDiskChart edge cases", () => {
  it("shows empty state when there is no usage data", () => {
    render(<DatabaseDiskChart databaseDiskUsage={[]} />);
    expect(screen.getByText(/No database storage data available/)).toBeInTheDocument();
  });

  it("filters out zero/missing byte rows (empty when none have size)", () => {
    render(
      <DatabaseDiskChart
        databaseDiskUsage={[{ Database: "db1" }, { Database: "db2", _disk_bytes: 0 }]}
      />
    );
    expect(screen.getByText(/No database storage data available/)).toBeInTheDocument();
  });

  it("sums byte totals across alternate field names and missing names", () => {
    render(
      <DatabaseDiskChart
        databaseDiskUsage={[
          { Database: "orders", _disk_bytes: 2 * 1024 * 1024 * 1024 }, // 2 GB
          { DataSize: 1024 * 1024 * 1024 }, // 1 GB, missing name -> "unknown"
        ]}
      />
    );
    // Total 3.0 GB rendered in the header.
    expect(screen.getByText(/Total:/)).toBeInTheDocument();
    expect(screen.getByText(/3\.0 GB/)).toBeInTheDocument();
  });

  it("reads DATABASE_NAME and TOTAL_DISK_USAGE_GB with percentages based on all rows", () => {
    const usageRows = Array.from({ length: 16 }, (_, index) => ({
      DATABASE_NAME: `db-${index + 1}`,
      TOTAL_DISK_USAGE_GB: index === 15 ? "0.9" : "1.0",
    }));

    const { chartData, totalBytes } = buildDatabaseDiskChartData(usageRows);

    expect(chartData).toHaveLength(15);
    expect(chartData[0].Database).toBe("db-1");
    expect(chartData[0]._pct).toBeCloseTo(100 / 15.9, 3);
    expect(totalBytes).toBeCloseTo(15.9 * 1024 ** 3, 3);
  });

  it("handles undefined prop", () => {
    render(<DatabaseDiskChart databaseDiskUsage={undefined} />);
    expect(screen.getByText(/No database storage data available/)).toBeInTheDocument();
  });

  it("unwraps legacy { rows: [...] } wrapper without crashing", () => {
    render(
      <DatabaseDiskChart
        databaseDiskUsage={{
          rows: [{ Database: "orders", _disk_bytes: 1024 * 1024 * 1024 }],
        }}
      />
    );
    expect(screen.getByText(/1\.0 GB/)).toBeInTheDocument();
  });
});
