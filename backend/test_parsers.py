"""
Comprehensive test suite for backend parsers module.
Tests the core parsing logic, recommendations engine, and critical pattern detection.
"""
import unittest
import json
import os
import tempfile
import tarfile
import zipfile
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from parsers import (
    generate_recommendations,
    build_cluster_overview,
    build_alloc_memory_overview,
    detect_log_patterns,
    build_config_health,
    extract_alloc_memory_metrics,
    parse_free,
    parse_df,
    parse_uptime,
    parse_thp,
    parse_sysctl_checks,
    classify_dmesg_events,
    get_critical_log_patterns,
    get_dmesg_patterns,
    safe_int,
    parse_report_directory,
    infer_deployment_method,
    parse_rebalance_status,
    extract_log_timeframe,
    summarize_backup_history,
    compute_pressure_events_per_hour,
    summarize_memory_pressure,
    summarize_cluster_layout,
    extract_process_health,
    extract_node_events,
    extract_rebalance_events,
    _parse_log_lines,
    _parse_log_lines_tailed,
    extract_query_patterns,
    extract_query_analysis,
    extract_replication_lag_patterns,
    extract_memory_utilization_trend,
    extract_long_running_transactions,
    extract_compilation_times,
    extract_heartbeat_failures,
    extract_table_skew_analytics,
    build_log_error_timeline,
    build_extended_diagnostics,
    hydrate_extended_diagnostics,
    _extended_diagnostics_populated,
    _primary_diagnostics_populated,
    build_mv_events_timeline,
    extract_cpu_health,
    extract_sysinfo_network_health,
    _normalize_sql,
    _safe_float_val,
    _is_async_transition_message,
    _is_tracelog_file,
    _dmesg_collector_status,
    _stream_extract_rows_from_json_file,
    parse_sdb_json_table,
    derive_database_disk_usage_from_table_statistics,
    resolve_database_disk_usage,
    resolve_memory_utilization,
    _as_row_list,
)
from superchecker import compute_diff


class TestRecommendationsEngine(unittest.TestCase):
    """Test the recommendations engine with various report scenarios."""

    def test_empty_report_returns_empty_list(self):
        """Edge case: Empty report should return no recommendations."""
        report = {"nodes": [], "cluster_overview": {}, "recommendations": []}
        recs = generate_recommendations(report)
        self.assertIsInstance(recs, list)

    def test_disk_usage_critical_threshold(self):
        """RULE-01: Disk usage > 90% should generate critical recommendation."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {"disk": [{"use_pct": 95, "mounted_on": "/var/lib/memsql", "filesystem": "/dev/sda1", "used": "900G", "size": "1T"}]}
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        disk_recs = [r for r in recs if r["category"] == "Storage"]
        self.assertTrue(any(r["severity"] == "critical" for r in disk_recs))

    def test_disk_usage_warning_threshold(self):
        """RULE-01: Disk usage 86-90% should generate warning recommendation."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {"disk": [{"use_pct": 87, "mounted_on": "/data", "filesystem": "/dev/sda2", "used": "87G", "size": "100G"}]}
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        disk_recs = [r for r in recs if r["category"] == "Storage"]
        self.assertTrue(any(r["severity"] == "warning" for r in disk_recs))

    def test_disk_usage_ignore_low_usage(self):
        """RULE-01: Disk usage < 86% should not generate storage recommendation."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {"disk": [{"use_pct": 50, "mounted_on": "/var/lib/memsql", "filesystem": "/dev/sda1", "used": "500G", "size": "1T"}]}
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        disk_recs = [r for r in recs if r["category"] == "Storage"]
        self.assertEqual(len(disk_recs), 0)

    def test_thp_not_disabled_generates_critical(self):
        """RULE-02: THP not disabled should generate critical recommendation."""
        report = {
            "nodes": [],
            "cluster_overview": {},
            "config_health": {
                "os_checks": [{
                    "name": "Transparent Huge Pages",
                    "status": "fail",
                    "detail": "THP is set to [always]",
                }]
            },
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        thp_recs = [r for r in recs if "Transparent Huge" in r["title"]]
        self.assertTrue(len(thp_recs) > 0)
        self.assertEqual(thp_recs[0]["severity"], "critical")

    def test_redundancy_degraded_offline_partitions(self):
        """RULE-03: Offline partitions should generate critical recommendation."""
        report = {
            "nodes": [],
            "databases": [],
            "cluster_overview": {
                "cluster_status": [
                    {"State": "OFFLINE", "Database": "db1"},
                    {"State": "ONLINE", "Database": "db2"},
                ]
            },
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        repl_recs = [r for r in recs if r["category"] == "Replication"]
        self.assertTrue(any("degraded" in r["title"].lower() or "risk" in r["title"].lower() for r in repl_recs))

    def test_oom_kill_detection_dmesg(self):
        """RULE-05: OOM kill in dmesg should generate critical recommendation."""
        report = {
            "nodes": [],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [{
                "category": "oom",
                "hostname": "node1",
                "line": "Out of memory: Killed process 1234",
                "conclusion": "Linux OOM-killer terminated a process",
            }],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        oom_recs = [r for r in recs if "OOM" in r["title"]]
        self.assertTrue(len(oom_recs) > 0)
        self.assertEqual(oom_recs[0]["severity"], "critical")

    def test_oom_pattern_in_logs(self):
        """RULE-05: OOM pattern in logs should generate critical recommendation."""
        report = {
            "nodes": [],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [{
                "category": "oom",
                "title": "OOM Kill Detected",
                "severity": "critical",
                "count": 5,
                "first_seen": "2024-01-01T00:00:00Z",
                "last_seen": "2024-01-01T12:00:00Z",
                "sample": "out of memory error",
                "nodes": ["node1"],
                "conclusion": "OOM detected in trace logs",
            }],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        oom_recs = [r for r in recs if "OOM" in r["title"]]
        self.assertTrue(len(oom_recs) >= 1)

    def test_pipeline_errors_generates_warning(self):
        """RULE-07: Pipeline in error state should generate warning."""
        report = {
            "nodes": [],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [
                {"PIPELINE_NAME": "pipeline1", "STATE": "ERROR"},
                {"PIPELINE_NAME": "pipeline2", "STATE": "RUNNING"},
            ],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        pipe_recs = [r for r in recs if r["category"] == "Pipelines"]
        self.assertTrue(any("error" in r["title"].lower() for r in pipe_recs))

    def test_mixed_versions_generates_warning(self):
        """RULE-08: Mixed node versions should generate warning."""
        report = {
            "nodes": [],
            "cluster_overview": {
                "nodes_detail": [
                    {"version": "8.1.5"},
                    {"version": "8.1.6"},
                ]
            },
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        version_recs = [r for r in recs if "version" in r["title"].lower()]
        self.assertTrue(len(version_recs) > 0)

    def test_nofile_limit_fail_generates_critical(self):
        """RULE-09: Low nofile limit should generate critical recommendation."""
        report = {
            "nodes": [],
            "cluster_overview": {},
            "config_health": {
                "os_checks": [{
                    "name": "Open Files Limit (nofile)",
                    "status": "fail",
                    "detail": "Current limit: 1024, Required: 1000000",
                }]
            },
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        nofile_recs = [r for r in recs if "nofile" in r["title"].lower() or "open files" in r["title"].lower()]
        self.assertTrue(len(nofile_recs) > 0)
        self.assertEqual(nofile_recs[0]["severity"], "critical")

    def test_backup_old_than_7_days_generates_warning(self):
        """RULE-10: Backup older than 7 days should generate warning."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        report = {
            "nodes": [],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [
                {"STATUS": "success", "START_TIMESTAMP": old_date},
            ],
        }
        recs = generate_recommendations(report)
        backup_recs = [r for r in recs if r["category"] == "Backup"]
        self.assertTrue(len(backup_recs) > 0)

    def test_no_backup_history_generates_warning(self):
        """RULE-10: No backup history should generate warning."""
        report = {
            "nodes": [],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        backup_recs = [r for r in recs if r["category"] == "Backup"]
        self.assertTrue(len(backup_recs) > 0)
        self.assertEqual(backup_recs[0]["severity"], "warning")

    def test_high_memory_usage_warning(self):
        """Memory usage > 85% should generate warning/critical."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {
                    "memory": {"used_pct": 92, "used_mb": 9000, "total_mb": 10000, "available_mb": 800}
                }
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        mem_recs = [r for r in recs if r["category"] == "Memory"]
        self.assertTrue(len(mem_recs) > 0)

    def test_swap_usage_generates_warning(self):
        """Swap usage > 0 should generate recommendation."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {
                    "memory": {"used_pct": 70, "swap_used_mb": 500, "swap_total_mb": 2000}
                }
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        swap_recs = [r for r in recs if "swap" in r["description"].lower() or "swap" in r["title"].lower()]
        self.assertTrue(len(swap_recs) > 0)


class TestCriticalLogPatterns(unittest.TestCase):
    """Test critical log pattern detection."""

    def test_oom_pattern_detection(self):
        """OOM pattern should be detected correctly."""
        logs = [
            {"timestamp": "2024-01-01T00:00:00Z", "severity": "ERROR", "message": "Out of memory in memsqld"},
            {"timestamp": "2024-01-01T00:00:01Z", "severity": "INFO", "message": "Normal operation"},
        ]
        patterns = detect_log_patterns(logs)
        oom_pats = [p for p in patterns if p["category"] == "oom"]
        self.assertEqual(len(oom_pats), 1)
        self.assertEqual(oom_pats[0]["count"], 1)

    def test_disk_full_pattern_detection(self):
        """Disk full pattern should be detected correctly."""
        logs = [
            {"timestamp": "2024-01-01T00:00:00Z", "severity": "ERROR", "message": "No space left on device"},
            {"timestamp": "2024-01-01T00:00:01Z", "severity": "ERROR", "message": "Disk full"},
        ]
        patterns = detect_log_patterns(logs)
        disk_pats = [p for p in patterns if p["category"] == "disk"]
        self.assertEqual(len(disk_pats), 1)
        self.assertEqual(disk_pats[0]["count"], 2)

    def test_replication_error_pattern(self):
        """Replication error pattern should be detected."""
        logs = [
            {"timestamp": "2024-01-01T00:00:00Z", "severity": "ERROR", "message": "Replication link down"},
        ]
        patterns = detect_log_patterns(logs)
        repl_pats = [p for p in patterns if p["category"] == "replication"]
        self.assertEqual(len(repl_pats), 1)
        self.assertEqual(repl_pats[0]["severity"], "critical")

    def test_crash_backtrace_pattern(self):
        """Crash/backtrace pattern should be detected."""
        logs = [
            {"timestamp": "2024-01-01T00:00:00Z", "severity": "FATAL", "message": "Segmentation fault"},
        ]
        patterns = detect_log_patterns(logs)
        crash_pats = [p for p in patterns if p["category"] == "crash"]
        self.assertEqual(len(crash_pats), 1)
        self.assertEqual(crash_pats[0]["severity"], "critical")

    def test_case_insensitive_detection(self):
        """Pattern matching should be case insensitive."""
        logs = [
            {"timestamp": "2024-01-01T00:00:00Z", "severity": "ERROR", "message": "OUT OF MEMORY"},
            {"timestamp": "2024-01-01T00:00:01Z", "severity": "ERROR", "message": "Out Of Memory"},
        ]
        patterns = detect_log_patterns(logs)
        oom_pats = [p for p in patterns if p["category"] == "oom"]
        self.assertEqual(oom_pats[0]["count"], 2)

    def test_empty_logs_returns_empty(self):
        """Empty log list should return empty patterns."""
        patterns = detect_log_patterns([])
        self.assertEqual(patterns, [])

    def test_no_critical_patterns_returns_empty(self):
        """Logs without critical patterns should return empty."""
        logs = [
            {"timestamp": "2024-01-01T00:00:00Z", "severity": "INFO", "message": "Query executed successfully"},
        ]
        patterns = detect_log_patterns(logs)
        self.assertEqual(patterns, [])


