import { beforeEach, describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import GuidedTourOverlay from "./GuidedTourOverlay";
import { GuidedModeProvider, useGuidedMode } from "./GuidedModeProvider";

const mocks = vi.hoisted(() => ({
  createDemoWorkspace: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  createDemoWorkspace: mocks.createDemoWorkspace,
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));


function Harness({ dashboard = false }) {
  const { launchDemoWorkspace, startTour } = useGuidedMode();
  return (
    <>
      <button type="button" onClick={() => startTour()}>Start tour</button>
      <button type="button" onClick={launchDemoWorkspace}>Launch demo</button>
      <div data-guide-id={dashboard ? "dashboard.demoBadge" : "demo.launch"}>
        Tour target
      </div>
      {dashboard && (
        <>
          <button
            type="button"
            data-testid="tab-disk-intelligence"
            data-guide-available="false"
          >
            Disk Intelligence
          </button>
          <button
            type="button"
            data-testid="tab-queries"
            data-guide-available="true"
          >
            Queries
          </button>
        </>
      )}
    </>
  );
}


function renderGuided(path = "/", dashboard = false) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <GuidedModeProvider>
        <Harness dashboard={dashboard} />
        <GuidedTourOverlay />
      </GuidedModeProvider>
    </MemoryRouter>,
  );
}


describe("GuidedModeProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("contains keyboard focus and closes the tour with Escape", async () => {
    renderGuided();
    const start = screen.getByRole("button", { name: "Start tour" });
    start.focus();
    fireEvent.click(start);

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveFocus());

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(start).toHaveFocus();
  });

  test("does not rethrow a handled demo launch failure", async () => {
    mocks.createDemoWorkspace.mockRejectedValueOnce(new Error("offline"));
    renderGuided();

    fireEvent.click(screen.getByRole("button", { name: "Launch demo" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith(
        "Could not create demo workspace",
      );
    });
  });

  test("filters unavailable dashboard tabs from the tour", async () => {
    renderGuided("/report/demo/overview", true);

    fireEvent.click(screen.getByRole("button", { name: "Start tour" }));

    await screen.findByRole("dialog");
    expect(screen.getByText("Guided mode · 1/8")).toBeInTheDocument();
  });
});
