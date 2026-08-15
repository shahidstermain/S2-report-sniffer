"""Tests for the /reports/{id}/logs/search endpoint and its storage backend.

Covers the bugs fixed in the log-search rewrite:
  A. severity filter previously returned zero results (uppercase vs lowercase mismatch)
  B. regex search previously returned zero results (literal substring pre-filter)
  C. case-sensitive flag ignored; timestamp-only keywords missed
  F. `truncated` flag was always False
  G. `nodes_searched` reported the cluster node count, not nodes with matches
"""
import asyncio
import sqlite3
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import server
from server import app
from storage import LocalReportStore


REPORT_ID = "00000000-0000-0000-0000-000000000000"
ALT_REPORT_ID = "11111111-1111-1111-1111-111111111111"

LOG_LINES = [
    {"timestamp": "2024-01-01 00:00:01", "severity": "ERROR", "message": "Connection refused", "hostname": "node-a", "role": "leaf", "source": "memsql.log"},
    {"timestamp": "2024-01-01 00:00:02", "severity": "WARN", "message": "Retry loop is stalling", "hostname": "node-a", "role": "leaf", "source": "memsql.log"},
    {"timestamp": "2024-01-01 00:00:03", "severity": "ERROR", "message": "error timeout contacting peer", "hostname": "node-b", "role": "aggregator", "source": "memsql.log"},
    {"timestamp": "2024-01-01 00:00:04", "severity": "INFO", "message": "backup started normally", "hostname": "node-b", "role": "aggregator", "source": "memsql.log"},
    {"timestamp": "2024-01-01 00:00:05", "severity": "FATAL", "message": "OOM killed", "hostname": "node-c", "role": "leaf", "source": "memsql.log"},
]


def _write_logs(store: LocalReportStore, report_id: str, lines):
    asyncio.run(store.write_report_logs(report_id, lines))


