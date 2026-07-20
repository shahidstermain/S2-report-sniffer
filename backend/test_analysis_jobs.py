import asyncio
from datetime import datetime, timedelta, timezone

from storage import LocalReportStore


def _run(coro):
    return asyncio.run(coro)


def _create_report(store: LocalReportStore, report_id: str) -> None:
    _run(store.create_report_stub(report_id, "Synthetic", 10, "zip"))


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

    _run(store.finish_analysis_job(report_id, "succeeded"))
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
    _run(store.finish_analysis_job(report_id, "failed", "test_failure"))

    _run(store.enqueue_analysis_job(report_id, {"archive_path": "second"}))
    job = _run(store.claim_analysis_job("worker-b"))
    assert job is not None
    assert job["request"]["archive_path"] == "second"
