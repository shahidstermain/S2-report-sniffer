import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import NodeHealthChart from "./NodeHealthChart";

describe("NodeHealthChart edge cases", () => {
  it("shows empty state when nodes_detail is missing", () => {
    render(<NodeHealthChart clusterOverview={{}} />);
    expect(screen.getByText(/No node data available/)).toBeInTheDocument();
  });

  it("counts online/offline and flags impaired clusters", () => {
    render(
      <NodeHealthChart
        clusterOverview={{
          nodes_detail: [
            { state: "online" },
            { state: "online" },
            { state: "offline" },
          ],
        }}
      />
    );
    expect(screen.getByText(/2 online/)).toBeInTheDocument();
    expect(screen.getByText(/1 offline/)).toBeInTheDocument();
    expect(screen.getByText(/3 total/)).toBeInTheDocument();
  });

  it("buckets unrecognized states as UNKNOWN without crashing", () => {
    render(
      <NodeHealthChart
        clusterOverview={{
          nodes_detail: [{ state: "online" }, { state: "frobnicated" }],
        }}
      />
    );
    expect(screen.getByText(/2 total/)).toBeInTheDocument();
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
  });

  it("falls back to status field and defaults missing state to unknown", () => {
    render(
      <NodeHealthChart
        clusterOverview={{ nodes_detail: [{ status: "online" }, {}] }}
      />
    );
    expect(screen.getByText(/2 total/)).toBeInTheDocument();
  });
});
