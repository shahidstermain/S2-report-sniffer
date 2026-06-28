import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { getReportOverview, getReportNodes } from "@/lib/api";
import BackupTimeline from "./charts/BackupTimeline";
import LogSeverityChart from "./charts/LogSeverityChart";
import PressureEventsChart from "./charts/PressureEventsChart";
import NodeHealthChart from "./charts/NodeHealthChart";
import DatabaseDiskChart from "./charts/DatabaseDiskChart";

const CHART_LAYOUTS = [
  { id: "backup", component: BackupTimeline, span: "full", label: "Backup Timeline" },
  { id: "severity", component: LogSeverityChart, span: "half", label: "Log Severity" },
  { id: "pressure", component: PressureEventsChart, span: "half", label: "Storage Stress Events" },
  { id: "nodes", component: NodeHealthChart, span: "half", label: "Node Status" },
  { id: "disk", component: DatabaseDiskChart, span: "half", label: "Database Storage" },
];

export default function ChartsDashboard() {
  const { reportId } = useParams();
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await getReportOverview(reportId);
        setOverview(res.data);
      } catch {
        // error handled by parent
      } finally {
        setLoading(false);
      }
    })();
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

  // Gather all data sources
  const backupHistory = overview.backup_history || [];
  const backupSummary = overview.backup_summary || {};
  const logSummary = overview.log_summary || {};
  const pressureEvents = overview.pressure_events_per_hour || {};
  const clusterOverview = overview.cluster_overview || {};
  const databaseDiskUsage = overview.database_disk_usage || [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="mb-2">
        <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: "Chivo, sans-serif" }}>
          📈 Cluster Diagnostics
        </h2>
        <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
          Metrics from {overview.report_name || "this report"} — backup history, tracelog levels, storage, and node health
        </p>
      </div>

      {/* Full-width: Backup Timeline */}
      <BackupTimeline backupHistory={backupHistory} backupSummary={backupSummary} />

      {/* Two-column row: Log Severity + Pressure Events */}
      <div className="lg:grid lg:grid-cols-2 lg:gap-4 space-y-4 lg:space-y-0">
        <LogSeverityChart logSummary={logSummary} />
        <PressureEventsChart pressureEvents={pressureEvents} />
      </div>

      {/* Two-column row: Node Health + Database Disk */}
      <div className="lg:grid lg:grid-cols-2 lg:gap-4 space-y-4 lg:space-y-0">
        <NodeHealthChart clusterOverview={clusterOverview} />
        <DatabaseDiskChart databaseDiskUsage={databaseDiskUsage} />
      </div>
    </div>
  );
}
