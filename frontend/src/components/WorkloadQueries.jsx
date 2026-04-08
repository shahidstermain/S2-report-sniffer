import { useState, useEffect, useMemo } from "react";
import { Loader2 } from "lucide-react";
import { getReportQueries } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from "recharts";

export default function WorkloadQueries({ reportId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("queries");

  useEffect(() => {
    getReportQueries(reportId).then(res => { setData(res.data); setLoading(false); }).catch(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-12"><Loader2 className="animate-spin" style={{ color: "var(--ss-purple)" }} /></div>;
  if (!data) return <p className="text-sm p-4" style={{ color: "var(--ss-mid-gray)" }}>No data available</p>;

  const queries = data.queries || [];
  const wm = data.workload_management || [];
  const blocked = data.cluster_overview?.blocked_queries || [];
  const processlist = data.cluster_overview?.processlist || [];
  const resourcePools = data.resource_pools || [];
  const allocMemory = data.alloc_memory || { per_node: [], totals: [] };

  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Workload & Queries
        </h2>
        <div className="sm:ml-auto w-full sm:w-auto overflow-x-auto">
        <div className="flex gap-0 border min-w-max" style={{ borderColor: "var(--ss-divider)" }}>
          {[
            { id: "queries", label: `Queries (${queries.length})` },
            { id: "heatmap", label: `Heatmap` },
            { id: "alloc", label: `Alloc (${allocMemory.per_node?.length || 0})` },
            { id: "processlist", label: `Processlist (${processlist.length})` },
            { id: "blocked", label: `Blocked (${blocked.length})` },
            { id: "pools", label: `Pools (${resourcePools.length})` },
            { id: "workload", label: `WLM (${wm.length})` },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`text-[10px] uppercase tracking-widest font-bold px-3 py-1.5 border-r last:border-r-0 ${
                tab === t.id ? "bg-[#AA00FF] text-white" : "bg-white text-zinc-500 hover:bg-zinc-50"
              }`}
              style={{ borderColor: "var(--ss-divider)" }}
              data-testid={`queries-tab-${t.id}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        </div>
      </div>

      {tab === "queries" && <QueriesTable queries={queries} />}
      {tab === "heatmap" && <WorkloadHeatmap queries={queries} />}
      {tab === "alloc" && <AllocMemoryView allocMemory={allocMemory} />}
      {tab === "processlist" && <GenericTable rows={processlist} />}
      {tab === "blocked" && <GenericTable rows={blocked} title="Blocked Queries" emptyMsg="No blocked queries — no lock contention detected" />}
      {tab === "pools" && <ResourcePoolsView pools={resourcePools} />}
      {tab === "workload" && <WLMTable rows={wm} />}
    </div>
  );
}

function WorkloadHeatmap({ queries }) {
  const chartData = useMemo(() => {
    return queries
      .filter(q => q.CPU_TIME_MS != null && q.MEMORY_BS != null)
      .map(q => ({
        x: parseInt(q.CPU_TIME_MS) || 0,
        y: parseInt(q.MEMORY_BS) / (1024 * 1024), // MB
        z: parseInt(q.COMMITS) || 1,
        name: q.ACTIVITY_NAME || "Unknown",
        queryText: (q.QUERY_TEXT || "").substring(0, 100) + "..."
      }))
      .filter(d => d.x > 0 || d.y > 0);
  }, [queries]);

  if (chartData.length === 0) {
    return (
      <div className="border p-8 text-center" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>No performance metrics available for heatmap</p>
      </div>
    );
  }

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-white border p-3 shadow-lg" style={{ borderColor: "var(--ss-divider)" }}>
          <p className="text-xs font-bold mb-1">{data.name}</p>
          <p className="text-[10px] font-mono text-zinc-500 mb-2">{data.queryText}</p>
          <div className="text-[10px] font-mono">
            <span style={{ color: "var(--ss-purple)" }}>CPU:</span> {data.x} ms <br />
            <span style={{ color: "var(--ss-info)" }}>Mem:</span> {data.y.toFixed(2)} MB <br />
            <span style={{ color: "var(--ss-warning)" }}>Commits:</span> {data.z}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          Query Performance Heatmap (CPU vs Memory)
        </h3>
        <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
          Outliers in the top-right represent queries consuming the most cluster resources. Bubble size indicates commit count.
        </p>
      </div>
      <div className="p-2 sm:p-4" style={{ height: "min(500px, 72vh)" }}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--ss-divider)" />
            <XAxis type="number" dataKey="x" name="CPU Time" unit="ms" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} stroke="var(--ss-mid-gray)" />
            <YAxis type="number" dataKey="y" name="Memory" unit="MB" tick={{ fontSize: 10, fontFamily: "JetBrains Mono" }} stroke="var(--ss-mid-gray)" />
            <ZAxis type="number" dataKey="z" range={[50, 400]} name="Commits" />
            <RechartsTooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3' }} />
            <Scatter name="Queries" data={chartData} fill="var(--ss-purple)" fillOpacity={0.6} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value >= 1024 ** 3) return `${(value / (1024 ** 3)).toFixed(2)} GB`;
  if (value >= 1024 ** 2) return `${(value / (1024 ** 2)).toFixed(2)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(2)} KB`;
  return `${value} B`;
}

function AllocMemoryView({ allocMemory }) {
  const perNode = allocMemory?.per_node || [];
  const totals = allocMemory?.totals || [];

  if (perNode.length === 0 && totals.length === 0) {
    return (
      <div className="border p-8 text-center" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>No Alloc_* memory metrics were found in this report</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Allocation Memory Breakdown
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
            These Alloc_* counters show where engine memory is being consumed. Large image/code allocation buckets often point to compile pressure or code-cache growth.
          </p>
        </div>
        <div className="p-4 grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: "var(--ss-mid-gray)" }}>
              Cluster Totals
            </p>
            <div className="space-y-2">
              {totals.slice(0, 8).map((item) => (
                <div key={item.metric} className="flex items-center justify-between border px-3 py-2" style={{ borderColor: "var(--ss-divider)" }}>
                  <span className="text-[11px] font-mono">{item.metric}</span>
                  <span className="text-[11px] font-mono font-bold">{formatBytes(item.value)}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: "var(--ss-mid-gray)" }}>
              Per Node
            </p>
            <div className="space-y-3">
              {perNode.map((node) => (
                <div key={node.hostname} className="border p-3" style={{ borderColor: "var(--ss-divider)" }}>
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <div className="text-xs font-mono font-bold">{node.hostname}</div>
                      <div className="text-[10px] uppercase tracking-widest" style={{ color: "var(--ss-mid-gray)" }}>{node.role}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px]" style={{ color: "var(--ss-mid-gray)" }}>Total Alloc</div>
                      <div className="text-xs font-mono font-bold">{formatBytes(node.total_bytes)}</div>
                    </div>
                  </div>
                  <div className="space-y-1">
                    {node.top_metrics.map((metric) => (
                      <div key={`${node.hostname}-${metric.metric}`} className="flex items-center justify-between text-[10px] font-mono">
                        <span className="truncate pr-3 min-w-0" title={metric.metric}>{metric.metric}</span>
                        <span className="font-bold">{formatBytes(metric.value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function QueriesTable({ queries }) {
  const [page, setPage] = useState(0);
  const pageSize = 50;
  const paginated = queries.slice(page * pageSize, (page + 1) * pageSize);
  const totalPages = Math.ceil(queries.length / pageSize);

  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
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
                        <div className="text-[11px] font-mono truncate max-w-[500px] cursor-help" style={{ color: "var(--ss-black)" }}>
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
        <div className="flex items-center justify-between px-4 py-2 border-t" style={{ borderColor: "var(--ss-divider)" }}>
          <span className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
            Page {page + 1} of {totalPages} ({queries.length} queries)
          </span>
          <div className="flex gap-1">
            <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
              className="text-[10px] uppercase font-bold px-2 py-1 border bg-white disabled:opacity-30" style={{ borderColor: "var(--ss-divider)" }}>Prev</button>
            <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1}
              className="text-[10px] uppercase font-bold px-2 py-1 border bg-white disabled:opacity-30" style={{ borderColor: "var(--ss-divider)" }}>Next</button>
          </div>
        </div>
      )}
    </div>
  );
}

function GenericTable({ rows, emptyMsg = "No data" }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="border p-8 text-center" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>{emptyMsg}</p>
      </div>
    );
  }
  const cols = Object.keys(rows[0]).slice(0, 10);
  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
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
      <div className="border p-8 text-center" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>No workload management data</p>
      </div>
    );
  }
  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
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
      <div className="border p-8 text-center" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <p className="text-sm" style={{ color: "var(--ss-mid-gray)" }}>No resource pool data</p>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
        <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Resource Pools (SHOW RESOURCE POOLS)
          </h3>
          <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
            Workload management resource pools are SingleStore's primary mechanism for isolating mixed workloads.
          </p>
        </div>
        <div className="p-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {pools.map((pool, i) => {
            const isDefault = (pool.Pool_Name || "").includes("default");
            const hasQueue = pool.Max_Queue_Depth && pool.Max_Queue_Depth !== "NULL" && pool.Max_Queue_Depth !== "0";
            return (
              <div key={i} className="border p-3" style={{ borderColor: "var(--ss-divider)" }} data-testid={`pool-${pool.Pool_Name}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-mono font-bold">{pool.Pool_Name}</span>
                  {isDefault && <span className="text-[9px] px-1 bg-zinc-100 text-zinc-500">DEFAULT</span>}
                </div>
                <div className="space-y-1 text-[10px] font-mono" style={{ color: "#525252" }}>
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
