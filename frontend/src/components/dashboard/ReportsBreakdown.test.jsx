import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import ReportsBreakdown from "./ReportsBreakdown";

describe("ReportsBreakdown", () => {
  it("uses total reports for processing and errored percentages", () => {
    render(
      <ReportsBreakdown
        status={{
          ready: 6,
          processing: 2,
          error: 1,
          healthy: 4,
          warning: 1,
          critical: 1,
          unknown: 0,
        }}
        deployments={[]}
        totalReady={6}
      />
    );

    const processingLabel = screen.getByText("Processing");
    const processingRow = processingLabel.parentElement;
    expect(processingRow).not.toBeNull();
    expect(within(processingRow).getByText("22%")).toBeInTheDocument();

    const erroredLabel = screen.getByText("Errored");
    const erroredRow = erroredLabel.parentElement;
    expect(erroredRow).not.toBeNull();
    expect(within(erroredRow).getByText("11%")).toBeInTheDocument();
  });
});
