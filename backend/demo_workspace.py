from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from storage import LocalReportStore


DEMO_WORKSPACE_VERSION = "2026.08-guided-mode"
DEMO_REPORT_IDS = {
    "incident": "11111111-2222-4333-8444-555555555501",
    "remediated": "11111111-2222-4333-8444-555555555502",
}


def _iso(minutes_delta: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_delta)).isoformat()


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
                "title": "Backup chain recovered",
                "description": "Synthetic remediation snapshot shows the backup history returning to successful runs.",
                "recommendation": "Keep monitoring backup duration and retention after the maintenance window.",
                "risk_score": 8,
                "confidence": 0.86,
                "basis": "observed",
            }
        ]

    return [
        {
            "checker_id": "nodeOffline",
            "severity": "critical",
            "title": "Leaf node is degraded or offline",
            "description": "One synthetic leaf is reporting a degraded state while other nodes are carrying additional partition work.",
            "recommendation": "Start with node health, disk saturation, and network timeout traces before rebalancing.",
            "risk_score": 92,
            "confidence": 0.94,
            "basis": "observed",
            "log_context": [{"hostname": "demo-leaf-2", "message": "ETIMEDOUT waiting for leaf heartbeat"}],
        },
        {
            "checker_id": "memoryPressure",
            "severity": "warning",
            "title": "High memory pressure on leaves",
            "description": "Synthetic leaf memory utilization is above the Sniffer heuristic warning band.",
            "recommendation": "Review long-running queries and resource pool pressure before increasing concurrency.",
            "risk_score": 68,
            "confidence": 0.9,
            "basis": "heuristic",
        },
        {
            "checker_id": "backupReliability",
            "severity": "warning",
            "title": "Recent backup failed",
            "description": "The demo backup history includes a failed backup followed by a longer-than-normal retry.",
            "recommendation": "Validate backup destination throughput and check tracelog backup events.",
            "risk_score": 64,
            "confidence": 0.88,
            "basis": "observed",
            "log_context": [{"hostname": "demo-ca-1", "message": "Backup failed: destination write timeout"}],
        },
        {
            "checker_id": "longRunningQueries",
            "severity": "warning",
            "title": "Long-Running Queries above Sniffer threshold",
            "description": "Synthetic processlist data includes a query running beyond the product-defined Sniffer elapsed-time threshold.",
            "recommendation": "Open Query Tracer and Log Search to correlate query text with locks and memory pressure.",
            "risk_score": 58,
            "confidence": 0.82,
            "basis": "heuristic",
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
            {"timestamp": _iso(-18), "severity": "warn", "hostname": "demo-leaf-3", "message": "fsync is behind by 2750ms"},
            {"timestamp": _iso(-11), "severity": "error", "hostname": "demo-leaf-2", "message": "synchronous replication transitioned to asynchronous mode"},
        ])
    else:
        base.extend([
            {"timestamp": _iso(-18), "severity": "info", "hostname": "demo-leaf-2", "message": "Leaf heartbeat recovered"},
            {"timestamp": _iso(-15), "severity": "info", "hostname": "demo-ca-1", "message": "Backup completed successfully"},
            {"timestamp": _iso(-9), "severity": "info", "hostname": "demo-leaf-3", "message": "fsync latency back within normal operating band"},
        ])
    return base


