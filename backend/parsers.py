"""
Parsers for SingleStore diagnostic report tar.gz bundles.
Walks the extracted directory tree and normalizes data into a queryable model.
"""
import json
import re
import os
import gzip
import tarfile
import tempfile
import shutil
import logging
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

# ─── File type recognition ─────────────────────────────────────────────

NODE_DIR_PATTERN = re.compile(r'^(.+?)-(MA|CA|LEAF|AGGREGATOR|MASTER)$')

LOG_LINE_PATTERN = re.compile(
    r'(\d+)\s+'                        # sequence number
    r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+'  # timestamp
    r'(INFO|WARN|WARNING|ERROR|FATAL|NOTICE|DEBUG):\s*'   # severity
    r'(.*)',                            # message
    re.DOTALL
)

def parse_report_archive(archive_path: str) -> dict:
    """Main entry point: extract tar.gz and parse everything."""
    extract_dir = tempfile.mkdtemp(prefix="sdb_report_")
    try:
        with tarfile.open(archive_path, 'r:gz') as tf:
            # Security: prevent path traversal
            for member in tf.getmembers():
                if member.name.startswith('/') or '..' in member.name:
                    raise ValueError(f"Unsafe path in archive: {member.name}")
            tf.extractall(extract_dir)

        # Find the report root (first directory inside extract)
        contents = os.listdir(extract_dir)
        if len(contents) == 1 and os.path.isdir(os.path.join(extract_dir, contents[0])):
            report_root = os.path.join(extract_dir, contents[0])
            report_name = contents[0]
        else:
            report_root = extract_dir
            report_name = os.path.basename(archive_path)

        return parse_report_directory(report_root, report_name)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def parse_report_directory(report_root: str, report_name: str) -> dict:
    """Parse an extracted report directory."""
    result = {
        "report_name": report_name,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
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
        "workload_management": [],
        "replication_status": [],
        "checks": [],
        "raw_node_count": 0,
    }

    # Parse index.json if present
    index_path = os.path.join(report_root, "index.json")
    if os.path.exists(index_path):
        try:
            with open(index_path) as f:
                result["index"] = json.load(f)
        except Exception:
            pass

    # Walk top-level directories
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

    result["raw_node_count"] = len(node_dirs)

    # Parse each node directory
    all_logs = []
    mv_nodes_data = None
    cluster_topology_data = None
    cluster_status_data = None
    databases_data = None
    queries_data = None
    events_data = None
    pipelines_data = None
    blocked_queries_data = None
    workload_mgmt_data = None
    replication_data = None
    table_statistics_data = None
    processlist_data = None

    for node_path, hostname, role in node_dirs:
        node_info = parse_node_directory(node_path, hostname, role)
        result["nodes"].append(node_info)

        # Collect centralized data from first node that has it (usually MA)
        if node_info.get("mv_nodes") and not mv_nodes_data:
            mv_nodes_data = node_info["mv_nodes"]
        if node_info.get("cluster_topology") and not cluster_topology_data:
            cluster_topology_data = node_info["cluster_topology"]
        if node_info.get("cluster_status") and not cluster_status_data:
            cluster_status_data = node_info["cluster_status"]
        if node_info.get("databases_extended") and not databases_data:
            databases_data = node_info["databases_extended"]
        if node_info.get("mv_queries") and not queries_data:
            queries_data = node_info["mv_queries"]
        if node_info.get("mv_events") and not events_data:
            events_data = node_info["mv_events"]
        if node_info.get("pipelines") and not pipelines_data:
            pipelines_data = node_info["pipelines"]
        if node_info.get("blocked_queries") and not blocked_queries_data:
            blocked_queries_data = node_info["blocked_queries"]
        if node_info.get("workload_management") and not workload_mgmt_data:
            workload_mgmt_data = node_info["workload_management"]
        if node_info.get("replication_status") and not replication_data:
            replication_data = node_info["replication_status"]
        if node_info.get("table_statistics") and not table_statistics_data:
            table_statistics_data = node_info["table_statistics"]
        if node_info.get("processlist") and not processlist_data:
            processlist_data = node_info["processlist"]

        # Collect logs
        all_logs.extend(node_info.get("trace_logs", []))

    # Build cluster overview from MV_NODES
    if mv_nodes_data:
        result["cluster_overview"] = build_cluster_overview(mv_nodes_data, result["nodes"])

    if cluster_topology_data:
        result["cluster_overview"]["topology"] = cluster_topology_data

    if cluster_status_data:
        result["cluster_overview"]["cluster_status"] = cluster_status_data

    # Process databases
    if databases_data:
        result["databases"] = databases_data

    # Process queries
    if queries_data:
        result["queries"] = queries_data[:500]  # Limit

    if events_data:
        result["events"] = events_data

    if pipelines_data:
        result["pipelines"] = pipelines_data

    if blocked_queries_data:
        result["cluster_overview"]["blocked_queries"] = blocked_queries_data

    if workload_mgmt_data:
        result["workload_management"] = workload_mgmt_data

    if replication_data:
        result["replication_status"] = replication_data

    if table_statistics_data:
        result["storage"] = table_statistics_data

    if processlist_data:
        result["cluster_overview"]["processlist"] = processlist_data[:200]

    # Process logs - sort by timestamp, keep manageable size
    all_logs.sort(key=lambda x: x.get("timestamp", ""))
    result["logs"] = all_logs[-5000:]  # Keep last 5000 log entries
    result["log_summary"] = build_log_summary(all_logs)

    # Generate recommendations
    result["recommendations"] = generate_recommendations(result)

    # Remove heavy internal fields from nodes before storing
    for node in result["nodes"]:
        node.pop("trace_logs", None)
        node.pop("mv_nodes", None)
        node.pop("cluster_topology", None)
        node.pop("cluster_status", None)
        node.pop("databases_extended", None)
        node.pop("mv_queries", None)
        node.pop("mv_events", None)
        node.pop("pipelines", None)
        node.pop("blocked_queries", None)
        node.pop("workload_management", None)
        node.pop("replication_status", None)
        node.pop("table_statistics", None)
        node.pop("processlist", None)

    return result


