import unittest
import io
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path

from parsers import parse_report_archive_streaming


class TestZipParsingVariants(unittest.TestCase):
    def test_parses_master_aggregator_dir_name_variant(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_zip_variant_"))
        report_dir = root / "report"
        node_dir = report_dir / "node-127.0.0.1-MasterAggregator"
        node_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "globalInfo").mkdir(parents=True, exist_ok=True)

        (node_dir / "informationSchemaMvNodes.json").write_text(json.dumps({
            "rows": [{"MEMSQL_ID": 1, "HOSTNAME": "node1", "ROLE": "Master Aggregator", "STATE": "online"}]
        }))

        zip_path = root / "report.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in report_dir.rglob("*"):
                zf.write(p, p.relative_to(report_dir.parent))

        parsed = parse_report_archive_streaming(str(zip_path))
        self.assertEqual(parsed.get("raw_node_count"), 1)
        co = parsed.get("cluster_overview") or {}
        self.assertGreaterEqual(co.get("total_nodes", 0), 1)

    def test_finds_report_root_in_nested_directories(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_zip_nested_"))
        nested = root / "outer" / "inner" / "actual_report"
        node_dir = nested / "hostA-MA"
        node_dir.mkdir(parents=True, exist_ok=True)
        (nested / "globalInfo").mkdir(parents=True, exist_ok=True)

        (node_dir / "informationSchemaMvNodes.json").write_text(json.dumps({
            "rows": [{"MEMSQL_ID": 1, "HOSTNAME": "hostA", "ROLE": "Master Aggregator", "STATE": "online"}]
        }))

        zip_path = root / "nested.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in (root / "outer").rglob("*"):
                zf.write(p, p.relative_to(root))

        parsed = parse_report_archive_streaming(str(zip_path))
        self.assertEqual(parsed.get("raw_node_count"), 1)
        co = parsed.get("cluster_overview") or {}
        self.assertGreaterEqual(co.get("total_nodes", 0), 1)

    def test_parses_plain_tar_archive(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_tar_variant_"))
        report_dir = root / "report"
        node_dir = report_dir / "node-127.0.0.1-MA"
        node_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "globalInfo").mkdir(parents=True, exist_ok=True)

        (node_dir / "informationSchemaMvNodes.json").write_text(json.dumps({
            "rows": [{"MEMSQL_ID": 1, "HOSTNAME": "node1", "ROLE": "Master Aggregator", "STATE": "online"}]
        }))

        tar_path = root / "report.tar"
        with tarfile.open(tar_path, "w:") as tf:
            for p in report_dir.rglob("*"):
                tf.add(p, p.relative_to(report_dir.parent))

        parsed = parse_report_archive_streaming(str(tar_path))
        self.assertEqual(parsed.get("detected_format"), "tar")
        self.assertEqual(parsed.get("raw_node_count"), 1)

    def test_parses_uuid_named_node_dir(self):
        # Real sdb-report bundles often name node dirs by host/UUID with no
        # -MA/-LEAF role suffix. These must still be detected so topology fills.
        root = Path(tempfile.mkdtemp(prefix="s2rs_uuid_node_"))
        report_dir = root / "report-2026-06-19T100325"
        node_dir = report_dir / "3f9a1c2e-0b7d-4c11-9a2e-abc123456789"
        node_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "globalInfo").mkdir(parents=True, exist_ok=True)

        (node_dir / "informationSchemaMvNodes.json").write_text(json.dumps({
            "rows": [
                {"ID": 1, "TYPE": "MA", "STATE": "online", "MAX_MEMORY_MB": 4096},
                {"ID": 2, "TYPE": "LEAF", "STATE": "online", "MAX_MEMORY_MB": 8192},
            ]
        }))

        zip_path = root / "report.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in report_dir.rglob("*"):
                zf.write(p, p.relative_to(report_dir.parent))

        parsed = parse_report_archive_streaming(str(zip_path))
        co = parsed.get("cluster_overview") or {}
        self.assertEqual(co.get("total_nodes"), 2)
        self.assertEqual(co.get("leaves"), 1)
        self.assertEqual(co.get("aggregators"), 1)

    def test_detects_node_dir_by_content_without_mv_nodes(self):
        # Sparse bundle: node dir name carries no role and there is no
        # informationSchemaMvNodes.json — detection falls back to content and a
        # minimal overview is derived so the dashboard is not all-zero.
        root = Path(tempfile.mkdtemp(prefix="s2rs_content_node_"))
        report_dir = root / "report"
        node_dir = report_dir / "node1"
        node_dir.mkdir(parents=True, exist_ok=True)
        (node_dir / "memsql.log").write_text("2026-05-01 10:00:00 INFO memsql started\n")
        (node_dir / "show-variables.tsv").write_text("Variable_name\tValue\nversion\t8.1.0\n")

        zip_path = root / "report.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in report_dir.rglob("*"):
                zf.write(p, p.relative_to(report_dir.parent))

        parsed = parse_report_archive_streaming(str(zip_path))
        self.assertEqual(parsed.get("raw_node_count"), 1)
        co = parsed.get("cluster_overview") or {}
        self.assertEqual(co.get("total_nodes"), 1)
        self.assertEqual(co.get("derived_from"), "node_directories")

    def test_parses_tar_gz_with_dot_root_member(self):
        # `tar czf report.tar.gz .` produces a leading "." root member; the
        # extractor must skip it rather than rejecting the whole archive.
        root = Path(tempfile.mkdtemp(prefix="s2rs_dotroot_"))
        src = root / "src"
        node_dir = src / "node-127.0.0.1-MA"
        node_dir.mkdir(parents=True, exist_ok=True)
        (src / "globalInfo").mkdir(parents=True, exist_ok=True)
        (node_dir / "informationSchemaMvNodes.json").write_text(json.dumps({
            "rows": [{"ID": 1, "TYPE": "MA", "STATE": "online"}]
        }))

        tar_path = root / "report.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(str(src), arcname=".")

        # Sanity check: the archive actually contains a bare "." member.
        with tarfile.open(tar_path, "r:gz") as tf:
            self.assertIn(".", [m.name for m in tf.getmembers()])

        parsed = parse_report_archive_streaming(str(tar_path))
        self.assertEqual(parsed.get("raw_node_count"), 1)
        co = parsed.get("cluster_overview") or {}
        self.assertEqual(co.get("total_nodes"), 1)

    def test_rejects_truncated_tar_gz_archive(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_bad_targz_"))
        tar_path = root / "broken.tar.gz"
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as tf:
            data = json.dumps({"ok": True}).encode("utf-8")
            info = tarfile.TarInfo(name="cluster.json")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        broken_bytes = payload.getvalue()[:-8]
        tar_path.write_bytes(broken_bytes)

        with self.assertRaisesRegex(ValueError, "Corrupted or incomplete gzip archive"):
            parse_report_archive_streaming(str(tar_path))


if __name__ == "__main__":
    unittest.main()

