import asyncio
import json
from types import SimpleNamespace

import pytest

import processing_lifecycle as lifecycle
from storage import LocalReportStore


class FakeStore:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates = []

    async def list_reports(self, limit=100):
        return self.rows[:limit]

    async def list_reports_by_status(self, status):
        return [row for row in self.rows if row.get("status") == status]

    async def update_report_fields(self, report_id, fields):
        self.updates.append((report_id, dict(fields)))
        for row in self.rows:
            if row.get("id") == report_id:
                row.update(fields)


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
    store = FakeStore()

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


def test_parser_timeout_becomes_terminal_error():
    store = FakeStore()

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
