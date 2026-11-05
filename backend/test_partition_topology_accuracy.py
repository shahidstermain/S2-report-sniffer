"""Full-census regression tests for MA roles and partition placement."""
import json
from unittest.mock import patch

from parsers import (
    build_cluster_overview_from_topology,
    build_partition_layout,
    parse_partitions,
    parse_report_directory,
    resolve_partition_layout,
    summarize_cluster_layout,
)
from product_features import anonymize_report
from investigation import build_ai_export_json


def write_collector(node, name, payload):
    node.mkdir(parents=True, exist_ok=True)
    (node / name).write_text(json.dumps(payload))


def data_rows(count=6002):
    return [{"Ordinal": i // 2, "Host": "shared", "Port": 3307 + i % 2,
             "Role": "Master" if i % 2 == 0 else "Slave", "Locked": 0}
            for i in range(count)]


def test_complete_report_keeps_all_rows_and_separates_reference_and_endpoints(tmp_path):
    parts = data_rows()
    status = [{"Host": r["Host"], "Port": r["Port"], "Database": f"app_{r['Ordinal']}",
               "Role": r["Role"], "Metadata Role": r["Role"]} for r in parts]
    status += [{"Host": "ma", "Port": 3306, "Database": "app", "Role": "master", "Metadata Role": "Reference"},
               {"Host": "shared", "Port": 3307, "Database": "app", "Role": "slave", "Metadata Role": "Reference"},
               {"Host": "shared", "Port": 3307, "Database": "app_0_AUTO_REPLICA", "Role": "slave", "Metadata Role": "Orphan"}]
    topology = {"engine": {
        "ShowAggregators": {"rows": [{"Host": "ma", "Port": 3306, "NodeID": 1, "Master_Aggregator": 1, "State": "online"}]},
        "ShowLeaves": {"rows": [{"Host": "shared", "Port": port, "NodeID": port, "State": "online", "Availability_Group": 0} for port in (3307, 3308)]},
    }}
    # Duplicate snapshots on multiple nodes must never multiply cluster totals.
    for name in ("ma-MA", "ca-CA"):
        node = tmp_path / name
        write_collector(node, "showPartitions.json", {"engine": {"app": {"rows": parts}}})
        write_collector(node, "showClusterStatus.json", {"engine": {"rows": status}})
        write_collector(node, "clusterTopology.json", topology)
    result = parse_report_directory(str(tmp_path), "complete")
    assert result["cluster_overview"]["aggregators"] == 1
    assert result["cluster_overview"]["leaves"] == 2
    assert result["cluster_overview"]["nodes_detail"][2]["type"] == "MA"
    assert result["cluster_overview"]["cluster_status"] == status
    assert result["partitions"]["app"]["partitions"] == parts
    assert result["partitions"]["app"]["truncated"] is False
    layout = result["cluster_layout"]
    assert layout["total_partitions"] == 6002
    assert layout["by_role"] == {"master": 3001, "replica": 3001, "other": 0}
    assert {(r["host"], r["port"]): r["total"] for r in layout["by_node"]} == {("shared", "3307"): 3001, ("shared", "3308"): 3001}
    assert layout["reference_rows"] == 2
    assert layout["orphan_rows"] == 1
    assert not layout["counts_are_lower_bounds"]
    assert "ma" not in layout["by_host"]
    exported = build_ai_export_json(result)
    assert exported["partition_inventory"]["databases"]["app"]["partitions"] == parts
    assert exported["partition_inventory"]["cluster_status"] == status
    assert exported["cluster_topology"]["master_aggregators"] == 1


def test_full_cluster_status_fallback_streams_beyond_file_and_row_display_limits(tmp_path):
    rows = [{"HOST": "leaf", "PORT": 3307, "DATABASE_NAME": f"db_{i}", "ROLE": "master", "METADATA_ROLE": "Master"} for i in range(2501)]
    rows += [{"HOST": "ma", "PORT": 3306, "ROLE": "master", "METADATA_ROLE": "Reference"}]
    write_collector(tmp_path / "ma-MA", "showClusterStatus.json", {"engine": {"rows": rows}})
    with patch("parsers.MAX_JSON_FILE_BYTES_DEFAULT", 1), patch("parsers._STREAM_JSON_CHUNK_BYTES", 71):
        parsed = parse_report_directory(str(tmp_path), "streamed")
    assert parsed["cluster_overview"]["cluster_status"] == rows
    layout = parsed["cluster_layout"]
    assert layout["total_partitions"] == 2501
    assert layout["reference_rows"] == 1
    assert layout["classification_complete"]
    assert not layout["counts_are_lower_bounds"]


def test_large_partitions_file_and_duplicate_engine_snapshot_preserve_every_record(tmp_path):
    rows = data_rows()
    write_collector(tmp_path, "showPartitions.json", {
        "engine1": {"app": {"rows": rows}}, "engine2": {"app": {"rows": rows[:2]}},
    })
    with patch("parsers.MAX_JSON_FILE_BYTES_BY_NAME", {"showPartitions.json": 1}):
        result = parse_partitions(str(tmp_path))
    assert result["app"]["count"] == len(rows)
    assert result["app"]["partitions"][-1] == rows[-1]
    assert result["app"]["sample_count"] == len(rows)


