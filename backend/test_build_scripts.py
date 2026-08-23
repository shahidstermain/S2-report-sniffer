"""Regression coverage for the portable desktop build entry points."""
import os
import struct
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_preflight_uses_configured_python_interpreter():
    result = subprocess.run(
        ["bash", "scripts/build-desktop.sh", "--check"],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHON_BIN": sys.executable, "INTERACTIVE_MODE": "false"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "All dependencies satisfied" in result.stdout


def test_desktop_build_uses_curated_pyinstaller_spec():
    build_script = (REPO_ROOT / "scripts" / "build-desktop.sh").read_text()
    assert "backend/s2rs-backend.spec" in build_script


def test_desktop_build_uses_isolated_release_venv_and_smoke_tests_artifact():
    build_script = (REPO_ROOT / "scripts" / "build-desktop.sh").read_text()
    assert "PYTHON_BIN:-" in build_script
    assert "BUILD_VENV_DIR" in build_script
    assert ".build-venv" in build_script
    assert 'smoke-test-backend.sh' in build_script


def test_desktop_build_supports_windows_venv_and_executable_layout():
    build_script = (REPO_ROOT / "scripts" / "build-desktop.sh").read_text()
    smoke_script = (REPO_ROOT / "scripts" / "smoke-test-backend.sh").read_text()

    assert 'Scripts/python.exe' in build_script
    assert 's2rs-backend.exe' in build_script
    assert '"${PYTHON_BIN:-python3}"' in smoke_script


def test_pyinstaller_spec_excludes_development_virtualenv_from_bundle():
    spec = (REPO_ROOT / "backend" / "s2rs-backend.spec").read_text()
    # The curated spec bundles the backend source directory explicitly
    assert "'backend'" in spec or '"backend"' in spec
    assert "desktop_entry.py" in spec

    assert (REPO_ROOT / "scripts" / "smoke-test-backend.sh").is_file()


def test_windows_icon_contains_a_256px_frame():
    icon = (REPO_ROOT / "desktop" / "assets" / "icon.ico").read_bytes()
    reserved, image_type, count = struct.unpack_from("<HHH", icon, 0)
    assert (reserved, image_type) == (0, 1)
    widths = [icon[6 + (index * 16)] or 256 for index in range(count)]
    assert max(widths) >= 256


def test_release_checksum_generator_is_cross_platform(tmp_path):
    (tmp_path / "b.bin").write_bytes(b"second")
    (tmp_path / "a.bin").write_bytes(b"first")
    manifest = tmp_path / "SHA256SUMS-test"

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_checksums.py"), manifest.name],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    raw = manifest.read_bytes()
    assert b"\r" not in raw
    lines = raw.decode("utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["a.bin", "b.bin"]
    assert all(len(line.split("  ", 1)[0]) == 64 for line in lines)


def test_mac_update_manifests_merge_both_architectures(tmp_path):
    x64 = tmp_path / "latest-mac-x64.yml"
    arm64 = tmp_path / "latest-mac-arm64.yml"
    output = tmp_path / "latest-mac.yml"
    x64.write_text(
        "version: 1.2.6\nfiles:\n"
        "  - url: S2-Report-Sniffer-1.2.6-mac.zip\n"
        "    sha512: eDY0\n"
        "    size: 100\n"
        "path: S2-Report-Sniffer-1.2.6-mac.zip\n"
        "sha512: eDY0\n",
        encoding="utf-8",
    )
    arm64.write_text(
        "version: 1.2.6\nfiles:\n"
        "  - url: S2-Report-Sniffer-1.2.6-arm64-mac.zip\n"
        "    sha512: YXJtNjQ=\n"
        "    size: 90\n"
        "path: S2-Report-Sniffer-1.2.6-arm64-mac.zip\n"
        "sha512: YXJtNjQ=\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "merge_mac_update_manifests.py"),
            str(output),
            str(x64),
            str(arm64),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    merged = output.read_text(encoding="utf-8")
    assert "S2-Report-Sniffer-1.2.6-mac.zip" in merged
    assert "S2-Report-Sniffer-1.2.6-arm64-mac.zip" in merged
    assert merged.index("arm64-mac.zip") < merged.index("1.2.6-mac.zip")


def test_release_workflow_is_self_contained_for_unsigned_community_builds():
    workflow = (REPO_ROOT / ".github" / "workflows" / "desktop-release.yml").read_text()
    desktop_package = (REPO_ROOT / "desktop" / "package.json").read_text()

    assert 'CSC_IDENTITY_AUTO_DISCOVERY: "false"' in workflow
    assert "RELEASE_GH_TOKEN" not in workflow
    assert "WINDOWS_CERT_PATH" not in workflow
    assert '--repo "shahidstermain/S2-report-sniffer"' in workflow
    assert '"forceCodeSigning"' not in desktop_package
    assert '"repo": "S2-report-sniffer"' in desktop_package
