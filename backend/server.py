# ── Standard library ──
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import gzip
import html
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import tarfile
import tempfile
import time
import uuid

# ── Third-party ──
import aiofiles
from fastapi import FastAPI, APIRouter, UploadFile, File, Query, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

_UPLOAD_RATE_LIMIT = 10
_upload_counts: dict = {}

def _client_ip(request: Request) -> str:
    return request.client.host if request and request.client else "unknown"


class _RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/api/reports/upload", "/reports/upload") or \
           request.url.path.rstrip("/") == "/api/reports/upload":
            ip = _client_ip(request)
            now = _time_now()
            if ip not in _upload_counts:
                _upload_counts[ip] = []
            _upload_counts[ip] = [t for t in _upload_counts[ip] if now - t < 60]
            if len(_upload_counts[ip]) >= _UPLOAD_RATE_LIMIT:
                return JSONResponse(
                    status_code=429,
                    content={"error": "rate_limit_exceeded", "detail": f"Upload rate limit: {_UPLOAD_RATE_LIMIT} per minute"},
                    headers={"Retry-After": "60"},
                )
            _upload_counts[ip].append(now)
            # Evict entries for IPs that have no recent uploads to prevent unbounded growth
            stale_ips = [k for k, v in _upload_counts.items() if not v]
            for k in stale_ips:
                del _upload_counts[k]
        return await call_next(request)


_time_now = time.time

ROOT_DIR = Path(__file__).parent

MAX_DECOMPRESSED_BUDGET = 50 * 1024 * 1024 * 1024
_BACKGROUND_TASK_SHUTDOWN_TIMEOUT_S = 30.0
_background_tasks: set[asyncio.Task] = set()


