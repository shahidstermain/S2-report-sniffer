import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PressureEventsChart from "./PressureEventsChart";

describe("PressureEventsChart edge cases", () => {
  it("shows empty state when there are no pressure events", () => {
    render(<PressureEventsChart pressureEvents={{}} />);
    expect(screen.getByText(/No write stalls or network timeouts detected/)).toBeInTheDocument();
  });

  it("treats all-zero buckets as empty", () => {
    render(<PressureEventsChart pressureEvents={{ etimedout: { "2024-01-01 10": 0 } }} />);
    expect(screen.getByText(/No write stalls or network timeouts detected/)).toBeInTheDocument();
  });

  it("aggregates event counts across hour buckets", () => {
    render(
      <PressureEventsChart
        pressureEvents={{
          etimedout: { "2024-01-01 10": 3, "2024-01-01 11": 7 },
          fsync_behind: { "2024-01-01 10": 2 },
        }}
      />
    );
    // 3 + 7 + 2 = 12 total events.
    expect(screen.getByText(/total events/)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("handles undefined pressureEvents prop", () => {
    render(<PressureEventsChart pressureEvents={undefined} />);
    expect(screen.getByText(/No write stalls or network timeouts detected/)).toBeInTheDocument();
  });
});
