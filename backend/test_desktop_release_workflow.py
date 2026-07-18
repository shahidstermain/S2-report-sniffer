from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "desktop-release.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_release_installs_locked_desktop_dependencies_before_packaging():
    workflow = _workflow_text()
    install_step = workflow.index("- name: Install desktop dependencies")
    publish_step = workflow.index("- name: Build and publish signed installer")

    assert install_step < publish_step
    install_block = workflow[install_step:publish_step]
    assert "working-directory: desktop" in install_block
    assert "run: npm ci" in install_block
    assert workflow.count("npx --no-install electron-builder") == 4


def test_windows_signing_uses_materialized_certificate_path():
    workflow = _workflow_text()

    assert 'echo "WINDOWS_CERT_PATH=$cert_path" >> "$GITHUB_ENV"' in workflow
    assert "WINDOWS_CERT_PATH: ${{ secrets.WINDOWS_CERT_PATH }}" not in workflow