def _payload(kind: str) -> dict[str, Any]:
    active = kind == "incident"
    report_id = DEMO_REPORT_IDS[kind]
    recs = _recommendations(active)
    logs = _logs(active)
    health_score = 42 if active else 92
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
    database_disk_usage = [
        {"database_name": "demo_sales", "compressed_size_mb": 184320 if active else 152000, "uncompressed_size_mb": 402000 if active else 330000},
        {"database_name": "demo_ops", "compressed_size_mb": 76800 if active else 64100, "uncompressed_size_mb": 155000 if active else 130000},
    ]

    return {
        "id": report_id,
        "report_name": "Demo: Active Incident" if active else "Demo: After Remediation",
        "uploaded_at": _iso(-60 if active else -20),
        "parsed_at": _iso(-59 if active else -19),
        "detected_format": "demo",
        "input_mode": "demo",
        "is_demo": True,
        "demo_workspace_version": DEMO_WORKSPACE_VERSION,
        "demo_scenario": kind,
        "privacy": {"synthetic": True, "anonymized": True, "contains_customer_data": False},
        "version": "8.7.14",
        "health_score": health_score,
        "health_grade": "F" if active else "A",
        "cluster_risk_score": 100 - health_score,
        "capabilities": {
            "partial": False,
            "overview": True,
            "disk-intelligence": True,
            "charts": True,
            "diagnostics": True,
            "nodes": True,
            "storage": True,
            "queries": True,
            "logs": True,
            "log-search": True,
            "config": True,
            "recommendations": True,
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
        "storage": [{"node": n["hostname"], "disk_used_pct": n["disk_used_pct"]} for n in nodes],
        "databases": [{"name": "demo_sales"}, {"name": "demo_ops"}],
        "database_disk_usage": {"rows": database_disk_usage},
        "table_storage": {
            "tables": [
                {"database": "demo_sales", "table": "orders", "compressed_size_mb": 122000 if active else 98000, "skew_ratio": 2.7 if active else 1.1},
                {"database": "demo_ops", "table": "inventory", "compressed_size_mb": 42000 if active else 39000, "skew_ratio": 1.9 if active else 1.0},
            ]
        },
        "partitions": {"high_skew_tables": 2 if active else 0, "max_skew_ratio": 2.7 if active else 1.1},
        "cluster_overhead": {"internal_overhead_pct": 14 if active else 8},
        "blobs_referenced_delta": {"growth_mb": 8192 if active else 256},
        "disk_intelligence": {
            "summary": {
                "reclaimable_mb": 28672 if active else 2048,
                "risk_level": "high" if active else "low",
                "is_estimate": True,
                "ha_adjusted": True,
            },
            "recommendations": ["Review table skew before expanding storage"] if active else ["No urgent disk action in demo remediation snapshot"],
        },
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


async def ensure_demo_workspace(store: LocalReportStore) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for kind in ("incident", "remediated"):
        payload = _payload(kind)
        report_id = payload["id"]
        existing = await store.get_report_fields(report_id, fields=["id"])
        if not existing:
            await store.create_report_stub(
                report_id,
                payload["report_name"],
                0,
                "demo",
            )
        await store.write_report_payload(report_id, payload)
        await store.write_report_logs(report_id, payload["logs"])
        await store.update_report_fields(
            report_id,
            {
                "report_name": payload["report_name"],
                "uploaded_at": payload["uploaded_at"],
                "status": "ready",
                "file_size": 0,
                "detected_format": "demo",
                "node_count": payload["cluster_overview"]["total_nodes"],
                "version": payload["version"],
                "health_score": str(payload["health_score"]),
                "recommendation_count": len(payload["recommendations"]),
                "cluster_risk_score": payload["cluster_risk_score"],
                "parsed_at": payload["parsed_at"],
                "deployment_method": "Self-managed demo",
                "deployment_confidence": "synthetic",
                "deployment_signals": "Synthetic guided-mode fixture",
                "log_count": len(payload["logs"]),
                "is_demo": 1,
                "progress_json": '{"stage":"complete","pct":100,"message":"Demo workspace ready"}',
            },
        )
        reports.append(
            {
                "id": report_id,
                "report_name": payload["report_name"],
                "scenario": kind,
                "health_score": payload["health_score"],
                "recommendation_count": len(payload["recommendations"]),
            }
        )

    return {
        "workspace": "guided-demo",
        "version": DEMO_WORKSPACE_VERSION,
        "synthetic": True,
        "reports": reports,
        "message": "Demo workspace ready",
    }
