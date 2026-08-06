import asyncio
import multiprocessing
import sys
import os
import shutil
import tempfile
import atexit
import signal
import time

import desktop_runtime_lock

multiprocessing.freeze_support()

_bundle = getattr(sys, '_MEIPASS', None)

if not _bundle:
    import backend as _backend_pkg  # noqa: F401 — verifies source tree can be imported
    # Suppress pyflakes by referencing the module object
    _backend_pkg


_log_dir = os.path.expanduser('~/Library/Logs/S2ReportSniffer')

# Runtime artifacts (lock file, extracted source) live under the data dir when
# S2RS_DATA_DIR is set; otherwise fall back to a stable, non-rotated location
# under ~/.s2-report-sniffer/run. Never reuse the log dir for the extracted
# source tree — macOS log rotation can purge it while the app is running,
# causing ImportError or, worse, a half-extracted module surface.
_data_dir = os.environ.get('S2RS_DATA_DIR')
if _data_dir:
    _runtime_dir = os.path.join(_data_dir, 'run')
else:
    _runtime_dir = os.path.expanduser('~/.s2-report-sniffer/run')
_runtime_dir = os.environ.get('S2RS_RUNTIME_DIR', _runtime_dir)


def _log(msg):
    try:
        os.makedirs(_log_dir, exist_ok=True)
        try:
            ts = time.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts = 'unknown'
        with open(os.path.join(_log_dir, 's2rs-backend.log'), 'a') as f:
            f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass


_lock_file = os.path.join(_runtime_dir, 's2rs_backend.lock')
try:
    os.makedirs(os.path.dirname(_lock_file), exist_ok=True)
except Exception:
    _lock_file = os.path.join(tempfile.gettempdir(), f's2rs_backend_{os.getpid()}.lock')

# Keep the lock fd open for process lifetime. flock is released on close/exit,
# so a crash cannot leave a stuck exclusive lock the way a PID-only file can.
_runtime_lock = desktop_runtime_lock.acquire_runtime_lock(_lock_file, os.getpid())
if not _runtime_lock.acquired:
    _log(
        f'Backend already running (lock held by PID '
        f'{_runtime_lock.holder_pid or "unknown"}) — refusing to start'
    )
    sys.exit(1)


def _cleanup_lock():
    desktop_runtime_lock.release_runtime_lock(_runtime_lock)


def _handle_shutdown_signal(signum, _frame):
    _log(f'Received signal {signum} — uvicorn will shut down gracefully')


try:
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
except Exception:
    pass

atexit.register(_cleanup_lock)


def _install_processing_guards(server_module):
    from processing_lifecycle import install_processing_lifecycle_guards

    recovered = asyncio.run(install_processing_lifecycle_guards(server_module))
    if recovered:
        _log(
            f'Recovered {recovered} interrupted report(s) '
            f'(finalized complete payloads or marked failed)'
        )
    _log('Report-processing lifecycle guards installed')


def main():
    _log('S2RS backend starting')

    host = os.environ.get('S2RS_HOST', '127.0.0.1')
    port = int(os.environ.get('S2RS_PORT', '8000'))
    log_level = os.environ.get('S2RS_LOG_LEVEL', 'info')

    _log(f'Bundle mode: {_bundle is not None}')
    _log(f'Python: {sys.version}')
    _log(f'PID: {os.getpid()}')

    if _bundle:
        _bundle_backend_dir = os.path.join(_bundle, 'backend')
        _log(f'MEIPASS={_bundle}')
        _log(f'Backend source={_bundle_backend_dir}')
        _log(f'Backend dir exists: {os.path.isdir(_bundle_backend_dir)}')

        if os.path.isdir(_bundle_backend_dir):
            # Extract under the runtime dir, NOT the log dir. macOS log
            # rotation can purge the log dir while the backend is running,
            # which would corrupt the running import surface and was the
            # underlying cause of several "Backend exited code 1" reports.
            extracted_dir = os.path.join(_runtime_dir, 's2rs-backend-src')
            os.makedirs(extracted_dir, exist_ok=True)
            _log(f'Extracting to {extracted_dir}')

            # Determine the set of files this bundle version ships so we can
            # purge stale modules left over from older bundles. A mismatch
            # between bundle version and extracted dir otherwise yields a
            # half-old / half-new import surface that crashes at startup.
            bundle_files = set()
            for fn in os.listdir(_bundle_backend_dir):
                # Defense in depth: filter test_*.py and conftest.py here
                # even if the .spec already excludes them. Some legacy
                # bundles shipped test files inside the archive and the
                # extraction loop would otherwise drop them on sys.path.
                if not fn.endswith('.py') or fn == '__init__.py':
                    continue
                if fn.startswith('test_') or fn == 'conftest.py':
                    _log(f'  skipping non-runtime module: {fn}')
                    continue
                bundle_files.add('app.py' if fn == 'server.py' else fn)

            # Purge anything in the extracted dir that this bundle does not
            # ship, plus the previous server.py->app.py copy and any
            # accidentally-extracted test files.
            try:
                for existing in os.listdir(extracted_dir):
                    if existing not in bundle_files:
                        existing_path = os.path.join(extracted_dir, existing)
                        if os.path.isfile(existing_path):
                            os.remove(existing_path)
                            _log(f'  purged stale: {existing}')
            except Exception as e:
                _log(f'  purge failed: {e!r}')

            for fn in sorted(os.listdir(_bundle_backend_dir)):
                if not fn.endswith('.py') or fn == '__init__.py':
                    continue
                if fn.startswith('test_') or fn == 'conftest.py':
                    continue
                src = os.path.join(_bundle_backend_dir, fn)
                if fn == 'server.py':
                    dst = os.path.join(extracted_dir, 'app.py')
                    _log('  server.py -> app.py')
                else:
                    dst = os.path.join(extracted_dir, fn)
                shutil.copy2(src, dst)
                _log(f'  copied {fn} to {os.path.basename(dst)}')

            sys.path.insert(0, extracted_dir)
            _log(f'sys.path[0]={extracted_dir}')

            try:
                import app as _srv
                sys.modules['server'] = _srv
                _log('app module loaded as server ✓')
            except Exception as e:
                _log(f'Import failed: {e}')
                raise
        else:
            _log('FATAL: backend dir not found in bundle')
            sys.exit(1)
    else:
        _log('Dev mode: using source tree')
        import server as _srv
        sys.modules['server'] = _srv

    _install_processing_guards(_srv)

    _log(f'Starting uvicorn on {host}:{port}')
    try:
        import uvicorn
        uvicorn.run(
            'server:app',
            host=host,
            port=port,
            log_level=log_level,
            reload=False,
        )
    finally:
        _log('Backend shutting down')
        _cleanup_lock()


if __name__ == '__main__':
    main()
