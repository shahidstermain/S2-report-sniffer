import math
import re
from collections import defaultdict
from datetime import datetime, timezone


SEVERITY_WEIGHT = {"critical": 85, "warning": 55, "info": 20}
PRIORITY_WEIGHT = {
    "availability": 30,
    "data-loss": 28,
    "storage": 26,
    "memory": 24,
    "replication": 22,
    "query": 18,
    "performance": 16,
    "configuration": 14,
    "environment": 12,
    "observability": 10,
}

# ─── Triage metadata tables ──────────────────────────────────────────
# Effort estimate: how hard is the fix for a field engineer?
EFFORT_BY_TAG = {
    "configuration": "low",       # sysctl / cnf change + restart
    "os-config": "low",            # sysctl change
    "environment": "low",          # env / sysctl
    "security": "low",             # chmod / chown
    "workload": "medium",          # pool tuning
    "hardware": "high",           # physical change
    "cpu": "high",                 # capacity / arch
    "memory": "medium",            # maximum_memory tuning + restart
    "storage": "medium",          # add disk / rebalance
    "replication": "medium",      # network + replication repair
    "query": "medium",             # plan / index review
    "performance": "medium",      # multi-factor
    "availability": "high",       # topology / node add
    "data-loss": "high",          # backup / replication recovery
    "observability": "low",       # re-collect bundle
}
EFFORT_DEFAULT = "medium"

# Impact label: business / operational severity mapping
IMPACT_BY_SEVERITY = {
    "critical": "cluster-down",
    "warning": "degraded",
    "info": "informational",
}
IMPACT_BY_TAG = {
    "data-loss": "data-at-risk",
    "availability": "outage-risk",
    "memory": "stability-risk",
    "storage": "capacity-risk",
    "replication": "rpo-risk",
}

# Quick-win: low-effort + meaningful impact
QUICK_WIN_TAGS = {"configuration", "os-config", "environment", "security", "observability"}
QUICK_WIN_SEVERITIES = {"critical", "warning"}

# Blast-radius: how many nodes / whole cluster?
def _compute_blast_radius(nodes: list, all_findings_count: int) -> str:
    if not nodes:
        return "cluster-wide"
    if len(nodes) == 1:
        return "single-node"
    if len(nodes) <= 3:
        return "multi-node"
    return "cluster-wide"

# Recommended action: what should the engineer do FIRST?
ACTION_BY_TAG = {
    "availability": "Add or restore leaf nodes; verify network paths.",
    "data-loss": "Verify backup integrity and replication state before any writes.",
    "memory": "Reduce maximum_memory or add RAM; check for OOM evidence.",
    "storage": "Expand disk or rebalance partitions; check fsync latency.",
    "replication": "Check network between node pairs; verify MV_REPLICATION_STATUS.",
    "configuration": "Apply sysctl / memsql.cnf change and restart affected nodes.",
    "os-config": "Apply sysctl change; persist across reboot.",
    "performance": "Review query plans, resource pools, and I/O subsystem.",
    "query": "Investigate long-running / blocked queries via SHOW PROCESSLIST.",
    "environment": "Fix OS-level settings (THP, ulimits, kernel params).",
    "observability": "Re-collect support bundle with longer log retention.",
    "security": "Fix file permissions on data directory and SSL keys.",
    "workload": "Review and adjust resource pool settings.",
    "hardware": "Schedule hardware upgrade or BIOS/UEFI change.",
    "cpu": "Investigate CPU saturation; consider capacity increase.",
}
ACTION_DEFAULT = "Investigate the evidence and apply the remediation steps."


def run_superchecker(report: dict) -> list:
    state = _CheckerState(report or {})
    state.run()
    state.correlate()
    state.sort_and_finalize()
    return state.findings


def run_superchecker_with_clusters(report: dict) -> tuple:
    """Run the superchecker and return (findings, incident_clusters).

    The incident_clusters list is empty when no 2+ findings share a tag or node.
    """
    state = _CheckerState(report or {})
    state.run()
    state.correlate()
    state.sort_and_finalize()
    return state.findings, state.incident_clusters


