import { useState, useEffect, useCallback, useRef } from "react";
import { Loader2, Search, X } from "lucide-react";
import { getReportLogs } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const SEVERITIES = ["ALL", "ERROR", "FATAL", "WARN", "INFO"];

export default function LogExplorer({ reportId }) {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("ALL");
  const [nodeFilter, setNodeFilter] = useState("");
  const [logSummary, setLogSummary] = useState({});
  const [nodes, setNodes] = useState([]);
  const searchRef = useRef(null);

  const fetchLogs = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = { page: p, page_size: 100 };
      if (search) params.search = search;
      if (severity !== "ALL") params.severity = severity;
      if (nodeFilter) params.node = nodeFilter;
      const res = await getReportLogs(reportId, params);
      setLogs(res.data.logs || []);
      setTotal(res.data.total || 0);
      setPage(res.data.page || 1);
      setTotalPages(res.data.total_pages || 0);
      if (res.data.log_summary) {
        setLogSummary(res.data.log_summary);
        setNodes(Object.keys(res.data.log_summary.per_node || {}));
      }
    } catch { /* */ }
    setLoading(false);
  }, [reportId, search, severity, nodeFilter]);

  useEffect(() => { fetchLogs(1); }, [severity, nodeFilter]); // eslint-disable-line
  
  const handleSearch = (e) => {
    e.preventDefault();
    fetchLogs(1);
  };

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
    const regex = /(ERROR:|WARN:|WARNING:|FATAL:)/gi;
    const parts = msg.split(regex);
    return parts.map((part, i) => 
      regex.test(part) ? (
        <strong key={i} style={{ color: "#D32F2F", backgroundColor: "rgba(211,47,47,0.1)", padding: "0 2px", borderRadius: "2px" }}>{part}</strong>
      ) : (
        part
      )
    );
  };

  return (
    <div className="animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 mb-4">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Log Explorer
        </h2>
        <span className="text-xs font-mono" style={{ color: "var(--ss-mid-gray)" }}>
          {total} entries
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
                onClick={() => setSeverity("ERROR")}
                className="flex items-center gap-1 hover:underline"
                style={{ color: "var(--ss-critical)" }}
              >
                <span className="w-2 h-2 rounded-full bg-red-500"></span>
                {errorCount} Errors
              </button>
            )}
            {warnCount > 0 && (
              <button 
                onClick={() => setSeverity("WARN")}
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
                <button onClick={() => { setSearch(""); fetchLogs(1); }} className="absolute right-2 top-1/2 -translate-y-1/2">
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
                onClick={() => setSeverity(s)}
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
          {nodes.length > 0 && (
            <select
              value={nodeFilter}
              onChange={(e) => setNodeFilter(e.target.value)}
              className="text-xs font-mono h-8 px-2 border bg-white"
              style={{ borderColor: "var(--ss-divider)" }}
              data-testid="log-node-filter"
            >
              <option value="">All Nodes</option>
              {nodes.map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* Log Lines */}
      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--ss-purple)" }} /></div>
        ) : logs.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>No log entries match your filters</p>
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
                  <span className="w-36 flex-shrink-0 text-zinc-400">{log.timestamp}</span>
                  <span className={`w-12 flex-shrink-0 font-bold ${logClass(log.severity)}`}>
                    {log.severity}
                  </span>
                  <span className="w-32 flex-shrink-0 text-zinc-400 truncate" title={log.hostname}>
                    [{log.role}] {log.hostname?.split('.')[0]}
                  </span>
                  <span className="flex-1 break-all whitespace-pre-wrap">{renderMessage(log.message)}</span>
                </div>
              ))}
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between px-4 py-2 border-t" style={{ borderColor: "var(--ss-divider)" }}>
              <span className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
                Page {page} of {totalPages} ({total} total)
              </span>
              <div className="flex gap-1">
                <button onClick={() => fetchLogs(page - 1)} disabled={page <= 1}
                  className="text-[10px] uppercase font-bold px-2 py-1 border bg-white disabled:opacity-30" style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="log-prev-page"
                >Prev</button>
                <button onClick={() => fetchLogs(page + 1)} disabled={page >= totalPages}
                  className="text-[10px] uppercase font-bold px-2 py-1 border bg-white disabled:opacity-30" style={{ borderColor: "var(--ss-divider)" }}
                  data-testid="log-next-page"
                >Next</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
