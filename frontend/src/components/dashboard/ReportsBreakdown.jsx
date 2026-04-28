import { CheckCircle2, AlertTriangle, XCircle, Loader2, Server } from "lucide-react";

function HealthRow({ label, count, total, color, icon: Icon }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3 py-2">
      <Icon size={14} style={{ color }} />
      <span className="text-xs flex-1 truncate" style={{ color: "var(--text-primary)" }}>{label}</span>
      <span className="text-xs tabular-nums font-semibold" style={{ color: "var(--text-primary)" }}>{count}</span>
      <span className="text-[10px] tabular-nums w-9 text-right" style={{ color: "var(--text-muted)" }}>{pct}%</span>
    </div>
  );
}

function Bar({ pct, color }) {
  return (
    <div className="h-1 rounded-full overflow-hidden mt-1" style={{ background: "var(--border-default)" }}>
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export default function ReportsBreakdown({ status, deployments, totalReady }) {
  const total = totalReady || (status.healthy + status.warning + status.critical) || 1;
  const items = [
    { label: "Healthy", count: status.healthy, color: "#00C853", icon: CheckCircle2 },
    { label: "Warning", count: status.warning, color: "#FF9800", icon: AlertTriangle },
    { label: "Critical", count: status.critical, color: "#F44336", icon: XCircle },
    { label: "Processing", count: status.processing, color: "#AA00FF", icon: Loader2 },
    { label: "Errored", count: status.error, color: "#6B6B80", icon: XCircle },
  ];

  return (
    <div className="space-y-3">
      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Health breakdown
        </h3>
        <p className="text-[11px] mb-3" style={{ color: "var(--text-muted)" }}>
          {totalReady} ready reports
        </p>
        <div className="divide-y" style={{ borderColor: "var(--border-default)" }}>
          {items.map((it) => (
            <HealthRow key={it.label} {...it} total={total} />
          ))}
        </div>
      </div>

      <div className="surface-card p-4">
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Top deployments
        </h3>
        {deployments.length === 0 ? (
          <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>No data yet</p>
        ) : (
          <div className="space-y-3">
            {deployments.slice(0, 5).map((d) => (
              <div key={d.label}>
                <div className="flex items-center gap-2">
                  <Server size={12} style={{ color: "var(--text-muted)" }} />
                  <span className="text-xs flex-1 truncate" style={{ color: "var(--text-primary)" }}>{d.label}</span>
                  <span className="text-xs tabular-nums font-semibold" style={{ color: "var(--text-primary)" }}>{d.count}</span>
                  <span className="text-[10px] tabular-nums w-9 text-right" style={{ color: "var(--text-muted)" }}>{d.pct}%</span>
                </div>
                <Bar pct={d.pct} color="#AA00FF" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
