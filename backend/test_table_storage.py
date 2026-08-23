import json
import asyncio

from fastapi.testclient import TestClient

from parsers import extract_table_storage_inventory, parse_report_directory
import server
from storage import LocalReportStore


def test_table_storage_uses_documented_storage_type_values():
    result = extract_table_storage_inventory([
        {
            "TABLE_SCHEMA": "sales",
            "TABLE_NAME": "events",
            "TABLE_TYPE": "BASE TABLE",
            "STORAGE_TYPE": "COLUMNSTORE",
            "DISTRIBUTED": 1,
            "TABLE_ROWS": "1200",
        },
        {
            "TABLE_SCHEMA": "sales",
            "TABLE_NAME": "sessions",
            "TABLE_TYPE": "BASE TABLE",
            "STORAGE_TYPE": "INMEMORY_ROWSTORE",
            "DISTRIBUTED": 0,
            "TABLE_ROWS": 25,
            "ROW_FORMAT": "COMPRESSION = SPARSE",
        },
    ])

    assert result["summary"] == {
        "total_tables": 2,
        "columnstore_tables": 1,
        "rowstore_tables": 1,
        "unknown_tables": 0,
    }
    assert result["tables"][0]["storage_type"] == "columnstore"
    assert result["tables"][0]["distributed"] is True
    assert result["tables"][1]["storage_type"] == "rowstore"
    assert result["tables"][1]["distributed"] is False
    assert result["source"] == "information_schema.TABLES.STORAGE_TYPE"


def test_table_storage_does_not_infer_unknown_values_or_classify_views():
    result = extract_table_storage_inventory([
        {
            "TABLE_SCHEMA": "sales",
            "TABLE_NAME": "summary_view",
            "TABLE_TYPE": "VIEW",
            "STORAGE_TYPE": "COLUMNSTORE",
        },
        {
            "table_schema": "sales",
            "table_name": "legacy_table",
            "table_type": "BASE TABLE",
            "storage_type": "future_storage_type",
        },
        {
            "TABLE_SCHEMA": "sales",
            "TABLE_NAME": "legacy_table",
            "TABLE_TYPE": "BASE TABLE",
            "STORAGE_TYPE": "future_storage_type",
        },
    ])

    assert result["summary"]["total_tables"] == 1
    assert result["summary"]["unknown_tables"] == 1
    assert result["tables"][0]["storage_type"] == "unknown"
    assert result["tables"][0]["storage_type_raw"] == "FUTURE_STORAGE_TYPE"


def test_table_storage_requires_table_identity():
    result = extract_table_storage_inventory([
        {"TABLE_SCHEMA": "sales", "STORAGE_TYPE": "COLUMNSTORE"},
        {"TABLE_NAME": "events", "STORAGE_TYPE": "INMEMORY_ROWSTORE"},
    ])
    assert result["summary"]["total_tables"] == 0
    assert result["tables"] == []


def test_table_storage_preserves_unknown_row_counts():
    result = extract_table_storage_inventory([{
        "TABLE_SCHEMA": "sales",
        "TABLE_NAME": "events",
        "TABLE_TYPE": "BASE TABLE",
        "STORAGE_TYPE": "COLUMNSTORE",
        "TABLE_ROWS": "None",
    }])
    assert result["tables"][0]["row_count"] is None


def test_cluster_report_parser_builds_table_storage_inventory(tmp_path):
    node = tmp_path / "node-host-master-0-MA"
    node.mkdir()
    (node / "informationSchemaTables.json").write_text(json.dumps({
        "rows": [
            {
                "TABLE_SCHEMA": "inventory",
                "TABLE_NAME": "orders",
                "TABLE_TYPE": "BASE TABLE",
                "STORAGE_TYPE": "COLUMNSTORE",
            },
            {
                "TABLE_SCHEMA": "inventory",
                "TABLE_NAME": "order_locks",
                "TABLE_TYPE": "BASE TABLE",
                "STORAGE_TYPE": "INMEMORY_ROWSTORE",
            },
        ]
    }))

    parsed = parse_report_directory(str(tmp_path), "synthetic")
    assert parsed["table_storage"]["summary"]["columnstore_tables"] == 1
    assert parsed["table_storage"]["summary"]["rowstore_tables"] == 1


def test_storage_endpoint_returns_table_storage_inventory(tmp_path):
    report_id = "10000000-0000-0000-0000-000000000001"
    store = LocalReportStore(base_dir=tmp_path)
    inventory = extract_table_storage_inventory([{
        "TABLE_SCHEMA": "inventory",
        "TABLE_NAME": "orders",
        "TABLE_TYPE": "BASE TABLE",
        "STORAGE_TYPE": "COLUMNSTORE",
    }])
    asyncio.run(store.create_report_stub(report_id, "table-storage", 1, "sparse"))
    asyncio.run(store.write_report_payload(report_id, {"table_storage": inventory}))
    previous_store = server.store
    server.store = store
    try:
        response = TestClient(server.app).get(f"/api/reports/{report_id}/storage")
    finally:
        server.store = previous_store

    assert response.status_code == 200
    assert response.json()["table_storage"]["summary"]["columnstore_tables"] == 1


