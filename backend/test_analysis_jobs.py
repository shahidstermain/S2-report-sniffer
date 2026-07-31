import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from storage import LocalReportStore


def _run(coro):
    return asyncio.run(coro)


def _create_report(store: LocalReportStore, report_id: str) -> None:
    _run(store.create_report_stub(report_id, "Synthetic", 10, "zip"))


def _job_state(store: LocalReportStore, report_id: str) -> dict:
    with store._store_db() as conn:
        conn.row_factory = __import__("sqlite3").Row
        row = conn.execute(
            "SELECT state, error_code, lease_owner FROM analysis_jobs WHERE report_id=?",
            (report_id,),
        ).fetchone()
        assert row is not None
        return dict(row)


def test_analysis_job_lifecycle(tmp_path):
    store = LocalReportStore(tmp_path)
    report_id = "11111111-1111-4111-8111-111111111111"
    _create_report(store, report_id)
    request = {"archive_path": str(tmp_path / "report.zip"), "anonymize": True}

    _run(store.enqueue_analysis_job(report_id, request))
    job = _run(store.claim_analysis_job("worker-a", lease_seconds=60))

    assert job is not None
    assert job["report_id"] == report_id
    assert job["request"] == request
    assert job["attempts"] == 1
    assert _run(store.claim_analysis_job("worker-b", lease_seconds=60)) is None
    assert _run(store.renew_analysis_job(report_id, "worker-a", 60)) is True

    assert _run(store.finish_analysis_job(report_id, "succeeded", worker_id="worker-a")) is True
    assert _run(store.claim_analysis_job("worker-b", lease_seconds=60)) is None


def test_expired_analysis_job_is_reclaimed(tmp_path):
    store = LocalReportStore(tmp_path)
    report_id = "22222222-2222-4222-8222-222222222222"
    _create_report(store, report_id)
    _run(store.enqueue_analysis_job(report_id, {"archive_path": str(tmp_path / "report.zip")}))
    assert _run(store.claim_analysis_job("dead-worker", lease_seconds=60)) is not None

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with store._store_db() as conn:
        conn.execute(
            "UPDATE analysis_jobs SET lease_expires_at=? WHERE report_id=?",
            (expired, report_id),
        )
        conn.commit()

    reclaimed = _run(store.claim_analysis_job("new-worker", lease_seconds=60))
    assert reclaimed is not None
    assert reclaimed["attempts"] == 2


def test_requeue_clears_terminal_job_state(tmp_path):
    store = LocalReportStore(tmp_path)
    report_id = "33333333-3333-4333-8333-333333333333"
    _create_report(store, report_id)
    _run(store.enqueue_analysis_job(report_id, {"archive_path": "first"}))
    assert _run(store.claim_analysis_job("worker-a")) is not None
    assert (
        _run(
            store.finish_analysis_job(
                report_id, "failed", "test_failure", worker_id="worker-a"
            )
        )
        is True
    )

    _run(store.enqueue_analysis_job(report_id, {"archive_path": "second"}))
    job = _run(store.claim_analysis_job("worker-b"))
    assert job is not None
    assert job["request"]["archive_path"] == "second"


def test_stale_worker_cannot_overwrite_reclaimed_job_finish(tmp_path):
    """After lease reclaim, the old worker must not flip succeeded → failed."""
    store = LocalReportStore(tmp_path)
    report_id = "44444444-4444-4444-8444-444444444444"
    _create_report(store, report_id)
    _run(store.enqueue_analysis_job(report_id, {"archive_path": "report.zip"}))

    assert _run(store.claim_analysis_job("stale-worker", lease_seconds=60)) is not None

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with store._store_db() as conn:
        conn.execute(
            "UPDATE analysis_jobs SET lease_expires_at=? WHERE report_id=?",
            (expired, report_id),
        )
        conn.commit()

    assert _run(store.claim_analysis_job("live-worker", lease_seconds=60)) is not None
    assert (
        _run(
            store.finish_analysis_job(
                report_id, "succeeded", worker_id="live-worker"
            )
        )
        is True
    )
    assert _job_state(store, report_id)["state"] == "succeeded"

    # Stale worker finishes late (e.g. handler exception after heartbeat stopped).
    assert (
        _run(
            store.finish_analysis_job(
                report_id, "failed", "worker_failure", worker_id="stale-worker"
            )
        )
        is False
    )
    state = _job_state(store, report_id)
    assert state["state"] == "succeeded"
    assert state["error_code"] is None
    assert state["lease_owner"] is None


def test_finish_requires_current_lease_owner_while_running(tmp_path):
    store = LocalReportStore(tmp_path)
    report_id = "55555555-5555-4555-8555-555555555555"
    _create_report(store, report_id)
    _run(store.enqueue_analysis_job(report_id, {"archive_path": "report.zip"}))
    assert _run(store.claim_analysis_job("owner", lease_seconds=60)) is not None

    assert (
        _run(
            store.finish_analysis_job(
                report_id, "failed", "spoofed", worker_id="not-owner"
            )
        )
        is False
    )
    state = _job_state(store, report_id)
    assert state["state"] == "running"
    assert state["lease_owner"] == "owner"


def test_reclaimed_job_does_not_downgrade_ready_report_when_source_missing(tmp_path):
    """Upload cleanup can delete the archive before finish_analysis_job runs.

    On reclaim, a missing source must not flip an already-ready report to error.
    """
    import server

    store = LocalReportStore(tmp_path)
    report_id = "44444444-4444-4444-8444-444444444444"
    _create_report(store, report_id)
    _run(store.update_report_fields(report_id, {"status": "ready"}))
    _run(
        store.write_report_payload(
            report_id,
            {"id": report_id, "status": "ready", "recommendations": []},
        )
    )

    missing = tmp_path / "already-deleted.zip"
    request = {
        "archive_path": str(missing),
        "file_size": 10,
        "remove_source_after_parse": True,
        "anonymize": True,
        "report_name": "already-deleted.zip",
    }

    with patch.object(server, "store", store):
        assert _run(server._run_analysis_job(report_id, request)) is True

    fields = _run(store.get_report_fields(report_id, fields=["status", "error"]))
    assert fields["status"] == "ready"
    assert not fields.get("error")


def test_parse_failure_preserves_ready_status(tmp_path):
    import server

    store = LocalReportStore(tmp_path)
    report_id = "55555555-5555-4555-8555-555555555555"
    _create_report(store, report_id)
    _run(store.update_report_fields(report_id, {"status": "ready"}))

    with patch.object(server, "store", store):
        ok = _run(
            server._parse_report_background(
                report_id,
                str(tmp_path / "gone.zip"),
                1,
                remove_source_after_parse=False,
                anonymize=True,
            )
        )

    assert ok is True
    fields = _run(store.get_report_fields(report_id, fields=["status"]))
    assert fields["status"] == "ready"
