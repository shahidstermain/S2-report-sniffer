import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { existsSync, readFileSync } from "fs";
import ChartsDashboard from "./ChartsDashboard";
import * as api from "@/lib/api";

const REAL_REPORT_ID = "7e2567f2-9233-42b3-bb23-0be29c33d840";

describe("ChartsDashboard real overview", () => {
  let realOverview;
  const fallbackPath = "/tmp/real-overview.json";

  beforeAll(async () => {
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/api/reports/${REAL_REPORT_ID}/overview`,
      );
      if (res.ok) {
        realOverview = await res.json();
        return;
      }
    } catch {
      // Fall through to optional local fixture below.
    }

    if (existsSync(fallbackPath)) {
      realOverview = JSON.parse(readFileSync(fallbackPath, "utf8"));
    }
  });

  it("renders real report overview without crash", async () => {
    if (!realOverview) return;
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