def test_storage_endpoint_hydrates_inventory_for_existing_reports(tmp_path):
    report_id = "10000000-0000-0000-0000-000000000002"
    store = LocalReportStore(base_dir=tmp_path)
    asyncio.run(store.create_report_stub(report_id, "table-storage", 1, "sparse"))
    asyncio.run(store.write_report_payload(report_id, {"nodes": [{
        "information_schema_tables": [{
            "TABLE_SCHEMA": "inventory",
            "TABLE_NAME": "locks",
            "TABLE_TYPE": "BASE TABLE",
            "STORAGE_TYPE": "INMEMORY_ROWSTORE",
        }]
    }]}))
    previous_store = server.store
    server.store = store
    try:
        response = TestClient(server.app).get(f"/api/reports/{report_id}/storage")
    finally:
        server.store = previous_store

    assert response.status_code == 200
    assert response.json()["table_storage"]["summary"]["rowstore_tables"] == 1
    persisted = asyncio.run(store.read_report_payload(report_id))
    assert persisted["table_storage"]["tables"][0]["table"] == "locks"


def test_storage_endpoint_hydrates_union_of_all_node_inventories(tmp_path):
    report_id = "10000000-0000-0000-0000-000000000004"
    store = LocalReportStore(base_dir=tmp_path)
    asyncio.run(store.create_report_stub(report_id, "legacy.zip", 1, "zip"))
    asyncio.run(store.write_report_payload(report_id, {
        "nodes": [
            {
                "hostname": "db-LEAF",
                "information_schema_tables": [{
                    "TABLE_SCHEMA": "inventory",
                    "TABLE_NAME": "leaf_local",
                    "TABLE_TYPE": "BASE TABLE",
                    "STORAGE_TYPE": "COLUMNSTORE",
                }],
            },
            {
                "hostname": "db-MA",
                "information_schema_tables": [
                    {
                        "TABLE_SCHEMA": "inventory",
                        "TABLE_NAME": "leaf_local",
                        "TABLE_TYPE": "BASE TABLE",
                        "STORAGE_TYPE": "COLUMNSTORE",
                    },
                    {
                        "TABLE_SCHEMA": "inventory",
                        "TABLE_NAME": "cluster_wide",
                        "TABLE_TYPE": "BASE TABLE",
                        "STORAGE_TYPE": "INMEMORY_ROWSTORE",
                    },
                ],
            },
        ],
    }))
    previous_store = server.store
    server.store = store
    try:
        response = TestClient(server.app).get(f"/api/reports/{report_id}/storage")
    finally:
        server.store = previous_store

    assert response.status_code == 200
    tables = {row["table"] for row in response.json()["table_storage"]["tables"]}
    assert tables == {"leaf_local", "cluster_wide"}
    persisted = asyncio.run(store.read_report_payload(report_id))
    assert {row["table"] for row in persisted["table_storage"]["tables"]} == tables


def test_storage_hydration_reanonymizes_table_schema_for_privacy_reports(tmp_path):
    """Hydrating table_storage must not persist raw TABLE_SCHEMA on anonymized reports."""
    report_id = "10000000-0000-0000-0000-000000000003"
    store = LocalReportStore(base_dir=tmp_path)
    asyncio.run(store.create_report_stub(report_id, "private-table-storage", 1, "sparse"))
    asyncio.run(store.write_report_payload(report_id, {
        "privacy": {"anonymized": True, "scheme": "stable-local-aliases-v1"},
        "nodes": [{
            "hostname": "NODE_1",
            "information_schema_tables": [{
                "TABLE_SCHEMA": "acme_billing",
                "TABLE_NAME": "invoices",
                "TABLE_TYPE": "BASE TABLE",
                "STORAGE_TYPE": "COLUMNSTORE",
            }],
        }],
    }))
    previous_store = server.store
    server.store = store
    try:
        response = TestClient(server.app).get(f"/api/reports/{report_id}/storage")
    finally:
        server.store = previous_store

    assert response.status_code == 200
    body = response.json()
    assert "acme_billing" not in json.dumps(body)
    persisted = asyncio.run(store.read_report_payload(report_id))
    assert "acme_billing" not in json.dumps(persisted)
    assert persisted["table_storage"]["tables"][0]["database"].startswith("DATABASE_")
