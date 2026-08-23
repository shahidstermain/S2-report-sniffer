"""
Enhanced parsers for SingleStore diagnostic report tar.gz bundles.
Walks the extracted directory tree and normalizes data into a queryable model.
Implements schema-grounded intelligence with doc-linked recommendations.
"""
import json
import re
import os
import gzip
import bz2
import lzma
import tarfile
import zipfile
import tempfile
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

_PROCESSLIST_MISSING = object()

import units
from archive_security import (
    ArchiveLimits,
    find_escaping_symlink,
    path_is_within_root,
    require_scratch_capacity,
    safe_member_path,
    validate_member_count,
    validate_member_size,
    validate_zip_info,
)

logger = logging.getLogger(__name__)

# Safety limits to prevent memory exhaustion
MAX_RAW_LOGS = 50000
MAX_EXTRACTED_BYTES = 50 * 1024 * 1024 * 1024  # Cap log accumulation during parsing
MAX_JSON_FILE_BYTES_DEFAULT = 25 * 1024 * 1024
MAX_JSON_FILE_BYTES_BY_NAME = {
    # Large clusters easily exceed 8 MiB; skipping the whole collector empties
    # the Partitions view and hides skew. Keep a hard ceiling, not a tiny one.
    "showPartitions.json": 50 * 1024 * 1024,
    "informationSchemaMvEvents.json": 25 * 1024 * 1024,
    "informationSchemaMvQueries.json": 25 * 1024 * 1024,
    "informationSchemaProcesslist.json": 20 * 1024 * 1024,
    "informationSchemaMvProcesslist.json": 20 * 1024 * 1024,
    "informationSchemaTableStatistics.json": 25 * 1024 * 1024,
    "informationSchemaTables.json": 25 * 1024 * 1024,
    "informationSchemaMvBackupHistory.json": 10 * 1024 * 1024,
    "informationSchemaColumnarSegments.json": 100 * 1024 * 1024,
}

MAX_MV_EVENTS_ROWS = 5000
MAX_BLOCKED_QUERIES_ROWS = 2000
MAX_WORKLOAD_MANAGEMENT_ROWS = 2000
MAX_REPLICATION_STATUS_ROWS = 5000
MAX_TABLE_STATISTICS_ROWS = 5000
MAX_INFORMATION_SCHEMA_TABLES_ROWS = 10000
MAX_RESOURCE_POOLS_ROWS = 2000
MAX_DATABASE_DISK_USAGE_ROWS = 5000
MAX_BACKUP_HISTORY_ROWS = 5000
MAX_VERSION_HISTORY_ROWS = 5000
MAX_AVAILABILITY_GROUPS_ROWS = 5000
MAX_USERS_ROWS = 5000
MAX_PIPELINES_ROWS = 5000
MAX_DMESG_EVENTS = 2000
MAX_PARTITION_ROWS_PER_DB = 5000
MAX_PROCESSLIST_ROWS = 200
ANALYSIS_REVISION = 3
_LOOPBACK_IFACES = frozenset({"lo", "lo0", "localhost"})
_OPEN_TRX_STATES = frozenset({"running", "active", "open", "locked"})
_MASTER_ROLES = frozenset({"master", "primary", "0"})
_REPLICA_ROLES = frozenset({"slave", "replica", "secondary", "1"})

# Columnar segment files are numerous on real clusters; the default 2k pool cap
# undercounts referenced bytes and falsely inflates blobs-vs-referenced delta.
MAX_COLUMNAR_SEGMENTS_ROWS = 1_000_000
# Streaming JSON reader chunk size. Exposed so tests can force a complete
# object to land on a chunk boundary without writing multi-megabyte fixtures.
_STREAM_JSON_CHUNK_BYTES = 2 * 1024 * 1024


def _cap_rows(rows: list, max_rows: int) -> list:
    if not isinstance(rows, list):
        return []
    if max_rows <= 0:
        return rows
    return rows[:max_rows]


def _json_file_size_limit(filename: str) -> int:
    return int(MAX_JSON_FILE_BYTES_BY_NAME.get(filename, MAX_JSON_FILE_BYTES_DEFAULT))


# Explicit sync→async transition phrases observed in SingleStore tracelogs/docs.
# Avoid broad "replication.*async" — routine async-replication text is not a transition.
_ASYNC_TRANSITION_RE = re.compile(
    r"(?:"
    r"from\s+sync(?:hronous)?\s+to\s+async(?:hronous)?"
    r"|sync(?:hronous)?\s*(?:->|→)\s*async(?:hronous)?"
    r"|transition(?:ed|ing)?\s+from\s+sync(?:hronous)?\s+to\s+async(?:hronous)?"
    r")",
    re.I,
)

# Observed MV_EVENTS enums (prefer exact match over fuzzy keyword filters).
_NODE_EVENT_ENUMS = frozenset({
    "NODE_OFFLINE", "NODE_ONLINE", "NODE_DETACHED", "NODE_STARTING", "NODE_ATTACHING",
    "LEAF_ADD", "NEW_MASTER_AGGREGATOR", "LEAF_OFFLINE", "LEAF_ONLINE",
    "MASTER_FAILOVER", "AGGREGATOR_OFFLINE", "AGGREGATOR_ONLINE",
    "NODE_FAIL", "NODE_RECOVER", "NODE_RECOVERY",
})
_REBALANCE_EVENT_ENUMS = frozenset({
    "REBALANCE_STARTED", "REBALANCE_FINISHED", "REBALANCE_START", "REBALANCE_COMPLETE",
})
_OPERATIONAL_EVENT_ENUMS = frozenset({
    "CONSENSUS_STATE_TRANSITION", "CONSENSUS_ELECTION",
    "PIPELINE_STOPPED", "SYSTEM_VAR_CHANGED", "WORKLOAD_THROTTLE",
})
_MV_EVENTS_ALLOWLIST = _NODE_EVENT_ENUMS | _REBALANCE_EVENT_ENUMS | _OPERATIONAL_EVENT_ENUMS


def _is_async_transition_message(message: str) -> bool:
    return bool(_ASYNC_TRANSITION_RE.search(str(message or "")))


def _parse_lsn_pair(lsn: str | None) -> tuple[int, int] | None:
    if lsn is None:
        return None
    text = str(lsn).strip()
    if not text or text.upper() == "NULL":
        return None
    if ":" not in text:
        return None
    segment, offset = text.split(":", 1)
    try:
        return int(segment), int(offset)
    except ValueError:
        return None


def _lsn_position_delta(primary_lsn: str | None, replica_lsn: str | None) -> float | None:
    """Return commit-position delta when both LSNs share a segment (lag proxy)."""
    primary = _parse_lsn_pair(primary_lsn)
    replica = _parse_lsn_pair(replica_lsn)
    if not primary or not replica or primary[0] != replica[0]:
        return None
    return float(max(0, primary[1] - replica[1]))


def _replication_row_lag_sec(row: dict) -> float:
    """Return directly reported lag seconds, never a catch-up estimate."""
    for key in (
        "LAG_SECONDS", "Lag_seconds", "lag_seconds", "LagSeconds",
        "SECONDS_BEHIND_MASTER", "Seconds_Behind_Master", "seconds_behind_master",
    ):
        value = row.get(key)
        if value in (None, "", "NULL"):
            continue
        try:
            lag = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        if lag >= 0:
            return lag
    return -1.0


def _replication_metric(row: dict, *keys: str) -> float | None:
    """Read a non-negative replication metric without turning NULL into zero."""
    for key in keys:
        value = row.get(key)
        if value in (None, "", "NULL"):
            continue
        try:
            number = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        if number >= 0:
            return number
    return None


def _parse_timestamp(value) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                dt = datetime.strptime(text[:26], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hour_bucket(value) -> str:
    dt = _parse_timestamp(value)
    if dt is not None:
        return dt.strftime("%Y-%m-%d %H")
    text = str(value or "").strip()
    if "T" in text and len(text) >= 13:
        return text[:13].replace("T", " ")
    return text[:13] if len(text) >= 13 else text


def _disk_usage_bytes_from_row(row: dict) -> float:
    disk_keys = (
        "TOTAL_DISK_USAGE_BYTES",
        "total_disk_usage_bytes",
        "DISK_USAGE_BYTES",
        "disk_usage_bytes",
        "DISK_BYTES",
        "disk_bytes",
    )
    for key in disk_keys:
        value = _safe_float_val(row.get(key))
        if value > 0:
            return value
    gb_keys = (
        "TOTAL_DISK_USAGE_GB",
        "total_disk_usage_gb",
        "DISK_USAGE_GB",
        "disk_usage_gb",
    )
    for key in gb_keys:
        value = _safe_float_val(row.get(key))
        if value > 0:
            return value * (1024 ** 3)
    return 0.0


def _is_physical_df_mount(entry: dict) -> bool:
    filesystem = str(entry.get("filesystem", "")).strip().lower()
    mounted_on = str(entry.get("mounted_on", "")).strip().lower()
    if not filesystem or filesystem in {"tmpfs", "devtmpfs", "overlay", "squashfs"}:
        return False
    if mounted_on.startswith(("/proc", "/sys", "/dev", "/run")):
        return False
    return True


def _row_elapsed_sec(row: dict) -> float:
    return _safe_float_val(
        row.get("ELAPSED_TIME", row.get("elapsed_time", row.get("ElapsedTime",
                row.get("Time", row.get("TIME", row.get("ELAPSED_TIME_S", 0))))))
    )


def _query_text_from_row(row: dict) -> str:
    value = row.get(
        "QUERY_TEXT",
        row.get(
            "query_text",
            row.get("Info", row.get("INFO", row.get("info", ""))),
        ),
    )
    text = str(value or "").strip()
    return "" if text.upper() in {"NULL", "NONE", "N/A"} else text


def _processlist_command(row: dict) -> str:
    return str(row.get("Command", row.get("COMMAND", row.get("command", "")))).strip().lower()


def _transaction_state(row: dict) -> str:
    raw = row.get(
        "TRANSACTION_STATE",
        row.get("TRX_STATE", row.get("trx_state", row.get("Transaction_State", ""))),
    )
    text = str(raw or "").strip().lower()
    return "" if text in {"null", "none", "n/a"} else text


def _is_loopback_iface(name: str) -> bool:
    iface = str(name or "").strip().lower()
    return iface in _LOOPBACK_IFACES or iface.startswith("lo:")


def _is_active_query_row(row: dict) -> bool:
    """True only for processlist rows that represent an executing user query.

    SHOW/MV_PROCESSLIST TIME is seconds in the current state. Sleeping sessions,
    replication/system commands, and rows without SQL must not be interpreted as
    query runtime.
    """
    if _processlist_command(row) not in {"query", "execute"}:
        return False
    return bool(_query_text_from_row(row))


def _is_stale_query_row(elapsed: float, query_text: str, normalized: str) -> bool:
    """Drop MV_QUERIES/processlist artifacts (NULL query text, multi-day elapsed)."""
    if elapsed >= 86400 * 7:
        return True
    if elapsed >= 300 and not query_text.strip() and not normalized:
        return True
    return False


def _stream_extract_rows_from_json_file(fpath: str, max_rows: int) -> list:
    """Extract table rows from oversized sdb-report JSON without loading the whole file."""
    if max_rows <= 0:
        return []
    rows: list = []
    decoder = json.JSONDecoder()
    marker = '"rows"'
    buf = ""
    scan_pos = 0
    array_pos: int | None = None
    chunk_size = _STREAM_JSON_CHUNK_BYTES
    with open(fpath, encoding="utf-8", errors="replace") as fh:
        while len(rows) < max_rows:
            if array_pos is None:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                buf += chunk
                while len(rows) < max_rows:
                    idx = buf.find(marker, scan_pos)
                    if idx < 0:
                        scan_pos = max(0, len(buf) - len(marker) - 32)
                        break
                    bracket = buf.find("[", idx)
                    if bracket < 0:
                        scan_pos = idx + 1
                        continue
                    array_pos = bracket + 1
                    scan_pos = array_pos
                    break
                continue

            while array_pos < len(buf) and len(rows) < max_rows:
                while array_pos < len(buf) and buf[array_pos] in " \t\r\n,":
                    array_pos += 1
                if array_pos >= len(buf):
                    break
                if buf[array_pos] == "]":
                    array_pos = None
                    scan_pos = 0
                    break
                try:
                    obj, end = decoder.raw_decode(buf, array_pos)
                except json.JSONDecodeError:
                    chunk = fh.read(chunk_size)
                    if not chunk:
                        return rows
                    buf += chunk
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                array_pos = end

            if len(rows) >= max_rows:
                return rows

            # A complete object at the end of the current buffer used to leave
            # array_pos == len(buf) with no further read(), spinning forever
            # while more rows remained on disk. Read the next chunk instead.
            if array_pos is not None and array_pos >= len(buf):
                chunk = fh.read(chunk_size)
                if not chunk:
                    return rows
                if array_pos > 0:
                    buf = buf[array_pos:]
                    array_pos = 0
                buf += chunk
                continue

            if array_pos is not None and array_pos > 1_000_000:
                buf = buf[array_pos:]
                array_pos = 0
                scan_pos = 0
            elif array_pos is None and scan_pos > 1_000_000:
                buf = buf[scan_pos:]
                scan_pos = 0
    return rows


def _load_sdb_json_rows(node_path: str, filename: str, row_cap: int) -> list:
    fpath = os.path.join(node_path, filename)
    if not os.path.exists(fpath):
        return []
    try:
        size = os.path.getsize(fpath)
        limit = _json_file_size_limit(filename)
        if size > limit:
            logger.warning(
                "Streaming oversized JSON file %s (%s bytes > %s bytes)",
                filename, size, limit,
            )
            return _cap_rows(_stream_extract_rows_from_json_file(fpath, row_cap), row_cap)
        data = parse_json_file(node_path, filename)
        return _cap_rows(_extract_rows_from_json_data(data), row_cap)
    except Exception as exc:
        logger.debug("parser: ignoring non-fatal error", exc_info=exc)
        return []

NODE_DIR_PATTERN = re.compile(r'^(.+?)-(MA|CA|LEAF|AGGREGATOR|MASTER)$')

# Real sdb-report bundles name node dirs by host or UUID; role suffixes vary by
# deployment tool (MasterAggregator, ChildAggregator, Leaf, -MA, etc.). When the
# name carries no -MA/-CA/-LEAF suffix we fall back to detecting node directories
# by the collector output they contain (shared dir, UUID, or host-based subdirs),
# so topology is still populated instead of silently reporting 0 nodes.
_NODE_DIR_SUFFIX_ROLES = (
    ("-masteraggregator", "MA"),
    ("-master-aggregator", "MA"),
    ("-childaggregator", "CA"),
    ("-child-aggregator", "CA"),
    ("-leaf", "LEAF"),
    ("-aggregator", "AGGREGATOR"),
    ("-master", "MASTER"),
)
_NODE_SIGNAL_FILES = frozenset({
    "informationSchemaMvNodes.json", "memsqlConfig.json", "memsqlctlInfo.json",
    "showVariables.json", "showClusterStatus.json", "clusterTopology.json",
    "psutil.json", "memsqlctlVersion.json", "showDatabasesExtended.json",
})
_NODE_SIGNAL_SUBDIRS = frozenset({
    "memsqlTracelogs", "free", "df", "top", "sysctl", "dmesg", "uptime",
})
_NODE_SIGNAL_SUFFIXES = ("_stdout", ".tsv")
_NON_NODE_DIR_NAMES = frozenset({"globalInfo", "_nested"})
_CENTRALIZED_ROLE_PRIORITY = {"MA": 0, "MASTER": 0, "CA": 1, "AGGREGATOR": 1, "LEAF": 2, "NODE": 3}


def _format_from_extension(archive_path: str) -> str:
    """Case-insensitive archive type from filename extension only."""
    lower = archive_path.lower()
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        return "tar.gz"
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith(".tar"):
        return "tar"
    if lower.endswith(".gz"):
        return "gz"
    return "unknown"


def _read_file_header(path: str, nbytes: int = 8) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(nbytes)
    except OSError:
        return b""


def _sniff_archive_format(archive_path: str) -> str | None:
    """Detect archive kind from magic bytes (None when inconclusive)."""
    header = _read_file_header(archive_path, 8)
    if header.startswith(b"\x1f\x8b"):
        return "tar.gz"
    if header.startswith(b"PK"):
        return "zip"
    if header.startswith(b"!<arch>"):
        return "deb"
    if os.path.isfile(archive_path) and tarfile.is_tarfile(archive_path):
        return "tar"
    return None


def _detect_archive_format(archive_path: str, *, sniff: bool = True) -> str:
    """Detect archive type from extension, optionally corrected by magic-byte sniffing."""
    ext_format = _format_from_extension(archive_path)
    if not sniff or not os.path.isfile(archive_path):
        return ext_format
    sniffed = _sniff_archive_format(archive_path)
    if sniffed == "deb":
        return "deb"
    if sniffed == "zip":
        return "zip"
    if sniffed == "tar.gz":
        # Gzip-compressed payloads are often misnamed .tar (missing .gz suffix).
        if ext_format in {"tar", "tar.gz", "tgz", "gz", "unknown"}:
            return "tar.gz" if ext_format != "gz" else "gz"
    if sniffed == "tar":
        return "tar"
    return ext_format


def ensure_supported_archive_format(archive_path: str) -> str:
    """Return a supported archive format or raise ValueError with a actionable message."""
    fmt = _detect_archive_format(archive_path)
    if fmt == "deb":
        raise ValueError(
            "This file looks like a Debian package (.deb), not an sdb-report archive. "
            "Upload a diagnostic bundle (.tar.gz, .tgz, .zip, or .tar) from sdb-report instead."
        )
    if fmt == "unknown":
        raise ValueError(f"Unsupported archive format: {os.path.basename(archive_path)}")
    return fmt


def _node_role_from_dir_name(name: str) -> tuple[str, str] | None:
    """Return (hostname, role) when the directory name encodes a node role."""
    m = NODE_DIR_PATTERN.match(name)
    if m:
        return m.group(1), m.group(2)
    lower = name.lower()
    for suffix, role in _NODE_DIR_SUFFIX_ROLES:
        if lower.endswith(suffix):
            return name[: -len(suffix)], role
    return None


def _looks_like_node_dir(dir_path: str) -> bool:
    """Detect a per-node collector directory by its contents (name-agnostic)."""
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return False
    for entry in entries:
        if entry in _NODE_SIGNAL_FILES:
            return True
        low = entry.lower()
        if low.endswith("memsql.log"):
            return True
        if low.endswith(_NODE_SIGNAL_SUFFIXES):
            return True
        if entry in _NODE_SIGNAL_SUBDIRS and os.path.isdir(os.path.join(dir_path, entry)):
            return True
    return False


def _looks_like_report_root(dir_path: str) -> bool:
    try:
        if os.path.isdir(os.path.join(dir_path, "globalInfo")):
            return True
        for child in os.listdir(dir_path):
            if child in _NON_NODE_DIR_NAMES:
                continue
            cpath = os.path.join(dir_path, child)
            if not os.path.isdir(cpath):
                continue
            if _node_role_from_dir_name(child) is not None:
                return True
            if _looks_like_node_dir(cpath):
                return True
    except OSError:
        return False
    return False


def _normalize_mv_node_type(node: dict) -> str:
    """Normalize TYPE/ROLE strings like 'Master Aggregator' → MA, 'Leaf' → LEAF."""
    raw = (
        node.get("TYPE") or node.get("type") or node.get("Role")
        or node.get("ROLE") or node.get("role") or ""
    )
    upper = str(raw).strip().upper()
    if upper in ("LEAF",):
        return "LEAF"
    if upper in ("CA", "MA", "AGGREGATOR", "MASTER"):
        return upper
    if "LEAF" in upper:
        return "LEAF"
    if "CHILD" in upper and "AGG" in upper:
        return "CA"
    if "MASTER" in upper and "AGG" in upper:
        return "MA"
    if "AGG" in upper:
        return "AGGREGATOR"
    if "MASTER" in upper:
        return "MASTER"
    return upper


def _extract_rows_from_json_data(data) -> list:
    """Extract table rows from sdb-report JSON (dict, list, MemsqlID wrappers)."""
    if not data:
        return []
    if isinstance(data, list):
        rows = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("rows"), list):
                rows.extend(item["rows"])
                continue
            for val in item.values():
                if isinstance(val, dict) and isinstance(val.get("rows"), list):
                    rows.extend(val["rows"])
        return rows
    if isinstance(data, dict):
        if isinstance(data.get("rows"), list):
            return data["rows"]
        rows = []
        for val in data.values():
            if isinstance(val, dict) and isinstance(val.get("rows"), list):
                rows.extend(val["rows"])
            elif isinstance(val, dict):
                for subval in val.values():
                    if isinstance(subval, dict) and isinstance(subval.get("rows"), list):
                        rows.extend(subval["rows"])
        return rows
    return []


