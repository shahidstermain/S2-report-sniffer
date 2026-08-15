"""
Disk reclamation accounting: cluster overhead buckets and blobs-vs-referenced delta.

ENH-1: Split CLUSTER OVERHEAD into referenced-non-table vs unreferenced-blobs sub-buckets.
ENH-2: Per-node on-disk blobs minus MV columnstore referenced bytes (HA-aware).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

import units
from archive_security import path_is_within_root

logger = logging.getLogger(__name__)

_DATADIR_BUCKET_SUFFIXES = {
    "transaction_logs": ("/data/logs", "/logs"),
    "logs": ("/data/logs", "/logs"), # Deprecated alias for transaction_logs
    "snapshots": ("/data/snapshots", "/snapshots"),
    "spill": ("/data/spill", "/spill"),
    "blobs": ("/data/blobs", "/blobs"),
    "tracelogs": ("/tracelogs",),
    "plancache": ("/plancache",),
    "auditlogs": ("/auditlogs",),
    "cores": ("/cores",),
}

_COLLECTOR_DIR_MAP = {
    "tracelogs": "tracelogsdir",
    "plancache": "plancachedir",
    "auditlogs": "auditlogsdir",
}

# Include deprecated "logs" so /data/logs paths match; _apply remaps to transaction_logs.
_DU_DATADIR_BUCKETS = frozenset(["transaction_logs", "logs", "snapshots", "spill", "blobs"])
_DU_COLLECTOR_BUCKETS = frozenset(list(_COLLECTOR_DIR_MAP.keys()) + ["cores"])

COLUMNAR_SEGMENTS_COLLECTOR = "informationSchemaColumnarSegments.json"

# ENH-3 defaults (percent of used cluster disk)
DEFAULT_UNREFERENCED_BLOBS_PCT_THRESHOLD = 15.0

_DU_LINE_RE = re.compile(r"^([\d.]+)\s*([KMGT]?)\s+(\S+)\s*$")


def parse_human_size_to_bytes(size_str: str) -> int:
    """Parse du -hca human sizes (binary KiB/MiB/GiB) to integer bytes."""
    try:
        return units.parse_size(size_str, binary=True)
    except (ValueError, TypeError):
        return 0


def _parse_du_line(line: str) -> tuple[int, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split("\t", 1)
    if len(parts) != 2:
        parts = line.split(None, 1)
        if len(parts) != 2:
            return None
    size_raw, path = parts[0].strip(), parts[1].strip()
    # du may emit "800G" or "800 G" — normalize
    size_raw = size_raw.replace(" ", "")
    try:
        size_bytes = units.parse_size(size_raw, binary=True)
    except (ValueError, TypeError):
        return None
    return size_bytes, path


def _path_matches_bucket(path: str, suffixes: tuple[str, ...]) -> bool:
    norm = path.rstrip("/")
    for suffix in suffixes:
        if norm.endswith(suffix):
            # Exclude deeper paths like .../data/blobs/16/647 when matching .../data/blobs
            if suffix.endswith("blobs") and norm.count("/data/blobs/") > 0:
                continue
            return True
    return False


def parse_du_hca_stdout(content: str) -> dict[str, Any]:
    """
    Parse du -hca stdout. Returns total_bytes (from ``total`` line if present)
    and per-path sizes for top-level matches.
    """
    lines = content.splitlines()
    total_bytes = 0
    path_sizes: dict[str, int] = {}
    for line in lines:
        parsed = _parse_du_line(line)
        if not parsed:
            continue
        size_bytes, path = parsed
        if path.strip().lower() == "total":
            total_bytes = max(total_bytes, size_bytes)
            continue
        path_sizes[path] = size_bytes
    return {"total_bytes": total_bytes, "paths": path_sizes}


def _read_node_directories_stdout(node_path: str, memsql_id: str, dir_kind: str) -> str:
    """Read a du-hca stdout file under nodeDirectoriesDiskUsage/."""
    base = os.path.join(node_path, "nodeDirectoriesDiskUsage")
    if not os.path.isdir(base) or not path_is_within_root(base, node_path):
        return ""
    prefix = f"{memsql_id}_du-hca_{dir_kind}_stdout"
    for fname in sorted(os.listdir(base)):
        if fname == prefix or fname.endswith(f"_du-hca_{dir_kind}_stdout"):
            fpath = os.path.join(base, fname)
            if not path_is_within_root(fpath, node_path):
                continue
            try:
                with open(fpath, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError as exc:
                logger.debug("disk_reclamation: cannot read %s: %s", fpath, exc)
    return ""


def _read_file_tail_bytes(fpath: str, max_bytes: int = 65536, *, root: str | None = None) -> str:
    if root is not None and not path_is_within_root(fpath, root):
        return ""
    try:
        with open(fpath, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _read_file_head_lines(fpath: str, max_lines: int = 4000, *, root: str | None = None) -> list[str]:
    if root is not None and not path_is_within_root(fpath, root):
        return []
    lines: list[str] = []
    try:
        with open(fpath, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                lines.append(line)
    except OSError:
        pass
    return lines


def _apply_du_lines_to_buckets(lines: list[str], buckets: dict[str, int]) -> None:
    for line in lines:
        parsed = _parse_du_line(line)
        if not parsed:
            continue
        size_bytes, path = parsed
        if path.strip().lower() == "total":
            buckets["datadir_total"] = max(buckets["datadir_total"], size_bytes)
            continue
        for bucket in _DU_DATADIR_BUCKETS:
            # Handle deprecated 'logs' alias by directing it to 'transaction_logs'
            target_bucket = "transaction_logs" if bucket == "logs" else bucket
            for suffix in _DATADIR_BUCKET_SUFFIXES[bucket]:
                if _path_matches_bucket(path, (suffix,)):
                    buckets[target_bucket] = max(buckets[target_bucket], size_bytes)
                    if bucket == "logs":
                        buckets["logs"] = buckets["transaction_logs"]
                    break


def _grep_binary() -> str:
    for candidate in ("/usr/bin/grep", "/bin/grep"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "grep"


def _grep_datadir_bucket_lines(fpath: str) -> list[str]:
    """Extract only top-level datadir bucket lines from huge du -hca outputs."""
    # Parent bucket paths end exactly at /data/{logs,blobs,snapshots,spill}; include total rollup.
    # Real du paths use /data/logs (not /data/transaction_logs); alias remap is in _apply.
    pattern = r"/data/(logs|blobs|snapshots|spill)$|\ttotal$"
    try:
        proc = subprocess.run(
            [_grep_binary(), "-aE", pattern, fpath],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode in (0, 1):
            return [ln for ln in proc.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("disk_reclamation: grep datadir buckets failed: %s", exc)
    return []


def _grep_cores_bytes(node_path: str, memsql_id: str) -> int:
    """Grep for core files in the datadir and sum their sizes."""
    base = os.path.join(node_path, "nodeDirectoriesDiskUsage")
    if not os.path.isdir(base):
        return 0
    prefix = f"{memsql_id}_du-hca_datadir_stdout"
    fpath = None
    for fname in sorted(os.listdir(base)):
        if fname == prefix or fname.endswith("_du-hca_datadir_stdout"):
            fpath = os.path.join(base, fname)
            break
    if not fpath:
        return 0

    # Grep for lines containing 'core.' files and sum their sizes
    pattern = r".*/data/memsqld/[^/]+/core\..*$"
    try:
        proc = subprocess.run(
            [_grep_binary(), "-aE", pattern, fpath],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode in (0, 1):
            total_bytes = 0
            for line in proc.stdout.splitlines():
                parsed = _parse_du_line(line)
                if parsed:
                    size_bytes, _ = parsed
                    total_bytes += size_bytes
            return total_bytes
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("disk_reclamation: grep cores failed: %s", exc)
    return 0


def _stream_du_datadir_buckets(node_path: str, memsql_id: str) -> dict[str, int]:
    """Extract datadir bucket sizes from du -hca stdout (grep + head for logs)."""
    base = os.path.join(node_path, "nodeDirectoriesDiskUsage")
    if not os.path.isdir(base) or not path_is_within_root(base, node_path):
        return {}
    prefix = f"{memsql_id}_du-hca_datadir_stdout"
    fpath = None
    for fname in sorted(os.listdir(base)):
        if fname == prefix or fname.endswith("_du-hca_datadir_stdout"):
            candidate = os.path.join(base, fname)
            if path_is_within_root(candidate, node_path):
                fpath = candidate
                break
    if not fpath:
        return {}

    buckets: dict[str, int] = {k: 0 for k in list(_DATADIR_BUCKET_SUFFIXES) + ["datadir_total"]}
    lines = _grep_datadir_bucket_lines(fpath)
    if not lines:
        _apply_du_lines_to_buckets(_read_file_head_lines(fpath, 8000, root=node_path), buckets)
        _apply_du_lines_to_buckets(_read_file_tail_bytes(fpath, 262144, root=node_path).splitlines(), buckets)
    else:
        _apply_du_lines_to_buckets(lines, buckets)
    # Logs often appear early; merge head scan when grep missed them.
    if buckets.get("logs", 0) == 0:
        _apply_du_lines_to_buckets(_read_file_head_lines(fpath, 8000, root=node_path), buckets)
    return buckets


def _resolve_memsql_id(node: dict) -> str:
    manifest = (node.get("metrics") or {}).get("node_disk_usage") or {}
    nodes = manifest.get("nodes") if isinstance(manifest, dict) else None
    if isinstance(nodes, list) and nodes:
        row = nodes[0]
        if isinstance(row, dict):
            return str(row.get("memsqlID") or row.get("memsql_id") or "")
    cfg = node.get("config") or {}
    ctl = cfg.get("memsqlctl_info") or {}
    if isinstance(ctl, dict):
        return str(ctl.get("memsqlID") or ctl.get("id") or "")
    return ""


def _node_data_mount_used_bytes(node: dict) -> int:
    """Best-effort used bytes on SingleStore data mounts from df collector."""
    total = 0
    for disk in (node.get("metrics") or {}).get("disk") or []:
        if not isinstance(disk, dict):
            continue
        mount = str(disk.get("mounted_on") or "").lower()
        if not any(tok in mount for tok in ("memsql", "hdisk", "data", "singlestore")):
            continue
        used = disk.get("used_bytes")
        if used is None:
            used_human = disk.get("used")
            used = parse_human_size_to_bytes(str(used_human)) if used_human else 0
        total += int(used or 0)
    return total


def _sum_database_disk_bytes(database_disk_usage: list) -> int:
    total = 0.0
    for row in database_disk_usage:
        if not isinstance(row, dict):
            continue
        direct = row.get("_disk_bytes") or row.get("disk_bytes")
        if direct:
            total += float(direct)
            continue
        gb = row.get("TOTAL_DISK_USAGE_GB")
        if gb is not None:
            total += float(gb) * (1024**3)
    return int(total)


def _detect_redundancy_level(report: dict) -> tuple[int, str]:
    """Return (numeric level, source description). Level 2+ implies HA doubling candidate."""
    overview = report.get("cluster_overview") or {}
    for nd in overview.get("nodes_detail") or []:
        if not isinstance(nd, dict):
            continue
    # Prefer show_variables from any node
    best = 0
    source = "unknown"
    for node in report.get("nodes") or []:
        sv = (node.get("show_variables") or {})
        if not isinstance(sv, dict):
            continue
        val = sv.get("redundancy_level")
        if val is None:
            continue
        try:
            level = int(str(val).strip())
            if level > best:
                best = level
                source = f"show_variables redundancy_level={level}"
        except ValueError:
            continue
    if best >= 2:
        return best, source
    # Fallback: availability groups imply HA
    ags = report.get("availability_groups") or []
    if isinstance(ags, list) and len(ags) >= 2:
        return 2, f"availability_groups count={len(ags)}"
    return best, source


def _columnstore_collector_present(report: dict) -> bool:
    for node in report.get("nodes") or []:
        node_path = node.get("_node_path") or ""
        if node_path and os.path.isfile(os.path.join(node_path, COLUMNAR_SEGMENTS_COLLECTOR)):
            return True
    # Parsed payload may already carry rows
    rows = report.get("columnstore_files") or []
    return bool(rows)


def _parse_columnstore_files_from_nodes(nodes: list) -> list[dict]:
    from parsers import parse_sdb_json_table  # local import avoids cycle at module load

    rows: list[dict] = []
    for node in nodes:
        node_path = node.get("_node_path") or ""
        if not node_path:
            continue
        table = parse_sdb_json_table(node_path, COLUMNAR_SEGMENTS_COLLECTOR)
        if table:
            rows.extend(table)
    return rows


def _columnstore_bytes_by_node(rows: list[dict], report: dict) -> dict[str, int]:
    """Sum referenced columnstore file bytes grouped by node host/id."""
    id_to_host: dict[str, str] = {}
    for nd in (report.get("cluster_overview") or {}).get("nodes_detail") or []:
        if not isinstance(nd, dict):
            continue
        nid = str(nd.get("id") or "")
        host = str(nd.get("ip_addr") or nd.get("hostname") or nid)
        if nid:
            id_to_host[nid] = host

    per_node: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        size = row.get("FILE_SIZE") or row.get("file_size") or row.get("BYTES") or row.get("bytes")
        try:
            size_i = int(float(size or 0))
        except (TypeError, ValueError):
            size_i = 0
        if size_i <= 0:
            continue
        node_key = str(
            row.get("NODE_ID")
            or row.get("node_id")
            or row.get("HOST")
            or row.get("host")
            or ""
        )
        host = id_to_host.get(node_key, node_key)
        if not host:
            continue
        per_node[host] = per_node.get(host, 0) + size_i
    return per_node


def resolve_blobs_referenced_delta(report: dict) -> dict[str, Any]:
    """
    ENH-2: Per-node on-disk blobs minus referenced columnstore bytes.

    Skips with an actionable message when columnstore detail collector is absent.
    """
    nodes = report.get("nodes") or []
    per_node_du: dict[str, dict[str, int]] = {}
    incomplete_nodes: list[str] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        host = str(node.get("hostname") or "unknown")
        cached = node.get("disk_du_buckets") if isinstance(node.get("disk_du_buckets"), dict) else {}
        if cached:
            per_node_du[host] = cached
            if not cached.get("blobs") and not cached.get("datadir_total"):
                incomplete_nodes.append(host)
            continue
        node_path = node.get("_node_path") or ""
        memsql_id = _resolve_memsql_id(node)
        if not node_path or not memsql_id:
            incomplete_nodes.append(host)
            continue
        datadir = _stream_du_datadir_buckets(node_path, memsql_id)
        if not datadir.get("blobs") and not datadir.get("datadir_total"):
            incomplete_nodes.append(host)
        per_node_du[host] = datadir

    if not _columnstore_collector_present(report):
        return {
            "status": "skipped",
            "skip_reason": (
                "Columnstore file detail not in this bundle. Re-collect with "
                "`sdb-report collect --include informationSchemaColumnarSegments` "
                "to compute blobs-vs-referenced delta."
            ),
            "per_node": [],
            "cluster": {},
            "ha_factor": 1,
            "ha_assumption": None,
            "incomplete_nodes": incomplete_nodes,
        }

    rows = report.get("columnstore_files") or []
    if not rows:
        rows = _parse_columnstore_files_from_nodes(nodes)
    referenced_by_node = _columnstore_bytes_by_node(rows, report)

    redundancy_level, redundancy_source = _detect_redundancy_level(report)
    ha_factor = 2 if redundancy_level >= 2 else 1
    ha_assumption = (
        f"HA redundancy detected ({redundancy_source}); referenced columnstore bytes "
        f"multiplied by {ha_factor} because MV columnstore file views may exclude "
        f"secondary partitions in 8.9+."
        if ha_factor > 1
        else "No HA redundancy detected; referenced bytes used as-is."
    )

    per_node_out: list[dict[str, Any]] = []
    cluster_on_disk = 0
    cluster_referenced = 0
    cluster_delta = 0

    all_hosts = sorted(set(list(per_node_du.keys()) + list(referenced_by_node.keys())))
    for host in all_hosts:
        du = per_node_du.get(host) or {}
        on_disk = int(du.get("blobs") or 0)
        referenced_raw = int(referenced_by_node.get(host) or 0)
        referenced = referenced_raw * ha_factor
        if host in incomplete_nodes and on_disk == 0:
            per_node_out.append({
                "node": host,
                "status": "incomplete",
                "on_disk_blobs_bytes": None,
                "referenced_bytes": referenced_raw,
                "referenced_adjusted_bytes": referenced,
                "delta_bytes": None,
                "delta_pct": None,
            })
            continue
        delta = max(0, on_disk - referenced)
        delta_pct = round((delta / on_disk) * 100, 1) if on_disk > 0 else 0.0
        per_node_out.append({
            "node": host,
            "status": "ok",
            "on_disk_blobs_bytes": on_disk,
            "referenced_bytes": referenced_raw,
            "referenced_adjusted_bytes": referenced,
            "delta_bytes": delta,
            "delta_pct": delta_pct,
        })
        cluster_on_disk += on_disk
        cluster_referenced += referenced
        cluster_delta += delta

    used_disk = sum(_node_data_mount_used_bytes(n) for n in nodes if isinstance(n, dict))
    return {
        "status": "ok" if per_node_out else "partial",
        "skip_reason": None,
        "ha_factor": ha_factor,
        "ha_assumption": ha_assumption,
        "redundancy_level": redundancy_level,
        "per_node": per_node_out,
        "incomplete_nodes": incomplete_nodes,
        "cluster": {
            "on_disk_blobs_bytes": cluster_on_disk,
            "referenced_adjusted_bytes": cluster_referenced,
            "delta_bytes": cluster_delta,
            "delta_pct_of_used_disk": round((cluster_delta / used_disk) * 100, 1) if used_disk > 0 else 0.0,
        },
    }


def extract_node_disk_du_buckets(node_path: str, manifest: Any) -> dict[str, int]:
    """Parse filesystem du collectors for one node (called during node directory parse)."""
    memsql_id = ""
    if isinstance(manifest, dict):
        nodes = manifest.get("nodes")
        if isinstance(nodes, list) and nodes:
            row = nodes[0]
            if isinstance(row, dict):
                memsql_id = str(row.get("memsqlID") or row.get("memsql_id") or "")
    if not memsql_id:
        return {}
    datadir = _stream_du_datadir_buckets(node_path, memsql_id)
    out = {
        "transaction_logs": int(datadir.get("transaction_logs") or datadir.get("logs") or 0),
        "logs": int(datadir.get("transaction_logs") or datadir.get("logs") or 0), # Deprecated alias
        "snapshots": int(datadir.get("snapshots") or 0),
        "spill": int(datadir.get("spill") or 0),
        "blobs": int(datadir.get("blobs") or 0),
        "datadir_total": int(datadir.get("datadir_total") or 0),
        "tracelogs": 0,
        "plancache": 0,
        "auditlogs": 0,
        "cores": 0,
    }
    for bucket, dir_kind in _COLLECTOR_DIR_MAP.items():
        content = _read_node_directories_stdout(node_path, memsql_id, dir_kind)
        if not content:
            continue
        parsed = parse_du_hca_stdout(content)
        total = int(parsed.get("total_bytes") or 0)
        if not total and parsed.get("paths"):
            total = max(parsed["paths"].values())
        out[bucket] = total
    return out


def _extract_node_non_table_buckets(node: dict) -> dict[str, int]:
    cached = node.get("disk_du_buckets")
    if isinstance(cached, dict) and cached:
        return {k: int(cached.get(k) or 0) for k in ["transaction_logs", "logs", "snapshots", "spill", "blobs", "tracelogs", "plancache", "auditlogs", "cores"]}

    host_path = node.get("_node_path") or ""
    memsql_id = _resolve_memsql_id(node)
    out = {k: 0 for k in ["transaction_logs", "logs", "snapshots", "spill", "blobs", "tracelogs", "plancache", "auditlogs", "cores"]}
    if not host_path or not memsql_id:
        return out

    datadir = _stream_du_datadir_buckets(host_path, memsql_id)
    for key in ("transaction_logs", "logs", "snapshots", "spill", "blobs"):
        out[key] = int(datadir.get(key) or 0)

    # Collect cores separately
    core_bytes = _grep_cores_bytes(host_path, memsql_id)
    if core_bytes > 0:
        out["cores"] = core_bytes

    for bucket, dir_kind in _COLLECTOR_DIR_MAP.items():
        content = _read_node_directories_stdout(host_path, memsql_id, dir_kind)
        if not content:
            continue
        parsed = parse_du_hca_stdout(content)
        total = int(parsed.get("total_bytes") or 0)
        if not total and parsed.get("paths"):
            # Use largest path entry as fallback (top-level dir line)
            total = max(parsed["paths"].values())
        out[bucket] = total
    return out


def _pct(part: int, whole: int) -> float:
    return round((part / whole) * 100, 2) if whole > 0 else 0.0


def _bucket_entry(bytes_val: int, used_disk: int) -> dict[str, Any]:
    return {
        "bytes": bytes_val,
        "gb": round(bytes_val / (1024**3), 2),
        "pct_of_used_disk": _pct(bytes_val, used_disk),
    }


def resolve_cluster_overhead_buckets(report: dict) -> dict[str, Any]:
    """
    ENH-1: Build CLUSTER OVERHEAD parent with named child buckets.

    Keeps a top-level ``total_bytes`` compatible with legacy single-value consumers.
    """
    from parsers import resolve_database_disk_usage

    nodes = report.get("nodes") or []
    database_disk_usage = resolve_database_disk_usage(report)
    attributed_table_bytes = _sum_database_disk_bytes(database_disk_usage)

    used_disk_bytes = sum(_node_data_mount_used_bytes(n) for n in nodes if isinstance(n, dict))
    if used_disk_bytes <= 0:
        overview = report.get("cluster_overview") or {}
        for nd in overview.get("nodes_detail") or []:
            if not isinstance(nd, dict):
                continue
            total_mb = float(nd.get("total_disk_mb") or 0)
            avail_mb = float(nd.get("available_disk_mb") or 0)
            if total_mb > 0:
                used_disk_bytes += int((total_mb - avail_mb) * 1024 * 1024)

    overhead_total = max(0, used_disk_bytes - attributed_table_bytes)

    # Aggregate per-node filesystem buckets
    agg = {k: 0 for k in ["transaction_logs", "logs", "snapshots", "spill", "tracelogs", "plancache", "auditlogs", "blobs", "cores"]}
    nodes_with_du = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        buckets = _extract_node_non_table_buckets(node)
        if any(buckets.values()):
            nodes_with_du += 1
        for k in agg:
            agg[k] += int(buckets.get(k) or 0)
    # Ensure logs (deprecated) is same as transaction_logs
    agg["logs"] = agg["transaction_logs"]

    blobs_delta = report.get("blobs_referenced_delta") or resolve_blobs_referenced_delta(report)
    # Only trust delta when status is ok — never treat full on-disk blobs as unreferenced
    # (that falsely trips reclamationStalled). Keep on-disk size as a separate scalar.
    unreferenced_blobs = 0
    if blobs_delta.get("status") == "ok":
        unreferenced_blobs = int((blobs_delta.get("cluster") or {}).get("delta_bytes") or 0)
    on_disk_blobs = int(agg["blobs"] or 0)

    referenced_non_table = (
        agg["transaction_logs"] + agg["snapshots"] + agg["spill"]
        + agg["tracelogs"] + agg["plancache"] + agg["auditlogs"] + agg["cores"]
    )

    children_sum = referenced_non_table + unreferenced_blobs
    other_overhead = max(0, overhead_total - children_sum)

    # Leaf buckets only — no deprecated `logs` alias and no rollup `referenced_non_table`
    # (those double-count in % displays / treemap children).
    children: dict[str, Any] = {
        "transaction_logs": _bucket_entry(agg["transaction_logs"], used_disk_bytes),
        "snapshots": _bucket_entry(agg["snapshots"], used_disk_bytes),
        "tracelogs": _bucket_entry(agg["tracelogs"], used_disk_bytes),
        "plancache": _bucket_entry(agg["plancache"], used_disk_bytes),
        "auditlogs": _bucket_entry(agg["auditlogs"], used_disk_bytes),
        "spill": _bucket_entry(agg["spill"], used_disk_bytes),
        "cores": _bucket_entry(agg["cores"], used_disk_bytes),
        "unreferenced_blobs": _bucket_entry(unreferenced_blobs, used_disk_bytes),
    }
    if other_overhead > 0:
        children["other_overhead"] = _bucket_entry(other_overhead, used_disk_bytes)

    return {
        "total_bytes": overhead_total,
        "pct_of_used_disk": _pct(overhead_total, used_disk_bytes),
        "used_disk_bytes": used_disk_bytes,
        "attributed_table_bytes": attributed_table_bytes,
        "nodes_with_du_data": nodes_with_du,
        "children": children,
        "referenced_non_table_bytes": referenced_non_table,
        "unreferenced_blobs_bytes": unreferenced_blobs,
        "on_disk_blobs_bytes": on_disk_blobs,
    }


def build_disk_intelligence(overhead: dict, blobs_delta: dict) -> dict[str, Any]:
    """Build the presentation payload from persisted normalized disk signals."""
    # ENH-5 completeness flags
    incomplete_nodes = list(set(blobs_delta.get("incomplete_nodes") or []))
    ha_adjusted = int(blobs_delta.get("ha_factor") or 1) > 1
    # HA-adjusted referenced bytes are an estimate — flag them the same as incomplete data.
    is_estimate = bool(incomplete_nodes) or ha_adjusted

    # Placeholder for per_database and remediation_hints
    per_database_stubs = {}
    remediation_hints = []

    return {
        "summary": {
            "total_used_bytes": overhead.get("used_disk_bytes") or 0,
            "attributed_table_bytes": overhead.get("attributed_table_bytes") or 0,
            "overhead_bytes": overhead.get("total_bytes") or 0,
            "overhead_pct": overhead.get("pct_of_used_disk") or 0.0,
            "is_estimate": is_estimate,
            "ha_adjusted": ha_adjusted,
            "incomplete_nodes": incomplete_nodes,
        },
        "cluster_overhead": overhead.get("children", {}),
        "per_node": blobs_delta.get("per_node", []),
        "per_database": per_database_stubs,
        "remediation_hints": remediation_hints,
    }


def resolve_disk_reclamation(report: dict) -> dict[str, Any]:
    """Compute ENH-2 delta then ENH-1 overhead buckets."""
    blobs_delta = resolve_blobs_referenced_delta(report)
    enriched = dict(report)
    enriched["blobs_referenced_delta"] = blobs_delta
    overhead = resolve_cluster_overhead_buckets(enriched)

    return {
        "disk_intelligence": build_disk_intelligence(overhead, blobs_delta),
        "blobs_referenced_delta": blobs_delta,
        "cluster_overhead": overhead,
    }
