"""Cross-platform exclusive lock for the desktop backend runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


@dataclass
class RuntimeLock:
    """Open descriptor that owns the process-wide desktop lock."""

    path: str
    fd: int | None
    acquired: bool
    holder_pid: str | None = None


def _try_lock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is not None:  # pragma: no branch - platform-specific
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return
    raise OSError("No supported file-locking implementation")


def _unlock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no branch - platform-specific
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _read_holder(fd: int) -> str | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        return os.read(fd, 64).decode("ascii", errors="ignore").strip("\0\r\n ") or None
    except OSError:
        return None


def acquire_runtime_lock(path: str, pid: int) -> RuntimeLock:
    """Atomically acquire the single-instance lock and annotate it with ``pid``."""

    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return RuntimeLock(path=path, fd=None, acquired=False)
    try:
        _try_lock(fd)
    except OSError:
        holder = _read_holder(fd)
        os.close(fd)
        return RuntimeLock(path=path, fd=None, acquired=False, holder_pid=holder)

    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(pid).encode("ascii"))
        os.fsync(fd)
    except OSError:
        # The descriptor still owns the lock even if PID annotation fails.
        pass
    return RuntimeLock(path=path, fd=fd, acquired=True, holder_pid=str(pid))


def release_runtime_lock(lock: RuntimeLock) -> None:
    """Release a runtime lock without unlinking its race-sensitive lock file."""

    if lock.fd is None:
        return
    try:
        _unlock(lock.fd)
    except OSError:
        pass
    try:
        os.close(lock.fd)
    except OSError:
        pass
    lock.fd = None
