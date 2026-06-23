import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from storage import LocalReportStore


class TestBackgroundParsePersistence(unittest.TestCase):
    def test_background_parse_persists_overview_diagnostics(self):
        report_id = "11111111-1111-4111-8111-111111111111"
        data_dir = Path(tempfile.mkdtemp(prefix="s2rs_parse_store_"))
        archive_path = data_dir / "report.tar"
        archive_path.write_bytes(b"placeholder")
        store = LocalReportStore(data_dir)
        parsed = {
            "parsed_at": "2026-06-23T11:00:00Z",
            "detected_format": "tar",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.7.0"},
            "nodes": [],
            "databases": [],
            "storage": [],
            "queries": [],
            "events": [],
            "pipelines": [],
            "log_summary": {},
            "logs": [],
            "recommendations": [],
            "workload_management": [],
            "replication_status": [],
            "config_health": {},
            "backup_history": [],
            "resource_pools": [],
            "database_disk_usage": [],
            "partitions": {},
            "cluster_layout": {"hosts": {"leaf-a": {"leaf_partitions": 16}}},
            "log_timeframe": {"leaf-a": {"first_log_entry": "2026-06-23T10:00:00Z"}},
            "backup_summary": {"success_count": 2, "failure_count": 0},
            "pressure_events_per_hour": {},
            "process_health": {"active_queries": 3},
            "version_history": [],
            "availability_groups": [],
            "users": [],
            "detected_log_patterns": [],
            "dmesg_events": [],
        }

        async def run_parse():
            await store.create_report_stub(report_id, "report.tar", 123, "tar")
            with patch.object(server, "store", store), patch.object(server, "parse_report_archive_streaming", return_value=parsed):
                await server._parse_report_background(report_id, str(archive_path), 123)
            return await store.read_report_payload(report_id)

        payload = asyncio.run(run_parse())

        self.assertEqual(payload["cluster_layout"], parsed["cluster_layout"])
        self.assertEqual(payload["log_timeframe"], parsed["log_timeframe"])
        self.assertEqual(payload["backup_summary"], parsed["backup_summary"])
        self.assertEqual(payload["process_health"], parsed["process_health"])


if __name__ == "__main__":
    unittest.main()
