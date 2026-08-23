from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from health_scoring import compute_health_metrics
from product_features import build_capabilities
from storage import LocalReportStore


DEMO_WORKSPACE_VERSION = "2026.08-guided-disk"
DEMO_REPORT_IDS = {
    "incident": "11111111-2222-4333-8444-555555555501",
    "remediated": "11111111-2222-4333-8444-555555555502",
}
_DEMO_WORKSPACE_LOCK = asyncio.Lock()


def _iso(minutes_delta: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_delta)).isoformat()


def _gib(value: float) -> int:
    return int(value * (1024 ** 3))


def _node(hostname: str, role: str, state: str, memory_pct: int, disk_pct: int) -> dict[str, Any]:
    return {
        "hostname": hostname,
        "role": role,
        "state": state,
        "status": "online" if state == "ONLINE" else "degraded",
        "memory_used_pct": memory_pct,
        "disk_used_pct": disk_pct,
        "version": "8.7.14",
        "config": {
            "process_limits": {
                "open_files": 4096 if memory_pct > 80 else 65535,
                "max_user_processes": 32768,
            }
        },
        "os_checks": {
            "fsync_lag_ms": 2750 if disk_pct > 85 else 180,
            "swappiness": 10,
        },
    }


def _recommendations(active_incident: bool) -> list[dict[str, Any]]:
    if not active_incident:
        return [
            {
                "checker_id": "backupReliability",
                "severity": "info",
                "category": "Backup",
                "title": "Backup chain recovered",
                "description": "Synthetic remediation snapshot shows the backup history returning to successful runs.",
                "evidence": "Synthetic backup history contains successful runs after remediation.",
                "remediation": "Keep monitoring backup duration and retention after the maintenance window.",
                "risk_score": 8,
                "confidence": 0.86,
                "basis": "observed",
                "triage": {
                    "impact": "monitoring",
                    "effort": "low",
                    "blast_radius": "cluster-wide",
                    "quick_win": True,
                    "priority": 3,
                    "recommended_action": "Monitor backup duration and retention.",
                },
            },
            {
                "checker_id": "diskUsage",
                "severity": "info",
                "category": "Disk",
                "title": "Disk pressure recovered",
                "description": "Synthetic post-remediation storage is below the demo warning band and temporary spill has been cleared.",
                "evidence": "Synthetic mount usage fell from 89% to 50% and spill overhead fell from 42 GiB to 2 GiB.",
                "remediation": "Continue trending mount usage, table growth, and non-table overhead.",
                "risk_score": 8,
                "confidence": 0.96,
                "basis": "observed",
                "triage": {
                    "impact": "monitoring",
                    "effort": "low",
                    "blast_radius": "cluster-wide",
                    "quick_win": True,
                    "priority": 3,
                    "recommended_action": "Continue monitoring disk growth and overhead.",
                },
            },
        ]

    return [
        {
            "checker_id": "nodeOffline",
            "severity": "critical",
            "category": "Availability",
            "title": "Leaf node is degraded or offline",
            "description": "One synthetic leaf is reporting a degraded state while other nodes are carrying additional partition work.",
            "evidence": "demo-leaf-2 is degraded and its heartbeat timed out.",
            "remediation": "Start with node health, disk saturation, and network timeout traces before rebalancing.",
            "risk_score": 92,
            "confidence": 0.94,
            "basis": "observed",
            "triage": {
                "impact": "availability",
                "effort": "medium",
                "blast_radius": "node",
                "quick_win": False,
                "priority": 1,
                "recommended_action": "Investigate demo-leaf-2 before rebalancing.",
            },
            "log_context": [{"hostname": "demo-leaf-2", "message": "ETIMEDOUT waiting for leaf heartbeat"}],
        },
        {
            "checker_id": "memoryPressure",
            "severity": "warning",
            "category": "Memory",
            "title": "High memory pressure on leaves",
            "description": "Synthetic leaf memory utilization is above the Sniffer heuristic warning band.",
            "evidence": "Synthetic leaf memory utilization reaches 91%.",
            "remediation": "Review long-running queries and resource pool pressure before increasing concurrency.",
            "risk_score": 68,
            "confidence": 0.9,
            "basis": "heuristic",
            "triage": {
                "impact": "performance",
                "effort": "medium",
                "blast_radius": "cluster-wide",
                "quick_win": False,
                "priority": 2,
                "recommended_action": "Review query and resource-pool memory pressure.",
            },
        },
        {
            "checker_id": "diskUsage",
            "severity": "warning",
            "category": "Disk",
            "title": "Leaf disks are approaching capacity",
            "description": "Synthetic filesystem snapshots show two leaves above the demo warning band, with spill and snapshot overhead consuming capacity.",
            "evidence": "demo-leaf-2 is 88% used and demo-leaf-3 is 92% used; non-table overhead is 160 GiB.",
            "remediation": "Inspect Disk Intelligence, validate reclaimable estimates, and reduce spill or snapshot retention before adding capacity.",
            "risk_score": 76,
            "confidence": 0.95,
            "basis": "observed",
            "triage": {
                "impact": "availability",
                "effort": "medium",
                "blast_radius": "node",
                "quick_win": True,
                "priority": 1,
                "recommended_action": "Review disk overhead and the highest-utilization leaves.",
            },
            "log_context": [{"hostname": "demo-leaf-3", "message": "fsync is behind by 2750ms"}],
        },
        {
            "checker_id": "backupReliability",
            "severity": "warning",
            "category": "Backup",
            "title": "Recent backup failed",
            "description": "The demo backup history includes a failed backup followed by a longer-than-normal retry.",
            "evidence": "Synthetic backup history contains a failed run and destination timeout.",
            "remediation": "Validate backup destination throughput and check tracelog backup events.",
            "risk_score": 64,
            "confidence": 0.88,
            "basis": "observed",
            "triage": {
                "impact": "recoverability",
                "effort": "medium",
                "blast_radius": "cluster-wide",
                "quick_win": False,
                "priority": 2,
                "recommended_action": "Validate backup destination throughput.",
            },
            "log_context": [{"hostname": "demo-ca-1", "message": "Backup failed: destination write timeout"}],
        },
        {
            "checker_id": "longRunningQueries",
            "severity": "warning",
            "category": "Queries",
            "title": "Long-Running Queries above Sniffer threshold",
            "description": "Synthetic processlist data includes a query running beyond the product-defined Sniffer elapsed-time threshold.",
            "evidence": "Synthetic processlist includes a query executing for 385 seconds.",
            "remediation": "Open Query Tracer and Log Search to correlate query text with locks and memory pressure.",
            "risk_score": 58,
            "confidence": 0.82,
            "basis": "heuristic",
            "triage": {
                "impact": "performance",
                "effort": "low",
                "blast_radius": "workload",
                "quick_win": True,
                "priority": 2,
                "recommended_action": "Correlate long-running queries with locks and memory.",
            },
        },
    ]


