import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test } from "vitest";
import HelpMenu from "./HelpMenu";


describe("HelpMenu", () => {
  test("renders its pane in a viewport-bounded portal", async () => {
    const { container } = render(
      <MemoryRouter>
        <HelpMenu />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open guided mode help" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveClass("max-h-[calc(100dvh-2rem)]");
    expect(dialog).toHaveClass("w-[calc(100vw-2rem)]");
    expect(container).not.toContainElement(dialog);
    expect(screen.getByText("Metric glossary")).toBeInTheDocument();
  });
});
