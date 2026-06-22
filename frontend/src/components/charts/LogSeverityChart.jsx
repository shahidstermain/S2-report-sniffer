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

const SEVERITY_ORDER = ["critical", "error", "warn", "warning", "notice", "info", "debug", "trace"];

function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div
      className="text-xs px-3 py-2 rounded shadow-lg"
      style={{
        background: "var(--surface-elevated)",
        border: "1px solid var(--border-strong)",
        color: "var(--text-primary)",
      }}
    >
      <div className="font-semibold mb-1" style={{ color: COLORS[p.name.toLowerCase()] || "var(--text-primary)" }}>
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
    </div>
  );
}

export default function LogSeverityChart({ logSummary }) {
  const chartData = useMemo(() => {
    if (!logSummary || Object.keys(logSummary).length === 0) return [];
    const severityCounts = logSummary.severity_counts || logSummary;
    const total = typeof logSummary.total === "number"
      ? logSummary.total
      : Object.values(severityCounts).reduce((a, b) => a + (typeof b === "number" ? b : 0), 0);
    return SEVERITY_ORDER
      .filter((key) => {
        const val = severityCounts[key] || severityCounts[key.toUpperCase()] || 0;
        return typeof val === "number" && val > 0;
      })
      .map((key) => ({
        name: key.charAt(0).toUpperCase() + key.slice(1),
        value: severityCounts[key] || severityCounts[key.toUpperCase()] || 0,
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
  const errorPct = ((chartData.find((d) => d.name === "Error")?.value || 0) / total * 100).toFixed(1);
  const warnPct = ((chartData.find((d) => d.name === "Warn")?.value || 0) / total * 100).toFixed(1);

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold">📊 Log Severity Distribution</h3>
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
          <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
            {total?.toLocaleString()} total
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
                <Cell key={i} fill={COLORS[entry.name.toLowerCase()] || "#AA00FF"} />
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
