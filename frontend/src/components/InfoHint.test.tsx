import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import InfoHint from "./InfoHint";

describe("InfoHint", () => {
  test("exposes an accessible label", () => {
    render(<InfoHint label="memory utilization" content="Memory captured when the report was collected." />);

    expect(
      screen.getByRole("button", { name: "About memory utilization" })
    ).toBeInTheDocument();
  });

  test("shows contextual help on keyboard focus", async () => {
    render(<InfoHint label="memory utilization" content="Memory captured when the report was collected." />);

    fireEvent.focus(screen.getByRole("button", { name: "About memory utilization" }));

    await waitFor(() => {
      expect(screen.getByRole("tooltip")).toHaveTextContent(
        "Memory captured when the report was collected."
      );
    });
  });

  test("shows contextual help on pointer hover", async () => {
    const user = userEvent.setup();
    render(<InfoHint label="disk usage" content="Disk usage from the report snapshot." />);

    await user.hover(screen.getByRole("button", { name: "About disk usage" }));

    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "Disk usage from the report snapshot."
    );
  });
});
