import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from superchecker import _CheckerState, run_superchecker

def test_memory_usage_critical():
    report = {
        "nodes": [
            {
                "hostname": "node1",
                "metrics": {
                    "memory": {
                        "used_pct": 95,
                        "total_mb": 100000
                    }
                },
                "show_variables": {
                    "maximum_memory": "100000"
                }
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "clusterMemoryUsage" and f["severity"] == "critical" for f in findings)

def test_node_online_status():
    report = {
        "cluster_overview": {
            "nodes_detail": [
                {"ip_addr": "node1", "state": "ONLINE", "type": "LEAF"},
                {"ip_addr": "node2", "state": "OFFLINE", "type": "LEAF"}
            ]
        }
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "leavesNotOnline" and f["severity"] == "critical" for f in findings)


def test_missing_node_state_does_not_emit_offline_findings():
    report = {
        "cluster_overview": {
            "nodes_detail": [
                {"ip_addr": "leaf-1", "type": "LEAF"},
                {"ip_addr": "aggregator-1", "type": "MA"},
                {"ip_addr": "leaf-2", "state": "UNKNOWN", "type": "LEAF"},
            ]
        }
    }
    findings = run_superchecker(report)
    assert not any(f["checker_id"] == "leavesNotOnline" for f in findings)
    assert not any(f["checker_id"] == "offlineAggregators" for f in findings)


def test_disk_usage_warning():
    report = {
        "nodes": [
            {
                "hostname": "node1",
                "metrics": {
                    "disk": [
                        {"mounted_on": "/", "use_pct": 75, "iuse_pct": 50, "used": "75G", "size": "100G"}
                    ]
                }
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "diskUsage" and f["severity"] == "warning" for f in findings)


def test_disk_usage_critical_above_80():
    report = {
        "nodes": [
            {
                "hostname": "node1",
                "metrics": {
                    "disk": [
                        {"mounted_on": "/", "use_pct": 85, "iuse_pct": 50, "used": "85G", "size": "100G"}
                    ]
                }
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "diskUsage" and f["severity"] == "critical" for f in findings)


def test_disk_usage_data_mount_warns_at_60():
    report = {
        "nodes": [
            {
                "hostname": "leaf1",
                "metrics": {
                    "disk": [
                        {"mounted_on": "/media/hdisk0/memsql", "use_pct": 65, "iuse_pct": 10, "used": "65G", "size": "100G"}
                    ]
                }
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "diskUsage" and f["severity"] == "warning" for f in findings)


def test_memory_committed_warns_at_75():
    report = {
        "nodes": [
            {
                "hostname": "leaf1",
                "metrics": {"memory_committed": {"commit_pct": 75}},
                "os_checks": {"sysctl": {"vm.overcommit_memory": {"numeric": 0}}},
            }
        ]
    }
    findings = run_superchecker(report)
    mc = [f for f in findings if f["checker_id"] == "memoryCommitted"]
    assert mc and mc[0]["severity"] == "warning"


def test_memory_committed_critical_above_90():
    report = {
        "nodes": [
            {
                "hostname": "leaf1",
                "metrics": {"memory_committed": {"commit_pct": 95}},
                "os_checks": {"sysctl": {"vm.overcommit_memory": {"numeric": 0}}},
            }
        ]
    }
    findings = run_superchecker(report)
    mc = [f for f in findings if f["checker_id"] == "memoryCommitted"]
    assert mc and mc[0]["severity"] == "critical"


def test_swap_usage_quiet_within_5_pct():
    report = {
        "nodes": [
            {
                "hostname": "leaf1",
                "metrics": {
                    "memory": {"swap_used_pct": 2.0, "swap_used_mb": 128},
                    "major_page_faults": {"pgmajflt_per_sec": 0},
                },
            }
        ]
    }
    findings = run_superchecker(report)
    assert not any(f["checker_id"] == "swapUsage" for f in findings)


def test_hdd_disk_latency_critical_above_25ms():
    report = {
        "nodes": [
            {
                "hostname": "leaf1",
                "metrics": {
                    "disk_latency": [
                        {"device": "sdb", "read_await_ms": 40, "write_await_ms": 12, "util_pct": 50, "rota": 1}
                    ]
                },
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(
        f["checker_id"] in ("diskLatencyRead", "diskLatencyWrite") and f["severity"] == "critical"
        for f in findings
    )


def test_max_memory_allows_ram_minus_10gb_on_large_hosts():
    # 128 GiB RAM with max_mem = RAM-10GB (~91%) should NOT warn (within ceiling).
    total_mb = 128 * 1024
    max_mem_mb = total_mb - 10 * 1024
    report = {
        "nodes": [
            {
                "hostname": "leaf-large",
                "metrics": {"memory": {"total_mb": total_mb}},
                "show_variables": {"maximum_memory": str(int(max_mem_mb))},
            }
        ]
    }
    findings = run_superchecker(report)
    assert not any(f["checker_id"] == "maxMemorySettings" for f in findings)


def test_max_memory_flags_above_documented_ceiling():
    total_mb = 128 * 1024
    max_mem_mb = total_mb  # 100% of RAM — above max(0.91*RAM, RAM-10GB)
    report = {
        "nodes": [
            {
                "hostname": "leaf-large",
                "metrics": {"memory": {"total_mb": total_mb}},
                "show_variables": {"maximum_memory": str(int(max_mem_mb))},
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "maxMemorySettings" for f in findings)


def test_used_cluster_capacity_skips_info_tier():
    report = {
        "cluster_overview": {"used_memory_mb": 40_000, "total_memory_mb": 100_000},
        "licensed_capacity_mb": "100000",
    }
    findings = run_superchecker(report)
    assert not any(f["checker_id"] == "usedClusterCapacity" for f in findings)


def test_used_cluster_capacity_warns_above_75():
    report = {
        "cluster_overview": {"used_memory_mb": 80_000, "total_memory_mb": 100_000},
        "licensed_capacity_mb": "100000",
    }
    findings = run_superchecker(report)
    uc = [f for f in findings if f["checker_id"] == "usedClusterCapacity"]
    assert uc and uc[0]["severity"] == "warning"

def test_replication_health():
    report = {
        "replication_status": [
            {"database": "db1", "role": "secondary", "LAG_SECONDS": 45}
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "replicationLag" and f["severity"] == "critical" for f in findings)

def test_blocked_and_long_queries():
    report = {
        "cluster_overview": {
            "blocked_queries": [
                {"blocking_query_id": "1234", "kill_status": "unkillable"},
                {"blocking_query_id": "1234", "kill_status": "killable"}
            ]
        }
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "blockedQueries" and f["severity"] == "warning" for f in findings)

def test_pipeline_analysis():
    report = {
        "pipelines": [
            {"pipeline_name": "p1", "state": "ERROR", "error_count": 5}
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "pipelineErrorAnalysis" for f in findings)


def test_security_checklist_does_not_mutate_pipeline_payload():
    report = {
        "pipelines": [{"PIPELINE_NAME": "cluster-pipeline", "SOURCE_TYPE": "KAFKA"}],
        "nodes": [{
            "hostname": "node-1",
            "show_variables": {"advanced_hdfs_pipelines": "OFF"},
            "pipelines_data": [{"PIPELINE_NAME": "node-pipeline", "SOURCE_TYPE": "HDFS"}],
        }],
    }
    original = [dict(row) for row in report["pipelines"]]
    findings = run_superchecker(report)
    assert report["pipelines"] == original
    assert any(f["checker_id"] == "sdbHCAdvancedHDFSPipelineFeatures" for f in findings)

def test_query_queues():
    report = {
        "resource_pools": [
            {"POOL_NAME": "general", "QUEUE_DEPTH": 55}
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "queuedQueries" and f["severity"] == "critical" for f in findings)

def test_orphan_databases():
    report = {
        "cluster_overview": {"orphan_databases": [{"Database": "db_test_orphan"}]}
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "orphanDatabases" for f in findings)

def test_missing_cluster_db_not_flagged_when_cluster_db_present():
    """Regression: the real SingleStore system database is named 'cluster'
    (see docs.singlestore.com/db/v9.0/reference/system-databases). The checker
    previously searched for a nonexistent 'cluster_management' database, which
    made this finding a permanent false positive on every real bundle."""
    report = {
        "databases": [
            {"Database": "cluster", "Status": "ONLINE"},
            {"Database": "information_schema", "Status": "ONLINE"},
            {"Database": "memsql", "Status": "ONLINE"},
            {"Database": "customer_db", "Status": "ONLINE"},
        ]
    }
    findings = run_superchecker(report)
    assert not any(f["checker_id"] == "missingClusterDb" for f in findings)

def test_missing_cluster_db_flagged_when_absent_with_specific_evidence():
    report = {
        "databases": [
            {"Database": "customer_db", "Status": "ONLINE"},
            {"Database": "another_db", "Status": "ONLINE"},
        ]
    }
    findings = run_superchecker(report)
    finding = next((f for f in findings if f["checker_id"] == "missingClusterDb"), None)
    assert finding is not None
    assert finding["severity"] == "critical"
    # Evidence must name the actually-observed databases, not a generic
    # "Database Detected"-style count with no diagnostic value.
    assert "customer_db" in finding["evidence"]
    assert "another_db" in finding["evidence"]
    assert "cluster" in finding["evidence"]
    # Recommended first action must mirror this finding's own remediation
    # rather than a generic tag-based default unrelated to a missing
    # metadata database (e.g. leaf-node/network guidance).
    assert finding["triage"]["recommended_action"] == finding["remediation"]
    assert "leaf" not in finding["triage"]["recommended_action"].lower()

def test_recommended_action_matches_finding_remediation_not_generic_tag_default():
    """Triage's 'recommended first action' must reflect each finding's own
    remediation text, not a generic tag-based default that can reference an
    unrelated fix (e.g. leaf-node guidance for an unrecoverable-database
    finding just because both happen to carry the 'availability' tag)."""
    report = {"databases": [{"Database": "db1", "Status": "UNRECOVERABLE"}]}
    findings = run_superchecker(report)
    finding = next(f for f in findings if f["checker_id"] == "unrecoverableDatabases")
    assert finding["triage"]["recommended_action"] == finding["remediation"]
    assert "leaf" not in finding["triage"]["recommended_action"].lower()

def test_delayed_thread_launches():
    report = {
        "nodes": [
            {
                "hostname": "node1",
                "metrics": {},
                "tracelogs": [{"message": "Delayed thread launch detected due to saturation"}]
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "delayedThreadLaunches" for f in findings)

def test_correlation_engine_suppresses_noise():
    report = {
        "cluster_overview": {
            "nodes_detail": [
                {"ip_addr": "node1", "state": "OFFLINE", "type": "LEAF"}
            ]
        },
        "replication_status": [
            {"database": "db1", "role": "secondary", "state": "disconnected"}
        ]
    }
    findings = run_superchecker(report)
    
    # We expect the offline node finding to exist
    assert any(f["checker_id"] == "leavesNotOnline" for f in findings)
    
    # We expect the disconnected replication slave to be suppressed by correlation
    assert not any(f["checker_id"] == "disconnectedReplicationSlaves" for f in findings)


def test_incident_cluster_member_ids_follow_final_finding_ids():
    state = _CheckerState({})
    state.findings = [
        {
            "id": 1,
            "checker_id": "clusterLowRisk",
            "severity": "info",
            "risk_score": 20,
            "priority_tags": ["storage"],
            "related_findings": [2],
            "triage": {"cluster_id": "INC-001"},
        },
        {
            "id": 2,
            "checker_id": "clusterHighRisk",
            "severity": "info",
            "risk_score": 30,
            "priority_tags": ["storage"],
            "related_findings": [1],
            "triage": {"cluster_id": "INC-001"},
        },
        {
            "id": 3,
            "checker_id": "unrelatedCritical",
            "severity": "critical",
            "risk_score": 90,
            "priority_tags": ["availability"],
            "related_findings": [],
            "triage": {},
        },
    ]
    state.incident_clusters = [
        {
            "cluster_id": "INC-001",
            "member_ids": [1, 2],
            "member_count": 2,
        }
    ]

    state.sort_and_finalize()

    assert state.incident_clusters[0]["member_ids"] == [2, 3]
    cluster_members = [
        finding for finding in state.findings
        if finding.get("triage", {}).get("cluster_id") == "INC-001"
    ]
    assert sorted(finding["id"] for finding in cluster_members) == [2, 3]
    assert cluster_members[0]["related_findings"] == [3]
    assert cluster_members[1]["related_findings"] == [2]


def test_firewall_port_blocking_detection_from_rebalance_status():
    report = {
        "cluster_overview": {
            "rebalance_status": [
                {
                    "Status": (
                        "failed (Slave database riodev:0 on "
                        "chdcnc-cdvr-sy-sst-1101.spectrum.com:3307 could not synchronize "
                        "with Master database on chdcnc-cdvr-sy-sst-1105.spectrum.com:3307)"
                    )
                }
            ]
        }
    }
    findings = run_superchecker(report)
    blocked = [f for f in findings if f["checker_id"] == "firewallPortBlocking"]
    assert blocked, "Expected firewallPortBlocking finding"
    assert blocked[0]["severity"] == "critical"
    assert "3307" in blocked[0]["evidence"]


def test_firewall_root_cause_suppresses_disconnected_replication():
    report = {
        "cluster_overview": {
            "rebalance_status": [
                {
                    "Status": (
                        "failed (Slave database riodev:0 on "
                        "src-node.example.com:3308 could not synchronize "
                        "with Master database on dst-node.example.com:3308)"
                    )
                }
            ]
        },
        "replication_status": [
            {"database": "riodev", "state": "disconnected"}
        ],
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "firewallPortBlocking" for f in findings)
    assert not any(f["checker_id"] == "disconnectedReplicationSlaves" for f in findings)


# ─── High-value checker tests ──────────────────────────────────────

def test_log_coverage_gap_no_logs():
    """logCoverageGap fires when a node has no log coverage at all."""
    report = {
        "log_timeframe": {
            "per_node": {
                "leaf-1": {"first_log_entry": "", "last_log_entry": "", "coverage_hours": 0.0}
            }
        }
    }
    findings = run_superchecker(report)
    gap = [f for f in findings if f["checker_id"] == "logCoverageGap"]
    assert gap, "Expected logCoverageGap finding for node with no logs"
    assert gap[0]["severity"] == "warning"


def test_log_coverage_gap_short_coverage():
    """logCoverageGap fires when log coverage is under 1 hour."""
    report = {
        "log_timeframe": {
            "per_node": {
                "leaf-1": {
                    "first_log_entry": "2024-01-10 09:00:00.000",
                    "last_log_entry": "2024-01-10 09:20:00.000",
                    "coverage_hours": 0.33,
                }
            }
        }
    }
    findings = run_superchecker(report)
    gap = [f for f in findings if f["checker_id"] == "logCoverageGap"]
    assert gap, "Expected logCoverageGap for <1 hour coverage"


def test_log_coverage_gap_sufficient_coverage():
    """logCoverageGap does NOT fire for adequate (>1 h) log coverage."""
    report = {
        "log_timeframe": {
            "per_node": {
                "leaf-1": {
                    "first_log_entry": "2024-01-10 08:00:00.000",
                    "last_log_entry": "2024-01-10 20:00:00.000",
                    "coverage_hours": 12.0,
                }
            }
        }
    }
    findings = run_superchecker(report)
    gap = [f for f in findings if f["checker_id"] == "logCoverageGap"]
    assert not gap, "logCoverageGap should not fire for 12h coverage"


def test_backup_reliability_critical_when_half_fail():
    """backupReliability fires as critical when >=50% of backups fail."""
    report = {
        "backup_summary": {
            "total": 4,
            "success_count": 2,
            "failure_count": 2,
            "latest_success_ts": "2024-01-08 10:00:00",
            "latest_duration_sec": 3600.0,
        }
    }
    findings = run_superchecker(report)
    rel = [f for f in findings if f["checker_id"] == "backupReliability"]
    assert rel, "Expected backupReliability finding"
    assert rel[0]["severity"] == "critical"


def test_backup_reliability_warning_when_quarter_fail():
    """backupReliability fires as warning when 25-49% fail."""
    report = {
        "backup_summary": {
            "total": 8,
            "success_count": 6,
            "failure_count": 2,
            "latest_success_ts": "2024-01-08 10:00:00",
            "latest_duration_sec": 1800.0,
        }
    }
    findings = run_superchecker(report)
    rel = [f for f in findings if f["checker_id"] == "backupReliability"]
    assert rel, "Expected backupReliability warning"
    assert rel[0]["severity"] == "warning"


def test_backup_reliability_no_finding_for_all_success():
    """backupReliability does not fire when all backups succeed."""
    report = {
        "backup_summary": {
            "total": 5,
            "success_count": 5,
            "failure_count": 0,
            "latest_success_ts": "2024-01-08 10:00:00",
            "latest_duration_sec": 1200.0,
        }
    }
    findings = run_superchecker(report)
    rel = [f for f in findings if f["checker_id"] == "backupReliability"]
    assert not rel, "backupReliability should not fire when there are no failures"


def test_network_pressure_etimedout_spike():
    """pressureEvents_etimedout fires when hourly ETIMEDOUT count exceeds threshold."""
    report = {
        "pressure_events_per_hour": {
            "etimedout": {"2024-01-10 09": 8, "2024-01-10 10": 12},
            "fsync_behind": {},
            "retry_stall": {},
        }
    }
    findings = run_superchecker(report)
    p = [f for f in findings if f["checker_id"] == "pressureEvents_etimedout"]
    assert p, "Expected pressureEvents_etimedout finding"
    assert p[0]["severity"] == "warning"


def test_network_pressure_no_finding_below_threshold():
    """pressureEvents_etimedout does not fire when counts are low."""
    report = {
        "pressure_events_per_hour": {
            "etimedout": {"2024-01-10 09": 2},
            "fsync_behind": {},
            "retry_stall": {},
        }
    }
    findings = run_superchecker(report)
    p = [f for f in findings if f["checker_id"] == "pressureEvents_etimedout"]
    assert not p, "pressureEvents_etimedout should not fire for counts below threshold"


def test_storage_pressure_fsync_finding():
    """pressureEvents_fsync_behind fires when fsync-behind events exceed threshold."""
    report = {
        "pressure_events_per_hour": {
            "etimedout": {},
            "fsync_behind": {"2024-01-10 11": 5},
            "retry_stall": {},
        }
    }
    findings = run_superchecker(report)
    p = [f for f in findings if f["checker_id"] == "pressureEvents_fsync_behind"]
    assert p, "Expected pressureEvents_fsync_behind finding"


def test_memory_pressure_oom_dmesg():
    """dmesgOOMKill fires when OOM is found in dmesg for a node."""
    report = {
        "memory_pressure": {
            "leaf-1": {
                "thp_status": "enabled",
                "oom_in_dmesg": True,
                "vm_swappiness": "0",
                "vm_max_map_count": 1000000,
            }
        }
    }
    findings = run_superchecker(report)
    oom = [f for f in findings if f["checker_id"] == "dmesgOOMKill"]
    assert oom, "Expected dmesgOOMKill finding"
    assert oom[0]["severity"] == "critical"


def test_memory_pressure_vm_swappiness():
    """vmSwappiness fires when vm.swappiness is above 1."""
    report = {
        "memory_pressure": {
            "node-1": {
                "thp_status": "disabled",
                "oom_in_dmesg": False,
                "vm_swappiness": "60",
                "vm_max_map_count": 1000000,
            }
        }
    }
    findings = run_superchecker(report)
    sev = [f for f in findings if f["checker_id"] == "vmSwappiness"]
    assert sev, "Expected vmSwappiness finding"
    assert sev[0]["severity"] == "warning"


def test_memory_pressure_vm_max_map_count():
    """maxMapCount fires when vm.max_map_count is below 1,000,000."""
    report = {
        "memory_pressure": {
            "node-1": {
                "thp_status": "disabled",
                "oom_in_dmesg": False,
                "vm_swappiness": "0",
                "vm_max_map_count": 65530,
            }
        }
    }
    findings = run_superchecker(report)
    mmc = [f for f in findings if f["checker_id"] == "maxMapCount"]
    assert mmc, "Expected maxMapCount critical finding"
    assert mmc[0]["severity"] == "critical"


def test_cluster_layout_imbalance():
    """clusterLayoutImbalance fires when partition skew across hosts is >=30%."""
    report = {
        "cluster_layout": {
            "by_host": {
                "leaf-1": {"master": 10, "slave": 10, "total": 20},
                "leaf-2": {"master": 10, "slave": 4, "total": 14},
            },
            "by_role": {"master": 20, "slave": 14},
            "total_partitions": 34,
        }
    }
    findings = run_superchecker(report)
    imb = [f for f in findings if f["checker_id"] == "clusterLayoutImbalance"]
    assert imb, "Expected clusterLayoutImbalance finding"


def test_cluster_layout_balanced_no_finding():
    """clusterLayoutImbalance does not fire for an evenly distributed cluster."""
    report = {
        "cluster_layout": {
            "by_host": {
                "leaf-1": {"master": 10, "slave": 10, "total": 20},
                "leaf-2": {"master": 10, "slave": 10, "total": 20},
            },
            "by_role": {"master": 20, "slave": 20},
            "total_partitions": 40,
        }
    }
    findings = run_superchecker(report)
    imb = [f for f in findings if f["checker_id"] == "clusterLayoutImbalance"]
    assert not imb, "clusterLayoutImbalance should not fire for balanced cluster"


def test_process_health_high_active_queries():
    """highActiveQueryCount fires when active query count >= 20."""
    active_rows = [
        {"Command": "Query", "Info": f"SELECT {i}", "Time": i}
        for i in range(25)
    ]
    report = {
        "process_health": {
            "active_count": 25,
            "sleeping_open_tx_count": 0,
            "active_queries": active_rows,
            "sleeping_open_transactions": [],
        }
    }
    findings = run_superchecker(report)
    haq = [f for f in findings if f["checker_id"] == "highActiveQueryCount"]
    assert haq, "Expected highActiveQueryCount finding"
    assert haq[0]["severity"] == "warning"


def test_process_health_sleeping_open_transactions():
    """sleepingOpenTransactions fires when sleeping open transactions exist."""
    report = {
        "process_health": {
            "active_count": 2,
            "sleeping_open_tx_count": 3,
            "active_queries": [],
            "sleeping_open_transactions": [
                {"Command": "Sleep", "TRX_STATE": "running", "Time": 120}
            ] * 3,
        }
    }
    findings = run_superchecker(report)
    sot = [f for f in findings if f["checker_id"] == "sleepingOpenTransactions"]
    assert sot, "Expected sleepingOpenTransactions finding"
    assert sot[0]["severity"] == "warning"


def test_process_health_no_findings_for_idle_cluster():
    """No process_health findings for a quiet cluster."""
    report = {
        "process_health": {
            "active_count": 0,
            "sleeping_open_tx_count": 0,
            "active_queries": [],
            "sleeping_open_transactions": [],
        }
    }
    findings = run_superchecker(report)
    ph = [f for f in findings if f["checker_id"] in ("highActiveQueryCount", "sleepingOpenTransactions")]
    assert not ph, "No process health findings expected for idle cluster"


# ─── Phase 3.2: Query Patterns + Replication Lag ─────────────────────

def test_query_patterns_runaway_queries():
    """runawayQueries fires when elapsed > 300s."""
    report = {
        "query_patterns": {
            "runaway_count": 2,
            "slow_count": 0,
            "max_elapsed_sec": 650.0,
            "total_memory_used_mb": 100.0,
            "runaway_queries": [
                {"elapsed_sec": 650.0, "query_text": "SELECT * FROM huge", "user": "etl", "database": "prod"}
            ],
            "slow_queries": [],
            "repeated_patterns": [],
        }
    }
    findings = run_superchecker(report)
    rq = [f for f in findings if f["checker_id"] == "runawayQueries"]
    assert rq, "Expected runawayQueries finding"
    assert rq[0]["severity"] == "critical"


def test_query_patterns_ignores_stale_null_query_runaway():
    """Stale MV_QUERIES rows (NULL query, multi-day elapsed) must not fire runawayQueries."""
    report = {
        "query_patterns": {
            "runaway_count": 0,
            "slow_count": 0,
            "max_elapsed_sec": 0.0,
            "total_memory_used_mb": 0.0,
            "runaway_queries": [],
            "slow_queries": [],
            "repeated_patterns": [],
        }
    }
    findings = run_superchecker(report)
    assert not any(f["checker_id"] == "runawayQueries" for f in findings)


def test_query_patterns_slow_queries():
    """slowQueries fires when 30s < elapsed < 300s."""
    report = {
        "query_patterns": {
            "runaway_count": 0,
            "slow_count": 3,
            "max_elapsed_sec": 90.0,
            "total_memory_used_mb": 50.0,
            "runaway_queries": [],
            "slow_queries": [
                {"elapsed_sec": 90.0, "query_text": "SELECT * FROM orders", "user": "app", "database": "prod"}
            ],
            "repeated_patterns": [],
        }
    }
    findings = run_superchecker(report)
    sq = [f for f in findings if f["checker_id"] == "slowQueries"]
    assert sq, "Expected slowQueries finding"
    assert sq[0]["severity"] == "warning"


def test_query_patterns_repeated_patterns():
    """repeatedQueryPatterns fires for normalized SQL appearing >=3 times."""
    report = {
        "query_patterns": {
            "runaway_count": 0,
            "slow_count": 0,
            "max_elapsed_sec": 0,
            "total_memory_used_mb": 0,
            "runaway_queries": [],
            "slow_queries": [],
            "repeated_patterns": [
                {"normalized_sql": "select * from t where id = ?", "count": 5, "max_elapsed_sec": 12.0, "sample_query": "SELECT * FROM t WHERE id = 1"}
            ],
        }
    }
    findings = run_superchecker(report)
    rp = [f for f in findings if f["checker_id"] == "repeatedQueryPatterns"]
    assert rp, "Expected repeatedQueryPatterns finding"
    assert rp[0]["severity"] == "info"


def test_query_patterns_high_memory_usage():
    """highQueryMemoryUsage fires when total query memory > 4GB."""
    report = {
        "query_patterns": {
            "runaway_count": 0,
            "slow_count": 0,
            "max_elapsed_sec": 0,
            "total_memory_used_mb": 5000.0,
            "memory_measurement_count": 2,
            "runaway_queries": [],
            "slow_queries": [],
            "repeated_patterns": [],
        }
    }
    findings = run_superchecker(report)
    hm = [f for f in findings if f["checker_id"] == "highQueryMemoryUsage"]
    assert hm, "Expected highQueryMemoryUsage finding"
    assert hm[0]["severity"] == "warning"


def test_query_patterns_no_findings_for_idle():
    """No query pattern findings when all queries are fast."""
    report = {
        "query_patterns": {
            "runaway_count": 0,
            "slow_count": 0,
            "max_elapsed_sec": 5.0,
            "total_memory_used_mb": 10.0,
            "runaway_queries": [],
            "slow_queries": [],
            "repeated_patterns": [],
        }
    }
    findings = run_superchecker(report)
    qp = [f for f in findings if f["checker_id"] in ("runawayQueries", "slowQueries", "repeatedQueryPatterns", "highQueryMemoryUsage")]
    assert not qp, "No query pattern findings expected for idle cluster"


def test_replication_lag_critical():
    """replicationLagCritical fires when max lag > 30s."""
    report = {
        "replication_lag_patterns": {
            "replication_state": "critical",
            "max_lag_sec": 45.0,
            "avg_lag_sec": 20.0,
            "lagging_count": 2,
            "async_transitions": 0,
            "lagging_pairs": [
                {"master": "m1", "slave": "s1", "lag_sec": 45.0, "severity": "critical"}
            ],
        }
    }
    findings = run_superchecker(report)
    rlc = [f for f in findings if f["checker_id"] == "replicationLagCritical"]
    assert rlc, "Expected replicationLagCritical finding"
    assert rlc[0]["severity"] == "critical"


def test_replication_lag_degraded():
    """replicationLagDegraded fires when 5s < max lag < 30s."""
    report = {
        "replication_lag_patterns": {
            "replication_state": "degraded",
            "max_lag_sec": 15.0,
            "avg_lag_sec": 8.0,
            "lagging_count": 1,
            "async_transitions": 0,
            "lagging_pairs": [
                {"master": "m1", "slave": "s1", "lag_sec": 15.0, "severity": "warning"}
            ],
        }
    }
    findings = run_superchecker(report)
    rld = [f for f in findings if f["checker_id"] == "replicationLagDegraded"]
    assert rld, "Expected replicationLagDegraded finding"
    assert rld[0]["severity"] == "warning"


def test_replication_lag_unknown_missing_seconds():
    """replicationLagUnknown fires when LAG_SECONDS is absent on inspected pairs."""
    report = {
        "replication_lag_patterns": {
            "replication_state": "unknown",
            "max_lag_sec": None,
            "avg_lag_sec": None,
            "lagging_count": 0,
            "unknown_lag_count": 1,
            "measured_lag_count": 0,
            "async_transitions": 0,
            "unknown_lag_pairs": [
                {"master": "m1", "slave": "s1", "lag_sec": None, "lsn_position_delta": 12.0}
            ],
        }
    }
    findings = run_superchecker(report)
    unk = [f for f in findings if f["checker_id"] == "replicationLagUnknown"]
    assert unk, "Expected replicationLagUnknown finding"
    assert unk[0]["severity"] == "info"


def test_replication_lag_healthy_no_unknown_finding():
    report = {
        "replication_lag_patterns": {
            "replication_state": "healthy",
            "max_lag_sec": None,
            "avg_lag_sec": None,
            "lagging_count": 0,
            "unknown_lag_count": 0,
            "measured_lag_count": 2,
            "async_transitions": 0,
            "lagging_pairs": [],
        }
    }
    findings = run_superchecker(report)
    unk = [f for f in findings if f["checker_id"] == "replicationLagUnknown"]
    assert not unk


def test_replication_async_transition_detected():
    """asyncTransitionDetected fires when sync→async transitions in logs."""
    report = {
        "replication_lag_patterns": {
            "replication_state": "critical",
            "max_lag_sec": 0.0,
            "avg_lag_sec": 0.0,
            "lagging_count": 0,
            "async_transitions": 3,
            "workload_throttle_events": 0,
            "lagging_pairs": [],
        }
    }
    findings = run_superchecker(report)
    at = [f for f in findings if f["checker_id"] == "asyncTransitionDetected"]
    assert at, "Expected asyncTransitionDetected finding"
    # Historical sync→async log events are warning-grade; they do not by themselves
    # prove the current link is unhealthy.
    assert at[0]["severity"] == "warning"


def test_workload_throttle_detected():
    report = {
        "replication_lag_patterns": {
            "replication_state": "critical",
            "max_lag_sec": 0.0,
            "avg_lag_sec": 0.0,
            "lagging_count": 0,
            "async_transitions": 0,
            "workload_throttle_events": 2,
            "lagging_pairs": [],
        }
    }
    findings = run_superchecker(report)
    wt = [f for f in findings if f["checker_id"] == "workloadThrottleDetected"]
    assert wt, "Expected workloadThrottleDetected finding"


def test_dmesg_collector_unavailable_info_finding():
    report = {
        "collector_availability": {
            "dmesg": {"nodes_total": 4, "stdout_available": 0, "stderr_only": 4, "unavailable": 0},
        }
    }
    findings = run_superchecker(report)
    dmesg = [f for f in findings if f["checker_id"] == "dmesgCollectorUnavailable"]
    assert dmesg, "Expected dmesgCollectorUnavailable finding"
    assert dmesg[0]["severity"] == "info"


def test_replication_lag_healthy_no_findings():
    """No replication findings when lag is within healthy range."""
    report = {
        "replication_lag_patterns": {
            "replication_state": "healthy",
            "max_lag_sec": 2.0,
            "avg_lag_sec": 1.0,
            "lagging_count": 0,
            "async_transitions": 0,
            "lagging_pairs": [],
        }
    }
    findings = run_superchecker(report)
    rl = [f for f in findings if f["checker_id"] in ("replicationLagCritical", "replicationLagDegraded", "asyncTransitionDetected")]
    assert not rl, "No replication lag findings expected for healthy state"


def test_replication_status_checker_defers_to_aggregated_patterns():
    report = {
        "replication_status": [{"LAG_SECONDS": 45.0, "MasterHost": "m1", "SlaveHost": "s1"}],
        "replication_lag_patterns": {
            "replication_state": "critical",
            "max_lag_sec": 45.0,
            "avg_lag_sec": 45.0,
            "lagging_count": 1,
            "async_transitions": 0,
            "workload_throttle_events": 0,
            "lagging_pairs": [{"master": "m1", "slave": "s1", "lag_sec": 45.0, "severity": "critical"}],
        },
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "replicationLagCritical" for f in findings)
    assert not any(f["checker_id"] == "replicationLag" for f in findings)


def test_network_buffer_single_letter_suffix_is_parsed():
    report = {
        "nodes": [
            {
                "hostname": "node1",
                "os_checks": {
                    "sysctl": {
                        "net.core.wmem_max": {"value": "8M"},
                        "net.core.rmem_max": {"value": "8M"},
                    }
                },
            }
        ]
    }
    findings = run_superchecker(report)
    assert not any(f["checker_id"] == "networkBuffersMax" for f in findings)


# ─── Item 1: Memory Utilization Trend ─────────────────────────────

def test_memory_utilization_critical_malformed_summary():
    """memoryUtilizationCritical must NOT fire if summary is malformed (e.g., nodes_over_90pct=99 but no per-node data)."""
    report = {
        "memory_utilization": {
            "cluster_summary": {
                "nodes_over_90pct": 99,
                "nodes_over_80pct": 99,
                "highest_utilization_pct": 99.0,
                "highest_utilization_node": "unknown",
                "avg_engine_used_pct": 99.0,
            },
            "per_node": {}, # Missing per-node data
        }
    }
    findings = run_superchecker(report)
    mc = [f for f in findings if f["checker_id"] == "memoryUtilizationCritical"]
    assert not mc, "memoryUtilizationCritical should not fire with malformed summary"

def test_memory_utilization_null_engine_pct_no_findings():
    """Null engine_used_pct must not be treated as 0% healthy."""
    report = {
        "memory_utilization": {
            "cluster_summary": {
                "nodes_over_90pct": 0,
                "nodes_over_80pct": 0,
                "highest_utilization_pct": None,
                "highest_utilization_node": None,
                "avg_engine_used_pct": None,
                "engine_metrics_available": False,
            },
            "per_node": {
                "leaf-01": {
                    "engine_used_pct": None,
                    "engine_used_mb": None,
                    "engine_max_mb": None,
                    "swap_used_pct": None,
                    "status": "unknown",
                    "engine_metrics_available": False,
                },
            },
        }
    }
    findings = run_superchecker(report)
    assert not [f for f in findings if f["checker_id"] in ("memoryUtilizationCritical", "memoryUtilizationWarning")]


def test_memory_utilization_critical_over_90pct():
    """memoryUtilizationCritical fires when any node >90%."""
    report = {
        "memory_utilization": {
            "cluster_summary": {
                "nodes_over_90pct": 1,
                "nodes_over_80pct": 1,
                "highest_utilization_pct": 93.8,
                "highest_utilization_node": "leaf-01",
                "avg_engine_used_pct": 85.0,
            },
            "per_node": {
                "leaf-01": {"engine_used_pct": 93.8, "engine_used_mb": 15000, "engine_max_mb": 16000},
            },
        }
    }
    findings = run_superchecker(report)
    mc = [f for f in findings if f["checker_id"] == "memoryUtilizationCritical"]
    assert mc, "Expected memoryUtilizationCritical finding"
    assert mc[0]["severity"] == "critical"
    assert "leaf-01" in mc[0]["nodes"]


def test_memory_utilization_warning_over_80pct():
    """memoryUtilizationWarning fires when nodes >80% but <=90%."""
    report = {
        "memory_utilization": {
            "cluster_summary": {
                "nodes_over_90pct": 0,
                "nodes_over_80pct": 2,
                "highest_utilization_pct": 85.0,
                "highest_utilization_node": "leaf-01",
                "avg_engine_used_pct": 82.0,
            },
            "per_node": {
                "leaf-01": {"engine_used_pct": 85.0},
                "leaf-02": {"engine_used_pct": 82.0},
            },
        }
    }
    findings = run_superchecker(report)
    mw = [f for f in findings if f["checker_id"] == "memoryUtilizationWarning"]
    assert mw, "Expected memoryUtilizationWarning finding"
    assert mw[0]["severity"] == "warning"


def test_memory_utilization_healthy_no_findings():
    """No memory findings when all nodes healthy."""
    report = {
        "memory_utilization": {
            "cluster_summary": {
                "nodes_over_90pct": 0,
                "nodes_over_80pct": 0,
                "highest_utilization_pct": 50.0,
                "highest_utilization_node": "leaf-01",
                "avg_engine_used_pct": 50.0,
            },
            "per_node": {
                "leaf-01": {"engine_used_pct": 50.0, "swap_used_pct": 0},
            },
        }
    }
    findings = run_superchecker(report)
    mu = [f for f in findings if f["checker_id"] in ("memoryUtilizationCritical", "memoryUtilizationWarning", "swapUsageDetected")]
    assert not mu, "No memory utilization findings expected for healthy state"


def test_swap_usage_detected():
    """swapUsageDetected fires when swap >5% (warning), >10% (critical) per SingleStore Toolbox."""
    report = {
        "memory_utilization": {
            "cluster_summary": {
                "nodes_over_90pct": 0,
                "nodes_over_80pct": 0,
                "highest_utilization_pct": 50.0,
                "highest_utilization_node": "",
                "avg_engine_used_pct": 50.0,
            },
            "per_node": {
                "leaf-01": {"engine_used_pct": 50.0, "swap_used_pct": 7.0},
            },
        }
    }
    findings = run_superchecker(report)
    su = [f for f in findings if f["checker_id"] == "swapUsageDetected"]
    assert su, "Expected swapUsageDetected finding"
    assert su[0]["severity"] == "warning"  # 7% > 5% but < 10%


def test_major_page_fault_thresholds_follow_grounding():
    report = {
        "nodes": [
            {"hostname": "node-low", "metrics": {"memory": {}, "major_page_faults": {"pgmajflt_per_sec": 5}}},
            {"hostname": "node-warn", "metrics": {"memory": {}, "major_page_faults": {"pgmajflt_per_sec": 10}}},
            {"hostname": "node-critical", "metrics": {"memory": {}, "major_page_faults": {"pgmajflt_per_sec": 20}}},
        ]
    }
    findings = run_superchecker(report)
    major = {tuple(f["nodes"]): f for f in findings if f["checker_id"] == "majorPageFaults"}
    assert ("node-low",) not in major
    assert major[("node-warn",)]["severity"] == "warning"
    assert major[("node-critical",)]["severity"] == "critical"


def test_vm_overcommit_zero_is_compliant_but_one_warns():
    report = {
        "nodes": [
            {
                "hostname": "node-ok",
                "os_checks": {"sysctl": {"vm.overcommit_memory": {"numeric": 0}, "vm.overcommit_ratio": {"numeric": 99}}},
            },
            {
                "hostname": "node-warn",
                "os_checks": {"sysctl": {"vm.overcommit_memory": {"numeric": 1}, "vm.overcommit_ratio": {"numeric": 99}}},
            },
        ]
    }
    findings = run_superchecker(report)
    overcommit = [f for f in findings if f["checker_id"] == "vmOvercommit"]
    assert len(overcommit) == 1
    assert overcommit[0]["nodes"] == ["node-warn"]
    assert "recommended vm.overcommit_memory is 0" in overcommit[0]["description"].lower()


def test_iowait_uses_distinct_checker_id():
    report = {
        "nodes": [
            {
                "hostname": "node1",
                "metrics": {"cpu_utilization": {"idle": 40, "iowait": 25}},
            }
        ]
    }
    findings = run_superchecker(report)
    assert any(f["checker_id"] == "cpuIowait" for f in findings)
    assert not any(
        f["checker_id"] == "cpuIdle" and "iowait" in f["title"].lower()
        for f in findings
    )


# ─── Item 2: Long-Running Transactions + Lock Contention ──────────

def test_long_running_transactions_detected():
    """longRunningTransactions fires for tx >60s."""
    report = {
        "long_running_transactions": {
            "long_tx_count": 2,
            "max_tx_duration_sec": 180.0,
            "lock_waiting_count": 0,
            "blocking_chains": 0,
            "largest_chain_size": 0,
            "has_unkillable": False,
            "lock_contention_level": "moderate",
            "long_running_tx": [
                {"duration_sec": 180.0, "query_text": "UPDATE huge_table SET x=1", "user": "etl"}
            ],
        }
    }
    findings = run_superchecker(report)
    lt = [f for f in findings if f["checker_id"] == "longRunningTransactions"]
    assert lt, "Expected longRunningTransactions finding"
    assert lt[0]["severity"] == "warning"  # <300s = warning


def test_long_running_transactions_critical_over_300s():
    """longRunningTransactions is critical when max >300s."""
    report = {
        "long_running_transactions": {
            "long_tx_count": 1,
            "max_tx_duration_sec": 450.0,
            "lock_waiting_count": 0,
            "blocking_chains": 0,
            "largest_chain_size": 0,
            "has_unkillable": False,
            "lock_contention_level": "moderate",
            "long_running_tx": [
                {"duration_sec": 450.0, "query_text": "DELETE FROM big_table", "user": "dbadmin"}
            ],
        }
    }
    findings = run_superchecker(report)
    lt = [f for f in findings if f["checker_id"] == "longRunningTransactions"]
    assert lt, "Expected longRunningTransactions finding"
    assert lt[0]["severity"] == "critical"


def test_lock_contention_moderate():
    """lockContention fires for blocking chains in moderate level."""
    report = {
        "long_running_transactions": {
            "long_tx_count": 0,
            "max_tx_duration_sec": 0,
            "lock_waiting_count": 0,
            "blocking_chains": 3,
            "largest_chain_size": 5,
            "has_unkillable": False,
            "lock_contention_level": "moderate",
            "long_running_tx": [],
        }
    }
    findings = run_superchecker(report)
    lc = [f for f in findings if f["checker_id"] == "lockContention"]
    assert lc, "Expected lockContention finding"
    assert lc[0]["severity"] == "warning"


def test_severe_lock_contention():
    """severeLockContention fires when level is severe."""
    report = {
        "long_running_transactions": {
            "long_tx_count": 0,
            "max_tx_duration_sec": 0,
            "lock_waiting_count": 8,
            "blocking_chains": 2,
            "largest_chain_size": 12,
            "has_unkillable": False,
            "lock_contention_level": "severe",
            "long_running_tx": [],
        }
    }
    findings = run_superchecker(report)
    slc = [f for f in findings if f["checker_id"] == "severeLockContention"]
    assert slc, "Expected severeLockContention finding"
    assert slc[0]["severity"] == "critical"


def test_unkillable_transaction():
    """unkillableTransaction fires when has_unkillable is True."""
    report = {
        "long_running_transactions": {
            "long_tx_count": 0,
            "max_tx_duration_sec": 0,
            "lock_waiting_count": 0,
            "blocking_chains": 1,
            "largest_chain_size": 20,
            "has_unkillable": True,
            "lock_contention_level": "severe",
            "long_running_tx": [],
        }
    }
    findings = run_superchecker(report)
    ut = [f for f in findings if f["checker_id"] == "unkillableTransaction"]
    assert ut, "Expected unkillableTransaction finding"
    assert ut[0]["severity"] == "critical"


def test_no_transaction_findings_for_idle():
    """No transaction findings when contention level is none."""
    report = {
        "long_running_transactions": {
            "long_tx_count": 0,
            "max_tx_duration_sec": 0,
            "lock_waiting_count": 0,
            "blocking_chains": 0,
            "largest_chain_size": 0,
            "has_unkillable": False,
            "lock_contention_level": "none",
            "long_running_tx": [],
        }
    }
    findings = run_superchecker(report)
    tx = [f for f in findings if f["checker_id"] in ("longRunningTransactions", "lockContention", "severeLockContention", "unkillableTransaction")]
    assert not tx, "No transaction findings expected for idle cluster"


def test_add_unique_deduplicates_findings():
    """Verify that _add_unique deduplicates findings and retains the longer evidence."""
    from superchecker import _CheckerState
    checker = _CheckerState({})
    # Add first finding
    checker._add_unique(
        checker_id="testUnique",
        severity="warning",
        category="Test",
        title="Test Title",
        description="Test Desc",
        evidence="short",
        remediation="remedy",
        nodes=["node-1"],
    )
    # Add second finding with same checker_id and nodes but longer evidence
    checker._add_unique(
        checker_id="testUnique",
        severity="warning",
        category="Test",
        title="Test Title",
        description="Test Desc",
        evidence="longer evidence",
        remediation="remedy",
        nodes=["node-1"],
    )
    # Check that there is only 1 finding and it has the longer evidence
    findings = [f for f in checker.findings if f["checker_id"] == "testUnique"]
    assert len(findings) == 1
    assert findings[0]["evidence"] == "longer evidence"


def test_unknown_thp_status_does_not_false_critical():
    """Missing THP collector (status=unknown) must not fake 'THP enabled'."""
    report = {
        "nodes": [
            {"hostname": "leaf-1", "os_checks": {"thp": {"status": "unknown"}}},
            {"hostname": "leaf-2", "os_checks": {"thp": {}}},
        ],
        "config_health": {
            "os_checks": [
                {
                    "name": "Transparent Huge Pages",
                    "status": "pass",
                    "detail": "THP collector unavailable; status unknown",
                }
            ]
        },
    }
    findings = run_superchecker(report)
    assert not [f for f in findings if f["checker_id"] == "transparentHugepage"]


def test_current_parse_unknown_thp_end_to_end():
    """build_config_health + superchecker must agree: unknown is not enabled."""
    from parsers import build_config_health

    nodes = [{"hostname": "leaf-1", "os_checks": {"thp": {"status": "unknown"}}}]
    report = {"nodes": nodes, "config_health": build_config_health(nodes)}
    findings = run_superchecker(report)
    assert not [f for f in findings if f["checker_id"] == "transparentHugepage"]


def test_thp_enabled_still_fires_critical():
    """Measured THP enabled must still produce a critical finding."""
    report = {
        "nodes": [
            {
                "hostname": "leaf-1",
                "os_checks": {
                    "thp": {
                        "enabled": "[always]",
                        "defrag": "[always]",
                        "status": "enabled",
                        "active": "always",
                        "active_defrag": "always",
                    }
                },
            }
        ]
    }
    findings = run_superchecker(report)
    thp = [f for f in findings if f["checker_id"] == "transparentHugepage"]
    assert thp
    assert thp[0]["severity"] == "critical"
    assert "leaf-1" in thp[0]["nodes"]


def test_robust_thp_disabled_only_if_both_never():
    """Verify THP fires warning if enabled is never but defrag is not never, or vice versa."""
    report = {
        "nodes": [
            {
                "hostname": "node-1",
                "os_checks": {
                    "thp": {"enabled": "always", "defrag": "always", "status": "enabled", "active": "always", "active_defrag": "always"},
                }
            },
            {
                "hostname": "node-2",
                "os_checks": {
                    "thp": {"enabled": "[never]", "defrag": "always", "status": "enabled", "active": "never", "active_defrag": "always"},
                }
            },
            {
                "hostname": "node-3",
                "os_checks": {
                    "thp": {"enabled": "[never]", "defrag": "[never]", "status": "disabled", "active": "never", "active_defrag": "never"},
                }
            }
        ]
    }
    findings = run_superchecker(report)
    thp_findings = [f for f in findings if f["checker_id"] == "transparentHugepage"]
    nodes_with_thp = []
    for f in thp_findings:
        nodes_with_thp.extend(f["nodes"])
    assert "node-1" in nodes_with_thp
    assert "node-2" in nodes_with_thp
    assert "node-3" not in nodes_with_thp


def test_somaxconn_limit_under_1024():
    """Verify net.core.somaxconn under 1024 fires somaxconnLimit."""
    report = {
        "nodes": [
            {
                "hostname": "node-1",
                "os_checks": {
                    "sysctl": {
                        "net.core.somaxconn": {"value": "512", "numeric": 512, "status": "fail"}
                    }
                }
            }
        ]
    }
    findings = run_superchecker(report)
    somax_findings = [f for f in findings if f["checker_id"] == "somaxconnLimit"]
    assert len(somax_findings) == 1
    assert somax_findings[0]["severity"] == "warning"
    assert "node-1" in somax_findings[0]["nodes"]


def test_aggressive_swappiness_boundaries():
    """Verify swappiness boundary conditions (1-10 healthy, outside warning)."""
    # 1. Test via os_checks.sysctl path
    for val, expected_finding in [
        (0, True),
        (1, False),
        (5, False),
        (10, False),
        (11, True),
        (60, True),
    ]:
        report = {
            "nodes": [
                {
                    "hostname": "node-1",
                    "os_checks": {
                        "sysctl": {
                            "vm.swappiness": {"value": str(val), "numeric": val, "status": "fail" if val == 0 or val > 10 else "pass"}
                        }
                    }
                }
            ]
        }
        findings = run_superchecker(report)
        sw_findings = [f for f in findings if f["checker_id"] == "vmSwappiness"]
        if expected_finding:
            assert len(sw_findings) == 1
            assert sw_findings[0]["severity"] == "warning"
            assert "node-1" in sw_findings[0]["nodes"]
        else:
            assert len(sw_findings) == 0

    # 2. Test via memory_pressure path
    for val, expected_finding in [
        (0, True),
        (1, False),
        (5, False),
        (10, False),
        (11, True),
        (60, True),
    ]:
        report = {
            "memory_pressure": {
                "node-1": {
                    "vm_swappiness": str(val)
                }
            }
        }
        findings = run_superchecker(report)
        sw_findings = [f for f in findings if f["checker_id"] == "vmSwappiness"]
        if expected_finding:
            assert len(sw_findings) == 1
            assert sw_findings[0]["severity"] == "warning"
        else:
            assert len(sw_findings) == 0


def test_aggressive_max_map_count_boundaries():
    """Verify max_map_count boundary conditions (critical under 1B, healthy >= 1B)."""
    # 1. Test via os_checks.sysctl path
    for val, expected_finding in [
        (999999999, True),
        (1000000000, False),
        (1000000001, False),
    ]:
        report = {
            "nodes": [
                {
                    "hostname": "node-1",
                    "os_checks": {
                        "sysctl": {
                            "vm.max_map_count": {"value": str(val), "numeric": val, "status": "fail" if val < 1000000000 else "pass"}
                        }
                    }
                }
            ]
        }
        findings = run_superchecker(report)
        mmc_findings = [f for f in findings if f["checker_id"] == "maxMapCount"]
        if expected_finding:
            assert len(mmc_findings) == 1
            assert mmc_findings[0]["severity"] == "critical"
        else:
            assert len(mmc_findings) == 0

    # 2. Test via memory_pressure path
    for val, expected_finding in [
        (999999999, True),
        (1000000000, False),
        (1000000001, False),
    ]:
        report = {
            "memory_pressure": {
                "node-1": {
                    "vm_max_map_count": str(val)
                }
            }
        }
        findings = run_superchecker(report)
        mmc_findings = [f for f in findings if f["checker_id"] == "maxMapCount"]
        if expected_finding:
            assert len(mmc_findings) == 1
            assert mmc_findings[0]["severity"] == "critical"
        else:
            assert len(mmc_findings) == 0


def test_aggressive_thp_boundaries():
    """Verify THP behaves correctly (disabled if enabled & defrag are never, warning/critical otherwise)."""
    cases = [
        ("[never] always", "[never]", "never", "never", "disabled", False),
        ("always", "never", "always", "never", "enabled", True),
        ("never", "always", "never", "always", "enabled", True),
        ("always", "always", "always", "always", "enabled", True),
        ("[never]", "[never]", "never", "never", "disabled", False),
        ("[always] madvise never", "[never]", "always", "never", "enabled", True),
    ]
    for enabled, defrag, active, active_defrag, status, expected_finding in cases:
        report = {
            "nodes": [
                {
                    "hostname": "node-1",
                    "os_checks": {
                        "thp": {
                            "enabled": enabled,
                            "defrag": defrag,
                            "active": active,
                            "active_defrag": active_defrag,
                            "status": status
                        }
                    }
                }
            ]
        }
        findings = run_superchecker(report)
        thp_findings = [f for f in findings if f["checker_id"] == "transparentHugepage"]
        if expected_finding:
            assert len(thp_findings) == 1
            assert thp_findings[0]["severity"] == "critical"
        else:
            assert len(thp_findings) == 0


def test_aggressive_somaxconn_boundaries():
    """Verify somaxconn limit boundaries (under 1024 warning, >= 1024 healthy)."""
    for val, expected_finding in [
        (1023, True),
        (1024, False),
        (1025, False),
        (2048, False),
    ]:
        report = {
            "nodes": [
                {
                    "hostname": "node-1",
                    "os_checks": {
                        "sysctl": {
                            "net.core.somaxconn": {"value": str(val), "numeric": val, "status": "fail" if val < 1024 else "pass"}
                        }
                    }
                }
            ]
        }
        findings = run_superchecker(report)
        somax_findings = [f for f in findings if f["checker_id"] == "somaxconnLimit"]
        if expected_finding:
            assert len(somax_findings) == 1
            assert somax_findings[0]["severity"] == "warning"
        else:
            assert len(somax_findings) == 0


def test_aggressive_add_unique_deduplication():
    """Aggressively verify _add_unique deduplicates properly and keeps/updates evidence."""
    from superchecker import _CheckerState
    checker = _CheckerState({})
    # 1. Identical finding added twice
    checker._add_unique("testUnique", "warning", "Test", "Title", "Desc", "short", "remedy", nodes=["node-1"])
    checker._add_unique("testUnique", "warning", "Test", "Title", "Desc", "short", "remedy", nodes=["node-1"])
    findings = [f for f in checker.findings if f["checker_id"] == "testUnique"]
    assert len(findings) == 1
    assert findings[0]["evidence"] == "short"

    # 2. Add with longer evidence (should update evidence)
    checker._add_unique("testUnique", "warning", "Test", "Title", "Desc", "longer evidence", "remedy", nodes=["node-1"])
    findings = [f for f in checker.findings if f["checker_id"] == "testUnique"]
    assert len(findings) == 1
    assert findings[0]["evidence"] == "longer evidence"

    # 3. Add with shorter evidence (should retain longer evidence)
    checker._add_unique("testUnique", "warning", "Test", "Title", "Desc", "tiny", "remedy", nodes=["node-1"])
    findings = [f for f in checker.findings if f["checker_id"] == "testUnique"]
    assert len(findings) == 1
    assert findings[0]["evidence"] == "longer evidence"

    # 4. Add with different node list (should not deduplicate)
    checker._add_unique("testUnique", "warning", "Test", "Title", "Desc", "other node", "remedy", nodes=["node-2"])
    findings = [f for f in checker.findings if f["checker_id"] == "testUnique"]
    assert len(findings) == 2


def test_incident_cluster_member_ids_match_final_finding_ids():
    """member_ids must use post-sort ids so UI cluster filters align with recommendations."""
    from superchecker import run_superchecker_with_clusters

    report = {
        "nodes": [
            {
                "hostname": "node-a",
                "metrics": {
                    "memory": {"used_pct": 92},
                    "disk": [{"mounted_on": "/var/lib/memsql", "use_pct": 92, "used": "9G", "size": "10G", "filesystem": "ext4"}],
                },
                "show_variables": {},
                "memsqld_process_limits": {"open_files_soft": 1024, "open_files_hard": 1024},
            },
            {
                "hostname": "node-b",
                "metrics": {
                    "memory": {"used_pct": 91},
                    "disk": [{"mounted_on": "/var/lib/memsql", "use_pct": 91, "used": "9G", "size": "10G", "filesystem": "ext4"}],
                },
                "show_variables": {},
                "memsqld_process_limits": {"open_files_soft": 1024, "open_files_hard": 1024},
            },
        ],
        "cluster_overview": {},
        "process_health": {},
        "query_patterns": {},
        "replication_lag_patterns": {},
        "memory_utilization": {},
        "long_running_transactions": {},
    }

    findings, clusters = run_superchecker_with_clusters(report)
    assert clusters, "Expected at least one incident cluster for shared-node findings"

    finding_ids = {f["id"] for f in findings}
    for cluster in clusters:
        assert cluster["member_ids"], f"{cluster['cluster_id']} missing member_ids"
        assert set(cluster["member_ids"]).issubset(finding_ids)
        stamped = [f for f in findings if f.get("triage", {}).get("cluster_id") == cluster["cluster_id"]]
        assert stamped, f"No findings stamped with {cluster['cluster_id']}"
        assert {f["id"] for f in stamped} == set(cluster["member_ids"])



def test_split_folded_variable_checkers():
    """attachRebalanceDelay / autoAttach / failureDetectionOn emit distinct IDs."""
    report = {
        "nodes": [
            {
                "hostname": "node-1",
                "show_variables_all": {
                    "attach_rebalance_delay_seconds": "300",
                    "auto_attach": "OFF",
                    "leaf_failure_detection": "OFF",
                    "interpreter_mode": "interpret_first",
                },
            }
        ]
    }
    findings = run_superchecker(report)
    ids = {f["checker_id"] for f in findings}
    assert "attachRebalanceDelay" in ids
    assert "autoAttach" in ids
    assert "failureDetectionOn" in ids
    assert "defaultVariables" not in ids


def test_cgroup_memory_usage_warning_and_critical():
    report = {
        "nodes": [
            {
                "hostname": "node-warn",
                "os_checks": {
                    "cgroup_info": {
                        "usage_bytes": 85,
                        "limit_bytes": 100,
                        "usage_pct": 85.0,
                    }
                },
            },
            {
                "hostname": "node-crit",
                "os_checks": {
                    "cgroup_info": {
                        "usage_bytes": 95,
                        "limit_bytes": 100,
                        "usage_pct": 95.0,
                    }
                },
            },
        ]
    }
    findings = run_superchecker(report)
    cg = [f for f in findings if f["checker_id"] == "cgroupMemoryUsage"]
    assert len(cg) == 2
    by_host = {f["nodes"][0]: f["severity"] for f in cg}
    assert by_host["node-warn"] == "warning"
    assert by_host["node-crit"] == "critical"


def test_security_checklist_emitters():
    """Representative sdbHC* checkers fire from variables / users / process evidence."""
    report = {
        "users": [
            {"User": "dashboard", "Host": "%"},
            {"User": "root", "Host": "localhost", "password": ""},
        ],
        "nodes": [
            {
                "hostname": "agg-1",
                "show_variables_all": {
                    "enable_wasm": "ON",
                    "http_api": "ON",
                    "auditlog_level": "OFF",
                    "node_replication_ssl_only": "OFF",
                    "default_user_require_ssl": "OFF",
                    "bind_address": "0000:0000:0000:0000:0000:0000:0000:0000",
                    "ssl_cert": "",
                    "ssl_key": "",
                    "password_min_length": "4",
                    "sync_permissions": "OFF",
                    "port": "3306",
                },
                "metrics": {
                    "ps": [
                        {"user": "root", "pid": "1", "cmd": "/bin/memsqld", "stat": "S",
                         "cpu_pct": "0", "mem_pct": "0", "vsz": "0", "rss": "0",
                         "start": "00:00", "time": "0:00"}
                    ]
                },
                "encrypted_block_devices": {"encrypted": False, "evidence": "NAME TYPE"},
            }
        ],
    }
    findings = run_superchecker(report)
    ids = {f["checker_id"] for f in findings}
    expected = {
        "sdbHCUnnecessaryDefaultUsers",
        "sdbHCRootPassword",
        "sdbHCEnableWASM",
        "sdbHChttpAPI",
        "sdbHCAuditlogLevel",
        "sdbHCReplicationTlsOnly",
        "sdbHCDefaultUserRequireSSL",
        "sdbHCBindAddress",
        "sdbHCNetworkAccess",
        "sdbHCTlsCertKey",
        "sdbHCPasswordPolicy",
        "sdbHCSyncPermissions",
        "sdbHCDefaultPort",
        "sdbHCServiceAccount",
        "sdbHCEncryptedBlockDevice",
    }
    missing = expected - ids
    assert not missing, f"Missing security checkers: {sorted(missing)}"


def test_ps_aux_stat_and_cmd_drive_process_checkers():
    """STAT/COMMAND must come from ps aux indexes 7/10 (not TTY/TIME)."""
    report = {
        "nodes": [
            {
                "hostname": "leaf-1",
                "metrics": {
                    "ps": [
                        {
                            "user": "memsql",
                            "pid": "1234",
                            "tty": "?",
                            "stat": "Z",
                            "start": "Jan01",
                            "time": "0:05",
                            "cmd": "[orchestrator] <defunct>",
                        },
                        {
                            "user": "root",
                            "pid": "1",
                            "tty": "?",
                            "stat": "Ss",
                            "start": "Jan01",
                            "time": "0:05",
                            "cmd": "/usr/bin/chronyd -f /etc/chrony.conf",
                        },
                    ]
                },
            }
        ]
    }
    findings = run_superchecker(report)
    ids = {f["checker_id"] for f in findings}
    assert "defunctProcesses" in ids
    assert "orchestratorProcesses" in ids
    assert "chronydDisabled" in ids
