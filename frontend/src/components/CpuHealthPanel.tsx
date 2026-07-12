import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Cell } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import InfoHint from "./InfoHint";

const CHART_COLORS = ["#2196F3", "#FF9800", "#9C27B0", "#ef4444"];

type CpuHealthPanelProps = {
  cpuHealth?: {
    summary?: { node_count?: number; outlier_count?: number; avg_util_pct?: number };
    per_node?: Array<{
      node_id: string;
      cpu_count: number;
      leaf_util_pct: number;
      avg_core_util: number;
      max_core_util: number;
      core_stddev: number;
      softirq_pct: number;
      iowait_pct: number;
      steal_pct: number;
      health_zscore: number;
      is_outlier: boolean;
    }>;
    insights?: string[];
  };
};

export default function CpuHealthPanel({ cpuHealth }: CpuHealthPanelProps) {
  const perNode = cpuHealth?.per_node || [];
  const insights = cpuHealth?.insights || [];

  const utilChart = useMemo(
    () => perNode.map((n) => ({
      node: String(n.node_id),
      utilPct: n.leaf_util_pct,
      outlier: n.is_outlier,
    })),
    [perNode],
  );

  const softirqChart = useMemo(
    () => perNode.map((n) => ({ node: String(n.node_id), softirqPct: n.softirq_pct })),
    [perNode],
  );

  if (!perNode.length) {
    return (
      <Card data-testid="cpu-health-panel">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-1">
            <CardTitle className="text-sm font-bold tracking-tight">CPU Health (cpulist)</CardTitle>
            <InfoHint label="cpulist CPU health" content="Per-node CPU utilization from MV_SYSINFO_CPULIST with Z-score outlier detection and SoftIRQ/IOWait signals. Legacy Nodes tab CPU section." />
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground italic">No MV_SYSINFO_CPULIST data in this report.</p>
        </CardContent>
      </Card>
    );
  }

  const avgUtil = cpuHealth?.summary?.avg_util_pct ?? 0;

  return (
    <Card data-testid="cpu-health-panel">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-sm font-bold tracking-tight">CPU Health (cpulist)</CardTitle>
          <InfoHint
            label="cpulist CPU health"
            content="Aggregated CPU utilization across cores per node. Red bars = |Z-score| > 2 vs cluster peers. High SoftIRQ suggests network interrupt pressure; high IOWait suggests storage saturation."
          />
          {cpuHealth?.summary?.outlier_count ? (
            <Badge variant="warning">{cpuHealth.summary.outlier_count} outlier(s)</Badge>
          ) : (
            <Badge variant="healthy">Normal</Badge>
          )}
          <span className="text-xs text-muted-foreground">Avg util: {avgUtil}%</span>
        </div>
        {insights.length > 0 && (
          <ul className="text-xs mt-2 space-y-1 text-muted-foreground list-disc pl-4">
            {insights.map((line) => <li key={line}>{line}</li>)}
          </ul>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div>
            <p className="text-xs font-bold mb-2">CPU Utilization % (red = outlier)</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={utilChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="node" tick={{ fontSize: 9 }} interval={0} angle={-35} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 10 }} unit="%" domain={[0, 100]} />
                <ReferenceLine y={avgUtil} stroke="#00d992" strokeDasharray="4 4" label={{ value: "Avg", fontSize: 10 }} />
                <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                <Bar dataKey="utilPct" name="Util %">
                  {utilChart.map((entry, i) => (
                    <Cell key={i} fill={entry.outlier ? CHART_COLORS[3] : CHART_COLORS[0]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div>
            <p className="text-xs font-bold mb-2">SoftIRQ % (network/interrupt pressure)</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={softirqChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="node" tick={{ fontSize: 9 }} interval={0} angle={-35} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 10 }} unit="%" />
                <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                <Bar dataKey="softirqPct" fill={CHART_COLORS[1]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="overflow-x-auto border" style={{ borderColor: "var(--ss-divider)" }}>
          <table className="w-full dense-table text-xs">
            <thead>
              <tr>
                {["node_id", "cpu_count", "leaf_util_pct", "core_stddev", "softirq_pct", "iowait_pct", "health_zscore"].map((h) => (
                  <th key={h} className="text-left">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {perNode.map((row) => (
                <tr key={row.node_id} style={{ background: row.is_outlier ? "rgba(244,67,54,0.1)" : undefined }}>
                  <td className="font-mono">{row.node_id}</td>
                  <td>{row.cpu_count}</td>
                  <td>{row.leaf_util_pct}</td>
                  <td>{row.core_stddev}</td>
                  <td>{row.softirq_pct}</td>
                  <td>{row.iowait_pct}</td>
                  <td>{row.health_zscore}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
