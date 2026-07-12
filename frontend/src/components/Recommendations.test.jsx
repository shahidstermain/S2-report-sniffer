import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { filterRecommendationsByCluster } from "./Recommendations";
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

const RECS = [
  { id: 1, checker_id: "maxOpenFiles", triage: { cluster_id: "INC-001" } },
  { id: 2, checker_id: "clusterMemoryUsage", triage: { cluster_id: "INC-001" } },
  { id: 3, checker_id: "slowQueries", triage: {} },
];

const CLUSTERS = [
  {
    cluster_id: "INC-001",
    member_ids: [1, 2],
    member_count: 2,
  },
];

describe("filterRecommendationsByCluster", () => {
  it("filters by triage.cluster_id stamp", () => {
    const filtered = filterRecommendationsByCluster(RECS, "INC-001", CLUSTERS);
    expect(filtered).toHaveLength(2);
    expect(filtered.map((r) => r.id)).toEqual([1, 2]);
  });

  it("falls back to member_ids when cluster stamp is missing", () => {
    const recs = [
      { id: 10, checker_id: "a" },
      { id: 11, checker_id: "b" },
      { id: 12, checker_id: "c" },
    ];
    const clusters = [{ cluster_id: "INC-002", member_ids: [10, 12] }];
    const filtered = filterRecommendationsByCluster(recs, "INC-002", clusters);
    expect(filtered.map((r) => r.id)).toEqual([10, 12]);
  });

  it("returns all recs when cluster id is unknown", () => {
    expect(filterRecommendationsByCluster(RECS, "INC-999", CLUSTERS)).toEqual(RECS);
  });
});

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
});
