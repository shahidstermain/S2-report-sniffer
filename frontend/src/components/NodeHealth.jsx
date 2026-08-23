import { useState, useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { getReportNodes } from "@/lib/api";
import { asRowList } from "@/lib/utils";
import { formatMegabytes, formatNumber } from "@/lib/utils-sdb";
import CpuHealthPanel from "./CpuHealthPanel";

/** Match a parsed node to an MV_NODES detail row without blank-IP wildcard joins. */
export function matchNodeDetail(node, nodesDetail) {
  const hostname = String(node?.hostname || "").trim().toLowerCase();
  if (!hostname) return undefined;
  return asRowList(nodesDetail).find((detail) => {
    const ip = String(detail?.ip_addr || "").trim().toLowerCase();
    const detailHost = String(detail?.hostname || detail?.host || "").trim().toLowerCase();
    if (detailHost && (detailHost === hostname || detailHost.includes(hostname) || hostname.includes(detailHost))) {
      return true;
    }
    // Empty ip_addr must not match: "".includes(hostname) is false, but
    // hostname.includes("") is true for every hostname.
    if (!ip) return false;
    return ip.includes(hostname) || hostname.includes(ip);
  });
}

export default function NodeHealth({ reportId, cpuHealth }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [sortBy, setSortBy] = useState("hostname");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    setData(null);
    getReportNodes(reportId)
      .then((res) => {
        if (!cancelled) {
          setData(res.data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [reportId]);

  if (loading) {
    return (
      <div className="animate-fade-in">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 mb-4">
          <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Node Health &amp; Capacity
          </h2>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-zinc-200 border" style={{ borderColor: "var(--ss-divider)" }}>
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="bg-white p-4 space-y-3">
              <div className="flex items-center justify-between mb-3">
                <div className="skeleton h-5 w-36" />
                <div className="skeleton w-2.5 h-2.5 rounded-full" />
              </div>
              {[1, 2, 3].map(j => (
                <div key={j} className="space-y-1">
                  <div className="skeleton h-3 w-16" />
                  <div className="skeleton h-2 w-full rounded" />
                  <div className="skeleton h-3 w-28" />
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (loadError || !data) {
    return (
      <div className="animate-fade-in flex flex-col items-center justify-center py-16 gap-3">
        <AlertTriangle size={28} style={{ color: "var(--ss-critical)", opacity: 0.5 }} />
        <p className="text-sm font-medium" style={{ color: "var(--ss-critical)" }}>Failed to load node data</p>
        <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>Check that the report has finished processing</p>
      </div>
    );
  }

  const nodes = asRowList(data.nodes);
  const nodesDetail = asRowList(data.cluster_overview?.nodes_detail);

  // Merge parsed node data with MV_NODES detail
  const merged = nodes.map((n) => ({ ...n, detail: matchNodeDetail(n, nodesDetail) }));

  const sorted = [...merged].sort((a, b) => {
    if (sortBy === "memory") {
      const aPct = a.metrics?.memory?.used_pct;
      const bPct = b.metrics?.memory?.used_pct;
      if (aPct == null && bPct == null) return 0;
      if (aPct == null) return 1;
      if (bPct == null) return -1;
      return Number(bPct) - Number(aPct);
    }
    if (sortBy === "disk") {
      const aDisk = getMaxDiskPct(a);
      const bDisk = getMaxDiskPct(b);
      if (aDisk < 0 && bDisk < 0) return 0;
      if (aDisk < 0) return 1;
      if (bDisk < 0) return -1;
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

      <div className="mb-6">
        <CpuHealthPanel cpuHealth={cpuHealth} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-zinc-200 border" style={{ borderColor: "var(--ss-divider)" }}>
        {sorted.map((node) => (
          <NodeCard key={node.hostname} node={node} />
        ))}
      </div>
    </div>
  );
}

export function pickDataDisk(disks) {
  if (!disks?.length) return {};
  const ranked = disks
    .map((disk) => {
      const mount = String(disk.mounted_on || "");
      let score = parseFloat(disk.use_pct) || 0;
      if (mount.includes("memsql") || mount.includes("hdisk") || mount.startsWith("/media/")) {
        score += 200;
      }
      if (mount === "/" || mount === "/boot" || mount === "/boot/efi") {
        score -= 100;
      }
      return { disk, score };
    })
    .sort((a, b) => b.score - a.score);
  return ranked[0]?.disk || {};
}

function NodeCard({ node }) {
  const mem = node.metrics?.memory || {};
  const disks = node.metrics?.disk || [];
  const detail = node.detail || {};
  const top = node.metrics?.top || {};

  const memsqlDisk = pickDataDisk(disks);
  const memPct = mem.used_pct == null ? null : Number(mem.used_pct);
  const diskPct = memsqlDisk?.use_pct == null ? null : Number(memsqlDisk.use_pct);
  const swapPct = mem.swap_used_pct == null ? null : Number(mem.swap_used_pct);
  const hasIssue = (memPct != null && memPct > 85) || (diskPct != null && diskPct > 80) || (swapPct != null && swapPct > 10);
  const nodeState = String(detail.state || "").trim().toLowerCase();
  const stateDot =
    !nodeState || nodeState === "unknown"
      ? "bg-zinc-400"
      : nodeState === "online"
        ? "bg-[#00C853]"
        : "bg-[#F44336]";

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
        <span className={`w-2.5 h-2.5 rounded-full ${stateDot}`} title={nodeState || "unknown"} />
      </div>

      {/* Host RAM from parse_free — distinct from maximum_memory % elsewhere */}
      <div className="space-y-2">
        <BarMetric
          label="Host RAM (OS)"
          pct={memPct}
          detail={`${formatMegabytes(mem.used_mb)} / ${formatMegabytes(mem.total_mb)} (${formatMegabytes(mem.available_mb)} avail)`}
        />
        {swapPct != null && swapPct > 0 && (
          <BarMetric
            label="Swap"
            pct={swapPct}
            detail={`${formatMegabytes(mem.swap_used_mb)} / ${formatMegabytes(mem.swap_total_mb)}`}
          />
        )}
        <BarMetric
          label="Disk"
          pct={diskPct}
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

export function BarMetric({ label, pct, detail }) {
  const known = pct != null && Number.isFinite(Number(pct));
  const value = known ? Number(pct) : null;
  const color = !known ? "var(--ss-mid-gray)" : value > 90 ? "var(--ss-critical)" : value > 75 ? "var(--ss-warning)" : "#00C853";
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "var(--ss-mid-gray)" }}>{label}</span>
        <span className="text-[10px] font-mono" style={{ color: known && value > 85 ? "var(--ss-critical)" : "#525252" }}>
          {known ? `${value}%` : "—"}
        </span>
      </div>
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: known ? `${Math.min(value, 100)}%` : "0%", background: color }} />
      </div>
      <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>{detail}</p>
    </div>
  );
}

function getMaxDiskPct(node) {
  const disks = node.metrics?.disk || [];
  const picked = pickDataDisk(disks);
  if (picked?.use_pct != null && Number.isFinite(Number(picked.use_pct))) {
    return Number(picked.use_pct);
  }
  return -1;
}
