import unittest
import os
import tempfile
import json
import zipfile
import io
import shutil
import tarfile
from unittest.mock import patch
from parsers import _validate_extract_path, parse_report_archive_streaming

class TestParsersIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="s2rs_parsers_")
        self.zip_path = os.path.join(self.test_dir, "test_report.zip")
        
        cluster_data = {
            "nodes": [
                {
                    "memsql_version": "8.5.1",
                    "role": "Master",
                    "process_name": "memsqld"
                }
            ],
            "version": "1.0",
            "variables": {"max_memory": "1000"}
        }
        
        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("cluster.json", json.dumps(cluster_data))
            zf.writestr("memsql.cnf", "max_memory=1000")
            zf.writestr("tracelogs/memsql.log", "some log line")

    def test_parse_report_full_flow(self):
        result = parse_report_archive_streaming(self.zip_path)

        self.assertIsNotNone(result)
        self.assertIn("cluster_overview", result)
        self.assertIn("nodes", result)
        self.assertIn("recommendations", result)

    def test_tar_members_cannot_write_outside_extract_dir(self):
        archive_path = os.path.join(self.test_dir, "malicious.tar")
        extract_dir = os.path.join(self.test_dir, "extract")
        escaped_path = os.path.join(self.test_dir, "escaped.txt")

        with tarfile.open(archive_path, "w") as tf:
            data = b"owned"
            info = tarfile.TarInfo(name="../escaped.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        with patch("parsers.tempfile.mkdtemp", return_value=extract_dir):
            with self.assertRaises(ValueError):
                parse_report_archive_streaming(archive_path)

        self.assertFalse(os.path.exists(escaped_path))

    def test_validate_extract_path_rejects_traversal_member_names(self):
        for member_name in ("../escaped.txt", "safe/../../escaped.txt"):
            with self.subTest(member_name=member_name):
                with self.assertRaises(ValueError):
                    _validate_extract_path(self.test_dir, member_name)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
