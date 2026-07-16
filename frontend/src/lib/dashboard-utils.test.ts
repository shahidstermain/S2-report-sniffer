import { describe, it, expect } from "vitest";
import { buildUploadsTimeline, computeStatusBreakdown, filterReports, sortReports } from "./dashboard-utils";

describe("buildUploadsTimeline", () => {
  it("classifies non-ready reports so stacked totals still match bucket counts", () => {
    const now = new Date("2026-07-14T12:00:00Z").getTime();
    const reports = [
      { uploaded_at: "2026-07-14T02:00:00Z", status: "ready", health_score: "critical" },
      { uploaded_at: "2026-07-14T03:00:00Z", status: "processing" },
      { uploaded_at: "2026-07-14T04:00:00Z", status: "error" },
      { uploaded_at: "2026-07-14T05:00:00Z", status: "ready", health_score: "unknown" },
      { uploaded_at: "2026-07-14T06:00:00Z", status: "queued" },
    ];

    const timeline = buildUploadsTimeline(reports, 1, now);

    expect(timeline).toHaveLength(1);
    expect(timeline[0]).toEqual(
      expect.objectContaining({
        count: 5,
        critical: 1,
        warning: 0,
        healthy: 0,
        processing: 1,
        error: 1,
        unknown: 2,
      })
    );
  });
});

describe("dashboard health helpers", () => {
  it("classifies numeric health scores through health grades", () => {
    const counts = computeStatusBreakdown([
      { status: "ready", health_score: 92, health_grade: "A" },
      { status: "ready", health_score: 74, health_grade: "C" },
      { status: "ready", health_score: 58, health_grade: "F" },
      { status: "processing" },
    ]);

    expect(counts).toEqual(
      expect.objectContaining({
        healthy: 1,
        warning: 1,
        critical: 1,
        processing: 1,
      })
    );
  });

  it("increments unknown for ready reports with unknown health", () => {
    const counts = computeStatusBreakdown([
      { status: "ready", health_score: "unknown" },
      { status: "ready" },
      { status: "queued" },
    ]);

    expect(counts).toEqual(
      expect.objectContaining({
        ready: 2,
        unknown: 3, // 2 ready-unknown health + 1 non-ready status
      })
    );
  });

  it("filters last-24h and last-7d KPI windows", () => {
    const now = new Date("2026-07-14T12:00:00Z").getTime();
    const reports = [
      { id: "r1", uploaded_at: "2026-07-14T08:00:00Z", status: "ready", health_score: 80, health_grade: "B" },
      { id: "r2", uploaded_at: "2026-07-10T08:00:00Z", status: "ready", health_score: 70, health_grade: "C" },
      { id: "r3", uploaded_at: "2026-07-01T08:00:00Z", status: "ready", health_score: 55, health_grade: "F" },
    ];

    expect(filterReports(reports, { timeFilter: "last24h", now }).map((r) => r.id)).toEqual(["r1"]);
    expect(filterReports(reports, { timeFilter: "last7d", now }).map((r) => r.id)).toEqual(["r1", "r2"]);
  });

  it("sorts numeric health scores instead of lexicographic strings", () => {
    const sorted = sortReports(
      [
        { id: "healthy", health_score: 92, health_grade: "A" },
        { id: "warning", health_score: 72, health_grade: "C" },
        { id: "critical", health_score: 55, health_grade: "F" },
      ],
      { key: "health_score", dir: "asc" }
    );

    expect(sorted.map((row) => row.id)).toEqual(["critical", "warning", "healthy"]);
  });
});
