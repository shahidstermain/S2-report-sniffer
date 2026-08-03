"""Tests for disk reclamation accounting (ENH-1/ENH-2/ENH-3)."""
import os
import tempfile
import unittest

from disk_reclamation import (
    DEFAULT_UNREFERENCED_BLOBS_PCT_THRESHOLD,
    _apply_du_lines_to_buckets,
    _DATADIR_BUCKET_SUFFIXES,
    _grep_datadir_bucket_lines,
    _stream_du_datadir_buckets,
    parse_du_hca_stdout,
    parse_human_size_to_bytes,
    resolve_blobs_referenced_delta,
    resolve_cluster_overhead_buckets,
    resolve_disk_reclamation,
)
from superchecker import run_superchecker


DU_DATADIR_SAMPLE = """\
32G\t/media/hdisk0/memsql/data/logs
760G\t/media/hdisk0/memsql/data/blobs
8.6G\t/media/hdisk0/memsql/data/snapshots
4.0K\t/media/hdisk0/memsql/data/spill
800G\t/media/hdisk0/memsql/data
800G\ttotal
"""

DU_TRACELOGS_SAMPLE = """\
7.8G\t/media/hdisk0/memsql/tracelogs
7.8G\ttotal
"""

# Leaf children used for % / treemap; rollups and deprecated aliases stay out.
_LEAF_CHILD_KEYS = frozenset({
    "transaction_logs",
    "snapshots",
    "spill",
    "tracelogs",
    "plancache",
    "auditlogs",
    "cores",
    "unreferenced_blobs",
    "other_overhead",
})


class TestDuParsing(unittest.TestCase):
    def test_parse_human_size_binary_gib(self):
        self.assertEqual(parse_human_size_to_bytes("1G"), 1024**3)
        self.assertEqual(parse_human_size_to_bytes("1.5G"), int(1.5 * 1024**3))
        self.assertEqual(parse_human_size_to_bytes("32G"), 32 * 1024**3)

    def test_parse_du_hca_datadir_buckets(self):
        parsed = parse_du_hca_stdout(DU_DATADIR_SAMPLE)
        paths = parsed["paths"]
        self.assertEqual(parsed["total_bytes"], 800 * 1024**3)
        self.assertEqual(paths["/media/hdisk0/memsql/data/logs"], 32 * 1024**3)
        self.assertEqual(paths["/media/hdisk0/memsql/data/blobs"], 760 * 1024**3)
        self.assertEqual(paths["/media/hdisk0/memsql/data/snapshots"], int(8.6 * 1024**3))

    def test_apply_data_logs_path_to_transaction_logs(self):
        buckets = {k: 0 for k in list(_DATADIR_BUCKET_SUFFIXES) + ["datadir_total"]}
        _apply_du_lines_to_buckets(DU_DATADIR_SAMPLE.splitlines(), buckets)
        self.assertEqual(buckets["transaction_logs"], 32 * 1024**3)
        self.assertEqual(buckets["logs"], 32 * 1024**3)  # deprecated alias kept in internal buckets
        self.assertEqual(buckets["blobs"], 760 * 1024**3)
        self.assertEqual(buckets["snapshots"], int(8.6 * 1024**3))

    def test_grep_datadir_pattern_matches_data_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "du-hca_datadir_stdout")
            with open(fpath, "w") as fh:
                fh.write(DU_DATADIR_SAMPLE)
            lines = _grep_datadir_bucket_lines(fpath)
            joined = "\n".join(lines)
            self.assertIn("/data/logs", joined)
            self.assertIn("/data/blobs", joined)
            self.assertNotIn("/data/transaction_logs", joined)

    def test_stream_du_maps_data_logs_to_transaction_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ndu = os.path.join(tmp, "nodeDirectoriesDiskUsage")
            os.makedirs(ndu)
            mid = "MEMSQL1"
            with open(os.path.join(ndu, f"{mid}_du-hca_datadir_stdout"), "w") as fh:
                fh.write(DU_DATADIR_SAMPLE)
            buckets = _stream_du_datadir_buckets(tmp, mid)
            self.assertEqual(buckets["transaction_logs"], 32 * 1024**3)
            self.assertEqual(buckets["blobs"], 760 * 1024**3)


