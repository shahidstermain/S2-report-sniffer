"""Tests for bounded tracelog indexing and store-wide disk retention."""

from __future__ import annotations

import asyncio
import gzip
import os
import time
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import parsers
import processing_lifecycle as lifecycle
import server
import storage_retention as retention
from storage import LocalReportStore


def _run(coro):
    return asyncio.run(coro)


def _create_ready_report(
    store: LocalReportStore,
    report_id: str,
    *,
    uploaded_at: str,
    parsed_at: str | None = None,
    extracted_bytes: int = 0,
    timeline_bytes: int = 0,
    external_extracted: Path | None = None,
) -> Path:
    _run(store.create_report_stub(report_id, f"report-{report_id[:8]}", 1024, "tar.gz"))
    report_dir = store.reports_dir / report_id
    report_dir.mkdir(parents=True, exist_ok=True)

    _run(
        store.write_report_payload(
            report_id,
            {
                "id": report_id,
                "report_name": f"report-{report_id[:8]}",
                "uploaded_at": uploaded_at,
                "status": "ready",
                "cluster_overview": {"version": "8.9.0"},
                "nodes": [],
                "recommendations": [],
            },
        )
    )
    _run(
        store.write_report_logs(
            report_id,
            [
                {
                    "timestamp": "2026-01-01 00:00:00.000",
                    "severity": "ERROR",
                    "hostname": "node-1",
                    "role": "LEAF",
                    "message": "parsed fallback log line",
                    "source": "memsql.log",
                }
            ],
        )
    )

    fields: dict[str, object] = {
        "status": "ready",
        "uploaded_at": uploaded_at,
        "parsed_at": parsed_at or uploaded_at,
    }
    if external_extracted is not None:
        fields["extracted_path"] = str(external_extracted)
    elif extracted_bytes > 0:
        ext_dir = store._extracted_dir(report_id)
        ext_dir.mkdir(parents=True, exist_ok=True)
        (ext_dir / "payload.bin").write_bytes(b"x" * extracted_bytes)
        fields["extracted_path"] = str(ext_dir)

    if timeline_bytes > 0:
        tl_path = store._timeline_path(report_id)
        tl_path.write_bytes(b"t" * timeline_bytes)

    _run(store.update_report_fields(report_id, fields))
    return report_dir


def test_retention_evicts_oldest_heavy_artifacts_first_and_preserves_dashboards(
    tmp_path, monkeypatch
):
    store = LocalReportStore(tmp_path / "data")
    monkeypatch.setenv("S2RS_MAX_EXTRACTED_KEEP_GB", "1")
    monkeypatch.setenv("S2RS_MAX_TIMELINE_KEEP_MB", "100")
    # Global cap = 15 KB
    monkeypatch.setenv("S2RS_MAX_RETAINED_GB", str(15_000 / 1024**3))

    oldest = str(uuid.uuid4())
    middle = str(uuid.uuid4())
    newest = str(uuid.uuid4())

    _create_ready_report(
        store,
        oldest,
        uploaded_at="2026-01-01T00:00:00+00:00",
        extracted_bytes=6_000,
        timeline_bytes=4_000,
    )
    _create_ready_report(
        store,
        middle,
        uploaded_at="2026-01-02T00:00:00+00:00",
        extracted_bytes=6_000,
        timeline_bytes=4_000,
    )
    _create_ready_report(
        store,
        newest,
        uploaded_at="2026-01-03T00:00:00+00:00",
        extracted_bytes=6_000,
        timeline_bytes=4_000,
    )

    summary = retention.enforce_storage_retention(store, protect_report_id=newest)

    assert summary["freed_bytes"] >= 15_000
    assert summary["total_heavy_bytes_after"] <= 15_000

    # Oldest had both extracted + timeline evicted; middle lost extracted first; newest untouched.
    assert not store._extracted_dir(oldest).exists()
    assert not store._timeline_path(oldest).exists()
    assert not store._extracted_dir(middle).exists()
    assert store._timeline_path(middle).exists()
    assert store._extracted_dir(newest).exists()
    assert store._timeline_path(newest).exists()

    # Evicted reports still keep their dashboard payload, parsed logs, and DB row.
    assert _run(store.read_report_payload(oldest)) is not None
    assert store._report_logs_path(oldest).exists()
    assert _run(store.get_extracted_path(oldest)) is None

    # /logs/search falls back to parsed mode cleanly after extracted eviction.
    with patch.object(server, "store", store):
        client = TestClient(server.app)
        res = client.get(f"/api/reports/{oldest}/logs/search", params={"keyword": "fallback"})
        assert res.status_code == 200
        body = res.json()
        assert body["search_mode"] == "parsed"
        assert body["total"] == 1


def test_retention_never_deletes_external_directory_import(tmp_path, monkeypatch):
    store = LocalReportStore(tmp_path / "data")
    external_dir = tmp_path / "customer-bundle"
    external_dir.mkdir()
    marker = external_dir / "keep.txt"
    marker.write_bytes(b"z" * 10_000)

    monkeypatch.setenv("S2RS_MAX_RETAINED_GB", "0")
    rid = str(uuid.uuid4())
    _create_ready_report(
        store,
        rid,
        uploaded_at="2026-01-01T00:00:00+00:00",
        timeline_bytes=2_000,
        external_extracted=external_dir,
    )

    retention.enforce_storage_retention(store)

    assert marker.exists()
    assert _run(store.get_extracted_path(rid)) == str(external_dir)
    assert not store._timeline_path(rid).exists()


