import asyncio

from demo_workspace import DEMO_REPORT_IDS, ensure_demo_workspace
from storage import LocalReportStore


def test_demo_workspace_is_idempotent_and_searchable(tmp_path):
    async def _run():
        store = LocalReportStore(base_dir=tmp_path)
        try:
            first = await ensure_demo_workspace(store)
            second = await ensure_demo_workspace(store)

            assert first["synthetic"] is True
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
