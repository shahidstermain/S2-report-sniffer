import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Server, HardDrive, Activity, ScrollText, AlertTriangle, LayoutDashboard, Loader2, Settings, ChevronLeft, Menu, X, Globe } from "lucide-react";
import { getReportOverview, getReportStatus } from "@/lib/api";
import ClusterOverview from "@/components/ClusterOverview";
import NodeHealth from "@/components/NodeHealth";
import StorageDistribution from "@/components/StorageDistribution";
import WorkloadQueries from "@/components/WorkloadQueries";
import LogExplorer from "@/components/LogExplorer";
import Recommendations from "@/components/Recommendations";
import ConfigHealth from "@/components/ConfigHealth";
import GleanSetup from "@/components/GleanSetup";
import InsightsPanel from "@/components/InsightsPanel";
import { publicAsset } from "@/lib/hostContext";

const SS_LOGO_WHITE = publicAsset("singlestore-logo-white.svg");
const SS_LOGO_BLACK = publicAsset("singlestore-logo-white.svg");

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "nodes", label: "Nodes", icon: Server },
  { id: "storage", label: "Storage", icon: HardDrive },
  { id: "queries", label: "Queries", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "config", label: "Config", icon: Settings },
  { id: "recommendations", label: "Issues", icon: AlertTriangle },
  { id: "glean", label: "Glean", icon: Globe },
];

