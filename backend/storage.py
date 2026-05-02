import asyncio
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def default_data_dir() -> Path:
    override = os.environ.get("S2RS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".s2-report-sniffer").resolve()


def _probe_sqlite_directory(dir_path: Path) -> bool:
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        probe_path = dir_path / ".probe.sqlite"
        try:
            if probe_path.exists():
                probe_path.unlink(missing_ok=True)
        except Exception:
            return False
        try:
            with sqlite3.connect(probe_path, timeout=5) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE IF NOT EXISTS _probe (id INTEGER PRIMARY KEY)")
                conn.execute("INSERT INTO _probe(id) VALUES (1)")
                conn.execute("DELETE FROM _probe")
                conn.commit()
            return True
        finally:
            try:
                probe_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                wal = Path(str(probe_path) + "-wal")
                shm = Path(str(probe_path) + "-shm")
                wal.unlink(missing_ok=True)
                shm.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        return False


@dataclass(frozen=True)
class StorageStatus:
    ok: bool
    message: str


class ReportStore:
    async def ping(self) -> StorageStatus:
        raise NotImplementedError()

    async def create_report_stub(self, report_id: str, report_name: str, file_size: int, detected_format: str) -> None:
        raise NotImplementedError()

    async def update_report_fields(self, report_id: str, fields: Dict[str, Any]) -> None:
        raise NotImplementedError()

    async def get_report_fields(self, report_id: str, fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError()

    async def list_reports(self, limit: int = 100) -> List[Dict[str, Any]]:
        raise NotImplementedError()

    async def delete_report(self, report_id: str) -> bool:
        raise NotImplementedError()

    async def write_report_payload(self, report_id: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError()

    async def read_report_payload(self, report_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError()

    async def write_report_logs(self, report_id: str, logs: List[Dict[str, Any]]) -> None:
        raise NotImplementedError()

    async def query_report_logs(
        self,
        report_id: str,
        search: Optional[str],
        severities: Optional[List[str]],
        node_prefix: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError()


class LocalReportStore(ReportStore):
    def __init__(self, base_dir: Optional[Path] = None):
        repo_root = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))).resolve()
        candidates: List[Path] = []
        if base_dir is not None:
            candidates.append(Path(base_dir).expanduser().resolve())
        else:
            override = os.environ.get("S2RS_DATA_DIR")
            if override:
                candidates.append(Path(override).expanduser().resolve())
            candidates.append((repo_root / ".local_data").resolve())
            candidates.append(default_data_dir().resolve())

        selected: Optional[Path] = None
        for candidate in candidates:
            if _probe_sqlite_directory(candidate):
                selected = candidate
                break
        if selected is None:
            selected = candidates[-1]
            selected.mkdir(parents=True, exist_ok=True)

        self.base_dir = selected
        self.db_path = self.base_dir / "reports.sqlite"
        self.reports_dir = self.base_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    report_name TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    detected_format TEXT NOT NULL,
                    node_count INTEGER,
                    version TEXT,
                    health_score TEXT,
                    recommendation_count INTEGER,
                    cluster_risk_score INTEGER,
                    progress_json TEXT,
                    payload_path TEXT,
                    deployment_method TEXT,
                    deployment_confidence TEXT,
                    deployment_signals TEXT,
                    error TEXT
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(reports)").fetchall()}
            if "deployment_method" not in cols:
                conn.execute("ALTER TABLE reports ADD COLUMN deployment_method TEXT")
            if "deployment_confidence" not in cols:
                conn.execute("ALTER TABLE reports ADD COLUMN deployment_confidence TEXT")
            if "deployment_signals" not in cols:
                conn.execute("ALTER TABLE reports ADD COLUMN deployment_signals TEXT")
            if "log_count" not in cols:
                conn.execute("ALTER TABLE reports ADD COLUMN log_count INTEGER")
            if "parsed_at" not in cols:
                conn.execute("ALTER TABLE reports ADD COLUMN parsed_at TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_uploaded_at ON reports(uploaded_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_uploads (
                    upload_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    total_chunks INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (upload_id, chunk_index)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_uploads_created_at ON chunk_uploads(created_at)")
            conn.commit()

    def _report_payload_path(self, report_id: str) -> Path:
        return (self.reports_dir / report_id / "report.json").resolve()

    def _report_logs_path(self, report_id: str) -> Path:
        return (self.reports_dir / report_id / "logs.jsonl").resolve()

    def _progress_default(self) -> Dict[str, Any]:
        return {
            "stage": "queued",
            "pct": 0,
            "message": "Queued",
            "nodes_discovered": 0,
            "files_processed": 0,
            "log_lines_indexed": 0,
        }

    async def ping(self) -> StorageStatus:
        try:
            def _ping():
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("SELECT 1")
            await asyncio.to_thread(_ping)
            return StorageStatus(ok=True, message="Local storage OK")
        except Exception as e:
            return StorageStatus(ok=False, message=str(e))

    async def create_report_stub(self, report_id: str, report_name: str, file_size: int, detected_format: str) -> None:
        uploaded_at = datetime.now(timezone.utc).isoformat()
        progress_json = json.dumps(self._progress_default())
        payload_path = str(self._report_payload_path(report_id))

        def _insert():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO reports (
                        id, report_name, uploaded_at, status, file_size, detected_format,
                        progress_json, payload_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (report_id, report_name, uploaded_at, "processing", file_size, detected_format, progress_json, payload_path),
                )
                conn.commit()

        await asyncio.to_thread(_insert)

    async def update_report_fields(self, report_id: str, fields: Dict[str, Any]) -> None:
        if not fields:
            return

        allowed = {
            "report_name", "uploaded_at", "status", "file_size", "detected_format",
            "node_count", "version", "health_score", "recommendation_count", "cluster_risk_score",
            "progress_json", "payload_path", "error",
            "deployment_method",
            "deployment_confidence",
            "deployment_signals",
            "log_count",
            "parsed_at",
        }
        update_cols = []
        values = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            update_cols.append(f"{k}=?")
            values.append(v)
        if not update_cols:
            return
        values.append(report_id)

        def _update():
            with sqlite3.connect(self.db_path) as conn:
                query = f"UPDATE reports SET {', '.join(update_cols)} WHERE id=?"  # nosec
                conn.execute(query, values)
                conn.commit()

        await asyncio.to_thread(_update)

    async def get_report_fields(self, report_id: str, fields: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        allowed = [
            "id", "report_name", "uploaded_at", "status", "file_size", "detected_format",
            "node_count", "version", "health_score", "recommendation_count", "cluster_risk_score",
            "progress_json", "payload_path", "error", "deployment_method", "deployment_confidence", "deployment_signals",
            "log_count", "parsed_at",
        ]
        select = allowed if not fields else [f for f in fields if f in allowed]
        if not select:
            select = ["id"]

        def _get():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                query = f"SELECT {', '.join(select)} FROM reports WHERE id=?"  # nosec
                row = conn.execute(query, (report_id,)).fetchone()
                return dict(row) if row else None

        doc = await asyncio.to_thread(_get)
        if not doc:
            return None
        if "progress_json" in doc and doc["progress_json"]:
            try:
                doc["progress"] = json.loads(doc["progress_json"])
            except Exception:
                doc["progress"] = None
        return doc

    async def list_reports(self, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, min(500, int(limit)))

        def _list():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, report_name, uploaded_at, status, node_count, version, health_score,
                           recommendation_count, file_size, detected_format, cluster_risk_score, deployment_method,
                           deployment_confidence, deployment_signals, log_count, parsed_at
                    FROM reports
                    ORDER BY uploaded_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]

        return await asyncio.to_thread(_list)

    async def delete_report(self, report_id: str) -> bool:
        payload_path = self._report_payload_path(report_id)
        report_dir = payload_path.parent

        def _delete_row() -> bool:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
                conn.commit()
                return cur.rowcount > 0

        deleted = await asyncio.to_thread(_delete_row)
        try:
            if report_dir.exists():
                for p in sorted(report_dir.rglob("*"), reverse=True):
                    if p.is_file():
                        p.unlink(missing_ok=True)
                    else:
                        try:
                            p.rmdir()
                        except Exception as e:
                            logger.debug("Could not remove directory %s: %s", p, e)
                try:
                    report_dir.rmdir()
                except Exception as e:
                    logger.debug("Could not remove report dir %s: %s", report_dir, e)
        except Exception as e:
            logger.warning("Error cleaning up report files for %s: %s", report_id, e)
        return deleted

    async def write_report_payload(self, report_id: str, payload: Dict[str, Any]) -> None:
        payload_path = self._report_payload_path(report_id)
        payload_path.parent.mkdir(parents=True, exist_ok=True)

        def _write():
            with open(payload_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        await asyncio.to_thread(_write)
        await self.update_report_fields(report_id, {"payload_path": str(payload_path)})

    async def read_report_payload(self, report_id: str) -> Optional[Dict[str, Any]]:
        payload_path = self._report_payload_path(report_id)
        if not payload_path.exists():
            return None

        # Check payload size to prevent memory exhaustion
        file_size = payload_path.stat().st_size
        MAX_PAYLOAD_SIZE = 100 * 1024 * 1024  # 100MB limit
        if file_size > MAX_PAYLOAD_SIZE:
            logger.warning(f"Payload for {report_id} is too large: {file_size / 1024 / 1024:.2f}MB")
            # Return truncated payload with error
            return {
                "error": f"Payload too large ({file_size / 1024 / 1024:.2f}MB), truncated",
                "report_id": report_id,
            }

        def _read():
            with open(payload_path, "r", encoding="utf-8") as f:
                return json.load(f)

        return await asyncio.to_thread(_read)

    async def write_report_logs(self, report_id: str, logs: List[Dict[str, Any]]) -> None:
        logs_path = self._report_logs_path(report_id)
        logs_path.parent.mkdir(parents=True, exist_ok=True)

        def _write():
            with open(logs_path, "w", encoding="utf-8") as f:
                for row in logs:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        await asyncio.to_thread(_write)

    async def query_report_logs(
        self,
        report_id: str,
        search: Optional[str],
        severities: Optional[List[str]],
        node_prefix: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        logs_path = self._report_logs_path(report_id)
        if not logs_path.exists():
            return [], 0
        page = max(1, int(page))
        page_size = max(10, min(500, int(page_size)))
        start = (page - 1) * page_size
        end = start + page_size
        search_l = (search or "").lower()
        node_prefix_l = (node_prefix or "").lower()
        sev_set = set((severities or []))

        def _scan():
            matched = []
            total = 0
            with open(logs_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if sev_set:
                        sev = str(row.get("severity", "")).lower()
                        if sev not in sev_set:
                            continue
                    if node_prefix_l:
                        hn = str(row.get("hostname", "")).lower()
                        if not hn.startswith(node_prefix_l):
                            continue
                    if search_l:
                        blob = (str(row.get("message", "")) + " " + str(row.get("hostname", ""))).lower()
                        if search_l not in blob:
                            continue
                    if total >= end:
                        total += 1
                        continue
                    if total >= start:
                        matched.append(row)
                    total += 1
            return matched, total

        return await asyncio.to_thread(_scan)

    async def save_chunk_state(self, upload_id: str, chunk_index: int, chunk_path: str,
                               filename: str, total_chunks: int) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        def _save():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO chunk_uploads (upload_id, chunk_index, chunk_path, filename, total_chunks, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(upload_id, chunk_index) DO UPDATE SET
                        chunk_path=excluded.chunk_path,
                        created_at=excluded.created_at
                    """,
                    (upload_id, chunk_index, chunk_path, filename, total_chunks, created_at),
                )
                conn.commit()
        await asyncio.to_thread(_save)

    async def load_chunk_state(self, upload_id: str) -> Optional[Dict[str, Any]]:
        def _load():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT chunk_index, chunk_path, filename, total_chunks, created_at FROM chunk_uploads WHERE upload_id=? ORDER BY chunk_index",
                    (upload_id,)
                ).fetchall()
                if not rows:
                    return None
                return {
                    "filename": rows[0]["filename"],
                    "total_chunks": rows[0]["total_chunks"],
                    "received_chunks": {row["chunk_index"]: row["chunk_path"] for row in rows},
                    "created_at": rows[0]["created_at"],
                }
        return await asyncio.to_thread(_load)

    async def get_chunk_paths(self, upload_id: str) -> Dict[int, str]:
        def _get_paths():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT chunk_index, chunk_path FROM chunk_uploads WHERE upload_id=? ORDER BY chunk_index",
                    (upload_id,)
                ).fetchall()
                return {row["chunk_index"]: row["chunk_path"] for row in rows}
        return await asyncio.to_thread(_get_paths)

    async def count_chunks(self, upload_id: str) -> int:
        def _count():
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT COUNT(*) as cnt FROM chunk_uploads WHERE upload_id=?", (upload_id,)).fetchone()
                return row[0] if row else 0
        return await asyncio.to_thread(_count)

    async def delete_chunk_state(self, upload_id: str) -> None:
        def _delete():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM chunk_uploads WHERE upload_id=?", (upload_id,))
                conn.commit()
        await asyncio.to_thread(_delete)

    async def cleanup_old_chunks(self, older_than_hours: int = 24) -> int:
        import datetime as _dt
        cutoff = datetime.now(timezone.utc) - _dt.timedelta(hours=older_than_hours)
        cutoff_str = cutoff.isoformat()
        def _cleanup():
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT chunk_path FROM chunk_uploads WHERE created_at < ?", (cutoff_str,)
                ).fetchall()
                count = 0
                for row in rows:
                    try:
                        Path(row[0]).unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning("Failed to remove stale chunk file %s: %s", row[0], e)
                    count += 1
                conn.execute("DELETE FROM chunk_uploads WHERE created_at < ?", (cutoff_str,))
                conn.commit()
                return count
        return await asyncio.to_thread(_cleanup)


def build_store() -> ReportStore:
    backend = (os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
    db_url = os.environ.get("DATABASE_URL")
    if db_url or backend == "postgres":
        raise NotImplementedError(
            "PostgreSQL backend is not yet implemented. "
            "Use STORAGE_BACKEND=local (default) with optional S2RS_DATA_DIR to set the data directory."
        )
    return LocalReportStore()
