import unittest

from investigation import _compact_report_signals, _replication_snapshot_lines
from parsers import (
    extract_query_patterns,
    extract_replication_lag_patterns,
    refresh_query_replication_analysis,
)
from superchecker import run_superchecker


class QueryPatternAccuracyTests(unittest.TestCase):
    def test_sleeping_sessions_are_not_queries(self):
        rows = [
            {"ID": "1", "COMMAND": "Sleep", "TIME": "9000", "STATE": "Idle", "INFO": "NULL"},
            {"ID": "2", "COMMAND": "Binlog Dump", "TIME": "8000", "INFO": "replication"},
        ]

        result = extract_query_patterns(rows)

        self.assertEqual(0, result["slow_count"])
        self.assertEqual(0, result["runaway_count"])
        self.assertEqual(0, result["active_query_count"])
        self.assertEqual(2, result["excluded_non_query_rows"])

    def test_only_executing_query_state_age_is_classified(self):
        rows = [
            {"ID": str(i), "COMMAND": "Query", "TIME": str(age), "STATE": "executing",
             "INFO": "SELECT * FROM orders WHERE id = 42"}
            for i, age in enumerate((31, 45, 301), start=1)
        ]

        result = extract_query_patterns(rows)

        self.assertEqual(2, result["slow_count"])
        self.assertEqual(1, result["runaway_count"])
        self.assertEqual("seconds_in_current_processlist_state", result["time_semantics"])
        self.assertEqual("concurrent_instances_in_one_snapshot", result["pattern_scope"])
        self.assertEqual(3, result["repeated_patterns"][0]["count"])

    def test_mv_queries_is_not_used_as_a_timing_source(self):
        result = extract_query_patterns(
            [],
            [{"QUERY_TEXT": "SELECT 1", "ELAPSED_TIME": "999"}],
            snapshot_available=False,
        )

        self.assertEqual("unavailable", result["analysis_state"])
        self.assertEqual(0, result["runaway_count"])

    def test_memory_is_unknown_when_collector_has_no_memory_metric(self):
        result = extract_query_patterns([
            {"ID": "1", "COMMAND": "Query", "TIME": "35", "INFO": "SELECT 1"}
        ])

        self.assertIsNone(result["total_memory_used_mb"])
        self.assertEqual([], result["top_by_memory"])
        self.assertEqual(0, result["memory_measurement_count"])


