import unittest

from grounding import DOCUMENTED, HEURISTIC, get_grounding
from superchecker import _CheckerState


def _findings_for(report: dict, method: str) -> list[dict]:
    state = _CheckerState(report)
    getattr(state, method)()
    return state.findings


class GroundingAlignmentTests(unittest.TestCase):
    def test_operational_thresholds_are_labeled_as_heuristics(self):
        for checker_id in (
            "cgroupMemoryUsage",
            "backupReliability",
            "cpuIowait",
            "diskMountDiscard",
            "diskMountNoatime",
            "memoryUtilizationCritical",
            "partitionCoreRatio",
            "replicationLag",
            "replicationLagDegraded",
            "tcpKeepalive",
            "usedClusterCapacity",
        ):
            with self.subTest(checker_id=checker_id):
                self.assertEqual(HEURISTIC, get_grounding(checker_id)["basis"])

    def test_cpu_governor_is_documented(self):
        grounding = get_grounding("cpuGovernor")
        self.assertEqual(DOCUMENTED, grounding["basis"])
        self.assertIn("performance", grounding["criterion"])

    def test_all_superchecker_checker_ids_are_grounded(self):
        import re
        from grounding import GROUNDING
        with open("backend/superchecker.py") as f:
            sc_code = f.read()
        checker_ids = set(re.findall(r'checker_id=[\"\x27]([a-zA-Z0-9_]+)[\"\x27]', sc_code))
        missing = checker_ids - set(GROUNDING.keys())
        self.assertEqual(set(), missing, f"Ungrounded checker IDs: {missing}")

    def test_documented_maximum_memory_formula_is_exact(self):
        grounding = get_grounding("maxMemorySettings")
        self.assertEqual(DOCUMENTED, grounding["basis"])
        self.assertIn("0.91 * RAM - 1 MB", grounding["criterion"])
        self.assertIn("maximum_table_memory <91%", grounding["criterion"])

    def test_long_running_query_grounding_matches_runtime_bands(self):
        criterion = get_grounding("longRunningQueries")["criterion"]
        self.assertIn(">30s", criterion)
        self.assertIn(">300s", criterion)


class CheckerAlignmentTests(unittest.TestCase):
    def test_query_elapsed_bands_are_30_and_300_seconds(self):
        warning = _findings_for(
            {"query_patterns": {
                "slow_count": 1,
                "runaway_count": 0,
                "max_elapsed_sec": 31,
                "slow_queries": [{"user": "u", "database": "db", "query_text": "select 1"}],
            }},
            "_check_query_patterns",
        )
        critical = _findings_for(
            {"query_patterns": {
                "slow_count": 0,
                "runaway_count": 1,
                "max_elapsed_sec": 301,
                "runaway_queries": [{"user": "u", "database": "db", "query_text": "select 1"}],
            }},
            "_check_query_patterns",
        )
        self.assertEqual("slowQueries", warning[0]["checker_id"])
        self.assertEqual("warning", warning[0]["severity"])
        self.assertEqual("runawayQueries", critical[0]["checker_id"])
        self.assertEqual("critical", critical[0]["severity"])

    def test_disk_latency_uses_documented_10_and_25_ms_bands_for_ssd(self):
        def report(read_ms: float) -> dict:
            return {
                "nodes": [{
                    "hostname": "leaf-1",
                    "metrics": {
                        "disk_latency": [{
                            "device": "nvme0n1",
                            "read_await_ms": read_ms,
                            "write_await_ms": 0,
                            "util_pct": 0,
                            "rota": 0,
                        }]
                    },
                }]
            }

        self.assertEqual([], _findings_for(report(6), "_check_disk_latency"))
        self.assertEqual(
            "warning",
            _findings_for(report(11), "_check_disk_latency")[0]["severity"],
        )
        self.assertEqual(
            "critical",
            _findings_for(report(26), "_check_disk_latency")[0]["severity"],
        )

    def test_posix_data_filesystems_are_not_rejected(self):
        report = {
            "nodes": [{
                "hostname": "leaf-1",
                "metrics": {
                    "mounts": [{
                        "mount": "/data",
                        "fstype": "zfs",
                        "is_data_device": "true",
                    }]
                },
            }]
        }
        findings = _findings_for(report, "_check_numa_ssd_filesystem")
        self.assertFalse(any(f["checker_id"] == "filesystemType" for f in findings))

    def test_volatile_data_filesystem_is_rejected(self):
        report = {
            "nodes": [{
                "hostname": "leaf-1",
                "metrics": {
                    "mounts": [{
                        "mount": "/data",
                        "fstype": "tmpfs",
                        "is_data_device": "true",
                    }]
                },
            }]
        }
        findings = _findings_for(report, "_check_numa_ssd_filesystem")
        self.assertEqual("filesystemType", findings[0]["checker_id"])

    def test_data_and_general_disk_thresholds_are_distinct(self):
        report = {
            "nodes": [{
                "hostname": "leaf-1",
                "metrics": {
                    "disk": [
                        {"mounted_on": "/data", "use_pct": 65, "iuse_pct": 0},
                        {"mounted_on": "/var", "use_pct": 65, "iuse_pct": 0},
                    ]
                },
            }]
        }
        findings = _findings_for(report, "_check_disk_usage_and_inodes")
        disk_findings = [f for f in findings if f["checker_id"] == "diskUsage"]
        self.assertEqual(1, len(disk_findings))
        self.assertIn("/data", disk_findings[0]["evidence"])

    def test_kubernetes_uses_operator_maximum_memory_ceiling(self):
        report = {
            "deployment_method": "Kubernetes Operator",
            "nodes": [{
                "hostname": "leaf-1",
                "show_variables": {"maximum_memory": 90_000},
                "metrics": {"memory": {"total_mb": 100_000}},
            }],
        }
        findings = _findings_for(report, "_check_versions_license_and_max_memory")
        maximum_memory = [
            f for f in findings
            if f["checker_id"] == "maxMemorySettings"
            and "maximum_memory=" in f["evidence"]
        ]
        self.assertEqual(1, len(maximum_memory))
        self.assertIn("0.80", maximum_memory[0]["evidence"])

    def test_maximum_table_memory_must_stay_below_91_percent(self):
        report = {
            "nodes": [{
                "hostname": "leaf-1",
                "show_variables": {
                    "maximum_memory": 80_000,
                    "maximum_table_memory": 91_000,
                },
                "metrics": {"memory": {"total_mb": 100_000}},
            }],
        }
        findings = _findings_for(report, "_check_versions_license_and_max_memory")
        table_memory = [
            f for f in findings
            if f["checker_id"] == "maxMemorySettings"
            and "maximum_table_memory=" in f["evidence"]
        ]
        self.assertEqual(1, len(table_memory))

    def test_superchecker_resilience_to_malformed_and_null_inputs(self):
        from superchecker import run_superchecker

        malformed_reports = [
            {},
            {"nodes": None, "cluster_overview": None},
            {"nodes": [None, {}, {"hostname": None, "metrics": None, "show_variables": None, "config": None, "os_checks": None}]},
            {"nodes": [{"metrics": {"memory": None, "disk": None, "cpu": None, "ps": None, "mounts": None}}]},
            {"cluster_overview": {"total_nodes": "bad", "total_memory_mb": "bad", "nodes_detail": [None, {}]}},
        ]
        for rep in malformed_reports:
            with self.subTest(rep=rep):
                # Must execute cleanly without unhandled exception
                findings = run_superchecker(rep)
                self.assertIsInstance(findings, list)


if __name__ == "__main__":
    unittest.main()
