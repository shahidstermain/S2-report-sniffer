import { useState, useEffect } from "react";
import { Loader2, Shield, Key, CheckCircle2, XCircle, AlertTriangle, Clock, ExternalLink } from "lucide-react";
import { getReportConfig } from "@/lib/api";

export default function ConfigHealth({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("os");

  useEffect(() => {
    getReportConfig(reportId).then(res => { setData(res.data); setLoading(false); }).catch(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--brand-primary)" }} /></div>;
  if (!data) return <p className="text-sm p-4" style={{ color: "var(--text-tertiary)" }}>No config data</p>;

  const ch = data.config_health || {};
  const osChecks = ch.os_checks || [];
  const varConsistency = ch.variable_consistency || {};
  const license = ch.license || {};
  const backups = data.backup_history || [];
  const users = data.users || [];
  const nodes = data.nodes || [];

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Configuration & Security Health
        </h2>
        <div className="ml-auto flex gap-0 border" style={{ borderColor: "var(--border-default)" }}>
          {[
            { id: "os", label: "OS Tuning" },
            { id: "vars", label: "Variables" },
            { id: "license", label: "License" },
            { id: "backup", label: "Backups" },
            { id: "users", label: "Users" },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 border-r last:border-r-0 ${
                tab === t.id ? "bg-[#002FA7] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
              }`} style={{ borderColor: "var(--border-default)" }}
              data-testid={`config-tab-${t.id}`}>{t.label}</button>
          ))}
        </div>
      </div>

      {tab === "os" && <OSTuningChecklist checks={osChecks} nodes={nodes} />}
      {tab === "vars" && <VariableConsistency vars={varConsistency} nodes={nodes} />}
      {tab === "license" && <LicenseCard license={license} />}
      {tab === "backup" && <BackupHealth backups={backups} />}
      {tab === "users" && <UsersAudit users={users} />}
    </div>
  );
}

function OSTuningChecklist({ checks, nodes }) {
  return (
    <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
      <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          OS Tuning Checklist
        </h3>
        <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
          System configuration checks based on SingleStore requirements
        </p>
      </div>
      <div className="divide-y" style={{ borderColor: "#F4F4F5" }}>
        {checks.map((check, i) => (
          <div key={i} className="flex items-start gap-3 px-4 py-3" data-testid={`os-check-${i}`}>
            <StatusIcon status={check.status} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{check.name}</span>
                <StatusBadge status={check.status} severity={check.severity} />
              </div>
              <p className="text-xs font-mono mt-0.5" style={{ color: "var(--text-secondary)" }}>{check.detail}</p>
              {check.remediation && check.status !== "pass" && (
                <p className="text-xs mt-1" style={{ color: "var(--brand-primary)" }}>{check.remediation}</p>
              )}
              {check.doc_link && check.status !== "pass" && (
                <a href={check.doc_link} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[10px] mt-1 underline" style={{ color: "var(--brand-primary)" }}>
                  <ExternalLink size={10} /> Documentation
                </a>
              )}
            </div>
          </div>
        ))}
        {/* Per-node process limits */}
        {nodes.map(n => {
          const pl = n.config?.process_limits || {};
          if (!pl.open_files_soft) return null;
          return (
            <div key={n.hostname} className="flex items-start gap-3 px-4 py-3">
              <StatusIcon status={pl.open_files_soft >= 100000 ? "pass" : "fail"} />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">nofile on {n.hostname}</span>
                  <StatusBadge status={pl.open_files_soft >= 100000 ? "pass" : "fail"} />
                </div>
                <p className="text-xs font-mono mt-0.5" style={{ color: "var(--text-secondary)" }}>
                  Soft: {pl.open_files_soft?.toLocaleString()} | Hard: {pl.open_files_hard?.toLocaleString()}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function VariableConsistency({ vars, nodes }) {
  const entries = Object.entries(vars);
  if (!entries.length) return <p className="text-sm p-4" style={{ color: "var(--text-tertiary)" }}>No variable data</p>;

  return (
    <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
      <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Key Variable Consistency
        </h3>
        <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
          Comparing critical SingleStore variables across all nodes
        </p>
      </div>
      <table className="w-full dense-table" data-testid="vars-table">
        <thead>
          <tr>
            <th className="text-left">Variable</th>
            <th className="text-left">Status</th>
            <th className="text-left">Values</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([name, vc]) => (
            <tr key={name}>
              <td className="font-medium" style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "12px" }}>{name}</td>
              <td>
                {vc.consistent ? (
                  <span className="badge-healthy text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5">CONSISTENT</span>
                ) : (
                  <span className="badge-warning text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5">MISMATCH</span>
                )}
              </td>
              <td className="text-[11px] font-mono">
                {vc.unique_values?.join(", ") || "—"}
                {!vc.consistent && (
                  <div className="text-[10px] mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                    {Object.entries(vc.values || {}).map(([h, v]) =>
                      <span key={h} className="mr-2">{h.split('.')[0]}={v}</span>
                    )}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LicenseCard({ license }) {
  if (!license || !license.type) {
    return <p className="text-sm p-4" style={{ color: "var(--text-tertiary)" }}>No license data available</p>;
  }
  const days = license.days_remaining;
  const isExpiring = days != null && days < 90;
  const isCritical = days != null && days < 30;

  return (
    <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
      <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>License Information</h3>
      </div>
      <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="license-card">
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>Type</p>
          <p className="text-lg font-mono font-bold mt-1">{license.type}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>Capacity</p>
          <p className="text-lg font-mono font-bold mt-1">{license.capacity}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>Expires</p>
          <p className={`text-lg font-mono font-bold mt-1 ${isCritical ? "status-critical" : isExpiring ? "status-warning" : ""}`}>
            {license.expiry_date ? new Date(license.expiry_date).toLocaleDateString() : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>Days Remaining</p>
          <p className={`text-lg font-mono font-bold mt-1 ${isCritical ? "status-critical" : isExpiring ? "status-warning" : "status-success"}`}>
            {days != null ? `${days} days` : "—"}
          </p>
        </div>
      </div>
      {isCritical && (
        <div className="border-t px-4 py-3" style={{ borderColor: "var(--border-default)", background: "rgba(255,59,48,0.03)" }}>
          <p className="text-xs font-medium status-critical">License expiring soon. Contact SingleStore sales to renew.</p>
        </div>
      )}
    </div>
  );
}

function BackupHealth({ backups }) {
  if (!backups.length) {
    return (
      <div className="border p-8 text-center" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <AlertTriangle size={32} className="mx-auto mb-2 status-warning" />
        <p className="text-sm font-medium">No backup history found</p>
        <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>
          MV_BACKUP_HISTORY is empty. Configure regular backups immediately.
        </p>
      </div>
    );
  }

  const successful = backups.filter(b => (b.STATUS || "").toLowerCase() === "success");
  const latest = successful.length > 0 ? successful[successful.length - 1] : null;
  const byDb = {};
  backups.forEach(b => {
    const db = b.DATABASE_NAME || "?";
    if (!byDb[db]) byDb[db] = { total: 0, success: 0, latest: "" };
    byDb[db].total++;
    if ((b.STATUS || "").toLowerCase() === "success") {
      byDb[db].success++;
      if (b.START_TIMESTAMP > byDb[db].latest) byDb[db].latest = b.START_TIMESTAMP;
    }
  });

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-px bg-zinc-200 border" style={{ borderColor: "var(--border-default)" }}>
        <div className="bg-white p-4">
          <p className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>Total Backups</p>
          <p className="text-2xl font-mono font-bold mt-1">{backups.length}</p>
        </div>
        <div className="bg-white p-4">
          <p className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>Successful</p>
          <p className="text-2xl font-mono font-bold mt-1 status-success">{successful.length}</p>
        </div>
        <div className="bg-white p-4">
          <p className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>Latest Backup</p>
          <p className="text-sm font-mono font-bold mt-1">{latest?.START_TIMESTAMP || "None"}</p>
        </div>
      </div>

      {/* Per-database */}
      <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>Backup by Database</h3>
        </div>
        <table className="w-full dense-table" data-testid="backup-table">
          <thead>
            <tr>
              <th className="text-left">Database</th>
              <th className="text-right">Total</th>
              <th className="text-right">Successful</th>
              <th className="text-left">Latest Backup</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(byDb).sort((a, b) => b[1].total - a[1].total).slice(0, 20).map(([db, info]) => (
              <tr key={db}>
                <td className="font-medium" style={{ fontFamily: "IBM Plex Sans, sans-serif" }}>{db}</td>
                <td className="text-right">{info.total}</td>
                <td className="text-right status-success">{info.success}</td>
                <td className="text-[11px]">{info.latest || "Never"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UsersAudit({ users }) {
  if (!users.length) return <p className="text-sm p-4" style={{ color: "var(--text-tertiary)" }}>No user data</p>;

  return (
    <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
      <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Users ({users.length})
        </h3>
      </div>
      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
        <table className="w-full dense-table" data-testid="users-table">
          <thead className="sticky top-0">
            <tr>
              <th className="text-left">User</th>
              <th className="text-left">Type</th>
              <th className="text-right">Connections</th>
              <th className="text-left">Resource Pool</th>
              <th className="text-left">Local</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u, i) => (
              <tr key={i}>
                <td className="font-medium" style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "11px" }}>{u.User || "—"}</td>
                <td>{u.Type || "—"}</td>
                <td className="text-right">{u.Connections || "0"}</td>
                <td className="text-[11px]">{u["Default resource pool"] || "default_pool"}</td>
                <td>{u["Is local"] || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusIcon({ status }) {
  if (status === "pass") return <CheckCircle2 size={16} className="status-success mt-0.5 flex-shrink-0" />;
  if (status === "fail") return <XCircle size={16} className="status-critical mt-0.5 flex-shrink-0" />;
  return <AlertTriangle size={16} className="status-warning mt-0.5 flex-shrink-0" />;
}

function StatusBadge({ status, severity }) {
  if (status === "pass") return <span className="badge-healthy text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5">PASS</span>;
  if (status === "fail") return <span className="badge-critical text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5">FAIL</span>;
  return <span className="badge-warning text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5">WARN</span>;
}
