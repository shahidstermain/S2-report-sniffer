#!/usr/bin/env python3
"""
Generate desktop app icons from Radiant Signal PNG masters.

Outputs:
  docs/s2rs-icon-512.png
  docs/s2rs-icon-1024.png
  desktop/assets/icon.icns   (macOS)
  desktop/assets/icon.ico    (Windows)
  desktop/assets/icon.png    (Linux, 512×512)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)
from icon_render import save_png  # noqa: E402

# Apple iconset: logical size → (1x filename suffix, 2x filename suffix)
ICONSET_ENTRIES = [
    (16, 16, 32),
    (32, 32, 64),
    (128, 128, 256),
    (256, 256, 512),
    (512, 512, 1024),
]


def repo_path(*parts: str) -> str:
    return os.path.join(REPO_ROOT, *parts)


def ensure_png_masters() -> str:
    """Generate 512 and 1024 PNG masters; return path to 1024 source."""
    png_512 = repo_path("docs", "s2rs-icon-512.png")
    png_1024 = repo_path("docs", "s2rs-icon-1024.png")
    os.makedirs(os.path.dirname(png_512), exist_ok=True)
    save_png(png_512, variant="full", size=512)
    save_png(png_1024, variant="full", size=1024)
    print(f"PNG → {png_512}")
    print(f"PNG → {png_1024}")
    return png_1024


def resize_with_sips(src: str, size: int, dest: str) -> None:
    subprocess.run(["sips", "-z", str(size), str(size), src, "--out", dest],
                   check=True, capture_output=True)


def build_icns(src_1024: str, dest_icns: str) -> None:
    if sys.platform != "darwin":
        print("Skipping .icns (requires macOS iconutil)", file=sys.stderr)
        return

    work = tempfile.mkdtemp(prefix="s2rs-iconset-")
    iconset = os.path.join(work, "S2ReportSniffer.iconset")
    os.makedirs(iconset, exist_ok=True)

    try:
        for logical, size_1x, size_2x in ICONSET_ENTRIES:
            out_1x = os.path.join(iconset, f"icon_{logical}x{logical}.png")
            out_2x = os.path.join(iconset, f"icon_{logical}x{logical}@2x.png")
            resize_with_sips(src_1024, size_1x, out_1x)
            resize_with_sips(src_1024, size_2x, out_2x)
            print(f"  iconset {logical}x{logical} + @{size_2x}")

        os.makedirs(os.path.dirname(dest_icns), exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", "-o", dest_icns, iconset],
                         check=True, capture_output=True)
        kb = os.path.getsize(dest_icns) / 1024
        print(f"ICNS → {dest_icns} ({kb:.1f} KB)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_ico(src_1024: str, dest_ico: str) -> None:
    """Build multi-size .ico using Pillow (no external png2ico dependency)."""
    from PIL import Image

    sizes = [16, 32, 48, 64, 128, 256]
    images: list[Image.Image] = []
    for sz in sizes:
        tmp = os.path.join(tempfile.gettempdir(), f"s2rs-ico-{sz}.png")
        resize_with_sips(src_1024, sz, tmp)
        images.append(Image.open(tmp).convert("RGBA"))

    # ICO format: store PNG-encoded frames (supported by Pillow ≥8)
    os.makedirs(os.path.dirname(dest_ico), exist_ok=True)
    images[0].save(
        dest_ico,
        format="ICO",
        sizes=[(im.width, im.height) for im in images],
        append_images=images[1:],
    )
    print(f"ICO → {dest_ico}")


def build_ico_pillow_only(src_1024: str, dest_ico: str) -> None:
    from icon_render import render_icon

    from PIL import Image

    sizes = [16, 32, 48, 64, 128, 256]
    images = [render_icon("full", sz).convert("RGBA") for sz in sizes]
    os.makedirs(os.path.dirname(dest_ico), exist_ok=True)
    images[0].save(
        dest_ico,
        format="ICO",
        sizes=[(im.width, im.height) for im in images],
        append_images=images[1:],
    )
    print(f"ICO → {dest_ico}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate S2 Report Sniffer desktop icons")
    parser.add_argument("--skip-icns", action="store_true", help="Skip macOS .icns generation")
    args = parser.parse_args()

    src = ensure_png_masters()

    dest_png = repo_path("desktop", "assets", "icon.png")
    shutil.copy2(repo_path("docs", "s2rs-icon-512.png"), dest_png)
    print(f"PNG → {dest_png}")

    dest_icns = repo_path("desktop", "assets", "icon.icns")
    if not args.skip_icns:
        build_icns(src, dest_icns)

    dest_ico = repo_path("desktop", "assets", "icon.ico")
    if sys.platform == "darwin" and shutil.which("sips"):
        build_ico(src, dest_ico)
    else:
        build_ico_pillow_only(src, dest_ico)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
