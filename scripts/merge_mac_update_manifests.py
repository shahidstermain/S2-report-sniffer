#!/usr/bin/env python3
"""Merge electron-builder macOS manifests from native architecture jobs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path


def _read_manifest(path: Path) -> tuple[str, list[dict[str, str]]]:
    version = ""
    files: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_files = False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("version:"):
            version = line.split(":", 1)[1].strip().strip("'\"")
            continue
        if line == "files:":
            in_files = True
            continue
        if in_files and line.startswith("  - url:"):
            current = {"url": line.split(":", 1)[1].strip().strip("'\"")}
            files.append(current)
            continue
        if in_files and current is not None and line.startswith("    "):
            key, value = line.strip().split(":", 1)
            current[key] = value.strip().strip("'\"")
            continue
        if in_files and line and not line.startswith(" "):
            in_files = False

    if not version or not files:
        raise ValueError(f"Incomplete macOS update manifest: {path}")
    for item in files:
        if not {"url", "sha512", "size"}.issubset(item):
            raise ValueError(f"Incomplete file entry in macOS manifest: {path}")
    return version, files


def merge_manifests(output: Path, inputs: list[Path]) -> None:
    """Write one deterministic updater manifest containing every native build."""

    versions: set[str] = set()
    files_by_url: dict[str, dict[str, str]] = {}
    for path in inputs:
        version, files = _read_manifest(path)
        versions.add(version)
        for item in files:
            existing = files_by_url.get(item["url"])
            if existing is not None and existing != item:
                raise ValueError(f"Conflicting manifest entry: {item['url']}")
            files_by_url[item["url"]] = item

    if len(versions) != 1:
        raise ValueError(f"macOS manifests disagree on version: {sorted(versions)}")

    files = sorted(
        files_by_url.values(),
        key=lambda item: ("arm64" not in item["url"], item["url"]),
    )
    default = next(
        (item for item in files if "arm64" in item["url"] and item["url"].endswith(".zip")),
        next(item for item in files if item["url"].endswith(".zip")),
    )
    generated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )

    lines = [f"version: {versions.pop()}", "files:"]
    for item in files:
        lines.extend(
            [
                f"  - url: {item['url']}",
                f"    sha512: {item['sha512']}",
                f"    size: {item['size']}",
            ]
        )
    lines.extend(
        [
            f"path: {default['url']}",
            f"sha512: {default['sha512']}",
            f"releaseDate: '{generated_at}'",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    merge_manifests(args.output, args.inputs)


if __name__ == "__main__":
    main()
