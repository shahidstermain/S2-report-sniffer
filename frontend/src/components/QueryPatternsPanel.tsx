import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils-sdb";
import InfoHint from "./InfoHint";
import QueryTracerPanel, { TraceSelector } from "./QueryTracerPanel";

/**
 * Query Pattern Analysis Panel
 * Shows long-running queries, queries exceeding Sniffer thresholds, repeated queries,
 * and memory usage from processlist analysis.
 */

interface QueryEntry {
  elapsed_sec: number;
  query_text: string;
  normalized?: string;
  user: string;
  database: string;
  memory_used_mb: number;
  node_id: string;
}

interface RepeatedPattern {
  normalized_sql: string;
  count: number;
  max_elapsed_sec: number;
  sample_query: string;
}

interface QueryPatternsPanelProps {
  reportId?: string;
  queryPatterns?: {
    slow_queries?: QueryEntry[];
    runaway_queries?: QueryEntry[];
    top_by_memory?: QueryEntry[];
    repeated_patterns?: RepeatedPattern[];
    slow_count?: number;
    runaway_count?: number;
    max_elapsed_sec?: number;
    total_memory_used_mb?: number;
  };
  onTrace?: (selector: TraceSelector) => void;
}

export default function QueryPatternsPanel({ reportId, queryPatterns, onTrace }: QueryPatternsPanelProps) {
  const [traceSelector, setTraceSelector] = useState<TraceSelector | null>(null);

  const openTrace = (selector: TraceSelector) => {
    if (onTrace) {
      onTrace(selector);
      return;
    }
    setTraceSelector(selector);
  };

  if (!queryPatterns) return null;

  // These property names are stable backend API fields. User-facing text uses
  // SingleStore documentation terminology.
  const thresholdQueries = queryPatterns.slow_queries || [];
  const longRunningQueries = queryPatterns.runaway_queries || [];
  const repeated = queryPatterns.repeated_patterns || [];
  const topMem = queryPatterns.top_by_memory || [];

  if (thresholdQueries.length === 0 && longRunningQueries.length === 0 && repeated.length === 0 && topMem.length === 0) {
    return null;
  }

  return (
    <Card className="shadow-sm">
      {reportId && traceSelector && (
        <QueryTracerPanel
          reportId={reportId}
          selector={traceSelector}
          onClose={() => setTraceSelector(null)}
        />
      )}
      <CardHeader className="border-b py-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="flex items-center gap-1">
              <CardTitle className="text-sm font-bold tracking-tight">Query Pattern Analysis</CardTitle>
              <InfoHint
                label="query pattern analysis"
                content="Snapshot of long-running queries, queries in the Sniffer 30-second to 5-minute elapsed-time band, repeated query patterns, and high-memory queries from processlist collectors. SingleStore documentation describes long-running queries without prescribing one universal duration threshold."
              />
            </div>
            <CardDescription>
              {longRunningQueries.length > 0 && `${longRunningQueries.length} long-running (>5 min) · `}
              {thresholdQueries.length > 0 && `${thresholdQueries.length} above Sniffer threshold · `}
              {repeated.length > 0 && `${repeated.length} repeated pattern${repeated.length > 1 ? "s" : ""}`}
              {longRunningQueries.length === 0 && thresholdQueries.length === 0 && repeated.length === 0 && "Query memory analysis"}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {longRunningQueries.length > 0 && <Badge variant="critical">{longRunningQueries.length} long-running</Badge>}
            {thresholdQueries.length > 0 && <Badge variant="warning">{thresholdQueries.length} above threshold</Badge>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* Long-running queries: Sniffer heuristic, elapsed time greater than 5 minutes. */}
        {longRunningQueries.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-red-50 dark:bg-red-950/20">
              <span className="text-xs font-bold text-red-700 dark:text-red-400">⚠ Long-Running Queries ({" > "}5 min)</span>
            </div>
            <div className="divide-y divide-border">
              {longRunningQueries.slice(0, 5).map((q, i) => (
                <QueryRow
                  key={`long-running-${i}`}
                  entry={q}
                  variant="critical"
                  onTrace={reportId ? () => openTrace({ query_text: q.query_text, normalized_sql: q.normalized }) : undefined}
                />
              ))}
            </div>
          </div>
        )}

        {/* Queries in the Sniffer elapsed-time threshold band. */}
        {thresholdQueries.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-amber-50 dark:bg-amber-950/20">
              <span className="text-xs font-bold text-amber-700 dark:text-amber-400">⏱ Queries Above the Sniffer Elapsed-Time Threshold (30s–5 min)</span>
            </div>
            <div className="divide-y divide-border">
              {thresholdQueries.slice(0, 5).map((q, i) => (
                <QueryRow
                  key={`threshold-${i}`}
                  entry={q}
                  variant="warning"
                  onTrace={reportId ? () => openTrace({ query_text: q.query_text, normalized_sql: q.normalized }) : undefined}
                />
              ))}
            </div>
          </div>
        )}

        {repeated.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-blue-50 dark:bg-blue-950/20">
              <span className="text-xs font-bold text-blue-700 dark:text-blue-400">🔄 Repeated Query Patterns (≥3 occurrences)</span>
            </div>
            <div className="divide-y divide-border">
              {repeated.slice(0, 5).map((pat, i) => (
                <div key={`repeated-${i}`} className="px-4 py-3">
                  <div className="flex items-center justify-between mb-1">
                    <Badge variant="info">{pat.count}x</Badge>
                    <span className="text-xs font-mono text-muted-foreground">max {pat.max_elapsed_sec}s</span>
                  </div>
                  <p className="text-xs font-mono text-muted-foreground truncate" title={pat.sample_query}>
                    {pat.sample_query}
                  </p>
                  {reportId && (
                    <button
                      type="button"
                      className="mt-2 text-[10px] uppercase font-bold px-2 py-1 border border-border text-[#00d992] hover:bg-muted/40"
                      onClick={() => openTrace({ query_text: pat.sample_query, normalized_sql: pat.normalized_sql })}
                    >
                      Trace query
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {topMem.length > 0 && topMem[0].memory_used_mb > 0 && (
          <div>
            <div className="px-4 py-2 bg-purple-50 dark:bg-purple-950/20">
              <span className="text-xs font-bold text-purple-700 dark:text-purple-400">💾 Queries with Highest Memory Use</span>
            </div>
            <div className="divide-y divide-border">
              {topMem.slice(0, 5).map((q, i) => (
                <QueryRow
                  key={`mem-${i}`}
                  entry={q}
                  variant="memory"
                  onTrace={reportId ? () => openTrace({ query_text: q.query_text, normalized_sql: q.normalized }) : undefined}
                />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function QueryRow({
  entry,
  variant,
  onTrace,
}: {
  entry: QueryEntry;
  variant: "critical" | "warning" | "memory";
  onTrace?: () => void;
}) {
  const colorClass =
    variant === "critical"
      ? "border-l-red-500"
      : variant === "warning"
      ? "border-l-amber-500"
      : "border-l-purple-500";

  return (
    <div className={cn("px-4 py-3 border-l-4", colorClass)}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono font-bold">{entry.elapsed_sec}s</span>
          {entry.memory_used_mb > 0 && (
            <span className="text-xs font-mono text-muted-foreground">{formatNumber(Math.round(entry.memory_used_mb))} MB</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{entry.user}@{entry.database}</span>
          {entry.node_id && <span className="font-mono">node:{entry.node_id}</span>}
        </div>
      </div>
      <p className="text-xs font-mono text-muted-foreground truncate" title={entry.query_text}>
        {entry.query_text}
      </p>
      {onTrace && (
        <button
          type="button"
          className="mt-2 text-[10px] uppercase font-bold px-2 py-1 border border-border text-[#00d992] hover:bg-muted/40"
          onClick={onTrace}
        >
          Trace query
        </button>
      )}
    </div>
  );
}
