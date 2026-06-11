import asyncio
import tempfile
import unittest
from pathlib import Path

from storage import LocalReportStore


class TestLocalReportStoreLogQueries(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = LocalReportStore(Path(self.tmpdir.name))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_query_report_logs_matches_uppercase_severity_filters(self):
        report_id = "report-with-logs"
        asyncio.run(
            self.store.write_report_logs(
                report_id,
                [
                    {
                        "timestamp": "2024-01-15T10:00:00Z",
                        "severity": "ERROR",
                        "hostname": "node-a",
                        "message": "Connection timeout",
                    },
                    {
                        "timestamp": "2024-01-15T10:00:01Z",
                        "severity": "INFO",
                        "hostname": "node-a",
                        "message": "Recovered",
                    },
                ],
            )
        )

        logs, total = asyncio.run(
            self.store.query_report_logs(
                report_id=report_id,
                search="timeout",
                severities=["ERROR"],
                node_prefix=None,
                page=1,
                page_size=10,
            )
        )

        self.assertEqual(total, 1)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["severity"], "ERROR")


if __name__ == "__main__":
    unittest.main()
