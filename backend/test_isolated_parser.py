import asyncio
import json
import multiprocessing
import os
import time
import zipfile

import pytest

import services.isolated_parser as isolated_parser
from services.isolated_parser import parse_archive_isolated


def _sleeping_child(send_connection, *_args) -> None:
    try:
        time.sleep(60)
    finally:
        send_connection.close()


def _crashing_child(*_args) -> None:
    os._exit(2)


def test_archive_parser_runs_in_child_process(tmp_path):
    archive = tmp_path / "report.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("cluster.json", json.dumps({"nodes": []}))

    parsed = asyncio.run(parse_archive_isolated(str(archive), None))
    assert parsed["detected_format"] == "zip"
    assert parsed["raw_node_count"] == 0


def test_parse_archive_isolated_cancellation_terminates_child_promptly(tmp_path, monkeypatch):
    real_get_context = multiprocessing.get_context
    spawned: list[multiprocessing.Process] = []

    class _ProxyContext:
        def __init__(self, real_ctx):
            self._real_ctx = real_ctx

        def Pipe(self, duplex=False):
            return self._real_ctx.Pipe(duplex=duplex)

        def Process(self, target, args=(), daemon=False):
            proc = self._real_ctx.Process(target=_sleeping_child, args=args, daemon=daemon)
            spawned.append(proc)
            return proc

    monkeypatch.setattr(
        isolated_parser.multiprocessing,
        "get_context",
        lambda method="spawn": _ProxyContext(real_get_context(method)),
    )

    async def scenario() -> float:
        task = asyncio.create_task(parse_archive_isolated(str(tmp_path / "missing.zip"), None))
        deadline = time.monotonic() + 5.0
        while not spawned and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert spawned, "child process was not spawned"
        # Let child enter sleep.
        await asyncio.sleep(0.1)

        cancel_started = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return time.monotonic() - cancel_started

    elapsed = asyncio.run(scenario())
    assert elapsed < 3.0, f"cancellation took too long: {elapsed:.2f}s"
    assert len(spawned) == 1
    assert not spawned[0].is_alive()
    assert spawned[0].exitcode is not None


def test_parse_archive_isolated_handles_child_crash_without_hanging(tmp_path, monkeypatch):
    real_get_context = multiprocessing.get_context

    class _ProxyContext:
        def __init__(self, real_ctx):
            self._real_ctx = real_ctx

        def Pipe(self, duplex=False):
            return self._real_ctx.Pipe(duplex=duplex)

        def Process(self, target, args=(), daemon=False):
            return self._real_ctx.Process(target=_crashing_child, args=args, daemon=daemon)

    monkeypatch.setattr(
        isolated_parser.multiprocessing,
        "get_context",
        lambda method="spawn": _ProxyContext(real_get_context(method)),
    )

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="exited"):
        asyncio.run(parse_archive_isolated(str(tmp_path / "crash.zip"), None))
    assert time.monotonic() - started < 5.0
