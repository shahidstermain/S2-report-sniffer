import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import RecentActivity from "./RecentActivity";

describe("RecentActivity", () => {
  it("renders unknown health with a neutral icon", () => {
    render(
      <MemoryRouter>
        <RecentActivity
          reports={[
            {
              id: "00000000-0000-4000-8000-000000000001",
              report_name: "Report without analysis",
              status: "ready",
              health_score: null,
            },
          ]}
        />
      </MemoryRouter>,
    );

    const row = screen.getByTestId(
      "recent-00000000-0000-4000-8000-000000000001",
    );
    expect(row.querySelector(".lucide-circle-help")).toBeInTheDocument();
  });
});
