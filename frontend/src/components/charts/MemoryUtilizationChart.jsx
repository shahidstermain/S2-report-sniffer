import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell,
} from "recharts";
import InfoHint from "../InfoHint";

function barColor(pct) {
  if (pct >= 95) return "#F44336";
  if (pct >= 85) return "#FF9800";
  if (pct >= 70) return "#FFC107";
  return "#00d992";
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
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
      <div>OS memory used: <b>{row.os_used_pct}%</b></div>
      {row.memsqld_rss_mb > 0 && (
        <div>memsqld RSS: <b>{row.memsqld_rss_mb} MB</b>
          {row.memsqld_pct_of_max > 0 && ` (${row.memsqld_pct_of_max}% of max)`}
        </div>
      )}
      {row.load_1m > 0 && <div>Load (1m): <b>{row.load_1m}</b></div>}
      {row.swap_used_pct > 0 && <div>Swap used: <b>{row.swap_used_pct}%</b></div>}
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

function nodeDisplayPct(node) {
  return Math.max(
    node.os_used_pct || 0,
    node.memsqld_pct_of_max || node.engine_used_pct || 0,
  );
}

export default function MemoryUtilizationChart({ memoryUtilization }) {
  const data = useMemo(() => {
    const nodes = normalizePerNodeRows(memoryUtilization);
    return nodes.map((n) => ({
      ...n,
      label: n.hostname?.split(":")[0]?.slice(-18) || n.hostname,
      display_pct: nodeDisplayPct(n),
      memsqld_pct_of_max: n.memsqld_pct_of_max ?? n.engine_used_pct ?? 0,
    }));
  }, [memoryUtilization]);

  const summary = memoryUtilization?.cluster_summary || {};
  const hotCount = memoryUtilization?.hot_node_count
    ?? ((summary.nodes_over_90pct || 0) + (summary.nodes_over_80pct || 0));
  const avgPct = memoryUtilization?.cluster_avg_used_pct
    ?? summary.avg_engine_used_pct
    ?? 0;

  if (!data.length) {
    return (
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-3">Memory Utilization by Node</h3>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          No per-node memory metrics available in this bundle.
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
            <InfoHint label="memory utilization chart" content="Per-node memory pressure at report collection time. Each bar uses the higher of OS utilization or memsqld usage relative to maximum_memory." />
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            OS memory use per node — bar height reflects worst of OS % or memsqld vs maximum_memory
          </p>
        </div>
        <span className="text-[11px] tabular-nums" style={{ color: "var(--text-muted)" }}>
          avg <b>{avgPct}%</b>
          {hotCount > 0 && (
            <span style={{ color: "#FF9800" }}> · {hotCount} hot</span>
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
            <Bar dataKey="display_pct" name="Memory %" radius={[0, 2, 2, 0]} maxBarSize={18}>
              {data.map((entry, i) => (
                <Cell key={entry.hostname || i} fill={barColor(entry.display_pct)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