def parse_node_directory(node_path: str, hostname: str, role: str) -> dict:
    """Parse all collectors in a node directory."""
    node = {
        "hostname": hostname,
        "role": role,
        "metrics": {},
        "config": {},
        "version": None,
        "memsql_id": None,
    }

    # Parse system commands
    node["metrics"]["memory"] = parse_free(node_path)
    node["metrics"]["disk"] = parse_df(node_path)
    node["metrics"]["uptime"] = parse_uptime(node_path)
    node["metrics"]["cpu_info"] = parse_cpu_info(node_path)
    node["metrics"]["top"] = parse_top(node_path)

    # Parse SingleStore JSON data
    node["config"]["memsql_config"] = parse_json_file(node_path, "memsqlConfig.json")
    node["config"]["memsqlctl_info"] = parse_json_file(node_path, "memsqlctlInfo.json")
    node["config"]["ulimit"] = parse_ulimit(node_path)
    node["config"]["numa"] = parse_numa(node_path)
    node["config"]["transparent_hugepage"] = parse_text_file(node_path, "transparentHugepage")
    node["config"]["sysctl"] = parse_text_file(node_path, "sysctl")
    node["config"]["process_limits"] = parse_json_file(node_path, "memsqldProcessLimits.json")
    node["config"]["os_release"] = parse_text_file(node_path, "osRelease")
    node["config"]["security_limits"] = parse_text_file(node_path, "securityLimits")

    node["metrics"]["node_disk_usage"] = parse_json_file(node_path, "nodeDirectoriesDiskUsage.json")
    node["metrics"]["psutil"] = parse_json_file(node_path, "psutil.json")
    node["metrics"]["lsblk"] = parse_text_file(node_path, "lsblk")
    node["metrics"]["network"] = {
        "ifconfig": parse_text_file(node_path, "ifconfig"),
        "ip_addr": parse_text_file(node_path, "ipAddr"),
        "netstat": parse_text_file(node_path, "netstat"),
    }
    node["metrics"]["dmesg"] = parse_dmesg(node_path)

    # Parse MV_NODES (cluster-wide, usually from MA)
    node["mv_nodes"] = parse_sdb_json_table(node_path, "informationSchemaMvNodes.json")
    node["cluster_topology"] = parse_cluster_topology(node_path)
    node["cluster_status"] = parse_sdb_json_table(node_path, "showClusterStatus.json")
    node["databases_extended"] = parse_sdb_json_table(node_path, "showDatabasesExtended.json")
    node["mv_queries"] = parse_sdb_json_table(node_path, "informationSchemaMvQueries.json")
    node["mv_events"] = parse_sdb_json_table(node_path, "informationSchemaMvEvents.json")
    node["pipelines"] = parse_pipelines(node_path)
    node["blocked_queries"] = parse_sdb_json_table(node_path, "informationSchemaMvBlockedQueries.json")
    node["workload_management"] = parse_sdb_json_table(node_path, "showWorkloadManagementStatus.json")
    node["replication_status"] = parse_sdb_json_table(node_path, "showReplicationStatus.json")
    node["table_statistics"] = parse_sdb_json_table(node_path, "informationSchemaTableStatistics.json")
    node["processlist"] = parse_sdb_json_table(node_path, "informationSchemaProcesslist.json")

    # Parse show variables for version
    show_vars = parse_json_file(node_path, "showVariables.json")
    if show_vars and isinstance(show_vars, list) and len(show_vars) > 0:
        item = show_vars[0] if isinstance(show_vars, list) else show_vars
        if isinstance(item, dict) and "rows" in item:
            for row in item["rows"]:
                vname = row.get("Variable_name", "")
                if vname == "memsql_version":
                    node["version"] = row.get("Value", "")
            if item.get("MemsqlID"):
                node["memsql_id"] = item["MemsqlID"]

    # Parse database status
    node["database_status"] = parse_sdb_json_table(node_path, "showDatabaseStatus.json")

    # Parse trace logs
    node["trace_logs"] = parse_trace_logs(node_path, hostname, role)

    return node


