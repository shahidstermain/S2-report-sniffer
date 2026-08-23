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
