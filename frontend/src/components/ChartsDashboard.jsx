import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { getReportOverview } from "@/lib/api";
import BackupTimeline from "./charts/BackupTimeline";
import LogSeverityChart from "./charts/LogSeverityChart";
import PressureEventsChart from "./charts/PressureEventsChart";
import MemoryUtilizationChart from "./charts/MemoryUtilizationChart";
import NodeHealthChart from "./charts/NodeHealthChart";
import DatabaseDiskChart from "./charts/DatabaseDiskChart";
import InfoHint from "./InfoHint";
import { asRowList } from "@/lib/utils";

export default function ChartsDashboard() {
  const { reportId } = useParams();
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // Clear prior report charts immediately so a slow fetch cannot paint report A under report B.
    setLoading(true);
    setOverview(null);
    (async () => {
      try {
        const res = await getReportOverview(reportId);
        if (!cancelled) setOverview(res.data);
      } catch {
        // Leave overview null; loading ends below.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  if (loading) {
    return (
      <div className="surface-card p-8 text-center">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading charts...</p>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="surface-card p-8 text-center">
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>No data available for charts.</p>
      </div>
    );
  }

  // Coerce table fields that may arrive as { rows: [...] } objects.
  const backupHistory = asRowList(overview.backup_history);
  const backupSummary = overview.backup_summary || {};
  const logSummary = overview.log_summary || {};
  const pressureEvents = overview.pressure_events_per_hour || {};
  const memoryUtilization = overview.memory_utilization || {};
  const clusterOverview = {
    ...(overview.cluster_overview || {}),
    nodes_detail: asRowList(overview.cluster_overview?.nodes_detail),
  };
  const databaseDiskUsage = asRowList(overview.database_disk_usage);

  return (
    <div className="space-y-4">
      <div className="mb-2">
        <div className="flex items-center gap-1">
          <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
            📈 Cluster Diagnostics
          </h2>
          <InfoHint label="cluster diagnostics charts" content="Visual summaries generated from parsed backup history, tracelog severity, pressure events, node state, storage, and memory data." />
        </div>
        <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
          Metrics from {overview.report_name || "this report"} — backup history, tracelog levels, storage, and node health
        </p>
      </div>

      <BackupTimeline backupHistory={backupHistory} backupSummary={backupSummary} />

      <div className="lg:grid lg:grid-cols-2 lg:gap-4 space-y-4 lg:space-y-0">
        <LogSeverityChart logSummary={logSummary} />
        <PressureEventsChart pressureEvents={pressureEvents} />
      </div>

      <div className="lg:grid lg:grid-cols-2 lg:gap-4 space-y-4 lg:space-y-0">
        <NodeHealthChart clusterOverview={clusterOverview} />
        <DatabaseDiskChart databaseDiskUsage={databaseDiskUsage} />
      </div>

      <MemoryUtilizationChart memoryUtilization={memoryUtilization} nodeCount={overview.node_count} />
    </div>
  );
}
