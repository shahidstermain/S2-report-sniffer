import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import LongRunningTransactionsPanel from "./LongRunningTransactionsPanel";

vi.mock("@/lib/api", () => ({
  listQueryTraces: vi.fn().mockResolvedValue({ data: { traces: [], total: 0 } }),
}));

vi.mock("./QueryTracerPanel", () => ({
  default: () => <div data-testid="query-tracer-panel" />,
}));

describe("LongRunningTransactionsPanel", () => {
  it("uses backend long_tx_count instead of the truncated preview length", () => {
    render(
      <LongRunningTransactionsPanel
        longRunningTransactions={{
          long_tx_count: 6,
          max_tx_duration_sec: 123,
          long_running_tx: [
            {
              duration_sec: 123,
              trx_state: "Running",
              trx_name: "trx-1",
              query_text: "select 1",
              user: "user1",
              database: "db1",
              node_id: "leaf-1",
            },
            {
              duration_sec: 95,
              trx_state: "Running",
              trx_name: "trx-2",
              query_text: "select 2",
              user: "user2",
              database: "db2",
              node_id: "leaf-2",
            },
          ],
          lock_waiting_count: 0,
          blocking_chains: 0,
          largest_chain_size: 0,
          has_unkillable: false,
          lock_contention_level: "moderate",
        }}
      />
    );

    expect(screen.getByText(/6 long tx \(max 123s\)/i)).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(
      screen.getAllByText((_, node) => node?.textContent === "⏱ Long-Running Transactions (6)").length
    ).toBeGreaterThan(0);
  });
});
