import asyncio
import json
import zipfile

from services.isolated_parser import parse_archive_isolated


def test_archive_parser_runs_in_child_process(tmp_path):
    archive = tmp_path / "report.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("cluster.json", json.dumps({"nodes": []}))

    parsed = asyncio.run(parse_archive_isolated(str(archive), None))
    assert parsed["detected_format"] == "zip"
    assert parsed["raw_node_count"] == 0
