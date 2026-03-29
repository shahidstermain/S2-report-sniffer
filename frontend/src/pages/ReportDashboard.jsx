import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Server, HardDrive, Activity, ScrollText, AlertTriangle, LayoutDashboard, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getReportOverview, getReportStatus } from "@/lib/api";
import ClusterOverview from "@/components/ClusterOverview";
import NodeHealth from "@/components/NodeHealth";
import StorageDistribution from "@/components/StorageDistribution";
import WorkloadQueries from "@/components/WorkloadQueries";
import LogExplorer from "@/components/LogExplorer";
import Recommendations from "@/components/Recommendations";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "nodes", label: "Nodes", icon: Server },
  { id: "storage", label: "Storage", icon: HardDrive },
  { id: "queries", label: "Queries", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
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
    } catch {
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Poll while processing
  useEffect(() => {
    if (status !== "processing") return;
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [status, fetchData]);

  if (loading || status === "processing") {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--canvas)" }}>
        <div className="text-center">
          <Loader2 size={32} className="animate-spin mx-auto mb-3" style={{ color: "var(--brand-primary)" }} />
          <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
            {status === "processing" ? "Parsing report..." : "Loading..."}
          </p>
        </div>
      </div>
    );
  }

  const co = overview?.cluster_overview || {};
  const healthLabel = overview?.health_score || "unknown";

  return (
    <div className="min-h-screen" style={{ background: "var(--canvas)" }}>
      {/* Header */}
      <header className="border-b" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <div className="max-w-[1600px] mx-auto px-4">
          <div className="flex items-center gap-3 py-3">
            <Button
              variant="ghost"
              size="sm"
              className="rounded-none h-8 px-2"
              onClick={() => navigate("/")}
              data-testid="back-button"
            >
              <ArrowLeft size={16} />
            </Button>
            <img
              src="https://static.prod-images.emergentagent.com/jobs/14e0f03a-9374-4d11-971f-4351c695e47e/images/5548b00c48e2b9b1d93d57f6d2bf6342cfbcb38b9f78dbecdf3fe8d34c5a4120.png"
              alt="SDB" className="w-6 h-6"
            />
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }} data-testid="report-title">
                {overview?.report_name || "Report"}
              </h1>
              <span className={`text-[10px] uppercase tracking-widest font-bold px-2 py-0.5 ${
                healthLabel === "critical" ? "badge-critical" :
                healthLabel === "warning" ? "badge-warning" : "badge-healthy"
              }`} data-testid="health-badge">
                {healthLabel}
              </span>
            </div>
            <div className="ml-auto flex items-center gap-4 text-xs" style={{ color: "var(--text-tertiary)", fontFamily: "JetBrains Mono, monospace" }}>
              <span data-testid="version-info">v{co.version || "?"}</span>
              <span>{co.total_nodes || 0} nodes</span>
              <span>{co.leaves || 0}L / {co.aggregators || 0}A</span>
            </div>
          </div>
          {/* Tabs */}
          <nav className="flex gap-0 -mb-px" data-testid="dashboard-tabs">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-colors border-b-2 ${
                    isActive
                      ? "border-[#002FA7] text-[#002FA7]"
                      : "border-transparent text-zinc-500 hover:text-zinc-800 hover:bg-zinc-50"
                  }`}
                  style={{ fontFamily: "IBM Plex Sans, sans-serif" }}
                  data-testid={`tab-${tab.id}`}
                >
                  <Icon size={14} />
                  {tab.label}
                  {tab.id === "recommendations" && overview?.recommendations?.length > 0 && (
                    <span className="ml-1 bg-[#FF3B30] text-white text-[9px] font-bold px-1.5 py-0.5 leading-none">
                      {overview.recommendations.length}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-[1600px] mx-auto px-4 py-6">
        {activeTab === "overview" && <ClusterOverview reportId={reportId} overview={overview} />}
        {activeTab === "nodes" && <NodeHealth reportId={reportId} />}
        {activeTab === "storage" && <StorageDistribution reportId={reportId} />}
        {activeTab === "queries" && <WorkloadQueries reportId={reportId} />}
        {activeTab === "logs" && <LogExplorer reportId={reportId} />}
        {activeTab === "recommendations" && <Recommendations reportId={reportId} />}
      </main>
    </div>
  );
}
