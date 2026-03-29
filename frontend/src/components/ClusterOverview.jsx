import { Server, HardDrive, Cpu, MemoryStick, AlertTriangle, Clock, Shield, ExternalLink } from "lucide-react";
import { formatBytes, formatUptime, formatNumber, severityBadgeClass } from "@/lib/utils-sdb";

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

  const criticalRecs = recs.filter(r => r.severity === "critical");
  const warningRecs = recs.filter(r => r.severity === "warning");
  const usedDiskMb = (co.total_disk_mb || 0) - (co.available_disk_mb || 0);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Top Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 border" style={{ borderColor: "var(--border-default)" }}>
        <MetricCard label="Nodes" value={co.total_nodes || 0} sub={`${co.online_nodes || 0} online / ${co.offline_nodes || 0} offline`} icon={Server} testId="metric-nodes" />
        <MetricCard label="Topology" value={`${co.leaves || 0}L / ${co.aggregators || 0}A`} sub={`AG: ${(co.availability_groups || []).join(", ") || "—"}`} icon={Server} testId="metric-topology" />
        <MetricCard label="Memory" value={`${co.memory_used_pct || 0}%`} sub={`${formatBytes(co.used_memory_mb)} of ${formatBytes(co.total_memory_mb)}`} icon={MemoryStick} testId="metric-memory"
          alert={co.memory_used_pct > 80} />
        <MetricCard label="Disk Used" value={`${co.disk_used_pct || 0}%`} sub={`${formatBytes(usedDiskMb)} of ${formatBytes(co.total_disk_mb)}`} icon={HardDrive} testId="metric-disk"
          alert={co.disk_used_pct > 80} />
        <MetricCard label="CPUs" value={co.total_cpus || 0} sub="total cores" icon={Cpu} testId="metric-cpus" />
        <MetricCard label="Version" value={co.version || "?"} sub={license.type ? `${license.type} License` : "SingleStore"} icon={Shield} testId="metric-version" />
      </div>

      {/* Issues Summary - Critical/Warning */}
      {recs.length > 0 && (
        <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3 flex items-center gap-2" style={{ borderColor: "var(--border-default)" }}>
            <AlertTriangle size={16} style={{ color: criticalRecs.length > 0 ? "var(--status-critical)" : "var(--status-warning)" }} />
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Issues Detected ({recs.length})
            </h3>
            <span className="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 badge-critical ml-2">
              {criticalRecs.length} critical
            </span>
            <span className="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 badge-warning ml-1">
              {warningRecs.length} warning
            </span>
          </div>
          <div className="divide-y" style={{ borderColor: "#F4F4F5" }}>
            {recs.slice(0, 6).map((rec) => (
              <div key={rec.id} className="flex items-start gap-3 px-4 py-3">
                <div className={`w-1 self-stretch flex-shrink-0 ${rec.severity === "critical" ? "bg-[#FF3B30]" : "bg-[#FFCC00]"}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${severityBadgeClass(rec.severity)}`}>
                      {rec.severity}
                    </span>
                    <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-tertiary)" }}>{rec.category}</span>
                    {rec.doc_link && (
                      <a href={rec.doc_link} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-0.5 text-[10px] underline" style={{ color: "var(--brand-primary)" }}>
                        <ExternalLink size={9} /> Docs
                      </a>
                    )}
                  </div>
                  <p className="text-sm font-medium mt-1">{rec.title}</p>
                  <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{rec.description}</p>
                  {rec.remediation && (
                    <p className="text-xs mt-1 italic" style={{ color: "var(--brand-primary)" }}>{rec.remediation}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Node Map */}
      <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }} data-testid="node-map-heading">
            Cluster Topology Map
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
            Each node's role, health, memory and disk utilization. Offline nodes are flagged in red.
          </p>
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-zinc-200">
          {(co.nodes_detail || []).map((node) => {
            const memPct = node.max_memory_mb > 0 ? Math.round(node.memory_used_mb / node.max_memory_mb * 100) : 0;
            const diskPct = node.total_disk_mb > 0 ? Math.round((node.total_disk_mb - node.available_disk_mb) / node.total_disk_mb * 100) : 0;
            const isOnline = node.state === "online";
            const isAgg = node.type === "MA" || node.type === "CA";
            return (
              <div key={node.id} className={`bg-white p-3 ${!isOnline ? "border-l-4 border-l-[#FF3B30]" : ""}`} data-testid={`node-card-${node.id}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${
                    node.type === "MA" ? "bg-[#002FA7] text-white" :
                    node.type === "CA" ? "bg-zinc-800 text-white" :
                    "bg-zinc-100 text-zinc-600"
                  }`}>{node.type}</span>
                  <div className="flex items-center gap-1">
                    {node.availability_group && node.availability_group !== "NULL" && (
                      <span className="text-[9px] font-mono px-1 border" style={{ borderColor: "var(--border-default)" }}>AG{node.availability_group}</span>
                    )}
                    <span className={`w-2 h-2 ${isOnline ? "bg-[#00C853]" : "bg-[#FF3B30] pulse-dot"}`} />
                  </div>
                </div>
                <p className="text-xs font-mono font-medium truncate" title={node.ip_addr}>{node.ip_addr}</p>
                <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                  ID:{node.id} | v{node.version} | {formatUptime(node.uptime_seconds)}
                </p>
                <div className="mt-2 space-y-1">
                  <MiniBar label="MEM" pct={memPct} value={`${formatBytes(node.memory_used_mb)}/${formatBytes(node.max_memory_mb)}`} />
                  <MiniBar label="DISK" pct={diskPct} value={`${formatBytes(node.total_disk_mb - node.available_disk_mb)}/${formatBytes(node.total_disk_mb)}`} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Database Disk Usage + Detected Patterns side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border" style={{ borderColor: "var(--border-default)" }}>
        {/* DB Disk Usage */}
        <div className="border-r" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Database Disk Usage
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
                      <div className="progress-fill" style={{ width: `${pct}%`, background: "var(--brand-primary)" }} />
                    </div>
                    <span className="text-[11px] font-mono w-16 text-right font-bold">{gb.toFixed(1)} GB</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="p-4 text-xs" style={{ color: "var(--text-tertiary)" }}>No disk usage data</p>
          )}
        </div>

        {/* Detected Log Patterns */}
        <div style={{ background: "var(--surface)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Detected Log Patterns
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
              Auto-detected critical patterns in tracelogs
            </p>
          </div>
          {detectedPatterns.length > 0 ? (
            <div className="divide-y" style={{ borderColor: "#F4F4F5" }}>
              {detectedPatterns.map((pat, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${severityBadgeClass(pat.severity)}`}>
                      {pat.severity}
                    </span>
                    <span className="text-sm font-medium">{pat.title}</span>
                    <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>×{pat.count}</span>
                  </div>
                  <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>{pat.conclusion}</p>
                  {pat.nodes?.length > 0 && (
                    <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                      Nodes: {pat.nodes.join(", ")}
                    </p>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="p-4 text-xs" style={{ color: "var(--text-tertiary)" }}>No critical patterns detected</p>
          )}
        </div>
      </div>

      {/* Events & Log Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border" style={{ borderColor: "var(--border-default)" }}>
        {/* Events */}
        <div className="border-r" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              MV_EVENTS ({events.length})
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
              Cluster's own audit trail of significant state changes
            </p>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {events.length === 0 ? (
              <p className="p-4 text-xs" style={{ color: "var(--text-tertiary)" }}>No events</p>
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
        <div style={{ background: "var(--surface)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Log Summary
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
              Correlated ERROR spikes across nodes indicate cluster-wide events
            </p>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-2 gap-3">
              {Object.entries(logSummary.severity_counts || {}).map(([sev, count]) => (
                <div key={sev} className="flex items-center justify-between border px-3 py-2" style={{ borderColor: "var(--border-default)" }}>
                  <span className={`text-[10px] uppercase tracking-widest font-bold ${
                    sev === "ERROR" || sev === "FATAL" ? "status-critical" :
                    sev === "WARN" ? "status-warning" : "text-zinc-500"
                  }`}>{sev}</span>
                  <span className="text-sm font-mono font-bold">{formatNumber(count)}</span>
                </div>
              ))}
            </div>
            {/* Per-node breakdown */}
            <div className="mt-3 border-t pt-3" style={{ borderColor: "#F4F4F5" }}>
              <p className="text-[9px] uppercase tracking-widest font-bold mb-2" style={{ color: "var(--text-tertiary)" }}>
                Errors per Node
              </p>
              {Object.entries(logSummary.per_node || {}).map(([node, counts]) => {
                const errs = (counts.ERROR || 0) + (counts.FATAL || 0);
                return errs > 0 ? (
                  <div key={node} className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-mono truncate w-40" style={{ color: "var(--text-secondary)" }}>{node.split('.')[0]}</span>
                    <span className="text-[10px] font-mono font-bold status-critical">{errs} err</span>
                    <span className="text-[10px] font-mono status-warning">{counts.WARN || 0} warn</span>
                  </div>
                ) : null;
              })}
            </div>
            <p className="text-xs mt-2" style={{ color: "var(--text-tertiary)" }}>
              Total: {formatNumber(logSummary.total)} entries across {Object.keys(logSummary.per_node || {}).length} nodes
            </p>
          </div>
        </div>
      </div>

      {/* Dmesg Critical Events */}
      {dmesgEvents.length > 0 && (
        <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Kernel (dmesg) Critical Events
            </h3>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
              OOM kills, storage errors, CPU lockups detected in kernel ring buffer
            </p>
          </div>
          <div className="divide-y max-h-48 overflow-y-auto" style={{ borderColor: "#F4F4F5" }}>
            {dmesgEvents.slice(0, 20).map((evt, i) => (
              <div key={i} className="flex items-start gap-3 px-4 py-2">
                <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 flex-shrink-0 ${severityBadgeClass(evt.severity)}`}>
                  {evt.severity}
                </span>
                <div className="min-w-0">
                  <p className="text-xs font-medium">{evt.title} — {evt.hostname}</p>
                  <p className="text-[10px] font-mono mt-0.5 truncate" style={{ color: "var(--text-secondary)" }} title={evt.line}>{evt.line}</p>
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
    <div className={`border-r border-b p-4 ${alert ? "bg-[rgba(255,59,48,0.02)]" : ""}`}
      style={{ borderColor: "var(--border-default)", background: alert ? undefined : "var(--surface)" }} data-testid={testId}>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={12} style={{ color: alert ? "var(--status-critical)" : "var(--text-tertiary)" }} />
        <span className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>{label}</span>
      </div>
      <p className={`text-xl font-mono font-bold tracking-tight ${alert ? "status-critical" : ""}`}
        style={{ fontFamily: "JetBrains Mono, monospace" }}>{value}</p>
      <p className="text-[11px] mt-0.5" style={{ color: "var(--text-tertiary)" }}>{sub}</p>
    </div>
  );
}

function MiniBar({ label, pct, value }) {
  const color = pct > 90 ? "#FF3B30" : pct > 75 ? "#FFCC00" : "#00C853";
  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] uppercase tracking-widest font-bold w-8" style={{ color: "var(--text-tertiary)" }}>{label}</span>
      <div className="flex-1 progress-bar">
        <div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
      <span className="text-[10px] font-mono w-24 text-right" style={{ color: pct > 85 ? "#FF3B30" : "var(--text-secondary)" }}>{value}</span>
    </div>
  );
}
