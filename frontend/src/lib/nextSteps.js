/** Action guidance keyed by finding type. */
const ACTION_BY_FINDING_TYPE = {
  tracelog_errors:
    "Investigate ERROR/FATAL tracelog entries and critical patterns (e.g. OOM kills). Correlate with memory pressure and long-running queries before deeper changes.",
  tracelog_warnings:
    "Review elevated WARN volume on the hottest nodes. Identify the repeating warning pattern in memsql.log and address the underlying cause.",
  backup_reliability:
    "Verify backup freshness and restore points. Investigate failed or stale backups and confirm DR procedures.",
  query_performance:
    "Identify and mitigate long-running queries. Review workload management, locks, and query memory usage.",
  oom_kill:
    "Address OOM kills: tune maximum_memory, reduce memory-heavy workloads, and validate host RAM headroom.",
  memory_pressure:
    "Reduce node memory pressure vs maximum_memory and host RAM. Validate maximum_memory settings against physical RAM on affected nodes.",
  partition_availability:
    "Restore partition primary assignments and redundancy. Confirm offline or degraded nodes are recovered.",
  cluster_metadata:
    "Recover the 'cluster' system database and control-plane metadata. Verify cluster registration and metadata DB health.",
  config_anomaly:
    "Correct host or cluster configuration deviations (ulimits, sysctl, licensing) called out in the finding.",
  license_compliance:
    "Renew or validate the cluster license before operations are blocked.",
  replication_lag:
    "Investigate replica lag and synchronous→asynchronous transitions between replica pairs.",
  swap_usage:
    "Reduce swap usage and fix vm.overcommit/swappiness settings that cause latency spikes.",
  disk_latency:
    "Investigate disk I/O latency and storage saturation on affected nodes.",
  partition_skew:
    "Rebalance uneven partition distribution and validate uniform layout across leaves.",
  topology_mismatch:
    "Repair cluster topology mismatches and confirm node roles match expected layout.",
  version_inconsistency:
    "Align mixed node versions and plan a controlled upgrade to a single release.",
  orphan_databases:
    "Clean up orphan databases/tables and validate metadata consistency.",
};

const SEVERITY_STYLES = {
  critical: { color: "#F44336", bg: "rgba(244, 67, 54, 0.1)" },
  warning: { color: "#FF9800", bg: "rgba(255, 149, 0, 0.1)" },
  high: { color: "#FF9800", bg: "rgba(255, 149, 0, 0.1)" },
  info: { color: "#2196F3", bg: "rgba(33, 150, 243, 0.1)" },
};

const CHECKER_TO_FINDING_TYPE = {
  runawayQueries: "query_performance",
  slowQueries: "query_performance",
  tracelogOOM: "oom_kill",
  dmesgOOMKill: "oom_kill",
  memoryUtilizationCritical: "memory_pressure",
  memoryUtilizationWarning: "memory_pressure",
  maxMemorySettings: "memory_pressure",
  missingClusterDb: "cluster_metadata",
  swapUsageDetected: "swap_usage",
  replicationLagCritical: "replication_lag",
  replicationLagDegraded: "replication_lag",
  asyncTransitionDetected: "replication_lag",
  backupReliability: "backup_reliability",
  leavesNotOnline: "partition_availability",
};

/** Docs-aligned display names for checker IDs (API IDs stay unchanged). */
const CHECKER_ID_DISPLAY_NAMES = {
  runawayQueries: "Long-Running Queries",
  slowQueries: "Queries Exceeding Sniffer Elapsed Threshold",
  longRunningQueries: "Long-Running Queries",
  longRunningTransactions: "Long-Running Transactions",
  reclamationStalled: "Columnstore Blob Residue With Pressure",
  usedClusterCapacity: "Licensed Memory Capacity Utilization",
  clusterMemoryUsage: "Cluster Memory Utilization",
  clusterLayoutImbalance: "Uneven Partition Distribution",
  asyncTransitionDetected: "Synchronous To Asynchronous Transition",
  maxMemorySettings: "maximum_memory Settings",
};

/** Docs-aligned labels for query-tracer types (API values stay unchanged). */
const TRACE_TYPE_DISPLAY_NAMES = {
  runaway: "Long-running",
  runaway_query: "Long-running query",
  slow: "Slow",
  lock_wait: "Lock wait",
};

export function humanizeCheckerId(checkerId) {
  if (!checkerId) return "Finding";
  if (CHECKER_ID_DISPLAY_NAMES[checkerId]) {
    return CHECKER_ID_DISPLAY_NAMES[checkerId];
  }
  return checkerId
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Prefer SingleStore docs vocabulary over internal "runaway" wording. */
export function humanizeTraceType(traceType) {
  if (!traceType) return "";
  const key = String(traceType).trim().toLowerCase();
  if (TRACE_TYPE_DISPLAY_NAMES[key]) {
    return TRACE_TYPE_DISPLAY_NAMES[key];
  }
  return String(traceType).replace(/_/g, " ");
}

/** Rewrite legacy user-facing titles that still say "Runaway …". */
export function normalizeFindingTitle(title, checkerId = "") {
  const text = String(title || "");
  if (!text) {
    return checkerId ? humanizeCheckerId(checkerId) : "";
  }
  if (/runaway/i.test(text) || checkerId === "runawayQueries") {
    return text
      .replace(/\bRunaway queries\b/gi, "Long-running queries")
      .replace(/\bRunaway query\b/gi, "Long-running query")
      .replace(/\brunaway\b/gi, "long-running");
  }
  return text;
}

export function buildFindingsLookup(findings) {
  const lookup = {};
  for (const finding of findings || []) {
    const id = finding.checker_id || finding.check_id || finding.id;
    if (id) lookup[id] = finding;
  }
  return lookup;
}

function resolveFindingType(finding) {
  if (finding?.type && finding.type !== "unknown") return finding.type;
  const checkerId = finding?.checker_id || finding?.check_id || finding?.id || "";
  if (CHECKER_TO_FINDING_TYPE[checkerId]) return CHECKER_TO_FINDING_TYPE[checkerId];
  const category = String(finding?.category || "").toLowerCase();
  if (category.includes("memory")) return "memory_pressure";
  if (category.includes("query")) return "query_performance";
  if (category.includes("replication")) return "replication_lag";
  if (category.includes("backup")) return "backup_reliability";
  if (category.includes("storage") || category.includes("disk")) return "disk_latency";
  return "config_anomaly";
}

/**
 * Build a priority-ordered next-steps list directly from findings.
 */
export function buildSuggestedNextSteps(findings = []) {
  const ranked = [...(findings || [])].sort((a, b) => {
    const rank = { critical: 0, warning: 1, high: 1, info: 2 };
    return (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3);
  });

  return ranked.slice(0, 8).map((finding, index) => {
    const findingType = resolveFindingType(finding);
    const findingId = finding.checker_id || finding.check_id || finding.id || findingType;
    return {
      priority: index + 1,
      findingId,
      findingType,
      severity: finding.severity || "info",
      title: finding.title || humanizeCheckerId(findingId),
      action:
        ACTION_BY_FINDING_TYPE[findingType]
        || `Investigate ${humanizeCheckerId(findingId)} signals from this report.`,
      version: finding.version || "",
    };
  });
}

export function severityStyle(severity) {
  return SEVERITY_STYLES[severity] || SEVERITY_STYLES.info;
}
