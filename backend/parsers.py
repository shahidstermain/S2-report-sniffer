"""
Enhanced parsers for SingleStore diagnostic report tar.gz bundles.
Walks the extracted directory tree and normalizes data into a queryable model.
Implements schema-grounded intelligence with doc-linked recommendations.
"""
import json
import re
import os
import gzip
import tarfile
import zipfile
import tempfile
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

# Safety limits to prevent memory exhaustion
MAX_RAW_LOGS = 50000  # Cap log accumulation during parsing

NODE_DIR_PATTERN = re.compile(r'^(.+?)-(MA|CA|LEAF|AGGREGATOR|MASTER)$')
LOG_LINE_PATTERN = re.compile(
    r'(\d+)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+(INFO|WARN|WARNING|ERROR|FATAL|NOTICE|DEBUG):\s*(.*)',
    re.DOTALL
)

# ─── Critical log patterns for auto-detection ──────────────────────
CRITICAL_LOG_PATTERNS = [
    {"pattern": re.compile(r'(out of memory|OOM|killed process)', re.I), "category": "oom",
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
    {"pattern": re.compile(r'(lock wait timeout|lock timeout exceeded)', re.I), "category": "locking",
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
    {"pattern": re.compile(r'(compilation failed|compilation error)', re.I), "category": "compilation",
     "title": "Query Compilation Issue", "severity": "warning",
     "conclusion": "Issues with query compilation. Review query complexity and aggregator memory.",
     "doc_link": "https://docs.singlestore.com/db/v9.0/troubleshooting/query-performance/"},
    {"pattern": re.compile(r'(backup failed|backup error)', re.I), "category": "backup",
     "title": "Backup Failure", "severity": "critical",
     "conclusion": "A database backup operation failed. Check backup destination availability and permissions.",
     "doc_link": "https://docs.singlestore.com/db/v9.0/user-and-cluster-administration/cluster-management/backup-and-restore/"},
]

DMESG_PATTERNS = [
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


def _normalize_archive_exception(exc: Exception, archive_path: str) -> Exception:
    message = str(exc).lower()
    archive_name = os.path.basename(archive_path)
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


def _extract_tar_members(tf: tarfile.TarFile, extract_dir: str) -> None:
    extract_root = os.path.realpath(extract_dir)
    for member in tf:
        target_path = os.path.realpath(os.path.join(extract_dir, member.name))
        if (
            member.name.startswith('/')
            or '..' in Path(member.name).parts
            or os.path.commonpath([extract_root, target_path]) != extract_root
            or member.issym()
            or member.islnk()
            or member.isdev()
        ):
            continue
        tf.extract(member, extract_dir, set_attrs=False)


def _extract_gzip_payload(archive_path: str, extract_dir: str) -> None:
    output_name = os.path.basename(archive_path)[:-3] or "archive"
    output_path = os.path.join(extract_dir, output_name)
    with gzip.open(archive_path, 'rb') as src, open(output_path, 'wb') as dst:
        shutil.copyfileobj(src, dst)
    if tarfile.is_tarfile(output_path):
        nested_dir = os.path.join(extract_dir, "_nested")
        os.makedirs(nested_dir, exist_ok=True)
        with tarfile.open(output_path, 'r:') as tf:
            _extract_tar_members(tf, nested_dir)
        os.unlink(output_path)


def _extract_tar_gz_payload(archive_path: str, extract_dir: str) -> None:
    output_name = os.path.basename(archive_path)
    if output_name.endswith('.tar.gz'):
        output_name = output_name[:-3]
    elif output_name.endswith('.tgz'):
        output_name = output_name[:-4] + '.tar'
    else:
        output_name = f"{output_name}.tar"
    output_path = os.path.join(extract_dir, output_name or "archive.tar")
    with gzip.open(archive_path, 'rb') as src, open(output_path, 'wb') as dst:
        shutil.copyfileobj(src, dst)
    with tarfile.open(output_path, 'r:') as tf:
        _extract_tar_members(tf, extract_dir)
    os.unlink(output_path)


def parse_report_archive_streaming(archive_path: str, progress_callback=None) -> dict:
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
            except Exception:
                pass

    try:
        _progress("extracting", message="Decompressing archive...")

        if archive_path.endswith('.zip'):
            detected_format = "zip"
            with zipfile.ZipFile(archive_path, 'r') as zf:
                for name in zf.namelist():
                    if name.startswith('/') or '..' in name:
                        raise ValueError(f"Unsafe path in archive: {name}")
                    zf.extract(name, extract_dir)
        elif archive_path.endswith(('.tar.gz', '.tgz')):
            detected_format = "tar.gz"
            _extract_tar_gz_payload(archive_path, extract_dir)
        elif archive_path.endswith('.tar'):
            detected_format = "tar"
            with tarfile.open(archive_path, 'r:') as tf:
                _extract_tar_members(tf, extract_dir)
        elif archive_path.endswith('.gz'):
            detected_format = "gz"
            _extract_gzip_payload(archive_path, extract_dir)
        else:
            raise ValueError(f"Unsupported archive format: {os.path.basename(archive_path)}")

        for entry in os.listdir(extract_dir):
            fpath = os.path.join(extract_dir, entry)
            if os.path.isfile(fpath) and (entry.endswith('.tar.gz') or entry.endswith('.tgz')):
                nested_dir = os.path.join(extract_dir, "_nested")
                os.makedirs(nested_dir, exist_ok=True)
                try:
                    with tarfile.open(fpath, 'r:gz') as tf:
                        _extract_tar_members(tf, nested_dir)
                    os.unlink(fpath)
                except Exception as exc:
                    normalized = _normalize_archive_exception(exc, fpath)
                    if normalized is exc:
                        raise
                    raise normalized from exc
                break

        def _looks_like_report_root(dir_path: str) -> bool:
            try:
                if os.path.isdir(os.path.join(dir_path, "globalInfo")):
                    return True
                for child in os.listdir(dir_path):
                    cpath = os.path.join(dir_path, child)
                    if not os.path.isdir(cpath):
                        continue
                    if NODE_DIR_PATTERN.match(child):
                        return True
                    lower = child.lower()
                    if lower.endswith("-masteraggregator") or lower.endswith("-master-aggregator"):
                        return True
            except Exception:
                return False
            return False

        base_dir = extract_dir
        if "_nested" in os.listdir(extract_dir):
            nested_dir = os.path.join(extract_dir, "_nested")
            try:
                if os.listdir(nested_dir):
                    base_dir = nested_dir
            except Exception:
                pass

        report_root = base_dir
        for _ in range(10):
            try:
                entries = [e for e in os.listdir(report_root) if e not in {"_nested"}]
            except Exception:
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
        return result
    except Exception as exc:
        normalized = _normalize_archive_exception(exc, archive_path)
        if normalized is exc:
            raise
        raise normalized from exc
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


# Keep backward-compat alias
def parse_report_archive(archive_path: str) -> dict:
    return parse_report_archive_streaming(archive_path)


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
        "dmesg_events": [],
    }

    index_path = os.path.join(report_root, "index.json")
    if os.path.exists(index_path):
        try:
            with open(index_path) as f:
                result["index"] = json.load(f)
        except Exception:
            pass

    node_dirs = []
    for entry in sorted(os.listdir(report_root)):
        full_path = os.path.join(report_root, entry)
        if not os.path.isdir(full_path):
            continue
        if entry == "globalInfo":
            result["global_info"] = parse_global_info(full_path)
            continue
        m = NODE_DIR_PATTERN.match(entry)
        if m:
            node_dirs.append((full_path, m.group(1), m.group(2)))
            continue
        lower = entry.lower()
        if lower.endswith("-masteraggregator"):
            node_dirs.append((full_path, entry[: -len("-MasterAggregator")], "MA"))
        elif lower.endswith("-master-aggregator"):
            node_dirs.append((full_path, entry[: -len("-Master-Aggregator")], "MA"))

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
                     "rebalance_status",
                     "mv_processlist"]:
            if key not in centralized and node_info.get(key):
                centralized[key] = node_info[key]

        all_logs.extend(node_info.get("trace_logs", []))
        # Trim during collection to prevent unbounded memory growth
        if len(all_logs) > MAX_RAW_LOGS:
            all_logs = all_logs[-MAX_RAW_LOGS:]

    # Build cluster overview
    if centralized.get("mv_nodes"):
        result["cluster_overview"] = build_cluster_overview(centralized["mv_nodes"], result["nodes"])
    if centralized.get("cluster_topology"):
        result["cluster_overview"]["topology"] = centralized["cluster_topology"]
    if centralized.get("cluster_status"):
        result["cluster_overview"]["cluster_status"] = centralized["cluster_status"][:300]
    if centralized.get("blocked_queries"):
        result["cluster_overview"]["blocked_queries"] = centralized["blocked_queries"]
    if centralized.get("processlist"):
        result["cluster_overview"]["processlist"] = centralized["processlist"][:200]
    if centralized.get("mv_processlist"):
        result["cluster_overview"]["mv_processlist"] = centralized["mv_processlist"][:200]
    if centralized.get("rebalance_status"):
        result["cluster_overview"]["rebalance_status"] = centralized["rebalance_status"][:300]

    # Assign other data
    if centralized.get("databases_extended"):
        result["databases"] = centralized["databases_extended"]
    if centralized.get("mv_queries"):
        result["queries"] = centralized["mv_queries"][:500]
    if centralized.get("mv_events"):
        result["events"] = centralized["mv_events"]
    if centralized.get("pipelines_data"):
        result["pipelines"] = centralized["pipelines_data"]
    if centralized.get("workload_management"):
        result["workload_management"] = centralized["workload_management"]
    if centralized.get("replication_status"):
        result["replication_status"] = centralized["replication_status"]
    if centralized.get("table_statistics"):
        result["storage"] = centralized["table_statistics"]
    if centralized.get("resource_pools"):
        result["resource_pools"] = centralized["resource_pools"]
    if centralized.get("database_disk_usage"):
        result["database_disk_usage"] = centralized["database_disk_usage"]
    if centralized.get("partitions"):
        result["partitions"] = centralized["partitions"]
    if centralized.get("backup_history"):
        result["backup_history"] = centralized["backup_history"]
    if centralized.get("version_history"):
        result["version_history"] = centralized["version_history"]
    if centralized.get("availability_groups"):
        result["availability_groups"] = centralized["availability_groups"]
    if centralized.get("users"):
        result["users"] = centralized["users"]

    # Process logs
    all_logs.sort(key=lambda x: x.get("timestamp", ""))
    result["logs"] = all_logs[-5000:]
    result["log_summary"] = build_log_summary(all_logs)
    result["alloc_memory"] = build_alloc_memory_overview(result["nodes"])

    # Detect critical log patterns
    result["detected_log_patterns"] = detect_log_patterns(all_logs)

    # High-value diagnostic aggregates
    result["log_timeframe"] = extract_log_timeframe(result["nodes"])
    result["backup_summary"] = summarize_backup_history(result.get("backup_history", []))
    result["pressure_events_per_hour"] = compute_pressure_events_per_hour(all_logs)
    result["memory_pressure"] = summarize_memory_pressure(result["nodes"])
    cluster_status_rows = result.get("cluster_overview", {}).get("cluster_status", [])
    result["cluster_layout"] = summarize_cluster_layout(cluster_status_rows)
    processlist_rows = result.get("cluster_overview", {}).get("processlist", [])
    result["process_health"] = extract_process_health(processlist_rows)

    # Collect dmesg events across all nodes
    all_dmesg = []
    for node in result["nodes"]:
        all_dmesg.extend(node.get("dmesg_events", []))
    result["dmesg_events"] = all_dmesg

    # Build config health from all nodes
    result["config_health"] = build_config_health(result["nodes"])

    # Generate recommendations
    result["recommendations"] = generate_recommendations(result)

    # Clean up heavy internal fields
    for node in result["nodes"]:
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
    }

    # System commands
    node["metrics"]["memory"] = parse_free(node_path)
    node["metrics"]["disk"] = parse_df(node_path)
    node["metrics"]["uptime"] = parse_uptime(node_path)
    node["metrics"]["cpu_info"] = parse_cpu_info(node_path)
    node["metrics"]["top"] = parse_top(node_path)
    node["metrics"]["psutil"] = parse_json_file(node_path, "psutil.json")
    node["metrics"]["node_disk_usage"] = parse_json_file(node_path, "nodeDirectoriesDiskUsage.json")
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
    node["os_checks"]["numa"] = parse_numa(node_path)
    node["os_checks"]["security_limits"] = parse_security_limits(node_path)

    # Dmesg
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
    node["database_status"] = parse_sdb_json_table(node_path, "showDatabaseStatus.json")
    node["license"] = parse_license(node_path)

    # Show variables for version + key vars
    show_vars = parse_json_file(node_path, "showVariables.json")
    node["show_variables"] = {}
    if show_vars and isinstance(show_vars, list) and show_vars:
        item = show_vars[0]
        if isinstance(item, dict) and "rows" in item:
            for row in item["rows"]:
                vname = row.get("Variable_name", "")
                vval = row.get("Value", "")
                if vname == "memsql_version":
                    node["version"] = vval
                if vname in ["memsql_version", "maximum_memory", "maximum_table_memory",
                             "default_partitions_per_leaf", "redundancy_level", "sql_mode",
                             "character_set_server", "maximum_columnstore_alter_memory",
                             "columnstore_disk_insert_threshold", "snapshots_to_keep",
                             "load_data_mem_limit", "background_merger_threads"]:
                    node["show_variables"][vname] = vval
            if item.get("MemsqlID"):
                node["memsql_id"] = item["MemsqlID"]

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
    result = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 6:
            use_pct_str = parts[4].replace('%', '')
            iuse_pct_str = parts[5].replace('%', '') if len(parts) > 5 and '%' in parts[5] else "0"
            mounted_on = parts[-1] if len(parts) > 5 else parts[5]
            if parts[5].endswith('%'):
                mounted_on = parts[6] if len(parts) > 6 else parts[5]
            result.append({
                "filesystem": parts[0], "size": parts[1], "used": parts[2],
                "avail": parts[3], "use_pct": safe_int(use_pct_str),
                "iuse_pct": safe_int(iuse_pct_str), "mounted_on": mounted_on,
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
            except Exception:
                pass
    result["status"] = "disabled" if result.get("active") == "never" else "enabled"
    return result


def parse_sysctl_checks(node_path: str) -> dict:
    content = read_stdout(node_path, "sysctl")
    if not content:
        return {}
    checks = {}
    key_params = {
        "vm.max_map_count": {"min": 1000000, "severity": "critical"},
        "vm.swappiness": {"max": 1, "severity": "warning"},
        "net.core.somaxconn": {"min": 1024, "severity": "warning"},
        "vm.overcommit_memory": {"info": True},
        "vm.overcommit_ratio": {"info": True},
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
            except Exception:
                pass
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
            except Exception:
                pass
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
                except Exception:
                    pass
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
                for line in open(fpath):
                    stripped = line.strip()
                    if stripped:
                        lines.append({"line": stripped[:500], "source": f})
            except Exception:
                pass
    return lines[-200:]


def classify_dmesg_events(raw_lines: list, hostname: str, role: str) -> list:
    events = []
    for item in raw_lines:
        line = item["line"]
        for pat in DMESG_PATTERNS:
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


def parse_mv_sysinfo(node_path: str) -> dict:
    data = parse_json_file(node_path, "informationSchemaMvSysinfo.json")
    if not data or not isinstance(data, dict):
        return {}
    result = {}
    for key in ["MV_SYSINFO_CPU", "MV_SYSINFO_MEM", "MV_SYSINFO_DISK", "MV_SYSINFO_NET", "MV_SYSINFO_CPULIST"]:
        val = data.get(key)
        if isinstance(val, dict) and "rows" in val:
            result[key] = val["rows"]
        elif isinstance(val, list):
            result[key] = val
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


def infer_deployment_method(nodes: list, cluster_overview: dict) -> dict:
    signals = []
    method = "Linux (sdb-deploy)"
    confidence = "low"

    for node in nodes or []:
        hostname = (node.get("hostname") or "").lower()
        if "helios" in hostname:
            method = "Helios Cloud Portal"
            confidence = "high"
            signals.append("hostname:helios")
            break

    if method == "Linux (sdb-deploy)":
        for node in nodes or []:
            for proc in (node.get("metrics", {}) or {}).get("ps", []) or []:
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
                    result[dbname] = {
                        "columns": dbval.get("columns", []),
                        "partitions": dbval["rows"],
                        "count": len(dbval["rows"]),
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
    return rows


# ─── SingleStore JSON parsers ───────────────────────────────────────

def parse_json_file(node_path: str, filename: str):
    fpath = os.path.join(node_path, filename)
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath) as f:
            return json.load(f)
    except Exception:
        return None


def parse_sdb_json_table(node_path: str, filename: str) -> list:
    data = parse_json_file(node_path, filename)
    if not data:
        return []
    if isinstance(data, list):
        rows = []
        for item in data:
            if isinstance(item, dict) and "rows" in item:
                rows.extend(item["rows"])
        return rows
    if isinstance(data, dict):
        if isinstance(data.get("rows"), list):
            return data["rows"]
        rows = []
        for key, val in data.items():
            if isinstance(val, dict) and "rows" in val:
                rows.extend(val["rows"])
            elif isinstance(val, dict):
                for subkey, subval in val.items():
                    if isinstance(subval, dict) and "rows" in subval:
                        rows.extend(subval["rows"])
        return rows
    return []


def parse_cluster_topology(node_path: str) -> dict:
    data = parse_json_file(node_path, "clusterTopology.json")
    if not data or not isinstance(data, dict):
        return {}
    result = {"leaves": [], "aggregators": []}
    for memsql_id, val in data.items():
        if isinstance(val, dict):
            if "ShowLeaves" in val and isinstance(val["ShowLeaves"], dict):
                if "rows" in val["ShowLeaves"]:
                    result["leaves"] = val["ShowLeaves"]["rows"]
            if "ShowAggregators" in val and isinstance(val["ShowAggregators"], dict):
                if "rows" in val["ShowAggregators"]:
                    result["aggregators"] = val["ShowAggregators"]["rows"]
    return result


def parse_pipelines(node_path: str) -> list:
    data = parse_json_file(node_path, "informationSchemaPipelines.json")
    if not data:
        return []
    rows = []
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                if "Pipelines" in val and isinstance(val["Pipelines"], dict):
                    if "rows" in val["Pipelines"]:
                        rows.extend(val["Pipelines"]["rows"])
                elif "rows" in val:
                    rows.extend(val["rows"])
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "rows" in item:
                rows.extend(item["rows"])
    return rows


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

def parse_trace_logs(node_path: str, hostname: str, role: str) -> list:
    logs_dir = os.path.join(node_path, "memsqlTracelogs")
    if not os.path.isdir(logs_dir):
        return []
    entries = []
    for f in sorted(os.listdir(logs_dir)):
        fpath = os.path.join(logs_dir, f)
        if not os.path.isfile(fpath):
            continue
        if '_memsql.log' not in f and '_memsql.log.' not in f:
            continue
        try:
            if f.endswith('.gz'):
                with gzip.open(fpath, 'rt', errors='replace') as fh:
                    entries.extend(_parse_log_lines(fh, hostname, role, f, 500))
            else:
                with open(fpath, errors='replace') as fh:
                    entries.extend(_parse_log_lines(fh, hostname, role, f, 2000))
        except Exception:
            pass
    return entries


def _parse_log_lines(fh, hostname, role, filename, max_lines=2000):
    entries = []
    count = 0
    for line in fh:
        if count >= max_lines:
            break
        m = LOG_LINE_PATTERN.match(line.strip())
        if m:
            severity = m.group(3)
            if severity == "WARNING":
                severity = "WARN"
            entries.append({
                "timestamp": m.group(2).strip(),
                "severity": severity,
                "message": m.group(4).strip()[:1000],
                "hostname": hostname, "role": role, "source": filename,
            })
            count += 1
    return entries


def detect_log_patterns(all_logs: list) -> list:
    """Detect critical patterns in log messages."""
    detected = defaultdict(lambda: {"count": 0, "first_seen": "", "last_seen": "", "sample": "", "nodes": set()})
    for log in all_logs:
        msg = log.get("message", "")
        for pat in CRITICAL_LOG_PATTERNS:
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
            if not node_ranges[hostname]["first"] or ts < node_ranges[hostname]["first"]:
                node_ranges[hostname]["first"] = ts
            if not node_ranges[hostname]["last"] or ts > node_ranges[hostname]["last"]:
                node_ranges[hostname]["last"] = ts

        if len(ts) >= 13:
            hourly_counts[ts[:13]][sev] += 1

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

_PRESSURE_PATTERNS = {
    "etimedout": re.compile(r'ETIMEDOUT|Connection timed out', re.I),
    "fsync_behind": re.compile(r'fsync is behind|slow fsync', re.I),
    "retry_stall": re.compile(r'Retry loop is stalling|stalling retry loop', re.I),
}


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
                first_ts = first_ts or min(ts_list)
                last_ts = last_ts or max(ts_list)
                if first_ts > min(ts_list):
                    first_ts = min(ts_list)
                if last_ts < max(ts_list):
                    last_ts = max(ts_list)
        coverage_hours: float = 0.0
        if first_ts and last_ts:
            try:
                fmt = "%Y-%m-%d %H:%M:%S.%f"
                dt_first = datetime.strptime(first_ts[:26], fmt)
                dt_last = datetime.strptime(last_ts[:26], fmt)
                coverage_hours = round((dt_last - dt_first).total_seconds() / 3600, 2)
            except Exception:
                pass
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
        def _row_ts(r):
            return str(r.get("END_TIMESTAMP") or r.get("START_TIMESTAMP") or "")
        best = max(successful_rows, key=_row_ts)
        latest_ts = _row_ts(best)
        start = str(best.get("START_TIMESTAMP", ""))
        end = str(best.get("END_TIMESTAMP", ""))
        if start and end:
            try:
                fmt = "%Y-%m-%d %H:%M:%S"
                dt_s = datetime.strptime(start[:19], fmt)
                dt_e = datetime.strptime(end[:19], fmt)
                latest_duration = round((dt_e - dt_s).total_seconds(), 1)
            except Exception:
                pass
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
    counts: dict = {k: defaultdict(int) for k in _PRESSURE_PATTERNS}
    for entry in all_logs:
        msg = entry.get("message", "")
        ts = entry.get("timestamp", "")
        hour_bucket = ts[:13] if len(ts) >= 13 else ts
        for key, pat in _PRESSURE_PATTERNS.items():
            if pat.search(msg):
                counts[key][hour_bucket] += 1
    return {k: dict(v) for k, v in counts.items()}


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
    """Summarise partition distribution by role and host from SHOW CLUSTER STATUS.

    Returns::

        {
            "by_host": {hostname: {"master": N, "slave": N, "total": N}},
            "by_role": {"master": N, "slave": N},
            "total_partitions": N,
        }
    """
    by_host: dict = defaultdict(lambda: {"master": 0, "slave": 0, "total": 0})
    by_role: dict = {"master": 0, "slave": 0}
    for row in cluster_status:
        host = str(row.get("Host", row.get("HOST", row.get("MasterHost", ""))))
        role = str(row.get("Role", row.get("ROLE", row.get("Ordinal", "")))).lower()
        is_master = role in ("master", "0", "primary")
        key = "master" if is_master else "slave"
        by_host[host][key] += 1
        by_host[host]["total"] += 1
        by_role[key] += 1
    return {
        "by_host": {h: dict(v) for h, v in by_host.items()},
        "by_role": by_role,
        "total_partitions": by_role["master"] + by_role["slave"],
    }


def extract_process_health(processlist: list) -> dict:
    """Identify non-sleeping queries and sleeping open transactions.

    Returns::

        {
            "active_queries": [row, ...],
            "sleeping_open_transactions": [row, ...],
            "active_count": N,
            "sleeping_open_tx_count": N,
        }
    """
    active: list = []
    sleeping_tx: list = []
    for row in processlist:
        cmd = str(row.get("Command", row.get("COMMAND", ""))).strip().lower()
        info = str(row.get("Info", row.get("QUERY_TEXT", row.get("info", "")))).strip()
        trx_state = str(
            row.get("TRX_STATE", row.get("trx_state", row.get("Transaction_State", "")))
        ).strip().lower()
        time_val = row.get("Time", row.get("ELAPSED_TIME_S", 0))
        try:
            time_sec = float(time_val)
        except (TypeError, ValueError):
            time_sec = 0.0
        if cmd != "sleep":
            active.append(row)
        elif cmd == "sleep" and trx_state in ("running", "active", "open"):
            sleeping_tx.append(row)
        elif cmd == "sleep" and time_sec > 30 and info and info.upper() != "NULL":
            sleeping_tx.append(row)
    return {
        "active_queries": active,
        "sleeping_open_transactions": sleeping_tx,
        "active_count": len(active),
        "sleeping_open_tx_count": len(sleeping_tx),
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
        node_type = (node.get("TYPE") or node.get("type") or node.get("Role") or node.get("ROLE") or "").upper()
        if node_type == "LEAF":
            overview["leaves"] += 1
        elif node_type in ("CA", "MA", "AGGREGATOR", "MASTER"):
            overview["aggregators"] += 1
        state = str(node.get("STATE") or node.get("State") or node.get("state") or "").lower()
        if state == "online":
            overview["online_nodes"] += 1
        else:
            overview["offline_nodes"] += 1
        overview["total_memory_mb"] += safe_int(node.get("MAX_MEMORY_MB", 0))
        overview["used_memory_mb"] += safe_int(node.get("MEMORY_USED_MB", 0))
        overview["total_disk_mb"] += safe_int(node.get("TOTAL_DATA_DISK_MB", 0))
        overview["available_disk_mb"] += safe_int(node.get("AVAILABLE_DATA_DISK_MB", 0))
        overview["total_cpus"] += safe_int(node.get("NUM_CPUS", 0))
        version = node.get("VERSION") or node.get("Version") or node.get("version")
        if not overview["version"] and version:
            overview["version"] = version
        ag = node.get("AVAILABILITY_GROUP", "") or node.get("AvailabilityGroup", "") or node.get("availability_group", "")
        if ag and ag != "NULL":
            overview["availability_groups"].add(ag)
        overview["nodes_detail"].append({
            "id": node.get("ID", "") or node.get("NodeId", "") or node.get("node_id", ""),
            "ip_addr": node.get("IP_ADDR", "") or node.get("IpAddr", "") or node.get("ip_addr", ""),
            "port": node.get("PORT", "") or node.get("Port", "") or node.get("port", ""),
            "type": node.get("TYPE", "") or node.get("Role", "") or node.get("role", ""),
            "state": node.get("STATE", "") or node.get("State", "") or node.get("state", ""),
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
    overview["availability_groups"] = sorted(list(overview["availability_groups"]))
    if overview["total_disk_mb"] > 0:
        used_disk = overview["total_disk_mb"] - overview["available_disk_mb"]
        overview["disk_used_pct"] = round(used_disk / overview["total_disk_mb"] * 100, 1)
    if overview["total_memory_mb"] > 0:
        overview["memory_used_pct"] = round(overview["used_memory_mb"] / overview["total_memory_mb"] * 100, 1)
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
    low_nofile = {h: v for h, v in process_limits_checks.items() if 0 < v < 100000}
    health["os_checks"].append({
        "name": "Open Files Limit (nofile)",
        "status": "fail" if low_nofile else "pass",
        "severity": "critical" if low_nofile else "pass",
        "detail": f"Low nofile on: {', '.join(f'{h}={v}' for h,v in low_nofile.items())}" if low_nofile else "nofile >= 100,000 on all nodes",
        "doc_link": "https://docs.singlestore.com/db/v9.0/setup/before-you-start/system-requirements/",
        "remediation": 'Add "memsql soft nofile 1000000" and "memsql hard nofile 1000000" to /etc/security/limits.conf and restart memsqld.'
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
    except Exception:
        pass

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

    # RULE-04: Replication lag
    repl = report.get("replication_status", [])
    # (Check if any lag data is available)

    # RULE-05: OOM kill in dmesg or logs
    for evt in report.get("dmesg_events", []):
        if evt["category"] == "oom":
            add_rec(
                severity="critical", category="Memory",
                title=f"OOM kill detected on {evt['hostname']}",
                description=evt["conclusion"],
                evidence=evt["line"][:200],
                remediation="1) Review maximum_memory setting vs. actual RAM. 2) Check for memory-heavy queries in MV_PLANCACHE. 3) Increase RAM or reduce maximum_memory. 4) Set vm.overcommit_memory=2 in sysctl.",
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
    # Already handled above via CRITICAL_LOG_PATTERNS

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
            except Exception:
                pass
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


# ─── Utilities ──────────────────────────────────────────────────────

def read_stdout(node_path, collector_name):
    dir_path = os.path.join(node_path, collector_name)
    if not os.path.isdir(dir_path):
        return ""
    for f in os.listdir(dir_path):
        if f.endswith('_stdout') or f == 'stdout':
            try:
                # Limit read to 100KB to prevent memory issues
                with open(os.path.join(dir_path, f)) as fh:
                    return fh.read(102400)
            except Exception:
                pass
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
            except Exception:
                pass
    return ""


def parse_global_info(global_path):
    result = {}
    for f in os.listdir(global_path):
        fpath = os.path.join(global_path, f)
        if os.path.isfile(fpath) and f.endswith('.json'):
            try:
                result[f.replace('.json', '')] = json.load(open(fpath))
            except Exception:
                pass
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
