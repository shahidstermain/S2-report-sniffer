import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import server
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

    def test_integrated_ui_serves_vite_static_assets_under_ui(self):
        original_ui_path = server.ui_path
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            static_dir = build_dir / "static"
            static_dir.mkdir()
            (build_dir / "index.html").write_text(
                '<script type="module" src="/ui/static/app.js"></script>',
                encoding="utf-8",
            )
            (static_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

            server.ui_path = build_dir
            try:
                response = self.client.get("/ui/static/app.js")
            finally:
                server.ui_path = original_ui_path

        self.assertEqual(response.status_code, 200)
        self.assertIn("console.log('ok');", response.text)


if __name__ == "__main__":
    unittest.main()