def _logs(active_incident: bool) -> list[dict[str, Any]]:
    base = [
        {"timestamp": _iso(-31), "severity": "info", "hostname": "demo-ca-1", "message": "Started backup demo_backup_20260823"},
        {"timestamp": _iso(-29), "severity": "info", "hostname": "demo-leaf-1", "message": "MV_PROCESSLIST snapshot captured 7 active queries"},
    ]
    if active_incident:
        base.extend([
            {"timestamp": _iso(-25), "severity": "warn", "hostname": "demo-leaf-2", "message": "ETIMEDOUT waiting for leaf heartbeat"},
            {"timestamp": _iso(-23), "severity": "error", "hostname": "demo-ca-1", "message": "Backup failed: destination write timeout"},
            {"timestamp": _iso(-20), "severity": "warn", "hostname": "demo-leaf-3", "message": "Filesystem /var/lib/memsql is 92% used"},
            {"timestamp": _iso(-18), "severity": "warn", "hostname": "demo-leaf-3", "message": "fsync is behind by 2750ms"},
            {"timestamp": _iso(-11), "severity": "error", "hostname": "demo-leaf-2", "message": "synchronous replication transitioned to asynchronous mode"},
        ])
    else:
        base.extend([
            {"timestamp": _iso(-18), "severity": "info", "hostname": "demo-leaf-2", "message": "Leaf heartbeat recovered"},
            {"timestamp": _iso(-15), "severity": "info", "hostname": "demo-ca-1", "message": "Backup completed successfully"},
            {"timestamp": _iso(-12), "severity": "info", "hostname": "demo-leaf-3", "message": "Filesystem /var/lib/memsql usage reduced to 50%"},
            {"timestamp": _iso(-9), "severity": "info", "hostname": "demo-leaf-3", "message": "fsync latency back within normal operating band"},
        ])
    return base