# ─── System command parsers ─────────────────────────────────────────

def parse_free(node_path: str) -> dict:
    """Parse free -m output."""
    content = read_stdout(node_path, "free")
    if not content:
        return {}
    result = {}
    for line in content.strip().split('\n'):
        parts = line.split()
        if len(parts) >= 4 and parts[0] == 'Mem:':
            result = {
                "total_mb": safe_int(parts[1]),
                "used_mb": safe_int(parts[2]),
                "free_mb": safe_int(parts[3]),
                "shared_mb": safe_int(parts[4]) if len(parts) > 4 else 0,
                "buff_cache_mb": safe_int(parts[5]) if len(parts) > 5 else 0,
                "available_mb": safe_int(parts[6]) if len(parts) > 6 else 0,
            }
            if result["total_mb"] > 0:
                result["used_pct"] = round(result["used_mb"] / result["total_mb"] * 100, 1)
        if len(parts) >= 4 and parts[0] == 'Swap:':
            result["swap_total_mb"] = safe_int(parts[1])
            result["swap_used_mb"] = safe_int(parts[2])
            result["swap_free_mb"] = safe_int(parts[3])
            if result["swap_total_mb"] > 0:
                result["swap_used_pct"] = round(result["swap_used_mb"] / result["swap_total_mb"] * 100, 1)
    return result


def parse_df(node_path: str) -> list:
    """Parse df -h output."""
    content = read_stdout(node_path, "df")
    if not content:
        return []
    lines = content.strip().split('\n')
    result = []
    for line in lines[1:]:  # Skip header
        parts = line.split()
        if len(parts) >= 6:
            use_pct_str = parts[4].replace('%', '')
            result.append({
                "filesystem": parts[0],
                "size": parts[1],
                "used": parts[2],
                "avail": parts[3],
                "use_pct": safe_int(use_pct_str),
                "mounted_on": parts[5] if len(parts) > 5 else "",
            })
    return result


def parse_uptime(node_path: str) -> dict:
    """Parse uptime output."""
    content = read_stdout(node_path, "uptime")
    if not content:
        return {}
    return {"raw": content.strip()}


def parse_cpu_info(node_path: str) -> dict:
    """Parse CPU threading/frequency info."""
    result = {}
    threading = parse_json_file(node_path, "cpuThreadingInfo.json")
    if threading:
        result["threading"] = threading
    freq = parse_json_file(node_path, "cpuFreqInfo.json")
    if freq:
        result["frequency"] = freq
    return result


