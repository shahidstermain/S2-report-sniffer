import asyncio
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from server import app, store


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


class TestLogSearchEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _seed_report_logs(self, logs):
        report_id = str(uuid.uuid4())
        payload = {
            "id": report_id,
            "status": "ready",
            "nodes": [{"hostname": "node-a"}],
        }
        asyncio.run(store.write_report_payload(report_id, payload))
        asyncio.run(store.write_report_logs(report_id, logs))
        return report_id

    def test_log_search_severity_filter_matches_indexed_uppercase_severity(self):
        report_id = self._seed_report_logs([
            {
                "timestamp": "2026-06-13T10:00:00Z",
                "hostname": "node-a",
                "severity": "ERROR",
                "message": "ETIMEDOUT while contacting leaf",
            }
        ])

        response = self.client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": "ETIMEDOUT", "severity": "ERROR"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["message"], "ETIMEDOUT while contacting leaf")

    def test_log_search_regex_matches_without_literal_prefilter(self):
        report_id = self._seed_report_logs([
            {
                "timestamp": "2026-06-13T10:00:00Z",
                "hostname": "node-a",
                "severity": "ERROR",
                "message": "error while waiting for connection timeout",
            }
        ])

        response = self.client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": "error.*timeout", "regex": "true"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["message"], "error while waiting for connection timeout")

    def test_log_search_node_filter_treats_hyphenated_hostname_as_literal_prefix(self):
        report_id = self._seed_report_logs([
            {
                "timestamp": "2026-06-13T10:00:00Z",
                "hostname": "node-a",
                "severity": "INFO",
                "message": "target message",
            }
        ])

        response = self.client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": "target", "node": "node-a"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["hostname"], "node-a")

    def test_log_search_regex_scans_beyond_first_storage_page(self):
        logs = [
            {
                "timestamp": "2026-06-13T10:00:00Z",
                "hostname": "node-a",
                "severity": "INFO",
                "message": f"nonmatching line {idx}",
            }
            for idx in range(500)
        ]
        logs.append({
            "timestamp": "2026-06-13T10:01:00Z",
            "hostname": "node-a",
            "severity": "ERROR",
            "message": "error after many lines timeout",
        })
        report_id = self._seed_report_logs(logs)

        response = self.client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": "error.*timeout", "regex": "true", "max_results": "2000"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["message"], "error after many lines timeout")

    def test_log_search_warning_alias_matches_stored_warn_severity(self):
        report_id = self._seed_report_logs([
            {
                "timestamp": "2026-06-13T10:00:00Z",
                "hostname": "node-a",
                "severity": "WARN",
                "message": "target warning",
            }
        ])

        response = self.client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": "target", "severity": "warning"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["severity"], "WARN")


class TestParsePersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_parse_completion_persists_overview_aggregate_fields(self):
        report_id = str(uuid.uuid4())
        asyncio.run(store.create_report_stub(report_id, "fixture", 0, "directory"))
        parsed = {
            "parsed_at": "2026-06-13T10:00:00Z",
            "detected_format": "directory",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.7.0", "nodes_detail": []},
            "nodes": [{"hostname": "node-a"}],
            "recommendations": [],
            "logs": [],
            "backup_summary": {"success_count": 1, "failure_count": 0},
            "log_timeframe": {"node-a": {"first_log_entry": "2026-06-13T09:00:00Z"}},
            "cluster_layout": {"node-a": {"partitions": 12}},
            "process_health": {"active_queries": 2},
        }

        with tempfile.TemporaryDirectory() as report_dir:
            with patch.object(server, "parse_report_directory", return_value=parsed):
                asyncio.run(server._parse_report_background(report_id, report_dir, 0))

        response = self.client.get(f"/api/reports/{report_id}/overview")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["backup_summary"], parsed["backup_summary"])
        self.assertEqual(data["log_timeframe"], parsed["log_timeframe"])
        self.assertEqual(data["cluster_layout"], parsed["cluster_layout"])
        self.assertEqual(data["process_health"], parsed["process_health"])


if __name__ == "__main__":
    unittest.main()
