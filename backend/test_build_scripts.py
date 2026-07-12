"""Regression coverage for the portable desktop build entry points."""
import os
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


def test_pyinstaller_spec_excludes_development_virtualenv_from_bundle():
    spec = (REPO_ROOT / "backend" / "s2rs-backend.spec").read_text()
    assert "os.walk" in spec
    assert "'.venv'" in spec

    assert (REPO_ROOT / "scripts" / "smoke-test-backend.sh").is_file()
