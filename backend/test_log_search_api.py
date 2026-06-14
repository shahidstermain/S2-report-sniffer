import asyncio
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_log_search_")

with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR}):
    import server


class TestRawLogSearchApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, raise_server_exceptions=False)
        self.report_id = str(uuid.uuid4())
        asyncio.run(server.store.write_report_payload(
            self.report_id,
            {"nodes": [{"hostname": "node-a"}], "log_summary": {}},
        ))
        asyncio.run(server.store.write_report_logs(self.report_id, [
            {
                "timestamp": "2024-01-15 10:00:00.000",
                "severity": "ERROR",
                "hostname": "node-a",
                "message": "Connection timeout after 30s",
            }
        ]))

    def tearDown(self):
        asyncio.run(server.store.delete_report(self.report_id))

    def test_regex_search_does_not_require_literal_substring_match(self):
        response = self.client.get(
            f"/api/reports/{self.report_id}/logs/search",
            params={"keyword": r"connect\w+", "regex": "true"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["matches"][0]["message"], "Connection timeout after 30s")


if __name__ == "__main__":
    unittest.main()
