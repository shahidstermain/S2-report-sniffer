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
    <th className={`text-${align} cursor-pointer select-none`} onClick={() => onChange(columnKey)}>
      <span className="inline-flex items-center gap-1">
        {label}
        <Icon size={11} style={{ opacity: active ? 1 : 0.5 }} />
      </span>
    </th>
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
    return sortReports(filtered, { key: sortKey, dir: sortDir });
  }, [reports, search, statusFilter, sortKey, sortDir]);

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
        : lower.endsWith(".tar")
          ? "Tar archive (.tar)"
          : lower.endsWith(".gz") && !lower.endsWith(".tar.gz")
            ? "Gzip archive (.gz)"
            : "Compressed archive (tar.gz)";
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
      await importReport(path);
      toast.success("Import queued. Parsing started.");
      setImportPath("");
      fetchReports(true);
    } catch (err) {
      toast.error("Import failed: " + parseUploadError(err));
    } finally {
      setImporting(false);
    }
  };

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (!window.confirm("Delete this report?")) return;
    try {
      await deleteReport(id);
      toast.success("Deleted");
      fetchReports(true);
    } catch {
      toast.error("Delete failed");
    }
  };

  const etaSeconds = uploadSpeed > 0 ? Math.round((totalBytes - uploadedBytes) / uploadSpeed) : null;
  const etaStr = etaSeconds != null
    ? (etaSeconds > 60 ? `${Math.floor(etaSeconds / 60)}m ${etaSeconds % 60}s` : `${etaSeconds}s`)
    : "";

  const totalCount = reports.length;
  const isFiltering = statusFilter !== "all" || search.trim().length > 0;

  return (
    <div className="min-h-screen" style={{ background: "var(--surface-bg)", color: "var(--text-primary)" }}>
      {/* ─── Top Bar ─────────────────────────────────────── */}
      <header
        className="sticky top-0 z-30 backdrop-blur"
        style={{
          background: "var(--header-bg)",
          borderBottom: "1px solid var(--border-default)",
        }}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center gap-3 sm:gap-4">
          <img src={SS_LOGO_BLACK} alt="SingleStore" style={{ width: "150px", maxWidth: "50vw", height: "auto" }} data-testid="app-logo" />
          <div className="hidden sm:block" style={{ width: "1px", height: "26px", background: "var(--border-default)" }} />
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Report Sniffer</span>
            <span style={{
              background: "var(--ss-purple-light)", color: "var(--ss-purple)",
              fontSize: "10px", fontWeight: 700, padding: "2px 8px", borderRadius: "4px",
            }}>v1</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden sm:inline text-[11px] tabular-nums" style={{ color: "var(--text-muted)" }} data-testid="last-updated">
              Updated {lastUpdatedLabel(lastUpdated)}
            </span>
            <button
              type="button"
              onClick={() => fetchReports()}
              className="icon-btn"
              aria-label="Refresh reports"
              title="Refresh"
              data-testid="refresh-button"
              disabled={loadingList}
            >
              <RefreshCw size={15} className={loadingList ? "animate-spin" : ""} />
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">
        {/* ─── Title ───────────────────────────────────────── */}
        <section>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Diagnostic dashboard
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Instant cluster insight for SingleStore Support Engineers
          </p>
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
          <div
            className={`dropzone p-6 sm:p-8 text-center cursor-pointer lg:col-span-2 ${dragOver ? "drag-over" : ""}`}
            data-testid="upload-dropzone"
            onClick={() => !uploading && fileRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files[0]); }}
          >
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
                <Loader2 size={28} className="animate-spin" style={{ color: "var(--ss-purple)" }} />
                <p className="text-sm font-semibold tabular-nums" style={{ color: "var(--text-primary)" }}>
                  Uploading {formatFileSize(uploadedBytes)} of {formatFileSize(totalBytes)} ({uploadProgress}%)
                </p>
                {etaStr && (
                  <p className="text-xs tabular-nums" style={{ color: "var(--text-muted)" }}>
                    {formatFileSize(uploadSpeed)}/s · {etaStr} remaining
                  </p>
                )}
                <div className="w-full max-w-sm progress-bar">
                  <div className="progress-fill" style={{ width: `${uploadProgress}%`, background: "var(--ss-purple)" }} />
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <Upload size={26} style={{ color: "var(--ss-purple)" }} />
                <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  Drop a diagnostic report here or click to browse
                </p>
                <div className="flex gap-2 text-xs flex-wrap justify-center">
                  <span className="chip">.tar.gz / .tgz</span>
                  <span className="chip">.tar / .gz</span>
                  <span className="chip">.zip</span>
                </div>
                <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                  sdb-report bundles up to 10 GB supported
                </p>
              </div>
            )}
          </div>

          <div className="surface-card p-4 flex flex-col gap-3">
            <div>
              <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Import from path</h3>
              <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                Local folder or archive on this machine
              </p>
            </div>
            <input
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              placeholder="/absolute/path/to/report"
              className="w-full px-3 py-2 rounded text-sm outline-none"
              style={{
                border: "1px solid var(--border-default)",
                background: "var(--surface-bg)",
                color: "var(--text-primary)",
              }}
              disabled={uploading || importing}
              data-testid="import-path-input"
              onKeyDown={(e) => { if (e.key === "Enter") handleImport(); }}
            />
            <button
              onClick={handleImport}
              className="px-4 py-2 rounded text-sm font-semibold mt-auto"
              style={{ background: "var(--ss-purple)", color: "white", opacity: (uploading || importing) ? 0.6 : 1 }}
              disabled={uploading || importing}
              data-testid="import-path-button"
            >
              {importing ? "Importing…" : "Import report"}
            </button>
          </div>
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
              <h2 className="text-lg font-semibold" data-testid="reports-heading" style={{ color: "var(--text-primary)" }}>
                Reports
              </h2>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                {visibleReports.length} of {totalCount} {totalCount === 1 ? "report" : "reports"}
                {isFiltering ? " · filtered" : ""}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: "var(--text-muted)" }} />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search…"
                  className="pl-8 pr-7 py-1.5 rounded text-xs outline-none w-44 sm:w-56"
                  style={{
                    border: "1px solid var(--border-default)",
                    background: "var(--surface-card)",
                    color: "var(--text-primary)",
                  }}
                  data-testid="search-input"
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2"
                    style={{ color: "var(--text-muted)" }}
                    aria-label="Clear search"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              <div className="flex items-center gap-1">
                {[
                  { id: "all", label: "All" },
                  { id: "critical", label: "Critical" },
                  { id: "warning", label: "Warning" },
                  { id: "healthy", label: "Healthy" },
                  { id: "processing", label: "Processing" },
                  { id: "error", label: "Error" },
                ].map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setStatusFilter(c.id)}
                    className={`chip ${statusFilter === c.id ? "active" : ""}`}
                    data-testid={`status-chip-${c.id}`}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {loadingList && totalCount === 0 ? (
            <div className="surface-card p-4 space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="skeleton h-8 w-full" />
              ))}
            </div>
          ) : totalCount === 0 ? (
            <div className="surface-card text-center py-16">
              <FileArchive size={36} className="mx-auto mb-3" style={{ color: "var(--ss-purple)", opacity: 0.3 }} />
              <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                No reports uploaded yet
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Drop an sdb-report archive above or import from a local path
              </p>
            </div>
          ) : visibleReports.length === 0 ? (
            <div className="surface-card text-center py-12">
              <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                No reports match the current filters
              </p>
              <button
                type="button"
                onClick={() => { setSearch(""); setStatusFilter("all"); }}
                className="text-xs mt-2 underline"
                style={{ color: "var(--ss-purple)" }}
              >
                Clear filters
              </button>
            </div>
          ) : (
            <div className="surface-card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full dense-table min-w-[1000px]" data-testid="reports-table">
                  <thead>
                    <tr>
                      <SortHeader label="Status" columnKey="health_score" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Report" columnKey="report_name" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Uploaded" columnKey="uploaded_at" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Package" columnKey="status" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Deployment" columnKey="deployment_method" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <SortHeader label="Size" columnKey="file_size" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} align="right" />
                      <SortHeader label="Nodes" columnKey="node_count" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <th className="text-left">Version</th>
                      <SortHeader label="Issues" columnKey="recommendation_count" sortKey={sortKey} sortDir={sortDir} onChange={handleSort} />
                      <th className="text-right" />
                    </tr>
                  </thead>
                  <tbody>
                    {visibleReports.map((r) => (
                      <tr
                        key={r.id}
                        className="cursor-pointer"
                        onClick={() => r.status === "ready" && navigate(`/report/${r.id}`)}
                        data-testid={`report-row-${r.id}`}
                      >
                        <td>
                          <div className="flex items-center gap-2">
                            {r.status === "processing" ? (
                              <Loader2 size={14} className="animate-spin" style={{ color: "var(--ss-purple)" }} />
                            ) : r.status === "error" ? (
                              <XCircle size={14} className="status-critical" />
                            ) : r.health_score === "critical" ? (
                              <XCircle size={14} className="status-critical" />
                            ) : r.health_score === "warning" ? (
                              <AlertTriangle size={14} className="status-warning" />
                            ) : (
                              <CheckCircle2 size={14} className="status-success" />
                            )}
                            <span className="text-[11px] uppercase tracking-wider font-bold" style={{
                              color: r.status === "processing" ? "var(--ss-purple)" :
                                     r.status === "error" ? "var(--ss-critical)" : healthColor(r.health_score)
                            }}>
                              {r.status === "ready" ? r.health_score : r.status}
                            </span>
                          </div>
                        </td>
                        <td style={{ fontFamily: "Inter, sans-serif", fontSize: "13px", fontWeight: 500 }}>{r.report_name}</td>
                        <td className="text-[12px] tabular-nums">{r.uploaded_at ? new Date(r.uploaded_at).toLocaleString() : "—"}</td>
                        <td>
                          {(() => {
                            const p = formatPackageType(r.detected_format);
                            return (
                              <span className="text-[11px] font-bold px-2 py-0.5 rounded border" title={p.title}
                                style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)", background: "var(--surface-card)" }}>
                                {p.label}
                              </span>
                            );
                          })()}
                        </td>
                        <td>
                          {(() => {
                            const d = formatDeploymentMethod(r.deployment_method);
                            return (
                              <span className="text-[11px] font-bold px-2 py-0.5 rounded border" title={deploymentTitle(r) || d.title}
                                style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)", background: "var(--surface-card)" }}>
                                {d.label}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="text-right text-[12px] tabular-nums">{formatFileSize(r.file_size)}</td>
                        <td className="tabular-nums">{r.node_count || "—"}</td>
                        <td>{r.version || "—"}</td>
                        <td>
                          {r.recommendation_count > 0 ? (
                            <span className="badge-warning text-[11px] font-bold px-2 py-0.5">{r.recommendation_count}</span>
                          ) : "—"}
                        </td>
                        <td className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            {r.status === "ready" && (
                              <button
                                onClick={(e) => { e.stopPropagation(); navigate(`/report/${r.id}`); }}
                                className="icon-btn"
                                style={{ width: 26, height: 26 }}
                                data-testid={`view-report-${r.id}`}
                                aria-label="Open report"
                              >
                                <ChevronRight size={13} />
                              </button>
                            )}
                            <button
                              onClick={(e) => handleDelete(e, r.id)}
                              className="icon-btn"
                              style={{ width: 26, height: 26 }}
                              data-testid={`delete-report-${r.id}`}
                              aria-label="Delete report"
                            >
                              <Trash2 size={13} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
