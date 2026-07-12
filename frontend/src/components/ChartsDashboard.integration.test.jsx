import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ChartsDashboard from "./ChartsDashboard";
import * as api from "@/lib/api";

describe("ChartsDashboard integration", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crash when overview fields use rows wrappers", async () => {
    vi.spyOn(api, "getReportOverview").mockResolvedValue({
      data: {
        report_name: "test-report",
        backup_history: { rows: [{ STATUS: "Success", START_TIMESTAMP: "2024-01-01 10:00:00", END_TIMESTAMP: "2024-01-01 10:01:00" }] },
        database_disk_usage: { rows: [{ Database: "db1", _disk_bytes: 1024 }] },
        cluster_overview: { nodes_detail: { rows: [{ state: "online" }] } },
        log_summary: { severity_counts: { INFO: 10, WARN: 2 } },
        pressure_events_per_hour: { etimedout: { "2024-01-01 09:00:00": 1 } },
        memory_utilization: { per_node: { "host-1": { os_used_pct: 50, hostname: "host-1" } } },
      },
    });

    render(
      <MemoryRouter initialEntries={["/report/test-id/charts"]}>
        <Routes>
          <Route path="/report/:reportId/charts" element={<ChartsDashboard />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Cluster Diagnostics/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Something went wrong/)).not.toBeInTheDocument();
  });
});
