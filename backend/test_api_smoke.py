import asyncio
from pathlib import Path
import tempfile
import unittest
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

    def test_integrated_ui_serves_vite_assets_under_ui_static(self):
        original_ui_path = server.ui_path
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            asset_dir = build_dir / "static" / "assets"
            asset_dir.mkdir(parents=True)
            (asset_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

            server.ui_path = build_dir
            try:
                response = self.client.get("/ui/static/assets/app.js")
            finally:
                server.ui_path = original_ui_path

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "console.log('ok');")

    def test_background_parser_persists_overview_diagnostics(self):
        parsed = {
            "parsed_at": "2026-05-14T11:00:00+00:00",
            "detected_format": "zip",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.1.0", "total_nodes": 1},
            "nodes": [],
            "recommendations": [],
            "cluster_layout": {"total_partitions": 4, "by_host": {"leaf-1": {"total": 4}}},
            "log_timeframe": {"per_node": {"leaf-1": {"coverage_hours": 2}}},
            "backup_summary": {"total": 2, "success_count": 1, "failure_count": 1},
            "process_health": {"active_count": 3, "sleeping_open_tx_count": 1},
        }

        original_store = server.store
        with tempfile.TemporaryDirectory() as tmp:
            local_store = LocalReportStore(Path(tmp))
            report_id = "00000000-0000-4000-8000-000000000001"
            asyncio.run(local_store.create_report_stub(report_id, "fixture.zip", 123, "zip"))
            server.store = local_store
            try:
                with patch.object(server, "parse_report_archive_streaming", return_value=parsed):
                    asyncio.run(server._parse_report_background(report_id, "fixture.zip", 123))
                payload = asyncio.run(local_store.read_report_payload(report_id))
            finally:
                server.store = original_store

        self.assertEqual(payload.get("cluster_layout"), parsed["cluster_layout"])
        self.assertEqual(payload.get("log_timeframe"), parsed["log_timeframe"])
        self.assertEqual(payload.get("backup_summary"), parsed["backup_summary"])
        self.assertEqual(payload.get("process_health"), parsed["process_health"])


if __name__ == "__main__":
    unittest.main()
