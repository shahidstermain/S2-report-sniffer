from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "desktop-release.yml"


def test_release_installs_locked_desktop_dependencies_before_packaging():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    install_step = workflow.index("- name: Install locked desktop dependencies")
    publish_step = workflow.index("- name: Build installer (unsigned)")
    assert install_step < publish_step
    install_block = workflow[install_step:publish_step]
    assert "working-directory: desktop" in install_block
    assert "run: npm ci" in install_block
    assert workflow.count("npx --no-install electron-builder") == 2
    assert "windows-latest" not in workflow
    assert "ubuntu-22.04" not in workflow
    assert "--win" not in workflow
    assert "--linux" not in workflow
    assert "workflow_dispatch:" in workflow
    assert 'mv latest-mac.yml "latest-${{ matrix.target }}.yml"' in workflow
    assert "merge_mac_update_manifests.py" in workflow
