import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { listQueryTraces } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface TraceCandidate {
  trace_id: string;
  trace_type: string;
  summary: string;
  connection_id?: string | null;
  elapsed_sec?: number | null;
  failure_stage?: string | null;
  confidence: { score: number; tier: string };
}

interface QueryTracePickerProps {
  reportId: string;
  onSelectTrace: (traceId: string) => void;
}

const TIER_VARIANT: Record<string, "success" | "warning" | "critical" | "info"> = {
  high: "success",
  medium: "warning",
  low: "critical",
};

export default function QueryTracePicker({ reportId, onSelectTrace }: QueryTracePickerProps) {
  const [traces, setTraces] = useState<TraceCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listQueryTraces(reportId)
      .then((res) => {
        if (cancelled) return;
        setTraces(res.data?.traces || []);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load trace index");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  if (loading) {
    return (
      <div className="flex justify-center py-4" data-testid="query-trace-picker-loading">
        <Loader2 className="h-4 w-4 animate-spin text-[#00d992]" />
      </div>
    );
  }

  if (error) {
    return <p className="text-xs text-muted-foreground p-3">{error}</p>;
  }

  if (traces.length === 0) {
    return (
      <p className="text-xs text-muted-foreground p-3 border rounded" style={{ borderColor: "var(--ss-divider)" }}>
        No traceable queries detected in this report snapshot.
      </p>
    );
  }

  return (
    <div className="border rounded overflow-hidden" style={{ borderColor: "var(--ss-divider)" }} data-testid="query-trace-picker">
      <div className="px-3 py-2 border-b text-[10px] uppercase tracking-wider font-bold text-muted-foreground" style={{ borderColor: "var(--ss-divider)" }}>
        Traceable queries ({traces.length})
      </div>
      <div className="max-h-[220px] overflow-y-auto divide-y" style={{ borderColor: "var(--ss-divider)" }}>
        {traces.slice(0, 25).map((trace) => (
          <button
            key={trace.trace_id}
            type="button"
            data-testid={`trace-candidate-${trace.trace_id}`}
            onClick={() => onSelectTrace(trace.trace_id)}
            className="w-full text-left px-3 py-2 hover:bg-muted/40 transition-colors"
          >
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <Badge variant={TIER_VARIANT[trace.confidence.tier] || "info"}>
                {trace.confidence.score}%
              </Badge>
              <Badge variant="outline">{trace.trace_type}</Badge>
              {trace.failure_stage && <Badge variant="critical">{trace.failure_stage}</Badge>}
              {trace.elapsed_sec != null && (
                <span className="text-[10px] font-mono text-muted-foreground">{trace.elapsed_sec}s</span>
              )}
            </div>
            <p className={cn("text-[11px] font-mono truncate")} title={trace.summary}>
              {trace.summary}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
