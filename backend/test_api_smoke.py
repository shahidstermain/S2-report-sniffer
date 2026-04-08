import unittest

from fastapi.testclient import TestClient

from server import app


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


if __name__ == "__main__":
    unittest.main()
