"""Archive extraction security regression tests (S-02 / S-03 ZIP/TAR slip)."""
import io
import tarfile
import zipfile
import tempfile
from pathlib import Path

import pytest

from parsers import _extract_tar_members, _validate_extract_path


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
