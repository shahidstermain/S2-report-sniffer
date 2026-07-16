import json
from pathlib import Path

from parsers import parse_sparse_report_file
from product_features import (
    anonymize_report,
    build_capabilities,
    build_markdown_export,
    build_portable_html,
    compare_reports,
    TelemetryStore,
)


def sample_payload():
    return {
        "id": "report-1",
        "report_name": "customer-prod.zip",
        "cluster_overview": {"version": "8.7.12", "total_nodes": 2},
        "nodes": [
            {
                "hostname": "db-prod-01.example.com",
                "version": "8.7.12",
                "show_variables": {"bind_address": "10.2.3.4", "password": "secret-value"},
            }
        ],
        "databases": [{"DATABASE_NAME": "customer_orders"}],
        "queries": [{"QUERY_TEXT": "select * from customer_orders where token='abc123'"}],
        "logs": [{"hostname": "db-prod-01.example.com", "message": "connect 10.2.3.4 password=hunter2"}],
        "recommendations": [
            {
                "checker_id": "diskUsage",
                "severity": "critical",
                "risk_score": 90,
                "confidence": 0.9,
                "title": "Disk usage high",
                "description": "Disk on db-prod-01.example.com is high",
                "remediation": "Free disk space",
                "evidence": "10.2.3.4 / customer_orders",
            }
        ],
        "storage": [{"DATABASE_NAME": "customer_orders", "SIZE_MB": 100}],
        "config_health": {"issues": 1},
        "log_count": 1,
    }


def test_build_capabilities_is_version_aware_and_marks_partial_data():
    payload = sample_payload()
    payload["queries"] = []
    capabilities = build_capabilities(payload)
    assert capabilities["engine_version"] == "8.7.12"
    assert capabilities["version_support"] == "supported"
    assert capabilities["mode"] == "bundle"
    assert capabilities["features"]["overview"]["available"] is True
    assert capabilities["features"]["queries"]["available"] is False
    assert "query" in capabilities["features"]["queries"]["reason"].lower()


def test_anonymize_report_masks_sensitive_values_consistently():
    payload = sample_payload()
    cleaned, manifest = anonymize_report(payload)
    blob = json.dumps(cleaned)
    assert "db-prod-01.example.com" not in blob
    assert "10.2.3.4" not in blob
    assert "customer_orders" not in blob
    assert "hunter2" not in blob
    assert "secret-value" not in blob
    assert cleaned["nodes"][0]["hostname"] == cleaned["logs"][0]["hostname"]
    assert cleaned["nodes"][0]["hostname"].startswith("NODE_")
    assert manifest["enabled"] is True
    assert manifest["replacements"] >= 4


def test_anonymize_report_masks_compound_credential_field_names():
    payload = {
        "config_health": {
            "admin_password": "admin-secret",
            "aws_secret_access_key": "aws-secret",
            "oauth_client_secret": "oauth-secret",
            "database_credentials": "database-secret",
            "jwt_signing_key": "jwt-secret",
            "refreshToken": "refresh-secret",
        }
    }
    cleaned, manifest = anonymize_report(payload)
    assert set(cleaned["config_health"].values()) == {"[REDACTED]"}
    assert manifest["replacements"] == 6


def test_anonymize_report_masks_host_assignments_in_unstructured_text():
    payload = {
        "logs": [
            {
                "hostname": "SPARSE_INPUT",
                "message": "connection failed host=db-prod-01.example.com",
            }
        ]
    }

    cleaned, _manifest = anonymize_report(payload)

    assert "db-prod-01.example.com" not in cleaned["logs"][0]["message"]
    assert "host=NODE_" in cleaned["logs"][0]["message"]


