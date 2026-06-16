"""Tests for expanded compression format handling and raw log search."""
import os
import gzip
import bz2
import lzma
import tempfile
import shutil
import unittest
from pathlib import Path

import lz4.frame
import zstandard

import sys
sys.path.insert(0, os.path.dirname(__file__))

from parsers import (
    _is_tracelog_file,
    _get_opener_for_file,
    parse_trace_logs,
    search_trace_logs_raw,
)


class TestTraceLogFileDetection(unittest.TestCase):
    """Test _is_tracelog_file filename detection."""

    def test_plain_log(self):
        self.assertTrue(_is_tracelog_file("node1_memsql.log"))

    def test_rotated_log(self):
        self.assertTrue(_is_tracelog_file("node1_memsql.log.1"))

    def test_gz_compressed(self):
        self.assertTrue(_is_tracelog_file("node1_memsql.log.gz"))

    def test_bz2_compressed(self):
        self.assertTrue(_is_tracelog_file("node1_memsql.log.bz2"))

    def test_xz_compressed(self):
        self.assertTrue(_is_tracelog_file("node1_memsql.log.xz"))

    def test_zst_compressed(self):
        self.assertTrue(_is_tracelog_file("node1_memsql.log.zst"))

    def test_lz4_compressed(self):
        self.assertTrue(_is_tracelog_file("node1_memsql.log.lz4"))

    def test_non_tracelog(self):
        self.assertFalse(_is_tracelog_file("error.log"))
        self.assertFalse(_is_tracelog_file("node1_audit.log"))
        self.assertFalse(_is_tracelog_file("memsql.log"))  # Missing _memsql.log

    def test_case_insensitive(self):
        self.assertTrue(_is_tracelog_file("node1_MEMSQL.LOG"))
        self.assertTrue(_is_tracelog_file("node1_Memsql.Log.gz"))


