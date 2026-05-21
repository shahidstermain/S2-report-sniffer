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
        <span style={{ color: "var(--text-secondary)" }}>Nodes:</span>
        <span className="font-semibold">{p.value}</span>
      </div>
      {p.total > 0 && (
        <div className="flex items-center gap-2 mt-1">
          <span style={{ color: "var(--text-secondary)" }}>Share:</span>
          <span className="font-semibold">{((p.value / p.total) * 100).toFixed(0)}%</span>
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
        <h3 className="text-sm font-semibold mb-3">🖥️ Node Health</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No node data available.
        </p>
      </div>
    );
  }

  const total = chartData.reduce((a, b) => a + b.value, 0);
  const onlineCount = chartData.find((d) => d.name === "Online")?.value || 0;
  const offlineCount = chartData.find((d) => d.name === "Offline")?.value || 0;

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold">🖥️ Node Health</h3>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Distribution of node states in the cluster
          </p>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
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
        </div>
      </div>

      <div style={{ height: 200, width: "100%" }}>
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
    </div>
  );
}