export default function ReportDashboard() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      console.log(`[Dashboard] Fetching status for report ${reportId}`);
      const statusRes = await getReportStatus(reportId);
      console.log(`[Dashboard] Status response:`, statusRes.data);
      setStatus(statusRes.data.status);
      setStatusData(statusRes.data);
      if (statusRes.data.status === "ready") {
        console.log(`[Dashboard] Report ready, fetching overview`);
        const res = await getReportOverview(reportId);
        console.log(`[Dashboard] Overview response:`, res.data);
        setOverview(res.data);
        setLoading(false);
      } else if (statusRes.data.status === "error") {
        console.log(`[Dashboard] Report error:`, statusRes.data.error);
        setLoading(false);
      } else {
        console.log(`[Dashboard] Report status: ${statusRes.data.status}, still loading`);
      }
    } catch (err) {
      console.error(`[Dashboard] Fetch error:`, err);
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (status !== "processing") return;
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [status, fetchData]);

  if (loading || status === "processing") {
    const prog = overview?.progress || statusData?.progress || {};
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--ss-light-gray)" }}>
        <div className="ss-card p-6 sm:p-8 w-[92vw] max-w-[480px] text-center">
          <img src={SS_LOGO_BLACK} alt="SingleStore" className="h-8 mx-auto mb-4 opacity-50" />
          {/* Skeleton shimmer or progress */}
          <div className="skeleton w-full h-2 mb-4" />
          <p className="text-sm font-semibold mb-1">
            {prog.message || (status === "processing" ? "Parsing diagnostic report..." : "Loading...")}
          </p>
          {prog.stage && prog.stage !== "queued" && (
            <div className="mt-3 space-y-2">
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${prog.pct || 5}%`, background: "#AA00FF" }} />
              </div>
              <div className="flex justify-between text-[11px]" style={{ color: "var(--ss-mid-gray)" }}>
                <span>Stage: {prog.stage}</span>
                <span>{prog.pct || 0}%</span>
              </div>
              {prog.nodes_discovered > 0 && (
                <p className="text-[11px]" style={{ color: "var(--ss-mid-gray)" }}>
                  {prog.nodes_discovered} nodes &middot; {prog.files_processed || 0} files &middot; {(prog.log_lines_indexed || 0).toLocaleString()} log lines
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (status === "error") {
    const message = (statusData?.error || statusData?.message || "Failed to parse report.").toString();
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--ss-light-gray)" }}>
        <div className="ss-card p-6 sm:p-8 w-[92vw] max-w-[560px]">
          <div className="flex items-center gap-3 mb-3">
            <AlertTriangle size={20} style={{ color: "#F44336" }} />
            <h1 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
              Report parsing failed
            </h1>
          </div>
          <p className="text-sm mb-4" style={{ color: "var(--ss-mid-gray)" }}>
            {message}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate("/")}
              className="px-4 py-2 rounded text-sm font-semibold"
              style={{ background: "var(--ss-white)", border: "1px solid var(--ss-divider)" }}
            >
              Back to Reports
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded text-sm font-semibold text-white"
              style={{ background: "var(--ss-purple)" }}
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  const co = overview?.cluster_overview || {};
  const healthLabel = overview?.health_score || "unknown";
  const recCount = overview?.recommendations?.length || 0;
  const pkg = (overview?.detected_format || statusData?.detected_format || "").toString();
  const deployment = (overview?.deployment_method || statusData?.deployment_method || "").toString();
  const deploymentConfidence = (overview?.deployment_confidence || statusData?.deployment_confidence || "").toString();
  const deploymentSignals = (overview?.deployment_signals || statusData?.deployment_signals || "").toString();
  const pkgLabel = (() => {
    const f = pkg.toLowerCase();
    if (!f) return "—";
    if (f === "zip") return "ZIP";
    if (f === "tar.gz") return "Tarball";
    if (f === "tar") return "Tarball";
    if (f === "gz") return "GZIP";
    if (f === "directory") return "Folder";
    return pkg;
  })();

  return (
    <div className="lg:flex min-h-screen" style={{ background: "var(--ss-light-gray)" }}>
      <div className="lg:hidden sticky top-0 z-40 flex items-center justify-between px-4 py-3 border-b bg-white" style={{ borderColor: "var(--ss-divider)" }}>
        <div className="min-w-0">
          <p className="text-sm font-semibold truncate">Report Sniffer</p>
          <p className="text-[10px] font-mono truncate" style={{ color: "var(--ss-mid-gray)" }}>
            {overview?.report_name || "Report"} · {healthLabel}
          </p>
        </div>
        <button
          onClick={() => setSidebarOpen((v) => !v)}
          className="p-2 rounded border bg-white"
          style={{ borderColor: "var(--ss-divider)" }}
          aria-label="Toggle navigation"
        >
          {sidebarOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </div>
      {sidebarOpen && (
        <button
          className="lg:hidden fixed inset-0 z-40 bg-black/40"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close navigation overlay"
        />
      )}
      {/* Sidebar */}
      <aside
        className={`sidebar flex flex-col fixed inset-y-0 left-0 z-50 transform transition-transform duration-200 lg:static lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        data-testid="dashboard-sidebar"
      >
        {/* Logo — big and visible */}
        <div className="px-4 pt-6 pb-4">
          <img src={SS_LOGO_WHITE} alt="SingleStore" style={{ width: "180px", height: "auto" }} data-testid="sidebar-logo" />
          <div className="mt-4 h-px rounded" style={{ background: "linear-gradient(90deg, transparent, rgba(170,0,255,0.5), transparent)" }} />
          <div className="flex items-center gap-2 mt-4">
            <span className="text-sm font-semibold text-white">Report Sniffer</span>
            <span style={{
              background: "rgba(170,0,255,0.3)", color: "#D199FF",
              fontSize: "10px", fontWeight: 700, padding: "2px 6px", borderRadius: "4px",
            }}>v1</span>
          </div>
          <p className="text-[10px] text-white/40 mt-1">Instant cluster insight</p>
        </div>

        {/* Back */}
        <button onClick={() => { setSidebarOpen(false); navigate("/"); }}
          className="flex items-center gap-2 px-4 py-2 text-xs text-white/50 hover:text-white/80 transition-colors"
          data-testid="back-button">
          <ChevronLeft size={14} /> All Reports
        </button>

        {/* Report Info */}
        <div className="px-4 py-3 border-y" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
          <p className="text-[11px] font-medium text-white truncate" title={overview?.report_name}>
            {overview?.report_name || "Report"}
          </p>
          <div className="flex items-center gap-2 mt-1.5">
            <span className={`text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded ${
              healthLabel === "critical" ? "badge-critical" :
              healthLabel === "warning" ? "badge-warning" : "badge-healthy"
            }`} data-testid="health-badge">{healthLabel}</span>
            <span className="text-[10px] font-mono text-white/40">v{co.version || "?"}</span>
          </div>
          <p className="text-[10px] font-mono text-white/40 mt-1">
            {co.total_nodes || 0} nodes &middot; {co.leaves || 0}L / {co.aggregators || 0}A
          </p>
          <p className="text-[10px] font-mono text-white/40 mt-1">
            Package: {pkgLabel}
          </p>
          <p className="text-[10px] font-mono text-white/40 mt-1">
            Deployment: {deployment || "—"}
          </p>
          {deploymentConfidence ? (
            <p className="text-[10px] font-mono text-white/40 mt-1">
              Confidence: {deploymentConfidence}
            </p>
          ) : null}
          {deploymentSignals ? (
            <p className="text-[10px] font-mono text-white/40 mt-1" title={deploymentSignals}>
              Signals: {deploymentSignals.length > 42 ? deploymentSignals.slice(0, 42) + "…" : deploymentSignals}
            </p>
          ) : null}
        </div>

        {/* Nav Items */}
        <nav className="flex-1 py-2" data-testid="dashboard-tabs">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button key={tab.id} onClick={() => { setActiveTab(tab.id); setSidebarOpen(false); }}
                className={`sidebar-item w-full ${isActive ? "active" : ""}`}
                data-testid={`tab-${tab.id}`}>
                <Icon size={16} />
                <span>{tab.label}</span>
                {tab.id === "recommendations" && recCount > 0 && (
                  <span className="ml-auto text-[10px] font-bold px-1.5 py-0.5 rounded"
                    style={{ background: "rgba(244,67,54,0.2)", color: "#FF8678" }}>
                    {recCount}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="p-4 text-[10px] text-white/30">
          SingleStore Report Sniffer v1
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 min-w-0 p-3 sm:p-4 lg:p-6 overflow-y-auto" style={{ maxHeight: "100vh" }}>
        {activeTab === "overview" && (
          <div className="lg:flex gap-4">
            <div className="flex-1">
              <ClusterOverview reportId={reportId} overview={overview} />
            </div>
            <div className="lg:w-80 mt-4 lg:mt-0">
              <InsightsPanel reportId={reportId} reportData={overview} findings={overview?.recommendations || []} />
            </div>
          </div>
        )}
        {activeTab === "nodes" && <NodeHealth reportId={reportId} />}
        {activeTab === "storage" && <StorageDistribution reportId={reportId} />}
        {activeTab === "queries" && <WorkloadQueries reportId={reportId} />}
        {activeTab === "logs" && <LogExplorer reportId={reportId} />}
        {activeTab === "config" && <ConfigHealth reportId={reportId} />}
        {activeTab === "recommendations" && <Recommendations reportId={reportId} />}
        {activeTab === "glean" && <GleanSetup />}
      </main>
    </div>
  );
}
