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


def test_release_signs_macos_update_manifest_before_checksums_and_publish():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    merge_step = workflow.index("- name: Merge and sign macOS update manifests")
    verify_step = workflow.index("- name: Verify complete macOS set")
    publish_step = workflow.index("- name: Publish macOS-only release")
    merge_block = workflow[merge_step:verify_step]

    # The signing key must come from the repository secret, and the step must fail
    # without it (the CLI exits non-zero), so an unsigned feed is never published.
    assert "S2RS_UPDATE_SIGNING_KEY: ${{ secrets.S2RS_UPDATE_SIGNING_KEY }}" in merge_block
    sign_index = merge_block.index("node scripts/sign-update-manifest.js release-artifacts/latest-mac.yml")
    checksum_index = merge_block.index("generate_checksums.py SHA256SUMS-macos")
    assert sign_index < checksum_index
    assert "test -f release-artifacts/latest-mac.yml.sig" in workflow[verify_step:publish_step]
    # The publish step uploads everything in release-artifacts/*, which includes the .sig.
    assert "release-artifacts/*" in workflow[publish_step:]
    assert workflow.count("actions/setup-node@v4") >= 3


def test_ci_runs_desktop_updater_tests_without_installing_electron():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'working-directory: desktop' in ci
    assert 'node --test "test/**/*.test.js"' in ci


def test_no_private_signing_key_material_in_repo_files():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    # The secret reference is allowed; a literal PEM block must never be committed.
    assert "BEGIN PRIVATE KEY" not in workflow
    assert "PRIVATE KEY" not in (REPO_ROOT / "desktop" / "update-signing.pub").read_text(encoding="utf-8")
