import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileArchive, Trash2, ChevronRight, Loader2, Server, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { uploadReport, listReports, deleteReport } from "@/lib/api";
import { healthColor } from "@/lib/utils-sdb";
import { useEffect } from "react";

const SS_LOGO_BLACK = "https://images.contentstack.io/v3/assets/bltac01ee6daa3a1e14/blt1c2b5b49b2a6e765/660fbc0fc3bc8b4365dd3b53/singlestore-horiztonal-lock-up-black.svg";

export default function ReportList() {
  const [reports, setReports] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);
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
    try {
      await uploadReport(file, (e) => {
        if (e.total) setUploadProgress(Math.round((e.loaded / e.total) * 100));
      });
      toast.success("Report uploaded — parsing in progress");
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
    try { await deleteReport(id); toast.success("Report deleted"); fetchReports(); } catch { toast.error("Delete failed"); }
  };

  const HealthIcon = ({ health }) => {
    switch (health) {
      case "critical": return <XCircle size={16} className="status-critical" />;
      case "warning": return <AlertTriangle size={16} className="status-warning" />;
      case "healthy": return <CheckCircle2 size={16} className="status-success" />;
      default: return <Server size={16} style={{ color: "var(--ss-mid-gray)" }} />;
    }
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--ss-light-gray)" }}>
      {/* Top Bar */}
      <header style={{ background: "var(--ss-white)", borderBottom: "1px solid var(--ss-divider)" }}>
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-4">
          <img src={SS_LOGO_BLACK} alt="SingleStore" className="h-6" data-testid="app-logo" />
          <div style={{ width: "1px", height: "24px", background: "var(--ss-divider)" }} />
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold" data-testid="app-title">Report Sniffer</span>
            <span style={{
              background: "var(--ss-purple-badge)", color: "var(--ss-purple)",
              fontSize: "10px", fontWeight: 700, padding: "2px 6px", borderRadius: "4px",
              letterSpacing: "0.05em"
            }}>v1</span>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        {/* Hero + Upload */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold mb-2" style={{ color: "var(--ss-black)" }}>
            SingleStore Report Sniffer
          </h1>
          <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>
            Instant cluster insight for SingleStore Support Engineers
          </p>
        </div>

        <div
          className={`dropzone p-10 text-center cursor-pointer mb-8 ${dragOver ? "drag-over" : ""}`}
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
              <Loader2 size={28} className="animate-spin" style={{ color: "var(--ss-purple)" }} />
              <p className="text-sm font-medium" style={{ color: "var(--ss-mid-gray)" }}>Uploading... {uploadProgress}%</p>
              <div className="w-64 progress-bar">
                <div className="progress-fill" style={{ width: `${uploadProgress}%`, background: "var(--ss-purple)" }} />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <Upload size={28} style={{ color: "var(--ss-purple)" }} />
              <p className="text-sm font-semibold" style={{ color: "var(--ss-black)" }}>
                Drop a diagnostic report here or click to browse
              </p>
              <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
                .tar.gz / .tgz (sdb-report bundle) &nbsp;&bull;&nbsp; .zip (extracted report folder)
              </p>
            </div>
          )}
        </div>

        {/* Reports List */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold" data-testid="reports-heading">Reports</h2>
          <span className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>{reports.length} report{reports.length !== 1 ? "s" : ""}</span>
        </div>

        {reports.length === 0 ? (
          <div className="ss-card text-center py-16">
            <FileArchive size={36} className="mx-auto mb-3" style={{ color: "var(--ss-purple)", opacity: 0.3 }} />
            <p className="text-sm font-medium" style={{ color: "var(--ss-mid-gray)" }}>No reports uploaded yet</p>
            <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>Upload a .tar.gz or .zip to get started</p>
          </div>
        ) : (
          <div className="ss-card overflow-hidden">
            <table className="w-full dense-table" data-testid="reports-table">
              <thead>
                <tr>
                  <th className="text-left">Status</th>
                  <th className="text-left">Report Name</th>
                  <th className="text-left">Uploaded</th>
                  <th className="text-left">Nodes</th>
                  <th className="text-left">Version</th>
                  <th className="text-left">Issues</th>
                  <th className="text-right">Actions</th>
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
                          <Loader2 size={14} className="animate-spin" style={{ color: "var(--ss-purple)" }} />
                        ) : r.status === "error" ? (
                          <XCircle size={14} className="status-critical" />
                        ) : (
                          <HealthIcon health={r.health_score} />
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
                    <td>{new Date(r.uploaded_at).toLocaleString()}</td>
                    <td>{r.node_count || "—"}</td>
                    <td>{r.version || "—"}</td>
                    <td>
                      {r.recommendation_count > 0 ? (
                        <span className="badge-warning text-[11px] font-bold px-2 py-0.5 inline-block">{r.recommendation_count}</span>
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
