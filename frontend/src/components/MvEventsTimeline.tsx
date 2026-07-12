import { useMemo, useState, useEffect } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ZAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import InfoHint from "./InfoHint";

const SEVERITY_COLORS: Record<string, string> = {
  NOTICE: "#00C853",
  WARNING: "#FF9800",
  ERROR: "#F44336",
  CRITICAL: "#B71C1C",
  UNKNOWN: "#607d8b",
};

function parseTimeMs(ts: string): number {
  const ms = Date.parse(ts);
  return Number.isFinite(ms) ? ms : 0;
}

function formatAxisTime(ms: number): string {
  if (!ms) return "";
  const d = new Date(ms);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

function EventsTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <div
      className="text-xs px-3 py-2 rounded shadow-lg max-w-sm"
      style={{ background: "#111", border: "1px solid #333", color: "#eee" }}
    >
      <div className="font-semibold mb-1">{p.event_time}</div>
      <div>Node: {p.node_id}</div>
      <div>Severity: {p.severity}</div>
      <div>Type: {p.event_type}</div>
      {p.details ? <div className="mt-1 opacity-80 break-words">{p.details}</div> : null}
    </div>
  );
}

type MvEventsTimelineProps = {
  timeline?: {
    points?: Array<{
      node_id: string;
      event_time: string;
      severity: string;
      event_type: string;
      details?: string;
    }>;
    total_count?: number;
    truncated?: boolean;
    nodes?: string[];
    severity_counts?: Record<string, number>;
  };
};

