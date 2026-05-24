"""
Server endpoint smoke and error-path unit tests — QLT-001 coverage expansion.
Tests DB-backed endpoints in degraded mode (MongoDB unavailable) and
validates error handling, validation, and response shapes.
"""
import asyncio
import os
import stat
import unittest
import io
import json
import tarfile
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_")

with patch.dict('os.environ', {'MONGO_URL': 'mongodb://localhost:27017', 'S2RS_DATA_DIR': TEST_DATA_DIR}):
    import server
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

    def test_upload_invalid_legacy_report_filename_returns_400(self):
        fake_file = io.BytesIO(b"data")
        response = self.client.post(
            "/api/reports/upload",
            files={"report": ("bad name.zip", fake_file, "application/zip")},
        )
        self.assertEqual(response.status_code, 400)

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


class TestUploadDirectorySelection(unittest.TestCase):
    def test_writable_upload_dir_repairs_user_owned_insecure_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate = Path(tmpdir) / "sdb_uploads"
            candidate.mkdir()
            if os.name == "posix":
                candidate.chmod(0o777)

            with patch.dict("os.environ", {"S2RS_UPLOAD_DIR": ""}):
                with patch.object(server.tempfile, "gettempdir", return_value=tmpdir):
                    selected = server._writable_upload_dir()

            self.assertEqual(selected, candidate)
            if os.name == "posix":
                self.assertFalse(candidate.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))


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

    def test_diff_route_with_valid_missing_ids_reaches_diff_handler(self):
        r = self.client.get(
            "/api/reports/diff",
            params={
                "from_id": "11111111-1111-1111-1111-111111111111",
                "to_id": "22222222-2222-2222-2222-222222222222",
            },
        )
        self.assertEqual(r.status_code, 404)

    def test_diff_route_returns_diff_for_existing_reports(self):
        from_id = str(uuid.uuid4())
        to_id = str(uuid.uuid4())

        async def write_payloads():
            await server.store.write_report_payload(from_id, {
                "recommendations": [
                    {"checker_id": "disk", "title": "Disk usage", "severity": "warning", "risk_score": 50}
                ]
            })
            await server.store.write_report_payload(to_id, {
                "recommendations": [
                    {"checker_id": "disk", "title": "Disk usage", "severity": "critical", "risk_score": 90},
                    {"checker_id": "memory", "title": "Memory pressure", "severity": "warning", "risk_score": 60},
                ]
            })

        asyncio.run(write_payloads())
        r = self.client.get("/api/reports/diff", params={"from_id": from_id, "to_id": to_id})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["worsened"], [{"title": "Disk usage", "checker_id": "disk"}])
        self.assertEqual(data["new"], [{"title": "Memory pressure", "checker_id": "memory"}])

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


class TestParsePersistenceFields(unittest.TestCase):
    def test_background_parse_persists_overview_aggregate_fields(self):
        report_id = str(uuid.uuid4())
        parsed_report = {
            "parsed_at": "2026-05-24T11:00:00+00:00",
            "detected_format": "directory",
            "raw_node_count": 1,
            "cluster_overview": {"version": "8.1.0", "cluster_status": []},
            "nodes": [],
            "databases": [],
            "storage": [],
            "queries": [],
            "events": [],
            "pipelines": [],
            "logs": [],
            "log_summary": {},
            "recommendations": [],
            "workload_management": [],
            "replication_status": [],
            "config_health": {},
            "backup_history": [],
            "resource_pools": [],
            "database_disk_usage": [],
            "partitions": {},
            "pressure_events_per_hour": {},
            "version_history": [],
            "availability_groups": [],
            "users": [],
            "detected_log_patterns": [],
            "dmesg_events": [],
            "cluster_layout": {"total_partitions": 2},
            "log_timeframe": {"cluster_first": "2026-05-24 10:00:00.000"},
            "backup_summary": {"total": 1, "success_count": 1},
            "process_health": {"active_count": 3},
            "alloc_memory": {"per_node": [{"hostname": "node-1"}]},
            "memory_pressure": {"node-1": {"vm_swappiness": "60"}},
        }

        async def run_parse():
            await server.store.create_report_stub(report_id, "fixture", 0, "directory")
            with tempfile.TemporaryDirectory() as tmpdir:
                with patch.object(server, "parse_report_directory", return_value=dict(parsed_report)):
                    await server._parse_report_background(report_id, tmpdir, 0)
            return await server.store.read_report_payload(report_id)

        payload = asyncio.run(run_parse())
        self.assertEqual(payload["cluster_layout"], parsed_report["cluster_layout"])
        self.assertEqual(payload["log_timeframe"], parsed_report["log_timeframe"])
        self.assertEqual(payload["backup_summary"], parsed_report["backup_summary"])
        self.assertEqual(payload["process_health"], parsed_report["process_health"])
        self.assertEqual(payload["alloc_memory"], parsed_report["alloc_memory"])
        self.assertEqual(payload["memory_pressure"], parsed_report["memory_pressure"])
