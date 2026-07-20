import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DiskIntelligence from "./DiskIntelligence";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getReportDiskIntelligence: vi.fn(),
}));

describe("DiskIntelligence", () => {
  it("renders loading state initially", () => {
    api.getReportDiskIntelligence.mockReturnValueOnce(new Promise(() => {})); // Never resolves

    render(
      <MemoryRouter initialEntries={["/report/test-report-id/disk-intelligence"]}>
        <Routes>
          <Route path="/report/:reportId/disk-intelligence" element={<DiskIntelligence />} />
        </Routes>
      </MemoryRouter>
    );

    expect(document.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("renders error state if data fetching fails", async () => {
    api.getReportDiskIntelligence.mockRejectedValueOnce(new Error("Failed to fetch"));

    render(
      <MemoryRouter initialEntries={["/report/test-report-id/disk-intelligence"]}>
        <Routes>
          <Route path="/report/:reportId/disk-intelligence" element={<DiskIntelligence />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("disk-intelligence-error")).toHaveTextContent("Failed to fetch");
    });
  });

  it("renders data correctly when available", async () => {
    api.getReportDiskIntelligence.mockResolvedValueOnce({
      data: {
        disk_intelligence: {
          summary: {
            total_used_bytes: 10 * (1024 ** 3),
            attributed_table_bytes: 5 * (1024 ** 3),
            overhead_bytes: 5 * (1024 ** 3),
            overhead_pct: 50.0,
            is_estimate: false,
            incomplete_nodes: [],
          },
          cluster_overhead: {
            transaction_logs: { bytes: 1 * (1024 ** 3), pct_of_used_disk: 10.0 },
            snapshots: { bytes: 2 * (1024 ** 3), pct_of_used_disk: 20.0 },
          },
          per_node: [
            { node: "node1", on_disk_blobs_bytes: 1000, referenced_adjusted_bytes: 500, delta_bytes: 500, delta_pct: 50.0 },
          ],
          remediation_hints: [],
        },
      },
    });

    render(
      <MemoryRouter initialEntries={["/report/test-report-id/disk-intelligence"]}>
        <Routes>
          <Route path="/report/:reportId/disk-intelligence" element={<DiskIntelligence />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /Disk Intelligence/i })).toBeInTheDocument();
      expect(screen.getAllByText(/Mount Used/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/10.00 GB/i)).toBeInTheDocument();
      expect(screen.getByText(/Transaction Logs/i)).toBeInTheDocument();
      expect(screen.getByText(/node1/i)).toBeInTheDocument();
    });
  });

  it("renders incomplete data banner if is_estimate is true", async () => {
    api.getReportDiskIntelligence.mockResolvedValueOnce({
      data: {
        disk_intelligence: {
          summary: {
            total_used_bytes: 10 * (1024 ** 3),
            attributed_table_bytes: 5 * (1024 ** 3),
            overhead_bytes: 5 * (1024 ** 3),
            overhead_pct: 50.0,
            is_estimate: true,
            incomplete_nodes: ["node-a", "node-b"],
          },
          cluster_overhead: {},
          per_node: [],
          remediation_hints: [],
        },
      },
    });

    render(
      <MemoryRouter initialEntries={["/report/test-report-id/disk-intelligence"]}>
        <Routes>
          <Route path="/report/:reportId/disk-intelligence" element={<DiskIntelligence />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Disk intelligence data is an estimate due to incomplete data from nodes: node-a, node-b./i)).toBeInTheDocument();
    });
  });

  it("renders legacy top-level disk signals while saved reports hydrate", async () => {
    api.getReportDiskIntelligence.mockResolvedValueOnce({
      data: {
        disk_intelligence: {},
        cluster_overhead: {
          used_disk_bytes: 10 * (1024 ** 3),
          attributed_table_bytes: 4 * (1024 ** 3),
          total_bytes: 6 * (1024 ** 3),
          pct_of_used_disk: 60,
          children: {
            transaction_logs: {
              bytes: 2 * (1024 ** 3),
              pct_of_used_disk: 20,
            },
          },
        },
        blobs_referenced_delta: {
          incomplete_nodes: ["node-a"],
          per_node: [],
          ha_factor: 1,
        },
      },
    });

    render(
      <MemoryRouter initialEntries={["/report/test-report-id/disk-intelligence"]}>
        <Routes>
          <Route path="/report/:reportId/disk-intelligence" element={<DiskIntelligence />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/10.00 GB/i)).toBeInTheDocument();
      expect(screen.getByText(/6.00 GB/i)).toBeInTheDocument();
      expect(screen.getByText(/Transaction Logs/i)).toBeInTheDocument();
      expect(screen.getByText(/incomplete data from nodes: node-a/i)).toBeInTheDocument();
    });
  });
});
