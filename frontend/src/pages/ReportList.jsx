import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileArchive, Trash2, ChevronRight, Loader2, Server, AlertTriangle, CheckCircle2, XCircle, Pause, Play } from "lucide-react";
import { toast } from "sonner";
import { uploadReport, listReports, deleteReport } from "@/lib/api";
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

export default function ReportList() {
  const [reports, setReports] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadedBytes, setUploadedBytes] = useState(0);
  const [totalBytes, setTotalBytes] = useState(0);
  const [uploadSpeed, setUploadSpeed] = useState(0);
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
    if (!validExts.some(ext => file.name.endsWith(ext))) {
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
      const format = file.name.endsWith('.zip') ? 'Extracted directory (zip)' : 'Compressed archive (tar.gz)';
      toast.success(`Uploaded. Detected format: ${format}. Parsing started.`);
      fetchReports();
    } catch (err) {
      toast.error("Upload failed: " + (err.response?.data?.detail || err.message));
    } finally {
      setUploading(false);
      setUploadProgress(0);
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
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-4">
          <img src={SS_LOGO_BLACK} alt="SingleStore" style={{ width: "160px", height: "auto" }} data-testid="app-logo" />
          <div style={{ width: "1px", height: "28px", background: "var(--ss-divider)" }} />
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold">Report Sniffer</span>
            <span style={{
              background: "rgba(170,0,255,0.1)", color: "#AA00FF",
              fontSize: "10px", fontWeight: 700, padding: "2px 8px", borderRadius: "4px",
            }}>v1</span>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-10">
        {/* Hero with large logo */}
        <div className="text-center mb-10">
          <img
            src={SS_LOGO_BLACK}
            alt="SingleStore"
            className="mx-auto mb-5"
            style={{ width: "280px", height: "auto" }}
            data-testid="hero-logo"
          />
          <h1 className="text-3xl font-bold tracking-tight mb-2">Report Sniffer</h1>
          <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>
            Instant cluster insight for SingleStore Support Engineers
          </p>
        </div>

        {/* Upload Dropzone */}
        <div
          className={`dropzone p-10 text-center cursor-pointer mb-10 ${dragOver ? "drag-over" : ""}`}
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
              <div className="w-80 progress-bar">
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

        {/* Reports Table */}
        <div className="flex items-center justify-between mb-3">
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
            <table className="w-full dense-table" data-testid="reports-table">
              <thead>
                <tr>
                  <th className="text-left">Status</th>
                  <th className="text-left">Report</th>
                  <th className="text-left">Uploaded</th>
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
        )}
      </main>
    </div>
  );
}
