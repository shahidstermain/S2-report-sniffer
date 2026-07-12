import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  CartesianGrid, ReferenceLine,
} from "recharts";
import InfoHint from "../InfoHint";

const COLORS = {
  success: "#00C853",
  failure: "#F44336",
  grid: "var(--border-default)",
  axis: "var(--text-muted)",
};

function formatDuration(sec) {
  if (!sec && sec !== 0) return "—";
  if (sec < 60) return `${sec.toFixed(0)}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s.toFixed(0)}s`;
}

function formatTs(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts.replace(" ", "T") + "Z");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
      " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch {
    return ts.slice(0, 16);
  }
}

function formatRelative(sec) {
  if (sec === null || sec === undefined || sec < 0) return "—";
  if (sec < 45) return `${Math.round(sec)}s`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m`;
  const hrs = Math.round(min / 60);
  if (hrs < 24) {
    const remainingMin = min % 60;
    return remainingMin ? `${Math.floor(min / 60)}h ${remainingMin}m` : `${hrs}h`;
  }
  const days = Math.round(hrs / 24);
  const remainingHrs = hrs % 24;
  return remainingHrs ? `${Math.floor(hrs / 24)}d ${remainingHrs}h` : `${days}d`;
}

function CustomTooltip({ active, payload, label }) {
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
      <div className="font-semibold mb-1">{formatTs(p.ts)}</div>
      <div className="flex items-center gap-2">
        <span
          className="w-2 h-2 rounded-full"
          style={{ background: p.success ? COLORS.success : COLORS.failure }}
        />
        <span style={{ color: "var(--text-secondary)" }}>Duration:</span>
        <span className="font-semibold">{formatDuration(p.duration)}</span>
      </div>
      {p.sinceLast !== null && p.sinceLast !== undefined && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>Since last backup:</span>
          <span className="font-semibold">{formatRelative(p.sinceLast)}</span>
        </div>
      )}
      <div className="flex items-center gap-2 mt-1">
        <span style={{ color: "var(--text-secondary)" }}>Status:</span>
        <span className="font-semibold" style={{ color: p.success ? COLORS.success : COLORS.failure }}>
          {p.status || "unknown"}
        </span>
      </div>
      {p.host && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>Host:</span>
          <span className="font-semibold">{p.host}</span>
        </div>
      )}
      {p.role && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>Role:</span>
          <span className="font-semibold">{p.role}</span>
        </div>
      )}
    </div>
  );
}

export default function BackupTimeline({ backupHistory, backupSummary }) {
  const chartData = useMemo(() => {
    if (!backupHistory || backupHistory.length === 0) return [];
    const mapped = backupHistory
      .map((row) => {
        const status = String(row.STATUS || row.status || "").toLowerCase();
        const success = ["success", "completed"].includes(status);
        const start = row.START_TIMESTAMP || "";
        const end = row.END_TIMESTAMP || "";
        // Derive duration from timestamps only when BOTH parse to real dates and
        // end is not before start. `new Date()` returns an Invalid Date (NaN on
        // subtraction) rather than throwing, so a try/catch cannot guard this —
        // we must validate the parsed values explicitly.
        let duration = null;
        const dtS = start ? new Date(start.replace(" ", "T") + "Z").getTime() : NaN;
        const dtE = end ? new Date(end.replace(" ", "T") + "Z").getTime() : NaN;
        if (Number.isFinite(dtS) && Number.isFinite(dtE) && dtE >= dtS) {
          duration = (dtE - dtS) / 1000;
        }
        if (duration === null && row.ELAPSED_TIME_S != null) {
          const elapsed = parseFloat(row.ELAPSED_TIME_S);
          if (Number.isFinite(elapsed) && elapsed >= 0) duration = elapsed;
        }
        return {
          ts: end || start,
          duration: duration,
          success,
          status: row.STATUS || row.status || "unknown",
          host: row.HOST || row.Host || "",
          role: row.ROLE || row.Role || "",
        };
      });
    const rows = mapped
      .filter((d) => d.ts && Number.isFinite(d.duration))
      .sort((a, b) => new Date(a.ts) - new Date(b.ts))
      .slice(-50) // last 50 backups
      .map((d, i, arr) => {
        let sinceLast = null;
        if (i > 0) {
          const prev = new Date(arr[i - 1].ts.replace(" ", "T") + "Z");
          const cur = new Date(d.ts.replace(" ", "T") + "Z");
          const diff = (cur - prev) / 1000;
          if (!Number.isNaN(diff)) sinceLast = diff;
        }
        return { ...d, sinceLast };
      });
    return rows;
  }, [backupHistory]);

  const stats = useMemo(() => {
    if (!chartData.length) return null;
    const durations = chartData.map((d) => d.duration).filter((d) => d !== null);
    if (!durations.length) return null;
    const avg = durations.reduce((a, b) => a + b, 0) / durations.length;
    const min = Math.min(...durations);
    const max = Math.max(...durations);
    const sorted = [...durations].sort((a, b) => a - b);
    const p95Idx = Math.min(sorted.length - 1, Math.ceil(0.95 * sorted.length) - 1);
    const p95 = sorted[Math.max(0, p95Idx)];
    const successCount = chartData.filter((d) => d.success).length;
    const failureCount = chartData.length - successCount;
    const maxRatio = avg > 0 ? max / avg : 0;
    return {
      avg, min, max, p95, maxRatio,
      total: chartData.length,
      successCount,
      failureCount,
      failureRate: chartData.length ? (failureCount / chartData.length) * 100 : 0,
    };
  }, [chartData]);

  if (!backupHistory || backupHistory.length === 0) {
    return (
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-3">📦 Backup Timeline</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No backup history found in this report.
        </p>
      </div>
    );
  }

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-1">
            <h3 className="text-sm font-semibold">📦 Backup Timeline</h3>
            <InfoHint label="backup timeline" content="Backup jobs parsed from MV_BACKUP_HISTORY. Bar height represents duration; color indicates success or failure." />
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Backup job duration over time — longer bars indicate slower backup operations
          </p>
        </div>
        {stats && (
          <div className="flex items-center gap-3 text-[11px]">
            <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
              Avg: <b style={{ color: "var(--text-primary)" }}>{formatDuration(stats.avg)}</b>
            </span>
            <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
              Min: <b style={{ color: "var(--text-primary)" }}>{formatDuration(stats.min)}</b>
            </span>
            <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
              Max: <b style={{ color: stats.maxRatio >= 2 ? COLORS.failure : "var(--text-primary)" }}>{formatDuration(stats.max)}</b>
            </span>
            <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
              P95: <b style={{ color: (stats.avg > 0 && stats.p95 / stats.avg >= 2) ? COLORS.failure : "var(--text-primary)" }}>{formatDuration(stats.p95)}</b>
            </span>
          </div>
        )}
      </div>

      {/* Summary bar */}
      {stats && (
        <div className="flex items-center gap-4 mb-3 text-[11px]">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: COLORS.success }} />
            {stats.successCount} successful
          </span>
          {stats.failureCount > 0 && (
            <span className="flex items-center gap-1" style={{ color: COLORS.failure }}>
              <span className="w-2 h-2 rounded-full" style={{ background: COLORS.failure }} />
              <b>{stats.failureCount} failed</b>
            </span>
          )}
          <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
            {stats.total} total backups
          </span>
        </div>
      )}

      <div style={{ height: 220, width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
            <XAxis
              dataKey="ts"
              tickFormatter={(v) => formatTs(v).split(" ")[0]}
              tick={{ fontSize: 10, fill: COLORS.axis }}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v) => formatDuration(v)}
              tick={{ fontSize: 10, fill: COLORS.axis }}
              width={50}
            />
            <Tooltip content={<CustomTooltip />} />
            {stats && stats.avg > 0 && (
              <ReferenceLine
                y={stats.avg * 2}
                stroke={COLORS.failure}
                strokeDasharray="4 4"
                strokeOpacity={0.8}
                label={{
                  value: `2× avg (${formatDuration(stats.avg * 2)})`,
                  position: "insideTopRight",
                  fill: COLORS.failure,
                  fontSize: 10,
                }}
              />
            )}
            <Bar dataKey="duration" radius={[3, 3, 0, 0]} name="Duration">
              {chartData.map((entry, i) => (
                <Cell key={i} fill={entry.success ? COLORS.success : COLORS.failure} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {stats && (stats.failureCount > 0 || stats.maxRatio > 3) && (
        <div
          className="mt-2 text-[11px] rounded px-2 py-1"
          style={{
            background: "rgba(244, 67, 54, 0.1)",
            border: "1px solid rgba(244, 67, 54, 0.35)",
            color: "var(--text-secondary)",
          }}
        >
          {stats.failureCount > 0
            ? `⚠️ ${stats.failureCount} failure${stats.failureCount > 1 ? "s" : ""} detected (${stats.failureRate.toFixed(0)}%) — check for disk pressure or network timeouts on the leaf nodes during backup windows.`
            : `⚠️ Backup duration variance is high — max is ${stats.maxRatio.toFixed(1)}× avg, suggesting intermittent resource contention on a leaf node.`}
        </div>
      )}
    </div>
  );
}
