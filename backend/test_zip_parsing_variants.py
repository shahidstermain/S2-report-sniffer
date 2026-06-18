import unittest
import gzip
import io
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import parsers
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

    def test_tar_members_cannot_escape_extract_dir(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_tar_escape_"))
        tar_path = root / "escape.tar"
        escaped_path = root / "leak" / "escaped.txt"

        with tarfile.open(tar_path, "w:") as tf:
            data = b"escaped"
            info = tarfile.TarInfo(name=f"safe/../../{root.name}/leak/escaped.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        with self.assertRaisesRegex(ValueError, "Path escape attempt"):
            parse_report_archive_streaming(str(tar_path))

        self.assertFalse(escaped_path.exists())

    def test_plain_gzip_payload_respects_extraction_budget(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_gz_budget_"))
        gz_path = root / "large.gz"

        with gzip.open(gz_path, "wb") as f:
            f.write(b"x" * 128)

        with patch.object(parsers, "MAX_EXTRACTED_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "Archive exceeds maximum safe extraction size"):
                parse_report_archive_streaming(str(gz_path))


if __name__ == "__main__":
    unittest.main()

