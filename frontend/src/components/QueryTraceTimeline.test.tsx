import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QueryTraceTimeline from "./QueryTraceTimeline";

const TIMELINE = {
  snapshot_timestamp: "2024-06-01 12:00:00.000000",
  collection_note: "Snapshot only.",
  lanes: [
    {
      role: "CLIENT",
      label: "Client",
      events: [{ id: "connect", label: "Client request", observed: false, stage_id: "client" }],
    },
    {
      role: "MA",
      label: "Aggregator (10.0.0.1)",
      events: [
        {
          id: "processlist_snapshot",
          label: "Processlist snapshot",
          observed: true,
          stage_id: "aggregator_ingress",
          elapsed_sec: 95,
        },
      ],
    },
  ],
};

describe("QueryTraceTimeline", () => {
  test("renders swim lanes and snapshot timestamp", () => {
    render(<QueryTraceTimeline timeline={TIMELINE} />);
    expect(screen.getByTestId("query-trace-timeline")).toBeInTheDocument();
    expect(screen.getByText(/Snapshot window ends/)).toBeInTheDocument();
    expect(screen.getByText("Processlist snapshot")).toBeInTheDocument();
  });

  test("selects stage on event click", async () => {
    const onSelectStage = vi.fn();
    const user = userEvent.setup();
    render(<QueryTraceTimeline timeline={TIMELINE} onSelectStage={onSelectStage} />);
    await user.click(screen.getByTestId("timeline-event-processlist_snapshot"));
    expect(onSelectStage).toHaveBeenCalledWith("aggregator_ingress");
  });
});
