import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Server, HardDrive, Activity, ScrollText, AlertTriangle, LayoutDashboard, Loader2, Settings, ChevronLeft } from "lucide-react";
import { getReportOverview, getReportStatus } from "@/lib/api";
import ClusterOverview from "@/components/ClusterOverview";
import NodeHealth from "@/components/NodeHealth";
import StorageDistribution from "@/components/StorageDistribution";
import WorkloadQueries from "@/components/WorkloadQueries";
import LogExplorer from "@/components/LogExplorer";
import Recommendations from "@/components/Recommendations";
import ConfigHealth from "@/components/ConfigHealth";

const SS_LOGO_WHITE = "https://images.contentstack.io/v3/assets/bltac01ee6daa3a1e14/blt4ccfca5719ee0d60/661426f02b98e95159100b9b/singlestore-horizontal-lock-up-white.svg";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "nodes", label: "Nodes", icon: Server },
  { id: "storage", label: "Storage", icon: HardDrive },
  { id: "queries", label: "Queries", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "config", label: "Config", icon: Settings },
  { id: "recommendations", label: "Issues", icon: AlertTriangle },
];

export default function ReportDashboard() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("overview");
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const statusRes = await getReportStatus(reportId);
      setStatus(statusRes.data.status);
      if (statusRes.data.status === "ready") {
        const res = await getReportOverview(reportId);
        setOverview(res.data);
        setLoading(false);
      } else if (statusRes.data.status === "error") {
        setLoading(false);
      }
    } catch { setLoading(false); }
  }, [reportId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (status !== "processing") return;
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [status, fetchData]);

  if (loading || status === "processing") {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--ss-light-gray)" }}>
        <div className="text-center">
          {/* Skeleton loading */}
          <div className="skeleton w-48 h-4 mx-auto mb-3" />
          <div className="skeleton w-32 h-3 mx-auto mb-2" />
          <div className="skeleton w-24 h-3 mx-auto" />
          <p className="text-sm font-medium mt-4" style={{ color: "var(--ss-mid-gray)" }}>
            {status === "processing" ? "Parsing diagnostic report..." : "Loading..."}
          </p>
        </div>
      </div>
    );
  }

  const co = overview?.cluster_overview || {};
  const healthLabel = overview?.health_score || "unknown";
  const recCount = overview?.recommendations?.length || 0;

  return (
    <div className="flex min-h-screen" style={{ background: "var(--ss-light-gray)" }}>
      {/* Sidebar */}
      <aside className="sidebar flex flex-col" data-testid="dashboard-sidebar">
        {/* Logo */}
        <div className="p-4 pb-2">
          <img src={SS_LOGO_WHITE} alt="SingleStore" className="h-5 mb-1" />
          <div className="flex items-center gap-1.5 mt-2">
            <span className="text-xs font-medium text-white/80">Report Sniffer</span>
            <span style={{
              background: "rgba(170,0,255,0.25)", color: "#D199FF",
              fontSize: "9px", fontWeight: 700, padding: "1px 5px", borderRadius: "3px",
            }}>v1</span>
          </div>
        </div>

        {/* Back */}
        <button onClick={() => navigate("/")}
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
        </div>

        {/* Nav Items */}
        <nav className="flex-1 py-2" data-testid="dashboard-tabs">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)}
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
      <main className="flex-1 min-w-0 p-6 overflow-y-auto" style={{ maxHeight: "100vh" }}>
        {activeTab === "overview" && <ClusterOverview reportId={reportId} overview={overview} />}
        {activeTab === "nodes" && <NodeHealth reportId={reportId} />}
        {activeTab === "storage" && <StorageDistribution reportId={reportId} />}
        {activeTab === "queries" && <WorkloadQueries reportId={reportId} />}
        {activeTab === "logs" && <LogExplorer reportId={reportId} />}
        {activeTab === "config" && <ConfigHealth reportId={reportId} />}
        {activeTab === "recommendations" && <Recommendations reportId={reportId} />}
      </main>
    </div>
  );
}
