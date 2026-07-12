"""Unit tests for query_tracer correlation engine."""
import os
import shutil
import tempfile
import unittest

from query_tracer import (
    compute_trace_id,
    list_query_trace_candidates,
    resolve_query_trace,
    get_query_trace_by_id,
    _infer_partition_routing,
)


def _lock_wait_report() -> dict:
    return {
        "cluster_overview": {
            "processlist": [
                {
                    "ID": "42",
                    "QUERY_TEXT": "SELECT * FROM orders WHERE status = 'pending'",
                    "ELAPSED_TIME": 95.0,
                    "NODE_ID": "10.0.0.3",
                    "State": "Waiting for lock",
                }
            ],
            "blocked_queries": [
                {
                    "BLOCKED_QUERY_ID": "42",
                    "BLOCKED_QUERY_TEXT": "SELECT * FROM orders WHERE status = 'pending'",
                    "BLOCKING_TYPE": "user transaction row lock",
                    "BLOCKED_NODE_ID": "10.0.0.3",
                }
            ],
            "nodes_detail": [
                {"id": 1, "ip_addr": "10.0.0.1", "type": "MA"},
                {"id": 3, "ip_addr": "10.0.0.3", "type": "LEAF"},
            ],
        },
        "queries": [
            {
                "ACTIVITY_NAME": "Select_orders_pending",
                "QUERY_TEXT": "SELECT * FROM orders WHERE status = ?",
                "ELAPSED_TIME": 95.0,
            }
        ],
        "partitions": {"total_partitions": 8},
    }


def _runaway_report() -> dict:
    return {
        "cluster_overview": {
            "processlist": [
                {
                    "ID": "17",
                    "QUERY_TEXT": "SELECT COUNT(*) FROM events WHERE ts > '2024-01-01'",
                    "Time": 420.0,
                    "NODE_ID": "10.0.0.2",
                    "Command": "Query",
                }
            ],
            "blocked_queries": [],
            "nodes_detail": [
                {"id": 1, "ip_addr": "10.0.0.1", "type": "MA"},
                {"id": 2, "ip_addr": "10.0.0.2", "type": "LEAF"},
            ],
        },
        "queries": [],
        "query_patterns": {
            "runaway_queries": [
                {
                    "elapsed_sec": 420.0,
                    "query_text": "SELECT COUNT(*) FROM events WHERE ts > '2024-01-01'",
                    "normalized": "select count(*) from events where ts > ?",
                    "user": "app",
                    "database": "analytics",
                    "node_id": "10.0.0.2",
                }
            ]
        },
        "partitions": {"total_partitions": 4},
    }