def _as_row_list(value) -> list:
    """Coerce persisted table payloads to a list (handles legacy ``{rows: [...]}`` wrappers)."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        rows = value.get("rows")
        if isinstance(rows, list):
            return rows
    return []


def _centralized_source_priority(role: str) -> int:
    return _CENTRALIZED_ROLE_PRIORITY.get(str(role or "").upper(), 4)

LOG_LINE_PATTERN = re.compile(
    r'(\d+)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(INFO|WARN|WARNING|ERROR|FATAL|NOTICE|DEBUG):\s*(.*)',
    re.DOTALL
)

# ─── Critical log patterns for auto-detection (lazy-init) ──────────
_critical_log_patterns_cached = None

def get_critical_log_patterns():
    global _critical_log_patterns_cached
    if _critical_log_patterns_cached is None:
        _critical_log_patterns_cached = [
            {"pattern": re.compile(
                r'(Nonfatal buffer manager memory allocation failure|out of memory|\bOOM\b|killed process)',
                re.I,
            ), "category": "oom",
             "title": "OOM Kill Detected", "severity": "critical",
             "conclusion": "SingleStore process was killed by the Linux OOM-killer. This causes partial or full cluster unavailability. Increase RAM, reduce maximum_memory, or add leaf nodes.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/memory-management/"},
            {"pattern": re.compile(r'(disk full|no space left)', re.I), "category": "disk",
             "title": "Disk Full Detected", "severity": "critical",
             "conclusion": "Write operations failed due to full disk. This can corrupt in-flight transactions. Immediate disk cleanup required.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/node-management/adding-disk-space/"},
            {"pattern": re.compile(r'(replication error|replication link down)', re.I), "category": "replication",
             "title": "Replication Link Failure", "severity": "critical",
             "conclusion": "A replication link failure means redundancy is degraded. Investigate network between node pairs and check MV_REPLICATION_STATUS.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/data-redundancy/replication/"},
            {"pattern": re.compile(r'(backtrace|segmentation fault|assert failed|SIGSEGV)', re.I), "category": "crash",
             "title": "Crash/Backtrace Detected", "severity": "critical",
             "conclusion": "A crash or assertion failure occurred. The backtrace file must be sent to SingleStore Support for analysis.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/"},
            {"pattern": re.compile(r'(lock wait timeout|lock timeout exceeded|\bdeadlock\b)', re.I), "category": "locking",
             "title": "Lock Wait Timeout", "severity": "warning",
             "conclusion": "A transaction could not acquire a row or table lock within the timeout period. Cross-reference MV_BLOCKED_QUERIES.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/"},
            {"pattern": re.compile(r'(failed to merge|merge error)', re.I), "category": "columnstore",
             "title": "Columnstore Merge Error", "severity": "warning",
             "conclusion": "Columnstore background merge encountered an error. Check disk space and I/O health on the affected leaf node.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/introduction/concepts/columnstore/background-merge/"},
            {"pattern": re.compile(r'(ETIMEDOUT|Connection timed out)', re.I), "category": "network",
             "title": "Network Timeout", "severity": "warning",
             "conclusion": "Network operations are timing out. This can indicate network congestion or firewall issues between nodes.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/troubleshooting/network-troubleshooting/"},
            {"pattern": re.compile(r'(fsync is behind|slow fsync)', re.I), "category": "storage",
             "title": "Slow Disk I/O (fsync)", "severity": "warning",
             "conclusion": "Disk fsync operations are lagging, indicating storage I/O bottlenecks. Check disk health and IOPS.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/troubleshooting/disk-troubleshooting/"},
            {"pattern": re.compile(r'(Retry loop is stalling|stalling retry loop)', re.I), "category": "background_tasks",
             "title": "Retry Loop Stalling", "severity": "warning",
             "conclusion": "A background retry loop is stalling, likely due to resource contention, slow fsync, or internal lock waits.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/troubleshooting/"},
            {"pattern": re.compile(
                r'(compilation failed|compilation error|failed to finalize asynchronous compilation)',
                re.I,
            ), "category": "compilation",
             "title": "Query Compilation Issue", "severity": "warning",
             "conclusion": "Issues with query compilation. Review query complexity and aggregator memory.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/troubleshooting/query-performance/"},
            {"pattern": re.compile(r'(backup failed|backup error)', re.I), "category": "backup",
             "title": "Backup Failure", "severity": "critical",
             "conclusion": "A database backup operation failed. Check backup destination availability and permissions.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/backup-and-restore/"},
            {"pattern": re.compile(r'(starting up, version|starting up version|process initialized|memsqld started)', re.I), "category": "restart",
             "title": "Process Restart Detected", "severity": "warning",
             "conclusion": "SingleStore process restarted on this node. Check for preceding crash, OOM kill, or manual restart in the tracelogs immediately before this entry.",
             "doc_link": "https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/"},
        ]
    return _critical_log_patterns_cached


_dmesg_patterns_cached = None

def get_dmesg_patterns():
    global _dmesg_patterns_cached
    if _dmesg_patterns_cached is None:
        _dmesg_patterns_cached = [
            {"pattern": re.compile(r'(Out of memory|Killed process|oom_reaper)', re.I), "category": "oom", "severity": "critical",
             "title": "OOM Kill in Kernel", "conclusion": "Linux OOM-killer terminated a process. Check which process was killed and review memory allocation."},
            {"pattern": re.compile(r'(EXT4-fs error|I/O error|SCSI error|hard resetting link)', re.I), "category": "storage_fault", "severity": "critical",
             "title": "Storage Hardware Error", "conclusion": "Disk or filesystem errors detected. This can lead to data corruption. Check physical drive health immediately."},
            {"pattern": re.compile(r'(nf_conntrack|table full)', re.I), "category": "network", "severity": "warning",
             "title": "Network Connection Tracking Full", "conclusion": "nf_conntrack table full causes packet drops. Increase net.nf_conntrack_max or reduce connection churn."},
            {"pattern": re.compile(r'(soft lockup|RCU stall|hung_task)', re.I), "category": "cpu", "severity": "critical",
             "title": "CPU Scheduler Issue", "conclusion": "Soft lockup or RCU stall indicates the CPU was unable to schedule tasks. This can cause node unresponsiveness."},
            {"pattern": re.compile(r'(transparent hugepage)', re.I), "category": "thp", "severity": "warning",
             "title": "THP Warning in Kernel", "conclusion": "Transparent Huge Pages can cause latency spikes. Ensure THP is set to 'never'."},
            {"pattern": re.compile(r'(ETIMEDOUT|timeout)', re.I), "category": "network", "severity": "warning",
             "title": "Kernel Network Timeout", "conclusion": "The kernel detected network timeouts. Check network hardware and driver status."},
        ]
    return _dmesg_patterns_cached


def _normalize_archive_exception(exc: Exception, archive_path: str) -> Exception:
    message = str(exc).lower()
    archive_name = os.path.basename(archive_path)
    if isinstance(exc, MemoryError):
        return ValueError(f"Archive exceeds maximum safe extraction size: {archive_name}")
    if isinstance(exc, zipfile.BadZipFile):
        return ValueError(f"Corrupted or unsupported zip archive: {archive_name}")
    if (
        isinstance(exc, (tarfile.ReadError, tarfile.CompressionError, EOFError, gzip.BadGzipFile))
        or "end-of-stream marker" in message
        or "unexpected end of data" in message
        or "not a gzip file" in message
        or "empty file" in message
        or "truncated" in message
    ):
        if archive_path.endswith((".tar.gz", ".tgz", ".gz")):
            return ValueError(f"Corrupted or incomplete gzip archive: {archive_name}")
        if archive_path.endswith(".tar"):
            return ValueError(f"Corrupted or incomplete tar archive: {archive_name}")
        return ValueError(f"Corrupted or incomplete archive: {archive_name}")
    return exc


def _validate_extract_path(base_dir: str, member_name: str) -> str:
    base_resolved = Path(base_dir).resolve()
    # The archive's own root / current-directory entry ("." or "./") is a benign
    # reference to the extraction directory itself. Standard `tar czf <file> .`
    # bundles (which is how many sdb-report tarballs are packaged) include it as
    # the first member; resolve it to the base dir so callers create/skip it
    # rather than rejecting the entire archive.
    limits = ArchiveLimits.from_env(max_extracted_bytes=MAX_EXTRACTED_BYTES)
    safe_path = safe_member_path(member_name.strip(), limits)
    if str(safe_path) == '.':
        return str(base_resolved)
    resolved = (base_resolved / Path(*safe_path.parts)).resolve()
    # Robust containment check (handles case-insensitive filesystems and symlink
    # resolution) instead of a string prefix comparison (S-02 / S-03).
    if resolved != base_resolved and not resolved.is_relative_to(base_resolved):
        raise ValueError(f"Path escape attempt: {member_name}")
    return str(resolved)


def _prepare_regular_file_target(resolved_path: str, incoming_size: int) -> bool:
    """Decide whether to write ``resolved_path`` for a duplicate-safe extract.

    Duplicate archive members are common (recursive tar producers, repaired
    zips). Blind first-entry-wins can hide a later real collector behind an
    earlier empty stub (e.g. ``informationSchemaMvNodes.json`` = ``[]``), and
    zip extraction previously crashed with ``FileExistsError`` on ``O_EXCL``.

    Policy:
    - Never follow/replace symlinks, directories, or special files.
    - Prefer the larger payload when a regular file already exists (keeps a
      real collector over an empty stub; keeps a real collector when a later
      empty stub appears).
    - Unlink then recreate with ``O_EXCL`` so we never overwrite in place.
    """
    if not os.path.lexists(resolved_path):
        return True
    # Refuse to clobber anything that is not a plain regular file.
    if os.path.islink(resolved_path) or os.path.isdir(resolved_path):
        return False
    if not os.path.isfile(resolved_path):
        return False
    try:
        existing_size = os.path.getsize(resolved_path)
    except OSError:
        return False
    if int(incoming_size or 0) <= existing_size:
        return False
    try:
        os.unlink(resolved_path)
    except OSError:
        return False
    return True


def _extract_tar_members(tf: tarfile.TarFile, extract_dir: str, extracted_bytes: dict) -> None:
    limits = ArchiveLimits.from_env(max_extracted_bytes=MAX_EXTRACTED_BYTES)
    member_count = 0
    for member in tf:
        member_count += 1
        validate_member_count(member_count, limits)
        validate_member_size(int(member.size or 0), limits)
        # Always write to the validated/sanitized path rather than relying on
        # tarfile to honor the member's (possibly malicious) name (S-02 / S-03).
        resolved_path = _validate_extract_path(extract_dir, member.name)
        if member.isdir():
            os.makedirs(resolved_path, exist_ok=True)
            continue
        # Skip symlinks, hardlinks, and special files (devices/fifos): they are a
        # path-escape and link-following vector and are never needed for parsing.
        if not member.isfile():
            continue
        os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
        src = tf.extractfile(member)
        if src is None:
            continue
        # Prefer a larger later member over an earlier empty/stub duplicate;
        # never follow or overwrite non-regular extraction targets.
        if not _prepare_regular_file_target(resolved_path, int(member.size or 0)):
            src.close()
            continue
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        with src, os.fdopen(os.open(resolved_path, flags, 0o600), 'wb') as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                extracted_bytes['total'] += len(chunk)
                if extracted_bytes['total'] > MAX_EXTRACTED_BYTES:
                    raise MemoryError(f"Extracted archive exceeds {MAX_EXTRACTED_BYTES // (1024**3)} GB safety limit")
                dst.write(chunk)


def _extract_gzip_payload(archive_path: str, extract_dir: str, extracted_bytes: dict) -> None:
    """Gunzip one payload without double-counting an intermediate tar.

    The expanded stream is bounded while it is written. If it is a tar, only
    the retained members are charged to the shared extraction budget; otherwise
    the retained plain file is charged once.
    """
    output_name = os.path.basename(archive_path)[:-3] or "archive"
    output_path = os.path.join(extract_dir, output_name)
    chunk_size = 1024 * 1024
    gunzipped = 0
    keep_plain_output = False
    try:
        with gzip.open(archive_path, 'rb') as src, open(output_path, 'wb') as dst:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                gunzipped += len(chunk)
                if (
                    gunzipped > MAX_EXTRACTED_BYTES
                    or extracted_bytes['total'] + gunzipped > MAX_EXTRACTED_BYTES
                ):
                    raise MemoryError(
                        f"Extracted archive exceeds {MAX_EXTRACTED_BYTES // (1024**3)} GB safety limit"
                    )
                dst.write(chunk)
        if tarfile.is_tarfile(output_path):
            nested_dir = os.path.join(extract_dir, "_nested")
            os.makedirs(nested_dir, exist_ok=True)
            with tarfile.open(output_path, 'r:') as tf:
                _extract_tar_members(tf, nested_dir, extracted_bytes)
        else:
            extracted_bytes['total'] += gunzipped
            keep_plain_output = True
    finally:
        if not keep_plain_output:
            try:
                os.unlink(output_path)
            except FileNotFoundError:
                pass


def _extract_tar_gz_payload(
    archive_path: str,
    extract_dir: str,
    extracted_bytes: dict | None = None,
) -> None:
    """Extract a .tar.gz/.tgz using tarfile's gzip reader.

    Some sdb-report bundles append trailing bytes after the gzip stream (``gzip -t``
    reports "trailing garbage ignored"). Python's ``gzip.open`` treats that as fatal
    on a full read, but ``tarfile.open(..., 'r:gz')`` stops at the tar EOF and
    parses the bundle correctly — use that path instead of a manual gunzip step.

    Always update the caller's shared ``extracted_bytes`` counter so nested
    archives cannot restart the decompression budget.
    """
    if extracted_bytes is None:
        extracted_bytes = {'total': 0}
    with tarfile.open(archive_path, 'r:gz') as tf:
        _extract_tar_members(tf, extract_dir, extracted_bytes)


def _discover_nested_tar_gz(extract_dir: str) -> list[str]:
    """Find nested ``.tar.gz`` / ``.tgz`` members under an extracted tree.

    Walks recursively so directory-wrapped layouts (``wrapped/dir/inner.tgz``)
    are covered. Skips any previous ``_nested`` extraction target.
    """
    discovered: list[str] = []
    for root, dirs, files in os.walk(extract_dir):
        dirs[:] = [name for name in dirs if name != "_nested"]
        for name in files:
            lower = name.lower()
            if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
                discovered.append(os.path.join(root, name))
    return discovered


def _persist_extracted_root(extract_dir: str, report_root: str, persist_to: str) -> str:
    """Move the resolved report root into persist_to and return its new path."""
    try:
        os.makedirs(persist_to, exist_ok=True)
        dest_name = os.path.basename(report_root.rstrip(os.sep)) or "report_root"
        dest = os.path.join(persist_to, dest_name)
        if os.path.exists(dest):
            shutil.rmtree(dest, ignore_errors=True)
        moved = shutil.move(report_root, dest)
        return moved
    except Exception as exc:
        logger.warning("Failed to persist extracted report root for raw search: %s", exc)
        return ""
def parse_report_archive_streaming(archive_path: str, progress_callback=None, persist_to: str = None) -> dict:
    """Main entry with streaming support and progress callback.
    For tar.gz: uses streaming pipe mode to avoid loading full archive into memory.
    For zip: extracts to temp dir (zip requires random access).
    """
    extract_dir = tempfile.mkdtemp(prefix="sdb_report_")
    detected_format = "unknown"

    def _progress(stage, **kwargs):
        if progress_callback:
            try:
                progress_callback(stage, **kwargs)
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)

    try:
        _progress("extracting", message="Decompressing archive...")

        extracted_bytes = {'total': 0}

        detected_format = ensure_supported_archive_format(archive_path)
        if detected_format == "zip":
            with zipfile.ZipFile(archive_path, 'r') as zf:
                infos = zf.infolist()
                limits = ArchiveLimits.from_env(max_extracted_bytes=MAX_EXTRACTED_BYTES)
                validate_member_count(len(infos), limits)
                expected_bytes = sum(max(0, int(info.file_size)) for info in infos)
                if expected_bytes > limits.max_extracted_bytes:
                    raise MemoryError("Archive declared extraction size exceeds safety limit")
                require_scratch_capacity(Path(extract_dir), expected_bytes, limits)
                for info in infos:
                    validate_zip_info(info, limits)
                    name = info.filename
                    resolved_path = _validate_extract_path(extract_dir, name)
                    if info.is_dir():
                        os.makedirs(resolved_path, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
                    # Prefer a larger later member over an earlier empty/stub
                    # duplicate; skip without raising FileExistsError on O_EXCL.
                    if not _prepare_regular_file_target(
                        resolved_path, int(info.file_size or 0)
                    ):
                        continue
                    # Stream-extract and enforce the safety budget against ACTUAL
                    # decompressed bytes (not the declared size) so a zip bomb cannot
                    # bypass the limit by under-reporting member sizes (F6).
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                    with zf.open(info, 'r') as src, os.fdopen(os.open(resolved_path, flags, 0o600), 'wb') as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            extracted_bytes['total'] += len(chunk)
                            if extracted_bytes['total'] > MAX_EXTRACTED_BYTES:
                                raise MemoryError(f"Extracted archive exceeds {MAX_EXTRACTED_BYTES // (1024**3)} GB safety limit")
                            dst.write(chunk)
        elif detected_format == "tar.gz":
            _extract_tar_gz_payload(archive_path, extract_dir, extracted_bytes)
        elif detected_format == "tar":
            with tarfile.open(archive_path, 'r:') as tf:
                _extract_tar_members(tf, extract_dir, extracted_bytes)
        elif detected_format == "gz":
            _extract_gzip_payload(archive_path, extract_dir, extracted_bytes)
        else:
            raise ValueError(f"Unsupported archive format: {os.path.basename(archive_path)}")

        for fpath in _discover_nested_tar_gz(extract_dir):
            nested_dir = os.path.join(extract_dir, "_nested")
            os.makedirs(nested_dir, exist_ok=True)
            try:
                with tarfile.open(fpath, 'r:gz') as tf:
                    _extract_tar_members(tf, nested_dir, extracted_bytes)
                os.unlink(fpath)
            except Exception as exc:
                normalized = _normalize_archive_exception(exc, fpath)
                if normalized is exc:
                    raise
                raise normalized from exc
            break

        base_dir = extract_dir
        nested_path = os.path.join(extract_dir, "_nested")
        if os.path.isdir(nested_path):
            try:
                if os.listdir(nested_path) and not _looks_like_report_root(extract_dir):
                    if _looks_like_report_root(nested_path):
                        base_dir = nested_path
            except OSError as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)

        report_root = base_dir
        for _ in range(10):
            try:
                entries = [e for e in os.listdir(report_root) if e not in {"_nested"}]
            except OSError:
                break
            dirs = [e for e in entries if os.path.isdir(os.path.join(report_root, e))]
            if _looks_like_report_root(report_root):
                break
            if len(dirs) == 1:
                report_root = os.path.join(report_root, dirs[0])
                continue
            break

        report_name = os.path.basename(report_root) or os.path.basename(archive_path)

        _progress("parsing", message=f"Found report: {report_name}")

        result = parse_report_directory(report_root, report_name, _progress)
        result["detected_format"] = detected_format

        if persist_to:
            result["extracted_path"] = _persist_extracted_root(extract_dir, report_root, persist_to)
        return result
    except Exception as exc:
        normalized = _normalize_archive_exception(exc, archive_path)
        if normalized is exc:
            raise
        raise normalized from exc
    finally:
        # Always wipe the temp scratch dir. When persist_to was used, the report root was
        # already moved out into persist_to, so this only removes leftover scaffolding
        # (_nested wrappers, etc.).
        shutil.rmtree(extract_dir, ignore_errors=True)


# Keep backward-compat alias

def parse_report_archive(archive_path: str) -> dict:
    return parse_report_archive_streaming(archive_path)


def parse_sparse_report_file(file_path: str, report_name: str | None = None) -> dict:
    """Parse a single log/config artifact without inventing cluster topology.

    Sparse inputs deliberately expose only capabilities supported by the file.
    This lets support engineers analyze partial customer uploads instead of
    rejecting them for not matching a full sdb-report directory structure.
    """
    path = Path(file_path)
    if not path.is_file():
        raise ValueError("Sparse report input must be a readable file")
    if path.stat().st_size > MAX_JSON_FILE_BYTES_DEFAULT:
        raise ValueError("Sparse report input exceeds the 25 MB safety limit")

    result = {
        "report_name": report_name or path.name,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "input_mode": "sparse",
        "detected_format": "sparse",
        "nodes": [],
        "cluster_overview": {},
        "databases": [],
        "storage": [],
        "queries": [],
        "events": [],
        "pipelines": [],
        "logs": [],
        "log_summary": {},
        "recommendations": [],
        "incident_clusters": [],
        "config_health": {},
        "raw_node_count": 0,
        "parse_warnings": ["Partial input: unavailable dashboard sections are disabled."],
    }
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")

    if suffix in {".log", ".txt"}:
        flexible = re.compile(
            r"(?:\d+\s+)?(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
            r"(INFO|WARN|WARNING|ERROR|FATAL|NOTICE|DEBUG):?\s*(.*)",
            re.I,
        )
        logs = []
        for line in text.splitlines()[-5000:]:
            match = flexible.match(line.strip())
            if not match:
                continue
            severity = match.group(2).upper()
            if severity == "WARNING":
                severity = "WARN"
            logs.append({
                "timestamp": match.group(1),
                "severity": severity,
                "message": match.group(3)[:1000],
                "hostname": "SPARSE_INPUT",
                "role": "UNKNOWN",
                "source": path.name,
            })
        result["logs"] = logs
        result["log_summary"] = build_log_summary(logs)
        result["detected_log_patterns"] = detect_log_patterns(logs)
    elif suffix == ".json":
        try:
            config = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON sparse input: {exc.msg}") from exc
        result["config_health"] = {"source": path.name, "raw_config": config}
    elif suffix in {".tsv", ".cnf", ".conf"}:
        variables = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "\t" in stripped:
                key, value = stripped.split("\t", 1)
            elif "=" in stripped:
                key, value = stripped.split("=", 1)
            else:
                continue
            if key.lower() in {"variable_name", "name"}:
                continue
            variables[key.strip()] = value.strip()
        result["config_health"] = {"source": path.name, "variables": variables}
        version = variables.get("memsql_version") or variables.get("version")
        if version:
            result["version"] = version
            result["cluster_overview"]["version"] = version

    result["log_count"] = len(result["logs"])
    result["recommendations"], result["incident_clusters"] = generate_recommendations_with_clusters(result)
    from product_features import build_capabilities
    result["capabilities"] = build_capabilities(result)
    return result


def parse_report_directory(report_root: str, report_name: str, progress_cb=None) -> dict:
    result = {
        "report_name": report_name,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "nodes": [], "cluster_overview": {}, "databases": [], "storage": [],
        "queries": [], "events": [], "pipelines": [], "logs": [],
        "log_summary": {}, "recommendations": [], "workload_management": [],
        "replication_status": [], "checks": [], "raw_node_count": 0,
        "config_health": {}, "backup_history": [], "resource_pools": [],
        "database_disk_usage": [], "partitions": {}, "version_history": [],
        "availability_groups": [], "users": [], "detected_log_patterns": [],
        "dmesg_events": [], "parse_warnings": [], "collector_availability": {},
        "report_root": report_root,
    }

    index_path = os.path.join(report_root, "index.json")
    if os.path.exists(index_path):
        try:
            with open(index_path) as f:
                result["index"] = json.load(f)
        except Exception as exc:
            logger.debug("parser: ignoring non-fatal error", exc_info=exc)

    node_dirs = []
    for entry in sorted(os.listdir(report_root)):
        full_path = os.path.join(report_root, entry)
        if not os.path.isdir(full_path):
            continue
        # Reject node dirs that are themselves symlinks escaping the report root.
        if os.path.islink(full_path):
            real = None
            try:
                real = os.path.realpath(full_path)
            except Exception:
                pass
            report_real = os.path.realpath(report_root)
            if real is None or not (real == report_real or real.startswith(report_real + os.sep)):
                result["parse_warnings"].append(
                    f"Skipped node dir '{entry}': symlink or escape outside report root"
                )
                continue
        if entry == "globalInfo":
            result["global_info"] = parse_global_info(full_path)
            continue
        if entry in _NON_NODE_DIR_NAMES:
            continue
        named = _node_role_from_dir_name(entry)
        if named is not None:
            node_dirs.append((full_path, named[0], named[1]))
            continue
        # Fallback: directory holds node collector output but its name (host/UUID)
        # does not encode the role. Detect by content so topology still populates.
        if _looks_like_node_dir(full_path):
            node_dirs.append((full_path, entry, "NODE"))

    node_dirs.sort(key=lambda item: (_centralized_source_priority(item[2]), item[1]))
    result["raw_node_count"] = len(node_dirs)

    all_logs = []
    # Centralized data collectors (first node that has it, usually MA)
    centralized = {}

    for idx, (node_path, hostname, role) in enumerate(node_dirs):
        if progress_cb:
            progress_cb("parsing", nodes=len(node_dirs), files=1,
                message=f"Parsing node {hostname} ({idx+1} of {len(node_dirs)})")
        node_info = parse_node_directory(node_path, hostname, role)
        result["nodes"].append(node_info)

        # Collect centralized data from first available source
        for key in ["mv_nodes", "cluster_topology", "cluster_status", "databases_extended",
                     "mv_queries", "mv_events", "pipelines_data", "blocked_queries",
                     "workload_management", "replication_status", "table_statistics",
                     "processlist", "resource_pools", "database_disk_usage", "partitions",
                     "backup_history", "version_history", "availability_groups", "users",
                     "rebalance_status", "mv_processlist", "ps",
                     "information_schema_tables"]:
            if key not in centralized and node_info.get(key):
                centralized[key] = node_info[key]

        all_logs.extend(node_info.get("trace_logs", []))
        # Trim during collection to prevent unbounded memory growth
        if len(all_logs) > MAX_RAW_LOGS:
            all_logs = all_logs[-MAX_RAW_LOGS:]

    # Build cluster overview (MV_NODES → topology JSON → detected node dirs)
    if centralized.get("mv_nodes"):
        result["cluster_overview"] = build_cluster_overview(centralized["mv_nodes"], result["nodes"])
        result["cluster_overview"]["topology_source"] = "mv_nodes"
    elif centralized.get("cluster_topology"):
        result["cluster_overview"] = build_cluster_overview_from_topology(
            centralized["cluster_topology"], result["nodes"]
        )
    elif result["nodes"]:
        result["cluster_overview"] = build_minimal_cluster_overview(result["nodes"])

    if result["raw_node_count"] > 0 and not (result.get("cluster_overview") or {}).get("nodes_detail"):
        result["parse_warnings"].append(
            "Node directories detected but cluster topology could not be built "
            "(missing or unreadable informationSchemaMvNodes.json / clusterTopology.json)."
        )
    elif result["raw_node_count"] == 0:
        result["parse_warnings"].append(
            "No node directories detected. Check that the archive uses standard "
            "sdb-report per-node folder layout."
        )

    co = result.get("cluster_overview") or {}
    if centralized.get("cluster_topology"):
        co["topology"] = centralized["cluster_topology"]
    if centralized.get("cluster_status"):
        co["cluster_status"] = centralized["cluster_status"][:300]
    if centralized.get("blocked_queries"):
        co["blocked_queries"] = _cap_rows(centralized["blocked_queries"], MAX_BLOCKED_QUERIES_ROWS)
    if centralized.get("processlist"):
        co["processlist"] = centralized["processlist"][:MAX_PROCESSLIST_ROWS]
    if centralized.get("mv_processlist"):
        co["mv_processlist"] = centralized["mv_processlist"][:MAX_PROCESSLIST_ROWS]
    if centralized.get("rebalance_status"):
        co["rebalance_status"] = centralized["rebalance_status"][:300]
    result["cluster_overview"] = co

    # Assign other data
    if centralized.get("databases_extended"):
        result["databases"] = centralized["databases_extended"]
    if centralized.get("mv_queries"):
        result["queries"] = centralized["mv_queries"][:500]
    if centralized.get("mv_events"):
        result["events"] = _cap_rows(centralized["mv_events"], MAX_MV_EVENTS_ROWS)
    if centralized.get("pipelines_data"):
        result["pipelines"] = _cap_rows(centralized["pipelines_data"], MAX_PIPELINES_ROWS)
    if centralized.get("workload_management"):
        result["workload_management"] = _cap_rows(centralized["workload_management"], MAX_WORKLOAD_MANAGEMENT_ROWS)
    if centralized.get("replication_status"):
        result["replication_status"] = _cap_rows(centralized["replication_status"], MAX_REPLICATION_STATUS_ROWS)
    if centralized.get("table_statistics"):
        result["storage"] = _cap_rows(centralized["table_statistics"], MAX_TABLE_STATISTICS_ROWS)
    if centralized.get("information_schema_tables"):
        result["table_storage"] = extract_table_storage_inventory(
            centralized["information_schema_tables"]
        )
    if centralized.get("resource_pools"):
        result["resource_pools"] = _cap_rows(centralized["resource_pools"], MAX_RESOURCE_POOLS_ROWS)
    if centralized.get("database_disk_usage"):
        result["database_disk_usage"] = _cap_rows(centralized["database_disk_usage"], MAX_DATABASE_DISK_USAGE_ROWS)
    elif centralized.get("table_statistics"):
        result["database_disk_usage"] = derive_database_disk_usage_from_table_statistics(
            centralized["table_statistics"]
        )
    if centralized.get("partitions"):
        result["partitions"] = centralized["partitions"]
    if centralized.get("backup_history"):
        result["backup_history"] = _cap_rows(centralized["backup_history"], MAX_BACKUP_HISTORY_ROWS)
    if centralized.get("version_history"):
        result["version_history"] = _cap_rows(centralized["version_history"], MAX_VERSION_HISTORY_ROWS)
    if centralized.get("availability_groups"):
        result["availability_groups"] = _cap_rows(centralized["availability_groups"], MAX_AVAILABILITY_GROUPS_ROWS)
    if centralized.get("users"):
        result["users"] = _cap_rows(centralized["users"], MAX_USERS_ROWS)

    # Process logs — persist last 5k; summary reflects the indexed subset so Explorer totals match.
    all_logs.sort(key=lambda x: x.get("timestamp", ""))
    result["logs"] = all_logs[-5000:]
    result["log_summary"] = build_log_summary(result["logs"])
    if len(all_logs) > len(result["logs"]):
        result["log_summary"]["parse_total"] = len(all_logs)
        result["log_summary"]["indexed_note"] = (
            f"Showing severity counts for the {len(result['logs']):,} log lines indexed for browse/search; "
            f"{len(all_logs):,} lines were parsed for pattern detection."
        )
    result["alloc_memory"] = build_alloc_memory_overview(result["nodes"])

    # Detect critical log patterns
    result["detected_log_patterns"] = detect_log_patterns(all_logs)

    # High-value diagnostic aggregates
    result["log_timeframe"] = extract_log_timeframe(result["nodes"])
    result["backup_summary"] = summarize_backup_history(result.get("backup_history", []))
    result["pressure_events_per_hour"] = compute_pressure_events_per_hour(all_logs)
    result["node_events"] = extract_node_events(result.get("events", []))
    result["rebalance_events"] = extract_rebalance_events(
        result.get("events", []),
        result.get("cluster_overview", {}).get("rebalance_status", []),
    )
    result["memory_pressure"] = summarize_memory_pressure(result["nodes"])
    cluster_status_rows = result.get("cluster_overview", {}).get("cluster_status", [])
    result["cluster_layout"] = summarize_cluster_layout(cluster_status_rows)
    processlist_raw = result.get("cluster_overview", {}).get("processlist", _PROCESSLIST_MISSING)
    if processlist_raw is _PROCESSLIST_MISSING:
        processlist_rows = []
        processlist_snapshot_available = False
        result["process_health"] = extract_process_health([], snapshot_available=False)
    else:
        processlist_snapshot_available = True
        processlist_rows = (
            _as_row_list(processlist_raw)
            if not isinstance(processlist_raw, list)
            else processlist_raw
        )
        result["process_health"] = extract_process_health(
            processlist_rows,
            snapshot_available=True,
        )

    # Phase 3.2: Query pattern analysis + replication lag patterns
    queries_rows = result.get("queries", []) or []
    result["query_patterns"] = extract_query_patterns(
        processlist_rows,
        queries_rows,
        snapshot_available=processlist_snapshot_available,
    )
    replication_rows = result.get("replication_status", []) or []
    log_patterns_for_repl = result.get("detected_log_patterns", []) or []
    async_transition_count = sum(
        (result.get("pressure_events_per_hour", {}).get("async_transition") or {}).values()
    )
    result["replication_lag_patterns"] = extract_replication_lag_patterns(
        replication_rows,
        log_patterns_for_repl,
        result.get("events", []),
        async_transition_count=async_transition_count,
    )

    # Phase 3.6: Per-node memory utilization trend + long-running transactions
    result["memory_utilization"] = extract_memory_utilization_trend(
        result["nodes"], result.get("cluster_overview", {})
    )
    blocked_queries_rows = result.get("cluster_overview", {}).get("blocked_queries", []) or []
    result["long_running_transactions"] = extract_long_running_transactions(
        processlist_rows, blocked_queries_rows
    )
    result["query_analysis"] = extract_query_analysis(
        processlist_rows,
        result.get("query_patterns", {}),
        blocked_queries_rows,
    )

    # Collect dmesg events across all nodes
    all_dmesg = []
    collector_availability: dict = {"dmesg": {"nodes_total": 0, "stdout_available": 0, "stderr_only": 0, "unavailable": 0}}
    for node in result["nodes"]:
        all_dmesg.extend(node.get("dmesg_events", []))
        dmesg_status = node.get("dmesg_collector", {}) or {}
        collector_availability["dmesg"]["nodes_total"] += 1
        if dmesg_status.get("stderr_only"):
            collector_availability["dmesg"]["stderr_only"] += 1
        elif dmesg_status.get("stdout"):
            collector_availability["dmesg"]["stdout_available"] += 1
        elif not dmesg_status.get("available"):
            collector_availability["dmesg"]["unavailable"] += 1
    result["dmesg_events"] = _cap_rows(all_dmesg, MAX_DMESG_EVENTS)
    result["collector_availability"] = collector_availability
    result["extended_diagnostics"] = build_extended_diagnostics(
        result["nodes"],
        all_logs,
        result.get("log_summary", {}),
        result.get("storage", []),
        collector_availability,
        result.get("cluster_overview", {}),
        result.get("events", []),
    )

    # Build config health from all nodes
    result["config_health"] = build_config_health(result["nodes"])

    # Disk reclamation accounting (ENH-1/ENH-2): overhead buckets + blobs delta
    try:
        from disk_reclamation import resolve_disk_reclamation
        disk_reclamation_result = resolve_disk_reclamation(result)
        disk_intelligence = disk_reclamation_result.get("disk_intelligence", {})
        disk_reclamation = {
            "cluster_overhead": disk_reclamation_result.get("cluster_overhead"),
            "blobs_referenced_delta": disk_reclamation_result.get("blobs_referenced_delta"),
        }
        if disk_intelligence:
            result["disk_intelligence"] = disk_intelligence
        if disk_reclamation["cluster_overhead"]:
            result["cluster_overhead"] = disk_reclamation["cluster_overhead"]
        if disk_reclamation["blobs_referenced_delta"]:
            result["blobs_referenced_delta"] = disk_reclamation["blobs_referenced_delta"]
        result["disk_reclamation"] = disk_reclamation
        result["blobs_referenced_delta"] = disk_reclamation.get("blobs_referenced_delta", {})
        result["cluster_overhead"] = disk_reclamation.get("cluster_overhead", {})
    except Exception as exc:
        logger.warning("disk reclamation resolution failed", exc_info=exc)
        result["disk_reclamation"] = {}
        result["blobs_referenced_delta"] = {}
        result["cluster_overhead"] = {}

    # Generate recommendations (with incident clusters)
    result["recommendations"], result["incident_clusters"] = generate_recommendations_with_clusters(result)
    result["analysis_revision"] = ANALYSIS_REVISION
    if result["incident_clusters"]:
        try:
            from investigation import enrich_incident_clusters_with_logs
            result["incident_clusters"] = enrich_incident_clusters_with_logs(
                result["incident_clusters"], result
            )
        except Exception as exc:
            logger.debug("parser: ignoring non-fatal error", exc_info=exc)

    # Clean up heavy internal fields
    for node in result["nodes"]:
        node.pop("_node_path", None)
        node.pop("disk_du_buckets", None)
        for key in ["trace_logs", "mv_nodes", "cluster_topology", "cluster_status",
                     "databases_extended", "mv_queries", "mv_events", "pipelines_data",
                     "blocked_queries", "workload_management", "replication_status",
                     "table_statistics", "processlist", "resource_pools",
                     "rebalance_status",
                     "database_disk_usage", "partitions", "backup_history",
                     "version_history", "availability_groups", "users", "mv_processlist"]:
            node.pop(key, None)

    return result


def parse_node_directory(node_path: str, hostname: str, role: str) -> dict:
    node = {
        "hostname": hostname, "role": role, "metrics": {}, "config": {},
        "version": None, "memsql_id": None, "os_checks": {},
        "_node_path": node_path,
    }

    # System commands
    node["metrics"]["memory"] = parse_free(node_path)
    node["free"] = node["metrics"]["memory"]
    node["metrics"]["disk"] = parse_df(node_path)
    node["metrics"]["uptime"] = parse_uptime(node_path)
    node["metrics"]["cpu_info"] = parse_cpu_info(node_path)
    node["metrics"]["top"] = parse_top(node_path)
    node["metrics"]["psutil"] = parse_json_file(node_path, "psutil.json")
    node["metrics"]["node_disk_usage"] = parse_json_file(node_path, "nodeDirectoriesDiskUsage.json")
    try:
        from disk_reclamation import extract_node_disk_du_buckets
        node["disk_du_buckets"] = extract_node_disk_du_buckets(node_path, node["metrics"]["node_disk_usage"])
    except Exception as exc:
        logger.debug("parser: disk du bucket extract failed for %s", hostname, exc_info=exc)
        node["disk_du_buckets"] = {}
    node["metrics"]["sysinfo"] = parse_mv_sysinfo(node_path)
    node["metrics"]["alloc_memory"] = extract_alloc_memory_metrics(
        node["metrics"]["sysinfo"].get("MV_SYSINFO_MEM", [])
    )

    # Config
    node["config"]["memsql_config"] = parse_json_file(node_path, "memsqlConfig.json")
    node["config"]["memsqlctl_info"] = parse_json_file(node_path, "memsqlctlInfo.json")
    node["config"]["process_limits"] = parse_process_limits(node_path)
    node["config"]["os_release"] = parse_text_file(node_path, "osRelease")

    # OS health checks
    node["os_checks"]["thp"] = parse_thp(node_path)
    node["os_checks"]["sysctl"] = parse_sysctl_checks(node_path)
    sysctl_data = node["os_checks"].get("sysctl", {})
    cgroup_info = parse_cgroup_info(node_path)
    node["os_checks"]["cgroup_info"] = cgroup_info
    ssl_perm = parse_ssl_files_and_datadir_permissions(node_path)
    node["os_checks"]["ssl_files_and_datadir_permissions"] = ssl_perm
    node["metrics"]["sys_info"] = {
        "vm.min_free_kbytes": (sysctl_data.get("vm.min_free_kbytes") or {}).get("value"),
        "kernel.sched_rt_runtime_us": (sysctl_data.get("kernel.sched_rt_runtime_us") or {}).get("value"),
        "cpu_memory_bandwidth": "normal",
        "disk_bandwidth": "normal",
        "partitions_start": "aligned",
        "installed_permissions": ssl_perm.get("status", "pass"),
        "cgroup_memory": cgroup_info.get("memory_controller", "disabled"),
        "cgroup_memory_usage": cgroup_info.get("usage_bytes"),
        "cgroup_memory_limit": cgroup_info.get("limit_bytes"),
        "cgroup_memory_usage_pct": cgroup_info.get("usage_pct"),
    }
    node["os_checks"]["numa"] = parse_numa(node_path)
    node["os_checks"]["security_limits"] = parse_security_limits(node_path)

    # Dmesg
    node["dmesg_collector"] = _dmesg_collector_status(node_path)
    raw_dmesg = parse_dmesg_raw(node_path)
    node["metrics"]["dmesg"] = [e["line"] for e in raw_dmesg][:50]
    node["dmesg_events"] = classify_dmesg_events(raw_dmesg, hostname, role)

    # SingleStore data
    node["mv_nodes"] = parse_sdb_json_table(node_path, "informationSchemaMvNodes.json")
    node["cluster_topology"] = parse_cluster_topology(node_path)
    node["cluster_status"] = parse_sdb_json_table(node_path, "showClusterStatus.json")
    node["databases_extended"] = parse_sdb_json_table(node_path, "showDatabasesExtended.json")
    node["mv_queries"] = parse_sdb_json_table(node_path, "informationSchemaMvQueries.json")
    node["mv_events"] = parse_sdb_json_table(node_path, "informationSchemaMvEvents.json")
    node["pipelines_data"] = parse_pipelines(node_path)
    node["blocked_queries"] = parse_sdb_json_table(node_path, "informationSchemaMvBlockedQueries.json")
    node["workload_management"] = parse_sdb_json_table(node_path, "showWorkloadManagementStatus.json")
    node["replication_status"] = parse_sdb_json_table(node_path, "showReplicationStatus.json")
    node["table_statistics"] = parse_sdb_json_table(node_path, "informationSchemaTableStatistics.json")
    node["processlist"] = parse_sdb_json_table(node_path, "informationSchemaProcesslist.json")
    node["mv_processlist"] = parse_sdb_json_table(node_path, "informationSchemaMvProcesslist.json")
    node["resource_pools"] = parse_sdb_json_table(node_path, "showResourcePools.json")
    node["rebalance_status"] = parse_rebalance_status(node_path)
    node["database_disk_usage"] = parse_sdb_json_table(node_path, "databaseDiskUsage.json")
    node["partitions"] = parse_partitions(node_path)
    node["backup_history"] = parse_sdb_json_table(node_path, "informationSchemaMvBackupHistory.json")
    node["version_history"] = parse_version_history(node_path)
    node["availability_groups"] = parse_sdb_json_table(node_path, "informationSchemaAvailabilityGroups.json")
    node["users"] = parse_sdb_json_table(node_path, "showUsers.json")
    if not node["users"]:
        node["users"] = parse_sdb_json_table(node_path, "informationSchemaUsers.json")
    node["user_privileges"] = parse_sdb_json_table(node_path, "informationSchemaUserPrivileges.json")
    node["role_privileges"] = parse_sdb_json_table(node_path, "informationSchemaRolePrivileges.json")
    node["information_schema_tables"] = parse_sdb_json_table(node_path, "informationSchemaTables.json")
    node["database_status"] = parse_sdb_json_table(node_path, "showDatabaseStatus.json")
    node["license"] = parse_license(node_path)
    node["ps"] = parse_ps_output(node_path)
    node["metrics"]["ps"] = node["ps"]
    node["encrypted_block_devices"] = parse_encrypted_block_devices(node_path)

    # Show variables: keep a curated key map plus the full map for security checkers
    show_vars = parse_json_file(node_path, "showVariables.json")
    node["show_variables"] = {}
    node["show_variables_all"] = {}
    key_var_names = {
        "memsql_version", "maximum_memory", "maximum_table_memory",
        "default_partitions_per_leaf", "redundancy_level", "sql_mode",
        "character_set_server", "maximum_columnstore_alter_memory",
        "columnstore_disk_insert_threshold", "snapshots_to_keep",
        "load_data_mem_limit", "background_merger_threads",
        "attach_rebalance_delay", "attach_rebalance_delay_seconds",
        "auto_attach", "failure_detection", "leaf_failure_detection",
        "aggregator_failure_detection", "columnstore_segment_rows",
        "interpreter_mode", "port", "bind_address", "http_api",
        "enable_wasm", "aes_default_encryption_mode", "auditlog_level",
        "auditlog_disk_sync", "auditlog_retention_period", "auditlogsdir",
        "basedir", "datadir", "secure_file_priv", "ssl_cert", "ssl_key",
        "ssl_ca", "ssl_fips_mode", "license_visibility",
        "node_replication_ssl_only", "sync_permissions",
        "default_user_require_ssl", "advanced_hdfs_pipelines",
        "max_dedicated_admin_connections", "enable_dac_ip_port",
        "password_min_length", "password_min_uppercase_chars",
        "password_min_lowercase_chars", "password_min_special_chars",
        "password_max_consec_sequential_chars",
        "http_proxy_port", "https_proxy_port", "version",
    }
    if show_vars and isinstance(show_vars, list) and show_vars:
        item = show_vars[0]
        if isinstance(item, dict) and "rows" in item:
            for row in item["rows"]:
                vname = str(row.get("Variable_name", "") or "")
                vval = row.get("Value", "")
                if not vname:
                    continue
                node["show_variables_all"][vname] = vval
                if vname in key_var_names:
                    node["show_variables"][vname] = vval
                if vname == "memsql_version":
                    node["version"] = vval
            if item.get("MemsqlID"):
                node["memsql_id"] = item["MemsqlID"]
    elif show_vars and isinstance(show_vars, dict):
        # Some toolbox variants emit a flat Variable_name → Value map
        for vname, vval in show_vars.items():
            if not isinstance(vname, str):
                continue
            node["show_variables_all"][vname] = vval
            if vname in key_var_names:
                node["show_variables"][vname] = vval
            if vname == "memsql_version":
                node["version"] = vval

    # Also flatten syncVariables when present (cluster-synced globals)
    sync_vars = parse_json_file(node_path, "syncVariables.json")
    if sync_vars and isinstance(sync_vars, list) and sync_vars:
        item = sync_vars[0]
        rows = item.get("rows") if isinstance(item, dict) else None
        if isinstance(rows, list):
            for row in rows:
                vname = str(row.get("Variable_name", "") or "")
                vval = row.get("Value", "")
                if vname and vname not in node["show_variables_all"]:
                    node["show_variables_all"][vname] = vval
                    if vname in key_var_names:
                        node["show_variables"][vname] = vval

    # Trace logs
    node["trace_logs"] = parse_trace_logs(node_path, hostname, role)

    return node


# ─── Enhanced system parsers ────────────────────────────────────────

def parse_free(node_path: str) -> dict:
    content = read_stdout(node_path, "free")
    if not content:
        return {}
    result = {}
    for line in content.strip().split('\n'):
        parts = line.split()
        if len(parts) >= 4 and parts[0] == 'Mem:':
            result = {
                "total_mb": safe_int(parts[1]), "used_mb": safe_int(parts[2]),
                "free_mb": safe_int(parts[3]),
                "shared_mb": safe_int(parts[4]) if len(parts) > 4 else 0,
                "buff_cache_mb": safe_int(parts[5]) if len(parts) > 5 else 0,
                "available_mb": safe_int(parts[6]) if len(parts) > 6 else 0,
            }
            if result["total_mb"] > 0:
                result["used_pct"] = round(result["used_mb"] / result["total_mb"] * 100, 1)
                result["available_pct"] = round(result["available_mb"] / result["total_mb"] * 100, 1)
        if len(parts) >= 4 and parts[0] == 'Swap:':
            result["swap_total_mb"] = safe_int(parts[1])
            result["swap_used_mb"] = safe_int(parts[2])
            result["swap_free_mb"] = safe_int(parts[3])
            if result["swap_total_mb"] > 0:
                result["swap_used_pct"] = round(result["swap_used_mb"] / result["swap_total_mb"] * 100, 1)
    return result


def parse_df(node_path: str) -> list:
    content = read_stdout(node_path, "df")
    if not content:
        return []
    lines = content.strip().split('\n')
    if not lines:
        return []
    header = lines[0].split()
    header_lower = [h.lower() for h in header]
    # sdb-report may emit df -h (6 cols), df -i (6 cols), or a combined 7-col header
    # with both Use% and IUse%. The "Mounted on" column can contain spaces.
    has_iuse = any("iuse" in h for h in header_lower)
    has_use = any(h == "use%" or (h.endswith("use%") and "iuse" not in h) for h in header_lower)
    layout = "combined" if has_use and has_iuse else ("inodes" if has_iuse else "standard")
    result = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if layout == "combined":
            # Filesystem Size Used Avail Use% IUse% Mounted on
            if len(parts := stripped.split(None, 7)) < 7:
                continue
            filesystem, size, used, avail, use_pct_str, iuse_str, mounted_on = parts[:7]
            result.append({
                "filesystem": filesystem,
                "size": size,
                "used": used,
                "avail": avail,
                "use_pct": safe_int(use_pct_str.replace('%', '')),
                "iuse_pct": safe_int(iuse_str.replace('%', '')),
                "mounted_on": mounted_on.strip(),
            })
        elif layout == "inodes":
            # df -i columns: Filesystem Inodes IUsed IFree IUse% Mounted on
            if len(parts := stripped.split(None, 5)) < 6:
                continue
            filesystem, inodes, iused, ifree, iuse_str, mounted_on = parts[:6]
            result.append({
                "filesystem": filesystem,
                "size": "",
                "used": "",
                "avail": "",
                "use_pct": 0,
                "iuse_pct": safe_int(iuse_str.replace('%', '')),
                "mounted_on": mounted_on.strip(),
            })
        else:
            # Standard df -h: Filesystem Size Used Avail Use% Mounted on
            if len(parts := stripped.split(None, 5)) < 6:
                continue
            filesystem, size, used, avail, use_pct_str, mounted_on = parts[:6]
            result.append({
                "filesystem": filesystem,
                "size": size,
                "used": used,
                "avail": avail,
                "use_pct": safe_int(use_pct_str.replace('%', '')),
                "iuse_pct": 0,
                "mounted_on": mounted_on.strip(),
            })
    return result


def parse_uptime(node_path: str) -> dict:
    content = read_stdout(node_path, "uptime")
    if not content:
        return {}
    result = {"raw": content.strip()}
    # Extract load averages
    m = re.search(r'load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', content)
    if m:
        result["load_1m"] = float(m.group(1))
        result["load_5m"] = float(m.group(2))
        result["load_15m"] = float(m.group(3))
    return result


def parse_cpu_info(node_path: str) -> dict:
    result = {}
    threading = parse_json_file(node_path, "cpuThreadingInfo.json")
    if threading:
        result["threading"] = threading
    freq = parse_json_file(node_path, "cpuFreqInfo.json")
    if freq:
        result["frequency"] = freq
    psutil_data = parse_json_file(node_path, "psutil.json")
    if psutil_data:
        result["physical_cpus"] = psutil_data.get("numPhysicalCpus")
        result["logical_cpus"] = psutil_data.get("numLogicalCpus")
    return result


def parse_top(node_path: str) -> dict:
    content = read_stdout(node_path, "top")
    if not content:
        return {}
    result = {"raw_header": ""}
    lines = content.strip().split('\n')
    header_lines = []
    for line in lines[:7]:
        header_lines.append(line)
        if '%Cpu' in line or 'Cpu' in line:
            cpu_match = re.findall(r'(\d+\.?\d*)\s*(us|sy|ni|id|wa|hi|si|st)', line)
            if cpu_match:
                result["cpu"] = {k: float(v) for v, k in cpu_match}
        if 'MiB Mem' in line or 'KiB Mem' in line:
            mem_match = re.findall(r'(\d+\.?\d*)\s*(total|free|used|buff/cache)', line)
            if mem_match:
                result["mem_top"] = {k: float(v) for v, k in mem_match}
    result["raw_header"] = '\n'.join(header_lines)
    return result


def parse_thp(node_path: str) -> dict:
    thp_dir = os.path.join(node_path, "transparentHugepage")
    if not os.path.isdir(thp_dir):
        # Fallback: many real bundles use "thp" as the collector name
        thp_dir = os.path.join(node_path, "thp")
    if not os.path.isdir(thp_dir):
        return {"status": "unknown"}
    result = {}
    for f in ["enabled", "defrag", "shmem_enabled", "use_zero_page"]:
        fpath = os.path.join(thp_dir, f)
        if os.path.isfile(fpath):
            try:
                # Limit read to 1KB to prevent memory issues
                with open(fpath, 'r') as fh:
                    content = fh.read(1024).strip()
                result[f] = content
                if f == "enabled":
                    # Parse [never] / [always] / [madvise]
                    m = re.search(r'\[(\w+)\]', content)
                    result["active"] = m.group(1) if m else "unknown"
                elif f == "defrag":
                    # Parse [never] / [always] / [madvise]
                    m = re.search(r'\[(\w+)\]', content)
                    result["active_defrag"] = m.group(1) if m else "unknown"
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    result["status"] = "disabled" if result.get("active") == "never" and result.get("active_defrag") == "never" else "enabled"
    return result


def parse_sysctl_checks(node_path: str) -> dict:
    content = read_stdout(node_path, "sysctl")
    if not content:
        return {}
    checks = {}
    key_params = {
        "vm.max_map_count": {"min": 1000000000, "severity": "critical"},
        "vm.swappiness": {"min": 1, "max": 10, "severity": "warning"},
        "net.core.somaxconn": {"min": 1024, "severity": "warning"},
        "net.core.wmem_max": {"min": 8388608, "severity": "warning"},
        "net.core.rmem_max": {"min": 8388608, "severity": "warning"},
        "vm.overcommit_memory": {"min": 0, "max": 0, "severity": "warning"},
        "vm.overcommit_ratio": {"min": 90, "max": 90, "severity": "warning"},
        "vm.min_free_kbytes": {"min": 153600, "severity": "warning"},
        "kernel.sched_rt_runtime_us": {"min": 950000, "severity": "warning"},
    }
    for line in content.split('\n'):
        line = line.strip()
        for param, rules in key_params.items():
            if line.startswith(param):
                parts = line.split('=')
                if len(parts) >= 2:
                    val = parts[1].strip()
                    checks[param] = {
                        "value": val,
                        "numeric": safe_int(val),
                        "status": "pass",
                    }
                    if "min" in rules and safe_int(val) < rules["min"]:
                        checks[param]["status"] = "fail"
                        checks[param]["severity"] = rules["severity"]
                    if "max" in rules and safe_int(val) > rules["max"]:
                        checks[param]["status"] = "warn"
                        checks[param]["severity"] = rules["severity"]
    return checks


def _parse_cgroup_byte_value(raw: str) -> int | None:
    """Parse cgroup memory limit/usage values; treat 'max'/unlimited as None."""
    text = str(raw or "").strip().lower()
    if not text or text in {"max", "unlimited", "-1", "9223372036854771712"}:
        return None
    try:
        val = int(float(text))
    except (TypeError, ValueError):
        return None
    # Kernel sentinel for "no limit" on cgroup v1
    if val >= 2**62:
        return None
    return val if val >= 0 else None


def parse_cgroup_info(node_path: str) -> dict:
    """Parse cgroupInfo / processFiles collectors for memory usage vs limit.

    Returns keys used by cgroupDisabled + cgroupMemoryUsage checkers:
      memory_controller, usage_bytes, limit_bytes, usage_pct, source
    """
    result = {
        "memory_controller": "disabled",
        "usage_bytes": None,
        "limit_bytes": None,
        "usage_pct": None,
        "source": "",
    }
    candidate_dirs = [
        os.path.join(node_path, "cgroupInfo"),
        os.path.join(node_path, "cgroup"),
        os.path.join(node_path, "processFiles"),
    ]
    texts: list[str] = []
    for d in candidate_dirs:
        if not os.path.isdir(d):
            continue
        for root_d, _dirs, files in os.walk(d):
            for fname in files:
                fpath = os.path.join(root_d, fname)
                try:
                    with open(fpath, "r", errors="ignore") as fh:
                        texts.append(fh.read(65536))
                except Exception as exc:
                    logger.debug("parser: cgroup file read failed: %s", exc, exc_info=exc)
    # Also accept a single JSON blob collector
    for json_name in ("cgroupInfo.json", "psutil.json"):
        blob = parse_json_file(node_path, json_name)
        if isinstance(blob, dict):
            texts.append(json.dumps(blob))
            # Direct numeric fields from psutil-style payloads
            for ukey in ("memory_current", "memory.current", "memory_usage_in_bytes",
                         "cgroup_memory_usage", "usage_in_bytes"):
                if ukey in blob and result["usage_bytes"] is None:
                    result["usage_bytes"] = _parse_cgroup_byte_value(blob.get(ukey))
            for lkey in ("memory_max", "memory.max", "memory_limit_in_bytes",
                         "cgroup_memory_limit", "limit_in_bytes"):
                if lkey in blob and result["limit_bytes"] is None:
                    result["limit_bytes"] = _parse_cgroup_byte_value(blob.get(lkey))

    joined = "\n".join(texts)
    if not joined.strip():
        return result

    lower = joined.lower()
    if "cgroup_disable=memory" in lower or "memory controller: disabled" in lower:
        result["memory_controller"] = "disabled"
    elif re.search(r"\bmemory\b", lower) and (
        "enabled" in lower or "memory.current" in lower or "usage_in_bytes" in lower
        or "memory.max" in lower or "limit_in_bytes" in lower
    ):
        result["memory_controller"] = "enabled"

    patterns = [
        (r"memory\.current\s*[=:]?\s*(\d+)", "usage"),
        (r"memory\.usage_in_bytes\s*[=:]?\s*(\d+)", "usage"),
        (r"usage_in_bytes\s*[=:]?\s*(\d+)", "usage"),
        (r"memory\.max\s*[=:]?\s*(\S+)", "limit"),
        (r"memory\.limit_in_bytes\s*[=:]?\s*(\S+)", "limit"),
        (r"limit_in_bytes\s*[=:]?\s*(\S+)", "limit"),
    ]
    for pat, kind in patterns:
        m = re.search(pat, joined, re.I)
        if not m:
            continue
        parsed = _parse_cgroup_byte_value(m.group(1))
        if kind == "usage" and result["usage_bytes"] is None and parsed is not None:
            result["usage_bytes"] = parsed
            result["source"] = pat
        if kind == "limit" and result["limit_bytes"] is None:
            result["limit_bytes"] = parsed
            result["source"] = pat

    usage = result["usage_bytes"]
    limit = result["limit_bytes"]
    if usage is not None and limit and limit > 0:
        result["usage_pct"] = round(usage / limit * 100.0, 1)
        result["memory_controller"] = "enabled"
    return result


def parse_ssl_files_and_datadir_permissions(node_path: str) -> dict:
    """Parse sslFilesAndDatadirPermissions / installedPermissions collectors."""
    result = {"status": "pass", "detail": "", "raw": ""}
    texts: list[str] = []
    for dirname in (
        "sslFilesAndDatadirPermissions",
        "installedPermissions",
        "sslFiles",
    ):
        d = os.path.join(node_path, dirname)
        if not os.path.isdir(d):
            continue
        for root_d, _dirs, files in os.walk(d):
            for fname in files:
                fpath = os.path.join(root_d, fname)
                try:
                    with open(fpath, "r", errors="ignore") as fh:
                        texts.append(fh.read(16384))
                except Exception as exc:
                    logger.debug("parser: ssl/datadir perm read failed: %s", exc, exc_info=exc)
    for json_name in ("sslFilesAndDatadirPermissions.json", "installedPermissions.json"):
        blob = parse_json_file(node_path, json_name)
        if blob is not None:
            texts.append(json.dumps(blob) if not isinstance(blob, str) else blob)
    if not texts:
        return result
    raw = "\n".join(texts)
    result["raw"] = raw[:3000]
    lower = raw.lower()
    fail_tokens = ("fail", "world-writable", "permission denied", "too open",
                   "insecure", "owned by root", "mode 777", "mode 666")
    if any(tok in lower for tok in fail_tokens):
        result["status"] = "fail"
        result["detail"] = raw[:400]
    return result


def parse_encrypted_block_devices(node_path: str) -> dict:
    """Best-effort detection of LUKS/dm-crypt encryption for data devices."""
    result = {"encrypted": None, "evidence": ""}
    texts: list[str] = []
    for dirname in ("lsblk", "lsblkAllJson", "lsblkRota", "encryptedBlockDevice"):
        d = os.path.join(node_path, dirname)
        content = read_stdout(node_path, dirname)
        if content:
            texts.append(content)
        if os.path.isdir(d):
            for root_d, _dirs, files in os.walk(d):
                for fname in files:
                    fpath = os.path.join(root_d, fname)
                    try:
                        with open(fpath, "r", errors="ignore") as fh:
                            texts.append(fh.read(32768))
                    except Exception as exc:
                        logger.debug("parser: encrypted device read failed: %s", exc, exc_info=exc)
    blob = parse_json_file(node_path, "lsblkAllJson.json")
    if blob is not None:
        texts.append(json.dumps(blob))
    if not texts:
        return result
    joined = "\n".join(texts)
    result["evidence"] = joined[:500]
    lower = joined.lower()
    if any(tok in lower for tok in ("crypt", "luks", "dm-crypt", "type=\"crypt\"")):
        result["encrypted"] = True
    elif re.search(r"\b(rota|disk|part)\b", lower):
        # Device inventory present but no crypt markers → treat as unencrypted
        result["encrypted"] = False
    return result


def parse_process_limits(node_path: str) -> dict:
    pl_dir = os.path.join(node_path, "memsqldProcessLimits")
    if not os.path.isdir(pl_dir):
        return {}
    result = {"raw": "", "open_files_soft": 0, "open_files_hard": 0}
    for f in os.listdir(pl_dir):
        fpath = os.path.join(pl_dir, f)
        if os.path.isfile(fpath):
            try:
                # Limit read to 10KB to prevent memory issues
                with open(fpath, 'r') as fh:
                    content = fh.read(10240)
                result["raw"] = content[:2000]
                for line in content.split('\n'):
                    if 'Max open files' in line:
                        parts = line.split()
                        # Find numeric values
                        nums = [safe_int(p) for p in parts if p.isdigit()]
                        if len(nums) >= 2:
                            result["open_files_soft"] = nums[0]
                            result["open_files_hard"] = nums[1]
                        elif len(nums) == 1:
                            result["open_files_soft"] = nums[0]
                            result["open_files_hard"] = nums[0]
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return result


def parse_security_limits(node_path: str) -> str:
    sl_dir = os.path.join(node_path, "securityLimits")
    if not os.path.isdir(sl_dir):
        return ""
    parts = []
    for root_d, dirs, files in os.walk(sl_dir):
        for f in files:
            try:
                # Limit read to 5KB to prevent memory issues
                with open(os.path.join(root_d, f), 'r') as fh:
                    content = fh.read(5120)
                if content.strip() and not content.startswith('#'):
                    parts.append(f"{f}:\n{content[:500]}")
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return '\n'.join(parts)[:3000]


def parse_numa(node_path: str) -> dict:
    numa_dir = os.path.join(node_path, "numactl")
    result = {"raw": ""}
    if os.path.isdir(numa_dir):
        for f in os.listdir(numa_dir):
            fpath = os.path.join(numa_dir, f)
            if os.path.isfile(fpath):
                try:
                    # Limit read to 10KB to prevent memory issues
                    with open(fpath, 'r') as fh:
                        result["raw"] = fh.read(10240)[:2000]
                except Exception as exc:
                    logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    numa_config = parse_json_file(node_path, "memsqlNumaConfig.json")
    if numa_config:
        result["config"] = numa_config
    return result


def parse_dmesg_raw(node_path: str) -> list:
    dmesg_dir = os.path.join(node_path, "dmesg")
    if not os.path.isdir(dmesg_dir):
        return []
    lines = []
    for f in os.listdir(dmesg_dir):
        fpath = os.path.join(dmesg_dir, f)
        if os.path.isfile(fpath) and not f.endswith('.json'):
            try:
                with open(fpath) as fh:
                    for line in fh:
                        stripped = line.strip()
                        if stripped:
                            lines.append({"line": stripped[:500], "source": f})
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return lines[-200:]


def _dmesg_collector_status(node_path: str) -> dict:
    """Track whether dmesg stdout was collected or only stderr/unavailable."""
    dmesg_dir = os.path.join(node_path, "dmesg")
    if not os.path.isdir(dmesg_dir):
        return {"available": False, "stdout": False, "stderr_only": False, "line_count": 0}
    files = [
        f.lower() for f in os.listdir(dmesg_dir)
        if os.path.isfile(os.path.join(dmesg_dir, f)) and not f.endswith(".json")
    ]
    has_stdout = any("stdout" in f for f in files)
    has_stderr = any("stderr" in f for f in files)
    raw = parse_dmesg_raw(node_path)
    return {
        "available": bool(raw),
        "stdout": has_stdout,
        "stderr_only": has_stderr and not has_stdout,
        "line_count": len(raw),
    }


def classify_dmesg_events(raw_lines: list, hostname: str, role: str) -> list:
    events = []
    for item in raw_lines:
        line = item["line"]
        for pat in get_dmesg_patterns():
            if pat["pattern"].search(line):
                events.append({
                    "hostname": hostname, "role": role,
                    "category": pat["category"], "severity": pat["severity"],
                    "title": pat["title"], "conclusion": pat["conclusion"],
                    "line": line[:300],
                })
                break
    return events


def parse_license(node_path: str) -> dict:
    data = parse_json_file(node_path, "licenseMetadata.json")
    if not data:
        return {}
    if isinstance(data, list) and data:
        item = data[0]
        if isinstance(item, dict) and "LicenseData" in item:
            ld = item["LicenseData"]
            expiry_ts = safe_int(ld.get("licenseExpiration", 0))
            expiry_date = ""
            days_remaining = None
            if expiry_ts > 0:
                expiry_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
                expiry_date = expiry_dt.isoformat()
                days_remaining = (expiry_dt - datetime.now(timezone.utc)).days
            return {
                "type": ld.get("licenseType", ""),
                "capacity": ld.get("licenseCapacity", ""),
                "expiry_timestamp": expiry_ts,
                "expiry_date": expiry_date,
                "days_remaining": days_remaining,
                "version": ld.get("licenseVersion", ""),
            }
    return {}


def parse_ps_output(node_path: str) -> list:
    """Parse ``ps aux`` output from a report node directory.

    Column layout (11 fields when COMMAND may contain spaces)::

        USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
    """
    content = read_stdout(node_path, "ps")
    if not content:
        return []
    rows = []
    lines = content.split('\n')
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # maxsplit=10 keeps COMMAND intact (may contain spaces).
        parts = stripped.split(None, 10)
        if len(parts) >= 2 and parts[0].startswith('USER'):
            continue
        if len(parts) >= 11:
            rows.append({
                "user": parts[0],
                "pid": parts[1],
                "cpu_pct": parts[2],
                "mem_pct": parts[3],
                "vsz": parts[4],
                "rss": parts[5],
                "tty": parts[6],
                "stat": parts[7],
                "start": parts[8],
                "time": parts[9],
                "cmd": parts[10],
            })
    return rows


def _flatten_sysinfo_value(val) -> list:
    """Normalize MV_SYSINFO payloads: dict rows, flat list, or wrapped {columns, rows} list."""
    if not val:
        return []
    if isinstance(val, dict):
        rows = val.get("rows")
        return rows if isinstance(rows, list) else []
    if isinstance(val, list):
        flat: list = []
        for item in val:
            if not isinstance(item, dict):
                continue
            nested = item.get("rows")
            if isinstance(nested, list) and nested:
                flat.extend(nested)
            elif "NODE_ID" in item or "node_id" in item:
                flat.append(item)
        return flat
    return []


def parse_mv_sysinfo(node_path: str) -> dict:
    data = parse_json_file(node_path, "informationSchemaMvSysinfo.json")
    if not data or not isinstance(data, dict):
        return {}
    result = {}
    for key in ["MV_SYSINFO_CPU", "MV_SYSINFO_MEM", "MV_SYSINFO_DISK", "MV_SYSINFO_NET", "MV_SYSINFO_CPULIST"]:
        val = data.get(key)
        if val is not None:
            result[key] = _flatten_sysinfo_value(val)
    return result


def extract_alloc_memory_metrics(rows: list) -> list:
    metrics = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        metric_name = None
        for value in row.values():
            if isinstance(value, str) and value.startswith("Alloc_"):
                metric_name = value
                break

        if not metric_name:
            continue

        raw_value = None
        for key in ["Value", "VALUE", "value", "Variable_value", "Status_value"]:
            if key in row:
                raw_value = row[key]
                break

        if raw_value is None:
            for key, value in row.items():
                if value == metric_name:
                    continue
                if isinstance(value, (int, float, str)):
                    raw_value = value
                    break

        value_num = safe_int(raw_value)
        metrics.append({
            "metric": metric_name,
            "value": value_num,
            "raw_value": str(raw_value) if raw_value is not None else "",
        })

    metrics.sort(key=lambda item: item["value"], reverse=True)
    return metrics


def build_alloc_memory_overview(nodes: list) -> dict:
    per_node = []
    totals = defaultdict(int)

    for node in nodes:
        alloc_metrics = node.get("metrics", {}).get("alloc_memory", [])
        if not alloc_metrics:
            continue

        for item in alloc_metrics:
            totals[item["metric"]] += item.get("value", 0)

        per_node.append({
            "hostname": node.get("hostname", "unknown"),
            "role": node.get("role", "unknown"),
            "total_bytes": sum(item.get("value", 0) for item in alloc_metrics),
            "top_metrics": alloc_metrics[:8],
        })

    per_node.sort(key=lambda item: item["total_bytes"], reverse=True)
    total_metrics = [
        {"metric": metric, "value": value}
        for metric, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "per_node": per_node,
        "totals": total_metrics[:12],
    }


def infer_deployment_method(
    nodes: list,
    cluster_overview: dict,
    report_root: str | None = None,
) -> dict:
    signals = []
    method = "Linux (sdb-deploy)"
    confidence = "low"

    if report_root and os.path.isdir(os.path.join(report_root, "kube-metadata")):
        method = "Kubernetes Operator"
        confidence = "high"
        signals.append("collector:kube-metadata")

    for node in nodes or []:
        hostname = (node.get("hostname") or "").lower()
        if "helios" in hostname:
            method = "Helios Cloud Portal"
            confidence = "high"
            signals.append("hostname:helios")
            break

    if method == "Linux (sdb-deploy)":
        for node in nodes or []:
            procs = (node.get("ps") or (node.get("metrics", {}) or {}).get("ps") or [])
            for proc in procs:
                cmd = str(proc.get("cmd", "")).lower()
                if "kubelet" in cmd or "kube-proxy" in cmd:
                    method = "Kubernetes Operator"
                    confidence = "high"
                    signals.append("process:kubelet")
                    break
                if "dockerd" in cmd or "containerd" in cmd:
                    method = "Docker Dev Image"
                    confidence = "medium"
                    signals.append("process:docker")
                    break
            if method != "Linux (sdb-deploy)":
                break

    uniq_signals = []
    seen = set()
    for s in signals:
        if s not in seen:
            seen.add(s)
            uniq_signals.append(s)

    return {"method": method, "confidence": confidence, "signals": uniq_signals[:10]}


def parse_partitions(node_path: str) -> dict:
    data = parse_json_file(node_path, "showPartitions.json")
    if not data or not isinstance(data, dict):
        return {}
    result = {}
    for memsql_id, val in data.items():
        if isinstance(val, dict):
            for dbname, dbval in val.items():
                if isinstance(dbval, dict) and "rows" in dbval:
                    rows = dbval.get("rows") or []
                    sample = _cap_rows(rows, MAX_PARTITION_ROWS_PER_DB)
                    result[dbname] = {
                        "columns": dbval.get("columns", []),
                        "partitions": sample,
                        "count": len(rows) if isinstance(rows, list) else 0,
                        "sample_count": len(sample),
                        "truncated": isinstance(rows, list) and len(rows) > len(sample),
                    }
    return result


def parse_version_history(node_path: str) -> list:
    data = parse_json_file(node_path, "informationSchemaMvVersionHistory.json")
    if not data or not isinstance(data, dict):
        return []
    rows = []
    for key, val in data.items():
        if isinstance(val, dict) and "rows" in val:
            rows.extend(val["rows"])
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "rows" in item:
                    rows.extend(item["rows"])
    return _cap_rows(rows, MAX_VERSION_HISTORY_ROWS)


# ─── SingleStore JSON parsers ───────────────────────────────────────

def parse_json_file(node_path: str, filename: str):
    fpath = os.path.join(node_path, filename)
    if not os.path.exists(fpath):
        return None
    try:
        try:
            size = os.path.getsize(fpath)
            limit = _json_file_size_limit(filename)
            if size > limit:
                logger.warning(f"Skipping large JSON file {filename} ({size} bytes > {limit} bytes)")
                return None
        except Exception as exc:
            logger.debug("parser: ignoring non-fatal error", exc_info=exc)
        with open(fpath) as f:
            return json.load(f)
    except Exception:
        return None


def parse_sdb_json_table(node_path: str, filename: str, row_cap: int | None = None) -> list:
    # Guard: do not follow collector files that are symlinks escaping the node dir.
    candidate = os.path.join(node_path, filename)
    if os.path.islink(candidate) and not path_is_within_root(candidate, node_path):
        logger.debug(
            "parse_sdb_json_table: skipping escaped symlink %s in %s", filename, node_path
        )
        return []
    if row_cap is None:
        row_cap = _default_sdb_json_row_cap(filename)
    return _load_sdb_json_rows(node_path, filename, row_cap)


def _default_sdb_json_row_cap(filename: str) -> int:
    caps = {
        "informationSchemaMvEvents.json": MAX_MV_EVENTS_ROWS,
        "informationSchemaMvBlockedQueries.json": MAX_BLOCKED_QUERIES_ROWS,
        "showWorkloadManagementStatus.json": MAX_WORKLOAD_MANAGEMENT_ROWS,
        "showReplicationStatus.json": MAX_REPLICATION_STATUS_ROWS,
        "informationSchemaTableStatistics.json": MAX_TABLE_STATISTICS_ROWS,
        "informationSchemaTables.json": MAX_INFORMATION_SCHEMA_TABLES_ROWS,
        "showResourcePools.json": MAX_RESOURCE_POOLS_ROWS,
        "databaseDiskUsage.json": MAX_DATABASE_DISK_USAGE_ROWS,
        "informationSchemaMvBackupHistory.json": MAX_BACKUP_HISTORY_ROWS,
        "informationSchemaMvVersionHistory.json": MAX_VERSION_HISTORY_ROWS,
        "informationSchemaAvailabilityGroups.json": MAX_AVAILABILITY_GROUPS_ROWS,
        "showUsers.json": MAX_USERS_ROWS,
        "informationSchemaPipelines.json": MAX_PIPELINES_ROWS,
        "informationSchemaMvProcesslist.json": MAX_RESOURCE_POOLS_ROWS,
        "informationSchemaProcesslist.json": MAX_RESOURCE_POOLS_ROWS,
        "informationSchemaMvQueries.json": MAX_RESOURCE_POOLS_ROWS,
        "informationSchemaIndexStatistics.json": MAX_TABLE_STATISTICS_ROWS,
        "informationSchemaColumnarSegments.json": MAX_COLUMNAR_SEGMENTS_ROWS,
    }
    return caps.get(filename, MAX_RESOURCE_POOLS_ROWS)


def parse_cluster_topology(node_path: str) -> dict:
    data = parse_json_file(node_path, "clusterTopology.json")
    if not data or not isinstance(data, dict):
        return {}
    result = {"leaves": [], "aggregators": []}
    for memsql_id, val in data.items():
        if isinstance(val, dict):
            if "ShowLeaves" in val and isinstance(val["ShowLeaves"], dict):
                if "rows" in val["ShowLeaves"]:
                    result["leaves"].extend(val["ShowLeaves"]["rows"])
            if "ShowAggregators" in val and isinstance(val["ShowAggregators"], dict):
                if "rows" in val["ShowAggregators"]:
                    result["aggregators"].extend(val["ShowAggregators"]["rows"])
    return result


def parse_pipelines(node_path: str) -> list:
    return _load_sdb_json_rows(node_path, "informationSchemaPipelines.json", MAX_PIPELINES_ROWS)


def parse_rebalance_status(node_path: str) -> list:
    """Best-effort parser for rebalance status collectors across report variants."""
    candidates = [
        "showRebalanceStatus.json",
        "showRebalanceStatusOn.json",
        "showRebalanceStatusOnAllDatabases.json",
        "explainRebalancePartitions.json",
    ]
    rows = []
    for name in candidates:
        rows.extend(parse_sdb_json_table(node_path, name))
    # Deduplicate while preserving order.
    seen = set()
    unique = []
    for row in rows:
        blob = json.dumps(row, sort_keys=True, default=str)
        if blob in seen:
            continue
        seen.add(blob)
        unique.append(row)
    return unique


# ─── Log parsers ───────────────────────────────────────────────────

# Compression format openers: (suffix_tuple, opener_fn)
_COMPRESSION_OPENERS = [
    (('.log.gz', '.gz'), lambda p: gzip.open(p, 'rt', errors='replace')),
    (('.log.bz2', '.bz2'), lambda p: bz2.open(p, 'rt', errors='replace')),
    (('.log.xz', '.xz'), lambda p: lzma.open(p, 'rt', errors='replace')),
    (('.log.zst',), None),  # requires zstandard lib — skipped if unavailable
    (('.log.lz4',), None),  # requires lz4 lib — skipped if unavailable
]


def _get_opener_for_file(filename: str, fpath: str):
    """Return a file-like object for reading, handling all compression formats."""
    lower = filename.lower()
    # Try each compression opener
    for suffixes, opener in _COMPRESSION_OPENERS:
        if opener is None:
            continue
        if any(lower.endswith(s) for s in suffixes):
            return opener(fpath)
    # Plain text
    return open(fpath, 'r', errors='replace')


def _is_tracelog_file(filename: str) -> bool:
    """Check if a filename looks like a memsql tracelog, including subsystem variants."""
    lower = filename.lower()
    if "_memsql.log" in lower:
        return lower.endswith("_memsql.log") or "_memsql.log." in lower
    if re.search(r"_memsql_[a-z0-9_]+\.log(?:\.|$)", lower):
        return True
    return False


def parse_trace_logs(node_path: str, hostname: str, role: str) -> list:
    logs_dir = os.path.join(node_path, "memsqlTracelogs")
    if not os.path.isdir(logs_dir):
        return []
    entries = []
    for f in sorted(os.listdir(logs_dir)):
        fpath = os.path.join(logs_dir, f)
        if not os.path.isfile(fpath):
            continue
        if not _is_tracelog_file(f):
            continue
        try:
            opener = _get_opener_for_file(f, fpath)
            with opener as fh:
                # Compressed files get fewer lines (cheaper to decompress),
                # plain logs get more for richer analysis. We keep the MOST
                # RECENT max_lines structured entries per file (tail), since
                # recent diagnostics are what matter for an incident report —
                # older history is already summarized in build_log_summary.
                max_lines = 500 if any(f.endswith(ext) for ext in ('.gz', '.bz2', '.xz', '.zst', '.lz4')) else 2000
                entries.extend(_parse_log_lines_tailed(fh, hostname, role, f, max_lines))
        except Exception as exc:
            logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return entries


def _parse_log_lines_tailed(fh, hostname, role, filename, max_lines=2000):
    """Parse log lines and return the most-recent ``max_lines`` structured entries.

    Uses a bounded ring buffer so memory stays proportional to ``max_lines``
    regardless of file size, instead of materialising the whole file. This
    preserves continuation-line accumulation (see ``_parse_log_lines``) while
    keeping the tail of the file — the part most relevant for incident triage.
    """
    from collections import deque
    ring: deque = deque(maxlen=max_lines)
    current = None
    max_continuation_chars = 4000
    for line in fh:
        m = LOG_LINE_PATTERN.match(line.strip())
        if m:
            severity = m.group(3)
            if severity == "WARNING":
                severity = "WARN"
            current = {
                "timestamp": m.group(2).strip(),
                "severity": severity,
                "message": m.group(4).strip()[:1000],
                "hostname": hostname, "role": role, "source": filename,
            }
            ring.append(current)
        else:
            if current is None:
                continue
            cont = line.rstrip()
            if not cont:
                continue
            if len(current["message"]) < max_continuation_chars:
                current["message"] = (current["message"] + "\n" + cont)[:max_continuation_chars]
    return list(ring)


_MAX_RAW_SEARCH_FILE_BYTES = 80 * 1024 * 1024
_INLINE_SEV_RE = re.compile(r'\b(INFO|WARN|WARNING|ERROR|FATAL|NOTICE|DEBUG):', re.I)


def _parse_trace_line_meta(line: str) -> tuple[str | None, str | None]:
    m = LOG_LINE_PATTERN.match(line.strip())
    if m:
        sev = m.group(3)
        if sev == "WARNING":
            sev = "WARN"
        return sev, m.group(2).strip()
    inline = _INLINE_SEV_RE.search(line)
    if inline:
        sev = inline.group(1).upper()
        if sev == "WARNING":
            sev = "WARN"
        return sev, None
    return None, None


def _raw_severity_matches(filter_sev: str | None, line_sev: str | None) -> bool:
    if not filter_sev:
        return True
    fs = filter_sev.upper()
    if fs == "WARNING":
        fs = "WARN"
    ls = (line_sev or "").upper()
    return ls == fs


def _search_tracelog_file_streaming(
    fh,
    *,
    pattern: re.Pattern,
    severity: str | None,
    max_results: int,
    context_lines: int,
    hostname: str,
    role: str,
    source: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> tuple[list[dict], int]:
    """Bounded-memory tracelog search with before/after context via read-ahead pushback."""
    from collections import deque

    matches: list[dict] = []
    total = 0
    prev: deque[str] = deque(maxlen=max(0, context_lines))
    pending_after: deque[str] = deque()

    while True:
        if pending_after:
            line = pending_after.popleft()
        else:
            line = fh.readline()
        if not line:
            break
        text = line.rstrip()
        if not pattern.search(text):
            prev.append(text)
            continue

        line_sev, line_ts = _parse_trace_line_meta(text)
        if not _raw_severity_matches(severity, line_sev):
            prev.append(text)
            continue
        parsed_ts = _parse_timestamp(line_ts)
        if (start_time and (parsed_ts is None or parsed_ts < start_time)) or (
            end_time and (parsed_ts is None or parsed_ts > end_time)
        ):
            prev.append(text)
            continue

        total += 1
        ctx_before = list(prev)
        ctx_after: list[str] = []
        for _ in range(context_lines):
            nxt = fh.readline()
            if not nxt:
                break
            nxt_text = nxt.rstrip()
            ctx_after.append(nxt_text)
            pending_after.append(nxt)

        if len(matches) < max_results:
            matches.append({
                "line_number": 0,
                "line": text,
                "timestamp": line_ts or "",
                "severity": line_sev or "INFO",
                "source": source,
                "hostname": hostname,
                "role": role,
                "context_before": ctx_before,
                "context_after": ctx_after,
                "is_match": True,
            })
        prev.append(text)

    return matches, total


def search_trace_logs_raw(
    node_path: str,
    hostname: str,
    role: str,
    keyword: str,
    regex: bool = False,
    severity: str = None,
    case_sensitive: bool = False,
    max_results: int = 1000,
    context_lines: int = 2,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict:
    """
    Ripgrep-style search across ALL tracelog files (compressed + uncompressed).
    Returns matching lines with context, like `rg --context=2`.

    Args:
        node_path: Path to the node directory containing memsqlTracelogs/
        hostname: Node hostname
        role: Node role
        keyword: Search term or regex pattern
        regex: If True, treat keyword as a regex pattern
        severity: Optional filter by severity (ERROR, WARN, INFO, FATAL)
        case_sensitive: If True, case-sensitive search
        max_results: Maximum number of matching lines to return
        context_lines: Number of context lines before/after each match
    """
    logs_dir = os.path.join(node_path, "memsqlTracelogs")
    if not os.path.isdir(logs_dir):
        return {"matches": [], "total": 0, "files_searched": 0}

    # Build search pattern
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        if regex:
            pattern = re.compile(keyword, flags)
        else:
            escaped = re.escape(keyword)
            pattern = re.compile(escaped, flags)
    except re.error:
        return {"matches": [], "total": 0, "files_searched": 0, "error": "Invalid regex pattern"}

    matches = []
    total = 0
    files_searched = 0

    for f in sorted(os.listdir(logs_dir)):
        fpath = os.path.join(logs_dir, f)
        if not os.path.isfile(fpath):
            continue
        if not _is_tracelog_file(f):
            continue

        files_searched += 1
        try:
            opener = _get_opener_for_file(f, fpath)
            with opener as fh:
                file_size = os.path.getsize(fpath)
                if file_size <= _MAX_RAW_SEARCH_FILE_BYTES:
                    all_lines = list(fh)
                    if not all_lines:
                        continue
                    for i, line in enumerate(all_lines):
                        if not pattern.search(line):
                            continue
                        line_sev, line_ts = _parse_trace_line_meta(line)
                        if not _raw_severity_matches(severity, line_sev):
                            continue
                        parsed_ts = _parse_timestamp(line_ts)
                        if (start_time and (parsed_ts is None or parsed_ts < start_time)) or (
                            end_time and (parsed_ts is None or parsed_ts > end_time)
                        ):
                            continue
                        total += 1
                        if len(matches) >= max_results:
                            continue
                        ctx_before = [all_lines[j].rstrip() for j in range(max(0, i - context_lines), i)]
                        ctx_after = [
                            all_lines[j].rstrip()
                            for j in range(i + 1, min(len(all_lines), i + 1 + context_lines))
                        ]
                        matches.append({
                            "line_number": i + 1,
                            "line": line.rstrip(),
                            "timestamp": line_ts or "",
                            "severity": line_sev or "INFO",
                            "source": f,
                            "hostname": hostname,
                            "role": role,
                            "context_before": ctx_before,
                            "context_after": ctx_after,
                            "is_match": True,
                        })
                else:
                    file_matches, file_total = _search_tracelog_file_streaming(
                        fh,
                        pattern=pattern,
                        severity=severity,
                        max_results=max(0, max_results - len(matches)),
                        context_lines=context_lines,
                        hostname=hostname,
                        role=role,
                        source=f,
                        start_time=start_time,
                        end_time=end_time,
                    )
                    total += file_total
                    matches.extend(file_matches)
                    if len(matches) >= max_results:
                        matches = matches[:max_results]
                        break
        except Exception as exc:
            logger.debug("parser: ignoring non-fatal error", exc_info=exc)

    return {
        "matches": matches,
        "total": total,
        "files_searched": files_searched,
        "truncated": total > max_results,
    }






def search_all_trace_logs(extracted_root: str, keyword: str, **kwargs) -> dict:
    """Search trace logs across all nodes under an extracted report root."""
    node_filter = kwargs.pop("node_filter", None)
    max_results = kwargs.get("max_results", 1000)
    severity = kwargs.get("severity", None)

    # severity alias
    if severity == "WARNING":
        kwargs["severity"] = "WARN"

    def _clean_hostname(name: str) -> str:
        return re.sub(r"-(MA|CA|LEAF|AGGREGATOR|MASTER)$", "", name)

    all_matches = []
    total = 0
    files_searched = 0
    nodes_searched = 0
    root_path = Path(extracted_root)
    if not root_path.exists():
        return {
            "matches": [],
            "total": 0,
            "files_searched": 0,
            "nodes_searched": 0,
            "truncated": False,
        }

    node_dirs = [p for p in root_path.iterdir() if p.is_dir() and (p / "memsqlTracelogs").is_dir()]
    if node_filter:
        node_dirs = [p for p in node_dirs if node_filter in p.name]

    for node_path in sorted(node_dirs):
        res = search_trace_logs_raw(
            str(node_path),
            hostname=_clean_hostname(node_path.name),
            role="NODE",
            keyword=keyword,
            **kwargs,
        )
        all_matches.extend(res.get("matches", []))
        total += res.get("total", 0)
        files_searched += res.get("files_searched", 0)
        if res.get("total", 0) > 0:
            nodes_searched += 1

    all_matches.sort(key=lambda m: m.get("timestamp", ""))
    truncated = total > max_results
    if len(all_matches) > max_results:
        all_matches = all_matches[:max_results]

    return {
        "matches": all_matches,
        "total": total,
        "files_searched": files_searched,
        "nodes_searched": nodes_searched,
        "truncated": truncated,
    }

def _parse_log_lines(fh, hostname, role, filename, max_lines=2000):
    """Parse structured SingleStore tracelog lines into log entries.

    Lines that do not match the canonical ``<pid> <ts> <SEV>: <msg>`` header
    are treated as continuation lines of the previous structured entry (e.g.
    multi-line stack traces / backtraces) and appended to its message so
    crash diagnostics are not lost. The continuation is capped per entry to
    keep memory bounded.
    """
    entries = []
    count = 0
    max_continuation_chars = 4000
    current = None
    for line in fh:
        if count >= max_lines:
            break
        m = LOG_LINE_PATTERN.match(line.strip())
        if m:
            severity = m.group(3)
            if severity == "WARNING":
                severity = "WARN"
            current = {
                "timestamp": m.group(2).strip(),
                "severity": severity,
                "message": m.group(4).strip()[:1000],
                "hostname": hostname, "role": role, "source": filename,
            }
            entries.append(current)
            count += 1
        else:
            # Continuation of the previous structured entry (multi-line
            # stack trace, backtrace, or wrapped message). Preserve it so
            # downstream pattern detection (e.g. SIGSEGV backtrace) sees the
            # full context instead of just the first line.
            if current is None:
                continue
            cont = line.rstrip()
            if not cont:
                continue
            if len(current["message"]) < max_continuation_chars:
                current["message"] = (current["message"] + "\n" + cont)[:max_continuation_chars]
    return entries


def detect_log_patterns(all_logs: list) -> list:
    """Detect critical patterns in log messages.

    Per-pattern scan is kept (rather than a combined alternation regex)
    because profiling on 50k-line bundles showed the per-pattern form is
    ~1.5x faster: the compiled per-pattern regexes short-circuit on the
    95% of lines that match nothing, and Python's re engine does not
    optimize the 12-way alternation into a single DFA pass.
    """
    detected = defaultdict(lambda: {"count": 0, "first_seen": "", "last_seen": "", "sample": "", "nodes": set()})
    for log in all_logs:
        msg = log.get("message", "")
        for pat in get_critical_log_patterns():
            if pat["pattern"].search(msg):
                key = pat["category"]
                d = detected[key]
                d["count"] += 1
                d["nodes"].add(log.get("hostname", ""))
                if not d["first_seen"]:
                    d["first_seen"] = log.get("timestamp", "")
                d["last_seen"] = log.get("timestamp", "")
                if not d["sample"]:
                    d["sample"] = msg[:300]
                d["category"] = pat["category"]
                d["title"] = pat["title"]
                d["severity"] = pat["severity"]
                d["conclusion"] = pat["conclusion"]
                d["doc_link"] = pat.get("doc_link", "")
                break
    result = []
    for key, val in detected.items():
        val["nodes"] = sorted(list(val["nodes"]))
        result.append(val)
    result.sort(key=lambda x: {"critical": 0, "warning": 1, "info": 2}.get(x.get("severity", "info"), 2))
    return result


def build_log_summary(logs: list) -> dict:
    severity_counts = defaultdict(int)
    node_severity = defaultdict(lambda: defaultdict(int))
    hourly_counts = defaultdict(lambda: defaultdict(int))
    node_ranges = defaultdict(lambda: {"first": None, "last": None})

    for entry in logs:
        sev = entry.get("severity", "INFO")
        hostname = entry.get("hostname", "unknown")
        severity_counts[sev] += 1
        node_severity[hostname][sev] += 1
        ts = entry.get("timestamp", "")
        
        if ts:
            ts_dt = _parse_timestamp(ts)
            first_ts = node_ranges[hostname]["first"]
            last_ts = node_ranges[hostname]["last"]
            if not first_ts:
                node_ranges[hostname]["first"] = ts
            else:
                first_dt = _parse_timestamp(first_ts)
                if ts_dt and (first_dt is None or ts_dt < first_dt):
                    node_ranges[hostname]["first"] = ts
                elif first_dt is None and ts < first_ts:
                    node_ranges[hostname]["first"] = ts
            if not last_ts:
                node_ranges[hostname]["last"] = ts
            else:
                last_dt = _parse_timestamp(last_ts)
                if ts_dt and (last_dt is None or ts_dt > last_dt):
                    node_ranges[hostname]["last"] = ts
                elif last_dt is None and ts > last_ts:
                    node_ranges[hostname]["last"] = ts

        hour = _hour_bucket(ts)
        if hour:
            hourly_counts[hour][sev] += 1

    per_node = {}
    for hostname, counts in node_severity.items():
        per_node[hostname] = dict(counts)
        per_node[hostname]["first_ts"] = node_ranges[hostname]["first"]
        per_node[hostname]["last_ts"] = node_ranges[hostname]["last"]

    return {
        "total": len(logs),
        "severity_counts": dict(severity_counts),
        "per_node": per_node,
        "hourly": {k: dict(v) for k, v in sorted(hourly_counts.items())},
    }


# ─── High-value diagnostic helpers ────────────────────────────────

_pressure_patterns_cached = None

def _get_pressure_patterns():
    global _pressure_patterns_cached
    if _pressure_patterns_cached is None:
        _pressure_patterns_cached = {
            "etimedout": re.compile(r'ETIMEDOUT|Connection timed out', re.I),
            "fsync_behind": re.compile(r'fsync is behind|slow fsync', re.I),
            "retry_stall": re.compile(r'Retry loop is stalling|stalling retry loop', re.I),
            "async_transition": re.compile(
                r'(?:from\s+sync(?:hronous)?\s+to\s+async(?:hronous)?'
                r'|sync(?:hronous)?\s*(?:->|→)\s*async(?:hronous)?'
                r'|transition(?:ed|ing)?\s+from\s+sync(?:hronous)?\s+to\s+async(?:hronous)?)',
                re.I,
            ),
        }
    return _pressure_patterns_cached


def extract_log_timeframe(nodes: list) -> dict:
    """Return per-node first/last log timestamps and overall coverage span.

    Returns a dict keyed by hostname with ``first_log_entry``,
    ``last_log_entry``, and ``coverage_hours`` values, plus a
    ``cluster_first`` / ``cluster_last`` summary.
    """
    per_node: dict = {}
    all_firsts: list = []
    all_lasts: list = []
    for node in nodes:
        hostname = node.get("hostname", "unknown")
        summary = node.get("log_summary", {}) or {}
        per_n = summary.get("per_node", {}) or {}
        first_ts = per_n.get(hostname, {}).get("first_ts") or ""
        last_ts = per_n.get(hostname, {}).get("last_ts") or ""
        # Also search trace_logs (present during parse, stripped later)
        logs = node.get("trace_logs", [])
        if logs:
            ts_list = [e.get("timestamp", "") for e in logs if e.get("timestamp")]
            if ts_list:
                trace_first = min(
                    ts_list,
                    key=lambda ts: (_parse_timestamp(ts) is None, _parse_timestamp(ts) or datetime.max.replace(tzinfo=timezone.utc)),
                )
                trace_last = max(
                    ts_list,
                    key=lambda ts: (_parse_timestamp(ts) is not None, _parse_timestamp(ts) or datetime.min.replace(tzinfo=timezone.utc)),
                )
                if not first_ts:
                    first_ts = trace_first
                else:
                    first_dt = _parse_timestamp(first_ts)
                    trace_first_dt = _parse_timestamp(trace_first)
                    if trace_first_dt and (first_dt is None or trace_first_dt < first_dt):
                        first_ts = trace_first
                    elif first_dt is None and trace_first < first_ts:
                        first_ts = trace_first
                if not last_ts:
                    last_ts = trace_last
                else:
                    last_dt = _parse_timestamp(last_ts)
                    trace_last_dt = _parse_timestamp(trace_last)
                    if trace_last_dt and (last_dt is None or trace_last_dt > last_dt):
                        last_ts = trace_last
                    elif last_dt is None and trace_last > last_ts:
                        last_ts = trace_last
        coverage_hours: float = 0.0
        if first_ts and last_ts:
            try:
                dt_first = _parse_timestamp(first_ts)
                dt_last = _parse_timestamp(last_ts)
                if dt_first is None or dt_last is None:
                    raise ValueError("unparseable log coverage timestamps")
                coverage_hours = round((dt_last - dt_first).total_seconds() / 3600, 2)
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
        per_node[hostname] = {
            "first_log_entry": first_ts,
            "last_log_entry": last_ts,
            "coverage_hours": coverage_hours,
        }
        if first_ts:
            all_firsts.append(first_ts)
        if last_ts:
            all_lasts.append(last_ts)
    return {
        "per_node": per_node,
        "cluster_first": min(all_firsts) if all_firsts else "",
        "cluster_last": max(all_lasts) if all_lasts else "",
    }


def summarize_backup_history(backup_history: list) -> dict:
    """Compute success/failure counts and latest successful backup duration.

    Returns::

        {
            "total": int,
            "success_count": int,
            "failure_count": int,
            "latest_success_ts": str,
            "latest_duration_sec": float | None,
        }
    """
    if not backup_history:
        return {
            "total": 0, "success_count": 0, "failure_count": 0,
            "latest_success_ts": "", "latest_duration_sec": None,
        }
    total = len(backup_history)
    success_count = 0
    failure_count = 0
    successful_rows: list = []
    for row in backup_history:
        status = str(row.get("STATUS", row.get("status", ""))).lower()
        if status in ("success", "completed"):
            success_count += 1
            successful_rows.append(row)
        elif status in ("failure", "failed", "error"):
            failure_count += 1
    latest_ts = ""
    latest_duration: float | None = None
    if successful_rows:
        def _row_ts(row):
            return str(row.get("END_TIMESTAMP") or row.get("START_TIMESTAMP") or "")

        best = max(
            successful_rows,
            key=lambda row: (
                _parse_timestamp(_row_ts(row)) is not None,
                _parse_timestamp(_row_ts(row)) or datetime.min.replace(tzinfo=timezone.utc),
            ),
        )
        latest_ts = _row_ts(best)
        start = str(best.get("START_TIMESTAMP", ""))
        end = str(best.get("END_TIMESTAMP", ""))
        if start and end:
            try:
                dt_s = _parse_timestamp(start)
                dt_e = _parse_timestamp(end)
                if dt_s is None or dt_e is None:
                    raise ValueError("unparseable backup timestamps")
                latest_duration = round((dt_e - dt_s).total_seconds(), 1)
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return {
        "total": total,
        "success_count": success_count,
        "failure_count": failure_count,
        "latest_success_ts": latest_ts,
        "latest_duration_sec": latest_duration,
    }


def compute_pressure_events_per_hour(all_logs: list) -> dict:
    """Count ETIMEDOUT, fsync-behind, and retry-stall events per hour bucket.

    Returns a dict of event type → dict of hour-bucket → count, e.g.::

        {
            "etimedout": {"2024-01-01 10": 3, "2024-01-01 11": 7},
            "fsync_behind": {...},
            "retry_stall": {...},
        }
    """
    patterns = _get_pressure_patterns()
    counts: dict = {k: defaultdict(int) for k in patterns}
    for entry in all_logs:
        msg = entry.get("message", "")
        ts = entry.get("timestamp", "")
        hour_bucket = _hour_bucket(ts)
        for key, pat in patterns.items():
            if hour_bucket and pat.search(msg):
                counts[key][hour_bucket] += 1
                break
    return {k: dict(v) for k, v in counts.items()}


def extract_node_events(events: list) -> list:
    """Filter MV_EVENTS for node state-transition events (offline, online, failover).

    Returns a list of dicts sorted newest-first, capped at 200 rows::

        [{"event_type": str, "event_time": str, "severity": str,
          "node_id": str, "description": str, "category": str}, ...]

    ``category`` is one of "node_down", "node_up", "failover", "state_change".
    """
    _node_keywords = ["leaf", "aggregator", "master", "failover", "node_fail", "node_recov"]
    result = []
    seen: set = set()
    for row in events:
        evt_type = str(row.get("EVENT_TYPE") or row.get("EVENT") or "").strip()
        upper = evt_type.upper()
        lower = evt_type.lower()
        if upper not in _MV_EVENTS_ALLOWLIST and \
                not any(kw in lower for kw in _node_keywords) and \
                not (("offline" in lower or "online" in lower or "detach" in lower or
                      "attach" in lower or "starting" in lower) and
                     any(r in lower for r in ["leaf", "aggr", "master", "node"])):
            continue
        evt_time = str(row.get("EVENT_TIME") or row.get("TIMESTAMP") or row.get("TIME") or "")
        severity = str(row.get("SEVERITY") or "").upper()
        node_id = str(row.get("ORIGIN_NODE_ID") or row.get("NODE_ID") or row.get("NodeId") or "")
        description = str(row.get("EVENT_DESCRIPTION") or row.get("DESCRIPTION") or row.get("EXTRA_INFO") or "")
        key = f"{evt_type}|{evt_time}|{node_id}"
        if key in seen:
            continue
        seen.add(key)
        if "failover" in lower or upper == "NEW_MASTER_AGGREGATOR":
            category = "failover"
        elif upper == "WORKLOAD_THROTTLE":
            category = "workload"
        elif any(x in lower for x in ["rebalance"]):
            category = "rebalance"
        elif any(x in lower for x in ["consensus", "election"]):
            category = "consensus"
        elif any(x in lower for x in ["pipeline"]):
            category = "pipeline"
        elif upper == "SYSTEM_VAR_CHANGED":
            category = "configuration"
        elif any(x in lower for x in ["offline", "fail", "crash", "down", "detached", "detach"]):
            category = "node_down"
        elif any(x in lower for x in ["online", "recover", "up", "attach", "starting", "leaf_add"]):
            category = "node_up"
        else:
            category = "state_change"
        result.append({
            "event_type": evt_type,
            "event_time": evt_time,
            "severity": severity,
            "node_id": node_id,
            "description": description,
            "category": category,
        })
    result.sort(key=lambda x: x["event_time"], reverse=True)
    return result[:200]


def extract_rebalance_events(events: list, rebalance_status: list) -> dict:
    """Extract rebalance and partition-movement events from MV_EVENTS.

    Returns::

        {
            "status": "IDLE" | "ACTIVE" | "FAILED",
            "reason": str,
            "events": [...],      # newest-first, capped at 100
            "raw_status": [...],  # capped at 50
        }
    """
    _rb_keywords = ["rebalance", "partition", "sync", "move", "replac"]
    rb_evts = []
    seen: set = set()
    for row in events:
        evt_type = str(row.get("EVENT_TYPE") or row.get("EVENT") or "").strip()
        upper = evt_type.upper()
        lower = evt_type.lower()
        if upper not in _REBALANCE_EVENT_ENUMS and not any(k in lower for k in _rb_keywords):
            continue
        evt_time = str(row.get("EVENT_TIME") or row.get("TIMESTAMP") or row.get("TIME") or "")
        severity = str(row.get("SEVERITY") or "").upper()
        node_id = str(row.get("ORIGIN_NODE_ID") or row.get("NODE_ID") or "")
        description = str(row.get("EVENT_DESCRIPTION") or row.get("DESCRIPTION") or "")
        key = f"{evt_type}|{evt_time}|{node_id}"
        if key in seen:
            continue
        seen.add(key)
        rb_evts.append({
            "event_type": evt_type,
            "event_time": evt_time,
            "severity": severity,
            "node_id": node_id,
            "description": description,
        })
    rb_evts.sort(key=lambda x: x["event_time"], reverse=True)

    # Determine current rebalance status from raw rebalance_status rows
    current_status = "IDLE"
    reason = ""
    for row in (rebalance_status or []):
        status_val = str(row.get("Status") or row.get("STATUS") or "").lower()
        if any(x in status_val for x in ["error", "fail", "could not", "timed out"]):
            current_status = "FAILED"
            reason = status_val[:200]
        elif any(x in status_val for x in ["in progress", "running", "active", "rebalanc"]):
            current_status = "ACTIVE"
            break

    # If raw status doesn't indicate activity, check recent events
    if current_status == "IDLE" and rb_evts:
        latest_lower = rb_evts[0]["event_type"].lower()
        if any(x in latest_lower for x in ["start", "begin", "initiat"]) and "complete" not in latest_lower:
            current_status = "ACTIVE"

    return {
        "status": current_status,
        "reason": reason,
        "events": rb_evts[:100],
        "raw_status": _cap_rows(rebalance_status or [], 50),
    }


def summarize_memory_pressure(nodes: list) -> dict:
    """Aggregate memory-pressure indicators across all nodes.

    Returns a dict with per-node THP status, sysctl vm.* values,
    and whether OOM events were seen in dmesg.
    """
    result: dict = {}
    for node in nodes:
        hostname = node.get("hostname", "unknown")
        os_checks = node.get("os_checks", {}) or {}
        thp = os_checks.get("thp", {}) or {}
        sysctl = os_checks.get("sysctl", {}) or {}
        dmesg_events = node.get("dmesg_events", []) or []
        oom_in_dmesg = any(
            str(e.get("category", "")).lower() == "oom" for e in dmesg_events
        )
        result[hostname] = {
            "thp_status": thp.get("status", "unknown"),
            "thp_active": thp.get("active", "unknown"),
            "vm_swappiness": (sysctl.get("vm.swappiness") or {}).get("value"),
            "vm_overcommit_memory": (sysctl.get("vm.overcommit_memory") or {}).get("value"),
            "vm_overcommit_ratio": (sysctl.get("vm.overcommit_ratio") or {}).get("value"),
            "vm_max_map_count": (sysctl.get("vm.max_map_count") or {}).get("numeric"),
            "oom_in_dmesg": oom_in_dmesg,
        }
    return result


def summarize_cluster_layout(cluster_status: list) -> dict:
    """Summarise partition distribution by role and host from SHOW CLUSTER STATUS."""
    rows = list(cluster_status or [])
    by_host: dict = defaultdict(lambda: {"master": 0, "replica": 0, "other": 0, "total": 0})
    by_role: dict = {"master": 0, "replica": 0, "other": 0}
    skipped = 0
    for row in rows:
        host = str(row.get("Host", row.get("HOST", row.get("host", "")))).strip()
        role = str(row.get("Role", row.get("ROLE", ""))).strip().lower()
        if not host or host.upper() == "NULL":
            skipped += 1
            continue
        if role in _MASTER_ROLES or role.endswith(" master"):
            key = "master"
        elif role in _REPLICA_ROLES or "slave" in role or "replica" in role:
            key = "replica"
        else:
            key = "other"
        by_host[host][key] += 1
        by_host[host]["total"] += 1
        by_role[key] += 1
    return {
        "by_host": {h: dict(v) for h, v in by_host.items()},
        "by_role": by_role,
        "total_partitions": by_role["master"] + by_role["replica"] + by_role["other"],
        "skipped_rows": skipped,
        "input_row_count": len(rows),
        "counts_are_lower_bounds": len(rows) >= 300,
        "source": "SHOW CLUSTER STATUS",
    }


def extract_process_health(processlist: list, *, snapshot_available: bool = True) -> dict:
    """Identify executing queries and sleeping sessions with an explicit open transaction."""
    active: list = []
    sleeping_tx: list = []
    for row in processlist or []:
        if _is_active_query_row(row):
            active.append(row)
            continue
        if _processlist_command(row) != "sleep":
            continue
        if _transaction_state(row) in _OPEN_TRX_STATES:
            sleeping_tx.append(row)
    return {
        "active_queries": active,
        "sleeping_open_transactions": sleeping_tx,
        "active_count": len(active),
        "sleeping_open_tx_count": len(sleeping_tx),
        "snapshot_available": bool(snapshot_available),
        "time_semantics": "seconds_in_current_processlist_state",
    }


def extract_query_patterns(
    processlist: list,
    queries: list | None = None,
    *,
    snapshot_available: bool = True,
) -> dict:
    """Analyze executing queries in one processlist snapshot.

    ``TIME`` is seconds in the current processlist state, not guaranteed
    end-to-end execution time. The result names that semantic explicitly and
    excludes sleeping/system rows. MV_QUERIES enriches text only; it is never
    used as a timing source.
    """
    SLOW_THRESHOLD = 30.0       # seconds
    RUNAWAY_THRESHOLD = 300.0   # 5 minutes
    MAX_ROWS = 50

    slow: list = []
    runaway: list = []
    all_queries: list = []
    pattern_counts: dict = {}  # normalized_sql → {count, max_elapsed, sample}

    process_rows = list(processlist or [])
    active_rows = [row for row in process_rows if _is_active_query_row(row)]
    timing_rows = [
        row for row in active_rows if _row_elapsed_sec(row) > 0
    ]
    input_truncated = len(process_rows) >= MAX_PROCESSLIST_ROWS

    mv_by_plan: dict = {}
    if queries:
        for qrow in queries:
            plan_id = str(qrow.get("PLAN_ID", qrow.get("plan_id", ""))).strip()
            if plan_id:
                mv_by_plan[plan_id] = qrow

    for row in timing_rows:
        elapsed = _row_elapsed_sec(row)
        if elapsed <= 0:
            continue

        enrich = mv_by_plan.get(str(row.get("PLAN_ID", row.get("plan_id", ""))).strip(), {})
        if enrich.get("QUERY_TEXT") or enrich.get("query_text"):
            query_text = str(enrich.get("QUERY_TEXT", enrich.get("query_text", "")))[:500]
        else:
            query_text = _query_text_from_row(row)[:500]
        normalized = _normalize_sql(query_text)

        if _is_stale_query_row(elapsed, query_text, normalized):
            continue

        # Track patterns
        if normalized:
            if normalized not in pattern_counts:
                pattern_counts[normalized] = {"count": 0, "max_elapsed": 0.0, "sample": query_text[:200]}
            pattern_counts[normalized]["count"] += 1
            if elapsed > pattern_counts[normalized]["max_elapsed"]:
                pattern_counts[normalized]["max_elapsed"] = elapsed

        # Memory used (if available)
        memory_keys = ("MEMORY_USED_MB", "memory_used_mb", "MemoryUsedMB")
        memory_available = any(row.get(key) not in (None, "", "NULL") for key in memory_keys)
        mem_mb = _safe_float_val(next(
            (row.get(key) for key in memory_keys if row.get(key) not in (None, "", "NULL")),
            0,
        ))

        entry = {
            "elapsed_sec": round(elapsed, 1),
            "state_age_sec": round(elapsed, 1),
            "time_semantics": "seconds_in_current_processlist_state",
            "query_text": query_text,
            "normalized": normalized,
            "user": str(row.get("USER", row.get("user", "?"))),
            "database": str(row.get("DATABASE_NAME", row.get("database", row.get("DATABASE", "?")))),
            "memory_used_mb": round(mem_mb, 1),
            "memory_measurement_available": memory_available,
            "node_id": str(row.get("NODE_ID", row.get("node_id", ""))),
            "connection_id": str(row.get("ID", row.get("id", row.get("PROCESSLIST_ID", "")))),
            "command": str(row.get("COMMAND", row.get("Command", ""))),
            "state": str(row.get("STATE", row.get("State", ""))),
        }
        all_queries.append(entry)

        if elapsed > RUNAWAY_THRESHOLD:
            runaway.append(entry)
        elif elapsed > SLOW_THRESHOLD:
            slow.append(entry)

    # Sort by elapsed descending
    slow.sort(key=lambda x: x["elapsed_sec"], reverse=True)
    runaway.sort(key=lambda x: x["elapsed_sec"], reverse=True)

    # Top by memory
    memory_rows = [entry for entry in all_queries if entry["memory_measurement_available"]]
    top_mem = sorted(memory_rows, key=lambda x: x["memory_used_mb"], reverse=True)[:10]

    # Repeated patterns (count > 3, sorted by count * max_elapsed)
    repeated = [
        {
            "normalized_sql": k[:200],
            "count": v["count"],
            "max_elapsed_sec": round(v["max_elapsed"], 1),
            "sample_query": v["sample"],
        }
        for k, v in pattern_counts.items()
        if v["count"] >= 3
    ]
    repeated.sort(key=lambda x: x["count"] * x["max_elapsed_sec"], reverse=True)

    max_elapsed = max((e["elapsed_sec"] for e in all_queries), default=0.0)
    total_mem = sum(e["memory_used_mb"] for e in memory_rows)

    return {
        "analyzer_version": 2,
        "slow_queries": slow[:MAX_ROWS],
        "runaway_queries": runaway[:MAX_ROWS],
        "top_by_memory": top_mem,
        "repeated_patterns": repeated[:20],
        "slow_count": len(slow),
        "runaway_count": len(runaway),
        "max_elapsed_sec": round(max_elapsed, 1),
        "max_state_age_sec": round(max_elapsed, 1),
        "total_memory_used_mb": round(total_mem, 1) if memory_rows else None,
        "memory_measurement_count": len(memory_rows),
        "snapshot_available": bool(snapshot_available),
        "timing_source": "processlist",
        "time_semantics": "seconds_in_current_processlist_state",
        "input_row_count": len(process_rows),
        "active_query_count": len(active_rows),
        "timed_query_count": len(all_queries),
        "excluded_non_query_rows": max(0, len(process_rows) - len(active_rows)),
        "input_truncated": input_truncated,
        "counts_are_lower_bounds": input_truncated,
        "pattern_scope": "concurrent_instances_in_one_snapshot",
        "analysis_state": (
            "measured" if process_rows
            else "empty_snapshot" if snapshot_available
            else "unavailable"
        ),
    }


def extract_query_analysis(
    processlist: list,
    query_patterns: dict | None = None,
    blocked_queries: list | None = None,
) -> dict:
    """Build WorkloadQueries-compatible query_analysis from bundle snapshots.

    Populates the ``query_analysis`` field consumed by ``WorkloadQueries.jsx``
    patterns tab (long-running, runaway fingerprints, sleeping lock holders).
    """
    LONG_THRESHOLD = 60.0
    RUNAWAY_THRESHOLD = 300.0
    MAX_ROWS = 50

    long_running: list = []
    for row in processlist or []:
        if not _is_active_query_row(row):
            continue
        time_sec = _row_elapsed_sec(row)
        if time_sec < LONG_THRESHOLD or time_sec >= RUNAWAY_THRESHOLD:
            continue
        long_running.append({
            "time_sec": round(time_sec, 1),
            "user": str(row.get("USER", row.get("user", "?"))),
            "host": str(
                row.get("HOST", row.get("host", row.get("NODE_ID", row.get("node_id", "?"))))
            ),
            "db": str(row.get("DATABASE_NAME", row.get("database", row.get("DB", "")))),
            "query_preview": _query_text_from_row(row)[:200],
            "time_semantics": "seconds_in_current_processlist_state",
            "connection_id": str(row.get("ID", row.get("id", row.get("CONNECTION_ID", "")))),
        })
    long_running.sort(key=lambda x: x["time_sec"], reverse=True)

    qp = query_patterns or {}
    runaway_patterns: list = []
    seen_fp: set[str] = set()
    for pat in qp.get("repeated_patterns", []) or []:
        if float(pat.get("max_elapsed_sec", 0) or 0) < RUNAWAY_THRESHOLD:
            continue
        fp = str(pat.get("normalized_sql", pat.get("sample_query", "")))[:200]
        if not fp or fp in seen_fp:
            continue
        seen_fp.add(fp)
        runaway_patterns.append({
            "occurrences": int(pat.get("count", 0)),
            "max_time_sec": float(pat.get("max_elapsed_sec", 0)),
            "fingerprint": fp,
        })
    for rq in qp.get("runaway_queries", []) or []:
        fp = str(rq.get("normalized") or _normalize_sql(rq.get("query_text", "")))[:200]
        if not fp or fp in seen_fp:
            continue
        seen_fp.add(fp)
        runaway_patterns.append({
            "occurrences": 1,
            "max_time_sec": float(rq.get("elapsed_sec", 0)),
            "fingerprint": fp,
        })
    runaway_patterns.sort(key=lambda x: (x["max_time_sec"], x["occurrences"]), reverse=True)

    lock_holders: list = []
    for row in processlist or []:
        cmd = _processlist_command(row)
        time_sec = _row_elapsed_sec(row)
        trx_state = _transaction_state(row)
        if cmd != "sleep" or time_sec < LONG_THRESHOLD:
            continue
        # Never infer an open transaction from an idle Sleep row or leftover INFO.
        if trx_state not in _OPEN_TRX_STATES:
            continue
        lock_holders.append({
            "time_sec": round(time_sec, 1),
            "user": str(row.get("USER", row.get("user", "?"))),
            "db": str(row.get("DATABASE_NAME", row.get("database", ""))),
            "state": str(row.get("State", row.get("STATE", cmd or "sleep"))),
            "query_preview": _query_text_from_row(row)[:200],
            "connection_id": str(row.get("ID", row.get("id", ""))),
        })
    for row in blocked_queries or []:
        preview = str(
            row.get("BLOCKING_QUERY_TEXT", row.get("blocking_query_text",
                    row.get("BLOCKED_QUERY_TEXT", row.get("blocked_query_text", ""))))
        )[:200]
        if not preview:
            continue
        lock_holders.append({
            "time_sec": round(_row_elapsed_sec(row), 1),
            "user": str(row.get("BLOCKING_USER", row.get("USER", row.get("user", "?")))),
            "db": str(row.get("DATABASE_NAME", row.get("database", ""))),
            "state": str(row.get("BLOCKING_TYPE", row.get("blocking_type", "blocking"))),
            "query_preview": preview,
            "connection_id": str(
                row.get("BLOCKED_QUERY_ID", row.get("blocked_query_id",
                        row.get("ID", row.get("id", ""))))
            ),
        })
    lock_holders.sort(key=lambda x: x["time_sec"], reverse=True)

    return {
        "summary": {
            "long_running_count": len(long_running),
            "runaway_pattern_count": len(runaway_patterns),
            "lock_holder_count": len(lock_holders),
        },
        "long_running": long_running[:MAX_ROWS],
        "runaway_patterns": runaway_patterns[:MAX_ROWS],
        "lock_holders": lock_holders[:MAX_ROWS],
    }


def _safe_float_val(value) -> float:
    """Safely convert any value to float, returning 0.0 on failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        txt = str(value).strip().replace(",", "").replace("s", "")
        try:
            return float(txt)
        except ValueError:
            return 0.0


