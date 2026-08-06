"""Lifecycle guards for desktop report-processing tasks.

The upload endpoint deliberately returns after accepting the Cluster Report, while
parsing continues in an in-memory asyncio task. Without explicit recovery, a
backend restart or task cancellation can leave the persisted SQLite row in the
``processing`` state forever. Large reports can also generate progress callbacks
faster than SQLite writes complete.

This module is installed by ``desktop_entry.py`` after the server module has been
loaded and before uvicorn begins accepting requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from types import ModuleType
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

_INTERRUPTED_MESSAGE = (
    "Processing was interrupted before completion, usually because the application "
    "or backend restarted. Delete this report and upload the Cluster Report again."
)
_CANCELLED_MESSAGE = (
    "Processing was cancelled before completion. Delete this report and upload the "
    "Cluster Report again."
)
_TIMEOUT_MESSAGE = (
    "Processing exceeded the configured time limit. Review the backend log, then "
    "delete this report and upload the Cluster Report again."
)
_DEFAULT_PROGRESS_WRITE_INTERVAL_S = 0.75
_DEFAULT_PROCESSING_TIMEOUT_S = 4 * 60 * 60
_TERMINAL_STATUSES = frozenset({"ready", "error"})
_monotonic = time.monotonic


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r", name, raw)
        return default
    return value if value > 0 else 0.0


async def _mark_processing_error(store: Any, report_id: str, message: str) -> None:
    """Persist a terminal error without exposing local paths or exception details.

    Refuses to overwrite an already-terminal ``ready`` report. Cancellation or
    timeout can land after ``_parse_report_background`` has persisted success and
    deleted the upload; downgrading that row to ``error`` would lose the analysis.
    """

    try:
        existing = await store.get_report_fields(report_id, fields=["status"])
    except Exception:
        existing = None
    if existing and existing.get("status") == "ready":
        logger.warning(
            "Not overwriting ready status for %s with processing error",
            report_id,
        )
        return

    await store.update_report_fields(
        report_id,
        {
            "status": "error",
            "error": message,
            "progress_json": json.dumps(
                {
                    "stage": "failed",
                    "pct": 0,
                    "message": message,
                }
            ),
        },
    )


def _payload_looks_complete(payload: Any) -> bool:
    """True when report.json was written by a successful parse (ready-after-payload)."""

    if not isinstance(payload, dict):
        return False
    if payload.get("status") != "ready":
        return False
    progress = payload.get("progress") or {}
    if not isinstance(progress, dict):
        return False
    return progress.get("stage") == "complete"


async def _finalize_completed_payload(store: Any, report_id: str) -> bool:
    """Promote a processing row whose payload was fully persisted before crash.

    ``_parse_report_background`` writes ``report.json`` before flipping SQLite
    status to ``ready``. A crash in that window leaves a complete payload with a
    ``processing`` row; marking it ``error`` would discard finished analysis.
    """

    reader = getattr(store, "read_report_payload", None)
    if not callable(reader):
        return False
    try:
        payload = await reader(report_id)
    except Exception:
        logger.exception(
            "Failed reading payload while recovering interrupted report %s",
            report_id,
        )
        return False
    if not _payload_looks_complete(payload):
        return False

    progress = payload.get("progress") or {}
    deployment_signals = payload.get("deployment_signals")
    if isinstance(deployment_signals, list):
        deployment_signals = ",".join(str(item) for item in deployment_signals)

    await store.update_report_fields(
        report_id,
        {
            "status": "ready",
            "error": None,
            "node_count": payload.get("node_count")
            or payload.get("raw_node_count")
            or 0,
            "version": payload.get("version"),
            "health_score": payload.get("health_score"),
            "recommendation_count": payload.get("recommendation_count"),
            "cluster_risk_score": payload.get("cluster_risk_score"),
            "deployment_method": payload.get("deployment_method"),
            "deployment_confidence": payload.get("deployment_confidence"),
            "deployment_signals": deployment_signals,
            "progress_json": json.dumps(progress),
        },
    )

    # Prevent a later lease reclaim from re-parsing and overwriting the payload.
    recover_job = getattr(store, "recover_analysis_job", None)
    if callable(recover_job):
        try:
            await recover_job(report_id, "succeeded")
        except Exception:
            logger.warning(
                "Failed to finish analysis job while finalizing recovered report %s",
                report_id,
                exc_info=True,
            )
    return True


async def recover_interrupted_reports(store: Any) -> int:
    """Recover rows orphaned by an earlier backend process.

    A freshly started desktop backend has no parser tasks from the previous process,
    so every persisted ``processing`` row is orphaned. Prefer finalizing rows whose
    ``report.json`` already reflects a completed parse; otherwise mark them error.
    """

    interrupted = await store.list_reports_by_status("processing")
    finalized = 0
    failed = 0
    for row in interrupted:
        report_id = str(row.get("id") or "")
        if not report_id:
            continue
        if await _finalize_completed_payload(store, report_id):
            finalized += 1
            continue
        await _mark_processing_error(store, report_id, _INTERRUPTED_MESSAGE)
        recover_job = getattr(store, "recover_analysis_job", None)
        if callable(recover_job):
            try:
                await recover_job(
                    report_id, "cancelled", "processing_interrupted"
                )
            except Exception:
                logger.warning(
                    "Failed to cancel orphaned analysis job for report %s",
                    report_id,
                    exc_info=True,
                )
        failed += 1

    handled = finalized + failed
    if handled:
        logger.warning(
            "Recovered %d interrupted report-processing row(s) "
            "(%d finalized from complete payload, %d marked failed)",
            handled,
            finalized,
            failed,
        )
    return handled


def install_progress_write_coalescing(
    store: Any,
    *,
    min_interval_s: float | None = None,
) -> None:
    """Coalesce progress-only writes while never delaying terminal status writes."""

    if getattr(store, "_s2rs_progress_coalescing_installed", False):
        return

    interval = (
        _positive_float_env(
            "S2RS_PROGRESS_WRITE_INTERVAL_S",
            _DEFAULT_PROGRESS_WRITE_INTERVAL_S,
        )
        if min_interval_s is None
        else max(0.0, float(min_interval_s))
    )
    original_update = store.update_report_fields
    last_progress_write: dict[str, float] = {}

    async def coalesced_update(report_id: str, fields: dict[str, Any]) -> None:
        field_names = set(fields)
        progress_only = field_names == {"progress_json"}
        terminal = fields.get("status") in _TERMINAL_STATUSES

        if progress_only and interval > 0:
            now = _monotonic()
            previous = last_progress_write.get(report_id)
            if previous is not None and now - previous < interval:
                return
            last_progress_write[report_id] = now

        if terminal:
            last_progress_write.pop(report_id, None)

        await original_update(report_id, fields)

    store.update_report_fields = coalesced_update
    store._s2rs_progress_coalescing_installed = True


async def _run_guarded_parser(
    original_parser: Callable[..., Awaitable[Any]],
    store: Any,
    report_id: str,
    *args: Any,
    timeout_s: float,
    **kwargs: Any,
) -> Any:
    try:
        parser_coro = original_parser(report_id, *args, **kwargs)
        if timeout_s > 0:
            return await asyncio.wait_for(parser_coro, timeout=timeout_s)
        return await parser_coro
    except asyncio.TimeoutError:
        logger.error(
            "Report %s processing exceeded %.0f seconds",
            report_id,
            timeout_s,
        )
        await _mark_processing_error(store, report_id, _TIMEOUT_MESSAGE)
        return None
    except asyncio.CancelledError:
        logger.warning("Report %s processing task was cancelled", report_id)
        await _mark_processing_error(store, report_id, _CANCELLED_MESSAGE)
        raise
    except BaseException:
        # The normal parser handles ordinary Exceptions itself. This final guard is
        # for BaseException subclasses or regressions that escape that handler.
        logger.exception("Unhandled report-processing failure for %s", report_id)
        await _mark_processing_error(
            store,
            report_id,
            "Processing failed unexpectedly. Review the backend log, then delete "
            "this report and upload the Cluster Report again.",
        )
        raise


def install_parser_guard(
    server_module: ModuleType,
    *,
    timeout_s: float | None = None,
) -> None:
    """Wrap the server's parser coroutine with cancellation and timeout handling."""

    if getattr(server_module, "_s2rs_parser_guard_installed", False):
        return

    original_parser = server_module._parse_report_background
    store = server_module.store
    timeout = (
        _positive_float_env(
            "S2RS_PROCESSING_TIMEOUT_S",
            _DEFAULT_PROCESSING_TIMEOUT_S,
        )
        if timeout_s is None
        else max(0.0, float(timeout_s))
    )

    async def guarded_parser(report_id: str, *args: Any, **kwargs: Any) -> Any:
        return await _run_guarded_parser(
            original_parser,
            store,
            report_id,
            *args,
            timeout_s=timeout,
            **kwargs,
        )

    server_module._parse_report_background = guarded_parser
    server_module._s2rs_parser_guard_installed = True


async def install_processing_lifecycle_guards(server_module: ModuleType) -> int:
    """Install all guards and recover rows orphaned by a prior process."""

    store = server_module.store
    install_progress_write_coalescing(store)
    recovered = await recover_interrupted_reports(store)
    install_parser_guard(server_module)
    return recovered
