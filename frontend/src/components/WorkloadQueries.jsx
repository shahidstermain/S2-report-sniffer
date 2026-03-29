import { useState, useEffect } from "react";
import { Loader2, Activity, Lock } from "lucide-react";
import { getReportQueries } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export default function WorkloadQueries({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("queries");

  useEffect(() => {
    getReportQueries(reportId).then(res => { setData(res.data); setLoading(false); }).catch(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--brand-primary)" }} /></div>;
  if (!data) return <p className="text-sm p-4" style={{ color: "var(--text-tertiary)" }}>No data available</p>;

  const queries = data.queries || [];
  const wm = data.workload_management || [];
  const blocked = data.cluster_overview?.blocked_queries || [];
  const processlist = data.cluster_overview?.processlist || [];
  const resourcePools = data.resource_pools || [];

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Workload & Queries
        </h2>
        <div className="ml-auto flex gap-0 border" style={{ borderColor: "var(--border-default)" }}>
          {[
            { id: "queries", label: `Queries (${queries.length})` },
            { id: "processlist", label: `Processlist (${processlist.length})` },
            { id: "blocked", label: `Blocked (${blocked.length})` },
            { id: "pools", label: `Pools (${resourcePools.length})` },
            { id: "workload", label: `WLM (${wm.length})` },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 border-r last:border-r-0 ${
                tab === t.id ? "bg-[#002FA7] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
              }`}
              style={{ borderColor: "var(--border-default)" }}
              data-testid={`queries-tab-${t.id}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "queries" && <QueriesTable queries={queries} />}
      {tab === "processlist" && <GenericTable rows={processlist} title="Active Processlist" />}
      {tab === "blocked" && <GenericTable rows={blocked} title="Blocked Queries" emptyMsg="No blocked queries — no lock contention detected" />}
      {tab === "pools" && <ResourcePoolsView pools={resourcePools} />}
      {tab === "workload" && <WLMTable rows={wm} />}
    </div>
  );
}

function QueriesTable({ queries }) {
  const [page, setPage] = useState(0);
  const pageSize = 50;
  const paginated = queries.slice(page * pageSize, (page + 1) * pageSize);
  const totalPages = Math.ceil(queries.length / pageSize);

  return (
    <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
      <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
        <table className="w-full dense-table" data-testid="queries-table">
          <thead className="sticky top-0">
            <tr>
              <th className="text-left w-12">#</th>
              <th className="text-left">Activity Name</th>
              <th className="text-left" style={{ minWidth: "400px" }}>Query Text</th>
              <th className="text-left">Warnings</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((q, i) => (
              <tr key={i}>
                <td className="text-zinc-400">{page * pageSize + i + 1}</td>
                <td className="text-[11px] truncate max-w-[200px]" title={q.ACTIVITY_NAME}>
                  {q.ACTIVITY_NAME || "—"}
                </td>
                <td>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="text-[11px] font-mono truncate max-w-[500px] cursor-help" style={{ color: "var(--text-primary)" }}>
                          {(q.QUERY_TEXT || "—").substring(0, 120)}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="bottom" className="max-w-[600px] p-3 rounded-none">
                        <pre className="text-[10px] font-mono whitespace-pre-wrap break-all">{q.QUERY_TEXT || "—"}</pre>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </td>
                <td className="text-[11px]">
                  {q.PLAN_WARNINGS ? (
                    <span className="status-warning">{q.PLAN_WARNINGS.substring(0, 80)}</span>
                  ) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-2 border-t" style={{ borderColor: "var(--border-default)" }}>
          <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            Page {page + 1} of {totalPages} ({queries.length} queries)
          </span>
          <div className="flex gap-1">
            <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
              className="text-[10px] uppercase font-bold px-2 py-1 border bg-white disabled:opacity-30" style={{ borderColor: "var(--border-default)" }}>Prev</button>
            <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
              className="text-[10px] uppercase font-bold px-2 py-1 border bg-white disabled:opacity-30" style={{ borderColor: "var(--border-default)" }}>Next</button>
          </div>
        </div>
      )}
    </div>
  );
}

function GenericTable({ rows, title, emptyMsg = "No data" }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="border p-8 text-center" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>{emptyMsg}</p>
      </div>
    );
  }
  const cols = Object.keys(rows[0]).slice(0, 10);
  return (
    <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
        <table className="w-full dense-table">
          <thead className="sticky top-0">
            <tr>
              {cols.map(c => <th key={c} className="text-left">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map((row, i) => (
              <tr key={i}>
                {cols.map(c => (
                  <td key={c} className="text-[11px] truncate max-w-[200px]" title={String(row[c] || "")}>
                    {String(row[c] || "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WLMTable({ rows }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="border p-8 text-center" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>No workload management data</p>
      </div>
    );
  }
  return (
    <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
      <div className="overflow-x-auto">
        <table className="w-full dense-table" data-testid="wlm-table">
          <thead>
            <tr>
              <th className="text-left">Stat</th>
              <th className="text-left">Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td className="font-medium" style={{ fontFamily: "IBM Plex Sans, sans-serif" }}>{row.Stat || "—"}</td>
                <td>{row.Value || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ResourcePoolsView({ pools }) {
  if (!pools || pools.length === 0) {
    return (
      <div className="border p-8 text-center" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>No resource pool data</p>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="border" style={{ borderColor: "var(--border-default)", background: "var(--surface)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--border-default)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Resource Pools (SHOW RESOURCE POOLS)
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-tertiary)" }}>
            Workload management resource pools are SingleStore's primary mechanism for isolating mixed workloads.
          </p>
        </div>
        <div className="p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {pools.map((pool, i) => {
            const isDefault = (pool.Pool_Name || "").includes("default");
            const hasQueue = pool.Max_Queue_Depth && pool.Max_Queue_Depth !== "NULL" && pool.Max_Queue_Depth !== "0";
            return (
              <div key={i} className="border p-3" style={{ borderColor: "var(--border-default)" }} data-testid={`pool-${pool.Pool_Name}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-mono font-bold">{pool.Pool_Name}</span>
                  {isDefault && <span className="text-[9px] px-1 bg-zinc-100 text-zinc-500">DEFAULT</span>}
                </div>
                <div className="space-y-1 text-[10px] font-mono" style={{ color: "var(--text-secondary)" }}>
                  <div className="flex justify-between">
                    <span>Memory %</span>
                    <span className="font-bold">{pool.Memory_Percentage || "NULL"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Max Concurrency</span>
                    <span className="font-bold">{pool.Max_Concurrency || "NULL"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Queue Depth</span>
                    <span className={`font-bold ${hasQueue ? "status-warning" : ""}`}>{pool.Max_Queue_Depth || "NULL"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Query Timeout</span>
                    <span className="font-bold">{pool.Query_Timeout || "NULL"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Soft CPU %</span>
                    <span className="font-bold">{pool.Soft_CPU_Limit_Percentage || "NULL"}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
