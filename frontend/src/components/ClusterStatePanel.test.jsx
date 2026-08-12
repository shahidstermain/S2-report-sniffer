import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import ClusterStatePanel from "./ClusterStatePanel";

describe("ClusterStatePanel", () => {
  test("keeps hook order stable when rebalance content appears after an empty mount", () => {
    const { rerender } = render(<ClusterStatePanel rebalanceEvents={null} />);
    expect(screen.queryByText(/Rebalance/i)).not.toBeInTheDocument();

    // Previously crashed with "Rendered more hooks than during the previous render"
    // because useMemo ran only on the contentful path after an early return.
    expect(() =>
      rerender(
        <ClusterStatePanel
          rebalanceEvents={{
            status: "ACTIVE",
            events: [
              {
                event_time: "2024-01-01T00:00:00",
                event_type: "REBALANCE_STARTED",
                node_id: "1",
                description: "moving partitions",
              },
            ],
            raw_status: [{ Status: "ACTIVE", Detail: "in progress" }],
          }}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByText("REBALANCING")).toBeInTheDocument();
    expect(screen.getByText("REBALANCE_STARTED")).toBeInTheDocument();
  });

  test("keeps hook order stable when rebalance content disappears", () => {
    const { rerender } = render(
      <ClusterStatePanel
        rebalanceEvents={{
          status: "FAILED",
          reason: "disk full",
          events: [{ event_time: "2024-01-01T00:00:00", event_type: "REBALANCE_FAILED" }],
        }}
      />,
    );
    expect(screen.getByText("REBALANCE FAILED")).toBeInTheDocument();

    expect(() => rerender(<ClusterStatePanel rebalanceEvents={{ status: "IDLE" }} />)).not.toThrow();
    expect(screen.queryByText("REBALANCE FAILED")).not.toBeInTheDocument();
  });

  test("accepts legacy {rows:[...]} wrappers for events and raw_status", () => {
    expect(() =>
      render(
        <ClusterStatePanel
          rebalanceEvents={{
            status: "IDLE",
            events: {
              rows: [
                {
                  event_time: "2024-01-01T00:00:00",
                  event_type: "REBALANCE_COMPLETED",
                },
              ],
            },
            raw_status: { rows: [{ Status: "IDLE" }] },
          }}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByText("REBALANCE_COMPLETED")).toBeInTheDocument();
  });
});
