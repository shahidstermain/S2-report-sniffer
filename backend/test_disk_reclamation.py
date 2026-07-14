"""Tests for disk reclamation accounting (ENH-1/ENH-2/ENH-3)."""
import os
import tempfile
import unittest

from disk_reclamation import (
    DEFAULT_UNREFERENCED_BLOBS_PCT_THRESHOLD,
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
            child_sum = sum(c["bytes"] for c in children.values())
            self.assertGreaterEqual(child_sum, overhead["referenced_non_table_bytes"])
            self.assertIn("unreferenced_blobs", children)
            self.assertEqual(overhead["total_bytes"], overhead["used_disk_bytes"] - overhead["attributed_table_bytes"])

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


if __name__ == "__main__":
    unittest.main()
