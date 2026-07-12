/** Action guidance keyed by finding type. */
const ACTION_BY_FINDING_TYPE = {
  tracelog_errors:
    "Investigate ERROR/FATAL tracelog entries and critical patterns (e.g. OOM kills). Correlate with memory pressure and runaway queries before deeper changes.",
  tracelog_warnings:
    "Review elevated WARN volume on the hottest nodes. Identify the repeating warning pattern in memsql.log and address the underlying cause.",
  backup_reliability:
    "Verify backup freshness and restore points. Investigate failed or stale backups and confirm DR procedures.",
  query_performance:
    "Identify and mitigate runaway or long-running queries. Review workload management, locks, and query memory usage.",
  oom_kill:
    "Address OOM kills: tune maximum_memory, reduce memory-heavy workloads, and validate host RAM headroom.",
  memory_pressure:
    "Reduce engine/OS memory pressure. Validate maximum_memory settings against physical RAM on affected nodes.",
  partition_availability:
    "Restore partition master assignments and redundancy. Confirm offline or degraded nodes are recovered.",
  cluster_metadata:
    "Recover cluster_management and control-plane metadata. Verify cluster registration and metadata DB health.",
  config_anomaly:
    "Correct host or cluster configuration deviations (ulimits, sysctl, licensing) called out in the finding.",
  license_compliance:
    "Renew or validate the cluster license before operations are blocked.",
  replication_lag:
    "Investigate replication lag and sync→async transitions between replica pairs.",
  replication_stopped:
    "Restore stopped replication and review HA durability settings.",
  swap_usage:
    "Reduce swap usage and fix vm.overcommit/swappiness settings that cause latency spikes.",
  disk_latency:
    "Investigate disk latency and storage saturation on affected nodes.",
  partition_skew:
    "Rebalance partition skew and validate uniform distribution across leaves.",
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
  swapUsageDetected: "swap_usage",
  replicationLagCritical: "replication_lag",
  replicationLagDegraded: "replication_lag",
  asyncTransitionDetected: "replication_stopped",
  backupReliability: "backup_reliability",
  leavesNotOnline: "partition_availability",
};

export function humanizeCheckerId(checkerId) {
  if (!checkerId) return "Finding";
  return checkerId
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
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
