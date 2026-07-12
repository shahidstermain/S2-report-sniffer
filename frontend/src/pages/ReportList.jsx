import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Upload, FileArchive, Trash2, ChevronRight, Loader2,
  AlertTriangle, CheckCircle2, XCircle,
  RefreshCw, Search, X, ArrowUpDown, ArrowUp, ArrowDown,
} from "lucide-react";
import { toast } from "sonner";
import { uploadReport, importReport, listReports, deleteReport } from "@/lib/api";
import { healthColor } from "@/lib/utils-sdb";
import {
  bucketByPeriod, computeStatusBreakdown, computeDeploymentBreakdown,
  buildUploadsTimeline, deltaFrom, filterReports, sortReports,
} from "@/lib/dashboard-utils";
import KpiStrip from "@/components/dashboard/KpiStrip";
import UploadsSparkline from "@/components/dashboard/UploadsSparkline";
import ReportsBreakdown from "@/components/dashboard/ReportsBreakdown";
import RecentActivity from "@/components/dashboard/RecentActivity";
import ThemeToggle from "@/components/dashboard/ThemeToggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { publicAsset } from "@/lib/hostContext";

const SS_LOGO_BLACK = publicAsset("singlestore-logo-white.svg");

const VALID_EXTS = [".tar.gz", ".tgz", ".tar", ".gz", ".zip"];
const ACCEPT_ATTR = ".zip,.tar,.tar.gz,.tgz,.gz,application/zip,application/x-tar,application/gzip,application/x-gzip,application/octet-stream";

function formatFileSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, size = bytes;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return `${size.toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

function formatPackageType(detectedFormat) {
  const f = String(detectedFormat || "").toLowerCase();
  if (!f) return { label: "—", title: "Unknown" };
  if (f === "zip") return { label: "ZIP", title: "ZIP archive" };
  if (f === "tar.gz") return { label: "Tarball", title: "Compressed tarball (.tar.gz/.tgz)" };
  if (f === "tar") return { label: "Tarball", title: "Tar archive (.tar)" };
  if (f === "gz") return { label: "GZIP", title: "Gzip file (.gz)" };
  if (f === "directory") return { label: "Folder", title: "Imported directory" };
  return { label: detectedFormat, title: String(detectedFormat) };
}

function formatDeploymentMethod(method) {
  const m = String(method || "");
  if (!m) return { label: "—", title: "Not analyzed yet" };
  return { label: m, title: m };
}

function deploymentTitle(r) {
  const method = String(r?.deployment_method || "");
  const confidence = String(r?.deployment_confidence || "");
  const signals = String(r?.deployment_signals || "");
  const lines = [];
  if (method) lines.push(method);
  if (confidence) lines.push(`Confidence: ${confidence}`);
  if (signals) lines.push(`Signals: ${signals}`);
  return lines.join("\n") || "Not analyzed yet";
}

function lastUpdatedLabel(ts) {
  if (!ts) return "—";
  const diff = Date.now() - ts;
  if (diff < 5_000) return "just now";
  const sec = Math.round(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  return new Date(ts).toLocaleTimeString();
}

function parseUploadError(err) {
  let msg = "Upload failed";
  const data = err?.response?.data;
  if (data?.detail) {
    const d = data.detail;
    if (typeof d === "string") msg = d;
    else if (d.message) msg = d.message;
    else if (d.error) msg = d.error;
    else if (Array.isArray(d.details)) msg = d.details.join(", ");
    else msg = JSON.stringify(d);
  } else if (typeof data === "string") msg = data;
  else if (data?.error) msg = data.error;
  else if (data?.message) msg = data.message;
  else if (err?.message) msg = err.message;
  if (msg === "Upload failed" && err?.response?.status) {
    const s = err.response.status;
    if (s === 413) msg = "File too large – maximum 10 GB allowed";
    else if (s === 400) msg = "Invalid file format or filename";
    else if (s === 500) msg = "Server error during upload – please try again";
  }
  return msg;
}

function SortHeader({ label, columnKey, sortKey, sortDir, onChange, align = "left" }) {
  const active = sortKey === columnKey;
  const Icon = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead className={cn("cursor-pointer select-none", align === "right" && "text-right")} onClick={() => onChange(columnKey)}>
      <span className="inline-flex items-center gap-1">
        {label}
        <Icon className={cn(!active && "opacity-50")} />
      </span>
    </TableHead>
  );
}

export default function ReportList() {
  const [reports, setReports] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [, setNowTick] = useState(0);

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadedBytes, setUploadedBytes] = useState(0);
  const [totalBytes, setTotalBytes] = useState(0);
  const [uploadSpeed, setUploadSpeed] = useState(0);
  const [importing, setImporting] = useState(false);
  const [importPath, setImportPath] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);
  const uploadStartRef = useRef(null);
  const navigate = useNavigate();

  // Filter / sort / search state
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortKey, setSortKey] = useState("uploaded_at");
  const [sortDir, setSortDir] = useState("desc");
  const [chartRange, setChartRange] = useState("14d");
  const [chartMode, setChartMode] = useState("stacked");
  const [pendingDeleteId, setPendingDeleteId] = useState(null);

  const fetchReports = useCallback(async (silent = false) => {
    if (!silent) setLoadingList(true);
    try {
      const res = await listReports();
      setReports(Array.isArray(res.data) ? res.data : []);
      setLastUpdated(Date.now());
    } catch {
      // keep last known reports; toast only on user-triggered refresh
      if (!silent) toast.error("Could not load reports");
    } finally {
      if (!silent) setLoadingList(false);
    }
  }, []);

  useEffect(() => { fetchReports(); }, [fetchReports]);

  // Auto-refresh while any report is processing
  useEffect(() => {
    const processing = reports.some((r) => r.status === "processing");
    if (!processing) return;
    const id = setInterval(() => fetchReports(true), 3000);
    return () => clearInterval(id);
  }, [reports, fetchReports]);

  // Re-render every 30s so "Last updated" stays fresh
  useEffect(() => {
    const id = setInterval(() => setNowTick((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  // Derived data
  const periods = useMemo(() => {
    const b = bucketByPeriod(reports);
    return {
      ...b,
      trend24h: deltaFrom(b.last24h, b.prev24h),
      trend7d: deltaFrom(b.last7d, b.prev7d),
    };
  }, [reports]);

  const statusBreakdown = useMemo(() => computeStatusBreakdown(reports), [reports]);
  const deploymentBreakdown = useMemo(() => computeDeploymentBreakdown(reports), [reports]);

  const timelineDays = chartRange === "7d" ? 7 : chartRange === "30d" ? 30 : 14;
  const timeline = useMemo(
    () => buildUploadsTimeline(reports, timelineDays),
    [reports, timelineDays]
  );

  const visibleReports = useMemo(() => {
    const filtered = filterReports(reports, { search, statusFilter });
    const sorted = sortReports(filtered, { key: sortKey, dir: sortDir });
    return [...sorted].sort((a, b) => {
      const aReady = a.status === "ready" && a.diagnostics_ready ? 1 : 0;
      const bReady = b.status === "ready" && b.diagnostics_ready ? 1 : 0;
      return bReady - aReady;
    });
  }, [reports, search, statusFilter, sortKey, sortDir]);

  const hasDiagnosticsReady = useMemo(
    () => reports.some((r) => r.status === "ready" && r.diagnostics_ready),
    [reports],
  );

  // Handlers
  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "report_name" ? "asc" : "desc");
    }
  };

  const handleKpiSelect = (id) => {
    setStatusFilter((cur) => (cur === id ? "all" : id));
  };

  const handleUpload = async (file) => {
    if (!file) return;
    const lower = (file.name || "").toLowerCase();
    if (!VALID_EXTS.some((ext) => lower.endsWith(ext))) {
      toast.error("Accepted formats: .tar.gz, .tgz, .tar, .gz, .zip");
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    setTotalBytes(file.size);
    setUploadedBytes(0);
    uploadStartRef.current = Date.now();
    try {
      await uploadReport(file, (e) => {
        if (e.total) {
          const pct = Math.round((e.loaded / e.total) * 100);
          setUploadProgress(pct);
          setUploadedBytes(e.loaded);
          const elapsed = (Date.now() - uploadStartRef.current) / 1000;
          if (elapsed > 0.5) setUploadSpeed(e.loaded / elapsed);
        }
      });
      const fmt = lower.endsWith(".zip")
        ? "Extracted directory (zip)"
        : lower.endsWith(".tar.gz") || lower.endsWith(".tgz")
          ? "Compressed archive (tar.gz)"
          : lower.endsWith(".tar")
            ? "Tar archive (.tar)"
            : lower.endsWith(".gz")
              ? "Gzip archive (.gz)"
              : "Unknown format";
      toast.success(`Uploaded. Detected format: ${fmt}. Parsing started.`);
      fetchReports(true);
    } catch (err) {
      toast.error("Upload failed: " + parseUploadError(err));
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleImport = async () => {
    const path = (importPath || "").trim();
    if (!path) { toast.error("Enter a file or directory path"); return; }
    setImporting(true);
    try {
      const res = await importReport(path);
      const reportId = res.data?.id;
      toast.success("Import queued. Opening Diagnostics tab…");
      setImportPath("");
      fetchReports(true);
      if (reportId) {
        navigate(`/report/${reportId}/diagnostics`);
      }
    } catch (err) {
      toast.error("Import failed: " + parseUploadError(err));
    } finally {
      setImporting(false);
    }
  };

  const handleDelete = (e, id) => {
    e.stopPropagation();
    setPendingDeleteId(id);
  };

  const confirmDelete = async () => {
    if (!pendingDeleteId) return;
    try {
      await deleteReport(pendingDeleteId);
      toast.success("Deleted");
      fetchReports(true);
    } catch {
      toast.error("Delete failed");
    } finally {
      setPendingDeleteId(null);
    }
  };

  const etaSeconds = uploadSpeed > 0 ? Math.round((totalBytes - uploadedBytes) / uploadSpeed) : null;
  const etaStr = etaSeconds != null
    ? (etaSeconds > 60 ? `${Math.floor(etaSeconds / 60)}m ${etaSeconds % 60}s` : `${etaSeconds}s`)
    : "";

  const totalCount = reports.length;
  const isFiltering = statusFilter !== "all" || search.trim().length > 0;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ─── Top Bar ─────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b bg-card/85 backdrop-blur supports-[backdrop-filter]:bg-card/70">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center gap-3 sm:gap-4">
          <img src={SS_LOGO_BLACK} alt="SingleStore" className="h-auto w-[120px] shrink-0 invert sm:w-[150px] dark:invert-0" data-testid="app-logo" />
          <Separator orientation="vertical" className="hidden sm:block h-6" />
          <div className="flex items-center gap-2 min-w-0">
            <span className="hidden text-base font-semibold text-foreground sm:inline" data-testid="app-title">Report Sniffer</span>
            <Badge className="text-[10px] font-bold border-0"
              style={{ background: "var(--ss-purple-light)", color: "var(--ss-purple)" }}>v1</Badge>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden sm:inline text-[11px] tabular-nums text-muted-foreground" data-testid="last-updated">
              Updated {lastUpdatedLabel(lastUpdated)}
            </span>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => fetchReports()}
              aria-label="Refresh reports"
              title="Refresh"
              data-testid="refresh-button"
              disabled={loadingList}
            >
              <RefreshCw className={loadingList ? "animate-spin" : ""} />
            </Button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8 flex flex-col gap-6">
        {/* ─── Title ───────────────────────────────────────── */}
        <section>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
            Diagnostic dashboard
          </h1>
          <p className="text-sm mt-1 text-muted-foreground">
            Instant cluster insight for SingleStore Support Engineers
          </p>
          {reports.some((r) => r.status === "ready") && !hasDiagnosticsReady && (
            <p className="text-xs mt-2 p-3 border rounded" style={{ borderColor: "var(--ss-warning)", color: "var(--ss-warning)" }} data-testid="no-diagnostics-banner">
              No report in this workspace has full Diagnostics panels yet. Use Import with an extracted sdb-report directory (not the Query Tracer test fixture).
            </p>
          )}
        </section>

        {/* ─── KPI Strip ───────────────────────────────────── */}
        <section data-testid="kpi-strip">
          <KpiStrip
            totals={totalCount}
            periods={periods}
            status={statusBreakdown}
            activeFilter={statusFilter}
            onSelect={handleKpiSelect}
          />
        </section>

        {/* ─── Upload + Import row ─────────────────────────── */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card
            className={cn(
              "lg:col-span-2 cursor-pointer border-dashed transition-colors hover:border-primary/50 hover:bg-accent/30",
              dragOver && "border-primary bg-accent/40"
            )}
            data-testid="upload-dropzone"
            onClick={() => !uploading && fileRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files[0]); }}
          >
            <CardContent className="p-6 sm:p-8 text-center">
            <input
              ref={fileRef}
              type="file"
              accept={ACCEPT_ATTR}
              className="hidden"
              onChange={(e) => handleUpload(e.target.files[0])}
              data-testid="file-input"
            />
            {uploading ? (
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="animate-spin text-primary" />
                <p className="text-sm font-semibold tabular-nums text-foreground">
                  Uploading {formatFileSize(uploadedBytes)} of {formatFileSize(totalBytes)} ({uploadProgress}%)
                </p>
                {etaStr && (
                  <p className="text-xs tabular-nums text-muted-foreground">
                    {formatFileSize(uploadSpeed)}/s · {etaStr} remaining
                  </p>
                )}
                <Progress value={uploadProgress} className="w-full max-w-sm h-2" />
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <Upload className="text-primary" />
                <p className="text-sm font-semibold text-foreground">
                  Drop a diagnostic report here or click to browse
                </p>
                <div className="flex gap-2 text-xs flex-wrap justify-center">
                  <Badge variant="outline">.tar.gz / .tgz</Badge>
                  <Badge variant="outline">.tar / .gz</Badge>
                  <Badge variant="outline">.zip</Badge>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  sdb-report bundles up to 10 GB supported
                </p>
              </div>
            )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Import from path</CardTitle>
              <CardDescription>Local folder or archive on this machine</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
            <Input
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              placeholder="/absolute/path/to/report"
              disabled={uploading || importing}
              data-testid="import-path-input"
              onKeyDown={(e) => { if (e.key === "Enter") handleImport(); }}
            />
            <Button
              onClick={handleImport}
              className="mt-auto"
              disabled={uploading || importing}
              data-testid="import-path-button"
            >
              {importing ? "Importing…" : "Import report"}
            </Button>
            </CardContent>
          </Card>
        </section>

        {/* ─── Charts + Sidebar ────────────────────────────── */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <UploadsSparkline
              data={timeline}
              range={chartRange}
              onRangeChange={setChartRange}
              mode={chartMode}
              onModeChange={setChartMode}
            />
          </div>
          <div className="space-y-4">
            <ReportsBreakdown
              status={statusBreakdown}
              deployments={deploymentBreakdown}
              totalReady={statusBreakdown.ready}
            />
            <RecentActivity reports={reports} />
          </div>
        </section>

        {/* ─── Reports table ───────────────────────────────── */}
        <section>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-3">
            <div>
              <h2 className="text-lg font-semibold text-foreground" data-testid="reports-heading">
                Reports
              </h2>
              <p className="text-xs mt-0.5 text-muted-foreground">
                {visibleReports.length} of {totalCount} {totalCount === 1 ? "report" : "reports"}
                {isFiltering ? " · filtered" : ""}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search…"
                  className="pl-8 pr-7 h-8 text-xs w-44 sm:w-56"
                  data-testid="search-input"
                />
                {search && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => setSearch("")}
                    className="absolute right-0 top-1/2 -translate-y-1/2 size-7"
                    aria-label="Clear search"
                  >
                    <X />
                  </Button>
                )}
              </div>
              <ToggleGroup
                type="single"
                value={statusFilter}
                onValueChange={(v) => v && setStatusFilter(v)}
                className="flex-wrap justify-start"
              >
                {[
                  { id: "all", label: "All" },
                  { id: "critical", label: "Critical" },
                  { id: "warning", label: "Warning" },
                  { id: "healthy", label: "Healthy" },
                  { id: "processing", label: "Processing" },
                  { id: "error", label: "Error" },
                ].map((c) => (
                  <ToggleGroupItem
                    key={c.id}
                    value={c.id}
                    size="sm"
                    className="text-xs data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
                    data-testid={`status-chip-${c.id}`}
                  >
                    {c.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          </div>

          {loadingList && totalCount === 0 ? (
            <Card>
              <CardContent className="p-4 flex flex-col gap-2">
                {[1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </CardContent>
            </Card>
          ) : totalCount === 0 ? (
            <Card className="text-center py-16">
              <CardContent>
                <FileArchive className="mx-auto mb-3 text-primary opacity-30" />
                <p className="text-sm font-medium text-muted-foreground">
                  No reports uploaded yet
                </p>
                <p className="text-xs mt-1 text-muted-foreground">
                  Drop an sdb-report archive above or import from a local path
                </p>
              </CardContent>
            </Card>
          ) : visibleReports.length === 0 ? (
            <Card className="text-center py-12">
              <CardContent>
                <p className="text-sm font-medium text-muted-foreground">
                  No reports match the current filters
                </p>
                <Button
                  type="button"
                  variant="link"
                  onClick={() => { setSearch(""); setStatusFilter("all"); }}
                  className="text-xs mt-2"
                >
                  Clear filters
                </Button>
              </CardContent>
            </Card>
          ) : (
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <Table className="min-w-[1000px]" data-testid="reports-table">
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <SortHeader label="Status" columnKey="health_score" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Report" columnKey="report_name" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Uploaded" columnKey="uploaded_at" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Package" columnKey="status" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Deployment" columnKey="deployment_method" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Size" columnKey="file_size" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} align="right" />
                      <SortHeader label="Nodes" columnKey="node_count" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <TableHead>Version</TableHead>
                      <TableHead>Diagnostics</TableHead>
                      <SortHeader label="Issues" columnKey="recommendation_count" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <TableHead className="text-right" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visibleReports.map((r) => (
                      <TableRow
                        key={r.id}
                        className="cursor-pointer"
                        onClick={() => r.status === "ready" && navigate(`/report/${r.id}`)}
                        data-testid={`report-row-${r.id}`}
                      >
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {r.status === "processing" ? (
                              <Loader2 className="animate-spin text-primary" />
                            ) : r.status === "error" ? (
                              <XCircle className="status-critical" />
                            ) : r.health_score === "critical" ? (
                              <XCircle className="status-critical" />
                            ) : r.health_score === "warning" ? (
                              <AlertTriangle className="status-warning" />
                            ) : (
                              <CheckCircle2 className="status-success" />
                            )}
                            <span className="text-[11px] uppercase tracking-wider font-bold" style={{
                              color: r.status === "processing" ? "var(--ss-purple)" :
                                     r.status === "error" ? "var(--ss-critical)" : healthColor(r.health_score)
                            }}>
                              {r.status === "ready" ? r.health_score : r.status}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="font-medium text-[13px]">
                          <div className="flex flex-col gap-0.5">
                            <span>{r.report_name}</span>
                            <span className="text-[10px] font-mono text-muted-foreground">{r.id.slice(0, 8)}</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-[12px] tabular-nums text-muted-foreground">{r.uploaded_at ? new Date(r.uploaded_at).toLocaleString() : "—"}</TableCell>
                        <TableCell>
                          {(() => {
                            const p = formatPackageType(r.detected_format);
                            return (
                              <Badge variant="outline" className="text-[11px]" title={p.title}>
                                {p.label}
                              </Badge>
                            );
                          })()}
                        </TableCell>
                        <TableCell>
                          {(() => {
                            const d = formatDeploymentMethod(r.deployment_method);
                            return (
                              <Badge variant="outline" className="text-[11px] max-w-[140px] truncate" title={deploymentTitle(r) || d.title}>
                                {d.label}
                              </Badge>
                            );
                          })()}
                        </TableCell>
                        <TableCell className="text-right text-[12px] tabular-nums">{formatFileSize(r.file_size)}</TableCell>
                        <TableCell className="tabular-nums">{r.node_count || "—"}</TableCell>
                        <TableCell>{r.version || "—"}</TableCell>
                        <TableCell>
                          {r.status === "ready" && r.diagnostics_ready ? (
                            <Badge variant="healthy" className="text-[10px]">Diagnostics</Badge>
                          ) : r.status === "ready" ? (
                            <Badge variant="outline" className="text-[10px] text-muted-foreground" title="Re-import bundle directory for MV_EVENTS, CPU, and network panels">
                              Dx pending
                            </Badge>
                          ) : "—"}
                        </TableCell>
                        <TableCell>
                          {r.recommendation_count > 0 ? (
                            <Badge variant="warning" className="text-[11px] tabular-nums">
                              {r.recommendation_count}
                            </Badge>
                          ) : "—"}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            {r.status === "ready" && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="size-7"
                                onClick={(e) => { e.stopPropagation(); navigate(`/report/${r.id}`); }}
                                data-testid={`view-report-${r.id}`}
                                aria-label="Open report"
                              >
                                <ChevronRight />
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7 text-muted-foreground hover:text-destructive"
                              onClick={(e) => handleDelete(e, r.id)}
                              data-testid={`delete-report-${r.id}`}
                              aria-label="Delete report"
                            >
                              <Trash2 />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}
        </section>
      </main>

      <AlertDialog open={!!pendingDeleteId} onOpenChange={(open) => !open && setPendingDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this report?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the report and its parsed diagnostics from local storage. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className={cn(buttonVariants({ variant: "destructive" }))}
              onClick={confirmDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
