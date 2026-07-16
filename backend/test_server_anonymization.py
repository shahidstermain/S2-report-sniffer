import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from storage import LocalReportStore

REPORT_ID = "00000000-0000-0000-0000-000000000123"


async def _parse_with_store(
    store: LocalReportStore,
    source_path: str,
    *,
    anonymize: bool,
) -> None:
    await store.create_report_stub(REPORT_ID, "Anonymized Report", 0, "sparse")
    with patch.object(server, "store", store):
        await server._parse_report_background(
            REPORT_ID,
            source_path,
            0,
            anonymize=anonymize,
            report_name="customer-prod.log",
        )


def test_background_parse_anonymizes_logs_and_payload_before_persistence(tmp_path):
    source = tmp_path / "customer-prod.log"
    source.write_text(
        "2026-07-12 10:20:30.123 ERROR host=db-prod-01 "
        "connect 10.23.45.67 password=S2RS_RAW_SENTINEL_SECRET\n",
        encoding="utf-8",
    )
    store = LocalReportStore(tmp_path / "data")

    asyncio.run(_parse_with_store(store, str(source), anonymize=True))

    logs_blob = store._report_logs_path(REPORT_ID).read_text(encoding="utf-8")
    payload = asyncio.run(store.read_report_payload(REPORT_ID))
    persisted_blob = logs_blob + json.dumps(payload)
    assert "db-prod-01" not in persisted_blob
    assert "10.23.45.67" not in persisted_blob
    assert "S2RS_RAW_SENTINEL_SECRET" not in persisted_blob
    assert payload["privacy"]["anonymized"] is True


def test_anonymized_directory_import_does_not_persist_local_source_paths(tmp_path):
    source_dir = tmp_path / "customer-prod-report"
    source_dir.mkdir()
    store = LocalReportStore(tmp_path / "data")

    asyncio.run(_parse_with_store(store, str(source_dir), anonymize=True))

    payload = asyncio.run(store.read_report_payload(REPORT_ID))
    fields = asyncio.run(store.get_report_fields(REPORT_ID, fields=["extracted_path"]))
    assert "report_root" not in payload
    assert "import_source_path" not in payload
    assert not fields.get("extracted_path")


def test_non_anonymized_parse_preserves_raw_log_values(tmp_path):
    source = tmp_path / "customer-prod.log"
    source.write_text(
        "2026-07-12 10:20:30.123 ERROR connect 10.23.45.67 "
        "password=S2RS_RAW_SENTINEL_SECRET\n",
        encoding="utf-8",
    )
    store = LocalReportStore(tmp_path / "data")

    asyncio.run(_parse_with_store(store, str(source), anonymize=False))

    logs_blob = store._report_logs_path(REPORT_ID).read_text(encoding="utf-8")
    assert "10.23.45.67" in logs_blob
    assert "S2RS_RAW_SENTINEL_SECRET" in logs_blob


def test_anonymized_parse_failure_does_not_persist_raw_exception_text(tmp_path):
    source = tmp_path / "customer-prod.log"
    source.write_text("invalid", encoding="utf-8")
    store = LocalReportStore(tmp_path / "data")
    asyncio.run(store.create_report_stub(REPORT_ID, "Anonymized Report", 0, "sparse"))

    with (
        patch.object(server, "store", store),
        patch.object(
            server,
            "parse_sparse_report_file",
            side_effect=ValueError(
                "/private/customer-leaf-01/S2RS_RAW_SENTINEL_SECRET"
            ),
        ),
    ):
        asyncio.run(
            server._parse_report_background(
                REPORT_ID,
                str(source),
                0,
                anonymize=True,
                report_name="customer-prod.log",
            )
        )

    fields = asyncio.run(
        store.get_report_fields(
            REPORT_ID,
            fields=["status", "error", "progress_json"],
        )
    )
    persisted_blob = json.dumps(fields)
    assert fields["status"] == "error"
    assert "customer-leaf-01" not in persisted_blob
    assert "S2RS_RAW_SENTINEL_SECRET" not in persisted_blob


def test_rehydrate_keeps_anonymized_payload_and_response_free_of_raw_data(
    tmp_path,
):
    source_dir = tmp_path / "customer-leaf-01"
    source_dir.mkdir()
    store = LocalReportStore(tmp_path / "data")
    asyncio.run(
        store.write_report_payload(
            REPORT_ID,
            {
                "id": REPORT_ID,
                "report_name": "Anonymized Report",
                "privacy": {"anonymized": True},
                "nodes": [{"hostname": "NODE_1"}],
                "extended_diagnostics": {},
            },
        )
    )
    raw_diagnostics = {
        "cpu_health": {
            "per_node": {
                "customer-leaf-01": {
                    "hostname": "customer-leaf-01",
                    "message": "connect 10.23.45.67",
                }
            }
        }
    }

    with (
        patch.object(server, "store", store),
        patch.object(
            server,
            "_resolve_allowed_import_path",
            return_value=source_dir,
        ),
        patch.object(
            server,
            "hydrate_extended_diagnostics",
            return_value=raw_diagnostics,
        ),
    ):
        response = TestClient(
            server.app,
            raise_server_exceptions=False,
        ).post(
            f"/api/reports/{REPORT_ID}/rehydrate-diagnostics",
            json={"path": str(source_dir)},
        )

    payload = asyncio.run(store.read_report_payload(REPORT_ID))
    persisted_blob = json.dumps(payload)
    response_blob = json.dumps(response.json())
    assert response.status_code == 200
    assert str(source_dir) not in persisted_blob
    assert str(source_dir) not in response_blob
    assert "customer-leaf-01" not in persisted_blob
    assert "customer-leaf-01" not in response_blob
    assert "10.23.45.67" not in persisted_blob
    assert "10.23.45.67" not in response_blob
    assert payload["privacy"]["anonymized"] is True
