import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatMegabytes } from "@/lib/utils-sdb";
import InfoHint from "./InfoHint";

/**
 * Per-node Memory Utilization Panel
 * Shows memory vs maximum_memory, host RAM (OS), swap, and table vs other allocators.
 */

interface NodeMemData {
  engine_used_mb: number | null;
  engine_max_mb: number | null;
  engine_used_pct: number | null;
  table_memory_mb: number;
  non_table_memory_mb: number;
  os_total_mb: number | null;
  os_used_mb: number | null;
  os_available_mb: number | null;
  os_used_pct: number | null;
  swap_total_mb: number | null;
  swap_used_mb: number | null;
  swap_used_pct: number | null;
  status: "healthy" | "warning" | "critical" | "unknown";
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

  const summary = memoryUtilization.cluster_summary;
  const perNode = memoryUtilization.per_node;
  const nodeEntries = Object.entries(perNode);
  const formatSummaryPct = (value: number | null | undefined) =>
    value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value)}%`;
  const hasIssues = (summary?.nodes_over_80pct ?? 0) > 0 || (summary?.nodes_over_90pct ?? 0) > 0 ||
    nodeEntries.some(([, d]) => d.swap_used_pct != null && d.swap_used_pct > 25);

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
              Avg engine: {formatSummaryPct(summary?.avg_engine_used_pct)} ·
              Highest: {formatSummaryPct(summary?.highest_utilization_pct)} on {summary?.highest_utilization_node || "—"}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {(summary?.nodes_over_90pct ?? 0) > 0 && (
              <Badge variant="critical">{summary?.nodes_over_90pct} over 90%</Badge>
            )}
            {(summary?.nodes_over_80pct ?? 0) > 0 && (
              <Badge variant="warning">{summary?.nodes_over_80pct} over 80%</Badge>
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
                  {data.status || "unknown"}
                </Badge>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                <MemBar
                  label="vs maximum_memory"
                  pct={data.engine_used_pct}
                  value={`${formatMegabytes(data.engine_used_mb)} / ${formatMegabytes(data.engine_max_mb)}`}
                />
                <MemBar
                  label="Host RAM (OS)"
                  pct={data.os_used_pct}
                  value={`${formatMegabytes(data.os_used_mb)} / ${formatMegabytes(data.os_total_mb)}`}
                />
                {data.swap_total_mb != null && data.swap_total_mb > 0 && (
                  <MemBar
                    label="Swap"
                    pct={data.swap_used_pct}
                    value={`${formatMegabytes(data.swap_used_mb)} / ${formatMegabytes(data.swap_total_mb)}`}
                  />
                )}
                <div className="space-y-0.5">
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Table vs other allocators</div>
                  <div className="font-mono text-[11px]">
                    <span className="text-blue-500">{formatMegabytes(data.table_memory_mb)}</span>
                    {" / "}
                    <span className="text-purple-500">{formatMegabytes(data.non_table_memory_mb)}</span>
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

function MemBar({ label, pct, value }: { label: string; pct: number | null | undefined; value: string }) {
  const known = pct != null && Number.isFinite(Number(pct));
  const valuePct = known ? Number(pct) : null;
  const color = !known
    ? "#8B8FA3"
    : valuePct! > 90
      ? STATUS_COLORS.critical
      : valuePct! > 80
        ? STATUS_COLORS.warning
        : STATUS_COLORS.healthy;
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</span>
        <span className="text-[10px] font-mono font-bold" style={{ color }}>
          {known ? `${valuePct}%` : "—"}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: known ? `${Math.min(100, valuePct!)}%` : "0%", backgroundColor: color }}
        />
      </div>
      <div className="font-mono text-[10px] text-muted-foreground">{value}</div>
    </div>
  );
}