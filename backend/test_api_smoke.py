import unittest
import tempfile
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

    def test_parse_background_persists_overview_diagnostics(self):
        parsed = {
            "parsed_at": "2026-05-02T00:00:00+00:00",
            "detected_format": "directory",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.7.0"},
            "nodes": [{"id": "1", "ip_addr": "10.0.0.1"}],
            "recommendations": [],
            "logs": [],
            "cluster_layout": {"total_partitions": 2, "by_host": {"10.0.0.1": {"total": 2}}},
            "log_timeframe": {"per_node": {"10.0.0.1": {"coverage_hours": 12}}},
            "backup_summary": {"total": 1, "success_count": 1, "failure_count": 0},
            "process_health": {"active_count": 3, "sleeping_open_tx_count": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            original_store = server.store
            test_store = LocalReportStore(Path(tmpdir))
            try:
                server.store = test_store
                report_id = "11111111-1111-1111-1111-111111111111"
                server.asyncio.run(test_store.create_report_stub(report_id, "sample", 0, "directory"))

                with patch("server.parse_report_directory", return_value=parsed):
                    server.asyncio.run(server._parse_report_background(report_id, tmpdir, 0))

                payload = server.asyncio.run(test_store.read_report_payload(report_id))
            finally:
                server.store = original_store

        self.assertEqual(payload["cluster_layout"], parsed["cluster_layout"])
        self.assertEqual(payload["log_timeframe"], parsed["log_timeframe"])
        self.assertEqual(payload["backup_summary"], parsed["backup_summary"])
        self.assertEqual(payload["process_health"], parsed["process_health"])


if __name__ == "__main__":
    unittest.main()
