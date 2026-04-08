"""
Monitoring module unit tests — QLT-001 coverage expansion.
"""
import unittest
import time
from monitoring import (
    AlertSeverity,
    AlertCategory,
    Alert,
    MetricsCollector,
    AlertManager,
    AuditLogger,
    HealthChecker,
    PerformanceMonitor,
)


class TestAlertDataclass(unittest.TestCase):
    def test_to_dict(self):
        alert = Alert(
            id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            severity="warning",
            category="performance",
            title="High CPU",
            message="CPU above 90%",
            context={"cpu": 95},
        )
        d = alert.to_dict()
        self.assertEqual(d["id"], "test-1")
        self.assertEqual(d["severity"], "warning")
        self.assertEqual(d["context"]["cpu"], 95)
        self.assertFalse(d["resolved"])


class TestMetricsCollector(unittest.TestCase):
    def setUp(self):
        self.mc = MetricsCollector(max_history=5)

    def test_increment_counter(self):
        self.mc.increment("requests")
        self.assertEqual(self.mc.get_counter("requests"), 1)
        self.mc.increment("requests", 5)
        self.assertEqual(self.mc.get_counter("requests"), 6)

    def test_gauge(self):
        self.mc.gauge("cpu_usage", 72.5)
        self.assertEqual(self.mc.get_gauge("cpu_usage"), 72.5)
        self.mc.gauge("cpu_usage", 80.0)
        self.assertEqual(self.mc.get_gauge("cpu_usage"), 80.0)

    def test_timing(self):
        self.mc.timing("request_latency", 45.2)
        entries = self.mc.get_metric("request_latency")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], "timing")
        self.assertEqual(entries[0]["value"], 45.2)

    def test_get_all_metrics(self):
        self.mc.increment("requests")
        self.mc.gauge("cpu", 50.0)
        all_metrics = self.mc.get_all_metrics()
        self.assertEqual(all_metrics["counters"]["requests"], 1)
        self.assertEqual(all_metrics["gauges"]["cpu"], 50.0)

    def test_max_history_enforced(self):
        for i in range(10):
            self.mc.increment("events")
        entries = self.mc.get_metric("events")
        self.assertLessEqual(len(entries), 5)

    def test_get_metric_with_since_filter(self):
        self.mc.increment("requests")
        time.sleep(0.01)
        since = datetime.now(timezone.utc).isoformat()
        time.sleep(0.01)
        self.mc.increment("requests")
        entries = self.mc.get_metric("requests", since=since)
        self.assertEqual(len(entries), 1)

    def test_tags_passed_through(self):
        self.mc.increment("requests", tags={"method": "GET", "endpoint": "/api/health"})
        entries = self.mc.get_metric("requests")
        self.assertEqual(entries[0]["tags"]["method"], "GET")
        self.assertEqual(entries[0]["tags"]["endpoint"], "/api/health")

    def test_get_counter_default_zero(self):
        self.assertEqual(self.mc.get_counter("nonexistent"), 0)

    def test_get_gauge_default_none(self):
        self.assertIsNone(self.mc.get_gauge("nonexistent"))


class TestAlertManager(unittest.TestCase):
    def setUp(self):
        self.am = AlertManager()

    def test_create_and_retrieve_alert(self):
        alert = self.am.create_alert(
            title="Disk Full",
            message="/data at 95%",
            severity=AlertSeverity.ERROR,
            category=AlertCategory.STORAGE,
            deduplication_key="disk-full-1",
        )
        self.assertIsNotNone(alert)
        active = self.am.get_active_alerts()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].title, "Disk Full")

    def test_deduplication_cooldown(self):
        key = "dup-key"
        a1 = self.am.create_alert(
            title="Dup",
            message="msg",
            severity=AlertSeverity.WARNING,
            category=AlertCategory.PARSING,
            deduplication_key=key,
        )
        a2 = self.am.create_alert(
            title="Dup",
            message="msg",
            severity=AlertSeverity.WARNING,
            category=AlertCategory.PARSING,
            deduplication_key=key,
        )
        self.assertIsNone(a2)

    def test_resolve_alert(self):
        key = "resolve-key"
        self.am.create_alert(
            title="Test",
            message="test",
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            deduplication_key=key,
        )
        result = self.am.resolve_alert(key, "Fixed in deploy")
        self.assertTrue(result)
        active = self.am.get_active_alerts()
        self.assertEqual(len(active), 0)

    def test_resolve_nonexistent_returns_false(self):
        self.assertFalse(self.am.resolve_alert("does-not-exist"))

    def test_get_active_alerts_by_severity(self):
        self.am.create_alert(
            title="Err", message="e", severity=AlertSeverity.ERROR,
            category=AlertCategory.SYSTEM, deduplication_key="err-1",
        )
        self.am.create_alert(
            title="Warn", message="w", severity=AlertSeverity.WARNING,
            category=AlertCategory.SYSTEM, deduplication_key="warn-1",
        )
        errors = self.am.get_active_alerts(severity=AlertSeverity.ERROR)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].severity, "error")

    def test_alert_summary(self):
        self.am.create_alert(
            title="Err", message="e", severity=AlertSeverity.ERROR,
            category=AlertCategory.STORAGE, deduplication_key="err-sum-1",
        )
        self.am.create_alert(
            title="Err2", message="e2", severity=AlertSeverity.ERROR,
            category=AlertCategory.STORAGE, deduplication_key="err-sum-2",
        )
        summary = self.am.get_alert_summary()
        self.assertEqual(summary["total_active"], 2)
        self.assertEqual(summary["by_severity"]["error"], 2)
        self.assertEqual(summary["by_category"]["storage"], 2)
        self.assertEqual(summary["critical_count"], 0)

    def test_max_active_alerts_evicts_oldest_resolved(self):
        am = AlertManager(max_active_alerts=2)
        for i in range(3):
            am.create_alert(
                title=f"Alert {i}",
                message=f"msg {i}",
                severity=AlertSeverity.INFO,
                category=AlertCategory.SYSTEM,
                deduplication_key=f"max-{i}",
            )
        if len(am.get_active_alerts()) > 2:
            am.resolve_alert("max-0")
        active = am.get_active_alerts()
        self.assertLessEqual(len(active), 2)


