import json
import os
import tempfile
from pathlib import Path

import partition_audit


def _write_cluster_status(node_dir: Path, rows: list[dict]) -> None:
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "showClusterStatus.json").write_text(json.dumps([{"rows": rows}]))


def test_counts_master_partitions_per_database_host():
    root = Path(tempfile.mkdtemp(prefix="s2rs_pa_"))
    _write_cluster_status(
        root / "host-a-LEAF",
        [
            {"Host": "10.0.0.1", "Database": "orders", "Role": "Master"},
            {"Host": "10.0.0.1", "Database": "orders", "Role": "Master"},
            {"Host": "10.0.0.1", "Database": "orders", "Role": "Slave"},
            {"Host": "10.0.0.2", "Database": "orders", "Role": "Master"},
            {"Host": "10.0.0.1", "Database": "inventory", "Role": "Master"},
        ],
    )
    counts = partition_audit.collect_master_partitions(str(root))
    assert counts == {("orders", "10.0.0.1"): 2, ("orders", "10.0.0.2"): 1, ("inventory", "10.0.0.1"): 1}


def test_ignores_slave_and_unknown_roles():
    root = Path(tempfile.mkdtemp(prefix="s2rs_pa_"))
    _write_cluster_status(
        root / "host-b-LEAF",
        [
            {"Host": "10.0.0.3", "Database": "db1", "Role": "Slave"},
            {"Host": "10.0.0.3", "Database": "db1", "Role": "Reference"},
            {"Host": "10.0.0.3", "Database": "db1", "Role": "master"},  # case-insensitive
        ],
    )
    counts = partition_audit.collect_master_partitions(str(root))
    assert counts == {("db1", "10.0.0.3"): 1}


def test_database_filter_is_case_insensitive():
    root = Path(tempfile.mkdtemp(prefix="s2rs_pa_"))
    _write_cluster_status(
        root / "host-c-LEAF",
        [
            {"Host": "h1", "Database": "Orders", "Role": "Master"},
            {"Host": "h2", "Database": "inventory", "Role": "Master"},
        ],
    )
    counts = partition_audit.collect_master_partitions(str(root), db_filter="orders")
    assert counts == {("Orders", "h1"): 1}


def test_uses_richest_single_cluster_status_file():
    # Each leaf often has a full cluster-wide copy; summing would N× inflate.
    root = Path(tempfile.mkdtemp(prefix="s2rs_pa_"))
    _write_cluster_status(
        root / "leaf-1",
        [{"Host": "h1", "Database": "db", "Role": "Master"}],
    )
    _write_cluster_status(
        root / "leaf-2",
        [
            {"Host": "h1", "Database": "db", "Role": "Master"},
            {"Host": "h2", "Database": "db", "Role": "Master"},
        ],
    )
    counts = partition_audit.collect_master_partitions(str(root))
    assert counts == {("db", "h1"): 1, ("db", "h2"): 1}


def test_missing_dir_returns_empty():
    counts = partition_audit.collect_master_partitions("/nonexistent/path")
    assert counts == {}


def test_text_format_totals():
    counts = {("orders", "10.0.0.1"): 2, ("orders", "10.0.0.2"): 1}
    text = partition_audit._format_text(counts)
    assert "Database: orders  Host: 10.0.0.1  Master partitions: 2" in text
    assert "Total master partitions: 3" in text


def test_json_format_serializes_list():
    counts = {("orders", "h1"): 1}
    payload = json.loads(partition_audit._format_json(counts))
    assert payload == [{"database": "orders", "host": "h1", "master_partitions": 1}]


def test_cli_missing_dir_returns_2(capsys):
    rc = partition_audit.main(["/no/such/dir"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "is not a directory" in err


def test_cli_no_rows_returns_zero(capsys):
    root = tempfile.mkdtemp(prefix="s2rs_pa_empty_")
    rc = partition_audit.main([root])
    assert rc == 0
    assert "No master partition rows" in capsys.readouterr().err
