import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LogExplorer from "./LogExplorer";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getReportLogs: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    message: vi.fn(),
  },
}));

const REPORT_ID = "d0000000-0000-0000-0000-000000000001";

function mockLogsPage(page, totalPages = 50) {
  vi.mocked(api.getReportLogs).mockImplementation(async (_id, params) => ({
    data: {
      logs: [
        {
          timestamp: "2024-01-01 00:00:00",
          severity: "INFO",
          hostname: "node-a",
          role: "LEAF",
          message: `page ${params.page} entry`,
        },
      ],
      total: totalPages * 100,
      page: params.page,
      total_pages: totalPages,
      log_summary: { per_node: { "node-a": {} }, severity_counts: {} },
    },
  }));
}

describe("LogExplorer pagination", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLogsPage(1);
  });

  it("renders go-to page controls when logs are paginated", async () => {
    render(<LogExplorer reportId={REPORT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId("log-go-to-page-input")).toBeInTheDocument();
    });
    expect(screen.getByTestId("log-first-page")).toBeInTheDocument();
    expect(screen.getByTestId("log-last-page")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 50 (5000 total)")).toBeInTheDocument();
  });

  it("jumps to a specific page via go-to input", async () => {
    const user = userEvent.setup();
    render(<LogExplorer reportId={REPORT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId("log-go-to-page-input")).toHaveValue(1);
    });

    const input = screen.getByTestId("log-go-to-page-input");
    await user.clear(input);
    await user.type(input, "37");
    await user.click(screen.getByTestId("log-go-to-page-button"));

    await waitFor(() => {
      expect(api.getReportLogs).toHaveBeenCalledWith(
        REPORT_ID,
        expect.objectContaining({ page: 37 })
      );
    });
  });

  it("jumps to last page via Last button", async () => {
    const user = userEvent.setup();
    render(<LogExplorer reportId={REPORT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId("log-last-page")).toBeEnabled();
    });

    await user.click(screen.getByTestId("log-last-page"));

    await waitFor(() => {
      expect(api.getReportLogs).toHaveBeenCalledWith(
        REPORT_ID,
        expect.objectContaining({ page: 50 })
      );
    });
  });

  it("clamps out-of-range go-to page to valid bounds", async () => {
    const user = userEvent.setup();
    render(<LogExplorer reportId={REPORT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId("log-go-to-page-input")).toBeInTheDocument();
    });

    const input = screen.getByTestId("log-go-to-page-input");
    await user.clear(input);
    await user.type(input, "99");
    fireEvent.submit(input.closest("form"));

    await waitFor(() => {
      expect(api.getReportLogs).toHaveBeenCalledWith(
        REPORT_ID,
        expect.objectContaining({ page: 50 })
      );
    });
  });

  it("refetches and clears prior rows when reportId changes", async () => {
    const reportB = "d0000000-0000-0000-0000-000000000002";
    vi.mocked(api.getReportLogs).mockImplementation(async (id) => ({
      data: {
        logs: [
          {
            timestamp: "2024-01-01 00:00:00",
            severity: "INFO",
            hostname: "node-a",
            role: "LEAF",
            message: id === REPORT_ID ? "logs for report A" : "logs for report B",
          },
        ],
        total: 1,
        page: 1,
        total_pages: 1,
        log_summary: { per_node: { "node-a": {} }, severity_counts: {} },
      },
    }));

    const { rerender } = render(<LogExplorer reportId={REPORT_ID} />);
    await waitFor(() => {
      expect(screen.getByText("logs for report A")).toBeInTheDocument();
    });

    rerender(<LogExplorer reportId={reportB} />);
    await waitFor(() => {
      expect(screen.queryByText("logs for report A")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText("logs for report B")).toBeInTheDocument();
    });
    expect(api.getReportLogs).toHaveBeenCalledWith(
      reportB,
      expect.objectContaining({ page: 1 }),
    );
  });
});
