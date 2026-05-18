import multiprocessing
import sys
import os
import shutil

multiprocessing.freeze_support()

_bundle = getattr(sys, '_MEIPASS', None)

if not _bundle:
    import backend  # noqa: F401 — verifies source tree can be imported


_log_dir = os.path.expanduser('~/Library/Logs/S2ReportSniffer')


def _log(msg):
    try:
        os.makedirs(_log_dir, exist_ok=True)
        try:
            from time import strftime
            ts = strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts = 'unknown'
        with open(os.path.join(_log_dir, 's2rs-backend.log'), 'a') as f:
            f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass


_lock_file = os.path.join(os.path.expanduser('~/Library/Logs/S2ReportSniffer'), 's2rs_backend.lock')
try:
    os.makedirs(os.path.dirname(_lock_file), exist_ok=True)
except Exception:
    _lock_file = f'/tmp/s2rs_backend_{os.getpid()}.lock'

if os.path.exists(_lock_file):
    try:
        with open(_lock_file) as f:
            pid_str = f.read().strip()
        if pid_str:
            try:
                os.kill(int(pid_str), 0)
                _log(f'Backend already running (PID {pid_str}) — exiting')
                sys.exit(1)
            except (OSError, ValueError):
                pass
    except Exception:
        pass

try:
    with open(_lock_file, 'w') as f:
        f.write(str(os.getpid()))
except Exception:
    pass


def _cleanup_lock():
    try:
        os.remove(_lock_file)
    except Exception:
        pass


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
            extracted_dir = os.path.join(_log_dir, 's2rs-backend-src')
            os.makedirs(extracted_dir, exist_ok=True)
            _log(f'Extracting to {extracted_dir}')

            for fn in os.listdir(_bundle_backend_dir):
                if fn.endswith('.py') and fn != '__init__.py':
                    src = os.path.join(_bundle_backend_dir, fn)
                    if fn == 'server.py':
                        dst = os.path.join(extracted_dir, 'app.py')
                        _log(f'  server.py -> app.py')
                    else:
                        dst = os.path.join(extracted_dir, fn)
                    shutil.copy2(src, dst)
                    _log(f'  copied {fn}')

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