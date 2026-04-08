"""
Real-time monitoring, alerting, and audit logging for the SingleStore Report Sniffer.
Provides structured logging, anomaly detection, and health monitoring.
"""
import logging
import time
import json
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import threading
import queue


logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertCategory(Enum):
    PARSING = "parsing"
    VALIDATION = "validation"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STORAGE = "storage"
    REPLICATION = "replication"
    AVAILABILITY = "availability"
    SYSTEM = "system"
    UPLOAD = "upload"


@dataclass
class Alert:
    id: str
    timestamp: str
    severity: str
    category: str
    title: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MetricsCollector:
    """
    Thread-safe metrics collector for monitoring system health and performance.
    """

    def __init__(self, max_history: int = 1000):
        self._metrics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._max_history = max_history

    def increment(self, metric: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            self._counters[metric] += value
            self._record_metric(metric, "counter", value, tags)

    def gauge(self, metric: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            self._gauges[metric] = value
            self._record_metric(metric, "gauge", value, tags)

    def timing(self, metric: str, duration_ms: float, tags: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            self._record_metric(metric, "timing", duration_ms, tags)

    def _record_metric(self, metric: str, metric_type: str, value: Any, tags: Optional[Dict[str, str]]) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": metric_type,
            "value": value,
            "tags": tags or {},
        }
        self._metrics[metric].append(entry)
        if len(self._metrics[metric]) > self._max_history:
            self._metrics[metric] = self._metrics[metric][-self._max_history:]

    def get_metric(self, metric: str, since: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            entries = self._metrics.get(metric, [])
            if since:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                entries = [e for e in entries if datetime.fromisoformat(e["timestamp"]) >= since_dt]
            return entries

    def get_counter(self, metric: str) -> int:
        with self._lock:
            return self._counters.get(metric, 0)

    def get_gauge(self, metric: str) -> Optional[float]:
        with self._lock:
            return self._gauges.get(metric)

    def get_all_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "metrics": {k: len(v) for k, v in self._metrics.items()},
            }


class AlertManager:
    """
    Centralized alert management with deduplication and rate limiting.
    """

    def __init__(self, max_active_alerts: int = 100):
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._lock = threading.RLock()
        self._max_active_alerts = max_active_alerts
        self._alert_cooldowns: Dict[str, float] = {}
        self._cooldown_seconds = 300

    def create_alert(
        self,
        title: str,
        message: str,
        severity: AlertSeverity,
        category: AlertCategory,
        context: Optional[Dict[str, Any]] = None,
        deduplication_key: Optional[str] = None,
    ) -> Optional[Alert]:
        key = deduplication_key or f"{category.value}:{title}"

        with self._lock:
            if key in self._alert_cooldowns:
                if time.time() - self._alert_cooldowns[key] < self._cooldown_seconds:
                    return None

            if key in self._active_alerts:
                existing = self._active_alerts[key]
                if not existing.resolved:
                    return None

            alert = Alert(
                id=key,
                timestamp=datetime.now(timezone.utc).isoformat(),
                severity=severity.value,
                category=category.value,
                title=title,
                message=message,
                context=context or {},
            )

            self._active_alerts[key] = alert
            self._alert_history.append(alert)

            if len(self._active_alerts) > self._max_active_alerts:
                oldest_key = next(iter(self._active_alerts))
                if self._active_alerts[oldest_key].resolved:
                    del self._active_alerts[oldest_key]

            self._alert_cooldowns[key] = time.time()

            logger.warning(f"ALERT [{severity.value.upper()}] [{category.value}] {title}: {message}")
            return alert

    def resolve_alert(self, key: str, message: Optional[str] = None) -> bool:
        with self._lock:
            if key not in self._active_alerts:
                return False

            alert = self._active_alerts[key]
            alert.resolved = True
            alert.resolved_at = datetime.now(timezone.utc).isoformat()
            if message:
                alert.message = message

            logger.info(f"ALERT RESOLVED: {key}")
            return True

    def get_active_alerts(self, severity: Optional[AlertSeverity] = None) -> List[Alert]:
        with self._lock:
            alerts = [a for a in self._active_alerts.values() if not a.resolved]
            if severity:
                alerts = [a for a in alerts if a.severity == severity.value]
            return sorted(alerts, key=lambda x: x.timestamp, reverse=True)

    def get_alert_summary(self) -> Dict[str, Any]:
        with self._lock:
            active = [a for a in self._active_alerts.values() if not a.resolved]
            by_severity = defaultdict(int)
            by_category = defaultdict(int)
            for alert in active:
                by_severity[alert.severity] += 1
                by_category[alert.category] += 1

            return {
                "total_active": len(active),
                "by_severity": dict(by_severity),
                "by_category": dict(by_category),
                "critical_count": by_severity.get("critical", 0),
            }


class AuditLogger:
    """
    Comprehensive audit logging for compliance and security tracking.
    """

    def __init__(self, max_entries: int = 10000):
        self._entries: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._max_entries = max_entries

    def log(
        self,
        action: str,
        resource: str,
        resource_id: str,
        actor: str = "system",
        result: str = "success",
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "resource": resource,
            "resource_id": resource_id,
            "actor": actor,
            "result": result,
            "details": details or {},
            "ip_address": ip_address,
        }

        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]

        logger.info(f"AUDIT: {action} {resource}/{resource_id} by {actor} -> {result}")

    def query(
        self,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        actor: Optional[str] = None,
        result: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            results = self._entries

            if action:
                results = [e for e in results if e["action"] == action]
            if resource:
                results = [e for e in results if e["resource"] == resource]
            if resource_id:
                results = [e for e in results if e["resource_id"] == resource_id]
            if actor:
                results = [e for e in results if e["actor"] == actor]
            if result:
                results = [e for e in results if e["result"] == result]
            if since:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                results = [e for e in results if datetime.fromisoformat(e["timestamp"]) >= since_dt]

            return sorted(results, key=lambda x: x["timestamp"], reverse=True)[:limit]


class HealthChecker:
    """
    System health monitoring with configurable checks.
    """

    def __init__(self):
        self._checks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def register_check(self, name: str, check_fn, severity: AlertSeverity = AlertSeverity.WARNING) -> None:
        with self._lock:
            self._checks[name] = {
                "fn": check_fn,
                "severity": severity,
                "last_run": None,
                "last_result": None,
                "last_message": None,
            }

    def run_check(self, name: str) -> bool:
        with self._lock:
            if name not in self._checks:
                return False

            check = self._checks[name]
            try:
                result, message = check["fn"]()
                check["last_result"] = result
                check["last_message"] = message
                check["last_run"] = datetime.now(timezone.utc).isoformat()
                return result
            except Exception as e:
                check["last_result"] = False
                check["last_message"] = str(e)
                check["last_run"] = datetime.now(timezone.utc).isoformat()
                return False

    def run_all_checks(self) -> Dict[str, Any]:
        results = {}
        with self._lock:
            check_names = list(self._checks.keys())

        for name in check_names:
            results[name] = self.run_check(name)

        failed = [name for name, result in results.items() if not result]
        return {
            "healthy": len(failed) == 0,
            "total_checks": len(results),
            "failed_checks": failed,
            "results": {
                name: {
                    "passed": result,
                    "message": self._checks[name]["last_message"],
                    "last_run": self._checks[name]["last_run"],
                }
                for name, result in results.items()
            },
        }


class PerformanceMonitor:
    """
    Request/response performance monitoring with percentiles.
    """

    def __init__(self, window_seconds: int = 60):
        self._window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
        self._request_counts: Dict[str, int] = defaultdict(int)
        self._error_counts: Dict[str, int] = defaultdict(int)

    def record_request(self, endpoint: str, duration_ms: float, status_code: int) -> None:
        with self._lock:
            now = time.time()
            self._requests[endpoint].append((now, duration_ms))
            self._request_counts[endpoint] += 1
            if status_code >= 400:
                self._error_counts[endpoint] += 1

            cutoff = now - self._window_seconds
            self._requests[endpoint] = [
                (t, d) for t, d in self._requests[endpoint] if t >= cutoff
            ]

    def get_stats(self, endpoint: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            endpoints = [endpoint] if endpoint else list(self._requests.keys())
            stats = {}

            for ep in endpoints:
                requests = self._requests.get(ep, [])
                if not requests:
                    stats[ep] = {"count": 0, "errors": 0, "percentiles": {}}
                    continue

                durations = [d for _, d in requests]
                durations_sorted = sorted(durations)

                count = len(durations)
                errors = self._error_counts.get(ep, 0)

                def percentile(data, p):
                    idx = int(len(data) * p / 100)
                    idx = min(idx, len(data) - 1)
                    return data[idx]

                stats[ep] = {
                    "count": count,
                    "errors": errors,
                    "error_rate": round(errors / count * 100, 2) if count > 0 else 0,
                    "min_ms": round(min(durations), 2),
                    "max_ms": round(max(durations), 2),
                    "avg_ms": round(sum(durations) / count, 2),
                    "percentiles": {
                        "p50": round(percentile(durations_sorted, 50), 2),
                        "p90": round(percentile(durations_sorted, 90), 2),
                        "p95": round(percentile(durations_sorted, 95), 2),
                        "p99": round(percentile(durations_sorted, 99), 2),
                    },
                }

            return stats if endpoint else stats


_global_metrics = MetricsCollector()
_global_alerts = AlertManager()
_global_audit = AuditLogger()
_global_health = HealthChecker()
_global_perf = PerformanceMonitor()


def get_metrics() -> MetricsCollector:
    return _global_metrics


def get_alerts() -> AlertManager:
    return _global_alerts


def get_audit() -> AuditLogger:
    return _global_audit


def get_health() -> HealthChecker:
    return _global_health


def get_performance() -> PerformanceMonitor:
    return _global_perf


def record_parsing_duration(report_id: str, duration_ms: float, status: str) -> None:
    _global_metrics.timing("parsing.duration", duration_ms, {"status": status})
    _global_metrics.increment("parsing.total", tags={"status": status})
    if status == "error":
        _global_alerts.create_alert(
            title=f"Parsing failed: {report_id[:8]}",
            message=f"Report parsing failed after {duration_ms:.0f}ms",
            severity=AlertSeverity.ERROR,
            category=AlertCategory.PARSING,
            context={"report_id": report_id, "duration_ms": duration_ms},
            deduplication_key=f"parsing_failure:{report_id}",
        )


def record_validation_failure(validation_type: str, details: Dict[str, Any]) -> None:
    _global_metrics.increment("validation.failures", tags={"type": validation_type})
    _global_alerts.create_alert(
        title=f"Validation failure: {validation_type}",
        message=f"Input validation failed for {validation_type}",
        severity=AlertSeverity.WARNING,
        category=AlertCategory.VALIDATION,
        context=details,
        deduplication_key=f"validation_failure:{validation_type}",
    )


def record_security_event(event_type: str, details: Dict[str, Any]) -> None:
    _global_metrics.increment("security.events", tags={"type": event_type})
    _global_alerts.create_alert(
        title=f"Security event: {event_type}",
        message=f"Security-related event detected: {event_type}",
        severity=AlertSeverity.WARNING,
        category=AlertCategory.SECURITY,
        context=details,
        deduplication_key=f"security_event:{event_type}",
    )
    _global_audit.log(
        action="security_event",
        resource="system",
        resource_id=event_type,
        result="detected",
        details=details,
    )


def record_upload_attempt(filename: str, file_size: int, ip_address: Optional[str] = None) -> str:
    upload_id = f"upload_{int(time.time() * 1000)}"
    _global_metrics.increment("uploads.total")
    _global_metrics.gauge("uploads.last_size_bytes", float(file_size))
    _global_audit.log(
        action="upload_attempt",
        resource="report",
        resource_id=upload_id,
        details={"filename": filename, "size": file_size},
        ip_address=ip_address,
    )
    return upload_id


def record_upload_complete(report_id: str, filename: str, duration_ms: float, status: str) -> None:
    _global_metrics.timing("upload.duration", duration_ms, {"status": status})
    _global_audit.log(
        action="upload_complete",
        resource="report",
        resource_id=report_id,
        result=status,
        details={"filename": filename, "duration_ms": duration_ms},
    )
    if status == "error":
        _global_alerts.create_alert(
            title=f"Upload failed: {filename[:30]}",
            message=f"Upload failed after {duration_ms:.0f}ms",
            severity=AlertSeverity.ERROR,
            category=AlertCategory.UPLOAD,
            context={"filename": filename, "report_id": report_id},
            deduplication_key=f"upload_failure:{report_id}",
        )


def log_anomaly(detection_type: str, severity: AlertSeverity, context: Dict[str, Any]) -> None:
    _global_metrics.increment("anomalies.detected", tags={"type": detection_type})
    _global_alerts.create_alert(
        title=f"Anomaly detected: {detection_type}",
        message=f"Unusual pattern detected in {detection_type}",
        severity=severity,
        category=AlertCategory.SYSTEM,
        context=context,
        deduplication_key=f"anomaly:{detection_type}",
    )