
from backend.superchecker import run_superchecker

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
