import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import server
from storage import LocalReportStore


def _write_json(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_parse_background_persists_overview_aggregates(tmp_path, monkeypatch):
    report_root = tmp_path / "report"
    node = report_root / "node1-MA"
    node.mkdir(parents=True)
    _write_json(
        node / "informationSchemaMvBackupHistory.json",
        {
            "rows": [
                {
                    "STATUS": "success",
                    "START_TIMESTAMP": "2024-01-10 09:00:00",
                    "END_TIMESTAMP": "2024-01-10 09:05:00",
                }
            ]
        },
    )
    _write_json(
        node / "informationSchemaProcesslist.json",
        {"rows": [{"Id": 1, "Command": "Query", "Info": "SELECT 1", "Time": 5}]},
    )
    _write_json(
        node / "showClusterStatus.json",
        {"rows": [{"Host": "leaf-1", "Role": "Master"}]},
    )

    temp_store = LocalReportStore(base_dir=tmp_path / "data")
    monkeypatch.setattr(server, "store", temp_store)
    report_id = "123e4567-e89b-12d3-a456-426614174000"

    async def run_parse():
        await temp_store.create_report_stub(report_id, "fixture", 0, "directory")
        await server._parse_report_background(report_id, str(report_root), 0)
        return await temp_store.read_report_payload(report_id)

    payload = asyncio.run(run_parse())

    assert payload["status"] == "ready"
    assert payload["backup_summary"]["success_count"] == 1
    assert payload["process_health"]["active_count"] == 1
    assert payload["cluster_layout"]["total_partitions"] == 1
