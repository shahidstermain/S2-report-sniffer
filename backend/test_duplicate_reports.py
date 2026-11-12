import asyncio
import io
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server as srv
from storage import LocalReportStore

FP = "sha256:" + "a" * 64
OTHER_FP = "sha256:" + "b" * 64


def _run(coro):
    return asyncio.run(coro)


def _report_ids(store: LocalReportStore) -> set[str]:
    with store._store_db() as conn:
        return {row[0] for row in conn.execute("SELECT id FROM reports").fetchall()}


def _stub(store: LocalReportStore, report_id: str, fingerprint: str | None, uploaded_at: str) -> None:
    _run(store.create_report_stub(report_id, "Synthetic", 10, "zip", content_fingerprint=fingerprint))
    _run(store.update_report_fields(report_id, {"uploaded_at": uploaded_at}))


def _zip_bytes(content: bytes = b"node data") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report/node-MA/memsql.log", content)
    return buf.getvalue()


def test_supersede_removes_only_older_duplicates(tmp_path):
    store = LocalReportStore(tmp_path)
    _stub(store, "old", FP, "2026-01-01T00:00:00+00:00")
    _stub(store, "current", FP, "2026-01-02T00:00:00+00:00")
    _stub(store, "newer", FP, "2026-01-03T00:00:00+00:00")
    _stub(store, "unrelated", OTHER_FP, "2026-01-01T00:00:00+00:00")
    _stub(store, "legacy", None, "2026-01-01T00:00:00+00:00")

    assert _run(store.supersede_duplicate_reports("current")) == ["old"]
    assert _report_ids(store) == {"current", "newer", "unrelated", "legacy"}


def test_supersede_without_fingerprint_is_noop(tmp_path):
    store = LocalReportStore(tmp_path)
    _stub(store, "a", None, "2026-01-01T00:00:00+00:00")
    _stub(store, "b", None, "2026-01-02T00:00:00+00:00")

    assert _run(store.supersede_duplicate_reports("b")) == []
    assert _report_ids(store) == {"a", "b"}


def test_supersede_cancels_inflight_job_of_older_duplicate(tmp_path):
    store = LocalReportStore(tmp_path)
    _stub(store, "old", FP, "2026-01-01T00:00:00+00:00")
    _stub(store, "new", FP, "2026-01-02T00:00:00+00:00")
    _run(store.enqueue_analysis_job("old", {"archive_path": "x"}))
    assert _run(store.claim_analysis_job("worker-a", lease_seconds=60)) is not None

    assert _run(store.supersede_duplicate_reports("new")) == ["old"]
    assert _run(store.renew_analysis_job("old", "worker-a", 60)) is False
    _run(store.write_report_payload("old", {"id": "old"}))
    assert not store._report_payload_path("old").exists()


def test_find_reports_by_fingerprint_excludes_self(tmp_path):
    store = LocalReportStore(tmp_path)
    _stub(store, "a", FP, "2026-01-01T00:00:00+00:00")
    _stub(store, "b", FP, "2026-01-02T00:00:00+00:00")

    assert _run(store.find_reports_by_fingerprint(FP, exclude_id="b")) == ["a"]
    assert _run(store.find_reports_by_fingerprint("", exclude_id="b")) == []


def test_existing_database_gains_fingerprint_column(tmp_path):
    with sqlite3.connect(tmp_path / "reports.sqlite") as conn:
        conn.execute(
            "CREATE TABLE reports (id TEXT PRIMARY KEY, report_name TEXT NOT NULL, "
            "uploaded_at TEXT NOT NULL, status TEXT NOT NULL, file_size INTEGER NOT NULL, "
            "detected_format TEXT NOT NULL, node_count INTEGER, version TEXT, health_score TEXT, "
            "recommendation_count INTEGER, cluster_risk_score INTEGER, progress_json TEXT, "
            "payload_path TEXT, error TEXT)"
        )
        conn.execute(
            "INSERT INTO reports (id, report_name, uploaded_at, status, file_size, detected_format) "
            "VALUES ('legacy', 'Old', '2026-01-01T00:00:00+00:00', 'ready', 1, 'zip')"
        )

    store = LocalReportStore(tmp_path)
    row = _run(store.get_report_fields("legacy", fields=["content_fingerprint"]))
    assert row == {"content_fingerprint": None}


def _client(store: LocalReportStore) -> TestClient:
    srv._upload_counts.clear()
    return TestClient(srv.app, raise_server_exceptions=False)


