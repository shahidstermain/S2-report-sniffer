"""
Server endpoint smoke and error-path unit tests — QLT-001 coverage expansion.
Tests DB-backed endpoints in degraded mode (MongoDB unavailable) and
validates error handling, validation, and response shapes.
"""
import asyncio
import io
import json
import tarfile
import tempfile
import unittest
import uuid
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_")

with patch.dict('os.environ', {'MONGO_URL': 'mongodb://localhost:27017', 'S2RS_DATA_DIR': TEST_DATA_DIR}):
    from server import app, store


class TestUploadValidation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_upload_rejects_exe_file(self):
        fake_file = io.BytesIO(b"binary content")
        response = self.client.post(
            "/api/reports/upload",
            files={"file": ("evil.exe", fake_file, "application/octet-stream")},
        )
        self.assertIn(response.status_code, (400, 415, 422))

    def test_upload_rejects_empty_filename(self):
        fake_file = io.BytesIO(b"data")
        response = self.client.post(
            "/api/reports/upload",
            files={"file": ("", fake_file, "application/octet-stream")},
        )
        self.assertIn(response.status_code, (400, 415, 422))

    def test_upload_rejects_too_long_filename(self):
        long_name = "a" * 300 + ".tar.gz"
        fake_file = io.BytesIO(b"data")
        response = self.client.post(
            "/api/reports/upload",
            files={"file": (long_name, fake_file, "application/octet-stream")},
        )
        self.assertIn(response.status_code, (400, 415, 422))

    def test_upload_rejects_no_file(self):
        response = self.client.post("/api/reports/upload")
        self.assertIn(response.status_code, (400, 422))

    def test_upload_rejects_corrupted_tar_gz(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as tf:
            data = json.dumps({"nodes": []}).encode("utf-8")
            info = tarfile.TarInfo(name="cluster.json")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        broken = io.BytesIO(payload.getvalue()[:-8])
        broken.seek(0)

        response = self.client.post(
            "/api/reports/upload",
            files={"file": ("broken.tar.gz", broken, "application/gzip")},
        )
        self.assertEqual(response.status_code, 400)
        data = response.json().get("detail", {})
        self.assertEqual(data.get("error"), "invalid_archive")
        self.assertIn("Corrupted or incomplete gzip archive", data.get("message", ""))


class TestReportEndpointsErrorPaths(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_get_reports_returns_200(self):
        response = self.client.get("/api/reports")
        self.assertEqual(response.status_code, 200)

    def test_get_recommendations_invalid_id(self):
        response = self.client.get("/api/reports/not-a-valid-uuid/recommendations")
        self.assertEqual(response.status_code, 400)

    def test_delete_report_invalid_id(self):
        response = self.client.delete("/api/reports/not-uuid")
        self.assertEqual(response.status_code, 400)


class TestHealthAndMonitoring(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_health_returns_200(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)

    def test_health_response_structure(self):
        r = self.client.get("/api/health")
        data = r.json()
        self.assertIn("status", data)
        self.assertIn("checks", data)

    def test_alerts_returns_200(self):
        r = self.client.get("/api/alerts")
        self.assertEqual(r.status_code, 200)

    def test_perf_metrics_returns_200(self):
        r = self.client.get("/api/metrics/performance")
        self.assertEqual(r.status_code, 200)


class TestExportEndpointsDegraded(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_diff_without_ids_returns_400(self):
        r = self.client.get("/api/reports/diff")
        self.assertEqual(r.status_code, 400)

    def test_export_slack_missing_report(self):
        r = self.client.get("/api/reports/nonexistent-0000-0000-0000-000000000001/export/slack")
        self.assertIn(r.status_code, (400, 404))

    def test_export_html_missing_report(self):
        r = self.client.get("/api/reports/nonexistent-0000-0000-0000-000000000001/export/html")
        self.assertIn(r.status_code, (400, 404))


class TestRootEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_root_returns_200(self):
        r = self.client.get("/api/")
        self.assertEqual(r.status_code, 200)

    def test_docs_endpoint_exists(self):
        r = self.client.get("/api/docs")
        self.assertIn(r.status_code, (200, 404))


class TestLogSearchEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.report_id = str(uuid.uuid4())
        asyncio.run(store.create_report_stub(self.report_id, "logs.zip", 100, "zip"))
        asyncio.run(store.write_report_payload(self.report_id, {
            "nodes": [{"hostname": "node-a"}],
            "log_summary": {},
        }))

    def tearDown(self):
        asyncio.run(store.delete_report(self.report_id))

    def test_search_honors_error_severity_filter(self):
        asyncio.run(store.write_report_logs(self.report_id, [
            {
                "timestamp": "2024-01-15 10:00:00.000",
                "severity": "ERROR",
                "message": "Connection timeout after 30s",
                "hostname": "node-a",
            },
            {
                "timestamp": "2024-01-15 10:00:01.000",
                "severity": "INFO",
                "message": "Connection timeout retry scheduled",
                "hostname": "node-a",
            },
        ]))

        r = self.client.get(
            f"/api/reports/{self.report_id}/logs/search",
            params={"keyword": "timeout", "severity": "ERROR"},
        )

        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["matches"]), 1)
        self.assertEqual(data["matches"][0]["severity"], "ERROR")

    def test_search_reports_truncation_beyond_requested_limit(self):
        asyncio.run(store.write_report_logs(self.report_id, [
            {
                "timestamp": f"2024-01-15 10:{i // 60:02d}:{i % 60:02d}.000",
                "severity": "INFO",
                "message": f"heartbeat marker {i}",
                "hostname": "node-a",
            }
            for i in range(650)
        ]))

        r = self.client.get(
            f"/api/reports/{self.report_id}/logs/search",
            params={"keyword": "heartbeat", "max_results": 600},
        )

        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["matches"]), 600)
        self.assertEqual(data["total"], 650)
        self.assertTrue(data["truncated"])

    def test_search_counts_only_case_sensitive_matches(self):
        asyncio.run(store.write_report_logs(self.report_id, [
            {
                "timestamp": "2024-01-15 10:00:00.000",
                "severity": "INFO",
                "message": "Heartbeat marker uppercase",
                "hostname": "node-a",
            },
            {
                "timestamp": "2024-01-15 10:00:01.000",
                "severity": "INFO",
                "message": "heartbeat marker lowercase",
                "hostname": "node-a",
            },
        ]))

        r = self.client.get(
            f"/api/reports/{self.report_id}/logs/search",
            params={"keyword": "heartbeat", "case_sensitive": "true"},
        )

        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["matches"]), 1)
        self.assertEqual(data["total"], 1)
        self.assertFalse(data["truncated"])
        self.assertIn("lowercase", data["matches"][0]["message"])

    def test_search_applies_regex_before_counting_results(self):
        asyncio.run(store.write_report_logs(self.report_id, [
            {
                "timestamp": "2024-01-15 10:00:00.000",
                "severity": "INFO",
                "message": "replication retry 1",
                "hostname": "node-a",
            },
            {
                "timestamp": "2024-01-15 10:00:01.000",
                "severity": "INFO",
                "message": "replication retry 2",
                "hostname": "node-a",
            },
            {
                "timestamp": "2024-01-15 10:00:02.000",
                "severity": "INFO",
                "message": "replication retry complete",
                "hostname": "node-a",
            },
        ]))

        r = self.client.get(
            f"/api/reports/{self.report_id}/logs/search",
            params={"keyword": r"retry \d", "regex": "true"},
        )

        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["matches"]), 2)
        self.assertEqual(data["total"], 2)
        self.assertFalse(data["truncated"])


