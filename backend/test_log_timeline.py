import asyncio
import io
import json
import tarfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from storage import LocalReportStore

REPORT_ID = "d0000000-0000-0000-0000-000000000010"


def make_cluster(root):
    # Two engines on the same host, plus a distinct host with a common prefix.
    for name, filename, content in [
        ("db-1-MA", "Master-3306-aaaaaaaaaa_memsql.log", "2026-01-01 00:00:00.001 INFO: quiet MA\n"),
        ("db-1-LEAF", "Leaf-3307-bbbbbbbbbb_memsql.log",
         "".join(f"165 2026-01-02 00:00:{n % 60:02d}.100 INFO: busy {n}\n" for n in range(5100))),
        ("db-10-CA", "memsql.log", "2026-01-01T08:01:00+08:00 ERROR: older error\n"),
    ]:
        directory = root / name / "memsqlTracelogs"
        directory.mkdir(parents=True)
        if name.endswith("-MA"):
            content = content.encode()
            with tarfile.open(directory / (filename + ".tar.gz"), "w:gz") as tar:
                member = tarfile.TarInfo(filename)
                member.size = len(content)
                tar.addfile(member, io.BytesIO(content))
        else:
            (directory / filename).write_text(content)
    (root / "idle-LEAF" / "memsqlTracelogs").mkdir(parents=True)


@pytest.mark.parametrize("anonymous", [False, True])
def test_import_and_browse_cluster_timeline(tmp_path, anonymous):
    source = tmp_path / "cluster"
    make_cluster(source)
    store = LocalReportStore(tmp_path / "data")
    with patch.object(server, "store", store):
        asyncio.run(store.create_report_stub(REPORT_ID, "cluster", 1, "directory"))
        assert asyncio.run(server._parse_report_background(REPORT_ID, str(source), 1, anonymize=anonymous))
        client = TestClient(server.app)
        route = f"/api/reports/{REPORT_ID}/logs"
        first = client.get(route, params={"page_size": 100}).json()
        assert first["timeline_indexed"] is True
        assert first["total"] == 5102
        assert first["logs"][0]["timestamp"] == "2026-01-02 00:00:59.100"
        assert len(first["log_nodes"]) == 4
        last = client.get(route, params={"page": 52, "page_size": 100}).json()["logs"]
        assert [r["message"] for r in last] == ["older error", "quiet MA"]
        ma = next(n for n in first["log_nodes"] if n["role"] == "MA")
        selected = client.get(route, params={
            "node": ma["hostname"], "node_exact": True, "node_role": "MA", "node_port": ma["port"]
        }).json()
        assert selected["total"] == 1
        assert selected["logs"][0]["message"] == "quiet MA"
        assert selected["log_nodes"] == first["log_nodes"]
        assert client.get(route, params={"node": ma["hostname"], "node_exact": True, "node_role": "CA"}).json()["total"] == 0
        if anonymous:
            assert ma["hostname"].startswith("NODE_")
            assert "db-1" not in json.dumps(last)
            assert b"db-1" not in store._timeline_path(REPORT_ID).read_bytes()
        assert len(first["logs"]) == 100
        page2 = client.get(route, params={"page": 2, "page_size": 100}).json()["logs"]
        assert not ({r["message"] for r in first["logs"]} & {r["message"] for r in page2})


def test_old_index_orders_before_paginating_and_keeps_node_choices(tmp_path):
    store = LocalReportStore(tmp_path)
    asyncio.run(store.create_report_stub(REPORT_ID, "old", 1, "zip"))
    rows = [{"timestamp": f"2026-01-{n:02d} 08:00:00", "hostname": f"h{n % 2}",
             "role": "LEAF", "message": str(n), "severity": "INFO"} for n in range(1, 16)]
    asyncio.run(store.write_report_logs(REPORT_ID, rows))
    with patch.object(server, "store", store):
        client = TestClient(server.app)
        route = f"/api/reports/{REPORT_ID}/logs"
        assert [r["message"] for r in client.get(route, params={"page_size": 10, "page": 2}).json()["logs"]] == ["5", "4", "3", "2", "1"]
        empty = client.get(route, params={"search": "absent"}).json()
        assert empty["timeline_indexed"] is False and empty["total"] == 0
        assert {n["hostname"] for n in empty["log_nodes"]} == {"h0", "h1"}