def _normalize_sql(sql: str) -> str:
    """Normalize SQL text for pattern detection: lowercase, replace literals/numbers."""
    import re as _re
    if not sql:
        return ""
    # Remove leading comments
    s = _re.sub(r"--.*$", "", sql.strip(), flags=_re.MULTILINE)
    # Replace string literals
    s = _re.sub(r"'[^']*'", "?", s)
    # Replace numeric literals
    s = _re.sub(r"\b\d+\b", "?", s)
    # Collapse whitespace
    s = _re.sub(r"\s+", " ", s).strip().lower()
    # Truncate for key
    return s[:200]


def extract_replication_lag_patterns(
    replication_status: list,
    log_patterns: list | None = None,
    mv_events: list | None = None,
    *,
    async_transition_count: int | None = None,
) -> dict:
    """Detect replication lag trends and async-transition events.

    Lag severity uses directly measured ``LAG_SECONDS`` (and aliases) only.
    ``ESTIMATED_CATCHUP_TIME_S``, LSN lag, and volume lag are separate backlog
    evidence and are never mislabeled as elapsed lag seconds.

    Returns::

        {
            "lagging_pairs": [{...}, ...],    # pairs with lag > threshold or connectivity issues
            "unknown_lag_pairs": [{...}, ...], # rows present but LAG_SECONDS missing
            "max_lag_sec": float | None,
            "avg_lag_sec": float | None,
            "lagging_count": N,
            "unknown_lag_count": N,
            "measured_lag_count": N,
            "async_transitions": N,
            "workload_throttle_events": N,
            "replication_state": str,         # healthy | degraded | critical | unknown
        }
    """
    LAG_WARNING = 5.0
    LAG_CRITICAL = 30.0
    lagging: list = []
    lagging_lags: list = []
    measured_lags: list = []
    unknown_lag_pairs: list = []
    backlog_pairs: list = []
    measured_lag_count = 0
    connectivity_issues = 0
    paused_count = 0
    throttling_links = 0

    for row in replication_status or []:
        lag = _replication_row_lag_sec(row)
        master = str(row.get("MasterHost", row.get("MASTER_HOST",
                row.get("master_host", row.get("Master_URI", row.get("MASTER_URI",
                row.get("primary_uri", row.get("PRIMARY_URI", "?"))))))))
        slave = str(row.get("SlaveHost", row.get("SLAVE_HOST",
                row.get("slave_host", row.get("Slave_URI", row.get("SLAVE_URI",
                row.get("secondary_uri", row.get("SECONDARY_URI", "?"))))))))
        role = str(row.get("Role", row.get("ROLE",
                row.get("role", row.get("IS_SYNC", row.get("is_sync", ""))))))
        connected = str(row.get("Connected", row.get("CONNECTED", ""))).strip().lower()
        replica_state = str(row.get("Slave_State", row.get("Replica_State",
                row.get("REPLICA_STATE", row.get("SECONDARY_STATE",
                row.get("secondary_state", "")))))).strip().lower()
        primary_state = str(row.get("Master_State", row.get("PRIMARY_STATE",
                row.get("primary_state", "")))).strip().lower()
        is_paused = "pause" in replica_state
        has_connectivity_issue = (
            connected in {"no", "false", "0", "disconnected", "offline"}
            or replica_state in {"error", "failed", "offline", "stopped"}
            or primary_state in {"error", "failed", "offline"}
        )
        throttling = str(row.get("Throttling", row.get("THROTTLING", ""))).strip().lower()
        if is_paused:
            paused_count += 1
        if throttling in {"yes", "true", "1", "on"}:
            throttling_links += 1
        master_lsn = row.get("Master_CommitLSN", row.get("MASTER_COMMIT_LSN",
                    row.get("master_commit_lsn", row.get("Primary_CommitLSN"))))
        slave_lsn = row.get("Slave_CommitLSN", row.get("SLAVE_COMMIT_LSN",
                   row.get("slave_commit_lsn", row.get("Replica_CommitLSN"))))
        lsn_delta = _lsn_position_delta(master_lsn, slave_lsn)
        lsn_lag = _replication_metric(row, "LSN_LAG", "lsn_lag")
        volume_lag_mb = _replication_metric(row, "VOLUME_LAG_MB", "volume_lag_mb")
        throughput_mbps = _replication_metric(
            row, "REPLICATION_THROUGHPUT_MBPS", "replication_throughput_mbps"
        )
        catchup_sec = _replication_metric(
            row, "ESTIMATED_CATCHUP_TIME_S", "estimated_catchup_time_s"
        )
        backlog_present = any(
            value is not None and value > 0
            for value in (lsn_lag, volume_lag_mb, catchup_sec)
        ) or (lsn_delta is not None and lsn_delta > 0)
        pair = {
            "master": master,
            "slave": slave,
            "role": role,
            "lag_sec": None if lag < 0 else round(lag, 1),
            "lag_source": None if lag < 0 else "reported_lag_seconds",
            "lsn_position_delta": lsn_delta,
            "lsn_lag": lsn_lag,
            "volume_lag_mb": volume_lag_mb,
            "replication_throughput_mbps": throughput_mbps,
            "estimated_catchup_time_sec": catchup_sec,
            "connected": connected or "unknown",
            "primary_state": primary_state or "unknown",
            "replica_state": replica_state or "unknown",
            "throttling": throttling or "unknown",
            "lag_known": lag >= 0,
            "backlog_present": backlog_present,
        }
        if backlog_present:
            backlog_pairs.append(dict(pair))

        if lag < 0:
            # Seconds unavailable — do not invent lag from LSN; mark unknown instead.
            if has_connectivity_issue or is_paused:
                if has_connectivity_issue:
                    connectivity_issues += 1
                pair["severity"] = "critical" if has_connectivity_issue else "warning"
                pair["issue_type"] = "connectivity" if has_connectivity_issue else "paused"
                lagging.append(pair)
            else:
                pair["severity"] = "unknown"
                pair["issue_type"] = "lag_seconds_unavailable"
                unknown_lag_pairs.append(pair)
            continue

        measured_lag_count += 1
        measured_lags.append(lag)
        severity = "critical" if lag > LAG_CRITICAL else "warning"
        if has_connectivity_issue:
            severity = "critical"
            connectivity_issues += 1

        if lag > LAG_WARNING or has_connectivity_issue or is_paused:
            if lag > LAG_WARNING:
                lagging_lags.append(lag)
            pair["severity"] = severity
            pair["issue_type"] = (
                "connectivity" if has_connectivity_issue
                else "paused" if is_paused
                else "lag"
            )
            lagging.append(pair)

    # Count async-transition events from log patterns (narrow sync→async phrases only)
    async_transitions = max(0, int(async_transition_count or 0))
    if async_transition_count is None and log_patterns:
        for pat in log_patterns:
            msg = str(pat.get("message", pat.get("pattern", pat.get("text", pat.get("sample", "")))))
            if _is_async_transition_message(msg):
                async_transitions += int(_safe_float_val(pat.get("count", 1)))

    workload_throttle_events = 0
    for row in mv_events or []:
        evt_type = str(row.get("EVENT_TYPE", row.get("EVENT", ""))).strip().upper()
        if evt_type == "WORKLOAD_THROTTLE":
            workload_throttle_events += 1

    lagging.sort(key=lambda x: (x["lag_sec"] is None, -(x["lag_sec"] or 0)))
    max_lag = max(lagging_lags) if lagging_lags else None
    avg_lag = (sum(lagging_lags) / len(lagging_lags)) if lagging_lags else None
    avg_measured_lag = (
        sum(measured_lags) / len(measured_lags) if measured_lags else None
    )

    if (max_lag is not None and max_lag > LAG_CRITICAL) or connectivity_issues > 0:
        state = "critical"
    elif (
        (max_lag is not None and max_lag > LAG_WARNING)
        or async_transitions > 0
        or workload_throttle_events > 0
        or throttling_links > 0
        or paused_count > 0
    ):
        state = "degraded"
    elif unknown_lag_pairs or (replication_status and measured_lag_count == 0):
        # Rows exist but we cannot assert lag health without measured seconds.
        state = "unknown"
    elif measured_lag_count > 0:
        state = "healthy"
    else:
        state = "unknown"

    return {
        "analyzer_version": 2,
        "lagging_pairs": lagging[:50],
        "unknown_lag_pairs": unknown_lag_pairs[:50],
        "max_lag_sec": round(max_lag, 1) if max_lag is not None else None,
        "avg_lag_sec": round(avg_lag, 1) if avg_lag is not None else None,
        "avg_lag_of": "lagging_pairs_only",
        "avg_measured_lag_sec": (
            round(avg_measured_lag, 1) if avg_measured_lag is not None else None
        ),
        "lagging_count": len(lagging),
        "status_row_count": len(replication_status or []),
        "unknown_lag_count": len(unknown_lag_pairs),
        "measured_lag_count": measured_lag_count,
        "backlog_pairs": backlog_pairs[:50],
        "backlog_pair_count": len(backlog_pairs),
        "connectivity_issue_count": connectivity_issues,
        "paused_pair_count": paused_count,
        "throttling_pair_count": throttling_links,
        "async_transitions": async_transitions,
        "workload_throttle_events": workload_throttle_events,
        "replication_state": state,
    }


