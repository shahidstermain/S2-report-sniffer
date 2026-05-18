"""
Server endpoint smoke and error-path unit tests — QLT-001 coverage expansion.
Tests DB-backed endpoints in degraded mode (MongoDB unavailable) and
validates error handling, validation, and response shapes.
"""
import unittest
import asyncio
import io
import json
import tarfile
import tempfile
import uuid
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_")

with patch.dict('os.environ', {'MONGO_URL': 'mongodb://localhost:27017', 'S2RS_DATA_DIR': TEST_DATA_DIR}):
    import server as server_module
    from server import app


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


class TestBackgroundParsingPayload(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_background_parse_persists_high_value_overview_fields(self):
        report_id = str(uuid.uuid4())
        parsed = {
            "parsed_at": "2026-05-18T11:00:00+00:00",
            "detected_format": "zip",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.5.0", "nodes_detail": []},
            "nodes": [],
            "databases": [],
            "storage": [],
            "queries": [],
            "events": [],
            "pipelines": [],
            "log_summary": {},
            "recommendations": [],
            "logs": [],
            "cluster_layout": {
                "total_partitions": 2,
                "by_host": {"leaf-1": {"master": 1, "slave": 1, "total": 2}},
            },
            "log_timeframe": {
                "cluster_first": "2026-05-18 09:00:00.000",
                "cluster_last": "2026-05-18 11:00:00.000",
                "per_node": {
                    "leaf-1": {
                        "first_log_entry": "2026-05-18 09:00:00.000",
                        "last_log_entry": "2026-05-18 11:00:00.000",
                        "coverage_hours": 2.0,
                    }
                },
            },
            "backup_summary": {"total": 1, "success_count": 0, "failure_count": 1},
            "process_health": {"active_count": 2, "sleeping_open_tx_count": 1},
        }

        async def parse_report():
            await server_module.store.create_report_stub(report_id, "bundle.zip", 123, "zip")
            await server_module._parse_report_background(report_id, "/tmp/bundle.zip", 123)

        with patch.object(server_module, "parse_report_archive_streaming", return_value=parsed):
            asyncio.run(parse_report())

        response = self.client.get(f"/api/reports/{report_id}/overview")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["cluster_layout"]["total_partitions"], 2)
        self.assertEqual(data["log_timeframe"]["per_node"]["leaf-1"]["coverage_hours"], 2.0)
        self.assertEqual(data["backup_summary"]["failure_count"], 1)
        self.assertEqual(data["process_health"]["sleeping_open_tx_count"], 1)


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


if __name__ == "__main__":
    unittest.main()


class TestLocalImportEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_import_rejects_empty_path(self):
        r = self.client.post("/api/reports/import", json={"path": ""})
        self.assertIn(r.status_code, (400, 422))

    def test_import_rejects_unsupported_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz") as f:
            r = self.client.post("/api/reports/import", json={"path": f.name})
            self.assertIn(r.status_code, (400, 404))

    def test_import_missing_path_returns_404(self):
        missing_path = tempfile.gettempdir() + "/definitely-missing-file.zip"
        r = self.client.post("/api/reports/import", json={"path": missing_path})
        self.assertEqual(r.status_code, 404)

    def test_import_accepts_directory(self):
        d = tempfile.mkdtemp(prefix="s2rs_import_")
        r = self.client.post("/api/reports/import", json={"path": d})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("id", data)
        self.assertEqual(data.get("status"), "processing")
