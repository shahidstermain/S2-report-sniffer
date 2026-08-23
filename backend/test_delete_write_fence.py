"""Regression: delete-during-parse must not resurrect customer report data.

Trigger scenario:
  1. Upload starts analysis (report row status=processing, analysis job running).
  2. Operator deletes the report; API returns success and the filesystem tree is gone.
  3. The in-flight parse/hydrate path still calls write_report_logs / write_report_payload.

Without a write fence, ``_atomic_write_text`` recreates ``reports/{id}/`` and FTS
inserts succeed with no FK to ``reports``, leaving customer diagnostics on disk
after a successful DELETE.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from storage import LocalReportStore


def _run(coro):
    return asyncio.run(coro)


REPORT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def test_late_payload_and_log_writes_do_not_resurrect_deleted_report(tmp_path):
    store = LocalReportStore(tmp_path)
    _run(store.create_report_stub(REPORT_ID, "customer-cluster.zip", 1024, "zip"))
    # Static fixture text only; no file is created or trusted at this path.
    _run(store.enqueue_analysis_job(REPORT_ID, {"archive_path": "/tmp/customer-cluster.zip"}))  # nosec B108
    assert _run(store.claim_analysis_job("worker-1", lease_seconds=60)) is not None

    assert _run(store.delete_report(REPORT_ID)) is True
    assert _run(store.get_report_fields(REPORT_ID)) is None
    report_dir = Path(tmp_path) / "reports" / REPORT_ID
    assert not report_dir.exists()

    # Late writers from the in-flight analysis / hydrate paths.
    _run(
        store.write_report_logs(
            REPORT_ID,
            [
                {
                    "timestamp": "2024-01-01 00:00:01",
                    "severity": "ERROR",
                    "message": "secret host customer.example.com",
                    "hostname": "leaf-1",
                }
            ],
        )
    )
    _run(
        store.write_report_payload(
            REPORT_ID,
            {
                "id": REPORT_ID,
                "nodes": [{"hostname": "customer.example.com"}],
                "disk_intelligence": {"summary": {"overhead_bytes": 1}},
            },
        )
    )
    _run(store.update_report_fields(REPORT_ID, {"status": "ready", "node_count": 1}))

    assert not report_dir.exists()
    assert not (report_dir / "report.json").exists()
    assert not (report_dir / "logs.jsonl").exists()

    with sqlite3.connect(Path(tmp_path) / "reports.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM reports WHERE id=?", (REPORT_ID,)).fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM report_logs_fts WHERE report_id=?",
                (REPORT_ID,),
            ).fetchone()[0]
            == 0
        )


def test_delete_purges_existing_fts_rows(tmp_path):
    store = LocalReportStore(tmp_path)
    _run(store.create_report_stub(REPORT_ID, "customer-cluster.zip", 1024, "zip"))
    _run(
        store.write_report_logs(
            REPORT_ID,
            [
                {
                    "timestamp": "2024-01-01 00:00:01",
                    "severity": "ERROR",
                    "message": "indexed before delete",
                    "hostname": "leaf-1",
                }
            ],
        )
    )
    with sqlite3.connect(Path(tmp_path) / "reports.sqlite") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM report_logs_fts WHERE report_id=?",
                (REPORT_ID,),
            ).fetchone()[0]
            == 1
        )

    assert _run(store.delete_report(REPORT_ID)) is True
    with sqlite3.connect(Path(tmp_path) / "reports.sqlite") as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM report_logs_fts WHERE report_id=?",
                (REPORT_ID,),
            ).fetchone()[0]
            == 0
        )


def test_write_report_logs_requires_existing_report_row(tmp_path):
    store = LocalReportStore(tmp_path)
    _run(
        store.write_report_logs(
            REPORT_ID,
            [{"timestamp": "t", "severity": "INFO", "message": "x", "hostname": "h"}],
        )
    )
    assert not (Path(tmp_path) / "reports" / REPORT_ID).exists()
