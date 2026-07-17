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
    """Persist a terminal error without exposing local paths or exception details."""

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


async def recover_interrupted_reports(store: Any) -> int:
    """Convert rows orphaned by an earlier backend process into actionable errors.

    A freshly started desktop backend has no parser tasks from the previous process,
    so every persisted ``processing`` row is necessarily orphaned.
    """

    rows = await store.list_reports(limit=500)
    interrupted = [row for row in rows if row.get("status") == "processing"]
    for row in interrupted:
        report_id = str(row.get("id") or "")
        if report_id:
            await _mark_processing_error(store, report_id, _INTERRUPTED_MESSAGE)

    if interrupted:
        logger.warning(
            "Recovered %d interrupted report-processing row(s)",
            len(interrupted),
        )
    return len(interrupted)


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
