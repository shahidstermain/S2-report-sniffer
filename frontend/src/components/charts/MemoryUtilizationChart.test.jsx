import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MemoryUtilizationChart, { normalizeMemoryChartRows } from "./MemoryUtilizationChart";

describe("MemoryUtilizationChart edge cases", () => {
  it("shows empty state when per_node is missing", () => {
    render(<MemoryUtilizationChart memoryUtilization={{}} />);
    expect(screen.getByText(/No per-node memory metrics available/)).toBeInTheDocument();
  });

  it("renders without crashing when node rows are missing pct fields", () => {
    render(
      <MemoryUtilizationChart
        memoryUtilization={{
          cluster_avg_used_pct: 0,
          per_node: [{ hostname: "leaf-1:3306" }, { hostname: "leaf-2:3306" }],
        }}
      />
    );
    // Heading still renders; no NaN thrown from missing os_used_pct/memsqld_pct_of_max.
    expect(screen.getByText(/Memory Utilization by Node/)).toBeInTheDocument();
  });

  it("handles per_node object map from backend", () => {
    render(
      <MemoryUtilizationChart
        memoryUtilization={{
          per_node: {
            "leaf-1:3306": {
              engine_used_pct: 42,
              os_used_pct: 55,
              status: "healthy",
            },
            "leaf-2:3306": {
              engine_used_pct: 88,
              os_used_pct: 72,
              status: "warning",
            },
          },
          cluster_summary: {
            avg_engine_used_pct: 65,
            nodes_over_80pct: 1,
            nodes_over_90pct: 0,
          },
        }}
      />
    );
    expect(screen.getByText(/Memory Utilization by Node/)).toBeInTheDocument();
    expect(screen.getByText(/avg/)).toBeInTheDocument();
    expect(screen.getByText(/65%/)).toBeInTheDocument();
  });

  it("keeps OS and engine percentages as separate series", () => {
    const rows = normalizeMemoryChartRows({
      per_node: {
        "leaf-1:3306": {
          engine_used_pct: 42,
          os_used_pct: 55,
        },
      },
    });

    expect(rows).toEqual([
      expect.objectContaining({
        hostname: "leaf-1:3306",
        os_used_pct: 55,
        engine_used_pct: 42,
      }),
    ]);
  });

  it("handles undefined memoryUtilization prop", () => {
    render(<MemoryUtilizationChart memoryUtilization={undefined} />);
    expect(screen.getByText(/No per-node memory metrics available/)).toBeInTheDocument();
  });
});
