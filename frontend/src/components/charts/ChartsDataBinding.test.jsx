import React from "react";
import { describe, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import LogSeverityChart from "./LogSeverityChart";
import DatabaseDiskChart from "./DatabaseDiskChart";

vi.mock("recharts", () => ({
  Bar: ({ children }) => <div>{children}</div>,
  BarChart: ({ children }) => <div>{children}</div>,
  CartesianGrid: () => null,
  Cell: () => null,
  Legend: () => null,
  Pie: ({ children }) => <div>{children}</div>,
  PieChart: ({ children }) => <div>{children}</div>,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

describe("chart data bindings", () => {
  test("LogSeverityChart reads nested API severity_counts", () => {
    render(
      <LogSeverityChart
        logSummary={{
          total: 8,
          severity_counts: {
            ERROR: 2,
            WARN: 1,
            INFO: 5,
          },
        }}
      />
    );

    expect(screen.queryByText("No log severity data available.")).not.toBeInTheDocument();
    expect(screen.getByText("ERROR 25.0%")).toBeInTheDocument();
    expect(screen.getByText("WARN 12.5%")).toBeInTheDocument();
    expect(screen.getByText("8 total")).toBeInTheDocument();
  });

  test("DatabaseDiskChart reads uppercase API disk usage fields", () => {
    render(
      <DatabaseDiskChart
        databaseDiskUsage={[
          { DATABASE_NAME: "app", TOTAL_DISK_USAGE_GB: "1.5" },
          { DATABASE_NAME: "logs", TOTAL_DISK_USAGE_GB: "0.5" },
        ]}
      />
    );

    expect(screen.queryByText("No database disk usage data available.")).not.toBeInTheDocument();
    expect(screen.getByText("Database Disk Usage")).toBeInTheDocument();
    expect(screen.getByText("2.0 GB")).toBeInTheDocument();
  });
});
