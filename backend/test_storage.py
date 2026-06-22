import tempfile
import unittest
from pathlib import Path

from storage import LocalReportStore


class TestLocalReportStoreLogFilters(unittest.IsolatedAsyncioTestCase):
    async def test_query_report_logs_normalizes_severity_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalReportStore(Path(tmp))
            report_id = "11111111-1111-1111-1111-111111111111"
            await store.create_report_stub(report_id, "severity-test", 1, "zip")
            await store.write_report_logs(
                report_id,
                [
                    {
                        "timestamp": "2026-01-01T00:00:00Z",
                        "severity": "ERROR",
                        "hostname": "node-a",
                        "message": "disk failed",
                    },
                    {
                        "timestamp": "2026-01-01T00:00:01Z",
                        "severity": "WARN",
                        "hostname": "node-a",
                        "message": "memory warning",
                    },
                ],
            )

            error_logs, error_total = await store.query_report_logs(
                report_id=report_id,
                search="disk",
                severities=["ERROR"],
                node_prefix=None,
                page=1,
                page_size=10,
            )
            warning_logs, warning_total = await store.query_report_logs(
                report_id=report_id,
                search="memory",
                severities=["warning"],
                node_prefix=None,
                page=1,
                page_size=10,
            )

            self.assertEqual(error_total, 1)
            self.assertEqual(len(error_logs), 1)
            self.assertEqual(error_logs[0]["severity"], "ERROR")
            self.assertEqual(warning_total, 1)
            self.assertEqual(len(warning_logs), 1)
            self.assertEqual(warning_logs[0]["severity"], "WARN")


if __name__ == "__main__":
    unittest.main()