class ReplicationLagAccuracyTests(unittest.TestCase):
    def test_catchup_estimate_is_not_relabelled_as_lag_seconds(self):
        result = extract_replication_lag_patterns([{
            "PRIMARY_URI": "primary/db",
            "SECONDARY_URI": "secondary/db",
            "PRIMARY_STATE": "online",
            "SECONDARY_STATE": "replicating",
            "LSN_LAG": "500",
            "VOLUME_LAG_MB": "12.5",
            "ESTIMATED_CATCHUP_TIME_S": "90",
        }])

        self.assertIsNone(result["max_lag_sec"])
        self.assertEqual(0, result["measured_lag_count"])
        self.assertEqual(1, result["backlog_pair_count"])
        self.assertEqual("unknown", result["replication_state"])
        self.assertEqual(90.0, result["backlog_pairs"][0]["estimated_catchup_time_sec"])

    def test_direct_lag_seconds_drive_lag_state(self):
        result = extract_replication_lag_patterns([
            {"LAG_SECONDS": "2", "Connected": "yes", "Slave_State": "replicating"},
            {"LAG_SECONDS": "12", "Connected": "yes", "Slave_State": "replicating"},
        ])

        self.assertEqual("degraded", result["replication_state"])
        self.assertEqual(12.0, result["max_lag_sec"])
        self.assertEqual(7.0, result["avg_measured_lag_sec"])
        self.assertEqual(12.0, result["avg_lag_sec"])

    def test_disconnected_link_is_critical_without_invented_lag(self):
        result = extract_replication_lag_patterns([{
            "Connected": "no",
            "Slave_State": "offline",
            "Master_CommitLSN": "0:10",
            "Slave_CommitLSN": "0:5",
        }])

        self.assertEqual("critical", result["replication_state"])
        self.assertIsNone(result["max_lag_sec"])
        self.assertEqual(1, result["connectivity_issue_count"])
        self.assertEqual("connectivity", result["lagging_pairs"][0]["issue_type"])

    def test_explicit_async_count_prevents_double_counting_log_summary(self):
        result = extract_replication_lag_patterns(
            [],
            [{"sample": "transitioned from synchronous to asynchronous", "count": 9}],
            async_transition_count=2,
        )

        self.assertEqual(2, result["async_transitions"])
        self.assertEqual("degraded", result["replication_state"])

    def test_findings_separate_backlog_from_unknown_elapsed_lag(self):
        analysis = extract_replication_lag_patterns([{
            "PRIMARY_URI": "primary/db",
            "SECONDARY_URI": "secondary/db",
            "LSN_LAG": "10",
            "ESTIMATED_CATCHUP_TIME_S": "4",
        }])

        findings = run_superchecker({
            "replication_status": [],
            "replication_lag_patterns": analysis,
        })
        checker_ids = {finding["checker_id"] for finding in findings}

        self.assertIn("replicationBacklogObserved", checker_ids)
        self.assertIn("replicationLagUnknown", checker_ids)
        self.assertNotIn("replicationLagCritical", checker_ids)

    def test_investigation_uses_canonical_state_and_preserves_units(self):
        analysis = extract_replication_lag_patterns([{
            "LSN_LAG": "10",
            "ESTIMATED_CATCHUP_TIME_S": "4",
        }])
        payload = {
            "replication_status": [{}],
            "replication_lag_patterns": analysis,
        }

        signals = _compact_report_signals(payload)
        lines = _replication_snapshot_lines(payload)

        self.assertEqual("unknown", signals["replication_state"])
        self.assertEqual(1, signals["replication_backlog_pair_count"])
        self.assertTrue(any("not converted to elapsed lag" in line for line in lines))

    def test_old_persisted_analysis_is_upgraded_once(self):
        payload = {
            "cluster_overview": {
                "processlist": [
                    {"COMMAND": "Sleep", "TIME": "9000", "INFO": "NULL"},
                ],
            },
            "queries": [],
            "replication_status": [
                {"LSN_LAG": "5", "ESTIMATED_CATCHUP_TIME_S": "2"},
            ],
        }

        self.assertTrue(refresh_query_replication_analysis(payload))
        self.assertEqual(3, payload["analysis_revision"])
        self.assertEqual(0, payload["query_patterns"]["runaway_count"])
        self.assertEqual(0, payload["process_health"]["sleeping_open_tx_count"])
        self.assertEqual(0, payload["query_analysis"]["summary"]["lock_holder_count"])
        self.assertEqual(1, payload["replication_lag_patterns"]["backlog_pair_count"])
        self.assertFalse(refresh_query_replication_analysis(payload))