def _payload(kind: str) -> dict[str, Any]:
    active = kind == "incident"
    report_id = DEMO_REPORT_IDS[kind]
    recs = _recommendations(active)
    logs = _logs(active)
    health_score, health_grade, cluster_risk_score = compute_health_metrics(recs)
    nodes = [
        _node("demo-ca-1", "CA", "ONLINE", 52, 43),
        _node("demo-leaf-1", "LEAF", "ONLINE", 84 if active else 57, 76 if active else 49),
        _node("demo-leaf-2", "LEAF", "DEGRADED" if active else "ONLINE", 91 if active else 54, 88 if active else 51),
        _node("demo-leaf-3", "LEAF", "ONLINE", 79 if active else 55, 92 if active else 50),
    ]
    queries = [
        {
            "id": "demo-query-1",
            "connection_id": "9421",
            "elapsed_time_ms": 385000 if active else 12000,
            "state": "Executing" if active else "Completed",
            "memory_mb": 14800 if active else 1200,
            "query_text": "SELECT customer_id, SUM(amount) FROM demo_orders GROUP BY customer_id ORDER BY 2 DESC",
            "database": "demo_sales",
            "host": "demo-leaf-1",
        },
        {
            "id": "demo-query-2",
            "connection_id": "9429",
            "elapsed_time_ms": 94000 if active else 8000,
            "state": "Waiting on lock" if active else "Completed",
            "memory_mb": 5200 if active else 600,
            "query_text": "UPDATE demo_inventory SET quantity = quantity - 1 WHERE sku = ?",
            "database": "demo_ops",
            "host": "demo-leaf-2",
        },
    ]
    database_sizes_gib = {
        "demo_sales": 612 if active else 430,
        "demo_ops": 188 if active else 150,
    }
    database_disk_usage = [
        {
            "DATABASE_NAME": database,
            "TOTAL_DISK_USAGE_GB": size_gib,
            "_disk_bytes": _gib(size_gib),
            "_source": "database_disk_usage",
        }
        for database, size_gib in database_sizes_gib.items()
    ]
    overhead_sizes_gib = {
        "transaction_logs": 32 if active else 8,
        "snapshots": 48 if active else 16,
        "tracelogs": 10 if active else 4,
        "spill": 42 if active else 2,
        "unreferenced_blobs": 28 if active else 6,
        "other_overhead": 0 if active else 4,
    }
    used_disk_gib = 960 if active else 620
    attributed_table_gib = sum(database_sizes_gib.values())
    overhead_gib = sum(overhead_sizes_gib.values())
    overhead_children = {
        key: {
            "bytes": _gib(size_gib),
            "pct_of_used_disk": round((size_gib / used_disk_gib) * 100, 1),
        }
        for key, size_gib in overhead_sizes_gib.items()
        if size_gib > 0
    }
    per_node_disk = [
        {
            "node": "demo-leaf-1",
            "status": "complete",
            "on_disk_blobs_bytes": _gib(286 if active else 198),
            "referenced_adjusted_bytes": _gib(262 if active else 196),
            "delta_bytes": _gib(24 if active else 2),
            "delta_pct": 8.4 if active else 1.0,
        },
        {
            "node": "demo-leaf-2",
            "status": "complete",
            "on_disk_blobs_bytes": _gib(274 if active else 194),
            "referenced_adjusted_bytes": _gib(238 if active else 191),
            "delta_bytes": _gib(36 if active else 3),
            "delta_pct": 13.1 if active else 1.5,
        },
        {
            "node": "demo-leaf-3",
            "status": "complete",
            "on_disk_blobs_bytes": _gib(264 if active else 190),
            "referenced_adjusted_bytes": _gib(252 if active else 189),
            "delta_bytes": _gib(12 if active else 1),
            "delta_pct": 4.5 if active else 0.5,
        },
    ]
    cluster_overhead = {
        "used_disk_bytes": _gib(used_disk_gib),
        "attributed_table_bytes": _gib(attributed_table_gib),
        "total_bytes": _gib(overhead_gib),
        "pct_of_used_disk": round((overhead_gib / used_disk_gib) * 100, 1),
        "children": overhead_children,
    }
    blobs_referenced_delta = {
        "status": "ok",
        "ha_factor": 2,
        "ha_assumption": "Synthetic demo assumes redundancy factor 2; referenced bytes are HA-adjusted.",
        "incomplete_nodes": [],
        "per_node": per_node_disk,
    }
    disk_intelligence = {
        "summary": {
            "total_used_bytes": _gib(used_disk_gib),
            "attributed_table_bytes": _gib(attributed_table_gib),
            "overhead_bytes": _gib(overhead_gib),
            "overhead_pct": round((overhead_gib / used_disk_gib) * 100, 1),
            "reclaimable_mb": (72 if active else 6) * 1024,
            "risk_level": "high" if active else "low",
            "is_estimate": True,
            "ha_adjusted": True,
            "incomplete_nodes": [],
        },
        "cluster_overhead": overhead_children,
        "per_node": per_node_disk,
        "remediation_hints": [
            "Validate spill and snapshot retention before adding capacity.",
            "Treat unreferenced-blob bytes as an estimate until verified on the cluster.",
        ] if active else [
            "Continue trending mount usage and non-table overhead.",
        ],
    }

    payload = {
        "id": report_id,
        "report_name": "Demo: Active Incident" if active else "Demo: After Remediation",
        "uploaded_at": _iso(-60 if active else -40),
        "parsed_at": _iso(-5),
        "status": "ready",
        "file_size": 0,
        "detected_format": "demo",
        "input_mode": "demo",
        "is_demo": True,
        "demo_workspace_version": DEMO_WORKSPACE_VERSION,
        "demo_scenario": kind,
        "privacy": {"synthetic": True, "anonymized": True, "contains_customer_data": False},
        "version": "8.7.14",
        "health_score": health_score,
        "health_grade": health_grade,
        "cluster_risk_score": cluster_risk_score,
        "node_count": len(nodes),
        "log_count": len(logs),
        "deployment_method": "Self-managed demo",
        "deployment_confidence": "synthetic",
        "deployment_signals": "Synthetic guided-mode fixture",
        "progress": {
            "stage": "complete",
            "pct": 100,
            "message": "Demo workspace ready",
        },
        "collector_availability": {
            "mv_nodes": True,
            "cluster_status": True,
            "show_variables": True,
            "processlist": True,
            "tracelogs": True,
        },
        "cluster_overview": {
            "version": "8.7.14",
            "total_nodes": len(nodes),
            "nodes": len(nodes),
            "leaves": 3,
            "aggregators": 1,
            "memory_usage_pct": 86 if active else 55,
            "disk_usage_pct": 89 if active else 50,
            "backup_status": "failed" if active else "healthy",
            "queries": len(queries),
            "nodes_detail": nodes,
            "processlist": queries,
            "mv_processlist": queries,
            "blocked_queries": [queries[1]] if active else [],
        },
        "nodes": nodes,
        "logs": logs,
        "queries": queries,
        "workload_management": [{"pool": "default_pool", "queued_queries": 5 if active else 0, "memory_pressure": "high" if active else "normal"}],
        "resource_pools": [{"name": "default_pool", "memory_percentage": 82 if active else 45, "concurrency": 16}],
        "alloc_memory": {"cluster_total_mb": 262144, "cluster_used_mb": 225443 if active else 144179},
        "storage": [
            {
                "TABLE_SCHEMA": "demo_sales",
                "TABLE_NAME": "orders",
                "STORAGE_TYPE": "COLUMNSTORE",
                "ROW_COUNT": 820_000_000 if active else 640_000_000,
                "MEMORY_USE": _gib(36 if active else 24),
                "DISK_USE": _gib(356 if active else 262),
            },
            {
                "TABLE_SCHEMA": "demo_sales",
                "TABLE_NAME": "order_items",
                "STORAGE_TYPE": "COLUMNSTORE",
                "ROW_COUNT": 1_860_000_000 if active else 1_420_000_000,
                "MEMORY_USE": _gib(48 if active else 31),
                "DISK_USE": _gib(256 if active else 168),
            },
            {
                "TABLE_SCHEMA": "demo_ops",
                "TABLE_NAME": "inventory",
                "STORAGE_TYPE": "INMEMORY_ROWSTORE",
                "ROW_COUNT": 4_200_000,
                "MEMORY_USE": _gib(18 if active else 12),
                "DISK_USE": _gib(38 if active else 28),
            },
        ],
        "databases": [
            {"Database": "demo_sales", "Role": "master", "State": "online", "Memory (MBs)": 86016},
            {"Database": "demo_ops", "Role": "master", "State": "online", "Memory (MBs)": 24576},
        ],
        "database_disk_usage": {"rows": database_disk_usage},
        "table_storage": {
            "summary": {
                "total_tables": 4,
                "columnstore_tables": 3,
                "rowstore_tables": 1,
                "unknown_tables": 0,
            },
            "tables": [
                {
                    "database": "demo_sales",
                    "table": "orders",
                    "table_type": "BASE TABLE",
                    "storage_type": "columnstore",
                    "distributed": True,
                    "row_count": 820_000_000 if active else 640_000_000,
                    "row_format": "COLUMNSTORE",
                },
                {
                    "database": "demo_sales",
                    "table": "order_items",
                    "table_type": "BASE TABLE",
                    "storage_type": "columnstore",
                    "distributed": True,
                    "row_count": 1_860_000_000 if active else 1_420_000_000,
                    "row_format": "COLUMNSTORE",
                },
                {
                    "database": "demo_sales",
                    "table": "events",
                    "table_type": "BASE TABLE",
                    "storage_type": "columnstore",
                    "distributed": True,
                    "row_count": 1_240_000_000 if active else 940_000_000,
                    "row_format": "COLUMNSTORE",
                },
                {
                    "database": "demo_ops",
                    "table": "inventory",
                    "table_type": "BASE TABLE",
                    "storage_type": "rowstore",
                    "distributed": True,
                    "row_count": 4_200_000,
                    "row_format": "INMEMORY_ROWSTORE",
                },
            ]
        },
        "partitions": {
            "demo_sales": {
                "count": 8,
                "partitions": [
                    {
                        "Ordinal": index,
                        "Host": (
                            "demo-leaf-3"
                            if active and index < 6
                            else f"demo-leaf-{(index % 3) + 1}"
                        ),
                        "Role": "master" if index % 2 == 0 else "slave",
                        "State": "online",
                    }
                    for index in range(8)
                ],
            },
            "demo_ops": {
                "count": 6,
                "partitions": [
                    {
                        "Ordinal": index,
                        "Host": f"demo-leaf-{(index % 3) + 1}",
                        "Role": "master" if index % 2 == 0 else "slave",
                        "State": "online",
                    }
                    for index in range(6)
                ],
            },
        },
        "cluster_overhead": cluster_overhead,
        "blobs_referenced_delta": blobs_referenced_delta,
        "disk_intelligence": disk_intelligence,
        "backup_history": {
            "rows": [
                {"database": "demo_sales", "status": "Failed" if active else "Success", "duration_seconds": 7200 if active else 1400, "completed_at": _iso(-24)},
                {"database": "demo_ops", "status": "Success", "duration_seconds": 1800 if active else 900, "completed_at": _iso(-48)},
            ]
        },
        "config_health": {
            "issues": [
                {"severity": "warning", "setting": "ulimit -n", "current": "4096", "recommended": "65535", "basis": "Sniffer heuristic"}
            ] if active else [],
            "summary": "Synthetic configuration finding present" if active else "No synthetic configuration issues",
        },
        "users": [{"user": "demo_admin", "host": "%"}],
        "version_history": [{"version": "8.7.14", "installed_at": _iso(-1440)}],
        "recommendations": recs,
        "pipelines": [{"name": "demo_ingest", "state": "Running" if not active else "Paused"}],
        "extended_diagnostics": {
            "collector_availability": {"mv_events": True, "cpu": True, "network": True},
            "cpu_health": {"max_cpu_pct": 94 if active else 37, "status": "pressure" if active else "normal"},
            "network_health": {"timeouts": 3 if active else 0},
            "events": [
                {"timestamp": _iso(-28), "event_type": "NODE_STATE", "message": "demo-leaf-2 degraded" if active else "demo-leaf-2 online"},
                {"timestamp": _iso(-16), "event_type": "REBALANCE", "message": "partition movement slowed by disk pressure" if active else "rebalance complete"},
            ],
        },
        "parse_warnings": [],
    }
    payload["capabilities"] = build_capabilities(payload)
    return payload


