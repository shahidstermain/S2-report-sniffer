import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QueryTracePicker from "./QueryTracePicker";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  listQueryTraces: vi.fn(),
}));

const mockTraces = {
  traces: [
    {
      trace_id: "sha256:abc123def4567890",
      trace_type: "lock_wait",
      summary: "SELECT * FROM orders WHERE status = 'pending'",
      confidence: { score: 72, tier: "medium" },
      failure_stage: "leaf_lock",
      elapsed_sec: 95,
    },
  ],
  total: 1,
};

describe("QueryTracePicker", () => {
  beforeEach(() => {
    vi.mocked(api.listQueryTraces).mockResolvedValue({ data: mockTraces } as never);
  });

  it("lists trace candidates and calls onSelectTrace", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    render(<QueryTracePicker reportId="report-1" onSelectTrace={onSelect} />);

    await waitFor(() => {
      expect(screen.getByTestId("query-trace-picker")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("trace-candidate-sha256:abc123def4567890"));
    expect(onSelect).toHaveBeenCalledWith("sha256:abc123def4567890");
  });
});
