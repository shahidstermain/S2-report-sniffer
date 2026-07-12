"""Regression tests for upload staging directory selection."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import server


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
