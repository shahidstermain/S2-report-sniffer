"""Helpers for desktop bundle runtime source extraction."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

_RUNTIME_PACKAGE_DIRS = ("services", "local_ai")
_RUNTIME_MIGRATIONS_DIR = "migrations"


def _is_runtime_root_module(filename: str) -> bool:
    if not filename.endswith(".py"):
        return False
    if filename == "__init__.py":
        return False
    if filename == "conftest.py":
        return False
    if filename.startswith("test_"):
        return False
    return True


def locate_bundle_backend_dir(bundle_root: str) -> str | None:
    """Locate the directory that contains runtime backend source files."""
    root = Path(bundle_root)
    candidates = (root / "backend", root)
    for candidate in candidates:
        if (candidate / "server.py").is_file():
            return str(candidate)
    return None


def collect_bundle_runtime_files(bundle_backend_dir: str) -> dict[str, str]:
    """Return {source_path: relative_dest_path} for runtime backend modules."""
    source_root = Path(bundle_backend_dir)
    runtime_files: dict[str, str] = {}

    for path in sorted(source_root.glob("*.py")):
        name = path.name
        if not _is_runtime_root_module(name):
            continue
        rel_dest = "app.py" if name == "server.py" else name
        runtime_files[str(path)] = rel_dest

    migrations_dir = source_root / _RUNTIME_MIGRATIONS_DIR
    if migrations_dir.is_dir():
        for path in sorted(migrations_dir.glob("*.py")):
            runtime_files[str(path)] = f"{_RUNTIME_MIGRATIONS_DIR}/{path.name}"

    for package_dir_name in _RUNTIME_PACKAGE_DIRS:
        package_dir = source_root / package_dir_name
        if not package_dir.is_dir():
            continue
        for path in sorted(package_dir.glob("*.py")):
            runtime_files[str(path)] = f"{package_dir_name}/{path.name}"

    return runtime_files


def _purge_stale_runtime_tree(extracted_dir: Path, expected_relative_files: set[str]) -> None:
    expected_dirs = {""}
    for rel_file in expected_relative_files:
        parent = Path(rel_file).parent
        while str(parent) not in ("", "."):
            expected_dirs.add(str(parent))
            parent = parent.parent

    for root, dirs, files in os.walk(extracted_dir, topdown=False):
        rel_root = os.path.relpath(root, extracted_dir)
        rel_root = "" if rel_root == "." else rel_root

        for filename in files:
            rel_path = f"{rel_root}/{filename}" if rel_root else filename
            if rel_path not in expected_relative_files:
                os.remove(Path(root) / filename)

        for dirname in dirs:
            rel_dir = f"{rel_root}/{dirname}" if rel_root else dirname
            dir_path = Path(root) / dirname
            if rel_dir not in expected_dirs:
                shutil.rmtree(dir_path, ignore_errors=True)
            elif not any(dir_path.iterdir()):
                dir_path.rmdir()


def sync_bundle_runtime_sources(
    bundle_backend_dir: str,
    extracted_dir: str,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    """Mirror backend runtime sources from bundle into extracted_dir."""
    copied: list[str] = []
    runtime_files = collect_bundle_runtime_files(bundle_backend_dir)

    extracted_root = Path(extracted_dir)
    extracted_root.mkdir(parents=True, exist_ok=True)
    _purge_stale_runtime_tree(extracted_root, set(runtime_files.values()))

    for source_path, rel_dest in runtime_files.items():
        destination_path = extracted_root / rel_dest
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        copied.append(rel_dest)
        if log:
            log(f"copied {Path(source_path).name} to {rel_dest}")

    return copied
