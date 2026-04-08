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


def run_superchecker(report: dict) -> list:
    state = _CheckerState(report or {})
    state.run()
    state.correlate()
    state.sort_and_finalize()
    return state.findings


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
        for key in ["cluster_overview", "config_health", "alloc_memory", "partitions", "index"]:
            if not isinstance(self.report.get(key), dict):
                self.report[key] = {}
        self.findings = []
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
        cluster_status = self.report.get("cluster_overview", {}).get("cluster_status", []) or []
        offline_parts = [
            cs for cs in cluster_status
            if str(cs.get("State", cs.get("state", ""))).lower() in ("offline", "unreachable", "needs attention")
        ]
        if offline_parts:
            self._add(
                checker_id="userDatabaseRedundancy",
                severity="critical",
                category="Replication",
                title=f"{len(offline_parts)} partition(s) with degraded redundancy",
                description="Partitions without healthy slaves increase failure blast radius.",
                evidence=f"non_healthy_partitions={len(offline_parts)}",
                remediation="Recover unhealthy nodes and run RESTORE REDUNDANCY for affected databases.",
                confidence=0.95,
                nodes=[],
                related_views=["showClusterStatus", "MV_CLUSTER_STATUS"],
                tags={"replication", "availability", "data-loss"},
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
        })

    def _check_cluster_memory_usage(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            mem = node.get("metrics", {}).get("memory", {}) or {}
            used_pct = float(mem.get("used_pct", 0) or 0)
            if used_pct > 85:
                self._add(
                    checker_id="clusterMemoryUsage",
                    severity="critical" if used_pct > 90 else "warning",
                    category="Memory",
                    title=f"High memory usage on {host} ({used_pct}%)",
                    description="Memory usage exceeds safe threshold.",
                    evidence=f"used_pct={used_pct}",
                    remediation="Tune maximum_memory and reduce memory-heavy workload.",
                    nodes=[host],
                    related_views=["free", "showVariables"],
                    tags={"memory", "availability"},
                )
            if float(mem.get("swap_used_mb", 0) or 0) > 0:
                self._add(
                    checker_id="swapUsage",
                    severity="warning",
                    category="Memory",
                    title=f"Swap usage on {host} ({mem.get('swap_used_mb', 0)} MB)",
                    description="Swap usage indicates memory pressure.",
                    evidence=f"swap_used_mb={mem.get('swap_used_mb', 0)}",
                    remediation="Reduce memory pressure and tune OS/engine memory settings.",
                    nodes=[host],
                    related_views=["free"],
                    tags={"memory", "performance"},
                )

    def _check_disk_usage_and_inodes(self):
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            for disk in node.get("metrics", {}).get("disk", []):
                pct = _to_float(disk.get("use_pct", 0))
                mount = str(disk.get("mounted_on", ""))
                if pct > 85 and any(x in mount.lower() for x in ("memsql", "data", "var", "/")):
                    self._add(
                        checker_id="diskUsage",
                        severity="critical" if pct > 90 else "warning",
                        category="Storage",
                        title=f"Disk usage {pct:.0f}% on {host} ({mount})",
                        description="Disk usage is high and can impact writes.",
                        evidence=f"use_pct={pct}",
                        remediation="Free/expand storage and rebalance data.",
                        nodes=[host],
                        related_views=["df"],
                        tags={"storage", "availability", "data-loss"},
                    )

    def _check_missing_checkers(self):
        # Alerting Checks
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

        # Pre-installation and Performance
        for node in self.report.get("nodes", []):
            host = node.get("hostname", "unknown")
            metrics = node.get("metrics", {})
            sys_info = metrics.get("sys_info", {})
            
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

            # cpuMemoryBandwidth
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

            # diskBandwidth
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

            # maxNicePriority
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

            # partitionsConsistency
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

            # installedPermissions
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

            # syncCnfVariables
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


                
            mem = metrics.get("memory", {})
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

            # cpuMemoryBandwidth
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

            # diskBandwidth
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

            # maxNicePriority
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

            # partitionsConsistency
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

            # installedPermissions
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

            # syncCnfVariables
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

            # cpuMemoryBandwidth
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

            # diskBandwidth
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

            # maxNicePriority
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

            # partitionsConsistency
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

            # installedPermissions
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

            # syncCnfVariables
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
