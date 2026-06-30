"""Archive extraction security regression tests (S-02 / S-03 ZIP/TAR slip)."""
import io
import tarfile
import zipfile
import tempfile
from pathlib import Path

import pytest

import parsers
from parsers import _extract_tar_members, _validate_extract_path


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


def test_tar_gz_budget_counts_extracted_files_once(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="s2rs_tgz_budget_"))
    archive_path = root / "report.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        for name in ("a.txt", "b.txt"):
            data = b"x" * 40
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

    extract_dir = root / "extract"
    extract_dir.mkdir()
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", 100)

    parsers._extract_tar_gz_payload(str(archive_path), str(extract_dir))

    assert (extract_dir / "a.txt").read_bytes() == b"x" * 40
    assert (extract_dir / "b.txt").read_bytes() == b"x" * 40


def test_validate_extract_path_used_by_zip_safe_name():
    base = tempfile.mkdtemp(prefix="s2rs_zip_")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("good/data.json", "{}")
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        target = Path(_validate_extract_path(base, zf.namelist()[0])).resolve()
    assert target.is_relative_to(Path(base).resolve())