def parse_top(node_path: str) -> dict:
    """Parse top output (summary lines)."""
    content = read_stdout(node_path, "top")
    if not content:
        return {}
    result = {"raw_header": ""}
    lines = content.strip().split('\n')
    header_lines = []
    for line in lines[:7]:  # Top header is usually first 5-7 lines
        header_lines.append(line)
        if '%Cpu' in line or 'Cpu' in line:
            # Parse CPU line: %Cpu(s):  1.9 us,  0.4 sy, ...
            cpu_match = re.findall(r'(\d+\.?\d*)\s*(us|sy|ni|id|wa|hi|si|st)', line)
            if cpu_match:
                result["cpu"] = {k: float(v) for v, k in cpu_match}
        if 'MiB Mem' in line or 'KiB Mem' in line:
            mem_match = re.findall(r'(\d+\.?\d*)\s*(total|free|used|buff/cache)', line)
            if mem_match:
                result["mem_top"] = {k: float(v) for v, k in mem_match}
    result["raw_header"] = '\n'.join(header_lines)
    return result


def parse_ulimit(node_path: str) -> dict:
    """Parse ulimit output."""
    content = read_stdout(node_path, "ulimit")
    if not content:
        return {}
    return {"raw": content.strip()}


def parse_numa(node_path: str) -> dict:
    """Parse numactl output."""
    numa_dir = os.path.join(node_path, "numactl")
    if not os.path.isdir(numa_dir):
        return {}
    result = {}
    for f in os.listdir(numa_dir):
        fpath = os.path.join(numa_dir, f)
        if os.path.isfile(fpath):
            try:
                with open(fpath) as fh:
                    result[f] = fh.read()[:2000]
            except Exception:
                pass
    return result


def parse_dmesg(node_path: str) -> list:
    """Parse dmesg for errors/warnings (last 100 interesting lines)."""
    dmesg_dir = os.path.join(node_path, "dmesg")
    if not os.path.isdir(dmesg_dir):
        return []
    result = []
    for f in os.listdir(dmesg_dir):
        fpath = os.path.join(dmesg_dir, f)
        if os.path.isfile(fpath):
            try:
                with open(fpath) as fh:
                    for line in fh:
                        low = line.lower()
                        if any(kw in low for kw in ['error', 'oom', 'kill', 'fail', 'warn', 'panic', 'segfault']):
                            result.append(line.strip()[:500])
            except Exception:
                pass
    return result[-50:]


# ─── SingleStore JSON parsers ───────────────────────────────────────

def parse_json_file(node_path: str, filename: str) -> any:
    """Load a JSON file from node directory."""
    fpath = os.path.join(node_path, filename)
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath) as f:
            return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to parse {fpath}: {e}")
        return None


def parse_sdb_json_table(node_path: str, filename: str) -> list:
    """Parse SingleStore JSON table format: [{MemsqlID, columns, rows}]."""
    data = parse_json_file(node_path, filename)
    if not data:
        return []

    # Handle list format
    if isinstance(data, list):
        rows = []
        for item in data:
            if isinstance(item, dict) and "rows" in item:
                rows.extend(item["rows"])
        return rows

    # Handle dict format (keyed by MemsqlID)
    if isinstance(data, dict):
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
    """Parse clusterTopology.json which has ShowLeaves/ShowAggregators."""
    data = parse_json_file(node_path, "clusterTopology.json")
    if not data or not isinstance(data, dict):
        return {}

    result = {"leaves": [], "aggregators": []}
    for memsql_id, val in data.items():
        if isinstance(val, dict):
            if "ShowLeaves" in val and isinstance(val["ShowLeaves"], dict):
                leaves = val["ShowLeaves"]
                if "rows" in leaves:
                    result["leaves"] = leaves["rows"]
            if "ShowAggregators" in val and isinstance(val["ShowAggregators"], dict):
                aggs = val["ShowAggregators"]
                if "rows" in aggs:
                    result["aggregators"] = aggs["rows"]
    return result


def parse_pipelines(node_path: str) -> list:
    """Parse informationSchemaPipelines.json (nested dict format)."""
    data = parse_json_file(node_path, "informationSchemaPipelines.json")
    if not data:
        return []

    rows = []
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                if "Pipelines" in val and isinstance(val["Pipelines"], dict):
                    p = val["Pipelines"]
                    if "rows" in p:
                        rows.extend(p["rows"])
                elif "rows" in val:
                    rows.extend(val["rows"])
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "rows" in item:
                rows.extend(item["rows"])
    return rows


# ─── Trace log parser ───────────────────────────────────────────────