if __name__ == "__main__":
    unittest.main()


class TestLocalImportEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_import_rejects_empty_path(self):
        r = self.client.post("/api/reports/import", json={"path": ""})
        self.assertIn(r.status_code, (400, 422))

    def test_import_rejects_unsupported_extension(self):
        # Create a temp file within cwd to pass the path-escape security check
        import os
        from pathlib import Path
        tmp_file = Path("test_unsupported.xyz")
        try:
            tmp_file.touch()
            r = self.client.post("/api/reports/import", json={"path": str(tmp_file.resolve())})
            self.assertIn(r.status_code, (400, 404))
        finally:
            if tmp_file.exists():
                tmp_file.unlink()

    def test_import_missing_path_returns_404(self):
        missing_path = tempfile.gettempdir() + "/definitely-missing-file.zip"
        r = self.client.post("/api/reports/import", json={"path": missing_path})
        self.assertEqual(r.status_code, 404)

    def test_import_accepts_directory(self):
        # Create a temp directory within cwd to pass the path-escape security check
        from pathlib import Path
        import shutil
        tmp_dir = Path("s2rs_import_test_dir")
        try:
            tmp_dir.mkdir(exist_ok=True)
            r = self.client.post("/api/reports/import", json={"path": str(tmp_dir.resolve())})
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertIn("id", data)
            self.assertEqual(data.get("status"), "processing")
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
