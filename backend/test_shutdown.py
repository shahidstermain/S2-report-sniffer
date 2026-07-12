"""Graceful shutdown hooks — storage WAL checkpoint and localhost-only API."""
import asyncio
import importlib
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

from storage import LocalReportStore

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_shutdown_test_")

with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR, "S2RS_DISABLE_GZIP": "1"}):
    import server

    server = importlib.reload(server)


class TestLocalReportStoreShutdown(unittest.TestCase):
    def test_shutdown_checkpoints_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalReportStore(base_dir=tmp)
            with store._store_db(init_wal=True) as conn:
                conn.execute(
                    "INSERT INTO reports (id, report_name, uploaded_at, status, file_size, detected_format) "
                    "VALUES ('r1', 'demo', '2026-01-01T00:00:00Z', 'ready', 1, 'zip')"
                )
                conn.commit()

            asyncio.run(store.shutdown())

            with sqlite3.connect(store.db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM reports").fetchone()
                self.assertEqual(row[0], 1)


class TestShutdownEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
            server.app,
            raise_server_exceptions=False,
        )

    def test_shutdown_allowed_for_testclient(self):
        response = self.client.post("/api/shutdown")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "shutting_down")

    def test_lifespan_shutdown_invokes_store_shutdown(self):
        with patch.object(server.store, "shutdown", new=AsyncMock()) as shutdown_mock:
            with self.client.__class__(server.app) as client:
                client.get("/api/health")
        shutdown_mock.assert_awaited_once()

    def test_shutdown_denied_when_client_not_loopback(self):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/shutdown",
            "headers": [],
            "client": ("203.0.113.10", 12345),
        }
        request = Request(scope)

        async def _invoke():
            with self.assertRaises(HTTPException) as ctx:
                await server.shutdown_server(request)
            self.assertEqual(ctx.exception.status_code, 403)

        asyncio.run(_invoke())


if __name__ == "__main__":
    unittest.main()
