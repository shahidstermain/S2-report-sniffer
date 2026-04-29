from fastapi import FastAPI, APIRouter, UploadFile, File, Query, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from fastapi.responses import FileResponse
import gzip
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import os
import logging
from pythonjsonlogger import jsonlogger

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Only add handler if not already present to avoid duplicates
if not logger.handlers:
    logHandler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)

import tempfile
import shutil
from pathlib import Path
from typing import Optional
import uuid
from datetime import datetime, timezone
import asyncio
import aiofiles
import time
from pydantic import BaseModel
import tarfile
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

app = FastAPI(
    title="SingleStore Report Sniffer v1",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
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

from parsers import parse_report_archive_streaming, parse_report_directory, infer_deployment_method, _normalize_archive_exception
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
    AlertCategory,
    record_parsing_duration,
    record_validation_failure,
    record_security_event,
    record_upload_attempt,
    record_upload_complete,
    log_anomaly,
)
from storage import build_store, LocalReportStore
from glean_mcp import GleanMCPClient, GleanConfigManager

UPLOAD_DIR = Path(tempfile.gettempdir()) / "sdb_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024 * 1024

metrics = get_metrics()
alerts = get_alerts()
audit = get_audit()
health_service = get_health()
perf = get_performance()
store = build_store()
logger.info(f"Storage base_dir={getattr(store, 'base_dir', None)} db_path={getattr(store, 'db_path', None)}")


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
        await store.update_report_fields(report_id, {"progress_json": __import__("json").dumps(progress)})
    except Exception as e:
        logger.warning(f"Failed to update progress for {report_id}: {e}")


