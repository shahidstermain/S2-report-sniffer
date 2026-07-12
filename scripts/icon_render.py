#!/usr/bin/env python3
"""
Rasterize Radiant Signal icon variants to PNG using Pillow.

SVG sources of truth live in docs/s2rs-icon.svg and docs/s2rs-icon-compact.svg.
This module mirrors that geometry for deterministic cross-platform PNG export
without requiring cairo/inkscape.
"""

from __future__ import annotations

import math
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

Variant = Literal["full", "compact"]

SIZE = 512
CX = CY = SIZE // 2
PAD = 32
OUTER_R = 224

PURPLE_900 = (54, 0, 97)       # #360061
PURPLE_700 = (130, 13, 223)    # #820DDF
PURPLE_500 = (209, 153, 255)   # #D199FF
BLUE_700 = (75, 71, 255)       # #4B47FF
WHITE = (255, 255, 255)
OFF_WHITE = (238, 244, 255)    # #EEF4FF


def _alpha(color: tuple[int, int, int], a: float) -> tuple[int, int, int, int]:
    return (*color, max(0, min(255, int(round(a * 255)))))


def _ring_points(count: int, radius: float, phase: float = -math.pi / 2) -> list[tuple[float, float]]:
    return [
        (CX + radius * math.cos(phase + 2 * math.pi * i / count),
         CY + radius * math.sin(phase + 2 * math.pi * i / count))
        for i in range(count)
    ]


def _draw_full(draw: ImageDraw.ImageDraw, img: Image.Image) -> None:
    draw.ellipse((CX - OUTER_R - 8, CY - OUTER_R - 8, CX + OUTER_R + 8, CY + OUTER_R + 8),
                 fill=PURPLE_900)

    for r, w, a in [(224, 1, 0.70), (176, 1, 0.35), (128, 1, 0.25), (80, 1, 0.18)]:
        bbox = (CX - r, CY - r, CX + r, CY + r)
        draw.arc(bbox, 0, 360, fill=_alpha(PURPLE_700, a), width=max(1, w))

    for i in range(12):
        angle = -math.pi / 2 + 2 * math.pi * i / 12
        x2 = CX + OUTER_R * math.cos(angle)
        y2 = CY + OUTER_R * math.sin(angle)
        draw.line((CX, CY, x2, y2), fill=_alpha(PURPLE_700, 0.18), width=1)

    for r, count in [(176, 8), (128, 6), (80, 6)]:
        for x, y in _ring_points(count, r, -math.pi / 2):
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=_alpha(PURPLE_500, 0.40))

    stream_alphas = [0.18, 0.32, 0.55, 0.32, 0.18]
    for sx, sa in zip([-32, -16, 0, 16, 32], stream_alphas):
        draw.line((CX + sx, CY - 132, CX + sx, CY + 132),
                  fill=_alpha(PURPLE_500, sa), width=1)
        for t in [-0.75, -0.30, 0.10, 0.45, 0.80]:
            dy = t * (132 - 10)
            draw.ellipse((CX + sx - 1.5, CY + dy - 1.5, CX + sx + 1.5, CY + dy + 1.5),
                         fill=_alpha(PURPLE_500, sa * 0.7))

    draw.arc((CX - OUTER_R, CY - OUTER_R, CX + OUTER_R, CY + OUTER_R),
             0, 360, fill=_alpha(PURPLE_700, 0.85), width=2)

    for deg in (0, 90, 180, 270):
        angle = math.radians(deg - 90)
        x1 = CX + (OUTER_R - 6) * math.cos(angle)
        y1 = CY + (OUTER_R - 6) * math.sin(angle)
        x2 = CX + (OUTER_R + 2) * math.cos(angle)
        y2 = CY + (OUTER_R + 2) * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=_alpha(PURPLE_500, 0.65), width=2)

    for r, color, w, a in [(56, PURPLE_500, 2, 0.95), (48, PURPLE_700, 1, 0.55), (40, BLUE_700, 2, 0.80)]:
        draw.arc((CX - r, CY - r, CX + r, CY + r), 0, 360, fill=_alpha(color, a), width=w)

    for i in range(8):
        angle = 2 * math.pi * i / 8 - math.pi / 8
        x1 = CX + 51 * math.cos(angle)
        y1 = CY + 51 * math.sin(angle)
        x2 = CX + 58 * math.cos(angle)
        y2 = CY + 58 * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=_alpha(PURPLE_500, 0.75), width=1)

    for r, a in [(26, 0.03), (21, 0.06), (16, 0.10)]:
        draw.ellipse((CX - r, CY - r, CX + r, CY + r), fill=_alpha(PURPLE_500, a))
    draw.ellipse((CX - 16, CY - 16, CX + 16, CY + 16), fill=_alpha(PURPLE_500, 0.80))

    arm = 9
    draw.line((CX - arm, CY, CX + arm, CY), fill=_alpha(WHITE, 0.85), width=1)
    draw.line((CX, CY - arm, CX, CY + arm), fill=_alpha(WHITE, 0.85), width=1)
    draw.ellipse((CX - 2.5, CY - 2.5, CX + 2.5, CY + 2.5), fill=_alpha(WHITE, 0.90))

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Menlo.ttc", 30)
    except OSError:
        font = ImageFont.load_default()
    text = "S2"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((CX - tw / 2, CY + OUTER_R - 48), text, fill=_alpha(OFF_WHITE, 0.88), font=font)

    draw.rectangle((PAD, PAD - 2, SIZE - PAD, PAD - 1), fill=_alpha(PURPLE_700, 0.35))

    bs = 14
    corners = [
        (PAD + 4, PAD + 4, 1, 1),
        (SIZE - PAD - 4, PAD + 4, -1, 1),
        (PAD + 4, SIZE - PAD - 4, 1, -1),
        (SIZE - PAD - 4, SIZE - PAD - 4, -1, -1),
    ]
    for bx, by, dx, dy in corners:
        draw.line((bx, by, bx + dx * bs, by), fill=_alpha(PURPLE_700, 0.45), width=1)
        draw.line((bx, by, bx, by + dy * bs), fill=_alpha(PURPLE_700, 0.45), width=1)


def _draw_compact(draw: ImageDraw.ImageDraw, img: Image.Image) -> None:
    draw.ellipse((CX - OUTER_R - 8, CY - OUTER_R - 8, CX + OUTER_R + 8, CY + OUTER_R + 8),
                 fill=PURPLE_900)

    for r, w, a in [(224, 2, 0.55), (160, 2, 0.35), (96, 1, 0.22)]:
        draw.arc((CX - r, CY - r, CX + r, CY + r), 0, 360, fill=_alpha(PURPLE_700, a), width=w)

    for i in range(8):
        angle = -math.pi / 2 + 2 * math.pi * i / 8
        x2 = CX + OUTER_R * math.cos(angle)
        y2 = CY + OUTER_R * math.sin(angle)
        draw.line((CX, CY, x2, y2), fill=_alpha(PURPLE_700, 0.28), width=2)

    for r, color, w, a in [(72, PURPLE_500, 4, 0.95), (52, BLUE_700, 3, 0.85)]:
        draw.arc((CX - r, CY - r, CX + r, CY + r), 0, 360, fill=_alpha(color, a), width=w)

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
    rgb = Image.new("RGB", img.size, PURPLE_900)
    rgb.paste(img, mask=img.split()[3])
    rgb.save(path, "PNG")
