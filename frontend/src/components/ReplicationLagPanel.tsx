import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Replication Lag Analysis Panel
 * Shows lagging pairs, async transitions, and overall replication state.
 */

interface LaggingPair {
  master: string;
  slave: string;
  role: string;
  lag_sec: number;
  severity: "warning" | "critical";
}

interface ReplicationLagPanelProps {
  replicationLagPatterns?: {
    lagging_pairs?: LaggingPair[];
    max_lag_sec?: number;
    avg_lag_sec?: number;
    lagging_count?: number;
    async_transitions?: number;
    replication_state?: "healthy" | "degraded" | "critical";
  };
}

const STATE_CONFIG = {
  healthy: { color: "#00C853", label: "Healthy", variant: "info" as const },
  degraded: { color: "#FF9800", label: "Degraded", variant: "warning" as const },
  critical: { color: "#F44336", label: "Critical", variant: "critical" as const },
};

export default function ReplicationLagPanel({ replicationLagPatterns }: ReplicationLagPanelProps) {
  if (!replicationLagPatterns) return null;

  const state = replicationLagPatterns.replication_state || "healthy";
  const lagging = replicationLagPatterns.lagging_pairs || [];
  const asyncCount = replicationLagPatterns.async_transitions || 0;
  const maxLag = replicationLagPatterns.max_lag_sec || 0;
  const avgLag = replicationLagPatterns.avg_lag_sec || 0;

  // Don't render if everything is healthy and no async transitions
  if (state === "healthy" && lagging.length === 0 && asyncCount === 0) {
    return null;
  }

  const config = STATE_CONFIG[state] || STATE_CONFIG.healthy;

  return (
    <Card className="shadow-sm">
      <CardHeader className="border-b py-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <CardTitle className="text-sm font-bold tracking-tight">Replication Lag Analysis</CardTitle>
            <CardDescription>
              {lagging.length > 0
                ? `${lagging.length} lagging pair${lagging.length > 1 ? "s" : ""}`
                : asyncCount > 0
                ? `${asyncCount} async transition${asyncCount > 1 ? "s" : ""}`
                : "All pairs within healthy range"}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Badge variant={config.variant}>{config.label}</Badge>
            {asyncCount > 0 && <Badge variant="critical">{asyncCount} async</Badge>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* Summary stats */}
        <div className="grid grid-cols-3 divide-x divide-border border-b">
          <StatBlock label="Max Lag" value={`${maxLag}s`} color={state === "critical" ? "#F44336" : state === "degraded" ? "#FF9800" : "#00C853"} />
          <StatBlock label="Avg Lag" value={`${avgLag}s`} />
          <StatBlock label="Lagging Pairs" value={String(replicationLagPatterns.lagging_count || 0)} />
        </div>

        {/* Lagging pairs table */}
        {lagging.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-slate-50 dark:bg-slate-900">
              <span className="text-xs font-bold">Lagging Replication Pairs</span>
            </div>
            <div className="divide-y divide-border">
              {lagging.slice(0, 10).map((pair, i) => (
                <div key={i} className="px-4 py-2 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-mono">
                    <span className="font-bold">{pair.master}</span>
                    <span className="text-muted-foreground">→</span>
                    <span>{pair.slave}</span>
                    {pair.role && <span className="text-muted-foreground">({pair.role})</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "text-xs font-mono font-bold",
                        pair.severity === "critical" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"
                      )}
                    >
                      {pair.lag_sec}s
                    </span>
                    <Badge variant={pair.severity === "critical" ? "critical" : "warning"}>
                      {pair.severity}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Async transitions warning */}
        {asyncCount > 0 && (
          <div className="px-4 py-3 bg-red-50 dark:bg-red-950/20 border-l-4 border-l-red-500">
            <div className="flex items-start gap-2">
              <span className="text-red-600 dark:text-red-400 text-sm">⚠</span>
              <div>
                <p className="text-xs font-bold text-red-700 dark:text-red-400">
                  {asyncCount} Sync→Async Replication Transition{asyncCount > 1 ? "s" : ""} Detected
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Transitions from synchronous to asynchronous replication indicate network or node stress.
                  Investigate network stability between master and leaf nodes.
                </p>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatBlock({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="px-4 py-3 text-center">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className="text-lg font-bold font-mono" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  );
}