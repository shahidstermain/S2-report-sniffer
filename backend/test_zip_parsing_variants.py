import unittest
import io
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path

from parsers import _extract_tar_members, parse_report_archive_streaming


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

    def test_tar_extraction_does_not_follow_symlink_outside_extract_root(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_tar_slip_"))
        archive_path = root / "malicious.tar"
        extract_dir = root / "extract"
        outside_dir = root / "outside"
        extract_dir.mkdir()
        outside_dir.mkdir()

        payload = b"escaped"
        with tarfile.open(archive_path, "w:") as tf:
            link = tarfile.TarInfo("report/link")
            link.type = tarfile.SYMTYPE
            link.linkname = str(outside_dir)
            tf.addfile(link)

            escaped = tarfile.TarInfo("report/link/owned.txt")
            escaped.size = len(payload)
            tf.addfile(escaped, io.BytesIO(payload))

        with tarfile.open(archive_path, "r:") as tf:
            _extract_tar_members(tf, str(extract_dir))

        self.assertFalse((outside_dir / "owned.txt").exists())


if __name__ == "__main__":
    unittest.main()