def parse_trace_logs(node_path: str, hostname: str, role: str) -> list:
    """Parse memsql trace logs."""
    logs_dir = os.path.join(node_path, "memsqlTracelogs")
    if not os.path.isdir(logs_dir):
        return []

    entries = []
    for f in sorted(os.listdir(logs_dir)):
        fpath = os.path.join(logs_dir, f)
        if not os.path.isfile(fpath):
            continue

        # Only parse main memsql.log files (not specialized sublogs unless they're small)
        if '_memsql.log' not in f and '_memsql.log.' not in f:
            continue

        try:
            if f.endswith('.gz'):
                with gzip.open(fpath, 'rt', errors='replace') as fh:
                    entries.extend(_parse_log_lines(fh, hostname, role, f, max_lines=500))
            else:
                with open(fpath, errors='replace') as fh:
                    entries.extend(_parse_log_lines(fh, hostname, role, f, max_lines=2000))
        except Exception as e:
            logger.debug(f"Failed to parse log {fpath}: {e}")

    return entries


def _parse_log_lines(fh, hostname: str, role: str, filename: str, max_lines: int = 2000) -> list:
    """Parse individual log lines."""
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
                "hostname": hostname,
                "role": role,
                "source": filename,
            })
            count += 1
    return entries


# ─── Log summary builder ───────────────────────────────────────────

def build_log_summary(logs: list) -> dict:
    """Build summary statistics from parsed logs."""
    severity_counts = defaultdict(int)
    node_severity = defaultdict(lambda: defaultdict(int))
    hourly_counts = defaultdict(lambda: defaultdict(int))

    for entry in logs:
        sev = entry.get("severity", "INFO")
        severity_counts[sev] += 1
        node_severity[entry.get("hostname", "unknown")][sev] += 1

        ts = entry.get("timestamp", "")
        if len(ts) >= 13:
            hour_key = ts[:13]  # "YYYY-MM-DD HH"
            hourly_counts[hour_key][sev] += 1

    return {
        "total": len(logs),
        "severity_counts": dict(severity_counts),
        "per_node": {k: dict(v) for k, v in node_severity.items()},
        "hourly": {k: dict(v) for k, v in sorted(hourly_counts.items())},
    }


# ─── Cluster overview builder ──────────────────────────────────────

def build_cluster_overview(mv_nodes: list, parsed_nodes: list) -> dict:
    """Build cluster overview from MV_NODES data."""
    overview = {
        "total_nodes": len(mv_nodes),
        "leaves": 0,
        "aggregators": 0,
        "online_nodes": 0,
        "offline_nodes": 0,
        "total_memory_mb": 0,
        "used_memory_mb": 0,
        "total_disk_mb": 0,
        "available_disk_mb": 0,
        "total_cpus": 0,
        "version": None,
        "nodes_detail": [],
        "availability_groups": set(),
    }

    for node in mv_nodes:
        node_type = node.get("TYPE", "").upper()
        if node_type == "LEAF":
            overview["leaves"] += 1
        elif node_type in ("CA", "MA", "AGGREGATOR", "MASTER"):
            overview["aggregators"] += 1

        state = node.get("STATE", "").lower()
        if state == "online":
            overview["online_nodes"] += 1
        else:
            overview["offline_nodes"] += 1

        overview["total_memory_mb"] += safe_int(node.get("MAX_MEMORY_MB", 0))
        overview["used_memory_mb"] += safe_int(node.get("MEMORY_USED_MB", 0))
        overview["total_disk_mb"] += safe_int(node.get("TOTAL_DATA_DISK_MB", 0))
        overview["available_disk_mb"] += safe_int(node.get("AVAILABLE_DATA_DISK_MB", 0))
        overview["total_cpus"] += safe_int(node.get("NUM_CPUS", 0))

        if not overview["version"] and node.get("VERSION"):
            overview["version"] = node["VERSION"]

        ag = node.get("AVAILABILITY_GROUP", "")
        if ag:
            overview["availability_groups"].add(ag)

        overview["nodes_detail"].append({
            "id": node.get("ID", ""),
            "ip_addr": node.get("IP_ADDR", ""),
            "port": node.get("PORT", ""),
            "type": node.get("TYPE", ""),
            "state": node.get("STATE", ""),
            "availability_group": ag,
            "num_cpus": safe_int(node.get("NUM_CPUS", 0)),
            "max_memory_mb": safe_int(node.get("MAX_MEMORY_MB", 0)),
            "memory_used_mb": safe_int(node.get("MEMORY_USED_MB", 0)),
            "table_memory_used_mb": safe_int(node.get("TABLE_MEMORY_USED_MB", 0)),
            "total_disk_mb": safe_int(node.get("TOTAL_DATA_DISK_MB", 0)),
            "available_disk_mb": safe_int(node.get("AVAILABLE_DATA_DISK_MB", 0)),
            "uptime_seconds": safe_int(node.get("UPTIME", 0)),
            "version": node.get("VERSION", ""),
        })

    overview["availability_groups"] = sorted(list(overview["availability_groups"]))

    if overview["total_disk_mb"] > 0:
        used_disk = overview["total_disk_mb"] - overview["available_disk_mb"]
        overview["disk_used_pct"] = round(used_disk / overview["total_disk_mb"] * 100, 1)
    if overview["total_memory_mb"] > 0:
        overview["memory_used_pct"] = round(overview["used_memory_mb"] / overview["total_memory_mb"] * 100, 1)

    return overview


