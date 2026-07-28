"""Desktop backend single-instance lock helpers.

Kept separate from ``desktop_entry.py`` so the stale-lock predicate can be unit
tested without running the entrypoint's import-time lock acquisition.
"""

from __future__ import annotations

import os
import subprocess


def pid_is_s2rs_backend(pid: int) -> bool:
    """Best-effort check that *pid* is a live s2rs-backend / desktop_entry process.

    Returns False for any process we cannot positively identify (different user,
    recycled PID, missing process, etc.).
    """
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        # ps -o args= prints the full command line so we can detect both the
        # bundled binary name and dev-mode ``python -m desktop_entry``.
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return False
        cmdline = (result.stdout or "").strip()
        if not cmdline:
            return False
        return "s2rs-backend" in cmdline or "desktop_entry" in cmdline
    except Exception:
        return False


def lock_is_stale(path: str, max_age_seconds: int = 24 * 60 * 60) -> bool:
    """Return True when an existing lock file should be ignored.

    A live s2rs-backend / desktop_entry PID always owns the lock, even when the
    lock file mtime is old. Startup writes the lock once and never refreshes
    mtime, so age alone must not treat a healthy long-running backend as stale.

    ``max_age_seconds`` is retained for call-site compatibility but is not used
    to override a positively identified live owner.
    """
    del max_age_seconds  # age-alone takeover is unsafe; ownership is PID-based
    try:
        with open(path) as handle:
            pid_str = handle.read().strip()
        if not pid_str:
            return True
        return not pid_is_s2rs_backend(int(pid_str))
    except Exception:
        return True
