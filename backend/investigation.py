"""Incident-cluster helpers and Glean handoff packet builder."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Finding helpers (canonical finding types for RCA)
# ---------------------------------------------------------------------------

CHECKER_ID_TO_FINDING_TYPE: dict[str, str] = {
    "backupHistory": "backup_reliability",
    "backupReliability": "backup_reliability",
    "runningBackup": "backup_reliability",
    "runawayQueries": "query_performance",
    "slowQueries": "query_performance",
    "longRunningQueries": "query_performance",
    "repeatedQueryPatterns": "query_performance",
    "highQueryMemoryUsage": "query_performance",
    "highActiveQueryCount": "query_performance",
    "sleepingOpenTransactions": "query_performance",
    "blockedQueries": "query_performance",
    "queuedQueries": "query_performance",
    "unkillableQueries": "query_performance",
    "longRunningTransactions": "query_performance",
    "lockContention": "query_performance",
    "severeLockContention": "query_performance",
    "unkillableTransaction": "query_performance",
    "tracelogOOM": "oom_kill",
    "dmesgOOMKill": "oom_kill",
    "unmappedMasterPartitions": "partition_availability",
    "userDatabaseRedundancy": "partition_availability",
    "partitionsConsistency": "partition_availability",
    "duplicatePartitionDatabase": "partition_availability",
    "clusterLayoutImbalance": "partition_availability",
    "explainRebalancePartitionsChecker": "partition_availability",
    "missingClusterDb": "cluster_metadata",
    "orphanDatabases": "orphan_databases",
    "orphanTables": "orphan_databases",
    "secondaryDatabases": "cluster_metadata",
    "validLicense": "license_compliance",
    "maxMemorySettings": "memory_pressure",
    "consistentMaxMemory": "memory_pressure",
    "clusterMemoryUsage": "memory_pressure",
    "memoryUtilizationCritical": "memory_pressure",
    "memoryUtilizationWarning": "memory_pressure",
    "memoryCommitted": "memory_pressure",
    "mallocActiveMemory": "memory_pressure",
    "swapEnabled": "swap_usage",
    "swapUsage": "swap_usage",
    "swapUsageDetected": "swap_usage",
    "vmOvercommit": "swap_usage",
    "vmSwappiness": "swap_usage",
    "replicationLag": "replication_lag",
    "replicationLagDegraded": "replication_lag",
    "replicationLagCritical": "replication_lag",
    "asyncTransitionDetected": "replication_stopped",
    "replicationPausedDatabases": "replication_stopped",
    "disconnectedReplicationSlaves": "replication_stopped",
    "diskLatencyRead": "disk_latency",
    "diskLatencyWrite": "disk_latency",
    "diskUsage": "disk_latency",
    "diskBandwidth": "disk_latency",
    "usedClusterCapacity": "disk_latency",
    "pipelineErrorAnalysis": "query_performance",
    "leavesNotOnline": "partition_availability",
    "offlineAggregators": "partition_availability",
    "firewallPortBlocking": "topology_mismatch",
    "tracelogErrors": "tracelog_errors",
    "tracelogWarnings": "tracelog_warnings",
}

CATEGORY_TO_FINDING_TYPE: dict[str, str] = {
    "backup": "backup_reliability",
    "query": "query_performance",
    "memory": "memory_pressure",
    "replication": "replication_lag",
    "storage": "disk_latency",
    "partition": "partition_availability",
    "availability": "partition_availability",
    "configuration": "config_anomaly",
    "license": "license_compliance",
    "logs": "tracelog_errors",
}


def resolve_finding_type(
    checker_id: str = "",
    category: str = "",
    title: str = "",
    provided_type: str = "",
) -> str:
    """Resolve a finding-type key from checker metadata."""
    if provided_type and provided_type != "unknown" and provided_type != "config_anomaly":
        return provided_type
    if checker_id and checker_id in CHECKER_ID_TO_FINDING_TYPE:
        return CHECKER_ID_TO_FINDING_TYPE[checker_id]
    category_key = (category or "").strip().lower()
    if category_key and category_key in CATEGORY_TO_FINDING_TYPE:
        return CATEGORY_TO_FINDING_TYPE[category_key]

    haystack = f"{checker_id} {title}".lower()
    heuristics = (
        ("replication", "replication_lag"),
        ("replica", "replication_lag"),
        ("backup", "backup_reliability"),
        ("oom", "oom_kill"),
        ("memory", "memory_pressure"),
        ("swap", "swap_usage"),
        ("disk", "disk_latency"),
        ("partition", "partition_availability"),
        ("query", "query_performance"),
        ("license", "license_compliance"),
        ("topology", "topology_mismatch"),
        ("version", "version_inconsistency"),
        ("orphan", "orphan_databases"),
    )
    for needle, finding_type in heuristics:
        if needle in haystack:
            return finding_type
    return "config_anomaly"


@dataclass
class Evidence:
    """Evidence supporting a finding."""
    collector: str
    node: str | None = None
    metric: str | None = None
    value: str | None = None
    raw_snippet: str | None = None


@dataclass
class Finding:
    """Canonical finding structure."""
    id: str
    type: str
    severity: str
    title: str
    summary: str
    evidence: list[Evidence]
    keywords: list[str]
    affected_nodes: list[str]
    version: str
    time_range: dict[str, str] | None = None


def parse_finding_evidence(raw: Any) -> list[Evidence]:
    """Normalize heterogeneous evidence payloads from superchecker/UI."""
    if isinstance(raw, list):
        evidence_objs: list[Evidence] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            evidence_objs.append(
                Evidence(
                    collector=item.get("collector", "superchecker"),
                    node=item.get("node"),
                    metric=item.get("metric"),
                    value=str(item.get("value")) if item.get("value") is not None else None,
                    raw_snippet=item.get("raw_snippet"),
                )
            )
        return evidence_objs
    if isinstance(raw, str) and raw.strip():
        return [Evidence(collector="superchecker", raw_snippet=raw.strip())]
    return []


def build_finding_keywords(raw: dict[str, Any]) -> list[str]:
    """Build keywords from checker metadata."""
    keywords: list[str] = []
    checker_id = raw.get("checker_id") or raw.get("check_id") or ""
    if checker_id:
        keywords.append(checker_id)
    category = raw.get("category") or ""
    if category:
        keywords.append(category.lower())
    title = raw.get("title") or ""
    for word in title.lower().split():
        if len(word) > 3:
            keywords.append(word)
    deduped: list[str] = []
    for keyword in keywords:
        if keyword not in deduped:
            deduped.append(keyword)
    return deduped[:10]


def finding_from_payload(raw: dict[str, Any], report_metadata: dict[str, Any] | None = None) -> Finding:
    """Convert a superchecker recommendation or UI payload into a canonical Finding."""
    report_metadata = report_metadata or {}
    checker_id = raw.get("checker_id") or raw.get("check_id") or ""
    finding_id = checker_id or raw.get("id") or ""
    title = raw.get("title") or checker_id or "finding"
    summary = raw.get("summary") or raw.get("description") or raw.get("message") or ""
    affected_nodes = raw.get("affected_nodes") or raw.get("nodes") or []
    if not isinstance(affected_nodes, list):
        affected_nodes = [str(affected_nodes)]

    return Finding(
        id=finding_id,
        type=resolve_finding_type(
            checker_id=checker_id,
            category=raw.get("category", ""),
            title=title,
            provided_type=raw.get("type", ""),
        ),
        severity=raw.get("severity", "info"),
        title=title,
        summary=summary,
        evidence=parse_finding_evidence(raw.get("evidence")),
        keywords=raw.get("keywords") or build_finding_keywords(raw),
        affected_nodes=[str(node) for node in affected_nodes if node],
        version=raw.get("version") or report_metadata.get("version", ""),
        time_range=raw.get("time_range"),
    )


def dedupe_preserve_order(items: list[str]) -> list[str]:
    """Dedup while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = (item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


_CHECKER_ID_DISPLAY_NAMES = {
    "runawayQueries": "long-running queries",
    "longRunningQueries": "long-running queries",
    "longRunningTransactions": "long-running transactions",
}


def humanize_checker_id(checker_id: str) -> str:
    """Turn camelCase checker ids into readable terms (docs vocabulary)."""
    if not checker_id:
        return ""
    if checker_id in _CHECKER_ID_DISPLAY_NAMES:
        return _CHECKER_ID_DISPLAY_NAMES[checker_id]
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", checker_id)
    spaced = spaced.replace("_", " ")
    return spaced.lower()


def normalize_finding_title(title: str | None, checker_id: str = "") -> str:
    """Rewrite legacy 'Runaway …' titles to docs-aligned 'Long-running …'."""
    text = str(title or "")
    if not text:
        return humanize_checker_id(checker_id) if checker_id else ""
    if "runaway" in text.lower() or checker_id == "runawayQueries":
        text = re.sub(r"\bRunaway queries\b", "Long-running queries", text, flags=re.I)
        text = re.sub(r"\bRunaway query\b", "Long-running query", text, flags=re.I)
        text = re.sub(r"\brunaway\b", "long-running", text, flags=re.I)
    return text



# Dominant tag → cluster investigation theme
TAG_TO_THEME: dict[str, str] = {
    "memory": "memory",
    "replication": "replication",
    "availability": "availability",
    "performance": "query",
    "storage": "storage",
    "backup": "backup",
    "environment": "availability",
    "os-config": "memory",
    "configuration": "config",
    "logs": "logs",
}

THEME_TO_PLAYBOOK: dict[str, str] = {
    "memory": "memory_pressure",
    "replication": "replication_lag",
    "availability": "partition_availability",
    "query": "query_performance",
    "storage": "disk_latency",
    "backup": "backup_reliability",
    "config": "config_anomaly",
    "logs": "tracelog_errors",
}

# Additional checker_id mappings for investigation playbooks
EXTRA_CHECKER_MAPPINGS: dict[str, str] = {
    "transparentHugepage": "memory_pressure",
    "vmMaxMapCount": "memory_pressure",
    "maxMapCount": "memory_pressure",
    "cgroupMemoryUsage": "memory_pressure",
    "attachRebalanceDelay": "config_anomaly",
    "autoAttach": "config_anomaly",
    "failureDetectionOn": "config_anomaly",
    "vmSwappinessHigh": "swap_usage",
    "minFreeKbytes": "memory_pressure",
    "cpuMemoryBandwidth": "memory_pressure",
    "majorPageFaults": "memory_pressure",
    "pressureEvents_etimedout": "partition_availability",
    "pressureEvents_fsync": "disk_latency",
    "pressureEvents_retry_stall": "query_performance",
    "pressureEvents_async_transition": "replication_stopped",
    "memsqlVersions": "version_inconsistency",
    "versionHashes": "version_inconsistency",
    "kernelVersions": "version_inconsistency",
    "numaConfiguration": "config_anomaly",
    "chronydDisabled": "config_anomaly",
    "cpuIdle": "config_anomaly",
    "workloadThrottleDetected": "query_performance",
    "dmesgCollectorUnavailable": "config_anomaly",
    "collectionErrors": "config_anomaly",
    "logCoverageGap": "tracelog_warnings",
    "readyQueueSaturated": "query_performance",
    "delayedThreadLaunches": "query_performance",
    "syncCnfVariables": "config_anomaly",
    "cgroupDisabled": "config_anomaly",
    "explainRebalancePartitionsChecker": "partition_skew",
}


def apply_extra_checker_mappings() -> None:
    """Merge supplemental checker mappings into the global registry."""
    CHECKER_ID_TO_FINDING_TYPE.update(EXTRA_CHECKER_MAPPINGS)


apply_extra_checker_mappings()


@dataclass
class InvestigationBundle:
    """Compact context package for cluster-centric investigation helpers."""

    report_id: str
    cluster_id: str
    theme: str
    playbook_key: str
    root_cause_checker_id: str
    root_cause_title: str
    symptom_summary: str
    affected_nodes: list[str]
    version: str
    time_range: dict[str, str] | None
    findings: list[Finding]
    report_signals: dict[str, Any]
    member_checker_ids: list[str] = field(default_factory=list)
    log_context: dict[str, Any] = field(default_factory=dict)


def resolve_cluster_theme(tags: list[str], root_cause_checker_id: str = "") -> str:
    """Pick investigation theme; declared root cause takes precedence over cluster tags."""
    if root_cause_checker_id:
        playbook = resolve_finding_type(checker_id=root_cause_checker_id)
        for theme, key in THEME_TO_PLAYBOOK.items():
            if key == playbook:
                return theme
    for tag in tags or []:
        theme = TAG_TO_THEME.get(str(tag).lower())
        if theme:
            return theme
    return "config"


def normalize_export_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize superchecker Export JSON into the shape investigation helpers expect.

    Export JSON (Recommendations → Export JSON) nests incident_clusters under
    ``triage``; stored report payloads may use top-level ``incident_clusters``.
    """
    if not payload:
        return {}
    normalized = dict(payload)
    triage = payload.get("triage") or {}
    if isinstance(triage, dict):
        if triage.get("incident_clusters") and not normalized.get("incident_clusters"):
            normalized["incident_clusters"] = triage["incident_clusters"]
        if triage.get("report_id") and not normalized.get("report_id"):
            normalized["report_id"] = triage["report_id"]
        if triage.get("report_name") and not normalized.get("report_name"):
            normalized["report_name"] = triage["report_name"]
        if triage.get("summary") and not normalized.get("triage_summary"):
            normalized["triage_summary"] = triage["summary"]
        if triage.get("health_score") and not normalized.get("health_score"):
            normalized["health_score"] = triage["health_score"]
        if triage.get("health_grade") and not normalized.get("health_grade"):
            normalized["health_grade"] = triage["health_grade"]
    return normalized


TAG_TO_LOG_CATEGORIES: dict[str, set[str]] = {
    "memory": {"oom"},
    "replication": {"replication"},
    "storage": {"storage", "disk"},
    "availability": {"crash", "restart", "network"},
    "performance": {"background_tasks", "locking", "compilation"},
    "backup": {"backup"},
    "logs": set(),
}

# SingleStore memsql.log phrases (self-managed clusters), most-specific first.
# Grounded in: Identifying and Reducing Memory Usage, disk/replication troubleshooting KBs.
TRACELOG_PHRASES: tuple[str, ...] = (
    "Nonfatal buffer manager memory allocation failure",
    "Failed to allocate",
    "Memory usage by SingleStore for tables",
    "Exiting query retry due to non-retryable",
    "failed to finalize asynchronous compilation",
    "Retry loop is stalling",
    "stalling retry loop",
    "Blob fsync is behind",
    "fsync is behind",
    "slow fsync",
    "Transitioned from sync to async",
    "from sync to async",
    "replication link down",
    "replication error",
    "compilation failed",
    "compilation error",
    "lock wait timeout",
    "lock timeout exceeded",
    "backup failed",
    "backup error",
    "no space left",
    "disk full",
    "failed to merge",
    "segmentation fault",
    "assert failed",
    "SIGSEGV",
    "Out of memory: Kill process",
    "Killed process",
    "starting up, version",
    "memsqld started",
    "Connection timed out",
    "ETIMEDOUT",
)

# Dynamic pressureEvents_* checker ids (see superchecker._check_network_storage_pressure).
PRESSURE_EVENT_KEYWORDS: dict[str, list[str]] = {
    "etimedout": ["ETIMEDOUT"],
    "fsync_behind": ["fsync is behind"],
    "retry_stall": ["Retry loop is stalling"],
}

CHECKER_LOG_KEYWORDS: dict[str, list[str]] = {
    "tracelogOOM": [
        "starting up, version",
        "Nonfatal buffer manager memory allocation failure",
    ],
    "dmesgOOMKill": ["starting up, version"],
    "memoryUtilizationCritical": ["Nonfatal buffer manager memory allocation failure"],
    "memoryUtilizationWarning": ["Nonfatal buffer manager memory allocation failure"],
    "clusterMemoryUsage": ["Nonfatal buffer manager memory allocation failure"],
    "highQueryMemoryUsage": ["Nonfatal buffer manager memory allocation failure"],
    "tracelogOOD": ["no space left", "disk full"],
    "detectCrashStackTraces": ["segmentation fault", "assert failed", "SIGSEGV"],
    "failedCodegen": ["compilation failed", "failed to finalize asynchronous compilation"],
    "failedBackgroundThreadAllocations": ["Retry loop is stalling"],
    "tracelogHardShutdown": ["hard shutdown"],
    "pressureEvents_etimedout": ["ETIMEDOUT"],
    "pressureEvents_fsync_behind": ["fsync is behind"],
    "pressureEvents_retry_stall": ["Retry loop is stalling"],
    "replicationLagCritical": ["replication link down", "replication error"],
    "replicationLagDegraded": ["replication link down"],
    "asyncTransitionDetected": ["from sync to async"],
    "disconnectedReplicationSlaves": ["replication link down"],
    "backupFailures": ["backup failed"],
    "backupReliability": ["backup failed"],
    "slowQueries": ["compilation failed"],
    "blockedQueries": ["lock wait timeout"],
    "longRunningTransactions": ["lock wait timeout"],
    "lockContention": ["lock wait timeout"],
    "severeLockContention": ["lock wait timeout"],
    "unkillableQueries": ["lock wait timeout"],
    "defunctProcesses": ["starting up, version"],
    "workloadThrottleDetected": ["WORKLOAD_THROTTLE"],
}

# Findings sourced from SQL/sysinfo/sysctl — no reliable memsql.log keyword.
CHECKERS_WITHOUT_TRACELOG: frozenset[str] = frozenset({
    "transparentHugepage", "vmMaxMapCount", "maxMapCount", "vmSwappiness", "vmOvercommit",
    "minFreeKbytes", "swapEnabled", "swapUsage", "swapUsageDetected",
    "chronydDisabled", "numaConfiguration", "filesystemType", "validateSsd",
    "cpuFeatures", "cpuHyperThreading", "cpuModel", "kernelVersions",
    "memsqlVersions", "versionHashes", "maxOpenFiles", "securityLimits",
    "installedPermissions", "cgroupDisabled", "cgroupMemoryUsage", "syncCnfVariables",
    "defaultVariables", "attachRebalanceDelay", "autoAttach", "failureDetectionOn",
    "defaultWorkloadManagement", "interpreterMode",
    "validLicense", "consistentMaxMemory", "maxMemorySettings",
    "orphanDatabases", "orphanTables", "secondaryDatabases",
    "partitionsConsistency", "duplicatePartitionDatabase",
    "unmappedMasterPartitions", "clusterLayoutImbalance",
    "leavesNotOnline", "offlineAggregators", "userDatabaseRedundancy",
    "pendingDatabases", "missingClusterDb", "unrecoverableDatabases",
    "highAvailability", "usedClusterCapacity", "diskUsage", "diskInodesUsage",
    "diskLatencyRead", "diskLatencyWrite", "diskBandwidth", "cpuMemoryBandwidth",
    "leafAverageRoundtripLatency", "networkBuffersMax", "firewallPortBlocking",
    "cpuIdle", "somaxconnLimit", "maxNicePriority", "orchestratorProcesses",
    "opsProcesses", "mallocActiveMemory", "columnstoreSegmentRows",
    "whitespacesInObjectName", "explainRebalancePartitionsChecker",
    "replicationLag", "replicationPausedDatabases", "backupHistory",
    "memoryCommitted", "majorPageFaults", "reclamationStalled",
    "runningAlterOrTruncate", "runningBackup", "highActiveQueryCount",
    "repeatedQueryPatterns", "logCoverageGap", "collectionErrors",
    "dmesgCollectorUnavailable", "sleepingOpenTransactions",
    "sdbHCAdvancedHDFSPipelineFeatures", "sdbHCAesDefaultEncryptionMode",
    "sdbHCAuditlogDiskSync", "sdbHCAuditlogLevel", "sdbHCAuditlogRetentionPeriod",
    "sdbHCAuditlogsDir", "sdbHCBindAddress", "sdbHCDedicatedAdminConnections",
    "sdbHCDefaultPort", "sdbHCDefaultUserRequireSSL", "sdbHCEnableWASM",
    "sdbHCEncryptedBlockDevice", "sdbHCEngineVersion",
    "sdbHCFailedLoginAttemptLockoutPolicy", "sdbHCLicenseVisibility",
    "sdbHCNetworkAccess", "sdbHCPasswordPolicy", "sdbHCReplicationTlsOnly",
    "sdbHCResourceLimits", "sdbHCReviewTlsConfig", "sdbHCRoleBasedAccessControl",
    "sdbHCRootPassword", "sdbHCRowLevelSecurity", "sdbHCSecureFilePriv",
    "sdbHCServiceAccount", "sdbHCSslFilesAndDatadirPermissions",
    "sdbHCSyncPermissions", "sdbHCTlsCertKey", "sdbHCTlsFipsMode",
    "sdbHCUnnecessaryDefaultUsers", "sdbHCUserAuthentication", "sdbHChttpAPI",
})

PATTERN_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "oom": ["Nonfatal buffer manager memory allocation failure", "starting up, version"],
    "disk": ["no space left", "disk full"],
    "replication": ["replication link down", "replication error"],
    "crash": ["segmentation fault", "assert failed", "SIGSEGV"],
    "locking": ["lock wait timeout", "lock timeout exceeded"],
    "columnstore": ["failed to merge", "merge error"],
    "network": ["ETIMEDOUT", "Connection timed out"],
    "storage": ["fsync is behind", "Blob fsync is behind"],
    "background_tasks": ["Retry loop is stalling", "stalling retry loop"],
    "compilation": ["compilation failed", "failed to finalize asynchronous compilation"],
    "backup": ["backup failed", "backup error"],
    "restart": ["starting up, version", "memsqld started"],
}

THEME_LOG_SEARCH_DEFAULTS: dict[str, list[str]] = {
    "memory": ["Nonfatal buffer manager memory allocation failure"],
    "replication": ["replication link down"],
    "availability": ["starting up, version"],
    "query": ["lock wait timeout", "compilation failed"],
    "storage": ["fsync is behind"],
    "backup": ["backup failed"],
    "logs": [],
    "config": [],
}

SQL_STOPWORDS = frozenset({
    "SELECT", "FROM", "WHERE", "JOIN", "AND", "OR", "INTO", "INSERT", "UPDATE",
    "DELETE", "WITH", "AS", "ON", "LEFT", "RIGHT", "INNER", "OUTER", "GROUP",
    "ORDER", "BY", "LIMIT", "HAVING", "UNION", "ALL", "DISTINCT", "SET", "COUNT",
})

MAX_CLUSTER_LOG_EXCERPTS = 12
MAX_CLUSTER_LOG_PATTERNS = 8


def _looks_like_checker_id(term: str) -> bool:
    """True when term is a camelCase checker id, not a tracelog substring."""
    if not term or " " in term:
        return False
    return bool(re.match(r"^[a-z][a-zA-Z0-9_]*$", term)) and any(c.isupper() for c in term[1:])


def _match_tracelog_phrases(text: str) -> list[str]:
    """Return documented memsql.log phrases found in text (longest match first)."""
    if not text:
        return []
    hay = str(text)
    hay_lower = hay.lower()
    matched: list[str] = []
    for phrase in TRACELOG_PHRASES:
        if phrase.lower() in hay_lower:
            matched.append(phrase)
    return dedupe_preserve_order(matched)


def _extract_sample_from_evidence(evidence: str) -> str:
    """Pull the tracelog sample embedded in superchecker evidence strings."""
    if not evidence:
        return ""
    match = re.search(r"sample=(.+)$", evidence, re.I | re.S)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_sql_tokens_from_evidence(evidence: str) -> list[str]:
    """Extract table/object names from query= evidence for log correlation."""
    if not evidence:
        return []
    terms: list[str] = []
    query_match = re.search(r"query=([^,]{8,})", evidence, re.I)
    if not query_match:
        return terms
    query_text = query_match.group(1).strip()
    from_match = re.search(r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", query_text, re.I)
    if from_match:
        terms.append(from_match.group(1))
        return terms
    for token in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b", query_text):
        if token.upper() not in SQL_STOPWORDS:
            terms.append(token)
            break
    return terms


def _is_dmesg_only_finding(finding: dict[str, Any], evidence: str) -> bool:
    """True when evidence is kernel/dmesg and memsql.log sample is absent."""
    views = {str(v) for v in (finding.get("related_views") or [])}
    if "dmesg" in views and "memsqlTracelogs" not in views:
        return True
    if re.search(r"kernel:|^\s*\[.*\]\s+Out of memory:", evidence, re.I | re.M):
        return True
    return False


def _checker_log_keywords(checker_id: str) -> list[str]:
    if checker_id in CHECKER_LOG_KEYWORDS:
        return list(CHECKER_LOG_KEYWORDS[checker_id])
    if checker_id.startswith("pressureEvents_"):
        suffix = checker_id[len("pressureEvents_"):]
        return list(PRESSURE_EVENT_KEYWORDS.get(suffix, []))
    return []


def _extract_keywords_from_evidence(evidence: str) -> list[str]:
    """Pull tracelog-searchable tokens from superchecker evidence strings."""
    if not evidence:
        return []
    terms: list[str] = []
    sample = _extract_sample_from_evidence(evidence)
    if sample:
        terms.extend(_match_tracelog_phrases(sample))
    terms.extend(_match_tracelog_phrases(evidence))
    terms.extend(_extract_sql_tokens_from_evidence(evidence))
    return dedupe_preserve_order(terms)


def _pattern_search_term(pattern: dict[str, Any]) -> list[str]:
    """Derive tracelog keywords from a detected pattern record."""
    terms: list[str] = []
    sample = (pattern.get("sample") or "").strip()
    if sample:
        terms.extend(_match_tracelog_phrases(sample))
        if not terms and len(sample) >= 12:
            terms.append(sample[:80])
    category = str(pattern.get("category") or "").lower()
    if not terms:
        terms.extend(PATTERN_CATEGORY_KEYWORDS.get(category, []))
    return dedupe_preserve_order([t for t in terms if t and not _looks_like_checker_id(t)])


def resolve_log_search_keywords(bundle: InvestigationBundle) -> list[str]:
    """Return tracelog-searchable keywords; never raw checker ids like runawayQueries."""
    terms: list[str] = []

    for pattern in bundle.log_context.get("patterns") or []:
        terms.extend(_pattern_search_term(pattern))
    for pattern in bundle.report_signals.get("cluster_log_patterns") or []:
        terms.extend(_pattern_search_term(pattern))
    for pattern in bundle.report_signals.get("detected_patterns") or []:
        terms.extend(_pattern_search_term(pattern))

    for excerpt in bundle.log_context.get("excerpts") or []:
        msg = str(excerpt.get("message") or "")
        terms.extend(_extract_keywords_from_evidence(msg))

    for checker in dedupe_preserve_order(
        [bundle.root_cause_checker_id, *bundle.member_checker_ids]
    ):
        if checker:
            terms.extend(_checker_log_keywords(checker))

    for finding in bundle.findings:
        for ev in finding.evidence or []:
            snippet = getattr(ev, "raw_snippet", None) or ""
            terms.extend(_extract_keywords_from_evidence(str(snippet)))
        terms.extend(_extract_keywords_from_evidence(finding.summary))

    theme_defaults = THEME_LOG_SEARCH_DEFAULTS.get(bundle.theme, [])
    terms.extend(theme_defaults)

    cleaned = [
        t for t in dedupe_preserve_order(terms)
        if t and not _looks_like_checker_id(t)
    ]
    generic_defaults = set(theme_defaults) | {
        kw for kws in CHECKER_LOG_KEYWORDS.values() for kw in kws
    }
    evidence_terms = [t for t in cleaned if t not in generic_defaults]
    if evidence_terms:
        return (evidence_terms + cleaned)[:6]
    return cleaned[:6]


def resolve_finding_log_search_terms(finding: dict[str, Any]) -> dict[str, str]:
    """Derive a tracelog-searchable keyword (+ optional node) for one finding.

    Used to power a per-finding "View in Logs" deep link. Prefers documented
    SingleStore memsql.log phrases from evidence samples, then checker-specific
    grounded keywords. Returns an empty keyword when the finding has no reliable
    tracelog correlate (config/SQL-only checkers).
    """
    checker_id = str(finding.get("checker_id") or "")
    evidence = str(finding.get("evidence") or "")

    nodes = [str(n).strip() for n in (finding.get("nodes") or []) if str(n).strip()]
    node = nodes[0] if len(nodes) == 1 else ""

    if checker_id in CHECKERS_WITHOUT_TRACELOG:
        return {"keyword": "", "node": node}

    evidence_terms = _extract_keywords_from_evidence(evidence)
    if _is_dmesg_only_finding(finding, evidence) and not _extract_sample_from_evidence(evidence):
        evidence_terms = [
            t for t in evidence_terms
            if t not in ("Out of memory: Kill process", "Killed process")
        ]
        if not evidence_terms:
            checker_terms = _checker_log_keywords(checker_id)
            cleaned = [t for t in checker_terms if t and not _looks_like_checker_id(t)]
            return {"keyword": cleaned[0] if cleaned else "", "node": node}

    checker_terms = _checker_log_keywords(checker_id)
    merged = dedupe_preserve_order(evidence_terms + checker_terms)
    cleaned = [t for t in merged if t and not _looks_like_checker_id(t)]

    keyword = cleaned[0] if cleaned else ""
    return {"keyword": keyword, "node": node}


def _node_matches_log_host(log_hostname: str, cluster_nodes: list[str]) -> bool:
    """Match parsed log hostnames to cluster node identifiers (short or FQDN)."""
    if not cluster_nodes:
        return True
    lh = (log_hostname or "").strip().lower()
    if not lh:
        return False
    lh_short = lh.split(".")[0]
    for node in cluster_nodes:
        n = (node or "").strip().lower()
        if not n:
            continue
        n_short = n.split(".")[0]
        if n in lh or lh in n or lh_short == n_short:
            return True
    return False


def _keywords_for_cluster(cluster: dict[str, Any], members: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for tag in cluster.get("tags") or []:
        tag_s = str(tag).strip()
        if tag_s:
            terms.append(tag_s)
    root = str(cluster.get("root_cause_checker_id") or "").strip()
    if root:
        terms.extend(_checker_log_keywords(root))
    for raw in members:
        checker = str(raw.get("checker_id") or "").strip()
        if checker:
            terms.extend(_checker_log_keywords(checker))
        for tag in raw.get("priority_tags") or raw.get("tags") or []:
            tag_s = str(tag).strip()
            if tag_s:
                terms.append(tag_s)
    return dedupe_preserve_order([t for t in terms if t])


def _pattern_matches_cluster(
    pattern: dict[str, Any],
    cluster_nodes: list[str],
    cluster_tags: list[str],
) -> bool:
    pat_nodes = pattern.get("nodes") or []
    if cluster_nodes and pat_nodes:
        if not any(_node_matches_log_host(str(pn), cluster_nodes) for pn in pat_nodes):
            return False
    category = str(pattern.get("category") or "").lower()
    if not cluster_tags:
        return True
    allowed: set[str] = set()
    for tag in cluster_tags:
        allowed.update(TAG_TO_LOG_CATEGORIES.get(str(tag).lower(), set()))
    if not allowed:
        return True
    return not category or category in allowed


def _build_cluster_log_context(
    cluster: dict[str, Any],
    members: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, Any]:
    """Attach cluster-scoped tracelog patterns and excerpts (no full log dump)."""
    nodes = list(cluster.get("nodes") or [])
    tags = list(cluster.get("tags") or [])
    keywords = _keywords_for_cluster(cluster, members)
    kw_lower = [k.lower() for k in keywords]

    patterns: list[dict[str, Any]] = []
    for pat in report.get("detected_log_patterns") or []:
        if not isinstance(pat, dict):
            continue
        if not _pattern_matches_cluster(pat, nodes, tags):
            continue
        patterns.append({
            "title": pat.get("title"),
            "category": pat.get("category"),
            "count": pat.get("count"),
            "severity": pat.get("severity"),
            "sample": (pat.get("sample") or "")[:400],
            "first_seen": pat.get("first_seen"),
            "last_seen": pat.get("last_seen"),
            "nodes": (pat.get("nodes") or [])[:5],
        })
    patterns.sort(
        key=lambda p: (
            {"critical": 0, "warning": 1, "info": 2}.get(str(p.get("severity", "info")), 2),
            -(int(p.get("count") or 0)),
        )
    )
    patterns = patterns[:MAX_CLUSTER_LOG_PATTERNS]

    excerpts: list[dict[str, Any]] = []
    seen_messages: set[str] = set()

    def _add_excerpt(timestamp: str, hostname: str, severity: str, message: str) -> None:
        msg = (message or "").strip()
        if not msg:
            return
        key = msg[:160]
        if key in seen_messages:
            return
        seen_messages.add(key)
        excerpts.append({
            "timestamp": timestamp or "",
            "hostname": hostname or "",
            "severity": severity or "",
            "message": msg[:500],
        })

    for log in report.get("logs") or []:
        if not isinstance(log, dict):
            continue
        if not _node_matches_log_host(str(log.get("hostname") or ""), nodes):
            continue
        msg = str(log.get("message") or "")
        sev = str(log.get("severity") or "").upper()
        matches_kw = any(kw in msg.lower() for kw in kw_lower) if kw_lower else False
        is_error = sev in ("ERROR", "CRITICAL", "FATAL")
        if matches_kw or is_error:
            _add_excerpt(
                str(log.get("timestamp") or ""),
                str(log.get("hostname") or ""),
                str(log.get("severity") or ""),
                msg,
            )
        if len(excerpts) >= MAX_CLUSTER_LOG_EXCERPTS:
            break

    if len(excerpts) < MAX_CLUSTER_LOG_EXCERPTS:
        for pat in patterns:
            sample = (pat.get("sample") or "").strip()
            if sample:
                _add_excerpt(
                    str(pat.get("last_seen") or pat.get("first_seen") or ""),
                    ", ".join(pat.get("nodes") or [])[:80],
                    str(pat.get("severity") or "warning"),
                    sample,
                )
            if len(excerpts) >= MAX_CLUSTER_LOG_EXCERPTS:
                break

    if len(excerpts) < MAX_CLUSTER_LOG_EXCERPTS:
        for raw in members:
            evidence = str(raw.get("evidence") or "").strip()
            if len(evidence) < 20:
                continue
            node_hint = (raw.get("nodes") or [""])[0]
            _add_excerpt("", str(node_hint), str(raw.get("severity") or ""), evidence)
            if len(excerpts) >= MAX_CLUSTER_LOG_EXCERPTS:
                break

    error_excerpts = sum(
        1 for e in excerpts
        if str(e.get("severity") or "").upper() in ("ERROR", "CRITICAL", "FATAL", "WARNING")
    )

    return {
        "patterns": patterns,
        "excerpts": excerpts[:MAX_CLUSTER_LOG_EXCERPTS],
        "summary": {
            "pattern_count": len(patterns),
            "excerpt_count": len(excerpts),
            "error_excerpts": error_excerpts,
        },
    }


def enrich_incident_clusters_with_logs(
    clusters: list[dict[str, Any]],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    """Add cluster-scoped tracelog patterns and excerpts to each incident cluster."""
    if not clusters:
        return clusters
    recs_by_id = {
        str(r.get("id")): r
        for r in (report.get("recommendations") or [])
        if r.get("id") is not None
    }
    enriched: list[dict[str, Any]] = []
    for cluster in clusters:
        cluster_copy = dict(cluster)
        member_ids = [str(mid) for mid in (cluster.get("member_ids") or [])]
        members = [recs_by_id[mid] for mid in member_ids if mid in recs_by_id]
        cluster_copy["log_context"] = _build_cluster_log_context(cluster_copy, members, report)
        enriched.append(cluster_copy)
    return enriched


def _incident_clusters(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(
        payload.get("incident_clusters")
        or (payload.get("triage") or {}).get("incident_clusters")
        or []
    )


def resolve_incident_clusters(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return incident clusters, enriching with log context when missing."""
    clusters = _incident_clusters(payload)
    if not clusters:
        return []
    if any(isinstance(c, dict) and c.get("log_context") for c in clusters):
        return clusters
    return enrich_incident_clusters_with_logs(clusters, payload)


def _compact_report_signals(
    payload: dict[str, Any],
    log_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract compact report signals — cluster-scoped log excerpts when available."""
    overview = payload.get("cluster_overview", {}) or {}
    log_summary = payload.get("log_summary", {}) or {}
    patterns = payload.get("detected_log_patterns", []) or []
    node_events = payload.get("node_events", []) or []
    replication = payload.get("replication_lag_patterns", {}) or {}
    memory_util = payload.get("memory_utilization", {}) or {}

    down_events = [
        e for e in node_events
        if isinstance(e, dict) and e.get("category") in ("node_down", "failover")
    ][:5]

    signals = {
        "cluster_name": overview.get("cluster_name", ""),
        "version": overview.get("version", ""),
        "log_errors": (log_summary.get("severity_counts", {}) or {}).get("ERROR", 0),
        "log_warnings": (log_summary.get("severity_counts", {}) or {}).get("WARN", 0),
        "detected_patterns": [
            {
                "title": p.get("title"),
                "count": p.get("count"),
                "severity": p.get("severity"),
            }
            for p in patterns[:5]
            if isinstance(p, dict)
        ],
        "node_down_events": down_events,
        "replication_state": replication.get("state"),
        "replication_max_lag_sec": replication.get("max_lag_sec"),
        "memory_cluster_status": (memory_util.get("cluster_summary", {}) or {}).get("status"),
        "nodes_over_90_pct": (memory_util.get("cluster_summary", {}) or {}).get("nodes_over_90_pct"),
    }
    if log_context:
        signals["cluster_log_patterns"] = log_context.get("patterns", [])[:MAX_CLUSTER_LOG_PATTERNS]
        signals["cluster_log_excerpts"] = log_context.get("excerpts", [])[:MAX_CLUSTER_LOG_EXCERPTS]
        signals["cluster_log_summary"] = log_context.get("summary", {})
    return signals


def _extract_time_range(payload: dict[str, Any]) -> dict[str, str] | None:
    coverage = payload.get("log_timeframe", {}) or {}
    first = coverage.get("first_log_entry") or coverage.get("earliest")
    last = coverage.get("last_log_entry") or coverage.get("latest")
    if first or last:
        return {"start": str(first or ""), "end": str(last or "")}
    return None


def _find_cluster(
    payload: dict[str, Any],
    cluster_id: str | None,
) -> dict[str, Any] | None:
    clusters = _incident_clusters(payload)
    if cluster_id:
        for cluster in clusters:
            if cluster.get("cluster_id") == cluster_id:
                return cluster
    return None


def _member_recommendations(
    payload: dict[str, Any],
    cluster: dict[str, Any] | None,
    finding_id: str | None,
) -> list[dict[str, Any]]:
    recs = payload.get("recommendations", []) or []
    if cluster:
        member_ids = {str(mid) for mid in (cluster.get("member_ids") or [])}
        return [r for r in recs if str(r.get("id")) in member_ids]
    if finding_id:
        for rec in recs:
            if str(rec.get("id")) == str(finding_id) or rec.get("checker_id") == finding_id:
                return [rec]
        for rec in recs:
            if rec.get("checker_id") == finding_id:
                return [rec]
    return []


def _synthetic_cluster_from_finding(rec: dict[str, Any]) -> dict[str, Any]:
    checker_id = rec.get("checker_id", "")
    return {
        "cluster_id": f"FINDING-{checker_id or rec.get('id', 'unknown')}",
        "root_cause_checker_id": checker_id,
        "root_cause_title": normalize_finding_title(rec.get("title", ""), checker_id),
        "summary": rec.get("description", ""),
        "member_ids": [rec.get("id")],
        "member_count": 1,
        "tags": list(rec.get("priority_tags") or rec.get("tags") or []),
        "nodes": list(rec.get("nodes") or []),
        "dominant_severity": rec.get("severity", "info"),
        "max_risk_score": rec.get("risk_score", 0),
    }


def build_investigation_bundle(
    report_id: str,
    payload: dict[str, Any],
    cluster_id: str | None = None,
    finding_id: str | None = None,
) -> InvestigationBundle | None:
    """Assemble investigation context from report payload and triage metadata."""
    payload = normalize_export_json_payload(payload)
    cluster = _find_cluster(payload, cluster_id)
    members = _member_recommendations(payload, cluster, finding_id)

    if not members and finding_id:
        recs = payload.get("recommendations", []) or []
        for rec in recs:
            if str(rec.get("checker_id")) == str(finding_id):
                members = [rec]
                cluster = _synthetic_cluster_from_finding(rec)
                break

    if not members:
        return None

    if not cluster:
        cluster = _synthetic_cluster_from_finding(members[0])

    version = (
        payload.get("cluster_overview", {}).get("version")
        or payload.get("version")
        or ""
    )
    report_metadata = {
        "report_id": report_id,
        "version": version,
        "deployment_type": payload.get("deployment_type", "unknown"),
    }

    findings: list[Finding] = []
    for raw in members:
        findings.append(finding_from_payload(raw, report_metadata))

    tags = list(cluster.get("tags") or [])
    root_cause = cluster.get("root_cause_checker_id", "")
    theme = resolve_cluster_theme(tags, root_cause)
    playbook_key = THEME_TO_PLAYBOOK.get(theme, "config_anomaly")

    affected_nodes = sorted({
        node
        for raw in members
        for node in (raw.get("nodes") or [])
        if node
    })
    if not affected_nodes:
        affected_nodes = list(cluster.get("nodes") or [])

    symptom_parts = [
        cluster.get("summary", ""),
        normalize_finding_title(cluster.get("root_cause_title", ""), root_cause),
    ]
    for raw in members[:3]:
        evidence = raw.get("evidence", "")
        if isinstance(evidence, str) and evidence:
            symptom_parts.append(evidence[:200])

    log_context = cluster.get("log_context") or {}
    if not log_context:
        log_context = _build_cluster_log_context(cluster, members, payload)

    return InvestigationBundle(
        report_id=report_id,
        cluster_id=cluster.get("cluster_id", cluster_id or "UNKNOWN"),
        theme=theme,
        playbook_key=playbook_key,
        root_cause_checker_id=root_cause,
        root_cause_title=normalize_finding_title(
            cluster.get("root_cause_title", ""), root_cause
        ),
        symptom_summary=" | ".join(p for p in symptom_parts if p)[:800],
        affected_nodes=affected_nodes,
        version=version,
        time_range=_extract_time_range(payload),
        findings=findings,
        report_signals=_compact_report_signals(payload, log_context),
        member_checker_ids=dedupe_preserve_order([
            str(raw.get("checker_id") or raw.get("id") or "")
            for raw in members
            if raw.get("checker_id") or raw.get("id")
        ]),
        log_context=log_context,
    )



def extract_known_doc_links(payload: dict[str, Any]) -> set[str]:
    """
    Extract valid HTTP doc links from superchecker recommendations (Export JSON shape).
    """
    links: set[str] = set()

    def _add_url(value: Any) -> None:
        if not isinstance(value, str):
            return
        candidate = value.strip()
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            links.add(candidate)

    for rec in payload.get("recommendations", []):
        if not isinstance(rec, dict):
            continue
        _add_url(rec.get("doc_link"))
        grounding = rec.get("grounding")
        if isinstance(grounding, dict):
            _add_url(grounding.get("source"))
    return links


MAX_PACKET_CHARS = 900_000
MAX_TOP_FINDINGS = 25
MAX_GLOBAL_EXCERPTS = 60
MAX_DETECTED_PATTERNS = 40
MAX_NODE_EVENTS = 40


def _severity_rank(severity: Any) -> int:
    return {"critical": 0, "warning": 1, "info": 2}.get(str(severity or "info").lower(), 2)


def _clip(text: Any, max_len: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


def _format_excerpt_line(excerpt: dict[str, Any]) -> str:
    ts = excerpt.get("timestamp") or "?"
    host = excerpt.get("hostname") or "?"
    sev = str(excerpt.get("severity") or "?").upper()
    msg = _clip(excerpt.get("message"), 400)
    return f"- `{ts}` `{host}` **{sev}**: {msg}"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _finding_severity_counts(recs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for rec in recs:
        sev = str(rec.get("severity") or "info").lower()
        if sev not in counts:
            sev = "info"
        counts[sev] += 1
    return counts


def _derive_triage_overview(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Lightweight triage buckets from per-finding triage metadata (same rules as /triage)."""
    act_now: list[dict[str, Any]] = []
    quick_wins: list[dict[str, Any]] = []
    act_soon: list[dict[str, Any]] = []
    backlog: list[dict[str, Any]] = []
    for rec in recs:
        triage = rec.get("triage") if isinstance(rec.get("triage"), dict) else {}
        priority = triage.get("priority", 3)
        entry = {
            "title": rec.get("title") or rec.get("checker_id"),
            "severity": rec.get("severity"),
            "nodes": rec.get("nodes") or [],
            "checker_id": rec.get("checker_id"),
            "quick_win": bool(triage.get("quick_win")),
            "recommended_action": triage.get("recommended_action") or "",
        }
        if priority == 1:
            act_now.append(entry)
        elif triage.get("quick_win"):
            quick_wins.append(entry)
        elif priority == 2:
            act_soon.append(entry)
        else:
            backlog.append(entry)
    return {
        "summary": {
            "act_now": len(act_now),
            "quick_wins": len(quick_wins),
            "act_soon": len(act_soon),
            "backlog": len(backlog),
        },
        "act_now": act_now,
        "quick_wins": quick_wins,
    }


def _memory_snapshot_lines(payload: dict[str, Any]) -> list[str]:
    mu = payload.get("memory_utilization") or {}
    if not isinstance(mu, dict):
        return []
    summary = mu.get("cluster_summary") if isinstance(mu.get("cluster_summary"), dict) else {}
    per_node = mu.get("per_node") if isinstance(mu.get("per_node"), dict) else {}
    lines: list[str] = []
    avg = _safe_float(summary.get("avg_engine_used_pct"))
    highest = _safe_float(summary.get("highest_utilization_pct"))
    highest_node = summary.get("highest_utilization_node") or ""
    if avg is not None or highest is not None:
        parts = []
        if avg is not None:
            parts.append(f"avg vs maximum_memory={avg:.1f}%")
        if highest is not None:
            parts.append(f"highest={highest:.1f}% on `{highest_node or '?'}`")
        over_90 = summary.get("nodes_over_90pct")
        over_80 = summary.get("nodes_over_80pct")
        if over_90 is not None:
            parts.append(f"nodes>90%={over_90}")
        if over_80 is not None:
            parts.append(f"nodes>80%={over_80}")
        lines.append(f"- Memory vs maximum_memory: {', '.join(parts)}")
    swap_hot = []
    for host, data in list(per_node.items())[:40]:
        if not isinstance(data, dict):
            continue
        swap_pct = _safe_float(data.get("swap_used_pct"))
        if swap_pct is not None and swap_pct > 5:
            swap_hot.append((host, swap_pct))
    if swap_hot:
        swap_hot.sort(key=lambda x: x[1], reverse=True)
        sample = ", ".join(f"`{h}`={p:.1f}%" for h, p in swap_hot[:8])
        lines.append(f"- Swap pressure (>5%): {sample}")
    return lines


def _replication_snapshot_lines(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("replication_status") or []
    if not isinstance(rows, list) or not rows:
        return []
    lags: list[float] = []
    paused = 0
    disconnected = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("LAG_SECONDS", "Lag_seconds", "Seconds_Behind_Master", "seconds_behind_master"):
            lag = _safe_float(row.get(key))
            if lag is not None:
                lags.append(lag)
                break
        blob = str(row).lower()
        connected = str(row.get("Connected", row.get("CONNECTED", ""))).strip().lower()
        if "paused" in blob:
            paused += 1
        if "disconnect" in blob or connected == "no":
            disconnected += 1
    lines = [f"- Replication links reported: {len(rows)}"]
    if lags:
        lines.append(
            f"- Lag: max={max(lags):.1f}s, median={sorted(lags)[len(lags) // 2]:.1f}s, "
            f"links>5s={sum(1 for x in lags if x > 5)}"
        )
    if paused:
        lines.append(f"- Paused / paused-like rows: {paused}")
    if disconnected:
        lines.append(f"- Disconnected rows: {disconnected}")
    return lines


def _disk_snapshot_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    disk = payload.get("disk_reclamation") if isinstance(payload.get("disk_reclamation"), dict) else {}
    overhead = disk.get("cluster_overhead") or payload.get("cluster_overhead") or {}
    if isinstance(overhead, dict) and overhead:
        total = overhead.get("total_overhead_bytes") or overhead.get("total_bytes")
        unref = overhead.get("unreferenced_blob_bytes") or overhead.get("unreferenced_blobs_bytes")
        if total is not None:
            lines.append(f"- Cluster disk overhead total_bytes=`{total}`")
        if unref is not None:
            lines.append(f"- Unreferenced blob bytes=`{unref}`")
    storage = payload.get("storage") if isinstance(payload.get("storage"), dict) else {}
    if storage.get("total_bytes") or storage.get("used_bytes"):
        lines.append(
            f"- Storage: used=`{storage.get('used_bytes', '?')}` / "
            f"total=`{storage.get('total_bytes', '?')}`"
        )
    # Fall back to high-signal disk findings when structured metrics are thin
    if not lines:
        disk_recs = [
            r
            for r in (payload.get("recommendations") or [])
            if isinstance(r, dict)
            and str(r.get("category") or "").lower() in {"storage", "disk", "environment"}
            and str(r.get("severity") or "").lower() in {"critical", "warning"}
        ][:6]
        for rec in disk_recs:
            lines.append(
                f"- [{str(rec.get('severity') or '?').upper()}] "
                f"{_clip(rec.get('title') or rec.get('checker_id'), 120)}"
            )
    return lines


def _triage_section_lines(
    triage_summary: Any,
    derived: dict[str, Any],
) -> list[str]:
    summary = triage_summary if isinstance(triage_summary, dict) else derived.get("summary") or {}
    lines = [
        "## Triage overview",
        "",
        f"- Act Now: {summary.get('act_now', 0)}",
        f"- Quick Wins: {summary.get('quick_wins', 0)}",
        f"- Act Soon: {summary.get('act_soon', 0)}",
        f"- Backlog: {summary.get('backlog', 0)}",
        "",
    ]
    act_now = derived.get("act_now") or []
    if act_now:
        lines.append("### Act now (top)")
        lines.append("")
        for item in act_now[:12]:
            sev = str(item.get("severity") or "critical").upper()
            title = _clip(item.get("title") or item.get("checker_id") or "finding", 140)
            nodes = item.get("nodes") or []
            node_s = f" — nodes: {', '.join(str(n) for n in nodes[:4])}" if nodes else ""
            action = item.get("recommended_action")
            lines.append(f"- **[{sev}] {title}**{node_s}")
            if action:
                lines.append(f"  - Action: {_clip(action, 220)}")
        lines.append("")
    quick = derived.get("quick_wins") or []
    if quick:
        lines.append("### Quick wins (top)")
        lines.append("")
        for item in quick[:8]:
            lines.append(f"- {_clip(item.get('title') or item.get('checker_id'), 140)}")
        lines.append("")
    return lines


def _capacity_section_lines(payload: dict[str, Any]) -> list[str]:
    mem = _memory_snapshot_lines(payload)
    repl = _replication_snapshot_lines(payload)
    disk = _disk_snapshot_lines(payload)
    if not (mem or repl or disk):
        return []
    lines = ["## Cluster capacity & replication snapshot", ""]
    if mem:
        lines.append("### Memory")
        lines.append("")
        lines.extend(mem)
        lines.append("")
    if repl:
        lines.append("### Replication")
        lines.append("")
        lines.extend(repl)
        lines.append("")
    if disk:
        lines.append("### Disk / storage")
        lines.append("")
        lines.extend(disk)
        lines.append("")
    return lines


def _affected_nodes_lines(recs: list[dict[str, Any]]) -> list[str]:
    tallies: dict[str, int] = {}
    for rec in recs:
        if str(rec.get("severity") or "").lower() not in {"critical", "warning"}:
            continue
        for node in rec.get("nodes") or []:
            name = str(node).strip()
            if not name:
                continue
            tallies[name] = tallies.get(name, 0) + 1
    if not tallies:
        return []
    ranked = sorted(tallies.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    lines = ["## Most-affected nodes", "", "| Node | Critical/warning findings |", "| --- | ---: |"]
    for name, count in ranked:
        lines.append(f"| `{name}` | {count} |")
    lines.append("")
    return lines


def _build_glean_prompt(
    report_name: str,
    health_score: Any,
    health_grade: Any,
    cluster_count: int,
    finding_count: int,
    pattern_count: int,
    triage_summary: Any,
) -> str:
    name = report_name or "this SingleStore cluster"
    grade_bit = f" (grade {health_grade})" if health_grade not in (None, "", "?") else ""
    triage_bit = ""
    if isinstance(triage_summary, dict):
        triage_bit = (
            f" Triage: Act Now={triage_summary.get('act_now', 0)}, "
            f"Quick Wins={triage_summary.get('quick_wins', 0)}, "
            f"Act Soon={triage_summary.get('act_soon', 0)}, "
            f"Backlog={triage_summary.get('backlog', 0)}."
        )
    return (
        f"I attached an S2 Report Sniffer incident packet for {name}. "
        f"Finding Severity Index (Sniffer, not cluster vitals): {health_score}{grade_bit}; {cluster_count} incident cluster(s); "
        f"{finding_count} top finding(s); {pattern_count} suspected log pattern(s)."
        f"{triage_bit} "
        "Using only the attached packet — especially Triage overview, Cluster capacity & "
        "replication snapshot, Top findings (with grounding), Incident clusters, and "
        "Suspected log lines — explain what is going wrong, the most likely root-cause "
        "chain, what to rule out, and a prioritized remediation plan. Cite packet sections; "
        "do not invent metrics that are not in the packet."
    )


def build_glean_packet(payload: dict[str, Any], report_id: str = "") -> dict[str, str]:
    """
    Build a whole-report Markdown packet for handoff into Glean Chat.

    Returns ``{filename, markdown, prompt}``. No network calls; local-only.
    """
    normalized = normalize_export_json_payload(payload or {})
    clusters = resolve_incident_clusters(normalized)
    recs = [r for r in (normalized.get("recommendations") or []) if isinstance(r, dict)]
    top_findings = sorted(
        recs,
        key=lambda r: (_severity_rank(r.get("severity")), -int(r.get("risk_score") or 0)),
    )[:MAX_TOP_FINDINGS]

    overview = normalized.get("cluster_overview") or {}
    if not isinstance(overview, dict):
        overview = {}
    log_timeframe = normalized.get("log_timeframe") or {}
    if not isinstance(log_timeframe, dict):
        log_timeframe = {}

    rid = str(
        report_id
        or normalized.get("report_id")
        or normalized.get("id")
        or "report"
    ).strip() or "report"
    short_id = rid[:8] if len(rid) >= 8 else rid
    report_name = str(normalized.get("report_name") or overview.get("cluster_name") or rid)
    health = normalized.get("health_score", overview.get("health_score", "?"))
    health_grade = (
        normalized.get("health_grade")
        or overview.get("health_grade")
        or "?"
    )
    risk = normalized.get("cluster_risk_score", overview.get("cluster_risk_score", "?"))
    node_count = overview.get("node_count") or overview.get("total_nodes") or len(
        normalized.get("nodes") or []
    )
    version = (
        overview.get("version")
        or normalized.get("version")
        or (normalized.get("cluster_overview") or {}).get("memsql_version")
        or "?"
    )
    sev_counts = _finding_severity_counts(recs)
    derived_triage = _derive_triage_overview(recs)
    triage_summary = normalized.get("triage_summary") or derived_triage.get("summary")

    detected_patterns = [
        p for p in (normalized.get("detected_log_patterns") or []) if isinstance(p, dict)
    ][:MAX_DETECTED_PATTERNS]
    node_events = [
        e for e in (normalized.get("node_events") or []) if isinstance(e, dict)
    ][:MAX_NODE_EVENTS]
    doc_links = sorted(extract_known_doc_links(normalized))

    prompt = _build_glean_prompt(
        report_name,
        health,
        health_grade,
        len(clusters),
        len(top_findings),
        len(detected_patterns),
        triage_summary,
    )

    lines: list[str] = [
        f"# S2 Report Sniffer — Incident Packet",
        "",
        f"- **Report:** {report_name}",
        f"- **Report ID:** `{rid}`",
        f"- **Uploaded:** {normalized.get('uploaded_at') or 'n/a'}",
        f"- **Finding Severity Index (Sniffer):** {health}",
        f"- **Health grade (Sniffer):** {health_grade}",
        f"- **Cluster risk:** {risk}",
        f"- **Version:** {version}",
        f"- **Nodes:** {node_count}",
        (
            f"- **Finding counts:** critical={sev_counts['critical']}, "
            f"warning={sev_counts['warning']}, info={sev_counts['info']}"
        ),
        f"- **Log timeframe:** {log_timeframe.get('first') or log_timeframe.get('start') or '?'} → "
        f"{log_timeframe.get('last') or log_timeframe.get('end') or '?'}",
        "",
        "## Suggested Glean prompt",
        "",
        prompt,
        "",
    ]
    lines.extend(_triage_section_lines(triage_summary, derived_triage))
    lines.extend(_capacity_section_lines(normalized))
    lines.extend(_affected_nodes_lines(recs))
    lines += [
        "## Top findings",
        "",
    ]

    if not top_findings:
        lines.append("_No recommendations in this report._")
        lines.append("")
    for rec in top_findings:
        sev = str(rec.get("severity") or "info").upper()
        title = _clip(rec.get("title") or rec.get("checker_id") or "finding", 160)
        cid = rec.get("checker_id") or rec.get("check_id") or ""
        risk_score = rec.get("risk_score", "")
        lines.append(f"### [{sev}] {title}")
        if cid:
            lines.append(f"- Checker: `{cid}` (risk {risk_score})")
        if rec.get("description") or rec.get("summary"):
            lines.append(f"- Summary: {_clip(rec.get('description') or rec.get('summary'), 300)}")
        if rec.get("evidence"):
            lines.append(f"- Evidence: {_clip(rec.get('evidence'), 400)}")
        if rec.get("remediation"):
            lines.append(f"- Remediation: {_clip(rec.get('remediation'), 300)}")
        grounding = rec.get("grounding") if isinstance(rec.get("grounding"), dict) else {}
        if grounding:
            basis = grounding.get("basis") or ""
            criterion = _clip(grounding.get("criterion"), 240)
            source = grounding.get("source") or ""
            lines.append(f"- Grounding: basis=`{basis}` — {criterion}")
            if source:
                lines.append(f"- Doc: {source}")
        elif rec.get("doc_link"):
            lines.append(f"- Doc: {rec.get('doc_link')}")
        lines.append("")

    lines += ["## Incident clusters", ""]
    if not clusters:
        lines.append("_No incident clusters detected._")
        lines.append("")
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cid = cluster.get("cluster_id") or "?"
        title = _clip(
            normalize_finding_title(
                cluster.get("title") or cluster.get("root_cause_title") or cid,
                cluster.get("root_cause_checker_id") or "",
            ),
            160,
        )
        sev = str(cluster.get("severity") or "info").upper()
        lines.append(f"### {cid} — [{sev}] {title}")
        if cluster.get("root_cause_checker_id"):
            lines.append(f"- Root cause candidate: `{cluster.get('root_cause_checker_id')}`")
        if cluster.get("summary") or cluster.get("symptom_summary"):
            lines.append(
                f"- Summary: {_clip(cluster.get('summary') or cluster.get('symptom_summary'), 320)}"
            )
        tags = cluster.get("tags") or []
        if tags:
            lines.append(f"- Tags: {', '.join(str(t) for t in tags[:8])}")
        members = cluster.get("member_ids") or cluster.get("members") or []
        if members:
            member_ids = [
                str(m.get("checker_id") if isinstance(m, dict) else m)
                for m in members[:12]
            ]
            lines.append(f"- Members: {', '.join(f'`{m}`' for m in member_ids if m)}")
        log_context = cluster.get("log_context") if isinstance(cluster.get("log_context"), dict) else {}
        patterns = [p for p in (log_context.get("patterns") or []) if isinstance(p, dict)]
        excerpts = [e for e in (log_context.get("excerpts") or []) if isinstance(e, dict)]
        if patterns:
            lines.append("- Cluster log patterns:")
            for pat in patterns[:MAX_CLUSTER_LOG_PATTERNS]:
                lines.append(
                    f"  - **{_clip(pat.get('title'), 80)}** "
                    f"({pat.get('severity', '?')}, count={pat.get('count', '?')}): "
                    f"{_clip(pat.get('sample'), 240)}"
                )
        if excerpts:
            lines.append("- Suspected log lines (cluster):")
            for excerpt in excerpts[:MAX_CLUSTER_LOG_EXCERPTS]:
                lines.append(f"  {_format_excerpt_line(excerpt)[2:]}")
        lines.append("")

    lines += ["## Suspected log patterns (report-wide)", ""]
    if not detected_patterns:
        lines.append("_No detected_log_patterns in this report._")
        lines.append("")
    for pat in detected_patterns:
        lines.append(
            f"- **{_clip(pat.get('title'), 100)}** "
            f"[{pat.get('severity', '?')}] count={pat.get('count', '?')} "
            f"category=`{pat.get('category', '')}` "
            f"nodes={', '.join(str(n) for n in (pat.get('nodes') or [])[:5])} "
            f"seen={pat.get('first_seen') or '?'} → {pat.get('last_seen') or '?'}"
        )
        if pat.get("sample"):
            lines.append(f"  - Sample: `{_clip(pat.get('sample'), 300)}`")
        if pat.get("conclusion"):
            lines.append(f"  - Conclusion: {_clip(pat.get('conclusion'), 240)}")
    lines.append("")

    # Deduplicate global excerpts across clusters for a dedicated section
    lines += ["## Suspected log lines (aggregated)", ""]
    seen_excerpt_keys: set[str] = set()
    aggregated: list[dict[str, Any]] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        log_context = cluster.get("log_context") if isinstance(cluster.get("log_context"), dict) else {}
        for excerpt in log_context.get("excerpts") or []:
            if not isinstance(excerpt, dict):
                continue
            key = f"{excerpt.get('timestamp')}|{excerpt.get('hostname')}|{excerpt.get('message')}"
            if key in seen_excerpt_keys:
                continue
            seen_excerpt_keys.add(key)
            aggregated.append(excerpt)
            if len(aggregated) >= MAX_GLOBAL_EXCERPTS:
                break
        if len(aggregated) >= MAX_GLOBAL_EXCERPTS:
            break
    if not aggregated:
        # Fall back to pattern samples as suspected lines
        for pat in detected_patterns:
            sample = pat.get("sample")
            if not sample:
                continue
            aggregated.append(
                {
                    "timestamp": pat.get("first_seen") or "?",
                    "hostname": ",".join(str(n) for n in (pat.get("nodes") or [])[:2]) or "?",
                    "severity": pat.get("severity") or "warning",
                    "message": sample,
                }
            )
            if len(aggregated) >= MAX_GLOBAL_EXCERPTS:
                break
    if not aggregated:
        lines.append("_No suspected log excerpts available. Prefer directory import or rehydrate-diagnostics for richer log context._")
        lines.append("")
    else:
        for excerpt in aggregated:
            lines.append(_format_excerpt_line(excerpt))
        lines.append("")

    lines += ["## Node events", ""]
    if not node_events:
        lines.append("_No node_events in this report._")
        lines.append("")
    for event in node_events:
        lines.append(
            f"- `{event.get('event_time') or '?'}` "
            f"**{event.get('event_type') or event.get('category') or 'event'}** "
            f"node=`{event.get('node_id') or '?'}` "
            f"[{event.get('severity') or '?'}]: "
            f"{_clip(event.get('description'), 240)}"
        )
    lines.append("")

    if doc_links:
        lines += ["## Known doc links", ""]
        for url in doc_links[:20]:
            lines.append(f"- {url}")
        lines.append("")

    lines += [
        "---",
        "_Generated locally by S2 Report Sniffer. Attach this file in Glean Chat; "
        "no data leaves the machine until you explicitly attach it._",
        "",
    ]

    markdown = "\n".join(lines)
    if len(markdown) > MAX_PACKET_CHARS:
        markdown = (
            markdown[: MAX_PACKET_CHARS - 80].rstrip()
            + "\n\n_…packet truncated to stay attachable…_\n"
        )

    filename = f"s2rs-incident-packet-{short_id}.md"
    return {
        "filename": filename,
        "markdown": markdown,
        "prompt": prompt,
    }


def build_in_app_actions(bundle: InvestigationBundle) -> list[dict[str, Any]]:
    """Suggest deep links into S2 Report Sniffer investigation surfaces."""
    actions: list[dict[str, Any]] = []
    node = bundle.affected_nodes[0] if bundle.affected_nodes else ""

    log_terms = resolve_log_search_keywords(bundle)

    if log_terms:
        actions.append({
            "type": "log_search",
            "label": "Search tracelogs",
            "tab": "log-search",
            "params": {
                "keyword": log_terms[0],
                "node": node,
            },
        })

    if bundle.theme in ("query", "memory"):
        actions.append({
            "type": "query_tracer",
            "label": "Open Query Tracer",
            "tab": "queries",
            "params": {},
        })

    if bundle.theme == "availability" or bundle.report_signals.get("node_down_events"):
        actions.append({
            "type": "node_down",
            "label": "Review node-down timeline",
            "tab": "overview",
            "params": {"nodes": bundle.affected_nodes[:3]},
        })

    if bundle.theme == "replication":
        actions.append({
            "type": "diagnostics",
            "label": "Open Diagnostics dashboard",
            "tab": "diagnostics",
            "params": {},
        })

    return actions
