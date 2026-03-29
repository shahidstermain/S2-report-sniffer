import { Server, HardDrive, Cpu, MemoryStick, AlertTriangle, CheckCircle2, XCircle, Clock } from "lucide-react";
import { formatBytes, formatUptime, formatNumber, severityBadgeClass } from "@/lib/utils-sdb";

export default function ClusterOverview({ reportId, overview }) {
  if (!overview) return null;
  const co = overview.cluster_overview || {};
  const recs = overview.recommendations || [];
  const events = overview.events || [];
  const logSummary = overview.log_summary || {};

  const criticalRecs = recs.filter(r => r.severity === "critical");
  const warningRecs = recs.filter(r => r.severity === "warning");

  const usedDiskMb = (co.total_disk_mb || 0) - (co.available_disk_mb || 0);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Top Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 border" style={{ borderColor: "var(--border-default)" }}>
        <MetricCard label="Nodes" value={co.total_nodes || 0} sub={`${co.online_nodes || 0} online`} icon={Server} testId="metric-nodes" />
        <MetricCard label="Leaves" value={co.leaves || 0} sub={`AG: ${(co.availability_groups || []).join(", ") || "—"}`} icon={Server} testId="metric-leaves" />
        <MetricCard label="Memory" value={formatBytes(co.used_memory_mb)} sub={`of ${formatBytes(co.total_memory_mb)} (${co.memory_used_pct || 0}%)`} icon={MemoryStick} testId="metric-memory" />
        <MetricCard label="Disk Used" value={formatBytes(usedDiskMb)} sub={`of ${formatBytes(co.total_disk_mb)} (${co.disk_used_pct || 0}%)`} icon={HardDrive} testId="metric-disk" />
        <MetricCard label="CPUs" value={co.total_cpus || 0} sub="total cores" icon={Cpu} testId="metric-cpus" />
        <MetricCard label="Version" value={co.version || "?"} sub="SingleStore" icon={Server} testId="metric-version" />
      </div>

      {/* Issues Summary */}
      {recs.length > 0 && (
        <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3 flex items-center gap-2" style={{ borderColor: "var(--border-default)" }}>
            <AlertTriangle size={16} style={{ color: criticalRecs.length > 0 ? "var(--status-critical)" : "var(--status-warning)" }} />
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Issues Detected
            </h3>
            <span className="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 badge-critical ml-2">
              {criticalRecs.length} critical
            </span>
            <span className="text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 badge-warning ml-1">
              {warningRecs.length} warning
            </span>
          </div>
          <div className="divide-y" style={{ borderColor: "#F4F4F5" }}>
            {recs.slice(0, 5).map((rec) => (
              <div key={rec.id} className="flex items-start gap-3 px-4 py-3">
                <div className={`w-1 self-stretch flex-shrink-0 ${
                  rec.severity === "critical" ? "bg-[#FF3B30]" : "bg-[#FFCC00]"
                }`} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${severityBadgeClass(rec.severity)}`}>
                      {rec.severity}
                    </span>
                    <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-tertiary)" }}>
                      {rec.category}
                    </span>
                  </div>
                  <p className="text-sm font-medium mt-1">{rec.title}</p>
                  <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{rec.description}</p>
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
            Node Map
          </h3>
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-px bg-zinc-200">
          {(co.nodes_detail || []).map((node) => {
            const memPct = node.max_memory_mb > 0 ? Math.round(node.memory_used_mb / node.max_memory_mb * 100) : 0;
            const diskPct = node.total_disk_mb > 0 ? Math.round((node.total_disk_mb - node.available_disk_mb) / node.total_disk_mb * 100) : 0;
            const isOnline = node.state === "online";
            return (
              <div key={node.id} className="bg-white p-3" data-testid={`node-card-${node.id}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] uppercase tracking-widest font-bold" style={{ color: "var(--text-secondary)" }}>
                    {node.type}
                  </span>
                  <span className={`w-2 h-2 rounded-full ${isOnline ? "bg-[#00C853]" : "bg-[#FF3B30] pulse-dot"}`} />
                </div>
                <p className="text-xs font-mono font-medium truncate" title={node.ip_addr}>
                  {node.ip_addr}
                </p>
                <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                  ID:{node.id} | AG:{node.availability_group} | {formatUptime(node.uptime_seconds)}
                </p>
                <div className="mt-2 space-y-1">
                  <MiniBar label="MEM" pct={memPct} value={`${formatBytes(node.memory_used_mb)}/${formatBytes(node.max_memory_mb)}`} />
                  <MiniBar label="DISK" pct={diskPct} value={`${diskPct}%`} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Events & Log Summary side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 border" style={{ borderColor: "var(--border-default)" }}>
        {/* Events */}
        <div className="border-r" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Recent Events ({events.length})
            </h3>
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
                  {events.slice(0, 20).map((ev, i) => (
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
            <p className="text-xs mt-3" style={{ color: "var(--text-tertiary)" }}>
              Total: {formatNumber(logSummary.total)} entries across {Object.keys(logSummary.per_node || {}).length} nodes
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, icon: Icon, testId }) {
  return (
    <div className="border-r border-b p-4" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }} data-testid={testId}>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={12} style={{ color: "var(--text-tertiary)" }} />
        <span className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>
          {label}
        </span>
      </div>
      <p className="text-xl font-mono font-bold tracking-tight" style={{ fontFamily: "JetBrains Mono, monospace" }}>
        {value}
      </p>
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
      <span className="text-[10px] font-mono w-16 text-right" style={{ color: "var(--text-secondary)" }}>{value}</span>
    </div>
  );
}
