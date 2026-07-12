import { useState, useEffect } from "react";
import { Loader2, Database } from "lucide-react";
import { getReportStorage } from "@/lib/api";
import { formatNumber } from "@/lib/utils-sdb";
import InfoHint from "./InfoHint";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

function diskDbName(row) {
  return row.DATABASE_NAME || row.Database || row.database || row.DB || "—";
}

function diskGb(row) {
  const direct = parseFloat(row.TOTAL_DISK_USAGE_GB);
  if (!Number.isNaN(direct) && direct > 0) return direct;
  const bytes = parseFloat(row._disk_bytes || row.disk_bytes || row.DataSize || row.size || 0);
  return bytes > 0 ? bytes / (1024 ** 3) : 0;
}

function ExpandableCell({ value, label, className = "" }) {
  const [open, setOpen] = useState(false);
  const text = value == null || value === "" ? "—" : String(value);
  const canExpand = text !== "—";

  return (
    <>
      <button
        type="button"
        className={`text-left truncate max-w-[200px] ${canExpand ? "cursor-pointer hover:underline" : "cursor-default"} ${className}`}
        onClick={() => canExpand && setOpen(true)}
        title={canExpand ? "Tap to view full value" : undefined}
        data-testid={canExpand ? "expandable-cell" : undefined}
      >
        {text}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{label || "Full value"}</DialogTitle>
          </DialogHeader>
          <pre className="text-xs font-mono whitespace-pre-wrap break-all max-h-[60vh] overflow-y-auto p-3 border rounded-md bg-muted/30">
            {text}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function StorageDistribution({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("databases");

  useEffect(() => {
    setLoading(true);
    setError(null);
    getReportStorage(reportId)
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err?.response?.data?.error || err?.message || "Failed to load storage data");
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
      <p className="text-sm p-4 status-warning" data-testid="storage-error">
        {error}
      </p>
    );
  }
  if (!data) return <p className="text-sm p-4" style={{ color: "var(--ss-mid-gray)" }}>No data</p>;

  const databases = data.databases || [];
  const storage = data.storage || [];
  const dbDisk = data.database_disk_usage || [];
  const partitions = data.partitions || {};
  const diskDerived = dbDisk.some((row) => row._source === "table_statistics");

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
        <div className="flex items-center gap-1">
          <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Storage & Distribution
          </h2>
          <InfoHint label="storage and distribution" content="Database, disk, partition, and table-storage snapshots parsed from the uploaded cluster report." />
        </div>
        <div className="sm:ml-auto w-full sm:w-auto overflow-x-auto">
        <div className="flex gap-0 border min-w-max" style={{ borderColor: "var(--ss-divider)" }}>
          {[
            { id: "databases", label: `Databases (${databases.length})` },
            { id: "disk", label: `Disk Usage (${dbDisk.length})` },
            { id: "partitions", label: `Partitions (${Object.keys(partitions).length})` },
            { id: "tables", label: `Tables (${storage.length})` },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 border-r last:border-r-0 ${
                tab === t.id ? "bg-[#AA00FF] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
              }`} style={{ borderColor: "var(--ss-divider)" }}
              data-testid={`storage-tab-${t.id}`}>{t.label}</button>
          ))}
        </div>
        </div>
      </div>

      {tab === "databases" && <DatabasesView databases={databases} />}
      {tab === "disk" && <DiskUsageView dbDisk={dbDisk} derived={diskDerived} />}
      {tab === "partitions" && <PartitionsView partitions={partitions} />}
      {tab === "tables" && <TablesView storage={storage} />}
    </div>
  );
}

function DatabasesView({ databases }) {
  if (!databases.length) return <EmptyState text="No database data available" />;
  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <div className="border-b px-4 py-3 flex items-center gap-2" style={{ borderColor: "var(--ss-divider)" }}>
        <Database size={14} style={{ color: "var(--ss-mid-gray)" }} />
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          SHOW DATABASES EXTENDED
        </h3>
        <span className="text-xs ml-1" style={{ color: "var(--ss-mid-gray)" }}>
          Per-database partition state and replication details
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full dense-table" data-testid="databases-table">
          <thead>
            <tr>
              <th className="text-left">Database</th>
              <th className="text-left">Role</th>
              <th className="text-left">State</th>
              <th className="text-right">Memory (MB)</th>
              <th className="text-right">Commits</th>
              <th className="text-left">Position</th>
              <th className="text-right">Async Slaves</th>
              <th className="text-right">Sync Slaves</th>
            </tr>
          </thead>
          <tbody>
            {databases.map((db, i) => (
              <tr key={i}>
                <td className="font-medium" style={{ fontFamily: "IBM Plex Sans, sans-serif" }}>
                  <ExpandableCell value={db.Database} label="Database" className="max-w-[160px]" />
                </td>
                <td>
                  <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${
                    (db.Role || "").includes("master") ? "bg-[#AA00FF] text-white" : "bg-zinc-100 text-zinc-600"
                  }`}>{db.Role || "—"}</span>
                </td>
                <td>
                  <span className={`text-[10px] uppercase tracking-widest font-bold ${
                    ["online", "replicating"].some(s => (db.State || "").includes(s)) ? "status-success" : "status-warning"
                  }`}>{db.State || "—"}</span>
                </td>
                <td className="text-right">{db["Memory (MBs)"] || "—"}</td>
                <td className="text-right">{formatNumber(db.Commits)}</td>
                <td className="text-[11px]">
                  <ExpandableCell value={db.Position} label="Position" className="max-w-[140px]" />
                </td>
                <td className="text-right">{db.AsyncSlaves || "—"}</td>
                <td className="text-right">{db.SyncSlaves || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DiskUsageView({ dbDisk, derived }) {
  if (!dbDisk.length) return <EmptyState text="No disk usage data" />;
  const sorted = [...dbDisk].sort((a, b) => diskGb(b) - diskGb(a));
  const maxGb = diskGb(sorted[0]) || 1;
  const totalGb = sorted.reduce((sum, d) => sum + diskGb(d), 0);

  return (
    <div className="space-y-4">
      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Database Disk Usage Treemap
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
            Total: {totalGb.toFixed(1)} GB across {sorted.length} databases. Identifies which databases consume the most storage.
          </p>
          {derived && (
            <p className="text-[10px] mt-1 status-warning">
              Estimated from table statistics (databaseDiskUsage.json not present in this bundle).
            </p>
          )}
        </div>
        <div className="p-4">
          <div className="flex flex-wrap gap-1" data-testid="disk-treemap">
            {sorted.map((db, i) => {
              const gb = diskGb(db);
              const pct = totalGb > 0 ? (gb / totalGb) * 100 : 0;
              const minWidth = Math.max(pct * 3, 60);
              const name = diskDbName(db);
              return (
                <div key={i}
                  className="border p-2 flex flex-col justify-between"
                  style={{
                    borderColor: "var(--ss-divider)",
                    background: i === 0 ? "rgba(0,47,167,0.05)" : "var(--ss-light-gray)",
                    minWidth: `${minWidth}px`,
                    flex: `${Math.max(pct, 5)} 1 0`,
                    height: `${Math.max(60, pct * 2)}px`
                  }}
                  title={`${name}: ${gb.toFixed(2)} GB (${pct.toFixed(1)}%)`}
                >
                  <span className="text-[10px] font-mono font-bold truncate">{name}</span>
                  <span className="text-[10px] font-mono" style={{ color: "#525252" }}>{gb.toFixed(1)} GB</span>
                </div>
              );
            })}
          </div>
        </div>
        <div className="border-t" style={{ borderColor: "var(--ss-divider)" }}>
          <table className="w-full dense-table" data-testid="disk-usage-table">
            <thead>
              <tr>
                <th className="text-left">Database</th>
                <th className="text-right">Size (GB)</th>
                <th className="text-left" style={{ width: "40%" }}>Proportion</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((db, i) => {
                const gb = diskGb(db);
                const pct = maxGb > 0 ? (gb / maxGb) * 100 : 0;
                return (
                  <tr key={i}>
                    <td className="font-medium" style={{ fontFamily: "IBM Plex Sans, sans-serif" }}>{diskDbName(db)}</td>
                    <td className="text-right font-bold">{gb.toFixed(2)}</td>
                    <td>
                      <div className="progress-bar">
                        <div className="progress-fill" style={{ width: `${pct}%`, background: "var(--ss-purple)" }} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function PartitionsView({ partitions }) {
  const dbNames = Object.keys(partitions);
  const [selectedDb, setSelectedDb] = useState(dbNames[0] || "");

  if (!dbNames.length) return <EmptyState text="No partition data" />;

  const dbData = partitions[selectedDb] || {};
  const parts = dbData.partitions || [];

  const hostCounts = {};
  parts.forEach(p => {
    const host = p.Host || "?";
    if (!hostCounts[host]) hostCounts[host] = { master: 0, slave: 0, total: 0 };
    hostCounts[host].total++;
    if ((p.Role || "").toLowerCase().includes("master")) hostCounts[host].master++;
    else hostCounts[host].slave++;
  });

  const avgPerHost = parts.length / Math.max(Object.keys(hostCounts).length, 1);
  const skewedHosts = Object.entries(hostCounts).filter(([, c]) => c.total > avgPerHost * 2);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap overflow-x-auto">
        {dbNames.map(db => (
          <button key={db} onClick={() => setSelectedDb(db)}
            className={`text-[10px] uppercase tracking-widest font-bold px-2 py-1 border ${
              selectedDb === db ? "bg-[#AA00FF] text-white border-[#AA00FF]" : "bg-white border-zinc-200"
            }`}>{db} ({partitions[db]?.count || 0})</button>
        ))}
      </div>

      {skewedHosts.length > 0 && (
        <div className="border-l-4 border-l-[#FF9800] px-4 py-2" style={{ background: "rgba(255,204,0,0.05)" }}>
          <p className="text-xs font-medium status-warning">
            Potential data skew: {skewedHosts.map(([h]) => h).join(", ")} have &gt;2x average partitions
          </p>
          <p className="text-[10px] mt-0.5" style={{ color: "#525252" }}>
            Data skew causes uneven query load across leaf nodes. Consider EXPLAIN REBALANCE PARTITIONS.
          </p>
        </div>
      )}

      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Partition Distribution: {selectedDb}
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
            {parts.length} partitions across {Object.keys(hostCounts).length} hosts
          </p>
        </div>
        <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(hostCounts).sort((a, b) => b[1].total - a[1].total).map(([host, counts]) => (
            <div key={host} className="border p-3" style={{ borderColor: "var(--ss-divider)" }}>
              <p className="text-[10px] font-mono">
                <ExpandableCell value={host} label="Host" className="max-w-full" />
              </p>
              <p className="text-lg font-mono font-bold mt-1">{counts.total}</p>
              <div className="flex gap-2 mt-1">
                <span className="text-[9px] font-bold" style={{ color: "var(--ss-purple)" }}>M:{counts.master}</span>
                <span className="text-[9px] font-bold" style={{ color: "var(--ss-mid-gray)" }}>S:{counts.slave}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TablesView({ storage }) {
  if (!storage.length) return <EmptyState text="No table statistics available" />;
  const cols = Object.keys(storage[0] || {}).slice(0, 10);
  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Table Statistics ({storage.length})
        </h3>
        <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
          Oversized rowstore tables may indicate missing columnstore conversion. Large index sizes suggest over-indexing. Tap any cell to view the full value.
        </p>
      </div>
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full dense-table" data-testid="storage-table">
          <thead className="sticky top-0">
            <tr>{cols.map(col => <th key={col} className="text-left">{col}</th>)}</tr>
          </thead>
          <tbody>
            {storage.slice(0, 100).map((row, i) => (
              <tr key={i}>
                {cols.map(c => (
                  <td key={c} className="text-[11px]">
                    <ExpandableCell value={row[c]} label={c} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {storage.length > 100 && (
        <p className="text-xs px-4 py-2" style={{ color: "var(--ss-mid-gray)" }}>Showing 100 of {storage.length}</p>
      )}
    </div>
  );
}

function EmptyState({ text }) {
  return (
    <div className="text-center py-12 border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <Database size={32} className="mx-auto mb-2" style={{ color: "var(--ss-mid-gray)" }} />
      <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>{text}</p>
    </div>
  );
}
