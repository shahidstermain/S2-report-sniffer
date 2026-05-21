import { useMemo } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";

const COLORS = {
  etimedout: "#F44336",
  fsync_behind: "#FF9800",
  retry_stall: "#9C27B0",
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
      <div className="font-semibold mb-1">{label}:00</div>
      {payload.map((p) => (
        p.value > 0 && (
          <div key={p.dataKey} className="flex items-center gap-2 tabular-nums">
            <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
            <span style={{ color: "var(--text-secondary)" }}>{p.name}:</span>
            <span className="font-semibold">{p.value}</span>
          </div>
        )
      ))}
    </div>
  );
}

const LABEL_MAP = {
  etimedout: "ETIMEDOUT",
  fsync_behind: "FSYNC behind",
  retry_stall: "Retry stall",
};

export default function PressureEventsChart({ pressureEvents }) {
  const chartData = useMemo(() => {
    if (!pressureEvents || Object.keys(pressureEvents).length === 0) return [];
    // Collect all hour buckets
    const allHours = new Set();
    for (const events of Object.values(pressureEvents)) {
      for (const hour of Object.keys(events)) {
        allHours.add(hour);
      }
    }
    const sortedHours = [...allHours].sort();
    return sortedHours.map((hour) => {
      const entry = { hour: hour.slice(11, 13) + ":00" }; // just the hour part
      for (const [key, hours] of Object.entries(pressureEvents)) {
        entry[key] = hours[hour] || 0;
      }
      return entry;
    });
  }, [pressureEvents]);

  const totalEvents = useMemo(() => {
    if (!pressureEvents) return 0;
    let total = 0;
    for (const hours of Object.values(pressureEvents)) {
      for (const count of Object.values(hours)) {
        total += count;
      }
    }
    return total;
  }, [pressureEvents]);

  if (!chartData.length || totalEvents === 0) {
    return (
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-3">⚡ Pressure Events</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No pressure events (ETIMEDOUT, FSYNC behind, retry stalls) detected.
        </p>
      </div>
    );
  }

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold">⚡ Pressure Events Timeline</h3>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            I/O pressure events per hour — spikes indicate storage stress
          </p>
        </div>
        <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)" }}>
          <b style={{ color: COLORS.etimedout }}>{totalEvents?.toLocaleString()}</b> total events
        </span>
      </div>

      <div style={{ height: 200, width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
            <XAxis
              dataKey="hour"
              tick={{ fontSize: 10, fill: COLORS.axis }}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 10, fill: COLORS.axis }}
              allowDecimals={false}
              width={30}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: "11px" }}
              formatter={(value) => (
                <span style={{ color: "var(--text-primary)" }}>{LABEL_MAP[value] || value}</span>
              )}
            />
            {Object.keys(COLORS)
              .filter((k) => k !== "grid" && k !== "axis")
              .map((key) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stackId="1"
                  stroke={COLORS[key]}
                  fill={COLORS[key]}
                  fillOpacity={0.3}
                  name={LABEL_MAP[key] || key}
                />
              ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
