import { useState, useEffect } from "react";
import { Loader2, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";
import { getReportRecommendations } from "@/lib/api";
import { severityBadgeClass } from "@/lib/utils-sdb";

export default function Recommendations({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(new Set());

  useEffect(() => {
    getReportRecommendations(reportId).then(res => { setData(res.data); setLoading(false); }).catch(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--brand-primary)" }} /></div>;

  const recs = data?.recommendations || [];

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const byCategory = {};
  recs.forEach(r => {
    const cat = r.category || "other";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(r);
  });

  return (
    <div className="animate-fade-in">
      <div className="flex items-center gap-4 mb-4">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Issues & Recommendations
        </h2>
        <span className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
          {recs.length} findings
        </span>
      </div>

      {recs.length === 0 ? (
        <div className="border p-12 text-center" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
          <CheckCircle2 size={40} className="mx-auto mb-3" style={{ color: "var(--status-success)" }} />
          <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>No issues detected</p>
          <p className="text-xs mt-1" style={{ color: "var(--text-tertiary)" }}>The cluster appears healthy based on available data</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(byCategory).map(([category, items]) => (
            <div key={category} className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
              <div className="border-b px-4 py-3 flex items-center gap-2" style={{ borderColor: "var(--border-default)" }}>
                <span className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--text-tertiary)" }}>
                  {category}
                </span>
                <span className="text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 bg-zinc-100 text-zinc-500">
                  {items.length}
                </span>
              </div>
              <div className="divide-y" style={{ borderColor: "#F4F4F5" }}>
                {items.map((rec) => {
                  const isExpanded = expanded.has(rec.id);
                  return (
                    <div key={rec.id} data-testid={`rec-${rec.id}`}>
                      <button
                        onClick={() => toggle(rec.id)}
                        className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-zinc-50 transition-colors"
                      >
                        <div className={`w-1 self-stretch flex-shrink-0 mt-0.5 ${
                          rec.severity === "critical" ? "bg-[#FF3B30]" : "bg-[#FFCC00]"
                        }`} />
                        {isExpanded ? <ChevronDown size={14} className="mt-0.5 flex-shrink-0" /> : <ChevronRight size={14} className="mt-0.5 flex-shrink-0" />}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${severityBadgeClass(rec.severity)}`}>
                              {rec.severity}
                            </span>
                          </div>
                          <p className="text-sm font-medium mt-1">{rec.title}</p>
                        </div>
                        {rec.nodes?.length > 0 && (
                          <span className="text-[10px] font-mono flex-shrink-0" style={{ color: "var(--text-tertiary)" }}>
                            {rec.nodes.join(", ")}
                          </span>
                        )}
                      </button>
                      {isExpanded && (
                        <div className="px-4 pb-4 pl-12 space-y-3">
                          <div>
                            <p className="text-[10px] uppercase tracking-[0.2em] font-bold mb-1" style={{ color: "var(--text-tertiary)" }}>
                              Description
                            </p>
                            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{rec.description}</p>
                          </div>
                          {rec.evidence && (
                            <div>
                              <p className="text-[10px] uppercase tracking-[0.2em] font-bold mb-1" style={{ color: "var(--text-tertiary)" }}>
                                Evidence
                              </p>
                              <p className="text-xs font-mono p-2 border" style={{ borderColor: "var(--border-default)", background: "var(--muted-bg)" }}>
                                {rec.evidence}
                              </p>
                            </div>
                          )}
                          {rec.remediation && (
                            <div>
                              <p className="text-[10px] uppercase tracking-[0.2em] font-bold mb-1" style={{ color: "var(--text-tertiary)" }}>
                                Recommended Action
                              </p>
                              <p className="text-sm" style={{ color: "var(--brand-primary)" }}>{rec.remediation}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
