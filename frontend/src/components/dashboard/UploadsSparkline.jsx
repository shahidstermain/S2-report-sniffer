import { useMemo } from "react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from "recharts";

const COLORS = {
  total: "#AA00FF",
  critical: "#F44336",
  warning: "#FF9800",
  healthy: "#00C853",
  grid: "var(--border-default)",
  axis: "var(--text-muted)",
};

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div
      className="text-xs px-3 py-2 rounded shadow-lg"
      style={{
        background: "var(--surface-elevated)",
        border: "1px solid var(--border-strong)",
        color: "var(--text-primary)",
      }}
    >
      <div className="font-semibold mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2 tabular-nums">
          <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span style={{ color: "var(--text-secondary)" }}>{p.name || p.dataKey}:</span>
          <span className="font-semibold">{p.value}</span>
        </div>
      ))}
    </div>
  );
}

const RANGES = [
  { id: "7d", label: "7d", days: 7 },
  { id: "14d", label: "14d", days: 14 },
  { id: "30d", label: "30d", days: 30 },
];

export default function UploadsSparkline({ data, range, onRangeChange, mode = "stacked", onModeChange }) {
  const totals = useMemo(() => {
    let total = 0, critical = 0, warning = 0, healthy = 0;
    for (const d of data) {
      total += d.count;
      critical += d.critical;
      warning += d.warning;
      healthy += d.healthy;
    }
    return { total, critical, warning, healthy };
  }, [data]);

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            Uploads over time
          </h3>
          <p className="text-[11px] mt-0.5 tabular-nums" style={{ color: "var(--text-muted)" }}>
            <span className="font-semibold" style={{ color: "var(--text-primary)" }}>{totals.total}</span> reports ·{" "}
            <span style={{ color: COLORS.critical }}>{totals.critical} critical</span> ·{" "}
            <span style={{ color: COLORS.warning }}>{totals.warning} warning</span> ·{" "}
            <span style={{ color: COLORS.healthy }}>{totals.healthy} healthy</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            {["area", "stacked"].map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => onModeChange && onModeChange(m)}
                className={`chip ${mode === m ? "active" : ""}`}
                data-testid={`chart-mode-${m}`}
              >
                {m === "area" ? "Total" : "Stacked"}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            {RANGES.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => onRangeChange && onRangeChange(r.id)}
                className={`chip ${range === r.id ? "active" : ""}`}
                data-testid={`chart-range-${r.id}`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div style={{ width: "100%", height: 200 }}>
        <ResponsiveContainer>
          {mode === "area" ? (
            <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <defs>
                <linearGradient id="sparkTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLORS.total} stopOpacity={0.45} />
                  <stop offset="100%" stopColor={COLORS.total} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--text-muted)" }} stroke={COLORS.grid} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "var(--text-muted)" }} stroke={COLORS.grid} width={28} />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="count" name="Total" stroke={COLORS.total} fill="url(#sparkTotal)" strokeWidth={2} />
            </AreaChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--text-muted)" }} stroke={COLORS.grid} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "var(--text-muted)" }} stroke={COLORS.grid} width={28} />
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="healthy" stackId="h" fill={COLORS.healthy} name="Healthy" radius={[0, 0, 0, 0]} />
              <Bar dataKey="warning" stackId="h" fill={COLORS.warning} name="Warning" />
              <Bar dataKey="critical" stackId="h" fill={COLORS.critical} name="Critical" radius={[3, 3, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
