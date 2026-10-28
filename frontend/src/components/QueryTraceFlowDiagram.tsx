import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";

export interface TraceStage {
  id: string;
  label: string;
  node_role: string;
  node_host: string;
  status: string;
  observed: boolean;
  metrics?: Record<string, unknown>;
  evidence?: Array<Record<string, unknown>>;
}

export interface TraceEdge {
  from: string;
  to: string;
  label?: string;
  inferred?: boolean;
}

interface QueryTraceFlowDiagramProps {
  stages: TraceStage[];
  edges: TraceEdge[];
  selectedStageId?: string | null;
  onSelectStage?: (stage: TraceStage | null) => void;
}

const STATUS_COLORS: Record<string, string> = {
  healthy: "#00d992",
  info: "#45B7D1",
  warning: "#FF9800",
  critical: "#F44336",
};

const ROLE_COLORS: Record<string, string> = {
  CLIENT: "#95A5A6",
  MA: "#FF6B6B",
  CA: "#45B7D1",
  LEAF: "#4ECDC4",
};

const STAGE_WIDTH = 130;
const STAGE_HEIGHT = 56;
const STAGE_GAP = 48;

function layoutStages(stages: TraceStage[]): Array<TraceStage & { x: number; y: number }> {
  const ordered = [...stages];
  const centerY = 120;
  const startX = 60;
  return ordered.map((stage, index) => ({
    ...stage,
    x: startX + index * (STAGE_WIDTH + STAGE_GAP),
    y: centerY,
  }));
}

export default function QueryTraceFlowDiagram({
  stages,
  edges,
  selectedStageId,
  onSelectStage,
}: QueryTraceFlowDiagramProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const layout = useMemo(() => layoutStages(stages), [stages]);
  const layoutMap = useMemo(() => new Map(layout.map((s) => [s.id, s])), [layout]);
  const width = Math.max(720, layout.length * (STAGE_WIDTH + STAGE_GAP) + 80);
  const height = 260;

  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;
    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>("g.zoom-root");

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.5, 2.5])
      .on("zoom", (event) => {
        g.attr("transform", event.transform.toString());
      });

    svg.call(zoom as never);
    return () => {
      svg.on(".zoom", null);
    };
  }, [layout.length]);

  return (
    <div ref={containerRef} className="w-full overflow-hidden rounded-md border border-border bg-[#050507]">
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="w-full h-[260px]" data-testid="query-trace-flow">
        <g className="zoom-root">
          {edges.map((edge, i) => {
            const from = layoutMap.get(edge.from);
            const to = layoutMap.get(edge.to);
            if (!from || !to) return null;
            const x1 = from.x + STAGE_WIDTH;
            const y1 = from.y + STAGE_HEIGHT / 2;
            const x2 = to.x;
            const y2 = to.y + STAGE_HEIGHT / 2;
            return (
              <g key={`edge-${i}`}>
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={edge.inferred ? "#6b7280" : "#00d992"}
                  strokeWidth={2}
                  strokeDasharray={edge.inferred ? "6 4" : undefined}
                  markerEnd="url(#arrow)"
                />
                {edge.label && edge.label !== "flow" && (
                  <text x={(x1 + x2) / 2} y={y1 - 8} fill="#9ca3af" fontSize={9} textAnchor="middle">
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}

          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#00d992" />
            </marker>
          </defs>

          {layout.map((stage) => {
            const statusColor = STATUS_COLORS[stage.status] || STATUS_COLORS.healthy;
            const roleColor = ROLE_COLORS[stage.node_role] || ROLE_COLORS.CLIENT;
            const selected = selectedStageId === stage.id;
            return (
              <g
                key={stage.id}
                transform={`translate(${stage.x}, ${stage.y})`}
                className="cursor-pointer"
                onClick={() => onSelectStage?.(selected ? null : stage)}
                data-testid={`trace-stage-${stage.id}`}
              >
                <rect
                  width={STAGE_WIDTH}
                  height={STAGE_HEIGHT}
                  rx={6}
                  fill="#111318"
                  stroke={selected ? "#00d992" : statusColor}
                  strokeWidth={selected ? 2.5 : 1.5}
                  strokeDasharray={stage.observed ? undefined : "5 3"}
                />
                <rect x={0} y={0} width={6} height={STAGE_HEIGHT} rx={2} fill={roleColor} />
                <text x={12} y={18} fill="#f3f4f6" fontSize={10} fontWeight={700}>
                  {stage.label}
                </text>
                <text x={12} y={34} fill="#9ca3af" fontSize={9}>
                  {stage.node_role} · {stage.node_host?.slice(0, 16) || "—"}
                </text>
                <text x={12} y={48} fill={statusColor} fontSize={8}>
                  {stage.observed ? "observed" : "inferred"}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-[10px] text-muted-foreground border-t border-border bg-[#0d0f14]">
        <div className="flex gap-4">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 border-2 border-[#00d992] rounded-sm bg-[#111318]" />
            <span><strong>Observed:</strong> Direct match from processlist, blocked queries, or tracelogs</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 border-2 border-dashed border-gray-500 rounded-sm bg-[#111318]" />
            <span><strong>Inferred:</strong> Reconstructed SingleStore engine stage (compilation, gather, partition fan-out)</span>
          </span>
        </div>
        <div className="text-[9px] text-gray-400 italic">
          Tip: Click any stage to inspect raw evidence rows, node IDs, and metrics below.
        </div>
      </div>
    </div>
  );
}
