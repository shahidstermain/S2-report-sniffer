import { useState, useEffect } from "react";
import { Loader2, AlertTriangle } from "lucide-react";
import { getReportNodes } from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/utils-sdb";

export default function NodeHealth({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState("hostname");

  useEffect(() => {
    getReportNodes(reportId).then(res => { setData(res.data); setLoading(false); }).catch(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--ss-purple)" }} /></div>;
  if (!data) return <p className="text-sm p-4" style={{ color: "var(--ss-mid-gray)" }}>No data available</p>;

  const nodes = data.nodes || [];
  const nodesDetail = data.cluster_overview?.nodes_detail || [];

  // Merge parsed node data with MV_NODES detail
  const merged = nodes.map(n => {
    const detail = nodesDetail.find(d =>
      (d.ip_addr || "").includes(n.hostname) || (n.hostname || "").includes(d.ip_addr)
    );
    return { ...n, detail };
  });

  const sorted = [...merged].sort((a, b) => {
    if (sortBy === "memory") {
      return (b.metrics?.memory?.used_pct || 0) - (a.metrics?.memory?.used_pct || 0);
    }
    if (sortBy === "disk") {
      const aDisk = getMaxDiskPct(a);
      const bDisk = getMaxDiskPct(b);
      return bDisk - aDisk;
    }
    return (a.hostname || "").localeCompare(b.hostname || "");
  });

  return (
    <div className="animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 mb-4">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Node Health & Capacity
        </h2>
        <div className="sm:ml-auto flex flex-wrap gap-1">
          {["hostname", "memory", "disk"].map(s => (
            <button
              key={s}
              onClick={() => setSortBy(s)}
              className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1 border ${
                sortBy === s ? "bg-[#AA00FF] text-white border-[#AA00FF]" : "bg-white border-zinc-200 text-zinc-500"
              }`}
              data-testid={`sort-${s}`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-zinc-200 border" style={{ borderColor: "var(--ss-divider)" }}>
        {sorted.map((node) => (
          <NodeCard key={node.hostname} node={node} />
        ))}
      </div>
    </div>
  );
}

function NodeCard({ node }) {
  const mem = node.metrics?.memory || {};
  const disks = node.metrics?.disk || [];
  const detail = node.detail || {};
  const top = node.metrics?.top || {};

  const memsqlDisk = disks.find(d => (d.mounted_on || "").includes("memsql")) || disks.find(d => d.use_pct > 50) || {};
  const hasIssue = (mem.used_pct || 0) > 85 || (memsqlDisk.use_pct || 0) > 80 || (mem.swap_used_pct || 0) > 10;

  return (
    <div className={`bg-white p-4 ${hasIssue ? "border-l-4 border-l-[#F44336]" : ""}`} data-testid={`node-health-card-${node.hostname}`}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${
              node.role === "MA" ? "bg-[#AA00FF] text-white" :
              node.role === "CA" ? "bg-zinc-800 text-white" :
              "bg-zinc-100 text-zinc-600"
            }`}>{node.role}</span>
            <span className="text-sm font-mono font-medium">{node.hostname}</span>
            {hasIssue && <AlertTriangle size={14} className="status-critical" />}
          </div>
          <p className="text-[10px] font-mono mt-1" style={{ color: "var(--ss-mid-gray)" }}>
            v{node.version || detail.version || "?"} | {detail.num_cpus || "?"} CPUs | ID:{detail.id || "?"}
          </p>
        </div>
        <span className={`w-2.5 h-2.5 rounded-full ${
          (detail.state || "online") === "online" ? "bg-[#00C853]" : "bg-[#F44336]"
        }`} />
      </div>

      {/* Memory */}
      <div className="space-y-2">
        <BarMetric
          label="Memory"
          pct={mem.used_pct || 0}
          detail={`${formatBytes(mem.used_mb)} / ${formatBytes(mem.total_mb)} (${formatBytes(mem.available_mb)} avail)`}
        />
        {mem.swap_used_mb > 0 && (
          <BarMetric
            label="Swap"
            pct={mem.swap_used_pct || 0}
            detail={`${formatBytes(mem.swap_used_mb)} / ${formatBytes(mem.swap_total_mb)}`}
          />
        )}
        <BarMetric
          label="Disk"
          pct={memsqlDisk.use_pct || 0}
          detail={`${memsqlDisk.used || "?"} / ${memsqlDisk.size || "?"} on ${memsqlDisk.mounted_on || "—"}`}
        />
      </div>

      {/* Key disk mounts */}
      {disks.length > 0 && (
        <div className="mt-3 border-t pt-2" style={{ borderColor: "#F4F4F5" }}>
          <p className="text-[9px] uppercase tracking-widest font-bold mb-1" style={{ color: "var(--ss-mid-gray)" }}>Filesystems</p>
          <div className="space-y-0.5">
            {disks.filter(d => d.use_pct > 20 || (d.mounted_on || "").includes("memsql")).slice(0, 5).map((d, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px] font-mono" style={{ color: "#525252" }}>
                <span className={`w-1.5 h-1.5 ${
                  d.use_pct > 90 ? "bg-[#F44336]" : d.use_pct > 75 ? "bg-[#FF9800]" : "bg-[#00C853]"
                }`} />
                <span className="truncate flex-1">{d.mounted_on}</span>
                <span>{d.use_pct}%</span>
                <span>{d.used}/{d.size}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BarMetric({ label, pct, detail }) {
  const color = pct > 90 ? "var(--ss-critical)" : pct > 75 ? "var(--ss-warning)" : "#00C853";
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "var(--ss-mid-gray)" }}>{label}</span>
        <span className="text-[10px] font-mono" style={{ color: pct > 85 ? "var(--ss-critical)" : "#525252" }}>
          {pct}%
        </span>
      </div>
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
      <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>{detail}</p>
    </div>
  );
}

function getMaxDiskPct(node) {
  const disks = node.metrics?.disk || [];
  const memsql = disks.find(d => (d.mounted_on || "").includes("memsql"));
  return memsql?.use_pct || Math.max(0, ...disks.map(d => d.use_pct || 0));
}