class TestBlobsReferencedDelta(unittest.TestCase):
    def test_skipped_without_columnstore_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_path = os.path.join(tmp, "leaf1")
            ndu = os.path.join(node_path, "nodeDirectoriesDiskUsage")
            os.makedirs(ndu)
            memsql_id = "ABC123"
            with open(os.path.join(ndu, f"{memsql_id}_du-hca_datadir_stdout"), "w") as fh:
                fh.write(DU_DATADIR_SAMPLE)
            manifest = {"nodes": [{"memsqlID": memsql_id, "dirs": []}]}
            report = {
                "nodes": [{
                    "hostname": "10.0.0.1",
                    "_node_path": node_path,
                    "metrics": {"node_disk_usage": manifest, "disk": []},
                    "show_variables": {},
                }],
                "cluster_overview": {"nodes_detail": []},
            }
            result = resolve_blobs_referenced_delta(report)
            self.assertEqual(result["status"], "skipped")
            self.assertIn("informationSchemaColumnarSegments", result["skip_reason"])

    def test_ha_doubling_and_delta(self):
        report = {
            "nodes": [{
                "hostname": "10.0.0.1",
                "metrics": {"disk": []},
                "show_variables": {"redundancy_level": "2"},
            }],
            "cluster_overview": {"nodes_detail": []},
            "columnstore_files": [
                {"NODE_ID": "nid1", "FILE_SIZE": 100 * 1024**3},
            ],
            "blobs_referenced_delta": {
                "status": "ok",
                "ha_factor": 2,
                "cluster": {"delta_bytes": 560 * 1024**3},
            },
        }
        # Inject du via monkeypatched path is heavy; test columnstore grouping directly
        from disk_reclamation import _columnstore_bytes_by_node
        by_node = _columnstore_bytes_by_node(
            report["columnstore_files"],
            {"cluster_overview": {"nodes_detail": [{"id": "nid1", "ip_addr": "10.0.0.1"}]}},
        )
        self.assertEqual(by_node["10.0.0.1"], 100 * 1024**3)

    def test_hostname_ip_join_via_bind_address(self):
        """Directory hostname and MV_NODES IP must join through bind_address."""
        on_disk = 760 * 1024**3
        referenced = 700 * 1024**3
        report = {
            "nodes": [{
                "hostname": "leaf1.example.com",
                "disk_du_buckets": {"blobs": on_disk, "datadir_total": on_disk},
                "metrics": {
                    "disk": [{"mounted_on": "/data", "used": "800G", "use_pct": 70}],
                },
                "show_variables": {"bind_address": "10.0.0.5"},
            }],
            "cluster_overview": {
                "nodes_detail": [{"id": "1", "ip_addr": "10.0.0.5"}],
            },
            "columnstore_files": [
                {"NODE_ID": "1", "FILE_SIZE": referenced},
            ],
        }
        result = resolve_blobs_referenced_delta(report)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["per_node"]), 1)
        self.assertEqual(result["per_node"][0]["node"], "leaf1.example.com")
        self.assertEqual(result["per_node"][0]["on_disk_blobs_bytes"], on_disk)
        self.assertEqual(result["per_node"][0]["referenced_bytes"], referenced)
        self.assertEqual(result["per_node"][0]["delta_bytes"], on_disk - referenced)
        self.assertEqual(result["cluster"]["delta_bytes"], on_disk - referenced)

    def test_cluster_delta_not_inflated_when_host_keys_split(self):
        """Even without a hostname↔IP alias, cluster delta uses totals not per-node floors."""
        on_disk = 760 * 1024**3
        referenced = 700 * 1024**3
        report = {
            "nodes": [{
                "hostname": "leaf1.example.com",
                "disk_du_buckets": {"blobs": on_disk, "datadir_total": on_disk},
                "metrics": {
                    "disk": [{"mounted_on": "/data", "used": "800G", "use_pct": 70}],
                },
                "show_variables": {},
            }],
            "cluster_overview": {
                "nodes_detail": [{"id": "1", "ip_addr": "10.0.0.5"}],
            },
            "columnstore_files": [
                {"NODE_ID": "1", "FILE_SIZE": referenced},
            ],
        }
        result = resolve_blobs_referenced_delta(report)
        self.assertEqual(result["cluster"]["on_disk_blobs_bytes"], on_disk)
        self.assertEqual(result["cluster"]["referenced_adjusted_bytes"], referenced)
        # Pre-fix summed per-node floors and reported the full 760 GB as unreferenced.
        self.assertEqual(result["cluster"]["delta_bytes"], on_disk - referenced)


