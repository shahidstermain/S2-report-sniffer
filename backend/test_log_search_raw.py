"""Tests for raw tracelog search with context lines (bug D fix) and the
extracted-dir persistence lifecycle.

Covers:
  D. context_before/context_after/line/line_number now populate from raw search
  E. full-archival search across compressed + uncompressed tracelogs
  - multi-node aggregation (search_all_trace_logs)
  - severity filter, node filter, case sensitivity, truncation
  - persist_to relocation in parse_report_archive_streaming
  - extracted_path persisted to / cleaned from storage on delete
  - 2 GB cap fallback (S2RS_MAX_EXTRACTED_KEEP_GB) for directory imports
  - endpoint prefers raw mode when extracted_path exists, falls back to parsed
"""
import asyncio
import gzip
import os
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

import server
from server import app
from storage import LocalReportStore
from parsers import search_all_trace_logs, parse_report_archive_streaming

REPORT_ID = "00000000-0000-0000-0000-000000000000"

# Format: <seq> <YYYY-MM-DD HH:MM:SS.mmm> <SEVERITY>: <message>
NODE_A_LOG = """\
1 2024-01-01 00:00:01.000 INFO: node-a starting up, version 8.1.5
2 2024-01-01 00:00:02.000 ERROR: Connection refused while contacting peer
3 2024-01-01 00:00:03.000 WARN: Retry loop is stalling on disk flush
4 2024-01-01 00:00:04.000 INFO: recovered, resume normal operation
5 2024-01-01 00:05:00.000 ERROR: ETIMEDOUT handshake to aggregator
"""

NODE_B_LOG = """\
1 2024-01-01 00:00:10.000 INFO: node-b aggregator ready
2 2024-01-01 00:00:11.000 FATAL: OOM killed by kernel
3 2024-01-01 00:00:12.000 WARN: fsync is behind on columnstore
4 2024-01-01 00:00:13.000 INFO: backup started normally
"""

NODE_C_LOG = """\
1 2024-01-01 00:00:20.000 ERROR: replication lag detected on leaf-3
2 2024-01-01 00:00:21.000 INFO: replication caught up
"""


def _make_extracted_root(base: str) -> str:
    """Build a fake sdb-report extracted root with 3 nodes (one with .gz log)."""
    root = os.path.join(base, "report_root")
    os.makedirs(root)
    # node-a-LEAF with a plain tracelog
    a = os.path.join(root, "node-a-LEAF")
    os.makedirs(os.path.join(a, "memsqlTracelogs"))
    with open(os.path.join(a, "memsqlTracelogs", "memsql_memsql.log"), "w") as f:
        f.write(NODE_A_LOG)
    # node-b-MA with a compressed tracelog (bug E: compressed search)
    b = os.path.join(root, "node-b-MA")
    os.makedirs(os.path.join(b, "memsqlTracelogs"))
    with gzip.open(os.path.join(b, "memsqlTracelogs", "memsql_memsql.log.gz"), "wt") as f:
        f.write(NODE_B_LOG)
    # node-c-LEAF with a plain tracelog
    c = os.path.join(root, "node-c-LEAF")
    os.makedirs(os.path.join(c, "memsqlTracelogs"))
    with open(os.path.join(c, "memsqlTracelogs", "memsql_memsql.log"), "w") as f:
        f.write(NODE_C_LOG)
    return root