class _CheckerState:
    def __init__(self, report: dict):
        self.report = report if isinstance(report, dict) else {}
        for key in [
            "nodes", "queries", "pipelines", "replication_status", "storage", "events",
            "backup_history", "detected_log_patterns", "dmesg_events", "databases",
            "availability_groups",
        ]:
            if not isinstance(self.report.get(key), list):
                self.report[key] = []
        for key in ["cluster_overview", "config_health", "alloc_memory", "partitions", "index",
                    "query_patterns", "replication_lag_patterns",
                    "memory_utilization", "long_running_transactions"]:
            if not isinstance(self.report.get(key), dict):
                self.report[key] = {}
        self.findings = []
        self.incident_clusters = []
        self._seq = 0

    def run(self):
        self._check_compatibility_inputs()
        self._check_cluster_memory_usage()
        self._check_disk_usage_and_inodes()
        self._check_disk_latency()
        self._check_node_online_status()
        self._check_database_redundancy_and_state()
        self._check_swap_faults_committed_memory()
        self._check_blocked_and_long_queries()
        self._check_query_queues()
        self._check_replication_health()
        self._check_network_port_blocking()
        self._check_cpu_idle_and_iowait()
        self._check_default_variables_and_interpreter_mode()
        self._check_preinstall_kernel_memory_network()
        self._check_numa_ssd_filesystem()
        self._check_cpu_kernel_model_consistency()
        self._check_process_limits_and_processes()
        self._check_versions_license_and_max_memory()
        self._check_malloc_columnstore_ha_partitions()
        self._check_running_operations()
        self._check_logs_and_backtraces()
        self._check_pipeline_analysis()
        self._check_collection_errors_and_object_names()
        self._check_log_coverage_gap()
        self._check_backup_reliability()
        self._check_network_storage_pressure()
        self._check_memory_pressure_indicators()
        self._check_cluster_layout_sanity()
        self._check_process_health_snapshot()
        self._check_query_patterns()
        self._check_replication_lag_patterns()
        self._check_memory_utilization()
        self._check_long_running_transactions()
        self._check_missing_checkers()

    def _check_compatibility_inputs(self):
        config_health = self.report.get("config_health", {}) or {}
        for check in config_health.get("os_checks", []) or []:
            name = check.get("name")
            status = str(check.get("status", "")).lower()
            if name == "Transparent Huge Pages" and status == "fail":
                self._add(
                    checker_id="transparentHugepage",
                    severity="critical",
                    category="Configuration",
                    title="Transparent Huge Pages not disabled",
                    description="THP causes latency spikes and memory fragmentation for SingleStore.",
                    evidence=str(check.get("detail", "")),
                    remediation="Set THP enabled/defrag to never and persist across reboot.",
                    confidence=0.98,
                    nodes=check.get("nodes", []) or [],
                    related_views=["transparentHugepage"],
                    tags={"environment", "performance"},
                )
            if name == "Open Files Limit (nofile)" and status == "fail":
                self._add(
                    checker_id="maxOpenFiles",
                    severity="critical",
                    category="Configuration",
                    title="Open files limit (nofile) too low",
                    description="SingleStore requires high file descriptor limits under production load.",
                    evidence=str(check.get("detail", "")),
                    remediation="Set memsql hard/soft nofile to >=1024000 and restart memsqld.",
                    confidence=0.98,
                    nodes=check.get("nodes", []) or [],
                    related_views=["memsqldProcessLimits", "securityLimits"],
                    tags={"environment", "availability"},
                )
        for evt in self.report.get("dmesg_events", []) or []:
            if str(evt.get("category", "")).lower() == "oom":
                self._add(
                    checker_id="tracelogOOM",
                    severity="critical",
                    category="Memory",
                    title=f"OOM kill detected on {evt.get('hostname', 'unknown')}",
                    description=str(evt.get("conclusion", "OOM kill detected")),
                    evidence=str(evt.get("line", ""))[:250],
                    remediation="Reduce memory pressure and tune maximum_memory relative to physical RAM.",
                    confidence=0.96,
                    nodes=[evt.get("hostname", "unknown")],
                    related_views=["dmesg", "free", "MV_SYSINFO_MEM"],
                    tags={"memory", "availability"},
                )
                break

    def _add_unique(self, checker_id: str, severity: str, category: str, title: str, description: str,
                    evidence: str, remediation: str, confidence: float = 0.8, nodes=None,
                    related_views=None, tags=None, doc_link: str = ""):
        nodes_sorted = sorted(set(nodes or []))
        for f in self.findings:
            if f["checker_id"] == checker_id and set(f["nodes"]) == set(nodes_sorted):
                if len(evidence) > len(f["evidence"]):
                    f["evidence"] = evidence
                return
        self._add(checker_id, severity, category, title, description, evidence, remediation,
                  confidence, nodes, related_views, tags, doc_link)

    def _add(self, checker_id: str, severity: str, category: str, title: str, description: str,
             evidence: str, remediation: str, confidence: float = 0.8, nodes=None,
             related_views=None, tags=None, doc_link: str = ""):
        severity = severity if severity in ("critical", "warning", "info") else "info"
        nodes = sorted(set(nodes or []))
        tags = set(tags or [])
        score = SEVERITY_WEIGHT[severity]
        for tag in tags:
            score += PRIORITY_WEIGHT.get(tag, 0) * 0.12
        score += min(15, len(nodes) * 2)
        score += max(0, min(10, int(round(confidence * 10))))
        self._seq += 1

        # ── Triage metadata ──────────────────────────────────────────
        # Impact: tag-specific override takes priority over severity default
        impact = IMPACT_BY_SEVERITY.get(severity, "informational")
        for tag in tags:
            if tag in IMPACT_BY_TAG:
                impact = IMPACT_BY_TAG[tag]
                break
        # Effort: pick the highest-effort tag (worst-case planning)
        efforts = [EFFORT_BY_TAG.get(t, EFFORT_DEFAULT) for t in tags]
        effort_rank = {"low": 0, "medium": 1, "high": 2}
        effort = max(efforts, key=lambda e: effort_rank.get(e, 1)) if efforts else EFFORT_DEFAULT
        # Quick-win: any low-effort tag + warning/critical (even if other tags
        # are higher effort, the low-effort fix is still actionable now)
        has_low_effort_tag = any(
            EFFORT_BY_TAG.get(t, EFFORT_DEFAULT) == "low" and t in QUICK_WIN_TAGS
            for t in tags
        )
        is_quick_win = has_low_effort_tag and severity in QUICK_WIN_SEVERITIES
        # Blast radius
        blast_radius = _compute_blast_radius(nodes, len(self.findings))
        # Recommended first action
        action = ACTION_DEFAULT
        for tag in tags:
            if tag in ACTION_BY_TAG:
                action = ACTION_BY_TAG[tag]
                break
        # Triage priority: 1 = act now, 2 = act soon, 3 = backlog
        if severity == "critical" or impact in ("data-at-risk", "outage-risk"):
            triage_priority = 1
        elif severity == "warning" or is_quick_win:
            triage_priority = 2
        else:
            triage_priority = 3

        self.findings.append({
            "id": self._seq,
            "checker_id": checker_id,
            "severity": severity,
            "category": category,
            "title": title,
            "description": description,
            "evidence": evidence,
            "remediation": remediation,
            "doc_link": doc_link or "",
            "nodes": nodes,
            "related_views": related_views or [],
            "risk_score": min(100, int(score)),
            "confidence": round(max(0.05, min(1.0, confidence)), 2),
            "related_findings": [],
            "priority_tags": sorted(tags),
            "triage": {
                "impact": impact,
                "effort": effort,
                "blast_radius": blast_radius,
                "quick_win": is_quick_win,
                "priority": triage_priority,
                "recommended_action": action,
            },
        })

    def _check_missing_checkers(self):
        cluster_overview = self.report.get("cluster_overview", {})
        orphan_dbs = cluster_overview.get("orphan_databases", [])
        if orphan_dbs:
            self._add(
                checker_id="orphanDatabases",
                severity="warning",
                category="Alerting",
                title=f"Orphan databases detected ({len(orphan_dbs)})",
                description="Orphan databases consume memory and resources but are not fully attached.",
                evidence=", ".join([str(db.get("Database", "unknown")) for db in orphan_dbs]),
                remediation="Drop or reattach orphan databases to reclaim resources.",
                confidence=0.9,
                nodes=[],
                tags={"storage", "memory"}
            )

        rebalance = cluster_overview.get("explain_rebalance_partitions", [])
        if rebalance:
            self._add(
                checker_id="explainRebalancePartitionsChecker",
                severity="warning",
                category="Alerting",
                title="Partitions are unbalanced",
                description="EXPLAIN REBALANCE PARTITIONS indicates partitions are not evenly distributed.",
                evidence=f"{len(rebalance)} databases need rebalancing",
                remediation="Run REBALANCE PARTITIONS ON affected databases.",
                confidence=0.85,
                nodes=[],
                tags={"performance", "storage"}
            )

        wlm = self.report.get("workload_management", [])
        if wlm:
            pools = [p.get("Pool_Name", "") for p in wlm if str(p.get("Pool_Name", "")) != ""]
            if len(pools) > 1:
                self._add(
                    checker_id="defaultWorkloadManagement",
                    severity="warning",
                    category="Performance",
                    title="Non-default Workload Management",
                    description="Custom resource pools detected. Ensure they do not starve critical queries.",
                    evidence=f"Pools: {', '.join(pools)}",
                    remediation="Review resource pool settings against SingleStore recommendations.",
                    confidence=0.7,
                    nodes=[],
                    tags={"performance", "workload"}
                )

        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            metrics = node.get("metrics", {})
            sys_info = metrics.get("sys_info", {})
            mem = metrics.get("memory", {})

            min_free = sys_info.get("vm.min_free_kbytes")
            if min_free and str(min_free).isdigit() and int(min_free) < 153600:
                self._add(
                    checker_id="minFreeKbytes",
                    severity="warning",
                    category="Pre-installation",
                    title="vm.min_free_kbytes is too low",
                    description="A low min_free_kbytes can cause memory allocation stalls.",
                    evidence=f"Node {host} has {min_free} (Recommended: 153600+)",
                    remediation="sysctl -w vm.min_free_kbytes=153600",
                    confidence=0.9,
                    nodes=[host],
                    tags={"os-config", "memory"}
                )

            cpu_mem = metrics.get("sys_info", {}).get("cpu_memory_bandwidth", "")
            if cpu_mem and "low" in str(cpu_mem).lower():
                self._add(
                    checker_id="cpuMemoryBandwidth",
                    severity="warning",
                    category="Performance",
                    title="Low CPU memory bandwidth detected",
                    description="Measured bandwidth is below vendor recommendations.",
                    evidence=f"Node {host}: {cpu_mem}",
                    remediation="Check BIOS/UEFI settings for memory interleaving or correct DIMM population.",
                    confidence=0.8,
                    nodes=[host],
                    tags={"performance", "hardware"}
                )

            disk_bw = metrics.get("sys_info", {}).get("disk_bandwidth", "")
            if disk_bw and "low" in str(disk_bw).lower():
                self._add(
                    checker_id="diskBandwidth",
                    severity="warning",
                    category="Performance",
                    title="Low disk bandwidth",
                    description="Sequential read speed is below the recommended 200 MB/s minimum for columnstore.",
                    evidence=f"Node {host}: {disk_bw}",
                    remediation="Upgrade storage to enterprise SSD/NVMe.",
                    confidence=0.85,
                    nodes=[host],
                    tags={"performance", "storage"}
                )

            nice = sys_info.get("kernel.sched_rt_runtime_us", "")
            if nice and str(nice).isdigit() and int(nice) < 950000:
                self._add(
                    checker_id="maxNicePriority",
                    severity="warning",
                    category="Pre-installation",
                    title="maxNicePriority is below recommended",
                    description="RT scheduler runtime might limit SingleStore background tasks.",
                    evidence=f"Node {host}: {nice}",
                    remediation="Set kernel.sched_rt_runtime_us to 950000 or configure cgroups properly.",
                    confidence=0.7,
                    nodes=[host],
                    tags={"os-config"}
                )

            part_cons = metrics.get("sys_info", {}).get("partitions_start", "")
            if part_cons and "unaligned" in str(part_cons).lower():
                self._add(
                    checker_id="partitionsConsistency",
                    severity="warning",
                    category="Pre-installation",
                    title="SSD partition alignment issue",
                    description="Partitions are not aligned to 4096-byte sectors, which degrades SSD performance.",
                    evidence=f"Node {host}: {part_cons}",
                    remediation="Recreate partitions with proper sector alignment.",
                    confidence=0.8,
                    nodes=[host],
                    tags={"storage", "hardware"}
                )

            perms = metrics.get("sys_info", {}).get("installed_permissions", "")
            if perms and "fail" in str(perms).lower():
                self._add(
                    checker_id="installedPermissions",
                    severity="critical",
                    category="Pre-installation",
                    title="Incorrect data directory permissions",
                    description="Data directory or SSL keys have insecure or incorrect permissions.",
                    evidence=f"Node {host}: {perms}",
                    remediation="Ensure datadir is owned by memsql:memsql with 700/750 permissions.",
                    confidence=0.9,
                    nodes=[host],
                    tags={"security", "configuration"}
                )

            sync_cnf = node.get("memsql_cnf", {})
            live_vars = self._node_show_vars(node)
            for k, v in sync_cnf.items():
                live_v = live_vars.get(k)
                if live_v and str(v) != str(live_v):
                    self._add(
                        checker_id="syncCnfVariables",
                        severity="warning",
                        category="Pre-installation",
                        title="memsql.cnf out of sync with live variables",
                        description=f"Variable {k} in memsql.cnf differs from the live in-engine value.",
                        evidence=f"Node {host}: cnf={v}, live={live_v}",
                        remediation="Restart the node to apply memsql.cnf, or run SET GLOBAL to sync live value.",
                        confidence=0.9,
                        nodes=[host],
                        tags={"configuration"}
                    )

            swap_total = mem.get("swap_total_mb", 0)
            if str(swap_total).isdigit() and int(swap_total) == 0:
                self._add(
                    checker_id="swapEnabled",
                    severity="warning",
                    category="Pre-installation",
                    title="Swap is disabled",
                    description="Having no swap space can lead to random OOM kills if memory is exhausted.",
                    evidence=f"Node {host} has 0 MB swap.",
                    remediation="Configure at least 10% of physical RAM as swap space.",
                    confidence=0.85,
                    nodes=[host],
                    tags={"os-config", "memory"}
                )

            cgroup = sys_info.get("cgroup_memory", "")
            if cgroup and "enabled" in str(cgroup).lower():
                self._add(
                    checker_id="cgroupDisabled",
                    severity="info",
                    category="Pre-installation",
                    title="Cgroup memory subsystem is enabled",
                    description="SingleStore does not use the memory subsystem, disabling it reduces kernel resource consumption.",
                    evidence=f"Node {host}: {cgroup}",
                    remediation="Disable cgroup memory subsystem if not using containerized deployments.",
                    confidence=0.7,
                    nodes=[host],
                    tags={"os-config", "memory"}
                )

            tracelogs = node.get("tracelogs", [])
            for log in tracelogs:
                text = str(log.get("message", "")).lower()
                if "delayed thread launch" in text:
                    self._add(
                        checker_id="delayedThreadLaunches",
                        severity="warning",
                        category="Performance",
                        title="Delayed thread launches detected",
                        description="Indicates CPU saturation or thread pool exhaustion.",
                        evidence=f"Found on {host}: {text[:100]}...",
                        remediation="Check CPU utilization and query concurrency.",
                        confidence=0.9,
                        nodes=[host],
                        tags={"performance", "cpu"}
                    )
                if "ready queue saturated" in text:
                    self._add(
                        checker_id="readyQueueSaturated",
                        severity="critical",
                        category="Performance",
                        title="Ready queue saturated",
                        description="The query execution thread pool is completely full.",
                        evidence=f"Found on {host}: {text[:100]}...",
                        remediation="Reduce concurrent query workload or optimize slow queries.",
                        confidence=0.95,
                        nodes=[host],
                        tags={"performance", "cpu"}
                    )

        self._check_orphan_tables()
        self._check_secondary_databases()
        self._check_used_cluster_capacity()
        self._check_chronyd_disabled()
        self._check_network_buffers_max()
        self._check_leaf_roundtrip_latency()
        self._check_unkillable_queries()

    def _check_orphan_tables(self):
        tables = self.report.get("information_schema_tables", []) or []
        if not tables:
            return
        orphan_rows = []
        for row in tables:
            table_type = str(row.get("TABLE_TYPE", row.get("table_type", "BASE TABLE"))).upper()
            has_partition = row.get("PARTITION_COUNT", row.get("partition_count", 0))
            if table_type == "BASE TABLE" and (has_partition == 0 or has_partition == "NULL" or has_partition == ""):
                orphan_rows.append(row)
        if not orphan_rows:
            return
        names = [str(r.get("TABLE_NAME", r.get("table_name", "?"))) for r in orphan_rows[:15]]
        self._add(
            checker_id="orphanTables",
            severity="warning",
            category="Schema",
            title=f"Orphan tables detected ({len(orphan_rows)})",
            description="Orphan tables, while unused, still consume memory. They can be cleared using CLEAR ORPHAN DATABASES.",
            evidence=f"Tables: {', '.join(names)}",
            remediation="Run CLEAR ORPHAN DATABASES to remove orphaned table metadata.",
            confidence=0.82,
            nodes=[],
            related_views=["informationSchemaTables"],
            tags={"storage", "memory"},
            doc_link="https://docs.singlestore.com/docs/clear-orphan-databases/",
        )

    def _check_secondary_databases(self):
        databases = self.report.get("databases", []) or []
        if not databases:
            return
        is_secondary = False
        for row in databases:
            is_replica = str(row.get("IS_REPLICA", row.get("is_replica", row.get("IS_READ_REPLICA", "")))).lower()
            if is_replica in ("true", "yes", "1"):
                is_secondary = True
                break
            repl_role = str(row.get("REPLICATION_ROLE", row.get("replication_role", ""))).lower()
            if repl_role == "secondary":
                is_secondary = True
                break
        if is_secondary:
            self._add(
                checker_id="secondaryDatabases",
                severity="info",
                category="Replication",
                title="Cluster appears to be a secondary/replicated cluster",
                description="This informational check can help determine if the cluster is the primary cluster, or a secondary/replicated one.",
                evidence="IS_REPLICA=true or REPLICATION_ROLE=secondary detected in database metadata",
                remediation="Verify that replication health and lag are within acceptable RPO targets.",
                confidence=0.78,
                nodes=[],
                related_views=["informationSchemaDistributedDatabases", "showDatabasesExtended"],
                tags={"replication", "availability"},
                doc_link="https://docs.singlestore.com/docs/replication/",
            )

    def _check_used_cluster_capacity(self):
        overview = self.report.get("cluster_overview", {}) or {}
        used_mb = float(overview.get("used_memory_mb", 0) or 0)
        total_mb = float(overview.get("total_memory_mb", 0) or 0)
        licensed_mb_str = str(self.report.get("licensed_capacity_mb", ""))
        if not licensed_mb_str:
            lic_data = (self.report.get("config_health", {}) or {}).get("license", {})
            if lic_data:
                cap = lic_data.get("capacity", "")
                if isinstance(cap, (int, float)):
                    licensed_mb_str = str(cap)
        licensed_mb = float(licensed_mb_str) if licensed_mb_str else 0
        if licensed_mb > 0 and used_mb > 0:
            pct = used_mb / licensed_mb * 100
            sev = "critical" if pct > 90 else "warning" if pct > 75 else "info"
            self._add(
                checker_id="usedClusterCapacity",
                severity=sev,
                category="Configuration",
                title=f"Used cluster capacity at {pct:.1f}% of licensed limit",
                description="Checks the used cluster capacity and compares it to the licensed cluster capacity.",
                evidence=f"used={_fmt_mb(used_mb)} licensed={_fmt_mb(licensed_mb)} ({pct:.1f}%)",
                remediation="Reduce memory usage, expand cluster capacity, or renew license to avoid service disruption.",
                confidence=0.88,
                nodes=[],
                related_views=["MV_NODES", "licenseMetadata"],
                tags={"configuration", "availability"},
                doc_link="https://docs.singlestore.com/",
            )
        elif total_mb > 0 and used_mb > 0:
            pct = used_mb / total_mb * 100
            sev = "critical" if pct > 90 else "warning" if pct > 75 else "info"
            self._add(
                checker_id="usedClusterCapacity",
                severity=sev,
                category="Configuration",
                title=f"Cluster memory at {pct:.1f}% of available capacity",
                description="Used cluster capacity compared against node allocated memory.",
                evidence=f"used={_fmt_mb(used_mb)} total_allocated={_fmt_mb(total_mb)} ({pct:.1f}%)",
                remediation="Reduce memory usage or add nodes to increase available capacity.",
                confidence=0.72,
                nodes=[],
                related_views=["MV_NODES"],
                tags={"configuration", "memory"},
            )

    def _check_chronyd_disabled(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            ps_rows = node.get("metrics", {}).get("ps", []) or []
            proc_text = " ".join(str(r.get("cmd", "")).lower() for r in ps_rows)
            if "chronyd" in proc_text or "chrony" in proc_text:
                self._add(
                    checker_id="chronydDisabled",
                    severity="warning",
                    category="Environment",
                    title=f"chronyd process detected on {host}",
                    description="We recommend that chronyd is disabled so that ntpd can be used for time synchronization.",
                    evidence="chronyd or chrony process found in ps output on host",
                    remediation="Contact your administrator to disable chronyd and use ntpd for time synchronization.",
                    confidence=0.82,
                    nodes=[host],
                    related_views=["ps aux"],
                    tags={"environment"},
                    doc_link="https://docs.singlestore.com/",
                )

    def _check_network_buffers_max(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            sysctl = node.get("os_checks", {}).get("sysctl", {}) or {}
            wmem_max_raw = str((sysctl.get("net.core.wmem_max", {}) or {}).get("value", ""))
            rmem_max_raw = str((sysctl.get("net.core.rmem_max", {}) or {}).get("value", ""))
            wmem = _parse_size_to_bytes(wmem_max_raw) if wmem_max_raw else 0
            rmem = _parse_size_to_bytes(rmem_max_raw) if rmem_max_raw else 0
            min_required = 8 * 1024 * 1024
            low_buffers = []
            if wmem > 0 and wmem < min_required:
                low_buffers.append(f"wmem_max={wmem_max_raw}({_fmt_mb(wmem/1024/1024)})")
            if rmem > 0 and rmem < min_required:
                low_buffers.append(f"rmem_max={rmem_max_raw}({_fmt_mb(rmem/1024/1024)})")
            if low_buffers:
                self._add(
                    checker_id="networkBuffersMax",
                    severity="warning",
                    category="Network",
                    title=f"Network buffer settings too low on {host}",
                    description="wmem_max and rmem_max are network settings that control send/receive socket buffer sizes. If too low, latency may result.",
                    evidence=f"Node {host}: {', '.join(low_buffers)} (required >= 8MB each)",
                    remediation="Set net.core.wmem_max and net.core.rmem_max to at least 8388608 in /etc/sysctl.conf.",
                    confidence=0.83,
                    nodes=[host],
                    related_views=["sysctl", "netstat"],
                    tags={"environment", "performance", "network"},
                    doc_link="https://docs.singlestore.com/",
                )

    def _check_leaf_roundtrip_latency(self):
        mv_nodes = self.report.get("cluster_overview", {}).get("nodes_detail", []) or []
        leaf_latencies = []
        for row in mv_nodes:
            node_type = str(row.get("type", "")).upper()
            if "LEAF" in node_type:
                lat = _to_float(row.get("LEAF_AVERAGE_ROUNDTRIP_LATENCY_US", row.get("leaf_avg_roundtrip_latency_us", row.get("avg_latency_us", 0))))
                if lat > 0:
                    leaf_latencies.append((lat, row.get("ip_addr", "unknown")))
        if leaf_latencies:
            high_latency = [(lat, h) for lat, h in leaf_latencies if lat > 5000]
            if high_latency:
                top = max(high_latency, key=lambda x: x[0])
                self._add(
                    checker_id="leafAverageRoundtripLatency",
                    severity="warning",
                    category="Network",
                    title=f"High leaf roundtrip latency on {top[1]} ({top[0]/1000:.1f}ms)",
                    description="If leaf roundtrip latency is high, we recommend checking network connectivity between hosts.",
                    evidence=f"highest_leaf_latency={top[0]}us ({top[0]/1000:.1f}ms) host={top[1]}",
                    remediation="Check network hardware, NIC settings, and inter-node firewall rules.",
                    confidence=0.76,
                    nodes=[top[1]],
                    related_views=["MV_NODES", "SHOW LEAVES"],
                    tags={"environment", "performance", "network"},
                    doc_link="https://docs.singlestore.com/",
                )

    def _check_unkillable_queries(self):
        proclist = self.report.get("cluster_overview", {}).get("processlist", []) or []
        mv_proc = self.report.get("cluster_overview", {}).get("mv_processlist", []) or []
        all_rows = proclist + mv_proc
        unkillable = []
        for row in all_rows:
            kill_status = str(row.get("Kill_Status", row.get("kill_status", ""))).lower()
            if kill_status == "unkillable":
                unkillable.append(row)
        if unkillable:
            sample = ", ".join(
                str(r.get("Info", r.get("QUERY_TEXT", "")))[:80] for r in unkillable[:3]
            )
            self._add(
                checker_id="unkillableQueries",
                severity="critical",
                category="Query",
                title=f"Unkillable queries detected ({len(unkillable)})",
                description="Unkillable queries indicate long-running processes that render other queries unkillable. We recommend identifying and addressing long-running processes.",
                evidence=f"unkillable_count={len(unkillable)} sample={sample}",
                remediation="Identify root cause of unkillable queries via SHOW PROCESSLIST and review the query plan for optimization opportunities.",
                confidence=0.92,
                nodes=[],
                related_views=["MV_PROCESSLIST", "informationSchemaProcesslist"],
                tags={"query", "availability"},
                doc_link="https://docs.singlestore.com/",
            )

    def correlate(self):
        if not self.findings:
            return

        # Basic root-cause correlation to suppress noisy alerts
        offline_checker_ids = {"leavesNotOnline", "offlineAggregators", "userDatabaseRedundancy"}
        has_offline_nodes = any(f.get("checker_id") in offline_checker_ids for f in self.findings)
        has_port_blocking = any(f.get("checker_id") == "firewallPortBlocking" for f in self.findings)
        
        if has_offline_nodes:
            # Suppress dependent alerts that are symptoms of offline nodes
            suppressed_checkers = {"disconnectedReplicationSlaves", "replicationLag", "blockedQueries", "queuedQueries"}
            self.findings = [f for f in self.findings if f.get("checker_id") not in suppressed_checkers]
        elif has_port_blocking:
            # When a clear network root cause is present, reduce secondary replication noise.
            suppressed_checkers = {"disconnectedReplicationSlaves"}
            self.findings = [f for f in self.findings if f.get("checker_id") not in suppressed_checkers]

        by_tag = defaultdict(list)
        by_node = defaultdict(list)
        for item in self.findings:
            for tag in item.get("priority_tags", []):
                by_tag[tag].append(item["id"])
            for node in item.get("nodes", []):
                by_node[node].append(item["id"])
        for item in self.findings:
            linked = set()
            for tag in item.get("priority_tags", []):
                linked.update(by_tag.get(tag, []))
            for node in item.get("nodes", []):
                linked.update(by_node.get(node, []))
            linked.discard(item["id"])
            if linked:
                item["related_findings"] = sorted(linked)[:8]
                item["risk_score"] = min(100, item["risk_score"] + min(8, len(linked)))

        # ── Incident clustering ──────────────────────────────────────
        # Group findings into incident clusters using shared tags + shared nodes.
        # Each cluster gets a root-cause candidate (highest risk_score) and a
        # human-readable summary, so the engineer sees "3 findings → 1 incident"
        # instead of 3 disconnected rows.
        self._build_incident_clusters(by_tag, by_node)

    def _build_incident_clusters(self, by_tag: dict, by_node: dict):
        """Union-Find clustering on shared tags and shared nodes.

        Two findings are in the same cluster if they share a tag or a node.
        Each cluster is annotated with a root-cause candidate and summary.
        """
        parent = {}
        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Union by shared tags (weight: tags are strong correlation signals)
        for ids in by_tag.values():
            if len(ids) < 2:
                continue
            root_id = ids[0]
            for other_id in ids[1:]:
                union(root_id, other_id)

        # Union by shared nodes
        for ids in by_node.values():
            if len(ids) < 2:
                continue
            root_id = ids[0]
            for other_id in ids[1:]:
                union(root_id, other_id)

        # Group findings by cluster root
        clusters = defaultdict(list)
        for item in self.findings:
            clusters[find(item["id"])].append(item)

        # Only keep clusters with 2+ findings (singletons are not "incidents")
        incident_clusters = []
        for root, members in clusters.items():
            if len(members) < 2:
                continue
            # Root-cause candidate: highest risk_score, then critical severity
            root_cause = max(
                members,
                key=lambda f: (
                    f.get("severity") == "critical",
                    f.get("risk_score", 0),
                    len(f.get("priority_tags", [])),
                ),
            )
            # Cluster summary
            tags_in_cluster = set()
            nodes_in_cluster = set()
            for m in members:
                tags_in_cluster.update(m.get("priority_tags", []))
                nodes_in_cluster.update(m.get("nodes", []))
            top_tags = sorted(tags_in_cluster)[:3]
            summary = (
                f"{len(members)} findings related to {', '.join(top_tags) or root_cause.get('category', 'unknown')}"
                f" on {', '.join(sorted(nodes_in_cluster)[:3]) or 'cluster'}"
            )
            cluster_id = f"INC-{len(incident_clusters) + 1:03d}"
            incident_clusters.append({
                "cluster_id": cluster_id,
                "root_cause_checker_id": root_cause.get("checker_id", ""),
                "root_cause_title": root_cause.get("title", ""),
                "summary": summary,
                "member_ids": sorted(m["id"] for m in members),
                "member_count": len(members),
                "max_risk_score": max(m.get("risk_score", 0) for m in members),
                "dominant_severity": root_cause.get("severity", "info"),
                "tags": sorted(tags_in_cluster),
                "nodes": sorted(nodes_in_cluster),
            })
            # Stamp each member with its cluster_id
            for m in members:
                m.setdefault("triage", {})
                m["triage"]["cluster_id"] = cluster_id

        # Sort clusters by max risk (descending) then by member count
        incident_clusters.sort(key=lambda c: (-c["max_risk_score"], -c["member_count"]))
        self.incident_clusters = incident_clusters

    def sort_and_finalize(self):
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        self.findings.sort(
            key=lambda x: (
                severity_order.get(x.get("severity", "info"), 2),
                -x.get("risk_score", 0),
                x.get("checker_id", ""),
            )
        )
        for idx, item in enumerate(self.findings, 1):
            item["id"] = idx
            tags = set(item.get("priority_tags", []))
            item["fix_first"] = (
                item.get("severity") == "critical" or
                ("availability" in tags or "data-loss" in tags or "storage" in tags or "memory" in tags or "replication" in tags)
            ) and int(item.get("risk_score", 0)) >= 70

    def _node_show_vars(self, node: dict) -> dict:
        vars_all = node.get("show_variables_all")
        if isinstance(vars_all, dict) and vars_all:
            return vars_all
        return node.get("show_variables", {}) or {}

    def _check_cluster_memory_usage(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            mem = node.get("metrics", {}).get("memory", {}) or {}
            used_pct = float(mem.get("used_pct", 0) or 0)
            if used_pct <= 80:
                continue
            severity = "critical" if used_pct > 90 else "warning"
            vars_map = self._node_show_vars(node)
            max_mem_raw = str(vars_map.get("maximum_memory", "0"))
            max_mem_mb = _to_mb(max_mem_raw)
            total_mb = float(mem.get("total_mb", 0) or 0)
            ratio = (max_mem_mb / total_mb * 100) if total_mb > 0 and max_mem_mb > 0 else 0
            if ratio > 90 and severity == "warning":
                severity = "critical"
            rec = f"Node {host}: memory {used_pct:.1f}% used"
            if ratio > 0:
                rec += f", maximum_memory to RAM ratio {ratio:.1f}%"
            self._add(
                checker_id="clusterMemoryUsage",
                severity=severity,
                category="Memory",
                title=f"High cluster memory pressure on {host}",
                description="Memory usage is above SingleStore safety thresholds and may trigger OOM or query failures.",
                evidence=rec,
                remediation="Lower maximum_memory to <=85% of RAM, rebalance workload, and investigate memory-heavy queries.",
                confidence=0.92,
                nodes=[host],
                related_views=["MV_SYSINFO_MEM", "showVariables", "free"],
                tags={"memory", "availability"},
                doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/memory-management/",
            )

    def _check_disk_usage_and_inodes(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            for disk in node.get("metrics", {}).get("disk", []):
                mount = disk.get("mounted_on", "")
                use_pct = _to_float(disk.get("use_pct"))
                inode_pct = _to_float(disk.get("iuse_pct"))
                if use_pct > 80:
                    severity = "critical" if use_pct > 90 else "warning"
                    self._add(
                        checker_id="diskUsage",
                        severity=severity,
                        category="Storage",
                        title=f"Disk usage high on {host} {mount}",
                        description="High disk usage can cause write stalls, replication lag, and node instability.",
                        evidence=f"{host} {mount}: {use_pct:.1f}% used ({disk.get('used', '?')} of {disk.get('size', '?')})",
                        remediation="Free disk space on data mounts first, then rebalance data and expand storage.",
                        confidence=0.96,
                        nodes=[host],
                        related_views=["df", "nodeDirectoriesDiskUsage"],
                        tags={"storage", "availability", "data-loss"},
                        doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/node-management/adding-disk-space/",
                    )
                if inode_pct > 70:
                    self._add(
                        checker_id="diskInodesUsage",
                        severity="critical" if inode_pct > 85 else "warning",
                        category="Storage",
                        title=f"Inode usage high on {host} {mount}",
                        description="Inode exhaustion can break file creation even when disk space appears available.",
                        evidence=f"{host} {mount}: inode use {inode_pct:.1f}%",
                        remediation="Clean directories with many small files and increase filesystem inode capacity.",
                        confidence=0.9,
                        nodes=[host],
                        related_views=["df"],
                        tags={"storage", "availability"},
                    )

    def _check_disk_latency(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            rows = node.get("metrics", {}).get("disk_latency", []) or []
            if not rows:
                continue
            for row in rows:
                device = row.get("device", "unknown")
                read_ms = _to_float(row.get("read_await_ms"))
                write_ms = _to_float(row.get("write_await_ms"))
                util = _to_float(row.get("util_pct"))
                rota = int(_to_float(row.get("rota")))
                ssd = rota == 0
                fail_read = ssd and read_ms > 5
                fail_write = ssd and write_ms > 5
                warn_read = (not ssd and read_ms > 20) or read_ms > 10
                warn_write = (not ssd and write_ms > 20) or write_ms > 10
                warn_util = util > 70
                if not any([fail_read, fail_write, warn_read, warn_write, warn_util]):
                    continue
                sev = "critical" if (fail_read or fail_write) else "warning"
                self._add(
                    checker_id="diskLatencyRead" if read_ms >= write_ms else "diskLatencyWrite",
                    severity=sev,
                    category="Storage",
                    title=f"Disk latency bottleneck on {host} device {device}",
                    description="Storage await/util metrics indicate possible I/O saturation.",
                    evidence=f"read_await={read_ms:.2f}ms write_await={write_ms:.2f}ms util={util:.1f}% rota={rota}",
                    remediation="Move hot data to faster storage, reduce write amplification, and verify mount/data placement.",
                    confidence=0.82,
                    nodes=[host],
                    related_views=["diskLatency", "lsblkRota"],
                    tags={"storage", "performance"},
                )

    def _check_node_online_status(self):
        mv_nodes = self.report.get("cluster_overview", {}).get("nodes_detail", []) or []
        events = self.report.get("events", []) or []
        now_ts = _report_time(self.report)
        for row in mv_nodes:
            node_state = str(row.get("state", "")).upper()
            node_type = str(row.get("type", "")).upper()
            host = row.get("ip_addr") or row.get("id") or "unknown"
            if "LEAF" in node_type and node_state != "ONLINE":
                evt = _latest_event_for_node(events, host)
                detail = f"leaf state={node_state}"
                if evt:
                    detail += f"; latest event={evt.get('EVENT_TYPE', evt.get('EVENT', 'unknown'))}"
                    age_min = _minutes_between(now_ts, evt.get("EVENT_TIME") or evt.get("TIMESTAMP"))
                    if age_min is not None:
                        detail += f" ({age_min} minutes ago)"
                self._add(
                    checker_id="leavesNotOnline",
                    severity="critical",
                    category="Availability",
                    title=f"Leaf node offline or degraded: {host}",
                    description="Offline leaf nodes can remove redundancy and impact query availability.",
                    evidence=detail,
                    remediation="Restore leaf connectivity/process health, then validate redundancy and affected databases.",
                    confidence=0.9,
                    nodes=[host],
                    related_views=["MV_NODES", "MV_EVENTS", "SHOW LEAVES"],
                    tags={"availability", "replication", "data-loss"},
                )
            if node_type in ("MA", "MASTER", "CA", "AGGREGATOR") and node_state != "ONLINE":
                criticality = "Master Aggregator" if node_type in ("MA", "MASTER") else "Child Aggregator"
                self._add(
                    checker_id="offlineAggregators",
                    severity="critical" if criticality == "Master Aggregator" else "warning",
                    category="Availability",
                    title=f"{criticality} offline: {host}",
                    description="Aggregator availability directly affects SQL routing and cluster control operations.",
                    evidence=f"{criticality} state={node_state}",
                    remediation="Recover aggregator immediately; prioritize master aggregator before downstream symptoms.",
                    confidence=0.95,
                    nodes=[host],
                    related_views=["SHOW AGGREGATORS", "MV_NODES"],
                    tags={"availability", "query"},
                )

    def _check_database_redundancy_and_state(self):
        dbs = self.report.get("databases", []) or []
        cluster_status = self.report.get("cluster_overview", {}).get("cluster_status", []) or []
        if cluster_status:
            unsafe = [r for r in cluster_status if str(r.get("State", "")).upper() not in ("ONLINE", "HEALTHY")]
            if unsafe:
                db_counter = defaultdict(int)
                for row in unsafe:
                    db_counter[row.get("Database", "unknown")] += 1
                top = ", ".join(f"{k}:{v}" for k, v in sorted(db_counter.items(), key=lambda x: x[1], reverse=True)[:6])
                self._add(
                    checker_id="userDatabaseRedundancy",
                    severity="critical",
                    category="Replication",
                    title=f"Databases with partition redundancy risk ({len(unsafe)} partitions)",
                    description="Partitions in non-healthy state indicate no safe redundant copy for part of the data.",
                    evidence=f"Affected database partition counts: {top}",
                    remediation="Run EXPLAIN/RESTORE REDUNDANCY per affected database and recover unhealthy nodes first.",
                    confidence=0.93,
                    nodes=[],
                    related_views=["showClusterStatus", "MV_CLUSTER_STATUS"],
                    tags={"replication", "data-loss", "availability"},
                )
        pending = []
        unrecoverable = []
        for row in dbs:
            status = str(row.get("Status", row.get("STATE", ""))).upper()
            name = row.get("Database", row.get("DATABASE_NAME", "unknown"))
            if status == "UNRECOVERABLE":
                unrecoverable.append(name)
            if status == "PENDING":
                pending.append(name)
        if unrecoverable:
            self._add(
                checker_id="unrecoverableDatabases",
                severity="critical",
                category="Availability",
                title="Unrecoverable databases detected",
                description="Databases in UNRECOVERABLE state require immediate restore/recovery action.",
                evidence=", ".join(sorted(unrecoverable)[:12]),
                remediation="Restore from backup or perform support-guided recovery before further write activity.",
                confidence=0.97,
                nodes=[],
                related_views=["showDatabasesExtended", "showDatabaseStatus"],
                tags={"data-loss", "availability"},
            )
        if pending:
            self._add(
                checker_id="pendingDatabases",
                severity="warning",
                category="Availability",
                title="Databases stuck in PENDING state",
                description="Databases remaining in PENDING can signal startup, recovery, or metadata issues.",
                evidence=", ".join(sorted(pending)[:12]),
                remediation="Inspect database state transitions and supporting node health/events.",
                confidence=0.74,
                nodes=[],
                related_views=["showDatabasesExtended"],
                tags={"availability"},
            )
        names = [str(row.get("Database") or row.get("DATABASE_NAME") or "") for row in dbs]
        if names and "cluster_management" not in {n.lower() for n in names}:
            self._add(
                checker_id="missingClusterDb",
                severity="critical",
                category="Configuration",
                title="cluster_management database missing",
                description="Missing cluster_management indicates control-plane metadata risk.",
                evidence=f"Databases detected: {len(names)}",
                remediation="Recreate/repair cluster metadata database using supported recovery procedure.",
                confidence=0.85,
                nodes=[],
                related_views=["showDatabasesExtended", "informationSchemaDistributedDatabases"],
                tags={"availability", "configuration"},
            )

    def _check_swap_faults_committed_memory(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            mem = node.get("metrics", {}).get("memory", {}) or {}
            swap_used_pct = _to_float(mem.get("swap_used_pct"))
            swap_used_mb = _to_float(mem.get("swap_used_mb"))
            pgmaj = _to_float((node.get("metrics", {}).get("major_page_faults") or {}).get("pgmajflt_per_sec"))
            if swap_used_pct > 5 or swap_used_mb > 0:
                sev = "critical" if swap_used_pct > 20 else "warning"
                if pgmaj > 0:
                    sev = "critical"
                evidence = f"swap_used_pct={swap_used_pct:.1f}% swap_used_mb={swap_used_mb:.1f} pgmajflt/s={pgmaj:.2f}"
                self._add(
                    checker_id="swapUsage",
                    severity=sev,
                    category="Memory",
                    title=f"Swap activity detected on {host}",
                    description="Swap usage indicates memory pressure and can significantly degrade query latency.",
                    evidence=evidence,
                    remediation="Reduce memory pressure, tune maximum_memory, and investigate high-memory workloads.",
                    confidence=0.9,
                    nodes=[host],
                    related_views=["swapUsage", "majorPageFaults", "free"],
                    tags={"memory", "performance", "availability"},
                )
            if pgmaj > 0:
                self._add(
                    checker_id="majorPageFaults",
                    severity="warning",
                    category="Memory",
                    title=f"Major page faults on {host}",
                    description="Major page faults indicate disk-backed memory access and potential pressure.",
                    evidence=f"pgmajflt/s={pgmaj:.2f}",
                    remediation="Correlate with swap and memory pressure; reduce cache churn and memory overcommit.",
                    confidence=0.86,
                    nodes=[host],
                    related_views=["majorPageFaults", "swapUsage"],
                    tags={"memory", "performance"},
                )
            commit_pct = _to_float((node.get("metrics", {}).get("memory_committed") or {}).get("commit_pct"))
            overcommit = _to_float((node.get("os_checks", {}).get("sysctl", {}).get("vm.overcommit_memory") or {}).get("numeric"))
            if commit_pct > 100:
                self._add(
                    checker_id="memoryCommitted",
                    severity="critical" if int(overcommit) == 2 else "warning",
                    category="Memory",
                    title=f"Committed memory exceeds 100% on {host}",
                    description="Overcommitted memory can trigger allocation failures and OOM events.",
                    evidence=f"commit={commit_pct:.1f}% vm.overcommit_memory={int(overcommit)}",
                    remediation="Reduce memory commitments and set vm.overcommit policy to recommended values.",
                    confidence=0.81,
                    nodes=[host],
                    related_views=["memoryCommitted", "sysctl"],
                    tags={"memory", "availability"},
                )

    def _check_blocked_and_long_queries(self):
        blocked = self.report.get("cluster_overview", {}).get("blocked_queries", []) or []
        if blocked:
            chains = defaultdict(list)
            unkillable = 0
            for row in blocked:
                blocker = row.get("blocking_query_id") or row.get("blocking_query") or "unknown"
                chains[blocker].append(row)
                if str(row.get("kill_status", "")).lower() == "unkillable":
                    unkillable += 1
            chain_sizes = sorted((len(v) for v in chains.values()), reverse=True)
            self._add(
                checker_id="blockedQueries",
                severity="warning",
                category="Query",
                title=f"Blocked queries detected ({len(blocked)} rows)",
                description="Blocking chains can cascade into latency spikes and queue growth.",
                evidence=f"chains={len(chains)} largest_chain={chain_sizes[0] if chain_sizes else 0} unkillable={unkillable}",
                remediation="Resolve root blockers first; terminate or rewrite blocking transactions where safe.",
                confidence=0.88,
                nodes=[],
                related_views=["MV_BLOCKED_QUERIES"],
                tags={"query", "performance"},
            )
        long_rows = []
        for row in self.report.get("queries", []) or []:
            elapsed = _to_float(row.get("ELAPSED_TIME", row.get("elapsed_time", row.get("ElapsedTime", 0))))
            if elapsed > 60:
                long_rows.append((elapsed, row))
        if long_rows:
            long_rows.sort(key=lambda x: x[0], reverse=True)
            top = long_rows[0][1]
            sev = "critical" if long_rows[0][0] > 600 else "warning"
            text = str(top.get("QUERY_TEXT", top.get("query_text", "")))[:220]
            usr = top.get("USER", top.get("user", "?"))
            dbn = top.get("DATABASE_NAME", top.get("database", "?"))
            self._add(
                checker_id="longRunningQueries",
                severity=sev,
                category="Query",
                title=f"Long-running queries detected ({len(long_rows)})",
                description="Long-running queries can monopolize memory/CPU and block downstream workloads.",
                evidence=f"top_elapsed={long_rows[0][0]:.1f}s user={usr} db={dbn} query={text}",
                remediation="Tune/terminate offending queries, add indexes, and validate workload management limits.",
                confidence=0.87,
                nodes=[],
                related_views=["MV_QUERIES", "MV_PROCESSLIST"],
                tags={"query", "performance", "memory"},
            )

    def _check_query_queues(self):
        pools = self.report.get("resource_pools", []) or []
        offenders = []
        for row in pools:
            depth = _to_float(row.get("QUEUE_DEPTH", row.get("queue_depth", row.get("QUEUE", 0))))
            if depth > 5:
                offenders.append((depth, row.get("POOL_NAME", row.get("name", "unknown"))))
        if offenders:
            offenders.sort(reverse=True)
            max_depth = offenders[0][0]
            self._add(
                checker_id="queuedQueries",
                severity="critical" if max_depth > 50 else "warning",
                category="Workload",
                title="Resource pool queue depth is elevated",
                description="High queue depth means queries are waiting for execution slots and latency increases.",
                evidence="; ".join(f"{name}:{int(depth)}" for depth, name in offenders[:8]),
                remediation="Increase pool capacity carefully, tune expensive queries, and reduce concurrent burst load.",
                confidence=0.78,
                nodes=[],
                related_views=["SHOW RESOURCE POOLS", "MV_WORKLOAD_MANAGEMENT_STATUS"],
                tags={"query", "performance"},
            )

    def _check_replication_health(self):
        rows = self.report.get("replication_status", []) or []
        lag_rows = []
        paused = []
        disconnected = []
        for row in rows:
            lag = _to_float(row.get("LAG_SECONDS", row.get("SECONDS_BEHIND_MASTER", row.get("lag_seconds", 0))))
            if lag > 5:
                lag_rows.append((lag, row))
            status_blob = f"{row}".lower()
            if "paused" in status_blob:
                paused.append(row)
            if "disconnect" in status_blob:
                disconnected.append(row)
        if lag_rows:
            lag_rows.sort(key=lambda x: x[0], reverse=True)
            max_lag = lag_rows[0][0]
            self._add(
                checker_id="replicationLag",
                severity="critical" if max_lag > 30 else "warning",
                category="Replication",
                title=f"Replication lag detected (max {max_lag:.1f}s)",
                description="Replication lag increases failover recovery point objective and data divergence risk.",
                evidence=f"rows_over_threshold={len(lag_rows)} max_lag={max_lag:.1f}s",
                remediation="Stabilize storage/network bottlenecks first, then inspect replication workers and source load.",
                confidence=0.89,
                nodes=[],
                related_views=["MV_REPLICATION_STATUS", "showReplicationStatus"],
                tags={"replication", "availability", "storage"},
            )
        if paused:
            self._add(
                checker_id="replicationPausedDatabases",
                severity="warning",
                category="Replication",
                title=f"Replication paused on {len(paused)} database link(s)",
                description="Paused replication leaves secondaries stale until resumed.",
                evidence=f"paused_rows={len(paused)}",
                remediation="Resume replication after validating source/target health and backlog size.",
                confidence=0.75,
                nodes=[],
                related_views=["MV_REPLICATION_MANAGEMENT"],
                tags={"replication"},
            )
        if disconnected:
            self._add(
                checker_id="disconnectedReplicationSlaves",
                severity="warning",
                category="Replication",
                title=f"Disconnected replication links detected ({len(disconnected)})",
                description="Disconnected replication slaves can break DR posture.",
                evidence=f"disconnected_rows={len(disconnected)}",
                remediation="Repair connectivity/auth and re-establish replication streams.",
                confidence=0.78,
                nodes=[],
                related_views=["showReplicationStatus", "MV_REPLICATION_STATUS"],
                tags={"replication", "availability"},
            )

    def _check_network_port_blocking(self):
        overview = self.report.get("cluster_overview", {}) or {}
        rebalance_rows = overview.get("rebalance_status", []) or []
        log_rows = self.report.get("logs", []) or []

        blocked_pairs = defaultdict(int)
        blocked_ports = defaultdict(int)
        samples = []

        sync_failure_re = re.compile(
            r"Slave database .*? on (?P<src_host>[^:\s]+):(?P<src_port>\d+)\s+could not synchron(?:ize|ise)\s+with Master database on\s+(?P<dst_host>[^:\s]+):(?P<dst_port>\d+)",
            re.IGNORECASE,
        )

        def _consume_text(blob: str):
            if not blob:
                return
            low = blob.lower()
            # Only classify likely firewall/network transport failures.
            if not any(tok in low for tok in ("could not synchron", "connection refused", "timed out", "timeout")):
                return
            m = sync_failure_re.search(blob)
            if not m:
                return
            src_host = m.group("src_host")
            dst_host = m.group("dst_host")
            src_port = m.group("src_port")
            dst_port = m.group("dst_port")
            pair_key = f"{src_host}:{src_port}->{dst_host}:{dst_port}"
            blocked_pairs[pair_key] += 1
            blocked_ports[src_port] += 1
            blocked_ports[dst_port] += 1
            if len(samples) < 4:
                samples.append(blob[:220])

        for row in rebalance_rows:
            status = str(row.get("Status", row.get("status", "")))
            _consume_text(status)

        for row in log_rows:
            _consume_text(str(row.get("message", "")))

        if not blocked_pairs:
            return

        top_pairs = sorted(blocked_pairs.items(), key=lambda kv: kv[1], reverse=True)
        top_ports = sorted(blocked_ports.items(), key=lambda kv: kv[1], reverse=True)
        evidence = (
            f"suspected_blocked_pairs={'; '.join(k for k, _ in top_pairs[:5])}; "
            f"suspected_ports={','.join(p for p, _ in top_ports[:6])}; "
            f"sample={samples[0] if samples else ''}"
        )
        remediation = (
            "Validate bidirectional TCP reachability for the listed host:port pairs, "
            "review host/network firewall ACLs, then rerun EXPLAIN/SHOW REBALANCE STATUS "
            "to confirm synchronization recovery."
        )
        nodes = sorted({
            endpoint.split(":")[0]
            for pair, _ in top_pairs
            for endpoint in pair.split("->")
        })
        self._add(
            checker_id="firewallPortBlocking",
            severity="critical",
            category="Network",
            title="Inter-node synchronization blocked by suspected network/firewall rules",
            description="Rebalance/replication sync failures indicate blocked inter-node connectivity on required database ports.",
            evidence=evidence,
            remediation=remediation,
            confidence=0.92,
            nodes=nodes,
            related_views=["SHOW REBALANCE STATUS", "EXPLAIN REBALANCE PARTITIONS", "showReplicationStatus", "MV_EVENTS"],
            tags={"availability", "replication", "environment"},
        )

    def _check_cpu_idle_and_iowait(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            cpu = (node.get("metrics", {}).get("cpu_utilization") or {})
            if not cpu:
                cpu = node.get("metrics", {}).get("top", {}).get("cpu", {}) or {}
            idle = _to_float(cpu.get("idle", cpu.get("id")))
            iowait = _to_float(cpu.get("iowait", cpu.get("wa")))
            if idle and idle < 5:
                self._add(
                    checker_id="cpuIdle",
                    severity="warning",
                    category="Performance",
                    title=f"CPU idle below 5% on {host}",
                    description="CPU headroom is exhausted and workload growth can trigger severe latency.",
                    evidence=f"user={_to_float(cpu.get('user', cpu.get('us'))):.1f}% system={_to_float(cpu.get('system', cpu.get('sy'))):.1f}% iowait={iowait:.1f}% idle={idle:.1f}%",
                    remediation="Tune expensive queries and scale out before sustained saturation.",
                    confidence=0.78,
                    nodes=[host],
                    related_views=["cpuUtilization", "top"],
                    tags={"performance", "query"},
                )
            if iowait > 20:
                self._add(
                    checker_id="cpuIdle",
                    severity="warning",
                    category="Performance",
                    title=f"High CPU iowait on {host}",
                    description="High iowait indicates a storage bottleneck rather than pure CPU saturation.",
                    evidence=f"iowait={iowait:.1f}%",
                    remediation="Investigate disk latency/utilization and rebalance I/O-heavy operations.",
                    confidence=0.8,
                    nodes=[host],
                    related_views=["cpuUtilization", "diskLatency"],
                    tags={"performance", "storage"},
                )

    def _check_default_variables_and_interpreter_mode(self):
        expected = {
            "attach_rebalance_delay": "120",
            "auto_attach": "ON",
            "failure_detection": "ON",
            "columnstore_segment_rows": "1024000",
        }
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            vars_map = self._node_show_vars(node)
            interpreter = str(vars_map.get("interpreter_mode", "")).lower()
            if interpreter and interpreter != "interpret_first":
                self._add(
                    checker_id="interpreterMode",
                    severity="warning",
                    category="Configuration",
                    title=f"interpreter_mode is non-recommended on {host}",
                    description="interpreter_mode should be interpret_first for recommended behavior.",
                    evidence=f"interpreter_mode={vars_map.get('interpreter_mode')}",
                    remediation="Set interpreter_mode=interpret_first and validate workload behavior.",
                    confidence=0.84,
                    nodes=[host],
                    related_views=["showVariables"],
                    tags={"configuration", "performance"},
                )
            mismatches = []
            for key, want in expected.items():
                cur = str(vars_map.get(key, ""))
                if cur and cur.upper() != want.upper():
                    mismatches.append(f"{key}={cur} expected={want}")
            if mismatches:
                self._add(
                    checker_id="defaultVariables",
                    severity="warning",
                    category="Configuration",
                    title=f"Non-default critical variables on {host}",
                    description="Key cluster variables deviate from recommended defaults and may impact stability/performance.",
                    evidence="; ".join(mismatches),
                    remediation="Align these variables with recommended defaults unless there is a deliberate documented exception.",
                    confidence=0.89,
                    nodes=[host],
                    related_views=["showVariables"],
                    tags={"configuration"},
                )

    def _check_preinstall_kernel_memory_network(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            thp = node.get("os_checks", {}).get("thp", {}) or {}
            enabled = str(thp.get("enabled", ""))
            defrag = str(thp.get("defrag", ""))
            is_enabled_never = "[never]" in enabled or thp.get("active") == "never" or thp.get("status") == "disabled"
            is_defrag_never = "[never]" in defrag or thp.get("active_defrag") == "never" or thp.get("status") == "disabled"
            if not (is_enabled_never and is_defrag_never):
                self._add_unique(
                    checker_id="transparentHugepage",
                    severity="critical",
                    category="Environment",
                    title=f"Transparent Huge Pages enabled on {host}",
                    description="THP causes memory latency jitter and is unsupported for production SingleStore tuning.",
                    evidence=f"enabled={enabled} defrag={defrag}",
                    remediation="Set enabled and defrag to [never] and persist via rc.local or tuned profile.",
                    confidence=0.97,
                    nodes=[host],
                    related_views=["transparentHugepage"],
                    tags={"environment", "performance"},
                )
            sysctl = node.get("os_checks", {}).get("sysctl", {}) or {}
            max_map = _to_float((sysctl.get("vm.max_map_count") or {}).get("numeric"))
            if max_map and max_map < 1_000_000_000:
                self._add_unique(
                    checker_id="vmMaxMapCount",
                    severity="critical",
                    category="Environment",
                    title=f"vm.max_map_count below minimum on {host}",
                    description="Low vm.max_map_count can cause mapping failures under load.",
                    evidence=f"vm.max_map_count={int(max_map)}",
                    remediation="Set vm.max_map_count=1000000000 and persist in /etc/sysctl.conf.",
                    confidence=0.94,
                    nodes=[host],
                    related_views=["sysctl"],
                    tags={"environment", "availability"},
                )
            overcommit = _to_float((sysctl.get("vm.overcommit_memory") or {}).get("numeric"))
            ratio = _to_float((sysctl.get("vm.overcommit_ratio") or {}).get("numeric"))
            if overcommit in (0, 1):
                self._add(
                    checker_id="vmOvercommit",
                    severity="warning",
                    category="Environment",
                    title=f"vm.overcommit_memory non-recommended on {host}",
                    description="Recommended vm.overcommit_memory is 2 with overcommit_ratio near 90.",
                    evidence=f"vm.overcommit_memory={int(overcommit)} vm.overcommit_ratio={ratio:.1f}",
                    remediation="Set vm.overcommit_memory=2 and vm.overcommit_ratio=90 where appropriate.",
                    confidence=0.83,
                    nodes=[host],
                    related_views=["sysctl"],
                    tags={"environment", "memory"},
                )
            if "vm.swappiness" in sysctl:
                swapn = _to_float((sysctl.get("vm.swappiness") or {}).get("numeric"))
                if swapn == 0 or swapn > 10:
                    self._add_unique(
                        checker_id="vmSwappiness",
                        severity="warning",
                        category="Environment",
                        title=f"vm.swappiness out of recommended range on {host}",
                        description="Recommended vm.swappiness is in the 1-10 range.",
                        evidence=f"vm.swappiness={swapn:.0f}",
                        remediation="Set vm.swappiness to a low non-zero value, typically between 1 and 10.",
                        confidence=0.86,
                        nodes=[host],
                        related_views=["sysctl"],
                        tags={"environment", "memory"},
                    )
            somax = _to_float((sysctl.get("net.core.somaxconn") or {}).get("numeric"))
            if somax and somax < 1024:
                self._add_unique(
                    checker_id="somaxconnLimit",
                    severity="warning",
                    category="Environment",
                    title=f"net.core.somaxconn too low on {host}",
                    description="Low somaxconn limits maximum connection backlog queue, which can cause connection timeouts under high spikes.",
                    evidence=f"net.core.somaxconn={int(somax)} (required >= 1024)",
                    remediation="Set net.core.somaxconn=1024 in /etc/sysctl.conf.",
                    confidence=0.85,
                    nodes=[host],
                    related_views=["sysctl"],
                    tags={"environment", "network"},
                )

    def _check_numa_ssd_filesystem(self):
        allowed_fs = {"ext4", "xfs", "tmpfs"}
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            numa_raw = (node.get("os_checks", {}).get("numa", {}) or {}).get("raw", "")
            nodes_match = re.findall(r"node\s+\d+", numa_raw.lower())
            numa_count = len(set(nodes_match))
            has_numactl_cfg = "numactl" in str((node.get("os_checks", {}).get("numa", {}) or {}).get("config", "")).lower()
            if numa_count > 1 and not has_numactl_cfg:
                self._add(
                    checker_id="numaConfiguration",
                    severity="warning",
                    category="Environment",
                    title=f"NUMA detected without binding config on {host}",
                    description="Multi-socket NUMA systems should run with explicit locality configuration.",
                    evidence=f"numa_nodes={numa_count} memsql_numa_config_present={has_numactl_cfg}",
                    remediation="Configure memsqld start with numactl binding and verify memory locality.",
                    confidence=0.76,
                    nodes=[host],
                    related_views=["numactl", "memsqlNumaConfig"],
                    tags={"environment", "performance"},
                )
            mount_rows = node.get("metrics", {}).get("mounts", []) or []
            for row in mount_rows:
                fs_type = str(row.get("fstype", "")).lower()
                mount = row.get("mount", "")
                if fs_type and fs_type not in allowed_fs:
                    self._add(
                        checker_id="filesystemType",
                        severity="critical",
                        category="Environment",
                        title=f"Unsupported filesystem type on {host} {mount}",
                        description="Only ext4, xfs, and tmpfs are supported for documented configurations.",
                        evidence=f"mount={mount} fstype={fs_type}",
                        remediation="Migrate SingleStore data directories to an officially supported filesystem.",
                        confidence=0.92,
                        nodes=[host],
                        related_views=["mount", "df"],
                        tags={"environment", "availability"},
                    )
            rota_rows = node.get("metrics", {}).get("lsblk_rota", []) or []
            for row in rota_rows:
                if int(_to_float(row.get("rota"))) == 1 and str(row.get("is_data_device", "false")).lower() == "true":
                    self._add(
                        checker_id="validateSsd",
                        severity="critical",
                        category="Environment",
                        title=f"Data directory appears to be on rotational disk on {host}",
                        description="Rotational disks are not recommended for SingleStore data paths.",
                        evidence=f"device={row.get('device')} rota=1 mount={row.get('mount')}",
                        remediation="Move data directory to SSD-backed storage.",
                        confidence=0.9,
                        nodes=[host],
                        related_views=["lsblkRota", "df", "nodeDirectoriesDiskUsage"],
                        tags={"environment", "performance", "storage"},
                    )

    def _check_cpu_kernel_model_consistency(self):
        cpu_models = defaultdict(set)
        kernels = defaultdict(set)
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            info = node.get("metrics", {}).get("cpu_info", {}) or {}
            flags = str((info.get("threading", {}) or {}).get("flags", "")).lower()
            if flags and "avx2" not in flags:
                self._add(
                    checker_id="cpuFeatures",
                    severity="warning",
                    category="Environment",
                    title=f"AVX2 not detected on {host}",
                    description="Missing AVX2 can reduce query performance for optimized execution paths.",
                    evidence=f"cpu_flags={flags[:180]}",
                    remediation="Prefer AVX2-capable hardware for performance-critical clusters.",
                    confidence=0.72,
                    nodes=[host],
                    related_views=["/proc/cpuinfo"],
                    tags={"environment", "performance"},
                )
            ht_enabled = str((info.get("threading", {}) or {}).get("hyperthreading", "")).lower()
            if ht_enabled in ("false", "off", "0"):
                self._add(
                    checker_id="cpuHyperThreading",
                    severity="warning",
                    category="Environment",
                    title=f"Hyper-threading disabled on {host}",
                    description="Disabled hyper-threading may reduce throughput for mixed OLTP/analytical workloads.",
                    evidence=f"hyperthreading={ht_enabled}",
                    remediation="Enable hyper-threading where CPU model and workload profile support it.",
                    confidence=0.68,
                    nodes=[host],
                    related_views=["cpuThreadingInfo"],
                    tags={"environment", "performance"},
                )
            model = str((info.get("threading", {}) or {}).get("model_name", "")) or str(info.get("model_name", ""))
            if model:
                cpu_models[model].add(host)
            rel = node.get("config", {}).get("os_release", "") or ""
            if rel:
                first = rel.splitlines()[0].strip()
                kernels[first].add(host)
        if len(cpu_models) > 1:
            detail = "; ".join(f"{m[:40]}: {len(h)} node(s)" for m, h in cpu_models.items())
            self._add(
                checker_id="cpuModel",
                severity="warning",
                category="Environment",
                title="Mixed CPU models detected across nodes",
                description="Heterogeneous CPU models can create uneven query latency and throughput.",
                evidence=detail,
                remediation="Use homogeneous CPU models per cluster where possible.",
                confidence=0.77,
                nodes=[],
                related_views=["cpuThreadingInfo", "/proc/cpuinfo"],
                tags={"environment", "performance"},
            )
        if len(kernels) > 1:
            detail = "; ".join(f"{k}: {len(h)} node(s)" for k, h in kernels.items())
            self._add(
                checker_id="kernelVersions",
                severity="warning",
                category="Environment",
                title="Kernel version mismatch across nodes",
                description="Kernel drift can create inconsistent scheduler/network/storage behavior.",
                evidence=detail,
                remediation="Standardize kernel versions across cluster nodes.",
                confidence=0.7,
                nodes=[],
                related_views=["osRelease"],
                tags={"environment"},
            )

    def _check_process_limits_and_processes(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            limits = node.get("config", {}).get("process_limits", {}) or {}
            soft = _to_float(limits.get("open_files_soft"))
            hard = _to_float(limits.get("open_files_hard"))
            if hard and hard < 1_024_000:
                self._add(
                    checker_id="maxOpenFiles",
                    severity="critical",
                    category="Environment",
                    title=f"nofile hard limit too low on {host}",
                    description="Insufficient nofile limits can fail high-concurrency workloads.",
                    evidence=f"soft={int(soft)} hard={int(hard)}",
                    remediation="Set memsql hard/soft nofile to >=1024000 in limits.conf and restart.",
                    confidence=0.95,
                    nodes=[host],
                    related_views=["memsqldProcessLimits", "securityLimits", "ulimit"],
                    tags={"environment", "availability"},
                )
            sec = str(node.get("os_checks", {}).get("security_limits", "")).lower()
            if sec:
                nofile_val = _extract_limit_value(sec, "nofile")
                nproc_val = _extract_limit_value(sec, "nproc")
                if nofile_val and nofile_val < 1_024_000:
                    self._add(
                        checker_id="securityLimits",
                        severity="critical",
                        category="Environment",
                        title=f"security limits nofile too low on {host}",
                        description="Configured nofile in security limits is below recommended minimum.",
                        evidence=f"nofile={nofile_val}",
                        remediation="Update limits.conf entries for memsql/wildcard users to required values.",
                        confidence=0.88,
                        nodes=[host],
                        related_views=["securityLimits"],
                        tags={"environment", "availability"},
                    )
                if nproc_val and nproc_val < 128_000:
                    self._add(
                        checker_id="securityLimits",
                        severity="critical",
                        category="Environment",
                        title=f"security limits nproc too low on {host}",
                        description="Configured nproc in security limits is below recommended minimum.",
                        evidence=f"nproc={nproc_val}",
                        remediation="Set nproc >=128000 for memsql user and reload limits.",
                        confidence=0.88,
                        nodes=[host],
                        related_views=["securityLimits"],
                        tags={"environment", "availability"},
                    )
            ps_rows = node.get("metrics", {}).get("ps", []) or []
            zombies = [r for r in ps_rows if str(r.get("stat", "")).upper().startswith("Z")]
            if zombies:
                self._add(
                    checker_id="defunctProcesses",
                    severity="warning",
                    category="System",
                    title=f"Defunct processes detected on {host}",
                    description="Zombie processes indicate parent process cleanup issues.",
                    evidence=f"zombie_count={len(zombies)} pids={','.join(str(z.get('pid')) for z in zombies[:10])}",
                    remediation="Inspect parent processes and process supervision state.",
                    confidence=0.72,
                    nodes=[host],
                    related_views=["ps aux"],
                    tags={"observability"},
                )
            proc_text = " ".join(str(r.get("cmd", "")).lower() for r in ps_rows)
            if "orchestrator" in proc_text:
                self._add(
                    checker_id="orchestratorProcesses",
                    severity="critical",
                    category="System",
                    title=f"orchestrator process found on {host}",
                    description="orchestrator alongside SingleStore is unsupported in this check profile.",
                    evidence="orchestrator process signature found in ps output",
                    remediation="Remove conflicting orchestrator service from SingleStore host.",
                    confidence=0.8,
                    nodes=[host],
                    related_views=["ps aux"],
                    tags={"environment", "availability"},
                )
            if "memsql-ops" in proc_text or "singlestore-ops" in proc_text:
                self._add(
                    checker_id="opsProcesses",
                    severity="warning",
                    category="System",
                    title=f"MemSQL Ops process detected on {host}",
                    description="Legacy Ops process is deprecated and should be removed from production hosts.",
                    evidence="ops process signature found in ps output",
                    remediation="Decommission deprecated Ops services.",
                    confidence=0.77,
                    nodes=[host],
                    related_views=["ps aux"],
                    tags={"environment"},
                )

    def _check_versions_license_and_max_memory(self):
        overview = self.report.get("cluster_overview", {}) or {}
        versions = defaultdict(set)
        max_mem_values = defaultdict(float)
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            vars_map = self._node_show_vars(node)
            max_mem_values[host] = _to_mb(vars_map.get("maximum_memory", 0))
        for row in overview.get("nodes_detail", []) or []:
            versions[str(row.get("version", ""))].add(str(row.get("ip_addr", row.get("id", ""))))
        if len([k for k in versions.keys() if k]) > 1:
            text = "; ".join(f"{v}: {len(h)} nodes" for v, h in versions.items() if v)
            self._add(
                checker_id="memsqlVersions",
                severity="warning",
                category="Configuration",
                title="Mixed SingleStore versions across nodes",
                description="Version skew can create behavior inconsistencies and upgrade risks.",
                evidence=text,
                remediation="Complete rolling upgrade quickly and keep cluster versions aligned.",
                confidence=0.93,
                nodes=[],
                related_views=["MV_NODES", "MV_VERSION_HISTORY"],
                tags={"configuration", "availability"},
            )
        non_ga = []
        for v in versions.keys():
            lv = str(v).lower()
            if any(x in lv for x in ("preview", "rc", "beta")):
                non_ga.append(v)
        if non_ga:
            self._add(
                checker_id="versionHashes",
                severity="warning",
                category="Configuration",
                title="Non-GA SingleStore version detected",
                description="Preview/RC versions may carry elevated operational risk.",
                evidence=", ".join(non_ga),
                remediation="Use GA builds for production clusters.",
                confidence=0.8,
                nodes=[],
                related_views=["MV_VERSION_HISTORY"],
                tags={"configuration"},
            )
        if max_mem_values:
            unique_vals = {round(v, 2) for v in max_mem_values.values() if v > 0}
            if len(unique_vals) > 1:
                detail = "; ".join(f"{h}={_fmt_mb(v)}" for h, v in max_mem_values.items() if v > 0)
                self._add(
                    checker_id="consistentMaxMemory",
                    severity="warning",
                    category="Configuration",
                    title="maximum_memory differs across nodes",
                    description="Inconsistent maximum_memory creates uneven memory pressure and performance behavior.",
                    evidence=detail,
                    remediation="Align maximum_memory values across leaf nodes unless intentionally segmented.",
                    confidence=0.92,
                    nodes=[],
                    related_views=["showVariables"],
                    tags={"configuration", "memory"},
                )
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            mem = node.get("metrics", {}).get("memory", {}) or {}
            total = _to_float(mem.get("total_mb"))
            vars_map = self._node_show_vars(node)
            max_mem = _to_mb(vars_map.get("maximum_memory", 0))
            if total > 0 and max_mem > 0:
                ratio = max_mem / total * 100
                if ratio > 90:
                    rec = math.floor(total / 1024 * 0.85)
                    self._add(
                        checker_id="maxMemorySettings",
                        severity="warning",
                        category="Configuration",
                        title=f"maximum_memory too high relative to RAM on {host}",
                        description="Aggressive maximum_memory leaves little headroom for OS and background tasks.",
                        evidence=f"maximum_memory={_fmt_mb(max_mem)} RAM={_fmt_mb(total)} ratio={ratio:.1f}% recommended<={rec}GB",
                        remediation="Reduce maximum_memory to approximately 85% of physical RAM.",
                        confidence=0.95,
                        nodes=[host],
                        related_views=["showVariables", "free"],
                        tags={"memory", "configuration"},
                    )
        lic = (self.report.get("config_health", {}) or {}).get("license")
        if lic and lic.get("days_remaining") is not None:
            days = int(lic.get("days_remaining"))
            if days < 0:
                sev = "critical"
            elif days < 30:
                sev = "warning"
            else:
                sev = "info"
            if sev in ("critical", "warning"):
                self._add(
                    checker_id="validLicense",
                    severity=sev,
                    category="Configuration",
                    title="License expiry risk",
                    description="License expiration can halt cluster operations depending on plan limits.",
                    evidence=f"type={lic.get('type')} expires={lic.get('expiry_date')} days_remaining={days}",
                    remediation="Renew or update license before expiry and validate node capacity limits.",
                    confidence=0.98,
                    nodes=[],
                    related_views=["licenseMetadata"],
                    tags={"configuration", "availability"},
                )

    def _check_malloc_columnstore_ha_partitions(self):
        alloc = self.report.get("alloc_memory", {}) or {}
        for node in alloc.get("per_node", []):
            total = _to_float(node.get("total_bytes"))
            host = node.get("hostname", "unknown")
            if total > 2 * 1024 * 1024 * 1024:
                self._add(
                    checker_id="mallocActiveMemory",
                    severity="warning",
                    category="Memory",
                    title=f"High C allocator active memory on {host}",
                    description="High allocator memory outside managed buffers can indicate leak-like behavior or unusual allocation patterns.",
                    evidence=f"alloc_total_bytes={int(total)}",
                    remediation="Inspect allocator-heavy code paths and correlate with query bursts and code generation activity.",
                    confidence=0.72,
                    nodes=[host],
                    related_views=["MV_GLOBAL_STATUS", "MV_SYSINFO_MEM"],
                    tags={"memory", "performance"},
                )
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            vars_map = self._node_show_vars(node)
            csr = str(vars_map.get("columnstore_segment_rows", ""))
            if csr and csr != "1024000":
                self._add(
                    checker_id="columnstoreSegmentRows",
                    severity="warning",
                    category="Configuration",
                    title=f"columnstore_segment_rows non-default on {host}",
                    description="Non-default columnstore segment sizing may impact merge cadence and query performance.",
                    evidence=f"columnstore_segment_rows={csr}",
                    remediation="Use default 1024000 unless workload-specific benchmarking justifies change.",
                    confidence=0.86,
                    nodes=[host],
                    related_views=["showVariables", "MV_COLUMNSTORE_MERGE_STATUS"],
                    tags={"configuration", "performance"},
                )
        ag = self.report.get("availability_groups", []) or []
        if not ag:
            self._add(
                checker_id="highAvailability",
                severity="info",
                category="Availability",
                title="HA groups not detected",
                description="No availability groups detected; deployment may be single-copy or non-HA.",
                evidence="informationSchemaAvailabilityGroups returned no rows",
                remediation="Configure availability groups and redundancy according to SLA requirements.",
                confidence=0.6,
                nodes=[],
                related_views=["informationSchemaAvailabilityGroups", "MV_NODES"],
                tags={"availability"},
            )
        partitions = self.report.get("partitions", {}) or {}
        dup_db = []
        unmapped = []
        for dbn, data in partitions.items():
            parts = data.get("partitions", []) if isinstance(data, dict) else []
            seen = set()
            for p in parts:
                pid = p.get("Partition", p.get("PARTITION_ID"))
                master = p.get("Master", p.get("MASTER_HOST", p.get("MASTER", "")))
                if pid in seen:
                    dup_db.append(dbn)
                seen.add(pid)
                if master in ("", None, "NULL"):
                    unmapped.append((dbn, pid))
        if dup_db:
            self._add(
                checker_id="duplicatePartitionDatabase",
                severity="warning",
                category="Availability",
                title="Duplicate partition IDs detected",
                description="Duplicate partition metadata can indicate inconsistent partition map state.",
                evidence=", ".join(sorted(set(dup_db))[:10]),
                remediation="Inspect partition metadata and reconcile partition maps.",
                confidence=0.8,
                nodes=[],
                related_views=["showPartitions"],
                tags={"availability", "replication"},
            )
        if unmapped:
            self._add(
                checker_id="unmappedMasterPartitions",
                severity="critical",
                category="Availability",
                title="Partitions without master assignment detected",
                description="Partitions missing a master are unavailable for normal operations.",
                evidence=f"count={len(unmapped)} sample={unmapped[0][0]}:{unmapped[0][1]}",
                remediation="Recover master assignments by restoring node health and redundancy state.",
                confidence=0.94,
                nodes=[],
                related_views=["showClusterStatus", "MV_CLUSTER_STATUS", "showPartitions"],
                tags={"availability", "data-loss", "replication"},
            )

    def _check_running_operations(self):
        processlist = self.report.get("cluster_overview", {}).get("processlist", []) or []
        running_ddl = []
        for row in processlist:
            query = str(row.get("Info", row.get("QUERY_TEXT", row.get("query", "")))).upper()
            if "ALTER TABLE" in query or "TRUNCATE" in query:
                running_ddl.append(query[:120])
        if running_ddl:
            self._add(
                checker_id="runningAlterOrTruncate",
                severity="info",
                category="Operations",
                title="ALTER/TRUNCATE operations currently running",
                description="DDL operations can explain lock waits and transient workload slowdowns.",
                evidence=f"count={len(running_ddl)} sample={running_ddl[0]}",
                remediation="Coordinate heavy DDL windows with workload expectations.",
                confidence=0.73,
                nodes=[],
                related_views=["MV_PROCESSLIST"],
                tags={"query"},
            )
        backups = self.report.get("backup_history", []) or []
        in_progress = [b for b in backups if str(b.get("STATUS", "")).lower() in ("running", "in_progress", "in progress")]
        if in_progress:
            self._add(
                checker_id="runningBackup",
                severity="info",
                category="Operations",
                title="Backup currently in progress",
                description="Active backups can temporarily affect storage and query latency.",
                evidence=f"in_progress_backups={len(in_progress)}",
                remediation="Account for backup I/O in workload diagnostics.",
                confidence=0.9,
                nodes=[],
                related_views=["MV_BACKUP_STATUS", "MV_BACKUP_HISTORY"],
                tags={"observability", "storage"},
            )
        successful = []
        for row in backups:
            if str(row.get("STATUS", "")).lower() == "success":
                ts = row.get("START_TIMESTAMP") or row.get("END_TIMESTAMP")
                if ts:
                    successful.append(str(ts))
        if not backups:
            self._add(
                checker_id="backupHistory",
                severity="warning",
                category="Backup",
                title="No backup history found",
                description="No backup records were found in backup history output.",
                evidence="backup_history is empty",
                remediation="Configure and run regular backups.",
                confidence=0.85,
                nodes=[],
                related_views=["MV_BACKUP_HISTORY"],
                tags={"data-loss", "observability"},
            )
        elif successful:
            latest_ts = max(successful)
            try:
                latest_dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - latest_dt).days
                self._add(
                    checker_id="backupHistory",
                    severity="info" if days < 7 else ("critical" if days > 30 else "warning"),
                    category="Backup",
                    title=f"Last successful backup was {days} days ago",
                    description="Backup freshness informs restore point risk.",
                    evidence=f"last_successful_backup={latest_ts}",
                    remediation="Keep automated backups frequent enough to meet RPO/RTO targets.",
                    confidence=0.84,
                    nodes=[],
                    related_views=["MV_BACKUP_HISTORY"],
                    tags={"data-loss", "observability"},
                )
            except Exception:
                pass

    def _check_logs_and_backtraces(self):
        patterns = self.report.get("detected_log_patterns", []) or []
        for p in patterns:
            category = str(p.get("category", "")).lower()
            count = int(_to_float(p.get("count")))
            nodes = p.get("nodes", []) or []
            sample = str(p.get("sample", ""))[:200]
            if count <= 0:
                continue
            if category == "oom":
                checker = "tracelogOOM"
                sev = "critical"
                tags = {"memory", "availability"}
            elif category == "disk":
                checker = "tracelogOOD"
                sev = "critical"
                tags = {"storage", "availability", "data-loss"}
            elif category == "crash":
                checker = "detectCrashStackTraces"
                sev = "critical"
                tags = {"availability", "data-loss"}
            elif category == "compilation":
                checker = "failedCodegen"
                sev = "warning"
                tags = {"query", "performance"}
            elif category == "background_tasks":
                checker = "failedBackgroundThreadAllocations"
                sev = "warning"
                tags = {"performance", "memory"}
            else:
                checker = "tracelogHardShutdown" if "shutdown" in p.get("title", "").lower() else "collectionErrors"
                sev = "warning" if p.get("severity") != "critical" else "critical"
                tags = {"observability"}
            self._add(
                checker_id=checker,
                severity=sev,
                category="Logs",
                title=f"{p.get('title', category)} ({count})",
                description=str(p.get("conclusion", "Log anomaly detected")),
                evidence=f"count={count} first={p.get('first_seen')} last={p.get('last_seen')} sample={sample}",
                remediation="Investigate surrounding log context and correlate with node/resource anomalies.",
                confidence=0.84 if checker != "collectionErrors" else 0.66,
                nodes=nodes,
                related_views=["memsqlTracelogs", "memsqlBacktraces", "memsqlStacks"],
                tags=tags,
                doc_link=p.get("doc_link", ""),
            )

    def _check_pipeline_analysis(self):
        rows = self.report.get("pipelines", []) or []
        if not rows:
            return
        by_state = defaultdict(int)
        by_name = defaultdict(int)
        for row in rows:
            state = str(row.get("STATE", row.get("state", "unknown"))).upper()
            name = row.get("PIPELINE_NAME", row.get("name", "unknown"))
            by_state[state] += 1
            if state in ("ERROR", "FAILED", "STOPPED"):
                by_name[name] += 1
        bad_total = sum(by_name.values())
        if bad_total:
            top = ", ".join(f"{k}:{v}" for k, v in sorted(by_name.items(), key=lambda x: x[1], reverse=True)[:8])
            self._add(
                checker_id="pipelineErrorAnalysis",
                severity="warning",
                category="Pipelines",
                title=f"Pipelines with operational errors ({bad_total})",
                description="Pipeline-level state analysis found non-running pipelines requiring targeted remediation.",
                evidence=f"states={dict(by_state)} bad={top}",
                remediation="Group by pipeline error type, fix source auth/connectivity/schema issues, then restart pipelines selectively.",
                confidence=0.82,
                nodes=[],
                related_views=["informationSchemaPipelines", "PIPELINES_ERRORS"],
                tags={"query", "availability"},
            )

    def _check_collection_errors_and_object_names(self):
        index = self.report.get("index", {}) or {}
        failed_hosts = index.get("failedHosts") or index.get("failed_hosts") or []
        if failed_hosts:
            score = max(0.0, 1.0 - (len(failed_hosts) / max(1, self.report.get("raw_node_count", 1))))
            sev = "critical" if score < 0.7 else "warning"
            self._add(
                checker_id="collectionErrors",
                severity=sev,
                category="Collection",
                title=f"Report collection incomplete on {len(failed_hosts)} host(s)",
                description="Missing collectors reduce diagnostic confidence and can hide root causes.",
                evidence=f"failed_hosts={','.join(str(h) for h in failed_hosts[:20])} completeness_score={score:.2f}",
                remediation="Re-run report collection with all hosts reachable and required permissions.",
                confidence=0.98,
                nodes=[],
                related_views=["failedHosts", "*.error"],
                tags={"observability"},
            )
        issues = []
        for row in self.report.get("storage", []) or []:
            for key in ("DATABASE_NAME", "TABLE_NAME", "COLUMN_NAME", "database", "table", "column"):
                name = row.get(key)
                if isinstance(name, str) and (name != name.strip() or "  " in name):
                    issues.append(f"{key}:{name}")
        if issues:
            self._add(
                checker_id="whitespacesInObjectName",
                severity="warning",
                category="Schema",
                title="Object names with problematic whitespace detected",
                description="Leading/trailing or repeated whitespace in object names complicates tooling and query authoring.",
                evidence="; ".join(issues[:20]),
                remediation="Rename affected objects to normalized identifiers without hidden whitespace.",
                confidence=0.78,
                nodes=[],
                related_views=["schema", "informationSchemaTables"],
                tags={"configuration"},
            )

    # ─── High-value checks ─────────────────────────────────────────

    def _check_log_coverage_gap(self):
        """Flag nodes where log coverage is very short or missing."""
        timeframe = self.report.get("log_timeframe", {}) or {}
        per_node = timeframe.get("per_node", {}) or {}
        for hostname, info in per_node.items():
            hours = _to_float(info.get("coverage_hours", 0))
            first = info.get("first_log_entry", "")
            last = info.get("last_log_entry", "")
            if not first and not last:
                self._add(
                    checker_id="logCoverageGap",
                    severity="warning",
                    category="Observability",
                    title=f"No log entries found for {hostname}",
                    description="No tracelog entries were parsed for this node, reducing diagnostic confidence.",
                    evidence=f"hostname={hostname} first_log_entry=none last_log_entry=none",
                    remediation="Ensure memsqlTracelogs directory is present and readable in the support bundle.",
                    confidence=0.88,
                    nodes=[hostname],
                    related_views=["memsqlTracelogs"],
                    tags={"observability"},
                )
            elif 0 < hours < 1:
                self._add(
                    checker_id="logCoverageGap",
                    severity="warning",
                    category="Observability",
                    title=f"Very short log coverage on {hostname} ({hours:.1f} h)",
                    description="Less than one hour of tracelog coverage limits root-cause analysis.",
                    evidence=f"hostname={hostname} first={first} last={last} coverage_hours={hours:.2f}",
                    remediation="Re-collect the support bundle with a longer log retention window.",
                    confidence=0.82,
                    nodes=[hostname],
                    related_views=["memsqlTracelogs"],
                    tags={"observability"},
                )

    def _check_backup_reliability(self):
        """Emit findings when backup failure rate is high."""
        summary = self.report.get("backup_summary", {}) or {}
        total = int(_to_float(summary.get("total", 0)))
        failures = int(_to_float(summary.get("failure_count", 0)))
        if total == 0 or failures == 0:
            return
        rate = failures / total
        if rate >= 0.5:
            sev = "critical"
        elif rate >= 0.25:
            sev = "warning"
        else:
            return
        self._add(
            checker_id="backupReliability",
            severity=sev,
            category="Backup",
            title=f"High backup failure rate: {failures}/{total} ({rate*100:.0f}%)",
            description="Frequent backup failures threaten the ability to meet RPO/RTO requirements.",
            evidence=f"failure_count={failures} total={total} latest_success={summary.get('latest_success_ts', 'unknown')}",
            remediation="Investigate backup destination availability, permissions, and disk space on backup target.",
            confidence=0.9,
            nodes=[],
            related_views=["MV_BACKUP_HISTORY", "informationSchemaMvBackupHistory"],
            tags={"data-loss", "observability"},
        )

    def _check_network_storage_pressure(self):
        """Flag elevated ETIMEDOUT/fsync/retry-stall event rates."""
        pressure = self.report.get("pressure_events_per_hour", {}) or {}
        thresholds = {
            "etimedout": (5, "ETIMEDOUT", "network", "Network timeout events are accumulating", "warning",
                          "Investigate inter-node network stability, firewall rules, and NIC health."),
            "fsync_behind": (3, "fsync is behind", "storage", "Disk fsync falling behind — I/O pressure detected", "warning",
                             "Check disk IOPS, I/O scheduler settings, and ensure data directories use SSDs."),
            "retry_stall": (3, "Retry loop stalling", "background_tasks",
                            "Background retry loops are stalling repeatedly", "warning",
                            "Correlate with disk I/O pressure, lock waits, or memory exhaustion on affected nodes."),
        }
        for key, (threshold, pat_label, cat, title, sev, remediation) in thresholds.items():
            by_hour = pressure.get(key, {}) or {}
            hot_hours = {h: c for h, c in by_hour.items() if c >= threshold}
            if not hot_hours:
                continue
            worst_hour, worst_count = max(hot_hours.items(), key=lambda x: x[1])
            self._add(
                checker_id=f"pressureEvents_{key}",
                severity=sev,
                category="Logs",
                title=f"{title} (peak {worst_count}/h at {worst_hour})",
                description=f"Elevated '{pat_label}' events in tracelogs indicate recurring {cat} pressure.",
                evidence=f"hot_hours={len(hot_hours)} worst_hour={worst_hour} worst_count={worst_count}",
                remediation=remediation,
                confidence=0.84,
                nodes=[],
                related_views=["memsqlTracelogs"],
                tags={cat, "performance"},
            )

    def _check_memory_pressure_indicators(self):
        """Flag OOM-killer evidence from dmesg, high vm.swappiness, and low vm.max_map_count
        using the pre-aggregated memory_pressure summary dict.

        Note: _check_preinstall_kernel_memory_network also checks swappiness and max_map_count
        via the per-node sysctl path (checker_id=vmSwappiness/maxMapCount). This method
        uses the same checker_ids so duplicate findings are consolidated in sort_and_finalize.
        """
        mem_pressure = self.report.get("memory_pressure", {}) or {}
        for hostname, info in mem_pressure.items():
            if info.get("oom_in_dmesg"):
                self._add(
                    checker_id="dmesgOOMKill",
                    severity="critical",
                    category="Memory",
                    title=f"OOM-killer evidence in dmesg on {hostname}",
                    description="The Linux OOM-killer terminated one or more processes on this node.",
                    evidence=f"hostname={hostname} oom_in_dmesg=true",
                    remediation="Increase physical RAM, reduce maximum_memory, or add leaf nodes to spread load.",
                    confidence=0.97,
                    nodes=[hostname],
                    related_views=["dmesg", "free"],
                    tags={"memory", "availability"},
                )
            swappiness = info.get("vm_swappiness")
            if swappiness is not None:
                try:
                    sv = int(swappiness)
                except (TypeError, ValueError):
                    sv = -1
                if sv >= 0 and (sv < 1 or sv > 10):
                    self._add_unique(
                        checker_id="vmSwappiness",
                        severity="warning",
                        category="Memory",
                        title=f"vm.swappiness={sv} is too high on {hostname}" if sv > 10 else f"vm.swappiness={sv} is too low on {hostname}",
                        description="High swappiness causes the kernel to swap SingleStore pages to disk, causing severe latency.",
                        evidence=f"hostname={hostname} vm.swappiness={sv}",
                        remediation="Set vm.swappiness to a low non-zero value (1-10) in /etc/sysctl.conf and apply with sysctl -p. Never set to 0.",
                        confidence=0.93,
                        nodes=[hostname],
                        related_views=["sysctl"],
                        tags={"memory", "performance"},
                    )
            max_map_count = info.get("vm_max_map_count")
            if max_map_count is not None:
                try:
                    mmc = int(_to_float(max_map_count))
                except (TypeError, ValueError):
                    mmc = -1
                if 0 < mmc < 1_000_000_000:
                    self._add_unique(
                        checker_id="vmMaxMapCount",
                        severity="critical",
                        category="Memory",
                        title=f"vm.max_map_count too low on {hostname}",
                        description="Low max_map_count prevents SingleStore from mapping sufficient memory regions.",
                        evidence=f"hostname={hostname} vm.max_map_count={mmc} (required>=1000000000)",
                        remediation="Set vm.max_map_count=1000000000 in /etc/sysctl.conf and apply with sysctl -p.",
                        confidence=0.96,
                        nodes=[hostname],
                        related_views=["sysctl"],
                        tags={"memory", "configuration"},
                    )

    def _check_cluster_layout_sanity(self):
        """Flag severely imbalanced partition distribution across hosts."""
        layout = self.report.get("cluster_layout", {}) or {}
        by_host = layout.get("by_host", {}) or {}
        if len(by_host) < 2:
            return
        totals = [v.get("total", 0) for v in by_host.values() if v.get("total", 0) > 0]
        if not totals:
            return
        min_t, max_t = min(totals), max(totals)
        if max_t == 0:
            return
        imbalance_pct = (max_t - min_t) / max_t * 100
        if imbalance_pct >= 30:
            host_detail = "; ".join(
                f"{h}:{v.get('total', 0)}" for h, v in sorted(by_host.items())
            )
            self._add(
                checker_id="clusterLayoutImbalance",
                severity="warning",
                category="Availability",
                title=f"Partition imbalance across hosts ({imbalance_pct:.0f}% skew)",
                description="Uneven partition distribution causes hot-spots and degrades query parallelism.",
                evidence=f"by_host={host_detail} min={min_t} max={max_t}",
                remediation="Run REBALANCE PARTITIONS to redistribute partitions evenly across leaf nodes.",
                confidence=0.82,
                nodes=[],
                related_views=["showClusterStatus", "MV_CLUSTER_STATUS"],
                tags={"performance", "availability"},
            )

    def _check_process_health_snapshot(self):
        """Flag non-sleeping queries and sleeping open transactions."""
        proc_health = self.report.get("process_health", {}) or {}
        active_count = int(_to_float(proc_health.get("active_count", 0)))
        sleeping_tx_count = int(_to_float(proc_health.get("sleeping_open_tx_count", 0)))
        active_queries = proc_health.get("active_queries", []) or []
        if active_count >= 20:
            sample = ", ".join(
                str(r.get("Info", r.get("QUERY_TEXT", "")))[:80]
                for r in active_queries[:3]
            )
            self._add(
                checker_id="highActiveQueryCount",
                severity="warning",
                category="Query",
                title=f"High active query count ({active_count}) in processlist",
                description="A large number of active (non-sleeping) queries may indicate concurrency saturation.",
                evidence=f"active_count={active_count} sample={sample}",
                remediation="Review query concurrency limits, resource pool settings, and index efficiency.",
                confidence=0.78,
                nodes=[],
                related_views=["informationSchemaProcesslist", "MV_PROCESSLIST"],
                tags={"query", "performance"},
            )
        if sleeping_tx_count > 0:
            self._add(
                checker_id="sleepingOpenTransactions",
                severity="warning",
                category="Query",
                title=f"Sleeping open transactions detected ({sleeping_tx_count})",
                description="Sleeping connections holding open transactions block row/table locks and consume memory.",
                evidence=f"sleeping_open_tx_count={sleeping_tx_count}",
                remediation="Identify and close idle transactions; set interactive_timeout and wait_timeout appropriately.",
                confidence=0.83,
                nodes=[],
                related_views=["informationSchemaProcesslist", "MV_PROCESSLIST"],
                tags={"query", "performance"},
            )

    def _check_query_patterns(self):
        """Detect slow, runaway, and repeated query patterns from processlist analysis."""
        qp = self.report.get("query_patterns", {}) or {}
        runaway_count = int(_to_float(qp.get("runaway_count", 0)))
        slow_count = int(_to_float(qp.get("slow_count", 0)))
        max_elapsed = _to_float(qp.get("max_elapsed_sec", 0))
        total_mem = _to_float(qp.get("total_memory_used_mb", 0))
        repeated = qp.get("repeated_patterns", []) or []

        # Runaway queries (elapsed > 5 min)
        if runaway_count > 0:
            top = (qp.get("runaway_queries") or [{}])[0]
            self._add(
                checker_id="runawayQueries",
                severity="critical",
                category="Query",
                title=f"Runaway queries detected ({runaway_count})",
                description="Queries running >5 minutes can monopolize CPU/memory and cause cascading latency.",
                evidence=f"max_elapsed={max_elapsed:.1f}s user={top.get('user','?')} db={top.get('database','?')} query={top.get('query_text','')[:120]}",
                remediation="Identify and kill runaway queries; add query timeouts and workload management rules.",
                confidence=0.92,
                nodes=[],
                related_views=["MV_QUERIES", "MV_PROCESSLIST"],
                tags={"query", "performance", "memory"},
            )
        # Slow queries (elapsed > 30s, not runaway)
        elif slow_count > 0:
            top = (qp.get("slow_queries") or [{}])[0]
            sev = "warning" if max_elapsed < 120 else "critical"
            self._add(
                checker_id="slowQueries",
                severity=sev,
                category="Query",
                title=f"Slow queries detected ({slow_count}, max {max_elapsed:.1f}s)",
                description="Queries exceeding 30s may indicate missing indexes or suboptimal plans.",
                evidence=f"max_elapsed={max_elapsed:.1f}s user={top.get('user','?')} db={top.get('database','?')}",
                remediation="Review EXPLAIN plans, add indexes, and consider query rewriting or partitioning.",
                confidence=0.85,
                nodes=[],
                related_views=["MV_QUERIES", "MV_PROCESSLIST"],
                tags={"query", "performance"},
            )

        # Repeated query patterns (same normalized SQL ≥3 times)
        if repeated:
            top_pat = repeated[0]
            self._add(
                checker_id="repeatedQueryPatterns",
                severity="info",
                category="Query",
                title=f"Repeated query pattern detected ({top_pat['count']}x, max {top_pat['max_elapsed_sec']}s)",
                description="The same normalized SQL appearing multiple times may benefit from caching or batching.",
                evidence=f"count={top_pat['count']} max_elapsed={top_pat['max_elapsed_sec']}s sample={top_pat['sample_query'][:100]}",
                remediation="Consider prepared statements, connection pooling, or application-level caching.",
                confidence=0.7,
                nodes=[],
                related_views=["MV_QUERIES"],
                tags={"query", "performance"},
            )

        # High total memory from active queries
        if total_mem > 4096:  # >4 GB across all active queries
            self._add(
                checker_id="highQueryMemoryUsage",
                severity="warning",
                category="Query",
                title=f"High memory usage from active queries ({total_mem:.0f} MB)",
                description="Active queries collectively using >4 GB may pressure overall memory allocation.",
                evidence=f"total_memory_used_mb={total_mem:.1f}",
                remediation="Review query memory profiles, check for spills to disk, and tune resource pool limits.",
                confidence=0.8,
                nodes=[],
                related_views=["MV_QUERIES", "MV_PROCESSLIST"],
                tags={"query", "memory"},
            )

    def _check_replication_lag_patterns(self):
        """Detect replication lag trends and async-transition events."""
        rlp = self.report.get("replication_lag_patterns", {}) or {}
        state = str(rlp.get("replication_state", "healthy"))
        max_lag = _to_float(rlp.get("max_lag_sec", 0))
        avg_lag = _to_float(rlp.get("avg_lag_sec", 0))
        lagging_count = int(_to_float(rlp.get("lagging_count", 0)))
        async_transitions = int(_to_float(rlp.get("async_transitions", 0)))
        lagging_pairs = rlp.get("lagging_pairs", []) or []

        if state == "critical":
            # Either high lag or async transitions detected
            if lagging_count > 0:
                top = lagging_pairs[0] if lagging_pairs else {}
                self._add(
                    checker_id="replicationLagCritical",
                    severity="critical",
                    category="Replication",
                    title=f"Critical replication lag (max {max_lag:.1f}s across {lagging_count} pairs)",
                    description="Replication lag >30s threatens failover RPO and data consistency.",
                    evidence=f"max_lag={max_lag:.1f}s avg_lag={avg_lag:.1f}s pairs={lagging_count} top={top.get('master','?')}→{top.get('slave','?')}",
                    remediation="Investigate network latency, storage throughput, and source query load on the lagging pair.",
                    confidence=0.93,
                    nodes=[],
                    related_views=["MV_REPLICATION_STATUS"],
                    tags={"replication", "availability"},
                )
            if async_transitions > 0:
                self._add(
                    checker_id="asyncTransitionDetected",
                    severity="critical",
                    category="Replication",
                    title=f"Sync→Async replication transitions detected ({async_transitions})",
                    description="Transitions from synchronous to asynchronous replication indicate network or node stress.",
                    evidence=f"async_transitions={async_transitions}",
                    remediation="Investigate network stability between master and leaf nodes; check for node failover events.",
                    confidence=0.9,
                    nodes=[],
                    related_views=["MV_REPLICATION_STATUS", "MV_EVENTS"],
                    tags={"replication", "availability"},
                )
        elif state == "degraded":
            self._add(
                checker_id="replicationLagDegraded",
                severity="warning",
                category="Replication",
                title=f"Replication lag degraded (max {max_lag:.1f}s)",
                description="Replication lag between 5–30s indicates growing replica drift.",
                evidence=f"max_lag={max_lag:.1f}s avg_lag={avg_lag:.1f}s pairs={lagging_count}",
                remediation="Monitor trend; if lag continues to grow, investigate source load and network.",
                confidence=0.82,
                nodes=[],
                related_views=["MV_REPLICATION_STATUS"],
                tags={"replication"},
            )

    def _check_memory_utilization(self):
        """Per-node memory utilization trend — flag nodes approaching memory limits."""
        mu = self.report.get("memory_utilization", {}) or {}
        summary = mu.get("cluster_summary", {}) or {}
        per_node = mu.get("per_node", {}) or {}

        nodes_over_90 = int(_to_float(summary.get("nodes_over_90pct", 0)))
        nodes_over_80 = int(_to_float(summary.get("nodes_over_80pct", 0)))
        highest_pct = _to_float(summary.get("highest_utilization_pct", 0))
        highest_node = str(summary.get("highest_utilization_node", ""))
        avg_pct = _to_float(summary.get("avg_engine_used_pct", 0))

        # Critical: any node over 90%
        if nodes_over_90 > 0:
            # Find the worst node details
            worst = {}
            for host, data in per_node.items():
                if _to_float(data.get("engine_used_pct", 0)) > 90:
                    worst = data
                    break
            self._add(
                checker_id="memoryUtilizationCritical",
                severity="critical",
                category="Memory",
                title=f"Critical memory utilization ({nodes_over_90} node{'s' if nodes_over_90 > 1 else ''} >90%)",
                description="Nodes exceeding 90% memory are at risk of OOM kills and performance degradation.",
                evidence=f"highest={highest_pct:.1f}% on {highest_node} avg={avg_pct:.1f}% engine_used={worst.get('engine_used_mb', 0)}MB max={worst.get('engine_max_mb', 0)}MB",
                remediation="Increase max_memory, reduce workload, or add nodes. Check for memory leaks in long-running queries.",
                confidence=0.93,
                nodes=[highest_node] if highest_node else [],
                related_views=["MV_NODES", "informationSchemaMvNodes"],
                tags={"memory", "performance"},
            )
        elif nodes_over_80 > 0:
            self._add(
                checker_id="memoryUtilizationWarning",
                severity="warning",
                category="Memory",
                title=f"High memory utilization ({nodes_over_80} node{'s' if nodes_over_80 > 1 else ''} >80%)",
                description="Nodes over 80% memory may face performance degradation under load spikes.",
                evidence=f"highest={highest_pct:.1f}% on {highest_node} avg={avg_pct:.1f}%",
                remediation="Monitor trend; consider increasing max_memory or rebalancing partitions.",
                confidence=0.85,
                nodes=[highest_node] if highest_node else [],
                related_views=["MV_NODES"],
                tags={"memory"},
            )

        # Check for swap usage (memory pressure indicator)
        # SingleStore Toolbox: <5% recommended, >5% caution, >10% not recommended
        swap_nodes = []
        for host, data in per_node.items():
            swap_pct = _to_float(data.get("swap_used_pct", 0))
            if swap_pct > 5:
                swap_nodes.append((host, swap_pct))
        if swap_nodes:
            swap_nodes.sort(key=lambda x: x[1], reverse=True)
            worst_swap = swap_nodes[0]
            sev = "critical" if worst_swap[1] > 10 else "warning"
            self._add(
                checker_id="swapUsageDetected",
                severity=sev,
                category="Memory",
                title=f"Swap usage detected ({len(swap_nodes)} node{'s' if len(swap_nodes) > 1 else ''}, max {worst_swap[1]:.0f}%)",
                description="Swap usage indicates the system is under memory pressure and paging to disk.",
                evidence=f"worst={worst_swap[0]}:{worst_swap[1]:.1f}% nodes={len(swap_nodes)}",
                remediation="Reduce memory footprint, increase physical RAM, or adjust vm.swappiness.",
                confidence=0.9,
                nodes=[h for h, _ in swap_nodes],
                tags={"memory", "environment"},
            )

    def _check_long_running_transactions(self):
        """Long-running transactions and lock contention detection."""
        lrt = self.report.get("long_running_transactions", {}) or {}
        long_count = int(_to_float(lrt.get("long_tx_count", 0)))
        max_duration = _to_float(lrt.get("max_tx_duration_sec", 0))
        lock_waiting = int(_to_float(lrt.get("lock_waiting_count", 0)))
        blocking_chains = int(_to_float(lrt.get("blocking_chains", 0)))
        largest_chain = int(_to_float(lrt.get("largest_chain_size", 0)))
        has_unkillable = bool(lrt.get("has_unkillable", False))
        level = str(lrt.get("lock_contention_level", "none"))

        if level == "severe":
            if has_unkillable:
                self._add(
                    checker_id="unkillableTransaction",
                    severity="critical",
                    category="Query",
                    title=f"Unkillable transaction detected (chain size {largest_chain})",
                    description="An unkillable transaction blocks all queries behind it and cannot be terminated normally.",
                    evidence=f"largest_chain={largest_chain} blocking_chains={blocking_chains} max_tx_duration={max_duration:.1f}s",
                    remediation="May require engine restart. Contact SingleStore support if KILL does not resolve it.",
                    confidence=0.95,
                    nodes=[],
                    related_views=["MV_BLOCKED_QUERIES", "MV_PROCESSLIST"],
                    tags={"query", "availability"},
                )
            else:
                top = (lrt.get("long_running_tx") or [{}])[0]
                self._add(
                    checker_id="severeLockContention",
                    severity="critical",
                    category="Query",
                    title=f"Severe lock contention (chain={largest_chain}, waiting={lock_waiting})",
                    description="Large blocking chains indicate cascading lock contention that can stall the entire workload.",
                    evidence=f"largest_chain={largest_chain} blocking_chains={blocking_chains} lock_waiting={lock_waiting} max_tx={max_duration:.1f}s",
                    remediation="Identify and terminate the root blocking transaction. Review transaction isolation and locking patterns.",
                    confidence=0.91,
                    nodes=[],
                    related_views=["MV_BLOCKED_QUERIES", "MV_PROCESSLIST"],
                    tags={"query", "performance"},
                )
        elif level == "moderate":
            if long_count > 0:
                top = (lrt.get("long_running_tx") or [{}])[0]
                sev = "warning" if max_duration < 300 else "critical"
                self._add(
                    checker_id="longRunningTransactions",
                    severity=sev,
                    category="Query",
                    title=f"Long-running transactions ({long_count}, max {max_duration:.1f}s)",
                    description="Transactions running >60s hold locks and consume resources.",
                    evidence=f"long_tx_count={long_count} max_duration={max_duration:.1f}s user={top.get('user','?')} query={top.get('query_text','')[:100]}",
                    remediation="Review transaction scope, add explicit commits, and avoid long-running DDL/DML in OLTP workloads.",
                    confidence=0.87,
                    nodes=[],
                    related_views=["MV_PROCESSLIST"],
                    tags={"query", "performance"},
                )
            if blocking_chains > 0:
                self._add(
                    checker_id="lockContention",
                    severity="warning",
                    category="Query",
                    title=f"Lock contention detected ({blocking_chains} blocking chain{'s' if blocking_chains > 1 else ''})",
                    description="Blocking chains reduce throughput and increase query latency.",
                    evidence=f"blocking_chains={blocking_chains} largest_chain={largest_chain} lock_waiting={lock_waiting}",
                    remediation="Identify root blocker, optimize transaction scope, and review isolation levels.",
                    confidence=0.83,
                    nodes=[],
                    related_views=["MV_BLOCKED_QUERIES"],
                    tags={"query", "performance"},
                )

def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    txt = str(value).strip().replace("%", "").replace(",", "")
    if not txt:
        return 0.0
    try:
        return float(txt)
    except ValueError:
        m = re.search(r"[-+]?\d*\.?\d+", txt)
        return float(m.group(0)) if m else 0.0


def _parse_size_to_bytes(raw) -> int:
    """Parse a sysctl size value like '8388608', '8M', '8MB' to bytes as int."""
    if not raw:
        return 0
    txt = str(raw).strip()
    mult = 1
    if txt.endswith(("k", "kb", "K", "KB")):
        mult = 1024
        txt = txt[:-2]
    elif txt.endswith(("m", "mb", "M", "MB")):
        mult = 1024 * 1024
        txt = txt[:-2]
    elif txt.endswith(("g", "gb", "G", "GB")):
        mult = 1024 * 1024 * 1024
        txt = txt[:-2]
    try:
        return int(float(txt)) * mult
    except (ValueError, TypeError):
        return 0


def _to_mb(raw) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    txt = str(raw).strip().lower()
    if not txt:
        return 0.0
    mult = 1.0
    if txt.endswith("gb") or txt.endswith("g"):
        mult = 1024.0
    elif txt.endswith("tb") or txt.endswith("t"):
        mult = 1024.0 * 1024.0
    elif txt.endswith("mb") or txt.endswith("m"):
        mult = 1.0
    num = _to_float(txt)
    return num * mult


def _fmt_mb(mb: float) -> str:
    if mb >= 1024 * 1024:
        return f"{mb / (1024 * 1024):.1f}TB"
    if mb >= 1024:
        return f"{mb / 1024:.1f}GB"
    return f"{mb:.0f}MB"


def _extract_limit_value(text: str, key: str):
    pattern = re.compile(rf"\b{key}\b\s+(\d+)\b", re.IGNORECASE)
    vals = [int(m.group(1)) for m in pattern.finditer(text)]
    if not vals:
        return None
    return max(vals)


def _report_time(report: dict):
    ts = report.get("parsed_at")
    if not ts:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _minutes_between(now_dt: datetime, ts):
    if not ts:
        return None
    if isinstance(ts, datetime):
        evt_dt = ts
    else:
        txt = str(ts).strip()
        try:
            evt_dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        except Exception:
            return None
    delta = now_dt - evt_dt
    return int(delta.total_seconds() // 60)


def _latest_event_for_node(events: list, host: str):
    best = None
    for row in events:
        blob = str(row).lower()
        if host.lower() not in blob:
            continue
        t = row.get("EVENT_TIME") or row.get("TIMESTAMP") or row.get("TIME")
        if best is None:
            best = row
            continue
        bt = best.get("EVENT_TIME") or best.get("TIMESTAMP") or best.get("TIME")
        if str(t) > str(bt):
            best = row
    return best
def compute_diff(old: list, new: list) -> dict:
    def key(rec):
        return (str(rec.get("checker_id","")), str(rec.get("title","")).strip())
    old_map = {key(r): r for r in old or []}
    new_map = {key(r): r for r in new or []}
    worsened = []
    improved = []
    resolved = []
    added = []
    for k, r_old in old_map.items():
        r_new = new_map.get(k)
        if not r_new:
            resolved.append({"title": r_old.get("title",""), "checker_id": r_old.get("checker_id","")})
            continue
        old_sev = r_old.get("severity","info")
        new_sev = r_new.get("severity","info")
        sev_rank = {"critical": 3, "warning": 2, "info": 1}
        old_rank = sev_rank.get(old_sev,1)
        new_rank = sev_rank.get(new_sev,1)
        old_risk = int(r_old.get("risk_score",0))
        new_risk = int(r_new.get("risk_score",0))
        if new_rank > old_rank or new_risk > old_risk:
            worsened.append({"title": r_new.get("title",""), "checker_id": r_new.get("checker_id","")})
        elif new_rank < old_rank or new_risk < old_risk:
            improved.append({"title": r_new.get("title",""), "checker_id": r_new.get("checker_id","")})
    for k, r_new in new_map.items():
        if k not in old_map:
            added.append({"title": r_new.get("title",""), "checker_id": r_new.get("checker_id","")})
    return {
        "new": added,
        "resolved": resolved,
        "worsened": worsened,
        "improved": improved,
    }