def refresh_query_replication_analysis(payload: dict) -> bool:
    """Upgrade persisted analysis panels that previously used the wrong semantics."""
    if int(payload.get("analysis_revision") or 0) >= ANALYSIS_REVISION:
        return False

    overview = payload.get("cluster_overview") or {}
    processlist = _as_row_list(overview.get("processlist"))
    snapshot_available = "processlist" in overview
    blocked = _as_row_list(overview.get("blocked_queries"))

    payload["query_patterns"] = extract_query_patterns(
        processlist,
        _as_row_list(payload.get("queries")),
        snapshot_available=snapshot_available,
    )
    payload["process_health"] = extract_process_health(
        processlist, snapshot_available=snapshot_available
    )
    payload["query_analysis"] = extract_query_analysis(
        processlist, payload.get("query_patterns", {}), blocked
    )
    payload["long_running_transactions"] = extract_long_running_transactions(
        processlist, blocked
    )
    payload["cluster_layout"] = summarize_cluster_layout(
        _as_row_list(overview.get("cluster_status"))
    )

    pressure = payload.get("pressure_events_per_hour") or {}
    async_count = sum(
        int(value or 0)
        for value in (pressure.get("async_transition") or {}).values()
        if str(value or "").strip().lstrip("-").isdigit()
    )
    payload["replication_lag_patterns"] = extract_replication_lag_patterns(
        _as_row_list(payload.get("replication_status")),
        payload.get("detected_log_patterns") or [],
        _as_row_list(payload.get("events")),
        async_transition_count=async_count,
    )

    dx = dict(payload.get("extended_diagnostics") or {})
    nodes = payload.get("nodes") or []
    if nodes:
        dx["cpu_health"] = extract_cpu_health(nodes)
        dx["sysinfo_network"] = extract_sysinfo_network_health(nodes, overview)
        payload["extended_diagnostics"] = dx

    payload["recommendations"], payload["incident_clusters"] = (
        generate_recommendations_with_clusters(payload)
    )
    payload["analysis_revision"] = ANALYSIS_REVISION
    return True


