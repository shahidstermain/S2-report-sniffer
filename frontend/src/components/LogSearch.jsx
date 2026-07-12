import { useState, useCallback, useRef } from "react";
import { Search, RegexIcon, Download, Filter, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { searchReportLogs } from "@/lib/api";
import InfoHint from "./InfoHint";

const SEVERITIES = ["ALL", "ERROR", "FATAL", "WARN", "INFO", "DEBUG"];

function matchText(match) {
  return match?.line || match?.message || "";
}

export default function LogSearch({ reportId }) {
  const [keyword, setKeyword] = useState("");
  const [regex, setRegex] = useState(false);
  const [severity, setSeverity] = useState("ALL");
  const [nodeFilter, setNodeFilter] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [nodesSearched, setNodesSearched] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [searchMode, setSearchMode] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedMatches, setExpandedMatches] = useState(new Set());
  const [searched, setSearched] = useState(false);
  const inputRef = useRef(null);

  const doSearch = useCallback(async (e) => {
    if (e) e.preventDefault();
    if (!keyword.trim()) return;

    setLoading(true);
    setSearched(true);
    setExpandedMatches(new Set());
    setError(null);

    try {
      const params = {
        keyword: keyword.trim(),
        regex,
        case_sensitive: caseSensitive,
        max_results: 500,
      };
      if (severity !== "ALL") params.severity = severity;
      if (nodeFilter.trim()) params.node = nodeFilter.trim();

      const res = await searchReportLogs(reportId, params);
      const data = res.data || {};

      setResults(data.matches || []);
      setTotal(data.total || 0);
      setNodesSearched(data.nodes_searched || 0);
      setTruncated(data.truncated || false);
      setSearchMode(data.search_mode || null);
    } catch (err) {
      const message =
        err?.response?.data?.message ||
        err?.response?.data?.detail?.message ||
        err?.message ||
        "Log search failed";
      setError(message);
      toast.error(message);
      setResults([]);
      setTotal(0);
      setSearchMode(null);
    }
    setLoading(false);
  }, [reportId, keyword, regex, severity, caseSensitive, nodeFilter]);

  const toggleExpand = (idx) => {
    setExpandedMatches((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const highlightText = (text) => {
    if (!text || !keyword) return text;
    try {
      const pattern = new RegExp(
        regex ? keyword : keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
        caseSensitive ? "g" : "gi"
      );
      const parts = text.split(pattern);
      const matches = text.match(pattern) || [];
      return parts.flatMap((part, i) => [
        part,
        matches[i] ? (
          <mark key={i} style={{ backgroundColor: "#FFD54F", color: "#000", padding: "0 2px", borderRadius: "2px" }}>
            {matches[i]}
          </mark>
        ) : null,
      ]);
    } catch {
      return text;
    }
  };

  const sevColor = (sev) => {
    switch ((sev || "").toUpperCase()) {
      case "ERROR": return "#D32F2F";
      case "FATAL": return "#B71C1C";
      case "WARN": case "WARNING": return "#F57C00";
      case "DEBUG": return "#78909C";
      default: return "#558B2F";
    }
  };

  const exportResults = () => {
    const lines = results.map((m) => {
      const ts = m.timestamp || "";
      const sev = m.severity || "INFO";
      const node = m.hostname || "";
      const msg = matchText(m);
      const before = (m.context_before || []).join("\n");
      const after = (m.context_after || []).join("\n");
      const body = [before, msg, after].filter(Boolean).join("\n");
      return `[${ts}] [${sev}] [${node}] ${body}`;
    }).join("\n\n");

    const blob = new Blob([lines], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `log-search-${keyword.replace(/[^a-z0-9]/gi, "_")}-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="ss-card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="flex items-center gap-1">
            <h2 className="text-lg font-bold flex items-center gap-2">
              <Search size={20} style={{ color: "#AA00FF" }} />
              Log Search
            </h2>
            <InfoHint label="log search" content="Searches tracelogs across report nodes. Raw mode includes surrounding lines when extracted files were retained; parsed mode searches the bounded log index." />
          </div>
          <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>
            Search across all nodes' tracelogs — supports plain text and regex
          </p>
        </div>
        {results.length > 0 && (
          <Button variant="outline" size="sm" onClick={exportResults} className="flex items-center gap-1">
            <Download size={14} /> Export
          </Button>
        )}
      </div>

      <form onSubmit={doSearch} className="space-y-3">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Input
              ref={inputRef}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="Search keyword or regex... (e.g., 'OOM killed', 'error.*timeout')"
              className="pr-10"
              data-testid="log-search-input"
            />
            <Search size={16} className="absolute right-3 top-1/2 -translate-y-1/2" style={{ color: "var(--ss-mid-gray)" }} />
          </div>
          <Button type="submit" disabled={loading || !keyword.trim()} style={{ background: "#AA00FF" }}>
            {loading ? "Searching..." : "Search"}
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={regex}
              onChange={(e) => setRegex(e.target.checked)}
              className="accent-purple-600"
            />
            <RegexIcon size={14} /> Regex
          </label>

          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={caseSensitive}
              onChange={(e) => setCaseSensitive(e.target.checked)}
              className="accent-purple-600"
            />
            Case sensitive
          </label>

          <div className="flex items-center gap-1">
            <Filter size={12} style={{ color: "var(--ss-mid-gray)" }} />
            <span className="text-gray-500">Severity:</span>
            <div className="flex gap-1">
              {SEVERITIES.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSeverity(s)}
                  className={`px-2 py-0.5 rounded text-[11px] font-semibold transition-colors ${
                    severity === s
                      ? "text-white"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                  style={severity === s ? { background: sevColor(s) } : {}}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <Input
            value={nodeFilter}
            onChange={(e) => setNodeFilter(e.target.value)}
            placeholder="Node prefix filter"
            className="h-7 w-40 text-xs font-mono"
          />
        </div>
      </form>

      {loading && (
        <div className="mt-6 text-center py-8">
          <div className="animate-spin mx-auto" style={{ width: 24, height: 24, border: "2px solid #e5e7eb", borderTopColor: "#AA00FF", borderRadius: "50%" }} />
          <p className="text-sm mt-2" style={{ color: "var(--ss-mid-gray)" }}>Searching across all nodes...</p>
        </div>
      )}

      {error && !loading && (
        <div className="mt-4 text-sm text-red-600 border border-red-200 rounded p-3">{error}</div>
      )}

      {!loading && searched && total === 0 && !error && (
        <div className="mt-6 text-center py-8">
          <p className="text-sm font-medium">No matches found</p>
          <p className="text-xs mt-1" style={{ color: "var(--ss-mid-gray)" }}>
            Try a different keyword, enable regex, or adjust the severity filter
          </p>
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="mt-4">
          <div className="flex items-center justify-between mb-3 text-xs flex-wrap gap-2">
            <span style={{ color: "var(--ss-mid-gray)" }}>
              Found <strong className="text-gray-900">{total}</strong> matches across <strong className="text-gray-900">{nodesSearched}</strong> nodes
              {truncated && " (showing first 500)"}
            </span>
            {searchMode && (
              <span
                className="px-2 py-0.5 rounded font-semibold uppercase tracking-wide"
                style={{
                  background: searchMode === "raw" ? "rgba(0,217,146,0.15)" : "rgba(170,0,255,0.1)",
                  color: searchMode === "raw" ? "#00a86b" : "#AA00FF",
                }}
              >
                {searchMode} mode{searchMode === "raw" ? " · context lines" : " · indexed logs"}
              </span>
            )}
          </div>

          <div className="space-y-1 max-h-[60vh] overflow-y-auto" style={{ scrollbarWidth: "thin" }}>
            {results.map((match, idx) => (
              <div
                key={idx}
                className="border rounded-lg overflow-hidden transition-colors hover:bg-gray-50"
                style={{ borderColor: "var(--ss-divider)" }}
              >
                <button
                  onClick={() => toggleExpand(idx)}
                  className="w-full flex items-center gap-3 px-3 py-2 text-left text-xs"
                >
                  <span
                    className="px-1.5 py-0.5 rounded font-bold text-white text-[10px] uppercase"
                    style={{ background: sevColor(match.severity) }}
                  >
                    {match.severity || "INFO"}
                  </span>
                  <span className="font-mono text-gray-500" title={match.timestamp}>
                    {match.timestamp?.slice(0, 19) || ""}
                  </span>
                  <span className="font-mono text-gray-400 text-[10px]" title={match.source}>
                    {match.hostname || ""}
                  </span>
                  <span className="flex-1 truncate font-mono">
                    {highlightText(matchText(match))}
                  </span>
                  {expandedMatches.has(idx) ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>

                {expandedMatches.has(idx) && (
                  <div className="px-3 pb-3 border-t" style={{ borderColor: "var(--ss-divider)" }}>
                    {(match.context_before?.length > 0 || match.context_after?.length > 0) ? (
                      <div className="mt-2 font-mono text-[11px] space-y-0.5">
                        {match.context_before?.map((line, i) => (
                          <div key={`b-${i}`} className="text-gray-400 pl-4">{line}</div>
                        ))}
                        <div className="bg-yellow-50 px-2 py-1 rounded text-gray-900 font-semibold border-l-2" style={{ borderColor: "#FFD54F" }}>
                          {highlightText(matchText(match))}
                        </div>
                        {match.context_after?.map((line, i) => (
                          <div key={`a-${i}`} className="text-gray-400 pl-4">{line}</div>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-2 font-mono text-[11px] text-gray-600 whitespace-pre-wrap">
                        {matchText(match)}
                      </div>
                    )}
                    <div className="flex gap-2 mt-2 text-[10px] text-gray-400">
                      {match.source && <span>File: {match.source}</span>}
                      {match.line_number > 0 && <span>Line: {match.line_number}</span>}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
