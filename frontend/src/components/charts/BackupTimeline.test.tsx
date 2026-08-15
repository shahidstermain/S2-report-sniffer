import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import BackupTimeline from "./BackupTimeline";

// Regression: malformed/negative-duration backup rows must not poison the
// duration stats. A single unparseable timestamp used to yield NaN that
// survived the filter and turned Avg/Min/Max/P95 into "—".
describe("BackupTimeline duration robustness", () => {
  const backupHistory = [
    { STATUS: "Success", START_TIMESTAMP: "2024-01-01 10:00:00", END_TIMESTAMP: "2024-01-01 10:01:00" }, // 60s
    { STATUS: "Success", START_TIMESTAMP: "2024-01-01 12:00:30", END_TIMESTAMP: "2024-01-01 12:00:00" }, // end<start -> dropped
    { STATUS: "Failed", START_TIMESTAMP: "N/A", END_TIMESTAMP: "N/A" }, // malformed, no elapsed -> dropped
    { STATUS: "Success", START_TIMESTAMP: "unknown", END_TIMESTAMP: "unknown", ELAPSED_TIME_S: "45" }, // fallback -> 45s
    { STATUS: "Success", START_TIMESTAMP: "2024-01-01 09:00:00", END_TIMESTAMP: "2024-01-01 09:00:00" }, // 0s
  ];

  it("drops NaN/negative durations and keeps stats finite", () => {
    render(<BackupTimeline backupHistory={backupHistory} backupSummary={{}} />);
    // 5 raw rows -> only 3 valid durations (60, 45, 0); the negative and the
    // malformed-without-elapsed rows are excluded.
    expect(screen.getByText(/3 total backups/)).toBeInTheDocument();
    // Avg = (60 + 45 + 0) / 3 = 35s (was "—" when NaN leaked in).
    expect(screen.getByText("35s")).toBeInTheDocument();
  });

  it("uses ELAPSED_TIME_S when timestamps are unparseable", () => {
    render(
      <BackupTimeline
        backupHistory={[
          { STATUS: "Success", START_TIMESTAMP: "bad", END_TIMESTAMP: "bad", ELAPSED_TIME_S: "45" },
        ]}
        backupSummary={{}}
      />
    );
    expect(screen.getByText(/1 total backups/)).toBeInTheDocument();
    // With one 45s backup, Avg/Min/Max/P95 all render "45s".
    expect(screen.getAllByText("45s").length).toBeGreaterThan(0);
  });

  it("shows empty state when there is no backup history", () => {
    render(<BackupTimeline backupHistory={[]} backupSummary={{}} />);
    expect(screen.getByText(/No backup history found/)).toBeInTheDocument();
  });

  it("unwraps legacy { rows: [...] } wrapper without crashing", () => {
    render(
      <BackupTimeline
        backupHistory={{
          rows: [
            {
              STATUS: "Success",
              START_TIMESTAMP: "2024-01-01 10:00:00",
              END_TIMESTAMP: "2024-01-01 10:01:00",
            },
          ],
        }}
        backupSummary={{}}
      />
    );
    expect(screen.getByText(/1 total backups/)).toBeInTheDocument();
  });
});
