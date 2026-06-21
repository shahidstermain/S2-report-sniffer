import asyncio
import uuid
import unittest

from fastapi.testclient import TestClient

from server import app, store


class TestLogSearchEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.report_id = str(uuid.uuid4())
        asyncio.run(store.create_report_stub(self.report_id, "log-search.tar.gz", 1024, "tar.gz"))
        asyncio.run(store.write_report_payload(self.report_id, {
            "status": "ready",
            "nodes": [
                {"hostname": "leaf-1", "role": "Leaf"},
            ],
        }))
        asyncio.run(store.write_report_logs(self.report_id, [
            {
                "timestamp": "2024-01-15 10:00:03.000",
                "severity": "ERROR",
                "hostname": "leaf-1",
                "role": "Leaf",
                "message": "Connection timeout after 30s",
            },
            {
                "timestamp": "2024-01-15 10:00:04.000",
                "severity": "WARN",
                "hostname": "leaf-1",
                "role": "Leaf",
                "message": "Memory usage above 80%",
            },
        ]))

    def tearDown(self):
        asyncio.run(store.delete_report(self.report_id))

    def test_regex_search_matches_indexed_log_messages(self):
        response = self.client.get(
            f"/api/reports/{self.report_id}/logs/search",
            params={"keyword": r"Connection.*30s", "regex": "true"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["message"], "Connection timeout after 30s")

    def test_uppercase_severity_filter_matches_stored_log_severity(self):
        response = self.client.get(
            f"/api/reports/{self.report_id}/logs/search",
            params={"keyword": "Connection", "severity": "ERROR"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["severity"], "ERROR")


if __name__ == "__main__":
    unittest.main()
