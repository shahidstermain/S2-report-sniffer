import { useState, useEffect, useCallback } from "react";
import { Loader2, ChevronLeft, ExternalLink, Search, Copy, Download, MessageSquare, Zap, Globe, Shield, Wrench, AlertTriangle, Clock, Layers, ListTodo, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { getReportRecommendations, getReportTriage, listQueryTraces, getGleanPacket } from "@/lib/api";
import { handoffGleanPacket } from "@/lib/gleanHandoff";
import { SeverityBadge } from "@/components/SeverityBadge";
import InfoHint from "./InfoHint";
import QueryTracerPanel from "./QueryTracerPanel";

const GROUNDING_BASIS_COLORS = {
  documented: "var(--ss-success)",
  "toolbox-default": "#00d992",
  heuristic: "var(--ss-warning)",
  observed: "var(--ss-purple)",
};

const GROUNDING_BASIS_LABELS = {
  documented: "Threshold published in SingleStore documentation",
  "toolbox-default": "SingleStore Toolbox / first-party tool default",
  heuristic: "Operational rule of thumb applied by this tool (not a documented SingleStore threshold)",
  observed: "Derived directly from evidence in this report bundle",
};

const TRACEABLE_CHECKERS = new Set([
  "runawayQueries",
  "slowQueries",
  "lockContention",
  "severeLockContention",
  "longRunningTransactions",
  "unkillableTransaction",
  "repeatedQueryPatterns",
]);

const LOCK_TRACE_CHECKERS = new Set([
  "lockContention",
  "severeLockContention",
  "unkillableTransaction",
]);

export function filterRecommendationsByCluster(recs, clusterId, clusters) {
  if (!clusterId) return recs;
  const cluster = clusters.find((c) => c.cluster_id === clusterId);
  if (!cluster) return recs;

  const byStamp = recs.filter((r) => r.triage?.cluster_id === clusterId);
  if (byStamp.length > 0) return byStamp;

  const memberIds = new Set((cluster.member_ids || []).map(String));
  return recs.filter((r) => memberIds.has(String(r.id)));
}

function isTraceableFinding(rec) {
  if (!rec) return false;
  return TRACEABLE_CHECKERS.has(rec.checker_id) || rec.category === "Query";
}

function traceSelectorFromFinding(rec) {
  if (!rec) return null;
  if (!TRACEABLE_CHECKERS.has(rec.checker_id) && rec.category !== "Query") return null;
  const evidence = rec.evidence || "";
  const queryMatch =
    evidence.match(/query=([^\n]+?)(?:\s*$|\s+user=)/) ||
    evidence.match(/sample=([^\n]+)/);
  if (queryMatch?.[1]) {
    return { query_text: queryMatch[1].trim() };
  }
  return null;
}

const TRIAGE_BUCKETS = [
  { key: "act_now", label: "Act Now", icon: AlertTriangle, color: "#F44336", desc: "Critical / data-at-risk" },
  { key: "quick_wins", label: "Quick Wins", icon: Zap, color: "#FF9800", desc: "Low-effort fixes first" },
  { key: "act_soon", label: "Act Soon", icon: Clock, color: "#FFC107", desc: "Warnings to address" },
  { key: "backlog", label: "Backlog", icon: ListTodo, color: "#2196F3", desc: "Informational items" },
];

function findRecById(recs, id) {
  return recs.find((r) => String(r.id) === String(id));
}

export default function Recommendations({ reportId, onNavigateTab }) {
  const [data, setData] = useState(null);
  const [triageData, setTriageData] = useState(null);
  const [triageError, setTriageError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [activeTriageBucket, setActiveTriageBucket] = useState(null);
  const [activeClusterId, setActiveClusterId] = useState(null);
  const [selectedFinding, setSelectedFinding] = useState(null);
  const [traceSelector, setTraceSelector] = useState(null);
  const [slackCopiedId, setSlackCopiedId] = useState(null);
  const [gleanBusy, setGleanBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setTriageData(null);
    setTriageError(null);

    Promise.all([
      getReportRecommendations(reportId),
      getReportTriage(reportId).catch((err) => ({ __error: err })),
    ])
      .then(([recRes, triageRes]) => {
        if (cancelled) return;
        const recs = recRes.data?.recommendations || [];
        setData(recRes.data);

        if (triageRes?.__error) {
          const status = triageRes.__error?.response?.status;
          setTriageError(status || "network");
        } else {
          setTriageData(triageRes.data);
          setTriageError(null);
        }
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [reportId]);

  const closeFinding = useCallback(() => {
    setSelectedFinding(null);
  }, []);

  useEffect(() => {
    const onKeyDown = (e) => { if (e.key === "Escape") closeFinding(); };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeFinding]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--ss-purple)" }} /></div>;

  const recs = data?.recommendations || [];
  const clusters = triageData?.incident_clusters || [];
  const triageSummary = triageData?.summary;

  let filtered = recs;
  if (search) {
    const q = search.toLowerCase();
    filtered = filtered.filter((r) =>
      (r.title || "").toLowerCase().includes(q) ||
      (r.description || "").toLowerCase().includes(q) ||
      (r.checker_id || "").toLowerCase().includes(q)
    );
  }
  if (filter !== "all") {
    filtered = filtered.filter((r) => r.severity === filter);
  }

  let tableRecs = selectedGroup
    ? (() => {
        const byCat = {};
        filtered.forEach((r) => {
          const cat = r.category || "Other";
          if (!byCat[cat]) byCat[cat] = [];
          byCat[cat].push(r);
        });
        return byCat[selectedGroup] || [];
      })()
    : filtered;

  if (activeTriageBucket && triageData?.[activeTriageBucket]) {
    const bucketIds = new Set(triageData[activeTriageBucket].map((e) => String(e.id)));
    tableRecs = tableRecs.filter((r) => bucketIds.has(String(r.id)));
  }

  if (activeClusterId) {
    tableRecs = filterRecommendationsByCluster(tableRecs, activeClusterId, clusters);
  }

  const critCount = recs.filter((r) => r.severity === "critical").length;
  const warnCount = recs.filter((r) => r.severity === "warning").length;
  const infoCount = recs.filter((r) => r.severity === "info").length;

  const scorePenalty = critCount * 15 + warnCount * 5;
  const healthScore = Math.max(0, 100 - scorePenalty);
  let grade = "A";
  let gradeColor = "var(--ss-success)";
  if (healthScore < 60) { grade = "F"; gradeColor = "#F44336"; }
  else if (healthScore < 70) { grade = "D"; gradeColor = "#FF9800"; }
  else if (healthScore < 80) { grade = "C"; gradeColor = "#FFC107"; }
  else if (healthScore < 90) { grade = "B"; gradeColor = "#8BC34A"; }

  const byCategory = {};
  filtered.forEach((r) => {
    const cat = r.category || "Other";
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(r);
  });

  const exportJSON = () => {
    const blob = new Blob([JSON.stringify({ recommendations: recs, triage: triageData }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `superchecker-findings-${reportId}.json`;
    a.click();
  };

  const analyzeInGlean = async () => {
    if (!reportId || gleanBusy) return;
    setGleanBusy(true);
    try {
      const res = await getGleanPacket(reportId);
      await handoffGleanPacket(res.data || {});
    } catch (err) {
      toast.error(err?.response?.data?.detail || err?.message || "Failed to build Glean packet");
    } finally {
      setGleanBusy(false);
    }
  };

  const copyToClipboard = () => {
    const s = triageSummary;
    const text = s
      ? `Cluster Health: ${healthScore}/100 (${grade})\nAct Now: ${s.act_now} | Quick Wins: ${s.quick_wins} | Act Soon: ${s.act_soon} | Backlog: ${s.backlog}\nIncidents: ${s.incident_clusters}\nReport: ${reportId}`
      : `Cluster Health: ${healthScore}/100 (${grade})\n${critCount} CRITICAL | ${warnCount} WARNING | ${infoCount} INFO\nReport: ${reportId}`;
    navigator.clipboard.writeText(text);
    alert("Copied to clipboard!");
  };

  const copyFindingToSlack = (rec) => {
    const triage = rec.triage || {};
    const severityEmoji = rec.severity === "critical" ? "🔴" : rec.severity === "warning" ? "🟡" : "🔵";
    const lines = [
      `${severityEmoji} *S2 Report Sniffer — ${rec.severity?.toUpperCase()} finding*`,
      `*${rec.title}*`,
      ``,
      `*Category:* ${rec.category || "—"}`,
      `*Checker:* \`${rec.checker_id}\``,
      `*Risk Score:* ${rec.risk_score || "—"}`,
      `*Confidence:* ${rec.confidence ? Math.round(rec.confidence * 100) + "%" : "—"}`,
      `*Impact:* ${triage.impact || "—"}`,
      `*Effort:* ${triage.effort || "—"}`,
      `*Blast Radius:* ${triage.blast_radius || "—"}`,
      triage.cluster_id ? `*Incident:* ${triage.cluster_id}` : "",
      triage.quick_win ? "⚡ *Quick Win — low effort, do this first*" : "",
      ``,
      `*Description:* ${rec.description || "—"}`,
      ``,
      `*Remediation:* ${rec.remediation || "—"}`,
      ``,
      `*Recommended Action:* ${triage.recommended_action || "—"}`,
      rec.nodes?.length > 0 ? `*Affected Nodes:* ${rec.nodes.join(", ")}` : "*Affected Nodes:* Cluster-wide",
      ``,
      `Report: ${reportId}`,
    ].filter(Boolean);
    navigator.clipboard.writeText(lines.join("\n")).then(() => {
      setSlackCopiedId(rec.id);
      setTimeout(() => setSlackCopiedId(null), 2000);
    });
  };

  const openFinding = (recOrId) => {
    const rec = typeof recOrId === "object" ? recOrId : findRecById(recs, recOrId);
    if (rec) setSelectedFinding(rec);
  };

  const toggleTriageBucket = (key) => {
    setActiveClusterId(null);
    setSelectedGroup(null);
    setActiveTriageBucket((prev) => (prev === key ? null : key));
  };

  const toggleCluster = (clusterId) => {
    setActiveTriageBucket(null);
    setSelectedGroup(null);
    setActiveClusterId((prev) => (prev === clusterId ? null : clusterId));
  };

  const openFindingTrace = async (rec) => {
    const direct = traceSelectorFromFinding(rec);
    if (direct) {
      setTraceSelector(direct);
      return;
    }
    if (LOCK_TRACE_CHECKERS.has(rec.checker_id)) {
      try {
        const res = await listQueryTraces(reportId);
        const lockTrace = (res.data?.traces || []).find((t) => t.trace_type === "lock_wait");
        if (lockTrace?.trace_id) {
          setTraceSelector({ trace_id: lockTrace.trace_id });
        }
      } catch {
        /* trace index unavailable */
      }
    }
  };

  return (
    <div className="animate-fade-in flex flex-col h-full">
      {traceSelector && (
        <QueryTracerPanel
          reportId={reportId}
          selector={traceSelector}
          onClose={() => setTraceSelector(null)}
        />
      )}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-6 p-4 sm:p-6 bg-white border border-[var(--ss-divider)] shadow-sm">
        <div className="flex items-center gap-4 sm:gap-6 min-w-0">
          <div style={{ width: 80, height: 80, position: "relative" }}>
            <svg width="80" height="80" viewBox="0 0 80 80">
              <circle cx="40" cy="40" r="34" fill="none" stroke="var(--ss-light-gray, #f4f4f5)" strokeWidth="6" />
              <circle
                cx="40" cy="40" r="34" fill="none" stroke={gradeColor} strokeWidth="6"
                strokeLinecap="round"
                strokeDasharray="213.6"
                strokeDashoffset={213.6 - (213.6 * healthScore / 100)}
                transform="rotate(-90 40 40)"
                className="gauge-ring"
                style={{ "--gauge-offset": `${213.6 - (213.6 * healthScore / 100)}` }}
              />
              <text x="40" y="44" textAnchor="middle" fontSize="22" fontWeight="700" fill={gradeColor} fontFamily="JetBrains Mono, monospace">{healthScore}</text>
              <text x="40" y="56" textAnchor="middle" fontSize="9" fontWeight="600" fill="var(--ss-mid-gray)" letterSpacing="1">{grade}</text>
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-1">
              <h2 className="text-xl font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>Cluster Health Score: Grade {grade}</h2>
              <InfoHint
                label="cluster health score"
                content="A triage score derived from detected findings: critical findings carry a larger penalty than warnings. Use the underlying evidence and remediation, not the grade alone."
              />
            </div>
            <div className="flex gap-4 mt-2 flex-wrap">
              <span className="text-xs font-bold text-[#F44336]">{critCount} CRITICAL</span>
              <span className="text-xs font-bold text-[#FF9800]">{warnCount} WARNING</span>
              <span className="text-xs font-bold text-[#2196F3]">{infoCount} INFO</span>
              {triageSummary && (
                <span className="text-xs font-mono text-[var(--ss-mid-gray)]">
                  {triageSummary.incident_clusters} incident cluster{triageSummary.incident_clusters !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={analyzeInGlean}
            disabled={gleanBusy}
            data-testid="analyze-in-glean"
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium border border-[var(--ss-purple)] text-[var(--ss-purple)] hover:bg-purple-50 transition disabled:opacity-60"
          >
            {gleanBusy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Analyze in Glean
          </button>
          <button onClick={copyToClipboard} className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium border border-[var(--ss-divider)] hover:bg-zinc-50 transition">
            <Copy size={14} /> Copy Summary
          </button>
          <button onClick={exportJSON} className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium border border-[var(--ss-divider)] hover:bg-zinc-50 transition">
            <Download size={14} /> Export JSON
          </button>
        </div>
      </div>

      {triageError && (
        <div className="mb-4 p-3 border border-amber-200 bg-amber-50 text-xs text-amber-800" data-testid="triage-error-banner">
          Triage view unavailable ({triageError}). Showing findings without prioritized buckets — re-upload the report to regenerate triage metadata.
        </div>
      )}

      {triageData && (
        <div className="mb-6 grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="triage-buckets">
          {TRIAGE_BUCKETS.map(({ key, label, icon: Icon, color, desc }) => {
            const count = triageSummary?.[key] ?? (triageData[key]?.length || 0);
            const active = activeTriageBucket === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggleTriageBucket(key)}
                className={`p-4 border text-left transition-colors ${active ? "border-[var(--ss-purple)] bg-purple-50/40 shadow-sm" : "border-[var(--ss-divider)] bg-white hover:border-zinc-300"}`}
                data-testid={`triage-bucket-${key}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <Icon size={14} style={{ color }} />
                    <span className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)]">{label}</span>
                  </div>
                  <span className="text-lg font-mono font-bold tabular-nums" style={{ color }}>{count}</span>
                </div>
                <p className="text-[10px] text-[var(--ss-mid-gray)]">{desc}</p>
              </button>
            );
          })}
        </div>
      )}

      {clusters.length > 0 && (
        <div className="mb-6 border border-[var(--ss-divider)] bg-white" data-testid="incident-clusters">
          <div className="px-4 py-2 border-b border-[var(--ss-divider)] bg-zinc-50 flex items-center gap-2">
            <Layers size={14} className="text-[var(--ss-purple)]" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--ss-mid-gray)]">Incident Clusters</h3>
            <span className="text-[10px] font-mono px-1.5 py-0.5 bg-zinc-200">{clusters.length}</span>
          </div>
          <div className="p-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {clusters.map((cluster) => {
              const active = activeClusterId === cluster.cluster_id;
              const sevColor = cluster.dominant_severity === "critical" ? "#F44336" : cluster.dominant_severity === "warning" ? "#FF9800" : "#2196F3";
              return (
                <div
                  key={cluster.cluster_id}
                  className={`p-3 border transition-colors ${active ? "border-[var(--ss-purple)] bg-purple-50/30" : "border-[var(--ss-divider)] hover:border-zinc-300"}`}
                  data-testid={`incident-cluster-${cluster.cluster_id}`}
                >
                  <button
                    type="button"
                    onClick={() => toggleCluster(cluster.cluster_id)}
                    className="w-full text-left"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded" style={{ background: `${sevColor}18`, color: sevColor }}>
                        {cluster.cluster_id}
                      </span>
                      <span className="text-[10px] font-mono text-[var(--ss-mid-gray)]">{cluster.member_count} findings</span>
                    </div>
                    <p className="text-xs font-semibold line-clamp-2 mb-1">{cluster.root_cause_title}</p>
                    <p className="text-[10px] text-[var(--ss-mid-gray)] line-clamp-2">{cluster.summary}</p>
                    {cluster.log_context?.summary?.excerpt_count > 0 && (
                      <p className="text-[10px] font-mono mt-1 text-[var(--ss-mid-gray)]" data-testid={`cluster-log-hint-${cluster.cluster_id}`}>
                        {cluster.log_context.summary.excerpt_count} log excerpt{cluster.log_context.summary.excerpt_count !== 1 ? "s" : ""}
                        {cluster.log_context.summary.pattern_count > 0
                          ? ` · ${cluster.log_context.summary.pattern_count} pattern${cluster.log_context.summary.pattern_count !== 1 ? "s" : ""}`
                          : ""}
                      </p>
                    )}
                    <p className="text-[10px] font-mono mt-2 text-[var(--ss-purple)]">Max risk: {cluster.max_risk_score}</p>
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex flex-col xl:flex-row gap-6 flex-1 min-h-0">
        <div className="w-full xl:w-1/4 flex flex-col gap-4 overflow-y-auto pr-0 xl:pr-2">
          <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--ss-mid-gray)] mb-2">Root Cause Groups</h3>
          {Object.entries(byCategory).map(([category, items]) => {
            const maxRisk = Math.max(...items.map((i) => i.risk_score || 0));
            return (
              <div
                key={category}
                className={`p-4 border cursor-pointer transition-colors ${selectedGroup === category ? "border-[var(--ss-purple)] bg-purple-50/30" : "border-[var(--ss-divider)] bg-white hover:border-zinc-300"}`}
                onClick={() => { setSelectedGroup(selectedGroup === category ? null : category); setActiveTriageBucket(null); setActiveClusterId(null); }}
              >
                <div className="flex justify-between items-start mb-2">
                  <h4 className="font-bold text-sm">{category}</h4>
                  <span className="text-[10px] font-bold px-1.5 py-0.5 bg-zinc-100">{items.length} items</span>
                </div>
                <p className="text-xs text-[var(--ss-mid-gray)] mb-3 line-clamp-2">{items[0]?.title} & others.</p>
                <div className="text-[10px] font-mono text-[var(--ss-purple)]">Max Risk: {maxRisk}</div>
              </div>
            );
          })}
        </div>

        <div className="w-full xl:w-3/4 flex flex-col border border-[var(--ss-divider)] bg-white overflow-hidden">
          <div className="p-3 border-b border-[var(--ss-divider)] flex flex-col md:flex-row md:justify-between md:items-center gap-3 bg-zinc-50">
            <div className="flex items-center gap-2 flex-wrap">
              {(activeTriageBucket || activeClusterId) && (
                <button
                  type="button"
                  onClick={() => { setActiveTriageBucket(null); setActiveClusterId(null); }}
                  className="text-[10px] uppercase tracking-widest font-bold px-2 py-1 border border-[var(--ss-purple)] text-[var(--ss-purple)] hover:bg-purple-50"
                >
                  Clear filter
                </button>
              )}
              {activeClusterId && (
                <span className="text-[10px] font-mono text-[var(--ss-purple)]" data-testid="active-cluster-filter">
                  {activeClusterId} · {tableRecs.length} findings
                </span>
              )}
              <div className="relative">
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
                <input
                  type="text"
                  placeholder="Search findings..."
                  className="pl-8 pr-3 py-1.5 text-xs border border-zinc-300 rounded w-full md:w-64 focus:outline-none focus:border-[var(--ss-purple)]"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
            <div className="w-full md:w-auto overflow-x-auto">
              <div className="flex gap-0 border border-[var(--ss-divider)] rounded overflow-hidden min-w-max">
                {["all", "critical", "warning"].map((f) => (
                  <button key={f} onClick={() => setFilter(f)}
                    className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 ${
                      filter === f ? "bg-[#AA00FF] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
                    } border-r last:border-r-0 border-[var(--ss-divider)]`}>
                    {f}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            <table className="w-full text-left border-collapse">
              <thead className="bg-zinc-50 sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="p-3 text-[10px] uppercase tracking-wider font-bold text-[var(--ss-mid-gray)] border-b border-[var(--ss-divider)]">Severity</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider font-bold text-[var(--ss-mid-gray)] border-b border-[var(--ss-divider)]">Checker</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider font-bold text-[var(--ss-mid-gray)] border-b border-[var(--ss-divider)]">Title</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider font-bold text-[var(--ss-mid-gray)] border-b border-[var(--ss-divider)]">Risk</th>
                  <th className="p-3 text-[10px] uppercase tracking-wider font-bold text-[var(--ss-mid-gray)] border-b border-[var(--ss-divider)]">Nodes</th>
                </tr>
              </thead>
              <tbody>
                {tableRecs.map((rec) => {
                  const riskScore = rec.risk_score || 0;
                  const riskPct = Math.min(100, riskScore);
                  const riskColor = riskScore >= 80 ? "var(--ss-critical)" : riskScore >= 50 ? "var(--ss-warning)" : riskScore > 0 ? "var(--ss-success)" : "var(--ss-divider)";
                  return (
                    <tr
                      key={rec.id}
                      className={`border-b border-[var(--ss-divider)] hover:bg-zinc-50 cursor-pointer transition-colors ${selectedFinding?.id === rec.id ? "bg-purple-50/50" : ""} ${rec.triage?.quick_win ? "bg-amber-50/30" : ""}`}
                      onClick={() => openFinding(rec)}
                    >
                      <td className="p-3">
                        <div className="flex items-center gap-1 flex-wrap">
                          <SeverityBadge severity={rec.severity} />
                          {rec.triage?.quick_win && (
                            <span title="Quick Win — low effort fix" className="inline-flex items-center"><Zap size={11} className="text-amber-500" /></span>
                          )}
                          {rec.triage?.cluster_id && (
                            <span className="text-[9px] font-mono px-1 py-0.5 bg-blue-50 text-blue-600 rounded">{rec.triage.cluster_id}</span>
                          )}
                        </div>
                      </td>
                      <td className="p-3 text-xs font-mono text-[var(--ss-mid-gray)]">{rec.checker_id}</td>
                      <td className="p-3 text-sm font-medium">{rec.title}</td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <div style={{ width: "60px", height: "6px", background: "var(--ss-light-gray)", borderRadius: "3px", overflow: "hidden" }}>
                            <div className="risk-bar-fill" style={{ "--risk-width": `${riskPct}%`, height: "100%", background: riskColor, borderRadius: "3px" }} />
                          </div>
                          <span className="text-xs font-mono font-bold" style={{ color: riskColor }}>{riskScore || "-"}</span>
                        </div>
                      </td>
                      <td className="p-3 text-[10px] font-mono text-[var(--ss-mid-gray)] truncate max-w-[100px]">{rec.nodes?.join(", ") || "Global"}</td>
                    </tr>
                  );
                })}
                {tableRecs.length === 0 && (
                  <tr>
                    <td colSpan="5" className="p-8 text-center text-sm text-[var(--ss-mid-gray)]">No findings match the current filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {selectedFinding && (
        <div className="fixed inset-y-0 right-0 w-full sm:w-[500px] max-w-full bg-white shadow-2xl border-l border-[var(--ss-divider)] z-50 flex flex-col transform transition-transform animate-slide-in-right">
          <div className="p-4 border-b border-[var(--ss-divider)] flex justify-between items-start bg-zinc-50">
            <div>
              <div className="flex gap-2 mb-2 flex-wrap">
                <SeverityBadge severity={selectedFinding.severity} />
                <span className="text-[10px] font-mono px-1.5 py-0.5 bg-zinc-200 text-zinc-700">{selectedFinding.checker_id}</span>
                {selectedFinding.triage?.cluster_id && (
                  <span className="text-[10px] font-mono px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded">{selectedFinding.triage.cluster_id}</span>
                )}
                {selectedFinding.triage?.quick_win && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded flex items-center gap-0.5"><Zap size={9} /> QUICK WIN</span>
                )}
              </div>
              <h2 className="text-lg font-bold">{selectedFinding.title}</h2>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => copyFindingToSlack(selectedFinding)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded transition-colors ${
                  slackCopiedId === selectedFinding.id ? "bg-green-100 text-green-700 border border-green-300" : "bg-[#4A154B] text-white hover:bg-[#611f69] border border-[#4A154B]"
                }`}
              >
                <MessageSquare size={14} />
                {slackCopiedId === selectedFinding.id ? "Copied!" : "Slack"}
              </button>
              <button onClick={closeFinding} className="p-1 hover:bg-zinc-200 rounded" title="Close (Esc)"><ChevronLeft size={20} /></button>
            </div>
          </div>

          <div className="p-6 overflow-y-auto flex-1 space-y-6">
            <div>
              <h4 className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)] mb-2">Description</h4>
              <p className="text-sm text-zinc-700">{selectedFinding.description}</p>
            </div>
            {selectedFinding.evidence && (
              <div>
                <h4 className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)] mb-2">Evidence</h4>
                <div className="bg-zinc-50 border border-zinc-200 p-3 rounded text-xs font-mono text-zinc-800 whitespace-pre-wrap">{selectedFinding.evidence}</div>
              </div>
            )}
            {selectedFinding.remediation && (
              <div>
                <h4 className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)] mb-2">Remediation Steps</h4>
                <div className="bg-purple-50 border border-purple-100 p-4 rounded text-sm text-[var(--ss-purple)] font-medium">{selectedFinding.remediation}</div>
              </div>
            )}
            {selectedFinding.triage && (
              <div>
                <h4 className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)] mb-2">Triage</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex items-center gap-2 p-2.5 border border-[var(--ss-divider)] rounded">
                    <Shield size={14} style={{ color: selectedFinding.triage.impact === "data-at-risk" ? "#F44336" : selectedFinding.triage.impact === "outage-risk" ? "#FF9800" : "var(--ss-purple)" }} />
                    <div>
                      <p className="text-[9px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)]">Impact</p>
                      <p className="text-xs font-semibold">{selectedFinding.triage.impact || "—"}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 p-2.5 border border-[var(--ss-divider)] rounded">
                    <Wrench size={14} style={{ color: selectedFinding.triage.effort === "low" ? "#4CAF50" : selectedFinding.triage.effort === "high" ? "#F44336" : "#FF9800" }} />
                    <div>
                      <p className="text-[9px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)]">Effort</p>
                      <p className="text-xs font-semibold">{selectedFinding.triage.effort || "—"}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 p-2.5 border border-[var(--ss-divider)] rounded">
                    <Globe size={14} style={{ color: "var(--ss-mid-gray)" }} />
                    <div>
                      <p className="text-[9px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)]">Blast Radius</p>
                      <p className="text-xs font-semibold">{selectedFinding.triage.blast_radius || "—"}</p>
                    </div>
                  </div>
                  {selectedFinding.triage.recommended_action && (
                    <div className="col-span-2 p-2.5 border border-[var(--ss-divider)] rounded">
                      <p className="text-[9px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)] mb-1">Recommended First Action</p>
                      <p className="text-xs font-medium">{selectedFinding.triage.recommended_action}</p>
                    </div>
                  )}
                </div>
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h4 className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)] mb-1">Risk Score</h4>
                <div className="flex items-center gap-3">
                  <div style={{ width: 48, height: 48, position: "relative", flexShrink: 0 }}>
                    <svg width="48" height="48" viewBox="0 0 48 48">
                      <circle cx="24" cy="24" r="20" fill="none" stroke="var(--ss-light-gray)" strokeWidth="4" />
                      <circle cx="24" cy="24" r="20" fill="none"
                        stroke={selectedFinding.risk_score >= 80 ? "var(--ss-critical)" : selectedFinding.risk_score >= 50 ? "var(--ss-warning)" : "var(--ss-success)"}
                        strokeWidth="4" strokeLinecap="round"
                        strokeDasharray="125.6"
                        strokeDashoffset={125.6 - (125.6 * (selectedFinding.risk_score || 0) / 100)}
                        transform="rotate(-90 24 24)"
                        className="gauge-ring"
                        style={{ "--gauge-offset": `${125.6 - (125.6 * (selectedFinding.risk_score || 0) / 100)}` }}
                      />
                    </svg>
                    <span className="absolute inset-0 flex items-center justify-center text-sm font-mono font-bold">{selectedFinding.risk_score || "N/A"}</span>
                  </div>
                </div>
              </div>
              <div>
                <h4 className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)] mb-1">Confidence</h4>
                <div className="flex items-center gap-3">
                  <div style={{ width: 48, height: 48, position: "relative", flexShrink: 0 }}>
                    <svg width="48" height="48" viewBox="0 0 48 48">
                      <circle cx="24" cy="24" r="20" fill="none" stroke="var(--ss-light-gray)" strokeWidth="4" />
                      <circle cx="24" cy="24" r="20" fill="none" stroke="var(--ss-purple)" strokeWidth="4" strokeLinecap="round"
                        strokeDasharray="125.6"
                        strokeDashoffset={125.6 - (125.6 * (selectedFinding.confidence ? Math.round(selectedFinding.confidence * 100) : 0) / 100)}
                        transform="rotate(-90 24 24)"
                        className="gauge-ring"
                        style={{ "--gauge-offset": `${125.6 - (125.6 * (selectedFinding.confidence ? Math.round(selectedFinding.confidence * 100) : 0) / 100)}` }}
                      />
                    </svg>
                    <span className="absolute inset-0 flex items-center justify-center text-xs font-mono font-bold">
                      {selectedFinding.confidence ? `${Math.round(selectedFinding.confidence * 100)}%` : "N/A"}
                    </span>
                  </div>
                </div>
              </div>
            </div>
            {selectedFinding.grounding && selectedFinding.grounding.criterion && (
              <div className="pt-4 border-t border-[var(--ss-divider)]">
                <div className="flex items-center gap-2 mb-1">
                  <h4 className="text-[10px] uppercase tracking-widest font-bold text-[var(--ss-mid-gray)]">Basis</h4>
                  <span
                    className="text-[9px] uppercase tracking-widest font-bold px-1.5 py-0.5 rounded"
                    style={{
                      color: GROUNDING_BASIS_COLORS[selectedFinding.grounding.basis] || "var(--ss-mid-gray)",
                      border: `1px solid ${GROUNDING_BASIS_COLORS[selectedFinding.grounding.basis] || "var(--ss-divider)"}`,
                    }}
                    title={GROUNDING_BASIS_LABELS[selectedFinding.grounding.basis] || selectedFinding.grounding.basis}
                  >
                    {selectedFinding.grounding.basis || "observed"}
                  </span>
                </div>
                <p className="text-xs text-[var(--ss-mid-gray)] leading-relaxed">{selectedFinding.grounding.criterion}</p>
              </div>
            )}
            {selectedFinding.doc_link && (
              <div className="pt-4 border-t border-[var(--ss-divider)]">
                <a href={selectedFinding.doc_link} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 text-sm font-bold text-[var(--ss-purple)] hover:underline">
                  <ExternalLink size={16} /> Read Official Documentation
                </a>
              </div>
            )}
            {isTraceableFinding(selectedFinding) && (
              <div className="pt-4 border-t border-[var(--ss-divider)]">
                <button
                  type="button"
                  data-testid="finding-trace-query"
                  onClick={() => openFindingTrace(selectedFinding)}
                  className="text-[10px] uppercase font-bold px-3 py-2 border"
                  style={{ borderColor: "var(--ss-divider)", color: "#00d992" }}
                >
                  Trace related query
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {selectedFinding && (
        <div className="fixed inset-0 bg-black/20 z-40 transition-opacity" onClick={closeFinding} />
      )}
    </div>
  );
}
