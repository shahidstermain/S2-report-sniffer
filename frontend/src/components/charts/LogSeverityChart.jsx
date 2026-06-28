import { useMemo } from "react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
} from "recharts";

const COLORS = {
  error: "#F44336",
  warn: "#FF9800",
  info: "#2196F3",
  debug: "#9E9E9E",
  critical: "#D32F2F",
  notice: "#4CAF50",
  trace: "#BDBDBD",
};

// `warning` aliases to `warn`; `fatal` aliases to `critical` — same color/bucket.
const SEVERITY_ALIASES = { warning: "warn", fatal: "critical" };

const SEVERITY_ORDER = ["critical", "fatal", "error", "warn", "warning", "notice", "info", "debug", "trace"];

const SEVERITY_MEANINGS = {
  critical: "Crash-level events — investigate immediately",
  error: "Operation failures — check recommendations panel",
  warn: "Degraded conditions — monitor for escalation",
  info: "Normal operational events",
  debug: "Verbose diagnostics — usually safe to ignore",
};

function severityColor(name) {
  const key = name.toLowerCase();
  return COLORS[SEVERITY_ALIASES[key] || key] || "#AA00FF";
}

function severityMeaning(name) {
  const key = name.toLowerCase();
  return SEVERITY_MEANINGS[SEVERITY_ALIASES[key] || key] || null;
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  const meaning = severityMeaning(p.name);
  return (
    <div
      className="text-xs px-3 py-2 rounded shadow-lg"
      style={{
        background: "var(--surface-elevated)",
        border: "1px solid var(--border-strong)",
        color: "var(--text-primary)",
        maxWidth: 240,
      }}
    >
      <div className="font-semibold mb-1" style={{ color: severityColor(p.name) }}>
        {p.name}
      </div>
      <div className="flex items-center gap-2">
        <span style={{ color: "var(--text-secondary)" }}>Count:</span>
        <span className="font-semibold">{p.value?.toLocaleString()}</span>
      </div>
      {p.total > 0 && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>Share:</span>
          <span className="font-semibold">{((p.value / p.total) * 100).toFixed(1)}%</span>
        </div>
      )}
      {meaning && (
        <div className="mt-1.5 pt-1.5" style={{ borderTop: "1px solid var(--border-default)", color: "var(--text-muted)" }}>
          {meaning}
        </div>
      )}
    </div>
  );
}

export default function LogSeverityChart({ logSummary }) {
  const chartData = useMemo(() => {
    if (!logSummary || Object.keys(logSummary).length === 0) return [];
    const total = Object.values(logSummary).reduce((a, b) => a + (typeof b === "number" ? b : 0), 0);
    // Fold aliases (e.g. `warning` -> `warn`) into a single bucket.
    const buckets = {};
    for (const key of SEVERITY_ORDER) {
      const val = logSummary[key] ?? logSummary[key.toUpperCase()] ?? 0;
      if (typeof val !== "number" || val <= 0) continue;
      const canonical = SEVERITY_ALIASES[key] || key;
      buckets[canonical] = (buckets[canonical] || 0) + val;
    }
    return Object.entries(buckets).map(([key, value]) => ({
      name: key.charAt(0).toUpperCase() + key.slice(1),
      value,
      total,
    }));
  }, [logSummary]);

  if (!chartData.length) {
    return (
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-3">📊 Log Severity</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No log severity data available.
        </p>
      </div>
    );
  }

  const total = chartData.reduce((a, b) => a + b.value, 0);
  const errorVal = chartData.find((d) => d.name === "Error")?.value || 0;
  const criticalVal = chartData.find((d) => d.name === "Critical")?.value || 0;
  const errorPctNum = total ? (errorVal / total) * 100 : 0;
  const errorPct = errorPctNum.toFixed(1);
  const warnPct = ((chartData.find((d) => d.name === "Warn")?.value || 0) / total * 100).toFixed(1);

  let riskBand = null;
  if (criticalVal > 0) {
    riskBand = { label: "CRITICAL", color: "#fff", bg: COLORS.critical };
  } else if (errorPctNum > 10) {
    riskBand = { label: "HIGH", color: "#fff", bg: COLORS.error };
  } else if (errorPctNum > 2) {
    riskBand = { label: "ELEVATED", color: "#1a1209", bg: COLORS.warn };
  }

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">📊 Log Severity Distribution</h3>
            {riskBand && (
              <span
                className="text-[10px] font-bold px-1.5 py-0.5 rounded tracking-wide"
                style={{ background: riskBand.bg, color: riskBand.color }}
              >
                {riskBand.label}
              </span>
            )}
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Ratio of log levels across all parsed logs
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <span className="tabular-nums" style={{ color: COLORS.error }}>
            ERROR {errorPct}%
          </span>
          <span className="tabular-nums" style={{ color: COLORS.warn }}>
            WARN {warnPct}%
          </span>
          <span
            className="text-[10px] font-medium px-1.5 py-0.5 rounded tabular-nums"
            style={{ background: "var(--surface-elevated)", border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          >
            {total?.toLocaleString()} events
          </span>
        </div>
      </div>

      <div style={{ height: 220, width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={85}
              paddingAngle={2}
              dataKey="value"
              nameKey="name"
              stroke="none"
            >
              {chartData.map((entry, i) => (
                <Cell key={i} fill={severityColor(entry.name)} />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: "11px" }}
              formatter={(value) => (
                <span style={{ color: "var(--text-primary)" }}>{value}</span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