def _track_background_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _shutdown_background_tasks() -> None:
    if not _background_tasks:
        return
    pending = [task for task in _background_tasks if not task.done()]
    if not pending:
        return
    logger.info("Waiting for %d background task(s) to finish", len(pending))
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=_BACKGROUND_TASK_SHUTDOWN_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Background tasks did not finish within %ss; cancelling",
            _BACKGROUND_TASK_SHUTDOWN_TIMEOUT_S,
        )
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def _is_loopback_client(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    host = (client.host or "").split("%", 1)[0]
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("S2RS_LOG_ROUTES", "").strip().lower() in {"1", "true", "yes", "y"}:
        _log_routes(app)
    yield
    logger.info("Application shutdown started")
    await _shutdown_background_tasks()
    try:
        await store.shutdown()
    except Exception:
        logger.exception("Store shutdown failed")
    logger.info("Application shutdown complete")


app = FastAPI(
    title="SingleStore Report Sniffer v1",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class _NoCacheUiStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/ui") or path.startswith("/static"):
            request.scope["headers"] = [
                (k, v)
                for (k, v) in request.scope.get("headers", [])
                if k not in {b"if-none-match", b"if-modified-since"}
            ]
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        return await call_next(request)


def _get_cors_origins() -> list[str]:
    env_val = os.environ.get('S2RS_CORS_ORIGINS', '').strip()
    if not env_val:
        return []
    if '*' in env_val:
        raise ValueError("Wildcard CORS origin ('*') is not permitted for security reasons")
    return [o.strip() for o in env_val.split(',') if o.strip()]


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        extra_connect: list[str] = []
        if _cloud_extensions_enabled():
            extra_connect.extend(["https://api.hostinger.com"])
        connect_src = "'self'" + (" " + " ".join(extra_connect) if extra_connect else "")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            f"connect-src {connect_src}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


from parsers import (
    parse_report_archive_streaming,
    parse_report_directory,
    parse_sparse_report_file,
    infer_deployment_method,
    _normalize_archive_exception,
    ensure_supported_archive_format,
    search_all_trace_logs,
    search_trace_logs_raw,
    hydrate_extended_diagnostics,
    _extended_diagnostics_populated,
    _primary_diagnostics_populated,
    resolve_database_disk_usage,
    resolve_memory_utilization,
    _as_row_list,
)
from validators import (
    RequestValidator,
    ValidationError,
    validate_report_id,
    validate_search_query,
    validate_severity_filter,
    validate_node_filter,
    validate_pagination,
    validate_filename,
    validate_file_size,
    validate_trace_id,
    validate_query_trace_selector,
    MAX_SEARCH_LENGTH,
    MAX_PAGE_SIZE,
)
from monitoring import (
    get_metrics,
    get_alerts,
    get_audit,
    get_health,
    get_performance,
    AlertSeverity,
    record_parsing_duration,
    record_validation_failure,
    record_security_event,
    record_upload_attempt,
    record_upload_complete,
    log_anomaly,
)
from storage import build_store, LocalReportStore
from investigation import build_glean_packet, resolve_incident_clusters, resolve_finding_log_search_terms
from product_features import (
    TelemetryStore,
    anonymize_report,
    build_markdown_export,
    build_portable_html,
    compare_reports,
)
from query_tracer import list_query_trace_candidates, resolve_query_trace, get_query_trace_by_id

def _ensure_upload_dir() -> Path:
    """Return a writable upload staging directory.

    Prefers ``{tempdir}/sdb_uploads``. If that path exists but is not writable
    (e.g. root-owned leftover), fall back to a private temp directory so uploads
    do not fail with PermissionError / HTTP 500.
    """
    preferred = Path(tempfile.gettempdir()) / "sdb_uploads"
    try:
        preferred.mkdir(exist_ok=True)
        probe = preferred / f".write_probe_{os.getpid()}"
        probe.write_text("")
        probe.unlink(missing_ok=True)
        return preferred
    except OSError:
        return Path(tempfile.mkdtemp(prefix="sdb_uploads_"))


UPLOAD_DIR = _ensure_upload_dir()


def _cloud_extensions_enabled() -> bool:
    """Hostinger and other optional cloud integrations. Disabled by default for local-first / air-gap."""
    v = os.environ.get("S2RS_ENABLE_CLOUD_EXTENSIONS", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _require_cloud_extensions() -> None:
    if not _cloud_extensions_enabled():
        raise HTTPException(
            404,
            {
                "error": "cloud_extensions_disabled",
                "message": (
                    "Optional cloud integrations are disabled. "
                    "Set S2RS_ENABLE_CLOUD_EXTENSIONS=1 to enable Hostinger routes."
                ),
            },
        )


CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024 * 1024

metrics = get_metrics()
alerts = get_alerts()
audit = get_audit()
health_service = get_health()
perf = get_performance()
store = build_store()
telemetry = TelemetryStore(getattr(store, "base_dir", Path.home() / ".s2-report-sniffer"))
logger.info(f"Storage base_dir={getattr(store, 'base_dir', None)} db_path={getattr(store, 'db_path', None)}")


def _resolve_allowed_import_path(raw_path: str) -> Path:
    """Resolve and validate a local import/rehydrate path against the allowlist."""
    if not raw_path or not raw_path.strip():
        raise HTTPException(400, {"error": "Invalid path", "message": "Path is required"})
    if len(raw_path) > 4096:
        raise HTTPException(400, {"error": "Invalid path", "message": "Path too long"})

    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        resolved = p.resolve()
    except Exception:
        resolved = p.absolute()

    if not resolved.exists():
        raise HTTPException(404, {"error": "Path not found", "path": str(resolved)})

    allowed_raw = os.environ.get("S2RS_IMPORT_ALLOWED_PATHS", "").strip()
    allowed_bases: list[Path] = []
    if allowed_raw:
        for entry in allowed_raw.split(os.pathsep):
            entry = entry.strip()
            if not entry:
                continue
            try:
                allowed_bases.append(Path(entry).expanduser().resolve())
            except Exception:
                continue
    if not allowed_bases:
        allowed_bases = [Path.cwd().resolve()]
        repo_root = Path(__file__).resolve().parent.parent
        if repo_root not in allowed_bases:
            allowed_bases.append(repo_root)

    if not any(resolved == base or resolved.is_relative_to(base) for base in allowed_bases):
        raise HTTPException(403, {"error": "Path not allowed", "path": str(resolved)})

    if resolved.is_dir():
        if not (os.access(resolved, os.R_OK) and os.access(resolved, os.X_OK)):
            raise HTTPException(403, {"error": "Permission denied", "message": "Directory is not readable", "path": str(resolved)})
    elif resolved.is_file():
        if not os.access(resolved, os.R_OK):
            raise HTTPException(403, {"error": "Permission denied", "message": "File is not readable", "path": str(resolved)})
    else:
        raise HTTPException(400, {"error": "Unsupported path", "message": "Path must be a file or directory", "path": str(resolved)})
    return resolved


async def _load_logs_for_hydration(report_id: str, limit: int = 5000) -> list:
    """Load persisted parsed logs for extended_diagnostics backfill."""
    if not isinstance(store, LocalReportStore):
        return []
    logs_path = store._report_logs_path(report_id)
    if not logs_path.exists():
        return []

    def _read():
        rows: list = []
        with open(logs_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
                if len(rows) >= limit:
                    break
        return rows

    return await asyncio.to_thread(_read)


async def _load_payload(report_id: str):
    """Read a report payload from storage, raising HTTP errors on missing or oversized payloads."""
    try:
        payload = await store.read_report_payload(report_id)
    except ValueError as exc:
        raise HTTPException(413, {"error": "payload_too_large", "message": str(exc)})
    if not payload:
        raise HTTPException(404, "Report not found")
    return payload


def _health_check_storage() -> tuple:
    try:
        if isinstance(store, LocalReportStore):
            import sqlite3

            with sqlite3.connect(store.db_path, timeout=2) as conn:
                conn.execute("SELECT 1")
            return True, "Local storage OK"
        return True, "Storage OK"
    except Exception as e:
        return False, str(e)[:120]

health_service.register_check("storage", _health_check_storage, AlertSeverity.CRITICAL)


async def _update_progress_safe(report_id: str, stage: str, pct: int, message: str, **extra):
    try:
        progress = {"stage": stage, "pct": pct, "message": message}
        progress.update(extra)
        await store.update_report_fields(report_id, {"progress_json": json.dumps(progress)})
    except Exception as e:
        logger.warning(f"Failed to update progress for {report_id}: {e}")


@api_router.post("/reports/upload")
async def upload_report(
    request: Request,
    file: UploadFile | None = File(None),
    report: UploadFile | None = File(None),
    anonymize: bool = Query(True),
):
    start_time = time.time()

    client_ip = request.client.host if request and request.client else "unknown"

    active_file = file or report
    if active_file is None:
        raise HTTPException(400, {
            "error": "No file uploaded",
            "message": "Send the file as multipart form-data field named 'file' (preferred) or 'report'.",
        })

    metric_filename = "[ANONYMIZED]" if anonymize else (active_file.filename or "")
    upload_id = record_upload_attempt(metric_filename, 0, client_ip)

    filename = active_file.filename or ""
    lower_name = filename.lower()
    if lower_name.endswith(".zip"):
        detected_format = "zip"
        ext = ".zip"
    elif lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz"):
        detected_format = "tar.gz"
        ext = ".tar.gz"
    elif lower_name.endswith(".tar"):
        detected_format = "tar"
        ext = ".tar"
    elif lower_name.endswith(".gz"):
        detected_format = "gz"
        ext = ".gz"
    elif lower_name.endswith((".log", ".txt", ".json", ".tsv", ".cnf", ".conf")):
        detected_format = "sparse"
        ext = Path(lower_name).suffix
    else:
        raise HTTPException(400, {
            "error": "Unsupported file type",
            "message": (
                "Accepted formats: .zip, .tar.gz, .tgz, .tar, .gz, "
                ".log, .txt, .json, .tsv, .cnf, .conf"
            ),
            "filename": filename,
        })

    is_valid, sanitized_name = validate_filename(filename)
    if not is_valid:
        record_validation_failure("filename", {"filename": active_file.filename})
        record_security_event("invalid_filename", {"filename": active_file.filename, "ip": client_ip})
        raise HTTPException(400, {
            "error": "Invalid filename",
            "message": sanitized_name,
            "filename": active_file.filename
        })

    report_id = str(uuid.uuid4())
    tmp_path = UPLOAD_DIR / f"{report_id}{ext}"

    try:
        file_size = 0
        max_file_size = MAX_UPLOAD_SIZE_BYTES

        async with aiofiles.open(tmp_path, "wb") as out:
            while True:
                chunk = await active_file.read(CHUNK_SIZE)
                if not chunk:
                    break

                if file_size + len(chunk) > max_file_size:
                    await out.close()
                    tmp_path.unlink(missing_ok=True)
                    metrics.increment("uploads.rejected", tags={"reason": "size_exceeded"})
                    raise HTTPException(413, {
                        "error": "file_size_exceeded",
                        "message": f"File exceeds maximum size of {max_file_size // (1024**3)}GB",
                        "max_size_gb": max_file_size // (1024**3),
                        "filename": filename,
                    })

                file_size += len(chunk)
                await out.write(chunk)

        validation_result = RequestValidator.validate_report_upload_request(filename, file_size)
        if not validation_result.is_valid:
            for error in validation_result.errors:
                record_validation_failure("upload", {"filename": filename, "error": error.message})
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(400, {
                "error": "Invalid file",
                "message": "File validation failed",
                "details": [e.message for e in validation_result.errors],
                "filename": filename,
            })

        # Content sniffing catches gzip-compressed tar misnamed as .tar and wrong types (.deb).
        if detected_format != "sparse":
            try:
                detected_format = ensure_supported_archive_format(str(tmp_path))
            except ValueError as e:
                record_validation_failure("archive", {"filename": filename, "reason": str(e)})
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(400, {
                    "error": "invalid_archive",
                    "message": str(e),
                    "filename": filename,
                })

        if detected_format == "zip":
            import zipfile
            try:
                with zipfile.ZipFile(tmp_path, "r") as zf:
                    infos = zf.infolist()
                    if not infos:
                        record_validation_failure("zip", {"filename": filename, "reason": "empty"})
                        tmp_path.unlink(missing_ok=True)
                        raise HTTPException(400, {
                            "error": "invalid_zip",
                            "message": "Zip archive is empty",
                            "filename": filename,
                        })
                    if any((zi.flag_bits & 0x1) == 0x1 for zi in infos):
                        record_validation_failure("zip", {"filename": filename, "reason": "encrypted"})
                        tmp_path.unlink(missing_ok=True)
                        raise HTTPException(400, {
                            "error": "encrypted_zip",
                            "message": "Password-protected zip archives are not supported",
                            "filename": filename,
                        })
                    if len(infos) > 200000:
                        record_validation_failure("zip", {"filename": filename, "reason": "too_many_entries", "entries": len(infos)})
                        tmp_path.unlink(missing_ok=True)
                        raise HTTPException(400, {
                            "error": "zip_too_large",
                            "message": "Zip archive contains too many entries",
                            "filename": filename,
                        })
            except zipfile.BadZipFile:
                record_validation_failure("zip", {"filename": filename, "reason": "bad_zip"})
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(400, {
                    "error": "invalid_zip",
                    "message": "Corrupted or unsupported zip archive",
                    "filename": filename,
                })
            except RuntimeError as e:
                msg = str(e).lower()
                if "password required" in msg or "encrypted" in msg:
                    record_validation_failure("zip", {"filename": filename, "reason": "encrypted_runtime"})
                    tmp_path.unlink(missing_ok=True)
                    raise HTTPException(400, {
                        "error": "encrypted_zip",
                        "message": "Password-protected zip archives are not supported",
                        "filename": filename,
                    })
                raise
        elif detected_format in {"tar.gz", "tar", "gz"}:
            try:
                if detected_format == "tar.gz":
                    budget = MAX_DECOMPRESSED_BUDGET
                    with tarfile.open(tmp_path, "r:gz") as tf:
                        for member in tf:
                            if member.isfile():
                                budget -= member.size or 0
                                if budget < 0:
                                    raise HTTPException(400, {
                                        "error": "decompression_bomb",
                                        "message": "Archive decompressed size exceeds safety limit (50 GB)",
                                        "filename": filename,
                                    })
                elif detected_format == "tar":
                    with tarfile.open(tmp_path, "r:") as tf:
                        for _member in tf:
                            pass
                else:
                    budget = MAX_DECOMPRESSED_BUDGET
                    with gzip.open(tmp_path, "rb") as gf:
                        while True:
                            chunk = gf.read(1024 * 1024)
                            if not chunk:
                                break
                            budget -= len(chunk)
                            if budget < 0:
                                raise HTTPException(400, {
                                    "error": "decompression_bomb",
                                    "message": "Archive decompressed size exceeds safety limit (50 GB)",
                                    "filename": filename,
                                })
            except Exception as e:
                normalized = _normalize_archive_exception(e, str(tmp_path))
                record_validation_failure("archive", {"filename": filename, "reason": str(normalized)})
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(400, {
                    "error": "invalid_archive",
                    "message": str(normalized),
                    "filename": filename,
                })

        upload_duration = (time.time() - start_time) * 1000
        perf.record_request("/reports/upload", upload_duration, 200)
        record_upload_complete(report_id, metric_filename, upload_duration, "success")

        report_doc = {
            "id": report_id,
            "report_name": sanitized_name,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "status": "processing",
            "file_size": file_size,
            "progress": {
                "stage": "queued",
                "pct": 0,
                "message": "Upload complete. Starting extraction...",
                "nodes_discovered": 0,
                "files_processed": 0,
                "log_lines_indexed": 0,
            },
        }
        stored_report_name = "Anonymized Report" if anonymize else sanitized_name
        await store.create_report_stub(report_id, stored_report_name, file_size, detected_format)
        await store.update_report_fields(report_id, {"progress_json": json.dumps(report_doc["progress"])})

        _track_background_task(
            _parse_report_background(
                report_id,
                str(tmp_path),
                file_size,
                remove_source_after_parse=True,
                anonymize=anonymize,
                report_name=sanitized_name,
            )
        )

        audit.log(
            action="report_upload",
            resource="report",
            resource_id=report_id,
            actor="anonymous",
            result="success",
            details={
                "filename": "[ANONYMIZED]" if anonymize else sanitized_name,
                "size": file_size,
                "duration_ms": upload_duration,
                "anonymized": anonymize,
            },
            ip_address=client_ip,
        )

        return {
            "id": report_id,
            "status": "processing",
            "file_size": file_size,
            "detected_format": detected_format,
            "anonymized": anonymize,
            "message": "Report uploaded and queued for processing",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        record_upload_complete(report_id, metric_filename, (time.time() - start_time) * 1000, "error")
        record_security_event("upload_error", {"error": str(e), "ip": client_ip})
        if os.environ.get('S2RS_ENVIRONMENT', '') == 'production':
            error_message = "An internal error occurred. Please try again or contact support."
        else:
            error_message = str(e)
        error_detail = {
            "error": "Upload failed",
            "message": error_message,
            "report_id": report_id if 'report_id' in locals() else None,
        }
        raise HTTPException(500, error_detail)


@api_router.options("/reports/upload")
async def upload_report_options():
    return Response(status_code=204)


@api_router.post("/reports/import")
async def import_report(request: Request):
    if os.environ.get('S2RS_DISABLE_LOCAL_IMPORT', '').strip().lower() in {'1', 'true', 'yes', 'y'}:
        raise HTTPException(403, {"error": "Local import is disabled"})
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, {"error": "Local import is not supported by this storage backend"})

    try:
        body = await request.json()
    except Exception:
        body = {}
    raw_path = (body.get("path") or "").strip()
    anonymize = body.get("anonymize", True)
    if not isinstance(anonymize, bool):
        raise HTTPException(400, {"error": "anonymize must be a boolean"})
    resolved = _resolve_allowed_import_path(raw_path)

    if resolved.is_dir():
        detected_format = "directory"
        file_size = 0
        scanned = 0
        try:
            for fp in resolved.rglob("*"):
                if fp.is_file():
                    try:
                        file_size += fp.stat().st_size
                    except Exception:
                        pass
                    scanned += 1
                    if scanned >= 50000:
                        break
        except Exception:
            pass
        report_name = resolved.name or "Imported directory"
    elif resolved.is_file():
        lower_name = resolved.name.lower()
        if lower_name.endswith(".zip"):
            detected_format = "zip"
        elif lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz"):
            detected_format = "tar.gz"
        elif lower_name.endswith(".tar"):
            detected_format = "tar"
        elif lower_name.endswith(".gz"):
            detected_format = "gz"
        elif lower_name.endswith((".log", ".txt", ".json", ".tsv", ".cnf", ".conf")):
            detected_format = "sparse"
        else:
            raise HTTPException(400, {
                "error": "Unsupported file type",
                "message": (
                    "Accepted formats: .zip, .tar.gz, .tgz, .tar, .gz, "
                    ".log, .txt, .json, .tsv, .cnf, .conf, or a directory"
                ),
                "path": str(resolved),
            })
        if detected_format != "sparse":
            try:
                detected_format = ensure_supported_archive_format(str(resolved))
            except ValueError as e:
                raise HTTPException(400, {
                    "error": "invalid_archive",
                    "message": str(e),
                    "path": str(resolved),
                })
        try:
            file_size = resolved.stat().st_size
        except Exception:
            file_size = 0
        report_name = resolved.name
    else:
        raise HTTPException(400, {"error": "Unsupported path", "message": "Path must be a file or directory", "path": str(resolved)})

    if len(report_name) > 255:
        report_name = report_name[:255]

    report_id = str(uuid.uuid4())
    client_ip = request.client.host if request and request.client else "unknown"

    stored_report_name = "Anonymized Report" if anonymize else report_name
    await store.create_report_stub(report_id, stored_report_name, file_size, detected_format)
    await store.update_report_fields(report_id, {"progress_json": json.dumps({
        "stage": "queued",
        "pct": 0,
        "message": "Import queued. Starting parsing...",
        "nodes_discovered": 0,
        "files_processed": 0,
        "log_lines_indexed": 0,
    })})

    audit.log(
        action="report_import",
        resource="report",
        resource_id=report_id,
        actor="anonymous",
        result="success",
        details={
            "path": "[ANONYMIZED]" if anonymize else str(resolved),
            "detected_format": detected_format,
            "size": file_size,
            "anonymized": anonymize,
        },
        ip_address=client_ip,
    )

    _track_background_task(
        _parse_report_background(
            report_id,
            str(resolved),
            file_size,
            anonymize=anonymize,
            report_name=report_name,
        )
    )

    return {
        "id": report_id,
        "status": "processing",
        "file_size": file_size,
        "detected_format": detected_format,
        "anonymized": anonymize,
        "message": "Report import queued for processing",
    }


def _extracted_keep_cap_bytes() -> int:
    """Max decompressed bytes to keep on disk for raw search (env-tunable)."""
    raw = os.environ.get("S2RS_MAX_EXTRACTED_KEEP_GB", "").strip()
    if raw:
        try:
            gb = float(raw)
            if gb > 0:
                return int(gb * 1024 ** 3)
        except ValueError:
            pass
    return 2 * 1024 ** 3  # default 2 GB


def _under_extracted_keep_cap(path: str | None) -> bool:
    """True if the extracted payload should be persisted for raw search.

    For archives (``path is None``) the cap is checked against decompressed
    budget tracking inside the parser; here we only honor the env cap. For
    directory imports (``path`` set) we measure the directory size on disk.
    """
    cap = _extracted_keep_cap_bytes()
    if path is None:
        return cap > 0
    try:
        total = 0
        for fp in Path(path).rglob("*"):
            if fp.is_file():
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
                if total > cap:
                    return False
        return total <= cap
    except Exception:
        return False


async def _parse_report_background(
    report_id: str,
    archive_path: str,
    file_size: int,
    *,
    remove_source_after_parse: bool = False,
    anonymize: bool = True,
    report_name: str | None = None,
):
    start_time = time.time()
    loop = asyncio.get_running_loop()

    try:
        await _update_progress_safe(report_id, "extracting", 5, "Discovering report structure...", files_processed=0)

        progress_state = {"files": 0, "nodes": 0, "logs": 0}

        def progress_callback(stage, files=0, nodes=0, logs=0, message=""):
            progress_state["files"] += files
            progress_state["nodes"] = max(progress_state["nodes"], nodes)
            progress_state["logs"] += logs
            progress_message = (
                f"Parsing... {progress_state['files']} files, "
                f"{progress_state['logs']} log lines"
            )
            if not anonymize and message:
                progress_message = message
            asyncio.run_coroutine_threadsafe(
                _update_progress_safe(report_id, stage,
                    min(90, 10 + (progress_state["files"] * 80 // max(progress_state["nodes"] * 50, 1))),
                    progress_message,
                    nodes_discovered=progress_state["nodes"],
                    files_processed=progress_state["files"],
                    log_lines_indexed=progress_state["logs"],
                ),
                loop
            )

        sparse_suffixes = {".log", ".txt", ".json", ".tsv", ".cnf", ".conf"}
        if os.path.isfile(archive_path) and Path(archive_path).suffix.lower() in sparse_suffixes:
            parsed = await loop.run_in_executor(
                None, parse_sparse_report_file, archive_path, report_name or os.path.basename(archive_path)
            )
        elif os.path.isdir(archive_path):
            parsed = await loop.run_in_executor(
                None, parse_report_directory, archive_path, os.path.basename(archive_path), progress_callback
            )
            parsed["detected_format"] = "directory"
            if not anonymize:
                # Directory imports already live on disk. Non-anonymized reports
                # may retain the source path for rehydration and raw log search.
                parsed["import_source_path"] = str(archive_path)
                if _under_extracted_keep_cap(archive_path):
                    parsed["extracted_path"] = str(archive_path)
        else:
            persist_to = None
            # An anonymized report never persists raw extracted files. The parser
            # may use temporary extraction space, which is cleaned after parsing.
            if not anonymize and _under_extracted_keep_cap(None):
                persist_to = str(store._extracted_dir(report_id)) if isinstance(store, LocalReportStore) else None
            parsed = await loop.run_in_executor(
                None,  # type: ignore[arg-type]
                parse_report_archive_streaming,  # type: ignore[arg-type]
                archive_path,
                progress_callback,
                persist_to,
            )
            if not remove_source_after_parse and not anonymize:
                parsed["import_source_path"] = str(archive_path)

        await _update_progress_safe(report_id, "analyzing", 90, "Running recommendations engine...")

        deployment = infer_deployment_method(
            parsed.get("nodes", []),
            parsed.get("cluster_overview", {}),
            parsed.get("report_root"),
        )
        deployment_method = deployment.get("method")
        deployment_confidence = deployment.get("confidence")
        deployment_signals = deployment.get("signals")
        parsed["deployment_method"] = deployment_method
        parsed["deployment_confidence"] = deployment_confidence
        parsed["deployment_signals"] = deployment_signals

        if anonymize:
            parsed, _privacy_manifest = anonymize_report(parsed)
            deployment_method = parsed.get("deployment_method")
            deployment_confidence = parsed.get("deployment_confidence")
            deployment_signals = parsed.get("deployment_signals")
        else:
            parsed["privacy"] = {
                "anonymized": False,
                "scheme": "none",
            }

        recs = parsed.get("recommendations", [])
        critical = sum(1 for r in recs if r.get("severity") == "critical")
        warnings = sum(1 for r in recs if r.get("severity") == "warning")
        health_score = "critical" if critical > 0 else ("warning" if warnings > 0 else "healthy")
        severity_weight = {"critical": 5, "warning": 3, "info": 1}
        cluster_risk_score = 0
        for r in recs[:100]:
            rs = int(r.get("risk_score", 0))
            w = severity_weight.get(r.get("severity", "info"), 1)
            cluster_risk_score += min(100, rs) * w
        cluster_risk_score = min(1000, cluster_risk_score)

        overview = parsed.get("cluster_overview", {})
        logs = parsed.pop("logs", [])
        if isinstance(store, LocalReportStore) and logs:
            await store.write_report_logs(report_id, logs)

        # Persist the extracted report root path so /logs/search can run raw
        # tracelog search with context. Empty/missing path => fallback to the
        # parsed-log storage search (no context).
        extracted_path = parsed.pop("extracted_path", "") or ""
        if extracted_path and isinstance(store, LocalReportStore):
            try:
                await store.set_extracted_path(report_id, extracted_path)
            except Exception as exc:
                logger.warning("Failed to record extracted_path for %s: %s", report_id, exc)

        update_doc = {
            "status": "ready",
            "parsed_at": parsed.get("parsed_at"),
            "detected_format": parsed.get("detected_format", "unknown"),
            "input_mode": parsed.get("input_mode", "bundle"),
            "capabilities": parsed.get("capabilities", {}),
            "privacy": parsed.get("privacy", {}),
            "parse_warnings": parsed.get("parse_warnings", []),
            "node_count": parsed.get("raw_node_count", 0),
            "version": overview.get("version"),
            "health_score": health_score,
            "recommendation_count": len(recs),
            "cluster_risk_score": cluster_risk_score,
            "cluster_overview": overview,
            "nodes": parsed.get("nodes", []),
            "databases": parsed.get("databases", []),
            "storage": parsed.get("storage", []),
            "queries": parsed.get("queries", []),
            "events": parsed.get("events", []),
            "pipelines": parsed.get("pipelines", []),
            "log_summary": parsed.get("log_summary", {}),
            "log_count": len(logs),
            "recommendations": recs,
            "incident_clusters": parsed.get("incident_clusters", []),
            "workload_management": parsed.get("workload_management", []),
            "replication_status": parsed.get("replication_status", []),
            "config_health": parsed.get("config_health", {}),
            "backup_history": parsed.get("backup_history", [])[-50:],
            "resource_pools": parsed.get("resource_pools", []),
            "database_disk_usage": parsed.get("database_disk_usage", []),
            "partitions": parsed.get("partitions", {}),
            "pressure_events_per_hour": parsed.get("pressure_events_per_hour", {}),
            "memory_utilization": parsed.get("memory_utilization", {}),
            "query_analysis": parsed.get("query_analysis", {}),
            "query_patterns": parsed.get("query_patterns", {}),
            "replication_lag_patterns": parsed.get("replication_lag_patterns", {}),
            "long_running_transactions": parsed.get("long_running_transactions", {}),
            "extended_diagnostics": parsed.get("extended_diagnostics", {}),
            "collector_availability": parsed.get("collector_availability", {}),
            "import_source_path": parsed.get("import_source_path"),
            "version_history": parsed.get("version_history", []),
            "availability_groups": parsed.get("availability_groups", []),
            "users": parsed.get("users", []),
            "detected_log_patterns": parsed.get("detected_log_patterns", []),
            "dmesg_events": parsed.get("dmesg_events", []),
            "deployment_method": deployment_method,
            "deployment_confidence": deployment_confidence,
            "deployment_signals": deployment_signals,
            "progress": {
                "stage": "complete", "pct": 100,
                "message": f"Analysis complete. {parsed.get('raw_node_count', 0)} nodes, {len(logs)} log lines, {len(recs)} recommendations",
                "nodes_discovered": parsed.get("raw_node_count", 0),
                "files_processed": progress_state.get("files", 0),
                "log_lines_indexed": len(logs),
            },
        }

        await store.update_report_fields(report_id, {
            "status": "ready",
            "node_count": parsed.get("raw_node_count", 0),
            "version": overview.get("version"),
            "health_score": health_score,
            "recommendation_count": len(recs),
            "cluster_risk_score": cluster_risk_score,
            "deployment_method": deployment_method,
            "deployment_confidence": deployment_confidence,
            "deployment_signals": ",".join(deployment_signals) if isinstance(deployment_signals, list) else (deployment_signals if deployment_signals else None),
            "progress_json": json.dumps(update_doc["progress"]),
        })
        if isinstance(store, LocalReportStore):
            meta = await store.get_report_fields(report_id, fields=["report_name", "uploaded_at", "file_size", "detected_format"])
            payload = dict(update_doc)
            payload["id"] = report_id
            payload["report_name"] = meta.get("report_name") if meta else ""
            payload["uploaded_at"] = meta.get("uploaded_at") if meta else datetime.now(timezone.utc).isoformat()
            payload["file_size"] = meta.get("file_size") if meta else None
            payload["detected_format"] = meta.get("detected_format") if meta else payload.get("detected_format")
            await store.write_report_payload(report_id, payload)

        duration_ms = (time.time() - start_time) * 1000
        record_parsing_duration(report_id, duration_ms, "success")
        metrics.gauge("parsing.last_duration_ms", duration_ms)
        version_text = str(overview.get("version") or "")
        version_match = re.search(r"(\d+)", version_text)
        telemetry.record("parse_complete", {
            "duration_ms": int(duration_ms),
            "checker_ids": [row.get("checker_id", "") for row in recs[:20]],
            "input_mode": parsed.get("input_mode", "bundle"),
            "engine_major": int(version_match.group(1)) if version_match else None,
            "node_count": parsed.get("raw_node_count", 0),
            "status": "success",
        })

        logger.info(f"Report {report_id} parsed: {parsed.get('raw_node_count', 0)} nodes, {len(logs)} logs, {len(recs)} recs in {duration_ms:.0f}ms")

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        record_parsing_duration(report_id, duration_ms, "error")
        stored_error = "Report parsing failed" if anonymize else str(e)
        if anonymize:
            logger.error(
                "Parsing failed for anonymized report %s (%s)",
                report_id,
                type(e).__name__,
            )
        else:
            logger.error(f"Parsing failed for {report_id}: {e}", exc_info=True)
        log_anomaly(
            "parsing_failure",
            AlertSeverity.ERROR,
            {"report_id": report_id, "error": stored_error},
        )

        await store.update_report_fields(report_id, {
            "status": "error",
            "error": stored_error,
            "progress_json": json.dumps(
                {"stage": "failed", "pct": 0, "message": stored_error}
            ),
        })
    finally:
        # Only delete temp upload files under UPLOAD_DIR — never user-provided import paths.
        if remove_source_after_parse:
            try:
                src = Path(archive_path).resolve()
                if src.is_file() and src.parent.resolve() == UPLOAD_DIR.resolve():
                    src.unlink(missing_ok=True)
            except Exception:
                pass


@api_router.get("/reports")
async def list_reports():
    rows = await store.list_reports(limit=100)
    if isinstance(store, LocalReportStore):
        for row in rows:
            if row.get("status") != "ready":
                row["diagnostics_ready"] = False
                continue
            try:
                payload = await store.read_report_payload(row["id"])
                dx = (payload or {}).get("extended_diagnostics") or {}
                row["diagnostics_ready"] = _primary_diagnostics_populated(dx)
            except Exception:
                row["diagnostics_ready"] = False
    return rows


@api_router.get("/reports/{report_id}/status")
async def get_report_status(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        record_validation_failure("report_id", {"report_id": report_id})
        raise HTTPException(400, e.message)

    logger.info(f"Fetching status for report {report_id}")
    doc = await store.get_report_fields(report_id, fields=["id", "status", "error", "progress_json", "deployment_method", "deployment_confidence", "deployment_signals", "detected_format", "file_size"])
    if not doc:
        logger.warning(f"Report {report_id} not found in database")
        raise HTTPException(404, "Report not found")
    
    logger.info(f"Report {report_id} status: {doc.get('status')}")
    progress_json = doc.get("progress_json")
    progress = None
    if progress_json:
        try:
            progress = json.loads(progress_json)
        except Exception as e:
            logger.error(f"Failed to parse progress_json for {report_id}: {e}")
    return {
        "id": report_id,
        "status": doc.get("status"),
        "error": doc.get("error"),
        "progress": progress,
        "detected_format": doc.get("detected_format"),
        "file_size": doc.get("file_size"),
        "deployment_method": doc.get("deployment_method"),
        "deployment_confidence": doc.get("deployment_confidence"),
        "deployment_signals": doc.get("deployment_signals"),
    }


@api_router.get("/reports/{report_id}/overview")
async def get_report_overview(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        record_validation_failure("report_id", {"report_id": report_id})
        raise HTTPException(400, e.message)

    logger.info(f"Fetching overview for report {report_id}")

    if not isinstance(store, LocalReportStore):
        logger.warning("Overview endpoint called with non-LocalReportStore")
        raise HTTPException(501, "Overview endpoint is only supported in local storage mode")
    
    payload = await _load_payload(report_id)
    logger.info("Report payload loaded for %s, extracting overview data", report_id)

    dx = payload.get("extended_diagnostics") or {}
    hydrated = False
    source_path = None
    if not _primary_diagnostics_populated(dx):
        all_logs = await _load_logs_for_hydration(report_id)
        extracted_root = await store.get_extracted_path(report_id)
        import_source = (payload.get("import_source_path") or "").strip()
        source_path = extracted_root or import_source or None
        dx = hydrate_extended_diagnostics(
            payload,
            all_logs=all_logs,
            source_path=source_path,
            report_name=payload.get("report_name"),
        )
        hydrated = _primary_diagnostics_populated(dx)
        if hydrated or dx != (payload.get("extended_diagnostics") or {}):
            payload["extended_diagnostics"] = dx
            if not payload.get("collector_availability") and dx.get("collector_availability"):
                payload["collector_availability"] = dx["collector_availability"]
            await store.write_report_payload(report_id, payload)

    result = {
        "cluster_overview": payload.get("cluster_overview", {}),
        "recommendations": payload.get("recommendations", []),
        "events": payload.get("events", []),
        "report_name": payload.get("report_name"),
        "uploaded_at": payload.get("uploaded_at"),
        "status": payload.get("status"),
        "health_score": payload.get("health_score"),
        "cluster_risk_score": payload.get("cluster_risk_score"),
        "node_count": payload.get("node_count", payload.get("raw_node_count", 0)),
        "version": payload.get("version"),
        "log_summary": payload.get("log_summary", {}),
        "database_disk_usage": resolve_database_disk_usage(payload),
        "availability_groups": payload.get("availability_groups", []),
        "version_history": payload.get("version_history", []),
        "detected_log_patterns": payload.get("detected_log_patterns", []),
        "dmesg_events": payload.get("dmesg_events", []),
        "detected_format": payload.get("detected_format"),
        "file_size": payload.get("file_size"),
        "deployment_method": payload.get("deployment_method"),
        "deployment_confidence": payload.get("deployment_confidence"),
        "deployment_signals": payload.get("deployment_signals"),
        "log_count": payload.get("log_count", 0),
        "progress": payload.get("progress", {}),
        "cluster_layout": payload.get("cluster_layout", {}),
        "log_timeframe": payload.get("log_timeframe", {}),
        "backup_summary": payload.get("backup_summary", {}),
        "backup_history": _as_row_list(payload.get("backup_history")),
        "pressure_events_per_hour": payload.get("pressure_events_per_hour", {}),
        "memory_utilization": resolve_memory_utilization(payload),
        "process_health": payload.get("process_health", {}),
        "query_patterns": payload.get("query_patterns", {}),
        "replication_lag_patterns": payload.get("replication_lag_patterns", {}),
        "replication_status": payload.get("replication_status", []),
        "long_running_transactions": payload.get("long_running_transactions", {}),
        "node_events": payload.get("node_events", []),
        "rebalance_events": payload.get("rebalance_events", {}),
        "incident_clusters": resolve_incident_clusters(payload),
        "extended_diagnostics": dx,
        "collector_availability": payload.get("collector_availability") or dx.get("collector_availability") or {},
        "diagnostics_ready": _primary_diagnostics_populated(dx),
    }
    logger.info("Overview data prepared for %s: node_count=%s, health_score=%s", report_id, result.get('node_count'), result.get('health_score'))
    return result


@api_router.post("/reports/{report_id}/rehydrate-diagnostics")
async def rehydrate_report_diagnostics(report_id: str, request: Request):
    """Re-build MV_EVENTS / CPU / network diagnostics from a bundle path."""
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        record_validation_failure("report_id", {"report_id": report_id})
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Rehydrate is only supported in local storage mode")

    try:
        body = await request.json()
    except Exception:
        body = {}
    resolved = _resolve_allowed_import_path((body.get("path") or "").strip())

    payload = await _load_payload(report_id)
    source = str(resolved)
    is_anonymized = bool((payload.get("privacy") or {}).get("anonymized"))
    if not is_anonymized:
        payload["import_source_path"] = source
    all_logs = await _load_logs_for_hydration(report_id)
    dx = hydrate_extended_diagnostics(
        payload,
        all_logs=all_logs,
        source_path=source,
        report_name=payload.get("report_name"),
    )
    payload["extended_diagnostics"] = dx
    if dx.get("collector_availability"):
        payload["collector_availability"] = dx["collector_availability"]
    if is_anonymized:
        payload, _privacy_manifest = anonymize_report(payload)
        payload.pop("import_source_path", None)
        dx = payload["extended_diagnostics"]
    await store.write_report_payload(report_id, payload)

    return {
        "diagnostics_ready": _primary_diagnostics_populated(dx),
        "import_source_path": None if is_anonymized else source,
        "extended_diagnostics": dx,
    }


@api_router.get("/reports/{report_id}/triage")
async def get_report_triage(report_id: str):
    """Triage view: prioritized action list derived from superchecker findings.

    Returns:
      - quick_wins:   low-effort, warning/critical findings (do these first)
      - act_now:      priority-1 findings (critical / data-at-risk / outage-risk)
      - act_soon:     priority-2 findings (warnings, medium effort)
      - backlog:      priority-3 findings (informational)
      - incident_clusters: grouped findings with root-cause candidates
      - summary:      counts + estimated total effort
    """
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        record_validation_failure("report_id", {"report_id": report_id})
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Triage endpoint is only supported in local storage mode")

    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")

    recs = payload.get("recommendations", []) or []
    clusters = resolve_incident_clusters(payload)

    quick_wins = []
    act_now = []
    act_soon = []
    backlog = []

    for rec in recs:
        triage = rec.get("triage", {}) or {}
        priority = triage.get("priority", 3)
        entry = {
            "id": rec.get("id"),
            "checker_id": rec.get("checker_id"),
            "severity": rec.get("severity"),
            "category": rec.get("category"),
            "title": rec.get("title"),
            "impact": triage.get("impact", ""),
            "effort": triage.get("effort", ""),
            "blast_radius": triage.get("blast_radius", ""),
            "quick_win": triage.get("quick_win", False),
            "priority": priority,
            "recommended_action": triage.get("recommended_action", ""),
            "risk_score": rec.get("risk_score", 0),
            "cluster_id": triage.get("cluster_id"),
            "nodes": rec.get("nodes", []),
        }
        if priority == 1:
            act_now.append(entry)
        elif triage.get("quick_win"):
            quick_wins.append(entry)
        elif priority == 2:
            act_soon.append(entry)
        else:
            backlog.append(entry)

    # Sort each bucket by risk_score descending
    for bucket in (quick_wins, act_now, act_soon, backlog):
        bucket.sort(key=lambda x: -x.get("risk_score", 0))

    effort_counts = {"low": 0, "medium": 0, "high": 0}
    for rec in recs:
        effort_val = (rec.get("triage", {}) or {}).get("effort", "medium")
        effort_counts[effort_val] = effort_counts.get(effort_val, 0) + 1

    return {
        "report_id": report_id,
        "report_name": payload.get("report_name"),
        "health_score": payload.get("health_score"),
        "summary": {
            "total_findings": len(recs),
            "quick_wins": len(quick_wins),
            "act_now": len(act_now),
            "act_soon": len(act_soon),
            "backlog": len(backlog),
            "incident_clusters": len(clusters),
            "effort_breakdown": effort_counts,
        },
        "quick_wins": quick_wins,
        "act_now": act_now,
        "act_soon": act_soon,
        "backlog": backlog,
        "incident_clusters": clusters,
    }


@api_router.get("/reports/{report_id}/nodes")
async def get_report_nodes(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Nodes endpoint is only supported in local storage mode")
    payload = await _load_payload(report_id)
    overview = payload.get("cluster_overview", {}) or {}
    return {"nodes": payload.get("nodes", []), "cluster_overview": {"nodes_detail": overview.get("nodes_detail", [])}}


@api_router.get("/reports/{report_id}/storage")
async def get_report_storage(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Storage endpoint is only supported in local storage mode")
    payload = await _load_payload(report_id)
    return {
        "databases": payload.get("databases", []),
        "storage": payload.get("storage", []),
        "database_disk_usage": resolve_database_disk_usage(payload),
        "partitions": payload.get("partitions", {}),
    }


@api_router.get("/reports/{report_id}/queries")
async def get_report_queries(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Queries endpoint is only supported in local storage mode")
    payload = await _load_payload(report_id)
    overview = payload.get("cluster_overview", {}) or {}
    return {
        "queries": payload.get("queries", []),
        "workload_management": payload.get("workload_management", []),
        "resource_pools": payload.get("resource_pools", []),
        "alloc_memory": payload.get("alloc_memory", {}),
        "cluster_overview": {
            "blocked_queries": overview.get("blocked_queries", []),
            "processlist": overview.get("processlist", []),
            "mv_processlist": overview.get("mv_processlist", []),
        },
        "query_analysis": payload.get("query_analysis", {}),
    }


@api_router.get("/reports/{report_id}/query-traces")
async def get_report_query_traces(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Query traces endpoint is only supported in local storage mode")

    payload = await _load_payload(report_id)
    candidates = list_query_trace_candidates(payload)
    return {
        "traces": candidates,
        "total": len(candidates),
    }


@api_router.get("/reports/{report_id}/query-traces/{trace_id}")
async def get_report_query_trace(report_id: str, trace_id: str):
    try:
        validate_report_id(report_id)
        validate_trace_id(trace_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Query traces endpoint is only supported in local storage mode")

    payload = await _load_payload(report_id)
    extracted_root = await store.get_extracted_path(report_id)
    trace = get_query_trace_by_id(payload, trace_id, extracted_root=extracted_root)
    if not trace:
        raise HTTPException(404, {"error": "trace_not_found", "message": "No trace matches trace_id"})
    return trace


@api_router.post("/reports/{report_id}/query-traces/resolve")
async def resolve_report_query_trace(report_id: str, request: Request):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Query traces endpoint is only supported in local storage mode")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, {"error": "invalid_json", "message": "Request body must be valid JSON"})

    try:
        selector = validate_query_trace_selector(body if isinstance(body, dict) else None)
    except ValidationError as e:
        raise HTTPException(400, {"error": e.code, "message": e.message, "field": e.field})

    payload = await _load_payload(report_id)
    extracted_root = await store.get_extracted_path(report_id)
    return resolve_query_trace(payload, selector, extracted_root=extracted_root)


@api_router.get("/reports/{report_id}/logs")
async def get_report_logs(
    report_id: str,
    search: str | None = Query(None),
    severity: str | None = Query(None),
    node: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=500),
):
    start_time = time.time()

    try:
        validate_report_id(report_id)
    except ValidationError as e:
        record_validation_failure("log_search", {"report_id": report_id})
        raise HTTPException(400, e.message)

    sanitized_search = validate_search_query(search)
    sanitized_severity = validate_severity_filter(severity)
    sanitized_node = validate_node_filter(node) if node else None
    page, page_size = validate_pagination(page, page_size, MAX_PAGE_SIZE)
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Logs endpoint is only supported in local storage mode")
    logs, total = await store.query_report_logs(
        report_id=report_id,
        search=sanitized_search,
        severities=sanitized_severity,
        node_prefix=sanitized_node,
        page=page,
        page_size=page_size,
    )
    try:
        payload = await store.read_report_payload(report_id)
    except ValueError:
        payload = None
    log_summary = payload.get("log_summary", {}) if payload else {}
    duration_ms = (time.time() - start_time) * 1000
    perf.record_request("/reports/{id}/logs", duration_ms, 200)
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "log_summary": log_summary,
    }


@api_router.get("/reports/{report_id}/logs/search")
async def search_report_logs_raw(
    report_id: str,
    keyword: str = Query(..., min_length=1, max_length=500),
    regex: bool = Query(False),
    severity: str | None = Query(None),
    node: str | None = Query(None),
    case_sensitive: bool = Query(False),
    max_results: int = Query(200, ge=1, le=2000),
):
    """
    Ripgrep-style search across ALL parsed tracelogs.
    Searches across all nodes' logs with keyword/regex, severity filter, and context.
    """
    start_time = time.time()

    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Log search is only supported in local storage mode")

    # Validate the regex up front so an invalid pattern 400s regardless of path.
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        re.compile(keyword if regex else re.escape(keyword), flags)
    except re.error:
        raise HTTPException(400, {"error": "invalid_regex", "message": "Invalid regex pattern"})

    # Prefer raw search over the persisted extracted report root: it scans the
    # full tracelogs (compressed + uncompressed) and returns context windows.
    # Falls back to the parsed-log storage search when no extracted root was
    # kept on disk (e.g. over the 2 GB persist cap or directory imports).
    extracted_root = await store.get_extracted_path(report_id)
    loop = asyncio.get_running_loop()

    if extracted_root:
        try:
            raw = await loop.run_in_executor(
                None,
                lambda: search_all_trace_logs(
                    extracted_root, keyword,
                    regex=regex, severity=severity,
                    case_sensitive=case_sensitive,
                    max_results=max_results,
                    context_lines=2,
                    node_filter=node,
                ),
            )
        except re.error:
            raise HTTPException(400, {"error": "invalid_regex", "message": "Invalid regex pattern"})
        duration_ms = (time.time() - start_time) * 1000
        perf.record_request("/reports/{id}/logs/search", duration_ms, 200)
        return {
            "matches": raw.get("matches", []),
            "total": raw.get("total", 0),
            "nodes_searched": raw.get("nodes_searched", 0),
            "truncated": raw.get("truncated", False),
            "search_mode": "raw",
            "search_params": {
                "keyword": keyword,
                "regex": regex,
                "severity": severity,
                "case_sensitive": case_sensitive,
            },
        }

    # Fallback: parsed-log storage search (no context windows).
    sev_list: list[str] | None = None
    if severity and severity.upper() != "ALL":
        sev = severity.strip().lower()
        if sev == "warning":
            sev = "warn"
        sev_list = [sev]

    try:
        matches, total, truncated = await store.search_report_logs(
            report_id=report_id,
            keyword=keyword,
            regex=regex,
            case_sensitive=case_sensitive,
            severities=sev_list,
            node_prefix=node,
            limit=max_results,
        )
    except ValueError as exc:
        if str(exc) == "invalid_regex":
            raise HTTPException(400, {"error": "invalid_regex", "message": "Invalid regex pattern"})
        raise

    # nodes_searched = distinct nodes that actually contributed matches, not the
    # total cluster node count.
    nodes_with_matches = {m.get("hostname") for m in matches if m.get("hostname")}
    nodes_searched = len(nodes_with_matches)

    duration_ms = (time.time() - start_time) * 1000
    perf.record_request("/reports/{id}/logs/search", duration_ms, 200)

    return {
        "matches": matches,
        "total": total,
        "nodes_searched": nodes_searched,
        "truncated": truncated,
        "search_mode": "parsed",
        "search_params": {
            "keyword": keyword,
            "regex": regex,
            "severity": severity,
            "case_sensitive": case_sensitive,
        },
    }


@api_router.get("/reports/{report_id}/pipelines")
async def get_report_pipelines(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Pipelines endpoint is only supported in local storage mode")
    payload = await _load_payload(report_id)
    return {"pipelines": payload.get("pipelines", [])}


@api_router.get("/reports/{report_id}/recommendations")
async def get_report_recommendations(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Recommendations endpoint is only supported in local storage mode")
    payload = await _load_payload(report_id)
    recs = payload.get("recommendations", []) or []
    # Attach a derived (never persisted) log-search hint per finding so the UI
    # can deep-link "View in Logs" straight to the evidence in memsql.log.
    enriched = []
    for rec in recs:
        rec = dict(rec) if isinstance(rec, dict) else rec
        if isinstance(rec, dict):
            rec["log_search"] = resolve_finding_log_search_terms(rec)
        enriched.append(rec)
    return {"recommendations": enriched}


@api_router.get("/reports/{report_id}/config")
async def get_report_config(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Config endpoint is only supported in local storage mode")
    payload = await _load_payload(report_id)
    nodes = payload.get("nodes", []) or []
    trimmed_nodes = []
    for n in nodes:
        trimmed_nodes.append({
            "hostname": n.get("hostname"),
            "role": n.get("role"),
            "show_variables": n.get("show_variables"),
            "os_checks": n.get("os_checks"),
            "config": {"process_limits": (n.get("config", {}) or {}).get("process_limits")},
            "license": n.get("license"),
        })
    return {
        "config_health": payload.get("config_health", {}),
        "backup_history": _as_row_list(payload.get("backup_history")),
        "users": payload.get("users", []),
        "version_history": payload.get("version_history", []),
        "nodes": trimmed_nodes,
    }


@api_router.delete("/reports/{report_id}")
async def delete_report(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        record_validation_failure("delete", {"report_id": report_id})
        raise HTTPException(400, e.message)

    deleted = await store.delete_report(report_id)
    if not deleted:
        raise HTTPException(404, "Report not found")

    audit.log(action="report_delete", resource="report", resource_id=report_id, result="success")
    return {"message": "Report deleted"}


@api_router.get("/reports/diff")
async def diff_reports(from_id: str = Query(...), to_id: str = Query(...)):
    try:
        validate_report_id(from_id)
        validate_report_id(to_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Diff endpoint is only supported in local storage mode")
    from_payload = await _load_payload(from_id)
    to_payload = await _load_payload(to_id)
    return compare_reports(from_payload, to_payload)


@api_router.get("/reports/{report_id}")
async def get_report(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Full report endpoint is only supported in local storage mode")
    payload = await _load_payload(report_id)
    return payload


@api_router.get("/health/deep")
async def deep_health_check():
    # Verify DB connectivity
    db_status = "ok"
    try:
        status = await store.ping()
        if not status.ok:
            db_status = "error"
    except Exception:
        db_status = "error"
        
    # Verify S3 connectivity if configured
    s3_status = "not_configured"
    if os.getenv("S3_BUCKET_NAME"):
        try:
            from s3_client import get_s3_client
            client = get_s3_client()
            client.head_bucket(Bucket=os.getenv("S3_BUCKET_NAME"))
            s3_status = "ok"
        except Exception:
            s3_status = "error"

    overall = "healthy" if db_status == "ok" and s3_status in ("ok", "not_configured") else "unhealthy"
    return {"status": overall, "db": db_status, "s3": s3_status}

@api_router.get("/health")
async def health_check():
    health_result = health_service.run_all_checks()
    return {
        "status": "healthy" if health_result["healthy"] else "degraded",
        "storage": (await store.ping()).ok,
        "checks": health_result,
        "metrics": metrics.get_all_metrics(),
    }


@api_router.post("/shutdown")
async def shutdown_server(request: Request):
    """Graceful shutdown hook for the desktop shell (localhost only)."""
    if not _is_loopback_client(request):
        record_security_event("shutdown_denied", {"client": getattr(request.client, "host", "unknown")})
        raise HTTPException(403, {"error": "forbidden", "message": "Shutdown is only allowed from localhost"})

    logger.info("Graceful shutdown requested from %s", request.client.host if request.client else "unknown")

    async def _signal_exit() -> None:
        await asyncio.sleep(0.1)
        os.kill(os.getpid(), signal.SIGTERM)

    _track_background_task(_signal_exit())
    return {"status": "shutting_down"}


@api_router.get("/alerts")
async def get_alerts_endpoint():
    alert_summary = alerts.get_alert_summary()
    return {
        "summary": alert_summary,
        "active_alerts": [a.to_dict() for a in alerts.get_active_alerts()],
    }


@api_router.get("/metrics/performance")
async def get_performance_metrics():
    return perf.get_stats()


@api_router.get("/hostinger/vps/virtual-machines")
async def hostinger_list_virtual_machines(page: int = Query(1)):
    _require_cloud_extensions()
    import httpx
    token = os.environ.get("HOSTINGER_API_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "Hostinger API not configured (HOSTINGER_API_TOKEN missing)")

    if page < 1:
        raise HTTPException(400, "page must be >= 1")

    url = "https://api.hostinger.com/api/vps/v1/virtual-machines"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers, params={"page": page})
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except Exception:
                payload = {"error": resp.text[:500]}
                
            if resp.status_code in (401, 403):
                raise HTTPException(401, {"status": resp.status_code, "error": "Unauthorized", "message": "Hostinger API token is missing, invalid, or expired. Please check your configuration."})
            elif resp.status_code == 429:
                raise HTTPException(429, {"status": resp.status_code, "error": "Too Many Requests", "message": "Hostinger API rate limit exceeded. Please try again later."})
            else:
                raise HTTPException(502, {"status": resp.status_code, "error": "Bad Gateway", "message": f"Hostinger API returned an error: {payload.get('message', 'Unknown error')}"})
                
        return resp.json()
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(504, {"error": "Gateway Timeout", "message": "Hostinger API request timed out."})
    except Exception as e:
        raise HTTPException(502, {"error": "Bad Gateway", "message": f"Hostinger API error: {str(e)[:200]}"})


@api_router.get("/settings/telemetry")
async def get_telemetry_settings():
    return telemetry.get_settings()


@api_router.put("/settings/telemetry")
async def update_telemetry_settings(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if "enabled" not in body or not isinstance(body.get("enabled"), bool):
        raise HTTPException(400, {"error": "enabled must be a boolean"})
    settings = telemetry.update_settings(enabled=body["enabled"])
    audit.log(
        action="telemetry_settings_update",
        resource="settings",
        resource_id="telemetry",
        result="success",
        details={"enabled": settings["enabled"], "external_delivery": False},
    )
    return settings


@api_router.get("/settings/telemetry/events")
async def get_local_telemetry_events(limit: int = Query(100, ge=1, le=1000)):
    """Inspect local allowlisted events. Nothing is uploaded externally."""
    return {"events": telemetry.read_events(limit), "external_delivery": False}


@api_router.get("/")
async def root():
    return {
        "message": "SingleStore Report Sniffer v1 API",
        "version": "1.0.0",
        "status": "ok",
        "docs": "/api/docs",
    }


@api_router.get("/reports/{report_id}/export/slack")
async def export_slack(report_id: str):
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Export endpoint is only supported in local storage mode")
    doc = await _load_payload(report_id)
    recs = doc.get("recommendations", []) or []
    top = sorted(recs, key=lambda r: ({"critical": 0, "warning": 1, "info": 2}.get(r.get("severity","info"),2), -int(r.get("risk_score",0))))[:8]
    lines = [f"- [{r.get('severity','info').upper()} | Risk {r.get('risk_score',0)} | Conf {int(float(r.get('confidence',0))*100)}%] {r.get('title','')}" for r in top]
    summary = {
        "title": f"Report {doc.get('report_name','')} — Health {doc.get('health_score','')} Risk {doc.get('cluster_risk_score',0)}",
        "uploaded_at": doc.get("uploaded_at",""),
        "top_findings": lines,
        "counts": {
            "critical": sum(1 for r in recs if r.get("severity")=="critical"),
            "warning": sum(1 for r in recs if r.get("severity")=="warning"),
            "info": sum(1 for r in recs if r.get("severity")=="info"),
        }
    }
    return summary


@api_router.get("/reports/{report_id}/export/markdown")
async def export_markdown(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as exc:
        raise HTTPException(400, exc.message)
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Export endpoint is only supported in local storage mode")
    doc = await _load_payload(report_id)
    content = build_markdown_export(doc)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="s2-report-{report_id}.md"'},
    )


@api_router.get("/reports/{report_id}/export/html")
async def export_html(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as exc:
        raise HTTPException(400, exc.message)
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Export endpoint is only supported in local storage mode")
    doc = await _load_payload(report_id)
    html_doc = build_portable_html(doc)
    return Response(
        content=html_doc,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="s2-report-{report_id}.html"'},
    )


@api_router.get("/reports/{report_id}/export/glean")
async def export_glean_packet(report_id: str):
    """Return a whole-report Markdown incident packet for Glean Chat handoff."""
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Export endpoint is only supported in local storage mode")
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)
    doc = await _load_payload(report_id)
    packet = build_glean_packet(doc, report_id=report_id)
    return JSONResponse(content=packet)


app.include_router(api_router)

_ui_dir = os.environ.get("S2RS_UI_DIR")
if _ui_dir:
    ui_path = Path(_ui_dir).expanduser().resolve()
else:
    ui_path = (ROOT_DIR.parent / "frontend" / "build").resolve()
if ui_path.exists() and ui_path.is_dir():
    static_dir = ui_path / "static"
    if static_dir.exists() and static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static")
        app.mount("/ui/static", StaticFiles(directory=str(static_dir), html=False), name="ui-static")


@app.get("/ui/")
async def ui_index():
    if not (ui_path.exists() and ui_path.is_dir()):
        raise HTTPException(404, "UI build not found")
    index_file = ui_path / "index.html"
    if not index_file.exists():
        raise HTTPException(404, "UI entrypoint not found")
    return FileResponse(str(index_file), media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/ui/{path:path}")
async def ui_spa(path: str):
    if not (ui_path.exists() and ui_path.is_dir()):
        raise HTTPException(404, "UI build not found")

    if ".." in path or path.startswith("/"):
        raise HTTPException(404, "Not found")

    safe_path = ui_path / path
    try:
        real_path = safe_path.resolve()
    except Exception:
        raise HTTPException(404, "Not found")

    try:
        real_path.relative_to(ui_path.resolve())
    except ValueError:
        raise HTTPException(404, "Not found")

    if real_path.exists() and real_path.is_file():
        return FileResponse(str(real_path), headers={"Cache-Control": "no-store"})

    index_file = ui_path / "index.html"
    return FileResponse(str(index_file), media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/")
async def ui_redirect():
    if ui_path.exists() and ui_path.is_dir():
        return RedirectResponse(url="/ui/")
    return {"message": "SingleStore Report Sniffer v1 API", "docs": "/api/docs"}


@app.get("/@vite/client")
async def vite_client_stub():
    return Response(status_code=204)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=_get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(_RateLimitMiddleware)
app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(_NoCacheUiStaticMiddleware)
if os.environ.get("S2RS_DISABLE_GZIP", "").strip().lower() not in {"1", "true", "yes", "y"}:
    app.add_middleware(GZipMiddleware, minimum_size=1000)


def _log_routes(app: FastAPI) -> None:
    try:
        items: list[tuple[str, str, str]] = []
        for r in getattr(app, "routes", []) or []:
            methods = sorted(m for m in (getattr(r, "methods", None) or set()) if m)
            path = getattr(r, "path", None)
            name = getattr(r, "name", None)
            if not path:
                continue
            items.append(("|".join(methods) if methods else "", path, name or ""))

        items.sort(key=lambda x: (x[1], x[0]))
        logger.info("Registered routes (%d)", len(items))
        for item in items:
            methods_str, path, name = item
            if methods_str:
                logger.info("%s %s %s", methods_str, path, name)
            else:
                logger.info("%s %s", path, name)
    except Exception:
        logger.exception("Failed to list routes")
