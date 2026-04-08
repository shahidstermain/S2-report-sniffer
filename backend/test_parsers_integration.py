import unittest
import os
import tempfile
import json
import zipfile
import asyncio
from unittest.mock import patch
from parsers import parse_report_archive_streaming

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

if __name__ == "__main__":
    unittest.main()
