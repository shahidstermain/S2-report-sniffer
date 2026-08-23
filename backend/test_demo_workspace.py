import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from demo_workspace import DEMO_REPORT_IDS, ensure_demo_workspace
from storage import LocalReportStore


def test_demo_workspace_is_idempotent_and_searchable(tmp_path):
    async def _run():
        store = LocalReportStore(base_dir=tmp_path)
        try:
            first, concurrent = await asyncio.gather(
                ensure_demo_workspace(store),
                ensure_demo_workspace(store),
            )
            second = await ensure_demo_workspace(store)

            assert first["synthetic"] is True
            assert [r["id"] for r in first["reports"]] == [
                r["id"] for r in concurrent["reports"]
            ]
            assert [r["id"] for r in first["reports"]] == [r["id"] for r in second["reports"]]
            assert {r["scenario"] for r in first["reports"]} == {"incident", "remediated"}

            rows = await store.list_reports()
            demo_rows = [row for row in rows if row.get("is_demo")]
            assert len(demo_rows) == 2
            assert {row["id"] for row in demo_rows} == set(DEMO_REPORT_IDS.values())

            incident = await store.read_report_payload(DEMO_REPORT_IDS["incident"])
            assert incident["is_demo"] is True
            assert incident["privacy"]["synthetic"] is True
            assert incident["recommendations"]
            assert incident["cluster_overview"]["total_nodes"] == 4
            assert incident["status"] == "ready"
            assert incident["node_count"] == 4
            assert incident["log_count"] == len(incident["logs"])
            assert incident["deployment_method"] == "Self-managed demo"
            assert incident["health_score"] == 65
            assert incident["cluster_risk_score"] == 35
            assert incident["health_grade"] == "D"
            disk_summary = incident["disk_intelligence"]["summary"]
            assert disk_summary["risk_level"] == "high"
            assert disk_summary["total_used_bytes"] > disk_summary["attributed_table_bytes"]
            assert disk_summary["overhead_bytes"] > 0
            assert len(incident["disk_intelligence"]["per_node"]) == 3
            assert incident["cluster_overhead"]["children"]["spill"]["bytes"] > 0
            assert incident["table_storage"]["summary"] == {
                "total_tables": 4,
                "columnstore_tables": 3,
                "rowstore_tables": 1,
                "unknown_tables": 0,
            }
            assert all(
                recommendation.get("remediation")
                and recommendation.get("triage", {}).get("recommended_action")
                for recommendation in incident["recommendations"]
            )

            parsed_at = datetime.fromisoformat(incident["parsed_at"])
            evidence_times = [
                datetime.fromisoformat(row["timestamp"])
                for row in incident["logs"]
            ]
            evidence_times.extend(
                datetime.fromisoformat(row["timestamp"])
                for row in incident["extended_diagnostics"]["events"]
            )
            evidence_times.extend(
                datetime.fromisoformat(row["completed_at"])
                for row in incident["backup_history"]["rows"]
            )
            assert max(evidence_times) <= parsed_at

            remediated = await store.read_report_payload(
                DEMO_REPORT_IDS["remediated"]
            )
            assert remediated["health_score"] == 100
            assert remediated["cluster_risk_score"] == 0
            assert (
                remediated["disk_intelligence"]["summary"]["total_used_bytes"]
                < disk_summary["total_used_bytes"]
            )
            assert (
                remediated["cluster_overhead"]["children"]["spill"]["bytes"]
                < incident["cluster_overhead"]["children"]["spill"]["bytes"]
            )

            matches, total, truncated = await store.search_report_logs(
                DEMO_REPORT_IDS["incident"],
                keyword="ETIMEDOUT",
                regex=False,
                case_sensitive=False,
                severities=None,
                node_prefix=None,
                limit=20,
            )
            assert total == 1
            assert truncated is False
            assert matches[0]["hostname"] == "demo-leaf-2"
        finally:
            await store.shutdown()

    asyncio.run(_run())


def test_demo_overview_returns_payload_metadata(tmp_path):
    import server

    store = LocalReportStore(base_dir=tmp_path)
    asyncio.run(ensure_demo_workspace(store))
    previous_store = server.store
    server.store = store
    try:
        client = TestClient(server.app)
        response = client.get(
            f"/api/reports/{DEMO_REPORT_IDS['incident']}/overview"
        )
        disk_response = client.get(
            f"/api/reports/{DEMO_REPORT_IDS['incident']}/disk-intelligence"
        )
        storage_response = client.get(
            f"/api/reports/{DEMO_REPORT_IDS['incident']}/storage"
        )
    finally:
        server.store = previous_store
        asyncio.run(store.shutdown())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["node_count"] == 4
    assert body["log_count"] == 7
    assert body["deployment_method"] == "Self-managed demo"
    assert disk_response.status_code == 200
    disk = disk_response.json()["disk_intelligence"]
    assert disk["summary"]["risk_level"] == "high"
    assert len(disk["per_node"]) == 3
    assert storage_response.status_code == 200
    storage = storage_response.json()
    assert len(storage["database_disk_usage"]) == 2
    assert storage["table_storage"]["summary"]["total_tables"] == 4
