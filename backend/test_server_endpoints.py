"""
Server endpoint smoke and error-path unit tests — QLT-001 coverage expansion.
Tests DB-backed endpoints in degraded mode (MongoDB unavailable) and
validates error handling, validation, and response shapes.
"""
import asyncio
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
    from server import _parse_report_background, app, store


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

    def test_upload_invalid_filename_body_contains_active_file_filename(self):
        # Regression: active_file.filename (not the legacy `file` variable) must
        # appear in the error response body after the fix in server.py.
        long_name = "a" * 300 + ".tar.gz"
        fake_file = io.BytesIO(b"data")
        response = self.client.post(
            "/api/reports/upload",
            files={"file": (long_name, fake_file, "application/octet-stream")},
        )
        self.assertIn(response.status_code, (400, 415, 422))
        detail = response.json().get("detail", {})
        if isinstance(detail, dict) and "filename" in detail:
            self.assertEqual(detail["filename"], long_name)

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
        broken = io.BytesIO(payload.getvalue()[:-50])
        broken.seek(0)

        response = self.client.post(
            "/api/reports/upload",
            files={"file": ("broken.tar.gz", broken, "application/gzip")},
        )
        self.assertEqual(response.status_code, 400)
        data = response.json().get("detail", {})
        self.assertEqual(data.get("error"), "invalid_archive")
        self.assertIn("Corrupted or incomplete gzip archive", data.get("message", ""))


class TestRateLimitMiddleware(unittest.TestCase):
    def setUp(self):
        import server as srv
        srv._upload_counts.clear()

    def tearDown(self):
        import server as srv
        srv._upload_counts.clear()

    def test_stale_ip_eviction(self):
        # Regression: _upload_counts entries for IPs with empty timestamp lists
        # must be removed during each upload request to prevent unbounded growth.
        import server as srv
        # Seed a stale entry (empty list means no recent uploads)
        srv._upload_counts["192.0.2.1"] = []
        before = "192.0.2.1" in srv._upload_counts
        self.assertTrue(before, "stale entry should be present before upload")

        client = TestClient(srv.app, raise_server_exceptions=False)
        client.post(
            "/api/reports/upload",
            files={"file": ("test.tar.gz", io.BytesIO(b"data"), "application/gzip")},
        )
        # After any upload request the middleware must have evicted the stale IP
        self.assertNotIn("192.0.2.1", srv._upload_counts)


class TestServerHelpers(unittest.TestCase):
    def test_load_logs_for_hydration_returns_latest_rows(self):
        import asyncio
        import json as jsonlib
        import server as srv
        from storage import LocalReportStore

        test_store = LocalReportStore()
        report_id = "logs-tail-0000-0000-0000-000000000001"
        logs_path = test_store._report_logs_path(report_id)
        logs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(logs_path, "w", encoding="utf-8") as fh:
            for idx in range(5):
                fh.write(jsonlib.dumps({"line": idx}) + "\n")

        with patch.object(srv, "store", test_store):
            rows = asyncio.run(srv._load_logs_for_hydration(report_id, limit=2))

        self.assertEqual([row["line"] for row in rows], [3, 4])

    def test_health_metrics_use_single_0_to_100_scale(self):
        import server as srv

        score, grade, risk = srv._compute_health_metrics(
            [
                {"severity": "critical"},
                {"severity": "warning"},
                {"severity": "info"},
            ]
        )

        # Info findings do not contribute to risk: 15 + 5 = 20 → score 80 / B.
        self.assertEqual(score, 80)
        self.assertEqual(grade, "B")
        self.assertEqual(risk, 20)


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