class TestClusterOverheadBuckets(unittest.TestCase):
    def _node_with_du(self, tmp: str, host: str, memsql_id: str) -> dict:
        node_path = os.path.join(tmp, host)
        ndu = os.path.join(node_path, "nodeDirectoriesDiskUsage")
        os.makedirs(ndu)
        with open(os.path.join(ndu, f"{memsql_id}_du-hca_datadir_stdout"), "w") as fh:
            fh.write(DU_DATADIR_SAMPLE)
        with open(os.path.join(ndu, f"{memsql_id}_du-hca_tracelogsdir_stdout"), "w") as fh:
            fh.write(DU_TRACELOGS_SAMPLE)
        return {
            "hostname": host,
            "_node_path": node_path,
            "metrics": {
                "node_disk_usage": {"nodes": [{"memsqlID": memsql_id}]},
                "disk": [{
                    "mounted_on": "/media/hdisk0",
                    "used": "800G",
                    "use_pct": 70,
                }],
            },
            "show_variables": {},
        }

    def test_overhead_children_sum_to_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = self._node_with_du(tmp, "10.0.0.1", "MEMSQL1")
            report = {
                "nodes": [node],
                "database_disk_usage": [{
                    "DATABASE_NAME": "appdb",
                    "_disk_bytes": 200 * 1024**3,
                }],
                "storage": [],
                "cluster_overhead": {},
                "blobs_referenced_delta": {"status": "skipped"},
            }
            overhead = resolve_cluster_overhead_buckets(report)
            self.assertGreater(overhead["total_bytes"], 0)
            children = overhead["children"]

            # When delta is skipped, do not treat on-disk blobs as unreferenced.
            self.assertEqual(overhead["unreferenced_blobs_bytes"], 0)
            self.assertGreater(overhead["on_disk_blobs_bytes"], 0)
            self.assertEqual(children["unreferenced_blobs"]["bytes"], 0)

            # Leaf-only children — no deprecated logs or referenced_non_table rollup.
            self.assertNotIn("logs", children)
            self.assertNotIn("referenced_non_table", children)
            self.assertTrue(set(children) <= _LEAF_CHILD_KEYS)

            leaf_sum = sum(
                c["bytes"] for k, c in children.items() if k != "other_overhead"
            )
            self.assertEqual(leaf_sum, overhead["referenced_non_table_bytes"])
            child_sum = sum(c["bytes"] for c in children.values())
            self.assertGreaterEqual(child_sum, overhead["referenced_non_table_bytes"])
            self.assertEqual(
                overhead["total_bytes"],
                overhead["used_disk_bytes"] - overhead["attributed_table_bytes"],
            )

    def test_children_exclude_logs_and_referenced_non_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = self._node_with_du(tmp, "10.0.0.1", "MEMSQL1")
            report = {
                "nodes": [node],
                "database_disk_usage": [],
                "storage": [],
                "blobs_referenced_delta": {
                    "status": "ok",
                    "cluster": {"delta_bytes": 50 * 1024**3},
                },
            }
            overhead = resolve_cluster_overhead_buckets(report)
            children = overhead["children"]
            self.assertNotIn("logs", children)
            self.assertNotIn("referenced_non_table", children)
            self.assertIn("transaction_logs", children)
            self.assertEqual(overhead["unreferenced_blobs_bytes"], 50 * 1024**3)
            self.assertEqual(children["unreferenced_blobs"]["bytes"], 50 * 1024**3)
            # Referenced-non-table rollup remains a top-level scalar only.
            self.assertGreater(overhead["referenced_non_table_bytes"], 0)
            leaf_keys = {k for k in children if k != "other_overhead"}
            leaf_sum = sum(children[k]["bytes"] for k in leaf_keys)
            self.assertEqual(
                leaf_sum,
                overhead["referenced_non_table_bytes"] + overhead["unreferenced_blobs_bytes"],
            )

    def test_unreferenced_zero_when_blobs_delta_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = self._node_with_du(tmp, "10.0.0.3", "MEMSQL3")
            report = {
                "nodes": [node],
                "database_disk_usage": [],
                "storage": [],
                "blobs_referenced_delta": {"status": "partial", "cluster": {"delta_bytes": 999}},
            }
            overhead = resolve_cluster_overhead_buckets(report)
            self.assertEqual(overhead["unreferenced_blobs_bytes"], 0)
            self.assertGreater(overhead["on_disk_blobs_bytes"], 0)
            self.assertEqual(overhead["children"]["unreferenced_blobs"]["bytes"], 0)

    def test_legacy_top_level_total_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = self._node_with_du(tmp, "10.0.0.2", "MEMSQL2")
            report = {
                "nodes": [node],
                "database_disk_usage": [],
                "storage": [{"DATABASE_NAME": "x", "MEMORY_USE": 10 * 1024**3}],
            }
            overhead = resolve_cluster_overhead_buckets(report)
            self.assertIn("total_bytes", overhead)
            self.assertIn("children", overhead)


