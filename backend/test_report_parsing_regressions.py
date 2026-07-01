"""Regression tests for sdb-report parsing edge cases (wrong analysis / read failures)."""
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from parsers import (
    _detect_archive_format,
    _extract_rows_from_json_data,
    _node_role_from_dir_name,
    _validate_extract_path,
    build_cluster_overview,
    build_cluster_overview_from_topology,
    build_minimal_cluster_overview,
    ensure_supported_archive_format,
    infer_deployment_method,
    parse_cluster_topology,
    parse_report_archive_streaming,
    parse_report_directory,
    parse_sdb_json_table,
    read_stdout,
)


class TestJsonRowExtraction(unittest.TestCase):
    def test_memsqlid_list_wrapper(self):
        data = [
            {
                "MemsqlID": 1,
                "MV_NODES": {
                    "rows": [
                        {"MEMSQL_ID": 1, "HOSTNAME": "n1", "ROLE": "Master Aggregator", "STATE": "online"},
                        {"MEMSQL_ID": 2, "HOSTNAME": "n2", "ROLE": "Leaf", "STATE": "online"},
                    ]
                },
            }
        ]
        rows = _extract_rows_from_json_data(data)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ROLE"], "Master Aggregator")

    def test_parse_sdb_json_table_memsqlid_wrapper(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_json_wrap_"))
        node = root / "node-MA"
        node.mkdir()
        (node / "informationSchemaMvNodes.json").write_text(json.dumps([
            {"MemsqlID": 1, "MV_NODES": {"rows": [{"ROLE": "Leaf", "HOSTNAME": "leaf1"}]}}
        ]))
        rows = parse_sdb_json_table(str(node), "informationSchemaMvNodes.json")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["HOSTNAME"], "leaf1")