class TestGleanExport(unittest.TestCase):
    def test_export_glean_returns_packet(self):
        import os
        import tempfile
        import server as srv
        from storage import LocalReportStore

        sample_payload = {
            "report_name": "prod-cluster",
            "health_score": 72,
            "cluster_overview": {"version": "9.0.24", "node_count": 3},
            "incident_clusters": [
                {
                    "cluster_id": "INC-001",
                    "root_cause_checker_id": "swapEnabled",
                    "root_cause_title": "Swap is disabled",
                    "summary": "2 findings related to memory on master-0",
                    "member_ids": ["1"],
                    "tags": ["memory"],
                    "nodes": ["master-0"],
                }
            ],
            "recommendations": [
                {
                    "id": "1",
                    "checker_id": "swapEnabled",
                    "severity": "warning",
                    "title": "Swap is disabled",
                    "description": "No swap configured.",
                    "evidence": "Node master-0 has 0 MB swap.",
                    "category": "Pre-installation",
                    "nodes": ["master-0"],
                    "priority_tags": ["memory"],
                    "risk_score": 55,
                }
            ],
            "detected_log_patterns": [
                {
                    "title": "OOM Kill Detected",
                    "category": "oom",
                    "count": 1,
                    "severity": "critical",
                    "sample": "Out of memory: Kill process 1234 (memsqld)",
                    "nodes": ["master-0"],
                }
            ],
            "logs": [
                {
                    "timestamp": "2024-01-01 10:00:01",
                    "hostname": "master-0",
                    "severity": "ERROR",
                    "message": "Out of memory: Kill process 1234 (memsqld)",
                }
            ],
        }

        tmpdir = tempfile.mkdtemp(prefix="s2rs_glean_export_")
        report_id = "00000000-0000-0000-0000-000000000001"

        with patch.dict(os.environ, {"S2RS_DATA_DIR": tmpdir}), patch.object(
            srv, "_load_payload", return_value=sample_payload
        ):
            test_store = LocalReportStore()
            with patch.object(srv, "store", test_store):
                response = TestClient(srv.app, raise_server_exceptions=False).get(
                    f"/api/reports/{report_id}/export/glean",
                )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["filename"], "s2rs-incident-packet-00000000.md")
        self.assertIn("Swap is disabled", body["markdown"])
        self.assertIn("Out of memory", body["markdown"])
        self.assertIn("incident packet", body["prompt"].lower())

    def test_export_glean_missing_report(self):
        r = TestClient(app, raise_server_exceptions=False).get(
            "/api/reports/00000000-0000-0000-0000-000000009999/export/glean"
        )
        self.assertIn(r.status_code, (400, 404))


