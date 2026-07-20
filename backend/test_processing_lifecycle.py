import asyncio
import json
from types import SimpleNamespace

import pytest

import processing_lifecycle as lifecycle
from storage import LocalReportStore


class FakeStore:
    def __init__(self, rows=None, payloads=None):
        self.rows = list(rows or [])
        self.payloads = dict(payloads or {})
        self.updates = []
        self.finished_jobs = []

    async def list_reports(self, limit=100):
        return self.rows[:limit]

    async def list_reports_by_status(self, status):
        return [row for row in self.rows if row.get("status") == status]

    async def get_report_fields(self, report_id, fields=None):
        for row in self.rows:
            if row.get("id") == report_id:
                if fields is None:
                    return dict(row)
                return {key: row.get(key) for key in fields}
        return None

    async def read_report_payload(self, report_id):
        return self.payloads.get(report_id)

    async def finish_analysis_job(self, report_id, state, error_code=None):
        self.finished_jobs.append((report_id, state, error_code))
    async def update_report_fields(self, report_id, fields):
        self.updates.append((report_id, dict(fields)))
        for row in self.rows:
            if row.get("id") == report_id:
                row.update(fields)
                return
        self.rows.append({"id": report_id, **fields})


def test_recover_interrupted_reports_marks_orphaned_rows_as_error():
    store = FakeStore(
        [
            {"id": "processing-id", "status": "processing"},
            {"id": "ready-id", "status": "ready"},
        ]
    )

    recovered = asyncio.run(lifecycle.recover_interrupted_reports(store))

    assert recovered == 1
    assert len(store.updates) == 1
    report_id, fields = store.updates[0]
    assert report_id == "processing-id"
    assert fields["status"] == "error"
    assert "interrupted" in fields["error"].lower()
    progress = json.loads(fields["progress_json"])
    assert progress["stage"] == "failed"
    assert store.finished_jobs == [
        ("processing-id", "cancelled", "processing_interrupted")
    ]


def test_recover_interrupted_reports_finalizes_complete_payload():
    """Crash after report.json write but before status=ready must not discard analysis."""
    store = FakeStore(
        rows=[{"id": "almost-ready", "status": "processing"}],
        payloads={
            "almost-ready": {
                "status": "ready",
                "progress": {"stage": "complete", "pct": 100, "message": "done"},
                "node_count": 3,
                "version": "8.9.0",
                "health_score": 80,
                "recommendation_count": 2,
                "cluster_risk_score": 20,
                "deployment_method": "toolbox",
                "deployment_confidence": "high",
                "deployment_signals": ["memsqlctl"],
            }
        },
    )

    recovered = asyncio.run(lifecycle.recover_interrupted_reports(store))

    assert recovered == 1
    assert store.rows[0]["status"] == "ready"
    assert store.rows[0]["error"] is None
    assert store.rows[0]["node_count"] == 3
    assert store.finished_jobs == [("almost-ready", "succeeded", None)]
    assert all(fields.get("status") != "error" for _, fields in store.updates)


def test_recover_interrupted_reports_does_not_finalize_incomplete_payload():
    store = FakeStore(
        rows=[{"id": "partial", "status": "processing"}],
        payloads={
            "partial": {
                "status": "processing",
                "progress": {"stage": "parsing", "pct": 40},
            }
        },
    )

    recovered = asyncio.run(lifecycle.recover_interrupted_reports(store))

    assert recovered == 1
    assert store.rows[0]["status"] == "error"
    assert store.finished_jobs == []