# ─── Recommendations engine ────────────────────────────────────────

def generate_recommendations(report: dict) -> list:
    """Generate actionable recommendations from parsed data."""
    recs = []
    rec_id = 0

    # Check node health
    for node in report.get("nodes", []):
        hostname = node["hostname"]
        role = node["role"]

        # Memory pressure
        mem = node.get("metrics", {}).get("memory", {})
        if mem.get("used_pct", 0) > 85:
            rec_id += 1
            recs.append({
                "id": rec_id,
                "severity": "critical" if mem["used_pct"] > 95 else "warning",
                "category": "memory",
                "title": f"High memory usage on {hostname}",
                "description": f"Memory usage is at {mem['used_pct']}% ({mem.get('used_mb', 0)} MB / {mem.get('total_mb', 0)} MB). This can cause OOM kills and query failures.",
                "evidence": f"free -m shows {mem.get('available_mb', 0)} MB available",
                "remediation": "Consider increasing memory, reducing max_table_memory, or investigating memory-heavy queries.",
                "nodes": [hostname],
            })

        if mem.get("swap_used_pct", 0) > 10:
            rec_id += 1
            recs.append({
                "id": rec_id,
                "severity": "warning",
                "category": "memory",
                "title": f"Swap usage detected on {hostname}",
                "description": f"Swap usage is {mem.get('swap_used_mb', 0)} MB ({mem.get('swap_used_pct', 0)}%). SingleStore performs best with no swap usage.",
                "evidence": f"free -m shows swap used: {mem.get('swap_used_mb', 0)} MB",
                "remediation": "Investigate memory pressure. Consider disabling swap (vm.swappiness=0) or adding more RAM.",
                "nodes": [hostname],
            })

        # Disk space
        disks = node.get("metrics", {}).get("disk", [])
        for disk in disks:
            if disk.get("use_pct", 0) > 80 and "memsql" in disk.get("mounted_on", "").lower():
                rec_id += 1
                recs.append({
                    "id": rec_id,
                    "severity": "critical" if disk["use_pct"] > 90 else "warning",
                    "category": "disk",
                    "title": f"High disk usage on {hostname} ({disk['mounted_on']})",
                    "description": f"Disk usage is at {disk['use_pct']}% on {disk['mounted_on']} (used: {disk['used']}, total: {disk['size']}).",
                    "evidence": f"df -h: {disk['filesystem']} mounted on {disk['mounted_on']}",
                    "remediation": "Free disk space, expand storage, or investigate large databases/tables. Consider running OPTIMIZE TABLE or checking for bloated tracelogs.",
                    "nodes": [hostname],
                })

        # Dmesg errors
        dmesg = node.get("metrics", {}).get("dmesg", [])
        oom_lines = [l for l in dmesg if 'oom' in l.lower() or 'kill' in l.lower()]
        if oom_lines:
            rec_id += 1
            recs.append({
                "id": rec_id,
                "severity": "critical",
                "category": "system",
                "title": f"OOM killer activity detected on {hostname}",
                "description": f"Found {len(oom_lines)} OOM-related entries in dmesg. The system may have killed processes due to memory exhaustion.",
                "evidence": oom_lines[0][:200] if oom_lines else "",
                "remediation": "Increase memory, reduce workload, or adjust vm.overcommit settings. Check if memsqld was killed.",
                "nodes": [hostname],
            })

    # Check cluster overview
    overview = report.get("cluster_overview", {})
    if overview.get("offline_nodes", 0) > 0:
        rec_id += 1
        recs.append({
            "id": rec_id,
            "severity": "critical",
            "category": "availability",
            "title": f"{overview['offline_nodes']} node(s) offline",
            "description": f"Out of {overview.get('total_nodes', 0)} nodes, {overview['offline_nodes']} are not in 'online' state.",
            "evidence": "SHOW CLUSTER STATUS / MV_NODES",
            "remediation": "Check node connectivity, memsqld process status, and network configuration.",
            "nodes": [],
        })

    # Check events for errors
    events = report.get("events", [])
    error_events = [e for e in events if e.get("SEVERITY", "").upper() in ("ERROR", "CRITICAL", "FATAL")]
    if error_events:
        rec_id += 1
        recs.append({
            "id": rec_id,
            "severity": "warning",
            "category": "events",
            "title": f"{len(error_events)} error event(s) detected",
            "description": f"MV_EVENTS contains {len(error_events)} entries with ERROR or higher severity.",
            "evidence": error_events[0].get("DETAILS", "")[:200] if error_events else "",
            "remediation": "Review event details in the Events section for specific error types and affected nodes.",
            "nodes": [],
        })

    # Check log patterns
    log_summary = report.get("log_summary", {})
    sev = log_summary.get("severity_counts", {})
    error_count = sev.get("ERROR", 0) + sev.get("FATAL", 0)
    if error_count > 10:
        rec_id += 1
        recs.append({
            "id": rec_id,
            "severity": "warning" if error_count < 50 else "critical",
            "category": "logs",
            "title": f"{error_count} error/fatal log entries detected",
            "description": f"Found {sev.get('ERROR', 0)} ERROR and {sev.get('FATAL', 0)} FATAL entries across all tracelogs.",
            "evidence": f"Log analysis across {log_summary.get('total', 0)} total entries",
            "remediation": "Review the Logs Explorer page to identify recurring error patterns and their root causes.",
            "nodes": [],
        })

    # Check for version mismatches across nodes
    versions = set()
    for nd in overview.get("nodes_detail", []):
        v = nd.get("version", "")
        if v:
            versions.add(v)
    if len(versions) > 1:
        rec_id += 1
        recs.append({
            "id": rec_id,
            "severity": "warning",
            "category": "configuration",
            "title": "Version mismatch across nodes",
            "description": f"Multiple SingleStore versions detected: {', '.join(sorted(versions))}. All nodes should run the same version.",
            "evidence": "MV_NODES VERSION column",
            "remediation": "Plan a rolling upgrade to ensure all nodes run the same version.",
            "nodes": [],
        })

    # Sort by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    recs.sort(key=lambda r: severity_order.get(r.get("severity", "info"), 2))

    return recs


