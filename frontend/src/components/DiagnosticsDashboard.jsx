import { useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { rehydrateDiagnostics } from "@/lib/api";
import InfoHint from "./InfoHint";
import { formatNumber } from "@/lib/utils-sdb";
import MvEventsTimeline from "./MvEventsTimeline";
import SysinfoNetworkPanel from "./SysinfoNetworkPanel";

const CHART_COLORS = ["#00d992", "#AA00FF", "#f59e0b", "#ef4444", "#3b82f6"];

function Section({ title, hint, children, testId }) {
  return (
    <Card data-testid={testId}>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-1">
          <CardTitle className="text-sm font-bold tracking-tight">{title}</CardTitle>
          {hint ? <InfoHint label={title} content={hint} /> : null}
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Empty({ text }) {
  return <p className="text-sm text-muted-foreground italic py-4">{text}</p>;
}

function MiniTable({ headers, rows, maxRows = 12 }) {
  if (!rows?.length) return <Empty text="No rows in this report snapshot." />;
  return (
    <div className="overflow-x-auto border" style={{ borderColor: "var(--ss-divider)" }}>
      <table className="w-full dense-table text-xs">
        <thead>
          <tr>{headers.map((h) => <th key={h} className="text-left">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, maxRows).map((row, i) => (
            <tr key={i}>
              {headers.map((h) => (
                <td key={h} className="font-mono max-w-[240px] truncate" title={String(row[h] ?? "")}>
                  {String(row[h] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DiagnosticsDashboard({ overview, reportId, onDiagnosticsUpdated }) {
  const dx = overview?.extended_diagnostics || {};
  const [rehydratePath, setRehydratePath] = useState("");
  const [rehydrating, setRehydrating] = useState(false);

  const compilation = dx.compilation_times || {};
  const heartbeat = dx.heartbeat_failures || {};
  const netstat = dx.netstat_summary || {};
  const pipelines = dx.pipeline_diagnostics || {};
  const skew = dx.table_skew || {};
  const logErrors = dx.log_error_timeline || {};
  const collectors = dx.collector_availability || overview?.collector_availability || {};

  const compilationChart = useMemo(
    () => (compilation.timeline || []).map((p) => ({
      hour: p.hour?.slice(5, 16) || p.hour,
      count: p.count,
      avgCompiled: p.avg_compiled_ms,
      avgQueued: p.avg_queued_ms,
    })),
    [compilation.timeline],
  );

  const errorChart = useMemo(
    () => (logErrors.timeline || []).map((p) => ({
      hour: p.hour?.slice(5, 16) || p.hour,
      total: p.total,
      error: p.error,
      fatal: p.fatal,
    })),
    [logErrors.timeline],
  );

  const heartbeatChart = useMemo(
    () => (heartbeat.timeline || []).map((p) => ({
      hour: p.hour?.slice(5, 16) || p.hour,
      count: p.count,
    })),
    [heartbeat.timeline],
  );

  const skewChart = useMemo(
    () => (skew.table_skew || []).slice(0, 15).map((t) => ({
      table: t.table?.length > 28 ? `${t.table.slice(0, 28)}…` : t.table,
      rowCv: t.row_skew_cv_pct,
      memCv: t.memory_skew_cv_pct,
    })),
    [skew.table_skew],
  );

  const hasPrimaryData = (
    (dx.mv_events_timeline?.total_count || 0) > 0
    || (dx.cpu_health?.per_node?.length || 0) > 0
    || (dx.sysinfo_network?.per_node?.length || 0) > 0
  );

  const hasPanelData = hasPrimaryData || (
    (compilation.sample_count || 0) > 0
    || (heartbeat.failure_count || 0) > 0
    || (logErrors.total_errors || 0) > 0
    || (skew.summary?.table_count || 0) > 0
    || (netstat.nodes_with_netstat || 0) > 0
    || (pipelines.error_count || 0) > 0
  );

  const parity = [
    { colleague: "Health Checks", s2rs: "Issues + Config + Overview coverage", status: "covered" },
    { colleague: "Compilation Times", s2rs: "Diagnostics → Compilation Performance", status: compilation.sample_count ? "covered" : "partial" },
    { colleague: "Pipeline Errors", s2rs: "Diagnostics → Pipeline Operations", status: pipelines.error_count ? "covered" : "partial" },
    { colleague: "Events", s2rs: "Diagnostics → MV_EVENTS scatter timeline", status: (dx.mv_events_timeline?.total_count || 0) > 0 ? "covered" : "partial" },
    { colleague: "Backups", s2rs: "Charts → Backup Timeline", status: "covered" },
    { colleague: "Network", s2rs: "Diagnostics → sysinfo-net + netstat", status: (netstat.nodes_with_netstat || dx.sysinfo_network?.per_node?.length) ? "covered" : "partial" },
    { colleague: "Connectivity", s2rs: "Diagnostics → Heartbeat failures", status: heartbeat.failure_count ? "covered" : "partial" },
    { colleague: "Nodes", s2rs: "Nodes → CPU cpulist health + topology", status: (dx.cpu_health?.per_node?.length || 0) > 0 ? "covered" : "partial" },
    { colleague: "Log Errors", s2rs: "Diagnostics → Error timeline + Log Explorer", status: logErrors.total_errors ? "covered" : "partial" },
    { colleague: "Process List", s2rs: "Queries → Processlist tab", status: "covered" },
    { colleague: "Table Data / Skew", s2rs: "Diagnostics → Table skew + Storage tables", status: skew.summary?.table_count ? "covered" : "partial" },
  ];

  return (
    <div className="space-y-4 animate-fade-in">
      <div>
        <div className="flex items-center gap-1">
          <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            Extended Diagnostics
          </h2>
          <InfoHint
            label="extended diagnostics"
            content="Panels aligned with the legacy SingleStore Support Dashboard (s2_dashboard): compilation latency, pipeline errors, netstat, heartbeat connectivity, table skew, and error-rate timelines — integrated with S2RS risk scoring and richer correlation."
          />
        </div>
        <p className="text-xs mt-1 text-muted-foreground">
          Colleague-dashboard parity with improved triage context. Snapshot data only — not live monitoring.
        </p>
        {!hasPrimaryData && overview?.status === "ready" && (
          <div className="text-xs mt-2 p-3 border rounded space-y-2" style={{ borderColor: "var(--ss-warning)", color: "var(--ss-warning)" }} data-testid="diagnostics-empty-hint">
            <p>
              MV_EVENTS, CPU, and network panels are empty. Open a report with the green Diagnostics badge on the list, or re-analyze from a bundle path below.
            </p>
            {(overview?.node_count || 0) === 0 && (
              <p className="opacity-90">
                This report has no cluster nodes (likely a test fixture). Import a real support bundle to populate diagnostics.
              </p>
            )}
            {reportId ? (
              <div className="flex flex-col sm:flex-row gap-2">
                <Input
                  value={rehydratePath}
                  onChange={(e) => setRehydratePath(e.target.value)}
                  placeholder="Path to extracted report folder or .tar.gz/.zip"
                  className="h-8 text-xs bg-background"
                  data-testid="diagnostics-rehydrate-path"
                />
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={rehydrating || !rehydratePath.trim()}
                  data-testid="diagnostics-rehydrate-btn"
                  onClick={async () => {
                    setRehydrating(true);
                    try {
                      await rehydrateDiagnostics(reportId, rehydratePath.trim());
                      toast.success("Diagnostics re-analyzed from bundle path.");
                      setRehydratePath("");
                      onDiagnosticsUpdated?.();
                    } catch (err) {
                      toast.error(err?.response?.data?.message || err?.response?.data?.error || "Re-analyze failed");
                    } finally {
                      setRehydrating(false);
                    }
                  }}
                >
                  {rehydrating ? "Analyzing…" : "Re-analyze"}
                </Button>
              </div>
            ) : null}
          </div>
        )}
      </div>

      <Section
        title="Dashboard parity map"
        hint="How each tab from the legacy s2_dashboard maps into Report Sniffer. Partial means the signal family exists but this report had no matching collector output."
        testId="diagnostics-parity-map"
      >
        <div className="overflow-x-auto border" style={{ borderColor: "var(--ss-divider)" }}>
          <table className="w-full dense-table text-xs">
            <thead>
              <tr>
                <th className="text-left">Legacy tab</th>
                <th className="text-left">Report Sniffer equivalent</th>
                <th className="text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {parity.map((row) => (
                <tr key={row.colleague}>
                  <td className="font-medium">{row.colleague}</td>
                  <td>{row.s2rs}</td>
                  <td>
                    <Badge variant={row.status === "covered" ? "healthy" : "warning"} className="text-[10px]">
                      {row.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <MvEventsTimeline timeline={dx.mv_events_timeline} />

      <SysinfoNetworkPanel network={dx.sysinfo_network} />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Section
          title="Compilation performance"
          hint="Async compile latency parsed from tracelog lines (submitted / queued / compiled milliseconds). Replaces the legacy Compilation Times tab."
          testId="diagnostics-compilation"
        >
          {compilation.sample_count > 0 ? (
            <>
              <div className="flex flex-wrap gap-3 mb-3 text-xs">
                <span>Samples: <strong>{formatNumber(compilation.sample_count)}</strong></span>
                <span>Max compiled: <strong>{compilation.max_compiled_ms} ms</strong></span>
                <span>Avg compiled: <strong>{compilation.avg_compiled_ms} ms</strong></span>
              </div>
              {compilationChart.length > 0 && (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={compilationChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="hour" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                    <Legend />
                    <Bar dataKey="count" name="Compilations/hr" fill={CHART_COLORS[0]} />
                    <Bar dataKey="avgCompiled" name="Avg compiled ms" fill={CHART_COLORS[1]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
              <MiniTable
                headers={["node", "timestamp", "compiled_ms", "queued_ms", "query_preview"]}
                rows={compilation.samples}
              />
            </>
          ) : (
            <Empty text="No async compilation timing lines found in tracelogs for this report." />
          )}
        </Section>

        <Section
          title="Log error rate"
          hint="Hourly ERROR/FATAL/CRITICAL counts from parsed tracelog index. Complements Log Explorer and Log Search."
          testId="diagnostics-log-errors"
        >
          {logErrors.total_errors > 0 ? (
            <>
              <p className="text-xs mb-3">Total error-level lines indexed: <strong>{formatNumber(logErrors.total_errors)}</strong></p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={errorChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="hour" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                  <Bar dataKey="total" name="Errors/hr" fill={CHART_COLORS[3]} />
                </BarChart>
              </ResponsiveContainer>
            </>
          ) : (
            <Empty text="No ERROR/FATAL tracelog entries in the parsed log window." />
          )}
        </Section>

        <Section
          title="Heartbeat connectivity"
          hint="HeartbeatConnectionFailure and ProcessNetworkEvents heartbeat errors from tracelogs. Legacy Connectivity tab equivalent."
          testId="diagnostics-heartbeat"
        >
          {heartbeat.failure_count > 0 ? (
            <>
              <p className="text-xs mb-3">
                Failures: <strong>{heartbeat.failure_count}</strong>
                {heartbeat.nodes_affected?.length ? ` across ${heartbeat.nodes_affected.length} node(s)` : ""}
              </p>
              {heartbeatChart.length > 0 && (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={heartbeatChart}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="hour" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                    <Bar dataKey="count" fill={CHART_COLORS[4]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
              <MiniTable headers={["node", "timestamp", "failure_type"]} rows={heartbeat.failures} />
            </>
          ) : (
            <Empty text="No heartbeat connectivity failures detected in tracelogs." />
          )}
        </Section>

        <Section
          title="Netstat TCP health"
          hint="Per-node netstat_stdout metrics with threshold breach flags. Legacy Network tab (netstat section)."
          testId="diagnostics-netstat"
        >
          {netstat.nodes_with_netstat > 0 ? (
            <>
              <p className="text-xs mb-3">Nodes with netstat data: <strong>{netstat.nodes_with_netstat}</strong></p>
              <MiniTable
                headers={["node", "breach_count"]}
                rows={(netstat.per_node || []).map((n) => ({ node: n.node, breach_count: n.breach_count }))}
              />
            </>
          ) : (
            <Empty text="No netstat_stdout collectors found in this bundle." />
          )}
        </Section>

        <Section
          title="Pipeline operations"
          hint="Pipeline error and batch TSV collectors from informationSchemaPipelines. Legacy Pipeline Errors tab."
          testId="diagnostics-pipelines"
        >
          {pipelines.error_count || pipelines.batch_count ? (
            <>
              <p className="text-xs mb-3">
                Errors: <strong>{pipelines.error_count || 0}</strong> · Batches: <strong>{pipelines.batch_count || 0}</strong>
              </p>
              <MiniTable
                headers={["node", "PIPELINE_NAME", "ERROR_TIME", "ERROR_CODE", "ERROR_MESSAGE"]}
                rows={(pipelines.errors || []).map((r) => ({
                  node: r.node,
                  PIPELINE_NAME: r.PIPELINE_NAME || r.pipeline_name,
                  ERROR_TIME: r.ERROR_TIME || r.error_time,
                  ERROR_CODE: r.ERROR_CODE || r.error_code,
                  ERROR_MESSAGE: (r.ERROR_MESSAGE || r.error_message || "").slice(0, 120),
                }))}
              />
            </>
          ) : (
            <Empty text="No pipeline error or batch TSV files in this report." />
          )}
        </Section>

        <Section
          title="Table skew analytics"
          hint="Row and memory coefficient-of-variation (CV) across partitions per table. CV ≥ 50% indicates high skew. Legacy Table Data tab."
          testId="diagnostics-skew"
        >
          {skew.summary?.table_count > 0 ? (
            <>
              <div className="flex flex-wrap gap-3 mb-3 text-xs">
                <span>Tables: <strong>{skew.summary.table_count}</strong></span>
                <span>High row skew: <strong>{skew.summary.high_row_skew_tables}</strong></span>
                <span>High memory skew: <strong>{skew.summary.high_memory_skew_tables}</strong></span>
                {skew.summary.idle_leaf_hosts > 0 && (
                  <span className="status-warning">
                    Idle leaves: <strong>{skew.summary.idle_leaf_hosts}</strong>
                  </span>
                )}
              </div>
              {skewChart.length > 0 && (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={skewChart} layout="vertical" margin={{ left: 80 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis type="number" tick={{ fontSize: 10 }} />
                    <YAxis type="category" dataKey="table" tick={{ fontSize: 9 }} width={80} />
                    <Tooltip contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }} />
                    <Legend />
                    <Bar dataKey="rowCv" name="Row CV %" fill={CHART_COLORS[0]} />
                    <Bar dataKey="memCv" name="Memory CV %" fill={CHART_COLORS[1]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
              <MiniTable
                headers={["table", "row_skew_cv_pct", "memory_skew_cv_pct", "partition_count", "total_rows"]}
                rows={skew.table_skew}
              />
            </>
          ) : (
            <Empty text="No table statistics available for skew analysis." />
          )}
        </Section>
      </div>

      {collectors?.dmesg && (
        <Section
          title="Collector availability"
          hint="Whether optional collectors were present in the bundle. Missing dmesg stdout does not mean a healthy kernel — only that the signal was not collected."
          testId="diagnostics-collectors"
        >
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="border p-3" style={{ borderColor: "var(--ss-divider)" }}>
              <div className="text-muted-foreground">Nodes</div>
              <div className="text-lg font-bold">{collectors.dmesg.nodes_total}</div>
            </div>
            <div className="border p-3" style={{ borderColor: "var(--ss-divider)" }}>
              <div className="text-muted-foreground">dmesg stdout</div>
              <div className="text-lg font-bold">{collectors.dmesg.stdout_available}</div>
            </div>
            <div className="border p-3" style={{ borderColor: "var(--ss-divider)" }}>
              <div className="text-muted-foreground">stderr only</div>
              <div className="text-lg font-bold">{collectors.dmesg.stderr_only}</div>
            </div>
            <div className="border p-3" style={{ borderColor: "var(--ss-divider)" }}>
              <div className="text-muted-foreground">unavailable</div>
              <div className="text-lg font-bold">{collectors.dmesg.unavailable}</div>
            </div>
          </div>
        </Section>
      )}
    </div>
  );
}
