import React from "react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import ReportList from "./ReportList";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const listReports = vi.fn().mockResolvedValue({ data: [] });

vi.mock("@/lib/api", () => ({
  listReports: (...args) => listReports(...args),
  uploadReport: vi.fn(),
  importReport: vi.fn(),
  deleteReport: vi.fn(),
}));
vi.mock("@/lib/utils-sdb", () => ({
  healthColor: vi.fn().mockReturnValue("green"),
  getHealthBucket: (r) => {
    const g = String(r?.health_grade || "").toUpperCase();
    if (g === "A" || g === "B") return "healthy";
    if (g === "C" || g === "D") return "warning";
    if (g === "F") return "critical";
    return "unknown";
  },
  getHealthScore: (v) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return null;
    return Math.max(0, Math.min(100, Math.round(n)));
  },
  getHealthGrade: (r) => String(r?.health_grade || "").toUpperCase() || null,
}));
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    ResponsiveContainer: ({ children }) => <div>{children}</div>,
  };
});

describe('ReportList Component', () => {
  beforeEach(() => {
    listReports.mockReset();
    listReports.mockResolvedValue({ data: [] });
  });

  test("renders backend-owned grade/score and clears fake missing file sizes", async () => {
    listReports.mockResolvedValueOnce({
      data: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          report_name: "prod-a",
          status: "ready",
          health_score: 72,
          health_grade: "C",
          uploaded_at: "2026-07-14T08:00:00Z",
          detected_format: "tar.gz",
          file_size: null,
          diagnostics_ready: true,
        },
      ],
    });

    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );

    const row = await screen.findByTestId("report-row-11111111-1111-1111-1111-111111111111");
    expect(within(row).getAllByText("C · 72").length).toBeGreaterThan(0);
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });

  test('renders header and main sections', async () => {
    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );
    expect(screen.getByTestId('app-logo')).toHaveClass('w-[120px]', 'sm:w-[150px]', 'shrink-0');
    expect(screen.getByTestId('app-title')).toHaveClass('hidden', 'sm:inline');
    expect(screen.getAllByText('Report Sniffer').length).toBeGreaterThan(0);
    // Use findByText because listReports is async
    expect(await screen.findByText('No reports uploaded yet')).toBeInTheDocument();
  });

  test('file input accepts all supported archive types', async () => {
    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );

    const input = screen.getByTestId('file-input');
    expect(input).toHaveAttribute(
      'accept',
      '.zip,.tar,.tar.gz,.tgz,.gz,application/zip,application/x-tar,application/gzip,application/x-gzip,application/octet-stream'
    );
    await waitFor(() => expect(screen.getByText('No reports uploaded yet')).toBeInTheDocument());
  });

  test("last 24h KPI applies a real time-window filter", async () => {
    listReports.mockResolvedValueOnce({
      data: [
        {
          id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
          report_name: "recent",
          status: "ready",
          health_score: 90,
          health_grade: "A",
          uploaded_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
          detected_format: "zip",
          file_size: 1024,
          diagnostics_ready: true,
        },
        {
          id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
          report_name: "older",
          status: "ready",
          health_score: 55,
          health_grade: "F",
          uploaded_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
          detected_format: "zip",
          file_size: 1024,
          diagnostics_ready: true,
        },
      ],
    });

    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );

    await screen.findByTestId("report-row-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
    fireEvent.click(screen.getByTestId("kpi-last24h"));

    expect(screen.getByTestId("report-row-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")).toBeInTheDocument();
    expect(screen.queryByTestId("report-row-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")).not.toBeInTheDocument();
  });
});