# ─── Utility functions ──────────────────────────────────────────────

def read_stdout(node_path: str, collector_name: str) -> str:
    """Read the _stdout file from a collector subdirectory."""
    dir_path = os.path.join(node_path, collector_name)
    if not os.path.isdir(dir_path):
        return ""
    for f in os.listdir(dir_path):
        if f.endswith('_stdout') or f == 'stdout':
            try:
                with open(os.path.join(dir_path, f)) as fh:
                    return fh.read()
            except Exception:
                pass
    return ""


def parse_text_file(node_path: str, collector_name: str) -> str:
    """Read raw text from a collector (either as file or from subdir)."""
    content = read_stdout(node_path, collector_name)
    if content:
        return content[:5000]
    # Try direct file
    for ext in ['', '.txt', '.log']:
        fpath = os.path.join(node_path, collector_name + ext)
        if os.path.isfile(fpath):
            try:
                with open(fpath) as f:
                    return f.read()[:5000]
            except Exception:
                pass
    return ""


def parse_global_info(global_path: str) -> dict:
    """Parse globalInfo directory."""
    result = {}
    for f in os.listdir(global_path):
        fpath = os.path.join(global_path, f)
        if os.path.isfile(fpath) and f.endswith('.json'):
            try:
                with open(fpath) as fh:
                    result[f.replace('.json', '')] = json.load(fh)
            except Exception:
                pass
    return result


def safe_int(val) -> int:
    """Safely convert to int."""
    try:
        return int(float(str(val).replace(',', '')))
    except (ValueError, TypeError):
        return 0