class TestSearchReportLogsStorage(unittest.TestCase):
    """Unit tests for LocalReportStore.search_report_logs (bugs A/B/C/F)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp(prefix="s2rs_logsearch_")
        self.store = LocalReportStore(base_dir=self._tmp)
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        _write_logs(self.store, REPORT_ID, LOG_LINES)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _search(self, **kw):
        kw.setdefault("report_id", REPORT_ID)
        kw.setdefault("keyword", "error")
        kw.setdefault("regex", False)
        kw.setdefault("case_sensitive", False)
        kw.setdefault("severities", None)
        kw.setdefault("node_prefix", None)
        kw.setdefault("limit", 100)
        return asyncio.run(self.store.search_report_logs(**kw))

    def test_plain_keyword_matches_case_insensitively(self):
        # "CONNECTION" (uppercase query) matches "Connection refused" (capital C)
        # case-insensitively. Severity field is not part of the match blob, so
        # querying a severity token like "ERROR" would only hit messages.
        matches, total, _ = self._search(keyword="CONNECTION")
        self.assertEqual(total, 1)
        self.assertEqual(matches[0]["hostname"], "node-a")

    def test_case_sensitive_keyword(self):
        # "ERROR" uppercase appears only as the severity token in the blob for
        # the first line; the third line's message is lowercase "error".
        matches, total, _ = self._search(keyword="Connection", case_sensitive=True)
        self.assertEqual(total, 1)
        self.assertEqual(matches[0]["hostname"], "node-a")

    def test_case_sensitive_excludes_lowercased(self):
        matches, total, _ = self._search(keyword="error", case_sensitive=True)
        # Only the lowercase "error timeout" message matches case-sensitively.
        self.assertEqual(total, 1)
        self.assertEqual(matches[0]["hostname"], "node-b")

    def test_regex_search_returns_matches(self):
        # Bug B: regex previously matched the literal string "error.*timeout".
        matches, total, _ = self._search(keyword="error.*timeout", regex=True)
        self.assertEqual(total, 1)
        self.assertEqual(matches[0]["hostname"], "node-b")

    def test_regex_search_unanchored(self):
        matches, total, _ = self._search(keyword="OOM|stalling", regex=True)
        self.assertEqual(total, 2)

    def test_severity_filter_returns_matches(self):
        # Bug A: severity filter previously dropped every matching row.
        matches, total, _ = self._search(keyword=".*", regex=True, severities=["error"])
        self.assertEqual(total, 2)
        for m in matches:
            self.assertEqual(m["severity"], "ERROR")

    def test_severity_filter_warn_alias(self):
        matches, total, _ = self._search(keyword="stalling", severities=["warn"])
        self.assertEqual(total, 1)
        self.assertEqual(matches[0]["severity"], "WARN")

    def test_severity_filter_excludes_other_severities(self):
        matches, total, _ = self._search(keyword=".*", regex=True, severities=["fatal"])
        self.assertEqual(total, 1)
        self.assertEqual(matches[0]["severity"], "FATAL")

    def test_timestamp_only_keyword_matches(self):
        # Bug C: timestamp was previously excluded from the search blob.
        matches, total, _ = self._search(keyword="2024-01-01 00:00:05", regex=True)
        self.assertEqual(total, 1)
        self.assertEqual(matches[0]["severity"], "FATAL")

    def test_node_prefix_filter(self):
        matches, total, _ = self._search(keyword=".*", regex=True, node_prefix="node-a")
        self.assertEqual(total, 2)
        self.assertTrue(all(m["hostname"] == "node-a" for m in matches))

    def test_truncation_flag(self):
        # Bug F: truncated was always False. Limit below the match count sets it True.
        matches, total, truncated = self._search(keyword=".*", regex=True, limit=2)
        self.assertGreater(total, 2)
        self.assertEqual(len(matches), 2)
        self.assertTrue(truncated)

    def test_truncation_flag_false_when_under_limit(self):
        matches, total, truncated = self._search(keyword=".*", regex=True, limit=100)
        self.assertFalse(truncated)

    def test_time_range_is_applied_before_limit_and_total(self):
        matches, total, truncated = self._search(
            keyword=".*",
            regex=True,
            limit=1,
            start_time=datetime(2024, 1, 1, 0, 0, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(total, 2)
        self.assertEqual(matches[0]["timestamp"], "2024-01-01 00:00:04")
        self.assertTrue(truncated)

    def test_invalid_regex_raises(self):
        with self.assertRaises(ValueError):
            self._search(keyword="[unclosed", regex=True)

    def test_missing_report_returns_empty(self):
        matches, total, truncated = self._search(report_id=ALT_REPORT_ID, keyword="anything")
        self.assertEqual(matches, [])
        self.assertEqual(total, 0)
        self.assertFalse(truncated)

    def test_delete_report_removes_indexed_log_rows(self):
        deleted = asyncio.run(self.store.delete_report(REPORT_ID))

        self.assertTrue(deleted)
        with self.store._store_db() as conn:
            try:
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM report_logs_fts WHERE report_id=?",
                    (REPORT_ID,),
                ).fetchone()[0]
            except sqlite3.OperationalError as exc:
                self.skipTest(f"SQLite FTS5 unavailable: {exc}")
        self.assertEqual(remaining, 0)


class TestSearchReportLogsEndpoint(unittest.TestCase):
    """Endpoint tests for /reports/{id}/logs/search (bugs A/B/G + 400)."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp(prefix="s2rs_logsearch_ep_")
        self._prev_store = server.store
        self.store = LocalReportStore(base_dir=self._tmp)
        server.store = self.store
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        _write_logs(self.store, REPORT_ID, LOG_LINES)

    def tearDown(self):
        server.store = self._prev_store
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _get(self, **params):
        params.setdefault("keyword", "error")
        return self.client.get(f"/api/reports/{REPORT_ID}/logs/search", params=params)

    def test_severity_filter_returns_results(self):
        # Bug A: severity=ERROR previously returned zero matches.
        res = self._get(keyword=".*", regex="true", severity="ERROR")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["total"], 2)
        for m in body["matches"]:
            self.assertEqual(m["severity"], "ERROR")

    def test_severity_warn_alias(self):
        res = self._get(keyword="stalling", severity="WARN")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["total"], 1)

    def test_regex_returns_results(self):
        # Bug B: regex previously returned zero matches.
        res = self._get(keyword="error.*timeout", regex="true")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["total"], 1)

    def test_nodes_searched_counts_only_matching_nodes(self):
        # Bug G: nodes_searched previously reported the total cluster node count.
        res = self._get(keyword=".*", regex="true")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        # Matches span node-a, node-b, node-c (all 5 lines).
        self.assertEqual(body["nodes_searched"], 3)
        self.assertEqual(body["total"], 5)

    def test_nodes_searched_excludes_non_matching_nodes(self):
        res = self._get(keyword="OOM", regex="true")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["nodes_searched"], 1)

    def test_truncated_flag(self):
        # Bug F: truncated previously always False.
        res = self._get(keyword=".*", regex="true", max_results=2)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(len(body["matches"]), 2)
        self.assertTrue(body["truncated"])

    def test_invalid_regex_returns_400(self):
        res = self._get(keyword="[unclosed", regex="true")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["error"], "invalid_regex")

    def test_case_sensitive(self):
        res = self._get(keyword="error", case_sensitive="true", regex="true")
        self.assertEqual(res.status_code, 200)
        # Only the lowercase "error timeout" message matches case-sensitively.
        self.assertEqual(res.json()["total"], 1)

    def test_search_params_echoed(self):
        res = self._get(keyword="OOM", regex="true", severity="FATAL")
        self.assertEqual(res.status_code, 200)
        sp = res.json()["search_params"]
        self.assertEqual(sp["keyword"], "OOM")
        self.assertTrue(sp["regex"])