class TestSearchAllTraceLogs(unittest.TestCase):
    """Unit tests for search_all_trace_logs (bugs D/E + multi-node)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="s2rs_rawsearch_")
        self.root = _make_extracted_root(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _search(self, **kw):
        kw.setdefault("extracted_root", self.root)
        kw.setdefault("keyword", "ERROR")
        kw.setdefault("regex", False)
        kw.setdefault("case_sensitive", False)
        kw.setdefault("max_results", 100)
        return search_all_trace_logs(**kw)

    def test_context_windows_populate(self):
        # Bug D: context_before/after must now populate from raw search.
        res = self._search(keyword="Connection refused")
        self.assertEqual(res["total"], 1)
        m = res["matches"][0]
        self.assertEqual(m["hostname"], "node-a")
        self.assertEqual(m["severity"], "ERROR")
        self.assertTrue(m["line_number"])
        self.assertIn("Connection refused", m["line"])
        # one line of context before (the INFO startup line)
        self.assertTrue(any("starting up" in ln for ln in m["context_before"]))
        # one line of context after (the WARN retry line)
        self.assertTrue(any("Retry loop" in ln for ln in m["context_after"]))

    def test_search_across_multiple_nodes(self):
        # Severity-filtered to ERROR: node-a x2, node-c x1 = 3 across 2 nodes.
        res = self._search(keyword=".*", regex=True, severity="ERROR")
        self.assertEqual(res["total"], 3)
        hostnames = {m["hostname"] for m in res["matches"]}
        self.assertEqual(hostnames, {"node-a", "node-c"})
        self.assertEqual(res["nodes_searched"], 2)

    def test_compressed_log_search(self):
        # Bug E: compressed .gz tracelogs must be searched.
        res = self._search(keyword="OOM killed")
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["matches"][0]["hostname"], "node-b")
        self.assertEqual(res["matches"][0]["severity"], "FATAL")
        self.assertEqual(res["matches"][0]["source"], "memsql_memsql.log.gz")

    def test_severity_filter(self):
        res = self._search(keyword=".*", regex=True, severity="FATAL")
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["matches"][0]["severity"], "FATAL")

    def test_severity_filter_warn_alias(self):
        res = self._search(keyword=".*", regex=True, severity="WARNING")
        self.assertEqual(res["total"], 2)
        for m in res["matches"]:
            self.assertEqual(m["severity"], "WARN")

    def test_node_filter(self):
        # All lines on node-a (5 lines), filtered by node.
        res = self._search(keyword=".*", regex=True, node_filter="node-a")
        self.assertEqual(res["total"], 5)
        self.assertTrue(all(m["hostname"] == "node-a" for m in res["matches"]))

    def test_case_sensitive(self):
        # Case-sensitive "ERROR" matches the severity-bearing lines (3: node-a
        # x2, node-c x1). Lowercase "error" matches none (no lowercase "error"
        # in any message).
        res = self._search(keyword="ERROR", case_sensitive=True)
        self.assertEqual(res["total"], 3)
        res_ci = self._search(keyword="error", case_sensitive=True)
        self.assertEqual(res_ci["total"], 0)

    def test_truncation(self):
        # .* matches all 11 lines; limit=2 truncates.
        res = self._search(keyword=".*", regex=True, max_results=2)
        self.assertEqual(res["total"], 11)
        self.assertEqual(len(res["matches"]), 2)
        self.assertTrue(res["truncated"])

    def test_invalid_regex_returns_empty(self):
        res = self._search(keyword="[unclosed", regex=True)
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["matches"], [])

    def test_missing_root_returns_empty(self):
        res = self._search(extracted_root="/nonexistent/path", keyword="anything")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["nodes_searched"], 0)

    def test_matches_sorted_by_timestamp(self):
        res = self._search(keyword=".*", regex=True)
        ts = [m["timestamp"] for m in res["matches"]]
        self.assertEqual(ts, sorted(ts))


class TestPersistExtractedRoot(unittest.TestCase):
    """parse_report_archive_streaming(persist_to=...) relocates the report root."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="s2rs_persist_")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_archive(self) -> str:
        """Build a minimal tar.gz containing a single-node report root."""
        import tarfile
        # Build a report root dir with one node
        src_root = os.path.join(self._tmp, "src_report")
        node = os.path.join(src_root, "host1-LEAF")
        os.makedirs(os.path.join(node, "memsqlTracelogs"))
        with open(os.path.join(node, "memsqlTracelogs", "memsql_memsql.log"), "w") as f:
            f.write("1 2024-01-01 00:00:01.000 INFO: hello world\n")
        # Also need a signal file so _looks_like_node_dir detects it
        with open(os.path.join(node, "informationSchemaMvNodes.json"), "w") as f:
            f.write("[]")
        # Tar it up
        archive = os.path.join(self._tmp, "report.tar.gz")
        with tarfile.open(archive, "w:gz") as tf:
            for dirpath, _dirs, files in os.walk(src_root):
                for fn in files:
                    fp = os.path.join(dirpath, fn)
                    arc = os.path.relpath(fp, self._tmp)
                    tf.add(fp, arcname=arc)
        return archive

    def test_persist_to_relocates_root(self):
        archive = self._make_archive()
        persist_to = os.path.join(self._tmp, "persisted")
        result = parse_report_archive_streaming(archive, persist_to=persist_to)
        self.assertTrue(result.get("extracted_path"))
        self.assertTrue(os.path.isdir(result["extracted_path"]))
        # The persisted root should contain the node dir with its tracelog
        found_tracelog = False
        for dp, _d, files in os.walk(result["extracted_path"]):
            if any("_memsql.log" in fn for fn in files):
                found_tracelog = True
                break
        self.assertTrue(found_tracelog, "persisted root must retain tracelogs")
        # Raw search should work against the persisted path
        res = search_all_trace_logs(result["extracted_path"], "hello", max_results=10)
        self.assertEqual(res["total"], 1)

    def test_no_persist_to_keeps_temp_cleanup(self):
        # Without persist_to, extracted_path must be absent and temp cleaned.
        archive = self._make_archive()
        result = parse_report_archive_streaming(archive)
        self.assertFalse(result.get("extracted_path"))


