import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import CpuHealthPanel from "./CpuHealthPanel";

describe("CpuHealthPanel", () => {
  it("renders empty state when no per_node data", () => {
    render(<CpuHealthPanel cpuHealth={{ per_node: [] }} />);
    expect(screen.getByText(/No CPU diagnostic data/i)).toBeInTheDocument();
  });

  it("renders current CPU snapshot by default when available and allows toggling to lifetime", () => {
    const mockCpuHealth = {
      summary: {
        node_count: 2,
        outlier_count: 0,
        avg_util_pct: 12.5,
        current_avg_util_pct: 12.5,
        lifetime_avg_util_pct: 35.55,
        has_current: true,
        has_lifetime: true,
      },
      per_node: [
        {
          node_id: "1",
          hostname: "leaf-1",
          role: "LEAF",
          leaf_util_pct: 15.0,
          current_util_pct: 15.0,
          lifetime_util_pct: 35.5,
          softirq_pct: 0.5,
          iowait_pct: 0.1,
          health_zscore: 0.0,
          is_outlier: false,
        },
        {
          node_id: "2",
          hostname: "leaf-2",
          role: "LEAF",
          leaf_util_pct: 10.0,
          current_util_pct: 10.0,
          lifetime_util_pct: 35.6,
          softirq_pct: 0.4,
          iowait_pct: 0.2,
          health_zscore: 0.0,
          is_outlier: false,
        },
      ],
      insights: [
        "Showing current CPU utilization snapshot (top). Cluster average current load: 12.5%.",
        "Cluster lifetime average since boot: 35.55% (computed from MV_SYSINFO_CPULIST cumulative uptime counters).",
      ],
    };

    render(<CpuHealthPanel cpuHealth={mockCpuHealth} />);

    // Default badge is Current
    expect(screen.getByText("Current (top snapshot)")).toBeInTheDocument();
    expect(screen.getByText(/Avg current util:\s*12.5%/)).toBeInTheDocument();
    expect(screen.getByText(/Current CPU Utilization %/)).toBeInTheDocument();

    // Toggle to lifetime
    const lifetimeBtn = screen.getByTestId("toggle-lifetime-cpu");
    expect(lifetimeBtn).toBeInTheDocument();
    fireEvent.click(lifetimeBtn);

    expect(screen.getByText("Lifetime Avg (since boot)")).toBeInTheDocument();
    expect(screen.getByText(/Avg lifetime util:\s*35.55%/)).toBeInTheDocument();
    expect(screen.getByText(/Lifetime Avg CPU Utilization %/)).toBeInTheDocument();
  });

  it("renders lifetime mode when only lifetime data is present", () => {
    const mockCpuHealth = {
      summary: {
        node_count: 1,
        outlier_count: 0,
        avg_util_pct: 50.0,
        lifetime_avg_util_pct: 50.0,
        has_current: false,
        has_lifetime: true,
      },
      per_node: [
        {
          node_id: "1",
          leaf_util_pct: 50.0,
          lifetime_util_pct: 50.0,
          softirq_pct: 0.0,
          iowait_pct: 0.0,
          health_zscore: 0.0,
          is_outlier: false,
        },
      ],
    };

    render(<CpuHealthPanel cpuHealth={mockCpuHealth} />);
    expect(screen.getByText("Lifetime Avg (since boot)")).toBeInTheDocument();
    expect(screen.getByText(/Avg lifetime util:/)).toBeInTheDocument();
    expect(screen.queryByTestId("toggle-current-cpu")).not.toBeInTheDocument();
  });
});
