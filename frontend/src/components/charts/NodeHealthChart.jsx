import { useMemo } from "react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
} from "recharts";

const COLORS = {
  online: "#00C853",
  offline: "#F44336",
  degraded: "#FF9800",
  recovering: "#2196F3",
  unknown: "#9E9E9E",
};

const STATE_MEANINGS = {
  online: "Node is active and serving queries",
  offline: "Node is unreachable — check the Recommendations tab for steps to bring it back online",
  degraded: "Node is running but impaired — review tracelog errors and disk usage on this node",
  recovering: "Node is rebuilding partition replicas — query performance may be reduced until recovery completes",
  unknown: "State could not be determined from the report snapshot",
};

function CustomTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  const meaning = STATE_MEANINGS[p.name.toLowerCase()];
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
      <div className="font-semibold mb-1" style={{ color: COLORS[p.name.toLowerCase()] || "var(--text-primary)" }}>
        {p.name}
      </div>
      <div className="flex items-center gap-2">
        <span style={{ color: "var(--text-secondary)" }}>Nodes:</span>
        <span className="font-semibold">{p.value}</span>
      </div>
      {p.total > 0 && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>Share:</span>
          <span className="font-semibold">{((p.value / p.total) * 100).toFixed(0)}%</span>
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

export default function NodeHealthChart({ clusterOverview }) {
  const chartData = useMemo(() => {
    if (!clusterOverview?.nodes_detail || clusterOverview.nodes_detail.length === 0) return [];
    const total = clusterOverview.nodes_detail.length;
    const counts = {};
    for (const node of clusterOverview.nodes_detail) {
      const state = (node.state || node.status || "unknown").toLowerCase();
      const label = state === "online" ? "Online"
        : state === "offline" ? "Offline"
        : state === "degraded" || state === "deactivating" ? "Degraded"
        : state === "recovering" || state === "recovery" ? "Recovering"
        : state.charAt(0).toUpperCase() + state.slice(1);
      counts[label] = (counts[label] || 0) + 1;
    }
    return Object.entries(counts).map(([name, value]) => ({
      name,
      value,
      total,
    }));
  }, [clusterOverview]);

  if (!chartData.length) {
    return (
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-3">🖥️ Node Status</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No node data available.
        </p>
      </div>
    );
  }

  const total = chartData.reduce((a, b) => a + b.value, 0);
  const onlineCount = chartData.find((d) => d.name === "Online")?.value || 0;
  const offlineCount = chartData.find((d) => d.name === "Offline")?.value || 0;
  const degradedCount = chartData.find((d) => d.name === "Degraded")?.value || 0;
  const recoveringCount = chartData.find((d) => d.name === "Recovering")?.value || 0;
  // Any state that isn't a recognized health state counts as "unknown".
  const unknownCount = chartData
    .filter((d) => !["Online", "Offline", "Degraded", "Recovering"].includes(d.name))
    .reduce((a, b) => a + b.value, 0);

  // Cluster health summary badge (priority: offline > degraded/recovering > unknown > healthy)
  let healthBadge;
  if (offlineCount > 0) {
    healthBadge = { label: "DEGRADED", color: "#fff", bg: COLORS.offline };
  } else if (degradedCount > 0 || recoveringCount > 0) {
    healthBadge = { label: "DEGRADED", color: "#1a1209", bg: COLORS.degraded };
  } else if (unknownCount > 0) {
    healthBadge = { label: "UNKNOWN", color: "#fff", bg: COLORS.unknown };
  } else {
    healthBadge = { label: "HEALTHY", color: "#04140d", bg: COLORS.online };
  }

  const impairedCount = offlineCount + degradedCount;

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold">🖥️ Node Status</h3>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Current state of each node in the SingleStore cluster
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="tabular-nums" style={{ color: COLORS.online }}>
            {onlineCount} online
          </span>
          {offlineCount > 0 && (
            <span className="tabular-nums" style={{ color: COLORS.offline }}>
              {offlineCount} offline
            </span>
          )}
          <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
            {total} total
          </span>
          <span
            className="text-[10px] font-bold px-1.5 py-0.5 rounded tracking-wide"
            style={{ background: healthBadge.bg, color: healthBadge.color }}
          >
            {healthBadge.label}
          </span>
        </div>
      </div>

      <div style={{ height: 200, width: "100%", position: "relative" }}>
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
          }}
        >
          <span
            className="font-semibold tabular-nums"
            style={{ fontSize: 18, color: onlineCount === total ? COLORS.online : "var(--text-primary)" }}
          >
            {onlineCount}/{total}
          </span>
          <span className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
            online
          </span>
        </div>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={45}
              outerRadius={75}
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

      {impairedCount > 0 && (
        <div
          className="mt-2 text-[11px] rounded px-2 py-1"
          style={{
            background: "rgba(244, 67, 54, 0.1)",
            border: "1px solid rgba(244, 67, 54, 0.35)",
            color: "var(--text-secondary)",
          }}
        >
          ⚠️ {impairedCount} node{impairedCount > 1 ? "s" : ""} {offlineCount > 0 ? "offline" : "degraded"} — cluster may be unable to serve all queries. Review the Recommendations tab for next steps.
        </div>
      )}
    </div>
  );
}
