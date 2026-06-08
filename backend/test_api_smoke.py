import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient

from server import app, store
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

    def test_log_search_filters_severity_case_insensitively(self):
        if not isinstance(store, LocalReportStore):
            self.skipTest("local log search is only supported by LocalReportStore")

        report_id = str(uuid.uuid4())
        asyncio.run(store.write_report_payload(report_id, {
            "report_id": report_id,
            "nodes": [{"hostname": "node-a"}],
            "log_summary": {},
        }))
        asyncio.run(store.write_report_logs(report_id, [
            {
                "timestamp": "2026-06-08 10:00:00.000000",
                "severity": "ERROR",
                "message": "replication failed on partition 7",
                "hostname": "node-a",
                "role": "leaf",
                "source": "memsql.log",
            },
            {
                "timestamp": "2026-06-08 10:01:00.000000",
                "severity": "INFO",
                "message": "replication recovered",
                "hostname": "node-a",
                "role": "leaf",
                "source": "memsql.log",
            },
        ]))

        try:
            response = self.client.get(
                f"/api/reports/{report_id}/logs/search",
                params={"keyword": "replication", "severity": "ERROR"},
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["matches"][0]["severity"], "ERROR")
            self.assertEqual(data["matches"][0]["message"], "replication failed on partition 7")
        finally:
            asyncio.run(store.delete_report(report_id))


if __name__ == "__main__":
    unittest.main()