def test_topology_fallback_recognizes_flag_roles_ids_and_groups():
    overview = build_cluster_overview_from_topology({
        "leaves": {"rows": [{"HOST": "shared", "PORT": 3307, "NodeID": 7, "STATE": "online", "AVAILABILITY_GROUP": 0}]},
        "aggregators": [
            {"Host": "shared", "Port": 3306, "Master_Aggregator": True, "NodeID": 1, "State": "online"},
            {"Host": "ca", "Port": 3306, "Master_Aggregator": False, "NodeID": 2, "State": "offline"},
            {"Host": "ca2", "Port": 3306, "Role": "follower", "NodeID": 3},
        ],
    }, [])
    assert overview["total_nodes"] == 4
    assert overview["aggregators"] == 3
    assert overview["leaves"] == 1
    assert overview["online_nodes"] == 2
    assert overview["offline_nodes"] == 1
    assert overview["availability_groups"] == ["0"]
    assert [n["type"] for n in overview["nodes_detail"]] == ["LEAF", "MA", "CA", "CA"]
    assert [n["id"] for n in overview["nodes_detail"]] == [7, 1, 2, 3]
    leader = build_cluster_overview_from_topology({"aggregators": [{"Host": "ma", "Role": "leader"}]}, [])
    assert leader["nodes_detail"][0]["type"] == "MA"


def test_unknown_replication_roles_are_not_replicas_and_metadata_classification_is_explicit():
    result = summarize_cluster_layout([
        {"Host": "leaf", "Port": 3306, "Role": "unknown", "Metadata Role": "Master"},
        {"Host": "leaf", "Port": 3307, "Role": "sync replica", "Metadata Role": "Slave"},
    ])
    assert result["by_role"] == {"master": 0, "replica": 1, "other": 1}
    assert len(result["by_node"]) == 2
    assert result["classification_complete"]
    assert not summarize_cluster_layout([{"Host": "leaf", "Role": "master"}])["classification_complete"]


def test_legacy_saved_reports_upgrade_from_retained_rows_without_claiming_samples_are_complete():
    parts = data_rows(6002)
    payload = {"partitions": {"app": {"partitions": parts, "count": 6002}},
               "cluster_layout": {"total_partitions": 300}}
    assert resolve_partition_layout(payload)["total_partitions"] == 6002
    assert not resolve_partition_layout(payload)["counts_are_lower_bounds"]
    payload["partitions"]["app"]["partitions"] = parts[:5000]
    assert resolve_partition_layout(payload)["counts_are_lower_bounds"]
    assert build_partition_layout({"empty": {"partitions": [], "count": 0}})["total_partitions"] == 0


def test_anonymization_preserves_endpoint_identity_and_never_leaks_summary_hosts():
    payload = {"partitions": {"customer_db": {"partitions": data_rows(4)}},
               "cluster_layout": build_partition_layout({"db": {"partitions": data_rows(4)}})}
    clean, _ = anonymize_report(payload)
    text = json.dumps(clean)
    assert "shared" not in text and "customer_db" not in text
    endpoints = clean["cluster_layout"]["by_node"]
    assert len(endpoints) == 2
    assert endpoints[0]["host"] == endpoints[1]["host"]
    assert endpoints[0]["host"] in clean["cluster_layout"]["by_host"]
    saved = next(iter(clean["partitions"].values()))["partitions"]
    assert set(saved[0]) == {"Ordinal", "Host", "Port", "Role", "Locked"}
    assert {row["Port"] for row in saved} == {3307, 3308}
    assert saved[0]["Host"] == endpoints[0]["host"]
    wrapped, _ = anonymize_report({"partitions": {"app": {"partitions": {"rows": data_rows(4)}}}})
    assert "rows" in next(iter(wrapped["partitions"].values()))["partitions"]


def test_export_preserves_node_inventory_beyond_fifty():
    nodes = [{"id": i, "ip_addr": "shared", "port": 3306 + i, "type": "MA" if i == 0 else "LEAF"} for i in range(70)]
    export = build_ai_export_json({"cluster_overview": {"nodes_detail": nodes}})
    assert len(export["cluster_topology"]["nodes"]) == 70
    assert export["cluster_topology"]["nodes"][-1]["port"] == 3375
    assert export["cluster_topology"]["nodes_detail"] == nodes


def test_legacy_ma_fallback_is_repaired_without_source_files():
    from parsers import resolve_cluster_overview
    old = {"cluster_overview": {
        "total_nodes": 2, "aggregators": 0, "leaves": 0,
        "nodes_detail": [{"ip_addr": "ma", "type": ""}, {"ip_addr": "leaf", "type": ""}],
        "topology": {"aggregators": [{"Host": "ma", "NodeID": 1, "Master_Aggregator": 1}],
                     "leaves": [{"Host": "leaf", "NodeID": 2}]},
    }}
    repaired = resolve_cluster_overview(old)
    assert repaired["aggregators"] == 1
    assert repaired["leaves"] == 1
    assert any(n["id"] == 1 and n["type"] == "MA" for n in repaired["nodes_detail"])
    assert old["cluster_overview"]["aggregators"] == 0


def test_skew_checker_uses_engine_ports_and_never_scores_partial_samples():
    from superchecker import run_superchecker
    layout = build_partition_layout({"app": {"partitions": [
        {"Host": "shared", "Port": 3306, "Role": "master"} for _ in range(10)
    ] + [{"Host": "shared", "Port": 3307, "Role": "master"}]}})
    def findings(summary):
        return [f for f in run_superchecker({"cluster_layout": summary}) if f["checker_id"] == "clusterLayoutImbalance"]
    assert findings(layout)
    assert not findings({**layout, "counts_are_lower_bounds": True})
    assert not findings({**layout, "classification_complete": False})