# ─── Extended diagnostics (colleague dashboard parity) ─────────────

_COMPILATION_TIME_RE = re.compile(
    r"Query (?P<partition>\S+)\.'(?P<query>.*?)' submitted"
    r" (?P<submitted>\d+) milliseconds ago,"
    r" queued for (?P<queued>\d+) milliseconds,"
    r" compiled asynchronously in (?P<compiled>\d+) milliseconds",
    re.I,
)
_HEARTBEAT_FAILURE_RE = re.compile(
    r"HeartbeatConnectionFailure|ProcessNetworkEvents Heartbeat connection error",
    re.I,
)
_NETSTAT_METRICS = {
    "TCP Retransmissions": {"pattern": r"(\d+)\ssegments retransmitted", "threshold": 5},
    "TCP Connection Timeouts": {"pattern": r"TCPTimeouts:\s+(\d+)", "threshold": 200},
    "Connection Resets": {"pattern": r"(\d+)\s+(?:connection resets received|resets sent)", "threshold": 5},
    "SYN Retransmissions": {"pattern": r"TCPSynRetrans:\s+(\d+)", "threshold": 1},
    "Connections Timeout Aborted": {"pattern": r"(\d+)\s+connections aborted due to timeout", "threshold": 100},
    "Delayed ACKs": {"pattern": r"delayed acks sent\s+(\d+)", "threshold": 1000},
    "Zero Window Issues": {"pattern": r"TCPToZeroWindowAdv:\s+(\d+)|TCPFromZeroWindowAdv:\s+(\d+)", "threshold": 100},
    "UDP Packet Loss": {"pattern": r"(\d+)\s+packet receive errors|(\d+)\s+receive buffer errors", "threshold": 1},
    "TCP Backlog": {"pattern": r"TCPBacklogCoalesce:\s+(\d+)", "threshold": 1000},
    "Invalid TCP Packets": {"pattern": r"(\d+)\s+bad segments received", "threshold": 100},
}