class TestCompressionOpeners(unittest.TestCase):
    """Test _get_opener_for_file handles different compression formats."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_content = "2024-01-15 10:00:00 [INFO] test line 1\n2024-01-15 10:00:01 [ERROR] test error line\n"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_plain(self, name):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'w') as f:
            f.write(self.test_content)
        return path

    def _write_gz(self, name):
        path = os.path.join(self.tmpdir, name)
        with gzip.open(path, 'wt') as f:
            f.write(self.test_content)
        return path

    def _write_bz2(self, name):
        path = os.path.join(self.tmpdir, name)
        with bz2.open(path, 'wt') as f:
            f.write(self.test_content)
        return path

    def _write_xz(self, name):
        path = os.path.join(self.tmpdir, name)
        with lzma.open(path, 'wt') as f:
            f.write(self.test_content)
        return path

    def _write_zst(self, name):
        path = os.path.join(self.tmpdir, name)
        with zstandard.open(path, 'wt', encoding='utf-8') as f:
            f.write(self.test_content)
        return path

    def _write_lz4(self, name):
        path = os.path.join(self.tmpdir, name)
        with lz4.frame.open(path, 'wt', encoding='utf-8') as f:
            f.write(self.test_content)
        return path

    def test_plain_opener(self):
        path = self._write_plain("node1_memsql.log")
        with _get_opener_for_file("node1_memsql.log", path) as f:
            content = f.read()
        self.assertIn("[INFO]", content)
        self.assertIn("[ERROR]", content)

    def test_gz_opener(self):
        path = self._write_gz("node1_memsql.log.gz")
        with _get_opener_for_file("node1_memsql.log.gz", path) as f:
            content = f.read()
        self.assertIn("[INFO]", content)

    def test_bz2_opener(self):
        path = self._write_bz2("node1_memsql.log.bz2")
        with _get_opener_for_file("node1_memsql.log.bz2", path) as f:
            content = f.read()
        self.assertIn("[ERROR]", content)

    def test_xz_opener(self):
        path = self._write_xz("node1_memsql.log.xz")
        with _get_opener_for_file("node1_memsql.log.xz", path) as f:
            content = f.read()
        self.assertIn("[INFO]", content)

    def test_zst_opener(self):
        path = self._write_zst("node1_memsql.log.zst")
        with _get_opener_for_file("node1_memsql.log.zst", path) as f:
            content = f.read()
        self.assertIn("[ERROR]", content)

    def test_lz4_opener(self):
        path = self._write_lz4("node1_memsql.log.lz4")
        with _get_opener_for_file("node1_memsql.log.lz4", path) as f:
            content = f.read()
        self.assertIn("[INFO]", content)


class TestParseTraceLogsMultiCompression(unittest.TestCase):
    """Test parse_trace_logs reads from mixed compression formats."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.node_dir = os.path.join(self.tmpdir, "test-node-127.0.0.1-MA")
        self.logs_dir = os.path.join(self.node_dir, "memsqlTracelogs")
        os.makedirs(self.logs_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_log(self, filename, content):
        path = os.path.join(self.logs_dir, filename)
        if filename.endswith('.gz'):
            with gzip.open(path, 'wt') as f:
                f.write(content)
        elif filename.endswith('.bz2'):
            with bz2.open(path, 'wt') as f:
                f.write(content)
        elif filename.endswith('.xz'):
            with lzma.open(path, 'wt') as f:
                f.write(content)
        elif filename.endswith('.zst'):
            with zstandard.open(path, 'wt', encoding='utf-8') as f:
                f.write(content)
        elif filename.endswith('.lz4'):
            with lz4.frame.open(path, 'wt', encoding='utf-8') as f:
                f.write(content)
        else:
            with open(path, 'w') as f:
                f.write(content)

    def test_mixed_compression(self):
        # Write logs in different formats matching SingleStore log format:
        # <pid> <timestamp> <severity>: <message>
        self._write_log("node1_memsql.log", "1234 2024-01-15 10:00:00.000 INFO: plain log line\n")
        self._write_log("node1_memsql.log.1.gz", "1234 2024-01-15 09:00:00.000 WARN: gz compressed warning\n")
        self._write_log("node1_memsql.log.2.bz2", "1234 2024-01-15 08:00:00.000 ERROR: bz2 compressed error\n")
        self._write_log("node1_memsql.log.3.xz", "1234 2024-01-15 07:00:00.000 INFO: xz compressed info\n")
        self._write_log("node1_memsql.log.4.zst", "1234 2024-01-15 06:00:00.000 ERROR: zst compressed error\n")
        self._write_log("node1_memsql.log.5.lz4", "1234 2024-01-15 05:00:00.000 WARN: lz4 compressed warning\n")

        entries = parse_trace_logs(self.node_dir, "test-node", "MasterAggregator")

        # Should have entries from all formats
        self.assertEqual(len(entries), 6)

        severities = {e["severity"] for e in entries}
        self.assertIn("INFO", severities)
        self.assertIn("WARN", severities)
        self.assertIn("ERROR", severities)

    def test_empty_dir(self):
        entries = parse_trace_logs(self.node_dir, "test-node", "MasterAggregator")
        self.assertEqual(entries, [])

    def test_no_tracelogs_dir(self):
        os.rmdir(self.logs_dir)
        entries = parse_trace_logs(self.node_dir, "test-node", "MasterAggregator")
        self.assertEqual(entries, [])


class TestSearchTraceLogsRaw(unittest.TestCase):
    """Test search_trace_logs_raw function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.node_dir = os.path.join(self.tmpdir, "test-node-127.0.0.1-MA")
        self.logs_dir = os.path.join(self.node_dir, "memsqlTracelogs")
        os.makedirs(self.logs_dir)

        # Write a multi-line log file matching SingleStore format
        log_lines = [
            "1234 2024-01-15 10:00:00.000 INFO: Starting node initialization",
            "1234 2024-01-15 10:00:01.000 INFO: Loading configuration",
            "1234 2024-01-15 10:00:02.000 WARN: Memory usage above 80%",
            "1234 2024-01-15 10:00:03.000 ERROR: Failed to connect to leaf node",
            "1234 2024-01-15 10:00:04.000 INFO: Retrying connection",
            "1234 2024-01-15 10:00:05.000 ERROR: Connection timeout after 30s",
            "1234 2024-01-15 10:00:06.000 FATAL: Node shutting down due to errors",
        ]
        self.log_content = "\n".join(log_lines) + "\n"

        path = os.path.join(self.logs_dir, "node1_memsql.log")
        with open(path, 'w') as f:
            f.write(self.log_content)

        # Write a compressed file
        gz_path = os.path.join(self.logs_dir, "node1_memsql.log.1.gz")
        with gzip.open(gz_path, 'wt') as f:
            f.write("1234 2024-01-15 09:00:00.000 WARN: Disk space low on /data\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_keyword_search(self):
        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator", "Failed"
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["files_searched"], 2)

    def test_regex_search(self):
        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator",
            keyword=r"connect\w+",
            regex=True
        )
        self.assertGreater(result["total"], 0)
        # Case-insensitive by default, so should match "connect", "connection", etc.
        for match in result["matches"]:
            self.assertTrue("connect" in match["line"].lower())

    def test_severity_filter(self):
        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator",
            keyword="",
            severity="WARN"
        )
        for match in result["matches"]:
            self.assertEqual(match["severity"], "WARN")

    def test_context_lines(self):
        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator",
            keyword="FATAL",
            context_lines=1
        )
        self.assertEqual(result["total"], 1)
        match = result["matches"][0]
        self.assertGreater(len(match["context_before"]), 0)
        self.assertEqual(len(match["context_after"]), 0)  # Last line

    def test_no_logs_dir(self):
        shutil.rmtree(self.logs_dir)
        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator", "test"
        )
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["total"], 0)

    def test_invalid_regex(self):
        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator",
            keyword="[invalid",
            regex=True
        )
        self.assertIn("error", result)

    def test_max_results(self):
        # Add many lines
        path = os.path.join(self.logs_dir, "node2_memsql.log")
        with open(path, 'w') as f:
            for i in range(100):
                f.write(f"1234 2024-01-15 11:00:{i:02d}.000 INFO: Info line {i}\n")

        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator",
            keyword="INFO",
            max_results=10
        )
        self.assertEqual(len(result["matches"]), 10)
        self.assertTrue(result["truncated"])

    def test_compressed_file_search(self):
        result = search_trace_logs_raw(
            self.node_dir, "test-node", "MasterAggregator",
            keyword="Disk space"
        )
        self.assertGreater(result["total"], 0)
        self.assertTrue(any("Disk space" in m["line"] for m in result["matches"]))


if __name__ == "__main__":
    unittest.main()
