import { useState, useEffect } from "react";
import { Loader2, Database } from "lucide-react";
import { getReportStorage } from "@/lib/api";
import { formatNumber } from "@/lib/utils-sdb";

export default function StorageDistribution({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getReportStorage(reportId).then(res => { setData(res.data); setLoading(false); }).catch(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--brand-primary)" }} /></div>;
  if (!data) return <p className="text-sm p-4" style={{ color: "var(--text-tertiary)" }}>No data available</p>;

  const databases = data.databases || [];
  const storage = data.storage || [];

  return (
    <div className="animate-fade-in space-y-6">
      <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
        Storage & Distribution
      </h2>

      {/* Databases */}
      {databases.length > 0 && (
        <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3 flex items-center gap-2" style={{ borderColor: "var(--border-default)" }}>
            <Database size={14} style={{ color: "var(--text-tertiary)" }} />
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Databases ({databases.length})
            </h3>
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
                </tr>
              </thead>
              <tbody>
                {databases.map((db, i) => (
                  <tr key={i}>
                    <td className="font-medium" style={{ fontFamily: "IBM Plex Sans, sans-serif" }}>{db.Database || "—"}</td>
                    <td>
                      <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${
                        (db.Role || "").includes("master") ? "bg-[#002FA7] text-white" : "bg-zinc-100 text-zinc-600"
                      }`}>
                        {db.Role || "—"}
                      </span>
                    </td>
                    <td>
                      <span className={`text-[10px] uppercase tracking-widest font-bold ${
                        (db.State || "").includes("online") || (db.State || "").includes("replicating") ? "status-success" : "status-warning"
                      }`}>
                        {db.State || "—"}
                      </span>
                    </td>
                    <td className="text-right">{db["Memory (MBs)"] || "—"}</td>
                    <td className="text-right">{formatNumber(db.Commits)}</td>
                    <td className="text-[11px]">{db.Position || "—"}</td>
                    <td className="text-right">{db.AsyncSlaves || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Table Statistics */}
      {storage.length > 0 && (
        <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
            <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Table Statistics ({storage.length})
            </h3>
          </div>
          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full dense-table" data-testid="storage-table">
              <thead className="sticky top-0">
                <tr>
                  {Object.keys(storage[0] || {}).slice(0, 8).map(col => (
                    <th key={col} className="text-left">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {storage.slice(0, 100).map((row, i) => (
                  <tr key={i}>
                    {Object.values(row).slice(0, 8).map((val, j) => (
                      <td key={j} className="text-[11px] truncate max-w-[200px]" title={String(val)}>
                        {String(val || "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {storage.length > 100 && (
            <p className="text-xs px-4 py-2" style={{ color: "var(--text-tertiary)" }}>
              Showing 100 of {storage.length} entries
            </p>
          )}
        </div>
      )}

      {databases.length === 0 && storage.length === 0 && (
        <div className="text-center py-12 border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <Database size={32} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)" }} />
          <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>No storage data available in this report</p>
        </div>
      )}
    </div>
  );
}
