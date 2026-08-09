"""Directory import/rehydrate must not follow escaping symlinks into host files."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from archive_security import find_escaping_symlink, path_is_within_root
from parsers import parse_node_directory, parse_report_directory, read_stdout
from server import app, _resolve_allowed_import_path


def _evil_mv_nodes_payload() -> list[dict]:
    return [
        {
            "MemsqlID": "x",
            "rows": [
                {
                    "HOST": "evil.example.com",
                    "PORT": 3306,
                    "TYPE": "LEAF",
                    "STATE": "ONLINE",
                    "NODE_ID": 99,
                    "MEMORY_USED_MB": 1,
                    "MEMORY_TOTAL_MB": 2,
                    "IP_ADDR": "10.9.9.9",
                }
            ],
        }
    ]


def test_path_is_within_root_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.json"
    secret.write_text("{}")
    root = tmp_path / "report"
    root.mkdir()
    inside = root / "ok.json"
    inside.write_text("{}")
    link = root / "secret.json"
    os.symlink(secret, link)
    assert path_is_within_root(inside, root)
    assert not path_is_within_root(link, root)


def test_find_escaping_symlink_detects_nested_collector_link(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "informationSchemaMvNodes.json").write_text("[]")
    report = tmp_path / "report"
    node = report / "host-MA"
    node.mkdir(parents=True)
    os.symlink(outside / "informationSchemaMvNodes.json", node / "informationSchemaMvNodes.json")
    escaped = find_escaping_symlink(report)
    assert escaped is not None
    assert escaped.endswith("informationSchemaMvNodes.json")


def test_parse_report_directory_skips_symlink_node_root(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "informationSchemaMvNodes.json").write_text(json.dumps(_evil_mv_nodes_payload()))
    report = tmp_path / "report"
    report.mkdir()
    os.symlink(outside, report / "host-MA")

    parsed = parse_report_directory(str(report), "symlink-node")
    blob = json.dumps(parsed)
    assert "10.9.9.9" not in blob
    assert "evil.example.com" not in blob
    assert parsed.get("raw_node_count") == 0
    assert any("symlink or escape" in w for w in parsed.get("parse_warnings") or [])


def test_parse_report_directory_skips_symlink_collector_file(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "informationSchemaMvNodes.json").write_text(json.dumps(_evil_mv_nodes_payload()))
    report = tmp_path / "report"
    node = report / "victim-MA"
    node.mkdir(parents=True)
    os.symlink(outside / "informationSchemaMvNodes.json", node / "informationSchemaMvNodes.json")
    (node / "free").mkdir()
    (node / "free" / "stdout").write_text("Mem: 1 1 0 0 0 0\n")

    # Direct node parse must not ingest the escaped collector.
    node_info = parse_node_directory(str(node), "victim", "MA")
    assert node_info.get("mv_nodes") in (None, [], {})

    parsed = parse_report_directory(str(report), "symlink-collector")
    blob = json.dumps(parsed)
    assert "10.9.9.9" not in blob
    assert "evil.example.com" not in blob
    nodes_detail = (parsed.get("cluster_overview") or {}).get("nodes_detail") or []
    assert not any(
        str(row.get("ip_addr") or "") == "10.9.9.9" for row in nodes_detail if isinstance(row, dict)
    )


def test_invalid_utf8_collector_degrades_without_raising(tmp_path: Path):
    node = tmp_path / "host-MA"
    collector = node / "collector"
    collector.mkdir(parents=True)
    (collector / "stdout").write_bytes(b"\xff\xfeinvalid")

    assert read_stdout(str(node), "collector") == ""


def test_resolve_allowed_import_path_rejects_escaping_symlink(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET")
    report = tmp_path / "report"
    node = report / "host-MA"
    node.mkdir(parents=True)
    os.symlink(outside / "secret.txt", node / "secret.txt")

    with patch.dict(os.environ, {"S2RS_IMPORT_ALLOWED_PATHS": str(tmp_path)}):
        with pytest.raises(Exception) as excinfo:
            _resolve_allowed_import_path(str(report))
    # FastAPI HTTPException carries status_code
    err = excinfo.value
    assert getattr(err, "status_code", None) == 400
    detail = getattr(err, "detail", {})
    assert isinstance(detail, dict)
    assert detail.get("error") == "Symlink escapes import root"


def test_import_api_rejects_directory_with_escaping_symlink(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "informationSchemaMvNodes.json").write_text(json.dumps(_evil_mv_nodes_payload()))
    report = tmp_path / "report"
    node = report / "host-MA"
    node.mkdir(parents=True)
    os.symlink(outside / "informationSchemaMvNodes.json", node / "informationSchemaMvNodes.json")

    client = TestClient(app, raise_server_exceptions=False)
    with patch.dict(os.environ, {"S2RS_IMPORT_ALLOWED_PATHS": str(tmp_path)}):
        response = client.post("/api/reports/import", json={"path": str(report)})
    assert response.status_code == 400
    body = response.json()
    assert body.get("error") == "Symlink escapes import root" or (
        isinstance(body.get("detail"), dict)
        and body["detail"].get("error") == "Symlink escapes import root"
    )
