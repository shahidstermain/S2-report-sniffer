import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import ReportDashboard from "./ReportDashboard";
import {
  exportReportHtml,
  exportReportMarkdown,
  getReportOverview,
  getReportStatus,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  exportReportHtml: vi.fn(),
  exportReportMarkdown: vi.fn(),
  getReportOverview: vi.fn(),
  getReportStatus: vi.fn(),
}));

vi.mock("@/components/ClusterOverview", () => ({ default: () => <div>Overview content</div> }));
vi.mock("@/components/NodeHealth", () => ({ default: () => <div>Nodes content</div> }));
vi.mock("@/components/StorageDistribution", () => ({ default: () => <div>Storage content</div> }));
vi.mock("@/components/WorkloadQueries", () => ({ default: () => <div>Queries content</div> }));
vi.mock("@/components/LogExplorer", () => ({ default: () => <div>Logs content</div> }));
vi.mock("@/components/LogSearch", () => ({ default: () => <div>Search content</div> }));
vi.mock("@/components/Recommendations", () => ({ default: () => <div>Issues content</div> }));
vi.mock("@/components/ConfigHealth", () => ({ default: () => <div>Config content</div> }));
vi.mock("@/components/InsightsPanel", () => ({ default: () => <div>Insights content</div> }));
vi.mock("@/components/ChartsDashboard", () => ({ default: () => <div>Charts content</div> }));
vi.mock("@/components/DiagnosticsDashboard", () => ({ default: () => <div>Diagnostics content</div> }));
vi.mock("@/components/DiskIntelligence", () => ({ default: () => <div>Disk content</div> }));

function renderDashboard(path) {
  const router = createMemoryRouter(
    [{ path: "/report/:reportId/*", element: <ReportDashboard /> }],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("ReportDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getReportStatus.mockResolvedValue({
      data: { status: "ready", detected_format: "zip" },
    });
    getReportOverview.mockResolvedValue({
      data: {
        report_name: "Anonymized Report",
        health_score: "healthy",
        privacy: { anonymized: true },
        cluster_overview: { total_nodes: 1, leaves: 1, aggregators: 0 },
        recommendations: [],
      },
    });
    exportReportMarkdown.mockResolvedValue({ data: new Blob(["markdown"]) });
    exportReportHtml.mockResolvedValue({ data: new Blob(["html"]) });
  });

  test("renders ready report export controls without crashing", async () => {
    renderDashboard("/report/report-1/overview");

    await waitFor(() => expect(getReportOverview).toHaveBeenCalledWith("report-1"));
    expect(screen.getByRole("button", { name: "Markdown" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "HTML" })).toBeInTheDocument();
  });

  test("exposes tour availability and one visible demo target", async () => {
    getReportOverview.mockResolvedValueOnce({
      data: {
        report_name: "Demo: Active Incident",
        status: "ready",
        is_demo: true,
        health_score: 70,
        privacy: { synthetic: true, anonymized: true },
        capabilities: {
          features: {
            overview: { available: true },
            "disk-intelligence": { available: false, reason: "No disk data" },
            recommendations: { available: true },
          },
        },
        cluster_overview: { total_nodes: 4, leaves: 3, aggregators: 1 },
        recommendations: [],
      },
    });

    renderDashboard("/report/demo/overview");

    await waitFor(() => expect(getReportOverview).toHaveBeenCalledWith("demo"));
    expect(screen.getByTestId("tab-disk-intelligence")).toHaveAttribute(
      "data-guide-available",
      "false",
    );
    expect(
      document.querySelectorAll('[data-guide-id="dashboard.demoBadge"]'),
    ).toHaveLength(1);
  });

  test("clears prior report overview when reportId changes", async () => {
    getReportOverview
      .mockResolvedValueOnce({
        data: {
          report_name: "Report Alpha",
          health_score: "healthy",
          privacy: { anonymized: true },
          cluster_overview: { total_nodes: 3, leaves: 2, aggregators: 1, version: "8.0" },
          recommendations: [],
        },
      })
      .mockResolvedValueOnce({
        data: {
          report_name: "Report Beta",
          health_score: "warning",
          privacy: { anonymized: true },
          cluster_overview: { total_nodes: 1, leaves: 1, aggregators: 0, version: "8.1" },
          recommendations: [],
        },
      });

    const router = renderDashboard("/report/report-1/overview");

    await waitFor(() => expect(screen.getByText("Report Alpha")).toBeInTheDocument());

    await router.navigate("/report/report-2/overview");

    // Prior overview must not remain painted under the new report URL.
    await waitFor(() => {
      expect(screen.queryByText("Report Alpha")).not.toBeInTheDocument();
    });
    await waitFor(() => expect(getReportOverview).toHaveBeenCalledWith("report-2"));
    await waitFor(() => expect(screen.getByText("Report Beta")).toBeInTheDocument());
  });
});
