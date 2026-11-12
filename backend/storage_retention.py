"""Bounded disk-retention policy and stale-artifact cleanup for local report storage.

SingleStore Cluster Reports can extract to multiple gigabytes on disk and contain
tens of millions of rotated tracelog lines. Keeping every extracted tree and an
unbounded ``tracelogs.sqlite`` index for every historical report allows the local
data directory to grow past 20-30 GB until disk space is exhausted.

This module enforces three complementary bounds without deleting report metadata,
parsed ``report.json`` dashboards, or bounded ``logs.jsonl`` samples:

1. Per-report heavy-artifact caps:
   - ``S2RS_MAX_EXTRACTED_KEEP_GB`` (default ``2.0`` GB, ``<= 0`` disables)
   - ``S2RS_MAX_TIMELINE_ROWS`` (default ``500000`` rows, ``<= 0`` disables)
   - ``S2RS_MAX_TIMELINE_KEEP_MB`` (default ``512`` MB, ``<= 0`` disables)
2. Store-wide heavy-artifact retention budget:
   - ``S2RS_MAX_RETAINED_GB`` (default ``4.0`` GB, ``<= 0`` disables)
   When owned ``extracted/`` trees and ``tracelogs.sqlite`` files exceed the
   budget, failed (``error``) and oversized legacy artifacts are removed first,
   followed by oldest-first LRU eviction of ``extracted/`` (then
   ``tracelogs.sqlite``) on completed reports while keeping ``report.json`` and
   ``logs.jsonl`` intact. External ``import_source_path`` directories are never
   touched.
3. Orphan and staging cleanup:
   Removes orphaned report directories without a SQLite row, stale ``.timeline-*``
   scratch directories, stale staged upload files in ``UPLOAD_DIR``, and expired
   temp directories older than the configured grace window.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_EXTRACTED_KEEP_GB = 2.0
_DEFAULT_TIMELINE_ROWS = 500_000
_DEFAULT_TIMELINE_KEEP_MB = 512.0
_DEFAULT_RETAINED_GB = 4.0
_STALE_TEMP_PREFIXES = ("s2rs-tracelog-", "sdb_report_")


def _env_float(name: str, default: float) -> tuple[bool, float]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return False, default
    try:
        return True, float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using default %s", name, raw, default)
        return False, default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using default %s", name, raw, default)
        return default


def max_extracted_keep_bytes() -> int:
    """Per-report cap on owned ``extracted/`` trees retained for raw search."""
    _, gb = _env_float("S2RS_MAX_EXTRACTED_KEEP_GB", _DEFAULT_EXTRACTED_KEEP_GB)
    if gb <= 0:
        return 0
    return int(gb * 1024**3)


def max_timeline_rows() -> int:
    """Maximum tracelog entries indexed per report into ``tracelogs.sqlite``."""
    rows = _env_int("S2RS_MAX_TIMELINE_ROWS", _DEFAULT_TIMELINE_ROWS)
    return max(0, rows)


def max_timeline_keep_bytes() -> int:
    """Per-report size cap on ``tracelogs.sqlite``."""
    _, mb = _env_float("S2RS_MAX_TIMELINE_KEEP_MB", _DEFAULT_TIMELINE_KEEP_MB)
    if mb <= 0:
        return 0
    return int(mb * 1024**2)


def max_retained_bytes() -> int:
    """Total byte budget for owned heavy artifacts across all saved reports."""
    explicit_retained, gb = _env_float("S2RS_MAX_RETAINED_GB", _DEFAULT_RETAINED_GB)
    if gb <= 0:
        return 0
    retained = int(gb * 1024**3)
    if not explicit_retained:
        explicit_single, single_gb = _env_float(
            "S2RS_MAX_EXTRACTED_KEEP_GB", _DEFAULT_EXTRACTED_KEEP_GB
        )
        if explicit_single and single_gb > 0:
            retained = max(retained, int(single_gb * 1024**3))
    return retained


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() and not path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for root, _dirs, files in os.walk(path, followlinks=False):
            for name in files:
                fp = Path(root) / name
                try:
                    if not fp.is_symlink():
                        total += fp.stat().st_size
                except OSError:
                    pass
    except OSError:
        return total
    return total


def _timeline_files(report_dir: Path) -> list[Path]:
    return [
        report_dir / "tracelogs.sqlite",
        report_dir / "tracelogs.sqlite-wal",
        report_dir / "tracelogs.sqlite-shm",
    ]


def _timeline_bytes(report_dir: Path) -> int:
    total = 0
    for fp in _timeline_files(report_dir):
        if fp.is_file() and not fp.is_symlink():
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def _remove_timeline_files(report_dir: Path) -> int:
    freed = 0
    for fp in _timeline_files(report_dir):
        if fp.is_file() and not fp.is_symlink():
            try:
                sz = fp.stat().st_size
                fp.unlink(missing_ok=True)
                freed += sz
            except OSError:
                logger.warning("Failed removing timeline artifact %s", fp, exc_info=True)
    return freed


def _is_within_dir(candidate: Path, parent: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(parent.resolve())
    except (OSError, ValueError):
        return False


def _remove_owned_extracted(
    store: Any, report_id: str, report_dir: Path, recorded_extracted: str | None
) -> int:
    extracted_dir = report_dir / "extracted"
    freed = _dir_bytes(extracted_dir) if extracted_dir.is_dir() else 0
    if extracted_dir.is_dir():
        shutil.rmtree(extracted_dir, ignore_errors=True)

    # Clear SQLite extracted_path only when it points inside the owned report dir;
    # directory imports point outside and remain valid for raw log search.
    if recorded_extracted:
        try:
            recorded_path = Path(recorded_extracted)
            if _is_within_dir(recorded_path, report_dir):
                with store._store_db() as conn:
                    conn.execute(
                        "UPDATE reports SET extracted_path=NULL WHERE id=?",
                        (report_id,),
                    )
                    conn.commit()
        except Exception:
            logger.warning(
                "Failed clearing extracted_path for %s after eviction",
                report_id,
                exc_info=True,
            )
    return freed


def scrub_report_heavy_artifacts(store: Any, report_id: str) -> int:
    """Remove owned ``extracted/`` and ``tracelogs.sqlite`` files for one report."""
    if not hasattr(store, "reports_dir") or not hasattr(store, "_store_db"):
        return 0
    report_dir = (Path(store.reports_dir) / report_id).resolve()
    if not _is_within_dir(report_dir, Path(store.reports_dir)) or not report_dir.is_dir():
        return 0
    recorded_extracted = None
    try:
        with store._store_db() as conn:
            row = conn.execute(
                "SELECT extracted_path FROM reports WHERE id=?",
                (report_id,),
            ).fetchone()
            if row:
                recorded_extracted = row[0]
    except Exception:
        pass
    freed = _remove_owned_extracted(store, report_id, report_dir, recorded_extracted)
    freed += _remove_timeline_files(report_dir)
    return freed


def _report_rows_and_active_ids(store: Any) -> tuple[dict[str, dict[str, Any]], set[str]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    active_ids: set[str] = set()
    with store._store_db() as conn:
        for row in conn.execute(
            "SELECT id, status, uploaded_at, parsed_at, extracted_path FROM reports"
        ).fetchall():
            rid = str(row[0])
            status = str(row[1] or "")
            rows_by_id[rid] = {
                "id": rid,
                "status": status,
                "uploaded_at": str(row[2] or ""),
                "parsed_at": str(row[3] or ""),
                "extracted_path": row[4],
            }
            if status == "processing":
                active_ids.add(rid)
        try:
            for row in conn.execute(
                "SELECT report_id FROM analysis_jobs WHERE state IN ('queued', 'running')"
            ).fetchall():
                active_ids.add(str(row[0]))
        except Exception:
            pass
    return rows_by_id, active_ids


def _sweep_orphaned_report_dirs(
    reports_dir: Path,
    known_ids: set[str],
    *,
    now: float,
    grace_seconds: float,
) -> int:
    freed = 0
    if not reports_dir.is_dir():
        return 0
    for child in list(reports_dir.iterdir()):
        if not child.is_dir() or child.is_symlink() or child.name.startswith("."):
            continue
        if child.name in known_ids:
            continue
        try:
            age = now - child.stat().st_mtime
        except OSError:
            continue
        if age < grace_seconds:
            continue
        if not _is_within_dir(child, reports_dir):
            continue
        freed += _dir_bytes(child)
        shutil.rmtree(child, ignore_errors=True)
        logger.info("Removed orphaned report directory %s", child.name)
    return freed


def _sweep_stale_timeline_scratch(
    base_dir: Path,
    *,
    now: float,
    grace_seconds: float,
) -> int:
    freed = 0
    if not base_dir.is_dir():
        return 0
    for child in list(base_dir.iterdir()):
        if not child.is_dir() or child.is_symlink():
            continue
        if not child.name.startswith(".timeline-"):
            continue
        try:
            age = now - child.stat().st_mtime
        except OSError:
            continue
        if age < grace_seconds:
            continue
        if not _is_within_dir(child, base_dir):
            continue
        freed += _dir_bytes(child)
        shutil.rmtree(child, ignore_errors=True)
        logger.info("Removed stale timeline scratch directory %s", child.name)
    return freed


def _sweep_stale_uploads(
    upload_dir: Path | None,
    rows_by_id: dict[str, dict[str, Any]],
    active_ids: set[str],
    *,
    now: float,
    grace_seconds: float,
) -> int:
    if upload_dir is None or not upload_dir.is_dir():
        return 0
    try:
        upload_root = upload_dir.resolve()
    except OSError:
        return 0
    freed = 0
    for fp in list(upload_root.iterdir()):
        if not fp.is_file() or fp.is_symlink() or fp.name.startswith("."):
            continue
        try:
            if fp.resolve().parent != upload_root:
                continue
            stat = fp.stat()
        except OSError:
            continue
        report_id = fp.name.split(".", 1)[0]
        if report_id in active_ids:
            continue
        row = rows_by_id.get(report_id)
        terminal = row is not None and row["status"] in {"ready", "error"}
        if not terminal and (now - stat.st_mtime) < grace_seconds:
            continue
        try:
            fp.unlink(missing_ok=True)
            freed += stat.st_size
            logger.info("Removed stale staged upload %s", fp.name)
        except OSError:
            pass
    return freed


def sweep_stale_temp_dirs(
    temp_dir: Path | None = None,
    *,
    max_age_seconds: float = 86_400.0,
) -> int:
    """Remove abandoned ``s2rs-tracelog-*`` / ``sdb_report_*`` temp dirs."""
    root = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
    if not root.is_dir():
        return 0
    now = time.time()
    freed = 0
    for child in list(root.iterdir()):
        if not child.is_dir() or child.is_symlink():
            continue
        if not child.name.startswith(_STALE_TEMP_PREFIXES):
            continue
        try:
            age = now - child.stat().st_mtime
        except OSError:
            continue
        if age < max_age_seconds:
            continue
        freed += _dir_bytes(child)
        shutil.rmtree(child, ignore_errors=True)
    return freed


def enforce_storage_retention(
    store: Any,
    *,
    protect_report_id: str | None = None,
    upload_dir: Path | None = None,
    orphan_grace_seconds: float = 300.0,
    temp_grace_seconds: float = 3600.0,
    upload_grace_seconds: float = 3600.0,
) -> dict[str, int]:
    """Enforce per-report and store-wide bounds on heavy report artifacts.

    Never deletes ``report.json``, ``logs.jsonl``, SQLite ``reports`` metadata,
    external ``import_source_path`` directories, or active ``processing`` jobs.
    """
    summary = {"freed_bytes": 0, "evicted_reports": 0, "total_heavy_bytes_after": 0}
    if not hasattr(store, "reports_dir") or not hasattr(store, "_store_db"):
        return summary

    reports_dir = Path(store.reports_dir)
    base_dir = Path(store.base_dir)
    if not reports_dir.is_dir():
        return summary

    now = time.time()
    rows_by_id, active_ids = _report_rows_and_active_ids(store)

    freed = 0
    freed += _sweep_orphaned_report_dirs(
        reports_dir, set(rows_by_id), now=now, grace_seconds=orphan_grace_seconds
    )
    freed += _sweep_stale_timeline_scratch(
        base_dir, now=now, grace_seconds=temp_grace_seconds
    )
    freed += _sweep_stale_uploads(
        upload_dir, rows_by_id, active_ids, now=now, grace_seconds=upload_grace_seconds
    )

    per_extracted_cap = max_extracted_keep_bytes()
    per_timeline_cap = max_timeline_keep_bytes()
    total_cap = max_retained_bytes()

    evicted_ids: set[str] = set()
    entries: list[dict[str, Any]] = []

    for child in list(reports_dir.iterdir()):
        if not child.is_dir() or child.is_symlink() or child.name.startswith("."):
            continue
        rid = child.name
        if rid in active_ids:
            continue
        row = rows_by_id.get(rid)
        if row is None:
            continue

        ext_dir = child / "extracted"
        ext_bytes = _dir_bytes(ext_dir) if ext_dir.is_dir() else 0
        tl_bytes = _timeline_bytes(child)

        if row["status"] == "error":
            if ext_bytes or tl_bytes:
                freed += _remove_owned_extracted(store, rid, child, row.get("extracted_path"))
                freed += _remove_timeline_files(child)
                evicted_ids.add(rid)
            continue

        if ext_bytes > 0 and (per_extracted_cap <= 0 or ext_bytes > per_extracted_cap):
            freed += _remove_owned_extracted(store, rid, child, row.get("extracted_path"))
            ext_bytes = 0
            evicted_ids.add(rid)

        if tl_bytes > 0 and (per_timeline_cap <= 0 or tl_bytes > per_timeline_cap):
            freed += _remove_timeline_files(child)
            tl_bytes = 0
            evicted_ids.add(rid)

        if ext_bytes > 0 or tl_bytes > 0:
            sort_ts = row.get("parsed_at") or row.get("uploaded_at") or ""
            entries.append(
                {
                    "id": rid,
                    "dir": child,
                    "extracted_path": row.get("extracted_path"),
                    "extracted_bytes": ext_bytes,
                    "timeline_bytes": tl_bytes,
                    "sort_key": (1 if rid == protect_report_id else 0, sort_ts, rid),
                }
            )

    total_heavy = sum(e["extracted_bytes"] + e["timeline_bytes"] for e in entries)
    if total_heavy > total_cap:
        entries.sort(key=lambda item: item["sort_key"])
        for entry in entries:
            if total_heavy <= total_cap:
                break
            rid = entry["id"]
            if entry["extracted_bytes"] > 0:
                removed = _remove_owned_extracted(
                    store, rid, entry["dir"], entry["extracted_path"]
                )
                freed += removed
                total_heavy = max(0, total_heavy - entry["extracted_bytes"])
                entry["extracted_bytes"] = 0
                evicted_ids.add(rid)
            if total_heavy <= total_cap:
                break
            if entry["timeline_bytes"] > 0:
                removed = _remove_timeline_files(entry["dir"])
                freed += removed
                total_heavy = max(0, total_heavy - entry["timeline_bytes"])
                entry["timeline_bytes"] = 0
                evicted_ids.add(rid)

    summary["freed_bytes"] = freed
    summary["evicted_reports"] = len(evicted_ids)
    summary["total_heavy_bytes_after"] = total_heavy
    if freed > 0:
        logger.info(
            "Storage retention reclaimed %.1f MB across %d report(s); "
            "retained heavy artifacts=%.1f MB (cap=%.1f MB)",
            freed / 1024**2,
            len(evicted_ids),
            total_heavy / 1024**2,
            total_cap / 1024**2,
        )
    return summary