def test_recover_interrupted_reports_includes_rows_beyond_list_cap(tmp_path):
    store = LocalReportStore(tmp_path)
    with store._store_db() as conn:
        conn.executemany(
            """INSERT INTO reports
               (id, report_name, uploaded_at, status, file_size, detected_format)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (f"ready-{index}", f"ready-{index}.zip", f"2026-07-20T12:{index // 60:02d}:{index % 60:02d}+00:00", "ready", 1, "zip")
                for index in range(500)
            ] + [("older-processing-id", "older.zip", "2026-07-19T00:00:00+00:00", "processing", 1, "zip")],
        )
        conn.commit()

    assert asyncio.run(lifecycle.recover_interrupted_reports(store)) == 1
    fields = asyncio.run(store.get_report_fields("older-processing-id", fields=["status"]))
    assert fields["status"] == "error"


def test_recover_interrupted_reports_finalizes_local_store_complete_payload(tmp_path):
    store = LocalReportStore(tmp_path)
    report_id = "payload-first-id"
    with store._store_db() as conn:
        conn.execute(
            """INSERT INTO reports
               (id, report_name, uploaded_at, status, file_size, detected_format)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_id, "almost.zip", "2026-08-06T00:00:00+00:00", "processing", 1, "zip"),
        )
        conn.execute(
            """INSERT INTO analysis_jobs
               (report_id, state, request_json, attempts, created_at, lease_owner)
               VALUES (?, 'running', '{}', 1, ?, 'old-worker')""",
            (report_id, "2026-08-06T00:00:00+00:00"),
        )
        conn.commit()
    asyncio.run(
        store.write_report_payload(
            report_id,
            {
                "status": "ready",
                "progress": {"stage": "complete", "pct": 100, "message": "done"},
                "node_count": 2,
                "recommendation_count": 1,
                "cluster_overview": {"version": "8.9.0"},
            },
        )
    )

    assert asyncio.run(lifecycle.recover_interrupted_reports(store)) == 1
    fields = asyncio.run(
        store.get_report_fields(report_id, fields=["status", "node_count", "error"])
    )
    assert fields["status"] == "ready"
    assert fields["node_count"] == 2
    assert fields["error"] is None

    def _job_state():
        with store._store_db() as conn:
            return conn.execute(
                "SELECT state FROM analysis_jobs WHERE report_id=?",
                (report_id,),
            ).fetchone()[0]

    assert _job_state() == "succeeded"


def test_parse_background_persists_payload_before_ready_status():
    """Guard the crash window: report.json must be written before status=ready."""
    from pathlib import Path

    source = Path(__file__).with_name("server.py").read_text(encoding="utf-8")
    write_idx = source.find("await store.write_report_payload(report_id, payload)")
    ready_idx = source.find('"status": "ready",\n            "node_count": parsed.get("raw_node_count", 0)')
    assert write_idx != -1
    assert ready_idx != -1
    assert write_idx < ready_idx


def test_recover_interrupted_reports_cancels_outstanding_analysis_jobs(tmp_path):
    store = LocalReportStore(tmp_path)
    report_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    asyncio.run(store.create_report_stub(report_id, "interrupted.zip", 1, "zip"))
    asyncio.run(
        store.enqueue_analysis_job(
            report_id,
            {"archive_path": "/tmp/missing-report.zip", "anonymize": True},
        )
    )
    assert asyncio.run(store.claim_analysis_job("dead-worker", lease_seconds=60)) is not None

    assert asyncio.run(lifecycle.recover_interrupted_reports(store)) == 1
    fields = asyncio.run(store.get_report_fields(report_id, fields=["status"]))
    assert fields["status"] == "error"
    # Cancelled jobs must not be reclaimable after restart.
    assert asyncio.run(store.claim_analysis_job("new-worker", lease_seconds=60)) is None


