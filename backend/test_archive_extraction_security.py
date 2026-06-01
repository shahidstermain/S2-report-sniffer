import io
import shutil
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from parsers import parse_report_archive_streaming


class TestArchiveExtractionSecurity(unittest.TestCase):
    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix="s2rs_extract_security_"))
        self.extract_dir = self.parent / "extract"
        self.extract_dir.mkdir()
        self.outside_file = self.parent / "pwned.txt"

    def tearDown(self):
        shutil.rmtree(self.parent, ignore_errors=True)

    def test_tar_rejects_traversal_member_before_write(self):
        archive_path = self.parent / "malicious.tar"
        with tarfile.open(archive_path, "w") as tf:
            data = b"owned"
            info = tarfile.TarInfo("safe/../../pwned.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        with patch("parsers.tempfile.mkdtemp", return_value=str(self.extract_dir)):
            with self.assertRaises(ValueError):
                parse_report_archive_streaming(str(archive_path))

        self.assertFalse(self.outside_file.exists())

    def test_zip_rejects_traversal_member_before_write(self):
        archive_path = self.parent / "malicious.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("safe/../../pwned.txt", "owned")

        with patch("parsers.tempfile.mkdtemp", return_value=str(self.extract_dir)):
            with self.assertRaises(ValueError):
                parse_report_archive_streaming(str(archive_path))

        self.assertFalse(self.outside_file.exists())


if __name__ == "__main__":
    unittest.main()
