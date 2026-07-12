"""Grounding registry for superchecker findings.

Every finding the app produces must declare *why* it fired: the basis for its
threshold or conclusion, and (where one exists) a verifiable SingleStore
documentation source. This keeps the analysis honest — nothing is arbitrary,
and heuristics are labeled as heuristics rather than dressed up as documented
requirements.

Basis vocabulary
----------------
- ``documented``     Threshold/criterion is published in SingleStore docs
                     (cite ``source``).
- ``toolbox-default``Value is a SingleStore Toolbox / sdb-report default or
                     first-party tool default (cite ``source``).
- ``heuristic``      Operational rule of thumb used by this tool. NOT a
                     published SingleStore threshold — surfaced as such so
                     engineers can apply judgement.
- ``observed``       Conclusion is drawn directly from report evidence
                     (a state/flag/event in the bundle); no fixed numeric
                     threshold is applied.

All ``source`` URLs below were verified against live SingleStore documentation.
"""

DOCUMENTED = "documented"
TOOLBOX = "toolbox-default"
HEURISTIC = "heuristic"
OBSERVED = "observed"

# ─── Verified SingleStore documentation sources ──────────────────────
# System Requirements & Recommendations — canonical Toolbox host-checker
# thresholds (THP, swap, vm.*, ulimit, disk latency/usage, network buffers,
# CPU, major page faults, committed/maximum memory, default ports).
SYSREQ = (
    "https://docs.singlestore.com/db/v9.1/reference/configuration-reference/"
    "cluster-configuration/system-requirements-and-recommendations/"
)
# maximum_memory default and ceiling (90% of RAM or RAM-10GB, whichever larger).
MAXMEM = (
    "https://docs.singlestore.com/db/v9.1/user-and-cluster-administration/"
    "maintain-your-cluster/managing-memory/maximum-memory/"
)
# Changing memory limits after deployment.
CHGMEM = (
    "https://docs.singlestore.com/db/v9.1/user-and-cluster-administration/"
    "maintain-your-cluster/managing-memory/change-memory-limits/"
)
# Replication & durability concepts (5s sync→async switch, redundancy-2, HA).
REPL = (
    "https://docs.singlestore.com/db/v9.1/user-and-cluster-administration/"
    "high-availability-and-disaster-recovery/replication-and-durability-concepts/replication/"
)
# MV_REPLICATION_STATUS view reference (lsn_lag, volume_lag_mb, catchup time).
MVREPL = (
    "https://docs.singlestore.com/db/v9.0/reference/information-schema-reference/"
    "replication-management/mv-replication-status/"
)
# Back up and restore data.
BACKUP = "https://docs.singlestore.com/db/v9.1/manage-data/back-up-and-restore-data/"
# Clear orphan databases (pre-existing, kept as-is).
ORPHAN = "https://docs.singlestore.com/docs/clear-orphan-databases/"

# Placeholder/generic links that must NOT be treated as real citations.
GENERIC_DOC_LINKS = {
    "",
    "https://docs.singlestore.com",
    "https://docs.singlestore.com/",
    "https://docs.singlestore.com/db/v9.0/",
    "https://docs.singlestore.com/db/v9.1/",
}


def _g(basis: str, source: str, criterion: str) -> dict:
    return {"basis": basis, "source": source, "criterion": criterion}


