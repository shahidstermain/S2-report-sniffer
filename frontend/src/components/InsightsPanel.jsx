import { useState, useEffect } from "react";
import { RefreshCw, ExternalLink, Search, AlertCircle, FileText, Clock, BookOpen, Users, Activity, ChevronDown, ChevronUp, CheckCircle2 } from "lucide-react";
import { enrichFindings } from "@/lib/api";
import { toast } from "sonner";

export default function InsightsPanel({ reportId, reportData, findings }) {
  const [enrichment, setEnrichment] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetched, setLastFetched] = useState(null);
  const [activeTab, setActiveTab] = useState("docs");
  const [expandedAudit, setExpandedAudit] = useState(false);

  useEffect(() => {
    if (reportId && findings && findings.length > 0) {
      fetchEnrichment();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId, findings]);

  const fetchEnrichment = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Convert findings to canonical format
      const canonicalFindings = findings.map(f => ({
        id: f.check_id || f.id || `finding-${Math.random().toString(36).substr(2, 9)}`,
        type: mapToFindingType(f.check_id || f.title),
        severity: f.severity || "info",
        title: f.title || f.check_id,
        summary: f.description || f.message || "",
        evidence: extractEvidence(f),
        keywords: extractKeywords(f),
        affected_nodes: f.affected_nodes || [],
        version: reportData?.cluster_overview?.version || reportData?.version || "",
        time_range: reportData?.time_range
      }));

      const reportMetadata = {
        report_id: reportId,
        version: reportData?.cluster_overview?.version || reportData?.version || "",
        deployment_type: reportData?.deployment_type || "unknown",
        cluster_name: reportData?.cluster_overview?.cluster_name || "",
        node_count: reportData?.cluster_overview?.total_nodes || 0
      };

      const res = await enrichFindings(reportId, canonicalFindings, reportMetadata);
      setEnrichment(res.data);
      setLastFetched(new Date());
    } catch (err) {
      console.error("Failed to fetch Glean enrichment:", err);
      setError(err.response?.data?.message || "Failed to fetch enrichment");
    } finally {
      setLoading(false);
    }
  };

  const mapToFindingType = (checkIdOrTitle) => {
    const typeMap = {
      "replication": "replication_lag",
      "replica": "replication_lag",
      "memory": "memory_pressure",
      "swap": "swap_usage",
      "disk": "disk_latency",
      "partition": "partition_skew",
      "topology": "topology_mismatch",
      "version": "version_inconsistency",
      "orphan": "orphan_databases",
      "config": "config_anomaly"
    };
    const lower = (checkIdOrTitle || "").toLowerCase();
    for (const [key, type] of Object.entries(typeMap)) {
      if (lower.includes(key)) return type;
    }
    return "config_anomaly";
  };

  const extractEvidence = (finding) => {
    const evidence = [];
    if (finding.collector) {
      evidence.push({ collector: finding.collector });
    }
    if (finding.node) {
      evidence.push({ collector: finding.collector || "unknown", node: finding.node });
    }
    if (finding.metric) {
      evidence.push({ collector: finding.collector || "unknown", metric: finding.metric, value: finding.value });
    }
    return evidence;
  };

  const extractKeywords = (finding) => {
    const keywords = [];
    if (finding.check_id) keywords.push(finding.check_id);
    if (finding.title) {
      finding.title.toLowerCase().split(/\s+/).forEach(word => {
        if (word.length > 3) keywords.push(word);
      });
    }
    return [...new Set(keywords)].slice(0, 10);
  };

  if (!reportId || !findings || findings.length === 0) {
    return (
      <div className="ss-card p-6" data-testid="insights-panel">
        <div className="flex items-center gap-2 mb-4">
          <Search size={20} style={{ color: "var(--ss-purple)" }} />
          <h3 className="text-sm font-bold uppercase tracking-wider">Glean Insights</h3>
        </div>
        <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>
          Load a report with findings to see related insights from Glean.
        </p>
      </div>
    );
  }

  return (
    <div className="ss-card p-6" data-testid="insights-panel">
      <div className="flex items-center justify-between mb-4 pb-3 border-b" style={{ borderColor: "var(--ss-divider)" }}>
        <div className="flex items-center gap-2">
          <Search size={20} style={{ color: "var(--ss-purple)" }} />
          <h3 className="text-sm font-bold uppercase tracking-wider">Glean Insights</h3>
          {enrichment?.finding_enrichments?.length > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded"
              style={{ background: "rgba(0, 47, 167, 0.1)", color: "#002FA7" }}>
              {enrichment.finding_enrichments.length} enriched
            </span>
          )}
        </div>
        <button
          onClick={fetchEnrichment}
          disabled={loading}
          className="p-1.5 rounded border hover:bg-zinc-50 transition-colors"
          style={{ borderColor: "var(--ss-divider)", opacity: loading ? 0.5 : 1 }}
          data-testid="refresh-insights-button"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {loading && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 p-3 rounded" style={{ background: "rgba(0, 47, 167, 0.05)" }}>
            <RefreshCw size={16} className="animate-spin" style={{ color: "#002FA7" }} />
            <span className="text-sm" style={{ color: "#002FA7" }}>
              Enriching findings with Glean...
            </span>
          </div>
          {[1, 2, 3].map((i) => (
            <div key={i} className="p-3 border rounded" style={{ borderColor: "var(--ss-divider)" }}>
              <div className="skeleton w-3/4 h-4 mb-2" />
              <div className="skeleton w-full h-3" />
            </div>
          ))}
        </div>
      )}

      {!loading && error && (
        <div className="flex items-center gap-2 p-3 rounded" style={{ background: "rgba(255, 59, 48, 0.05)", border: "1px solid rgba(255, 59, 48, 0.2)" }}>
          <AlertCircle size={16} style={{ color: "#FF3B30" }} />
          <p className="text-sm" style={{ color: "#FF3B30" }}>
            {error}
          </p>
        </div>
      )}

      {!loading && !error && enrichment && (
        <>
          {/* Recommendations */}
          {enrichment.recommendations && enrichment.recommendations.length > 0 && (
            <div className="mb-4 p-3 rounded" style={{ background: "rgba(0, 47, 167, 0.05)", border: "1px solid rgba(0, 47, 167, 0.2)" }}>
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle2 size={16} style={{ color: "#002FA7" }} />
                <span className="text-sm font-semibold" style={{ color: "#002FA7" }}>Recommendations</span>
              </div>
              <ul className="space-y-1 text-xs" style={{ color: "var(--ss-mid-gray)" }}>
                {enrichment.recommendations.map((rec, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span style={{ color: "#002FA7" }}>•</span>
                    <span>{rec}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Evidence Tabs */}
          {enrichment.finding_enrichments.length > 0 && (
            <div className="mb-4">
              <div className="flex gap-1 mb-3 border-b" style={{ borderColor: "var(--ss-divider)" }}>
                <button
                  onClick={() => setActiveTab("docs")}
                  className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                    activeTab === "docs" 
                      ? "border-[#002FA7] text-[#002FA7]" 
                      : "border-transparent hover:text-[#002FA7]"
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <BookOpen size={14} />
                    Docs & Runbooks
                  </div>
                </button>
                <button
                  onClick={() => setActiveTab("cases")}
                  className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                    activeTab === "cases" 
                      ? "border-[#002FA7] text-[#002FA7]" 
                      : "border-transparent hover:text-[#002FA7]"
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <Activity size={14} />
                    Similar Cases
                  </div>
                </button>
                <button
                  onClick={() => setActiveTab("people")}
                  className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                    activeTab === "people" 
                      ? "border-[#002FA7] text-[#002FA7]" 
                      : "border-transparent hover:text-[#002FA7]"
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <Users size={14} />
                    SMEs / Owners
                  </div>
                </button>
              </div>

              {/* Tab Content */}
              <div className="space-y-3">
                {activeTab === "docs" && renderDocsTab(enrichment)}
                {activeTab === "cases" && renderCasesTab(enrichment)}
                {activeTab === "people" && renderPeopleTab(enrichment)}
              </div>
            </div>
          )}

          {/* Audit Panel */}
          {enrichment.retrieval_plan && enrichment.retrieval_plan.length > 0 && (
            <div className="mt-4 pt-4 border-t" style={{ borderColor: "var(--ss-divider)" }}>
              <button
                onClick={() => setExpandedAudit(!expandedAudit)}
                className="flex items-center justify-between w-full text-left"
                data-testid="audit-panel-toggle"
              >
                <div className="flex items-center gap-2">
                  <Activity size={14} style={{ color: "var(--ss-mid-gray)" }} />
                  <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--ss-mid-gray)" }}>
                    Retrieval Audit
                  </span>
                </div>
                {expandedAudit ? <ChevronUp size={14} style={{ color: "var(--ss-mid-gray)" }} /> : <ChevronDown size={14} style={{ color: "var(--ss-mid-gray)" }} />}
              </button>
              
              {expandedAudit && (
                <div className="mt-3 space-y-2 text-xs" style={{ color: "var(--ss-mid-gray)" }}>
                  {enrichment.retrieval_plan.map((plan, i) => (
                    <div key={i} className="p-2 rounded" style={{ background: "rgba(0, 0, 0, 0.03)" }}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium" style={{ color: "var(--ss-mid-gray)" }}>
                          {plan.finding_type} ({plan.finding_severity})
                        </span>
                        <span className="font-mono">{plan.version}</span>
                      </div>
                      <div className="space-y-1">
                        <div>
                          <span className="font-medium">Datasources:</span> {plan.datasources?.join(", ") || "N/A"}
                        </div>
                        <div>
                          <span className="font-medium">Freshness:</span> {plan.days_back} days
                        </div>
                        <div>
                          <span className="font-medium">Queries:</span>
                          <div className="mt-1 space-y-0.5 pl-2">
                            {plan.doc_queries?.slice(0, 2).map((q, j) => (
                              <div key={j} className="italic">• {q}</div>
                            ))}
                            {plan.doc_queries?.length > 2 && <div className="italic">• ...{plan.doc_queries.length - 2} more</div>}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && enrichment?.finding_enrichments?.length === 0 && (
            <div className="text-center py-8">
              <FileText size={32} className="mx-auto mb-3" style={{ color: "var(--ss-mid-gray)" }} />
              <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>
                No additional insights found in Glean for these findings
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>
                Try adjusting your Glean search query or check your connection
              </p>
            </div>
          )}
        </>
      )}

      {lastFetched && !loading && (
        <div className="flex items-center gap-1 mt-4 pt-3 border-t text-[10px]" style={{ borderColor: "var(--ss-divider)", color: "var(--ss-mid-gray)" }}>
          <Clock size={12} />
          <span>Last enriched: {lastFetched.toLocaleTimeString()}</span>
        </div>
      )}
    </div>
  );
}

function renderDocsTab(enrichment) {
  const allDocs = enrichment.finding_enrichments.flatMap(fe => 
    (fe.docs || []).map(doc => ({ ...doc, finding_id: fe.finding_id }))
  );

  if (allDocs.length === 0) {
    return (
      <div className="text-center py-4">
        <BookOpen size={24} className="mx-auto mb-2" style={{ color: "var(--ss-mid-gray)", opacity: 0.5 }} />
        <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>No documentation found</p>
      </div>
    );
  }

  return allDocs.slice(0, 10).map((doc, index) => (
    <div
      key={index}
      className="p-3 border rounded hover:bg-zinc-50 transition-colors"
      style={{ borderColor: "var(--ss-divider)" }}
      data-testid={`doc-card-${index}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <h4 className="text-sm font-semibold line-clamp-2" style={{ fontFamily: "Chivo, sans-serif" }}>
          {doc.title}
        </h4>
        {doc.url && doc.url !== "#" && (
          <a
            href={doc.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-shrink-0 p-1 rounded hover:bg-zinc-200"
            style={{ color: "#002FA7" }}
            data-testid={`doc-link-${index}`}
          >
            <ExternalLink size={14} />
          </a>
        )}
      </div>
      <p className="text-xs mb-2 line-clamp-3" style={{ color: "var(--ss-mid-gray)" }}>
        {doc.snippet}
      </p>
      <div className="flex items-center justify-between text-[10px]" style={{ color: "var(--ss-mid-gray)" }}>
        <span className="font-mono uppercase tracking-wider">{doc.source}</span>
        {doc.score !== undefined && (
          <span>Score: {Math.round(doc.score * 100)}%</span>
        )}
      </div>
      {doc.finding_id && (
        <div className="mt-1 text-[10px]" style={{ color: "var(--ss-mid-gray)" }}>
          <span className="font-medium">From:</span> {doc.finding_id}
        </div>
      )}
    </div>
  ));
}

function renderCasesTab(enrichment) {
  const allCases = enrichment.finding_enrichments.flatMap(fe => 
    (fe.cases || []).map(c => ({ ...c, finding_id: fe.finding_id }))
  );

  if (allCases.length === 0) {
    return (
      <div className="text-center py-4">
        <Activity size={24} className="mx-auto mb-2" style={{ color: "var(--ss-mid-gray)", opacity: 0.5 }} />
        <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>No similar cases found</p>
      </div>
    );
  }

  return allCases.slice(0, 10).map((caseItem, index) => (
    <div
      key={index}
      className="p-3 border rounded hover:bg-zinc-50 transition-colors"
      style={{ borderColor: "var(--ss-divider)" }}
      data-testid={`case-card-${index}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <h4 className="text-sm font-semibold line-clamp-2" style={{ fontFamily: "Chivo, sans-serif" }}>
          {caseItem.title}
        </h4>
        {caseItem.url && caseItem.url !== "#" && (
          <a
            href={caseItem.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-shrink-0 p-1 rounded hover:bg-zinc-200"
            style={{ color: "#002FA7" }}
          >
            <ExternalLink size={14} />
          </a>
        )}
      </div>
      <p className="text-xs mb-2 line-clamp-3" style={{ color: "var(--ss-mid-gray)" }}>
        {caseItem.snippet}
      </p>
      <div className="flex items-center justify-between text-[10px]" style={{ color: "var(--ss-mid-gray)" }}>
        <span className="font-mono uppercase tracking-wider">{caseItem.source}</span>
        {caseItem.score !== undefined && (
          <span>Score: {Math.round(caseItem.score * 100)}%</span>
        )}
      </div>
    </div>
  ));
}

function renderPeopleTab(enrichment) {
  const allPeople = enrichment.finding_enrichments.flatMap(fe => fe.people || []);

  if (allPeople.length === 0) {
    return (
      <div className="text-center py-4">
        <Users size={24} className="mx-auto mb-2" style={{ color: "var(--ss-mid-gray)", opacity: 0.5 }} />
        <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>No SMEs found</p>
      </div>
    );
  }

  return allPeople.slice(0, 10).map((person, index) => (
    <div
      key={index}
      className="p-3 border rounded hover:bg-zinc-50 transition-colors"
      style={{ borderColor: "var(--ss-divider)" }}
      data-testid={`person-card-${index}`}
    >
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ background: "rgba(0, 47, 167, 0.1)" }}>
          <Users size={16} style={{ color: "#002FA7" }} />
        </div>
        <div>
          <h4 className="text-sm font-semibold" style={{ fontFamily: "Chivo, sans-serif" }}>
            {person.name}
          </h4>
          <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
            {person.title}
          </p>
          {person.department && (
            <p className="text-[10px]" style={{ color: "var(--ss-mid-gray)" }}>
              {person.department}
            </p>
          )}
        </div>
      </div>
    </div>
  ));
}
