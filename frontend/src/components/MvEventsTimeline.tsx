import { useMemo, useState, useEffect } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ZAxis, ReferenceArea,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import InfoHint from "./InfoHint";

type SeverityMeta = { label: string; color: string; z: number };

// Severity palette aligned to the DESIGN.md semantic roles (warm amber warning,
// coral error, deep red critical) with a muted mint for low-signal notices.
const SEVERITY_META: Record<string, SeverityMeta> = {
  NOTICE: { label: "Notice", color: "#2dd4a7", z: 45 },
  WARNING: { label: "Warning", color: "#f5a623", z: 80 },
  ERROR: { label: "Error", color: "#fb565b", z: 115 },
  CRITICAL: { label: "Critical", color: "#dc2626", z: 150 },
  UNKNOWN: { label: "Unknown", color: "#8b949e", z: 60 },
};

// High → low, used for legend/table sort so the eye lands on criticals first.
const SEVERITY_DESC = ["CRITICAL", "ERROR", "WARNING", "NOTICE", "UNKNOWN"];
// Low → high, used for chart draw order so criticals render on top of the pile.
const SEVERITY_DRAW = ["NOTICE", "WARNING", "ERROR", "CRITICAL", "UNKNOWN"];

function metaFor(sev: string): SeverityMeta {
  return SEVERITY_META[sev] || SEVERITY_META.UNKNOWN;
}

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
  const meta = metaFor(p.severity || "UNKNOWN");
  return (
    <div
      className="text-xs rounded-md shadow-lg max-w-xs overflow-hidden"
      style={{
        background: "var(--surface-elevated)",
        border: "1px solid var(--border-strong)",
        color: "var(--text-primary)",
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-1.5"
        style={{ borderBottom: "1px solid var(--border-default)" }}
      >
        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: meta.color }} />
        <span className="font-semibold uppercase tracking-wide" style={{ color: meta.color }}>
          {meta.label}
        </span>
        <span className="ml-auto font-mono" style={{ color: "var(--text-muted)" }}>
          {p.node_id}
        </span>
      </div>
      <div className="px-3 py-2 space-y-1">
        <div className="font-mono" style={{ color: "var(--text-secondary)" }}>{p.event_time}</div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Type: </span>
          <span className="font-medium">{p.event_type}</span>
        </div>
        {p.details ? (
          <div className="pt-1 break-words leading-snug" style={{ color: "var(--text-secondary)" }}>
            {p.details}
          </div>
        ) : null}
      </div>
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
  const [hiddenSeverities, setHiddenSeverities] = useState<string[]>([]);

  useEffect(() => {
    if (allNodes.length) {
      setSelectedNodes(allNodes);
    }
  }, [allNodes.join(",")]);

  const nodeIndex = useMemo(() => {
    const map: Record<string, number> = {};
    allNodes.forEach((n, i) => { map[n] = i; });
    return map;
  }, [allNodes]);

  const activeNodes = selectedNodes.length > 0 ? selectedNodes : allNodes;

  // Severity counts across the whole dataset (for the legend chips).
  const severityCounts = useMemo(() => {
    if (timeline?.severity_counts && Object.keys(timeline.severity_counts).length) {
      return timeline.severity_counts;
    }
    const counts: Record<string, number> = {};
    for (const p of points) {
      const sev = p.severity || "UNKNOWN";
      counts[sev] = (counts[sev] || 0) + 1;
    }
    return counts;
  }, [timeline?.severity_counts, points]);

  const presentSeverities = useMemo(
    () => SEVERITY_DESC.filter((s) => (severityCounts[s] || 0) > 0)
      .concat(Object.keys(severityCounts).filter((s) => !SEVERITY_DESC.includes(s) && severityCounts[s] > 0)),
    [severityCounts],
  );

  const filtered = useMemo(
    () => points.filter(
      (p) => activeNodes.includes(p.node_id) && !hiddenSeverities.includes(p.severity || "UNKNOWN"),
    ),
    [points, activeNodes, hiddenSeverities],
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
        z: metaFor(sev).z,
      });
    }
    const severities = [
      ...SEVERITY_DRAW.filter((s) => groups[s]?.length),
      ...Object.keys(groups).filter((s) => !SEVERITY_DRAW.includes(s)),
    ];
    return severities.map((sev) => ({ severity: sev, data: groups[sev] }));
  }, [filtered, nodeIndex]);

  const toggleNode = (node: string) => {
    setSelectedNodes((prev) =>
      prev.includes(node) ? prev.filter((n) => n !== node) : [...prev, node],
    );
  };

  const toggleSeverity = (sev: string) => {
    setHiddenSeverities((prev) =>
      prev.includes(sev) ? prev.filter((s) => s !== sev) : [...prev, sev],
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

  const chartHeight = Math.min(Math.max(allNodes.length * 44 + 90, 260), 520);

  return (
    <Card data-testid="mv-events-timeline">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-sm font-bold tracking-tight">MV_EVENTS Timeline</CardTitle>
          <InfoHint
            label="MV_EVENTS timeline"
            content="Scatter timeline of all MV_EVENTS rows: X = time, Y = origin node. Markers are colored and sized by severity (Notice / Warning / Error / Critical). Toggle severities or nodes to filter; the table below syncs to your selection."
          />
          <Badge variant="secondary" className="text-[10px]">
            {timeline?.total_count ?? points.length} events
            {timeline?.truncated ? " (truncated)" : ""}
          </Badge>
        </div>

        {/* Severity legend + filter */}
        <div className="flex flex-wrap items-center gap-1.5 mt-3">
          {presentSeverities.map((sev) => {
            const meta = metaFor(sev);
            const hidden = hiddenSeverities.includes(sev);
            return (
              <button
                key={sev}
                type="button"
                onClick={() => toggleSeverity(sev)}
                title={hidden ? `Show ${meta.label}` : `Hide ${meta.label}`}
                className="flex items-center gap-1.5 rounded-full pl-1.5 pr-2 py-0.5 text-[10px] font-medium transition-opacity"
                style={{
                  border: `1px solid ${hidden ? "var(--border-default)" : meta.color}`,
                  background: hidden ? "transparent" : `${meta.color}1f`,
                  color: hidden ? "var(--text-muted)" : "var(--text-primary)",
                  opacity: hidden ? 0.55 : 1,
                }}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: hidden ? "var(--text-muted)" : meta.color }}
                />
                <span className="uppercase tracking-wide">{meta.label}</span>
                <span className="tabular-nums" style={{ color: "var(--text-muted)" }}>
                  {(severityCounts[sev] || 0).toLocaleString()}
                </span>
              </button>
            );
          })}
        </div>

        {/* Node filter */}
        <div className="flex flex-wrap items-center gap-1 mt-2">
          <span className="text-[10px] uppercase tracking-wider mr-1" style={{ color: "var(--text-muted)" }}>
            Nodes
          </span>
          <button
            type="button"
            className="text-[10px] px-2 py-0.5 rounded border font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
            onClick={() => setSelectedNodes(allNodes)}
          >
            All
          </button>
          <button
            type="button"
            className="text-[10px] px-2 py-0.5 rounded border font-semibold uppercase tracking-wider"
            style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
            onClick={() => setSelectedNodes([])}
          >
            None
          </button>
          {allNodes.map((node) => {
            const on = activeNodes.includes(node);
            return (
              <button
                key={node}
                type="button"
                onClick={() => toggleNode(node)}
                className="text-[10px] px-2 py-0.5 rounded border font-mono transition-colors"
                style={{
                  borderColor: on ? "#00d992" : "var(--border-default)",
                  background: on ? "rgba(0,217,146,0.14)" : "transparent",
                  color: on ? "var(--text-primary)" : "var(--text-muted)",
                  opacity: on ? 1 : 0.6,
                }}
              >
                {node}
              </button>
            );
          })}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <ResponsiveContainer width="100%" height={chartHeight}>
          <ScatterChart margin={{ top: 10, right: 24, bottom: 24, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" strokeOpacity={0.5} vertical={false} />
            {/* Subtle alternating swimlanes so each node's row is easy to follow */}
            {allNodes.map((_, i) => (
              i % 2 === 1 ? (
                <ReferenceArea
                  key={`band-${i}`}
                  y1={i - 0.5}
                  y2={i + 0.5}
                  fill="var(--text-muted)"
                  fillOpacity={0.05}
                  ifOverflow="extendDomain"
                />
              ) : null
            ))}
            <XAxis
              type="number"
              dataKey="x"
              domain={["dataMin", "dataMax"]}
              tickFormatter={formatAxisTime}
              tick={{ fontSize: 10, fill: "var(--text-muted)" }}
              stroke="var(--border-strong)"
              name="Time"
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[-0.5, Math.max(allNodes.length - 0.5, 0.5)]}
              ticks={allNodes.map((_, i) => i)}
              tickFormatter={(v) => allNodes[v] ?? ""}
              tick={{ fontSize: 10, fill: "var(--text-secondary)" }}
              stroke="var(--border-strong)"
              width={108}
              name="Node"
              reversed
            />
            <ZAxis type="number" dataKey="z" range={[30, 150]} />
            <Tooltip content={<EventsTooltip />} cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }} />
            {scatterBySeverity.map(({ severity, data }) => (
              <Scatter
                key={severity}
                name={metaFor(severity).label}
                data={data}
                fill={metaFor(severity).color}
                fillOpacity={0.82}
                shape="diamond"
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>

        <div className="rounded border overflow-hidden" style={{ borderColor: "var(--border-default)" }}>
          <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
            <table className="w-full dense-table text-xs">
              <thead className="sticky top-0 z-10 bg-[var(--surface-elevated)]">
                <tr>
                  {["Node", "Time", "Severity", "Type", "Details"].map((h) => (
                    <th key={h} className="text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, 400).map((row, i) => {
                  const meta = metaFor(row.severity || "UNKNOWN");
                  return (
                    <tr key={`${row.event_time}-${row.node_id}-${i}`}>
                      <td className="font-mono">{row.node_id}</td>
                      <td className="font-mono whitespace-nowrap">{row.event_time}</td>
                      <td>
                        <span
                          className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide"
                          style={{ background: `${meta.color}22`, color: meta.color }}
                        >
                          <span className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} />
                          {meta.label}
                        </span>
                      </td>
                      <td>{row.event_type}</td>
                      <td className="max-w-md truncate" title={row.details}>{row.details}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        {filtered.length > 400 && (
          <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>
            Showing first 400 of {filtered.length.toLocaleString()} filtered events.
          </p>
        )}
        {filtered.length === 0 && (
          <p className="text-[11px] italic" style={{ color: "var(--text-muted)" }}>
            No events match the current severity/node filters.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
