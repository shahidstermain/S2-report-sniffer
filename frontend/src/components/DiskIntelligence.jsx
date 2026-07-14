import { useState, useEffect } from "react";
import { AlertTriangle, Database, HardDrive, LayoutDashboard, Loader2 } from "lucide-react";
import { getReportDiskIntelligence } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/utils-sdb";
import InfoHint from "./InfoHint";
import { BarMetric } from "./NodeHealth"; // Re-use BarMetric from NodeHealth

function DiskIntelligence({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getReportDiskIntelligence(reportId)
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err?.response?.data?.error || err?.message || "Failed to load disk intelligence data");
        setLoading(false);
      });
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

  const { summary, cluster_overhead, per_node, remediation_hints } = data.disk_intelligence || {};
  const { total_used_bytes, attributed_table_bytes, overhead_bytes, overhead_pct, is_estimate, incomplete_nodes } = summary || {};

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
          <InfoHint label="Disk Intelligence" content="Detailed breakdown of disk usage beyond simple database sizes, identifying overheads and potential for reclamation." />
        </div>
      </div>

      {is_estimate && incomplete_nodes?.length > 0 && (
        <p className="text-[10px] mt-1 status-warning">
          Disk intelligence data is an estimate due to incomplete data from nodes: {incomplete_nodes.join(", ")}.
        </p>
      )}

      {/* Hero Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard label="Mount Used" value={formatBytes(total_used_bytes)} description="Total disk space used by SingleStore data directories" />
        <MetricCard label="Physical Data" value={formatBytes(attributed_table_bytes)} description="Estimated disk space used by actual database tables" />
        <MetricCard label="Logical Size (Overhead)" value={formatBytes(overhead_bytes)} description={`Space not attributed to tables (${overhead_pct.toFixed(1)}% of Mount Used)`} />
      </div>

      {/* Waterfall/Treemap - Reusing StorageDistribution logic */}
      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Cluster Overhead Breakdown
          </h3>
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
              {sortedChildren.map((child) => (
                <tr key={child.key}>
                  <td>{child.label}</td>
                  <td className="text-right">{formatBytes(child.bytes)}</td>
                  <td className="text-right">{child.pct_of_used_disk.toFixed(1)}%</td>
                </tr>
              ))}
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
    unreferenced_blobs: "Unreferenced blobs",
    other_overhead: "Other overhead",
  };
  return labels[key] || key;
}

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
