"""Exclusive desktop backend runtime lock.

Uses ``fcntl.flock`` so acquisition is atomic across processes. A PID-only
check-then-write lock file races when two launches probe and both proceed.
"""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass


@dataclass
class RuntimeLock:
    path: str
    fd: int | None
    acquired: bool
    holder_pid: str | None = None


def acquire_runtime_lock(path: str, pid: int) -> RuntimeLock:
    """Try to acquire an exclusive lock at ``path`` for ``pid``."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return RuntimeLock(path=path, fd=None, acquired=False, holder_pid=None)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = None
        try:
            with open(path, encoding="utf-8") as handle:
                holder = handle.read().strip() or None
        except OSError:
            holder = None
        os.close(fd)
        return RuntimeLock(path=path, fd=None, acquired=False, holder_pid=holder)
    except OSError:
        os.close(fd)
        return RuntimeLock(path=path, fd=None, acquired=False, holder_pid=None)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, str(pid).encode("ascii"))
        os.fsync(fd)
    except OSError:
        # Still hold the flock even if PID annotation fails.
        pass
    return RuntimeLock(path=path, fd=fd, acquired=True, holder_pid=str(pid))


def release_runtime_lock(lock: RuntimeLock) -> None:
    """Release flock and remove the lock file when we still own the PID record."""
    if lock.fd is not None:
        try:
            fcntl.flock(lock.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(lock.fd)
        except OSError:
            pass
        lock.fd = None
    try:
        if not os.path.exists(lock.path):
            return
        with open(lock.path, encoding="utf-8") as handle:
            pid_str = handle.read().strip()
        if lock.holder_pid and pid_str == lock.holder_pid:
            os.remove(lock.path)
        elif not lock.holder_pid:
            # Best-effort cleanup when holder annotation was never written.
            os.remove(lock.path)
    except OSError:
        pass
