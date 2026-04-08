import unittest
import io
import zipfile
import tempfile
import base64
from unittest.mock import patch
from fastapi.testclient import TestClient

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_zip_edges_")

with patch.dict("os.environ", {"MONGO_URL": "mongodb://localhost:27017", "S2RS_DATA_DIR": TEST_DATA_DIR}):
    from server import app


class TestZipUploadEdgeCases(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_upload_rejects_empty_zip_archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED):
            pass
        buf.seek(0)

        res = self.client.post(
            "/api/reports/upload",
            files={"file": ("empty.zip", buf, "application/zip")},
        )
        self.assertEqual(res.status_code, 400)
        detail = res.json().get("detail")
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("error"), "invalid_zip")
        self.assertIn("empty", str(detail.get("message", "")).lower())

    def test_upload_rejects_corrupt_zip(self):
        buf = io.BytesIO(b"not a zip")
        res = self.client.post(
            "/api/reports/upload",
            files={"file": ("corrupt.zip", buf, "application/zip")},
        )
        self.assertEqual(res.status_code, 400)
        detail = res.json().get("detail")
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("error"), "invalid_zip")

    def test_upload_rejects_password_protected_zip(self):
        b64 = (
            "UEsDBAoACQAAALJ5flyGphA2EQAAAAUAAABKABwAdmFyL2ZvbGRlcnMvZ3IveHYyOHBsZjEwOGJjZHozOXpzenlxOGRjMDAwMGduL1QvczJyc196aXBlbmNfdWRkZV9zYzkvYS50eHRVVAkAA8hFymnIRcppdXgLAAEE9QEAAAQUAAAAi9zs1ZoA"
            "2eqdiPGYaWCeNLBQSwcIhqYQNhEAAAAFAAAAUEsBAh4DCgAJAAAAsnl+XIamEDYRAAAABQAAAEoAGAAAAAAAAQAAAKSBAAAAAHZhci9mb2xkZXJzL2dyL3h2MjhwbGYxMDhiY2R6Mzl6c3p5cThkYzAwMDBnbi9UL3MycnNfemlwZW5jX3VkZGVfc2M5L2EudHh0VVQFAAPIRcppdXgLAAEE9QEAAAQUAAAAUEsFBgAAAAABAAEAkAAAAKUAAAAAAA=="
        )
        raw = base64.b64decode(b64)
        buf = io.BytesIO(raw)
        res = self.client.post(
            "/api/reports/upload",
            files={"file": ("protected.zip", buf, "application/zip")},
        )
        self.assertEqual(res.status_code, 400)
        detail = res.json().get("detail")
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("error"), "encrypted_zip")


if __name__ == "__main__":
    unittest.main()

