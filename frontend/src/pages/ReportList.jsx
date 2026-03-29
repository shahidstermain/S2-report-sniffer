import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Upload, FileArchive, Trash2, ChevronRight, Loader2, Server, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { uploadReport, listReports, deleteReport } from "@/lib/api";
import { formatBytes, healthColor } from "@/lib/utils-sdb";
import { useEffect } from "react";

export default function ReportList() {
  const [reports, setReports] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);
  const navigate = useNavigate();

  const fetchReports = useCallback(async () => {
    try {
      const res = await listReports();
      setReports(res.data);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => { fetchReports(); }, [fetchReports]);

  // Poll for processing reports
  useEffect(() => {
    const processing = reports.some(r => r.status === "processing");
    if (!processing) return;
    const interval = setInterval(fetchReports, 3000);
    return () => clearInterval(interval);
  }, [reports, fetchReports]);

  const handleUpload = async (file) => {
    if (!file) return;
    if (!file.name.endsWith(".tar.gz") && !file.name.endsWith(".tgz")) {
      toast.error("Only .tar.gz files are accepted");
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    try {
      const res = await uploadReport(file, (e) => {
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
    try {
      await deleteReport(id);
      toast.success("Report deleted");
      fetchReports();
    } catch {
      toast.error("Delete failed");
    }
  };

  const HealthIcon = ({ health }) => {
    switch (health) {
      case "critical": return <XCircle size={16} className="status-critical" />;
      case "warning": return <AlertTriangle size={16} className="status-warning" />;
      case "healthy": return <CheckCircle2 size={16} className="status-success" />;
      default: return <Server size={16} className="text-zinc-400" />;
    }
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--canvas)" }}>
      {/* Header */}
      <header className="border-b" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
          <img
            src="https://static.prod-images.emergentagent.com/jobs/14e0f03a-9374-4d11-971f-4351c695e47e/images/5548b00c48e2b9b1d93d57f6d2bf6342cfbcb38b9f78dbecdf3fe8d34c5a4120.png"
            alt="SDB Insight"
            className="w-8 h-8"
            data-testid="app-logo"
          />
          <h1 className="text-xl font-black tracking-tighter" style={{ fontFamily: "Chivo, sans-serif" }} data-testid="app-title">
            SDB Insight
          </h1>
          <span className="text-xs uppercase tracking-widest ml-1" style={{ color: "var(--text-tertiary)", fontFamily: "IBM Plex Sans, sans-serif" }}>
            Diagnostics
          </span>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Upload Zone */}
        <div
          className={`dropzone p-12 text-center cursor-pointer mb-8 ${dragOver ? "drag-over" : ""}`}
          data-testid="upload-dropzone"
          onClick={() => !uploading && fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const file = e.dataTransfer.files[0];
            if (file) handleUpload(file);
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".tar.gz,.tgz"
            className="hidden"
            onChange={(e) => handleUpload(e.target.files[0])}
            data-testid="file-input"
          />
          {uploading ? (
            <div className="flex flex-col items-center gap-3">
              <Loader2 size={32} className="animate-spin" style={{ color: "var(--brand-primary)" }} />
              <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>
                Uploading... {uploadProgress}%
              </p>
              <div className="w-64 progress-bar">
                <div className="progress-fill" style={{ width: `${uploadProgress}%`, background: "var(--brand-primary)" }} />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <Upload size={32} style={{ color: "var(--text-tertiary)" }} />
              <p className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
                Drop a .tar.gz diagnostic report here or click to browse
              </p>
              <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                Supports sdb-report collect-and-check bundles
              </p>
            </div>
          )}
        </div>

        {/* Reports List */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }} data-testid="reports-heading">
              Reports
            </h2>
            <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              {reports.length} report{reports.length !== 1 ? "s" : ""}
            </span>
          </div>

          {reports.length === 0 ? (
            <div className="text-center py-16 border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
              <FileArchive size={40} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)" }} />
              <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>No reports uploaded yet</p>
            </div>
          ) : (
            <div className="border" style={{ borderColor: "var(--border-default)" }}>
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
                    <tr
                      key={r.id}
                      className="cursor-pointer"
                      onClick={() => r.status === "ready" && navigate(`/report/${r.id}`)}
                      data-testid={`report-row-${r.id}`}
                    >
                      <td>
                        <div className="flex items-center gap-2">
                          {r.status === "processing" ? (
                            <Loader2 size={14} className="animate-spin" style={{ color: "var(--brand-primary)" }} />
                          ) : r.status === "error" ? (
                            <XCircle size={14} className="status-critical" />
                          ) : (
                            <HealthIcon health={r.health_score} />
                          )}
                          <span className="text-[10px] uppercase tracking-widest font-bold" style={{
                            color: r.status === "processing" ? "var(--brand-primary)" :
                                   r.status === "error" ? "var(--status-critical)" :
                                   healthColor(r.health_score)
                          }}>
                            {r.status === "ready" ? r.health_score : r.status}
                          </span>
                        </div>
                      </td>
                      <td className="font-medium" style={{ fontFamily: "IBM Plex Sans, sans-serif", fontSize: "13px" }}>
                        {r.report_name}
                      </td>
                      <td>{new Date(r.uploaded_at).toLocaleString()}</td>
                      <td>{r.node_count || "—"}</td>
                      <td>{r.version || "—"}</td>
                      <td>
                        {r.recommendation_count > 0 ? (
                          <span className="badge-warning text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 inline-block">
                            {r.recommendation_count}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          {r.status === "ready" && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 rounded-none"
                              onClick={(e) => { e.stopPropagation(); navigate(`/report/${r.id}`); }}
                              data-testid={`view-report-${r.id}`}
                            >
                              <ChevronRight size={14} />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 rounded-none text-zinc-400 hover:text-red-500"
                            onClick={(e) => handleDelete(e, r.id)}
                            data-testid={`delete-report-${r.id}`}
                          >
                            <Trash2 size={14} />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
