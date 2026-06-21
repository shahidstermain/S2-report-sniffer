import React from "react";
import { describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const searchReportLogs = vi.fn().mockResolvedValue({
  data: {
    matches: [
      {
        timestamp: "2024-01-15 10:00:03.000",
        severity: "ERROR",
        hostname: "leaf-1",
        message: "Connection timeout after 30s",
      },
    ],
    total: 1,
    nodes_searched: 1,
    truncated: false,
  },
});

vi.mock("@/lib/api", () => ({
  searchReportLogs,
}));

import LogSearch from "./LogSearch";

describe("LogSearch", () => {
  test("searches through the shared API client", async () => {
    render(<LogSearch reportId="report-1" />);

    fireEvent.change(screen.getByTestId("log-search-input"), {
      target: { value: "Connection" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => {
      expect(searchReportLogs).toHaveBeenCalledWith("report-1", {
        keyword: "Connection",
        regex: false,
        case_sensitive: false,
        max_results: 500,
      });
    });
    expect(await screen.findByText(/Found/)).toBeInTheDocument();
  });
});
