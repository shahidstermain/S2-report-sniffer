import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, Legend,
} from "recharts";
import InfoHint from "../InfoHint";

function barColor(pct) {
  if (pct == null || !Number.isFinite(pct)) return "#6B6B80";
  if (pct >= 90) return "#F44336";
  if (pct >= 80) return "#FF9800";
  return "#00d992";
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const formatPct = (value) => (value == null ? "—" : `${value}%`);
  return (
    <div
      className="text-xs px-3 py-2 rounded shadow-lg"
      style={{
        background: "var(--surface-elevated)",
        border: "1px solid var(--border-strong)",
        color: "var(--text-primary)",
        maxWidth: 260,
      }}
    >
      <div className="font-semibold mb-1">{row.hostname}</div>
      <div>OS memory used: <b>{formatPct(row.os_used_pct)}</b></div>
      <div>Engine memory used: <b>{formatPct(row.engine_used_pct)}</b></div>
      {row.swap_used_pct != null && row.swap_used_pct > 0 && <div>Swap used: <b>{row.swap_used_pct}%</b></div>}
    </div>
  );
}

function normalizePerNodeRows(memoryUtilization) {
  const perNode = memoryUtilization?.per_node;
  if (!perNode) return [];
  if (Array.isArray(perNode)) return perNode;
  if (typeof perNode === "object") {
    return Object.entries(perNode).map(([hostname, data]) => ({
      ...(data && typeof data === "object" ? data : {}),
      hostname,
    }));
  }
  return [];
}

function toPct(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function normalizeMemoryChartRows(memoryUtilization) {
  const nodes = normalizePerNodeRows(memoryUtilization);
  return nodes.map((node) => {
    const os_used_pct = toPct(node.os_used_pct);
    const engine_used_pct = toPct(node.engine_used_pct);
    return {
      ...node,
      label: node.hostname?.split(":")[0]?.slice(-18) || node.hostname,
      os_used_pct,
      engine_used_pct,
    };
  });
}

export default function MemoryUtilizationChart({ memoryUtilization, nodeCount }) {
  const data = useMemo(() => {
    return normalizeMemoryChartRows(memoryUtilization);
  }, [memoryUtilization]);

  const summary = memoryUtilization?.cluster_summary || {};
  const hotFromBackend = summary.nodes_over_80pct;
  const hotRecount = data.filter(
    (node) =>
      (node.os_used_pct != null && node.os_used_pct > 80) ||
      (node.engine_used_pct != null && node.engine_used_pct > 80),
  ).length;
  const hotCount = hotFromBackend ?? (hotRecount > 0 ? hotRecount : 0);
  const hotIsRecount = hotFromBackend == null && hotRecount > 0;
  const engineAvgRaw = summary.avg_engine_used_pct;
  const engineAvgPct = engineAvgRaw == null || !Number.isFinite(Number(engineAvgRaw))
    ? null
    : Number(engineAvgRaw);

  if (!data.length) {
    const emptyMessage = nodeCount === 0
      ? "This report has no parsed cluster nodes. Upload a full sdb-report bundle to see per-node memory metrics."
      : "No per-node memory metrics available in this bundle.";
    return (
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-3">Memory Utilization by Node</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {emptyMessage}
        </p>
      </div>
    );
  }

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-1">
            <h3 className="text-sm font-semibold">Memory Utilization by Node</h3>
            <InfoHint label="memory utilization chart" content="Per-node memory pressure at report collection time. Bars show OS memory usage and engine memory usage relative to maximum_memory as separate series." />
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            OS and engine memory percentages per node, shown as separate bars
          </p>
        </div>
        <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)" }}>
          engine avg <b>{engineAvgPct == null ? "—" : `${engineAvgPct}%`}</b>
          {hotCount > 0 && (
            <span style={{ color: "#FF9800" }}>
              {" "}· {hotCount} hot{hotIsRecount ? " (UI recount)" : ""}
            </span>
          )}
        </span>
      </div>

      <div style={{ height: Math.max(160, data.length * 28), width: "100%" }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, left: 4, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" horizontal={false} />
            <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="%" />
            <YAxis
              type="category"
              dataKey="label"
              width={90}
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="os_used_pct" name="OS %" radius={[0, 2, 2, 0]} maxBarSize={12}>
              {data.map((entry, i) => (
                <Cell key={`os-${entry.hostname || i}`} fill={barColor(entry.os_used_pct)} />
              ))}
            </Bar>
            <Bar dataKey="engine_used_pct" name="Engine %" radius={[0, 2, 2, 0]} maxBarSize={12}>
              {data.map((entry, i) => (
                <Cell key={`engine-${entry.hostname || i}`} fill={barColor(entry.engine_used_pct)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
