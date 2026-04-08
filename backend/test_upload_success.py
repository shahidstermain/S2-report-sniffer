import unittest
import io
import zipfile
import tempfile
import json
import os
from unittest.mock import patch
from fastapi.testclient import TestClient

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_success_")

with patch.dict('os.environ', {'MONGO_URL': 'mongodb://localhost:27017', 'S2RS_DATA_DIR': TEST_DATA_DIR}):
    from server import app

class TestUploadSuccess(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_upload_valid_zip(self):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("cluster.json", json.dumps({"nodes": []}))
        
        zip_buffer.seek(0)
        
        response = self.client.post(
            "/api/reports/upload",
            files={"file": ("test_report.zip", zip_buffer, "application/zip")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data.get("status"), "processing")
        self.assertEqual(data.get("detected_format"), "zip")

    def test_upload_valid_zip_accepts_report_field_name(self):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("cluster.json", json.dumps({"nodes": []}))

        zip_buffer.seek(0)

        response = self.client.post(
            "/api/reports/upload",
            files={"report": ("test_report.zip", zip_buffer, "application/zip")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data.get("status"), "processing")
        self.assertEqual(data.get("detected_format"), "zip")

    def test_upload_valid_tar_gz(self):
        import tarfile
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
            with tarfile.open(name=tmp.name, mode="w:gz") as tf:
                info = tarfile.TarInfo(name="cluster.json")
                data = json.dumps({"nodes": []}).encode("utf-8")
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            tmp.seek(0)
            tar_buffer = io.BytesIO(tmp.read())
            tar_buffer.seek(0)
        
        response = self.client.post(
            "/api/reports/upload",
            files={"file": ("test_report.tar.gz", tar_buffer, "application/gzip")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data.get("status"), "processing")
        self.assertEqual(data.get("detected_format"), "tar.gz")

if __name__ == "__main__":
    unittest.main()
