import multiprocessing
import sys

# CRITICAL: Must call freeze_support before any other imports for PyInstaller
# This prevents recursive process spawning when the executable runs
multiprocessing.freeze_support()

# Singleton lock to prevent duplicate backend processes
import os
import tempfile
_lock_file = os.path.join(tempfile.gettempdir(), "s2rs_backend.lock")
if os.path.exists(_lock_file):
    # Check if process is actually running
    try:
        with open(_lock_file, 'r') as f:
            pid = f.read().strip()
        if pid and os.path.exists(f"/proc/{pid}"):
            print(f"Backend already running (PID {pid})", file=sys.stderr)
            sys.exit(1)
    except:
        pass
# Write current PID to lock file
try:
    with open(_lock_file, 'w') as f:
        f.write(str(os.getpid()))
except:
    pass

import uvicorn


def main():
    host = os.environ.get("S2RS_HOST", "127.0.0.1")
    port = int(os.environ.get("S2RS_PORT", "8000"))
    log_level = os.environ.get("S2RS_LOG_LEVEL", "info")
    uvicorn.run("server:app", host=host, port=port, log_level=log_level, reload=False)


if __name__ == "__main__":
    main()

