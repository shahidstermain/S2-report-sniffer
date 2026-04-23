"""
Investigation flow templates for common issue types.
Provides step-by-step debugging paths for support engineers.
"""

INVESTIGATION_FLOWS = {
    "oom_kill_detected": {
        "entryPoint": "oom_kill_detected",
        "steps": [
            "Check affected nodes in cluster overview",
            "Inspect dmesg events for OOM details and victim process",
            "Review memory pressure metrics (free, show-variables)",
            "Check maximum_memory configuration on affected nodes",
            "Review workload management for memory-intensive queries"
        ]
    },
    "disk_full_detected": {
        "entryPoint": "disk_full_detected",
        "steps": [
            "Check affected nodes and mount points in df output",
            "Review database disk usage by database",
            "Check for large log files in memsql.log",
            "Review columnstore disk usage and partition distribution",
            "Consider running REBALANCE PARTITIONS or adding disk space"
        ]
    },
    "replication_failure": {
        "entryPoint": "replication_failure",
        "steps": [
            "Check MV_REPLICATION_STATUS for failed partitions",
            "Verify network connectivity between node pairs",
            "Review replication lag metrics",
            "Check for disk full on aggregator or leaf nodes",
            "Inspect error logs for replication-specific errors"
        ]
    },
    "high_memory_usage": {
        "entryPoint": "high_memory_usage",
        "steps": [
            "Review memory usage across all nodes",
            "Check maximum_memory configuration vs physical RAM",
            "Identify memory-intensive queries in MV_QUERIES",
            "Review columnstore memory usage",
            "Check for memory leaks or long-running transactions"
        ]
    },
    "blocked_queries": {
        "entryPoint": "blocked_queries",
        "steps": [
            "Check MV_BLOCKED_QUERIES for blocking transactions",
            "Identify the blocking query and transaction",
            "Review lock wait timeout settings",
            "Check for long-running transactions in MV_PROCESSLIST",
            "Consider KILL QUERY for blocking sessions"
        ]
    },
    "node_offline": {
        "entryPoint": "node_offline",
        "steps": [
            "Check MV_NODES for node availability status",
            "Review node-specific error logs",
            "Verify network connectivity to the node",
            "Check system-level services (memsqld status)",
            "Review system metrics for resource exhaustion"
        ]
    },
    "config_misconfiguration": {
        "entryPoint": "config_misconfiguration",
        "steps": [
            "Review SHOW VARIABLES output for affected settings",
            "Compare configuration across nodes",
            "Check config_health for OS-level issues",
            "Verify settings match SingleStore recommendations",
            "Review documentation for specific variable requirements"
        ]
    },
    "backup_failure": {
        "entryPoint": "backup_failure",
        "steps": [
            "Check MV_BACKUP_HISTORY for failure patterns",
            "Review backup-specific error logs",
            "Verify backup storage location and permissions",
            "Check for disk space issues during backup",
            "Review backup configuration and schedule"
        ]
    }
}


def get_investigation_flow(checker_id: str) -> dict:
    """Get investigation flow template for a given checker ID."""
    # Map common checker IDs to investigation flows
    flow_mapping = {
        "tracelogOOM": "oom_kill_detected",
        "diskUsage": "disk_full_detected",
        "replicationHealth": "replication_failure",
        "clusterMemoryUsage": "high_memory_usage",
        "blockedQueries": "blocked_queries",
        "nodeOffline": "node_offline",
        "transparentHugepage": "config_misconfiguration",
        "maxOpenFiles": "config_misconfiguration",
        "backupReliability": "backup_failure",
    }
    
    flow_key = flow_mapping.get(checker_id)
    if flow_key:
        return INVESTIGATION_FLOWS.get(flow_key, {
            "entryPoint": checker_id,
            "steps": ["Review the issue details and evidence", "Check related system metrics", "Inspect relevant logs"]
        })
    
    return {
        "entryPoint": checker_id,
        "steps": ["Review the issue details and evidence", "Check related system metrics", "Inspect relevant logs"]
    }


def estimate_blast_radius(checker_id: str, nodes: list, report: dict) -> dict:
    """Estimate blast radius (impact scope) for a finding."""
    if not isinstance(nodes, list):
        nodes = []
    node_count = len(nodes)
    
    report_nodes = report.get("nodes", [])
    if not isinstance(report_nodes, list):
        report_nodes = []
    total_nodes = len(report_nodes) or 1
    
    # Determine scope based on node count and checker type
    if node_count == 0:
        scope = "cluster-wide"
    elif node_count == 1:
        scope = "node-local"
    elif node_count < total_nodes / 2:
        scope = "partial"
    else:
        scope = "cluster-wide"
    
    # Estimate partitions affected for certain checkers
    partitions_affected = 0
    if checker_id and isinstance(checker_id, str):
        checker_lower = checker_id.lower()
        if "replication" in checker_lower or "backup" in checker_lower:
            # Rough estimate based on cluster size
            partitions_affected = total_nodes * 50  # Assume ~50 partitions per node
    
    return {
        "nodesAffected": node_count,
        "partitionsAffected": partitions_affected,
        "scope": scope
    }
