"""Resource-limited subprocess boundary for untrusted archive parsing."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from typing import Any


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


def _parse_archive_child(send_connection, archive_path: str, persist_to: str | None) -> None:
    try:
        _apply_resource_limits()
        from parsers import parse_report_archive_streaming

        send_connection.send((True, parse_report_archive_streaming(archive_path, None, persist_to)))
    except BaseException as exc:
        send_connection.send((False, type(exc).__name__, str(exc)[:1000]))
    finally:
        send_connection.close()


def _run_child(archive_path: str, persist_to: str | None) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_archive_child,
        args=(send, archive_path, persist_to),
        daemon=False,
    )
    process.start()
    send.close()
    timeout = max(60, int(os.environ.get("S2RS_PARSE_WALL_SECONDS", "7200")))
    try:
        if not receive.poll(timeout):
            process.terminate()
            raise TimeoutError("Archive parser exceeded wall-clock limit")
        message = receive.recv()
    finally:
        receive.close()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join()
    if message[0] is True:
        return message[1]
    raise ValueError(f"Isolated parser failed ({message[1]}): {message[2]}")


async def parse_archive_isolated(
    archive_path: str, persist_to: str | None
) -> dict[str, Any]:
    return await asyncio.to_thread(_run_child, archive_path, persist_to)
