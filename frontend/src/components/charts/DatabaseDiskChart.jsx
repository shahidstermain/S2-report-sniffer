import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid, LabelList,
} from "recharts";
import InfoHint from "../InfoHint";
import { asRowList } from "@/lib/utils";

const COLORS = {
  bar: "#AA00FF",
  barHover: "#D199FF",
  grid: "var(--border-default)",
  axis: "var(--text-muted)",
};

// Percentage-of-total drives the color: a database eating a large share of
// database storage in the report is what an engineer needs to spot, regardless of rank.
function colorForPct(pct) {
  if (pct > 40) return "#F44336"; // red
  if (pct > 20) return "#FF9800"; // orange
  if (pct > 10) return "#FFC107"; // amber
  return "#AA00FF"; // purple
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let val = parseFloat(bytes);
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

function diskName(row) {
  return row.DATABASE_NAME || row.Database || row.database || row.DB || "unknown";
}

function diskBytes(row) {
  const gb = parseFloat(row.TOTAL_DISK_USAGE_GB || row.total_disk_usage_gb || 0);
  if (!Number.isNaN(gb) && gb > 0) return gb * 1024 ** 3;
  return parseFloat(row._disk_bytes || row.disk_bytes || row.DataSize || row.size || 0);
}

export function buildDatabaseDiskChartData(usageRows) {
  const rows = usageRows
    .map((row) => {
      const name = diskName(row);
      const bytes = diskBytes(row);
      return {
        name,
        Database: name,
        _bytes: bytes,
        Partitions: row.Partitions || row.partitions || "",
      };
    })
    .filter((row) => row._bytes > 0)
    .sort((a, b) => b._bytes - a._bytes);

  const totalBytes = rows.reduce((sum, row) => sum + row._bytes, 0);
  const chartData = rows.slice(0, 15).map((row) => ({
    ...row,
    _pct: totalBytes > 0 ? (row._bytes / totalBytes) * 100 : 0,
  }));

  return { chartData, totalBytes };
}

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
      <div className="font-semibold mb-1">{p.Database || p.database || p.name}</div>
      <div className="flex items-center gap-2">
        <span style={{ color: "var(--text-secondary)" }}>Storage used:</span>
        <span className="font-semibold">{formatBytes(p._bytes)}</span>
      </div>
      {p._pct !== undefined && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>% of database storage in report:</span>
          <span className="font-semibold">{p._pct.toFixed(1)}%</span>
        </div>
      )}
      {p.Partitions && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>Partitions:</span>
          <span className="font-semibold">{p.Partitions}</span>
        </div>
      )}
    </div>
  );
}

export default function DatabaseDiskChart({ databaseDiskUsage }) {
  const usageRows = asRowList(databaseDiskUsage);

  const { chartData, totalBytes } = useMemo(() => {
    if (!usageRows.length) return { chartData: [], totalBytes: 0 };
    return buildDatabaseDiskChartData(usageRows);
  }, [usageRows]);

  if (!chartData.length) {
    return (
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-3">💾 Database Storage</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No database storage data available.
        </p>
      </div>
    );
  }

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-1">
            <h3 className="text-sm font-semibold">💾 Database Storage</h3>
            <InfoHint label="database storage chart" content="Top databases by parsed disk footprint. Bar color reflects each database's share of total database storage in the report." />
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Top 15 databases by disk footprint on the cluster
          </p>
        </div>
        <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)" }}>
          Total: <b style={{ color: "var(--text-primary)" }}>{formatBytes(totalBytes)}</b>
        </span>
      </div>

      <div style={{ height: Math.max(250, chartData.length * 28), width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 5, right: 30, left: 120, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} horizontal={false} />
            <XAxis
              type="number"
              tickFormatter={(v) => formatBytes(v)}
              tick={{ fontSize: 10, fill: COLORS.axis }}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 10, fill: "var(--text-primary)" }}
              width={110}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: "var(--border-default)", fillOpacity: 0.2 }} />
            <Bar dataKey="_bytes" name="Disk Usage" radius={[0, 3, 3, 0]} barSize={18}>
              {chartData.map((entry, i) => (
                <Cell key={i} fill={colorForPct(entry._pct)} />
              ))}
              <LabelList
                dataKey="_pct"
                position="right"
                formatter={(v) => `${Number(v).toFixed(0)}%`}
                style={{ fontSize: 10, fill: "var(--text-secondary)" }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {chartData.length > 0 && chartData[0]._pct > 50 && (
        <div
          className="mt-2 text-[11px] rounded px-2 py-1"
          style={{
            background: "rgba(244, 67, 54, 0.1)",
            border: "1px solid rgba(244, 67, 54, 0.35)",
            color: "var(--text-secondary)",
          }}
        >
          ⚠️ {chartData[0].name} accounts for {chartData[0]._pct.toFixed(0)}% of database storage in report — monitor for storage exhaustion on the leaf nodes.
        </div>
      )}
    </div>
  );
}
