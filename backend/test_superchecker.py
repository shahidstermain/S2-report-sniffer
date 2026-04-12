import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from superchecker import run_superchecker

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

def test_disk_usage_warning():
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
    assert any(f["checker_id"] == "diskUsage" and f["severity"] == "warning" for f in findings)

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
    """vmMaxMapCount fires when vm.max_map_count is below 1,000,000."""
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
    mmc = [f for f in findings if f["checker_id"] == "vmMaxMapCount"]
    assert mmc, "Expected vmMaxMapCount critical finding"
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
