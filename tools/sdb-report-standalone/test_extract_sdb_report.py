import os
import stat
import subprocess
import tarfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("extract-sdb-report.sh")


def _make_toolbox_tarball(tmp_path: Path) -> Path:
    root = tmp_path / "toolbox-root"
    bin_dir = root / "singlestoredb-toolbox" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "sdb-report"
    binary.write_text("#!/usr/bin/env bash\nif [[ ${1:-} == version ]]; then echo 'sdb-report test'; fi\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    tar_path = tmp_path / "singlestoredb-toolbox-test.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(root / "singlestoredb-toolbox", arcname="singlestoredb-toolbox")
    return tar_path


def test_refuses_non_empty_unmanaged_output_without_deleting_contents(tmp_path: Path) -> None:
    package_path = _make_toolbox_tarball(tmp_path)
    output_dir = tmp_path / "important-output"
    output_dir.mkdir()
    sentinel = output_dir / "keep-me.txt"
    sentinel.write_text("do not delete\n")

    result = subprocess.run(
        ["bash", str(SCRIPT), str(package_path), "--output", str(output_dir)],
        cwd=SCRIPT.parent,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Refusing to replace non-empty unmanaged output directory" in result.stderr
    assert sentinel.read_text() == "do not delete\n"
