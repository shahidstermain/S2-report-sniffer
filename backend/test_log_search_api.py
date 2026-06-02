import asyncio
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient


TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_log_search_")

with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR}):
    from server import app, store


class TestReportLogSearchApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_regex_search_scans_logs_without_literal_prefilter(self):
        report_id = str(uuid.uuid4())
        asyncio.run(store.create_report_stub(report_id, "regex-report.zip", 1024, "zip"))
        asyncio.run(store.write_report_payload(report_id, {"nodes": [{"hostname": "node-a"}]}))
        asyncio.run(store.write_report_logs(report_id, [
            {
                "timestamp": "2024-01-15 10:00:00.000",
                "severity": "ERROR",
                "hostname": "node-a",
                "message": "error connecting to leaf timeout after 30s",
            }
        ]))

        response = self.client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": r"error.*timeout", "regex": "true"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(len(body["matches"]), 1)
        self.assertIn("timeout", body["matches"][0]["message"])


if __name__ == "__main__":
    unittest.main()
