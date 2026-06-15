import asyncio
import io
import tarfile
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from parsers import parse_report_archive_streaming
import server as server_module
from storage import LocalReportStore


class TestArchiveExtractionSafety(unittest.TestCase):
    def test_tar_absolute_member_cannot_write_outside_extract_dir(self):
        marker = Path(tempfile.gettempdir()) / f"s2rs_tar_slip_{uuid.uuid4().hex}.txt"
        archive_path = Path(tempfile.gettempdir()) / f"s2rs_tar_slip_{uuid.uuid4().hex}.tar"
        marker.unlink(missing_ok=True)
        try:
            with tarfile.open(archive_path, "w") as tf:
                data = b"escaped"
                info = tarfile.TarInfo(str(marker))
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

            with self.assertRaises(ValueError):
                parse_report_archive_streaming(str(archive_path))
            self.assertFalse(marker.exists())
        finally:
            marker.unlink(missing_ok=True)
            archive_path.unlink(missing_ok=True)


class TestDiffEndpointSafety(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server_module.app, raise_server_exceptions=False)

    def test_diff_rejects_invalid_report_ids_before_storage_lookup(self):
        response = self.client.get(
            "/api/reports/diff",
            params={"from_id": "../report", "to_id": str(uuid.uuid4())},
        )
        self.assertEqual(response.status_code, 400)

    def test_diff_uses_local_import_path_for_valid_reports(self):
        with tempfile.TemporaryDirectory(prefix="s2rs_diff_test_") as tmpdir:
            old_store = server_module.store
            test_store = LocalReportStore(Path(tmpdir))
            server_module.store = test_store
            try:
                from_id = str(uuid.uuid4())
                to_id = str(uuid.uuid4())
                asyncio.run(test_store.create_report_stub(from_id, "from.tar.gz", 1, "tar.gz"))
                asyncio.run(test_store.create_report_stub(to_id, "to.tar.gz", 1, "tar.gz"))
                asyncio.run(test_store.write_report_payload(from_id, {"recommendations": []}))
                asyncio.run(
                    test_store.write_report_payload(
                        to_id,
                        {
                            "recommendations": [
                                {
                                    "checker_id": "disk_space",
                                    "title": "Disk space low",
                                    "severity": "warning",
                                    "risk_score": 50,
                                }
                            ]
                        },
                    )
                )

                response = self.client.get(
                    "/api/reports/diff",
                    params={"from_id": from_id, "to_id": to_id},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["new"], [{"title": "Disk space low", "checker_id": "disk_space"}])
            finally:
                server_module.store = old_store


class TestLocalReportStoreSafety(unittest.TestCase):
    def test_failed_payload_write_preserves_existing_payload(self):
        with tempfile.TemporaryDirectory(prefix="s2rs_payload_test_") as tmpdir:
            store = LocalReportStore(Path(tmpdir))
            report_id = str(uuid.uuid4())
            asyncio.run(store.write_report_payload(report_id, {"status": "old"}))

            def fail_after_partial_write(payload, file_obj):
                file_obj.write('{"status":')
                raise RuntimeError("simulated serialization failure")

            with patch("storage.json.dump", side_effect=fail_after_partial_write):
                with self.assertRaises(RuntimeError):
                    asyncio.run(store.write_report_payload(report_id, {"status": "new"}))

            self.assertEqual(asyncio.run(store.read_report_payload(report_id)), {"status": "old"})


if __name__ == "__main__":
    unittest.main()
