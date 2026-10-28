import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, X, AlertTriangle } from "lucide-react";
import { getQueryTrace, resolveQueryTrace } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import QueryTraceFlowDiagram, { TraceStage } from "./QueryTraceFlowDiagram";
import QueryTraceTimeline, { TraceTimeline } from "./QueryTraceTimeline";
import InfoHint from "./InfoHint";
import { humanizeTraceType } from "@/lib/nextSteps";

export interface TraceSelector {
  trace_id?: string;
  connection_id?: string;
  activity_name?: string;
  query_text?: string;
  normalized_sql?: string;
}

interface QueryTracerPanelProps {
  reportId: string;
  selector: TraceSelector | null;
  onClose: () => void;
}

interface LogCorrelation {
  pattern: string;
  node: string;
  role?: string;
  timestamp?: string;
  severity?: string;
  line_number?: number;
  line: string;
  source?: string;
}

interface TracePayload {
  trace_id: string;
  trace_type: string;
  query_text: string;
  routing?: {
    label: string;
    confidence: string;
    reason?: string;
    matched_columns?: string[];
  };
  confidence: {
    score: number;
    tier: "low" | "medium" | "high";
    factors: Array<{ id: string; label: string; weight: number; present: boolean }>;
  };
  stages: TraceStage[];
  edges: Array<{ from: string; to: string; label?: string; inferred?: boolean }>;
  timeline?: TraceTimeline;
  failure?: {
    stage_id: string;
    category: string;
    summary: string;
    blocking_type?: string | null;
  } | null;
  related_findings?: string[];
  evidence_summary?: string[];
  log_correlations?: LogCorrelation[];
  limitations?: string[];
}

type TraceTab = "summary" | "flow" | "timeline" | "logs" | "findings";

const TIER_VARIANT: Record<string, "success" | "warning" | "critical" | "info"> = {
  high: "success",
  medium: "warning",
  low: "critical",
};

const TRACE_TABS: Array<{ id: TraceTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "flow", label: "Flow" },
  { id: "timeline", label: "Timeline" },
  { id: "logs", label: "Logs" },
  { id: "findings", label: "Findings" },
];

const LOW_CONFIDENCE_COPY =
  "This trace is reconstructed from a point-in-time Cluster Report, not live query profiling. Stages marked dashed are inferred.";

function hasOnlyTraceId(selector: TraceSelector): boolean {
  return Boolean(
    selector.trace_id &&
      !selector.connection_id &&
      !selector.activity_name &&
      !selector.query_text &&
      !selector.normalized_sql
  );
}