class TestDmesgPatterns(unittest.TestCase):
    """Test dmesg event classification."""

    def test_oom_in_dmesg(self):
        """OOM in dmesg should be classified correctly."""
        dmesg = [{"line": "Out of memory: Killed process 1234", "timestamp": ""}]
        events = classify_dmesg_events(dmesg, "node1", "LEAF")
        self.assertEqual(events[0]["category"], "oom")
        self.assertEqual(events[0]["severity"], "critical")

    def test_storage_fault_detection(self):
        """Storage hardware errors should be classified."""
        dmesg = [{"line": "EXT4-fs error", "timestamp": ""}]
        events = classify_dmesg_events(dmesg, "node1", "LEAF")
        self.assertEqual(events[0]["category"], "storage_fault")

    def test_thp_warning_in_dmesg(self):
        """THP warnings in dmesg should be classified."""
        dmesg = [{"line": "transparent hugepage: some process is using it", "timestamp": ""}]
        events = classify_dmesg_events(dmesg, "node1", "LEAF")
        self.assertEqual(events[0]["category"], "thp")


class TestBuildClusterOverview(unittest.TestCase):
    """Test cluster overview building."""

    def test_empty_nodes(self):
        """Empty nodes should return empty overview."""
        overview = build_cluster_overview([], [])
        self.assertIsInstance(overview, dict)

    def test_single_node_overview(self):
        """Single node should create valid overview."""
        mv_nodes = [{"NodeId": 0, "Host": "node1", "State": "online", "Role": "Master", "Version": "8.1.5"}]
        nodes = [{"hostname": "node1", "role": "MA"}]
        overview = build_cluster_overview(mv_nodes, nodes)
        self.assertIn("total_nodes", overview)
        self.assertEqual(overview["total_nodes"], 1)

    def test_version_extraction(self):
        """Version should be extracted from nodes."""
        mv_nodes = [{"NodeId": 0, "Host": "node1", "State": "online", "Role": "Master", "Version": "8.1.5"}]
        nodes = [{"hostname": "node1", "role": "MA", "version": "8.1.5"}]
        overview = build_cluster_overview(mv_nodes, nodes)
        self.assertEqual(overview.get("version"), "8.1.5")

    def test_missing_node_state_is_unknown_not_offline(self):
        """Topology-only rows without MV_NODES state should not count as offline."""
        mv_nodes = [
            {"NodeId": 1, "Host": "leaf-1", "Role": "Leaf"},
            {"NodeId": 2, "Host": "aggregator-1", "Role": "Master Aggregator"},
            {"NodeId": 3, "Host": "leaf-2", "Role": "Leaf", "State": "UNKNOWN"},
        ]
        overview = build_cluster_overview(mv_nodes, [])
        self.assertEqual(overview["online_nodes"], 0)
        self.assertEqual(overview["offline_nodes"], 0)
        self.assertEqual([n["state"] for n in overview["nodes_detail"]], ["", "", "unknown"])


class TestBuildConfigHealth(unittest.TestCase):
    """Test config health building."""

    def test_empty_nodes(self):
        """Empty nodes should return empty config health."""
        health = build_config_health([])
        self.assertIsInstance(health, dict)

    def test_thp_check_passing(self):
        """THP check should pass when set to never."""
        nodes = [{
            "hostname": "node1",
            "os_checks": {
                "thp": {"status": "disabled", "active": "never"}
            }
        }]
        health = build_config_health(nodes)
        self.assertIn("os_checks", health)


class TestParsingHelpers(unittest.TestCase):
    """Test parsing helper functions."""

    def test_safe_int_valid(self):
        """safe_int should parse valid integers."""
        self.assertEqual(safe_int("12345"), 12345)
        self.assertEqual(safe_int("0"), 0)
        self.assertEqual(safe_int("1000000"), 1000000)

    def test_safe_int_invalid(self):
        """safe_int should return 0 for invalid strings."""
        self.assertEqual(safe_int("abc"), 0)
        self.assertEqual(safe_int(""), 0)
        self.assertEqual(safe_int(None), 0)

    def test_safe_int_with_percentage(self):
        """safe_int should handle percentage strings."""
        self.assertEqual(safe_int("85%"), 85)
        self.assertEqual(safe_int("100%"), 100)

    def test_parse_rebalance_status_reads_candidate_files(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_rebalance_"))
        node = root / "node-MA"
        node.mkdir(parents=True, exist_ok=True)
        sample = [{"Action": "PROMOTE PARTITION WITH REPOINT", "Status": "failed (... could not synchronize ...)"}]
        (node / "showRebalanceStatus.json").write_text(json.dumps({"rows": sample}))
        rows = parse_rebalance_status(str(node))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("Action"), "PROMOTE PARTITION WITH REPOINT")


class TestAllocMemoryHelpers(unittest.TestCase):
    """Test Alloc_* extraction and aggregation."""

    def test_extract_alloc_memory_metrics_from_rows(self):
        rows = [
            {"Name": "Alloc_unit_images", "Value": "1048576"},
            {"Variable_name": "Alloc_object_code_images", "Variable_value": "2097152"},
            {"Name": "Total_server_memory", "Value": "999"},
            {"Name": "Alloc_compiled_unit_sections", "Value": "512"},
        ]

        metrics = extract_alloc_memory_metrics(rows)

        self.assertEqual(
            [metric["metric"] for metric in metrics],
            [
                "Alloc_object_code_images",
                "Alloc_unit_images",
                "Alloc_compiled_unit_sections",
            ],
        )
        self.assertEqual(metrics[0]["value"], 2097152)

    def test_build_alloc_memory_overview(self):
        nodes = [
            {
                "hostname": "leaf-1",
                "role": "LEAF",
                "metrics": {
                    "alloc_memory": [
                        {"metric": "Alloc_unit_images", "value": 100},
                        {"metric": "Alloc_object_code_images", "value": 200},
                    ]
                },
            },
            {
                "hostname": "agg-1",
                "role": "MASTER",
                "metrics": {
                    "alloc_memory": [
                        {"metric": "Alloc_unit_images", "value": 300},
                    ]
                },
            },
        ]

        overview = build_alloc_memory_overview(nodes)

        self.assertEqual(len(overview["per_node"]), 2)
        self.assertEqual(overview["per_node"][0]["total_bytes"], 300)
        self.assertEqual(overview["per_node"][1]["total_bytes"], 300)
        self.assertEqual(overview["totals"][0]["metric"], "Alloc_unit_images")
        self.assertEqual(overview["totals"][0]["value"], 400)


class TestParseFree(unittest.TestCase):
    """Test free command parsing."""

    def test_parse_free_output(self):
        """Valid free output should be parsed correctly."""
        content = """              total        used        free      shared  buff/cache   available
Mem:        8192044     4096022     2048011      123456     2048011     3891233
Swap:       2097152        512     2096640"""
        root = Path(tempfile.mkdtemp(prefix="s2rs_free_"))
        node = root / "node-MA" / "free"
        node.mkdir(parents=True, exist_ok=True)
        (node / "free_stdout").write_text(content)
        result = parse_free(str(root / "node-MA"))
        self.assertEqual(result.get("total_mb"), 8192044)
        self.assertEqual(result.get("swap_total_mb"), 2097152)

    def test_parse_free_empty(self):
        """Empty content should return empty dict."""
        root = Path(tempfile.mkdtemp(prefix="s2rs_free_empty_"))
        (root / "node-MA").mkdir(parents=True, exist_ok=True)
        result = parse_free(str(root / "node-MA"))
        self.assertEqual(result, {})


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and failure modes."""

    def test_missing_node_metrics(self):
        """Nodes with missing metrics should not crash recommendations."""
        report = {
            "nodes": [{"hostname": "node1"}],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        try:
            recs = generate_recommendations(report)
            self.assertIsInstance(recs, list)
        except Exception as e:
            self.fail(f"generate_recommendations crashed: {e}")

    def test_none_values_in_report(self):
        """None values in report should be handled gracefully."""
        report = {
            "nodes": None,
            "cluster_overview": None,
            "config_health": None,
            "detected_log_patterns": None,
            "dmesg_events": None,
            "pipelines": None,
            "replication_status": None,
            "backup_history": None,
        }
        try:
            recs = generate_recommendations(report)
            self.assertIsInstance(recs, list)
        except Exception:
            pass

    def test_malformed_disk_data(self):
        """Malformed disk data should not crash parser."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {"disk": [{"invalid": "data"}]}
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        try:
            recs = generate_recommendations(report)
            self.assertIsInstance(recs, list)
        except Exception:
            pass


