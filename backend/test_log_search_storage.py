import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from storage import LocalReportStore

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_log_search_")

with patch.dict("os.environ", {"MONGO_URL": "mongodb://localhost:27017", "S2RS_DATA_DIR": TEST_DATA_DIR}):
    import server


class TestLogSearchStorage(unittest.TestCase):
    def test_query_report_logs_normalizes_severity_filters(self):
        async def run():
            store = LocalReportStore(Path(TEST_DATA_DIR) / "direct_storage")
            report_id = str(uuid.uuid4())
            await store.create_report_stub(report_id, "severity.zip", 100, "zip")
            await store.write_report_logs(report_id, [
                {"hostname": "node-a", "severity": "WARN", "message": "disk warning"},
                {"hostname": "node-a", "severity": "INFO", "message": "startup complete"},
            ])

            logs, total = await store.query_report_logs(
                report_id=report_id,
                search="warning",
                severities=["WARN"],
                node_prefix=None,
                page=1,
                page_size=50,
            )
            return logs, total

        logs, total = asyncio.run(run())

        self.assertEqual(total, 1)
        self.assertEqual(logs[0]["severity"], "WARN")

    def test_raw_log_regex_search_does_not_require_literal_substring_match(self):
        report_id = str(uuid.uuid4())

        async def seed():
            await server.store.create_report_stub(report_id, "regex.zip", 100, "zip")
            await server.store.write_report_payload(report_id, {
                "id": report_id,
                "nodes": [{"hostname": "node-a"}],
            })
            await server.store.write_report_logs(report_id, [
                {
                    "timestamp": "2024-01-15 10:00:00.000",
                    "hostname": "node-a",
                    "severity": "ERROR",
                    "message": "Failed to connect to leaf node",
                },
            ])

        asyncio.run(seed())

        client = TestClient(server.app, raise_server_exceptions=False)
        response = client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": r"connect\w*", "regex": "true", "severity": "ERROR"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["message"], "Failed to connect to leaf node")

    def test_raw_log_search_accepts_common_key_value_terms(self):
        report_id = str(uuid.uuid4())

        async def seed():
            await server.store.create_report_stub(report_id, "kv-search.zip", 100, "zip")
            await server.store.write_report_payload(report_id, {
                "id": report_id,
                "nodes": [{"hostname": "node-a"}],
            })
            await server.store.write_report_logs(report_id, [
                {
                    "timestamp": "2024-01-15 10:01:00.000",
                    "hostname": "node-a",
                    "severity": "INFO",
                    "message": "connection_id=123 failed during retry",
                },
            ])

        asyncio.run(seed())

        client = TestClient(server.app, raise_server_exceptions=False)
        response = client.get(
            f"/api/reports/{report_id}/logs/search",
            params={"keyword": "connection_id=123"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["matches"][0]["message"], "connection_id=123 failed during retry")


if __name__ == "__main__":
    unittest.main()
