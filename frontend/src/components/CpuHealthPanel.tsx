import { useState, useMemo, useEffect } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Cell } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import InfoHint from "./InfoHint";

const CHART_COLORS = ["#2196F3", "#FF9800", "#9C27B0", "#ef4444"];

type CpuHealthPanelProps = {
  cpuHealth?: {
    summary?: {
      node_count?: number;
      outlier_count?: number;
      avg_util_pct?: number;
      current_avg_util_pct?: number;
      lifetime_avg_util_pct?: number;
      has_current?: boolean;
      has_lifetime?: boolean;
      window?: string;
      source?: string;
    };
    per_node?: Array<{
      node_id: string;
      hostname?: string;
      role?: string;
      cpu_count?: number;
      leaf_util_pct: number;
      current_util_pct?: number;
      lifetime_util_pct?: number;
      avg_core_util?: number;
      max_core_util?: number;
      core_stddev?: number;
      softirq_pct: number;
      iowait_pct: number;
      steal_pct?: number;
      current_user_pct?: number;
      current_system_pct?: number;
      current_iowait_pct?: number;
      current_softirq_pct?: number;
      lifetime_softirq_pct?: number;
      lifetime_iowait_pct?: number;
      health_zscore: number;
      is_outlier: boolean;
      window?: string;
    }>;
    insights?: string[];
    source?: string;
    window?: string;
  };
};

