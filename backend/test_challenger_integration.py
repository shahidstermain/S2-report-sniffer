"""
Adversarial Integration Tests for Diagnostic Checker Logic, Validators, Monitoring, and Storage.
Written by Adversarial Test Challenger 2.
"""
import unittest
import tempfile
import shutil
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from validators import (
    validate_report_structure,
    validate_parsed_report_safe,
    RequestValidator,
    ValidationError
)
from superchecker import run_superchecker, _CheckerState
from parsers import generate_recommendations
from storage import LocalReportStore
from monitoring import (
    record_parsing_duration,
    record_validation_failure,
    record_security_event,
    record_upload_attempt,
    record_upload_complete,
    get_metrics,
    get_alerts
)

class TestChallengerIntegration(unittest.TestCase):
    def setUp(self):
        # Setup temporary directories for LocalReportStore
        self.test_dir = tempfile.mkdtemp(prefix="s2rs_challenger_")
        self.base_dir = Path(self.test_dir)
        self.store = LocalReportStore(base_dir=self.base_dir)

    def tearDown(self):
        # Cleanup temporary files
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_validators_with_checker_outputs(self):
        # Construct report containing typical schema output with new checks
        report = {
            "report_name": "Test integration bundle",
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "nodes": [
                {
                    "hostname": "node-1.s2.internal",
                    "role": "Master",
                    "os_checks": {
                        "thp": {
                            "enabled": "[never]",
                            "defrag": "always",
                            "status": "enabled",
                            "active": "never",
                            "active_defrag": "always"
                        },
                        "sysctl": {
                            "vm.max_map_count": {"numeric": 120000, "value": "120000"},
                            "vm.swappiness": {"numeric": 15, "value": "15"},
                            "net.core.somaxconn": {"numeric": 512, "value": "512"}
                        }
                    },
                    "metrics": {
                        "sys_info": {
                            "vm.min_free_kbytes": 153600,
                            "kernel.sched_rt_runtime_us": 950000,
                            "cpu_memory_bandwidth": "normal",
                            "disk_bandwidth": "normal",
                            "partitions_start": "aligned",
                            "installed_permissions": "pass",
                            "cgroup_memory": "disabled"
                        }
                    }
                }
            ],
            "config_health": {
                "os_checks": [
                    {
                        "name": "Transparent Huge Pages",
                        "status": "fail",
                        "detail": "enabled is never but defrag is always",
                        "nodes": ["node-1.s2.internal"]
                    }
                ]
            }
        }

        # 1. Test validator structure validation
        res = validate_report_structure(report)
        self.assertTrue(res.is_valid)

        # 2. Test safety checks (detecting dangerous scripts/patterns)
        safe = validate_parsed_report_safe(report)
        self.assertTrue(safe)

        # 3. Test validation rejection under hostile/bad data
        bad_report = {
            "report_name": "Bad report",
            "parsed_at": "now",
            "nodes": [
                {
                    "hostname": "bad/host",  # invalid slash
                    "role": "Leaf"
                }
            ]
        }
        res_bad = validate_report_structure(bad_report)
        self.assertFalse(res_bad.is_valid)

        # 4. Test safety rejection of dangerous content
        dangerous_report = {
            "report_name": "Danger <script>alert(1)</script>",
            "parsed_at": "now",
            "nodes": [{"hostname": "node-1", "role": "Master"}]
        }
        self.assertFalse(validate_parsed_report_safe(dangerous_report))

    def test_superchecker_output_payload_content(self):
        # Test full checker flow execution to ensure new parameters produce the expected findings
        report = {
            "nodes": [
                {
                    "hostname": "node-1",
                    "role": "Master",
                    "os_checks": {
                        "thp": {
                            "enabled": "[never]",
                            "defrag": "always",
                            "status": "enabled",
                            "active": "never",
                            "active_defrag": "always"
                        },
                        "sysctl": {
                            "vm.max_map_count": {"numeric": 120000, "value": "120000"},
                            "vm.swappiness": {"numeric": 15, "value": "15"},
                            "net.core.somaxconn": {"numeric": 512, "value": "512"}
                        }
                    }
                }
            ]
        }
        findings = run_superchecker(report)

        # Map findings by checker_id
        by_id = {f["checker_id"]: f for f in findings}

        # Ensure findings exist for transparentHugepage, vmMaxMapCount, vmSwappiness, and somaxconnLimit
        self.assertIn("transparentHugepage", by_id)
        self.assertIn("vmMaxMapCount", by_id)
        self.assertIn("vmSwappiness", by_id)
        self.assertIn("somaxconnLimit", by_id)

        # Verify severities and formats
        self.assertEqual(by_id["transparentHugepage"]["severity"], "critical")
        self.assertEqual(by_id["vmMaxMapCount"]["severity"], "critical")
        self.assertEqual(by_id["vmSwappiness"]["severity"], "warning")
        self.assertEqual(by_id["somaxconnLimit"]["severity"], "warning")

        # Verify correct types in fields
        for f in findings:
            self.assertIsInstance(f["title"], str)
            self.assertIsInstance(f["description"], str)
            self.assertIsInstance(f["evidence"], str)
            self.assertIsInstance(f["remediation"], str)
            self.assertIsInstance(f["nodes"], list)
            self.assertIsInstance(f["risk_score"], int)

    def test_storage_integration_with_superchecker_payload(self):
        # We run the superchecker, get findings, construct the payload dict,
        # write it to SQLite & JSON storage, and read it back to guarantee compatibility.
        report_id = "00000000-0000-0000-0000-000000000001"
        report_name = "test_integration_report.zip"
        file_size = 1048576
        detected_format = "zip"

        report_data = {
            "report_name": "Integration Report",
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "nodes": [
                {
                    "hostname": "host-a",
                    "role": "Master",
                    "os_checks": {
                        "thp": {"enabled": "always", "defrag": "always", "active": "always", "active_defrag": "always"},
                        "sysctl": {
                            "vm.max_map_count": {"numeric": 200000, "value": "200000"},
                            "vm.swappiness": {"numeric": 60, "value": "60"},
                            "net.core.somaxconn": {"numeric": 128, "value": "128"}
                        }
                    }
                }
            ]
        }

        # Run superchecker to get recommendations
        recs = run_superchecker(report_data)

        # Create stub
        asyncio.run(self.store.create_report_stub(report_id, report_name, file_size, detected_format))

        # Update metadata fields
        update_fields = {
            "status": "ready",
            "node_count": len(report_data["nodes"]),
            "version": "8.5",
            "health_score": "80",
            "recommendation_count": len(recs),
            "cluster_risk_score": 45,
            "deployment_method": "operator",
            "deployment_confidence": "high",
            "deployment_signals": "operator-process,k8s-labels",
            "parsed_at": report_data["parsed_at"],
        }
        asyncio.run(self.store.update_report_fields(report_id, update_fields))

        # Assemble full payload
        payload = dict(report_data)
        payload["id"] = report_id
        payload["report_name"] = report_name
        payload["uploaded_at"] = datetime.now(timezone.utc).isoformat()
        payload["file_size"] = file_size
        payload["detected_format"] = detected_format
        payload["recommendations"] = recs

        # Write payload
        asyncio.run(self.store.write_report_payload(report_id, payload))

        # Read back metadata
        meta = asyncio.run(self.store.get_report_fields(report_id))
        self.assertIsNotNone(meta)
        self.assertEqual(meta["status"], "ready")
        self.assertEqual(meta["node_count"], 1)
        self.assertEqual(meta["deployment_method"], "operator")
        self.assertEqual(meta["deployment_confidence"], "high")

        # Read back payload
        loaded_payload = asyncio.run(self.store.read_report_payload(report_id))
        self.assertIsNotNone(loaded_payload)
        self.assertEqual(loaded_payload["id"], report_id)
        self.assertEqual(len(loaded_payload["recommendations"]), len(recs))

        # Check that we can find our new findings in recommendations
        findings_ids = [f["checker_id"] for f in loaded_payload["recommendations"]]
        self.assertIn("transparentHugepage", findings_ids)
        self.assertIn("vmMaxMapCount", findings_ids)
        self.assertIn("vmSwappiness", findings_ids)
        self.assertIn("somaxconnLimit", findings_ids)

        # Try list reports
        reports_list = asyncio.run(self.store.list_reports())
        self.assertEqual(len(reports_list), 1)
        self.assertEqual(reports_list[0]["id"], report_id)
        self.assertEqual(reports_list[0]["deployment_method"], "operator")

        # Delete report
        deleted = asyncio.run(self.store.delete_report(report_id))
        self.assertTrue(deleted)

    def test_monitoring_integration(self):
        # Verify that all monitoring helper functions work fine with typical parameters
        report_id = "00000000-0000-0000-0000-000000000002"

        # Record parsing duration (success)
        record_parsing_duration(report_id, 125.5, "success")
        metrics = get_metrics()
        self.assertGreaterEqual(metrics.get_counter("parsing.total"), 1)

        # Record parsing duration (error)
        record_parsing_duration(report_id, 45.0, "error")
        self.assertGreaterEqual(metrics.get_counter("parsing.total"), 2)

        # Record validation failure
        record_validation_failure("upload", {"filename": "bad.exe", "reason": "extension_not_allowed"})
        self.assertGreaterEqual(metrics.get_counter("validation.failures"), 1)

        # Record security event
        record_security_event("path_traversal_attempt", {"ip": "127.0.0.1", "path": "../etc/passwd"})
        self.assertGreaterEqual(metrics.get_counter("security.events"), 1)

        # Record upload attempt
        upload_id = record_upload_attempt("report.zip", 2048)
        self.assertTrue(len(upload_id) > 0)
        self.assertGreaterEqual(metrics.get_counter("uploads.total"), 1)

        # Record upload complete
        record_upload_complete(report_id, "report.zip", 300.0, "success")


if __name__ == "__main__":
    unittest.main()
