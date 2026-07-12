import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { readFileSync } from "fs";
import ChartsDashboard from "./ChartsDashboard";
import * as api from "@/lib/api";

const REAL_REPORT_ID = "7e2567f2-9233-42b3-bb23-0be29c33d840";

describe("ChartsDashboard real overview", () => {
  let realOverview;

  beforeAll(async () => {
    const res = await fetch(
      `http://127.0.0.1:8000/api/reports/${REAL_REPORT_ID}/overview`,
    );
    if (!res.ok) {
      realOverview = JSON.parse(readFileSync("/tmp/real-overview.json", "utf8"));
      return;
    }
    realOverview = await res.json();
  });

  it("renders real report overview without crash", async () => {
    vi.spyOn(api, "getReportOverview").mockResolvedValue({ data: realOverview });

    render(
      <MemoryRouter initialEntries={[`/report/${REAL_REPORT_ID}/charts`]}>
        <Routes>
          <Route path="/report/:reportId/charts" element={<ChartsDashboard />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Cluster Diagnostics/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Backup Timeline/)).toBeInTheDocument();
  });
});
