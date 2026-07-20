import asyncio
import contextlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SQLITE_CONNECT_TIMEOUT_S = 30.0
_SQLITE_BUSY_TIMEOUT_MS = 30000


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

    async def update_report_fields(self, report_id: str, fields: dict[str, Any]) -> None:
        raise NotImplementedError()

    async def get_report_fields(self, report_id: str, fields: list[str] | None = None) -> dict[str, Any] | None:
        raise NotImplementedError()

    async def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError()

    async def delete_report(self, report_id: str) -> bool:
        raise NotImplementedError()

    async def write_report_payload(self, report_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError()

    async def read_report_payload(self, report_id: str) -> dict[str, Any] | None:
        raise NotImplementedError()

    async def write_report_logs(self, report_id: str, logs: list[dict[str, Any]]) -> None:
        raise NotImplementedError()

    async def query_report_logs(
        self,
        report_id: str,
        search: str | None,
        severities: list[str] | None,
        node_prefix: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        raise NotImplementedError()

    async def search_report_logs(
        self,
        report_id: str,
        keyword: str,
        regex: bool,
        case_sensitive: bool,
        severities: list[str] | None,
        node_prefix: str | None,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        raise NotImplementedError()

    async def shutdown(self) -> None:
        """Release storage resources on process exit. Override in concrete stores."""
        return None

    async def enqueue_analysis_job(self, report_id: str, request: dict[str, Any]) -> None:
        raise NotImplementedError()

    async def claim_analysis_job(self, worker_id: str, lease_seconds: int = 300) -> dict[str, Any] | None:
        raise NotImplementedError()

    async def finish_analysis_job(self, report_id: str, state: str, error_code: str | None = None) -> None:
        raise NotImplementedError()

    async def renew_analysis_job(self, report_id: str, worker_id: str, lease_seconds: int = 300) -> bool:
        raise NotImplementedError()


class LocalReportStore(ReportStore):
    def __init__(self, base_dir: Path | None = None):
        repo_root = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))).resolve()
        candidates: list[Path] = []
        if base_dir is not None:
            candidates.append(Path(base_dir).expanduser().resolve())
        else:
            override = os.environ.get("S2RS_DATA_DIR")
            if override:
                candidates.append(Path(override).expanduser().resolve())
            candidates.append((repo_root / ".local_data").resolve())
            candidates.append(default_data_dir().resolve())

        selected: Path | None = None
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

    @contextlib.contextmanager
    def _store_db(self, *, init_wal: bool = False):
        """SQLite connection with busy timeout (and optional WAL init for first-time setup)."""
        conn = sqlite3.connect(str(self.db_path), timeout=_SQLITE_CONNECT_TIMEOUT_S)
        try:
            conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-32768")
            conn.execute("PRAGMA mmap_size=268435456")
            if init_wal:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._store_db(init_wal=True) as conn:
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
            if "extracted_path" not in cols:
                conn.execute("ALTER TABLE reports ADD COLUMN extracted_path TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_uploaded_at ON reports(uploaded_at)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_status_uploaded "
                "ON reports(status, uploaded_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_parsed_at "
                "ON reports(parsed_at DESC) WHERE status='ready'"
            )
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    report_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK (
                        state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
                    ),
                    request_json TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error_code TEXT,
                    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_claim "
                "ON analysis_jobs(state, created_at)"
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS report_logs_fts USING fts5(
                        report_id UNINDEXED,
                        row_json UNINDEXED,
                        searchable,
                        tokenize='trigram'
                    )
                    """
                )
            except sqlite3.OperationalError:
                logger.info("SQLite FTS5 trigram index unavailable; JSONL search remains active")
            conn.commit()

    @staticmethod
    def _retry_locked(operation, *, attempts: int = 5):
        for attempt in range(attempts):
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                if attempt + 1 >= attempts:
                    raise
                time.sleep(min(0.05 * (2 ** attempt), 0.8))

    @staticmethod
    def _atomic_write_text(path: Path, writer) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                writer(handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _report_payload_path(self, report_id: str) -> Path:
        return (self.reports_dir / report_id / "report.json").resolve()

    def _report_logs_path(self, report_id: str) -> Path:
        return (self.reports_dir / report_id / "logs.jsonl").resolve()

    def _extracted_dir(self, report_id: str) -> Path:
        """On-disk location for a persisted extracted report root (raw search)."""
        return (self.reports_dir / report_id / "extracted").resolve()

    def _progress_default(self) -> dict[str, Any]:
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
                with self._store_db() as conn:
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
            with self._store_db() as conn:
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

        await asyncio.to_thread(self._retry_locked, _insert)

    async def update_report_fields(self, report_id: str, fields: dict[str, Any]) -> None:
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
            "extracted_path",
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
            with self._store_db() as conn:
                query = f"UPDATE reports SET {', '.join(update_cols)} WHERE id=?"  # nosec
                conn.execute(query, values)
                conn.commit()

        await asyncio.to_thread(self._retry_locked, _update)

    async def get_report_fields(self, report_id: str, fields: list[str] | None = None) -> dict[str, Any] | None:
        allowed = [
            "id", "report_name", "uploaded_at", "status", "file_size", "detected_format",
            "node_count", "version", "health_score", "recommendation_count", "cluster_risk_score",
            "progress_json", "payload_path", "error", "deployment_method", "deployment_confidence", "deployment_signals",
            "log_count", "parsed_at", "extracted_path",
        ]
        select = allowed if not fields else [f for f in fields if f in allowed]
        if not select:
            select = ["id"]

        def _get():
            with self._store_db() as conn:
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

    async def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit)))

        def _list():
            with self._store_db() as conn:
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
            with self._store_db() as conn:
                cur = conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
                conn.commit()
                return cur.rowcount > 0

        deleted = await asyncio.to_thread(self._retry_locked, _delete_row)
        cleanup_errors: list[str] = []
        try:
            if report_dir.exists():
                for p in sorted(report_dir.rglob("*"), reverse=True):
                    if p.is_file():
                        try:
                            p.unlink(missing_ok=True)
                        except OSError as exc:
                            cleanup_errors.append(f"unlink {p.name}: {exc}")
                    else:
                        try:
                            p.rmdir()
                        except OSError as exc:
                            cleanup_errors.append(f"rmdir {p.name}: {exc}")
                try:
                    report_dir.rmdir()
                except OSError as exc:
                    cleanup_errors.append(f"rmdir {report_dir.name}: {exc}")
        except OSError as exc:
            cleanup_errors.append(str(exc))
        if cleanup_errors:
            logger.warning(
                "Report directory cleanup incomplete for %s: %s",
                report_id,
                "; ".join(cleanup_errors),
            )
        return deleted

    async def write_report_payload(self, report_id: str, payload: dict[str, Any]) -> None:
        payload_path = self._report_payload_path(report_id)

        def _write():
            self._atomic_write_text(
                payload_path,
                lambda handle: json.dump(payload, handle, ensure_ascii=False),
            )
        await asyncio.to_thread(_write)
        await self.update_report_fields(report_id, {"payload_path": str(payload_path)})

    async def read_report_payload(self, report_id: str) -> dict[str, Any] | None:
        payload_path = self._report_payload_path(report_id)
        if not payload_path.exists():
            return None

        # Check payload size to prevent memory exhaustion
        file_size = payload_path.stat().st_size
        MAX_PAYLOAD_SIZE = 100 * 1024 * 1024  # 100MB limit
        if file_size > MAX_PAYLOAD_SIZE:
            logger.warning(f"Payload for {report_id} is too large: {file_size / 1024 / 1024:.2f}MB")
            raise ValueError(f"Payload too large ({file_size / 1024 / 1024:.2f}MB); cannot load for in-memory access")

        def _read():
            with open(payload_path, "r", encoding="utf-8") as f:
                return json.load(f)

        return await asyncio.to_thread(_read)

    async def set_extracted_path(self, report_id: str, path: str) -> None:
        """Record the on-disk extracted-report path so raw search can find it."""
        if not path:
            return
        await self.update_report_fields(report_id, {"extracted_path": str(path)})

    async def get_extracted_path(self, report_id: str) -> str | None:
        doc = await self.get_report_fields(report_id, fields=["extracted_path"])
        if not doc:
            return None
        p = str(doc.get("extracted_path") or "")
        if p and os.path.isdir(p):
            return p
        return None

    async def write_report_logs(self, report_id: str, logs: list[dict[str, Any]]) -> None:
        logs_path = self._report_logs_path(report_id)

        def _write():
            def _write_rows(f):
                for row in logs:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._atomic_write_text(logs_path, _write_rows)
            with self._store_db() as conn:
                try:
                    conn.execute("DELETE FROM report_logs_fts WHERE report_id=?", (report_id,))
                    conn.executemany(
                        "INSERT INTO report_logs_fts(report_id, row_json, searchable) VALUES (?, ?, ?)",
                        (
                            (
                                report_id,
                                json.dumps(row, ensure_ascii=False),
                                f"{row.get('timestamp', '')} {row.get('message', '')} {row.get('hostname', '')}",
                            )
                            for row in logs
                        ),
                    )
                    conn.commit()
                except sqlite3.OperationalError:
                    conn.rollback()
        await asyncio.to_thread(_write)

    async def query_report_logs(
        self,
        report_id: str,
        search: str | None,
        severities: list[str] | None,
        node_prefix: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
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
                        blob = (
                            f"{row.get('timestamp', '')} {row.get('message', '')} {row.get('hostname', '')}"
                        ).lower()
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

    async def search_report_logs(
        self,
        report_id: str,
        keyword: str,
        regex: bool,
        case_sensitive: bool,
        severities: list[str] | None,
        node_prefix: str | None,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """Single-pass authoritative search over persisted parsed logs.

        Matches the keyword (literal or regex, case-sensitive or not) against
        ``timestamp + message + hostname``. Severity and node filters are
        applied as lowercase comparisons. Returns ``(matches, total_matching,
        truncated)`` where ``total_matching`` counts every hit so the caller can
        report truncation accurately.
        """
        logs_path = self._report_logs_path(report_id)
        if not logs_path.exists():
            return [], 0, False
        limit = max(1, min(2000, int(limit)))
        sev_set = {(s or "").lower() for s in (severities or [])}
        node_prefix_l = (node_prefix or "").lower()
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(keyword if regex else re.escape(keyword), flags)
        except re.error as exc:
            raise ValueError("invalid_regex") from exc

        def _in_time_range(row: dict[str, Any]) -> bool:
            if start_time is None and end_time is None:
                return True
            try:
                parsed = datetime.fromisoformat(str(row.get("timestamp", "")).replace("Z", "+00:00"))
            except ValueError:
                return False
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
            return not (start_time and parsed < start_time) and not (end_time and parsed > end_time)

        def _search_fts():
            if regex or case_sensitive or len(keyword) < 3:
                return None
            with self._store_db() as conn:
                try:
                    conn.row_factory = sqlite3.Row
                    query = '"' + keyword.replace('"', '""') + '"'
                    rows = conn.execute(
                        "SELECT row_json FROM report_logs_fts "
                        "WHERE report_logs_fts MATCH ? AND report_id=?",
                        (query, report_id),
                    ).fetchall()
                except sqlite3.OperationalError:
                    return None
            matches: list[dict[str, Any]] = []
            total = 0
            for record in rows:
                try:
                    row = json.loads(record["row_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if sev_set and str(row.get("severity", "")).lower() not in sev_set:
                    continue
                if node_prefix_l and not str(row.get("hostname", "")).lower().startswith(node_prefix_l):
                    continue
                if not _in_time_range(row):
                    continue
                # Preserve exact legacy substring semantics even if an SQLite
                # tokenizer returns a broader candidate set.
                blob = f"{row.get('timestamp', '')} {row.get('message', '')} {row.get('hostname', '')}"
                if pattern.search(blob):
                    total += 1
                    if len(matches) < limit:
                        matches.append(row)
            return matches, total, total > limit

        indexed = await asyncio.to_thread(_search_fts)
        if indexed is not None:
            return indexed

        def _scan():
            matches: list[dict[str, Any]] = []
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
                    if not _in_time_range(row):
                        continue
                    blob = f"{row.get('timestamp', '')} {row.get('message', '')} {row.get('hostname', '')}"
                    if pattern.search(blob):
                        total += 1
                        if len(matches) < limit:
                            matches.append(row)
            return matches, total, total > limit

        return await asyncio.to_thread(_scan)

    async def enqueue_analysis_job(self, report_id: str, request: dict[str, Any]) -> None:
        created_at = datetime.now(timezone.utc).isoformat()

        def _enqueue() -> None:
            with self._store_db() as conn:
                conn.execute(
                    """
                    INSERT INTO analysis_jobs (
                        report_id, state, request_json, attempts, created_at
                    ) VALUES (?, 'queued', ?, 0, ?)
                    ON CONFLICT(report_id) DO UPDATE SET
                        state='queued', request_json=excluded.request_json,
                        lease_owner=NULL, lease_expires_at=NULL,
                        finished_at=NULL, error_code=NULL
                    """,
                    (report_id, json.dumps(request), created_at),
                )
                conn.commit()

        await asyncio.to_thread(self._retry_locked, _enqueue)

    async def claim_analysis_job(
        self, worker_id: str, lease_seconds: int = 300
    ) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        lease_text = (now + timedelta(seconds=max(30, lease_seconds))).isoformat()

        def _claim() -> dict[str, Any] | None:
            with self._store_db() as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT report_id, request_json, attempts
                    FROM analysis_jobs
                    WHERE state='queued'
                       OR (state='running' AND lease_expires_at < ?)
                    ORDER BY created_at
                    LIMIT 1
                    """,
                    (now_text,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None
                changed = conn.execute(
                    """
                    UPDATE analysis_jobs
                    SET state='running', attempts=attempts+1,
                        lease_owner=?, lease_expires_at=?,
                        started_at=COALESCE(started_at, ?), finished_at=NULL
                    WHERE report_id=? AND (
                        state='queued' OR (state='running' AND lease_expires_at < ?)
                    )
                    """,
                    (worker_id, lease_text, now_text, row["report_id"], now_text),
                )
                conn.commit()
                if changed.rowcount != 1:
                    return None
                try:
                    request = json.loads(row["request_json"])
                except (TypeError, json.JSONDecodeError):
                    request = {}
                return {
                    "report_id": row["report_id"],
                    "request": request,
                    "attempts": int(row["attempts"]) + 1,
                }

        return await asyncio.to_thread(self._retry_locked, _claim)

    async def renew_analysis_job(
        self, report_id: str, worker_id: str, lease_seconds: int = 300
    ) -> bool:
        lease_text = (
            datetime.now(timezone.utc) + timedelta(seconds=max(30, lease_seconds))
        ).isoformat()

        def _renew() -> bool:
            with self._store_db() as conn:
                cursor = conn.execute(
                    """
                    UPDATE analysis_jobs SET lease_expires_at=?
                    WHERE report_id=? AND state='running' AND lease_owner=?
                    """,
                    (lease_text, report_id, worker_id),
                )
                conn.commit()
                return cursor.rowcount == 1

        return await asyncio.to_thread(self._retry_locked, _renew)

    async def finish_analysis_job(
        self, report_id: str, state: str, error_code: str | None = None
    ) -> None:
        if state not in {"succeeded", "failed", "cancelled"}:
            raise ValueError(f"Invalid terminal analysis job state: {state}")
        finished_at = datetime.now(timezone.utc).isoformat()

        def _finish() -> None:
            with self._store_db() as conn:
                conn.execute(
                    """
                    UPDATE analysis_jobs
                    SET state=?, finished_at=?, error_code=?,
                        lease_owner=NULL, lease_expires_at=NULL
                    WHERE report_id=?
                    """,
                    (state, finished_at, error_code, report_id),
                )
                conn.commit()

        await asyncio.to_thread(self._retry_locked, _finish)

    async def save_chunk_state(self, upload_id: str, chunk_index: int, chunk_path: str,
                               filename: str, total_chunks: int) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        def _save():
            with self._store_db() as conn:
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

    async def load_chunk_state(self, upload_id: str) -> dict[str, Any] | None:
        def _load():
            with self._store_db() as conn:
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

    async def get_chunk_paths(self, upload_id: str) -> dict[int, str]:
        def _get_paths():
            with self._store_db() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT chunk_index, chunk_path FROM chunk_uploads WHERE upload_id=? ORDER BY chunk_index",
                    (upload_id,)
                ).fetchall()
                return {row["chunk_index"]: row["chunk_path"] for row in rows}
        return await asyncio.to_thread(_get_paths)

    async def count_chunks(self, upload_id: str) -> int:
        def _count():
            with self._store_db() as conn:
                row = conn.execute("SELECT COUNT(*) as cnt FROM chunk_uploads WHERE upload_id=?", (upload_id,)).fetchone()
                return row[0] if row else 0
        return await asyncio.to_thread(_count)

    async def delete_chunk_state(self, upload_id: str) -> None:
        def _delete():
            with self._store_db() as conn:
                conn.execute("DELETE FROM chunk_uploads WHERE upload_id=?", (upload_id,))
                conn.commit()
        await asyncio.to_thread(_delete)

    async def cleanup_old_chunks(self, older_than_hours: int = 24) -> int:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        cutoff_str = cutoff.isoformat()
        def _cleanup():
            with self._store_db() as conn:
                rows = conn.execute(
                    "SELECT chunk_path FROM chunk_uploads WHERE created_at < ?", (cutoff_str,)
                ).fetchall()
                count = 0
                for row in rows:
                    try:
                        Path(row[0]).unlink(missing_ok=True)
                    except Exception:
                        pass
                    count += 1
                conn.execute("DELETE FROM chunk_uploads WHERE created_at < ?", (cutoff_str,))
                conn.commit()
                return count
        return await asyncio.to_thread(_cleanup)

    async def shutdown(self) -> None:
        """Checkpoint WAL so SQLite state is clean after abrupt parent exit."""

        def _shutdown() -> None:
            if not self.db_path.exists():
                return
            with self._store_db() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()

        await asyncio.to_thread(_shutdown)


def build_store() -> ReportStore:
    backend = (os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
    db_url = os.environ.get("DATABASE_URL")
    if db_url or backend == "postgres":
        # Temporary fallback placeholder.
        # Once PostgreSQL models are fully implemented, this will return PostgresReportStore()
        pass
    
    if backend == "local":
        return LocalReportStore()
    return LocalReportStore()