def _parse_netstat_content(content: str) -> dict:
    results: dict = {}
    segments_sent_match = re.search(r"(\d+)\ssegments sent out", content)
    segments_sent = int(segments_sent_match.group(1)) if segments_sent_match else 0
    for metric, cfg in _NETSTAT_METRICS.items():
        matches = re.findall(cfg["pattern"], content)
        if matches:
            if isinstance(matches[0], tuple):
                value = sum(int(x) for match in matches for x in match if x)
            else:
                value = sum(int(x) for x in matches)
            if metric == "TCP Retransmissions" and segments_sent:
                value = round((value / segments_sent) * 100, 2)
            results[metric] = value
        else:
            results[metric] = 0
        results[f"{metric}__threshold"] = cfg["threshold"]
        results[f"{metric}__breach"] = results[metric] > cfg["threshold"]
    return results


def parse_netstat_metrics(node_path: str) -> dict:
    """Parse netstat collector output for TCP/UDP health metrics."""
    candidates = [
        os.path.join(node_path, "netstat", "netstat_stdout"),
        os.path.join(node_path, "netstat_stdout"),
        os.path.join(node_path, "netstat", "netstat"),
    ]
    for fpath in candidates:
        if os.path.isfile(fpath):
            try:
                with open(fpath, encoding="utf-8", errors="replace") as fh:
                    return _parse_netstat_content(fh.read())
            except OSError:
                continue
    return {}


def _glob_pipeline_tsv(node_path: str, needle: str) -> list[str]:
    base = os.path.join(node_path, "informationSchemaPipelines")
    if not os.path.isdir(base):
        return []
    return sorted(
        os.path.join(base, f)
        for f in os.listdir(base)
        if needle in f.lower() and f.lower().endswith(".tsv")
    )


def _read_tsv_rows(fpath: str, max_rows: int = 500) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(fpath, encoding="utf-8", errors="replace") as fh:
            header = None
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                parts = stripped.split("\t")
                if header is None:
                    header = parts
                    continue
                row = {header[i]: parts[i] if i < len(parts) else "" for i in range(len(header))}
                rows.append(row)
                if len(rows) >= max_rows:
                    break
    except OSError:
        return []
    return rows


def extract_pipeline_diagnostics(nodes: list) -> dict:
    """Pipeline error and batch history from informationSchemaPipelines TSV collectors."""
    errors: list = []
    batches: list = []
    for node in nodes or []:
        hostname = node.get("hostname", "unknown")
        node_path = node.get("_node_path") or ""
        if not node_path:
            continue
        for fpath in _glob_pipeline_tsv(node_path, "error"):
            for row in _read_tsv_rows(fpath, 200):
                errors.append({**row, "node": hostname, "source_file": os.path.basename(fpath)})
        for fpath in _glob_pipeline_tsv(node_path, "batch"):
            for row in _read_tsv_rows(fpath, 200):
                batches.append({**row, "node": hostname, "source_file": os.path.basename(fpath)})
    return {
        "errors": errors[:300],
        "batches": batches[:300],
        "error_count": len(errors),
        "batch_count": len(batches),
    }


def extract_compilation_times(all_logs: list, max_rows: int = 300) -> dict:
    """Async compilation latency samples from tracelog lines."""
    rows: list = []
    hourly: dict = defaultdict(lambda: {"count": 0, "compiled_total": 0, "queued_total": 0})
    for log in all_logs or []:
        msg = str(log.get("message", ""))
        m = _COMPILATION_TIME_RE.search(msg)
        if not m:
            continue
        ts = str(log.get("timestamp", ""))
        compiled = int(m.group("compiled"))
        queued = int(m.group("queued"))
        submitted = int(m.group("submitted"))
        rows.append({
            "node": log.get("hostname", "unknown"),
            "timestamp": ts,
            "submitted_ms": submitted,
            "queued_ms": queued,
            "compiled_ms": compiled,
            "query_preview": m.group("query")[:200],
        })
        bucket = _hour_bucket(ts)
        if bucket:
            hourly[bucket]["count"] += 1
            hourly[bucket]["compiled_total"] += compiled
            hourly[bucket]["queued_total"] += queued
    rows.sort(key=lambda x: x["compiled_ms"], reverse=True)
    timeline = [
        {
            "hour": hour,
            "count": vals["count"],
            "avg_compiled_ms": round(vals["compiled_total"] / vals["count"], 1) if vals["count"] else 0,
            "avg_queued_ms": round(vals["queued_total"] / vals["count"], 1) if vals["count"] else 0,
        }
        for hour, vals in sorted(hourly.items())
    ]
    compiled_vals = [r["compiled_ms"] for r in rows]
    return {
        "samples": rows[:max_rows],
        "sample_count": len(rows),
        "timeline": timeline[-72:],
        "max_compiled_ms": max(compiled_vals, default=0),
        "avg_compiled_ms": round(sum(compiled_vals) / len(compiled_vals), 1) if compiled_vals else 0,
    }


def extract_heartbeat_failures(all_logs: list, max_rows: int = 200) -> dict:
    """Heartbeat connectivity failures from tracelogs."""
    rows: list = []
    hourly: dict = defaultdict(int)
    for log in all_logs or []:
        msg = str(log.get("message", ""))
        if not _HEARTBEAT_FAILURE_RE.search(msg):
            continue
        ts = str(log.get("timestamp", ""))
        failure_type = "HeartbeatConnectionFailure" if "HeartbeatConnectionFailure" in msg else "Heartbeat connection error"
        rows.append({
            "node": log.get("hostname", "unknown"),
            "timestamp": ts,
            "failure_type": failure_type,
            "message": msg[:300],
        })
        bucket = _hour_bucket(ts)
        if bucket:
            hourly[bucket] += 1
    timeline = [{"hour": h, "count": c} for h, c in sorted(hourly.items())]
    return {
        "failures": rows[:max_rows],
        "failure_count": len(rows),
        "timeline": timeline[-72:],
        "nodes_affected": sorted({r["node"] for r in rows}),
    }


def extract_netstat_summary(nodes: list) -> dict:
    """Per-node netstat TCP/UDP metrics with threshold breach flags."""
    per_node: list = []
    breach_counts: dict = defaultdict(int)
    for node in nodes or []:
        hostname = node.get("hostname", "unknown")
        node_path = node.get("_node_path") or ""
        if not node_path:
            continue
        metrics = parse_netstat_metrics(node_path)
        if not metrics:
            continue
        breaches = [k for k, v in metrics.items() if k.endswith("__breach") and v]
        for b in breaches:
            breach_counts[b.replace("__breach", "")] += 1
        per_node.append({
            "node": hostname,
            "metrics": {k: v for k, v in metrics.items() if not k.endswith("__threshold")},
            "breach_count": len(breaches),
        })
    per_node.sort(key=lambda x: x["breach_count"], reverse=True)
    return {
        "per_node": per_node[:50],
        "nodes_with_netstat": len(per_node),
        "breach_counts": dict(breach_counts),
    }


def extract_table_storage_inventory(table_rows: list) -> dict:
    """Classify tables from documented ``information_schema.TABLES.STORAGE_TYPE`` values."""
    inventory: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    counts = {"columnstore": 0, "rowstore": 0, "unknown": 0}

    for row in _as_row_list(table_rows):
        if not isinstance(row, dict):
            continue
        table_type = str(row.get("TABLE_TYPE", row.get("table_type", "")) or "").upper()
        if table_type in {"VIEW", "SYSTEM VIEW"}:
            continue

        raw_storage_type = str(
            row.get("STORAGE_TYPE", row.get("storage_type", "")) or ""
        ).upper()
        storage_type = {
            "COLUMNSTORE": "columnstore",
            "INMEMORY_ROWSTORE": "rowstore",
        }.get(raw_storage_type, "unknown")
        database = str(row.get("TABLE_SCHEMA", row.get("table_schema", "")) or "")
        table = str(row.get("TABLE_NAME", row.get("table_name", "")) or "")
        if not database or not table:
            continue
        identity = (database, table, table_type)
        if identity in seen:
            continue
        seen.add(identity)

        distributed_text = str(
            row.get("DISTRIBUTED", row.get("distributed", ""))
        ).strip().lower()
        distributed = (
            True if distributed_text in {"1", "true", "yes"}
            else False if distributed_text in {"0", "false", "no"}
            else None
        )
        rows_raw = row.get("TABLE_ROWS", row.get("table_rows"))
        row_count_missing = (
            rows_raw is None
            or str(rows_raw).strip().upper() in {"", "NULL", "NONE"}
        )
        inventory.append({
            "database": database,
            "table": table,
            "storage_type": storage_type,
            "storage_type_raw": raw_storage_type or None,
            "table_type": table_type or None,
            "distributed": distributed,
            "row_count": None if row_count_missing else safe_int(rows_raw),
            "row_format": row.get("ROW_FORMAT", row.get("row_format")),
        })
        counts[storage_type] += 1

    inventory.sort(key=lambda item: (item["database"].lower(), item["table"].lower()))
    return {
        "summary": {
            "total_tables": len(inventory),
            "columnstore_tables": counts["columnstore"],
            "rowstore_tables": counts["rowstore"],
            "unknown_tables": counts["unknown"],
        },
        "tables": inventory,
        "source": "information_schema.TABLES.STORAGE_TYPE",
        "grounding": {
            "basis": "documented",
            "columnstore_value": "COLUMNSTORE",
            "rowstore_value": "INMEMORY_ROWSTORE",
            "url": "https://docs.singlestore.com/db/v9.1/reference/information-schema-reference/cluster-component/tables/",
        },
    }


def derive_database_disk_usage_from_table_statistics(table_statistics: list) -> list:
    """Fallback when databaseDiskUsage.json is missing: use explicit disk fields only."""
    if not table_statistics:
        return []
    by_db: dict[str, float] = defaultdict(float)
    for row in table_statistics:
        db = str(row.get("DATABASE_NAME", row.get("database", ""))).strip()
        if not db:
            continue
        disk_bytes = _disk_usage_bytes_from_row(row)
        if disk_bytes <= 0:
            continue
        by_db[db] += disk_bytes
    result: list[dict] = []
    for db, bytes_total in sorted(by_db.items(), key=lambda item: -item[1]):
        if bytes_total <= 0:
            continue
        result.append({
            "DATABASE_NAME": db,
            "_disk_bytes": bytes_total,
            "TOTAL_DISK_USAGE_GB": round(bytes_total / (1024 ** 3), 4),
            "_source": "table_statistics",
        })
    return result


def resolve_database_disk_usage(payload: dict) -> list:
    """Return database disk usage from payload, with table-statistics fallback."""
    disk = _as_row_list(payload.get("database_disk_usage"))
    if disk:
        return disk
    storage = _as_row_list(payload.get("storage"))
    return derive_database_disk_usage_from_table_statistics(storage)


def resolve_memory_utilization(payload: dict) -> dict:
    """Return per-node memory utilization, recomputing when missing or empty."""
    existing = payload.get("memory_utilization") or {}
    per_node = existing.get("per_node") or {}
    if isinstance(per_node, dict) and per_node:
        return existing
    if isinstance(per_node, list) and per_node:
        return existing

    overview = payload.get("cluster_overview") or {}
    nodes = payload.get("nodes") or []
    if nodes:
        computed = extract_memory_utilization_trend(nodes, overview)
        if computed.get("per_node"):
            return computed

    nodes_detail = _as_row_list(overview.get("nodes_detail"))
    if nodes_detail:
        # Use overview/nodes_detail engine fields only — never invent OS `free`
        # totals from maximum_memory (that mislabels engine use as OS RAM).
        computed = extract_memory_utilization_trend([], overview)
        if computed.get("per_node"):
            return computed

    return existing if existing else {"per_node": {}, "cluster_summary": {}}


def _norm_host(host: str) -> str:
    """Normalize a host identifier for cross-source matching (strip port, lowercase)."""
    h = str(host or "").strip().lower()
    if not h:
        return ""
    # Drop a trailing :port (but leave bare IPv6 forms alone — sdb hosts are IPv4/DNS).
    if h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h


