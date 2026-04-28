import { useNavigate } from "react-router-dom";
import { CheckCircle2, AlertTriangle, XCircle, Loader2, ChevronRight } from "lucide-react";

function timeAgo(value) {
  if (!value) return "—";
  const t = new Date(value).getTime();
  if (!Number.isFinite(t)) return "—";
  const diff = Date.now() - t;
  const sec = Math.round(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.round(hr / 24);
  return `${d}d ago`;
}

function statusGlyph(r) {
  const s = String(r.status || "").toLowerCase();
  if (s === "processing") return { Icon: Loader2, color: "#AA00FF", spin: true };
  if (s === "error") return { Icon: XCircle, color: "#F44336" };
  const h = String(r.health_score || "").toLowerCase();
  if (h === "critical") return { Icon: XCircle, color: "#F44336" };
  if (h === "warning") return { Icon: AlertTriangle, color: "#FF9800" };
  return { Icon: CheckCircle2, color: "#00C853" };
}

export default function RecentActivity({ reports }) {
  const navigate = useNavigate();
  const items = [...reports]
    .sort((a, b) => new Date(b.uploaded_at || 0).getTime() - new Date(a.uploaded_at || 0).getTime())
    .slice(0, 6);

  return (
    <div className="surface-card p-4">
      <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
        Recent activity
      </h3>
      {items.length === 0 ? (
        <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
          No recent uploads
        </p>
      ) : (
        <ul className="divide-y" style={{ borderColor: "var(--border-default)" }}>
          {items.map((r) => {
            const { Icon, color, spin } = statusGlyph(r);
            return (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => r.status === "ready" && navigate(`/report/${r.id}`)}
                  disabled={r.status !== "ready"}
                  className="w-full text-left py-2 flex items-center gap-2 group"
                  data-testid={`recent-${r.id}`}
                >
                  <Icon size={14} className={spin ? "animate-spin" : ""} style={{ color, flexShrink: 0 }} />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
                      {r.report_name || "Report"}
                    </p>
                    <p className="text-[10px] tabular-nums" style={{ color: "var(--text-muted)" }}>
                      {timeAgo(r.uploaded_at)} · {r.deployment_method || "—"}
                    </p>
                  </div>
                  {r.status === "ready" && (
                    <ChevronRight size={14} style={{ color: "var(--text-muted)" }} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
