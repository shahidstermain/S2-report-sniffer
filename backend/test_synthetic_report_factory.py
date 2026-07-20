import io
import json
from pathlib import Path
import tarfile

from parsers import parse_report_archive_streaming


def build_synthetic_cluster_report(
    target: Path, *, leaves: int, aggregators: int, log_lines: int
) -> Path:
    with tarfile.open(target, "w:gz") as archive:
        for index in range(leaves + aggregators):
            role = "LEAF" if index < leaves else "CA"
            node = f"synthetic-{index}-{role}"
            rows = {"rows": [{"HOSTNAME": node, "ROLE": role, "STATE": "ONLINE"}]}
            payload = json.dumps(rows).encode()
            info = tarfile.TarInfo(f"report/{node}/informationSchemaMvNodes.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

            logs = "".join(
                f"{line + 1} 2026-01-01 00:00:{line % 60:02d}.000 INFO: synthetic line {line}\n"
                for line in range(log_lines)
            ).encode()
            log_info = tarfile.TarInfo(f"report/{node}/memsqlTracelogs/latest_memsql.log")
            log_info.size = len(logs)
            archive.addfile(log_info, io.BytesIO(logs))
    return target


def test_generated_multi_node_report_round_trip(tmp_path):
    archive = build_synthetic_cluster_report(
        tmp_path / "synthetic.tar.gz", leaves=3, aggregators=1, log_lines=20
    )
    parsed = parse_report_archive_streaming(str(archive))
    assert parsed["raw_node_count"] == 4
    assert len(parsed["logs"]) == 80
