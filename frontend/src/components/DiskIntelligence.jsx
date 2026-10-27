import { useState, useEffect, Fragment } from "react";
import { LayoutDashboard, Loader2, ChevronDown, ChevronRight, Info } from "lucide-react";
import { getReportDiskIntelligence } from "@/lib/api";
import { formatBytes } from "@/lib/utils-sdb";
import InfoHint from "./InfoHint";

function DiskIntelligence({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedChild, setExpandedChild] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    getReportDiskIntelligence(reportId)
      .then((res) => {
        if (!cancelled) {
          setData(res.data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        const detail = err?.response?.data?.detail;
        const detailMessage =
          typeof detail === "string"
            ? detail
            : detail?.error || detail?.message;
        setError(detailMessage || err?.response?.data?.error || err?.message || "Failed to load disk intelligence data");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="animate-spin" style={{ color: "var(--ss-purple)" }} />
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm p-4 status-warning" data-testid="disk-intelligence-error">
        {error}
      </p>
    );
  }

  if (!data) return <EmptyState text="No disk intelligence data available" />;

  const persisted = data.disk_intelligence || {};
  const legacyOverhead = data.cluster_overhead || {};
  const summary = persisted.summary || (legacyOverhead.used_disk_bytes != null ? {
    total_used_bytes: legacyOverhead.used_disk_bytes,
    attributed_table_bytes: legacyOverhead.attributed_table_bytes,
    overhead_bytes: legacyOverhead.total_bytes,
    overhead_pct: legacyOverhead.pct_of_used_disk,
    is_estimate: true,
    incomplete_nodes: data.blobs_referenced_delta?.incomplete_nodes || [],
    ha_adjusted: Number(data.blobs_referenced_delta?.ha_factor || 1) > 1,
  } : null);
  const cluster_overhead = persisted.cluster_overhead || legacyOverhead.children || {};
  const per_node = persisted.per_node || data.blobs_referenced_delta?.per_node || [];
  const remediation_hints = persisted.remediation_hints || [];

  if (!summary && !Object.keys(cluster_overhead).length && !per_node.length) {
    return <EmptyState text="No disk intelligence data available" />;
  }
  const { total_used_bytes, attributed_table_bytes, overhead_bytes, overhead_pct, is_estimate, incomplete_nodes, ha_adjusted } = summary || {};

  const children = Object.entries(cluster_overhead || {}).map(([key, value]) => ({
    key,
    label: overheadChildLabel(key),
    ...value,
  })).filter(c => c.bytes > 0);

  const sortedChildren = children.sort((a, b) => b.bytes - a.bytes);

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
        <div className="flex items-center gap-1">
          <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Disk Intelligence
          </h2>
          <InfoHint label="Disk Intelligence" content="Sniffer storage breakdown — not a SingleStore docs product. Shows attributed table bytes vs non-table disk overhead, including on-disk columnstore blob residue estimated from report collectors." />
        </div>
      </div>

      {is_estimate && incomplete_nodes?.length > 0 && (
        <p className="text-[10px] mt-1 status-warning">
          Disk intelligence data is an estimate due to incomplete data from nodes: {incomplete_nodes.join(", ")}.
        </p>
      )}
      {is_estimate && ha_adjusted && !(incomplete_nodes?.length > 0) && (
        <p className="text-[10px] mt-1 status-warning">
          Disk intelligence is HA-adjusted (blob accounting multiplied by redundancy) and treated as an estimate.
        </p>
      )}

      {/* Hero Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard label="Mount Used" value={formatBytes(total_used_bytes)} description="Total disk space used by SingleStore data directories" />
        <MetricCard
          label="Attributed table bytes"
          value={formatBytes(attributed_table_bytes)}
          description={
            is_estimate
              ? "Bytes attributed to database tables from statistics (estimate when inventory is incomplete or HA-adjusted)"
              : "Disk space attributed to database tables"
          }
        />
        <MetricCard
          label="Non-table disk overhead"
          value={formatBytes(overhead_bytes)}
          description={`Space not attributed to tables (${Number.isFinite(Number(overhead_pct)) ? Number(overhead_pct).toFixed(1) : "—"}% of Mount Used)`}
        />
      </div>

      {/* Waterfall/Treemap - Reusing StorageDistribution logic */}
      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Cluster Overhead Breakdown
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Non-table disk space consumed across data mounts. Click any category to expand details.
          </p>
        </div>
        <div className="p-4">
          <table className="w-full dense-table">
            <thead>
              <tr>
                <th className="text-left">Bucket</th>
                <th className="text-right">Size</th>
                <th className="text-right">% of Mount Used</th>
              </tr>
            </thead>
            <tbody>
              {sortedChildren.map((child) => {
                const isExpanded = expandedChild === child.key;
                const desc = OVERHEAD_DESCRIPTIONS[child.key] || "Internal SingleStore non-table storage component.";
                return (
                  <Fragment key={child.key}>
                    <tr
                      onClick={() => setExpandedChild(isExpanded ? null : child.key)}
                      className="cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/40 select-none transition-colors"
                      data-testid={`di-overhead-row-${child.key}`}
                      title={`Click to ${isExpanded ? "collapse" : "expand"} details for ${child.label}`}
                    >
                      <td className="flex items-center gap-1.5 py-1.5">
                        {isExpanded ? (
                          <ChevronDown className="w-3.5 h-3.5 text-amber-600 shrink-0" />
                        ) : (
                          <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                        )}
                        <span className="font-medium">{child.label}</span>
                      </td>
                      <td className="text-right font-mono">{formatBytes(child.bytes)}</td>
                      <td className="text-right font-mono">
                        {Number.isFinite(Number(child.pct_of_used_disk))
                          ? `${Number(child.pct_of_used_disk).toFixed(1)}%`
                          : "—"}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-amber-50/40 dark:bg-amber-950/20 border-b border-amber-200/40 dark:border-amber-900/30" data-testid={`di-overhead-detail-${child.key}`}>
                        <td colSpan={3} className="p-2.5 pl-8 text-xs">
                          <div className="flex items-start gap-2">
                            <Info className="w-3.5 h-3.5 text-amber-600 mt-0.5 shrink-0" />
                            <div>
                              <p className="font-semibold text-amber-900 dark:text-amber-200 text-[11px]">{child.label}</p>
                              <p className="text-zinc-600 dark:text-zinc-400 mt-0.5 text-[11px] leading-relaxed">
                                {desc}
                              </p>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Per-node Table */}
      {per_node?.length > 0 && (
        <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Per-Node Disk Overview
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full dense-table">
              <thead>
                <tr>
                  <th className="text-left">Node</th>
                  <th className="text-right">On-disk blobs</th>
                  <th className="text-right">Referenced (adj.)</th>
                  <th className="text-right">Delta</th>
                  <th className="text-right">Delta %</th>
                </tr>
              </thead>
              <tbody>
                {per_node.map((row) => (
                  <tr key={row.node}>
                    <td>{row.node}{row.status === "incomplete" ? " (incomplete)" : ""}</td>
                    <td className="text-right">{row.on_disk_blobs_bytes != null ? formatBytes(row.on_disk_blobs_bytes) : "—"}</td>
                    <td className="text-right">{row.referenced_adjusted_bytes != null ? formatBytes(row.referenced_adjusted_bytes) : "—"}</td>
                    <td className="text-right">{row.delta_bytes != null ? formatBytes(row.delta_bytes) : "—"}</td>
                    <td className="text-right">{row.delta_pct != null ? `${row.delta_pct}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function overheadChildLabel(key) {
  const labels = {
    transaction_logs: "Transaction Logs",
    logs: "Logs (deprecated)",
    snapshots: "Snapshots",
    tracelogs: "Tracelogs",
    plancache: "Plancache",
    auditlogs: "Audit logs",
    spill: "Spill",
    cores: "Cores",
    referenced_non_table: "Referenced non-table",
    unreferenced_blobs: "Unattributed on-disk blobs (Sniffer)",
    other_overhead: "Other overhead",
  };
  return labels[key] || key;
}

const OVERHEAD_DESCRIPTIONS = {
  other_overhead: "Any remaining used disk space on the mount not captured by the explicit categories above (such as filesystem metadata, OS temp files, or binaries).",
  unreferenced_blobs: "Columnstore blob files present on disk that are no longer referenced by active table metadata (e.g., awaiting background garbage collection or blob reclamation).",
  transaction_logs: "Write-ahead transaction log segments (*.clg files) required for ACID transaction durability and replication across partition replicas.",
  snapshots: "Periodic point-in-time partition snapshots written to disk to allow transaction logs to be safely truncated and accelerate node restart recovery.",
  tracelogs: "SingleStore engine diagnostic logs (memsql.log and rotated logs in tracelogsdir) recording operational events, queries, and errors.",
  plancache: "Disk-cached compiled query execution plans and generated code libraries stored in plancachedir.",
  auditlogs: "Security and query audit log files stored on disk when audit logging is enabled.",
  spill: "Temporary disk spill files generated when memory-intensive queries (large hash joins, aggregations, or sorts) exceed available memory limits.",
  cores: "Core dump files generated if an engine process terminated unexpectedly.",
  referenced_non_table: "Total disk space consumed by non-table engine files referenced by active database partitions.",
  logs: "Write-ahead transaction log segments (*.clg files).",
};

function MetricCard({ label, value, description }) {
  return (
    <div className="border p-4" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <p className="text-[10px] uppercase tracking-widest font-bold" style={{ color: "var(--ss-mid-gray)" }}>{label}</p>
      <p className="text-xl font-bold font-mono mt-1" style={{ fontFamily: "Chivo, sans-serif" }}>{value}</p>
      <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>{description}</p>
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div className="text-center py-12 border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <LayoutDashboard size={32} className="mx-auto mb-2" style={{ color: "var(--ss-mid-gray)" }} />
      <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>{text}</p>
    </div>
  );
}

export default DiskIntelligence;
