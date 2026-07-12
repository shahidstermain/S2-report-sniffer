import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Cell } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import InfoHint from "./InfoHint";

const CHART_COLORS = ["#00d992", "#AA00FF", "#f59e0b", "#ef4444", "#3b82f6", "#9C27B0"];

type SysinfoNetworkPanelProps = {
  network?: {
    summary?: { node_count?: number; outlier_count?: number; leaf_count?: number };
    per_node?: Array<{
      node_id: string;
      type: string;
      total_received_gb: number;
      total_transmitted_gb: number;
      primary_interface?: string;
      z_score: number;
      is_outlier: boolean;
      daily_avg_gb?: number | null;
    }>;
    interfaces?: Array<{
      node_id: string;
      interface: string;
      total_traffic_gb: number;
    }>;
    insights?: string[];
  };
};

export default function SysinfoNetworkPanel({ network }: SysinfoNetworkPanelProps) {
  const perNode = network?.per_node || [];
  const insights = network?.insights || [];

  const txChart = useMemo(
    () => perNode.map((n) => ({
      node: String(n.node_id),
      txGb: n.total_transmitted_gb,
      outlier: n.is_outlier,
    })),
    [perNode],
  );

  const zChart = useMemo(
    () => perNode.filter((n) => n.type === "LEAF").map((n) => ({
      node: String(n.node_id),
      zScore: n.z_score,
      outlier: n.is_outlier,
    })),
    [perNode],
  );

  const ifaceChart = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const row of network?.interfaces || []) {
      totals[row.interface] = (totals[row.interface] || 0) + row.total_traffic_gb;
    }
    return Object.entries(totals)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([iface, gb]) => ({ interface: iface, trafficGb: Math.round(gb * 100) / 100 }));
  }, [network?.interfaces]);

  if (!perNode.length) {
    return (
      <Card data-testid="sysinfo-network-panel">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-1">
            <CardTitle className="text-sm font-bold tracking-tight">Network Traffic (sysinfo-net)</CardTitle>
            <InfoHint label="sysinfo-net" content="Leaf-to-leaf cumulative traffic from MV_SYSINFO_NET with Z-score outlier detection. Legacy Network tab sysinfo section." />
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground italic">No MV_SYSINFO_NET data in this report.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="sysinfo-network-panel">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-sm font-bold tracking-tight">Network Traffic (sysinfo-net)</CardTitle>
          <InfoHint
            label="sysinfo-net traffic"
            content="Cumulative RX/TX per node from MV_SYSINFO_NET. Red bars mark leaf nodes with |Z-score| > 2 vs peer transmit volume — indicates possible data skew or hot nodes."
          />
          {network?.summary?.outlier_count ? (
            <Badge variant="warning">{network.summary.outlier_count} outlier(s)</Badge>
          ) : (
            <Badge variant="healthy">Balanced</Badge>
          )}
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
            <p className="text-xs font-bold mb-2">Total Transmitted per Node</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={txChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="node" tick={{ fontSize: 9 }} interval={0} angle={-35} textAnchor="end" height={60} />
                <YAxis tick={{ fontSize: 10 }} unit=" GB" />
                <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                <Bar dataKey="txGb" name="Transmitted GB">
                  {txChart.map((entry, i) => (
                    <Cell key={i} fill={entry.outlier ? CHART_COLORS[3] : CHART_COLORS[0]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {zChart.length > 1 && (
            <div>
              <p className="text-xs font-bold mb-2">Leaf Traffic Z-Score</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={zChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="node" tick={{ fontSize: 9 }} interval={0} angle={-35} textAnchor="end" height={60} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <ReferenceLine y={2} stroke="#ef4444" strokeDasharray="4 4" />
                  <ReferenceLine y={-2} stroke="#ef4444" strokeDasharray="4 4" />
                  <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                  <Bar dataKey="zScore" name="Z-Score" fill={CHART_COLORS[4]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {ifaceChart.length > 0 && (
          <div>
            <p className="text-xs font-bold mb-2">Top Interfaces by Traffic</p>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={ifaceChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="interface" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} unit=" GB" />
                <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                <Bar dataKey="trafficGb" fill={CHART_COLORS[1]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="overflow-x-auto border" style={{ borderColor: "var(--ss-divider)" }}>
          <table className="w-full dense-table text-xs">
            <thead>
              <tr>
                {["node_id", "type", "total_received_gb", "total_transmitted_gb", "primary_interface", "z_score", "daily_avg_gb"].map((h) => (
                  <th key={h} className="text-left">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {perNode.map((row) => (
                <tr key={row.node_id} style={{ background: row.is_outlier ? "rgba(244,67,54,0.1)" : undefined }}>
                  <td className="font-mono">{row.node_id}</td>
                  <td>{row.type}</td>
                  <td>{row.total_received_gb}</td>
                  <td>{row.total_transmitted_gb}</td>
                  <td>{row.primary_interface || "—"}</td>
                  <td>{row.z_score}</td>
                  <td>{row.daily_avg_gb ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