class TestQueryTracer(unittest.TestCase):
    def test_compute_trace_id_stable(self):
        tid1 = compute_trace_id("select * from t", connection_id="1", trace_type="runaway")
        tid2 = compute_trace_id("select * from t", connection_id="1", trace_type="runaway")
        self.assertEqual(tid1, tid2)
        self.assertTrue(tid1.startswith("sha256:"))

    def test_list_candidates_lock_wait(self):
        report = _lock_wait_report()
        candidates = list_query_trace_candidates(report)
        self.assertGreaterEqual(len(candidates), 1)
        lock_candidates = [c for c in candidates if c["trace_type"] == "lock_wait"]
        self.assertEqual(len(lock_candidates), 1)
        self.assertEqual(lock_candidates[0]["failure_stage"], "leaf_lock")
        self.assertGreaterEqual(lock_candidates[0]["confidence"]["score"], 50)

    def test_list_candidates_runaway(self):
        report = _runaway_report()
        candidates = list_query_trace_candidates(report)
        runaway = [c for c in candidates if c["trace_type"] == "runaway"]
        self.assertGreaterEqual(len(runaway), 1)
        self.assertEqual(runaway[0]["failure_stage"], "leaf_execute")

    def test_resolve_lock_wait_trace(self):
        report = _lock_wait_report()
        trace = resolve_query_trace(
            report,
            {"connection_id": "42", "query_text": "SELECT * FROM orders WHERE status = 'pending'"},
        )
        self.assertEqual(trace["trace_type"], "lock_wait")
        self.assertIn("confidence", trace)
        self.assertGreater(trace["confidence"]["score"], 0)
        self.assertTrue(any(f["present"] for f in trace["confidence"]["factors"]))
        self.assertIsNotNone(trace["failure"])
        self.assertEqual(trace["failure"]["stage_id"], "leaf_lock")

        stage_ids = [s["id"] for s in trace["stages"]]
        self.assertIn("aggregator_ingress", stage_ids)
        self.assertIn("leaf_lock", stage_ids)

        ingress = next(s for s in trace["stages"] if s["id"] == "aggregator_ingress")
        self.assertTrue(ingress["observed"])
        compile_stage = next(s for s in trace["stages"] if s["id"] == "compile")
        self.assertFalse(compile_stage["observed"])

    def test_resolve_runaway_trace(self):
        report = _runaway_report()
        trace = resolve_query_trace(report, {"connection_id": "17"})
        self.assertEqual(trace["trace_type"], "runaway")
        self.assertEqual(trace["failure"]["category"], "runaway_query")
        leaf = next(s for s in trace["stages"] if s["id"] == "leaf_execute")
        self.assertTrue(leaf["observed"])

    def test_confidence_factor_breakdown(self):
        report = _lock_wait_report()
        trace = resolve_query_trace(report, {"connection_id": "42"})
        factors = trace["confidence"]["factors"]
        factor_ids = {f["id"] for f in factors}
        self.assertIn("connection_id_match", factor_ids)
        self.assertIn("blocked_query_row", factor_ids)
        self.assertIn(trace["confidence"]["tier"], ("low", "medium", "high"))
        self.assertEqual(trace["routing"]["label"], "partitions:single")

    def test_get_query_trace_by_id(self):
        report = _lock_wait_report()
        candidates = list_query_trace_candidates(report)
        trace_id = candidates[0]["trace_id"]
        trace = get_query_trace_by_id(report, trace_id)
        self.assertIsNotNone(trace)
        self.assertEqual(trace["trace_id"], trace_id)

    def test_edges_mark_inferred_routing(self):
        report = _runaway_report()
        trace = resolve_query_trace(report, {"connection_id": "17"})
        route_edge = next(
            e for e in trace["edges"] if e["from"] == "route" and e["to"] in {"distribute", "leaf_execute"}
        )
        self.assertTrue(route_edge["inferred"])
        self.assertIn("partitions:", route_edge["label"])

    def test_infer_partition_routing_equality(self):
        report = {"partitions": {"total_partitions": 8}, "cluster_layout": {"total_partitions": 8}}
        info = _infer_partition_routing(report, "SELECT * FROM orders WHERE status = 'pending'")
        self.assertEqual(info["label"], "partitions:single")
        self.assertEqual(info["confidence"], "medium")
        self.assertIn("status", info["matched_columns"])

    def test_infer_partition_routing_inlist(self):
        report = {"partitions": {"total_partitions": 8}}
        info = _infer_partition_routing(report, "SELECT * FROM orders WHERE id IN (1, 2, 3)")
        self.assertEqual(info["label"], "partitions:inlist")

    def test_resolve_includes_timeline_and_routing(self):
        report = _lock_wait_report()
        report["log_timeframe"] = {"cluster_last": "2024-06-01 12:00:00.000000"}
        trace = resolve_query_trace(report, {"connection_id": "42"})
        self.assertIn("timeline", trace)
        self.assertIn("routing", trace)
        self.assertGreaterEqual(len(trace["timeline"]["lanes"]), 3)
        self.assertEqual(trace["routing"]["label"], "partitions:single")

    def test_distribute_stage_for_fanout(self):
        report = _runaway_report()
        trace = resolve_query_trace(report, {"connection_id": "17"})
        stage_ids = [s["id"] for s in trace["stages"]]
        self.assertIn("distribute", stage_ids)

    def test_log_correlations_affect_leaf_execute_status(self):
        report = _runaway_report()
        report["cluster_overview"]["processlist"][0]["NODE_ID"] = "leaf-a"
        tmp = tempfile.mkdtemp(prefix="s2rs_qtrace_logs_")
        try:
            root = os.path.join(tmp, "report_root")
            node = os.path.join(root, "leaf-a-LEAF")
            os.makedirs(os.path.join(node, "memsqlTracelogs"))
            with open(os.path.join(node, "memsqlTracelogs", "memsql_memsql.log"), "w") as f:
                f.write("1 2024-01-01 00:05:00.000 ERROR: ETIMEDOUT handshake to aggregator\n")

            trace = resolve_query_trace(report, {"connection_id": "17"}, extracted_root=root)
            self.assertGreater(len(trace["log_correlations"]), 0)
            etimedout_hits = [h for h in trace["log_correlations"] if h.get("pattern") == "etimedout"]
            self.assertGreaterEqual(len(etimedout_hits), 1)
            leaf = next(s for s in trace["stages"] if s["id"] == "leaf_execute")
            self.assertEqual(leaf["status"], "critical")
            self.assertTrue(any("tracelog hit" in item.lower() for item in trace.get("evidence_summary", [])))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_wlm_queue_stage_when_queued(self):
        report = _runaway_report()
        report["cluster_overview"]["processlist"][0]["State"] = "Queued in workload management"
        trace = resolve_query_trace(report, {"connection_id": "17"})
        stage_ids = [s["id"] for s in trace["stages"]]
        self.assertIn("wlm_queue", stage_ids)
        self.assertIn("workloadManagementQueue", trace.get("related_findings", []))


if __name__ == "__main__":
    unittest.main()
