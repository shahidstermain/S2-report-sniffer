export const METRIC_GLOSSARY = [
  {
    id: "cluster.health",
    title: "Finding severity / Cluster Health Score",
    source: "Backend recommendations and Sniffer risk scoring",
    basis: "Sniffer heuristic",
    meaning: "A compact severity score derived from findings. It is not an official SingleStore health verdict.",
    interpret: "Lower scores mean more or higher-severity findings. Unknown means the backend did not have enough evidence.",
    next: "Open Issues to review the evidence and recommended actions.",
  },
  {
    id: "overview.topology",
    title: "Topology",
    source: "MV_NODES, cluster status, and parser-normalized node details",
    basis: "Observed",
    meaning: "Shows aggregators, leaves, and node state distribution.",
    interpret: "Offline/degraded leaves and uneven layout increase investigation urgency.",
    next: "Open Nodes and Diagnostics to correlate state changes with events.",
  },
  {
    id: "overview.memory",
    title: "Memory pressure",
    source: "Host memory collectors and process/query memory snapshots",
    basis: "Sniffer heuristic",
    meaning: "Highlights cluster and per-node memory pressure.",
    interpret: "High memory plus long-running queries often points to workload or concurrency pressure.",
    next: "Open Queries and Query Tracer to inspect high-memory statements.",
  },
  {
    id: "overview.disk",
    title: "Disk usage and reclaimability",
    source: "Database disk usage, table storage, df output, and Disk Intelligence",
    basis: "Observed + Sniffer heuristic",
    meaning: "Shows storage pressure, skew, and estimated reclaimable space.",
    interpret: "High disk pressure with skew should be reviewed before capacity changes.",
    next: "Open Disk Intelligence and Storage.",
  },
  {
    id: "disk.mount_usage",
    title: "Mount used",
    source: "Filesystem usage collected from each SingleStore data-directory mount",
    basis: "Observed",
    meaning: "The bytes currently used on the filesystem, including table data and non-table files.",
    interpret: "A high percentage is a capacity warning, but it does not identify which files are safe to remove.",
    next: "Compare the highest-utilization nodes with the overhead breakdown and filesystem collector.",
  },
  {
    id: "disk.non_table_overhead",
    title: "Non-table disk overhead",
    source: "Mount-used bytes minus bytes attributed to database tables",
    basis: "Sniffer-derived estimate",
    meaning: "Groups transaction logs, snapshots, tracelogs, spill, cores, and unattributed files outside table storage.",
    interpret: "Large spill or snapshot buckets can explain pressure even when table growth is stable.",
    next: "Validate the largest bucket on the affected node before deleting or changing retention.",
  },
  {
    id: "disk.reclaimable",
    title: "Estimated reclaimable bytes",
    source: "On-disk columnstore blobs compared with HA-adjusted referenced bytes",
    basis: "Sniffer heuristic",
    meaning: "An investigation estimate of blob bytes not attributed to current table references.",
    interpret: "It is not a delete instruction and may be affected by redundancy or incomplete collectors.",
    next: "Confirm with current cluster state and SingleStore-supported maintenance procedures.",
  },
  {
    id: "disk.table_storage",
    title: "Table storage type",
    source: "information_schema.TABLES.STORAGE_TYPE",
    basis: "Observed",
    meaning: "Distinguishes columnstore (Universal Storage), in-memory rowstore, and unknown table types.",
    interpret: "Storage type changes memory and disk expectations; unknown values are never inferred.",
    next: "Review large rowstore tables and table growth alongside workload requirements.",
  },
  {
    id: "overview.backups",
    title: "Backup reliability",
    source: "Backup history and tracelog backup events",
    basis: "Observed",
    meaning: "Reports recent backup success/failure and duration signals.",
    interpret: "Failed or slow backups can indicate IO, network, or destination pressure.",
    next: "Search tracelogs for backup failures and check Config.",
  },
  {
    id: "queries.long_running",
    title: "Long-Running Queries",
    source: "SHOW PROCESSLIST / information_schema.PROCESSLIST / MV_PROCESSLIST snapshots",
    basis: "Sniffer heuristic",
    meaning: "Queries running beyond product-defined Sniffer elapsed-time thresholds.",
    interpret: "Long elapsed time is a triage signal, not proof of a bad query.",
    next: "Trace the query and correlate with locks, memory, and logs.",
  },
  {
    id: "logs.search",
    title: "Log Search",
    source: "Raw retained tracelogs when available; parsed logs fallback otherwise",
    basis: "Observed",
    meaning: "Searches tracelog messages such as ETIMEDOUT, fsync is behind, backup failed.",
    interpret: "Use actual tracelog text or patterns rather than checker IDs.",
    next: "Start from an Issue's suggested log search terms.",
  },
];

export function getMetricById(id) {
  return METRIC_GLOSSARY.find((item) => item.id === id) || null;
}

export function glossaryForPage(pageKey) {
  if (pageKey === "queries") return METRIC_GLOSSARY.filter((item) => item.id.includes("queries") || item.id.includes("memory"));
  if (pageKey === "logs" || pageKey === "log-search") return METRIC_GLOSSARY.filter((item) => item.id.includes("logs"));
  if (pageKey === "storage" || pageKey === "disk-intelligence") return METRIC_GLOSSARY.filter((item) => item.id.includes("disk"));
  return METRIC_GLOSSARY.slice(0, 5);
}
