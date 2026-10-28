import { lazy, Suspense, useState, useEffect, useCallback } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Server, HardDrive, Activity, ScrollText, AlertTriangle, LayoutDashboard, Settings, ChevronLeft, Menu, Search, BarChart3, Stethoscope, ShieldCheck, FileText, Download } from "lucide-react";
import { exportReportHtml, exportReportMarkdown, getReportOverview, getReportStatus } from "@/lib/api";
import { publicAsset } from "@/lib/hostContext";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { getHealthBucket, getHealthGrade, getHealthScore } from "@/lib/utils-sdb";
import { cn } from "@/lib/utils";
import { firstAvailableTab, tabState } from "@/lib/product-ui";
import HelpMenu from "@/guided-mode/HelpMenu";
import ExplainPagePanel from "@/guided-mode/ExplainPagePanel";

const ClusterOverview = lazy(() => import("@/components/ClusterOverview"));
const NodeHealth = lazy(() => import("@/components/NodeHealth"));
const StorageDistribution = lazy(() => import("@/components/StorageDistribution"));
const WorkloadQueries = lazy(() => import("@/components/WorkloadQueries"));
const LogExplorer = lazy(() => import("@/components/LogExplorer"));
const LogSearch = lazy(() => import("@/components/LogSearch"));
const Recommendations = lazy(() => import("@/components/Recommendations"));
const ConfigHealth = lazy(() => import("@/components/ConfigHealth"));
const InsightsPanel = lazy(() => import("@/components/InsightsPanel"));
const DiskIntelligence = lazy(() => import("@/components/DiskIntelligence"));
const ChartsDashboard = lazy(() => import("@/components/ChartsDashboard"));
const DiagnosticsDashboard = lazy(() => import("@/components/DiagnosticsDashboard"));

const SS_LOGO_WHITE = publicAsset("singlestore-logo-white.svg");
const SS_LOGO_BLACK = publicAsset("singlestore-logo-white.svg");

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "recommendations", label: "Issues", icon: AlertTriangle },
  { id: "diagnostics", label: "Diagnostics", icon: Stethoscope },
  { id: "nodes", label: "Nodes", icon: Server },
  { id: "storage", label: "Storage", icon: HardDrive },
  { id: "queries", label: "Queries", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "config", label: "Config", icon: Settings },
];

