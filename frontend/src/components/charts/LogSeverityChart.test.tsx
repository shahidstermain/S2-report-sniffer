import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LogSeverityChart from "./LogSeverityChart";

describe("LogSeverityChart", () => {
  it("reads nested severity_counts from log_summary", () => {
    render(
      <LogSeverityChart
        logSummary={{
          total: 120,
          severity_counts: { ERROR: 12, WARN: 30, INFO: 78 },
        }}
      />
    );
    expect(screen.getByText(/120 events/)).toBeInTheDocument();
    expect(screen.getByText(/ERROR/)).toBeInTheDocument();
  });

  it("shows empty state when no severity data", () => {
    render(<LogSeverityChart logSummary={{}} />);
    expect(screen.getByText(/No tracelog severity data available/)).toBeInTheDocument();
  });

  it("keeps unrecognized severities instead of silently dropping them", () => {
    render(
      <LogSeverityChart
        logSummary={{
          severity_counts: { ERROR: 10, INFO: 40, EMERGENCY: 50 },
        }}
      />
    );
    // The unusual "EMERGENCY" level must still be counted in the total (100),
    // not dropped like the old fixed allow-list did (which would show 50).
    // (Recharts legend text isn't rendered in jsdom, so the total is the
    // observable proof the severity survived bucketing.)
    expect(screen.getByText(/100 events/)).toBeInTheDocument();
  });

  it("folds aliases (warning->warn, fatal->critical) into one total", () => {
    render(
      <LogSeverityChart
        logSummary={{
          severity_counts: { WARN: 5, WARNING: 5, FATAL: 3, CRITICAL: 2 },
        }}
      />
    );
    // 5+5 warn + 3+2 critical = 15, with no double counting.
    expect(screen.getByText(/15 events/)).toBeInTheDocument();
  });

  it("ignores non-severity numeric fields in the fallback path", () => {
    // No nested severity_counts -> falls back to the whole object. The numeric
    // `total`/`parse_total` fields must not be summed into the severity total.
    render(
      <LogSeverityChart
        logSummary={{ total: 999, parse_total: 5000, ERROR: 4, INFO: 6 }}
      />
    );
    expect(screen.getByText(/10 events/)).toBeInTheDocument();
  });
});