@api_router.post("/reports/upload")
async def upload_report(
    file: UploadFile | None = File(None),
    report: UploadFile | None = File(None),
    request: Request = None,
):
    start_time = time.time()

    client_ip = request.client.host if request and request.client else "unknown"

    active_file = file or report
    if active_file is None:
        raise HTTPException(400, {
            "error": "No file uploaded",
            "message": "Send the file as multipart form-data field named 'file' (preferred) or 'report'.",
        })

    upload_id = record_upload_attempt(active_file.filename, 0, client_ip)

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
    else:
        raise HTTPException(400, {
            "error": "Unsupported file type",
            "message": "Accepted formats: .zip, .tar.gz, .tgz, .tar, .gz",
            "filename": filename,
        })

    is_valid, sanitized_name = validate_filename(filename)
    if not is_valid:
        record_validation_failure("filename", {"filename": file.filename})
        record_security_event("invalid_filename", {"filename": file.filename, "ip": client_ip})
        raise HTTPException(400, {
            "error": "Invalid filename",
            "message": sanitized_name,
            "filename": file.filename
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
                    with gzip.open(tmp_path, "rb") as src, tempfile.NamedTemporaryFile(suffix=".tar") as expanded:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            expanded.write(chunk)
                        expanded.flush()
                        with tarfile.open(expanded.name, "r:") as tf:
                            for _member in tf:
                                pass
                elif detected_format == "tar":
                    with tarfile.open(tmp_path, "r:") as tf:
                        for _member in tf:
                            pass
                else:
                    with gzip.open(tmp_path, "rb") as gf:
                        while gf.read(1024 * 1024):
                            pass
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
        record_upload_complete(report_id, active_file.filename, upload_duration, "success")

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
        await store.create_report_stub(report_id, sanitized_name, file_size, detected_format)
        await store.update_report_fields(report_id, {"progress_json": __import__("json").dumps(report_doc["progress"])})

        asyncio.create_task(_parse_report_background(report_id, str(tmp_path), file_size))

        audit.log(
            action="report_upload",
            resource="report",
            resource_id=report_id,
            actor="anonymous",
            result="success",
            details={"filename": sanitized_name, "size": file_size, "duration_ms": upload_duration},
            ip_address=client_ip,
        )

        return {
            "id": report_id,
            "status": "processing",
            "file_size": file_size,
            "detected_format": detected_format,
            "message": "Report uploaded and queued for processing",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        record_upload_complete(report_id, active_file.filename, (time.time() - start_time) * 1000, "error")
        record_security_event("upload_error", {"error": str(e), "ip": client_ip})
        
        error_detail = {
            "error": "Upload failed",
            "message": str(e),
            "report_id": report_id if 'report_id' in locals() else None,
            "filename": active_file.filename if active_file and active_file.filename else "unknown"
        }
        raise HTTPException(500, error_detail)


@api_router.options("/reports/upload")
async def upload_report_options():
    return Response(status_code=204)


class LocalImportRequest(BaseModel):
    path: str


@api_router.post("/reports/import")
async def import_report(payload: LocalImportRequest, request: Request = None):
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, {"error": "Local import is not supported by this storage backend"})

    raw_path = (payload.path or "").strip()
    if not raw_path:
        raise HTTPException(400, {"error": "Invalid path", "message": "Path is required"})
    if len(raw_path) > 4096:
        raise HTTPException(400, {"error": "Invalid path", "message": "Path too long"})

    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p)
    try:
        resolved = p.resolve()
    except Exception:
        resolved = p.absolute()

    if not resolved.exists():
        raise HTTPException(404, {"error": "Path not found", "path": str(resolved)})

    import os

    if resolved.is_dir():
        if not (os.access(resolved, os.R_OK) and os.access(resolved, os.X_OK)):
            raise HTTPException(403, {"error": "Permission denied", "message": "Directory is not readable", "path": str(resolved)})
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
        if not os.access(resolved, os.R_OK):
            raise HTTPException(403, {"error": "Permission denied", "message": "File is not readable", "path": str(resolved)})
        lower_name = resolved.name.lower()
        if lower_name.endswith(".zip"):
            detected_format = "zip"
        elif lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz"):
            detected_format = "tar.gz"
        elif lower_name.endswith(".tar"):
            detected_format = "tar"
        elif lower_name.endswith(".gz"):
            detected_format = "gz"
        else:
            raise HTTPException(400, {
                "error": "Unsupported file type",
                "message": "Accepted formats: .zip, .tar.gz, .tgz, .tar, .gz, or a directory",
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

    await store.create_report_stub(report_id, report_name, file_size, detected_format)
    await store.update_report_fields(report_id, {"progress_json": __import__("json").dumps({
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
        details={"path": str(resolved), "detected_format": detected_format, "size": file_size},
        ip_address=client_ip,
    )

    asyncio.create_task(_parse_report_background(report_id, str(resolved), file_size))

    return {
        "id": report_id,
        "status": "processing",
        "file_size": file_size,
        "detected_format": detected_format,
        "message": "Report import queued for processing",
    }


async def _parse_report_background(report_id: str, archive_path: str, file_size: int):
    start_time = time.time()
    loop = asyncio.get_event_loop()

    try:
        await _update_progress_safe(report_id, "extracting", 5, "Discovering report structure...", files_processed=0)

        progress_state = {"files": 0, "nodes": 0, "logs": 0}

        def progress_callback(stage, files=0, nodes=0, logs=0, message=""):
            progress_state["files"] += files
            progress_state["nodes"] = max(progress_state["nodes"], nodes)
            progress_state["logs"] += logs
            asyncio.run_coroutine_threadsafe(
                _update_progress_safe(report_id, stage,
                    min(90, 10 + (progress_state["files"] * 80 // max(progress_state["nodes"] * 50, 1))),
                    message or f"Parsing... {progress_state['files']} files, {progress_state['logs']} log lines",
                    nodes_discovered=progress_state["nodes"],
                    files_processed=progress_state["files"],
                    log_lines_indexed=progress_state["logs"],
                ),
                loop
            )

        import os

        if os.path.isdir(archive_path):
            parsed = await loop.run_in_executor(
                None, parse_report_directory, archive_path, os.path.basename(archive_path), progress_callback
            )
            parsed["detected_format"] = "directory"
        else:
            parsed = await loop.run_in_executor(
                None, parse_report_archive_streaming, archive_path, progress_callback
            )

        await _update_progress_safe(report_id, "analyzing", 90, "Running recommendations engine...")

        deployment = infer_deployment_method(parsed.get("nodes", []), parsed.get("cluster_overview", {}))
        deployment_method = deployment.get("method")
        deployment_confidence = deployment.get("confidence")
        deployment_signals = deployment.get("signals")

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

        update_doc = {
            "status": "ready",
            "parsed_at": parsed.get("parsed_at"),
            "detected_format": parsed.get("detected_format", "unknown"),
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
            "workload_management": parsed.get("workload_management", []),
            "replication_status": parsed.get("replication_status", []),
            "config_health": parsed.get("config_health", {}),
            "backup_history": parsed.get("backup_history", [])[-50:],
            "resource_pools": parsed.get("resource_pools", []),
            "database_disk_usage": parsed.get("database_disk_usage", []),
            "partitions": parsed.get("partitions", {}),
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
            "progress_json": __import__("json").dumps(update_doc["progress"]),
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

        logger.info(f"Report {report_id} parsed: {parsed.get('raw_node_count', 0)} nodes, {len(logs)} logs, {len(recs)} recs in {duration_ms:.0f}ms")

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        record_parsing_duration(report_id, duration_ms, "error")
        logger.error(f"Parsing failed for {report_id}: {e}", exc_info=True)
        log_anomaly("parsing_failure", AlertSeverity.ERROR, {"report_id": report_id, "error": str(e)})

        await store.update_report_fields(report_id, {
            "status": "error",
            "error": str(e),
            "progress_json": __import__("json").dumps({"stage": "failed", "pct": 0, "message": str(e)}),
        })
    finally:
        try:
            os.unlink(archive_path)
        except Exception:
            pass


@api_router.get("/reports")
async def list_reports():
    return await store.list_reports(limit=100)


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
            progress = __import__("json").loads(progress_json)
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
        logger.warning(f"Overview endpoint called with non-LocalReportStore")
        raise HTTPException(501, "Overview endpoint is only supported in local storage mode")
    
    payload = await store.read_report_payload(report_id)
    if not payload:
        logger.warning(f"Report payload not found for {report_id}")
        raise HTTPException(404, "Report not found")
    
    logger.info(f"Report payload loaded for {report_id}, extracting overview data")
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
        "database_disk_usage": payload.get("database_disk_usage", []),
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
    }
    logger.info(f"Overview data prepared for {report_id}: node_count={result.get('node_count')}, health_score={result.get('health_score')}")
    return result


@api_router.get("/reports/{report_id}/nodes")
async def get_report_nodes(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Nodes endpoint is only supported in local storage mode")
    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")
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
    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")
    return {
        "databases": payload.get("databases", []),
        "storage": payload.get("storage", []),
        "database_disk_usage": payload.get("database_disk_usage", []),
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
    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")
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
    }


@api_router.get("/reports/{report_id}/logs")
async def get_report_logs(
    report_id: str,
    search: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    node: Optional[str] = Query(None),
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
    payload = await store.read_report_payload(report_id)
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


@api_router.get("/reports/{report_id}/pipelines")
async def get_report_pipelines(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Pipelines endpoint is only supported in local storage mode")
    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")
    return {"pipelines": payload.get("pipelines", [])}


@api_router.get("/reports/{report_id}/recommendations")
async def get_report_recommendations(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Recommendations endpoint is only supported in local storage mode")
    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")
    return {"recommendations": payload.get("recommendations", [])}


@api_router.get("/reports/{report_id}/config")
async def get_report_config(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Config endpoint is only supported in local storage mode")
    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")
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
        "backup_history": payload.get("backup_history", []),
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


@api_router.get("/reports/{report_id}")
async def get_report(report_id: str):
    try:
        validate_report_id(report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)

    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Full report endpoint is only supported in local storage mode")
    payload = await store.read_report_payload(report_id)
    if not payload:
        raise HTTPException(404, "Report not found")
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


@api_router.get("/")
async def root():
    return {
        "message": "SingleStore Report Sniffer v1 API",
        "version": "1.0.0",
        "status": "ok",
        "docs": "/api/docs",
    }


@api_router.get("/reports/diff")
async def diff_reports(from_id: str = Query(...), to_id: str = Query(...)):
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Diff endpoint is only supported in local storage mode")
    from_payload = await store.read_report_payload(from_id)
    to_payload = await store.read_report_payload(to_id)
    if not from_payload or not to_payload:
        raise HTTPException(404, "Report(s) not found")
    from backend.superchecker import compute_diff  # type: ignore
    diff = compute_diff(from_payload.get("recommendations", []), to_payload.get("recommendations", []))
    return diff


@api_router.get("/reports/{report_id}/export/slack")
async def export_slack(report_id: str):
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Export endpoint is only supported in local storage mode")
    doc = await store.read_report_payload(report_id)
    if not doc:
        raise HTTPException(404, "Report not found")
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


@api_router.get("/reports/{report_id}/export/html")
async def export_html(report_id: str):
    if not isinstance(store, LocalReportStore):
        raise HTTPException(501, "Export endpoint is only supported in local storage mode")
    doc = await store.read_report_payload(report_id)
    if not doc:
        raise HTTPException(404, "Report not found")
    rows = []
    for r in doc.get("recommendations", [])[:100]:
        rows.append(f"<tr><td>{r.get('severity','')}</td><td>{r.get('risk_score','')}</td><td>{int(float(r.get('confidence',0))*100)}%</td><td>{r.get('title','')}</td></tr>")
    html = f"<html><head><title>Report {doc.get('report_name','')}</title></head><body><h1>Health {doc.get('health_score','')}</h1><h3>Risk {doc.get('cluster_risk_score',0)}</h3><table border='1'><tr><th>Severity</th><th>Risk</th><th>Conf</th><th>Title</th></tr>{''.join(rows)}</table></body></html>"
    return JSONResponse(content={"html": html})


# Glean MCP Integration Routes

class GleanConfigRequest(BaseModel):
    glean_url: str
    mcp_port: int = 3000
    enabled: bool = False


@api_router.get("/glean/config")
async def get_glean_config():
    """Get current Glean configuration."""
    config = GleanConfigManager.load_config()
    safe_config = {
        "glean_url": config.get("glean_url", ""),
        "mcp_port": config.get("mcp_port", 3000),
        "enabled": config.get("enabled", False)
    }
    return safe_config


@api_router.post("/glean/config")
async def save_glean_config(payload: GleanConfigRequest):
    """Save Glean configuration."""
    config = {
        "glean_url": payload.glean_url.strip(),
        "mcp_port": payload.mcp_port,
        "enabled": payload.enabled
    }
    
    # Validate URL format if provided
    if config["glean_url"] and not (config["glean_url"].startswith("http://") or config["glean_url"].startswith("https://")):
        raise HTTPException(400, {"error": "Invalid URL", "message": "Glean URL must start with http:// or https://"})
    
    # Validate port range
    if not (1 <= config["mcp_port"] <= 65535):
        raise HTTPException(400, {"error": "Invalid port", "message": "MCP port must be between 1 and 65535"})
    
    success = GleanConfigManager.save_config(config)
    if not success:
        raise HTTPException(500, {"error": "Failed to save config", "message": "Could not write configuration file"})
    
    audit.log(action="glean_config_update", resource="glean", resource_id="config", result="success", details={"enabled": config["enabled"]})
    return {"message": "Glean configuration saved"}


@api_router.post("/glean/health")
async def test_glean_connection():
    """Test connection to Glean MCP server."""
    client = GleanConfigManager.get_client()
    if not client:
        return {"status": "error", "message": "Glean not configured or enabled"}
    
    health_result = await client.health_check()
    return health_result


class GleanInsightsRequest(BaseModel):
    report_id: str
    report_summary: Optional[str] = None
    report_data: Optional[dict] = None


@api_router.post("/glean/insights")
async def fetch_glean_insights(payload: GleanInsightsRequest):
    """Fetch Glean insights for a report (legacy endpoint)."""
    try:
        validate_report_id(payload.report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)
    
    client = GleanConfigManager.get_client()
    if not client:
        return {"insights": [], "message": "Glean not configured or enabled"}
    
    # Build query from report data if provided
    if payload.report_data:
        query = client.build_query_from_report(payload.report_data)
    elif payload.report_summary:
        query = payload.report_summary
    else:
        # Fallback: fetch report data from storage
        if not isinstance(store, LocalReportStore):
            return {"insights": [], "message": "Report data required for insights"}
        doc = await store.read_report_payload(payload.report_id)
        if not doc:
            raise HTTPException(404, "Report not found")
        query = client.build_query_from_report(doc)
    
    # Fetch insights
    context = payload.report_data or {}
    insights = await client.fetch_related_insights(query, context)
    
    logger.info(f"Fetched {len(insights)} Glean insights for report {payload.report_id}")
    return {"insights": insights, "count": len(insights)}


class GleanEnrichmentRequest(BaseModel):
    report_id: str
    findings: List[dict]
    report_metadata: dict


@api_router.post("/glean/enrich")
async def enrich_findings(payload: GleanEnrichmentRequest):
    """Enrich findings with Glean using retrieval planner and evidence ranking."""
    try:
        validate_report_id(payload.report_id)
    except ValidationError as e:
        raise HTTPException(400, e.message)
    
    client = GleanConfigManager.get_client()
    if not client:
        return {
            "enriched": False,
            "message": "Glean not configured or enabled",
            "finding_enrichments": [],
            "retrieval_plan": [],
            "recommendations": []
        }
    
    # Convert findings to Finding dataclass objects
    from glean_mcp import Finding, Evidence
    findings_objects = []
    for f in payload.findings:
        evidence_objs = [Evidence(**e) for e in f.get("evidence", [])]
        finding_obj = Finding(
            id=f.get("id", ""),
            type=f.get("type", "unknown"),
            severity=f.get("severity", "info"),
            title=f.get("title", ""),
            summary=f.get("summary", ""),
            evidence=evidence_objs,
            keywords=f.get("keywords", []),
            affected_nodes=f.get("affected_nodes", []),
            version=f.get("version", ""),
            time_range=f.get("time_range")
        )
        findings_objects.append(finding_obj)
    
    # Run enrichment
    try:
        enrichment_result = await client.enrich_findings(findings_objects, payload.report_metadata)
        
        # Convert dataclasses to dicts for JSON response
        result = {
            "enriched": True,
            "report_id": enrichment_result.report_id,
            "enriched_at": enrichment_result.enriched_at,
            "finding_enrichments": enrichment_result.finding_enrichments,
            "retrieval_plan": enrichment_result.retrieval_plan,
            "recommendations": enrichment_result.recommendations
        }
        
        logger.info(f"Enriched {len(findings_objects)} findings for report {payload.report_id}")
        return result
    except Exception as e:
        logger.error(f"Enrichment failed for report {payload.report_id}: {e}")
        return {
            "enriched": False,
            "message": f"Enrichment failed: {str(e)}",
            "finding_enrichments": [],
            "retrieval_plan": [],
            "recommendations": []
        }


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

    if path.startswith("static/"):
        raise HTTPException(404, "Not found")

    candidate = (ui_path / path).resolve()
    try:
        root = ui_path.resolve()
    except Exception:
        root = ui_path
    if str(candidate).startswith(str(root)) and candidate.exists() and candidate.is_file():
        return FileResponse(str(candidate), headers={"Cache-Control": "no-store"})

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
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(_NoCacheUiStaticMiddleware)
if os.environ.get("S2RS_DISABLE_GZIP", "").strip().lower() not in {"1", "true", "yes", "y"}:
    app.add_middleware(GZipMiddleware, minimum_size=1000)


def _log_routes(app: FastAPI) -> None:
    try:
        items = []
        for r in getattr(app, "routes", []) or []:
            methods = sorted(m for m in (getattr(r, "methods", None) or set()) if m)
            path = getattr(r, "path", None)
            name = getattr(r, "name", None)
            if not path:
                continue
            items.append(("|".join(methods) if methods else "", path, name or ""))

        items.sort(key=lambda x: (x[1], x[0]))
        logger.info("Registered routes (%d)", len(items))
        for methods, path, name in items:
            if methods:
                logger.info("%s %s %s", methods, path, name)
            else:
                logger.info("%s %s", path, name)
    except Exception:
        logger.exception("Failed to list routes")


async def startup_app():
    if os.environ.get("S2RS_LOG_ROUTES", "").strip().lower() in {"1", "true", "yes", "y"}:
        _log_routes(app)
    return


async def shutdown_app():
    return


app.add_event_handler("startup", startup_app)
app.add_event_handler("shutdown", shutdown_app)
