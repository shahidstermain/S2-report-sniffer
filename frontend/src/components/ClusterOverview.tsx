import { Server, HardDrive, MemoryStick, AlertTriangle, Clock, ExternalLink, Database, Activity } from "lucide-react";
import { formatBytes, formatUptime, formatNumber, severityBadgeClass } from "@/lib/utils-sdb";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import NodeDownDetails from "./NodeDownDetails";
import ClusterStatePanel from "./ClusterStatePanel";
import ClusterTopologyMap from "./ClusterTopologyMap";
import QueryPatternsPanel from "./QueryPatternsPanel";
import ReplicationLagPanel from "./ReplicationLagPanel";

export default function ClusterOverview({ reportId, overview }) {
  if (!overview) return null;
  const co = overview.cluster_overview || {};
  const recs = overview.recommendations || [];
  const events = overview.events || [];
  const logSummary = overview.log_summary || {};
  const dbDiskUsage = overview.database_disk_usage || [];
  const detectedPatterns = overview.detected_log_patterns || [];
  const license = overview.config_health?.license || {};
  const dmesgEvents = overview.dmesg_events || [];
  const clusterLayout = overview.cluster_layout || {};
  const logTimeframe = overview.log_timeframe || {};
  const backupSummary = overview.backup_summary || {};
  const processHealth = overview.process_health || {};

  const criticalRecs = recs.filter(r => r.severity === "critical");
  const warningRecs = recs.filter(r => r.severity === "warning");
  const usedDiskMb = (co.total_disk_mb || 0) - (co.available_disk_mb || 0);

  const nodeEvents = overview.node_events || [];
  const rebalanceEvents = overview.rebalance_events || null;

  const backupOk = backupSummary.success_count || 0;
  const backupFail = backupSummary.failure_count || 0;
  const backupTotal = backupSummary.total || 0;
  const backupAlert = backupFail > 0;

  const activeQueries = processHealth.active_count || 0;
  const sleepingTx = processHealth.sleeping_open_tx_count || 0;
  const processAlert = sleepingTx > 0;

  const totalPartitions = clusterLayout.total_partitions || 0;

  const logPerNode = logTimeframe.per_node || {};
  const fmtTs = (ts) => ts?.slice(0, 16) ?? "";

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      {/* Top Metric Cards */}
      <Card className="overflow-hidden shadow-sm">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 divide-x divide-y divide-border">
          <MetricCard label="Nodes" value={co.total_nodes || 0} sub={`${co.online_nodes || 0} online / ${co.offline_nodes || 0} offline`} icon={Server} testId="metric-nodes" />
          <MetricCard label="Topology" value={`${co.leaves || 0}L / ${co.aggregators || 0}A`} sub={`AG: ${(co.availability_groups || []).join(", ") || "—"}`} icon={Server} testId="metric-topology" />
          <MetricCard label="Memory" value={`${co.memory_used_pct || 0}%`} sub={`${formatBytes(co.used_memory_mb)} of ${formatBytes(co.total_memory_mb)}`} icon={MemoryStick} testId="metric-memory"
            alert={co.memory_used_pct > 80} />
          <MetricCard label="Disk Used" value={`${co.disk_used_pct || 0}%`} sub={`${formatBytes(usedDiskMb)} of ${formatBytes(co.total_disk_mb)}`} icon={HardDrive} testId="metric-disk"
            alert={co.disk_used_pct > 80} />
          <MetricCard label="Backups"
            value={backupTotal > 0 ? `${backupOk}/${backupTotal}` : "—"}
            sub={backupTotal > 0 ? `${backupFail} failed` : "No history"}
            icon={Database} testId="metric-backups" alert={backupAlert} />
          <MetricCard label="Queries"
            value={activeQueries > 0 ? `${activeQueries} active` : "Idle"}
            sub={sleepingTx > 0 ? `${sleepingTx} sleeping open tx` : "No open tx"}
            icon={Activity} testId="metric-queries" alert={processAlert} />
        </div>
      </Card>

      {/* Issues Summary - Critical/Warning */}
      {recs.length > 0 && (
        <Card className="shadow-sm overflow-hidden">
          <CardHeader className="border-b py-3">
            <div className="flex flex-wrap items-center gap-2">
              <AlertTriangle className={cn("h-4 w-4", criticalRecs.length > 0 ? "text-[var(--ss-critical)]" : "text-[var(--ss-warning)]")} />
              <CardTitle className="text-sm font-bold tracking-tight">
                Issues Detected ({recs.length})
              </CardTitle>
              <Badge variant="critical">{criticalRecs.length} critical</Badge>
              <Badge variant="warning">{warningRecs.length} warning</Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y divide-border">
              {recs.slice(0, 6).map((rec) => (
                <div key={rec.id} className="flex items-start gap-3 px-4 py-3">
                  <div className={cn(
                    "w-1 self-stretch flex-shrink-0 rounded-full",
                    rec.severity === "critical" ? "bg-[var(--red-bright)]" : "bg-[var(--amber-bright)]"
                  )} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={rec.severity === "critical" ? "critical" : rec.severity === "warning" ? "warning" : "info"}>
                        {rec.severity}
                      </Badge>
                      <span className="text-[10px] uppercase tracking-widest text-muted-foreground">{rec.category}</span>
                      {rec.doc_link && (
                        <a href={rec.doc_link} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-0.5 text-[10px] text-primary underline">
                          <ExternalLink data-icon="inline-start" /> Docs
                        </a>
                      )}
                    </div>
                    <p className="text-sm font-medium mt-1">{rec.title}</p>
                    <p className="text-xs mt-0.5 text-muted-foreground">{rec.description}</p>
                    {rec.remediation && (
                      <p className="text-xs mt-1 italic text-primary">{rec.remediation}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Interactive Cluster Topology Map */}
      <ClusterTopologyMap
        clusterLayout={clusterLayout}
        clusterOverview={co}
        nodeEvents={nodeEvents}
        replicationStatus={overview.replication_status}
      />

      {/* Offline node deep-dive: only renders when nodes are not ONLINE */}
      <NodeDownDetails
        nodeEvents={nodeEvents}
        nodesDetail={co.nodes_detail}
        dmesgEvents={dmesgEvents}
        detectedLogPatterns={detectedPatterns}
        logTimeframe={logTimeframe}
      />

      {/* Rebalance / partition state: only renders when there is activity or non-IDLE status */}
      <ClusterStatePanel rebalanceEvents={rebalanceEvents} />

      {/* Phase 3.2: Query Pattern Analysis */}
      <QueryPatternsPanel queryPatterns={overview.query_patterns} />

      {/* Phase 3.2: Replication Lag Analysis */}
      <ReplicationLagPanel replicationLagPatterns={overview.replication_lag_patterns} />

      {/* Log Coverage Strip */}
      {Object.keys(logPerNode).length > 0 && (
        <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Inter, sans-serif" }}>
              Tracelog Coverage by Node
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
              Tracelog time window per node — short coverage may limit diagnostic accuracy.
              {logTimeframe.cluster_first && (
                <span className="ml-2 font-mono">
                  Cluster window: {fmtTs(logTimeframe.cluster_first)} → {fmtTs(logTimeframe.cluster_last)}
                </span>
              )}
            </p>
          </div>
          <div className="divide-y" style={{ borderColor: "var(--divider-light)" }}>
            {Object.entries(logPerNode).map(([hostname, tf]) => {
              const hours = tf.coverage_hours || 0;
              const coverageColor = hours === 0 ? "var(--ss-mid-gray)" : hours < 1 ? "var(--ss-critical)" : hours < 4 ? "var(--ss-warning)" : "var(--ss-success)";
              const coveragePct = Math.min(100, hours > 0 ? Math.round((hours / 168) * 100) : 0);
              return (
                <div key={hostname} className="flex items-center gap-3 px-4 py-2">
                  <span className="text-[11px] font-mono w-36 truncate" style={{ color: "var(--text-body)" }} title={hostname}>{hostname.split('.')[0]}</span>
                  <div className="flex-1 progress-bar">
                    <div className="progress-fill" style={{ width: `${coveragePct}%`, background: coverageColor }} />
                  </div>
                  <span className="text-[11px] font-mono w-16 text-right font-bold" style={{ color: coverageColor }}>
                    {hours > 0 ? `${hours}h` : "No logs"}
                  </span>
                  {tf.first_log_entry && (
                    <span className="text-[10px] font-mono hidden lg:block" style={{ color: "var(--ss-mid-gray)", minWidth: "11rem" }}>
                      {fmtTs(tf.first_log_entry)} → {fmtTs(tf.last_log_entry)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Database Disk Usage + Detected Patterns side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border" style={{ borderColor: "var(--ss-divider)" }}>
        {/* DB Disk Usage */}
        <div className="border-r" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Inter, sans-serif" }}>
              Database Storage
            </h3>
          </div>
          {dbDiskUsage.length > 0 ? (
            <div className="p-4">
              {dbDiskUsage.sort((a, b) => parseFloat(b.TOTAL_DISK_USAGE_GB || 0) - parseFloat(a.TOTAL_DISK_USAGE_GB || 0)).map((db, i) => {
                const gb = parseFloat(db.TOTAL_DISK_USAGE_GB || 0);
                const maxGb = parseFloat(dbDiskUsage[0]?.TOTAL_DISK_USAGE_GB || 1);
                const pct = maxGb > 0 ? (gb / maxGb) * 100 : 0;
                return (
                  <div key={i} className="flex items-center gap-3 mb-1.5">
                    <span className="text-[11px] font-mono w-32 truncate" title={db.DATABASE_NAME}>{db.DATABASE_NAME}</span>
                    <div className="flex-1 progress-bar">
                      <div className="progress-fill" style={{ width: `${pct}%`, background: "var(--ss-purple)" }} />
                    </div>
                    <span className="text-[11px] font-mono w-16 text-right font-bold">{gb.toFixed(1)} GB</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="p-4 text-xs" style={{ color: "var(--ss-mid-gray)" }}>No storage data available</p>
          )}
        </div>

        {/* Detected Log Patterns */}
        <div style={{ background: "var(--ss-white)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Inter, sans-serif" }}>
              Critical Tracelog Patterns
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
              Patterns matched against known SingleStore failure signatures
            </p>
          </div>
          {detectedPatterns.length > 0 ? (
            <div className="divide-y" style={{ borderColor: "var(--divider-light)" }}>
              {detectedPatterns.map((pat, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${severityBadgeClass(pat.severity)}`}>
                      {pat.severity}
                    </span>
                    <span className="text-sm font-medium">{pat.title}</span>
                    <span className="text-[10px] font-mono" style={{ color: "var(--ss-mid-gray)" }}>×{pat.count}</span>
                  </div>
                  <p className="text-xs mt-1" style={{ color: "var(--text-body)" }}>{pat.conclusion}</p>
                  {pat.nodes?.length > 0 && (
                    <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
                      Nodes: {pat.nodes.join(", ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="p-4 text-xs" style={{ color: "var(--ss-mid-gray)" }}>No critical patterns detected</p>
          )}
        </div>
      </div>

      {/* Events & Log Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border" style={{ borderColor: "var(--ss-divider)" }}>
        {/* Events */}
        <div className="border-r" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Inter, sans-serif" }}>
              Cluster State Events — MV_EVENTS ({events.length})
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
              Significant state changes recorded by SingleStore
            </p>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {events.length === 0 ? (
              <p className="p-4 text-xs" style={{ color: "var(--ss-mid-gray)" }}>No events</p>
            ) : (
              <table className="w-full dense-table">
                <thead>
                  <tr>
                    <th className="text-left">Time</th>
                    <th className="text-left">Severity</th>
                    <th className="text-left">Type</th>
                    <th className="text-left">Node</th>
                  </tr>
                </thead>
                <tbody>
                  {events.slice(0, 30).map((ev, i) => (
                    <tr key={i}>
                      <td className="text-[11px]">{ev.EVENT_TIME || "—"}</td>
                      <td>
                        <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${
                          (ev.SEVERITY || "").includes("ERROR") ? "badge-critical" :
                          (ev.SEVERITY || "").includes("WARN") ? "badge-warning" : "badge-healthy"
                        }`}>{ev.SEVERITY}</span>
                      </td>
                      <td className="text-[11px]">{ev.EVENT_TYPE || "—"}</td>
                      <td className="text-[11px]">{ev.ORIGIN_NODE_ID || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Log Summary */}
        <div style={{ background: "var(--ss-white)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Log Summary
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
              Correlated ERROR spikes across nodes indicate cluster-wide events
            </p>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-2 gap-3">
              {Object.entries(logSummary.severity_counts || {}).map(([sev, count]) => (
                <div key={sev} className="flex items-center justify-between border px-3 py-2" style={{ borderColor: "var(--ss-divider)" }}>
                  <span className={`text-[10px] uppercase tracking-widest font-bold ${
                    sev === "ERROR" || sev === "FATAL" ? "status-critical" :
                    sev === "WARN" ? "status-warning" : "text-zinc-500"
                  }`}>{sev}</span>
                  <span className="text-sm font-mono font-bold">{formatNumber(count)}</span>
                </div>
              ))}
            </div>
            {/* Per-node breakdown */}
            <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--divider-light)" }}>
              <p className="text-[9px] uppercase tracking-widest font-bold mb-2" style={{ color: "var(--ss-mid-gray)" }}>
                Error Count & Tracelog Window per Node
              </p>
              {Object.entries(logSummary.per_node || {}).map(([node, counts]) => {
                const errs = (counts.ERROR || 0) + (counts.FATAL || 0);
                return (
                  <div key={node} className="mb-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] font-mono truncate max-w-[10rem] sm:max-w-[12rem]" style={{ color: "#525252" }}>{node.split('.')[0]}</span>
                      {errs > 0 ? (
                        <span className="text-[10px] font-mono font-bold status-critical">{errs} errors</span>
                      ) : (
                        <span className="text-[10px] font-mono" style={{ color: "var(--ss-success)" }}>0 errors</span>
                      )}
                      {counts.WARN > 0 && (
                        <span className="text-[10px] font-mono status-warning">{counts.WARN} warn</span>
                      )}
                    </div>
                    {(counts.first_ts || counts.last_ts) && (
                      <p className="text-[9px] font-mono ml-0.5" style={{ color: "var(--ss-mid-gray)" }}>
                        {counts.first_ts || "?"} → {counts.last_ts || "?"}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="text-xs mt-2" style={{ color: "var(--ss-mid-gray)" }}>
              Total: {formatNumber(logSummary.total)} entries across {Object.keys(logSummary.per_node || {}).length} nodes
            </p>
          </div>
        </div>
      </div>

      {/* Dmesg Critical Events */}
      {dmesgEvents.length > 0 && (
        <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              OS Kernel Events (dmesg)
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
              OOM kills, storage errors, and CPU lockups from the kernel ring buffer
            </p>
          </div>
          <div className="divide-y max-h-48 overflow-y-auto" style={{ borderColor: "var(--divider-light)" }}>
            {dmesgEvents.slice(0, 20).map((evt, i) => (
              <div key={i} className="flex items-start gap-3 px-4 py-2">
                <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 flex-shrink-0 ${severityBadgeClass(evt.severity)}`}>
                  {evt.severity}
                </span>
                <div className="min-w-0">
                  <p className="text-xs font-medium">{evt.title} — {evt.hostname}</p>
                  <p className="text-[10px] font-mono mt-0.5 truncate" style={{ color: "var(--text-body)" }} title={evt.line}>{evt.line}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, sub, icon: Icon, testId, alert }) {
  return (
    <div
      className={cn("p-4 bg-card", alert && "bg-destructive/5")}
      data-testid={testId}
    >
      <div className="flex items-center gap-1.5 mb-2">
        <Icon className={cn(alert ? "text-[var(--ss-critical)]" : "text-muted-foreground")} />
        <span className="text-[10px] uppercase tracking-[0.2em] font-bold text-muted-foreground">{label}</span>
      </div>
      <p className={cn(
        "text-xl font-mono font-bold tracking-tight",
        alert && "text-[var(--ss-critical)]"
      )}>{value}</p>
      <p className="text-[11px] mt-0.5 text-muted-foreground">{sub}</p>
    </div>
  );
}

function MiniBar({ label, pct, value }) {
  const color = pct > 90 ? "var(--ss-critical)" : pct > 75 ? "var(--ss-warning)" : "#00C853";
  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] uppercase tracking-widest font-bold w-8" style={{ color: "var(--ss-mid-gray)" }}>{label}</span>
      <div className="flex-1 progress-bar">
        <div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
      <span className="text-[10px] font-mono w-24 text-right" style={{ color: pct > 85 ? "var(--ss-critical)" : "#525252" }}>{value}</span>
    </div>
  );
}
