import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Long-Running Transactions & Lock Contention Panel
 * Shows long-running tx, lock waiting, blocking chains, and unkillable queries.
 */

interface LongTxEntry {
  duration_sec: number;
  trx_state: string;
  trx_name: string;
  query_text: string;
  user: string;
  database: string;
  node_id: string;
}

interface LockWaitingEntry {
  duration_sec: number;
  query_text: string;
  user: string;
}

interface LongRunningTransactionsPanelProps {
  longRunningTransactions?: {
    long_running_tx?: LongTxEntry[];
    max_tx_duration_sec?: number;
    long_tx_count?: number;
    lock_waiting_count?: number;
    blocking_chains?: number;
    largest_chain_size?: number;
    has_unkillable?: boolean;
    lock_contention_level?: "none" | "moderate" | "severe";
  };
}

export default function LongRunningTransactionsPanel({ longRunningTransactions }: LongRunningTransactionsPanelProps) {
  if (!longRunningTransactions) return null;

  const level = longRunningTransactions.lock_contention_level || "none";
  const longTx = longRunningTransactions.long_running_tx || [];
  const lockCount = longRunningTransactions.lock_waiting_count || 0;
  const chains = longRunningTransactions.blocking_chains || 0;
  const largestChain = longRunningTransactions.largest_chain_size || 0;
  const unkillable = longRunningTransactions.has_unkillable || false;
  const maxDuration = longRunningTransactions.max_tx_duration_sec || 0;

  if (level === "none" && longTx.length === 0 && lockCount === 0 && chains === 0) {
    return null;
  }

  const levelConfig = {
    severe: { variant: "critical" as const, label: "Severe", color: "#F44336" },
    moderate: { variant: "warning" as const, label: "Moderate", color: "#FF9800" },
    none: { variant: "info" as const, label: "None", color: "#00C853" },
  };
  const config = levelConfig[level] || levelConfig.none;

  return (
    <Card className="shadow-sm">
      <CardHeader className="border-b py-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <CardTitle className="text-sm font-bold tracking-tight">Long-Running Transactions & Lock Contention</CardTitle>
            <CardDescription>
              {longTx.length > 0 && `${longTx.length} long tx (max ${maxDuration}s) · `}
              {lockCount > 0 && `${lockCount} lock waits · `}
              {chains > 0 && `${chains} blocking chains (largest: ${largestChain})`}
              {longTx.length === 0 && lockCount === 0 && chains === 0 && "No issues detected"}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Badge variant={config.variant}>Contention: {config.label}</Badge>
            {unkillable && <Badge variant="critical">⚠ Unkillable</Badge>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {/* Summary stats */}
        <div className="grid grid-cols-4 divide-x divide-border border-b">
          <StatBlock label="Long TX" value={String(longTx.length || 0)} />
          <StatBlock label="Lock Waits" value={String(lockCount)} />
          <StatBlock label="Block Chains" value={String(chains)} />
          <StatBlock label="Largest Chain" value={String(largestChain)} />
        </div>

        {/* Unkillable warning */}
        {unkillable && (
          <div className="px-4 py-3 bg-red-50 dark:bg-red-950/20 border-l-4 border-l-red-500">
            <div className="flex items-start gap-2">
              <span className="text-red-600 dark:text-red-400 text-sm">⚠</span>
              <div>
                <p className="text-xs font-bold text-red-700 dark:text-red-400">
                  Unkillable Transaction Detected
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  This transaction cannot be terminated with KILL and may require an engine restart.
                  Contact SingleStore support if KILL does not resolve it.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Long-running transactions */}
        {longTx.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 bg-amber-50 dark:bg-amber-950/20">
              <span className="text-xs font-bold text-amber-700 dark:text-amber-400">
                ⏱ Long-Running Transactions ({" > "}60s)
              </span>
            </div>
            <div className="divide-y divide-border">
              {longTx.slice(0, 5).map((tx, i) => (
                <div key={i} className="px-4 py-3 border-l-4 border-l-amber-500">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono font-bold">{tx.duration_sec}s</span>
                      <Badge variant="info">{tx.trx_state}</Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">{tx.user}@{tx.database}</span>
                  </div>
                  <p className="text-xs font-mono text-muted-foreground truncate" title={tx.query_text}>
                    {tx.query_text}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Severe contention info */}
        {level === "severe" && !unkillable && (
          <div className="px-4 py-3 bg-red-50 dark:bg-red-950/20 border-l-4 border-l-red-500">
            <p className="text-xs font-bold text-red-700 dark:text-red-400">
              Severe Lock Contention — chain size {largestChain}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Large blocking chains can stall the entire workload. Identify and terminate the root blocking transaction.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-4 py-3 text-center">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className="text-lg font-bold font-mono">{value}</div>
    </div>
  );
}