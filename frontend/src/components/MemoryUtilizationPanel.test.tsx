import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MemoryUtilizationPanel from "./MemoryUtilizationPanel";

const mockPerNode = {
  "node-1": {
    engine_used_mb: 4000,
    engine_max_mb: 8000,
    engine_used_pct: 50,
    table_memory_mb: 2000,
    non_table_memory_mb: 2000,
    os_total_mb: 16000,
    os_used_mb: 8000,
    os_available_mb: 8000,
    os_used_pct: 50,
    swap_total_mb: 4096,
    swap_used_mb: 0,
    swap_used_pct: 0,
    status: "healthy" as const,
  },
  "node-2": {
    engine_used_mb: 7200,
    engine_max_mb: 8000,
    engine_used_pct: 90,
    table_memory_mb: 3000,
    non_table_memory_mb: 4200,
    os_total_mb: 16000,
    os_used_mb: 14000,
    os_available_mb: 2000,
    os_used_pct: 87.5,
    swap_total_mb: 4096,
    swap_used_mb: 512,
    swap_used_pct: 12.5,
    status: "critical" as const,
  },
};

const mockSummary = {
  total_engine_memory_mb: 16000,
  total_used_engine_mb: 11200,
  avg_engine_used_pct: 70,
  total_os_memory_mb: 32000,
  total_os_used_mb: 22000,
  nodes_over_80pct: 1,
  nodes_over_90pct: 1,
  highest_utilization_node: "node-2",
  highest_utilization_pct: 90,
};

describe("MemoryUtilizationPanel", () => {
  test("renders without crashing with valid data", () => {
    const { container } = render(
      <MemoryUtilizationPanel
        memoryUtilization={{ per_node: mockPerNode, cluster_summary: mockSummary }}
      />
    );
    expect(container.firstChild).not.toBeNull();
  });

  test("renders null when no per_node data", () => {
    const { container } = render(
      <MemoryUtilizationPanel memoryUtilization={{ per_node: {} }} />
    );
    expect(container.firstChild).toBeNull();
  });

  test("renders null when memoryUtilization is undefined", () => {
    const { container } = render(<MemoryUtilizationPanel />);
    expect(container.firstChild).toBeNull();
  });

  test("shows cluster summary values in the UI", () => {
    render(
      <MemoryUtilizationPanel
        memoryUtilization={{ per_node: mockPerNode, cluster_summary: mockSummary }}
      />
    );
    // The highest utilization node name should appear somewhere (possibly multiple times)
    expect(screen.getAllByText(/node-2/i).length).toBeGreaterThan(0);
  });
});