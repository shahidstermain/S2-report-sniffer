from pathlib import Path

from desktop_bundle_support import (
    collect_bundle_runtime_files,
    locate_bundle_backend_dir,
    sync_bundle_runtime_sources,
)


def _write(path: Path, content: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_locate_bundle_backend_dir_prefers_backend_subdir(tmp_path: Path):
    _write(tmp_path / "server.py")
    _write(tmp_path / "backend" / "server.py")
    resolved = locate_bundle_backend_dir(str(tmp_path))
    assert resolved == str(tmp_path / "backend")


def test_locate_bundle_backend_dir_falls_back_to_bundle_root(tmp_path: Path):
    _write(tmp_path / "server.py")
    resolved = locate_bundle_backend_dir(str(tmp_path))
    assert resolved == str(tmp_path)


def test_collect_bundle_runtime_files_includes_package_modules(tmp_path: Path):
    _write(tmp_path / "server.py", "app = object()\n")
    _write(tmp_path / "parsers.py")
    _write(tmp_path / "test_parsers.py")
    _write(tmp_path / "conftest.py")
    _write(tmp_path / "services" / "__init__.py")
    _write(tmp_path / "services" / "analysis_jobs.py")
    _write(tmp_path / "local_ai" / "__init__.py")
    _write(tmp_path / "local_ai" / "service.py")
    _write(tmp_path / "migrations" / "001_add_recommendations_metadata.py")

    runtime = collect_bundle_runtime_files(str(tmp_path))
    rel_paths = set(runtime.values())
    assert "app.py" in rel_paths
    assert "parsers.py" in rel_paths
    assert "services/analysis_jobs.py" in rel_paths
    assert "local_ai/service.py" in rel_paths
    assert "migrations/001_add_recommendations_metadata.py" in rel_paths
    assert "test_parsers.py" not in rel_paths
    assert "conftest.py" not in rel_paths


def test_sync_bundle_runtime_sources_copies_and_purges_stale_paths(tmp_path: Path):
    bundle = tmp_path / "bundle_backend"
    extracted = tmp_path / "extracted"

    _write(bundle / "server.py", "app = object()\n")
    _write(bundle / "validators.py")
    _write(bundle / "services" / "__init__.py")
    _write(bundle / "services" / "analysis_jobs.py")
    _write(bundle / "local_ai" / "__init__.py")
    _write(bundle / "local_ai" / "service.py")
    _write(bundle / "migrations" / "001_add_recommendations_metadata.py")

    _write(extracted / "stale.py")
    _write(extracted / "legacy_pkg" / "__init__.py")
    _write(extracted / "legacy_pkg" / "old.py")

    copied = sync_bundle_runtime_sources(str(bundle), str(extracted))
    assert "app.py" in copied
    assert (extracted / "app.py").is_file()
    assert (extracted / "validators.py").is_file()
    assert (extracted / "services" / "analysis_jobs.py").is_file()
    assert (extracted / "local_ai" / "service.py").is_file()
    assert (extracted / "migrations" / "001_add_recommendations_metadata.py").is_file()

    assert not (extracted / "stale.py").exists()
    assert not (extracted / "legacy_pkg").exists()