export default function CpuHealthPanel({ cpuHealth }: CpuHealthPanelProps) {
  const perNode = cpuHealth?.per_node || [];
  const insights = cpuHealth?.insights || [];

  const hasCurrent = perNode.some((n) => n.current_util_pct != null);
  const hasLifetime = perNode.some((n) => n.lifetime_util_pct != null);

  const [metricView, setMetricView] = useState<"current" | "lifetime">(() =>
    hasCurrent ? "current" : "lifetime"
  );

  useEffect(() => {
    if (hasCurrent) {
      setMetricView("current");
    } else if (hasLifetime) {
      setMetricView("lifetime");
    }
  }, [hasCurrent, hasLifetime]);

  const isCurrent = metricView === "current" && hasCurrent;

  const utilChart = useMemo(
    () =>
      perNode.map((n) => {
        const val = isCurrent
          ? (n.current_util_pct ?? n.leaf_util_pct)
          : (n.lifetime_util_pct ?? n.leaf_util_pct);
        return {
          node: String(n.node_id),
          hostname: n.hostname,
          role: n.role,
          utilPct: val == null ? 0 : val,
          outlier: n.is_outlier,
          currentPct: n.current_util_pct,
          lifetimePct: n.lifetime_util_pct,
        };
      }),
    [perNode, isCurrent],
  );

  const softirqChart = useMemo(
    () =>
      perNode.map((n) => ({
        node: String(n.node_id),
        softirqPct: isCurrent
          ? (n.current_softirq_pct ?? n.softirq_pct)
          : (n.lifetime_softirq_pct ?? n.softirq_pct),
      })),
    [perNode, isCurrent],
  );

  const avgUtil = useMemo(() => {
    if (isCurrent && cpuHealth?.summary?.current_avg_util_pct != null) {
      return Number(cpuHealth.summary.current_avg_util_pct);
    }
    if (!isCurrent && cpuHealth?.summary?.lifetime_avg_util_pct != null) {
      return Number(cpuHealth.summary.lifetime_avg_util_pct);
    }
    const vals = utilChart
      .map((d) => d.utilPct)
      .filter((v) => v != null && Number.isFinite(Number(v)));
    if (!vals.length) return null;
    return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 100) / 100;
  }, [isCurrent, cpuHealth?.summary, utilChart]);

  if (!perNode.length) {
    return (
      <Card data-testid="cpu-health-panel">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-1">
            <CardTitle className="text-sm font-bold tracking-tight">CPU Health</CardTitle>
            <InfoHint
              label="CPU health"
              content="Per-node CPU utilization combining current load snapshots and cumulative since-boot statistics."
            />
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground italic">No CPU diagnostic data in this report.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="cpu-health-panel">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-sm font-bold tracking-tight">CPU Health</CardTitle>
            <InfoHint
              label="CPU health"
              content="Current CPU is an instantaneous utilization snapshot sampled from top during report collection. Lifetime average is computed from MV_SYSINFO_CPULIST cumulative counters across total host uptime (~days since boot). Red bars indicate |Z-score| > 2 vs cluster peers."
            />
            <Badge variant="outline" className="text-[10px]">
              {isCurrent ? "Current (top snapshot)" : "Lifetime Avg (since boot)"}
            </Badge>
            {cpuHealth?.summary?.outlier_count ? (
              <Badge variant="warning">{cpuHealth.summary.outlier_count} outlier(s)</Badge>
            ) : (
              <Badge variant="healthy">Normal</Badge>
            )}
            <span className="text-xs text-muted-foreground font-medium">
              {isCurrent ? "Avg current util:" : "Avg lifetime util:"} {avgUtil == null ? "—" : `${avgUtil}%`}
            </span>
          </div>

          {hasCurrent && hasLifetime && (
            <div className="flex items-center gap-1 bg-zinc-100 p-0.5 rounded border border-zinc-200">
              <button
                type="button"
                onClick={() => setMetricView("current")}
                className={`text-[10px] font-bold px-2 py-0.5 rounded transition-colors ${
                  isCurrent
                    ? "bg-[#AA00FF] text-white"
                    : "text-zinc-600 hover:text-zinc-900"
                }`}
                data-testid="toggle-current-cpu"
              >
                Current CPU (Snapshot)
              </button>
              <button
                type="button"
                onClick={() => setMetricView("lifetime")}
                className={`text-[10px] font-bold px-2 py-0.5 rounded transition-colors ${
                  !isCurrent
                    ? "bg-[#AA00FF] text-white"
                    : "text-zinc-600 hover:text-zinc-900"
                }`}
                data-testid="toggle-lifetime-cpu"
              >
                Lifetime Avg (Since Boot)
              </button>
            </div>
          )}
        </div>

        {insights.length > 0 && (
          <ul className="text-xs mt-2 space-y-1 text-muted-foreground list-disc pl-4">
            {insights.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div>
            <p className="text-xs font-bold mb-2">
              {isCurrent
                ? "Current CPU Utilization % (red = outlier)"
                : "Lifetime Avg CPU Utilization % (since boot, red = outlier)"}
            </p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={utilChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="node" tick={{ fontSize: 9 }} interval={0} angle={-35} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 10 }} unit="%" domain={[0, 100]} />
                {avgUtil != null && (
                  <ReferenceLine
                    y={avgUtil}
                    stroke="#00d992"
                    strokeDasharray="4 4"
                    label={{ value: "Avg", fontSize: 10 }}
                  />
                )}
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const item = payload[0].payload;
                    return (
                      <div
                        style={{
                          background: "#111",
                          border: "1px solid #333",
                          fontSize: 11,
                          padding: "6px 10px",
                          color: "#fff",
                        }}
                      >
                        <p className="font-bold">
                          Node {item.node} {item.role ? `(${item.role})` : ""}
                        </p>
                        {item.hostname && (
                          <p className="text-[10px] text-zinc-400 font-mono mb-1">{item.hostname}</p>
                        )}
                        <div className="space-y-0.5">
                          {item.currentPct != null && (
                            <p className={isCurrent ? "text-emerald-400 font-bold" : "text-zinc-300"}>
                              Current CPU: {item.currentPct}%
                            </p>
                          )}
                          {item.lifetimePct != null && (
                            <p className={!isCurrent ? "text-emerald-400 font-bold" : "text-zinc-400"}>
                              Lifetime Avg: {item.lifetimePct}%
                            </p>
                          )}
                        </div>
                      </div>
                    );
                  }}
                />
                <Bar dataKey="utilPct" name="Util %">
                  {utilChart.map((entry, i) => (
                    <Cell key={i} fill={entry.outlier ? CHART_COLORS[3] : CHART_COLORS[0]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div>
            <p className="text-xs font-bold mb-2">
              SoftIRQ % ({isCurrent ? "current interrupt activity" : "lifetime interrupt share"})
            </p>
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
                {["Node ID", "Role / Host", "Current Util %", "Lifetime Util %", "SoftIRQ %", "IOWait %", "Z-Score"].map(
                  (h) => (
                    <th key={h} className="text-left">
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {perNode.map((row) => (
                <tr key={row.node_id} style={{ background: row.is_outlier ? "rgba(244,67,54,0.1)" : undefined }}>
                  <td className="font-mono font-medium">{row.node_id}</td>
                  <td className="text-muted-foreground">
                    {row.role || "—"} {row.hostname ? `(${row.hostname})` : ""}
                  </td>
                  <td className="font-mono">
                    {row.current_util_pct != null ? `${row.current_util_pct}%` : "—"}
                  </td>
                  <td className="font-mono">
                    {row.lifetime_util_pct != null ? `${row.lifetime_util_pct}%` : "—"}
                  </td>
                  <td className="font-mono">
                    {row.softirq_pct != null ? `${row.softirq_pct}%` : "—"}
                  </td>
                  <td className="font-mono">
                    {row.iowait_pct != null ? `${row.iowait_pct}%` : "—"}
                  </td>
                  <td className="font-mono">
                    {row.health_zscore != null ? row.health_zscore : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
