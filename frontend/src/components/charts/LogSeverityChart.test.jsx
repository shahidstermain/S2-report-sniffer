import React from "react";
import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import LogSeverityChart from "./LogSeverityChart";

describe("LogSeverityChart", () => {
  test("renders nested severity_counts from overview log_summary", () => {
    render(
      <LogSeverityChart
        logSummary={{
          total: 3,
          severity_counts: {
            ERROR: 2,
            WARN: 1,
          },
        }}
      />
    );

    expect(screen.queryByText("No log severity data available.")).not.toBeInTheDocument();
    expect(screen.getByText("ERROR 66.7%")).toBeInTheDocument();
    expect(screen.getByText("WARN 33.3%")).toBeInTheDocument();
  });
});
