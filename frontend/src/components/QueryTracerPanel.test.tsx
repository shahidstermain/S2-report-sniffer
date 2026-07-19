import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QueryTracerPanel from "./QueryTracerPanel";
import TerminologyNormalizer from "./TerminologyNormalizer";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  resolveQueryTrace: vi.fn(),
  getQueryTrace: vi.fn(),
}));

const mockTrace = {
  trace_id: "sha256:abc123def4567890",
  trace_type: "lock_wait",
  query_text: "SELECT * FROM orders",
  confidence: {
    score: 35,
    tier: "low",
    factors: [{ id: "blocked_query_row", label: "Blocked row", weight: 20, present: true }],
  },
  stages: [
    {
      id: "client",
      label: "Client",
      node_role: "CLIENT",
      node_host: "client",
      status: "healthy",
      observed: false,
    },
    {
      id: "leaf_lock",
      label: "Leaf lock wait",
      node_role: "LEAF",
      node_host: "10.0.0.3",
      status: "critical",
      observed: true,
      evidence: [{ source: "mv_blocked_queries" }],
    },
  ],
  edges: [{ from: "client", to: "leaf_lock", label: "flow", inferred: true }],
  failure: { stage_id: "leaf_lock", category: "lock_wait", summary: "Waiting for row lock" },
  routing: { label: "partitions:single", confidence: "medium", reason: "Equality on status" },
  timeline: {
    snapshot_timestamp: "2024-06-01 12:00:00.000000",
    lanes: [
      {
        role: "MA",
        label: "Aggregator (10.0.0.1)",
        events: [{ id: "ingress", label: "Processlist snapshot", observed: true, stage_id: "aggregator_ingress" }],
      },
    ],
  },
  related_findings: ["lockContention"],
  evidence_summary: ["MV_BLOCKED_QUERIES", "processlist id 42"],
  log_correlations: [],
  limitations: ["No EXPLAIN/PROFILE in bundle."],
};

describe("QueryTracerPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.resolveQueryTrace).mockResolvedValue({ data: mockTrace } as never);
    vi.mocked(api.getQueryTrace).mockResolvedValue({ data: mockTrace } as never);
  });

  it("renders summary, evidence strip, and low-confidence banner", async () => {
    render(
      <QueryTracerPanel
        reportId="report-1"
        selector={{ connection_id: "42", query_text: "SELECT * FROM orders" }}
        onClose={() => {}}
      />
    );

    expect(screen.getByTestId("query-tracer-panel")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("low-confidence-banner")).toBeInTheDocument();
      expect(screen.getByTestId("evidence-strip")).toBeInTheDocument();
    });

    expect(screen.getByText(/MV_BLOCKED_QUERIES/)).toBeInTheDocument();
    expect(screen.getByText(/35%/)).toBeInTheDocument();
  });

  it("switches to flow and findings tabs", async () => {
    const user = userEvent.setup();
    render(
      <QueryTracerPanel
        reportId="report-1"
        selector={{ connection_id: "42" }}
        onClose={() => {}}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("trace-tab-flow")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("trace-tab-flow"));
    expect(screen.getByTestId("query-trace-flow")).toBeInTheDocument();

    await user.click(screen.getByTestId("trace-tab-findings"));
    expect(screen.getByText("lockContention")).toBeInTheDocument();
  });

  it("loads trace by trace_id via getQueryTrace", async () => {
    render(
      <QueryTracerPanel
        reportId="report-1"
        selector={{ trace_id: "sha256:abc123def4567890" }}
        onClose={() => {}}
      />
    );

    await waitFor(() => {
      expect(api.getQueryTrace).toHaveBeenCalledWith("report-1", "sha256:abc123def4567890");
    });
    expect(api.resolveQueryTrace).not.toHaveBeenCalled();
  });

  it("preserves raw SQL terminology while normalization is active", async () => {
    const rawQuery = "SELECT * FROM events WHERE label = 'Slow Queries'";
    vi.mocked(api.resolveQueryTrace).mockResolvedValue({
      data: { ...mockTrace, query_text: rawQuery },
    } as never);

    render(
      <>
        <TerminologyNormalizer />
        <QueryTracerPanel
          reportId="report-1"
          selector={{ connection_id: "42", query_text: rawQuery }}
          onClose={() => {}}
        />
      </>
    );

    await waitFor(() => {
      expect(screen.getByText(rawQuery)).toBeInTheDocument();
    });
  });
});
