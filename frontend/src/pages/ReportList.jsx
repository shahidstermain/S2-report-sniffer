import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileArchive, Trash2, ChevronRight, Loader2, Server, AlertTriangle, CheckCircle2, XCircle, Pause, Play } from "lucide-react";
import { toast } from "sonner";
import { uploadReport, importReport, listReports, deleteReport } from "@/lib/api";
import { healthColor } from "@/lib/utils-sdb";
import { useEffect } from "react";

const SS_LOGO_BLACK = "https://images.contentstack.io/v3/assets/bltac01ee6daa3a1e14/blt1c2b5b49b2a6e765/660fbc0fc3bc8b4365dd3b53/singlestore-horiztonal-lock-up-black.svg";

function formatFileSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let size = bytes;
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

export default function ReportList() {
  const [reports, setReports] = useState([]);
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

  const fetchReports = useCallback(async () => {
    try { const res = await listReports(); setReports(res.data); } catch { /* */ }
  }, []);

  useEffect(() => { fetchReports(); }, [fetchReports]);

  useEffect(() => {
    const processing = reports.some(r => r.status === "processing");
    if (!processing) return;
    const interval = setInterval(fetchReports, 3000);
    return () => clearInterval(interval);
  }, [reports, fetchReports]);

  const handleUpload = async (file) => {
    if (!file) return;
    const validExts = [".tar.gz", ".tgz", ".zip"];
    const lowerName = (file.name || "").toLowerCase();
    if (!validExts.some(ext => lowerName.endsWith(ext))) {
      toast.error("Accepted formats: .tar.gz, .tgz, .zip");
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
      const format = lowerName.endsWith('.zip') ? 'Extracted directory (zip)' : 'Compressed archive (tar.gz)';
      toast.success(`Uploaded. Detected format: ${format}. Parsing started.`);
      fetchReports();
    } catch (err) {
      console.error("Upload error:", err);
      let errorMessage = "Upload failed";
      
      // Enhanced error parsing for different response formats
      if (err.response?.data) {
        const errorData = err.response.data;
        console.log("Error response data:", errorData);
        
        // Handle FastAPI's default error format (detail key)
        if (errorData.detail) {
          const detail = errorData.detail;
          if (typeof detail === 'string') {
            errorMessage = detail;
          } else if (typeof detail === 'object') {
            // Parse structured detail object
            if (detail.message) {
              errorMessage = detail.message;
            } else if (detail.error) {
              errorMessage = detail.error;
            } else if (detail.details && Array.isArray(detail.details)) {
              errorMessage = detail.details.join(', ');
            } else {
              // Fallback to JSON string representation
              errorMessage = JSON.stringify(detail);
            }
          }
        } else if (typeof errorData === 'string') {
          errorMessage = errorData;
        } else if (errorData.error) {
          errorMessage = errorData.error;
        } else if (errorData.message) {
          errorMessage = errorData.message;
        } else if (errorData.details && Array.isArray(errorData.details)) {
          errorMessage = errorData.details.join(', ');
        } else {
          // Fallback for unknown error format
          errorMessage = JSON.stringify(errorData);
        }
      } else if (err.message) {
        errorMessage = err.message;
      }
      
      // If we still have a generic message, try to get more specific error info
      if (errorMessage === "Upload failed" && err.response?.status) {
        const status = err.response.status;
        if (status === 413) {
          errorMessage = "File too large - maximum 10GB allowed";
        } else if (status === 400) {
          errorMessage = "Invalid file format or filename";
        } else if (status === 500) {
          errorMessage = "Server error during upload - please try again";
        }
      }
      
      toast.error("Upload failed: " + errorMessage);
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleImport = async () => {
    const path = (importPath || "").trim();
    if (!path) {
      toast.error("Enter a file or directory path");
      return;
    }
    setImporting(true);
    try {
      await importReport(path);
      toast.success("Import queued. Parsing started.");
      setImportPath("");
      fetchReports();
    } catch (err) {
      console.error("Import error:", err);
      let errorMessage = "Import failed";

      if (err.response?.data) {
        const errorData = err.response.data;

        if (errorData.detail) {
          const detail = errorData.detail;
          if (typeof detail === "string") {
            errorMessage = detail;
          } else if (typeof detail === "object") {
            if (detail.message) {
              errorMessage = detail.message;
            } else if (detail.error) {
              errorMessage = detail.error;
            } else if (detail.details && Array.isArray(detail.details)) {
              errorMessage = detail.details.join(", ");
            } else {
              errorMessage = JSON.stringify(detail);
            }
          }
        } else if (typeof errorData === "string") {
          errorMessage = errorData;
        } else if (errorData.message) {
          errorMessage = errorData.message;
        } else if (errorData.error) {
          errorMessage = errorData.error;
        } else {
          errorMessage = JSON.stringify(errorData);
        }
      } else if (err.message) {
        errorMessage = err.message;
      }

      toast.error("Import failed: " + errorMessage);
    } finally {
      setImporting(false);
    }
  };

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (!window.confirm("Delete this report?")) return;
    try { await deleteReport(id); toast.success("Deleted"); fetchReports(); } catch { toast.error("Delete failed"); }
  };

  const etaSeconds = uploadSpeed > 0 ? Math.round((totalBytes - uploadedBytes) / uploadSpeed) : null;
  const etaStr = etaSeconds != null ? (etaSeconds > 60 ? `${Math.floor(etaSeconds/60)}m ${etaSeconds%60}s` : `${etaSeconds}s`) : "";

  return (
    <div className="min-h-screen" style={{ background: "var(--ss-light-gray)" }}>
      {/* Header */}
      <header style={{ background: "var(--ss-white)", borderBottom: "1px solid var(--ss-divider)" }}>
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center gap-3 sm:gap-4">
          <img src={SS_LOGO_BLACK} alt="SingleStore" style={{ width: "160px", maxWidth: "60vw", height: "auto" }} data-testid="app-logo" />
          <div className="hidden sm:block" style={{ width: "1px", height: "28px", background: "var(--ss-divider)" }} />
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-base font-semibold">Report Sniffer</span>
            <span style={{
              background: "rgba(170,0,255,0.1)", color: "#AA00FF",
              fontSize: "10px", fontWeight: 700, padding: "2px 8px", borderRadius: "4px",
            }}>v1</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => navigate("/vps")}
              className="flex items-center gap-2 text-xs border px-3 py-2 rounded bg-white"
              style={{ borderColor: "var(--ss-divider)" }}
              data-testid="nav-vps"
            >
              <Server size={14} /> VPS
            </button>
            <button
              onClick={() => navigate("/supabase/todos")}
              className="text-xs border px-3 py-2 rounded bg-white"
              style={{ borderColor: "var(--ss-divider)" }}
              data-testid="nav-supabase"
            >
              Supabase
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
        {/* Hero with large logo */}
        <div className="text-center mb-8 sm:mb-12">
          <div className="relative inline-block mb-6">
            <img
              src={SS_LOGO_BLACK}
              alt="SingleStore"
              className="mx-auto"
              style={{ width: "min(340px, 78vw)", height: "auto" }}
              data-testid="hero-logo"
            />
            <div 
              className="absolute bottom-0 left-1/2 transform -translate-x-1/2 h-1 rounded-full"
              style={{ width: "120px", background: "linear-gradient(90deg, transparent, #AA00FF, transparent)" }}
            />
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight mb-3" style={{ color: "var(--ss-charcoal)" }}>Report Sniffer</h1>
          <p className="text-base font-medium mb-1" style={{ color: "var(--ss-purple)" }}>
            Powered by SingleStore
          </p>
          <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>
            Instant cluster insight for SingleStore Support Engineers
          </p>
        </div>

        {/* Upload Dropzone */}
        <div
          className={`dropzone p-6 sm:p-10 text-center cursor-pointer mb-8 sm:mb-10 ${dragOver ? "drag-over" : ""}`}
          data-testid="upload-dropzone"
          onClick={() => !uploading && fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files[0]); }}
        >
          <input ref={fileRef} type="file" accept=".tar.gz,.tgz,.zip" className="hidden"
            onChange={(e) => handleUpload(e.target.files[0])} data-testid="file-input" />
          {uploading ? (
            <div className="flex flex-col items-center gap-3">
              <Loader2 size={28} className="animate-spin" style={{ color: "#AA00FF" }} />
              <p className="text-sm font-semibold">
                Uploading: {formatFileSize(uploadedBytes)} of {formatFileSize(totalBytes)} ({uploadProgress}%)
              </p>
              {etaStr && <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
                {formatFileSize(uploadSpeed)}/s &middot; {etaStr} remaining
              </p>}
              <div className="w-full max-w-80 progress-bar">
                <div className="progress-fill" style={{ width: `${uploadProgress}%`, background: "#AA00FF" }} />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <Upload size={32} style={{ color: "#AA00FF" }} />
              <p className="text-sm font-semibold">
                Drop a diagnostic report here or click to browse
              </p>
              <div className="flex gap-4 text-xs" style={{ color: "var(--ss-mid-gray)" }}>
                <span className="px-2 py-1 border rounded" style={{ borderColor: "var(--ss-divider)" }}>.tar.gz / .tgz</span>
                <span className="px-2 py-1 border rounded" style={{ borderColor: "var(--ss-divider)" }}>.zip</span>
              </div>
              <p className="text-[11px]" style={{ color: "var(--ss-mid-gray)" }}>
                sdb-report bundles up to 10 GB supported
              </p>
            </div>
          )}
        </div>

        <div className="ss-card p-4 mb-10">
          <div className="flex flex-col md:flex-row gap-3 items-stretch md:items-center">
            <div className="flex-1">
              <input
                value={importPath}
                onChange={(e) => setImportPath(e.target.value)}
                placeholder="Import from local path (absolute or relative)"
                className="w-full px-3 py-2 rounded border text-sm"
                style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}
                disabled={uploading || importing}
                data-testid="import-path-input"
              />
            </div>
            <button
              onClick={handleImport}
              className="px-4 py-2 rounded text-sm font-semibold"
              style={{ background: "#AA00FF", color: "white", opacity: uploading || importing ? 0.6 : 1 }}
              disabled={uploading || importing}
              data-testid="import-path-button"
            >
              {importing ? "Importing..." : "Import"}
            </button>
          </div>
          <div className="mt-2 text-[11px]" style={{ color: "var(--ss-mid-gray)" }}>
            Supports directories and archives: .zip, .tar.gz, .tgz, .tar, .gz
          </div>
        </div>

        <div className="ss-card p-4 mb-10">
          <div className="text-sm font-semibold mb-2">Deployment Options at a Glance</div>
          <div className="overflow-x-auto">
            <table className="w-full dense-table" data-testid="deployment-options-table">
              <thead>
                <tr>
                  <th className="text-left">Method</th>
                  <th className="text-left">Best For</th>
                  <th className="text-left">Infrastructure Required</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="text-[12px] font-medium">Helios Cloud Portal</td>
                  <td className="text-[12px]">Production, no-ops</td>
                  <td className="text-[12px]">None (fully managed)</td>
                </tr>
                <tr>
                  <td className="text-[12px] font-medium">Docker Dev Image</td>
                  <td className="text-[12px]">Local dev, CI/CD</td>
                  <td className="text-[12px]">Docker only</td>
                </tr>
                <tr>
                  <td className="text-[12px] font-medium">Linux (sdb-deploy)</td>
                  <td className="text-[12px]">On-premises / VMs</td>
                  <td className="text-[12px]">Linux hosts + SingleStore Tools</td>
                </tr>
                <tr>
                  <td className="text-[12px] font-medium">Kubernetes Operator</td>
                  <td className="text-[12px]">Cloud-native production</td>
                  <td className="text-[12px]">K8s cluster + Helm + License</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Reports Table */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
          <h2 className="text-lg font-semibold" data-testid="reports-heading">Reports</h2>
          <span className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>{reports.length} report{reports.length !== 1 ? "s" : ""}</span>
        </div>

        {reports.length === 0 ? (
          <div className="ss-card text-center py-16">
            <FileArchive size={36} className="mx-auto mb-3" style={{ color: "#AA00FF", opacity: 0.25 }} />
            <p className="text-sm font-medium" style={{ color: "var(--ss-mid-gray)" }}>No reports uploaded yet</p>
          </div>
        ) : (
          <div className="ss-card overflow-hidden">
            <div className="overflow-x-auto">
            <table className="w-full dense-table min-w-[980px]" data-testid="reports-table">
              <thead>
                <tr>
                  <th className="text-left">Status</th>
                  <th className="text-left">Report</th>
                  <th className="text-left">Uploaded</th>
                  <th className="text-left">Package</th>
                  <th className="text-left">Deployment</th>
                  <th className="text-right">Size</th>
                  <th className="text-left">Nodes</th>
                  <th className="text-left">Version</th>
                  <th className="text-left">Issues</th>
                  <th className="text-right"></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr key={r.id} className="cursor-pointer"
                    onClick={() => r.status === "ready" && navigate(`/report/${r.id}`)}
                    data-testid={`report-row-${r.id}`}>
                    <td>
                      <div className="flex items-center gap-2">
                        {r.status === "processing" ? (
                          <Loader2 size={14} className="animate-spin" style={{ color: "#AA00FF" }} />
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
                          color: r.status === "processing" ? "#AA00FF" :
                                 r.status === "error" ? "var(--ss-critical)" : healthColor(r.health_score)
                        }}>
                          {r.status === "ready" ? r.health_score : r.status}
                        </span>
                      </div>
                    </td>
                    <td style={{ fontFamily: "Inter, sans-serif", fontSize: "13px", fontWeight: 500 }}>{r.report_name}</td>
                    <td className="text-[12px]">{new Date(r.uploaded_at).toLocaleString()}</td>
                    <td>
                      {(() => {
                        const p = formatPackageType(r.detected_format);
                        return (
                          <span className="text-[11px] font-bold px-2 py-0.5 rounded border" title={p.title}
                            style={{ borderColor: "var(--ss-divider)", color: "var(--ss-mid-gray)", background: "var(--ss-white)" }}>
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
                            style={{ borderColor: "var(--ss-divider)", color: "var(--ss-mid-gray)", background: "var(--ss-white)" }}>
                            {d.label}
                          </span>
                        );
                      })()}
                    </td>
                    <td className="text-right text-[12px]">{formatFileSize(r.file_size)}</td>
                    <td>{r.node_count || "—"}</td>
                    <td>{r.version || "—"}</td>
                    <td>
                      {r.recommendation_count > 0 ? (
                        <span className="badge-warning text-[11px] font-bold px-2 py-0.5">{r.recommendation_count}</span>
                      ) : "—"}
                    </td>
                    <td className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {r.status === "ready" && (
                          <button onClick={(e) => { e.stopPropagation(); navigate(`/report/${r.id}`); }}
                            className="p-1.5 rounded hover:bg-gray-100" data-testid={`view-report-${r.id}`}>
                            <ChevronRight size={14} />
                          </button>
                        )}
                        <button onClick={(e) => handleDelete(e, r.id)}
                          className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500"
                          data-testid={`delete-report-${r.id}`}>
                          <Trash2 size={14} />
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
      </main>
    </div>
  );
}