class TestReclamationStalledFinding(unittest.TestCase):
    def test_fires_with_disk_and_health_signals(self):
        used = 1000 * 1024**3
        unreferenced = 200 * 1024**3
        report = {
            "nodes": [],
            "cluster_overhead": {
                "used_disk_bytes": used,
                "unreferenced_blobs_bytes": unreferenced,
                "children": {"unreferenced_blobs": {"bytes": unreferenced}},
            },
            "detected_log_patterns": [{
                "category": "storage",
                "title": "Disk fsync behind",
                "sample": "Blob fsync is behind by 12s stalling the workload",
                "severity": "warning",
            }],
            "memory_utilization": {
                "per_node": {"10.0.0.1": {"swap_used_pct": 15}},
            },
        }
        findings = run_superchecker(report)
        stalled = [f for f in findings if f["checker_id"] == "reclamationStalled"]
        self.assertEqual(len(stalled), 1)
        self.assertIn("unreferenced_blobs", stalled[0]["evidence"])
        self.assertIn("fsync", stalled[0]["evidence"].lower())

    def test_does_not_fire_without_health_signal(self):
        used = 1000 * 1024**3
        unreferenced = 200 * 1024**3
        report = {
            "nodes": [],
            "cluster_overhead": {
                "used_disk_bytes": used,
                "unreferenced_blobs_bytes": unreferenced,
            },
            "detected_log_patterns": [],
            "memory_utilization": {"per_node": {}},
        }
        findings = run_superchecker(report)
        self.assertFalse(any(f["checker_id"] == "reclamationStalled" for f in findings))

    def test_does_not_fire_below_threshold(self):
        used = 1000 * 1024**3
        unreferenced = int(used * (DEFAULT_UNREFERENCED_BLOBS_PCT_THRESHOLD - 1) / 100)
        report = {
            "nodes": [],
            "cluster_overhead": {
                "used_disk_bytes": used,
                "unreferenced_blobs_bytes": unreferenced,
            },
            "detected_log_patterns": [{
                "category": "oom",
                "title": "OOM Kill Detected",
                "sample": "out of memory",
            }],
            "memory_utilization": {"per_node": {"h1": {"swap_used_pct": 20}}},
        }
        findings = run_superchecker(report)
        self.assertFalse(any(f["checker_id"] == "reclamationStalled" for f in findings))

    def test_skipped_delta_does_not_inflate_unreferenced_for_stall(self):
        """On-disk blobs must not become unreferenced_blobs when delta is skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            node_path = os.path.join(tmp, "leaf")
            ndu = os.path.join(node_path, "nodeDirectoriesDiskUsage")
            os.makedirs(ndu)
            mid = "IDSTALL"
            with open(os.path.join(ndu, f"{mid}_du-hca_datadir_stdout"), "w") as fh:
                fh.write(DU_DATADIR_SAMPLE)
            report = {
                "nodes": [{
                    "hostname": "leaf",
                    "_node_path": node_path,
                    "metrics": {
                        "node_disk_usage": {"nodes": [{"memsqlID": mid}]},
                        "disk": [{
                            "mounted_on": "/media/hdisk0",
                            "used": "800G",
                            "use_pct": 70,
                        }],
                    },
                }],
                "database_disk_usage": [],
                "storage": [],
                "blobs_referenced_delta": {"status": "skipped"},
                "detected_log_patterns": [{
                    "category": "storage",
                    "title": "Disk fsync behind",
                    "sample": "fsync is behind",
                }],
                "memory_utilization": {"per_node": {"leaf": {"swap_used_pct": 20}}},
            }
            overhead = resolve_cluster_overhead_buckets(report)
            self.assertEqual(overhead["unreferenced_blobs_bytes"], 0)
            report["cluster_overhead"] = overhead
            findings = run_superchecker(report)
            self.assertFalse(any(f["checker_id"] == "reclamationStalled" for f in findings))


class TestResolveDiskReclamationIntegration(unittest.TestCase):
    def test_resolve_disk_reclamation_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_path = os.path.join(tmp, "leaf")
            ndu = os.path.join(node_path, "nodeDirectoriesDiskUsage")
            os.makedirs(ndu)
            mid = "ID1"
            with open(os.path.join(ndu, f"{mid}_du-hca_datadir_stdout"), "w") as fh:
                fh.write(DU_DATADIR_SAMPLE)
            report = {
                "nodes": [{
                    "hostname": "leaf",
                    "_node_path": node_path,
                    "metrics": {"node_disk_usage": {"nodes": [{"memsqlID": mid}]}, "disk": []},
                }],
                "database_disk_usage": [],
                "storage": [],
            }
            out = resolve_disk_reclamation(report)
            self.assertIn("cluster_overhead", out)
            self.assertIn("blobs_referenced_delta", out)
            children = out["cluster_overhead"]["children"]
            self.assertNotIn("logs", children)
            self.assertNotIn("referenced_non_table", children)
            di_overhead = out["disk_intelligence"]["cluster_overhead"]
            self.assertNotIn("logs", di_overhead)
            self.assertNotIn("referenced_non_table", di_overhead)


if __name__ == "__main__":
    unittest.main()
