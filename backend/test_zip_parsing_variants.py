import unittest
import io
import json
import gzip
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from parsers import parse_report_archive_streaming
import parsers


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

    def test_rejects_absolute_tar_member_without_writing_outside_extract_dir(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_tar_escape_"))
        outside_path = root.parent / f"{root.name}_outside.txt"
        outside_path.unlink(missing_ok=True)
        tar_path = root / "escape.tar"
        data = b"outside write"

        with tarfile.open(tar_path, "w:") as tf:
            info = tarfile.TarInfo(name=str(outside_path))
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        try:
            with self.assertRaisesRegex(ValueError, "Invalid archive member name"):
                parse_report_archive_streaming(str(tar_path))
            self.assertFalse(outside_path.exists())
        finally:
            outside_path.unlink(missing_ok=True)

    def test_rejects_standalone_gzip_payload_over_extraction_budget(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_gz_budget_"))
        gz_path = root / "large.log.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(b"0123456789")

        original_budget = parsers.MAX_EXTRACTED_BYTES
        parsers.MAX_EXTRACTED_BYTES = 5
        try:
            with self.assertRaisesRegex(ValueError, "maximum safe extraction size"):
                parse_report_archive_streaming(str(gz_path))
        finally:
            parsers.MAX_EXTRACTED_BYTES = original_budget

    def test_package_import_uses_packaged_superchecker(self):
        repo_root = Path(__file__).resolve().parents[1]
        script = """
import importlib
import sys
import types

fake = types.ModuleType("backend.superchecker")
fake.run_superchecker = lambda report: [{"id": "package-superchecker"}]
sys.modules["backend.superchecker"] = fake
parsers = importlib.import_module("backend.parsers")
assert parsers.generate_recommendations({}) == [{"id": "package-superchecker"}]
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            env={"PYTHONPATH": str(repo_root)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