def test_recover_interrupted_reports_includes_rows_older_than_list_cap(tmp_path):
    store = LocalReportStore(tmp_path)
    with store._store_db() as conn:
        conn.executemany(
            """
            INSERT INTO reports (
                id, report_name, uploaded_at, status, file_size, detected_format
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"ready-{index}",
                    f"ready-{index}.zip",
                    f"2026-07-20T12:{index // 60:02d}:{index % 60:02d}+00:00",
                    "ready",
                    1,
                    "zip",
                )
                for index in range(500)
            ]
            + [
                (
                    "older-processing-id",
                    "older-processing.zip",
                    "2026-07-19T00:00:00+00:00",
                    "processing",
                    1,
                    "zip",
                )
            ],
        )
        conn.commit()

    recovered = asyncio.run(lifecycle.recover_interrupted_reports(store))

    assert recovered == 1
    oldest = asyncio.run(
        store.get_report_fields("older-processing-id", fields=["status", "error"])
    )
    assert oldest is not None
    assert oldest["status"] == "error"
    assert "interrupted" in oldest["error"].lower()


def test_progress_updates_are_coalesced_but_terminal_status_is_never_skipped(
    monkeypatch,
):
    store = FakeStore()
    times = iter([100.0, 100.1])
    monkeypatch.setattr(lifecycle, "_monotonic", lambda: next(times))
    lifecycle.install_progress_write_coalescing(store, min_interval_s=1.0)

    asyncio.run(store.update_report_fields("report-id", {"progress_json": "first"}))
    asyncio.run(store.update_report_fields("report-id", {"progress_json": "second"}))
    asyncio.run(
        store.update_report_fields(
            "report-id",
            {
                "status": "ready",
                "progress_json": "complete",
            },
        )
    )

    assert store.updates == [
        ("report-id", {"progress_json": "first"}),
        ("report-id", {"status": "ready", "progress_json": "complete"}),
    ]


def test_cancelled_parser_is_persisted_as_error():
    store = FakeStore([{"id": "report-id", "status": "processing"}])

    async def cancelled_parser(report_id, *_args, **_kwargs):
        raise asyncio.CancelledError()

    server_module = SimpleNamespace(
        store=store,
        _parse_report_background=cancelled_parser,
    )
    lifecycle.install_parser_guard(server_module, timeout_s=0)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            server_module._parse_report_background("report-id", "report.zip", 1)
        )

    assert store.updates[-1][0] == "report-id"
    assert store.updates[-1][1]["status"] == "error"
    assert "cancelled" in store.updates[-1][1]["error"].lower()


def test_cancelled_parser_does_not_downgrade_ready_report():
    store = FakeStore([{"id": "report-id", "status": "ready"}])

    async def cancelled_parser(report_id, *_args, **_kwargs):
        raise asyncio.CancelledError()

    server_module = SimpleNamespace(
        store=store,
        _parse_report_background=cancelled_parser,
    )
    lifecycle.install_parser_guard(server_module, timeout_s=0)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server_module._parse_report_background("report-id", "report.zip", 1))

    assert store.updates == []
    assert store.rows[0]["status"] == "ready"


def test_parser_timeout_becomes_terminal_error():
    store = FakeStore([{"id": "report-id", "status": "processing"}])

    async def stalled_parser(report_id, *_args, **_kwargs):
        await asyncio.sleep(10)

    server_module = SimpleNamespace(
        store=store,
        _parse_report_background=stalled_parser,
    )
    lifecycle.install_parser_guard(server_module, timeout_s=0.01)

    result = asyncio.run(
        server_module._parse_report_background("report-id", "report.zip", 1)
    )

    assert result is None
    assert store.updates[-1][0] == "report-id"
    assert store.updates[-1][1]["status"] == "error"
    assert "time limit" in store.updates[-1][1]["error"].lower()


def test_installation_is_idempotent():
    store = FakeStore()

    async def parser(report_id, *_args, **_kwargs):
        return report_id

    server_module = SimpleNamespace(
        store=store,
        _parse_report_background=parser,
    )

    lifecycle.install_progress_write_coalescing(store, min_interval_s=1.0)
    wrapped_update = store.update_report_fields
    lifecycle.install_progress_write_coalescing(store, min_interval_s=1.0)
    assert store.update_report_fields is wrapped_update

    lifecycle.install_parser_guard(server_module, timeout_s=0)
    wrapped_parser = server_module._parse_report_background
    lifecycle.install_parser_guard(server_module, timeout_s=0)
    assert server_module._parse_report_background is wrapped_parser