class OtherAnalyzerAccuracyTests(unittest.TestCase):
    def test_idle_sleep_is_not_an_open_transaction(self):
        from parsers import extract_process_health, extract_query_analysis, extract_long_running_transactions

        rows = [
            {"ID": "1", "COMMAND": "Sleep", "TIME": "198971", "STATE": "Idle",
             "INFO": "NULL", "TRANSACTION_STATE": "NULL"},
            {"ID": "2", "COMMAND": "Query", "TIME": "12", "STATE": "executing",
             "INFO": "SELECT 1", "TRANSACTION_STATE": "running"},
        ]
        health = extract_process_health(rows)
        analysis = extract_query_analysis(rows, {"repeated_patterns": [{"normalized_sql": "select ?", "count": 5, "max_elapsed_sec": 12}]})
        tx = extract_long_running_transactions(rows)

        self.assertEqual(1, health["active_count"])
        self.assertEqual(0, health["sleeping_open_tx_count"])
        self.assertEqual(0, analysis["summary"]["lock_holder_count"])
        self.assertEqual(0, analysis["summary"]["runaway_pattern_count"])
        self.assertEqual(0, tx["long_tx_count"])

    def test_sleeping_open_transaction_requires_transaction_state(self):
        from parsers import extract_process_health

        rows = [{
            "COMMAND": "Sleep", "TIME": "90", "INFO": "SELECT 1",
            "TRANSACTION_STATE": "open",
        }]
        self.assertEqual(1, extract_process_health(rows)["sleeping_open_tx_count"])

    def test_process_health_counts_full_snapshot_but_bounds_details(self):
        from parsers import PROCESSLIST_OVERVIEW_ROWS, extract_process_health

        rows = [
            {
                "ID": str(index),
                "COMMAND": "Query",
                "TIME": str(index + 1),
                "STATE": "executing",
                "INFO": f"SELECT {index}",
            }
            for index in range(PROCESSLIST_OVERVIEW_ROWS + 25)
        ]

        health = extract_process_health(rows)

        self.assertEqual(PROCESSLIST_OVERVIEW_ROWS + 25, health["active_count"])
        self.assertEqual(PROCESSLIST_OVERVIEW_ROWS, len(health["active_queries"]))
        self.assertTrue(health["details_truncated"])

    def test_cluster_layout_does_not_treat_unknown_roles_as_replicas(self):
        from parsers import summarize_cluster_layout

        layout = summarize_cluster_layout([
            {"Host": "leaf-a", "Role": "Master"},
            {"Host": "leaf-b", "Role": "sync slave"},
            {"Host": "leaf-c", "Role": "async slave"},
            {"Host": "", "Role": "Master"},
        ])
        self.assertEqual({"master": 1, "replica": 2, "other": 0}, layout["by_role"])
        self.assertEqual(3, layout["total_partitions"])
        self.assertEqual(1, layout["skipped_rows"])

    def test_cpu_percentages_use_total_since_boot_time(self):
        from parsers import extract_cpu_health

        result = extract_cpu_health([{
            "metrics": {
                "sysinfo": {
                    "MV_SYSINFO_CPULIST": [{
                        "NODE_ID": "1",
                        "TOTAL_USED_CUMULATIVE_NS": "100",
                        "IDLE_CUMULATIVE_NS": "890",
                        "IOWAIT_CUMULATIVE_NS": "10",
                        "SOFTIRQ_CUMULATIVE_NS": "0",
                        "STEAL_CUMULATIVE_NS": "0",
                    }]
                }
            }
        }])
        node = result["per_node"][0]
        self.assertEqual(10.0, node["leaf_util_pct"])
        self.assertEqual(1.0, node["iowait_pct"])
        self.assertEqual("since_boot_cumulative", result["window"])
        self.assertFalse(any("All nodes within normal" in msg for msg in result["insights"]))

    def test_network_excludes_loopback_from_primary_interface(self):
        from parsers import extract_sysinfo_network_health

        result = extract_sysinfo_network_health(
            [{
                "hostname": "10.0.0.1",
                "metrics": {
                    "uptime": {"raw": "up 10 days, 0:00"},
                    "sysinfo": {
                        "MV_SYSINFO_NET": [
                            {"NODE_ID": "1", "INTERFACE": "lo",
                             "RECEIVED_CUMULATIVE_B": str(80 * 1024 ** 3),
                             "TRANSMITTED_CUMULATIVE_B": str(80 * 1024 ** 3)},
                            {"NODE_ID": "1", "INTERFACE": "eth0",
                             "RECEIVED_CUMULATIVE_B": str(5 * 1024 ** 3),
                             "TRANSMITTED_CUMULATIVE_B": str(4 * 1024 ** 3)},
                        ]
                    },
                },
            }],
            {"nodes_detail": [{"id": "1", "type": "LEAF", "ip_addr": "10.0.0.1"}]},
        )
        node = result["per_node"][0]
        self.assertEqual("eth0", node["primary_interface"])
        self.assertEqual(5.0, node["total_received_gb"])
        self.assertFalse(any("Primary interface: lo" in msg for msg in result["insights"]))

    def test_zero_cpu_idle_is_still_a_finding(self):
        findings = run_superchecker({
            "nodes": [{"hostname": "leaf-1", "metrics": {"cpu_utilization": {"idle": 0, "user": 90, "system": 10, "iowait": 0}}}],
        })
        ids = {f["checker_id"] for f in findings}
        self.assertIn("cpuIdle", ids)


if __name__ == "__main__":
    unittest.main()
