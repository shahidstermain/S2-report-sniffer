import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
});
