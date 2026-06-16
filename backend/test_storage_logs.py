import tempfile
import unittest
from pathlib import Path

from storage import LocalReportStore


class TestLocalReportStoreLogQueries(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalReportStore(Path(self.tmpdir.name))
        self.report_id = "report-1"
        await self.store.write_report_logs(
            self.report_id,
            [
                {
                    "timestamp": "2024-01-15T10:00:00Z",
                    "severity": "ERROR",
                    "hostname": "node-a",
                    "message": "Failed to connect to leaf",
                },
                {
                    "timestamp": "2024-01-15T10:00:01Z",
                    "severity": "WARN",
                    "hostname": "node-a",
                    "message": "Memory pressure above threshold",
                },
            ],
        )

    async def asyncTearDown(self):
        self.tmpdir.cleanup()

    async def test_query_report_logs_normalizes_uppercase_severity_filters(self):
        logs, total = await self.store.query_report_logs(
            report_id=self.report_id,
            search="Failed",
            severities=["ERROR"],
            node_prefix=None,
            page=1,
            page_size=10,
        )

        self.assertEqual(total, 1)
        self.assertEqual([row["severity"] for row in logs], ["ERROR"])

    async def test_query_report_logs_matches_warning_alias_to_warn_rows(self):
        logs, total = await self.store.query_report_logs(
            report_id=self.report_id,
            search="Memory",
            severities=["warning"],
            node_prefix=None,
            page=1,
            page_size=10,
        )

        self.assertEqual(total, 1)
        self.assertEqual([row["severity"] for row in logs], ["WARN"])


if __name__ == "__main__":
    unittest.main()
