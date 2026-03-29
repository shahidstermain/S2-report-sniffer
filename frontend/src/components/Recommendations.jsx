import { useState, useEffect } from "react";
import { Loader2, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { getReportRecommendations } from "@/lib/api";
import { severityBadgeClass } from "@/lib/utils-sdb";

export default function Recommendations({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(new Set());
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    getReportRecommendations(reportId).then(res => { setData(res.data); setLoading(false); }).catch(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--ss-purple)" }} /></div>;

  const recs = data?.recommendations || [];
  const filtered = filter === "all" ? recs : recs.filter(r => r.severity === filter);

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const expandAll = () => setExpanded(new Set(filtered.map(r => r.id)));
  const collapseAll = () => setExpanded(new Set());

  const byCategory = {};
  filtered.forEach(r => {
    const cat = r.category || "Other";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(r);
  });

  const critCount = recs.filter(r => r.severity === "critical").length;
  const warnCount = recs.filter(r => r.severity === "warning").length;

  return (
    <div className="animate-fade-in">
      <div className="flex items-center gap-4 mb-4 flex-wrap">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Issues & Recommendations
        </h2>
        <span className="text-xs font-mono" style={{ color: "var(--ss-mid-gray)" }}>
          {recs.length} findings
        </span>

        {/* Severity filter */}
        <div className="ml-auto flex gap-0 border" style={{ borderColor: "var(--ss-divider)" }}>
          {[
            { id: "all", label: `All (${recs.length})` },
            { id: "critical", label: `Critical (${critCount})` },
            { id: "warning", label: `Warning (${warnCount})` },
          ].map(f => (
            <button key={f.id} onClick={() => setFilter(f.id)}
              className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 border-r last:border-r-0 ${
                filter === f.id ? "bg-[#AA00FF] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
              }`} style={{ borderColor: "var(--ss-divider)" }}
              data-testid={`rec-filter-${f.id}`}>{f.label}</button>
          ))}
        </div>
        <div className="flex gap-1">
          <button onClick={expandAll} className="text-[10px] underline" style={{ color: "var(--ss-purple)" }}>Expand All</button>
          <button onClick={collapseAll} className="text-[10px] underline ml-2" style={{ color: "var(--ss-mid-gray)" }}>Collapse</button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="border p-12 text-center" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
          <CheckCircle2 size={40} className="mx-auto mb-3" style={{ color: "var(--ss-success)" }} />
          <p className="text-sm font-medium" style={{ color: "#525252" }}>No issues detected</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(byCategory).map(([category, items]) => (
            <div key={category} className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
              <div className="border-b px-4 py-3 flex items-center gap-2" style={{ borderColor: "var(--ss-divider)" }}>
                <span className="text-[10px] uppercase tracking-[0.2em] font-bold" style={{ color: "var(--ss-mid-gray)" }}>
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
                      <button onClick={() => toggle(rec.id)}
                        className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-zinc-50 transition-colors">
                        <div className={`w-1 self-stretch flex-shrink-0 mt-0.5 ${
                          rec.severity === "critical" ? "bg-[#F44336]" : "bg-[#FF9800]"}`} />
                        {isExpanded ? <ChevronDown size={14} className="mt-0.5 flex-shrink-0" /> : <ChevronRight size={14} className="mt-0.5 flex-shrink-0" />}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${severityBadgeClass(rec.severity)}`}>
                              {rec.severity}
                            </span>
                            {rec.doc_link && (
                              <a href={rec.doc_link} target="_blank" rel="noopener noreferrer"
                                onClick={e => e.stopPropagation()}
                                className="inline-flex items-center gap-0.5 text-[10px] underline" style={{ color: "var(--ss-purple)" }}>
                                <ExternalLink size={9} /> Docs
                              </a>
                            )}
                          </div>
                          <p className="text-sm font-medium mt-1">{rec.title}</p>
                        </div>
                        {rec.nodes?.length > 0 && (
                          <span className="text-[10px] font-mono flex-shrink-0" style={{ color: "var(--ss-mid-gray)" }}>
                            {rec.nodes.join(", ")}
                          </span>
                        )}
                      </button>
                      {isExpanded && (
                        <div className="px-4 pb-4 pl-12 space-y-3 bg-zinc-50/50">
                          <div>
                            <SectionLabel>Description</SectionLabel>
                            <p className="text-sm" style={{ color: "#525252" }}>{rec.description}</p>
                          </div>
                          {rec.evidence && (
                            <div>
                              <SectionLabel>Evidence</SectionLabel>
                              <p className="text-xs font-mono p-2 border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
                                {rec.evidence}
                              </p>
                            </div>
                          )}
                          {rec.remediation && (
                            <div>
                              <SectionLabel>Recommended Action</SectionLabel>
                              <p className="text-sm" style={{ color: "var(--ss-purple)" }}>{rec.remediation}</p>
                            </div>
                          )}
                          {rec.related_views?.length > 0 && (
                            <div>
                              <SectionLabel>Sources</SectionLabel>
                              <p className="text-[10px] font-mono" style={{ color: "var(--ss-mid-gray)" }}>
                                {rec.related_views.join(", ")}
                              </p>
                            </div>
                          )}
                          {rec.doc_link && (
                            <a href={rec.doc_link} target="_blank" rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs underline" style={{ color: "var(--ss-purple)" }}>
                              <ExternalLink size={12} /> View Documentation
                            </a>
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

function SectionLabel({ children }) {
  return (
    <p className="text-[10px] uppercase tracking-[0.2em] font-bold mb-1" style={{ color: "var(--ss-mid-gray)" }}>
      {children}
    </p>
  );
}
