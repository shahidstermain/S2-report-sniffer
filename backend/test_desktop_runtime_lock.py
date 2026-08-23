"""Regression tests for desktop single-instance lock ownership."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from desktop_runtime_lock import lock_is_stale, pid_is_s2rs_backend


def _spawn_desktop_entry_like() -> subprocess.Popen:
    # Command line must contain ``desktop_entry`` so pid_is_s2rs_backend matches.
    return subprocess.Popen(
        ["python3", "-c", "import time;  # desktop_entry\ntime.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_lock_with_live_owner_is_not_stale_after_24h(tmp_path: Path):
    helper = _spawn_desktop_entry_like()
    try:
        time.sleep(0.2)
        assert pid_is_s2rs_backend(helper.pid)

        lock_path = tmp_path / "s2rs_backend.lock"
        lock_path.write_text(str(helper.pid), encoding="utf-8")
        aged = time.time() - (25 * 60 * 60)
        os.utime(lock_path, (aged, aged))

        assert lock_is_stale(str(lock_path)) is False
    finally:
        helper.kill()
        helper.wait(timeout=5)


def test_lock_with_dead_owner_is_stale(tmp_path: Path):
    helper = _spawn_desktop_entry_like()
    pid = helper.pid
    helper.kill()
    helper.wait(timeout=5)
    time.sleep(0.1)

    lock_path = tmp_path / "s2rs_backend.lock"
    lock_path.write_text(str(pid), encoding="utf-8")

    assert pid_is_s2rs_backend(pid) is False
    assert lock_is_stale(str(lock_path)) is True


def test_empty_lock_file_is_stale(tmp_path: Path):
    lock_path = tmp_path / "s2rs_backend.lock"
    lock_path.write_text("", encoding="utf-8")
    assert lock_is_stale(str(lock_path)) is True


def test_missing_lock_file_is_stale(tmp_path: Path):
    assert lock_is_stale(str(tmp_path / "missing.lock")) is True