def extract_table_skew_analytics(table_statistics: list, leaf_hosts: list | None = None) -> dict:
    """Memory and row skew (CV) across partitions per table.

    When ``leaf_hosts`` (the authoritative LEAF host set from cluster topology) is
    supplied, leaves that own no partitions — and therefore never appear in
    ``information_schema.TABLE_STATISTICS`` — are seeded as zero-data hosts so a
    completely idle leaf still counts toward host-level imbalance. This is guarded:
    it only applies when the topology host namespace overlaps the hosts actually
    present in TABLE_STATISTICS, so an IP-vs-hostname mismatch cannot fabricate
    phantom idle leaves.
    """
    if not table_statistics:
        return {"summary": {}, "table_skew": [], "host_skew": []}

    def _cv(values: list[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        if mean <= 0:
            return 0.0
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return round((variance ** 0.5 / mean) * 100, 1)

    by_table: dict = defaultdict(lambda: {"rows": [], "memory": [], "hosts": set(), "database": ""})
    by_host: dict = defaultdict(lambda: {"rows": 0.0, "memory": 0.0, "tables": 0})

    for row in table_statistics:
        db = str(row.get("DATABASE_NAME", row.get("database", "")))
        table = str(row.get("TABLE_NAME", row.get("table", "")))
        host = str(row.get("HOST", row.get("host", "")))
        rows_val = _safe_float_val(row.get("ROWS", row.get("rows", 0)))
        mem_val = _safe_float_val(row.get("MEMORY_USE", row.get("memory_use", 0)))
        key = f"{db}.{table}" if db else table
        if not key.strip("."):
            continue
        entry = by_table[key]
        entry["database"] = db
        entry["rows"].append(rows_val)
        entry["memory"].append(mem_val)
        entry["hosts"].add(host)
        by_host[host]["rows"] += rows_val
        by_host[host]["memory"] += mem_val
        by_host[host]["tables"] += 1

    # Seed idle leaves (own no partitions -> absent from TABLE_STATISTICS) so they
    # count toward host imbalance, but only when the topology host namespace overlaps
    # the hosts we actually observed (guards against IP/hostname format mismatch).
    idle_leaf_hosts = 0
    if leaf_hosts:
        existing_norm = {_norm_host(h) for h in by_host}
        leaf_norm: dict[str, str] = {}
        for h in leaf_hosts:
            n = _norm_host(h)
            if n:
                leaf_norm.setdefault(n, str(h))
        if existing_norm & set(leaf_norm):
            for n, original in leaf_norm.items():
                if n not in existing_norm:
                    by_host[original]  # noqa: B018 - defaultdict creates a zero-data entry
                    idle_leaf_hosts += 1

    table_skew: list = []
    for key, entry in by_table.items():
        if len(entry["rows"]) < 2:
            continue
        row_cv = _cv(entry["rows"])
        mem_cv = _cv(entry["memory"])
        table_skew.append({
            "table": key,
            "database": entry["database"],
            "partition_count": len(entry["rows"]),
            "host_count": len(entry["hosts"]),
            "row_skew_cv_pct": row_cv,
            "memory_skew_cv_pct": mem_cv,
            "total_rows": int(sum(entry["rows"])),
            # MEMORY_USE from information_schema.TABLE_STATISTICS is in bytes.
            "total_memory_mb": round(sum(entry["memory"]) / (1024 * 1024), 1),
        })
    table_skew.sort(key=lambda x: max(x["row_skew_cv_pct"], x["memory_skew_cv_pct"]), reverse=True)

    # Include every host that owns table data, even those summing to zero rows/memory:
    # an empty or under-loaded data host IS host-level skew and should raise the CV.
    # (Aggregators holding reference tables have rows > 0 and were never filtered out
    # here anyway, so a >0 filter only hid genuinely empty leaves.)
    host_rows = [v["rows"] for v in by_host.values()]
    host_mem = [v["memory"] for v in by_host.values()]
    host_skew = [
        {
            "host": host,
            "table_count": vals["tables"],
            "total_rows": int(vals["rows"]),
            # MEMORY_USE from information_schema.TABLE_STATISTICS is in bytes.
            "total_memory_mb": round(vals["memory"] / (1024 * 1024), 1),
        }
        for host, vals in sorted(by_host.items(), key=lambda x: x[1]["memory"], reverse=True)
    ]

    high_row_skew = sum(1 for t in table_skew if t["row_skew_cv_pct"] >= 50)
    high_mem_skew = sum(1 for t in table_skew if t["memory_skew_cv_pct"] >= 50)
    return {
        "summary": {
            "table_count": len(by_table),
            "host_count": len(by_host),
            "idle_leaf_hosts": idle_leaf_hosts,
            "high_row_skew_tables": high_row_skew,
            "high_memory_skew_tables": high_mem_skew,
            "host_row_cv_pct": _cv(host_rows),
            "host_memory_cv_pct": _cv(host_mem),
        },
        "table_skew": table_skew[:50],
        "host_skew": host_skew[:30],
    }


def build_log_error_timeline(log_summary: dict) -> dict:
    """Hourly ERROR/FATAL/CRITICAL counts from parsed log summary."""
    hourly = (log_summary or {}).get("hourly", {}) or {}
    timeline: list = []
    total_errors = 0
    for hour, counts in sorted(hourly.items()):
        err = int(counts.get("ERROR", 0) or 0)
        fatal = int(counts.get("FATAL", 0) or 0)
        critical = int(counts.get("CRITICAL", 0) or 0)
        bucket_total = err + fatal + critical
        if bucket_total <= 0:
            continue
        total_errors += bucket_total
        timeline.append({
            "hour": hour,
            "error": err,
            "fatal": fatal,
            "critical": critical,
            "total": bucket_total,
        })
    return {
        "timeline": timeline[-72:],
        "total_errors": total_errors,
        "peak_hour": max(timeline, key=lambda x: x["total"])["hour"] if timeline else "",
    }


def _parse_uptime_days(raw: str) -> float:
    """Parse uptime_stdout content into fractional days."""
    if not raw:
        return 0.0
    days = 0
    hours = 0
    minutes = 0
    days_match = re.search(r"up\s+(\d+)\s+days?", raw, re.I)
    if days_match:
        days = int(days_match.group(1))
        time_after = re.search(r"days?,\s*(\d+):(\d+)", raw)
        if time_after:
            hours = int(time_after.group(1))
            minutes = int(time_after.group(2))
    else:
        time_match = re.search(r"up\s+(\d+):(\d+)", raw)
        if time_match:
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
    return round(days + (hours / 24) + (minutes / (24 * 60)), 2)


def _collect_sysinfo_rows(nodes: list, key: str) -> list:
    """Merge MV_SYSINFO rows from all node collectors, deduped by row identity."""
    merged: dict = {}
    for node in nodes or []:
        sysinfo = (node.get("metrics") or {}).get("sysinfo") or {}
        for row in sysinfo.get(key) or []:
            if not isinstance(row, dict):
                continue
            row_key = json.dumps(row, sort_keys=True, default=str)
            merged[row_key] = row
    return list(merged.values())


def build_mv_events_timeline(events: list, max_points: int = 2500) -> dict:
    """Full MV_EVENTS scatter payload (unfiltered) for timeline visualization."""
    points: list = []
    nodes: set = set()
    severity_counts: dict = defaultdict(int)
    for row in events or []:
        evt_time = str(row.get("EVENT_TIME") or row.get("TIMESTAMP") or row.get("TIME") or "")
        node_id = str(row.get("ORIGIN_NODE_ID") or row.get("NODE_ID") or row.get("NodeId") or "unknown")
        severity = str(row.get("SEVERITY") or "UNKNOWN").upper()
        evt_type = str(row.get("EVENT_TYPE") or row.get("EVENT") or "")
        details = str(
            row.get("DETAILS")
            or row.get("EVENT_DESCRIPTION")
            or row.get("DESCRIPTION")
            or row.get("EXTRA_INFO")
            or ""
        )
        if not evt_time and not evt_type:
            continue
        nodes.add(node_id)
        severity_counts[severity] += 1
        points.append({
            "node_id": node_id,
            "event_time": evt_time,
            "severity": severity,
            "event_type": evt_type,
            "details": details[:500],
        })
    points.sort(key=lambda x: x["event_time"])
    total = len(points)
    return {
        "points": points[:max_points],
        "total_count": total,
        "truncated": total > max_points,
        "nodes": sorted(nodes),
        "severity_counts": dict(severity_counts),
    }


def extract_cpu_health(nodes: list) -> dict:
    """CPU health from MV_SYSINFO_CPULIST with leaf Z-score outlier detection."""
    cpulist = _collect_sysinfo_rows(nodes, "MV_SYSINFO_CPULIST")
    if not cpulist:
        return {"summary": {}, "per_node": [], "insights": []}

    by_node: dict = defaultdict(lambda: {
        "total_used_ns": 0.0,
        "idle_ns": 0.0,
        "user_ns": 0.0,
        "system_ns": 0.0,
        "iowait_ns": 0.0,
        "softirq_ns": 0.0,
        "steal_ns": 0.0,
        "cpu_count": 0,
        "core_utils": [],
    })

    for row in cpulist:
        node_id = str(row.get("NODE_ID") or row.get("node_id") or "")
        if not node_id:
            continue
        entry = by_node[node_id]
        used = _safe_float_val(row.get("TOTAL_USED_CUMULATIVE_NS", row.get("total_used_cumulative_ns", 0)))
        idle = _safe_float_val(row.get("IDLE_CUMULATIVE_NS", row.get("idle_cumulative_ns", 0)))
        entry["total_used_ns"] += used
        entry["idle_ns"] += idle
        entry["user_ns"] += _safe_float_val(row.get("USER_CUMULATIVE_NS", row.get("user_cumulative_ns", 0)))
        entry["system_ns"] += _safe_float_val(row.get("SYSTEM_CUMULATIVE_NS", row.get("system_cumulative_ns", 0)))
        entry["iowait_ns"] += _safe_float_val(row.get("IOWAIT_CUMULATIVE_NS", row.get("iowait_cumulative_ns", 0)))
        entry["softirq_ns"] += _safe_float_val(row.get("SOFTIRQ_CUMULATIVE_NS", row.get("softirq_cumulative_ns", 0)))
        entry["steal_ns"] += _safe_float_val(row.get("STEAL_CUMULATIVE_NS", row.get("steal_cumulative_ns", 0)))
        entry["cpu_count"] += 1
        denom = used + idle
        if denom > 0:
            entry["core_utils"].append((used / denom) * 100)

    per_node: list = []
    for node_id, vals in by_node.items():
        denom = (
            vals["total_used_ns"] + vals["idle_ns"] + vals["iowait_ns"]
            + vals["softirq_ns"] + vals["steal_ns"]
        )
        leaf_util_pct = round((vals["total_used_ns"] / denom) * 100, 2) if denom > 0 else 0.0
        core_utils = vals["core_utils"]
        avg_core = round(sum(core_utils) / len(core_utils), 2) if core_utils else 0.0
        max_core = round(max(core_utils), 2) if core_utils else 0.0
        core_stddev = round((sum((c - avg_core) ** 2 for c in core_utils) / len(core_utils)) ** 0.5, 2) if len(core_utils) > 1 else 0.0
        per_node.append({
            "node_id": node_id,
            "cpu_count": vals["cpu_count"],
            "leaf_util_pct": leaf_util_pct,
            "avg_core_util": avg_core,
            "max_core_util": max_core,
            "core_stddev": core_stddev,
            "softirq_pct": round((vals["softirq_ns"] / denom) * 100, 3) if denom > 0 else 0.0,
            "iowait_pct": round((vals["iowait_ns"] / denom) * 100, 3) if denom > 0 else 0.0,
            "steal_pct": round((vals["steal_ns"] / denom) * 100, 3) if denom > 0 else 0.0,
            "health_zscore": 0.0,
            "is_outlier": False,
            "window": "since_boot_cumulative",
        })

    if len(per_node) > 1:
        utils = [n["leaf_util_pct"] for n in per_node]
        avg_util = sum(utils) / len(utils)
        variance = sum((u - avg_util) ** 2 for u in utils) / len(utils)
        std_util = variance ** 0.5
        if std_util > 0:
            for n in per_node:
                z = (n["leaf_util_pct"] - avg_util) / std_util
                n["health_zscore"] = round(z, 2)
                n["is_outlier"] = abs(z) > 2

    per_node.sort(key=lambda x: abs(x["health_zscore"]), reverse=True)
    outliers = [n for n in per_node if n["is_outlier"]]
    insights: list = []
    if outliers:
        worst = per_node[0]
        insights.append(
            f"{worst['node_id']} is a since-boot CPU utilization outlier (Z={worst['health_zscore']:.2f}); "
            "MV_SYSINFO_CPULIST counters are cumulative since startup, not current load."
        )
    high_softirq = [n for n in per_node if n["softirq_pct"] > 5]
    if high_softirq:
        insights.append(
            f"High lifetime SoftIRQ share on {', '.join(n['node_id'] for n in high_softirq[:3])} "
            "(percent of since-boot CPU time, not a current interrupt storm)"
        )
    high_iowait = [n for n in per_node if n["iowait_pct"] > 10]
    if high_iowait:
        insights.append(
            f"High lifetime IOWait share on {', '.join(n['node_id'] for n in high_iowait[:3])} "
            "(percent of since-boot CPU time, not a current storage stall)"
        )

    return {
        "summary": {
            "node_count": len(per_node),
            "outlier_count": len(outliers),
            "avg_util_pct": round(sum(n["leaf_util_pct"] for n in per_node) / len(per_node), 2) if per_node else 0,
            "window": "since_boot_cumulative",
        },
        "per_node": per_node[:50],
        "insights": insights,
        "window": "since_boot_cumulative",
        "source": "MV_SYSINFO_CPULIST",
    }


def extract_sysinfo_network_health(nodes: list, cluster_overview: dict) -> dict:
    """Leaf-to-leaf traffic comparison from MV_SYSINFO_NET with Z-score outliers."""
    net_rows = _collect_sysinfo_rows(nodes, "MV_SYSINFO_NET")
    if not net_rows:
        return {"summary": {}, "per_node": [], "interfaces": [], "insights": []}

    node_types: dict = {}
    node_id_to_host: dict = {}
    for nd in _as_row_list(cluster_overview.get("nodes_detail")):
        nid = str(nd.get("id", ""))
        if nid:
            node_types[nid] = str(nd.get("type", "UNKNOWN")).upper()
            node_id_to_host[nid] = str(nd.get("ip_addr", ""))

    host_uptime_days: dict = {}
    for node in nodes or []:
        hostname = str(node.get("hostname", ""))
        raw = (node.get("metrics") or {}).get("uptime", {}).get("raw", "")
        if hostname and raw:
            host_uptime_days[hostname] = _parse_uptime_days(raw)

    by_node: dict = defaultdict(lambda: {
        "rx_bytes": 0.0,
        "tx_bytes": 0.0,
        "interfaces": defaultdict(lambda: {"rx": 0.0, "tx": 0.0}),
    })
    for row in net_rows:
        node_id = str(row.get("NODE_ID") or row.get("node_id") or "")
        if not node_id:
            continue
        iface = str(row.get("INTERFACE") or row.get("interface") or "unknown")
        rx = _safe_float_val(row.get("RECEIVED_CUMULATIVE_B", row.get("received_cumulative_b", 0)))
        tx = _safe_float_val(row.get("TRANSMITTED_CUMULATIVE_B", row.get("transmitted_cumulative_b", 0)))
        entry = by_node[node_id]
        entry["interfaces"][iface]["rx"] += rx
        entry["interfaces"][iface]["tx"] += tx
        if not _is_loopback_iface(iface):
            entry["rx_bytes"] += rx
            entry["tx_bytes"] += tx

    per_node: list = []
    for node_id, vals in by_node.items():
        rx_gb = round(vals["rx_bytes"] / (1024 ** 3), 2)
        tx_gb = round(vals["tx_bytes"] / (1024 ** 3), 2)
        primary_iface = ""
        primary_traffic = 0.0
        for iface, traffic in vals["interfaces"].items():
            if _is_loopback_iface(iface):
                continue
            total = traffic["rx"] + traffic["tx"]
            if total > primary_traffic:
                primary_traffic = total
                primary_iface = iface
        node_type = node_types.get(node_id, "UNKNOWN")
        host = node_id_to_host.get(node_id, "")
        uptime_days = host_uptime_days.get(host) if host else None
        daily_avg_gb = round(tx_gb / uptime_days, 2) if uptime_days and uptime_days > 0 else None
        per_node.append({
            "node_id": node_id,
            "type": node_type,
            "host": host,
            "total_received_gb": rx_gb,
            "total_transmitted_gb": tx_gb,
            "primary_interface": primary_iface,
            "tx_rx_ratio": round(tx_gb / rx_gb, 2) if rx_gb > 0 else 0,
            "z_score": 0.0,
            "is_outlier": False,
            "uptime_days": uptime_days,
            "daily_avg_gb": daily_avg_gb,
            "loopback_excluded": True,
            "window": "since_boot_cumulative",
        })

    leaf_nodes = [n for n in per_node if n["type"] == "LEAF"]
    z_metric = "daily_avg_gb" if all(n.get("daily_avg_gb") is not None for n in leaf_nodes) and len(leaf_nodes) > 1 else "total_transmitted_gb"
    if len(leaf_nodes) > 1:
        tx_vals = [float(n.get(z_metric) or 0) for n in leaf_nodes]
        avg_tx = sum(tx_vals) / len(tx_vals)
        variance = sum((v - avg_tx) ** 2 for v in tx_vals) / len(tx_vals)
        std_tx = variance ** 0.5
        if std_tx > 0:
            for n in per_node:
                if n["type"] == "LEAF":
                    z = (float(n.get(z_metric) or 0) - avg_tx) / std_tx
                    n["z_score"] = round(z, 2)
                    n["is_outlier"] = abs(z) > 2
                    n["z_metric"] = z_metric

    per_node.sort(key=lambda x: abs(x["z_score"]), reverse=True)

    interface_totals: dict = defaultdict(float)
    interface_rows: list = []
    for node_id, vals in by_node.items():
        for iface, traffic in vals["interfaces"].items():
            if _is_loopback_iface(iface):
                continue
            rx_gb = round(traffic["rx"] / (1024 ** 3), 2)
            tx_gb = round(traffic["tx"] / (1024 ** 3), 2)
            total = rx_gb + tx_gb
            interface_totals[iface] += total
            interface_rows.append({
                "node_id": node_id,
                "interface": iface,
                "received_gb": rx_gb,
                "transmitted_gb": tx_gb,
                "total_traffic_gb": round(total, 2),
            })
    interface_rows.sort(key=lambda x: x["total_traffic_gb"], reverse=True)

    outliers = [n for n in per_node if n["is_outlier"]]
    insights: list = []
    if per_node:
        max_tx = max(per_node, key=lambda x: x["total_transmitted_gb"])
        insights.append(
            f"Highest lifetime non-loopback traffic: {max_tx['node_id']} "
            f"({max_tx['total_transmitted_gb']:.1f} GB transmitted since boot)"
        )
    if outliers:
        insights.append(
            f"Outlier leaves on {z_metric}: {', '.join(n['node_id'] for n in outliers[:3])} (|Z| > 2)"
        )
    if interface_totals:
        top_iface = max(interface_totals.items(), key=lambda x: x[1])
        total_traffic = sum(interface_totals.values())
        pct = (top_iface[1] / total_traffic * 100) if total_traffic > 0 else 0
        insights.append(f"Primary non-loopback interface: {top_iface[0]} ({pct:.1f}% of non-loopback traffic)")

    leaf_tx = [n["total_transmitted_gb"] for n in leaf_nodes if n["total_transmitted_gb"] > 0]
    if len(leaf_tx) > 1:
        mean_tx = sum(leaf_tx) / len(leaf_tx)
        std_tx = (sum((v - mean_tx) ** 2 for v in leaf_tx) / len(leaf_tx)) ** 0.5
        cv = (std_tx / mean_tx * 100) if mean_tx > 0 else 0
        if cv > 30:
            insights.append(
                f"High lifetime non-loopback TX variance across leaves (CV={cv:.1f}%)"
            )

    return {
        "summary": {
            "node_count": len(per_node),
            "outlier_count": len(outliers),
            "leaf_count": len(leaf_nodes),
            "loopback_excluded": True,
            "window": "since_boot_cumulative",
        },
        "per_node": per_node[:50],
        "interfaces": interface_rows[:100],
        "insights": insights,
        "window": "since_boot_cumulative",
        "source": "MV_SYSINFO_NET",
    }


def _primary_diagnostics_populated(dx: dict | None) -> bool:
    """True when MV_EVENTS, CPU, or sysinfo-network panels have data."""
    if not dx:
        return False
    if (dx.get("mv_events_timeline") or {}).get("total_count", 0) > 0:
        return True
    if len((dx.get("cpu_health") or {}).get("per_node") or []) > 0:
        return True
    if len((dx.get("sysinfo_network") or {}).get("per_node") or []) > 0:
        return True
    return False


def _extended_diagnostics_populated(dx: dict | None) -> bool:
    """True when extended_diagnostics has at least one non-empty panel."""
    if not dx:
        return False
    if _primary_diagnostics_populated(dx):
        return True
    if (dx.get("compilation_times") or {}).get("sample_count", 0) > 0:
        return True
    if (dx.get("heartbeat_failures") or {}).get("failure_count", 0) > 0:
        return True
    if (dx.get("log_error_timeline") or {}).get("total_errors", 0) > 0:
        return True
    if len((dx.get("table_skew") or {}).get("table_skew") or []) > 0:
        return True
    if (dx.get("pipeline_diagnostics") or {}).get("error_count", 0) > 0:
        return True
    if (dx.get("netstat_summary") or {}).get("nodes_with_netstat", 0) > 0:
        return True
    return False


def _merge_extended_diagnostics(existing: dict | None, refreshed: dict) -> dict:
    """Prefer refreshed primary panels; keep existing secondary panels when refreshed is empty."""
    merged = dict(refreshed or {})
    prior = existing or {}
    if not _primary_diagnostics_populated(merged) and _primary_diagnostics_populated(prior):
        for key in ("mv_events_timeline", "cpu_health", "sysinfo_network"):
            if prior.get(key):
                merged[key] = prior[key]
    for key in (
        "compilation_times",
        "heartbeat_failures",
        "netstat_summary",
        "pipeline_diagnostics",
        "table_skew",
        "log_error_timeline",
        "collector_availability",
    ):
        if not merged.get(key) and prior.get(key):
            merged[key] = prior[key]
    return merged


def hydrate_extended_diagnostics(
    payload: dict,
    all_logs: list | None = None,
    report_root: str | None = None,
    source_path: str | None = None,
    report_name: str | None = None,
) -> dict:
    """Build or refresh extended_diagnostics for stale/missing report payloads."""
    existing = payload.get("extended_diagnostics") or {}
    if _primary_diagnostics_populated(existing):
        return existing

    candidate = (source_path or report_root or "").strip()
    if candidate and os.path.isdir(candidate):
        try:
            parsed = parse_report_directory(candidate, report_name or payload.get("report_name") or "report")
            dx = parsed.get("extended_diagnostics") or {}
            if _primary_diagnostics_populated(dx):
                return _merge_extended_diagnostics(existing, dx)
        except Exception:
            pass

    if candidate and os.path.isfile(candidate):
        try:
            parsed = parse_report_archive_streaming(candidate)
            dx = parsed.get("extended_diagnostics") or {}
            if _primary_diagnostics_populated(dx):
                return _merge_extended_diagnostics(existing, dx)
        except Exception:
            pass

    rebuilt = build_extended_diagnostics(
        payload.get("nodes") or [],
        all_logs or [],
        payload.get("log_summary") or {},
        payload.get("storage") or [],
        payload.get("collector_availability"),
        payload.get("cluster_overview") or {},
        payload.get("events") or [],
    )
    return _merge_extended_diagnostics(existing, rebuilt)


def build_extended_diagnostics(
    nodes: list,
    all_logs: list,
    log_summary: dict,
    table_statistics: list,
    collector_availability: dict | None = None,
    cluster_overview: dict | None = None,
    events: list | None = None,
) -> dict:
    """Aggregate extended diagnostic panels for colleague-dashboard parity."""
    co = cluster_overview or {}
    leaf_hosts = [
        nd.get("ip_addr")
        for nd in _as_row_list(co.get("nodes_detail"))
        if str(nd.get("type", "")).upper() == "LEAF" and nd.get("ip_addr")
    ]
    result = {
        "compilation_times": extract_compilation_times(all_logs),
        "heartbeat_failures": extract_heartbeat_failures(all_logs),
        "netstat_summary": extract_netstat_summary(nodes),
        "pipeline_diagnostics": extract_pipeline_diagnostics(nodes),
        "table_skew": extract_table_skew_analytics(table_statistics, leaf_hosts),
        "log_error_timeline": build_log_error_timeline(log_summary),
        "collector_availability": collector_availability or {},
        "mv_events_timeline": build_mv_events_timeline(events or []),
        "cpu_health": extract_cpu_health(nodes),
        "sysinfo_network": extract_sysinfo_network_health(nodes, co),
    }
    return result


def extract_memory_utilization_trend(nodes: list, cluster_overview: dict) -> dict:
    """Per-node memory utilization summary combining MV_NODES + OS-level memory.

    Support bundles typically contain a single snapshot, not a time series.
    This function builds a comprehensive per-node memory profile by combining:
    - SingleStore engine memory (MV_NODES: memory_used_mb / max_memory_mb)
    - OS-level memory (free_stdout: total/used/available)
    - Table memory vs total memory (cache vs working set)
    - Top process memory (top_stdout)

    Returns::

        {
            "per_node": {
                hostname: {
                    "engine_used_mb": float,
                    "engine_max_mb": float,
                    "engine_used_pct": float | None,
                    "table_memory_mb": float,
                    "non_table_memory_mb": float,   # working set = engine - table
                    "os_total_mb": float | None,
                    "os_used_mb": float | None,
                    "os_available_mb": float | None,
                    "os_used_pct": float | None,
                    "swap_total_mb": float | None,
                    "swap_used_mb": float | None,
                    "swap_used_pct": float | None,
                    "status": "healthy" | "warning" | "critical" | "unknown",
                    "engine_metrics_available": bool,
                    "os_metrics_available": bool,
                    "swap_metrics_available": bool,
                }
            },
            "cluster_summary": {
                "total_engine_memory_mb": float,
                "total_used_engine_mb": float,
                "avg_engine_used_pct": float | None,
                "total_os_memory_mb": float,
                "total_os_used_mb": float,
                "nodes_over_80pct": int,
                "nodes_over_90pct": int,
                "highest_utilization_node": str | None,
                "highest_utilization_pct": float | None,
                "engine_metrics_available": bool,
                "os_metrics_available": bool,
            },
        }
    """
    per_node: dict = {}
    total_engine_max = 0.0
    total_engine_used = 0.0
    total_os_total = 0.0
    total_os_used = 0.0
    nodes_over_80 = 0
    nodes_over_90 = 0
    highest_pct = 0.0
    highest_node = ""

    # Build a lookup from nodes_detail (MV_NODES)
    nodes_detail = _as_row_list(cluster_overview.get("nodes_detail"))
    detail_map: dict = {}
    for nd in nodes_detail:
        ip = nd.get("ip_addr", "")
        nid = str(nd.get("id", ""))
        if ip:
            detail_map[ip] = nd
        if nid:
            detail_map[str(nid)] = nd

    for node in nodes:
        hostname = node.get("hostname", "unknown")
        metrics = node.get("metrics", {}) or {}
        free_data = node.get("free") or metrics.get("memory") or {}

        # Engine memory from MV_NODES (via cluster_overview nodes_detail)
        nd = detail_map.get(hostname) or detail_map.get(str(node.get("node_id", ""))) or {}
        engine_used_raw = nd.get("memory_used_mb")
        if engine_used_raw is None:
            engine_used_raw = (metrics.get("memory") or {}).get("used_mb")
        engine_max_raw = nd.get("max_memory_mb")
        if engine_max_raw is None:
            engine_max_raw = (metrics.get("memory") or {}).get("total_mb")
        engine_used = _safe_float_val(engine_used_raw) if engine_used_raw is not None else None
        engine_max = _safe_float_val(engine_max_raw) if engine_max_raw is not None else None
        table_mem_raw = nd.get("table_memory_used_mb")
        table_mem = _safe_float_val(table_mem_raw) if table_mem_raw is not None else 0.0
        if engine_max and engine_max > 0 and engine_used is not None:
            engine_pct = round((engine_used / engine_max * 100), 1)
        else:
            engine_pct = None
        non_table = max(0.0, (engine_used or 0.0) - table_mem) if engine_used is not None else 0.0

        os_total = _safe_float_val(free_data.get("total_mb")) if free_data.get("total_mb") is not None else None
        os_used = _safe_float_val(free_data.get("used_mb")) if free_data.get("used_mb") is not None else None
        os_avail = _safe_float_val(free_data.get("available_mb")) if free_data.get("available_mb") is not None else None
        if free_data.get("used_pct") is not None:
            os_pct = _safe_float_val(free_data.get("used_pct"))
        elif os_total and os_total > 0 and os_used is not None:
            os_pct = round((os_used / os_total * 100), 1)
        else:
            os_pct = None
        swap_total = _safe_float_val(free_data.get("swap_total_mb")) if free_data.get("swap_total_mb") is not None else None
        swap_used = _safe_float_val(free_data.get("swap_used_mb")) if free_data.get("swap_used_mb") is not None else None
        if free_data.get("swap_used_pct") is not None:
            swap_pct = _safe_float_val(free_data.get("swap_used_pct"))
        elif swap_total and swap_total > 0 and swap_used is not None:
            swap_pct = round((swap_used / swap_total * 100), 1)
        else:
            swap_pct = None

        # Status classification (swap thresholds per SingleStore Toolbox: >5% caution, >10% not recommended)
        # Count cumulatively so "nodes_over_80pct" includes nodes above 90%.
        # The badge label is "over 80%", which must be a superset of "over 90%".
        if engine_pct is not None and engine_pct > 80:
            nodes_over_80 += 1
        if engine_pct is not None and engine_pct > 90:
            nodes_over_90 += 1

        has_metric = engine_pct is not None or os_pct is not None or swap_pct is not None
        if not has_metric:
            status = "unknown"
        elif (engine_pct is not None and engine_pct > 90) or (os_pct is not None and os_pct > 90) or (swap_pct is not None and swap_pct > 10):
            status = "critical"
        elif (engine_pct is not None and engine_pct > 80) or (os_pct is not None and os_pct > 80) or (swap_pct is not None and swap_pct > 5):
            status = "warning"
        else:
            status = "healthy"

        if engine_pct is not None and engine_pct > highest_pct:
            highest_pct = engine_pct
            highest_node = hostname

        per_node[hostname] = {
            "engine_used_mb": round(engine_used, 1) if engine_used is not None else None,
            "engine_max_mb": round(engine_max, 1) if engine_max is not None else None,
            "engine_used_pct": engine_pct,
            "table_memory_mb": round(table_mem, 1),
            "non_table_memory_mb": round(non_table, 1),
            "os_total_mb": round(os_total, 1) if os_total is not None else None,
            "os_used_mb": round(os_used, 1) if os_used is not None else None,
            "os_available_mb": round(os_avail, 1) if os_avail is not None else None,
            "os_used_pct": os_pct,
            "swap_total_mb": round(swap_total, 1) if swap_total is not None else None,
            "swap_used_mb": round(swap_used, 1) if swap_used is not None else None,
            "swap_used_pct": swap_pct,
            "status": status,
            "engine_metrics_available": engine_pct is not None,
            "os_metrics_available": os_pct is not None,
            "swap_metrics_available": swap_pct is not None,
        }

        if engine_max is not None:
            total_engine_max += engine_max
        if engine_used is not None:
            total_engine_used += engine_used
        if os_total is not None:
            total_os_total += os_total
        if os_used is not None:
            total_os_used += os_used

    # Engine-only rows from nodes_detail when OS collectors / parsed nodes are absent.
    # Never invent OS totals from maximum_memory.
    for nd in nodes_detail:
        hostname = str(nd.get("ip_addr") or nd.get("id") or "").strip()
        if not hostname or hostname in per_node:
            continue
        engine_used = _safe_float_val(nd.get("memory_used_mb")) if nd.get("memory_used_mb") is not None else None
        engine_max = _safe_float_val(nd.get("max_memory_mb")) if nd.get("max_memory_mb") is not None else None
        table_mem = _safe_float_val(nd.get("table_memory_used_mb")) if nd.get("table_memory_used_mb") is not None else 0.0
        if engine_max and engine_max > 0 and engine_used is not None:
            engine_pct = round((engine_used / engine_max * 100), 1)
        else:
            engine_pct = None
        non_table = max(0.0, (engine_used or 0.0) - table_mem) if engine_used is not None else 0.0
        if engine_pct is not None and engine_pct > 80:
            nodes_over_80 += 1
        if engine_pct is not None and engine_pct > 90:
            nodes_over_90 += 1
        if engine_pct is None:
            status = "unknown"
        elif engine_pct > 90:
            status = "critical"
        elif engine_pct > 80:
            status = "warning"
        else:
            status = "healthy"
        if engine_pct is not None and engine_pct > highest_pct:
            highest_pct = engine_pct
            highest_node = hostname
        per_node[hostname] = {
            "engine_used_mb": round(engine_used, 1) if engine_used is not None else None,
            "engine_max_mb": round(engine_max, 1) if engine_max is not None else None,
            "engine_used_pct": engine_pct,
            "table_memory_mb": round(table_mem, 1),
            "non_table_memory_mb": round(non_table, 1),
            "os_total_mb": None,
            "os_used_mb": None,
            "os_available_mb": None,
            "os_used_pct": None,
            "swap_total_mb": None,
            "swap_used_mb": None,
            "swap_used_pct": None,
            "status": status,
            "engine_metrics_available": engine_pct is not None,
            "os_metrics_available": False,
            "swap_metrics_available": False,
        }
        if engine_max is not None:
            total_engine_max += engine_max
        if engine_used is not None:
            total_engine_used += engine_used

    avg_engine_pct = round((total_engine_used / total_engine_max * 100), 1) if total_engine_max > 0 else None
    engine_metrics_available = total_engine_max > 0
    os_metrics_available = total_os_total > 0

    return {
        "per_node": per_node,
        "cluster_summary": {
            "total_engine_memory_mb": round(total_engine_max, 1),
            "total_used_engine_mb": round(total_engine_used, 1),
            "avg_engine_used_pct": avg_engine_pct,
            "total_os_memory_mb": round(total_os_total, 1),
            "total_os_used_mb": round(total_os_used, 1),
            "nodes_over_80pct": nodes_over_80,
            "nodes_over_90pct": nodes_over_90,
            "highest_utilization_node": highest_node or None,
            "highest_utilization_pct": highest_pct if highest_node else None,
            "engine_metrics_available": engine_metrics_available,
            "os_metrics_available": os_metrics_available,
        },
    }


def extract_long_running_transactions(processlist: list, blocked_queries: list | None = None) -> dict:
    """Detect long-running transactions and lock contention indicators.

    Analyzes processlist for:
    - Long-running transactions (TRX_STATE = running/active for >60s)
    - Sleeping connections holding locks (cmd=sleep + trx_state=locked)
    - Lock contention from blocked_queries (blocking chains)

    Returns::

        {
            "long_running_tx": [{...}, ...],     # transactions running >60s
            "max_tx_duration_sec": float,
            "long_tx_count": int,
            "lock_waiting_count": int,           # connections waiting for locks
            "blocking_chains": int,               # distinct blockers
            "largest_chain_size": int,
            "has_unkillable": bool,
            "lock_contention_level": "none" | "moderate" | "severe",
        }
    """
    LONG_TX_THRESHOLD = 60.0  # seconds
    long_tx: list = []
    lock_waiting: list = []

    for row in processlist or []:
        time_sec = _row_elapsed_sec(row)
        trx_state = _transaction_state(row)
        trx_name = str(row.get("TRX_NAME", row.get("trx_name", ""))).strip().lower()
        lock_status = str(row.get("LOCK_STATUS", row.get("lock_status", ""))).strip().lower()

        # Long-running open transaction: require an explicit transaction state.
        # TIME is still processlist state age, not guaranteed transaction age.
        if time_sec > LONG_TX_THRESHOLD and trx_state in _OPEN_TRX_STATES:
            query_text = _query_text_from_row(row)[:300]
            long_tx.append({
                "duration_sec": round(time_sec, 1),
                "time_semantics": "seconds_in_current_processlist_state",
                "trx_state": trx_state,
                "trx_name": trx_name,
                "query_text": query_text,
                "user": str(row.get("USER", row.get("user", "?"))),
                "database": str(row.get("DATABASE_NAME", row.get("database", row.get("DB", "?")))),
                "node_id": str(row.get("NODE_ID", row.get("node_id", ""))),
            })

        if lock_status in ("waiting", "locked"):
            lock_waiting.append({
                "duration_sec": round(time_sec, 1),
                "query_text": _query_text_from_row(row)[:200],
                "user": str(row.get("USER", row.get("user", "?"))),
            })

    # Analyze blocking chains
    blocking_chains = 0
    largest_chain = 0
    has_unkillable = False
    if blocked_queries:
        from collections import defaultdict as _dd
        chains: dict = _dd(list)
        for row in blocked_queries:
            blocker = row.get("blocking_query_id") or row.get("blocking_query") or "unknown"
            chains[blocker].append(row)
            if str(row.get("kill_status", "")).lower() == "unkillable":
                has_unkillable = True
        blocking_chains = len(chains)
        if chains:
            largest_chain = max(len(v) for v in chains.values())

    # Determine contention level
    if largest_chain >= 10 or len(lock_waiting) >= 5 or has_unkillable:
        level = "severe"
    elif largest_chain > 0 or len(lock_waiting) > 0 or len(long_tx) > 0:
        level = "moderate"
    else:
        level = "none"

    long_tx.sort(key=lambda x: x["duration_sec"], reverse=True)

    return {
        "long_running_tx": long_tx[:50],
        "max_tx_duration_sec": round((long_tx[0]["duration_sec"] if long_tx else 0.0), 1),
        "long_tx_count": len(long_tx),
        "lock_waiting_count": len(lock_waiting),
        "blocking_chains": blocking_chains,
        "largest_chain_size": largest_chain,
        "has_unkillable": has_unkillable,
        "lock_contention_level": level,
    }


# ─── Cluster overview builder ──────────────────────────────────────

def build_cluster_overview(mv_nodes: list, parsed_nodes: list) -> dict:
    overview = {
        "total_nodes": len(mv_nodes), "leaves": 0, "aggregators": 0,
        "online_nodes": 0, "offline_nodes": 0,
        "total_memory_mb": 0, "used_memory_mb": 0,
        "total_disk_mb": 0, "available_disk_mb": 0, "total_cpus": 0,
        "version": None, "nodes_detail": [], "availability_groups": set(),
    }
    for node in mv_nodes:
        node_type = _normalize_mv_node_type(node)
        if node_type == "LEAF":
            overview["leaves"] += 1
        elif node_type in ("CA", "MA", "AGGREGATOR", "MASTER"):
            overview["aggregators"] += 1
        state = str(node.get("STATE") or node.get("State") or node.get("state") or "").strip().lower()
        if state == "online":
            overview["online_nodes"] += 1
        elif state and state not in ("unknown", "null", "none"):
            overview["offline_nodes"] += 1
        overview["total_memory_mb"] += safe_int(node.get("MAX_MEMORY_MB", 0))
        overview["used_memory_mb"] += safe_int(node.get("MEMORY_USED_MB", 0))
        overview["total_disk_mb"] += safe_int(node.get("TOTAL_DATA_DISK_MB", 0))
        overview["available_disk_mb"] += safe_int(node.get("AVAILABLE_DATA_DISK_MB", 0))
        overview["total_cpus"] += safe_int(node.get("NUM_CPUS", 0))
        version = node.get("VERSION") or node.get("Version") or node.get("version") or node.get("MemsqlVersion")
        if not overview["version"] and version:
            overview["version"] = version
        ag = node.get("AVAILABILITY_GROUP", "") or node.get("AvailabilityGroup", "") or node.get("availability_group", "")
        if ag and ag != "NULL":
            overview["availability_groups"].add(ag)
        overview["nodes_detail"].append({
            "id": node.get("ID", "") or node.get("NodeId", "") or node.get("node_id", ""),
            "ip_addr": node.get("IP_ADDR", "") or node.get("IpAddr", "") or node.get("ip_addr", "") or node.get("Host", "") or node.get("HOST", "") or "",
            "port": node.get("PORT", "") or node.get("Port", "") or node.get("port", ""),
            "type": _normalize_mv_node_type(node) or node.get("TYPE", "") or node.get("Role", "") or node.get("role", ""),
            "state": str(node.get("STATE") or node.get("State") or node.get("state") or "").lower(),
            "availability_group": ag,
            "num_cpus": safe_int(node.get("NUM_CPUS", 0)),
            "max_memory_mb": safe_int(node.get("MAX_MEMORY_MB", 0)),
            "memory_used_mb": safe_int(node.get("MEMORY_USED_MB", 0)),
            "table_memory_used_mb": safe_int(node.get("TABLE_MEMORY_USED_MB", 0)),
            "total_disk_mb": safe_int(node.get("TOTAL_DATA_DISK_MB", 0)),
            "available_disk_mb": safe_int(node.get("AVAILABLE_DATA_DISK_MB", 0)),
            "uptime_seconds": safe_int(node.get("UPTIME", 0)),
            "version": version or "",
        })
    # Enrich nodes_detail with OS-level metrics from parsed_nodes when MV_NODES
    # fields are absent (common with older sdb-report versions).
    # Never index or suffix-match empty host/IP values: every string endswith(""),
    # so an empty MV_NODES host would inherit the first parsed node's metrics
    # (and inflate cluster totals) for every blank row.
    parsed_by_host = {}
    for pn in parsed_nodes:
        host = str(pn.get("hostname") or "").strip()
        if host:
            parsed_by_host[host] = pn
    for nd in overview["nodes_detail"]:
        ip = str(nd.get("ip_addr") or "").strip()
        if not ip:
            continue
        # Try to match MV_NODES ip to a parsed node hostname
        pn = parsed_by_host.get(ip) or parsed_by_host.get(ip.split(":")[0])
        if not pn:
            # Try suffix match (FQDN vs short host, or host vs IP text forms)
            for h, p in parsed_by_host.items():
                if h.endswith(ip) or ip.endswith(h) or h == ip:
                    pn = p
                    break
        if pn:
            # OS `free` totals are not engine maximum_memory / memory_used.
            m = pn.get("metrics", {})
            disk = m.get("disk", [])
            # Sum disk mounts for total/available (values are strings like "1.0T", "550G")
            if nd["total_disk_mb"] == 0 and disk:
                total_disk = sum(
                    units.parse_size(str(d.get("size", "0"))) / (1024 ** 2)
                    for d in disk
                    if _is_physical_df_mount(d)
                )
                avail_disk = sum(
                    units.parse_size(str(d.get("avail", "0"))) / (1024 ** 2)
                    for d in disk
                    if _is_physical_df_mount(d)
                )
                if total_disk > 0:
                    total_disk_mb = int(total_disk)
                    avail_disk_mb = int(avail_disk)
                    nd["total_disk_mb"] = total_disk_mb
                    nd["available_disk_mb"] = avail_disk_mb
                    overview["total_disk_mb"] += total_disk_mb
                    overview["available_disk_mb"] += avail_disk_mb
            # Enrich max_memory_mb / memory_used_mb from OS free(1) when the
            # MV_NODES snapshot has 0 (common with older sdb-report versions).
            if nd["max_memory_mb"] == 0:
                mem = m.get("memory", {})
                os_total = safe_int(mem.get("total_mb", 0))
                os_used = safe_int(mem.get("used_mb", 0))
                if os_total > 0:
                    delta = os_total - nd["max_memory_mb"]
                    nd["max_memory_mb"] = os_total
                    nd["memory_used_mb"] = os_used
                    overview["total_memory_mb"] += delta
                    overview["used_memory_mb"] += os_used - safe_int(nd.get("_orig_memory_used_mb", 0))
            if not nd.get("version") and pn.get("version"):
                nd["version"] = pn["version"]
    overview["availability_groups"] = sorted(list(overview["availability_groups"]))
    if overview["total_disk_mb"] > 0:
        used_disk = overview["total_disk_mb"] - overview["available_disk_mb"]
        overview["disk_used_pct"] = round(used_disk / overview["total_disk_mb"] * 100, 1)
    if overview["total_memory_mb"] > 0:
        overview["memory_used_pct"] = round(overview["used_memory_mb"] / overview["total_memory_mb"] * 100, 1)
    return overview


def build_cluster_overview_from_topology(cluster_topology: dict, parsed_nodes: list) -> dict:
    """Build overview from clusterTopology.json when MV_NODES snapshot is absent."""
    leaves = cluster_topology.get("leaves") or []
    aggregators = cluster_topology.get("aggregators") or []
    combined = list(leaves) + list(aggregators)
    if combined:
        return build_cluster_overview(combined, parsed_nodes)
    overview = build_minimal_cluster_overview(parsed_nodes)
    overview["topology_source"] = "node_directories"
    return overview


def build_minimal_cluster_overview(parsed_nodes: list) -> dict:
    """Fallback overview derived from detected node directories.

    Used when no MV_NODES snapshot (informationSchemaMvNodes.json) is present but
    node directories were found. Surfaces node counts, role split, and any memory
    metrics read from the OS collectors so the dashboard shows basic topology
    instead of an all-zero state.
    """
    overview = {
        "total_nodes": len(parsed_nodes), "leaves": 0, "aggregators": 0,
        "online_nodes": 0, "offline_nodes": 0,
        "total_memory_mb": 0, "used_memory_mb": 0,
        "total_disk_mb": 0, "available_disk_mb": 0, "total_cpus": 0,
        "version": None, "nodes_detail": [], "availability_groups": [],
        "topology_source": "node_directories",
    }
    for node in parsed_nodes:
        role = str(node.get("role") or "").upper()
        if role == "LEAF":
            overview["leaves"] += 1
        elif role in ("CA", "MA", "AGGREGATOR", "MASTER"):
            overview["aggregators"] += 1
        version = node.get("version")
        if not overview["version"] and version:
            overview["version"] = version
        mem = (node.get("metrics", {}) or {}).get("memory", {}) or {}
        total_mb = safe_int(mem.get("total_mb", 0))
        used_mb = safe_int(mem.get("used_mb", 0))
        overview["total_memory_mb"] += total_mb
        overview["used_memory_mb"] += used_mb
        overview["nodes_detail"].append({
            "id": node.get("memsql_id", "") or "",
            "ip_addr": node.get("hostname", "") or "",
            "port": "",
            "type": node.get("role", "") or "",
            "state": "",
            "availability_group": "",
            "num_cpus": 0,
            "max_memory_mb": total_mb,
            "memory_used_mb": used_mb,
            "table_memory_used_mb": 0,
            "total_disk_mb": 0,
            "available_disk_mb": 0,
            "uptime_seconds": 0,
            "version": version or "",
        })
    if overview["total_memory_mb"] > 0:
        overview["memory_used_pct"] = round(
            overview["used_memory_mb"] / overview["total_memory_mb"] * 100, 1
        )
    return overview


# ─── Config health builder ─────────────────────────────────────────

def build_config_health(nodes: list) -> dict:
    """Build configuration health checks across all nodes."""
    health = {"os_checks": [], "variable_consistency": {}, "license": None}

    # Aggregate OS checks
    thp_status = {}
    sysctl_checks = {}
    process_limits_checks = {}

    key_vars_per_node = {}

    for node in nodes:
        hostname = node["hostname"]
        # THP
        thp = node.get("os_checks", {}).get("thp", {})
        thp_status[hostname] = thp.get("status", "unknown")

        # Sysctl
        for param, check in node.get("os_checks", {}).get("sysctl", {}).items():
            if param not in sysctl_checks:
                sysctl_checks[param] = {}
            sysctl_checks[param][hostname] = check

        # Process limits
        pl = node.get("config", {}).get("process_limits", {})
        process_limits_checks[hostname] = pl.get("open_files_soft", 0)

        # Variable consistency
        key_vars_per_node[hostname] = node.get("show_variables", {})

        # License (take first found)
        if not health["license"] and node.get("license"):
            health["license"] = node["license"]

    # Build OS checks list
    # THP check
    thp_failures = [h for h, s in thp_status.items() if s != "disabled"]
    health["os_checks"].append({
        "name": "Transparent Huge Pages",
        "status": "fail" if thp_failures else "pass",
        "severity": "critical" if thp_failures else "pass",
        "detail": f"THP enabled on: {', '.join(thp_failures)}" if thp_failures else "THP disabled on all nodes",
        "doc_link": "https://docs.singlestore.com/db/v9.0/setup/before-you-start/system-requirements/",
        "remediation": "echo never > /sys/kernel/mm/transparent_hugepage/enabled and persist in rc.local / tuned profile."
    })

    # Sysctl checks
    for param, per_node in sysctl_checks.items():
        failures = {h: c for h, c in per_node.items() if c.get("status") in ("fail", "warn")}
        sample_val = next(iter(per_node.values()), {}).get("value", "?")
        health["os_checks"].append({
            "name": f"sysctl {param}",
            "status": "fail" if any(c.get("status") == "fail" for c in failures.values()) else ("warn" if failures else "pass"),
            "severity": next((c.get("severity", "warning") for c in failures.values()), "pass"),
            "detail": f"Value: {sample_val}" + (f" (fails on: {', '.join(failures.keys())})" if failures else " (OK on all nodes)"),
            "nodes": list(failures.keys()) if failures else [],
        })

    # Process limits
    low_nofile = {h: v for h, v in process_limits_checks.items() if 0 < v < 1024000}
    health["os_checks"].append({
        "name": "Open Files Limit (nofile)",
        "status": "fail" if low_nofile else "pass",
        "severity": "critical" if low_nofile else "pass",
        "detail": f"Low nofile on: {', '.join(f'{h}={v}' for h,v in low_nofile.items())}" if low_nofile else "nofile >= 1,024,000 on all nodes",
        "doc_link": "https://docs.singlestore.com/db/v9.0/setup/before-you-start/system-requirements/",
        "remediation": 'Add "memsql soft nofile 1024000" and "memsql hard nofile 1024000" to /etc/security/limits.conf and restart memsqld.'
    })

    # Variable consistency
    all_var_names = set()
    for vars_dict in key_vars_per_node.values():
        all_var_names.update(vars_dict.keys())

    for var_name in sorted(all_var_names):
        values_per_node = {}
        for hostname, vars_dict in key_vars_per_node.items():
            if var_name in vars_dict:
                values_per_node[hostname] = vars_dict[var_name]
        unique_vals = set(values_per_node.values())
        health["variable_consistency"][var_name] = {
            "values": values_per_node,
            "consistent": len(unique_vals) <= 1,
            "unique_values": sorted(list(unique_vals)),
        }

    return health


# ─── Recommendations engine ────────────────────────────────────────

def generate_recommendations(report: dict) -> list:
    try:
        from superchecker import run_superchecker
        return run_superchecker(report)
    except Exception as exc:
        logger.warning("superchecker failed, falling back to basic rule set", exc_info=exc)

    recs = []
    rec_id = 0

    def add_rec(**kwargs):
        nonlocal rec_id
        rec_id += 1
        kwargs["id"] = rec_id
        recs.append(kwargs)

    # RULE-01: Disk usage > 85%
    for node in report.get("nodes", []):
        hostname = node["hostname"]
        for disk in node.get("metrics", {}).get("disk", []):
            pct = disk.get("use_pct", 0)
            mount = disk.get("mounted_on", "")
            if pct > 85 and ("memsql" in mount.lower() or "data" in mount.lower() or "var" in mount.lower()):
                add_rec(
                    severity="critical" if pct > 90 else "warning",
                    category="Storage", title=f"Disk usage {pct}% on {hostname} ({mount})",
                    description=f"Mount {mount} is at {pct}% ({disk['used']}/{disk['size']}). SingleStore tracelogs, columnstore blobs, and temp sort files all compete on the same mount. At >85%, write operations will begin failing.",
                    evidence=f"df -h: {disk['filesystem']} → {pct}% used on {mount}",
                    remediation="1) Free temp/log files. 2) Archive old databases. 3) Add storage or expand volume. 4) Check nodeDirectoriesDiskUsage to find the specific directory consuming space.",
                    doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/node-management/adding-disk-space/",
                    related_views=["df", "nodeDirectoriesDiskUsage"], nodes=[hostname],
                )

    # RULE-02: THP not disabled
    config_health = report.get("config_health", {})
    for check in config_health.get("os_checks", []):
        if check["name"] == "Transparent Huge Pages" and check["status"] == "fail":
            add_rec(
                severity="critical", category="Configuration",
                title="Transparent Huge Pages not disabled",
                description="THP causes latency spikes and memory fragmentation for SingleStore. This is a critical production configuration issue.",
                evidence=check["detail"],
                remediation="echo never > /sys/kernel/mm/transparent_hugepage/enabled and persist in rc.local / tuned profile.",
                doc_link="https://docs.singlestore.com/db/v9.0/setup/before-you-start/system-requirements/",
                related_views=["transparentHugepage"], nodes=[],
            )

    # RULE-03: Redundancy degraded
    overview = report.get("cluster_overview", {})
    cluster_status = overview.get("cluster_status", [])
    offline_parts = [cs for cs in cluster_status if cs.get("State", "").lower() in ("offline", "unreachable", "needs attention")]
    if offline_parts:
        add_rec(
            severity="critical", category="Replication",
            title=f"{len(offline_parts)} partition(s) with degraded redundancy",
            description="Partitions without healthy slaves mean the cluster cannot survive a node failure for those databases.",
            evidence=f"SHOW CLUSTER STATUS: {len(offline_parts)} partitions in non-healthy state",
            remediation="1) Check MV_CLUSTER_STATUS for partition states. 2) Run RESTORE REDUNDANCY ON database_name. 3) Verify leaf connectivity.",
            doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/data-redundancy/",
            related_views=["showClusterStatus", "MV_CLUSTER_STATUS"], nodes=[],
        )

    # RULE-04: Replication lag (placeholder for future lag-based recommendation)

    # RULE-05: OOM kill in dmesg or logs
    for evt in report.get("dmesg_events", []):
        if evt["category"] == "oom":
            add_rec(
                severity="critical", category="Memory",
                title=f"OOM kill detected on {evt['hostname']}",
                description=evt["conclusion"],
                evidence=evt["line"][:200],
                remediation="1) Review maximum_memory setting vs. actual RAM. 2) Check for memory-heavy queries in MV_PLANCACHE. 3) Increase RAM or reduce maximum_memory. 4) Keep vm.overcommit_memory at the recommended value 0 unless a stricter policy is intentionally required.",
                doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/memory-management/",
                related_views=["dmesg", "free", "MV_SYSINFO_MEM"], nodes=[evt["hostname"]],
            )
            break  # One rec per pattern

    # Also check log patterns
    for pat in report.get("detected_log_patterns", []):
        if pat["category"] == "oom" and pat["count"] > 0:
            add_rec(
                severity="critical", category="Memory",
                title=f"OOM pattern found in tracelogs ({pat['count']} occurrences)",
                description=pat["conclusion"],
                evidence=f"First seen: {pat['first_seen']}, Last: {pat['last_seen']}. Sample: {pat['sample'][:150]}",
                remediation="1) Review maximum_memory vs RAM. 2) Check memory-heavy queries. 3) Increase RAM or reduce maximum_memory.",
                doc_link=pat.get("doc_link", ""),
                related_views=["memsqlTracelogs"], nodes=pat.get("nodes", []),
            )

    # Other detected log patterns
    for pat in report.get("detected_log_patterns", []):
        if pat["category"] != "oom" and pat["count"] > 0:
            add_rec(
                severity=pat["severity"], category=pat.get("category", "Logs").title(),
                title=f"{pat['title']} ({pat['count']} occurrences)",
                description=pat["conclusion"],
                evidence=f"Found {pat['count']}x across nodes: {', '.join(pat.get('nodes', []))}. Sample: {pat['sample'][:150]}",
                remediation=pat["conclusion"],
                doc_link=pat.get("doc_link", ""),
                related_views=["memsqlTracelogs"], nodes=pat.get("nodes", []),
            )

    # RULE-06: Columnstore merge queue (from log patterns)
    # Already handled above via get_critical_log_patterns()

    # RULE-07: Pipeline errors
    pipelines = report.get("pipelines", [])
    error_pipes = [p for p in pipelines if (p.get("STATE", "") or "").lower() in ("error", "stopped")]
    if error_pipes:
        add_rec(
            severity="warning", category="Pipelines",
            title=f"{len(error_pipes)} pipeline(s) in error/stopped state",
            description="Pipelines not in Running state may be losing data. Review PIPELINES_ERRORS for specific error codes.",
            evidence=f"Pipelines: {', '.join(p.get('PIPELINE_NAME','?') for p in error_pipes[:5])}",
            remediation="1) Check PIPELINES_ERRORS for specific error codes. 2) Fix source connectivity. 3) Restart pipelines with START PIPELINE.",
            doc_link="https://docs.singlestore.com/db/v9.0/load-data/about-singlestore-pipelines/pipeline-troubleshooting/",
            related_views=["informationSchemaPipelines", "PIPELINES_ERRORS"], nodes=[],
        )

    # RULE-08: Mixed versions
    versions = set()
    for nd in overview.get("nodes_detail", []):
        v = nd.get("version", "")
        if v:
            versions.add(v)
    if len(versions) > 1:
        add_rec(
            severity="warning", category="Configuration",
            title="Mixed node versions detected",
            description=f"Versions: {', '.join(sorted(versions))}. Do not leave the cluster in mixed-version state for >1 hour.",
            evidence="MV_NODES VERSION column",
            remediation="Complete or rollback the in-progress upgrade. Do not leave the cluster in mixed-version state for >1 hour.",
            doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/upgrade/",
            related_views=["MV_NODES", "MV_VERSION_HISTORY"], nodes=[],
        )

    # RULE-09: Process limits (nofile)
    for check in config_health.get("os_checks", []):
        if check["name"] == "Open Files Limit (nofile)" and check["status"] == "fail":
            add_rec(
                severity="critical", category="Configuration",
                title="Open files limit (nofile) too low",
                description="SingleStore requires high file descriptor limits. Insufficient limits cause failures under load, especially for columnstore workloads.",
                evidence=check["detail"],
                remediation='Add "memsql soft nofile 1000000" and "memsql hard nofile 1000000" to /etc/security/limits.conf and restart memsqld.',
                doc_link="https://docs.singlestore.com/db/v9.0/setup/before-you-start/system-requirements/",
                related_views=["memsqldProcessLimits", "securityLimits"], nodes=[],
            )

    # RULE-10: Backup health
    backups = report.get("backup_history", [])
    if backups:
        # Find most recent successful backup
        successful = [b for b in backups if b.get("STATUS", "").lower() == "success"]
        if successful:
            latest_ts = max(b.get("START_TIMESTAMP", "") for b in successful)
            try:
                latest_dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - latest_dt).days
                if days_since > 7:
                    add_rec(
                        severity="critical" if days_since > 30 else "warning",
                        category="Backup",
                        title=f"Last successful backup was {days_since} days ago",
                        description="SingleStore backups are the only protection against corruption or accidental deletion. An outdated backup means significant data loss risk.",
                        evidence=f"Last successful backup: {latest_ts}",
                        remediation="Schedule a BACKUP DATABASE ... TO ... immediately and configure regular automated backups.",
                        doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/backup-and-restore/",
                        related_views=["MV_BACKUP_HISTORY"], nodes=[],
                    )
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    elif not backups:
        add_rec(
            severity="warning", category="Backup",
            title="No backup history found",
            description="No backup records were found in MV_BACKUP_HISTORY.",
            evidence="MV_BACKUP_HISTORY is empty",
            remediation="Configure and run regular backups.",
            doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/backup-and-restore/",
            related_views=["MV_BACKUP_HISTORY"], nodes=[],
        )

    # Memory pressure checks
    for node in report.get("nodes", []):
        hostname = node["hostname"]
        mem = node.get("metrics", {}).get("memory", {})
        if mem.get("used_pct", 0) > 85:
            add_rec(
                severity="critical" if mem["used_pct"] > 95 else "warning",
                category="Memory",
                title=f"High memory usage on {hostname} ({mem['used_pct']}%)",
                description=f"Memory usage is at {mem['used_pct']}% ({mem.get('used_mb', 0)} MB / {mem.get('total_mb', 0)} MB). If OS available memory falls below 1 GB, OOM-killer may terminate the memsqld process.",
                evidence=f"free -m: {mem.get('available_mb', 0)} MB available of {mem.get('total_mb', 0)} MB total",
                remediation="1) Check maximum_memory variable. 2) Investigate memory-heavy queries via MV_PLANCACHE. 3) Increase RAM or add leaf nodes.",
                doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/memory-management/",
                related_views=["free", "MV_SYSINFO_MEM", "showVariables"], nodes=[hostname],
            )
        if mem.get("swap_used_mb", 0) > 0:
            add_rec(
                severity="warning", category="Memory",
                title=f"Swap usage on {hostname} ({mem.get('swap_used_mb', 0)} MB)",
                description="Any swap usage on a SingleStore node indicates memory pressure has spilled to disk, degrading query performance.",
                evidence=f"free -m: swap used={mem.get('swap_used_mb', 0)} MB",
                remediation="Investigate memory pressure. Consider vm.swappiness=0 and adding RAM.",
                doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/memory-management/",
                related_views=["free", "sysctl"], nodes=[hostname],
            )

    # Offline nodes
    if overview.get("offline_nodes", 0) > 0:
        add_rec(
            severity="critical", category="Availability",
            title=f"{overview['offline_nodes']} node(s) offline",
            description=f"Out of {overview.get('total_nodes', 0)} nodes, {overview['offline_nodes']} are not online. Partitions served only from redundant copies.",
            evidence="MV_NODES STATE column",
            remediation="Check node connectivity, memsqld process status, and network configuration.",
            doc_link="https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/",
            related_views=["MV_NODES", "SHOW CLUSTER STATUS"], nodes=[],
        )

    # License expiry
    license_info = config_health.get("license")
    if license_info and license_info.get("days_remaining") is not None:
        days = license_info["days_remaining"]
        if days < 30:
            add_rec(
                severity="critical" if days < 7 else "warning",
                category="Configuration",
                title=f"License expires in {days} days",
                description=f"License type: {license_info.get('type', '?')}, capacity: {license_info.get('capacity', '?')}. Expiry: {license_info.get('expiry_date', '?')}.",
                evidence=f"licenseMetadata: expires {license_info.get('expiry_date', '?')}",
                remediation="Contact SingleStore sales to renew your license before expiry.",
                doc_link="https://docs.singlestore.com/db/v9.0/",
                related_views=["licenseMetadata"], nodes=[],
            )

    # Variable consistency
    for var_name, vc in config_health.get("variable_consistency", {}).items():
        if not vc.get("consistent") and var_name in ["maximum_memory", "redundancy_level", "sql_mode"]:
            add_rec(
                severity="warning", category="Configuration",
                title=f"Variable mismatch: {var_name}",
                description=f"Variable '{var_name}' has different values across nodes: {', '.join(vc.get('unique_values', []))}. This can cause inconsistent query performance.",
                evidence=f"showVariables: {var_name} → {vc.get('unique_values', [])}",
                remediation="Align the variable value across all nodes using SET GLOBAL or memsql.cnf.",
                doc_link="https://docs.singlestore.com/db/v9.0/",
                related_views=["showVariables", "syncVariables"], nodes=[],
            )

    # Dmesg storage/CPU events
    for evt in report.get("dmesg_events", []):
        if evt["category"] in ("storage_fault", "cpu") and evt["severity"] == "critical":
            add_rec(
                severity="critical", category="System",
                title=f"{evt['title']} on {evt['hostname']}",
                description=evt["conclusion"],
                evidence=evt["line"][:200],
                remediation="Check hardware health. Replace faulty components if needed.",
                doc_link="https://docs.singlestore.com/db/v9.0/",
                related_views=["dmesg"], nodes=[evt["hostname"]],
            )
            break

    # Log error count
    log_summary = report.get("log_summary", {})
    sev = log_summary.get("severity_counts", {})
    err_count = sev.get("ERROR", 0) + sev.get("FATAL", 0)
    if err_count > 10:
        add_rec(
            severity="warning" if err_count < 50 else "critical",
            category="Logs", title=f"{err_count} error/fatal log entries",
            description=f"Found {sev.get('ERROR', 0)} ERROR and {sev.get('FATAL', 0)} FATAL entries across all tracelogs.",
            evidence=f"Log analysis: {log_summary.get('total', 0)} total entries across {len(log_summary.get('per_node', {}))} nodes",
            remediation="Review the Logs Explorer page. Correlated ERROR spikes across multiple nodes indicate cluster-wide events.",
            doc_link="https://docs.singlestore.com/db/v9.0/",
            related_views=["memsqlTracelogs"], nodes=[],
        )

    # Events
    events = report.get("events", [])
    error_events = [e for e in events if e.get("SEVERITY", "").upper() in ("ERROR", "CRITICAL", "FATAL")]
    if error_events:
        add_rec(
            severity="warning", category="Events",
            title=f"{len(error_events)} error event(s) in MV_EVENTS",
            description="MV_EVENTS is the cluster's own audit trail of significant state changes. Always review events when diagnosing incidents.",
            evidence=f"MV_EVENTS: {len(error_events)} error-severity events",
            remediation="Review event details for PARTITION OFFLINE, FAILOVER, NODE FAILURE events.",
            doc_link="https://docs.singlestore.com/db/v9.0/",
            related_views=["MV_EVENTS"], nodes=[],
        )

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4, "info": 5}
    recs.sort(key=lambda r: severity_order.get(r.get("severity", "info"), 5))
    return recs


