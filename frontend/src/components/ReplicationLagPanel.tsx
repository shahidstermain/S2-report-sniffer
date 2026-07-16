import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import InfoHint from "./InfoHint";

/**
 * Replication Lag Analysis Panel
 * Shows lagging pairs, async transitions, and overall replication state.
 */

interface LaggingPair {
  master: string;
  slave: string;
  role?: string;
  lag_sec: number | null;
  lsn_position_delta?: number | null;
  severity: "warning" | "critical" | "unknown";
  lag_known?: boolean;
}

interface ReplicationLagPanelProps {
  replicationLagPatterns?: {
    lagging_pairs?: LaggingPair[];
    unknown_lag_pairs?: LaggingPair[];
    max_lag_sec?: number | null;
    avg_lag_sec?: number | null;
    avg_lag_of?: string;
    lagging_count?: number;
    unknown_lag_count?: number;
    measured_lag_count?: number;
    async_transitions?: number;
    replication_state?: "healthy" | "degraded" | "critical" | "unknown";
  };
}

const STATE_CONFIG = {
  healthy: { color: "#00C853", label: "Healthy", variant: "info" as const },
  degraded: { color: "#FF9800", label: "Degraded", variant: "warning" as const },
  critical: { color: "#F44336", label: "Critical", variant: "critical" as const },
  unknown: { color: "#9E9E9E", label: "Unknown", variant: "info" as const },
};

export default function ReplicationLagPanel({ replicationLagPatterns }: ReplicationLagPanelProps) {
  if (!replicationLagPatterns) return null;

  const lagging = replicationLagPatterns.lagging_pairs || [];
  const unknownPairs = replicationLagPatterns.unknown_lag_pairs || [];
  const asyncCount = replicationLagPatterns.async_transitions || 0;
  const maxLag = replicationLagPatterns.max_lag_sec;
  const avgLag = replicationLagPatterns.avg_lag_sec;
  const unknownCount = replicationLagPatterns.unknown_lag_count ?? unknownPairs.length;

  // Never invent "healthy" when state is missing — derive from lag evidence.
  const state =
    replicationLagPatterns.replication_state ||
    (lagging.length > 0 ? "degraded" : "unknown");

  // Don't render if everything is healthy and no incomplete/unknown lag signals
  if (
    state === "healthy" &&
    lagging.length === 0 &&
    asyncCount === 0 &&
    unknownCount === 0
  ) {
    return null;
  }
  // No replication rows / no lag evidence at all — don't invent a panel.
  if (state === "unknown" && lagging.length === 0 && asyncCount === 0 && unknownCount === 0) {
    return null;
  }

  const config = STATE_CONFIG[state] || STATE_CONFIG.unknown;

  return (
    <Card className="shadow-sm">
      <CardHeader className="border-b py-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="flex items-center gap-1">
              <CardTitle className="text-sm font-bold tracking-tight">Replication Lag Analysis</CardTitle>
              <InfoHint
                label="replication lag analysis"
                content="Replica lag uses measured LAG_SECONDS from replication status. Missing seconds mark pairs as unknown (LSN position deltas are evidence, not seconds). Above 5s is warning and above 30s is critical (Sniffer bands; docs document a 5s synchronous→asynchronous switch under stress)."
              />
            </div>
            <CardDescription>
              {lagging.length > 0
                ? `${lagging.length} lagging pair${lagging.length > 1 ? "s" : ""}`
                : unknownCount > 0
                ? `${unknownCount} pair${unknownCount > 1 ? "s" : ""} with unknown lag seconds`
                : asyncCount > 0
                ? `${asyncCount} synchronous→asynchronous transition${asyncCount > 1 ? "s" : ""}`
                : state === "unknown"
                ? "Lag seconds unavailable"
                : "All pairs within healthy range"}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Badge variant={config.variant}>{config.label}</Badge>
            {unknownCount > 0 && <Badge variant="info">{unknownCount} unknown lag</Badge>}
            {asyncCount > 0 && <Badge variant="critical">{asyncCount} sync→async</Badge>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* Summary stats */}
        <div className="grid grid-cols-3 divide-x divide-border border-b">
          <StatBlock
            label="Max Lag"
            value={formatLagValue(maxLag)}
            color={
              state === "critical"
                ? "#F44336"
                : state === "degraded"
                ? "#FF9800"
                : state === "healthy"
                ? "#00C853"
                : undefined
            }
          />
          <StatBlock
            label="Avg Lag"
            value={formatLagValue(avgLag)}
            hint={replicationLagPatterns.avg_lag_of === "lagging_pairs_only" || lagging.length > 0 ? "lagging pairs only" : undefined}
          />
          <StatBlock label="Lagging Pairs" value={String(replicationLagPatterns.lagging_count || 0)} />
        </div>

        {/* Lagging pairs table */}
        {lagging.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-slate-50 dark:bg-slate-900 flex items-center justify-between gap-2">
              <span className="text-xs font-bold">Lagging replica pairs (primary → replica)</span>
              {lagging.length > 10 && (
                <span className="text-[10px] text-muted-foreground">
                  Showing 10 of {lagging.length}
                </span>
              )}
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
                      {pair.lag_sec == null ? "—" : `${pair.lag_sec}s`}
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

        {unknownPairs.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-slate-50 dark:bg-slate-900">
              <span className="text-xs font-bold">Pairs Without Lag Seconds</span>
            </div>
            <div className="divide-y divide-border">
              {unknownPairs.slice(0, 10).map((pair, i) => (
                <div key={i} className="px-4 py-2 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-mono">
                    <span className="font-bold">{pair.master}</span>
                    <span className="text-muted-foreground">→</span>
                    <span>{pair.slave}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
                    {pair.lsn_position_delta != null ? (
                      <span>LSN Δ {pair.lsn_position_delta}</span>
                    ) : (
                      <span>lag seconds missing</span>
                    )}
                    <Badge variant="info">unknown</Badge>
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
                  {asyncCount} Synchronous → asynchronous replication transition{asyncCount > 1 ? "s" : ""} detected
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  A sync replica that fails to respond within ~5 seconds can switch to asynchronous
                  replication (documented redundancy behavior). Investigate network stability between
                  primary and replica nodes.
                </p>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function formatLagValue(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value >= 60) return `${(value / 60).toFixed(1)}m`;
  return `${value.toFixed(1)}s`;
}

function StatBlock({ label, value, color, hint }: { label: string; value: string; color?: string; hint?: string }) {
  return (
    <div className="px-4 py-3 text-center">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className="text-lg font-bold font-mono" style={color ? { color } : undefined}>
        {value}
      </div>
      {hint && <div className="text-[9px] text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  );
}