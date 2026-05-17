import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

with patch.dict("os.environ", {"S2RS_DATA_DIR": tempfile.mkdtemp(prefix="s2rs_test_payload_")}):
    import server
    from storage import LocalReportStore


class TestOverviewPayloadPersistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="s2rs_payload_store_")
        self.archive_dir = tempfile.TemporaryDirectory(prefix="s2rs_payload_archive_")
        self.original_store = server.store
        self.store = LocalReportStore(Path(self.temp_dir.name))
        server.store = self.store

    async def asyncTearDown(self):
        server.store = self.original_store
        self.archive_dir.cleanup()
        self.temp_dir.cleanup()

    async def test_background_parse_persists_overview_diagnostic_aggregates(self):
        report_id = str(uuid.uuid4())
        await self.store.create_report_stub(report_id, "support-bundle", 0, "directory")

        parsed = {
            "parsed_at": "2026-05-17T11:00:00+00:00",
            "detected_format": "directory",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.7.1"},
            "nodes": [],
            "logs": [],
            "recommendations": [],
            "log_summary": {},
            "events": [],
            "log_timeframe": {
                "per_node": {
                    "node-a": {
                        "first_log_entry": "2026-05-17 10:00:00.000000",
                        "last_log_entry": "2026-05-17 11:00:00.000000",
                        "coverage_hours": 1.0,
                    }
                },
                "cluster_first": "2026-05-17 10:00:00.000000",
                "cluster_last": "2026-05-17 11:00:00.000000",
            },
            "backup_summary": {
                "total": 2,
                "success_count": 1,
                "failure_count": 1,
                "latest_success_ts": "2026-05-17 10:30:00",
                "latest_duration_sec": 42.0,
            },
            "cluster_layout": {
                "by_host": {"node-a": {"master": 1, "slave": 0, "total": 1}},
                "by_role": {"master": 1, "slave": 0},
                "total_partitions": 1,
            },
            "process_health": {
                "active_queries": [{"Info": "select 1"}],
                "sleeping_open_transactions": [],
                "active_count": 1,
                "sleeping_open_tx_count": 0,
            },
        }

        with patch.object(server, "parse_report_directory", return_value=parsed):
            await server._parse_report_background(report_id, self.archive_dir.name, 0)

        payload = await self.store.read_report_payload(report_id)
        self.assertEqual(payload.get("log_timeframe"), parsed["log_timeframe"])
        self.assertEqual(payload.get("backup_summary"), parsed["backup_summary"])
        self.assertEqual(payload.get("cluster_layout"), parsed["cluster_layout"])
        self.assertEqual(payload.get("process_health"), parsed["process_health"])


if __name__ == "__main__":
    unittest.main()
