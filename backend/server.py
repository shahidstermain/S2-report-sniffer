from fastapi import FastAPI, APIRouter, UploadFile, File, Query, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import tempfile
import shutil
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="SingleStore Report Sniffer v1")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import parsers
from parsers import parse_report_archive

UPLOAD_DIR = Path(tempfile.gettempdir()) / "sdb_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# ─── Models ─────────────────────────────────────────────────────────

class ReportSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    report_name: str
    uploaded_at: str
    status: str
    node_count: int = 0
    version: Optional[str] = None
    health_score: Optional[str] = None
    recommendation_count: int = 0

# ─── Upload & Parse ────────────────────────────────────────────────

@api_router.post("/reports/upload")
async def upload_report(file: UploadFile = File(...)):
    """Upload and parse a tar.gz diagnostic report."""
    if not file.filename.endswith(('.tar.gz', '.tgz', '.zip')):
        raise HTTPException(400, "Only .tar.gz, .tgz, and .zip files are accepted")

    report_id = str(uuid.uuid4())
    ext = ".zip" if file.filename.endswith('.zip') else ".tar.gz"
    tmp_path = UPLOAD_DIR / f"{report_id}{ext}"

    try:
        # Save uploaded file
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Create initial report record
        report_doc = {
            "id": report_id,
            "report_name": file.filename,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "status": "processing",
            "file_size": len(content),
        }
        await db.reports.insert_one(report_doc)

        # Parse in background
        asyncio.create_task(_parse_report_background(report_id, str(tmp_path)))

        return {"id": report_id, "status": "processing", "message": "Report uploaded and parsing started"}

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise HTTPException(500, f"Upload failed: {str(e)}")


async def _parse_report_background(report_id: str, archive_path: str):
    """Background task to parse the report."""
    try:
        loop = asyncio.get_event_loop()
        parsed = await loop.run_in_executor(None, parse_report_archive, archive_path)

        # Compute health score
        recs = parsed.get("recommendations", [])
        critical = sum(1 for r in recs if r.get("severity") == "critical")
        warnings = sum(1 for r in recs if r.get("severity") == "warning")
        if critical > 0:
            health = "critical"
        elif warnings > 0:
            health = "warning"
        else:
            health = "healthy"

        overview = parsed.get("cluster_overview", {})

        # Update report with parsed data
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
                "logs": parsed.get("logs", []),
                "log_summary": parsed.get("log_summary", {}),
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
            }}
        )
        logger.info(f"Report {report_id} parsed successfully")

    except Exception as e:
        logger.error(f"Parsing failed for {report_id}: {e}", exc_info=True)
        await db.reports.update_one(
            {"id": report_id},
            {"$set": {"status": "error", "error": str(e)}}
        )
    finally:
        try:
            os.unlink(archive_path)
        except Exception:
            pass


# ─── List Reports ──────────────────────────────────────────────────

@api_router.get("/reports")
async def list_reports():
    """List all uploaded reports."""
    reports = await db.reports.find(
        {},
        {"_id": 0, "id": 1, "report_name": 1, "uploaded_at": 1, "status": 1,
         "node_count": 1, "version": 1, "health_score": 1, "recommendation_count": 1,
         "file_size": 1}
    ).sort("uploaded_at", -1).to_list(100)
    return reports


# ─── Report Status ─────────────────────────────────────────────────

@api_router.get("/reports/{report_id}/status")
async def get_report_status(report_id: str):
    doc = await db.reports.find_one({"id": report_id}, {"_id": 0, "id": 1, "status": 1, "error": 1})
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
         "dmesg_events": 1, "config_health.license": 1}
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


# ─── Logs ──────────────────────────────────────────────────────────

@api_router.get("/reports/{report_id}/logs")
async def get_report_logs(
    report_id: str,
    search: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    node: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=500),
):
    doc = await db.reports.find_one(
        {"id": report_id},
        {"_id": 0, "logs": 1, "log_summary": 1}
    )
    if not doc:
        raise HTTPException(404, "Report not found")

    logs = doc.get("logs", [])

    # Apply filters
    if severity:
        sevs = [s.strip().upper() for s in severity.split(",")]
        logs = [l for l in logs if l.get("severity", "").upper() in sevs]
    if node:
        logs = [l for l in logs if node.lower() in l.get("hostname", "").lower()]
    if search:
        search_lower = search.lower()
        logs = [l for l in logs if search_lower in l.get("message", "").lower()
                or search_lower in l.get("hostname", "").lower()]

    total = len(logs)
    start = (page - 1) * page_size
    end = start + page_size
    page_logs = logs[start:end]

    return {
        "logs": page_logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "log_summary": doc.get("log_summary", {}),
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
    if result.deleted_count == 0:
        raise HTTPException(404, "Report not found")
    return {"message": "Report deleted"}


# ─── Health check ──────────────────────────────────────────────────

@api_router.get("/")
async def root():
    return {"message": "SDB Insight API", "status": "ok"}


# ─── App setup ─────────────────────────────────────────────────────

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
