"""Archive extraction security regression tests (S-02 / S-03 ZIP/TAR slip)."""
import gzip
import io
import tarfile
import zipfile
import tempfile
from pathlib import Path

import pytest

import parsers
from parsers import _extract_gzip_payload, _extract_tar_members, _validate_extract_path


def test_validate_extract_path_rejects_traversal():
    base = tempfile.mkdtemp(prefix="s2rs_extract_")
    # Traversal names must be rejected outright (fail-closed), not silently kept.
    with pytest.raises(ValueError):
        _validate_extract_path(base, "../../etc/passwd")


def test_validate_extract_path_allows_root_dot_member():
    # The archive's own root entry ("." / "./") is benign and must resolve to the
    # extraction dir, not abort the whole extraction (regression: 0 nodes).
    base = tempfile.mkdtemp(prefix="s2rs_dot_")
    base_resolved = str(Path(base).resolve())
    assert _validate_extract_path(base, ".") == base_resolved
    assert _validate_extract_path(base, "./") == base_resolved
    # Parent-traversal must still be rejected.
    with pytest.raises(ValueError):
        _validate_extract_path(base, "..")


def test_tar_extraction_skips_root_dot_member():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        root = tarfile.TarInfo(name=".")
        root.type = tarfile.DIRTYPE
        tf.addfile(root)
        data = b"{}"
        info = tarfile.TarInfo(name="./data.json")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)

    extract_dir = Path(tempfile.mkdtemp(prefix="s2rs_dotroot_"))
    with tarfile.open(fileobj=buf, mode="r") as tf:
        _extract_tar_members(tf, str(extract_dir), {"total": 0})
    assert (extract_dir / "data.json").exists()


def test_tar_extraction_rejects_path_escape():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        data = b"pwned"
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)

    root = Path(tempfile.mkdtemp(prefix="s2rs_tar_"))
    extract_dir = root / "ext"
    extract_dir.mkdir()
    with tarfile.open(fileobj=buf, mode="r") as tf:
        with pytest.raises(ValueError):
            _extract_tar_members(tf, str(extract_dir), {"total": 0})

    # The malicious member must NOT escape to the parent directory.
    assert not (root / "escape.txt").exists()


def test_tar_extraction_skips_symlinks():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        link = tarfile.TarInfo(name="link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    buf.seek(0)

    extract_dir = Path(tempfile.mkdtemp(prefix="s2rs_symlink_"))
    with tarfile.open(fileobj=buf, mode="r") as tf:
        _extract_tar_members(tf, str(extract_dir), {"total": 0})

    # Symlinks are intentionally not materialized.
    assert not (extract_dir / "link").exists()


def test_validate_extract_path_used_by_zip_safe_name():
    base = tempfile.mkdtemp(prefix="s2rs_zip_")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("good/data.json", "{}")
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        target = Path(_validate_extract_path(base, zf.namelist()[0])).resolve()
    assert target.is_relative_to(Path(base).resolve())


def _write_gzipped_tar(path: Path, member_name: str, payload: bytes) -> int:
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        info = tarfile.TarInfo(name=member_name)
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    tar_bytes = tar_buf.getvalue()
    with gzip.open(path, "wb") as gz:
        gz.write(tar_bytes)
    return len(tar_bytes)


def test_gzip_of_tar_does_not_double_count_extraction_budget(monkeypatch):
    """``.gz`` of a tar must charge retained member bytes once, like ``.tar.gz``.

    Regression: ``_extract_gzip_payload`` counted gunzip bytes into the temp tar
    and again while extracting members, falsely rejecting archives near half the
    safety budget.
    """
    payload = b"x" * (3 * 1024 * 1024)
    budget = 5 * 1024 * 1024
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", budget)

    root = Path(tempfile.mkdtemp(prefix="s2rs_gz_budget_"))
    gz_path = root / "report.gz"
    tar_size = _write_gzipped_tar(gz_path, "host-MA/big.bin", payload)
    assert tar_size < budget < 2 * tar_size

    extract_dir = root / "ext"
    extract_dir.mkdir()
    extracted = {"total": 0}
    _extract_gzip_payload(str(gz_path), str(extract_dir), extracted)

    nested = extract_dir / "_nested" / "host-MA" / "big.bin"
    assert nested.is_file()
    assert nested.read_bytes() == payload
    assert extracted["total"] == len(payload)
    assert extracted["total"] <= budget
    assert not (extract_dir / "report").exists()


def test_plain_gzip_payload_counts_gunzipped_bytes_once(monkeypatch):
    """Non-tar ``.gz`` payloads still charge the retained gunzipped file size."""
    payload = b"plain-collector-bytes" * 1000
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", 1024 * 1024)

    root = Path(tempfile.mkdtemp(prefix="s2rs_gz_plain_"))
    gz_path = root / "collector.gz"
    with gzip.open(gz_path, "wb") as gz:
        gz.write(payload)

    extract_dir = root / "ext"
    extract_dir.mkdir()
    extracted = {"total": 0}
    _extract_gzip_payload(str(gz_path), str(extract_dir), extracted)

    out = extract_dir / "collector"
    assert out.is_file()
    assert out.read_bytes() == payload
    assert extracted["total"] == len(payload)


def test_gz_and_tar_gz_same_payload_accept_under_shared_budget(monkeypatch):
    """Upload-format parity: identical gzipped-tar content must not fail only as ``.gz``."""
    payload = b"y" * (3 * 1024 * 1024)
    budget = 5 * 1024 * 1024
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", budget)

    root = Path(tempfile.mkdtemp(prefix="s2rs_gz_parity_"))
    tar_size = _write_gzipped_tar(root / "report.gz", "host-MA/data.bin", payload)
    assert tar_size < budget < 2 * tar_size
    tar_gz_path = root / "report.tar.gz"
    tar_gz_path.write_bytes((root / "report.gz").read_bytes())

    gz_extract = {"total": 0}
    gz_dir = root / "gz_ext"
    gz_dir.mkdir()
    _extract_gzip_payload(str(root / "report.gz"), str(gz_dir), gz_extract)

    tgz_dir = root / "tgz_ext"
    tgz_dir.mkdir()
    parsers._extract_tar_gz_payload(str(tar_gz_path), str(tgz_dir))

    assert (gz_dir / "_nested" / "host-MA" / "data.bin").read_bytes() == payload
    assert (tgz_dir / "host-MA" / "data.bin").read_bytes() == payload
    assert gz_extract["total"] == len(payload)
