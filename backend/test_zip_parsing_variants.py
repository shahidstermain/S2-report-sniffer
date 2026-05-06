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

    def test_tar_symlink_member_cannot_write_outside_extract_dir(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_tar_escape_"))
        victim_dir = root / "victim"
        victim_dir.mkdir()
        tar_path = root / "report.tar"

        with tarfile.open(tar_path, "w:") as tf:
            global_info = tarfile.TarInfo(name="report/globalInfo/")
            global_info.type = tarfile.DIRTYPE
            tf.addfile(global_info)

            node_dir = tarfile.TarInfo(name="report/node-127.0.0.1-MA/")
            node_dir.type = tarfile.DIRTYPE
            tf.addfile(node_dir)

            node_data = json.dumps({
                "rows": [{"MEMSQL_ID": 1, "HOSTNAME": "node1", "ROLE": "Master Aggregator", "STATE": "online"}]
            }).encode("utf-8")
            node_info = tarfile.TarInfo(name="report/node-127.0.0.1-MA/informationSchemaMvNodes.json")
            node_info.size = len(node_data)
            tf.addfile(node_info, io.BytesIO(node_data))

            symlink = tarfile.TarInfo(name="report/leak")
            symlink.type = tarfile.SYMTYPE
            symlink.linkname = str(victim_dir)
            tf.addfile(symlink)

            escaped_data = b"escaped"
            escaped_info = tarfile.TarInfo(name="report/leak/pwned.txt")
            escaped_info.size = len(escaped_data)
            tf.addfile(escaped_info, io.BytesIO(escaped_data))

        parsed = parse_report_archive_streaming(str(tar_path))

        self.assertEqual(parsed.get("raw_node_count"), 1)
        self.assertFalse((victim_dir / "pwned.txt").exists())

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

