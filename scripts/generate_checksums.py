#!/usr/bin/env python3
"""Generate a deterministic SHA-256 manifest for release artifacts."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: generate_checksums.py OUTPUT_FILE", file=sys.stderr)
        return 2

    output = Path(sys.argv[1])
    files = sorted(
        path
        for path in Path.cwd().iterdir()
        if path.is_file()
        and not path.name.startswith("SHA256SUMS-")
        and path.resolve() != output.resolve()
    )
    if not files:
        print("No release artifacts found for checksum generation.", file=sys.stderr)
        return 1

    output.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )
    print(f"Wrote {output} with {len(files)} artifact checksum(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
