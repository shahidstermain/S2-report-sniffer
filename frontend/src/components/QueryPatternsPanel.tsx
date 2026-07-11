import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/utils-sdb";

/**
 * Query Pattern Analysis Panel
 * Shows slow, runaway, repeated queries and memory usage from processlist analysis.
 */

interface QueryEntry {
  elapsed_sec: number;
  query_text: string;
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
}

export default function QueryPatternsPanel({ queryPatterns }: QueryPatternsPanelProps) {
  if (!queryPatterns) return null;

  const slow = queryPatterns.slow_queries || [];
  const runaway = queryPatterns.runaway_queries || [];
  const repeated = queryPatterns.repeated_patterns || [];
  const topMem = queryPatterns.top_by_memory || [];
  const maxElapsed = queryPatterns.max_elapsed_sec || 0;
  const totalMem = queryPatterns.total_memory_used_mb || 0;

  if (slow.length === 0 && runaway.length === 0 && repeated.length === 0 && topMem.length === 0) {
    return null; // Don't render if nothing interesting
  }

  return (
    <Card className="shadow-sm">
      <CardHeader className="border-b py-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <CardTitle className="text-sm font-bold tracking-tight">Query Pattern Analysis</CardTitle>
            <CardDescription>
              {runaway.length > 0 && `${runaway.length} runaway · `}
              {slow.length > 0 && `${slow.length} slow · `}
              {repeated.length > 0 && `${repeated.length} repeated pattern${repeated.length > 1 ? "s" : ""}`}
              {runaway.length === 0 && slow.length === 0 && repeated.length === 0 && "Memory usage analysis"}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {runaway.length > 0 && <Badge variant="critical">{runaway.length} runaway</Badge>}
            {slow.length > 0 && <Badge variant="warning">{slow.length} slow</Badge>}
            {totalMem > 4096 && <Badge variant="warning">{formatNumber(Math.round(totalMem))} MB</Badge>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* Runaway queries (highest priority) */}
        {runaway.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-red-50 dark:bg-red-950/20">
              <span className="text-xs font-bold text-red-700 dark:text-red-400">⚠ Runaway Queries ({" > "}5 min)</span>
            </div>
            <div className="divide-y divide-border">
              {runaway.slice(0, 5).map((q, i) => (
                <QueryRow key={`runaway-${i}`} entry={q} variant="critical" />
              ))}
            </div>
          </div>
        )}

        {/* Slow queries */}
        {slow.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-amber-50 dark:bg-amber-950/20">
              <span className="text-xs font-bold text-amber-700 dark:text-amber-400">⏱ Slow Queries (30s – 5 min)</span>
            </div>
            <div className="divide-y divide-border">
              {slow.slice(0, 5).map((q, i) => (
                <QueryRow key={`slow-${i}`} entry={q} variant="warning" />
              ))}
            </div>
          </div>
        )}

        {/* Repeated patterns */}
        {repeated.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-blue-50 dark:bg-blue-950/20">
              <span className="text-xs font-bold text-blue-700 dark:text-blue-400">🔄 Repeated Patterns (≥3 occurrences)</span>
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
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Top by memory */}
        {topMem.length > 0 && topMem[0].memory_used_mb > 0 && (
          <div>
            <div className="px-4 py-2 bg-purple-50 dark:bg-purple-950/20">
              <span className="text-xs font-bold text-purple-700 dark:text-purple-400">💾 Top Queries by Memory</span>
            </div>
            <div className="divide-y divide-border">
              {topMem.slice(0, 5).map((q, i) => (
                <QueryRow key={`mem-${i}`} entry={q} variant="memory" />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function QueryRow({ entry, variant }: { entry: QueryEntry; variant: "critical" | "warning" | "memory" }) {
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
    </div>
  );
}