# ─── Per-checker grounding ───────────────────────────────────────────
# Keyed by checker_id. Criterion text states the exact documented rule or,
# for heuristics, plainly says it is an operational threshold.
GROUNDING: dict[str, dict] = {
    # ── Host / OS configuration (Toolbox host checkers, SYSREQ) ──────
    "transparentHugepage": _g(
        DOCUMENTED, SYSREQ,
        "THP enabled/defrag must read [never] or [madvise] on every node; "
        "SingleStore Toolbox 'transparentHugepage' checker.",
    ),
    "maxOpenFiles": _g(
        DOCUMENTED, SYSREQ,
        "memsql user NOFILE (open files) limit must be 1024000 "
        "(/etc/security/limits.conf).",
    ),
    "securityLimits": _g(
        DOCUMENTED, SYSREQ,
        "limits.conf: NOFILE 1024000 and nproc 128000 for the memsql user.",
    ),
    "maxNicePriority": _g(
        DOCUMENTED, SYSREQ,
        "SingleStore recommends the max nice limit be set to -10 for the "
        "memsql user.",
    ),
    "minFreeKbytes": _g(
        DOCUMENTED, SYSREQ,
        "vm.min_free_kbytes should be 1% of system RAM or 4 GB, whichever is "
        "smaller (Toolbox 'minFreeKbytes').",
    ),
    "vmMaxMapCount": _g(
        DOCUMENTED, SYSREQ,
        "vm.max_map_count must be at least 1000000000 (Toolbox 'maxMapCount').",
    ),
    "vmOvercommit": _g(
        DOCUMENTED, SYSREQ,
        "vm.overcommit_memory should be 0; =1 is not recommended "
        "(Toolbox 'vmOvercommit').",
    ),
    "vmSwappiness": _g(
        DOCUMENTED, SYSREQ,
        "vm.swappiness should be set between 1 and 10 and never 0 "
        "(Toolbox 'vmSwappiness').",
    ),
    "somaxconnLimit": _g(
        DOCUMENTED, SYSREQ,
        "net.core.somaxconn must be at least 1024; lower values can let "
        "connection requests overwhelm the host.",
    ),
    "networkBuffersMax": _g(
        DOCUMENTED, SYSREQ,
        "net.core.rmem_max and net.core.wmem_max must each be >= 8 MB "
        "(8388608 bytes) (Toolbox 'networkBuffersMax').",
    ),
    "swapEnabled": _g(
        DOCUMENTED, SYSREQ,
        "Total swap on each host should be >= 10% of physical RAM "
        "(Toolbox 'swapEnabled').",
    ),
    "swapUsage": _g(
        DOCUMENTED, SYSREQ,
        "Swap in active use: <5% recommended, >5% caution, >10% not "
        "recommended (Toolbox 'swapUsage').",
    ),
    "swapUsageDetected": _g(
        DOCUMENTED, SYSREQ,
        "Swap in active use: <5% recommended, >5% caution (warning), >10% "
        "not recommended (critical) — Toolbox 'swapUsage' thresholds.",
    ),
    "cgroupDisabled": _g(
        DOCUMENTED, SYSREQ,
        "cgroups should be disabled in non-VM deployments "
        "(Toolbox 'cgroupDisabled').",
    ),
    "majorPageFaults": _g(
        DOCUMENTED, SYSREQ,
        "Major page faults/sec: <10 recommended, 10-20 caution, >20 not "
        "recommended (Toolbox 'majorPageFaults').",
    ),
    "memoryCommitted": _g(
        DOCUMENTED, SYSREQ,
        "Committed memory per host: <30% recommended, 70-90% caution, >90% "
        "not recommended (Toolbox 'memoryCommitted').",
    ),
    "numaConfiguration": _g(
        DOCUMENTED, SYSREQ,
        "NUMA binding recommended on leaf hosts; aggregators should not be "
        "NUMA-bound (Toolbox 'numaConfiguration').",
    ),
    "filesystemType": _g(
        DOCUMENTED, SYSREQ,
        "Data directory must be on a POSIX-compliant filesystem; ext4 and xfs "
        "are the officially supported types (Toolbox 'filesystemType').",
    ),
    "validateSsd": _g(
        DOCUMENTED, SYSREQ,
        "SSD storage is recommended for each host (Toolbox 'validateSsd').",
    ),
    "cpuFeatures": _g(
        DOCUMENTED, SYSREQ,
        "SSE4.2 and AVX2 instruction-set extensions recommended "
        "(Toolbox 'cpuFeatures').",
    ),
    "cpuHyperThreading": _g(
        DOCUMENTED, SYSREQ,
        "Hyperthreading should be enabled (Toolbox 'cpuHyperThreading').",
    ),
    "cpuModel": _g(
        DOCUMENTED, SYSREQ,
        "All hosts should run the same CPU model (Toolbox 'cpuModel').",
    ),
    "cpuIdle": _g(
        DOCUMENTED, SYSREQ,
        "CPU idle: >25% recommended, <25% caution, <5% not recommended "
        "(Toolbox 'cpuIdle').",
    ),
    "cpuMemoryBandwidth": _g(
        DOCUMENTED, SYSREQ,
        "CPU-memory bandwidth must be >= 4 Gb/s per CPU and latency <= "
        "500000 ns (Toolbox 'cpuMemoryBandwidth').",
    ),
    "diskBandwidth": _g(
        DOCUMENTED, SYSREQ,
        "Disk read/write/sync-read bandwidth must be >= 128 ops/s "
        "(Toolbox 'diskBandwidth').",
    ),
    "diskLatencyRead": _g(
        DOCUMENTED, SYSREQ,
        "Disk read latency: <10 ms recommended, >10 ms caution, >25 ms not "
        "recommended (Toolbox 'diskLatency'). SSD >5 ms is an added early "
        "warning applied by this tool.",
    ),
    "diskLatencyWrite": _g(
        DOCUMENTED, SYSREQ,
        "Disk write latency: <10 ms recommended, >10 ms caution, >25 ms not "
        "recommended (Toolbox 'diskLatency'). SSD >5 ms is an added early "
        "warning applied by this tool.",
    ),
    "diskUsage": _g(
        DOCUMENTED, SYSREQ,
        "Free disk space: >30% recommended; 70-80% full caution; >80% full "
        "not recommended. Data volume should never exceed 60% utilization "
        "(Toolbox 'diskUsage').",
    ),
    "diskInodesUsage": _g(
        HEURISTIC, SYSREQ,
        "Inode-exhaustion early warning (>70% warning, >85% critical). "
        "Operational heuristic; not a published SingleStore Toolbox threshold.",
    ),
    "defunctProcesses": _g(
        DOCUMENTED, SYSREQ,
        "All defunct (zombie) processes should be cleared before deployment "
        "(Toolbox 'defunctProcesses').",
    ),
    "orchestratorProcesses": _g(
        DOCUMENTED, SYSREQ,
        "Informational: sdb-report notifies if an orchestrator process is "
        "present (Toolbox 'orchestratorProcesses').",
    ),
    "chronydDisabled": _g(
        HEURISTIC, SYSREQ,
        "SingleStore documents installing/running ntpd for time sync; "
        "disabling chronyd in favour of ntpd is a support convention, not a "
        "hard Toolbox requirement.",
    ),
    "kernelVersions": _g(
        DOCUMENTED, SYSREQ,
        "Kernel versions must be identical across all hosts "
        "(Toolbox 'kernelVersions').",
    ),
    "firewallPortBlocking": _g(
        DOCUMENTED, SYSREQ,
        "Intra-cluster traffic uses TCP 3306; 22/443/8080 have documented "
        "roles. Blocked ports break node-to-node communication.",
    ),

    # ── Memory limits / utilization ─────────────────────────────────
    "maxMemorySettings": _g(
        DOCUMENTED, MAXMEM,
        "maximum_memory ceiling is 90% of physical RAM, or RAM minus 10 GB, "
        "whichever is larger; maximum_table_memory < 91%.",
    ),
    "consistentMaxMemory": _g(
        DOCUMENTED, MAXMEM,
        "SingleStore recommends each leaf be allocated an equal amount of RAM; "
        "maximum_memory is derived from host RAM at deploy time.",
    ),
    "clusterMemoryUsage": _g(
        HEURISTIC, MAXMEM,
        "Node memory >80% (warning) / >90% (critical) as an OOM early warning. "
        "Grounded in documented behavior: disk spilling engages at 75% memory "
        "load and maximum_memory ceiling is 90% of RAM. The 80/90 alert points "
        "are this tool's operational thresholds.",
    ),
    "memoryUtilizationCritical": _g(
        DOCUMENTED, MAXMEM,
        "Engine memory >90% meets the documented maximum_memory ceiling "
        "(90% of RAM); at/above this, queries fail and OOM risk is high.",
    ),
    "memoryUtilizationWarning": _g(
        HEURISTIC, MAXMEM,
        "Engine memory >80% early warning below the documented 90% ceiling. "
        "Operational threshold applied by this tool.",
    ),
    "mallocActiveMemory": _g(
        HEURISTIC, MAXMEM,
        "Allocator active-memory pressure heuristic; no published fixed "
        "threshold.",
    ),
    "usedClusterCapacity": _g(
        OBSERVED, "",
        "Compares used memory against licensed/allocated capacity read from "
        "the bundle's license metadata (75%/90% alert points are this tool's "
        "operational thresholds).",
    ),

    # ── Replication / HA / durability ───────────────────────────────
    "asyncTransitionDetected": _g(
        DOCUMENTED, REPL,
        "A sync replica that fails to respond within 5 seconds switches to "
        "asynchronous replication (documented redundancy-2 behavior).",
    ),
    "replicationLag": _g(
        DOCUMENTED, REPL,
        ">5s lag is the documented point at which a sync replica switches to "
        "async; >30s (critical) is this tool's RPO escalation heuristic.",
    ),
    "replicationLagDegraded": _g(
        DOCUMENTED, REPL,
        "5-30s replica drift. The 5s floor matches the documented sync→async "
        "switch; the 30s cap is an operational escalation point.",
    ),
    "replicationLagCritical": _g(
        HEURISTIC, MVREPL,
        "Lag >30s across pairs (from MV_REPLICATION_STATUS lsn/volume lag). "
        "The 30s RPO threshold is this tool's operational escalation.",
    ),
    "workloadThrottleDetected": _g(
        OBSERVED, REPL,
        "WORKLOAD_THROTTLE MV_EVENTS observed directly in the bundle "
        "(sync replica replay fell behind and writes were throttled).",
    ),
    "replicationPausedDatabases": _g(
        OBSERVED, MVREPL,
        "Replication link reported in a paused state in the bundle.",
    ),
    "disconnectedReplicationSlaves": _g(
        OBSERVED, MVREPL,
        "Replication link reported disconnected/Connected=no in the bundle.",
    ),
    "secondaryDatabases": _g(
        OBSERVED, REPL,
        "IS_REPLICA/REPLICATION_ROLE metadata indicates a secondary "
        "(replicated) cluster.",
    ),
    "userDatabaseRedundancy": _g(
        OBSERVED, REPL,
        "Partitions reported in a non-ONLINE/HEALTHY state in cluster status; "
        "redundancy-2 requires a healthy replica for every partition.",
    ),
    "highAvailability": _g(
        DOCUMENTED, REPL,
        "High availability (redundancy-2) pairs leaves so every partition has "
        "a replica on the paired leaf.",
    ),

    # ── Backup ──────────────────────────────────────────────────────
    "backupReliability": _g(
        OBSERVED, BACKUP,
        "Backup success/failure counts read from the bundle's backup history "
        "(>=50% failures critical, 25-49% warning — this tool's rollup).",
    ),
    "backupHistory": _g(
        OBSERVED, BACKUP,
        "Backup history rows and recency read directly from the bundle.",
    ),
    "runningBackup": _g(
        OBSERVED, BACKUP,
        "An in-progress BACKUP DATABASE operation observed in running "
        "operations.",
    ),

    # ── OOM / memory pressure (log/dmesg evidence) ──────────────────
    "tracelogOOM": _g(
        DOCUMENTED, SYSREQ,
        "Linux OOM-killer invocation found in dmesg/tracelog; the "
        "'OutOfMemory' Toolbox checker requires the OOM killer not run on any "
        "host.",
    ),
    "dmesgOOMKill": _g(
        DOCUMENTED, SYSREQ,
        "Linux OOM-killer invocation found in dmesg; the 'OutOfMemory' Toolbox "
        "checker requires the OOM killer not run on any host.",
    ),

    # ── Schema / storage housekeeping ───────────────────────────────
    "orphanDatabases": _g(
        DOCUMENTED, ORPHAN,
        "Orphaned databases still consume memory; removed with CLEAR ORPHAN "
        "DATABASES.",
    ),
    "orphanTables": _g(
        DOCUMENTED, ORPHAN,
        "Orphan tables still consume memory; removed with CLEAR ORPHAN "
        "DATABASES.",
    ),

    # ── Query / transaction heuristics (operational thresholds) ─────
    "longRunningQueries": _g(
        HEURISTIC, "",
        "Query elapsed >60s (warning) / >600s (critical). Operational "
        "thresholds; SingleStore does not publish a fixed slow-query cutoff.",
    ),
    "runawayQueries": _g(
        HEURISTIC, "",
        "Query elapsed >5 minutes flagged as runaway. Operational threshold, "
        "not a documented SingleStore limit.",
    ),
    "slowQueries": _g(
        HEURISTIC, "",
        "Query elapsed >30s (warning) / >120s (critical). Operational "
        "thresholds, not a documented SingleStore limit.",
    ),
    "repeatedQueryPatterns": _g(
        HEURISTIC, "",
        "Same normalized SQL seen >=3 times. Operational heuristic for "
        "batching/caching opportunities.",
    ),
    "highQueryMemoryUsage": _g(
        HEURISTIC, "",
        "Active queries collectively using >4 GB. Operational early-warning "
        "threshold applied by this tool.",
    ),
    "highActiveQueryCount": _g(
        HEURISTIC, "",
        "Elevated concurrent active-query count. Operational heuristic; "
        "compare against configured resource-pool concurrency.",
    ),
    "sleepingOpenTransactions": _g(
        OBSERVED, "",
        "Sleeping connections holding open transactions observed in the "
        "processlist.",
    ),
    "blockedQueries": _g(
        OBSERVED, "",
        "Blocking chains derived directly from MV_BLOCKED_QUERIES rows in the "
        "bundle.",
    ),
    "queuedQueries": _g(
        HEURISTIC, "",
        "Resource-pool queue depth >5 (warning) / >50 (critical). Operational "
        "thresholds applied by this tool.",
    ),
    "unkillableQueries": _g(
        OBSERVED, "",
        "Kill_Status=unkillable observed directly in the processlist.",
    ),
    "longRunningTransactions": _g(
        HEURISTIC, "",
        "Transactions open >60s (warning) / >300s (critical). Operational "
        "thresholds; long transactions hold locks and resources.",
    ),
    "lockContention": _g(
        OBSERVED, "",
        "Blocking chains observed in MV_BLOCKED_QUERIES.",
    ),
    "severeLockContention": _g(
        HEURISTIC, "",
        "Blocking chain size >=10 classified as severe. Operational threshold "
        "applied by this tool.",
    ),
    "unkillableTransaction": _g(
        OBSERVED, "",
        "An unkillable transaction observed at the head of a blocking chain.",
    ),

    # ── Workload / thread pool heuristics ───────────────────────────
    "defaultWorkloadManagement": _g(
        HEURISTIC, "",
        "Workload-management left at defaults. Operational advisory, not a "
        "documented failure condition.",
    ),
    "delayedThreadLaunches": _g(
        HEURISTIC, "",
        "Delayed thread launches indicate thread-pool saturation. Operational "
        "heuristic derived from engine status counters.",
    ),
    "readyQueueSaturated": _g(
        HEURISTIC, "",
        "Ready-queue saturation heuristic derived from engine status counters.",
    ),

    # ── Cluster layout / partitions (observed from bundle) ──────────
    "clusterLayoutImbalance": _g(
        HEURISTIC, "",
        "Uneven partition distribution across hosts/roles. Operational balance "
        "heuristic, not a hard requirement.",
    ),
    "partitionsConsistency": _g(
        OBSERVED, "",
        "Partition-count consistency evaluated from partition metadata in the "
        "bundle.",
    ),
    "duplicatePartitionDatabase": _g(
        OBSERVED, "",
        "Duplicate partition assignments observed in partition metadata.",
    ),
    "unmappedMasterPartitions": _g(
        OBSERVED, "",
        "Master partitions without a mapping observed in partition metadata.",
    ),
    "explainRebalancePartitionsChecker": _g(
        OBSERVED, "",
        "Rebalance/partition-movement activity observed in MV_EVENTS / "
        "rebalance status.",
    ),
    "columnstoreSegmentRows": _g(
        HEURISTIC, "",
        "Columnstore segment-row health heuristic; flags small/fragmented "
        "segments that benefit from OPTIMIZE TABLE.",
    ),

    # ── Availability (observed states) ──────────────────────────────
    "leavesNotOnline": _g(
        OBSERVED, "",
        "Leaf node state != ONLINE read from MV_NODES.",
    ),
    "offlineAggregators": _g(
        OBSERVED, "",
        "Aggregator state != ONLINE read from MV_NODES / SHOW AGGREGATORS.",
    ),
    "unrecoverableDatabases": _g(
        OBSERVED, "",
        "Database Status=UNRECOVERABLE observed in the bundle.",
    ),
    "pendingDatabases": _g(
        OBSERVED, "",
        "Database Status=PENDING observed in the bundle.",
    ),
    "missingClusterDb": _g(
        OBSERVED, "",
        "Expected cluster database absent from database metadata.",
    ),
    "runningAlterOrTruncate": _g(
        OBSERVED, "",
        "In-progress ALTER/TRUNCATE observed in running operations.",
    ),

    # ── Network / latency ───────────────────────────────────────────
    "leafAverageRoundtripLatency": _g(
        HEURISTIC, SYSREQ,
        "Leaf roundtrip latency >5000 us (5 ms) flagged. Operational "
        "threshold; SingleStore documents network buffer/latency guidance but "
        "not a fixed leaf-roundtrip limit.",
    ),

    # ── Versions / license / permissions ────────────────────────────
    "memsqlVersions": _g(
        DOCUMENTED, SYSREQ,
        "Engine versions should be consistent across the cluster.",
    ),
    "versionHashes": _g(
        DOCUMENTED, SYSREQ,
        "Engine build hashes should be consistent across the cluster.",
    ),
    "validLicense": _g(
        OBSERVED, "",
        "License validity/expiry read directly from the bundle's license "
        "metadata.",
    ),
    "installedPermissions": _g(
        OBSERVED, SYSREQ,
        "Install/data directory ownership and permissions evaluated from the "
        "bundle.",
    ),
    "syncCnfVariables": _g(
        OBSERVED, "",
        "memsql.cnf variable drift across nodes evaluated from the bundle.",
    ),
    "interpreterMode": _g(
        HEURISTIC, "",
        "Interpreter/codegen mode advisory; interpreter mode is slower than "
        "compiled execution. Operational advisory.",
    ),
    "defaultVariables": _g(
        HEURISTIC, "",
        "Notable engine variables left at defaults. Operational advisory.",
    ),

    # ── Observability / collection gaps (observed) ──────────────────
    "logCoverageGap": _g(
        OBSERVED, "",
        "Gaps between first/last tracelog timestamps observed across nodes.",
    ),
    "collectionErrors": _g(
        OBSERVED, "",
        "Collection errors present in the bundle's collection metadata.",
    ),
    "dmesgCollectorUnavailable": _g(
        OBSERVED, "",
        "dmesg output missing/empty for one or more nodes in the bundle.",
    ),
    "pipelineErrorAnalysis": _g(
        OBSERVED, "",
        "Pipeline error rows observed in pipeline metadata.",
    ),
    "whitespacesInObjectName": _g(
        OBSERVED, "",
        "Object names containing whitespace observed in schema metadata.",
    ),
    "opsProcesses": _g(
        OBSERVED, "",
        "SingleStore Ops process observed in ps output.",
    ),
}


def get_grounding(checker_id: str) -> dict:
    """Return grounding metadata for a checker.

    Falls back to an ``observed`` basis for checkers without an explicit entry
    (e.g. dynamically named ones like ``pressureEvents_*``), which is the
    honest default: those findings are derived directly from bundle evidence.
    """
    entry = GROUNDING.get(checker_id)
    if entry:
        return entry
    if checker_id.startswith("pressureEvents_"):
        return _g(
            OBSERVED, "",
            "Hourly count of a specific pressure pattern (ETIMEDOUT, fsync "
            "behind, retry stall, etc.) matched directly in the tracelogs.",
        )
    return _g(
        OBSERVED, "",
        "Derived directly from report evidence; no fixed threshold applied.",
    )


def resolve_doc_link(checker_id: str, provided: str) -> str:
    """Choose the best documentation link for a finding.

    Uses the caller-provided link when it is specific; otherwise falls back to
    the checker's grounded source. Generic/placeholder links are treated as
    'no link' so we never surface an unhelpful bare domain.
    """
    provided = (provided or "").strip()
    if provided and provided not in GENERIC_DOC_LINKS:
        return provided
    return get_grounding(checker_id).get("source", "")
