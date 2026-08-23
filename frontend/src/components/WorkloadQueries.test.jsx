import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import WorkloadQueries from "./WorkloadQueries";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getReportQueries: vi.fn(),
  getQueryTrace: vi.fn(),
  resolveQueryTrace: vi.fn(),
  listQueryTraces: vi.fn().mockResolvedValue({ data: { traces: [], total: 0 } }),
}));

vi.mock("./QueryTraceFlowDiagram", () => ({
  default: () => <div data-testid="query-trace-flow" />,
}));

vi.mock("./QueryTraceTimeline", () => ({
  default: () => <div data-testid="query-trace-timeline" />,
}));

const TRACE_ID = "sha256:cd159c617313c3d8";

describe("WorkloadQueries deep-link", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getQueryTrace).mockResolvedValue({
      data: {
        trace_id: TRACE_ID,
        trace_type: "lock_wait",
        query_text: "SELECT * FROM orders",
        confidence: { score: 65, tier: "medium", factors: [] },
        stages: [{ id: "client", label: "Client", node_role: "CLIENT", node_host: "client", status: "healthy", observed: false }],
        edges: [],
      },
    });
  });

  it("opens QueryTracerPanel during queries load when initialTraceId is set", async () => {
    let resolveQueries;
    vi.mocked(api.getReportQueries).mockReturnValue(
      new Promise((resolve) => {
        resolveQueries = resolve;
      })
    );

    render(<WorkloadQueries reportId="d0000000-0000-0000-0000-000000000001" initialTraceId={TRACE_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId("query-tracer-panel")).toBeInTheDocument();
    });

    resolveQueries({
      data: {
        queries: [],
        workload_management: [],
        cluster_overview: { blocked_queries: [], processlist: [] },
        resource_pools: [],
        alloc_memory: { per_node: [], totals: [] },
        query_analysis: { summary: {}, long_running: [], runaway_patterns: [], lock_holders: [] },
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("query-tracer-panel")).toBeInTheDocument();
    });
    expect(api.getQueryTrace).toHaveBeenCalledWith("d0000000-0000-0000-0000-000000000001", TRACE_ID);
  });

  it("uses backend summary counts instead of truncated pattern arrays", async () => {
    vi.mocked(api.getReportQueries).mockResolvedValue({
      data: {
        queries: [],
        workload_management: [],
        cluster_overview: { blocked_queries: [], processlist: [] },
        resource_pools: [],
        alloc_memory: { per_node: [], totals: [] },
        query_analysis: {
          summary: {
            long_running_count: 4,
            runaway_pattern_count: 2,
            lock_holder_count: 1,
          },
          long_running: [{ time_sec: 61, user: "u1", host: "h1", db: "db1", query_preview: "select 1" }],
          runaway_patterns: [{ occurrences: 3, max_time_sec: 19, fingerprint: "select * from t" }],
          lock_holders: [{ time_sec: 88, user: "u2", db: "db2", state: "sleep", query_preview: "update t set x = 1" }],
        },
      },
    });

    render(<WorkloadQueries reportId="d0000000-0000-0000-0000-000000000002" />);

    await waitFor(() => {
      expect(screen.getByText("Patterns (7)")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("queries-tab-patterns"));

    await waitFor(() => {
      expect(screen.getByText("Long-running queries (4)")).toBeInTheDocument();
      expect(screen.getByText("Long-running query patterns (>5 min) (2)")).toBeInTheDocument();
      expect(screen.getByText("Sleeping lock holders (1)")).toBeInTheDocument();
    });
  });

  it("does not crash when query tables arrive as {rows: [...]} wrappers", async () => {
    vi.mocked(api.getReportQueries).mockResolvedValue({
      data: {
        queries: { rows: [{ QUERY_TEXT: "select 1", ACTIVITY_NAME: "q1" }] },
        workload_management: { rows: [] },
        cluster_overview: {
          blocked_queries: { rows: [] },
          processlist: { rows: [] },
        },
        resource_pools: { rows: [] },
        alloc_memory: { per_node: [], totals: [] },
        query_analysis: { summary: {}, long_running: [], runaway_patterns: [], lock_holders: [] },
      },
    });

    render(<WorkloadQueries reportId="d0000000-0000-0000-0000-000000000003" />);

    await waitFor(() => {
      expect(screen.getByText("Queries (1)")).toBeInTheDocument();
    });
    expect(screen.getByText("select 1")).toBeInTheDocument();
  });

  it("clears prior queries while loading a different reportId", async () => {
    let resolveSecond;
    vi.mocked(api.getReportQueries)
      .mockResolvedValueOnce({
        data: {
          queries: [{ QUERY_TEXT: "select from report-a", ACTIVITY_NAME: "qa" }],
          workload_management: [],
          cluster_overview: { blocked_queries: [], processlist: [] },
          resource_pools: [],
          alloc_memory: { per_node: [], totals: [] },
          query_analysis: { summary: {}, long_running: [], runaway_patterns: [], lock_holders: [] },
        },
      })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveSecond = resolve;
        }),
      );

    const { rerender } = render(
      <WorkloadQueries reportId="d0000000-0000-0000-0000-00000000000a" />,
    );

    await waitFor(() => {
      expect(screen.getByText("select from report-a")).toBeInTheDocument();
    });

    rerender(<WorkloadQueries reportId="d0000000-0000-0000-0000-00000000000b" />);

    await waitFor(() => {
      expect(screen.queryByText("select from report-a")).not.toBeInTheDocument();
    });

    resolveSecond({
      data: {
        queries: [{ QUERY_TEXT: "select from report-b", ACTIVITY_NAME: "qb" }],
        workload_management: [],
        cluster_overview: { blocked_queries: [], processlist: [] },
        resource_pools: [],
        alloc_memory: { per_node: [], totals: [] },
        query_analysis: { summary: {}, long_running: [], runaway_patterns: [], lock_holders: [] },
      },
    });

    await waitFor(() => {
      expect(screen.getByText("select from report-b")).toBeInTheDocument();
    });
  });
});
