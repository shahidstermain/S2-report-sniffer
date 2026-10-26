export const REPORT_LIST_TOUR = [
  {
    id: "upload",
    target: "reports.upload",
    title: "Upload or drop a Cluster Report",
    body: "Upload a SingleStore Cluster Report archive to start local parsing and analysis.",
  },
  {
    id: "kpis",
    target: "reports.kpis",
    title: "Workspace KPIs",
    body: "These summarize the Cluster Reports currently stored in this local workspace.",
  },
  {
    id: "compare",
    target: "reports.compare",
    title: "Compare snapshots",
    body: "Select two ready reports to compare new, resolved, and changed findings.",
  },
  {
    id: "table",
    target: "reports.table",
    title: "Open a report",
    body: "Each ready Cluster Report opens its analysis dashboard.",
  },
];

export const DASHBOARD_TOUR = [
  {
    id: "summary",
    target: "dashboard.summary",
    title: "Report summary",
    body: "This area shows backend-owned health score, topology, package type, deployment inference, and privacy state.",
  },
  {
    id: "tabs",
    target: "dashboard.tabs",
    title: "Feature navigation",
    body: "Move through Overview, Disk Intelligence, Charts, Diagnostics, Nodes, Storage, Queries, Logs, Config, and Issues.",
  },
  {
    id: "overview",
    target: "dashboard.content",
    tabId: "overview",
    title: "Overview",
    body: "Start here for node count, topology, memory, disk, backups, query pressure, and the high-level investigation story.",
  },
  {
    id: "disk",
    target: "dashboard.content",
    tabId: "disk-intelligence",
    title: "Disk Intelligence",
    body: "Shows mount usage, table bytes, spill/snapshot overhead, and HA-adjusted blob estimates. Estimates are never delete instructions.",
  },
  {
    id: "queries",
    target: "dashboard.content",
    tabId: "queries",
    title: "Queries and tracing",
    body: "Use processlist snapshots and Query Tracer to inspect long-running statements, memory use, locks, and activity.",
  },
  {
    id: "logs",
    target: "dashboard.content",
    tabId: "log-search",
    title: "Log Search",
    body: "Search actual tracelog terms such as ETIMEDOUT, fsync is behind, and backup failed. Raw search is used when retained extracts exist.",
  },
  {
    id: "issues",
    target: "dashboard.content",
    tabId: "recommendations",
    title: "Issues and recommendations",
    body: "Findings are grounded with observed/documented/heuristic basis and provide next-step investigation links.",
  },
  {
    id: "exports",
    target: "dashboard.exports",
    title: "Exports",
    body: "Save Markdown/HTML or use Analyze in Glean from Issues. Export actions stay local until the user shares a file elsewhere.",
  },
];

export function tourForPath(pathname) {
  if (pathname.includes("/report/")) return DASHBOARD_TOUR;
  return REPORT_LIST_TOUR;
}

export function availableTourSteps(steps, isTabAvailable) {
  return steps.filter((step) => (
    !step.tabId || isTabAvailable(step.tabId)
  ));
}

export function pageKeyFromPath(pathname) {
  if (!pathname.includes("/report/")) return "reports";
  const parts = pathname.split("/").filter(Boolean);
  const reportIndex = parts.indexOf("report");
  return parts[reportIndex + 2] || "overview";
}
