import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import InfoHint from "../InfoHint";

const COLORS = {
  etimedout: "#F44336",
  fsync_behind: "#FF9800",
  retry_stall: "#9C27B0",
  async_transition: "#2196F3",
  grid: "var(--border-default)",
  axis: "var(--text-muted)",
};

const MEANING_MAP = {
  etimedout: "Connection timeout to a remote node or storage — often signals disk I/O saturation or network loss",
  fsync_behind: "Redo log flush is falling behind — disk cannot absorb write throughput",
  retry_stall: "Transaction is stuck in a retry loop — check for lock contention or a slow leaf node",
  async_transition: "Database replication transitioned from sync to async — elevated RPO / lag risk",
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
        maxWidth: 280,
      }}
    >
      <div className="font-semibold mb-1">{label}</div>
      {payload.map((p) => (
        p.value > 0 && (
          <div key={p.dataKey} className="mb-1 last:mb-0">
            <div className="flex items-center gap-2 tabular-nums">
              <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
              <span style={{ color: "var(--text-secondary)" }}>{p.name}:</span>
              <span className="font-semibold">{p.value}</span>
            </div>
            {MEANING_MAP[p.dataKey] && (
              <div className="text-[10px] ml-4" style={{ color: "var(--text-muted)" }}>
                {MEANING_MAP[p.dataKey]}
              </div>
            )}
          </div>
        )
      ))}
    </div>
  );
}

const LABEL_MAP = {
  etimedout: "Network Timeout (ETIMEDOUT)",
  fsync_behind: "Redo Log Flush Delay (fsync)",
  retry_stall: "Write Retry Stall",
  async_transition: "Async Replication Transition",
};

function parseHourBucket(hour) {
  const match = String(hour).trim().match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2})$/);
  if (!match) return null;
  const [, year, month, day, hh] = match;
  return Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hh));
}

function formatHourBucket(timestamp) {
  const date = new Date(timestamp);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hour = String(date.getUTCHours()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}`;
}

export function buildPressureChartData(pressureEvents) {
  if (!pressureEvents || Object.keys(pressureEvents).length === 0) return [];

  const hourSet = new Set();
  for (const events of Object.values(pressureEvents)) {
    for (const hour of Object.keys(events)) {
      hourSet.add(hour);
    }
  }

  const parsedHours = [...hourSet]
    .map((hour) => ({ hour, timestamp: parseHourBucket(hour) }))
    .filter((entry) => entry.timestamp != null)
    .sort((a, b) => a.timestamp - b.timestamp);

  if (!parsedHours.length) return [];

  const filledHours = [];
  for (let ts = parsedHours[0].timestamp; ts <= parsedHours[parsedHours.length - 1].timestamp; ts += 3600 * 1000) {
    filledHours.push(formatHourBucket(ts));
  }

  const multiDay = filledHours.length > 24;
  return filledHours.map((hour) => {
    const hh = hour.slice(11, 13);
    const mmdd = hour.slice(5, 10).replace("-", "/");
    const label = multiDay ? `${mmdd} ${hh}` : `${hh}:00`;
    const entry = { hour: label, _raw: hour };
    for (const [key, hours] of Object.entries(pressureEvents)) {
      entry[key] = hours?.[hour] ?? 0;
    }
    return entry;
  });
}

export default function PressureEventsChart({ pressureEvents }) {
  const chartData = useMemo(() => buildPressureChartData(pressureEvents), [pressureEvents]);

  // Find the single biggest pressure spike (any one type in one hour) for the callout.
  const peak = useMemo(() => {
    let best = null;
    for (const row of chartData) {
      for (const key of Object.keys(LABEL_MAP)) {
        const v = row[key] || 0;
        if (v > 10 && (!best || v > best.count)) {
          best = { count: v, type: LABEL_MAP[key] || key, label: row.hour };
        }
      }
    }
    return best;
  }, [chartData]);

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
        <h3 className="text-sm font-semibold mb-3">⚡ Storage Stress Events</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No write stalls or network timeouts detected in tracelogs.
        </p>
      </div>
    );
  }

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-1">
            <h3 className="text-sm font-semibold">⚡ Storage Stress Events</h3>
            <InfoHint label="storage stress events" content="Hourly matching-line counts for network timeouts, delayed fsync, retry stalls, and explicit sync-to-async transitions. Repeated log lines may represent one incident." />
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Write stalls and network timeouts per hour — spikes indicate disk or node pressure
          </p>
        </div>
        <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)" }}>
          <b
            style={{
              color: totalEvents > 100 ? COLORS.etimedout
                : totalEvents > 10 ? COLORS.fsync_behind
                : "var(--text-muted)",
            }}
          >
            {totalEvents?.toLocaleString()}
          </b> total events
        </span>
      </div>

      <div style={{ height: 200, width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
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
                <Bar
                  key={key}
                  dataKey={key}
                  stackId="1"
                  fill={COLORS[key]}
                  name={LABEL_MAP[key] || key}
                />
              ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {peak && (
        <div
          className="mt-2 text-[11px] rounded px-2 py-1"
          style={{
            background: "rgba(244, 67, 54, 0.1)",
            border: "1px solid rgba(244, 67, 54, 0.35)",
            color: "var(--text-secondary)",
          }}
        >
          ⚠️ Peak stress at {peak.label} — {peak.count} {peak.type} events in one hour. Correlate with SingleStore tracelog errors and disk I/O metrics at this time.
        </div>
      )}
    </div>
  );
}
