import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import StorageDistribution from "./StorageDistribution";

vi.mock("@/lib/api", () => ({
  getReportStorage: vi.fn(),
}));

import { getReportStorage } from "@/lib/api";

describe("StorageDistribution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders CLUSTER OVERHEAD child buckets when present", async () => {
    getReportStorage.mockResolvedValue({
      data: {
        databases: [],
        storage: [],
        database_disk_usage: [
          { DATABASE_NAME: "appdb", TOTAL_DISK_USAGE_GB: 200, _disk_bytes: 200 * 1024 ** 3 },
        ],
        partitions: {},
        cluster_overhead: {
          total_bytes: 600 * 1024 ** 3,
          pct_of_used_disk: 75,
          used_disk_bytes: 800 * 1024 ** 3,
          children: {
            logs: { bytes: 32 * 1024 ** 3, pct_of_used_disk: 4 },
            unreferenced_blobs: { bytes: 500 * 1024 ** 3, pct_of_used_disk: 62.5 },
            referenced_non_table: { bytes: 50 * 1024 ** 3, pct_of_used_disk: 6.25 },
          },
        },
        blobs_referenced_delta: { status: "skipped", skip_reason: "Re-collect with columnstore detail." },
      },
    });

    render(<StorageDistribution reportId="test-id" />);
    await waitFor(() => expect(screen.getByTestId("storage-tab-disk")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("storage-tab-disk"));

    expect(screen.getByTestId("treemap-cluster-overhead")).toBeInTheDocument();
    expect(screen.getByTestId("overhead-parent-row")).toHaveTextContent("CLUSTER OVERHEAD");
    expect(screen.getByTestId("overhead-child-unreferenced_blobs")).toBeInTheDocument();
  });

  it("shows disk usage derived from table statistics when databaseDiskUsage.json is absent", async () => {
    getReportStorage.mockResolvedValue({
      data: {
        databases: [],
        storage: [
          { DATABASE_NAME: "slateprod", MEMORY_USE: 2 * 1024 * 1024 * 1024 },
          { DATABASE_NAME: "slateprod", MEMORY_USE: 1024 * 1024 * 1024 },
        ],
        database_disk_usage: [
          {
            DATABASE_NAME: "slateprod",
            TOTAL_DISK_USAGE_GB: 3,
            _source: "table_statistics",
          },
        ],
        partitions: {},
      },
    });

    render(<StorageDistribution reportId="test-id" />);

    await waitFor(() => {
      expect(screen.getByTestId("storage-tab-disk")).toHaveTextContent("Disk Usage (1)");
    });

    fireEvent.click(screen.getByTestId("storage-tab-disk"));

    expect(screen.getByText(/Estimated from table statistics/)).toBeInTheDocument();
    const table = screen.getByTestId("disk-usage-table");
    expect(table).toHaveTextContent("slateprod");
    expect(table).toHaveTextContent("3.00");
  });

  it("opens a dialog with the full cell value on tap", async () => {
    getReportStorage.mockResolvedValue({
      data: {
        databases: [],
        storage: [
          {
            COMPUTE_ID: "14883958144909418660:18000",
            DATABASE_NAME: "ml_analytics",
            TABLE_NAME: "example_table",
          },
        ],
        database_disk_usage: [],
        partitions: {},
      },
    });

    render(<StorageDistribution reportId="test-id" />);

    await waitFor(() => {
      expect(screen.getByTestId("storage-tab-tables")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("storage-tab-tables"));

    const cell = await screen.findByText("14883958144909418660:18000");
    fireEvent.click(cell);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getAllByText("14883958144909418660:18000").length).toBeGreaterThan(1);
    });
  });
});