export default function ReportDashboard() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeTab, setActiveTab] = useState("overview");
  const [initialTraceId, setInitialTraceId] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);
  const [statusData, setStatusData] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [logSearchPrefill, setLogSearchPrefill] = useState({ keyword: "", node: "" });
  const [logViewMode, setLogViewMode] = useState("search");
  const [storageSubTab, setStorageSubTab] = useState("databases");
  const [exporting, setExporting] = useState(null);

  const fetchData = useCallback(async (isCancelled = () => false) => {
    try {
      const statusRes = await getReportStatus(reportId);
      if (isCancelled()) return;
      setStatus(statusRes.data.status);
      setStatusData(statusRes.data);
      if (statusRes.data.status === "ready") {
        const res = await getReportOverview(reportId);
        if (isCancelled()) return;
        setOverview(res.data);
        setLoading(false);
      } else if (statusRes.data.status === "error") {
        setLoading(false);
      } else {
        // Keep loading/processing UI while the report is still parsing.
      }
    } catch (err) {
      if (!isCancelled()) setLoading(false);
    }
  }, [reportId]);

  useEffect(() => {
    let cancelled = false;
    // Clear prior report state immediately so a slow fetch cannot paint report A under report B's URL.
    setLoading(true);
    setOverview(null);
    setStatus(null);
    setStatusData(null);
    setLogSearchPrefill({ keyword: "", node: "" });
    fetchData(() => cancelled);
    return () => { cancelled = true; };
  }, [fetchData]);

  useEffect(() => {
    const traceMatch = location.pathname.match(/\/queries\/trace\/(sha256:[a-f0-9]{16})/i);
    if (traceMatch) {
      setActiveTab("queries");
      setInitialTraceId(traceMatch[1].toLowerCase());
      return;
    }
    setInitialTraceId(null);
    const tabMatch = location.pathname.match(/\/report\/[^/]+\/([^/]+)/);
    const tabId = tabMatch?.[1];
    if (tabId === "disk-intelligence") {
      setActiveTab("storage");
      setStorageSubTab("intelligence");
      return;
    }
    if (tabId === "log-search") {
      setActiveTab("logs");
      setLogViewMode("search");
      return;
    }
    if (tabId === "charts") {
      setActiveTab("overview");
      return;
    }
    if (tabId && TABS.some((tab) => tab.id === tabId)) {
      setActiveTab(tabId);
    }
  }, [location.pathname]);

  const openTab = useCallback((tabId) => {
    setActiveTab(tabId);
    setSidebarOpen(false);
    navigate(`/report/${reportId}/${tabId}`);
  }, [navigate, reportId]);

  const handleInvestigationNavigate = useCallback((tabId, params = {}) => {
    const targetTab = tabId === "log-search" ? "logs" : tabId === "disk-intelligence" ? "storage" : tabId;
    if ((tabId === "log-search" || tabId === "logs") && params.keyword) {
      setLogSearchPrefill({
        keyword: params.keyword || "",
        node: params.node || "",
      });
      setLogViewMode("search");
    }
    if (tabId === "disk-intelligence") {
      setStorageSubTab("intelligence");
    }
    openTab(targetTab);
  }, [openTab]);

  useEffect(() => {
    if (status !== "processing") return;
    let cancelled = false;
    const interval = setInterval(() => {
      fetchData(() => cancelled);
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [status, fetchData]);

  useEffect(() => {
    if (!overview?.capabilities) return;
    const current = tabState(activeTab, overview.capabilities);
    if (!current.available) {
      setActiveTab(firstAvailableTab(TABS.map((tab) => tab.id), overview.capabilities));
    }
  }, [overview, activeTab]);

  const downloadExport = async (format) => {
    setExporting(format);
    try {
      const response = format === "markdown"
        ? await exportReportMarkdown(reportId)
        : await exportReportHtml(reportId);
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `s2-report-${reportId}.${format === "markdown" ? "md" : "html"}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(null);
    }
  };

  if (loading || status === "processing") {
    const prog = overview?.progress || statusData?.progress || {};
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md shadow-lg">
          <CardHeader className="text-center pb-2">
            <img src={SS_LOGO_BLACK} alt="SingleStore" className="h-8 mx-auto mb-2 opacity-60" />
            <CardTitle className="text-sm font-semibold">
              {prog.message || (status === "processing" ? "Parsing Cluster Report…" : "Loading…")}
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
    const message = (statusData?.error || statusData?.message || "Failed to parse the Cluster Report.").toString();
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
  const healthScore = getHealthScore(overview?.health_score);
  const healthGrade = getHealthGrade(overview);
  const healthBucket = getHealthBucket(overview);
  const capabilities = overview?.capabilities || null;
  const isPartial = overview?.input_mode === "sparse" || capabilities?.partial;
  const privacy = overview?.privacy || {};
  const parseWarnings = overview?.parse_warnings || [];
  const healthLabel = healthGrade && healthScore != null
    ? `Finding severity ${healthGrade} · ${healthScore}`
    : healthBucket === "unknown"
      ? "unknown"
      : healthBucket;
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
    <div className="lg:flex min-h-screen w-full max-w-full overflow-hidden" style={{ background: "var(--ss-light-gray)" }}>
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
        <div className="mx-2 mb-2 flex items-center gap-2" data-guide-id="guided.help"><HelpMenu compact /></div>
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
        <div className="px-4 py-3 border-y border-white/10" data-guide-id="dashboard.summary">
          <p className="text-[11px] font-medium text-white truncate" title={overview?.report_name}>
            {overview?.report_name || "Report"}
          </p>
          <div className="flex items-center gap-2 mt-1.5">
            <Badge
              variant={healthBucket === "critical" ? "critical" : healthBucket === "warning" ? "warning" : "healthy"}
              data-testid="health-badge"
            >
              {healthGrade || healthBucket}
            </Badge>
            <span className="text-[10px] font-mono text-white/40">v{co.version || "?"}</span>
          </div>
          <p className="text-[10px] font-mono text-white/40 mt-1">
            {co.total_nodes || 0} nodes &middot; {co.leaves || 0}L / {co.aggregators || 0}A
          </p>
          <p className="text-[10px] font-mono text-white/40 mt-1">
            Package: {pkgLabel}
          </p>
          <p
            className="text-[10px] font-mono text-white/40 mt-1 cursor-help"
            title={[
              deployment && `Deployment: ${deployment}`,
              deploymentConfidence && `Confidence: ${deploymentConfidence}`,
              deploymentSignals && `Signals: ${deploymentSignals}`,
            ].filter(Boolean).join("\n") || undefined}
          >
            Deployment: {deployment || "—"}
          </p>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {isPartial && <Badge variant="outline" className="text-[9px] border-amber-400/30 text-amber-300">Partial input</Badge>}
            {privacy.anonymized && <Badge variant="outline" className="text-[9px] border-emerald-400/30 text-emerald-300"><ShieldCheck className="size-3" /> Anonymized</Badge>}
          </div>
          <div className="grid grid-cols-2 gap-1.5 mt-3" data-guide-id="dashboard.exports">
            <Button size="sm" variant="outline" className="h-7 text-[10px] border-white/15 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white" onClick={() => downloadExport("markdown")} disabled={Boolean(exporting)}>
              <FileText className="size-3" /> {exporting === "markdown" ? "Saving…" : "Markdown"}
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] border-white/15 bg-white/5 text-white/70 hover:bg-white/10 hover:text-white" onClick={() => downloadExport("html")} disabled={Boolean(exporting)}>
              <Download className="size-3" /> {exporting === "html" ? "Saving…" : "HTML"}
            </Button>
          </div>
        </div>

        {/* Nav Items */}
        <ScrollArea className="flex-1">
          <nav className="py-2" data-testid="dashboard-tabs" data-guide-id="dashboard.tabs">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              const capability = tabState(tab.id, capabilities);
              return (
                <button key={tab.id} onClick={() => openTab(tab.id)}
                  className={cn("sidebar-item w-full", isActive && "active")}
                  data-testid={`tab-${tab.id}`}
                  data-guide-available={capability.available ? "true" : "false"}>
                  <Icon />
                  <span>{tab.label}</span>
                  {!capability.available && <span className="ml-auto text-[9px] uppercase tracking-wide">No data</span>}
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
      <main className="flex-1 min-w-0 w-full p-3 sm:p-4 lg:p-6 overflow-x-hidden overflow-y-auto" style={{ maxHeight: "100dvh" }}>
        <ExplainPagePanel />
        {(isPartial || parseWarnings.length > 0) && (
          <Alert className="mb-4 border-amber-400/30 bg-amber-400/5">
            <AlertTriangle className="text-amber-500" />
            <AlertTitle>{isPartial ? "Partial diagnostic input" : "Report parsing notice"}</AlertTitle>
            <AlertDescription>
              {parseWarnings[0] || "Only dashboard sections backed by the supplied data are enabled."}
            </AlertDescription>
          </Alert>
        )}
        <div data-guide-id="dashboard.content">
        <Suspense fallback={<div className="py-12 text-center text-sm text-muted-foreground">Loading dashboard section…</div>}>
        {activeTab === "overview" && (
          <div className="lg:flex gap-4">
            <div className="flex-1">
              <ClusterOverview reportId={reportId} overview={overview} />
            </div>
            <div className="lg:w-80 mt-4 lg:mt-0">
              <InsightsPanel
                reportId={reportId}
                reportData={overview}
                findings={overview?.recommendations || []}
                onNavigateToIssues={() => openTab("recommendations")}
              />
            </div>
          </div>
        )}
        {activeTab === "diagnostics" && (
          <DiagnosticsDashboard
            overview={overview}
            reportId={reportId}
            onDiagnosticsUpdated={fetchData}
          />
        )}
        {activeTab === "nodes" && (
          <NodeHealth
            reportId={reportId}
            cpuHealth={overview?.extended_diagnostics?.cpu_health}
          />
        )}
        {activeTab === "storage" && <StorageDistribution reportId={reportId} initialSubTab={storageSubTab} />}
        {activeTab === "queries" && <WorkloadQueries reportId={reportId} initialTraceId={initialTraceId} />}
        {activeTab === "logs" && (
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 bg-white p-3 border" style={{ borderColor: "var(--ss-divider)" }}>
              <div>
                <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
                  Tracelog Viewer &amp; Search
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Search raw tracelogs with regex and context windows, or inspect the parsed log stream.
                </p>
              </div>
              <div className="flex gap-0 border self-start sm:self-auto" style={{ borderColor: "var(--ss-divider)" }}>
                <button
                  type="button"
                  onClick={() => setLogViewMode("search")}
                  className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 border-r ${
                    logViewMode === "search" ? "bg-[#AA00FF] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
                  }`}
                  data-testid="logs-tab-search"
                >
                  Log Search
                </button>
                <button
                  type="button"
                  onClick={() => setLogViewMode("stream")}
                  className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 ${
                    logViewMode === "stream" ? "bg-[#AA00FF] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
                  }`}
                  data-testid="logs-tab-stream"
                >
                  Log Stream
                </button>
              </div>
            </div>
            {logViewMode === "search" ? (
              <LogSearch
                reportId={reportId}
                initialKeyword={logSearchPrefill.keyword}
                initialNode={logSearchPrefill.node}
              />
            ) : (
              <LogExplorer reportId={reportId} />
            )}
          </div>
        )}
        {activeTab === "config" && <ConfigHealth reportId={reportId} />}
        {activeTab === "recommendations" && (
          <Recommendations reportId={reportId} onNavigateTab={handleInvestigationNavigate} />
        )}
        </Suspense>
        </div>
      </main>
    </div>
  );
}
