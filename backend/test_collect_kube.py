import json
import tempfile
import unittest
from pathlib import Path

from parsers import parse_collect_kube


class TestCollectKubeParsing(unittest.TestCase):
    def test_parse_collect_kube_populates_expected_fields(self):
        root = Path(tempfile.mkdtemp(prefix="s2rs_collect_kube_"))
        pod_dir = root / "memsql-leaf-0"
        pod_dir.mkdir(parents=True, exist_ok=True)

        (pod_dir / "informationSchemaMvNodes.json").write_text(json.dumps({
            "rows": [{
                "MEMSQL_ID": 1,
                "HOSTNAME": "leaf-0",
                "ROLE": "Leaf",
                "TYPE": "LEAF",
                "STATE": "online",
                "MAX_MEMORY_MB": 1024,
                "MEMORY_USED_MB": 256,
                "TOTAL_DATA_DISK_MB": 2048,
                "AVAILABLE_DATA_DISK_MB": 1024,
                "NUM_CPUS": 4
            }]
        }))
        (pod_dir / "showClusterStatus.json").write_text(json.dumps({
            "rows": [{"Host": "leaf-0", "Role": "Leaf", "State": "online"}]
        }))
        (pod_dir / "informationSchemaMvQueries.json").write_text(json.dumps({
            "rows": [{"QUERY_TEXT": "select 1", "STATE": "running"}]
        }))
        (pod_dir / "informationSchemaMvEvents.json").write_text(json.dumps({
            "rows": [{"EVENT_TYPE": "test_event", "SEVERITY": "INFO"}]
        }))
        (pod_dir / "informationSchemaMvBackupHistory.json").write_text(json.dumps({
            "rows": [{
                "STATUS": "success",
                "START_TIMESTAMP": "2026-04-22 10:00:00",
                "END_TIMESTAMP": "2026-04-22 10:05:00"
            }]
        }))
        (pod_dir / "informationSchemaProcesslist.json").write_text(json.dumps({
            "rows": [{
                "NODE_ID": 1,
                "ID": 100,
                "USER": "root",
                "HOST": "leaf-0",
                "DB": "test",
                "COMMAND": "Query",
                "TIME": 3,
                "STATE": "Running",
                "INFO": "select 1"
            }]
        }))

        parsed = parse_collect_kube(str(root), "collect-kube-report")

        self.assertEqual(parsed.get("bundle_type"), "K8s-Operator")
        self.assertEqual(parsed.get("raw_node_count"), 1)
        self.assertEqual(len(parsed.get("queries", [])), 1)
        self.assertEqual(len(parsed.get("events", [])), 1)
        self.assertEqual(parsed.get("backup_summary", {}).get("success_count"), 1)
        self.assertIn("cluster_status", parsed.get("cluster_overview", {}))
        self.assertIn("processlist", parsed.get("cluster_overview", {}))
        self.assertIn("recommendations", parsed)
        self.assertIn("cluster_layout", parsed)
        self.assertIn("process_health", parsed)
        self.assertEqual(parsed.get("dmesg_events"), [])

        node = parsed.get("nodes", [])[0]
        self.assertNotIn("trace_logs", node)
        self.assertNotIn("mv_queries", node)
        self.assertNotIn("processlist", node)


if __name__ == "__main__":
    unittest.main()