class TestGetReportLogsNodeFilter(unittest.TestCase):
    """/reports/{id}/logs node filtration — hyphenated hostnames must match.

    Regression: validate_node_filter used to re.escape() the node value, but
    query_report_logs consumes it via str.startswith (literal, not regex), so
    any hostname containing a hyphen/dot returned zero logs.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp(prefix="s2rs_logs_nodefilter_")
        self._prev_store = server.store
        self.store = LocalReportStore(base_dir=self._tmp)
        server.store = self.store
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        asyncio.run(self.store.write_report_logs(REPORT_ID, [
            {"timestamp": "2024-01-01 00:00:01", "severity": "ERROR",
             "message": "Connection refused", "hostname": "node-a-leaf",
             "role": "leaf", "source": "memsql.log"},
            {"timestamp": "2024-01-01 00:00:02", "severity": "WARN",
             "message": "stalling", "hostname": "node-a-leaf",
             "role": "leaf", "source": "memsql.log"},
            {"timestamp": "2024-01-01 00:00:03", "severity": "ERROR",
             "message": "timeout", "hostname": "node-b.example.com",
             "role": "aggregator", "source": "memsql.log"},
            {"timestamp": "2024-01-01 00:00:04", "severity": "INFO",
             "message": "ok", "hostname": "node-b.example.com",
             "role": "aggregator", "source": "memsql.log"},
        ]))

    def tearDown(self):
        server.store = self._prev_store
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _get(self, **params):
        return self.client.get(f"/api/reports/{REPORT_ID}/logs", params=params)

    def test_no_filter_returns_all(self):
        body = self._get().json()
        self.assertEqual(body["total"], 4)

    def test_hyphenated_node_filter(self):
        # The bug: validate_node_filter escaped "node-a-leaf" -> "node\\-a\\-leaf",
        # and str.startswith failed, returning zero logs.
        body = self._get(node="node-a-leaf").json()
        self.assertEqual(body["total"], 2)
        self.assertTrue(all(r["hostname"] == "node-a-leaf" for r in body["logs"]))

    def test_dotted_hostname_filter(self):
        body = self._get(node="node-b.example.com").json()
        self.assertEqual(body["total"], 2)
        self.assertTrue(all(r["hostname"] == "node-b.example.com" for r in body["logs"]))

    def test_node_prefix_filter(self):
        # startswith semantics: "node-a" should match "node-a-leaf".
        body = self._get(node="node-a").json()
        self.assertEqual(body["total"], 2)

    def test_node_filter_with_severity(self):
        body = self._get(node="node-a-leaf", severity="ERROR").json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["logs"][0]["severity"], "ERROR")

    def test_nonexistent_node_returns_empty(self):
        body = self._get(node="node-z").json()
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["logs"], [])


if __name__ == "__main__":
    unittest.main()