export default function MvEventsTimeline({ timeline }: MvEventsTimelineProps) {
  const points = timeline?.points || [];
  const allNodes = timeline?.nodes || [];
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);

  useEffect(() => {
    if (allNodes.length) {
      setSelectedNodes(allNodes);
    }
  }, [allNodes.join(",")]);

  // #region agent log
  useEffect(() => {
    const sample = points.slice(0, 5).map((p) => ({
      ts: p.event_time,
      ms: parseTimeMs(p.event_time),
      node: p.node_id,
      severity: p.severity,
    }));
    fetch("http://127.0.0.1:7642/ingest/8c40d513-4927-4b75-9d76-87afc63f90d0", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "0667a1" },
      body: JSON.stringify({
        sessionId: "0667a1",
        hypothesisId: "H5",
        location: "MvEventsTimeline.tsx:render",
        message: "mv events scatter data",
        data: {
          pointsLen: points.length,
          nodesLen: allNodes.length,
          filteredLen: points.filter((p) => (selectedNodes.length ? selectedNodes : allNodes).includes(p.node_id)).length,
          zeroTsCount: sample.filter((s) => !s.ms).length,
          sample,
        },
        timestamp: Date.now(),
        runId: "pre-fix",
      }),
    }).catch(() => {});
  }, [points, allNodes, selectedNodes]);
  // #endregion

  const nodeIndex = useMemo(() => {
    const map: Record<string, number> = {};
    allNodes.forEach((n, i) => { map[n] = i; });
    return map;
  }, [allNodes]);

  const activeNodes = selectedNodes.length > 0 ? selectedNodes : allNodes;

  const filtered = useMemo(
    () => points.filter((p) => activeNodes.includes(p.node_id)),
    [points, activeNodes],
  );

  const scatterBySeverity = useMemo(() => {
    const groups: Record<string, any[]> = {};
    for (const p of filtered) {
      const sev = p.severity || "UNKNOWN";
      if (!groups[sev]) groups[sev] = [];
      groups[sev].push({
        ...p,
        x: parseTimeMs(p.event_time),
        y: nodeIndex[p.node_id] ?? 0,
        z: 60,
      });
    }
    const order = ["NOTICE", "WARNING", "ERROR", "CRITICAL"];
    const severities = [
      ...order.filter((s) => groups[s]?.length),
      ...Object.keys(groups).filter((s) => !order.includes(s)),
    ];
    return severities.map((sev) => ({ severity: sev, data: groups[sev] }));
  }, [filtered, nodeIndex]);

  const toggleNode = (node: string) => {
    setSelectedNodes((prev) =>
      prev.includes(node) ? prev.filter((n) => n !== node) : [...prev, node],
    );
  };

  if (!points.length) {
    return (
      <Card data-testid="mv-events-timeline">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-1">
            <CardTitle className="text-sm font-bold tracking-tight">MV_EVENTS Timeline</CardTitle>
            <InfoHint
              label="MV_EVENTS timeline"
              content="Full cluster event scatter from informationSchemaMvEvents — same view as the legacy Events tab, with severity coloring and node filtering."
            />
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground italic">No MV_EVENTS data in this report.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="mv-events-timeline">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-sm font-bold tracking-tight">MV_EVENTS Timeline</CardTitle>
          <InfoHint
            label="MV_EVENTS timeline"
            content="Scatter timeline of all MV_EVENTS rows: X = time, Y = origin node. Diamond markers colored by severity (Notice / Warning / Error). Filter nodes below; table syncs to selection."
          />
          <Badge variant="secondary" className="text-[10px]">
            {timeline?.total_count ?? points.length} events
            {timeline?.truncated ? " (truncated)" : ""}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-1 mt-2">
          <button
            type="button"
            className="text-[10px] px-2 py-0.5 border font-bold uppercase tracking-wider"
            style={{ borderColor: "var(--ss-divider)" }}
            onClick={() => setSelectedNodes(allNodes)}
          >
            All nodes
          </button>
          {allNodes.map((node) => (
            <button
              key={node}
              type="button"
              onClick={() => toggleNode(node)}
              className={`text-[10px] px-2 py-0.5 border font-mono ${
                activeNodes.includes(node)
                  ? "bg-[#00d992]/20 border-[#00d992]"
                  : "opacity-50 border-zinc-600"
              }`}
            >
              {node}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ResponsiveContainer width="100%" height={420}>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis
              type="number"
              dataKey="x"
              domain={["dataMin", "dataMax"]}
              tickFormatter={formatAxisTime}
              tick={{ fontSize: 10 }}
              name="Time"
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[-0.5, Math.max(allNodes.length - 0.5, 0.5)]}
              ticks={allNodes.map((_, i) => i)}
              tickFormatter={(v) => allNodes[v] ?? ""}
              tick={{ fontSize: 9 }}
              width={100}
              name="Node"
              reversed
            />
            <ZAxis type="number" dataKey="z" range={[40, 40]} />
            <Tooltip content={<EventsTooltip />} />
            <Legend />
            {scatterBySeverity.map(({ severity, data }) => (
              <Scatter
                key={severity}
                name={severity}
                data={data}
                fill={SEVERITY_COLORS[severity] || SEVERITY_COLORS.UNKNOWN}
                shape="diamond"
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>

        <div className="overflow-x-auto border max-h-[320px] overflow-y-auto" style={{ borderColor: "var(--ss-divider)" }}>
          <table className="w-full dense-table text-xs">
            <thead className="sticky top-0 bg-[var(--surface-elevated)]">
              <tr>
                {["node_id", "event_time", "severity", "event_type", "details"].map((h) => (
                  <th key={h} className="text-left">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 400).map((row, i) => (
                <tr
                  key={`${row.event_time}-${row.node_id}-${i}`}
                  style={{
                    background:
                      row.severity === "ERROR" || row.severity === "CRITICAL"
                        ? "rgba(244,67,54,0.12)"
                        : row.severity === "WARNING"
                          ? "rgba(255,152,0,0.1)"
                          : undefined,
                  }}
                >
                  <td className="font-mono">{row.node_id}</td>
                  <td className="font-mono whitespace-nowrap">{row.event_time}</td>
                  <td>{row.severity}</td>
                  <td>{row.event_type}</td>
                  <td className="max-w-md truncate" title={row.details}>{row.details}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length > 400 && (
          <p className="text-[10px] text-muted-foreground">Showing first 400 of {filtered.length} filtered events.</p>
        )}
      </CardContent>
    </Card>
  );
}
