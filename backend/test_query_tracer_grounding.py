"""Regression tests for query_tracer grounding against documented SingleStore schemas."""
import unittest

import query_tracer as qt


def _report(**overrides):
    report = {
        "cluster_overview": {
            "processlist": [],
            "blocked_queries": [],
            "mv_processlist": [],
            "workload_management": [],
            "nodes_detail": [],
        },
        "queries": [],
        "query_patterns": {},
        "partitions": {},
        "cluster_layout": {},
        "rebalance_events": {"status": "IDLE"},
        "log_timeframe": {},
    }
    report.update(overrides)
    return report


class NodeIdTests(unittest.TestCase):
    def test_processlist_host_is_client_not_node(self):
        row = {"ID": 7, "HOST": "laptop.example.com:52010", "Info": "select 1"}
        self.assertEqual("", qt._node_id(row))
        self.assertEqual("laptop.example.com:52010", qt._client_host(row))

    def test_node_id_uses_documented_columns(self):
        self.assertEqual("3", qt._node_id({"NODE_ID": 3}))
        self.assertEqual("4", qt._node_id({"BLOCKED_NODE_ID": 4}))


class BlockedQuerySchemaTests(unittest.TestCase):
    def test_documented_blocking_columns_are_used(self):
        row = {
            "ID": 11,
            "QUERY_TEXT": "update t set a=1",
            "NODE_ID": 2,
            "BLOCKING_ID": 12,
            "BLOCKING_NODE_ID": 3,
            "BLOCKING_TYPE": "Row lock",
        }
        self.assertEqual("12", qt._blocking_id(row))
        self.assertEqual("3", qt._blocking_node_id(row))
        self.assertEqual("Row lock", qt._blocking_type(row))

    def test_lock_wait_candidate_carries_blocker_identity(self):
        report = _report()
        report["cluster_overview"]["blocked_queries"] = [
            {
                "ID": 11,
                "QUERY_TEXT": "update t set a=1",
                "NODE_ID": 2,
                "BLOCKING_ID": 12,
                "BLOCKING_NODE_ID": 3,
                "BLOCKING_TYPE": "Row lock",
            }
        ]
        candidates = qt.list_query_trace_candidates(report)
        self.assertEqual(1, len(candidates))
        cand = candidates[0]
        self.assertEqual("lock_wait", cand["trace_type"])
        self.assertEqual("12", cand["blocking_query_id"])
        self.assertEqual("3", cand["blocking_node_id"])

    def test_lock_wait_failure_reports_blocker(self):
        report = _report()
        report["cluster_overview"]["blocked_queries"] = [
            {
                "ID": 11,
                "QUERY_TEXT": "update t set a=1",
                "NODE_ID": 2,
                "BLOCKING_ID": 12,
                "BLOCKING_NODE_ID": 3,
                "BLOCKING_TYPE": "Row lock",
            }
        ]
        trace = qt.resolve_query_trace(report, {"query_text": "update t set a=1"})
        self.assertEqual("lock_wait", trace["trace_type"])
        self.assertEqual("12", trace["failure"]["blocking_query_id"])
        self.assertEqual("3", trace["failure"]["blocking_node_id"])


class ElapsedSemanticsTests(unittest.TestCase):
    def test_zero_elapsed_is_not_treated_as_missing(self):
        self.assertEqual(0.0, qt._elapsed_sec({"ELAPSED_TIME": 0, "Time": 42}))

    def test_null_strings_are_skipped(self):
        self.assertEqual(42.0, qt._elapsed_sec({"ELAPSED_TIME": "NULL", "Time": 42}))

    def test_candidate_marks_state_age_semantics(self):
        report = _report()
        report["cluster_overview"]["processlist"] = [
            {"ID": 5, "Command": "Query", "Info": "select sleep(1)", "Time": 400, "State": "executing"}
        ]
        report["query_patterns"] = {
            "runaway_queries": [
                {"query_text": "select sleep(1)", "normalized": "select sleep(?)", "max_elapsed_sec": 400, "user": "u", "database": "d"}
            ]
        }
        candidates = qt.list_query_trace_candidates(report)
        self.assertTrue(candidates)
        self.assertEqual("seconds_in_current_processlist_state", candidates[0]["time_semantics"])


class PartitionRoutingTests(unittest.TestCase):
    def test_unverified_equality_does_not_claim_single_partition(self):
        info = qt._infer_partition_routing(_report(), "select * from t where id = 5")
        self.assertEqual("partitions:unknown", info["label"])
        self.assertEqual("low", info["confidence"])
        self.assertIn("cannot be verified", info["reason"])

    def test_single_partition_cluster_is_high_confidence(self):
        report = _report(partitions={"total_partitions": 1})
        info = qt._infer_partition_routing(report, "select * from t where id = 5")
        self.assertEqual("partitions:single", info["label"])
        self.assertEqual("high", info["confidence"])

    def test_unknown_routing_still_shows_distribute_stage(self):
        report = _report()
        report["cluster_overview"]["processlist"] = [
            {"ID": 5, "Command": "Query", "Info": "select * from t where id = 5", "Time": 1, "State": "executing"}
        ]
        trace = qt.resolve_query_trace(report, {"query_text": "select * from t where id = 5"})
        stage_ids = [s["id"] for s in trace["stages"]]
        self.assertIn("distribute", stage_ids)


class WlmQueueTests(unittest.TestCase):
    def test_reason_for_queueing_column_is_detected(self):
        report = _report()
        report["cluster_overview"]["processlist"] = [
            {"ID": 9, "Command": "Query", "Info": "select 1", "Time": 3, "State": "executing"}
        ]
        report["cluster_overview"]["mv_processlist"] = [
            {"ID": 9, "REASON_FOR_QUEUEING": "Waiting for resources in pool default"}
        ]
        info = qt._detect_wlm_queued(report, report["cluster_overview"]["processlist"][0])
        self.assertTrue(info["queued"])
        self.assertEqual("mv_processlist", info["source"])

    def test_null_reason_for_queueing_is_not_queued(self):
        report = _report()
        row = {"ID": 9, "Command": "Query", "Info": "select 1", "State": "executing", "REASON_FOR_QUEUEING": "NULL"}
        info = qt._detect_wlm_queued(report, row)
        self.assertFalse(info["queued"])


class LogCorrelationScopeTests(unittest.TestCase):
    def test_node_level_hits_do_not_raise_confidence(self):
        hits = [{"pattern": "etimedout", "scope": "node"}]
        flags = qt._log_pattern_flags(hits)
        self.assertTrue(flags["etimedout"])
        # Confidence factor requires query-scoped hit
        report = _report()
        report["cluster_overview"]["processlist"] = [
            {"ID": 5, "Command": "Query", "Info": "select 1", "Time": 400, "State": "executing"}
        ]
        trace = qt.resolve_query_trace(report, {"query_text": "select 1"}, extracted_root=None)
        factor_ids = {f["id"] for f in trace["confidence"]["factors"]}
        self.assertNotIn("tracelog_correlation", factor_ids)


if __name__ == "__main__":
    unittest.main()
