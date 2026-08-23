import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import ChartsDashboard from "./ChartsDashboard";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getReportOverview: vi.fn(),
}));

function renderCharts(path) {
  const router = createMemoryRouter(
    [{ path: "/report/:reportId/*", element: <ChartsDashboard /> }],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("ChartsDashboard reportId transitions", () => {
  beforeEach(() => {
    vi.mocked(api.getReportOverview).mockReset();
  });

  it("clears prior report charts while loading a different reportId", async () => {
    let resolveSecond;
    vi.mocked(api.getReportOverview)
      .mockResolvedValueOnce({
        data: {
          report_name: "Report Alpha",
          backup_history: [],
          backup_summary: {},
          log_summary: {},
          pressure_events_per_hour: {},
          memory_utilization: {},
          cluster_overview: { nodes_detail: [{ state: "online" }] },
          database_disk_usage: [],
        },
      })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveSecond = resolve;
        }),
      );

    const router = renderCharts("/report/a0000000-0000-0000-0000-00000000000a/charts");

    await waitFor(() => {
      expect(screen.getByText(/Metrics from Report Alpha/)).toBeInTheDocument();
    });

    await router.navigate("/report/b0000000-0000-0000-0000-00000000000b/charts");

    await waitFor(() => {
      expect(screen.queryByText(/Metrics from Report Alpha/)).not.toBeInTheDocument();
      expect(screen.getByText(/Loading charts/)).toBeInTheDocument();
    });

    resolveSecond({
      data: {
        report_name: "Report Beta",
        backup_history: [],
        backup_summary: {},
        log_summary: {},
        pressure_events_per_hour: {},
        memory_utilization: {},
        cluster_overview: { nodes_detail: [{ state: "online" }] },
        database_disk_usage: [],
      },
    });

    await waitFor(() => {
      expect(screen.getByText(/Metrics from Report Beta/)).toBeInTheDocument();
    });
  });
});