class TestPropertyBasedScenarios(unittest.TestCase):
    """Property-based tests for invariants."""

    def test_recommendations_always_has_id(self):
        """All recommendations must have a unique ID."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {"disk": [{"use_pct": 95, "mounted_on": "/var/lib", "filesystem": "/dev/sda1", "used": "100G", "size": "100G"}]}
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        for rec in recs:
            self.assertIn("id", rec)
            self.assertIsInstance(rec["id"], int)

    def test_recommendations_have_required_fields(self):
        """All recommendations must have required fields."""
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {"disk": [{"use_pct": 95, "mounted_on": "/var/lib", "filesystem": "/dev/sda1", "used": "100G", "size": "100G"}]}
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        required_fields = ["severity", "category", "title", "description", "evidence", "remediation"]
        for rec in recs:
            for field in required_fields:
                self.assertIn(field, rec, f"Missing {field} in recommendation: {rec}")

    def test_severity_values_valid(self):
        """Severity must be one of the valid values."""
        valid_severities = {"critical", "warning", "info"}
        report = {
            "nodes": [{
                "hostname": "node1",
                "metrics": {"disk": [{"use_pct": 95, "mounted_on": "/var/lib", "filesystem": "/dev/sda1", "used": "100G", "size": "100G"}]}
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        for rec in recs:
            self.assertIn(rec["severity"], valid_severities, f"Invalid severity: {rec['severity']}")


class TestSuperCheckerEnhancements(unittest.TestCase):
    def test_superchecker_fields_present(self):
        report = {
            "nodes": [{
                "hostname": "leaf-1",
                "metrics": {"disk": [{"use_pct": 95, "mounted_on": "/data", "filesystem": "/dev/sda1", "used": "95G", "size": "100G"}]},
                "show_variables": {"maximum_memory": "48GB"},
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        self.assertTrue(len(recs) > 0)
        self.assertIn("checker_id", recs[0])
        self.assertIn("risk_score", recs[0])
        self.assertIn("confidence", recs[0])

    def test_related_findings_generated_from_shared_node(self):
        report = {
            "nodes": [{
                "hostname": "leaf-1",
                "metrics": {
                    "disk": [{"use_pct": 95, "mounted_on": "/data", "filesystem": "/dev/sda1", "used": "95G", "size": "100G"}],
                    "memory": {"used_pct": 96, "total_mb": 10000, "used_mb": 9600, "available_mb": 200},
                },
                "show_variables": {"maximum_memory": "9GB"},
            }],
            "cluster_overview": {},
            "config_health": {"os_checks": []},
            "detected_log_patterns": [],
            "dmesg_events": [],
            "pipelines": [],
            "replication_status": [],
            "backup_history": [],
        }
        recs = generate_recommendations(report)
        linked = [r for r in recs if r.get("related_findings")]
        self.assertTrue(len(linked) > 0)

    def test_compute_diff_basic(self):
        old = [
            {"checker_id": "diskUsage", "title": "Disk usage high", "severity": "warning", "risk_score": 60},
            {"checker_id": "transparentHugepage", "title": "THP not disabled", "severity": "critical", "risk_score": 90},
        ]
        new = [
            {"checker_id": "diskUsage", "title": "Disk usage high", "severity": "critical", "risk_score": 95},
            {"checker_id": "replicationLag", "title": "Replication lag detected", "severity": "warning", "risk_score": 70},
        ]
        diff = compute_diff(old, new)
        self.assertTrue(any(d["checker_id"] == "replicationLag" for d in diff["new"]))
        self.assertTrue(any(d["checker_id"] == "transparentHugepage" for d in diff["resolved"]))
        self.assertTrue(any(d["checker_id"] == "diskUsage" for d in diff["worsened"]))


class TestDeploymentInference(unittest.TestCase):
    def test_kubernetes_detected_from_processes(self):
        nodes = [
            {"hostname": "node-1", "metrics": {"ps": [{"cmd": "/usr/bin/kubelet"}]}, "config": {}},
        ]
        res = infer_deployment_method(nodes, {"total_nodes": 1})
        self.assertEqual(res.get("method"), "Kubernetes Operator")
        self.assertIn(res.get("confidence"), ("medium", "high"))

    def test_docker_detected_from_processes(self):
        nodes = [
            {"hostname": "node-1", "metrics": {"ps": [{"cmd": "/usr/bin/dockerd"}]}, "config": {}},
        ]
        res = infer_deployment_method(nodes, {"total_nodes": 1})
        self.assertEqual(res.get("method"), "Docker Dev Image")

    def test_helios_detected_from_hostname(self):
        nodes = [
            {"hostname": "helios-prod-01", "metrics": {}, "config": {}},
        ]
        res = infer_deployment_method(nodes, {"total_nodes": 1})
        self.assertEqual(res.get("method"), "Helios Cloud Portal")

    def test_linux_default_when_no_signals(self):
        nodes = [
            {"hostname": "node-1", "metrics": {"ps": [{"cmd": "/usr/sbin/sshd"}]}, "config": {}},
        ]
        res = infer_deployment_method(nodes, {"total_nodes": 1})
        self.assertIn(res.get("method"), ("Linux (sdb-deploy)", "Unknown"))

    def test_kubernetes_detected_from_kube_metadata_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "kube-metadata"))
            nodes = [{"hostname": "node-1", "metrics": {}, "config": {}}]
            res = infer_deployment_method(nodes, {"total_nodes": 1}, report_root=tmp)
        self.assertEqual(res.get("method"), "Kubernetes Operator")
        self.assertEqual(res.get("confidence"), "high")
        self.assertIn("collector:kube-metadata", res.get("signals", []))


class TestExtractLogTimeframe(unittest.TestCase):
    """Tests for extract_log_timeframe helper."""

    def _make_node(self, hostname, trace_logs):
        return {"hostname": hostname, "trace_logs": trace_logs, "log_summary": {}}

    def test_single_node_with_logs(self):
        logs = [
            {"timestamp": "2024-01-10 08:00:00.000", "severity": "INFO", "message": "startup"},
            {"timestamp": "2024-01-10 10:30:00.000", "severity": "WARN", "message": "slow query"},
        ]
        nodes = [self._make_node("leaf-1", logs)]
        result = extract_log_timeframe(nodes)
        info = result["per_node"]["leaf-1"]
        self.assertEqual(info["first_log_entry"], "2024-01-10 08:00:00.000")
        self.assertEqual(info["last_log_entry"], "2024-01-10 10:30:00.000")
        self.assertAlmostEqual(info["coverage_hours"], 2.5, places=1)

    def test_empty_logs_returns_empty_strings(self):
        nodes = [self._make_node("leaf-1", [])]
        result = extract_log_timeframe(nodes)
        info = result["per_node"]["leaf-1"]
        self.assertEqual(info["first_log_entry"], "")
        self.assertEqual(info["last_log_entry"], "")
        self.assertEqual(info["coverage_hours"], 0.0)

    def test_cluster_first_and_last_across_nodes(self):
        logs_a = [{"timestamp": "2024-01-10 06:00:00.000", "severity": "INFO", "message": "a"}]
        logs_b = [{"timestamp": "2024-01-10 12:00:00.000", "severity": "INFO", "message": "b"}]
        nodes = [self._make_node("node-a", logs_a), self._make_node("node-b", logs_b)]
        result = extract_log_timeframe(nodes)
        self.assertEqual(result["cluster_first"], "2024-01-10 06:00:00.000")
        self.assertEqual(result["cluster_last"], "2024-01-10 12:00:00.000")

    def test_empty_nodes_list(self):
        result = extract_log_timeframe([])
        self.assertEqual(result["cluster_first"], "")
        self.assertEqual(result["cluster_last"], "")
        self.assertEqual(result["per_node"], {})


class TestSummarizeBackupHistory(unittest.TestCase):
    """Tests for summarize_backup_history helper."""

    def test_empty_history(self):
        result = summarize_backup_history([])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["success_count"], 0)
        self.assertEqual(result["failure_count"], 0)
        self.assertIsNone(result["latest_duration_sec"])

    def test_all_success(self):
        rows = [
            {"STATUS": "success", "START_TIMESTAMP": "2024-01-01 10:00:00", "END_TIMESTAMP": "2024-01-01 10:30:00"},
            {"STATUS": "success", "START_TIMESTAMP": "2024-01-02 10:00:00", "END_TIMESTAMP": "2024-01-02 10:45:00"},
        ]
        result = summarize_backup_history(rows)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["latest_success_ts"], "2024-01-02 10:45:00")
        self.assertAlmostEqual(result["latest_duration_sec"], 2700.0)

    def test_mixed_success_failure(self):
        rows = [
            {"STATUS": "success", "START_TIMESTAMP": "2024-01-01 10:00:00", "END_TIMESTAMP": "2024-01-01 11:00:00"},
            {"STATUS": "failure", "START_TIMESTAMP": "2024-01-02 10:00:00", "END_TIMESTAMP": "2024-01-02 10:01:00"},
            {"STATUS": "failed", "START_TIMESTAMP": "2024-01-03 10:00:00", "END_TIMESTAMP": "2024-01-03 10:02:00"},
        ]
        result = summarize_backup_history(rows)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failure_count"], 2)

    def test_no_end_timestamp_no_duration(self):
        rows = [{"STATUS": "success", "START_TIMESTAMP": "2024-01-01 10:00:00"}]
        result = summarize_backup_history(rows)
        self.assertEqual(result["success_count"], 1)
        self.assertIsNone(result["latest_duration_sec"])


class TestDatabaseDiskUsageFallback(unittest.TestCase):
    def test_derives_per_database_totals_from_table_statistics(self):
        rows = [
            {"DATABASE_NAME": "slateprod", "MEMORY_USE": 2 * 1024 * 1024 * 1024},
            {"DATABASE_NAME": "slateprod", "MEMORY_USE": 1024 * 1024 * 1024},
            {"DATABASE_NAME": "ml_analytics", "MEMORY_USE": 0},
        ]
        result = derive_database_disk_usage_from_table_statistics(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["DATABASE_NAME"], "slateprod")
        self.assertEqual(result[0]["_disk_bytes"], 3 * 1024 * 1024 * 1024)
        self.assertAlmostEqual(result[0]["TOTAL_DISK_USAGE_GB"], 3.0, places=3)
        self.assertEqual(result[0]["_source"], "table_statistics")

    def test_resolve_prefers_native_database_disk_usage(self):
        payload = {
            "database_disk_usage": [{"DATABASE_NAME": "native", "TOTAL_DISK_USAGE_GB": 12}],
            "storage": [{"DATABASE_NAME": "fallback", "MEMORY_USE": 1024}],
        }
        self.assertEqual(resolve_database_disk_usage(payload)[0]["DATABASE_NAME"], "native")

    def test_resolve_falls_back_to_storage(self):
        payload = {
            "database_disk_usage": [],
            "storage": [{"DATABASE_NAME": "fallback", "MEMORY_USE": 1024 * 1024 * 1024}],
        }
        resolved = resolve_database_disk_usage(payload)
        self.assertEqual(resolved[0]["DATABASE_NAME"], "fallback")
        self.assertEqual(resolved[0]["_source"], "table_statistics")

    def test_resolve_unwraps_rows_wrapper(self):
        payload = {
            "database_disk_usage": {
                "rows": [{"DATABASE_NAME": "wrapped", "TOTAL_DISK_USAGE_GB": 5}],
            },
        }
        resolved = resolve_database_disk_usage(payload)
        self.assertEqual(resolved[0]["DATABASE_NAME"], "wrapped")

    def test_resolve_memory_utilization_prefers_stored(self):
        payload = {
            "memory_utilization": {"per_node": {"host-1": {"os_used_pct": 42}}},
            "nodes": [{"hostname": "host-2"}],
        }
        resolved = resolve_memory_utilization(payload)
        self.assertEqual(resolved["per_node"]["host-1"]["os_used_pct"], 42)

    def test_resolve_memory_utilization_recomputes_from_nodes(self):
        payload = {
            "memory_utilization": {"per_node": {}},
            "nodes": [{"hostname": "10.0.0.1", "free": {"total_mb": 1000, "used_mb": 500, "used_pct": 50}}],
            "cluster_overview": {
                "nodes_detail": [{"ip_addr": "10.0.0.1", "memory_used_mb": 200, "max_memory_mb": 400}],
            },
        }
        resolved = resolve_memory_utilization(payload)
        self.assertIn("10.0.0.1", resolved["per_node"])
        self.assertEqual(resolved["per_node"]["10.0.0.1"]["os_used_pct"], 50)

    def test_resolve_memory_utilization_recomputes_from_wrapped_nodes_detail(self):
        payload = {
            "memory_utilization": {"per_node": {}},
            "nodes": [{"hostname": "10.0.0.1", "free": {"total_mb": 1000, "used_mb": 500, "used_pct": 50}}],
            "cluster_overview": {
                "nodes_detail": {
                    "rows": [{"ip_addr": "10.0.0.1", "memory_used_mb": 200, "max_memory_mb": 400}]
                },
            },
        }
        resolved = resolve_memory_utilization(payload)
        self.assertIn("10.0.0.1", resolved["per_node"])
        self.assertEqual(resolved["per_node"]["10.0.0.1"]["engine_used_pct"], 50)

    def test_resolve_memory_utilization_from_nodes_detail_only(self):
        payload = {
            "memory_utilization": {},
            "nodes": [],
            "cluster_overview": {
                "nodes_detail": [{"ip_addr": "10.0.0.2", "memory_used_mb": 100, "max_memory_mb": 200}],
            },
        }
        resolved = resolve_memory_utilization(payload)
        self.assertIn("10.0.0.2", resolved["per_node"])


class TestAsRowList(unittest.TestCase):
    def test_list_passthrough(self):
        self.assertEqual(_as_row_list([{"a": 1}]), [{"a": 1}])

    def test_unwraps_rows_key(self):
        self.assertEqual(_as_row_list({"rows": [{"b": 2}]}), [{"b": 2}])

    def test_non_table_dict_returns_empty(self):
        self.assertEqual(_as_row_list({"foo": 1}), [])


class TestComputePressureEventsPerHour(unittest.TestCase):
    """Tests for compute_pressure_events_per_hour helper."""

    def test_etimedout_counted(self):
        logs = [
            {"timestamp": "2024-01-10 09:00:00.000", "message": "ETIMEDOUT on node sync"},
            {"timestamp": "2024-01-10 09:15:00.000", "message": "Connection timed out to peer"},
            {"timestamp": "2024-01-10 10:00:00.000", "message": "ETIMEDOUT again"},
        ]
        result = compute_pressure_events_per_hour(logs)
        self.assertEqual(result["etimedout"].get("2024-01-10 09"), 2)
        self.assertEqual(result["etimedout"].get("2024-01-10 10"), 1)
        self.assertEqual(sum(result["fsync_behind"].values()), 0)

    def test_fsync_and_retry_counted(self):
        logs = [
            {"timestamp": "2024-01-10 08:00:00.000", "message": "fsync is behind by 1s"},
            {"timestamp": "2024-01-10 08:30:00.000", "message": "Retry loop is stalling"},
        ]
        result = compute_pressure_events_per_hour(logs)
        self.assertEqual(result["fsync_behind"].get("2024-01-10 08"), 1)
        self.assertEqual(result["retry_stall"].get("2024-01-10 08"), 1)

    def test_empty_logs_returns_empty_dicts(self):
        result = compute_pressure_events_per_hour([])
        self.assertEqual(result["etimedout"], {})
        self.assertEqual(result["fsync_behind"], {})
        self.assertEqual(result["retry_stall"], {})

    def test_no_matching_patterns_returns_empty(self):
        logs = [{"timestamp": "2024-01-10 08:00:00.000", "message": "normal startup complete"}]
        result = compute_pressure_events_per_hour(logs)
        self.assertEqual(sum(result["etimedout"].values()), 0)


class TestSummarizeMemoryPressure(unittest.TestCase):
    """Tests for summarize_memory_pressure helper."""

    def test_oom_in_dmesg_detected(self):
        nodes = [{
            "hostname": "leaf-1",
            "os_checks": {"thp": {"status": "enabled", "active": "always"}, "sysctl": {}},
            "dmesg_events": [{"category": "oom", "title": "OOM Kill"}],
        }]
        result = summarize_memory_pressure(nodes)
        self.assertTrue(result["leaf-1"]["oom_in_dmesg"])

    def test_thp_status_captured(self):
        nodes = [{
            "hostname": "leaf-1",
            "os_checks": {"thp": {"status": "disabled", "active": "never"}, "sysctl": {}},
            "dmesg_events": [],
        }]
        result = summarize_memory_pressure(nodes)
        self.assertEqual(result["leaf-1"]["thp_status"], "disabled")

    def test_swappiness_captured(self):
        nodes = [{
            "hostname": "node-1",
            "os_checks": {
                "thp": {},
                "sysctl": {"vm.swappiness": {"value": "60", "numeric": 60, "status": "warn"}},
            },
            "dmesg_events": [],
        }]
        result = summarize_memory_pressure(nodes)
        self.assertEqual(result["node-1"]["vm_swappiness"], "60")

    def test_max_map_count_captured(self):
        nodes = [{
            "hostname": "node-2",
            "os_checks": {
                "thp": {},
                "sysctl": {"vm.max_map_count": {"value": "65530", "numeric": 65530, "status": "fail"}},
            },
            "dmesg_events": [],
        }]
        result = summarize_memory_pressure(nodes)
        self.assertEqual(result["node-2"]["vm_max_map_count"], 65530)

    def test_empty_nodes_list(self):
        self.assertEqual(summarize_memory_pressure([]), {})


class TestSummarizeClusterLayout(unittest.TestCase):
    """Tests for summarize_cluster_layout helper."""

    def test_basic_partition_counts(self):
        rows = [
            {"Host": "leaf-1", "Role": "Master"},
            {"Host": "leaf-1", "Role": "Slave"},
            {"Host": "leaf-2", "Role": "Master"},
            {"Host": "leaf-2", "Role": "Slave"},
        ]
        result = summarize_cluster_layout(rows)
        self.assertEqual(result["by_role"]["master"], 2)
        self.assertEqual(result["by_role"]["slave"], 2)
        self.assertEqual(result["total_partitions"], 4)
        self.assertEqual(result["by_host"]["leaf-1"]["total"], 2)

    def test_empty_cluster_status(self):
        result = summarize_cluster_layout([])
        self.assertEqual(result["total_partitions"], 0)
        self.assertEqual(result["by_host"], {})

    def test_all_masters(self):
        rows = [{"Host": "h1", "Role": "Master"}, {"Host": "h2", "Role": "Master"}]
        result = summarize_cluster_layout(rows)
        self.assertEqual(result["by_role"]["master"], 2)
        self.assertEqual(result["by_role"]["slave"], 0)


class TestExtractProcessHealth(unittest.TestCase):
    """Tests for extract_process_health helper."""

    def test_active_queries_counted(self):
        rows = [
            {"Command": "Query", "Info": "SELECT 1", "Time": 5},
            {"Command": "Query", "Info": "SELECT sleep(100)", "Time": 100},
            {"Command": "Sleep", "Info": None, "Time": 0},
        ]
        result = extract_process_health(rows)
        self.assertEqual(result["active_count"], 2)

    def test_sleeping_open_transaction_detected(self):
        rows = [
            {"Command": "Sleep", "Info": "SELECT 1", "TRX_STATE": "running", "Time": 60},
        ]
        result = extract_process_health(rows)
        self.assertEqual(result["sleeping_open_tx_count"], 1)

    def test_sleeping_connection_no_tx_not_flagged(self):
        rows = [
            {"Command": "Sleep", "Info": None, "TRX_STATE": "", "Time": 5},
        ]
        result = extract_process_health(rows)
        self.assertEqual(result["sleeping_open_tx_count"], 0)
        self.assertEqual(result["active_count"], 0)

    def test_empty_processlist(self):
        result = extract_process_health([])
        self.assertEqual(result["active_count"], 0)
        self.assertEqual(result["sleeping_open_tx_count"], 0)
        self.assertEqual(result["active_queries"], [])
        self.assertEqual(result["sleeping_open_transactions"], [])


class TestExtractNodeEvents(unittest.TestCase):
    """Tests for extract_node_events helper."""

    def _make_event(self, event_type, event_time="2024-01-01 00:00:00", node_id="1", description=""):
        return {
            "EVENT_TYPE": event_type,
            "EVENT_TIME": event_time,
            "SEVERITY": "WARNING",
            "ORIGIN_NODE_ID": node_id,
            "EVENT_DESCRIPTION": description,
        }

    def test_empty_input(self):
        self.assertEqual(extract_node_events([]), [])

    def test_filters_non_node_events(self):
        events = [self._make_event("BACKUP_START"), self._make_event("QUERY_SLOW")]
        result = extract_node_events(events)
        self.assertEqual(result, [])

    def test_node_down_category(self):
        events = [self._make_event("LEAF_OFFLINE")]
        result = extract_node_events(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "node_down")
        self.assertEqual(result[0]["event_type"], "LEAF_OFFLINE")

    def test_node_up_category(self):
        events = [self._make_event("LEAF_ONLINE")]
        result = extract_node_events(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "node_up")

    def test_failover_category(self):
        events = [self._make_event("MASTER_FAILOVER")]
        result = extract_node_events(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "failover")

    def test_state_change_category_fallback(self):
        events = [self._make_event("LEAF_STATE_CHANGE")]
        result = extract_node_events(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "state_change")

    def test_deduplication(self):
        evt = self._make_event("LEAF_OFFLINE", "2024-01-01 00:00:00", "1")
        events = [evt, evt.copy()]
        result = extract_node_events(events)
        self.assertEqual(len(result), 1)

    def test_sorted_newest_first(self):
        events = [
            self._make_event("LEAF_OFFLINE", "2024-01-01 00:00:00", "1"),
            self._make_event("LEAF_ONLINE", "2024-01-02 00:00:00", "1"),
        ]
        result = extract_node_events(events)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["event_type"], "LEAF_ONLINE")

    def test_lifecycle_enums_included(self):
        events = [
            self._make_event("NODE_DETACHED", "2024-01-03 00:00:00", "2"),
            self._make_event("NODE_STARTING", "2024-01-02 00:00:00", "2"),
            self._make_event("NODE_ATTACHING", "2024-01-01 00:00:00", "2"),
        ]
        result = extract_node_events(events)
        self.assertEqual(len(result), 3)
        types = {e["event_type"] for e in result}
        self.assertEqual(types, {"NODE_DETACHED", "NODE_STARTING", "NODE_ATTACHING"})
        detached = next(e for e in result if e["event_type"] == "NODE_DETACHED")
        self.assertEqual(detached["category"], "node_down")

    def test_operational_enums_included(self):
        events = [
            self._make_event("WORKLOAD_THROTTLE"),
            self._make_event("CONSENSUS_ELECTION"),
            self._make_event("SYSTEM_VAR_CHANGED"),
        ]
        result = extract_node_events(events)
        self.assertEqual(len(result), 3)
        categories = {e["category"] for e in result}
        self.assertIn("workload", categories)
        self.assertIn("consensus", categories)
        self.assertIn("configuration", categories)

    def test_capped_at_200(self):
        base = datetime(2024, 1, 1)
        events = [
            self._make_event("LEAF_OFFLINE", (base + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"), str(i))
            for i in range(249)
        ]
        result = extract_node_events(events)
        self.assertLessEqual(len(result), 200)

    def test_normalizes_field_names(self):
        event = {
            "EVENT": "AGGREGATOR_FAIL",
            "TIMESTAMP": "2024-01-01 10:00:00",
            "SEVERITY": "CRITICAL",
            "NODE_ID": "42",
            "DESCRIPTION": "node unreachable",
        }
        result = extract_node_events([event])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["node_id"], "42")
        self.assertEqual(result[0]["category"], "node_down")


class TestExtractRebalanceEvents(unittest.TestCase):
    """Tests for extract_rebalance_events helper."""

    def _make_event(self, event_type, event_time="2024-01-01 00:00:00", node_id="1"):
        return {
            "EVENT_TYPE": event_type,
            "EVENT_TIME": event_time,
            "SEVERITY": "INFO",
            "ORIGIN_NODE_ID": node_id,
            "EVENT_DESCRIPTION": "",
        }

    def test_empty_inputs(self):
        result = extract_rebalance_events([], [])
        self.assertEqual(result["status"], "IDLE")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["raw_status"], [])

    def test_filters_non_rebalance_events(self):
        events = [self._make_event("BACKUP_START"), self._make_event("LEAF_OFFLINE")]
        result = extract_rebalance_events(events, [])
        self.assertEqual(result["events"], [])

    def test_rebalance_event_included(self):
        events = [self._make_event("REBALANCE_START")]
        result = extract_rebalance_events(events, [])
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["event_type"], "REBALANCE_START")

    def test_rebalance_started_finished_enums(self):
        events = [
            self._make_event("REBALANCE_STARTED"),
            self._make_event("REBALANCE_FINISHED"),
        ]
        result = extract_rebalance_events(events, [])
        self.assertEqual(len(result["events"]), 2)
        types = {e["event_type"] for e in result["events"]}
        self.assertEqual(types, {"REBALANCE_STARTED", "REBALANCE_FINISHED"})

    def test_partition_move_event_included(self):
        events = [self._make_event("PARTITION_MOVE_COMPLETE")]
        result = extract_rebalance_events(events, [])
        self.assertEqual(len(result["events"]), 1)

    def test_status_active_from_raw_status(self):
        rs = [{"Status": "in progress"}]
        result = extract_rebalance_events([], rs)
        self.assertEqual(result["status"], "ACTIVE")

    def test_status_failed_from_raw_status(self):
        rs = [{"Status": "rebalance failed"}]
        result = extract_rebalance_events([], rs)
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("failed", result["reason"])

    def test_status_active_inferred_from_recent_event(self):
        events = [self._make_event("REBALANCE_START")]
        result = extract_rebalance_events(events, [])
        self.assertEqual(result["status"], "ACTIVE")

    def test_status_idle_when_most_recent_event_is_complete(self):
        events = [
            self._make_event("REBALANCE_COMPLETE", "2024-01-02 00:00:00"),
            self._make_event("REBALANCE_START", "2024-01-01 00:00:00"),
        ]
        result = extract_rebalance_events(events, [])
        self.assertEqual(result["status"], "IDLE")

    def test_events_capped_at_100(self):
        base = datetime(2024, 1, 1)
        events = [
            self._make_event("PARTITION_SYNC", (base + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"), str(i))
            for i in range(1, 120)
        ]
        result = extract_rebalance_events(events, [])
        self.assertLessEqual(len(result["events"]), 100)

    def test_raw_status_capped_at_50(self):
        rs = [{"Status": "idle"} for _ in range(60)]
        result = extract_rebalance_events([], rs)
        self.assertLessEqual(len(result["raw_status"]), 50)

    def test_deduplication(self):
        evt = self._make_event("REBALANCE_START", "2024-01-01 00:00:00", "1")
        result = extract_rebalance_events([evt, evt.copy()], [])
        self.assertEqual(len(result["events"]), 1)

    def test_events_sorted_newest_first(self):
        events = [
            self._make_event("REBALANCE_START", "2024-01-01 00:00:00"),
            self._make_event("PARTITION_MOVE", "2024-01-03 00:00:00"),
        ]
        result = extract_rebalance_events(events, [])
        self.assertGreater(result["events"][0]["event_time"], result["events"][1]["event_time"])


class TestParseDfAccuracy(unittest.TestCase):
    """Tests for the rewritten parse_df that handles both df variants and
    mount paths with spaces."""

    def _write_df(self, content):
        root = Path(tempfile.mkdtemp(prefix="s2rs_df_"))
        node = root / "node-MA" / "df"
        node.mkdir(parents=True, exist_ok=True)
        (node / "df_stdout").write_text(content)
        return root / "node-MA"

    def test_standard_df_h_layout(self):
        content = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       100G   85G   15G  85% /var/lib/memsql\n"
            "/dev/sda2       200G  180G   20G  90% /data\n"
        )
        rows = parse_df(str(self._write_df(content)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["mounted_on"], "/var/lib/memsql")
        self.assertEqual(rows[0]["use_pct"], 85)
        self.assertEqual(rows[0]["iuse_pct"], 0)  # no inode column → default 0
        self.assertEqual(rows[1]["mounted_on"], "/data")
        self.assertEqual(rows[1]["use_pct"], 90)

    def test_mount_path_with_spaces(self):
        content = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/sda1       100G   85G   15G  85% /mnt/my data dir\n"
        )
        rows = parse_df(str(self._write_df(content)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mounted_on"], "/mnt/my data dir")

    def test_df_with_inode_column(self):
        content = (
            "Filesystem Inodes IUsed IFree IUse% Mounted on\n"
            "/dev/sda1   1000    10   990    1% /var/lib/memsql\n"
        )
        rows = parse_df(str(self._write_df(content)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mounted_on"], "/var/lib/memsql")
        self.assertEqual(rows[0]["iuse_pct"], 1)
        self.assertEqual(rows[0]["use_pct"], 0)

    def test_combined_df_h_and_i_layout(self):
        """Combined 7-column df (Use% + IUse%) must not zero disk use_pct."""
        content = (
            "Filesystem      Size  Used Avail Use% IUse% Mounted on\n"
            "overlay          75G   20G   55G  27%    1% /\n"
            "/dev/nvme0n1p1   75G   20G   55G  27%    1% /tmp\n"
        )
        rows = parse_df(str(self._write_df(content)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["use_pct"], 27)
        self.assertEqual(rows[0]["iuse_pct"], 1)
        self.assertEqual(rows[0]["mounted_on"], "/")
        self.assertEqual(rows[1]["mounted_on"], "/tmp")  # nosec B108 - literal is df fixture text, not a temp path

    def test_empty_df_returns_empty(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_df_empty_"))
        (root / "node-MA").mkdir(parents=True, exist_ok=True)
        self.assertEqual(parse_df(str(root / "node-MA")), [])

    def test_malformed_line_skipped(self):
        content = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "garbage short line\n"
            "/dev/sda1       100G   85G   15G  85% /data\n"
        )
        rows = parse_df(str(self._write_df(content)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mounted_on"], "/data")


class TestParseLogLinesContinuation(unittest.TestCase):
    """Multi-line stack-trace continuation lines must be preserved on the
    preceding structured entry so backtrace/SIGSEGV detection sees the full
    context instead of just the first line."""

    SAMPLE = (
        "12345 2024-01-10 08:00:00.000 INFO: normal startup\n"
        "12345 2024-01-10 08:00:01.000 FATAL: Segmentation fault\n"
        "Backtrace:\n"
        "  /usr/lib/libmemsql.so(+0x1234) [0x7fff1234]\n"
        "  /usr/lib/libmemsql.so(+0x5678) [0x7fff5678]\n"
        "12345 2024-01-10 08:00:02.000 INFO: recovered\n"
    )

    def test_continuation_appended_to_preceding_entry(self):
        import io
        entries = _parse_log_lines(io.StringIO(self.SAMPLE), "leaf-1", "LEAF", "memsql.log")
        self.assertEqual(len(entries), 3)
        fatal = entries[1]
        self.assertEqual(fatal["severity"], "FATAL")
        self.assertIn("Segmentation fault", fatal["message"])
        self.assertIn("Backtrace:", fatal["message"])
        self.assertIn("libmemsql.so(+0x1234)", fatal["message"])

    def test_continuation_does_not_create_spurious_entries(self):
        import io
        entries = _parse_log_lines(io.StringIO(self.SAMPLE), "leaf-1", "LEAF", "memsql.log")
        # 3 structured header lines → exactly 3 entries (continuations merged)
        self.assertEqual(len(entries), 3)
        # First entry has no continuation
        self.assertEqual(entries[0]["message"], "normal startup")
        # Third entry is the post-recovery INFO line
        self.assertEqual(entries[2]["message"], "recovered")


class TestParseLogLinesTailed(unittest.TestCase):
    """The tailed reader must return the MOST RECENT max_lines entries
    (tail), not the first N — recent diagnostics matter most for triage."""

    def _make_stream(self, n):
        import io
        lines = []
        for i in range(n):
            lines.append(f"{i} 2024-01-10 08:00:{i:02d}.000 INFO: message {i}\n")
        return io.StringIO("".join(lines))

    def test_returns_tail_when_over_cap(self):
        entries = _parse_log_lines_tailed(self._make_stream(100), "n", "LEAF", "memsql.log", max_lines=20)
        self.assertEqual(len(entries), 20)
        # Most recent 20 → messages 80..99
        self.assertEqual(entries[0]["message"], "message 80")
        self.assertEqual(entries[-1]["message"], "message 99")

    def test_returns_all_when_under_cap(self):
        entries = _parse_log_lines_tailed(self._make_stream(5), "n", "LEAF", "memsql.log", max_lines=20)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0]["message"], "message 0")
        self.assertEqual(entries[-1]["message"], "message 4")

    def test_parses_timestamp_without_fractional_seconds(self):
        import io
        stream = io.StringIO("1 2024-01-10 08:00:00 INFO: no fractional seconds\n")
        entries = _parse_log_lines_tailed(stream, "n", "LEAF", "memsql.log", max_lines=5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["timestamp"], "2024-01-10 08:00:00")
        self.assertEqual(entries[0]["message"], "no fractional seconds")

    def test_continuation_preserved_in_tail(self):
        import io
        # 3 structured entries + 1 continuation line on entry 2; cap at 2
        # so only entries 2 and 3 survive, but entry 2 must still carry its
        # continuation text.
        content = (
            "1 2024-01-10 08:00:00.000 INFO: first\n"
            "2 2024-01-10 08:00:01.000 FATAL: boom\n"
            "continuation line for boom\n"
            "3 2024-01-10 08:00:02.000 INFO: third\n"
        )
        entries = _parse_log_lines_tailed(io.StringIO(content), "n", "LEAF", "memsql.log", max_lines=2)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["severity"], "FATAL")
        self.assertIn("continuation line for boom", entries[0]["message"])
        self.assertEqual(entries[1]["message"], "third")


class TestPatternDetectionAccuracy(unittest.TestCase):
    """Verify every defined critical-log and dmesg pattern is correctly
    attributed to its category by detect_log_patterns / classify_dmesg_events.
    Guards against pattern-list regressions where a new entry silently fails
    to match its intended sample text."""

    def test_critical_log_patterns_all_identified(self):
        samples = {
            "oom": "out of memory in memsqld",
            "disk": "No space left on device",
            "replication": "replication link down to leaf-2",
            "crash": "SIGSEGV backtrace received",
            "locking": "lock wait timeout exceeded",
            "columnstore": "failed to merge columnstore blob",
            "network": "ETIMEDOUT connecting to peer",
            "storage": "fsync is behind by 4 seconds",
            "background_tasks": "Retry loop is stalling",
            "compilation": "Failed to finalize asynchronous compilation",
            "backup": "backup failed to S3",
            "restart": "memsqld started, version 8.5.1",
        }
        for expected_cat, msg in samples.items():
            logs = [{"timestamp": "2024-01-01T00:00:00Z", "severity": "ERROR",
                     "message": msg, "hostname": "n1"}]
            result = detect_log_patterns(logs)
            cats = {r["category"] for r in result}
            self.assertIn(expected_cat, cats, f"pattern did not fire for {expected_cat}: {msg}")

    def test_dmesg_patterns_all_identified(self):
        samples = {
            "oom": "Out of memory: Killed process 1234",
            "storage_fault": "EXT4-fs error on device sda1",
            "network": "nf_conntrack: table full, dropping packet",
            "cpu": "soft lockup CPU#0 stuck for 23s",
            "thp": "transparent hugepage enabled",
        }
        for expected_cat, line in samples.items():
            events = classify_dmesg_events([{"line": line, "timestamp": ""}], "n1", "LEAF")
            cats = {e["category"] for e in events}
            self.assertIn(expected_cat, cats, f"dmesg pattern did not fire for {expected_cat}: {line}")

    def test_detect_log_patterns_counts_and_categories(self):
        logs = [
            {"timestamp": "2024-01-01T00:00:00Z", "severity": "ERROR", "message": "out of memory"},
            {"timestamp": "2024-01-01T00:00:01Z", "severity": "ERROR", "message": "out of memory"},
            {"timestamp": "2024-01-01T00:00:02Z", "severity": "ERROR", "message": "disk full"},
            {"timestamp": "2024-01-01T00:00:03Z", "severity": "WARN", "message": "ETIMEDOUT to peer"},
            {"hostname": "node1"},
        ]
        result = detect_log_patterns(logs)
        cats = {r["category"]: r["count"] for r in result}
        self.assertEqual(cats.get("oom"), 2)
        self.assertEqual(cats.get("disk"), 1)
        self.assertEqual(cats.get("network"), 1)

    def test_oom_does_not_match_room_substring(self):
        logs = [{"timestamp": "2024-01-01T00:00:00Z", "severity": "INFO",
                 "message": "entering conference room for maintenance", "hostname": "n1"}]
        self.assertEqual(detect_log_patterns(logs), [])

    def test_deadlock_pattern_detected(self):
        logs = [{"timestamp": "2024-01-01T00:00:00Z", "severity": "ERROR",
                 "message": "deadlock found when trying to get lock", "hostname": "n1"}]
        result = detect_log_patterns(logs)
        self.assertEqual(result[0]["category"], "locking")

    def test_no_match_returns_empty(self):
        logs = [{"timestamp": "2024-01-01T00:00:00Z", "severity": "INFO", "message": "all good"}]
        self.assertEqual(detect_log_patterns(logs), [])


class TestPressureEventsAccuracy(unittest.TestCase):
    """Verify compute_pressure_events_per_hour counts all four event families
    correctly and does not double-count overlapping patterns."""

    def test_all_four_families_counted(self):
        logs = [
            {"timestamp": "2024-01-10 09:00:00.000", "message": "ETIMEDOUT to peer"},
            {"timestamp": "2024-01-10 09:15:00.000", "message": "fsync is behind by 5s"},
            {"timestamp": "2024-01-10 09:30:00.000", "message": "Retry loop is stalling"},
            {"timestamp": "2024-01-10 09:45:00.000", "message": "Database db1 from sync to async"},
        ]
        result = compute_pressure_events_per_hour(logs)
        self.assertEqual(result["etimedout"].get("2024-01-10 09"), 1)
        self.assertEqual(result["fsync_behind"].get("2024-01-10 09"), 1)
        self.assertEqual(result["retry_stall"].get("2024-01-10 09"), 1)
        self.assertEqual(result["async_transition"].get("2024-01-10 09"), 1)

    def test_overlapping_patterns_not_double_counted(self):
        # 'Connection timed out' matches etimedout; ensure it is not also
        # attributed to another family.
        logs = [{"timestamp": "2024-01-10 09:00:00.000", "message": "Connection timed out"}]
        result = compute_pressure_events_per_hour(logs)
        self.assertEqual(sum(sum(v.values()) for v in result.values()), 1)
        self.assertEqual(result["etimedout"].get("2024-01-10 09"), 1)

    def test_async_transition_rejects_broad_replication_async(self):
        self.assertFalse(_is_async_transition_message("async replication is healthy"))
        self.assertFalse(_is_async_transition_message("replication role is async slave"))
        self.assertTrue(_is_async_transition_message("Database db1 from sync to async"))
        self.assertTrue(_is_async_transition_message("Transitioned from sync to async replication"))
        logs = [{"timestamp": "2024-01-10 09:00:00.000", "message": "async replication running"}]
        result = compute_pressure_events_per_hour(logs)
        self.assertEqual(result["async_transition"], {})
        repl = extract_replication_lag_patterns([], [{"message": "async replication running"}])
        self.assertEqual(repl["async_transitions"], 0)
class TestExtractQueryPatterns(unittest.TestCase):
    """Test query pattern detection: slow, runaway, repeated, memory."""

    def test_empty_processlist_returns_empty(self):
        result = extract_query_patterns([])
        self.assertEqual(result["slow_count"], 0)
        self.assertEqual(result["runaway_count"], 0)
        self.assertEqual(result["max_elapsed_sec"], 0.0)
        self.assertEqual(result["slow_queries"], [])
        self.assertEqual(result["runaway_queries"], [])

    def test_slow_query_detected(self):
        rows = [{"ELAPSED_TIME": 45.0, "QUERY_TEXT": "SELECT * FROM users", "USER": "app", "DATABASE_NAME": "prod"}]
        result = extract_query_patterns(rows)
        self.assertEqual(result["slow_count"], 1)
        self.assertEqual(result["runaway_count"], 0)
        self.assertEqual(result["slow_queries"][0]["elapsed_sec"], 45.0)
        self.assertEqual(result["slow_queries"][0]["user"], "app")

    def test_runaway_query_detected(self):
        rows = [{"ELAPSED_TIME": 600.0, "QUERY_TEXT": "SELECT * FROM huge_table", "USER": "etl"}]
        result = extract_query_patterns(rows)
        self.assertEqual(result["runaway_count"], 1)
        self.assertEqual(result["slow_count"], 0)  # runaway excluded from slow
        self.assertEqual(result["runaway_queries"][0]["elapsed_sec"], 600.0)

    def test_repeated_pattern_detected(self):
        rows = [
            {"ELAPSED_TIME": 10.0, "QUERY_TEXT": "SELECT * FROM orders WHERE id = 123"},
            {"ELAPSED_TIME": 12.0, "QUERY_TEXT": "SELECT * FROM orders WHERE id = 456"},
            {"ELAPSED_TIME": 8.0, "QUERY_TEXT": "SELECT * FROM orders WHERE id = 789"},
        ]
        result = extract_query_patterns(rows)
        self.assertEqual(len(result["repeated_patterns"]), 1)
        self.assertEqual(result["repeated_patterns"][0]["count"], 3)

    def test_top_by_memory_sorted(self):
        rows = [
            {"ELAPSED_TIME": 5.0, "QUERY_TEXT": "SELECT 1", "MEMORY_USED_MB": 100},
            {"ELAPSED_TIME": 3.0, "QUERY_TEXT": "SELECT 2", "MEMORY_USED_MB": 500},
            {"ELAPSED_TIME": 7.0, "QUERY_TEXT": "SELECT 3", "MEMORY_USED_MB": 50},
        ]
        result = extract_query_patterns(rows)
        self.assertEqual(result["top_by_memory"][0]["memory_used_mb"], 500.0)
        self.assertEqual(result["top_by_memory"][1]["memory_used_mb"], 100.0)

    def test_max_elapsed_and_total_memory(self):
        rows = [
            {"ELAPSED_TIME": 100.0, "QUERY_TEXT": "SELECT 1", "MEMORY_USED_MB": 200},
            {"ELAPSED_TIME": 50.0, "QUERY_TEXT": "SELECT 2", "MEMORY_USED_MB": 300},
        ]
        result = extract_query_patterns(rows)
        self.assertEqual(result["max_elapsed_sec"], 100.0)
        self.assertEqual(result["total_memory_used_mb"], 500.0)

    def test_queries_from_mv_queries_preferred(self):
        processlist = [{"TIME": "10", "INFO": "SELECT FROM PL", "PLAN_ID": "42"}]
        mv_queries = [{"PLAN_ID": "42", "QUERY_TEXT": "SELECT enriched FROM MV", "MEMORY_USED_MB": 256}]
        result = extract_query_patterns(processlist, mv_queries)
        self.assertEqual(result["slow_count"], 0)
        rows = [{"TIME": "200", "INFO": "SELECT FROM PL", "PLAN_ID": "42"}]
        result = extract_query_patterns(rows, mv_queries)
        self.assertEqual(result["slow_count"], 1)
        self.assertIn("FROM MV", result["slow_queries"][0]["query_text"])

    def test_processlist_time_field_used_for_elapsed(self):
        rows = [{"TIME": "3150", "INFO": "SELECT * FROM big_table", "COMMAND": "Sleep", "USER": "app"}]
        result = extract_query_patterns(rows)
        self.assertEqual(result["runaway_count"], 1)
        self.assertEqual(result["runaway_queries"][0]["elapsed_sec"], 3150.0)

    def test_normalize_sql_replaces_literals(self):
        normalized = _normalize_sql("SELECT * FROM users WHERE id = 123 AND name = 'john'")
        self.assertNotIn("123", normalized)
        self.assertNotIn("'john'", normalized)
        self.assertIn("?", normalized)

    def test_normalize_sql_empty(self):
        self.assertEqual(_normalize_sql(""), "")
        self.assertEqual(_normalize_sql(None), "")

    def test_safe_float_val_handles_edge_cases(self):
        self.assertEqual(_safe_float_val(None), 0.0)
        self.assertEqual(_safe_float_val("not_a_number"), 0.0)
        self.assertEqual(_safe_float_val("42"), 42.0)
        self.assertEqual(_safe_float_val(3.14), 3.14)


class TestExtractQueryAnalysis(unittest.TestCase):
    """query_analysis payload for WorkloadQueries patterns tab."""

    def test_empty_inputs(self):
        result = extract_query_analysis([], {}, [])
        self.assertEqual(result["summary"]["long_running_count"], 0)
        self.assertEqual(result["long_running"], [])

    def test_long_running_from_processlist(self):
        rows = [{"TIME": "120", "INFO": "SELECT slow", "USER": "app", "HOST": "10.0.0.1", "DATABASE_NAME": "db1", "ID": "9"}]
        result = extract_query_analysis(rows, {}, [])
        self.assertEqual(result["summary"]["long_running_count"], 1)
        self.assertEqual(result["long_running"][0]["time_sec"], 120.0)
        self.assertEqual(result["long_running"][0]["connection_id"], "9")

    def test_runaway_patterns_from_query_patterns(self):
        qp = {
            "runaway_queries": [
                {"elapsed_sec": 400, "query_text": "SELECT COUNT(*) FROM t", "normalized": "select count(*) from t"},
            ],
            "repeated_patterns": [],
        }
        result = extract_query_analysis([], qp, [])
        self.assertEqual(result["summary"]["runaway_pattern_count"], 1)
        self.assertIn("select count", result["runaway_patterns"][0]["fingerprint"])

    def test_lock_holders_from_blocked_queries(self):
        blocked = [{"BLOCKED_QUERY_TEXT": "UPDATE t SET x=1", "BLOCKING_TYPE": "row lock", "BLOCKED_QUERY_ID": "55"}]
        result = extract_query_analysis([], {}, blocked)
        self.assertEqual(result["summary"]["lock_holder_count"], 1)
        self.assertIn("UPDATE", result["lock_holders"][0]["query_preview"])


class TestDmesgCollectorStatus(unittest.TestCase):
    def test_stderr_only_marked_unavailable_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            dmesg_dir = Path(tmp) / "dmesg"
            dmesg_dir.mkdir()
            (dmesg_dir / "dmesg_stderr").write_text("dmesg: read kernel buffer failed\n", encoding="utf-8")
            status = _dmesg_collector_status(tmp)
        self.assertTrue(status["stderr_only"])
        self.assertFalse(status["stdout"])

    def test_stdout_available_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            dmesg_dir = Path(tmp) / "dmesg"
            dmesg_dir.mkdir()
            (dmesg_dir / "dmesg_stdout").write_text("[123.0] Out of memory: Killed process 99\n", encoding="utf-8")
            status = _dmesg_collector_status(tmp)
        self.assertTrue(status["stdout"])
        self.assertFalse(status["stderr_only"])
        self.assertTrue(status["available"])


class TestExtractReplicationLagPatterns(unittest.TestCase):
    """Test replication lag detection and async transitions."""

    def test_empty_replication_status(self):
        result = extract_replication_lag_patterns([])
        self.assertEqual(result["replication_state"], "healthy")
        self.assertEqual(result["max_lag_sec"], 0.0)
        self.assertEqual(result["lagging_count"], 0)

    def test_healthy_lag(self):
        rows = [{"LAG_SECONDS": 2.0, "MasterHost": "m1", "SlaveHost": "s1"}]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["replication_state"], "healthy")
        self.assertEqual(result["lagging_count"], 0)

    def test_lsn_position_delta_used_when_lag_seconds_missing(self):
        rows = [{
            "Master_CommitLSN": "0:142",
            "Slave_CommitLSN": "0:120",
            "Master_URI": "m1",
            "Slave_URI": "s1",
            "Role": "async slave",
            "Connected": "yes",
            "Slave_State": "replicating",
        }]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["lagging_count"], 1)
        self.assertEqual(result["lagging_pairs"][0]["lag_sec"], 22.0)
        self.assertEqual(result["replication_state"], "degraded")

    def test_disconnected_replication_flagged_critical(self):
        rows = [{
            "Master_CommitLSN": "0:10",
            "Slave_CommitLSN": "0:10",
            "Connected": "no",
            "Slave_State": "replicating",
            "Master_URI": "m1",
            "Slave_URI": "s1",
        }]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["lagging_count"], 1)
        self.assertEqual(result["lagging_pairs"][0]["severity"], "critical")

    def test_degraded_lag(self):
        rows = [{"LAG_SECONDS": 15.0, "MasterHost": "m1", "SlaveHost": "s1"}]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["replication_state"], "degraded")
        self.assertEqual(result["lagging_count"], 1)
        self.assertEqual(result["lagging_pairs"][0]["lag_sec"], 15.0)
        self.assertEqual(result["lagging_pairs"][0]["severity"], "warning")

    def test_critical_lag(self):
        rows = [{"LAG_SECONDS": 45.0, "MasterHost": "m1", "SlaveHost": "s1"}]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["replication_state"], "critical")
        self.assertEqual(result["lagging_pairs"][0]["severity"], "critical")

    def test_avg_lag_calculated(self):
        rows = [
            {"LAG_SECONDS": 10.0, "MasterHost": "m1", "SlaveHost": "s1"},
            {"LAG_SECONDS": 20.0, "MasterHost": "m2", "SlaveHost": "s2"},
        ]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["avg_lag_sec"], 15.0)

    def test_async_transitions_from_log_patterns(self):
        log_patterns = [{"message": "Transitioned from sync to async replication"}]
        result = extract_replication_lag_patterns([], log_patterns)
        self.assertEqual(result["async_transitions"], 1)
        self.assertEqual(result["replication_state"], "critical")

    def test_workload_throttle_events_from_mv_events(self):
        events = [
            {"EVENT_TYPE": "WORKLOAD_THROTTLE", "EVENT_TIME": "2024-01-01 00:00:00"},
            {"EVENT_TYPE": "WORKLOAD_THROTTLE", "EVENT_TIME": "2024-01-01 00:01:00"},
            {"EVENT_TYPE": "NODE_ONLINE", "EVENT_TIME": "2024-01-01 00:02:00"},
        ]
        result = extract_replication_lag_patterns([], [], events)
        self.assertEqual(result["workload_throttle_events"], 2)
        self.assertEqual(result["replication_state"], "critical")

    def test_lagging_pairs_sorted_by_lag_desc(self):
        rows = [
            {"LAG_SECONDS": 10.0, "MasterHost": "m1", "SlaveHost": "s1"},
            {"LAG_SECONDS": 50.0, "MasterHost": "m2", "SlaveHost": "s2"},
            {"LAG_SECONDS": 8.0, "MasterHost": "m3", "SlaveHost": "s3"},
        ]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["lagging_pairs"][0]["lag_sec"], 50.0)
        self.assertEqual(result["lagging_pairs"][1]["lag_sec"], 10.0)
        self.assertEqual(result["lagging_pairs"][2]["lag_sec"], 8.0)

    def test_negative_lag_skipped(self):
        rows = [
            {"LAG_SECONDS": -1.0, "MasterHost": "m1", "SlaveHost": "s1"},
            {"LAG_SECONDS": 12.0, "MasterHost": "m2", "SlaveHost": "s2"},
        ]
        result = extract_replication_lag_patterns(rows)
        self.assertEqual(result["lagging_count"], 1)  # only the 12s one


class TestExtractMemoryUtilizationTrend(unittest.TestCase):
    """Test per-node memory utilization trend analysis."""

    def test_empty_nodes_returns_empty(self):
        result = extract_memory_utilization_trend([], {})
        self.assertEqual(result["per_node"], {})
        self.assertEqual(result["cluster_summary"]["avg_engine_used_pct"], 0.0)
        self.assertEqual(result["cluster_summary"]["nodes_over_90pct"], 0)

    def test_healthy_node(self):
        nodes = [{"hostname": "node1", "free": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25}}]
        overview = {"nodes_detail": [{"ip_addr": "node1", "memory_used_mb": 4000, "max_memory_mb": 16000}]}
        result = extract_memory_utilization_trend(nodes, overview)
        self.assertEqual(result["per_node"]["node1"]["engine_used_pct"], 25.0)
        self.assertEqual(result["per_node"]["node1"]["status"], "healthy")

    def test_metrics_memory_used_when_free_alias_missing(self):
        nodes = [{"hostname": "node1", "metrics": {"memory": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25}}}]
        overview = {"nodes_detail": [{"ip_addr": "node1", "memory_used_mb": 4000, "max_memory_mb": 16000}]}
        result = extract_memory_utilization_trend(nodes, overview)
        self.assertEqual(result["per_node"]["node1"]["os_total_mb"], 16000.0)
        self.assertEqual(result["per_node"]["node1"]["os_used_pct"], 25.0)

    def test_warning_node_over_80pct(self):
        nodes = [{"hostname": "node1", "free": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25}}]
        overview = {"nodes_detail": [{"ip_addr": "node1", "memory_used_mb": 13000, "max_memory_mb": 16000}]}
        result = extract_memory_utilization_trend(nodes, overview)
        self.assertEqual(result["per_node"]["node1"]["status"], "warning")
        self.assertEqual(result["cluster_summary"]["nodes_over_80pct"], 1)
        self.assertEqual(result["cluster_summary"]["nodes_over_90pct"], 0)

    def test_critical_node_over_90pct(self):
        nodes = [{"hostname": "node1", "free": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25}}]
        overview = {"nodes_detail": [{"ip_addr": "node1", "memory_used_mb": 15000, "max_memory_mb": 16000}]}
        result = extract_memory_utilization_trend(nodes, overview)
        self.assertEqual(result["per_node"]["node1"]["status"], "critical")
        self.assertEqual(result["cluster_summary"]["nodes_over_90pct"], 1)

    def test_swap_usage_detected(self):
        nodes = [{"hostname": "node1", "free": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25, "swap_total_mb": 8000, "swap_used_mb": 600, "swap_used_pct": 7.5}}]
        overview = {"nodes_detail": [{"ip_addr": "node1", "memory_used_mb": 4000, "max_memory_mb": 16000}]}
        result = extract_memory_utilization_trend(nodes, overview)
        self.assertEqual(result["per_node"]["node1"]["swap_used_pct"], 7.5)
        self.assertEqual(result["per_node"]["node1"]["status"], "warning")  # swap 5-10% = warning per Toolbox

    def test_table_vs_non_table_memory(self):
        nodes = [{"hostname": "node1", "free": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25}}]
        overview = {"nodes_detail": [{"ip_addr": "node1", "memory_used_mb": 10000, "max_memory_mb": 16000, "table_memory_used_mb": 7000}]}
        result = extract_memory_utilization_trend(nodes, overview)
        self.assertEqual(result["per_node"]["node1"]["table_memory_mb"], 7000.0)
        self.assertEqual(result["per_node"]["node1"]["non_table_memory_mb"], 3000.0)

    def test_highest_utilization_node_tracked(self):
        nodes = [
            {"hostname": "node1", "free": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25}},
            {"hostname": "node2", "free": {"total_mb": 16000, "used_mb": 4000, "used_pct": 25}},
        ]
        overview = {"nodes_detail": [
            {"ip_addr": "node1", "memory_used_mb": 8000, "max_memory_mb": 16000},
            {"ip_addr": "node2", "memory_used_mb": 14000, "max_memory_mb": 16000},
        ]}
        result = extract_memory_utilization_trend(nodes, overview)
        self.assertEqual(result["cluster_summary"]["highest_utilization_node"], "node2")
        self.assertAlmostEqual(result["cluster_summary"]["highest_utilization_pct"], 87.5, places=1)


class TestStreamingJsonRows(unittest.TestCase):
    def test_stream_extract_rows_caps_without_full_load(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_stream_json_"))
        payload = {
            "memsql-1": {
                "Pipelines": {
                    "rows": [{"PIPELINE_NAME": f"p{i}", "STATE": "Running"} for i in range(120)]
                }
            }
        }
        fpath = root / "informationSchemaPipelines.json"
        fpath.write_text(json.dumps(payload))
        rows = _stream_extract_rows_from_json_file(str(fpath), 25)
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[0]["PIPELINE_NAME"], "p0")

    def test_parse_sdb_json_table_streams_oversized_file(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_stream_table_"))
        node = root / "node-MA"
        node.mkdir()
        rows_data = [{"PIPELINE_NAME": f"pipe-{i}", "STATE": "Running"} for i in range(80)]
        payload = {"id1": {"Pipelines": {"rows": rows_data}}}
        (node / "informationSchemaPipelines.json").write_text(json.dumps(payload))
        # Shrink limit so the loader must stream
        import parsers as parsers_mod
        old = parsers_mod.MAX_JSON_FILE_BYTES_BY_NAME.get("informationSchemaPipelines.json")
        parsers_mod.MAX_JSON_FILE_BYTES_BY_NAME["informationSchemaPipelines.json"] = 512
        try:
            rows = parse_sdb_json_table(str(node), "informationSchemaPipelines.json")
            self.assertGreater(len(rows), 0)
            self.assertLessEqual(len(rows), parsers_mod.MAX_PIPELINES_ROWS)
            self.assertEqual(rows[0]["PIPELINE_NAME"], "pipe-0")
        finally:
            if old is None:
                parsers_mod.MAX_JSON_FILE_BYTES_BY_NAME.pop("informationSchemaPipelines.json", None)
            else:
                parsers_mod.MAX_JSON_FILE_BYTES_BY_NAME["informationSchemaPipelines.json"] = old


class TestSubsystemTracelogCoverage(unittest.TestCase):
    def test_subsystem_log_filenames_match(self):
        self.assertTrue(_is_tracelog_file("Leaf-3306-ABC_memsql_NETWORK.log"))
        self.assertTrue(_is_tracelog_file("Leaf-3306-ABC_memsql.log"))
        self.assertFalse(_is_tracelog_file("startup.log"))


class TestExtractLongRunningTransactions(unittest.TestCase):
    """Test long-running transaction and lock contention detection."""

    def test_empty_processlist(self):
        result = extract_long_running_transactions([])
        self.assertEqual(result["long_tx_count"], 0)
        self.assertEqual(result["lock_contention_level"], "none")

    def test_long_running_tx_detected(self):
        rows = [{"Time": 120, "TRX_STATE": "running", "Info": "UPDATE large_table SET x=1", "USER": "app"}]
        result = extract_long_running_transactions(rows)
        self.assertEqual(result["long_tx_count"], 1)
        self.assertEqual(result["max_tx_duration_sec"], 120.0)
        self.assertEqual(result["lock_contention_level"], "moderate")

    def test_short_tx_not_detected(self):
        rows = [{"Time": 30, "TRX_STATE": "running", "Info": "SELECT 1"}]
        result = extract_long_running_transactions(rows)
        self.assertEqual(result["long_tx_count"], 0)

    def test_lock_waiting_detected(self):
        rows = [{"Time": 10, "LOCK_STATUS": "waiting", "Info": "SELECT * FROM t", "USER": "app"}]
        result = extract_long_running_transactions(rows)
        self.assertEqual(result["lock_waiting_count"], 1)
        self.assertEqual(result["lock_contention_level"], "moderate")

    def test_severe_contention_from_large_chain(self):
        blocked = [{"blocking_query_id": "q1"}] * 15
        result = extract_long_running_transactions([], blocked)
        self.assertEqual(result["largest_chain_size"], 15)
        self.assertEqual(result["lock_contention_level"], "severe")

    def test_unkillable_detected(self):
        blocked = [{"blocking_query_id": "q1", "kill_status": "unkillable"}]
        result = extract_long_running_transactions([], blocked)
        self.assertTrue(result["has_unkillable"])
        self.assertEqual(result["lock_contention_level"], "severe")

    def test_multiple_blocking_chains_counted(self):
        blocked = [
            {"blocking_query_id": "q1"}, {"blocking_query_id": "q1"},
            {"blocking_query_id": "q2"}, {"blocking_query_id": "q2"}, {"blocking_query_id": "q2"},
        ]
        result = extract_long_running_transactions([], blocked)
        self.assertEqual(result["blocking_chains"], 2)
        self.assertEqual(result["largest_chain_size"], 3)


class TestExtendedDiagnostics(unittest.TestCase):
    """Colleague-dashboard parity extractors."""

    def test_extract_compilation_times(self):
        logs = [{
            "hostname": "leaf-1",
            "timestamp": "2024-06-15T10:30:00",
            "message": (
                "Query 0.'SELECT * FROM t' submitted 100 milliseconds ago, "
                "queued for 50 milliseconds, compiled asynchronously in 5000 milliseconds"
            ),
        }]
        result = extract_compilation_times(logs)
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["max_compiled_ms"], 5000)
        self.assertEqual(result["samples"][0]["compiled_ms"], 5000)

    def test_extract_heartbeat_failures(self):
        logs = [
            {"hostname": "ma-1", "timestamp": "2024-06-15T11:00:00", "message": "HeartbeatConnectionFailure to leaf"},
            {"hostname": "leaf-1", "timestamp": "2024-06-15T11:05:00", "message": "ProcessNetworkEvents Heartbeat connection error"},
        ]
        result = extract_heartbeat_failures(logs)
        self.assertEqual(result["failure_count"], 2)
        self.assertEqual(sorted(result["nodes_affected"]), ["leaf-1", "ma-1"])

    def test_extract_table_skew_analytics(self):
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "skewed", "HOST": "h1", "ROWS": 1000, "MEMORY_USE": 100},
            {"DATABASE_NAME": "db", "TABLE_NAME": "skewed", "HOST": "h2", "ROWS": 100, "MEMORY_USE": 10},
            {"DATABASE_NAME": "db", "TABLE_NAME": "skewed", "HOST": "h3", "ROWS": 50, "MEMORY_USE": 5},
        ]
        result = extract_table_skew_analytics(stats)
        self.assertEqual(result["summary"]["table_count"], 1)
        self.assertGreater(result["table_skew"][0]["row_skew_cv_pct"], 50)

    def test_table_skew_cv_is_exact_population_cv(self):
        # Population CV for rows [1000, 100, 50]: std/mean * 100 ≈ 113.9%.
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "h1", "ROWS": 1000, "MEMORY_USE": 0},
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "h2", "ROWS": 100, "MEMORY_USE": 0},
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "h3", "ROWS": 50, "MEMORY_USE": 0},
        ]
        result = extract_table_skew_analytics(stats)
        self.assertAlmostEqual(result["table_skew"][0]["row_skew_cv_pct"], 113.9, delta=0.1)

    def test_table_skew_uniform_table_has_zero_row_skew(self):
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "even", "HOST": "h1", "ROWS": 500, "MEMORY_USE": 2 * 1024 * 1024},
            {"DATABASE_NAME": "db", "TABLE_NAME": "even", "HOST": "h2", "ROWS": 500, "MEMORY_USE": 1 * 1024 * 1024},
        ]
        result = extract_table_skew_analytics(stats)
        row = result["table_skew"][0]
        self.assertEqual(row["row_skew_cv_pct"], 0.0)
        self.assertEqual(row["partition_count"], 2)
        # MEMORY_USE is bytes; 2 MiB + 1 MiB must report as 3.0 MB, not raw bytes.
        self.assertAlmostEqual(row["total_memory_mb"], 3.0, delta=0.05)

    def test_table_skew_small_memory_reports_megabytes_not_bytes(self):
        # Regression: a sub-1MB table previously reported raw byte counts as MB.
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "tiny", "HOST": "h1", "ROWS": 10, "MEMORY_USE": 524_288},
            {"DATABASE_NAME": "db", "TABLE_NAME": "tiny", "HOST": "h2", "ROWS": 10, "MEMORY_USE": 262_144},
        ]
        result = extract_table_skew_analytics(stats)
        # 524288 + 262144 bytes = 0.75 MiB, must be < 1 MB (not ~786432 "MB").
        self.assertLess(result["table_skew"][0]["total_memory_mb"], 1.0)
        self.assertAlmostEqual(result["host_skew"][0]["total_memory_mb"], 0.5, delta=0.01)

    def test_host_skew_counts_empty_data_hosts(self):
        # An empty leaf (0 rows) among loaded hosts is genuine imbalance and must
        # raise host_row_cv_pct rather than being silently dropped.
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "loaded", "ROWS": 1000, "MEMORY_USE": 1024 * 1024},
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "empty", "ROWS": 0, "MEMORY_USE": 0},
        ]
        result = extract_table_skew_analytics(stats)
        self.assertEqual(result["summary"]["host_count"], 2)
        # rows [1000, 0] -> mean 500, std 500 -> CV = 100%.
        self.assertAlmostEqual(result["summary"]["host_row_cv_pct"], 100.0, delta=0.1)

    def test_idle_leaf_from_topology_counts_toward_host_skew(self):
        # h3 is a known leaf that owns no partitions, so it never appears in
        # TABLE_STATISTICS. With the topology leaf set it must be seeded as idle.
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "h1", "ROWS": 1000, "MEMORY_USE": 0},
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "h2", "ROWS": 1000, "MEMORY_USE": 0},
        ]
        result = extract_table_skew_analytics(stats, leaf_hosts=["h1", "h2", "h3"])
        self.assertEqual(result["summary"]["idle_leaf_hosts"], 1)
        self.assertEqual(result["summary"]["host_count"], 3)
        # Without the idle leaf the two loaded hosts are balanced (CV 0); h3 lifts it.
        self.assertGreater(result["summary"]["host_row_cv_pct"], 0)
        self.assertIn("h3", [h["host"] for h in result["host_skew"]])

    def test_idle_leaf_seeding_skipped_on_host_namespace_mismatch(self):
        # Topology reports hostnames but TABLE_STATISTICS uses IPs -> no overlap,
        # so we must NOT fabricate phantom idle leaves.
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "10.0.0.1", "ROWS": 500, "MEMORY_USE": 0},
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "10.0.0.2", "ROWS": 500, "MEMORY_USE": 0},
        ]
        result = extract_table_skew_analytics(stats, leaf_hosts=["leaf-a", "leaf-b", "leaf-c"])
        self.assertEqual(result["summary"]["idle_leaf_hosts"], 0)
        self.assertEqual(result["summary"]["host_count"], 2)

    def test_idle_leaf_matching_ignores_port_suffix(self):
        # Topology host "h1:3306" must match TABLE_STATISTICS host "h1" (no phantom idle).
        stats = [
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "h1", "ROWS": 100, "MEMORY_USE": 0},
            {"DATABASE_NAME": "db", "TABLE_NAME": "t", "HOST": "h1", "ROWS": 100, "MEMORY_USE": 0},
        ]
        result = extract_table_skew_analytics(stats, leaf_hosts=["h1:3306"])
        self.assertEqual(result["summary"]["idle_leaf_hosts"], 0)
        self.assertEqual(result["summary"]["host_count"], 1)

    def test_build_log_error_timeline(self):
        summary = {
            "hourly": {
                "2024-06-15T10": {"ERROR": 5, "FATAL": 1, "INFO": 100},
                "2024-06-15T11": {"ERROR": 2},
            },
        }
        result = build_log_error_timeline(summary)
        self.assertEqual(result["total_errors"], 8)
        self.assertEqual(len(result["timeline"]), 2)

    def test_build_extended_diagnostics_shape(self):
        result = build_extended_diagnostics([], [], {}, [], {"dmesg": {"nodes_total": 1}})
        self.assertIn("compilation_times", result)
        self.assertIn("pipeline_diagnostics", result)
        self.assertIn("table_skew", result)
        self.assertIn("mv_events_timeline", result)
        self.assertIn("cpu_health", result)
        self.assertIn("sysinfo_network", result)
        self.assertEqual(result["collector_availability"]["dmesg"]["nodes_total"], 1)

    def test_build_mv_events_timeline(self):
        events = [
            {"ORIGIN_NODE_ID": "1", "EVENT_TIME": "2024-06-15T10:00:00", "SEVERITY": "ERROR", "EVENT_TYPE": "NODE_FAIL", "DETAILS": "down"},
            {"ORIGIN_NODE_ID": "2", "EVENT_TIME": "2024-06-15T11:00:00", "SEVERITY": "NOTICE", "EVENT_TYPE": "NODE_UP", "DETAILS": "up"},
        ]
        result = build_mv_events_timeline(events)
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(sorted(result["nodes"]), ["1", "2"])
        self.assertEqual(result["severity_counts"]["ERROR"], 1)

    def test_extract_cpu_health(self):
        nodes = [{
            "metrics": {
                "sysinfo": {
                    "MV_SYSINFO_CPULIST": [
                        {"NODE_ID": "10", "TOTAL_USED_CUMULATIVE_NS": 700, "IDLE_CUMULATIVE_NS": 300, "CPU_ID": "0",
                         "SOFTIRQ_CUMULATIVE_NS": 50, "IOWAIT_CUMULATIVE_NS": 20, "STEAL_CUMULATIVE_NS": 0},
                        {"NODE_ID": "11", "TOTAL_USED_CUMULATIVE_NS": 200, "IDLE_CUMULATIVE_NS": 800, "CPU_ID": "0",
                         "SOFTIRQ_CUMULATIVE_NS": 5, "IOWAIT_CUMULATIVE_NS": 2, "STEAL_CUMULATIVE_NS": 0},
                    ],
                },
            },
        }]
        result = extract_cpu_health(nodes)
        self.assertEqual(result["summary"]["node_count"], 2)
        self.assertEqual(len(result["per_node"]), 2)
        self.assertGreater(result["per_node"][0]["leaf_util_pct"], result["per_node"][1]["leaf_util_pct"])

    def test_extract_sysinfo_network_health(self):
        nodes = [{
            "hostname": "leaf-1.example.com",
            "metrics": {
                "uptime": {"raw": "up 10 days,  2:30,  1 user,  load average: 1.0, 1.0, 1.0"},
                "sysinfo": {
                    "MV_SYSINFO_NET": [
                        {"NODE_ID": "10", "INTERFACE": "eth0", "RECEIVED_CUMULATIVE_B": 10 * 1024 ** 3, "TRANSMITTED_CUMULATIVE_B": 20 * 1024 ** 3},
                        {"NODE_ID": "11", "INTERFACE": "eth0", "RECEIVED_CUMULATIVE_B": 5 * 1024 ** 3, "TRANSMITTED_CUMULATIVE_B": 5 * 1024 ** 3},
                    ],
                },
            },
        }]
        co = {"nodes_detail": [
            {"id": "10", "type": "LEAF", "ip_addr": "leaf-1.example.com"},
            {"id": "11", "type": "LEAF", "ip_addr": "leaf-2.example.com"},
        ]}
        result = extract_sysinfo_network_health(nodes, co)
        self.assertEqual(result["summary"]["node_count"], 2)
        self.assertEqual(len(result["per_node"]), 2)
        self.assertGreater(result["per_node"][0]["total_transmitted_gb"], 15)

    def test_flatten_sysinfo_wrapped_rows(self):
        from parsers import _flatten_sysinfo_value, extract_cpu_health
        wrapped = [{
            "MemsqlID": "abc",
            "columns": ["NODE_ID", "CPU_ID"],
            "rows": [
                {"NODE_ID": "1", "CPU_ID": "0", "TOTAL_USED_CUMULATIVE_NS": 500, "IDLE_CUMULATIVE_NS": 500},
            ],
        }]
        flat = _flatten_sysinfo_value(wrapped)
        self.assertEqual(len(flat), 1)
        self.assertEqual(flat[0]["NODE_ID"], "1")
        nodes = [{"metrics": {"sysinfo": {"MV_SYSINFO_CPULIST": flat}}}]
        cpu = extract_cpu_health(nodes)
        self.assertEqual(cpu["summary"]["node_count"], 1)

    def test_hydrate_extended_diagnostics_from_logs(self):
        payload = {
            "log_summary": {
                "hourly": {"2024-06-15T10": {"ERROR": 3, "INFO": 1}},
            },
            "nodes": [],
            "events": [],
        }
        result = hydrate_extended_diagnostics(payload, all_logs=[])
        self.assertTrue(_extended_diagnostics_populated(result))
        self.assertFalse(_primary_diagnostics_populated(result))
        self.assertEqual(result["log_error_timeline"]["total_errors"], 3)

    def test_hydrate_extended_diagnostics_accepts_wrapped_nodes_detail(self):
        payload = {
            "cluster_overview": {
                "nodes_detail": {
                    "rows": [{"id": "1", "type": "LEAF", "ip_addr": "leaf-1"}],
                },
            },
            "nodes": [
                {
                    "hostname": "leaf-1",
                    "metrics": {
                        "sysinfo": {
                            "MV_SYSINFO_NET": [
                                {
                                    "NODE_ID": "1",
                                    "INTERFACE": "eth0",
                                    "RECEIVED_CUMULATIVE_B": 1024,
                                    "TRANSMITTED_CUMULATIVE_B": 2048,
                                },
                            ],
                        },
                    },
                },
            ],
            "events": [],
        }

        result = hydrate_extended_diagnostics(payload, all_logs=[])

        self.assertIn("table_skew", result)
        self.assertEqual(result["sysinfo_network"]["summary"]["node_count"], 1)

    def test_primary_panels_empty_allows_rehydration(self):
        existing = {
            "mv_events_timeline": {"total_count": 0, "points": []},
            "cpu_health": {"per_node": []},
            "sysinfo_network": {"per_node": []},
            "log_error_timeline": {"total_errors": 42, "timeline": []},
        }
        self.assertTrue(_extended_diagnostics_populated(existing))
        self.assertFalse(_primary_diagnostics_populated(existing))


if __name__ == "__main__":
    unittest.main()
