"""Regression tests for atomic desktop single-instance locking."""

from __future__ import annotations

import os
from pathlib import Path

import desktop_runtime_lock


def test_acquire_runtime_lock_is_exclusive(tmp_path: Path):
    lock_path = tmp_path / "s2rs_backend.lock"
    first = desktop_runtime_lock.acquire_runtime_lock(str(lock_path), os.getpid())
    assert first.acquired is True
    assert first.fd is not None
    assert lock_path.read_text(encoding="utf-8") == str(os.getpid())

    second = desktop_runtime_lock.acquire_runtime_lock(str(lock_path), os.getpid() + 1)
    assert second.acquired is False
    assert second.holder_pid == str(os.getpid())

    desktop_runtime_lock.release_runtime_lock(first)
    third = desktop_runtime_lock.acquire_runtime_lock(str(lock_path), 4242)
    assert third.acquired is True
    assert lock_path.read_text(encoding="utf-8") == "4242"
    desktop_runtime_lock.release_runtime_lock(third)


def test_release_keeps_stable_lock_inode(tmp_path: Path):
    lock_path = tmp_path / "s2rs_backend.lock"
    lock = desktop_runtime_lock.acquire_runtime_lock(str(lock_path), os.getpid())
    inode = lock_path.stat().st_ino

    desktop_runtime_lock.release_runtime_lock(lock)

    assert lock_path.stat().st_ino == inode


def test_desktop_entry_uses_atomic_lock_helper():
    source = Path(__file__).with_name("desktop_entry.py").read_text(encoding="utf-8")
    helper = Path(__file__).with_name("desktop_runtime_lock.py").read_text(encoding="utf-8")
    assert "acquire_runtime_lock" in source
    assert "fcntl.flock" in helper
    assert "msvcrt.locking" in helper
    assert "open(_lock_file, 'w')" not in source