def test_anonymize_report_masks_quoted_peer_hosts_and_ipv6():
    payload = {
        "logs": [
            {
                "message": (
                    'host="customer-leaf-01" '
                    "SLAVE_HOST: customer-leaf-02 "
                    "peer_host='customer-leaf-03' "
                    "connect 2001:db8::42"
                )
            }
        ]
    }

    cleaned, _manifest = anonymize_report(payload)
    message = cleaned["logs"][0]["message"]

    assert "customer-leaf" not in message
    assert "2001:db8::42" not in message
    assert 'host="NODE_' in message
    assert "SLAVE_HOST: NODE_" in message
    assert "peer_host='NODE_" in message
    assert "IP_" in message


def test_anonymize_report_masks_json_and_space_containing_secrets():
    payload = {
        "logs": [
            {
                "message": (
                    '{"password":"S2RS_JSON_SENTINEL",'
                    '"token":"secret value with spaces"}'
                )
            }
        ]
    }

    cleaned, _manifest = anonymize_report(payload)
    message = cleaned["logs"][0]["message"]

    assert "S2RS_JSON_SENTINEL" not in message
    assert "secret value with spaces" not in message
    assert message.count("[REDACTED]") == 2


def test_anonymize_report_masks_escaped_secrets_inside_json_strings():
    payload = {
        "logs": [
            {
                "message": (
                    '{"password":"prefix\\\\\\"ESCAPED_QUOTE_SECRET"}'
                )
            }
        ]
    }

    cleaned, _manifest = anonymize_report(payload)
    message = cleaned["logs"][0]["message"]

    assert "ESCAPED_QUOTE_SECRET" not in message
    assert "[REDACTED]" in message


def test_anonymize_report_masks_secrets_in_prefixed_json_fragments():
    payload = {
        "logs": [
            {
                "message": (
                    'payload={"password":123456789,'
                    '"token":"prefix\\\\\\"ESCAPED_FRAGMENT_SECRET"}'
                )
            }
        ]
    }

    cleaned, _manifest = anonymize_report(payload)
    message = cleaned["logs"][0]["message"]

    assert "123456789" not in message
    assert "ESCAPED_FRAGMENT_SECRET" not in message
    assert message.count("[REDACTED]") == 2


def test_anonymize_report_masks_backslash_escaped_json_fragments():
    payload = {
        "logs": [
            {
                "message": (
                    'payload={\\"password\\":314159265,'
                    '\\"token\\":\\"API_ESCAPED_SECRET\\"}'
                )
            }
        ]
    }

    cleaned, _manifest = anonymize_report(payload)
    message = cleaned["logs"][0]["message"]

    assert "314159265" not in message
    assert "API_ESCAPED_SECRET" not in message
    assert message.count("[REDACTED]") == 2


def test_anonymize_report_masks_non_string_secret_values():
    payload = {
        "api_token": 987654321,
        "credentials": {"username": "admin", "password": 1234},
    }

    cleaned, _manifest = anonymize_report(payload)

    assert cleaned["api_token"] == "[REDACTED]"
    assert cleaned["credentials"] == "[REDACTED]"


def test_anonymize_report_masks_case_and_fqdn_hostname_variants():
    payload = {
        "nodes": [{"hostname": "Customer-Leaf-01"}],
        "logs": [
            {
                "message": (
                    "customer-leaf-01 failed; "
                    "CUSTOMER-LEAF-01.EXAMPLE.COM failed"
                )
            }
        ],
    }

    cleaned, _manifest = anonymize_report(payload)
    message = cleaned["logs"][0]["message"]

    assert "customer-leaf-01" not in message.lower()
    assert message.count("NODE_1") == 2


def test_anonymize_report_masks_camel_case_replication_hosts():
    payload = {
        "replication_status": [
            {
                "MasterHost": "remote-master.customer.internal",
                "SlaveHost": "remote-dr-leaf.customer.internal",
            }
        ]
    }

    cleaned, _manifest = anonymize_report(payload)
    row = cleaned["replication_status"][0]

    assert row["MasterHost"].startswith("NODE_")
    assert row["SlaveHost"].startswith("NODE_")
    assert "customer.internal" not in json.dumps(cleaned)


