import { useState, useEffect, useRef } from "react";
import { Loader2, Search, X } from "lucide-react";
import { getReportLogs } from "@/lib/api";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import InfoHint from "./InfoHint";

const SEVERITIES = ["ALL", "ERROR", "FATAL", "WARN", "INFO"];

export default function LogExplorer({ reportId }) {
  return <ReportLogStream key={reportId} reportId={reportId} />;
}

function ReportLogStream({ reportId }) {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [legacy, setLegacy] = useState(false);
  const [error, setError] = useState("");
  const [severity, setSeverity] = useState("ALL");
  const [nodeFilter, setNodeFilter] = useState("");
  const [logSummary, setLogSummary] = useState({});
  const [nodes, setNodes] = useState([]);
  const [goToPageInput, setGoToPageInput] = useState("");
  const searchRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const params = { page, page_size: 100 };
    if (appliedSearch) params.search = appliedSearch;
    if (severity !== "ALL") params.severity = severity === "ERRORS" ? "ERROR,FATAL" : severity;
    if (nodeFilter) {
      const [hostname, role, port] = JSON.parse(nodeFilter);
      Object.assign(params, { node: hostname, node_role: role, node_port: port, node_exact: true });
    }
    setLoading(true);
    setError("");
    getReportLogs(reportId, params).then(({ data }) => {
      if (cancelled) return;
      setLogs(data.logs || []);
      setTotal(data.total || 0);
      setTotalPages(data.total_pages || 0);
      setLogSummary({ severity_counts: data.timeline_severity_counts || data.log_summary?.severity_counts || {} });
      const options = data.log_nodes || Object.keys(data.log_summary?.per_node || {})
        .map((hostname) => ({ hostname, role: "", port: "" }));
      setNodes([...options].sort((a, b) => a.hostname.localeCompare(b.hostname, undefined, { numeric: true })));
      setLegacy(data.timeline_indexed === false);
    }).catch((err) => {
      if (cancelled) return;
      setLogs([]);
      setTotal(0);
      setTotalPages(0);
      setError(err?.response?.data?.message || err?.message || "Failed to load tracelogs");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reportId, appliedSearch, severity, nodeFilter, page]);

  function changeSeverity(value) {
    setSeverity(value);
    setPage(1);
  }

  useEffect(() => {
    setGoToPageInput(String(page));
  }, [page]);
  
  const handleSearch = (e) => {
    e.preventDefault();
    setAppliedSearch(search.trim());
    setPage(1);
  };

  const handleGoToPage = (e) => {
    e.preventDefault();
    if (totalPages < 1) return;
    const parsed = Number.parseInt(goToPageInput.trim(), 10);
    if (!Number.isFinite(parsed)) {
      toast.error("Enter a valid page number");
      return;
    }
    const target = Math.min(Math.max(parsed, 1), totalPages);
    if (target !== parsed) {
      toast.message(`Jumped to page ${target} (valid range: 1–${totalPages})`);
    }
    setPage(target);
  };

  const pageButtonClass =
    "text-[10px] uppercase font-bold px-2 py-1 border bg-white disabled:opacity-30 hover:bg-zinc-50";

  const logClass = (sev) => {
    switch ((sev || "").toUpperCase()) {
      case "ERROR": return "log-error";
      case "FATAL": return "log-fatal";
      case "WARN": case "WARNING": return "log-warn";
      default: return "log-info";
    }
  };

  const logRowClass = (sev) => {
    switch ((sev || "").toUpperCase()) {
      case "ERROR": return "log-row-error";
      case "FATAL": return "log-row-fatal";
      case "WARN": case "WARNING": return "log-row-warn";
      default: return "log-row-info";
    }
  };

  const errorCount = (logSummary?.severity_counts?.ERROR || 0) + (logSummary?.severity_counts?.FATAL || 0);
  const warnCount = (logSummary?.severity_counts?.WARN || 0) + (logSummary?.severity_counts?.WARNING || 0);

  const renderMessage = (msg) => {
    if (!msg) return "";
    const parts = msg.split(/(ERROR:|WARN:|WARNING:|FATAL:)/gi);
    return parts.map((part, i) => {
      const upper = part.toUpperCase();
      if (upper === "ERROR:" || upper === "WARN:" || upper === "WARNING:" || upper === "FATAL:") {
        return (
          <strong
            key={i}
            style={{
              color: "#D32F2F",
              backgroundColor: "rgba(211,47,47,0.1)",
              padding: "0 2px",
              borderRadius: "2px",
            }}
          >
            {part}
          </strong>
        );
      }
      return <span key={i}>{part}</span>;
    });
  };

  return (
    <div className="animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 mb-4">
        <div className="flex items-center gap-1">
          <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Tracelog Explorer
          </h2>
          <InfoHint label="tracelog explorer" content="Browse timestamped tracelog entries from the Cluster Report. Filter by node, severity, or message." />
        </div>
        <span className="text-xs font-mono" style={{ color: "var(--ss-mid-gray)" }}>
          {total} entries · Newest first
        </span>
      </div>

      {/* Highlights Banner */}
      {(errorCount > 0 || warnCount > 0) && (
        <div className="mb-4 p-3 rounded border flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4" style={{ backgroundColor: "rgba(244, 67, 54, 0.05)", borderColor: "var(--ss-critical)" }}>
          <div className="font-bold text-sm" style={{ color: "var(--ss-critical)" }}>
            Attention Required:
          </div>
          <div className="flex flex-wrap gap-3 text-xs font-mono">
            {errorCount > 0 && (
              <button 
                onClick={() => changeSeverity("ERRORS")}
                className="flex items-center gap-1 hover:underline"
                style={{ color: "var(--ss-critical)" }}
                title="Filter ERROR and FATAL severities"
              >
                <span className="w-2 h-2 rounded-full bg-red-500"></span>
                {errorCount} Errors/Fatal
              </button>
            )}
            {warnCount > 0 && (
              <button 
                onClick={() => changeSeverity("WARN")}
                className="flex items-center gap-1 hover:underline"
                style={{ color: "var(--ss-warning)" }}
              >
                <span className="w-2 h-2 rounded-full bg-orange-500"></span>
                {warnCount} Warnings
              </button>
            )}
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="border mb-4" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <div className="p-3 flex flex-wrap items-center gap-3">
          {/* Search */}
          <form onSubmit={handleSearch} className="flex-1 min-w-0 w-full sm:w-auto flex gap-1">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--ss-mid-gray)" }} />
              <Input
                ref={searchRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search logs (grep-style)..."
                className="pl-9 rounded-none border-zinc-300 text-sm font-mono h-8"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
                data-testid="log-search-input"
              />
              {search && (
                <button type="button" aria-label="Clear search" onClick={() => { setSearch(""); setAppliedSearch(""); setPage(1); }} className="absolute right-2 top-1/2 -translate-y-1/2">
                  <X size={14} style={{ color: "var(--ss-mid-gray)" }} />
                </button>
              )}
            </div>
            <Button type="submit" className="rounded-none h-8 px-4 bg-[#AA00FF] hover:bg-[#9200DB] text-white text-xs" data-testid="log-search-button">
              Search
            </Button>
          </form>

          {/* Severity filter */}
          <div className="w-full sm:w-auto overflow-x-auto">
          <div className="flex gap-0 border min-w-max" style={{ borderColor: "var(--ss-divider)" }}>
            {SEVERITIES.map(s => (
              <button
                key={s}
                onClick={() => changeSeverity(s)}
                className={`text-[10px] uppercase tracking-widest font-bold px-2.5 py-1 border-r last:border-r-0 ${
                  severity === s ? "bg-[#AA00FF] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
                }`}
                style={{ borderColor: "var(--ss-divider)" }}
                data-testid={`log-filter-${s.toLowerCase()}`}
              >
                {s}
              </button>
            ))}
          </div>
          </div>

          {/* Node filter */}
          <label className="flex items-center gap-2 text-xs font-medium">
            Node
            <select
              value={nodeFilter}
              onChange={(e) => { setNodeFilter(e.target.value); setPage(1); }}
              className="text-xs font-mono h-8 px-2 border bg-white"
              style={{ borderColor: "var(--ss-divider)" }}
              data-testid="log-node-filter"
            >
              <option value="">All Nodes</option>
              {nodes.map(({ hostname, role, port }) => {
                const key = JSON.stringify([hostname, role, port]);
                return <option key={key} value={key}>{hostname}{port ? `:${port}` : ""}{role ? ` (${role})` : ""}</option>;
              })}
            </select>
          </label>
        </div>
      </div>

      {legacy && <p className="mb-3 text-xs text-muted-foreground">This saved report uses the older tracelog index. Import the original Cluster Report again to include its full timeline.</p>}

      {/* Log Lines */}
      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--ss-purple)" }} /></div>
        ) : error ? (
          <p role="alert" className="p-4 text-sm">{error}</p>
        ) : logs.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>{nodeFilter || appliedSearch || severity !== "ALL" ? "No tracelog entries match these filters." : "No timestamped tracelog entries were found in this report."}</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto font-mono text-[11px]" style={{ fontFamily: "JetBrains Mono, monospace" }} data-testid="log-lines">
              {logs.map((log, i) => (
                <div
                  key={i}
                  className={`flex min-w-[760px] border-b px-3 py-1 hover:bg-zinc-50 ${logRowClass(log.severity)}`}
                  style={{ borderColor: "#F4F4F5" }}
                  data-testid={`log-entry-${i}`}
                >
                  <span className="w-48 flex-shrink-0 text-zinc-600">{log.timestamp}</span>
                  <span className={`w-12 flex-shrink-0 font-bold ${logClass(log.severity)}`}>
                    {log.severity}
                  </span>
                  <span className="w-32 flex-shrink-0 text-zinc-400 truncate" title={log.hostname}>
                    [{log.role}] {log.hostname}{log.node_port ? `:${log.node_port}` : ""}
                  </span>
                  <span className="flex-1 break-all whitespace-pre-wrap">{renderMessage(log.message)}</span>
                </div>
              ))}
            </div>

            {/* Pagination */}
            <div className="flex flex-col gap-2 px-4 py-2 border-t sm:flex-row sm:items-center sm:justify-between" style={{ borderColor: "var(--ss-divider)" }}>
              <span className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
                Page {page} of {totalPages} ({total} total)
              </span>
              <div className="flex flex-wrap items-center gap-1">
                <button
                  onClick={() => setPage(1)}
                  disabled={page <= 1}
                  className={pageButtonClass}
                  style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="log-first-page"
                >
                  First
                </button>
                <button
                  onClick={() => setPage(page - 1)}
                  disabled={page <= 1}
                  className={pageButtonClass}
                  style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="log-prev-page"
                >
                  Prev
                </button>
                <form onSubmit={handleGoToPage} className="flex items-center gap-1">
                  <label htmlFor="log-go-to-page" className="sr-only">Go to page</label>
                  <Input
                    id="log-go-to-page"
                    type="number"
                    min={1}
                    max={totalPages || 1}
                    value={goToPageInput}
                    onChange={(e) => setGoToPageInput(e.target.value)}
                    className="h-7 w-14 rounded-none border-zinc-300 text-[11px] font-mono px-2 text-center"
                    style={{ fontFamily: "JetBrains Mono, monospace" }}
                    data-testid="log-go-to-page-input"
                  />
                  <button
                    type="submit"
                    disabled={totalPages < 1}
                    className={pageButtonClass}
                    style={{ borderColor: "var(--ss-divider)" }}
                    data-testid="log-go-to-page-button"
                  >
                    Go
                  </button>
                </form>
                <button
                  onClick={() => setPage(page + 1)}
                  disabled={page >= totalPages}
                  className={pageButtonClass}
                  style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="log-next-page"
                >
                  Next
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={page >= totalPages || totalPages < 1}
                  className={pageButtonClass}
                  style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="log-last-page"
                >
                  Last
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