class TestAuditLogger(unittest.TestCase):
    def setUp(self):
        self.al = AuditLogger(max_entries=5)

    def test_log_and_retrieve(self):
        self.al.log(
            action="UPLOAD_REPORT",
            resource="report",
            resource_id="r-123",
            actor="user@example.com",
            result="success",
            details={"filename": "report.tar.gz", "size_mb": 45},
        )
        entries = self.al.query(actor="user@example.com")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "UPLOAD_REPORT")
        self.assertEqual(entries[0]["result"], "success")

    def test_max_entries_enforced(self):
        for i in range(10):
            self.al.log(
                action="ACTION",
                resource="r",
                resource_id=f"id-{i}",
                result="success",
            )
        entries = self.al.query()
        self.assertLessEqual(len(entries), 5)

    def test_query_by_resource(self):
        self.al.log("UPLOAD", "report", "r1", result="success")
        self.al.log("DELETE", "report", "r2", result="success")
        self.al.log("UPLOAD", "node", "n1", result="success")
        self.assertEqual(len(self.al.query(resource="report")), 2)
        self.assertEqual(len(self.al.query(resource="node")), 1)

    def test_query_by_result(self):
        self.al.log("UPLOAD", "r", "r1", result="success")
        self.al.log("UPLOAD", "r", "r2", result="failure")
        self.assertEqual(len(self.al.query(result="success")), 1)
        self.assertEqual(len(self.al.query(result="failure")), 1)

    def test_query_no_match(self):
        self.al.log("UPLOAD", "r", "r1", result="success")
        self.assertEqual(len(self.al.query(actor="nobody@example.com")), 0)


class TestHealthChecker(unittest.TestCase):
    def setUp(self):
        self.hc = HealthChecker()

    def test_register_and_run_check(self):
        self.hc.register_check("db_connectivity", lambda: (True, "Connected"))
        result = self.hc.run_check("db_connectivity")
        self.assertTrue(result)
        summary = self.hc.run_all_checks()
        self.assertTrue(summary["healthy"])
        self.assertEqual(summary["total_checks"], 1)

    def test_register_check_with_severity(self):
        self.hc.register_check(
            "disk_space", lambda: (False, "Low disk"), severity=AlertSeverity.ERROR
        )
        result = self.hc.run_check("disk_space")
        self.assertFalse(result)

    def test_run_nonexistent_check_returns_false(self):
        self.assertFalse(self.hc.run_check("does-not-exist"))

    def test_run_check_catches_exception(self):
        self.hc.register_check("bad", lambda: (_ for _ in ()).throw(ValueError("fail")))
        result = self.hc.run_check("bad")
        self.assertFalse(result)
        summary = self.hc.run_all_checks()
        self.assertFalse(summary["healthy"])
        self.assertIn("bad", summary["failed_checks"])

    def test_run_all_checks_empty(self):
        summary = self.hc.run_all_checks()
        self.assertTrue(summary["healthy"])
        self.assertEqual(summary["total_checks"], 0)


class TestPerformanceMonitor(unittest.TestCase):
    def setUp(self):
        self.pm = PerformanceMonitor(window_seconds=60)

    def test_record_request(self):
        self.pm.record_request("/api/health", 12.5, 200)
        stats = self.pm.get_stats()
        self.assertEqual(stats["/api/health"]["count"], 1)

    def test_record_error(self):
        self.pm.record_request("/api/reports", 500.0, 500)
        stats = self.pm.get_stats()
        self.assertEqual(stats["/api/reports"]["errors"], 1)

    def test_get_stats_by_endpoint(self):
        self.pm.record_request("/api/health", 10.0, 200)
        self.pm.record_request("/api/health", 20.0, 200)
        self.pm.record_request("/api/reports", 100.0, 200)
        stats = self.pm.get_stats(endpoint="/api/health")
        self.assertEqual(stats["/api/health"]["count"], 2)

    def test_get_stats_empty(self):
        stats = self.pm.get_stats()
        self.assertNotIn("/api/health", stats)

    def test_stats_with_latency_percentiles(self):
        for i in range(10):
            self.pm.record_request("/api/health", float(i + 1), 200)
        stats = self.pm.get_stats()
        self.assertIn("p50", stats["/api/health"]["percentiles"])
        self.assertIn("p95", stats["/api/health"]["percentiles"])
        self.assertIn("p99", stats["/api/health"]["percentiles"])


from datetime import datetime, timezone


if __name__ == "__main__":
    unittest.main()
