"""
Integration test helpers for backend modules.
Provides fixtures and utilities for testing MongoDB-dependent and archive-parsing paths
in degraded (no-MongoDB) or fully mocked environments.
"""
import io
import tarfile
import zipfile
import os
import tempfile
import hashlib
from typing import Dict, Any, List


def create_fake_tar_archive(member_files: Dict[str, str], compression: str = "gz") -> bytes:
    mode = f"w:{compression}" if compression else "w"
    suffix = f".tar.{compression}" if compression else ".tar"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        with tarfile.open(name=tmp.name, mode=mode) as tf:
            for name, content in member_files.items():
                data = content.encode("utf-8") if isinstance(content, str) else content
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        tmp.seek(0)
        return tmp.read()


def create_fake_zip_archive(member_files: Dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in member_files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(name, data)
    return buf.getvalue()


def minimal_report_archive(archive_type: str = "tar.gz", include_manifest: bool = True) -> bytes:
    manifest = (
        '{"collected_at": "2026-03-30T00:00:00Z", "hostname": "test-node-1", '
        '"memsql_version": "8.1.5", "report_version": "1.0"}'
    )
    files = {}
    if include_manifest:
        files["report_manifest.json"] = manifest
    if archive_type == "zip":
        return create_fake_zip_archive(files)
    comp = archive_type.replace("tar.", "")
    return create_fake_tar_archive(files, compression=comp if comp in ("gz", "bz2", "xz") else "gz")


def minimal_report_json() -> Dict[str, Any]:
    return {
        "report_id": "00000000-0000-0000-0000-000000000000",
        "collected_at": "2026-03-30T00:00:00Z",
        "nodes": [],
        "databases": [],
        "cluster_overview": {
            "cluster_status": [],
            "nodes_detail": [],
        },
        "config_health": {"os_checks": []},
        "detected_log_patterns": [],
        "dmesg_events": [],
        "pipelines": [],
        "backup_history": [],
        "recommendations": [],
        "cluster_risk_score": 0,
        "health_score": "unknown",
    }


def synth_node(metrics_override: Dict[str, Any] = None) -> Dict[str, Any]:
    return {
        "hostname": "synth-node-1",
        "node_id": "00000000-0001",
        "role": "leaf",
        "metrics": {
            "cpu": {"idle_pct": 85.0, "user_pct": 12.0, "sys_pct": 2.0, "iowait_pct": 1.0},
            "memory": {"total_mb": 65536, "used_mb": 32768, "used_pct": 50.0, "swap_used_mb": 0},
            "disk": [
                {"filesystem": "/dev/sda1", "size": "100G", "used": "50G", "use_pct": 50, "mounted_on": "/"}
            ],
            "disk_latency": {"reads_await_ms": 1.2, "writes_await_ms": 2.1, "util_pct": 5.0},
        },
        "show_variables": {
            "maximum_memory": "32GB",
            "attach_rebalance_delay": "120",
            "auto_attach": "on",
            "columnstore_segment_rows": "1048576",
            "interpreter_mode": "interpret_first",
        },
        "show_variables_all": {},
        **(metrics_override or {}),
    }


def synth_superchecker_report(nodes: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "report_id": "11111111-1111-1111-1111-111111111111",
        "collected_at": "2026-03-30T00:00:00Z",
        "nodes": nodes or [synth_node()],
        "databases": [],
        "cluster_overview": {
            "cluster_status": [],
            "nodes_detail": [{"version": "8.1.5"}],
        },
        "config_health": {"os_checks": []},
        "detected_log_patterns": [],
        "dmesg_events": [],
        "pipelines": [],
        "backup_history": [],
        "recommendations": [],
        "cluster_risk_score": 0,
        "health_score": "unknown",
    }


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    tar_bytes = minimal_report_archive("tar.gz")
    zip_bytes = minimal_report_archive("zip")
    print(f"tar.gz size: {len(tar_bytes)}, hash: {file_hash(tar_bytes)}")
    print(f"zip size: {len(zip_bytes)}, hash: {file_hash(zip_bytes)}")
