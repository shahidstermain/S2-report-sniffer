import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

from storage import LocalReportStore
import server


class RecordingLocalReportStore(LocalReportStore):
    def __init__(self, base_dir: Path):
        self.events = []
        super().__init__(base_dir)

    async def update_report_fields(self, report_id, fields):
        if fields.get("status") == "ready":
            self.events.append("status_ready")
        await super().update_report_fields(report_id, fields)

    async def write_report_payload(self, report_id, payload):
        self.events.append("payload_written")
        await super().write_report_payload(report_id, payload)


def test_parse_background_persists_diagnostic_aggregates_before_ready(tmp_path):
    report_id = str(uuid.uuid4())
    archive_path = tmp_path / "support.zip"
    archive_path.write_bytes(b"placeholder")
    store = RecordingLocalReportStore(tmp_path / "data")
    parsed_report = {
        "parsed_at": "2026-06-12T11:00:00+00:00",
        "detected_format": "zip",
        "raw_node_count": 1,
        "cluster_overview": {"version": "8.5.0"},
        "nodes": [],
        "databases": [],
        "storage": [],
        "queries": [],
        "events": [],
        "pipelines": [],
        "logs": [],
        "log_summary": {"total": 0},
        "recommendations": [],
        "workload_management": [],
        "replication_status": [],
        "config_health": {},
        "backup_history": [],
        "resource_pools": [],
        "database_disk_usage": [],
        "partitions": {},
        "pressure_events_per_hour": {},
        "version_history": [],
        "availability_groups": [],
        "users": [],
        "detected_log_patterns": [],
        "dmesg_events": [],
        "alloc_memory": {"totals": [{"allocator": "BufferManager", "mb": 512}]},
        "log_timeframe": {"overall": {"first": "2026-06-12T10:00:00Z"}},
        "backup_summary": {"total": 1, "success_count": 1, "failure_count": 0},
        "memory_pressure": {"node-a": {"oom_events": False}},
        "cluster_layout": {"total_partitions": 8, "by_host": {"node-a": {"total": 8}}},
        "process_health": {"active_count": 2, "sleeping_open_tx_count": 1},
    }

    async def run_parse():
        await store.create_report_stub(report_id, "support.zip", 11, "zip")
        with patch.object(server, "store", store), patch.object(
            server, "parse_report_archive_streaming", return_value=dict(parsed_report)
        ):
            await server._parse_report_background(report_id, str(archive_path), 11)
        return await store.read_report_payload(report_id)

    payload = asyncio.run(run_parse())

    assert payload["alloc_memory"] == parsed_report["alloc_memory"]
    assert payload["log_timeframe"] == parsed_report["log_timeframe"]
    assert payload["backup_summary"] == parsed_report["backup_summary"]
    assert payload["memory_pressure"] == parsed_report["memory_pressure"]
    assert payload["cluster_layout"] == parsed_report["cluster_layout"]
    assert payload["process_health"] == parsed_report["process_health"]
    assert store.events.index("payload_written") < store.events.index("status_ready")
