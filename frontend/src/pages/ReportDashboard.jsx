import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Server, HardDrive, Activity, ScrollText, AlertTriangle, LayoutDashboard, Settings, ChevronLeft, Menu, Globe, Search, BarChart3 } from "lucide-react";
import { getReportOverview, getReportStatus } from "@/lib/api";
import ClusterOverview from "@/components/ClusterOverview";
import NodeHealth from "@/components/NodeHealth";
import StorageDistribution from "@/components/StorageDistribution";
import WorkloadQueries from "@/components/WorkloadQueries";
import LogExplorer from "@/components/LogExplorer";
import LogSearch from "@/components/LogSearch";
import Recommendations from "@/components/Recommendations";
import ConfigHealth from "@/components/ConfigHealth";
import GleanSetup from "@/components/GleanSetup";
import InsightsPanel from "@/components/InsightsPanel";
import ChartsDashboard from "@/components/ChartsDashboard";
import { publicAsset } from "@/lib/hostContext";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const SS_LOGO_WHITE = publicAsset("singlestore-logo-white.svg");
const SS_LOGO_BLACK = publicAsset("singlestore-logo-white.svg");

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "charts", label: "Charts", icon: BarChart3 },
  { id: "nodes", label: "Nodes", icon: Server },
  { id: "storage", label: "Storage", icon: HardDrive },
  { id: "queries", label: "Queries", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "log-search", label: "Log Search", icon: Search },
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
      const statusRes = await getReportStatus(reportId);
      setStatus(statusRes.data.status);
      setStatusData(statusRes.data);
      if (statusRes.data.status === "ready") {
        const res = await getReportOverview(reportId);
        setOverview(res.data);
        setLoading(false);
      } else if (statusRes.data.status === "error") {
        setLoading(false);
      } else {
      }
    } catch (err) {
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
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader className="text-center pb-2">
            <img src={SS_LOGO_BLACK} alt="SingleStore" className="h-8 mx-auto mb-2 opacity-60" />
            <CardTitle className="text-sm font-semibold">
              {prog.message || (status === "processing" ? "Parsing diagnostic report…" : "Loading…")}
            </CardTitle>
            {prog.stage && prog.stage !== "queued" && (
              <CardDescription>Stage: {prog.stage}</CardDescription>
            )}
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Skeleton className="h-2 w-full" />
            {prog.stage && prog.stage !== "queued" && (
              <>
                <Progress value={prog.pct || 5} className="h-2" />
                <div className="flex justify-between text-[11px] text-muted-foreground">
                  <span>{prog.pct || 0}% complete</span>
                  {prog.nodes_discovered > 0 && (
                    <span>
                      {prog.nodes_discovered} nodes · {prog.files_processed || 0} files
                    </span>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (status === "error") {
    const message = (statusData?.error || statusData?.message || "Failed to parse report.").toString();
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-lg shadow-lg">
          <CardHeader>
            <Alert variant="destructive" className="border-destructive/30">
              <AlertTriangle data-icon="inline-start" />
              <AlertTitle>Report parsing failed</AlertTitle>
              <AlertDescription>{message}</AlertDescription>
            </Alert>
          </CardHeader>
          <CardContent className="flex items-center gap-2">
            <Button variant="outline" onClick={() => navigate("/")}>
              Back to Reports
            </Button>
            <Button onClick={() => window.location.reload()}>
              Retry
            </Button>
          </CardContent>
        </Card>
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
      <div className="lg:hidden sticky top-0 z-40 flex items-center justify-between px-4 py-3 border-b bg-card">
        <div className="min-w-0">
          <p className="text-sm font-semibold truncate">Report Sniffer</p>
          <p className="text-[10px] font-mono truncate text-muted-foreground">
            {overview?.report_name || "Report"} · {healthLabel}
          </p>
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={() => setSidebarOpen((v) => !v)}
          aria-label="Toggle navigation"
        >
          <Menu />
        </Button>
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
          <Separator className="mt-4 bg-gradient-to-r from-transparent via-[rgba(170,0,255,0.5)] to-transparent" />
          <div className="flex items-center gap-2 mt-4">
            <span className="text-sm font-semibold text-white">Report Sniffer</span>
            <Badge className="text-[10px] font-bold px-1.5 py-0 border-0"
              style={{ background: "rgba(170,0,255,0.3)", color: "#D199FF" }}>v1</Badge>
          </div>
          <p className="text-[10px] text-white/40 mt-1">Instant cluster insight</p>
        </div>

        {/* Back */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => { setSidebarOpen(false); navigate("/"); }}
          className="mx-2 justify-start text-white/50 hover:text-white/80 hover:bg-white/5"
          data-testid="back-button"
        >
          <ChevronLeft data-icon="inline-start" />
          All Reports
        </Button>

        {/* Report Info */}
        <div className="px-4 py-3 border-y border-white/10">
          <p className="text-[11px] font-medium text-white truncate" title={overview?.report_name}>
            {overview?.report_name || "Report"}
          </p>
          <div className="flex items-center gap-2 mt-1.5">
            <Badge
              variant={healthLabel === "critical" ? "critical" : healthLabel === "warning" ? "warning" : "healthy"}
              data-testid="health-badge"
            >
              {healthLabel}
            </Badge>
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
        <ScrollArea className="flex-1">
          <nav className="py-2" data-testid="dashboard-tabs">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button key={tab.id} onClick={() => { setActiveTab(tab.id); setSidebarOpen(false); }}
                  className={cn("sidebar-item w-full", isActive && "active")}
                  data-testid={`tab-${tab.id}`}>
                  <Icon />
                  <span>{tab.label}</span>
                  {tab.id === "recommendations" && recCount > 0 && (
                    <Badge variant="destructive" className="ml-auto text-[10px] px-1.5 py-0">
                      {recCount}
                    </Badge>
                  )}
                </button>
              );
            })}
          </nav>
        </ScrollArea>

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
        {activeTab === "charts" && <ChartsDashboard />}
        {activeTab === "nodes" && <NodeHealth reportId={reportId} />}
        {activeTab === "storage" && <StorageDistribution reportId={reportId} />}
        {activeTab === "queries" && <WorkloadQueries reportId={reportId} />}
        {activeTab === "logs" && <LogExplorer reportId={reportId} />}
        {activeTab === "log-search" && <LogSearch reportId={reportId} />}
        {activeTab === "config" && <ConfigHealth reportId={reportId} />}
        {activeTab === "recommendations" && <Recommendations reportId={reportId} />}
        {activeTab === "glean" && <GleanSetup />}
      </main>
    </div>
  );
}