def test_retention_cleans_error_oversized_orphans_scratch_and_uploads(tmp_path, monkeypatch):
    store = LocalReportStore(tmp_path / "data")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()

    monkeypatch.setenv("S2RS_MAX_EXTRACTED_KEEP_GB", "0.00001")  # ~10 KB
    monkeypatch.setenv("S2RS_MAX_TIMELINE_KEEP_MB", "0.01")  # ~10 KB
    monkeypatch.setenv("S2RS_MAX_RETAINED_GB", "1")

    # 1. Error report with leftover extracted + timeline
    err_id = str(uuid.uuid4())
    _run(store.create_report_stub(err_id, "failed.tar.gz", 10, "tar.gz"))
    store._extracted_dir(err_id).mkdir(parents=True, exist_ok=True)
    (store._extracted_dir(err_id) / "junk.bin").write_bytes(b"a" * 2048)
    store._timeline_path(err_id).write_bytes(b"b" * 2048)
    _run(store.update_report_fields(err_id, {"status": "error"}))

    # 2. Legacy oversized single timeline (> 10 KB)
    legacy_id = str(uuid.uuid4())
    _create_ready_report(
        store,
        legacy_id,
        uploaded_at="2026-01-02T00:00:00+00:00",
        timeline_bytes=25_000,
    )

    # 3. Active processing report must NOT be touched (neither artifacts nor staged upload)
    active_id = str(uuid.uuid4())
    _run(store.create_report_stub(active_id, "active.tar.gz", 10, "tar.gz"))
    store._extracted_dir(active_id).mkdir(parents=True, exist_ok=True)
    (store._extracted_dir(active_id) / "active.bin").write_bytes(b"c" * 20_000)
    active_upload = upload_dir / f"{active_id}.tar.gz"
    active_upload.write_bytes(b"active-archive")

    # 4. Stale staged upload for terminal report + orphaned dir + stale .timeline-* + stale temp dir
    stale_upload = upload_dir / f"{err_id}.tar.gz"
    stale_upload.write_bytes(b"stale-archive")
    orphan_dir = store.reports_dir / str(uuid.uuid4())
    orphan_dir.mkdir()
    (orphan_dir / "old.txt").write_text("orphan")
    stale_tl_scratch = store.base_dir / ".timeline-abandoned"
    stale_tl_scratch.mkdir()
    (stale_tl_scratch / "tracelogs.sqlite").write_bytes(b"temp")
    stale_tmp = temp_dir / "s2rs-tracelog-old"
    stale_tmp.mkdir()
    (stale_tmp / "entries.jsonl").write_bytes(b"temp")

    old_mtime = time.time() - 90_000
    for p in (orphan_dir, stale_tl_scratch, stale_tmp):
        os.utime(p, (old_mtime, old_mtime))

    retention.enforce_storage_retention(
        store,
        upload_dir=upload_dir,
        orphan_grace_seconds=60.0,
        temp_grace_seconds=60.0,
        upload_grace_seconds=60.0,
    )
    retention.sweep_stale_temp_dirs(temp_dir, max_age_seconds=3600.0)

    assert not store._extracted_dir(err_id).exists()
    assert not store._timeline_path(err_id).exists()
    assert not store._timeline_path(legacy_id).exists()
    assert not stale_upload.exists()
    assert not orphan_dir.exists()
    assert not stale_tl_scratch.exists()
    assert not stale_tmp.exists()
    assert (store._extracted_dir(active_id) / "active.bin").exists()
    assert active_upload.exists()


def test_processing_lifecycle_scrubs_artifacts_on_interrupted_error(tmp_path):
    store = LocalReportStore(tmp_path / "data")
    rid = str(uuid.uuid4())
    _run(store.create_report_stub(rid, "interrupted.tar.gz", 10, "tar.gz"))
    store._extracted_dir(rid).mkdir(parents=True, exist_ok=True)
    (store._extracted_dir(rid) / "part.bin").write_bytes(b"x" * 4096)
    store._timeline_path(rid).write_bytes(b"y" * 4096)

    recovered = _run(lifecycle.recover_interrupted_reports(store))
    assert recovered == 1
    assert not store._extracted_dir(rid).exists()
    assert not store._timeline_path(rid).exists()


def test_parse_report_directory_bounds_timeline_spool_across_nodes(tmp_path, monkeypatch):
    bundle = tmp_path / "cluster-bundle"
    for node_name in ("host1-MA", "host2-LEAF"):
        log_dir = bundle / node_name / "memsqlTracelogs"
        log_dir.mkdir(parents=True)
        (log_dir / "memsql.log").write_text(
            "".join(
                f"100 2026-01-02 00:00:{i % 60:02d}.000 INFO: active info {i}\n"
                for i in range(60)
            )
            + "100 2026-01-02 00:01:00.000 ERROR: critical active error\n"
        )
        with gzip.open(log_dir / "memsql.log.1.gz", "wt") as gz:
            gz.write(
                "".join(
                    f"100 2026-01-01 00:00:{i % 60:02d}.000 INFO: old info {i}\n"
                    for i in range(100)
                )
            )

    monkeypatch.setenv("S2RS_MAX_TIMELINE_ROWS", "40")
    spool = tmp_path / "entries.jsonl"
    parsers.parse_report_directory(str(bundle), "cluster-bundle", log_spool=spool)

    lines = [line for line in spool.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) <= 40
    # Both nodes received a fair share of the bounded timeline spool.
    assert any("host1" in line for line in lines)
    assert any("host2" in line for line in lines)