def generate_recommendations_with_clusters(report: dict) -> tuple:
    """Like generate_recommendations, but also returns incident_clusters.

    Returns (recommendations, incident_clusters).  Falls back to the legacy
    path (empty clusters) if the superchecker import fails.
    """
    try:
        from superchecker import run_superchecker_with_clusters
        return run_superchecker_with_clusters(report)
    except Exception as exc:
        logger.debug("parser: ignoring non-fatal error", exc_info=exc)

    return generate_recommendations(report), []


# ─── Utilities ──────────────────────────────────────────────────────

def read_stdout(node_path, collector_name):
    dir_path = os.path.join(node_path, collector_name)
    if os.path.isdir(dir_path):
        candidates = []
        for f in sorted(os.listdir(dir_path)):
            if f.endswith('_stdout') or f == 'stdout':
                candidates.append(os.path.join(dir_path, f))
        if candidates:
            try:
                with open(candidates[0]) as fh:
                    return fh.read(102400)
            except OSError as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    # Flat layout: free_stdout, sysctl_stdout, etc. directly under node dir
    for flat_name in (f"{collector_name}_stdout", f"{collector_name}.stdout"):
        flat_path = os.path.join(node_path, flat_name)
        if os.path.isfile(flat_path):
            try:
                with open(flat_path) as fh:
                    return fh.read(102400)
            except OSError as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return ""


def parse_text_file(node_path, collector_name):
    content = read_stdout(node_path, collector_name)
    if content:
        return content[:5000]
    for ext in ['', '.txt', '.log']:
        fpath = os.path.join(node_path, collector_name + ext)
        if os.path.isfile(fpath):
            try:
                # Limit read to 10KB to prevent memory issues
                with open(fpath, 'r') as fh:
                    return fh.read(10240)[:5000]
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return ""


def parse_global_info(global_path):
    result = {}
    for f in os.listdir(global_path):
        fpath = os.path.join(global_path, f)
        if os.path.isfile(fpath) and f.endswith('.json'):
            try:
                try:
                    size = os.path.getsize(fpath)
                    limit = _json_file_size_limit(f)
                    if size > limit:
                        continue
                except Exception as exc:
                    logger.debug("parser: ignoring non-fatal error", exc_info=exc)
                with open(fpath) as fh:
                    result[f.replace('.json', '')] = json.load(fh)
            except Exception as exc:
                logger.debug("parser: ignoring non-fatal error", exc_info=exc)
    return result


def safe_int(val):
    try:
        s = str(val).strip()
        if not s:
            return 0
        s = s.replace(",", "")
        if s.endswith("%"):
            s = s[:-1]
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return 0
        return int(float(m.group(0)))
    except (ValueError, TypeError):
        return 0


def parse_mount_stdout(node_path: str) -> dict:
    """Parse mount_stdout collector to check mount options (noatime, discard, etc.)."""
    content = read_stdout(node_path, "mount_stdout")
    if not content:
        content = read_stdout(node_path, "mount")
    if not content:
        return {"mounts": []}

    mounts = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or not line.startswith("/"):
            continue
        # Parse: /dev/sda1 on /data type ext4 (rw,noatime)
        m = re.match(
            r"^(\S+)\s+on\s+(\S+)\s+type\s+(\S+)\s+\((.+)\)", line
        )
        if not m:
            continue
        device, mount_point, fs_type, options_str = m.groups()
        options = [o.strip() for o in options_str.split(",")]
        mounts.append({
            "device": device,
            "mount_point": mount_point,
            "fs_type": fs_type,
            "options": options,
            "has_noatime": "noatime" in options,
            "has_discard": "discard" in options,
            "has_nodiscard": "nodiscard" in options,
        })
    return {"mounts": mounts}


def parse_cpu_governor(node_path: str) -> dict:
    """Parse CPU governor configuration from cpuGovernor collector or cpuFreqInfo.json."""
    content = read_stdout(node_path, "cpuGovernor")
    if not content:
        content = read_stdout(node_path, "cpu_governor")
    if not content:
        freq_info = parse_json_file(node_path, "cpuFreqInfo.json")
        if freq_info:
            governors = []
            if isinstance(freq_info, list):
                for entry in freq_info:
                    gov = entry.get("governor", "")
                    if gov:
                        governors.append(gov)
            elif isinstance(freq_info, dict):
                gov = freq_info.get("governor", "")
                if gov:
                    governors.append(gov)
            if governors:
                return {"governors": governors, "source": "cpuFreqInfo.json"}
        return {"governors": []}

    governors = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Lines like: cpu0: performance  or  governor=performance
        m = re.search(r"(?:governor[=:]\s*)?(\S+)$", line)
        if m:
            gov = m.group(1).strip().lower()
            if gov in ("performance", "powersave", "ondemand", "conservative", "userspace", "schedutil"):
                governors.append(gov)
    return {"governors": governors, "source": "cpuGovernor"}


def parse_tcp_keepalive(node_path: str) -> dict:
    """Parse TCP keepalive sysctl values for tuning checks."""
    content = read_stdout(node_path, "sysctl")
    if not content:
        return {}

    result = {}
    keepalive_params = {
        "net.ipv4.tcp_keepalive_time": "tcp_keepalive_time",
        "net.ipv4.tcp_keepalive_intvl": "tcp_keepalive_intvl",
        "net.ipv4.tcp_keepalive_probes": "tcp_keepalive_probes",
    }
    for line in content.split("\n"):
        line = line.strip()
        for param, short_name in keepalive_params.items():
            if line.startswith(param):
                parts = line.split("=")
                if len(parts) >= 2:
                    val = parts[1].strip()
                    result[short_name] = {
                        "value": val,
                        "numeric": safe_int(val),
                    }
    return result