class TestExtractedKeepCap(unittest.TestCase):
    """S2RS_MAX_EXTRACTED_KEEP_GB contract for raw-search retention."""

    def setUp(self):
        self._prev = os.environ.get("S2RS_MAX_EXTRACTED_KEEP_GB")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("S2RS_MAX_EXTRACTED_KEEP_GB", None)
        else:
            os.environ["S2RS_MAX_EXTRACTED_KEEP_GB"] = self._prev

    def test_zero_disables_retention(self):
        os.environ["S2RS_MAX_EXTRACTED_KEEP_GB"] = "0"
        self.assertEqual(server._extracted_keep_cap_bytes(), 0)
        self.assertFalse(server._under_extracted_keep_cap(None))

    def test_default_cap_when_unset(self):
        os.environ.pop("S2RS_MAX_EXTRACTED_KEEP_GB", None)
        self.assertEqual(server._extracted_keep_cap_bytes(), 2 * 1024 ** 3)
        self.assertTrue(server._under_extracted_keep_cap(None))

    def test_discard_owned_extracted_over_tiny_cap(self):
        os.environ["S2RS_MAX_EXTRACTED_KEEP_GB"] = "0.000000001"  # ~1 byte
        tmp = tempfile.mkdtemp(prefix="s2rs_keepcap_")
        prev_store = server.store
        try:
            store = LocalReportStore(base_dir=tmp)
            server.store = store
            asyncio.run(store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
            owned = store._extracted_dir(REPORT_ID)
            os.makedirs(owned, exist_ok=True)
            marker = os.path.join(owned, "fat.bin")
            with open(marker, "wb") as fh:
                fh.write(b"x" * 4096)
            parsed = {"extracted_path": str(owned)}
            server._discard_owned_extracted_if_over_cap(REPORT_ID, parsed)
            self.assertNotIn("extracted_path", parsed)
            self.assertFalse(os.path.isdir(owned))
        finally:
            server.store = prev_store
            shutil.rmtree(tmp, ignore_errors=True)


class TestStorageExtractedPath(unittest.TestCase):
    """LocalReportStore.set/get_extracted_path + delete cleanup."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="s2rs_storage_ep_")
        self.store = LocalReportStore(base_dir=self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_set_and_get_extracted_path(self):
        # Need a report row first.
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        p = os.path.join(self._tmp, "some_extracted")
        os.makedirs(p)
        asyncio.run(self.store.set_extracted_path(REPORT_ID, p))
        got = asyncio.run(self.store.get_extracted_path(REPORT_ID))
        self.assertEqual(got, p)

    def test_get_returns_none_for_missing_dir(self):
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        asyncio.run(self.store.set_extracted_path(REPORT_ID, "/nonexistent/xyz"))
        self.assertIsNone(asyncio.run(self.store.get_extracted_path(REPORT_ID)))

    def test_get_returns_none_when_unset(self):
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        self.assertIsNone(asyncio.run(self.store.get_extracted_path(REPORT_ID)))

    def test_delete_wipes_extracted_dir(self):
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        # Simulate the parser persisting into the per-report extracted dir.
        extracted = self.store._extracted_dir(REPORT_ID)
        os.makedirs(extracted, exist_ok=True)
        with open(os.path.join(extracted, "marker.txt"), "w") as f:
            f.write("x")
        asyncio.run(self.store.set_extracted_path(REPORT_ID, str(extracted)))
        self.assertTrue(os.path.isdir(extracted))
        deleted = asyncio.run(self.store.delete_report(REPORT_ID))
        self.assertTrue(deleted)
        self.assertFalse(os.path.isdir(extracted))


class TestEndpointRawSearch(unittest.TestCase):
    """/logs/search uses raw mode when extracted_path exists (bug D)."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="s2rs_ep_raw_")
        self._prev_store = server.store
        self.store = LocalReportStore(base_dir=self._tmp)
        server.store = self.store
        asyncio.run(self.store.create_report_stub(REPORT_ID, "r", 100, "tar.gz"))
        self.root = _make_extracted_root(self._tmp)
        asyncio.run(self.store.set_extracted_path(REPORT_ID, self.root))

    def tearDown(self):
        server.store = self._prev_store
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _get(self, **params):
        params.setdefault("keyword", "ERROR")
        return self.client.get(f"/api/reports/{REPORT_ID}/logs/search", params=params)

    def test_raw_mode_returns_context(self):
        res = self._get(keyword="Connection refused")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["search_mode"], "raw")
        self.assertEqual(body["total"], 1)
        m = body["matches"][0]
        self.assertTrue(m["context_before"])
        self.assertTrue(m["context_after"])
        self.assertIn("line_number", m)
        self.assertIn("line", m)

    def test_raw_mode_severity_filter(self):
        res = self._get(keyword=".*", regex="true", severity="FATAL")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["search_mode"], "raw")
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["matches"][0]["severity"], "FATAL")

    def test_raw_mode_compressed_log(self):
        res = self._get(keyword="OOM killed")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["search_mode"], "raw")
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["matches"][0]["hostname"], "node-b")

    def test_raw_mode_nodes_searched(self):
        res = self._get(keyword=".*", regex="true")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["nodes_searched"], 3)

    def test_raw_mode_invalid_regex_400(self):
        res = self._get(keyword="[unclosed", regex="true")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"]["error"], "invalid_regex")

    def test_fallback_to_parsed_when_no_extracted_path(self):
        # Remove the extracted path → endpoint must fall back to parsed mode.
        asyncio.run(self.store.update_report_fields(REPORT_ID, {"extracted_path": ""}))
        # Write some parsed logs so the fallback has something to find.
        asyncio.run(self.store.write_report_logs(REPORT_ID, [
            {"timestamp": "2024-01-01 00:00:01", "severity": "ERROR",
             "message": "Connection refused", "hostname": "node-a",
             "role": "leaf", "source": "memsql.log"},
        ]))
        res = self._get(keyword="Connection")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["search_mode"], "parsed")
        self.assertEqual(body["total"], 1)
        # Parsed mode has no context windows.
        self.assertNotIn("context_before", body["matches"][0])


if __name__ == "__main__":
    unittest.main()
