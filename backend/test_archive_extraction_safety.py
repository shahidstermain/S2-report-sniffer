import gzip
import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import parsers
from parsers import parse_report_archive_streaming


class TestArchiveExtractionSafety(unittest.TestCase):
    def test_rejects_absolute_tar_member_without_writing_outside_extract_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside_path = root / "outside.txt"
            tar_path = root / "malicious.tar"

            payload = b"owned"
            with tarfile.open(tar_path, "w:") as tf:
                info = tarfile.TarInfo(name=str(outside_path))
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))

            with self.assertRaisesRegex(ValueError, "Invalid archive member name|Path escape"):
                parse_report_archive_streaming(str(tar_path))

            self.assertFalse(outside_path.exists())

    def test_gzip_payload_enforces_extracted_size_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gzip_path = root / "large.log.gz"
            extract_dir = root / "extract"
            extract_dir.mkdir()

            with gzip.open(gzip_path, "wb") as fh:
                fh.write(b"x" * 32)

            original_limit = parsers.MAX_EXTRACTED_BYTES
            parsers.MAX_EXTRACTED_BYTES = 16
            try:
                with self.assertRaises(MemoryError):
                    parsers._extract_gzip_payload(str(gzip_path), str(extract_dir), {"total": 0})
            finally:
                parsers.MAX_EXTRACTED_BYTES = original_limit


if __name__ == "__main__":
    unittest.main()
