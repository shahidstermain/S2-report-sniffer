import pytest
from backend.superchecker import run_superchecker

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