export default function QueryTracerPanel({ reportId, selector, onClose }: QueryTracerPanelProps) {
  const [trace, setTrace] = useState<TracePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TraceTab>("summary");
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);

  const loadTrace = useCallback(async () => {
    if (!selector) return;
    setLoading(true);
    setError(null);
    setSelectedStageId(null);
    setActiveTab("summary");
    try {
      const res = hasOnlyTraceId(selector)
        ? await getQueryTrace(reportId, selector.trace_id!)
        : await resolveQueryTrace(reportId, selector);
      setTrace(res.data);
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        "Failed to load query trace";
      setError(message);
      setTrace(null);
    } finally {
      setLoading(false);
    }
  }, [reportId, selector]);

  useEffect(() => {
    if (selector) loadTrace();
  }, [selector, loadTrace]);

  if (!selector) return null;

  const selectedStage = trace?.stages.find((s) => s.id === selectedStageId) || null;
  const logCount = trace?.log_correlations?.length || 0;
  const findingsCount = trace?.related_findings?.length || 0;

  // Portal to <body> so ancestor transforms/filters (page fade-in wrappers,
  // animated cards) can never become the containing block for this overlay.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      data-testid="query-tracer-panel"
      role="dialog"
      aria-modal="true"
      aria-label="Query Tracer"
    >
      <div className="w-full max-w-5xl max-h-[90vh] min-w-0 overflow-hidden rounded-lg border border-border bg-background shadow-xl flex flex-col">
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-bold tracking-tight">Query Tracer</h3>
              <InfoHint
                label="query tracer methodology"
                content="How it works: Stitches point-in-time report snapshots (SHOW/MV_PROCESSLIST, MV_BLOCKED_QUERIES, and node tracelogs) across aggregators and leaves. Solid stages show direct evidence; dashed stages (compilation, gather, partition fan-out) are inferred models because offline Cluster Reports omit live EXPLAIN/PROFILE."
              />
              {trace && (
                <Badge variant={TIER_VARIANT[trace.confidence.tier] || "info"}>
                  {trace.confidence.score}% {trace.confidence.tier}
                </Badge>
              )}
              {trace?.trace_type && <Badge variant="outline">{humanizeTraceType(trace.trace_type)}</Badge>}
              {trace?.routing?.label && <Badge variant="info">{trace.routing.label}</Badge>}
            </div>
            <p
              className="text-xs text-muted-foreground truncate mt-1"
              title={trace?.query_text || selector.query_text}
              data-raw-value="true"
            >
              {trace?.query_text || selector.query_text || "Loading trace…"}
            </p>
            {trace?.routing?.reason && (
              <p className="text-[10px] text-muted-foreground mt-1">{trace.routing.reason}</p>
            )}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close query tracer">
            <X className="h-4 w-4" />
          </Button>
        </div>

        {trace && !loading && (
          <div className="flex gap-1 px-4 pt-3 border-b border-border overflow-x-auto">
            {TRACE_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                data-testid={`trace-tab-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "text-[10px] uppercase tracking-wider font-bold px-3 py-1.5 rounded-t border border-b-0 shrink-0",
                  activeTab === tab.id
                    ? "bg-background border-border text-[#00d992]"
                    : "bg-muted/30 border-transparent text-muted-foreground"
                )}
              >
                {tab.label}
                {tab.id === "logs" && logCount > 0 ? ` (${logCount})` : ""}
                {tab.id === "findings" && findingsCount > 0 ? ` (${findingsCount})` : ""}
              </button>
            ))}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {loading && (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[#00d992]" />
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-500 border border-red-500/30 rounded p-3">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          {trace && !loading && (
            <>
              {trace.confidence.tier === "low" && (
                <div className="rounded border border-amber-500/40 bg-amber-950/20 px-3 py-2 text-xs text-amber-200" data-testid="low-confidence-banner">
                  {LOW_CONFIDENCE_COPY}
                </div>
              )}

              {trace.evidence_summary && trace.evidence_summary.length > 0 && (
                <div className="rounded border border-border bg-muted/20 px-3 py-2 text-[10px] font-mono flex flex-wrap gap-2" data-testid="evidence-strip">
                  <span className="text-muted-foreground uppercase tracking-wider font-bold">Evidence:</span>
                  {trace.evidence_summary.map((item) => (
                    <span key={item} className="px-1.5 py-0.5 rounded bg-background border border-border">
                      {item}
                    </span>
                  ))}
                </div>
              )}

              {trace.failure && (
                <div className="rounded border border-red-500/30 bg-red-950/20 px-3 py-2 text-xs">
                  <span className="font-semibold text-red-400">Failure stage: {trace.failure.stage_id}</span>
                  <span className="text-muted-foreground"> — {trace.failure.summary}</span>
                </div>
              )}

              {activeTab === "summary" && (
                <div className="space-y-3 text-xs">
                  <div className="rounded border border-border bg-muted/30 p-2.5 text-[11px] leading-relaxed text-muted-foreground flex items-start gap-2" data-testid="tracer-methodology-note">
                    <span className="font-semibold text-foreground shrink-0">Data correlation:</span>
                    <span>
                      Reconstructed offline by correlating point-in-time snapshots across nodes: <code className="font-mono text-[10px] bg-background px-1 py-0.5 rounded border border-border">SHOW PROCESSLIST</code> (connection state, elapsed runtime), <code className="font-mono text-[10px] bg-background px-1 py-0.5 rounded border border-border">MV_BLOCKED_QUERIES</code> (blocker connection &amp; node IDs), and node tracelogs. Solid stages are backed by direct snapshot rows; dashed stages represent architectural SingleStore routing &amp; coordination stages.
                    </span>
                  </div>
                  <div className="grid sm:grid-cols-2 gap-3">
                    <div className="rounded border border-border p-3">
                      <div className="flex items-center justify-between mb-1">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Trace type</p>
                        <InfoHint
                          label="trace type"
                          content="Classified based on observed symptoms: 'Lock wait' when matched in MV_BLOCKED_QUERIES; 'Runaway' when elapsed state duration exceeds 300s; 'Slow' when >30s; or 'Generic' for normal query correlation."
                        />
                      </div>
                      <p className="font-semibold">{humanizeTraceType(trace.trace_type)}</p>
                    </div>
                    <div className="rounded border border-border p-3">
                      <div className="flex items-center justify-between mb-1">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Partition Routing</p>
                        <InfoHint
                          label="partition routing"
                          content="Inferred from query text predicates and cluster layout. Since Cluster Reports omit full shard-key DDL, equality checks without verified shard keys default to 'partitions:unknown' or 'partitions:all' (cluster-wide fan-out)."
                        />
                      </div>
                      <p className="font-semibold">{trace.routing?.label || "—"}</p>
                      {trace.routing?.reason && <p className="text-muted-foreground mt-1 text-[11px]">{trace.routing.reason}</p>}
                    </div>
                  </div>
                  <div className="rounded border border-border p-3">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Stage overview</p>
                      <span className="text-[10px] text-muted-foreground">Click a stage to switch to Flow view</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {trace.stages.map((stage) => (
                        <button
                          key={stage.id}
                          type="button"
                          onClick={() => {
                            setActiveTab("flow");
                            setSelectedStageId(stage.id);
                          }}
                          className={cn(
                            "px-2.5 py-1.5 rounded border text-[10px] flex items-center gap-1.5 transition-colors hover:bg-muted/40",
                            stage.observed ? "border-[#00d992]" : "border-dashed border-muted-foreground",
                            stage.status === "critical" && "text-red-400 border-red-500",
                            stage.status === "warning" && "text-amber-400 border-amber-500"
                          )}
                        >
                          <span className={cn(
                            "w-1.5 h-1.5 rounded-full shrink-0",
                            stage.status === "critical" ? "bg-red-500" : stage.status === "warning" ? "bg-amber-500" : "bg-[#00d992]"
                          )} />
                          <span>{stage.label}</span>
                          <span className="text-[9px] text-muted-foreground">({stage.observed ? "observed" : "inferred"})</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {activeTab === "flow" && (
                <QueryTraceFlowDiagram
                  stages={trace.stages}
                  edges={trace.edges}
                  selectedStageId={selectedStageId}
                  onSelectStage={(stage) => setSelectedStageId(stage?.id || null)}
                />
              )}

              {activeTab === "timeline" && trace.timeline && (
                <QueryTraceTimeline
                  timeline={trace.timeline}
                  selectedStageId={selectedStageId}
                  onSelectStage={setSelectedStageId}
                />
              )}

              {activeTab === "logs" && (
                <div className="rounded border border-border">
                  {logCount === 0 ? (
                    <p className="p-4 text-xs text-muted-foreground">
                      No correlated tracelog hits. Raw log search requires a persisted extracted report root
                      (default cap 2 GB via S2RS_MAX_EXTRACTED_KEEP_GB). Re-upload or import with persistence enabled.
                    </p>
                  ) : (
                    <div className="divide-y divide-border max-h-[360px] overflow-y-auto">
                      {trace.log_correlations?.map((hit, idx) => (
                        <div key={`${hit.pattern}-${idx}`} className="p-3 text-xs space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <Badge variant="outline">{hit.pattern}</Badge>
                            {hit.node && <span className="font-mono text-muted-foreground">{hit.node}</span>}
                            {hit.timestamp && <span className="font-mono text-[10px]">{hit.timestamp}</span>}
                          </div>
                          <pre className="text-[10px] font-mono bg-muted/40 p-2 rounded overflow-x-auto whitespace-pre-wrap">
                            {hit.line}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {activeTab === "findings" && (
                <div className="rounded border border-border p-3">
                  {findingsCount === 0 ? (
                    <p className="text-xs text-muted-foreground">No related superchecker findings for this trace type.</p>
                  ) : (
                    <ul className="space-y-2">
                      {trace.related_findings?.map((finding) => (
                        <li key={finding} className="flex items-center gap-2 text-xs">
                          <Badge variant="outline">{finding}</Badge>
                          <span className="text-muted-foreground">See Issues tab for remediation</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="grid md:grid-cols-2 gap-4">
                <div className="rounded border border-border p-3">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      Confidence scoring breakdown
                    </h4>
                    <InfoHint
                      label="confidence score factors"
                      content="Weights reflect data reliability: Direct connection matches (+25), MV_BLOCKED_QUERIES rows (+20), and MV_QUERIES (+20) provide strong evidence. Lack of verified shard keys imposes a -15 fan-out inference penalty."
                    />
                  </div>
                  <ul className="space-y-1 text-xs">
                    {trace.confidence.factors.map((f) => (
                      <li key={f.id} className="flex justify-between gap-2">
                        <span className={cn(!f.present && "text-muted-foreground")}>{f.label}</span>
                        <span className="font-mono">{f.weight > 0 ? `+${f.weight}` : f.weight}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 pt-2 border-t border-border/60 text-[10px] text-muted-foreground leading-relaxed">
                    Higher scores mean multiple independent tables (processlist, blocked queries, node tracelogs) cross-verified the exact same connection or activity.
                  </div>
                </div>

                <div className="rounded border border-border p-3">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      {selectedStage ? `Evidence — ${selectedStage.label}` : "Selected stage evidence"}
                    </h4>
                    {selectedStage && (
                      <Badge variant={selectedStage.observed ? "success" : "outline"} className="text-[9px]">
                        {selectedStage.observed ? "Direct Snapshot" : "Architectural Model"}
                      </Badge>
                    )}
                  </div>
                  {selectedStage ? (
                    <div className="text-xs space-y-2">
                      <p>
                        <span className="text-muted-foreground">Status:</span>{" "}
                        <span className={cn(
                          "font-semibold",
                          selectedStage.status === "critical" ? "text-red-400" : selectedStage.status === "warning" ? "text-amber-400" : "text-[#00d992]"
                        )}>
                          {selectedStage.status}
                        </span>
                      </p>
                      <p>
                        <span className="text-muted-foreground">Layer:</span>{" "}
                        {selectedStage.observed ? "observed (solid line — verified in Cluster Report)" : "inferred (dashed line — SingleStore engine model)"}
                      </p>
                      {selectedStage.evidence && selectedStage.evidence.length > 0 ? (
                        <div>
                          <span className="text-[10px] text-muted-foreground block mb-1">Raw snapshot correlation:</span>
                          <pre className="text-[10px] font-mono bg-muted/40 p-2 rounded overflow-x-auto max-h-[140px]">
                            {JSON.stringify(selectedStage.evidence, null, 2)}
                          </pre>
                        </div>
                      ) : (
                        <p className="text-muted-foreground text-[11px] italic">
                          No direct tabular evidence captured for this intermediate stage in the Cluster Report.
                        </p>
                      )}
                      {selectedStage.metrics && Object.keys(selectedStage.metrics).length > 0 && (
                        <div>
                          <span className="text-[10px] text-muted-foreground block mb-1">Stage metrics:</span>
                          <pre className="text-[10px] font-mono bg-muted/40 p-2 rounded overflow-x-auto max-h-[140px]">
                            {JSON.stringify(selectedStage.metrics, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      Click any stage in the <strong>Flow</strong> or <strong>Timeline</strong> diagrams to inspect its underlying snapshot rows, node identity, and metrics.
                    </p>
                  )}
                </div>
              </div>

              {trace.limitations && trace.limitations.length > 0 && (
                <p className="text-[10px] text-muted-foreground italic">{trace.limitations.join(" ")}</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