def test_anonymize_report_masks_hosts_in_replication_uris_and_connections():
    payload = {
        "replication_status": [
            {
                "Master_URI": "remote-master.customer.internal:3306/main",
                "Replica_URI": "remote-replica.customer.internal:3306/main",
                "Slave_URI": "remote-slave.customer.internal:3306/main",
            }
        ],
        "pipeline": {
            "connection_string": (
                "kafka-broker/customer-topic;bucket=customer-backups"
            )
        },
    }

    cleaned, _manifest = anonymize_report(payload)
    blob = json.dumps(cleaned)

    assert "customer.internal" not in blob
    assert "kafka-broker" not in blob
    assert "customer-topic" not in blob
    assert "customer-backups" not in blob
    assert {
        cleaned["replication_status"][0]["Master_URI"],
        cleaned["replication_status"][0]["Replica_URI"],
        cleaned["replication_status"][0]["Slave_URI"],
        cleaned["pipeline"]["connection_string"],
    } == {
        "CONNECTION_1",
        "CONNECTION_2",
        "CONNECTION_3",
        "CONNECTION_4",
    }


def test_anonymize_report_does_not_replace_short_hosts_inside_other_tokens():
    payload = {
        "nodes": [{"hostname": "ma"}],
        "config": {"maximum_memory": "1024"},
        "doc_link": "https://docs.example.com/maximum-memory",
    }

    cleaned, _manifest = anonymize_report(payload)

    assert cleaned["nodes"][0]["hostname"] == "NODE_1"
    assert cleaned["config"] == {"maximum_memory": "1024"}
    assert cleaned["doc_link"] == "https://docs.example.com/maximum-memory"


def test_anonymize_report_preserves_document_sources_but_aliases_file_sources():
    payload = {
        "grounding": {"source": "https://docs.example.com/replication"},
        "logs": [{"source": "customer-leaf-01.log"}],
    }

    cleaned, _manifest = anonymize_report(payload)

    assert cleaned["grounding"]["source"] == "https://docs.example.com/replication"
    assert cleaned["logs"][0]["source"] == "SOURCE_1.log"


def test_anonymize_report_sanitizes_credentials_and_ips_in_source_urls():
    payload = {
        "collector": {
            "source": (
                "https://user:S2RS_PASSWORD@10.23.45.67/private/report.json"
            )
        }
    }

    cleaned, _manifest = anonymize_report(payload)
    source = cleaned["collector"]["source"]

    assert "user:S2RS_PASSWORD" not in source
    assert "10.23.45.67" not in source
    assert "[REDACTED]@" in source
    assert "IP_" in source


def test_anonymize_report_masks_url_only_hosts_but_preserves_doc_hosts():
    payload = {
        "logs": [
            {
                "message": (
                    "fetch https://user:secret@customer-db.internal/private"
                )
            }
        ],
        "recommendations": [
            {"doc_link": "https://docs.singlestore.com/db/latest/"}
        ],
    }

    cleaned, _manifest = anonymize_report(payload)
    blob = cleaned["logs"][0]["message"]

    assert "user:secret" not in blob
    assert "customer-db.internal" not in blob
    assert "NODE_" in blob
    assert (
        cleaned["recommendations"][0]["doc_link"]
        == "https://docs.singlestore.com/db/latest/"
    )


def test_anonymize_report_masks_hostnames_used_as_dictionary_keys():
    payload = {
        "nodes": [{"hostname": "customer-leaf-01"}],
        "log_summary": {"per_node": {"customer-leaf-01": {"ERROR": 2}}},
        "memory_utilization": {
            "per_node": {"customer-leaf-01": {"memory_pct": 82}}
        },
    }

    cleaned, _manifest = anonymize_report(payload)

    alias = cleaned["nodes"][0]["hostname"]
    assert alias.startswith("NODE_")
    assert set(cleaned["log_summary"]["per_node"]) == {alias}
    assert set(cleaned["memory_utilization"]["per_node"]) == {alias}