async def _ensure_demo_report(
    store: LocalReportStore,
    kind: str,
) -> dict[str, Any]:
    payload = _payload(kind)
    report_id = payload["id"]
    await store.create_report_stub(
        report_id,
        payload["report_name"],
        0,
        "demo",
        if_not_exists=True,
    )
    await store.write_report_payload(report_id, payload)
    await store.write_report_logs(report_id, payload["logs"])
    await store.update_report_fields(
        report_id,
        {
            "report_name": payload["report_name"],
            "uploaded_at": payload["uploaded_at"],
            "status": payload["status"],
            "file_size": payload["file_size"],
            "detected_format": payload["detected_format"],
            "node_count": payload["node_count"],
            "version": payload["version"],
            "health_score": str(payload["health_score"]),
            "recommendation_count": len(payload["recommendations"]),
            "cluster_risk_score": payload["cluster_risk_score"],
            "parsed_at": payload["parsed_at"],
            "deployment_method": payload["deployment_method"],
            "deployment_confidence": payload["deployment_confidence"],
            "deployment_signals": payload["deployment_signals"],
            "log_count": payload["log_count"],
            "is_demo": 1,
            "progress_json": (
                '{"stage":"complete","pct":100,'
                '"message":"Demo workspace ready"}'
            ),
        },
    )
    return {
        "id": report_id,
        "report_name": payload["report_name"],
        "scenario": kind,
        "health_score": payload["health_score"],
        "recommendation_count": len(payload["recommendations"]),
    }


async def ensure_demo_workspace(store: LocalReportStore) -> dict[str, Any]:
    """Create or refresh the synthetic workspace as one in-process operation."""

    async with _DEMO_WORKSPACE_LOCK:
        reports = [
            await _ensure_demo_report(store, kind)
            for kind in ("incident", "remediated")
        ]

    return {
        "workspace": "guided-demo",
        "version": DEMO_WORKSPACE_VERSION,
        "synthetic": True,
        "reports": reports,
        "message": "Demo workspace ready",
    }
