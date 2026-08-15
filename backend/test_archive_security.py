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


def test_validate_extract_path_used_by_zip_safe_name():
    base = tempfile.mkdtemp(prefix="s2rs_zip_")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("good/data.json", "{}")
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        target = Path(_validate_extract_path(base, zf.namelist()[0])).resolve()
    assert target.is_relative_to(Path(base).resolve())


def _write_tar_gz(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for name, payload in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))


def test_nested_tar_gz_shares_extraction_budget(monkeypatch, tmp_path):
    """Outer .tar.gz + nested .tar.gz must share one decompression counter.

    Regression: `_extract_tar_gz_payload` used a private counter, so nested
    expansion restarted at 0 and could exceed MAX_EXTRACTED_BYTES (~2x).
    """
    budget = 256 * 1024
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", budget)

    chunk = b"Z" * (budget - 8 * 1024)
    nested_path = tmp_path / "bomb.tar.gz"
    _write_tar_gz(nested_path, {"nested_pad.bin": chunk})

    outer_path = tmp_path / "outer.tar.gz"
    _write_tar_gz(
        outer_path,
        {
            "outer_pad.bin": chunk,
            "bomb.tar.gz": nested_path.read_bytes(),
        },
    )

    with pytest.raises(ValueError, match="maximum safe extraction size"):
        parsers.parse_report_archive_streaming(str(outer_path))


def test_directory_wrapped_nested_tar_gz_shares_extraction_budget(monkeypatch, tmp_path):
    """Nested .tar.gz under a subdirectory must still count against the budget."""
    budget = 256 * 1024
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", budget)

    chunk = b"Y" * (budget - 8 * 1024)
    nested_path = tmp_path / "bomb.tar.gz"
    _write_tar_gz(nested_path, {"nested_pad.bin": chunk})

    outer_path = tmp_path / "outer.tar.gz"
    _write_tar_gz(
        outer_path,
        {
            "outer_pad.bin": chunk,
            "wrapped/dir/bomb.tar.gz": nested_path.read_bytes(),
        },
    )

    with pytest.raises(ValueError, match="maximum safe extraction size"):
        parsers.parse_report_archive_streaming(str(outer_path))


def test_zip_directory_wrapped_nested_tar_gz_shares_extraction_budget(monkeypatch, tmp_path):
    """Zip wrappers with nested tarballs under directories must enforce the budget."""
    budget = 256 * 1024
    monkeypatch.setattr(parsers, "MAX_EXTRACTED_BYTES", budget)

    chunk = b"X" * (budget - 8 * 1024)
    nested_path = tmp_path / "bomb.tar.gz"
    _write_tar_gz(nested_path, {"nested_pad.bin": chunk})

    zip_path = tmp_path / "wrap.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("outer_pad.bin", chunk)
        zf.write(nested_path, arcname="wrapped/dir/bomb.tar.gz")

    with pytest.raises(ValueError, match="maximum safe extraction size"):
        parsers.parse_report_archive_streaming(str(zip_path))
