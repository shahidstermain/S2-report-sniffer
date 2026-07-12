#!/usr/bin/env python3
"""
Generate web favicon assets from the compact Radiant Signal variant.

Outputs:
  frontend/public/assets/favicon.ico  (16, 32, 48)
  frontend/public/assets/favicon.svg  (compact SVG copy)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)
from icon_render import render_icon, save_png  # noqa: E402


def repo_path(*parts: str) -> str:
    return os.path.join(REPO_ROOT, *parts)


def build_favicon_ico(dest: str) -> None:
    from PIL import Image

    sizes = [16, 32, 48]
    images = [render_icon("compact", sz).convert("RGBA") for sz in sizes]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    images[0].save(
        dest,
        format="ICO",
        sizes=[(im.width, im.height) for im in images],
        append_images=images[1:],
    )
    print(f"ICO → {dest}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate S2 Report Sniffer favicons")
    parser.parse_args()

    assets_dir = repo_path("frontend", "public", "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # Compact PNG preview (optional, useful for docs)
    preview = repo_path("docs", "s2rs-icon-compact-512.png")
    save_png(preview, variant="compact", size=512)
    print(f"PNG → {preview}")

    build_favicon_ico(os.path.join(assets_dir, "favicon.ico"))

    src_svg = repo_path("docs", "s2rs-icon-compact.svg")
    dest_svg = os.path.join(assets_dir, "favicon.svg")
    shutil.copy2(src_svg, dest_svg)
    print(f"SVG → {dest_svg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