class TestNodeDirDetection(unittest.TestCase):
    def test_role_suffix_variants(self):
        cases = {
            "host-MasterAggregator": ("host", "MA"),
            "host-ChildAggregator": ("host", "CA"),
            "host-Leaf": ("host", "LEAF"),
            "db-1-MA": ("db-1", "MA"),
        }
        for name, expected in cases.items():
            self.assertEqual(_node_role_from_dir_name(name), expected)

    def test_content_based_uuid_node_dir(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_uuid_node_"))
        report = root / "report"
        node = report / "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        node.mkdir(parents=True)
        (report / "globalInfo").mkdir()
        (node / "memsqlConfig.json").write_text("{}")

        parsed = parse_report_directory(str(report), "uuid-report")
        self.assertEqual(parsed["raw_node_count"], 1)
        self.assertEqual(parsed["cluster_overview"]["total_nodes"], 1)

    def test_three_node_topology_from_directories(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_three_node_"))
        report = root / "report"
        (report / "globalInfo").mkdir(parents=True)
        for dirname in ("host-MasterAggregator", "host-ChildAggregator", "host-Leaf"):
            nd = report / dirname
            nd.mkdir()
            (nd / "memsqlConfig.json").write_text("{}")

        parsed = parse_report_directory(str(report), "three-node")
        self.assertEqual(parsed["raw_node_count"], 3)
        co = parsed["cluster_overview"]
        self.assertEqual(co["aggregators"], 2)
        self.assertEqual(co["leaves"], 1)
        self.assertEqual(co.get("topology_source"), "node_directories")
        self.assertEqual(co["offline_nodes"], 0)
        offline_ids = {"leavesNotOnline", "offlineAggregators"}
        self.assertFalse(
            any(rec["checker_id"] in offline_ids for rec in parsed["recommendations"])
        )


class TestRoleNormalization(unittest.TestCase):
    def test_master_aggregator_role_string(self):
        mv_nodes = [
            {"ROLE": "Master Aggregator", "STATE": "online", "HOSTNAME": "ma1"},
            {"ROLE": "Leaf", "STATE": "online", "HOSTNAME": "leaf1"},
        ]
        overview = build_cluster_overview(mv_nodes, [])
        self.assertEqual(overview["aggregators"], 1)
        self.assertEqual(overview["leaves"], 1)

    def test_topology_fallback_overview(self):
        topology = {
            "leaves": [{"ROLE": "Leaf", "HOSTNAME": "l1"}],
            "aggregators": [{"ROLE": "Master Aggregator", "HOSTNAME": "a1"}],
        }
        overview = build_cluster_overview_from_topology(topology, [])
        self.assertEqual(overview["leaves"], 1)
        self.assertEqual(overview["aggregators"], 1)
        self.assertEqual(overview["offline_nodes"], 0)


class TestStdoutLayouts(unittest.TestCase):
    def test_flat_stdout_at_node_root(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_flat_stdout_"))
        node = root / "host-Leaf"
        node.mkdir()
        (node / "free_stdout").write_text("              total        used        free\nMem:       16384000     8192000     8192000")
        text = read_stdout(str(node), "free")
        self.assertIn("Mem:", text)
        self.assertNotEqual(text, "")


class TestClusterTopologyMerge(unittest.TestCase):
    def test_merges_rows_across_memsqlid_keys(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_topo_merge_"))
        node = root / "node-MA"
        node.mkdir()
        (node / "clusterTopology.json").write_text(json.dumps({
            "1": {
                "ShowLeaves": {"rows": [{"Host": "leaf1"}]},
                "ShowAggregators": {"rows": [{"Host": "agg1"}]},
            },
            "2": {
                "ShowLeaves": {"rows": [{"Host": "leaf2"}]},
                "ShowAggregators": {"rows": [{"Host": "agg2"}]},
            },
        }))
        topo = parse_cluster_topology(str(node))
        self.assertEqual(len(topo["leaves"]), 2)
        self.assertEqual(len(topo["aggregators"]), 2)


class TestArchiveFormats(unittest.TestCase):
    def test_case_insensitive_extension_detection(self):
        self.assertEqual(_detect_archive_format("/path/REPORT.ZIP", sniff=False), "zip")
        self.assertEqual(_detect_archive_format("/path/bundle.TAR.GZ", sniff=False), "tar.gz")
        self.assertEqual(_detect_archive_format("/path/data.TGZ", sniff=False), "tar.gz")

    def test_sniffs_gzip_tar_misnamed_as_dot_tar(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_sniff_tar_"))
        report_dir = root / "report"
        node_dir = report_dir / "host-Leaf"
        node_dir.mkdir(parents=True)
        (report_dir / "globalInfo").mkdir()
        (node_dir / "memsqlConfig.json").write_text("{}")

        misnamed = root / "report.tar"
        with tarfile.open(misnamed, "w:gz") as tf:
            tf.add(report_dir, arcname="report")

        self.assertEqual(_detect_archive_format(str(misnamed)), "tar.gz")
        parsed = parse_report_archive_streaming(str(misnamed))
        self.assertEqual(parsed.get("raw_node_count"), 1)

    def test_rejects_debian_package_with_clear_message(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_deb_"))
        deb_as_tar = root / "toolbox.tar"
        deb_as_tar.write_bytes(b"!<arch>\n")
        with self.assertRaisesRegex(ValueError, "Debian package"):
            ensure_supported_archive_format(str(deb_as_tar))

    def test_dot_root_tar_member_allowed(self):
        base = tempfile.mkdtemp(prefix="s2rs_dot_root_")
        resolved = _validate_extract_path(base, ".")
        self.assertEqual(resolved, str(Path(base).resolve()))

    def test_parses_tar_with_dot_root_member(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_dot_tar_"))
        report_dir = root / "report"
        node_dir = report_dir / "host-Leaf"
        node_dir.mkdir(parents=True)
        (report_dir / "globalInfo").mkdir()
        (node_dir / "memsqlConfig.json").write_text("{}")

        tar_path = root / "report.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(report_dir, arcname=".")

        parsed = parse_report_archive_streaming(str(tar_path))
        self.assertEqual(parsed.get("raw_node_count"), 1)

    def test_parses_uppercase_zip_extension(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_upper_zip_"))
        report_dir = root / "report"
        node_dir = report_dir / "host-MA"
        node_dir.mkdir(parents=True)
        (report_dir / "globalInfo").mkdir()
        (node_dir / "memsqlConfig.json").write_text("{}")

        zip_path = root / "report.ZIP"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in report_dir.rglob("*"):
                zf.write(p, p.relative_to(report_dir.parent))

        parsed = parse_report_archive_streaming(str(zip_path))
        self.assertEqual(parsed.get("detected_format"), "zip")
        self.assertEqual(parsed.get("raw_node_count"), 1)


class TestParseWarnings(unittest.TestCase):
    def test_warning_when_no_nodes_detected(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_no_nodes_"))
        report = root / "empty"
        report.mkdir()
        (report / "globalInfo").mkdir()
        parsed = parse_report_directory(str(report), "empty")
        self.assertEqual(parsed["raw_node_count"], 0)
        warnings = parsed.get("parse_warnings") or []
        self.assertTrue(any("No node directories" in w for w in warnings))


class TestDeploymentInference(unittest.TestCase):
    def test_reads_ps_from_node_root(self):
        nodes = [{"hostname": "n1", "role": "MA", "ps": [{"cmd": "/usr/bin/kubelet"}]}]
        result = infer_deployment_method(nodes, {})
        self.assertEqual(result["method"], "Kubernetes Operator")


class TestMinimalOverview(unittest.TestCase):
    def test_build_minimal_from_parsed_nodes(self):
        nodes = [
            {"hostname": "ma", "role": "MA", "version": "8.5.0", "metrics": {"memory": {"total_mb": 1000, "used_mb": 500}}},
            {"hostname": "leaf", "role": "LEAF", "metrics": {"memory": {"total_mb": 2000, "used_mb": 1000}}},
        ]
        overview = build_minimal_cluster_overview(nodes)
        self.assertEqual(overview["total_nodes"], 2)
        self.assertEqual(overview["aggregators"], 1)
        self.assertEqual(overview["leaves"], 1)
        self.assertEqual(overview["version"], "8.5.0")


if __name__ == "__main__":
    unittest.main()
