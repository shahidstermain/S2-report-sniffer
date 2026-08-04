import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import Recommendations from "./Recommendations";

const getReportRecommendations = vi.fn();
const getReportTriage = vi.fn();
const listQueryTraces = vi.fn();
const getGleanPacket = vi.fn();
const handoffGleanPacket = vi.fn();

vi.mock("@/lib/api", () => ({
  getReportRecommendations: (...args) => getReportRecommendations(...args),
  getReportTriage: (...args) => getReportTriage(...args),
  listQueryTraces: (...args) => listQueryTraces(...args),
  getGleanPacket: (...args) => getGleanPacket(...args),
}));

vi.mock("@/lib/gleanHandoff", () => ({
  handoffGleanPacket: (...args) => handoffGleanPacket(...args),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("Analyze in Glean button", () => {
  beforeEach(() => {
    getReportRecommendations.mockReset();
    getReportTriage.mockReset();
    listQueryTraces.mockReset();
    getGleanPacket.mockReset();
    handoffGleanPacket.mockReset();

    getReportRecommendations.mockResolvedValue({
      data: {
        recommendations: [
          {
            id: 1,
            checker_id: "swapEnabled",
            severity: "warning",
            title: "Swap is disabled",
            risk_score: 55,
            confidence: 0.8,
            category: "Memory",
          },
        ],
      },
    });
    getReportTriage.mockResolvedValue({
      data: {
        health_score: 74,
        health_grade: "C",
        summary: { act_now: 0, quick_wins: 1, act_soon: 0, backlog: 0, incident_clusters: 0 },
        act_now: [],
        quick_wins: [],
        act_soon: [],
        backlog: [],
        incident_clusters: [],
      },
    });
    getGleanPacket.mockResolvedValue({
      data: {
        filename: "s2rs-incident-packet-abc.md",
        markdown: "# packet",
        prompt: "Please analyze",
      },
    });
    handoffGleanPacket.mockResolvedValue({ mode: "web" });
  });

  it("fetches the packet and hands it off", async () => {
    render(<Recommendations reportId="00000000-0000-0000-0000-000000000001" />);

    const button = await screen.findByTestId("analyze-in-glean");
    fireEvent.click(button);

    await waitFor(() => {
      expect(getGleanPacket).toHaveBeenCalledWith("00000000-0000-0000-0000-000000000001");
      expect(handoffGleanPacket).toHaveBeenCalledWith({
        filename: "s2rs-incident-packet-abc.md",
        markdown: "# packet",
        prompt: "Please analyze",
      });
    });
  });

  it("renders the backend-owned health score and grade", async () => {
    render(<Recommendations reportId="00000000-0000-0000-0000-000000000001" />);

    expect(await screen.findByText(/Finding Severity Index: Grade C/)).toBeInTheDocument();
    expect(screen.getByText("74")).toBeInTheDocument();
  });

  it("does not fabricate health score or grade when triage omits them", async () => {
    getReportTriage.mockResolvedValue({
      data: {
        summary: { act_now: 0, quick_wins: 0, act_soon: 0, backlog: 0, incident_clusters: 0 },
        act_now: [],
        quick_wins: [],
        act_soon: [],
        backlog: [],
        incident_clusters: [],
      },
    });

    render(<Recommendations reportId="00000000-0000-0000-0000-000000000001" />);

    expect(await screen.findByText("Finding Severity Index")).toBeInTheDocument();
    expect(screen.queryByText(/Grade [A-F]/)).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("Evidence visibility and log navigation", () => {
  beforeEach(() => {
    getReportRecommendations.mockReset();
    getReportTriage.mockReset();
  });

  it("shows full evidence, affected nodes, and evidence sources; 'View in Logs' deep-links with the backend hint", async () => {
    const onNavigateTab = vi.fn();
    getReportRecommendations.mockResolvedValue({
      data: {
        recommendations: [
          {
            id: 1,
            checker_id: "tracelogOOM",
            severity: "critical",
            title: "OOM kill detected on host1",
            description: "desc",
            evidence: "Jul 10 02:15:00 host1 kernel: Out of memory: Kill process 1234",
            remediation: "Reduce memory pressure.",
            risk_score: 90,
            confidence: 0.9,
            category: "Memory",
            nodes: ["host1"],
            related_views: ["dmesg", "free", "MV_SYSINFO_MEM"],
            log_search: { keyword: "starting up, version", node: "host1" },
            triage: {},
          },
        ],
      },
    });
    getReportTriage.mockResolvedValue({
      data: {
        summary: { act_now: 1, quick_wins: 0, act_soon: 0, backlog: 0, incident_clusters: 0 },
        act_now: [],
        quick_wins: [],
        act_soon: [],
        backlog: [],
        incident_clusters: [],
      },
    });

    render(<Recommendations reportId="00000000-0000-0000-0000-000000000001" onNavigateTab={onNavigateTab} />);

    fireEvent.click(await screen.findByText("OOM kill detected on host1"));

    expect(await screen.findByTestId("finding-evidence-full")).toHaveTextContent(
      "Out of memory: Kill process 1234"
    );
    expect(screen.getByTestId("finding-related-views")).toHaveTextContent("dmesg");
    expect(within(screen.getByTestId("finding-nodes")).getByText("host1")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("finding-view-in-logs"));
    expect(onNavigateTab).toHaveBeenCalledWith("log-search", {
      keyword: "starting up, version",
      node: "host1",
    });
  });

  it("hides View in Logs when no grounded tracelog keyword exists", async () => {
    const onNavigateTab = vi.fn();
    getReportRecommendations.mockResolvedValue({
      data: {
        recommendations: [
          {
            id: 2,
            checker_id: "swapUsageDetected",
            severity: "warning",
            title: "Swap usage detected",
            description: "desc",
            evidence: "swap_used_pct=42.0%",
            nodes: [],
            log_search: { keyword: "", node: "" },
            triage: {},
          },
        ],
      },
    });
    getReportTriage.mockResolvedValue({
      data: {
        summary: { act_now: 0, quick_wins: 0, act_soon: 1, backlog: 0, incident_clusters: 0 },
        act_now: [], quick_wins: [], act_soon: [], backlog: [], incident_clusters: [],
      },
    });

    render(<Recommendations reportId="00000000-0000-0000-0000-000000000001" onNavigateTab={onNavigateTab} />);

    fireEvent.click(await screen.findByText("Swap usage detected"));
    expect(screen.queryByTestId("finding-view-in-logs")).not.toBeInTheDocument();
  });

  it("falls back to empty keyword when backend hint is missing for config checkers", async () => {
    const onNavigateTab = vi.fn();
    getReportRecommendations.mockResolvedValue({
      data: {
        recommendations: [
          {
            id: 2,
            checker_id: "swapUsageDetected",
            severity: "warning",
            title: "Swap usage detected",
            description: "desc",
            evidence: "swap_used_pct=42.0%",
            nodes: [],
            triage: {},
          },
        ],
      },
    });
    getReportTriage.mockResolvedValue({
      data: {
        summary: { act_now: 0, quick_wins: 0, act_soon: 1, backlog: 0, incident_clusters: 0 },
        act_now: [], quick_wins: [], act_soon: [], backlog: [], incident_clusters: [],
      },
    });

    render(<Recommendations reportId="00000000-0000-0000-0000-000000000001" onNavigateTab={onNavigateTab} />);

    fireEvent.click(await screen.findByText("Swap usage detected"));
    expect(screen.queryByTestId("finding-view-in-logs")).not.toBeInTheDocument();
  });
});

describe("Recommendations fetch failure", () => {
  beforeEach(() => {
    getReportRecommendations.mockReset();
    getReportTriage.mockReset();
  });

  it("shows an error instead of a false empty findings list when recommendations fail", async () => {
    getReportRecommendations.mockRejectedValue({ response: { status: 500 } });
    getReportTriage.mockResolvedValue({ data: {} });

    render(<Recommendations reportId="00000000-0000-0000-0000-000000000001" />);

    expect(await screen.findByTestId("recommendations-error")).toBeInTheDocument();
    expect(screen.queryByText(/Finding Severity Index/)).not.toBeInTheDocument();
  });

  it("clears prior report findings when reportId changes and the next fetch fails", async () => {
    getReportRecommendations.mockResolvedValueOnce({
      data: {
        recommendations: [
          {
            id: 1,
            checker_id: "swapEnabled",
            severity: "critical",
            title: "Swap is enabled on report A",
            risk_score: 85,
            confidence: 0.9,
            category: "Memory",
          },
        ],
        health_score: 40,
        health_grade: "D",
      },
    });
    getReportTriage.mockResolvedValue({
      data: {
        health_score: 40,
        health_grade: "D",
        summary: { act_now: 1, quick_wins: 0, act_soon: 0, backlog: 0, incident_clusters: 0 },
        act_now: [],
        quick_wins: [],
        act_soon: [],
        backlog: [],
        incident_clusters: [],
      },
    });

    const { rerender } = render(
      <Recommendations reportId="00000000-0000-0000-0000-000000000001" />,
    );
    expect(await screen.findByText("Swap is enabled on report A")).toBeInTheDocument();

    getReportRecommendations.mockRejectedValueOnce({ response: { status: 502 } });
    rerender(<Recommendations reportId="00000000-0000-0000-0000-000000000002" />);

    expect(await screen.findByTestId("recommendations-error")).toBeInTheDocument();
    expect(screen.queryByText("Swap is enabled on report A")).not.toBeInTheDocument();
  });
});
