import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import InsightsPanel from "./InsightsPanel";

describe("InsightsPanel", () => {
  test("derives next steps from findings", () => {
    render(
      <InsightsPanel
        findings={[
          { checker_id: "tracelogOOM", severity: "critical", title: "OOM kills" },
          { checker_id: "slowQueries", severity: "warning", title: "Slow queries" },
        ]}
      />
    );

    expect(screen.getByTestId("insights-next-steps")).toBeInTheDocument();
    expect(screen.getAllByText(/OOM kills/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Slow queries/i).length).toBeGreaterThan(0);
  });

  test("shows empty guidance when there are no findings", () => {
    render(<InsightsPanel findings={[]} />);
    expect(screen.getByText(/Load a report with findings/i)).toBeInTheDocument();
  });
});
