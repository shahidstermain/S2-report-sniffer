from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
import uuid


logger = logging.getLogger(__name__)


class AnalysisJobStore(Protocol):
    async def claim_analysis_job(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None: ...
    async def renew_analysis_job(self, report_id: str, worker_id: str, lease_seconds: int) -> bool: ...
    async def finish_analysis_job(
        self,
        report_id: str,
        state: str,
        error_code: str | None = None,
        *,
        worker_id: str,
    ) -> bool: ...
    async def enqueue_analysis_job(self, report_id: str, request: dict[str, Any]) -> None: ...


AnalysisHandler = Callable[[str, dict[str, Any]], Awaitable[bool]]


class AnalysisJobRunner:
    """Bounded workers over a durable SQLite-backed analysis queue."""

    def __init__(
        self,
        store: AnalysisJobStore,
        handler: AnalysisHandler,
        *,
        worker_count: int = 1,
        lease_seconds: int = 300,
    ) -> None:
        self.store = store
        self.handler = handler
        self.worker_count = max(1, min(4, worker_count))
        self.lease_seconds = max(30, lease_seconds)
        self._workers: list[asyncio.Task] = []
        self._wakeup = asyncio.Event()

    async def start(self) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(index + 1))
            for index in range(self.worker_count)
        ]
        self._wakeup.set()

    async def stop(self) -> None:
        workers, self._workers = self._workers, []
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    async def enqueue(self, report_id: str, request: dict[str, Any]) -> None:
        await self.store.enqueue_analysis_job(report_id, request)
        self._wakeup.set()

    async def _heartbeat(self, report_id: str, worker_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(max(10, self.lease_seconds // 4))
                renewed = await self.store.renew_analysis_job(
                    report_id, worker_id, self.lease_seconds
                )
                if not renewed:
                    return
        except asyncio.CancelledError:
            return

    async def _still_owns_lease(self, report_id: str, worker_id: str) -> bool:
        """Return True only while this worker still holds the analysis lease.

        Used to skip terminal ``finish_analysis_job`` after reclaim so a stale
        worker cannot overwrite the successor's job state, and as the signal
        that in-flight handlers must not persist payload/logs.
        """
        return await self.store.renew_analysis_job(
            report_id, worker_id, self.lease_seconds
        )

    async def _worker(self, number: int) -> None:
        worker_id = f"{os.getpid()}:{number}:{uuid.uuid4().hex[:8]}"
        while True:
            self._wakeup.clear()
            job = await self.store.claim_analysis_job(worker_id, self.lease_seconds)
            if job is None:
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=2.0)
                except TimeoutError:
                    pass
                continue
            report_id = str(job["report_id"])
            # Inject lease identity into the in-memory request only (never persisted).
            handler_request = dict(job.get("request") or {})
            handler_request["_worker_id"] = worker_id
            handler_request["_lease_seconds"] = self.lease_seconds
            heartbeat = asyncio.create_task(self._heartbeat(report_id, worker_id))
            try:
                try:
                    succeeded = await self.handler(report_id, handler_request)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Analysis worker failed for report %s", report_id)
                    if await self._still_owns_lease(report_id, worker_id):
                        finished = await self.store.finish_analysis_job(
                            report_id,
                            "failed",
                            "worker_failure",
                            worker_id=worker_id,
                        )
                        if not finished:
                            logger.warning(
                                "Ignored stale analysis failure finish for report %s from worker %s "
                                "(lease no longer owned)",
                                report_id,
                                worker_id,
                            )
                    else:
                        logger.warning(
                            "Skipping failed finish for report %s; analysis lease was reclaimed",
                            report_id,
                        )
                else:
                    if await self._still_owns_lease(report_id, worker_id):
                        finished = await self.store.finish_analysis_job(
                            report_id,
                            "succeeded" if succeeded else "failed",
                            None if succeeded else "analysis_failed",
                            worker_id=worker_id,
                        )
                        if not finished:
                            logger.warning(
                                "Ignored stale analysis finish for report %s from worker %s "
                                "(lease no longer owned)",
                                report_id,
                                worker_id,
                            )
                    else:
                        logger.warning(
                            "Skipping finish for report %s; analysis lease was reclaimed",
                            report_id,
                        )
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
