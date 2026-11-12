#!/usr/bin/env python3
"""Rasterize S2 Report Sniffer icon variants to PNG using Pillow.

Both variants mirror the Superdesign "Signal Lens" mark:

* ``full`` mirrors ``docs/assets/logo.svg`` (README logo + desktop app icon).
* ``compact`` mirrors ``docs/s2rs-icon-compact.svg`` (web favicon).

Geometry is expressed in the 256-unit glyph space used by the SVGs and drawn
at 4x supersampling, so output stays crisp at any size. Keeping the renderer
dependency-free makes icon generation deterministic on macOS, Windows, and
Linux build runners.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from PIL import Image, ImageDraw

Variant = Literal["full", "compact"]

SIZE = 512
SUPERSAMPLE = 4

# SingleStore brand palette (singlestore.com/brand).
PURPLE_500 = (209, 153, 255)  # #D199FF
PURPLE_700 = (130, 13, 223)  # #820DDF
BLACK_100 = (242, 242, 242)  # #F2F2F2
TILE = (20, 20, 20)  # #141414
TILE_BORDER = (54, 54, 54)  # #363636

TILE_RADIUS = 225 / 1024

# Glyph placement inside the tile, as (scale, tx, ty) relative to a 1024 canvas.
FULL_TRANSFORM = (2.6, 171.4, 161.0)
COMPACT_TRANSFORM = (3.4, 42.8, 117.6)


def _tile(canvas: int, border: bool) -> Image.Image:
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = round(canvas * TILE_RADIUS)
    draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=radius, fill=TILE)

    # Top-left Purple 700 tint fading to transparent (matches SVG gradient).
    small = Image.new("L", (256, 256), 0)
    small.putdata(
        [
            round(255 * 0.18 * max(0.0, 1 - ((x + y) / 512) / 0.6))
            for y in range(256)
            for x in range(256)
        ]
    )
    tint = small.resize((canvas, canvas), Image.Resampling.BILINEAR)
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, canvas - 1, canvas - 1), radius=radius, fill=255
    )
    tint = Image.composite(tint, Image.new("L", tint.size, 0), mask)
    img.paste(Image.new("RGBA", img.size, (*PURPLE_700, 255)), mask=tint)

    if border:
        width = max(1, round(canvas * 8 / 1024))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            (0, 0, canvas - 1, canvas - 1),
            radius=radius,
            outline=TILE_BORDER,
            width=width,
        )
    return img


def _mapper(
    canvas: int, transform: tuple[float, float, float]
) -> tuple[Callable[[float], float], Callable[[float], float], float]:
    scale, tx, ty = transform
    k = canvas / 1024
    return (
        lambda x: (tx + x * scale) * k,
        lambda y: (ty + y * scale) * k,
        scale * k,
    )


def _draw_full(draw: ImageDraw.ImageDraw, canvas: int) -> None:
    mx, my, s = _mapper(canvas, FULL_TRANSFORM)
    w = 16 * s
    half = w / 2

    def cap(x: float, y: float, color: tuple[int, int, int]) -> None:
        draw.ellipse((mx(x) - half, my(y) - half, mx(x) + half, my(y) + half), fill=color)

    def line(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int]) -> None:
        draw.line((mx(x1), my(y1), mx(x2), my(y2)), fill=color, width=round(w))
        cap(x1, y1, color)
        cap(x2, y2, color)

    def ellipse_box(cx: float, cy: float, rx: float, ry: float) -> tuple[float, ...]:
        return (
            mx(cx - rx) - half,
            my(cy - ry) - half,
            mx(cx + rx) + half,
            my(cy + ry) + half,
        )

    # Database cylinder (Purple 500).
    draw.ellipse(ellipse_box(108, 64, 76, 24), outline=PURPLE_500, width=round(w))
    line(32, 64, 32, 160, PURPLE_500)
    draw.arc(ellipse_box(108, 160, 76, 24), 90, 180, fill=PURPLE_500, width=round(w))
    cap(108, 184, PURPLE_500)
    line(184, 64, 184, 114, PURPLE_500)
    draw.arc(ellipse_box(108, 112, 76, 24), 90, 180, fill=PURPLE_500, width=round(w))
    cap(32, 112, PURPLE_500)
    cap(108, 136, PURPLE_500)

    # Lens (Black 100).
    draw.ellipse(ellipse_box(160, 160, 48, 48), outline=BLACK_100, width=round(w))
    line(194, 194, 232, 232, BLACK_100)


def _draw_compact(draw: ImageDraw.ImageDraw, canvas: int) -> None:
    mx, my, s = _mapper(canvas, COMPACT_TRANSFORM)
    w = 24 * s
    half = w / 2
    for cx, cy, r, color in ((108, 64, 40, PURPLE_500), (160, 160, 48, BLACK_100)):
        draw.ellipse(
            (mx(cx - r) - half, my(cy - r) - half, mx(cx + r) + half, my(cy + r) + half),
            outline=color,
            width=round(w),
        )


def render_icon(variant: Variant = "full", size: int = SIZE) -> Image.Image:
    canvas = size * SUPERSAMPLE
    img = _tile(canvas, border=variant == "full")
    draw = ImageDraw.Draw(img, "RGBA")
    if variant == "full":
        _draw_full(draw, canvas)
    else:
        _draw_compact(draw, canvas)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def save_png(path: str, variant: Variant = "full", size: int = SIZE) -> None:
    render_icon(variant, size).save(path, "PNG")