def test_anonymize_report_masks_hostnames_present_only_as_per_node_keys():
    payload = {
        "memory_utilization": {
            "per_node": {"Only-Key-Host.example.com": {"memory_pct": 82}}
        }
    }

    cleaned, _manifest = anonymize_report(payload)
    host_keys = set(cleaned["memory_utilization"]["per_node"])

    assert host_keys == {"NODE_1"}


def test_anonymize_report_masks_database_names_used_as_partition_keys():
    payload = {
        "partitions": {
            "customer_orders_prod": [
                {"partition_id": 0, "host": "leaf-01"}
            ]
        }
    }

    cleaned, _manifest = anonymize_report(payload)

    assert set(cleaned["partitions"]) == {"DATABASE_1"}


def test_anonymize_report_removes_local_source_paths_recursively():
    payload = {
        "report_root": "/private/customer-report",
        "import_source_path": "/private/customer-report.zip",
        "extracted_path": "/private/extracted/customer-report",
        "nodes": [
            {
                "hostname": "db-prod-01",
                "_node_path": "/private/customer-report/db-prod-01-LEAF",
            }
        ],
    }

    cleaned, _manifest = anonymize_report(payload)

    assert "report_root" not in cleaned
    assert "import_source_path" not in cleaned
    assert "extracted_path" not in cleaned
    assert "_node_path" not in cleaned["nodes"][0]


def test_compare_reports_includes_configuration_and_metric_deltas():
    before = sample_payload()
    after = sample_payload()
    before["cluster_overview"]["total_nodes"] = 2
    after["cluster_overview"]["total_nodes"] = 3
    before["nodes"][0]["show_variables"]["maximum_memory"] = "100"
    after["nodes"][0]["show_variables"]["maximum_memory"] = "200"
    after["recommendations"].append({
        "checker_id": "replicationLag", "severity": "warning", "risk_score": 70,
        "title": "Replication lag", "confidence": 0.8,
    })
    result = compare_reports(before, after)
    assert result["summary"]["new_findings"] == 1
    assert result["metrics"]["total_nodes"]["before"] == 2
    assert result["metrics"]["total_nodes"]["after"] == 3
    assert any(row["key"] == "maximum_memory" for row in result["configuration_changes"])


def test_exports_are_customer_facing_and_escape_untrusted_content():
    payload = sample_payload()
    payload["recommendations"][0]["title"] = "Disk <script>alert(1)</script>"
    markdown = build_markdown_export(payload)
    html_doc = build_portable_html(payload)
    assert "## Recommended actions" in markdown
    assert "Free disk space" in markdown
    assert "<!doctype html>" in html_doc.lower()
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc
    assert "https://" not in html_doc


def test_sparse_log_file_creates_log_capability_without_fake_topology(tmp_path: Path):
    log_file = tmp_path / "memsql.log"
    log_file.write_text("2026-07-12 10:20:30.123 ERROR Out of memory on 10.2.3.4\n")
    result = parse_sparse_report_file(str(log_file))
    assert result["input_mode"] == "sparse"
    assert result["raw_node_count"] == 0
    assert result["logs"]
    assert result["capabilities"]["features"]["logs"]["available"] is True
    assert result["capabilities"]["features"]["storage"]["available"] is False


def test_telemetry_store_is_disabled_by_default_and_records_only_allowlisted_fields(tmp_path: Path):
    store = TelemetryStore(tmp_path)
    assert store.get_settings()["enabled"] is False
    assert store.record("parse_complete", {"duration_ms": 1200, "checker_ids": ["diskUsage"], "hostname": "secret"}) is False
    store.update_settings(enabled=True)
    assert store.record("parse_complete", {"duration_ms": 1200, "checker_ids": ["diskUsage"], "hostname": "secret"}) is True
    events = store.read_events()
    assert events[0]["duration_ms"] == 1200
    assert events[0]["checker_ids"] == ["diskUsage"]
    assert "hostname" not in events[0]
    assert store.get_settings()["external_delivery"] is False
