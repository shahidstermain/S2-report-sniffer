#!/usr/bin/env python3
"""Rasterize S2 Report Sniffer icon variants to PNG using Pillow.

The full desktop variant mirrors ``docs/assets/logo.svg``, which is also used
by the repository README. The compact web variant remains available for the
favicon. Keeping the renderer dependency-free makes icon generation
deterministic on macOS, Windows, and Linux build runners.
"""

from __future__ import annotations

import math
from typing import Literal

from PIL import Image, ImageDraw

Variant = Literal["full", "compact"]

SIZE = 512
CX = CY = SIZE // 2
PAD = 32
OUTER_R = 224

PURPLE_900 = (54, 0, 97)  # #360061
PURPLE_700 = (130, 13, 223)  # #820DDF
PURPLE_500 = (209, 153, 255)  # #D199FF
BLUE_700 = (75, 71, 255)  # #4B47FF
WHITE = (255, 255, 255)
OFF_WHITE = (238, 244, 255)  # #EEF4FF
SNIFFER_BLACK = (5, 5, 7)  # #050507
SINGLESTORE_GREEN = (0, 217, 146)  # #00D992


def _alpha(color: tuple[int, int, int], a: float) -> tuple[int, int, int, int]:
    return (*color, max(0, min(255, int(round(a * 255)))))


def _ring_points(
    count: int, radius: float, phase: float = -math.pi / 2
) -> list[tuple[float, float]]:
    return [
        (
            CX + radius * math.cos(phase + 2 * math.pi * i / count),
            CY + radius * math.sin(phase + 2 * math.pi * i / count),
        )
        for i in range(count)
    ]


def _draw_full(draw: ImageDraw.ImageDraw, img: Image.Image) -> None:
    # Draw at 4x the README SVG coordinate system for clean antialiasing.
    scale = SIZE / 220
    px = lambda value: round(value * scale)
    stroke = px(4)
    green = SINGLESTORE_GREEN

    draw.rounded_rectangle(
        (0, 0, SIZE - 1, SIZE - 1), radius=px(24), fill=SNIFFER_BLACK
    )

    # Database cylinder, matching docs/assets/logo.svg.
    left, right = px(62), px(158)
    top_y, bottom_y = px(58), px(162)
    ellipse_height = px(28)
    draw.ellipse(
        (left, top_y - ellipse_height // 2, right, top_y + ellipse_height // 2),
        outline=green,
        width=stroke,
    )
    draw.line((left, top_y, left, bottom_y), fill=green, width=stroke)
    draw.line((right, top_y, right, bottom_y), fill=green, width=stroke)
    draw.arc(
        (left, bottom_y - ellipse_height // 2, right, bottom_y + ellipse_height // 2),
        0,
        180,
        fill=green,
        width=stroke,
    )
    soft_green = _alpha(green, 0.45)
    for ring_y in (98, 130):
        draw.arc(
            (
                left,
                px(ring_y) - ellipse_height // 2,
                right,
                px(ring_y) + ellipse_height // 2,
            ),
            0,
            180,
            fill=soft_green,
            width=stroke,
        )

    # Snout and bridge. The rounded body intentionally overlaps the cylinder.
    snout = (px(88), px(92), px(132), px(134))
    draw.rounded_rectangle(snout, radius=px(18), fill=green)
    draw.line((px(110), px(80), px(110), px(92)), fill=green, width=stroke)

    for nostril_x in (103, 117):
        draw.ellipse(
            (px(nostril_x - 2.2), px(115 - 3.2), px(nostril_x + 2.2), px(115 + 3.2)),
            fill=SNIFFER_BLACK,
        )
    draw.arc(
        (px(100), px(122), px(120), px(136)), 0, 180, fill=green, width=max(1, px(2.5))
    )


def _draw_compact(draw: ImageDraw.ImageDraw, img: Image.Image) -> None:
    draw.ellipse(
        (CX - OUTER_R - 8, CY - OUTER_R - 8, CX + OUTER_R + 8, CY + OUTER_R + 8),
        fill=PURPLE_900,
    )

    for r, w, a in [(224, 2, 0.55), (160, 2, 0.35), (96, 1, 0.22)]:
        draw.arc(
            (CX - r, CY - r, CX + r, CY + r),
            0,
            360,
            fill=_alpha(PURPLE_700, a),
            width=w,
        )

    for i in range(8):
        angle = -math.pi / 2 + 2 * math.pi * i / 8
        x2 = CX + OUTER_R * math.cos(angle)
        y2 = CY + OUTER_R * math.sin(angle)
        draw.line((CX, CY, x2, y2), fill=_alpha(PURPLE_700, 0.28), width=2)

    for r, color, w, a in [(72, PURPLE_500, 4, 0.95), (52, BLUE_700, 3, 0.85)]:
        draw.arc(
            (CX - r, CY - r, CX + r, CY + r), 0, 360, fill=_alpha(color, a), width=w
        )

    draw.ellipse((CX - 24, CY - 24, CX + 24, CY + 24), fill=_alpha(PURPLE_500, 0.85))
    draw.ellipse((CX - 24, CY - 24, CX + 24, CY + 24), fill=_alpha(WHITE, 0.15))
    draw.line((CX - 12, CY, CX + 12, CY), fill=_alpha(WHITE, 0.90), width=3)
    draw.line((CX, CY - 12, CX, CY + 12), fill=_alpha(WHITE, 0.90), width=3)
    draw.ellipse((CX - 4, CY - 4, CX + 4, CY + 4), fill=_alpha(WHITE, 0.95))


def render_icon(variant: Variant = "full", size: int = 512) -> Image.Image:
    if size != SIZE:
        base = render_icon(variant, SIZE)
        return base.resize((size, size), Image.Resampling.LANCZOS)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    if variant == "full":
        _draw_full(draw, img)
    else:
        _draw_compact(draw, img)
    return img


def save_png(path: str, variant: Variant = "full", size: int = 512) -> None:
    img = render_icon(variant, size)
    background = SNIFFER_BLACK if variant == "full" else PURPLE_900
    rgb = Image.new("RGB", img.size, background)
    rgb.paste(img, mask=img.split()[3])
    rgb.save(path, "PNG")
