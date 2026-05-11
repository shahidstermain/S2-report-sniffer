import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from server import app
from storage import LocalReportStore


class TestApiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_and_monitoring_endpoints(self):
        health = self.client.get("/api/health")
        alerts = self.client.get("/api/alerts")
        perf = self.client.get("/api/metrics/performance")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(alerts.status_code, 200)
        self.assertEqual(perf.status_code, 200)

    def test_report_endpoints(self):
        reports = self.client.get("/api/reports")
        recs = self.client.get("/api/reports/nonexistent/recommendations")

        self.assertEqual(reports.status_code, 200)
        self.assertIn(recs.status_code, (404, 400))

    def test_export_and_diff_endpoints(self):
        diff = self.client.get("/api/reports/diff", params={"from_id": "a", "to_id": "b"})
        slack = self.client.get("/api/reports/nonexistent/export/slack")
        html = self.client.get("/api/reports/nonexistent/export/html")

        self.assertIn(diff.status_code, (404, 400))
        self.assertIn(slack.status_code, (404, 400))
        self.assertIn(html.status_code, (404, 400))

    def test_background_parse_persists_overview_diagnostic_aggregates(self):
        report_id = str(uuid.uuid4())
        parsed_report = {
            "parsed_at": "2026-05-11T11:00:00Z",
            "detected_format": "directory",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.5.0", "nodes_detail": []},
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
            "version_history": [],
            "availability_groups": [],
            "users": [],
            "detected_log_patterns": [],
            "dmesg_events": [],
            "cluster_layout": {"by_host": {"leaf-1": {"master": 1, "slave": 1, "total": 2}}},
            "log_timeframe": {
                "per_node": {
                    "leaf-1": {
                        "first_log_entry": "2026-05-11 10:00:00.000",
                        "last_log_entry": "2026-05-11 11:00:00.000",
                        "coverage_hours": 1.0,
                    }
                },
                "cluster_first": "2026-05-11 10:00:00.000",
                "cluster_last": "2026-05-11 11:00:00.000",
            },
            "backup_summary": {"total": 1, "success_count": 1, "failure_count": 0},
            "process_health": {"active_count": 1, "sleeping_open_tx_count": 0, "active_queries": []},
        }

        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as report_dir:
            test_store = LocalReportStore(Path(data_dir))
            asyncio.run(test_store.create_report_stub(report_id, "fixture-report", 123, "directory"))

            with patch.object(server, "store", test_store), patch.object(server, "parse_report_directory", return_value=dict(parsed_report)):
                asyncio.run(server._parse_report_background(report_id, report_dir, 123))

            with patch.object(server, "store", test_store):
                response = self.client.get(f"/api/reports/{report_id}/overview")

        self.assertEqual(response.status_code, 200)
        overview = response.json()
        self.assertEqual(overview["cluster_layout"], parsed_report["cluster_layout"])
        self.assertEqual(overview["log_timeframe"], parsed_report["log_timeframe"])
        self.assertEqual(overview["backup_summary"], parsed_report["backup_summary"])
        self.assertEqual(overview["process_health"], parsed_report["process_health"])


if __name__ == "__main__":
    unittest.main()
