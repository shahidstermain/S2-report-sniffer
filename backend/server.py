from fastapi import FastAPI, APIRouter, UploadFile, File, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional
import uuid
from datetime import datetime, timezone
import asyncio
import aiofiles

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="SingleStore Report Sniffer v1")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from parsers import parse_report_archive_streaming

UPLOAD_DIR = Path(tempfile.gettempdir()) / "sdb_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

CHUNK_SIZE = 1024 * 1024  # 1MB chunks for streaming file write


# ─── Chunked Streaming Upload ──────────────────────────────────────

@api_router.post("/reports/upload")
async def upload_report(file: UploadFile = File(...)):
    """Upload and parse a diagnostic report. Streams to disk in chunks."""
    if not file.filename.endswith(('.tar.gz', '.tgz', '.zip')):
        raise HTTPException(400, "Only .tar.gz, .tgz, and .zip files are accepted")

    report_id = str(uuid.uuid4())
    ext = ".zip" if file.filename.endswith('.zip') else ".tar.gz"
    tmp_path = UPLOAD_DIR / f"{report_id}{ext}"

    try:
        # Stream file to disk in chunks — never load entire file into RAM
        file_size = 0
        async with aiofiles.open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                await out.write(chunk)
                file_size += len(chunk)

        # Create report record with progress tracking
        report_doc = {
            "id": report_id,
            "report_name": file.filename,
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
        await db.reports.insert_one(report_doc)

        # Parse in background
        asyncio.create_task(_parse_report_background(report_id, str(tmp_path), file_size))

        return {
            "id": report_id,
            "status": "processing",
            "file_size": file_size,
            "detected_format": "zip" if ext == ".zip" else "tar.gz",
            "message": "Report uploaded and queued for processing",
        }

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise HTTPException(500, f"Upload failed: {str(e)}")


async def _update_progress(report_id: str, stage: str, pct: int, message: str, **extra):
    """Update parsing progress in MongoDB."""
    progress = {"stage": stage, "pct": pct, "message": message}
    progress.update(extra)
    await db.reports.update_one(
        {"id": report_id},
        {"$set": {"progress": progress}}
    )


async def _parse_report_background(report_id: str, archive_path: str, file_size: int):
    """Background task to parse the report with progress reporting."""
    try:
        await _update_progress(report_id, "extracting", 5,
            "Discovering report structure...", files_processed=0)

        loop = asyncio.get_event_loop()

        # Progress callback that the parser calls
        progress_state = {"files": 0, "nodes": 0, "logs": 0}

        def progress_callback(stage, files=0, nodes=0, logs=0, message=""):
            progress_state["files"] += files
            progress_state["nodes"] = max(progress_state["nodes"], nodes)
            progress_state["logs"] += logs
            # We can't await in sync callback, so we schedule it
            asyncio.run_coroutine_threadsafe(
                _update_progress(report_id, stage,
                    min(90, 10 + (progress_state["files"] * 80 // max(progress_state["nodes"] * 50, 1))),
                    message or f"Parsing... {progress_state['files']} files, {progress_state['logs']} log lines",
                    nodes_discovered=progress_state["nodes"],
                    files_processed=progress_state["files"],
                    log_lines_indexed=progress_state["logs"],
                ),
                loop
            )

        parsed = await loop.run_in_executor(
            None, parse_report_archive_streaming, archive_path, progress_callback
        )

        await _update_progress(report_id, "analyzing", 90,
            "Running recommendations engine...")

        # Compute health score
        recs = parsed.get("recommendations", [])
        critical = sum(1 for r in recs if r.get("severity") == "critical")
        warnings = sum(1 for r in recs if r.get("severity") == "warning")
        health = "critical" if critical > 0 else ("warning" if warnings > 0 else "healthy")

        overview = parsed.get("cluster_overview", {})

        # Store logs in separate collection for scalability
        logs = parsed.pop("logs", [])
        if logs:
            # Batch insert logs in chunks of 5000
            log_docs = [{"report_id": report_id, **log} for log in logs]
            for i in range(0, len(log_docs), 5000):
                batch = log_docs[i:i+5000]
                await db.report_logs.insert_many(batch, ordered=False)

        await _update_progress(report_id, "storing", 95,
            f"Saving results... {len(recs)} issues found")

        # Update report with parsed data (logs stored separately)
        await db.reports.update_one(
            {"id": report_id},
            {"$set": {
                "status": "ready",
                "parsed_at": parsed.get("parsed_at"),
                "detected_format": parsed.get("detected_format", "unknown"),
                "node_count": parsed.get("raw_node_count", 0),
                "version": overview.get("version"),
                "health_score": health,
                "recommendation_count": len(recs),
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
                "progress": {
                    "stage": "complete", "pct": 100,
                    "message": f"Analysis complete. {parsed.get('raw_node_count', 0)} nodes, {len(logs)} log lines, {len(recs)} recommendations",
                    "nodes_discovered": parsed.get("raw_node_count", 0),
                    "files_processed": progress_state.get("files", 0),
                    "log_lines_indexed": len(logs),
                },
            }}
        )
        logger.info(f"Report {report_id} parsed: {parsed.get('raw_node_count', 0)} nodes, {len(logs)} logs, {len(recs)} recs")

    except Exception as e:
        logger.error(f"Parsing failed for {report_id}: {e}", exc_info=True)
        await db.reports.update_one(
            {"id": report_id},
            {"$set": {
                "status": "error",
                "error": str(e),
                "progress": {"stage": "failed", "pct": 0, "message": str(e)},
            }}
        )
    finally:
        try:
            os.unlink(archive_path)
        except Exception:
            pass


# ─── List Reports ──────────────────────────────────────────────────

@api_router.get("/reports")
async def list_reports():
    reports = await db.reports.find(
        {},
        {"_id": 0, "id": 1, "report_name": 1, "uploaded_at": 1, "status": 1,
         "node_count": 1, "version": 1, "health_score": 1, "recommendation_count": 1,
         "file_size": 1, "detected_format": 1}
    ).sort("uploaded_at", -1).to_list(100)
    return reports


# ─── Report Status with Progress ──────────────────────────────────

@api_router.get("/reports/{report_id}/status")
async def get_report_status(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "id": 1, "status": 1, "error": 1, "progress": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Cluster Overview ──────────────────────────────────────────────

@api_router.get("/reports/{report_id}/overview")
async def get_report_overview(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "cluster_overview": 1, "recommendations": 1, "events": 1,
         "report_name": 1, "uploaded_at": 1, "status": 1, "health_score": 1,
         "node_count": 1, "version": 1, "log_summary": 1, "database_disk_usage": 1,
         "availability_groups": 1, "version_history": 1, "detected_log_patterns": 1,
         "dmesg_events": 1, "config_health.license": 1, "detected_format": 1,
         "file_size": 1, "log_count": 1, "progress": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Node Health ───────────────────────────────────────────────────

@api_router.get("/reports/{report_id}/nodes")
async def get_report_nodes(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "nodes": 1, "cluster_overview.nodes_detail": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Storage ───────────────────────────────────────────────────────

@api_router.get("/reports/{report_id}/storage")
async def get_report_storage(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "databases": 1, "storage": 1, "database_disk_usage": 1,
         "partitions": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Workload & Queries ───────────────────────────────────────────

@api_router.get("/reports/{report_id}/queries")
async def get_report_queries(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "queries": 1, "workload_management": 1,
         "cluster_overview.blocked_queries": 1, "cluster_overview.processlist": 1,
         "cluster_overview.mv_processlist": 1, "resource_pools": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Config Health ─────────────────────────────────────────────────

@api_router.get("/reports/{report_id}/config")
async def get_report_config(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "config_health": 1, "backup_history": 1, "users": 1,
         "version_history": 1, "nodes.show_variables": 1, "nodes.hostname": 1,
         "nodes.role": 1, "nodes.os_checks": 1, "nodes.config.process_limits": 1,
         "nodes.license": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Logs (from separate collection for scalability) ──────────────

@api_router.get("/reports/{report_id}/logs")
async def get_report_logs(
    report_id: str,
    search: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    node: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=500),
):
    # Build MongoDB query filter
    query_filter = {"report_id": report_id}
    if severity:
        sevs = [s.strip().upper() for s in severity.split(",")]
        query_filter["severity"] = {"$in": sevs}
    if node:
        query_filter["hostname"] = {"$regex": node, "$options": "i"}
    if search:
        query_filter["$or"] = [
            {"message": {"$regex": search, "$options": "i"}},
            {"hostname": {"$regex": search, "$options": "i"}},
        ]

    total = await db.report_logs.count_documents(query_filter)
    skip = (page - 1) * page_size
    logs = await db.report_logs.find(
        query_filter, {"_id": 0, "report_id": 0}
    ).sort("timestamp", 1).skip(skip).limit(page_size).to_list(page_size)

    # Get log summary from report doc
    report = await db.reports.find_one(
        {"id": report_id}, {"_id": 0, "log_summary": 1}
    )

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "log_summary": report.get("log_summary", {}) if report else {},
    }


# ─── Pipelines ────────────────────────────────────────────────────

@api_router.get("/reports/{report_id}/pipelines")
async def get_report_pipelines(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "pipelines": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Recommendations ──────────────────────────────────────────────

@api_router.get("/reports/{report_id}/recommendations")
async def get_report_recommendations(report_id: str):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "recommendations": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")
    return doc


# ─── Delete Report ─────────────────────────────────────────────────

@api_router.delete("/reports/{report_id}")
async def delete_report(report_id: str):
    result = await db.reports.delete_one({"id": report_id})
    # Also delete logs from separate collection
    await db.report_logs.delete_many({"report_id": report_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Report not found")
    return {"message": "Report deleted"}


# ─── Health check ──────────────────────────────────────────────────

@api_router.get("/")
async def root():
    return {"message": "SingleStore Report Sniffer v1 API", "status": "ok"}


# ─── App setup ─────────────────────────────────────────────────────

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db():
    # Create indexes for log queries
    await db.report_logs.create_index([("report_id", 1), ("timestamp", 1)])
    await db.report_logs.create_index([("report_id", 1), ("severity", 1)])
    await db.report_logs.create_index([("report_id", 1), ("hostname", 1)])

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
