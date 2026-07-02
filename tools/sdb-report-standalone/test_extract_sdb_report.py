import os
import subprocess
import tarfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("extract-sdb-report.sh")


def make_toolbox_package(tmp_path: Path) -> Path:
    package_root = tmp_path / "toolbox-root"
    bin_dir = package_root / "bin"
    bin_dir.mkdir(parents=True)
    sdb_report = bin_dir / "sdb-report"
    sdb_report.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == \"version\" ]]; then\n"
        "  echo 'sdb-report test-version'\n"
        "fi\n"
    )
    sdb_report.chmod(0o755)

    package_path = tmp_path / "singlestoredb-toolbox.tar.gz"
    with tarfile.open(package_path, "w:gz") as tf:
        tf.add(package_root, arcname="singlestoredb-toolbox")
    return package_path


def run_extractor(package_path: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TMPDIR"] = str(output_dir.parent)
    return subprocess.run(
        ["bash", str(SCRIPT), "-o", str(output_dir), str(package_path)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def test_installs_into_empty_output_directory(tmp_path: Path):
    package_path = make_toolbox_package(tmp_path)
    output_dir = tmp_path / "bundle"

    result = run_extractor(package_path, output_dir)

    assert result.returncode == 0, result.stderr
    assert (output_dir / "bin" / "sdb-report").is_file()
    assert (output_dir / "bin" / "memsql-report").is_symlink()
    assert (output_dir / ".sdb-report-standalone").read_text() == "managed-by=extract-sdb-report.sh\n"


def test_refuses_non_empty_unmanaged_output_directory(tmp_path: Path):
    package_path = make_toolbox_package(tmp_path)
    output_dir = tmp_path / "important"
    output_dir.mkdir()
    sentinel = output_dir / "do-not-delete.txt"
    sentinel.write_text("keep me")

    result = run_extractor(package_path, output_dir)

    assert result.returncode != 0
    assert "Refusing to delete unmanaged files" in result.stderr
    assert sentinel.read_text() == "keep me"
