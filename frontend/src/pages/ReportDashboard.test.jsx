import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

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
    render(
      <MemoryRouter initialEntries={["/report/report-1/overview"]}>
        <Routes>
          <Route path="/report/:reportId/*" element={<ReportDashboard />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(getReportOverview).toHaveBeenCalledWith("report-1"));
    expect(screen.getByRole("button", { name: "Markdown" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "HTML" })).toBeInTheDocument();
  });
});
