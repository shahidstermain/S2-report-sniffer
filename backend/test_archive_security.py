"""Archive extraction security regression tests (S-02 / S-03 ZIP/TAR slip)."""
import io
import tarfile
import zipfile
import tempfile
from pathlib import Path

import pytest

import parsers
from parsers import _extract_tar_members, _validate_extract_path, parse_report_archive_streaming


def test_validate_extract_path_rejects_traversal():
    base = tempfile.mkdtemp(prefix="s2rs_extract_")
    # Traversal names must be rejected outright (fail-closed), not silently kept.
    with pytest.raises(ValueError):
        _validate_extract_path(base, "../../etc/passwd")


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


@pytest.mark.parametrize("inner_name", ["support_bundle.tar.gz", "outer/support_bundle.tar.gz"])
def test_nested_tar_gz_inside_zip_counts_expanded_tar_stream(monkeypatch, tmp_path, inner_name):
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="node-a/empty.log")
        info.size = 0
        tf.addfile(info, io.BytesIO(b""))
    nested_bytes = nested.getvalue()

    archive_path = tmp_path / "support_bundle.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, nested_bytes)

    # The inner tar stream expands well beyond this budget even though its file
    # payload is empty. Nested extraction must count gzip output, not only files.
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", len(nested_bytes) + 512)

    with pytest.raises(ValueError, match="Archive exceeds maximum safe extraction size"):
        parse_report_archive_streaming(str(archive_path))


def test_nested_tar_gz_inside_tar_gz_shares_decompression_budget(monkeypatch, tmp_path):
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="node-a/empty.log")
        info.size = 0
        tf.addfile(info, io.BytesIO(b""))
    nested_bytes = nested.getvalue()

    archive_path = tmp_path / "support_bundle.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        info = tarfile.TarInfo(name="outer/support_bundle.tar.gz")
        info.size = len(nested_bytes)
        tf.addfile(info, io.BytesIO(nested_bytes))

    # The outer tar stream fits this budget, but expanding the nested tar stream
    # must continue from the same counter and push the aggregate over the limit.
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", 15 * 1024)

    with pytest.raises(ValueError, match="Archive exceeds maximum safe extraction size"):
        parse_report_archive_streaming(str(archive_path))
