"""Resource-limited subprocess boundary for untrusted archive parsing."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import threading
import time
from typing import Any

_POLL_INTERVAL_S = 0.25
logger = logging.getLogger(__name__)


def process_isolation_enabled() -> bool:
    raw = os.environ.get("S2RS_PROCESS_ISOLATION", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    # Unit tests rely on monkeypatching parser callables in-process. Dedicated
    # isolation tests exercise this boundary explicitly.
    return "PYTEST_CURRENT_TEST" not in os.environ


def _apply_resource_limits() -> None:
    try:
        import resource
    except ImportError:
        return
    memory_mb = max(512, int(os.environ.get("S2RS_PARSE_MEMORY_MB", "4096")))
    cpu_seconds = max(60, int(os.environ.get("S2RS_PARSE_CPU_SECONDS", "3600")))
    nofile = max(128, int(os.environ.get("S2RS_PARSE_MAX_FILES", "2048")))
    limits = (
        (resource.RLIMIT_AS, memory_mb * 1024 * 1024),
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_NOFILE, nofile),
    )
    for kind, soft in limits:
        try:
            _old_soft, old_hard = resource.getrlimit(kind)
            new_soft = min(soft, old_hard) if old_hard != resource.RLIM_INFINITY else soft
            resource.setrlimit(kind, (new_soft, old_hard))
        except (OSError, ValueError):
            continue


def _parse_archive_child(send_connection, archive_path: str, persist_to: str | None, log_spool=None) -> None:
    try:
        _apply_resource_limits()
        from parsers import parse_report_archive_streaming

        send_connection.send((True, parse_report_archive_streaming(archive_path, None, persist_to, log_spool)))
    except BaseException as exc:
        send_connection.send((False, type(exc).__name__, str(exc)[:1000]))
    finally:
        send_connection.close()


def _terminate_process(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
    process.join(timeout=2.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=2.0)


def _run_child(
    archive_path: str,
    persist_to: str | None,
    log_spool=None,
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_archive_child,
        args=(send, archive_path, persist_to, log_spool),
        daemon=False,
    )
    process.start()
    send.close()
    timeout = max(60, int(os.environ.get("S2RS_PARSE_WALL_SECONDS", "7200")))
    deadline = time.monotonic() + timeout
    message = None
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError("Isolated archive parser cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Archive parser exceeded wall-clock limit")
            step = min(_POLL_INTERVAL_S, remaining)
            if receive.poll(step):
                try:
                    message = receive.recv()
                except EOFError as exc:
                    process.join(timeout=2.0)
                    raise RuntimeError(
                        f"Isolated parser exited unexpectedly (exitcode={process.exitcode})"
                    ) from exc
                break
            if not process.is_alive() and not receive.poll(0):
                raise RuntimeError(
                    f"Isolated parser exited without result (exitcode={process.exitcode})"
                )
    finally:
        receive.close()
        _terminate_process(process)

    if message[0] is True:
        return message[1]
    raise ValueError(f"Isolated parser failed ({message[1]}): {message[2]}")


async def parse_archive_isolated(
    archive_path: str, persist_to: str | None, log_spool=None
) -> dict[str, Any]:
    cancel_event = threading.Event()
    task = asyncio.create_task(
        asyncio.to_thread(
            _run_child,
            archive_path,
            persist_to,
            log_spool,
            cancel_event=cancel_event,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel_event.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
        except (asyncio.CancelledError, TimeoutError):
            logger.debug("Timed out or re-cancelled waiting for isolated parser cleanup")
        except Exception as exc:
            logger.debug("Isolated parser raised during cancellation cleanup: %s", exc)
        raise
