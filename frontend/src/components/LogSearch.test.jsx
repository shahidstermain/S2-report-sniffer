import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LogSearch, { formatMatchBlock } from "./LogSearch";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  searchReportLogs: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const REPORT_ID = "d0000000-0000-0000-0000-000000000001";

const SAMPLE_MATCH = {
  timestamp: "2026-07-09 04:03:50.068",
  severity: "INFO",
  hostname: "node-a",
  source: "memsql_memsql.log",
  line_number: 42,
  line: "INFO: BottleGrpcClientRefreshTask: Thread 115105 (ntid 828, conn id -1): Run: Found existing Bottle Service GRPC client.",
  context_before: ["388802442292 2026-07-09 04:03:49.900 DEBUG: prior line"],
  context_after: ["388802442292 2026-07-09 04:03:50.200 DEBUG: following line"],
};

describe("formatMatchBlock", () => {
  it("includes metadata, match line, and context", () => {
    const text = formatMatchBlock(SAMPLE_MATCH);
    expect(text).toContain("[2026-07-09 04:03:50.068]");
    expect(text).toContain("file: memsql_memsql.log");
    expect(text).toContain("prior line");
    expect(text).toContain("BottleGrpcClientRefreshTask");
    expect(text).toContain("following line");
  });
});

describe("LogSearch result panel", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  const execCommand = vi.fn().mockReturnValue(true);

  beforeEach(() => {
    writeText.mockClear();
    writeText.mockResolvedValue(undefined);
    execCommand.mockClear();
    execCommand.mockReturnValue(true);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    document.execCommand = execCommand;
    vi.mocked(api.searchReportLogs).mockClear();
    vi.mocked(api.searchReportLogs).mockResolvedValue({
      data: {
        matches: [SAMPLE_MATCH],
        total: 1,
        nodes_searched: 1,
        truncated: false,
        search_mode: "raw",
      },
    });
  });

  it("shows full wrapped log block when expanded", async () => {
    const user = userEvent.setup();
    render(<LogSearch reportId={REPORT_ID} />);

    await user.type(screen.getByTestId("log-search-input"), "BottleGrpc");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => {
      expect(screen.getByTestId("log-search-result-0")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("log-search-toggle-0"));

    const block = screen.getByTestId("log-search-block-0");
    expect(block).toHaveClass("whitespace-pre-wrap");
    expect(block.textContent).toContain("prior line");
    expect(block.textContent).toContain("following line");
    expect(block.textContent).toContain("BottleGrpcClientRefreshTask");
  });

  it("copies full log block in one tap without expanding", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });

    const user = userEvent.setup();
    render(<LogSearch reportId={REPORT_ID} />);

    await user.type(screen.getByTestId("log-search-input"), "BottleGrpc");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => {
      expect(screen.getByTestId("log-search-copy-0")).toBeInTheDocument();
    });

    await fireEvent.click(screen.getByTestId("log-search-copy-0"));

    await waitFor(() => {
      expect(screen.getByTestId("log-search-copy-0")).toHaveTextContent("Copied");
    });
  });
});
