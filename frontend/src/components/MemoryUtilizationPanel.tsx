import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/lib/utils-sdb";
import InfoHint from "./InfoHint";

/**
 * Per-node Memory Utilization Panel
 * Shows engine memory, OS memory, swap usage, and table vs non-table memory.
 */

interface NodeMemData {
  engine_used_mb: number;
  engine_max_mb: number;
  engine_used_pct: number;
  table_memory_mb: number;
  non_table_memory_mb: number;
  os_total_mb: number;
  os_used_mb: number;
  os_available_mb: number;
  os_used_pct: number;
  swap_total_mb: number;
  swap_used_mb: number;
  swap_used_pct: number;
  status: "healthy" | "warning" | "critical";
}

interface MemoryUtilizationPanelProps {
  memoryUtilization?: {
    per_node?: Record<string, NodeMemData>;
    cluster_summary?: {
      total_engine_memory_mb: number;
      total_used_engine_mb: number;
      avg_engine_used_pct: number;
      total_os_memory_mb: number;
      total_os_used_mb: number;
      nodes_over_80pct: number;
      nodes_over_90pct: number;
      highest_utilization_node: string;
      highest_utilization_pct: number;
    };
  };
}

const STATUS_COLORS: Record<string, string> = {
  healthy: "#00C853",
  warning: "#FF9800",
  critical: "#F44336",
};

export default function MemoryUtilizationPanel({ memoryUtilization }: MemoryUtilizationPanelProps) {
  if (!memoryUtilization?.per_node || Object.keys(memoryUtilization.per_node).length === 0) {
    return null;
  }

  const summary = memoryUtilization.cluster_summary || {
    total_engine_memory_mb: 0,
    total_used_engine_mb: 0,
    avg_engine_used_pct: 0,
    total_os_memory_mb: 0,
    total_os_used_mb: 0,
    nodes_over_80pct: 0,
    nodes_over_90pct: 0,
    highest_utilization_node: "",
    highest_utilization_pct: 0,
  };
  const perNode = memoryUtilization.per_node;
  const nodeEntries = Object.entries(perNode);
  const hasIssues = summary.nodes_over_80pct > 0 || summary.nodes_over_90pct > 0 ||
    nodeEntries.some(([, d]) => d.swap_used_pct > 25);

  if (!hasIssues) return null;

  return (
    <Card className="shadow-sm">
      <CardHeader className="border-b py-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="flex items-center gap-1">
              <CardTitle className="text-sm font-bold tracking-tight">Memory Utilization</CardTitle>
              <InfoHint
                label="memory utilization analysis"
                content="Per-node engine, operating-system, swap, table, and working-set memory captured in the report snapshot."
              />
            </div>
            <CardDescription>
              Avg engine: {summary.avg_engine_used_pct || 0}% ·
              Highest: {summary.highest_utilization_pct || 0}% on {summary.highest_utilization_node || "—"}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {summary.nodes_over_90pct > 0 && (
              <Badge variant="critical">{summary.nodes_over_90pct} over 90%</Badge>
            )}
            {summary.nodes_over_80pct > 0 && (
              <Badge variant="warning">{summary.nodes_over_80pct} over 80%</Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-border">
          {nodeEntries.map(([hostname, data]) => (
            <div key={hostname} className="px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono font-bold">{hostname}</span>
                <Badge
                  variant={data.status === "critical" ? "critical" : data.status === "warning" ? "warning" : "info"}
                >
                  {data.status}
                </Badge>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                <MemBar
                  label="Engine"
                  pct={data.engine_used_pct}
                  value={`${formatBytes(data.engine_used_mb)} / ${formatBytes(data.engine_max_mb)}`}
                />
                <MemBar
                  label="OS"
                  pct={data.os_used_pct}
                  value={`${formatBytes(data.os_used_mb)} / ${formatBytes(data.os_total_mb)}`}
                />
                {data.swap_total_mb > 0 && (
                  <MemBar
                    label="Swap"
                    pct={data.swap_used_pct}
                    value={`${formatBytes(data.swap_used_mb)} / ${formatBytes(data.swap_total_mb)}`}
                  />
                )}
                <div className="space-y-0.5">
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Table vs Working</div>
                  <div className="font-mono text-[11px]">
                    <span className="text-blue-500">{formatBytes(data.table_memory_mb)}</span>
                    {" / "}
                    <span className="text-purple-500">{formatBytes(data.non_table_memory_mb)}</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function MemBar({ label, pct, value }: { label: string; pct: number; value: string }) {
  const color = pct > 90 ? STATUS_COLORS.critical : pct > 80 ? STATUS_COLORS.warning : STATUS_COLORS.healthy;
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</span>
        <span className="text-[10px] font-mono font-bold" style={{ color }}>
          {pct}%
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.min(100, pct)}%`, backgroundColor: color }}
        />
      </div>
      <div className="font-mono text-[10px] text-muted-foreground">{value}</div>
    </div>
  );
}