def test_upload_same_archive_reports_and_replaces_previous_analysis(tmp_path):
    store = LocalReportStore(tmp_path / "data")
    payload = _zip_bytes()
    with patch.object(srv, "store", store), patch.object(srv, "UPLOAD_DIR", tmp_path):
        client = _client(store)
        first = client.post("/api/reports/upload", files={"file": ("r.zip", payload, "application/zip")})
        assert first.status_code == 200, first.text
        assert first.json()["replaces_report_ids"] == []

        second = client.post("/api/reports/upload", files={"file": ("r.zip", payload, "application/zip")})
        assert second.status_code == 200, second.text
        first_id, second_id = first.json()["id"], second.json()["id"]
        assert second.json()["replaces_report_ids"] == [first_id]

        different = client.post(
            "/api/reports/upload",
            files={"file": ("r.zip", _zip_bytes(b"other"), "application/zip")},
        )
        assert different.json()["replaces_report_ids"] == []

        # Old analysis stays until the new one is ready.
        _run(srv._supersede_duplicate_reports(second_id))
        assert first_id in _report_ids(store)

        _run(store.update_report_fields(second_id, {"status": "ready"}))
        _run(srv._supersede_duplicate_reports(second_id))
        assert first_id not in _report_ids(store)
        assert {second_id, different.json()["id"]} <= _report_ids(store)


def test_upload_can_opt_out_of_replacement(tmp_path):
    store = LocalReportStore(tmp_path / "data")
    payload = _zip_bytes()
    with patch.object(srv, "store", store), patch.object(srv, "UPLOAD_DIR", tmp_path):
        client = _client(store)
        first = client.post("/api/reports/upload", files={"file": ("r.zip", payload, "application/zip")})
        kept = client.post(
            "/api/reports/upload?replace_duplicates=false",
            files={"file": ("r.zip", payload, "application/zip")},
        )
        assert kept.json()["replaces_report_ids"] == []
        kept_id = kept.json()["id"]
        _run(store.update_report_fields(kept_id, {"status": "ready"}))
        _run(srv._supersede_duplicate_reports(kept_id))
        assert {first.json()["id"], kept_id} <= _report_ids(store)


def test_import_matches_uploaded_archive_content(tmp_path):
    store = LocalReportStore(tmp_path / "data")
    archive = tmp_path / "imports" / "r.zip"
    archive.parent.mkdir()
    archive.write_bytes(_zip_bytes())
    env = {"S2RS_IMPORT_ALLOWED_PATHS": str(archive.parent)}
    with patch.object(srv, "store", store), patch.object(srv, "UPLOAD_DIR", tmp_path), patch.dict(
        "os.environ", env
    ):
        client = _client(store)
        uploaded = client.post(
            "/api/reports/upload", files={"file": ("r.zip", archive.read_bytes(), "application/zip")}
        )
        imported = client.post("/api/reports/import", json={"path": str(archive)})
        assert imported.status_code == 200, imported.text
        assert imported.json()["replaces_report_ids"] == [uploaded.json()["id"]]

        rejected = client.post(
            "/api/reports/import", json={"path": str(archive), "replace_duplicates": "yes"}
        )
        assert rejected.status_code == 400


def test_directory_reimport_is_a_duplicate(tmp_path):
    store = LocalReportStore(tmp_path / "data")
    report_dir = tmp_path / "imports" / "bundle"
    report_dir.mkdir(parents=True)
    (report_dir / "memsql.log").write_text("line\n")
    env = {"S2RS_IMPORT_ALLOWED_PATHS": str(report_dir.parent)}
    with patch.object(srv, "store", store), patch.dict("os.environ", env):
        client = _client(store)
        first = client.post("/api/reports/import", json={"path": str(report_dir)})
        second = client.post("/api/reports/import", json={"path": str(report_dir)})
        assert second.json()["replaces_report_ids"] == [first.json()["id"]]


def test_run_analysis_job_supersedes_after_success(tmp_path):
    store = LocalReportStore(tmp_path)
    _stub(store, "old", FP, "2026-01-01T00:00:00+00:00")
    _stub(store, "new", FP, "2026-01-02T00:00:00+00:00")

    async def fake_parse(report_id, *args, **kwargs):
        await store.update_report_fields(report_id, {"status": "ready"})
        return True

    with patch.object(srv, "store", store), patch.object(srv, "_parse_report_background", fake_parse):
        assert _run(srv._run_analysis_job("new", {"archive_path": str(Path(tmp_path) / "x.zip")})) is True
    assert _report_ids(store) == {"new"}


def test_failed_analysis_keeps_previous_report(tmp_path):
    store = LocalReportStore(tmp_path)
    _stub(store, "old", FP, "2026-01-01T00:00:00+00:00")
    _stub(store, "new", FP, "2026-01-02T00:00:00+00:00")

    async def fake_parse(report_id, *args, **kwargs):
        await store.update_report_fields(report_id, {"status": "error"})
        return False

    with patch.object(srv, "store", store), patch.object(srv, "_parse_report_background", fake_parse):
        assert _run(srv._run_analysis_job("new", {"archive_path": "x.zip"})) is False
    assert _report_ids(store) == {"old", "new"}
