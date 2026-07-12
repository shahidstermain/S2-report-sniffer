import { useCallback, useEffect, useState } from "react";
import { Loader2, X, AlertTriangle } from "lucide-react";
import { getQueryTrace, resolveQueryTrace } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import QueryTraceFlowDiagram, { TraceStage } from "./QueryTraceFlowDiagram";
import QueryTraceTimeline, { TraceTimeline } from "./QueryTraceTimeline";
import InfoHint from "./InfoHint";

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
  "This trace is reconstructed from a point-in-time bundle, not live query profiling. Stages marked dashed are inferred.";

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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" data-testid="query-tracer-panel">
      <div className="w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-lg border border-border bg-background shadow-xl flex flex-col">
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-bold tracking-tight">Query Tracer</h3>
              <InfoHint
                label="query tracer"
                content="Reconstructed from point-in-time bundle snapshots. Dashed stages are inferred; solid stages have direct evidence."
              />
              {trace && (
                <Badge variant={TIER_VARIANT[trace.confidence.tier] || "info"}>
                  {trace.confidence.score}% {trace.confidence.tier}
                </Badge>
              )}
              {trace?.trace_type && <Badge variant="outline">{trace.trace_type}</Badge>}
              {trace?.routing?.label && <Badge variant="info">{trace.routing.label}</Badge>}
            </div>
            <p className="text-xs text-muted-foreground truncate mt-1" title={trace?.query_text || selector.query_text}>
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
                  <div className="grid sm:grid-cols-2 gap-3">
                    <div className="rounded border border-border p-3">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Trace type</p>
                      <p className="font-semibold">{trace.trace_type}</p>
                    </div>
                    <div className="rounded border border-border p-3">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Routing</p>
                      <p className="font-semibold">{trace.routing?.label || "—"}</p>
                      {trace.routing?.reason && <p className="text-muted-foreground mt-1">{trace.routing.reason}</p>}
                    </div>
                  </div>
                  <div className="rounded border border-border p-3">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Stage overview</p>
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
                            "px-2 py-1 rounded border text-[10px]",
                            stage.observed ? "border-[#00d992]" : "border-dashed border-muted-foreground",
                            stage.status === "critical" && "text-red-400"
                          )}
                        >
                          {stage.label}
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
                  <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                    Confidence factors
                  </h4>
                  <ul className="space-y-1 text-xs">
                    {trace.confidence.factors.map((f) => (
                      <li key={f.id} className="flex justify-between gap-2">
                        <span className={cn(!f.present && "text-muted-foreground")}>{f.label}</span>
                        <span className="font-mono">{f.weight > 0 ? `+${f.weight}` : f.weight}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="rounded border border-border p-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                    {selectedStage ? `Evidence — ${selectedStage.label}` : "Select a stage"}
                  </h4>
                  {selectedStage ? (
                    <div className="text-xs space-y-2">
                      <p>
                        <span className="text-muted-foreground">Status:</span> {selectedStage.status}
                      </p>
                      <p>
                        <span className="text-muted-foreground">Layer:</span>{" "}
                        {selectedStage.observed ? "observed (solid)" : "inferred (dashed)"}
                      </p>
                      {selectedStage.evidence && selectedStage.evidence.length > 0 ? (
                        <pre className="text-[10px] font-mono bg-muted/40 p-2 rounded overflow-x-auto">
                          {JSON.stringify(selectedStage.evidence, null, 2)}
                        </pre>
                      ) : (
                        <p className="text-muted-foreground">No direct evidence rows for this stage.</p>
                      )}
                      {selectedStage.metrics && Object.keys(selectedStage.metrics).length > 0 && (
                        <pre className="text-[10px] font-mono bg-muted/40 p-2 rounded overflow-x-auto">
                          {JSON.stringify(selectedStage.metrics, null, 2)}
                        </pre>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Click a flow or timeline event to inspect evidence and metrics.
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
    </div>
  );
}