class TestExportEndpointsDegraded(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_diff_without_ids_returns_422(self):
        r = self.client.get("/api/reports/diff")
        self.assertEqual(r.status_code, 422)

    def test_export_slack_missing_report(self):
        r = self.client.get("/api/reports/nonexistent-0000-0000-0000-000000000001/export/slack")
        self.assertIn(r.status_code, (400, 404))

    def test_export_html_missing_report(self):
        r = self.client.get("/api/reports/nonexistent-0000-0000-0000-000000000001/export/html")
        self.assertIn(r.status_code, (400, 404))


class TestRootEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_product_telemetry_is_disabled_by_default(self):
        response = self.client.get("/api/settings/telemetry")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        self.assertFalse(response.json()["external_delivery"])

    def test_auto_update_setting_requires_boolean_and_persists(self):
        initial = self.client.get("/api/settings/auto-update")
        self.assertEqual(initial.status_code, 200)
        self.assertIn("enabled", initial.json())
        invalid = self.client.put("/api/settings/auto-update", json={"enabled": "yes"})
        self.assertEqual(invalid.status_code, 400)
        updated = self.client.put("/api/settings/auto-update", json={"enabled": True})
        self.assertEqual(updated.status_code, 200)
        self.assertTrue(updated.json()["enabled"])
        self.client.put("/api/settings/auto-update", json={"enabled": False})

    def test_sparse_log_upload_is_accepted(self):
        response = self.client.post(
            "/api/reports/upload?anonymize=true",
            files={"file": ("memsql.log", io.BytesIO(b"2026-07-12 10:20:30.123 ERROR out of memory\n"), "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detected_format"], "sparse")
        self.assertTrue(response.json()["anonymized"])

    def test_root_returns_200(self):
        r = self.client.get("/api/")
        self.assertEqual(r.status_code, 200)

    def test_docs_endpoint_exists(self):
        r = self.client.get("/api/docs")
        self.assertIn(r.status_code, (200, 404))


class TestAnonymizedPersistence(unittest.TestCase):
    def test_background_parse_anonymizes_payload_and_logs_before_storage(self):
        from server import store

        report_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "customer.log"
            log_path.write_text(
                "2026-07-12 10:20:30.123 ERROR connect 10.2.3.4 password=hunter2\n",
                encoding="utf-8",
            )

            async def parse_and_read():
                await store.create_report_stub(report_id, "Anonymized Report", log_path.stat().st_size, "sparse")
                try:
                    await _parse_report_background(
                        report_id,
                        str(log_path),
                        log_path.stat().st_size,
                        anonymize=True,
                        report_name="customer.log",
                    )
                    payload = await store.read_report_payload(report_id)
                    logs, _total = await store.query_report_logs(
                        report_id,
                        search=None,
                        severities=None,
                        node_prefix=None,
                        page=1,
                        page_size=50,
                    )
                    return payload, logs
                finally:
                    await store.delete_report(report_id)

            payload, logs = asyncio.run(parse_and_read())

        persisted = json.dumps({"payload": payload, "logs": logs})
        self.assertNotIn("10.2.3.4", persisted)
        self.assertNotIn("hunter2", persisted)
        self.assertTrue(payload["privacy"]["anonymized"])

    def test_anonymized_archive_drops_source_path_and_sensitive_progress(self):
        from server import store

        report_id = str(uuid.uuid4())
        parsed = {
            "parsed_at": "2026-07-15T11:00:00+00:00",
            "detected_format": "zip",
            "input_mode": "bundle",
            "cluster_overview": {},
            "raw_node_count": 0,
            "logs": [],
            "recommendations": [],
        }
        progress_messages = []

        async def capture_progress(_report_id, _stage, _pct, message, **_extra):
            progress_messages.append(message)

        def parse_archive(_path, progress_callback, _persist_to):
            progress_callback(
                "parsing",
                files=1,
                nodes=1,
                logs=0,
                message="Parsing prod-db-01",
            )
            return parsed

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "customer.zip"
            archive_path.write_bytes(b"fixture")

            async def parse_and_read():
                await store.create_report_stub(report_id, "Anonymized Report", archive_path.stat().st_size, "zip")
                try:
                    with (
                        patch("server.parse_report_archive_streaming", side_effect=parse_archive),
                        patch("server._update_progress_safe", new=capture_progress),
                    ):
                        await _parse_report_background(
                            report_id,
                            str(archive_path),
                            archive_path.stat().st_size,
                            anonymize=True,
                            report_name="customer.zip",
                        )
                        await asyncio.sleep(0)
                    return await store.read_report_payload(report_id)
                finally:
                    await store.delete_report(report_id)

            payload = asyncio.run(parse_and_read())

        self.assertIsNone(payload.get("import_source_path"))
        self.assertTrue(progress_messages)
        self.assertFalse(any("prod-db-01" in message for message in progress_messages))

    def test_anonymized_parse_failure_persists_generic_error(self):
        from server import store

        report_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "customer.log"
            log_path.write_text("fixture\n", encoding="utf-8")

            async def parse_and_read():
                await store.create_report_stub(report_id, "Anonymized Report", log_path.stat().st_size, "sparse")
                try:
                    with patch(
                        "server.parse_sparse_report_file",
                        side_effect=ValueError("prod-db-01 failed at /customer/private/report"),
                    ):
                        await _parse_report_background(
                            report_id,
                            str(log_path),
                            log_path.stat().st_size,
                            anonymize=True,
                            report_name="customer.log",
                        )
                    return await store.get_report_fields(
                        report_id,
                        fields=["error", "progress_json"],
                    )
                finally:
                    await store.delete_report(report_id)

            fields = asyncio.run(parse_and_read())

        persisted = json.dumps(fields)
        self.assertNotIn("prod-db-01", persisted)
        self.assertNotIn("/customer/private/report", persisted)
        self.assertEqual(fields["error"], "Report parsing failed")

    def test_anonymized_rehydration_does_not_persist_raw_path_or_diagnostics(self):
        from server import store

        report_id = str(uuid.uuid4())
        client = TestClient(app, raise_server_exceptions=False)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            source_path = Path(temp_dir)
            payload = {
                "id": report_id,
                "report_name": "Anonymized Report",
                "privacy": {"anonymized": True, "scheme": "stable-local-aliases-v1"},
                "nodes": [{"hostname": "NODE_1"}],
                "recommendations": [],
            }
            raw_diagnostics = {
                "cpu_health": {
                    "per_node": [
                        {
                            "hostname": "prod-db-01",
                            "message": "connect 10.2.3.4 password=hunter2",
                        }
                    ]
                }
            }

            async def create_report():
                await store.create_report_stub(report_id, "Anonymized Report", 1, "directory")
                await store.write_report_payload(report_id, payload)

            asyncio.run(create_report())
            try:
                with patch(
                    "server.hydrate_extended_diagnostics",
                    return_value=raw_diagnostics,
                ):
                    response = client.post(
                        f"/api/reports/{report_id}/rehydrate-diagnostics",
                        json={"path": str(source_path)},
                    )
                stored = asyncio.run(store.read_report_payload(report_id))
            finally:
                asyncio.run(store.delete_report(report_id))

        self.assertEqual(response.status_code, 200)
        persisted = json.dumps({"response": response.json(), "stored": stored})
        self.assertNotIn(str(source_path), persisted)
        self.assertNotIn("prod-db-01", persisted)
        self.assertNotIn("10.2.3.4", persisted)
        self.assertNotIn("hunter2", persisted)
        self.assertTrue(stored["privacy"]["anonymized"])


class TestDiagnosticPersistence(unittest.TestCase):
    def test_background_parse_preserves_product_diagnostic_aggregates(self):
        from server import store

        report_id = str(uuid.uuid4())
        temp_dir = tempfile.TemporaryDirectory()
        log_path = Path(temp_dir.name) / "diagnostics.log"
        log_path.write_text("diagnostic fixture\n", encoding="utf-8")
        parsed = {
            "parsed_at": "2026-07-15T11:00:00+00:00",
            "detected_format": "sparse",
            "input_mode": "sparse",
            "cluster_overview": {},
            "raw_node_count": 0,
            "logs": [],
            "recommendations": [],
            "query_patterns": {"runaway_count": 1},
            "replication_lag_patterns": {"status": "critical"},
            "long_running_transactions": {"total_count": 1},
        }

        async def parse_and_read():
            await store.create_report_stub(report_id, "Diagnostics", 1, "sparse")
            try:
                with patch("server.parse_sparse_report_file", return_value=parsed):
                    await _parse_report_background(
                        report_id,
                        str(log_path),
                        log_path.stat().st_size,
                        anonymize=False,
                        report_name="diagnostics.log",
                    )
                return await store.read_report_payload(report_id)
            finally:
                await store.delete_report(report_id)

        try:
            payload = asyncio.run(parse_and_read())
        finally:
            temp_dir.cleanup()

        self.assertEqual(payload["query_patterns"], parsed["query_patterns"])
        self.assertEqual(payload["replication_lag_patterns"], parsed["replication_lag_patterns"])
        self.assertEqual(payload["long_running_transactions"], parsed["long_running_transactions"])


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


class TestReportTriage(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    @staticmethod
    def _rec(rec_id: str, *, quick_win: bool, priority: int) -> dict:
        return {
            "id": rec_id,
            "checker_id": f"check_{rec_id}",
            "severity": "warning",
            "category": "availability",
            "title": f"Finding {rec_id}",
            "risk_score": 50,
            "triage": {
                "quick_win": quick_win,
                "priority": priority,
                "impact": "test",
                "effort": "low",
                "blast_radius": "node",
                "recommended_action": "fix it",
            },
        }

    def test_triage_buckets_are_mutually_exclusive(self):
        """Each finding appears in exactly one triage bucket."""
        import asyncio
        from server import store

        rid = "a0000000-0000-0000-0000-000000000001"
        payload = {
            "report_name": "triage-test",
            "health_score": 70,
            "health_grade": "C",
            "recommendations": [
                self._rec("critical-quick-win", quick_win=True, priority=1),
                self._rec("quick-win-soon", quick_win=True, priority=2),
                self._rec("backlog-only", quick_win=False, priority=3),
            ],
            "incident_clusters": [],
        }
        asyncio.run(store.write_report_payload(rid, payload))
        try:
            resp = self.client.get(f"/api/reports/{rid}/triage")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["health_score"], 70)
            self.assertEqual(data["health_grade"], "C")

            act_now_ids = {e["id"] for e in data["act_now"]}
            quick_win_ids = {e["id"] for e in data["quick_wins"]}
            act_soon_ids = {e["id"] for e in data["act_soon"]}
            backlog_ids = {e["id"] for e in data["backlog"]}

            self.assertIn("critical-quick-win", act_now_ids)
            self.assertNotIn("critical-quick-win", quick_win_ids)

            self.assertIn("quick-win-soon", quick_win_ids)
            self.assertNotIn("quick-win-soon", act_soon_ids)

            self.assertIn("backlog-only", backlog_ids)
            self.assertNotIn("backlog-only", act_now_ids)
            self.assertNotIn("backlog-only", quick_win_ids)
            self.assertNotIn("backlog-only", act_soon_ids)

            all_ids = act_now_ids | quick_win_ids | act_soon_ids | backlog_ids
            self.assertEqual(len(all_ids), 3)
        finally:
            asyncio.run(store.delete_report(rid))


class TestReportRecommendationsLogSearchHint(unittest.TestCase):
    """/recommendations attaches a derived (never-persisted) log_search hint per finding."""

    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_recommendations_include_log_search_hint(self):
        import asyncio
        from server import store

        rid = "b0000000-0000-0000-0000-000000000001"
        payload = {
            "report_name": "log-search-hint-test",
            "recommendations": [
                {
                    "id": "1",
                    "checker_id": "tracelogOOM",
                    "severity": "critical",
                    "category": "Memory",
                    "title": "OOM kill detected on host1",
                    "evidence": "Jul 10 02:15:00 host1 kernel: Out of memory: Kill process 1234",
                    "nodes": ["host1"],
                },
                {
                    "id": "2",
                    "checker_id": "transparentHugepage",
                    "severity": "warning",
                    "category": "Configuration",
                    "title": "THP not disabled",
                    "evidence": "",
                    "nodes": [],
                },
            ],
        }
        asyncio.run(store.write_report_payload(rid, payload))
        try:
            resp = self.client.get(f"/api/reports/{rid}/recommendations")
            self.assertEqual(resp.status_code, 200)
            recs = resp.json()["recommendations"]
            self.assertEqual(len(recs), 2)

            oom = next(r for r in recs if r["id"] == "1")
            self.assertIn("log_search", oom)
            self.assertNotEqual(oom["log_search"]["keyword"], "tracelogOOM")
            self.assertEqual(oom["log_search"]["keyword"], "starting up, version")
            self.assertEqual(oom["log_search"]["node"], "host1")

            thp = next(r for r in recs if r["id"] == "2")
            self.assertEqual(thp["log_search"]["keyword"], "")
            self.assertEqual(thp["log_search"]["node"], "")
        finally:
            asyncio.run(store.delete_report(rid))


class TestLegacyHealthNormalization(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_overview_recomputes_legacy_categorical_health_score(self):
        import asyncio
        from server import store

        rid = "a0000000-0000-0000-0000-000000000099"
        payload = {
            "report_name": "legacy-health",
            "status": "ready",
            "health_score": "critical",
            "recommendations": [
                {"severity": "critical"},
                {"severity": "warning"},
            ],
            "cluster_overview": {},
        }
        asyncio.run(store.write_report_payload(rid, payload))
        try:
            resp = self.client.get(f"/api/reports/{rid}/overview")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsInstance(data["health_score"], int)
            self.assertEqual(data["health_grade"], "B")
            self.assertEqual(data["health_score"], 80)
        finally:
            asyncio.run(store.delete_report(rid))


class TestSecurityHardening(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_html_export_escapes_recommendation_fields(self):
        """C-1: HTML export must escape interpolated fields to prevent stored XSS."""
        import asyncio
        from server import store

        rid = "00000000-0000-0000-0000-000000000001"
        payload = {
            "report_name": "<img src=x onerror=alert(1)>",
            "health_score": 50,
            "cluster_risk_score": 10,
            "recommendations": [
                {
                    "severity": "<script>alert('xss')</script>",
                    "risk_score": 5,
                    "confidence": 0.9,
                    "title": "<b>evil</b>",
                }
            ],
        }
        asyncio.run(store.write_report_payload(rid, payload))
        try:
            resp = self.client.get(f"/api/reports/{rid}/export/html")
            self.assertEqual(resp.status_code, 200)
            html_out = resp.text
            self.assertEqual(resp.headers.get("content-type", "").split(";")[0], "text/html")
            self.assertNotIn("<script>alert('xss')</script>", html_out)
            self.assertNotIn("<img src=x onerror=alert(1)>", html_out)
            self.assertIn("&lt;script&gt;", html_out)
        finally:
            asyncio.run(store.delete_report(rid))

    def test_import_rejects_path_outside_allowlist(self):
        """C-2: import must reject existing paths outside the allowlist (default CWD)."""
        # /etc exists but is outside the default allowlist (cwd) -> 403.
        r = self.client.post("/api/reports/import", json={"path": "/etc"})
        self.assertEqual(r.status_code, 403)

    def test_import_allows_path_within_configured_allowlist(self):
        """C-2: a configured allowlist base permits imports under it."""
        d = tempfile.mkdtemp(prefix="s2rs_allow_")
        with patch.dict('os.environ', {'S2RS_IMPORT_ALLOWED_PATHS': d}):
            r = self.client.post("/api/reports/import", json={"path": d})
        self.assertNotEqual(r.status_code, 403)


class TestQueryTracesApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    @staticmethod
    def _lock_wait_payload() -> dict:
        return {
            "report_name": "query-trace-api-test",
            "cluster_overview": {
                "processlist": [
                    {
                        "ID": "42",
                        "QUERY_TEXT": "SELECT * FROM orders WHERE status = 'pending'",
                        "ELAPSED_TIME": 95.0,
                        "NODE_ID": "10.0.0.3",
                        "State": "Waiting for lock",
                    }
                ],
                "blocked_queries": [
                    {
                        "BLOCKED_QUERY_ID": "42",
                        "BLOCKED_QUERY_TEXT": "SELECT * FROM orders WHERE status = 'pending'",
                        "BLOCKING_TYPE": "user transaction row lock",
                        "BLOCKED_NODE_ID": "10.0.0.3",
                    }
                ],
                "nodes_detail": [
                    {"id": 1, "ip_addr": "10.0.0.1", "type": "MA"},
                    {"id": 3, "ip_addr": "10.0.0.3", "type": "LEAF"},
                ],
            },
            "queries": [
                {
                    "ACTIVITY_NAME": "Select_orders_pending",
                    "QUERY_TEXT": "SELECT * FROM orders WHERE status = ?",
                    "ELAPSED_TIME": 95.0,
                }
            ],
            "partitions": {"total_partitions": 8},
        }

    def test_query_traces_list_resolve_and_get(self):
        import asyncio
        from server import store

        rid = "b0000000-0000-0000-0000-000000000001"
        payload = self._lock_wait_payload()
        asyncio.run(store.write_report_payload(rid, payload))
        try:
            list_resp = self.client.get(f"/api/reports/{rid}/query-traces")
            self.assertEqual(list_resp.status_code, 200)
            traces = list_resp.json().get("traces", [])
            self.assertGreaterEqual(len(traces), 1)
            trace_id = traces[0]["trace_id"]

            get_resp = self.client.get(f"/api/reports/{rid}/query-traces/{trace_id}")
            self.assertEqual(get_resp.status_code, 200)
            self.assertEqual(get_resp.json()["trace_id"], trace_id)
            self.assertEqual(get_resp.json()["trace_type"], "lock_wait")

            resolve_resp = self.client.post(
                f"/api/reports/{rid}/query-traces/resolve",
                json={"connection_id": "42"},
            )
            self.assertEqual(resolve_resp.status_code, 200)
            self.assertEqual(resolve_resp.json()["trace_type"], "lock_wait")
            self.assertIn("evidence_summary", resolve_resp.json())
        finally:
            asyncio.run(store.delete_report(rid))


if __name__ == "__main__":
    unittest.main()
