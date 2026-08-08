"""Regression tests for upload staging directory selection."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest import mock

import server
from fastapi.testclient import TestClient
from storage import LocalReportStore


def test_ensure_upload_dir_uses_preferred_when_writable(tmp_path, monkeypatch):
    preferred = tmp_path / "sdb_uploads"
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path))

    result = server._ensure_upload_dir()

    assert result == preferred
    assert preferred.is_dir()
    probe = preferred / "ok.txt"
    probe.write_text("ok")
    assert probe.read_text() == "ok"


def test_ensure_upload_dir_falls_back_when_preferred_not_writable(tmp_path, monkeypatch):
    preferred = tmp_path / "sdb_uploads"
    preferred.mkdir()
    fallback = tmp_path / "fallback_uploads"
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_mkdtemp(prefix="sdb_uploads_"):
        fallback.mkdir(exist_ok=True)
        return str(fallback)

    monkeypatch.setattr(server.tempfile, "mkdtemp", fake_mkdtemp)

    def deny_probe(self, data, encoding=None, errors=None, newline=None):
        if self.parent == preferred and str(self.name).startswith(".write_probe_"):
            raise PermissionError("denied")
        return Path.write_text(self, data, encoding=encoding, errors=errors, newline=newline)

    with mock.patch.object(Path, "write_text", deny_probe):
        result = server._ensure_upload_dir()

    assert result == fallback
    assert result != preferred
    assert result.is_dir()


def test_scrub_staged_upload_removes_report_archive(tmp_path, monkeypatch):
    upload_dir = tmp_path / "sdb_uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(server, "UPLOAD_DIR", upload_dir)
    report_id = str(uuid.uuid4())
    staged = upload_dir / f"{report_id}.zip"
    staged.write_bytes(b"customer-cluster-report")
    other = upload_dir / f"{uuid.uuid4()}.zip"
    other.write_bytes(b"keep-me")

    server._scrub_staged_upload(report_id)

    assert not staged.exists()
    assert other.exists()


def test_delete_report_scrubs_staging_when_job_never_runs(tmp_path, monkeypatch):
    """DELETE before worker claim must not leave the staged Cluster Report on disk."""
    data_dir = tmp_path / "data"
    upload_dir = tmp_path / "sdb_uploads"
    upload_dir.mkdir()
    store = LocalReportStore(str(data_dir))
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(server, "UPLOAD_DIR", upload_dir)

    report_id = str(uuid.uuid4())
    staged = upload_dir / f"{report_id}.tar.gz"
    staged.write_bytes(b"fixture-archive")
    asyncio.run(store.create_report_stub(report_id, "pending.zip", staged.stat().st_size, "tar.gz"))
    asyncio.run(
        store.enqueue_analysis_job(
            report_id,
            {
                "archive_path": str(staged),
                "file_size": staged.stat().st_size,
                "remove_source_after_parse": True,
            },
        )
    )

    client = TestClient(server.app, raise_server_exceptions=True)
    response = client.delete(f"/api/reports/{report_id}")
    assert response.status_code == 200
    assert not staged.exists()
    assert asyncio.run(store.get_report_fields(report_id, fields=["status"])) is None
