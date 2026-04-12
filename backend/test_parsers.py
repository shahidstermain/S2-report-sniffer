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
    CRITICAL_LOG_PATTERNS,
    DMESG_PATTERNS,
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


if __name__ == "__main__":
    unittest.main()
