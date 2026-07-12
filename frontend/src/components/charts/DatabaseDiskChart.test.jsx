import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DatabaseDiskChart from "./DatabaseDiskChart";

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

  it("handles undefined prop", () => {
    render(<DatabaseDiskChart databaseDiskUsage={undefined} />);
    expect(screen.getByText(/No database storage data available/)).toBeInTheDocument();
  });
});
