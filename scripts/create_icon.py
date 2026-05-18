#!/usr/bin/env python3
"""
S2 Report Sniffer App Icon — v2 (Refined Masterpiece)
Radiant Signal philosophy: the instrument that reveals cluster health.
"""

import math
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

PURPLE_900 = HexColor("#360061")
PURPLE_700 = HexColor("#820DDF")
PURPLE_500 = HexColor("#D199FF")
BLUE_700   = HexColor("#4B47FF")
WHITE      = HexColor("#FFFFFF")
OFF_WHITE  = HexColor("#EEF4FF")

SIZE = 512
CX   = SIZE / 2
CY   = SIZE / 2
PAD  = 28

OUTER_R    = SIZE / 2 - PAD          # 228
RING_A     = OUTER_R * 0.80          # 182
RING_B     = OUTER_R * 0.58          # 132
RING_C     = OUTER_R * 0.36          # 82
LENS_OUTER = OUTER_R * 0.27          # 62
LENS_INNER = OUTER_R * 0.19          # 43
LENS_MID   = OUTER_R * 0.23          # 52
CORE_R     = OUTER_R * 0.09          # 20


def draw(c):
    # ── 1. Background field ───────────────────────────────────────────────
    c.setFillColor(PURPLE_900)
    c.circle(CX, CY, OUTER_R + 4, fill=1, stroke=0)

    # ── 2. Concentric rings ───────────────────────────────────────────────
    for r, w, a in [
        (OUTER_R, 1.0, 0.70),
        (RING_A,  0.6, 0.35),
        (RING_B,  0.5, 0.25),
        (RING_C,  0.4, 0.18),
    ]:
        c.setStrokeColor(PURPLE_700)
        c.setLineWidth(w)
        c.setStrokeAlpha(a)
        c.circle(CX, CY, r, fill=0, stroke=1)
    c.setStrokeAlpha(1.0)

    # ── 3. Radial spokes (cluster nodes / distributed infra) ────────────
    n_spokes = 16
    for i in range(n_spokes):
        angle = 2 * math.pi * i / n_spokes - math.pi / 2
        x2 = CX + OUTER_R * math.cos(angle)
        y2 = CY + OUTER_R * math.sin(angle)
        c.setStrokeColor(PURPLE_700)
        c.setLineWidth(0.4)
        c.setStrokeAlpha(0.18)
        c.line(CX, CY, x2, y2)
    c.setStrokeAlpha(1.0)

    # ── 4. Node markers at ring intersections ─────────────────────────────
    for r, count in [(RING_A, 8), (RING_B, 12), (RING_C, 6)]:
        for i in range(count):
            angle = 2 * math.pi * i / count - math.pi / count
            x = CX + r * math.cos(angle)
            y = CY + r * math.sin(angle)
            c.setFillColor(PURPLE_500)
            c.setFillAlpha(0.40)
            c.circle(x, y, 2.0, fill=1, stroke=0)
    c.setFillAlpha(1.0)

    # ── 5. Data streams (vertical telemetry lines) ─────────────────────────
    stream_xs = [-32, -16, 0, 16, 32]
    stream_alphas = [0.18, 0.32, 0.55, 0.32, 0.18]

    for sx, sa in zip(stream_xs, stream_alphas):
        c.setStrokeColor(PURPLE_500)
        c.setLineWidth(1.2)
        c.setStrokeAlpha(sa)
        c.line(CX + sx, CY - RING_B, CX + sx, CY + RING_B)

        # Data packet markers
        for j, t in enumerate([-0.75, -0.30, 0.10, 0.45, 0.80]):
            dy = t * (RING_B - 10)
            c.setFillColor(PURPLE_500)
            c.setFillAlpha(sa * 0.7)
            c.circle(CX + sx, CY + dy, 1.5, fill=1, stroke=0)
    c.setStrokeAlpha(1.0)
    c.setFillAlpha(1.0)

    # ── 6. Outer border — bright accent ring ─────────────────────────────
    c.setStrokeColor(PURPLE_700)
    c.setLineWidth(2.0)
    c.setStrokeAlpha(0.85)
    c.circle(CX, CY, OUTER_R, fill=0, stroke=1)
    c.setStrokeAlpha(1.0)

    # ── 7. Cardinal tick marks (N/E/S/W at outer ring) ────────────────────
    for deg in (0, 90, 180, 270):
        angle = math.radians(deg - 90)
        x1 = CX + (OUTER_R - 6) * math.cos(angle)
        y1 = CY + (OUTER_R - 6) * math.sin(angle)
        x2 = CX + (OUTER_R + 2) * math.cos(angle)
        y2 = CY + (OUTER_R + 2) * math.sin(angle)
        c.setStrokeColor(PURPLE_500)
        c.setLineWidth(1.5)
        c.setStrokeAlpha(0.65)
        c.line(x1, y1, x2, y2)

        # Secondary tick (45° offset, smaller)
        for offset in (-45, 45):
            angle2 = math.radians(deg + offset - 90)
            x1s = CX + (OUTER_R - 3) * math.cos(angle2)
            y1s = CY + (OUTER_R - 3) * math.sin(angle2)
            x2s = CX + (OUTER_R + 1) * math.cos(angle2)
            y2s = CY + (OUTER_R + 1) * math.sin(angle2)
            c.setStrokeColor(PURPLE_500)
            c.setLineWidth(0.8)
            c.setStrokeAlpha(0.35)
            c.line(x1s, y1s, x2s, y2s)
    c.setStrokeAlpha(1.0)

    # ── 8. Magnifier lens — outer ring ───────────────────────────────────
    c.setStrokeColor(PURPLE_500)
    c.setLineWidth(2.0)
    c.setStrokeAlpha(0.95)
    c.circle(CX, CY, LENS_OUTER, fill=0, stroke=1)

    # Lens mid ring
    c.setStrokeColor(PURPLE_700)
    c.setLineWidth(0.8)
    c.setStrokeAlpha(0.55)
    c.circle(CX, CY, LENS_MID, fill=0, stroke=1)

    # Lens inner ring — electric blue accent
    c.setStrokeColor(BLUE_700)
    c.setLineWidth(1.5)
    c.setStrokeAlpha(0.80)
    c.circle(CX, CY, LENS_INNER, fill=0, stroke=1)
    c.setStrokeAlpha(1.0)

    # ── 9. Scope tick marks on outer lens ring ────────────────────────────
    for i in range(8):
        angle = 2 * math.pi * i / 8 - math.pi / 8
        x1 = CX + (LENS_OUTER - 5) * math.cos(angle)
        y1 = CY + (LENS_OUTER - 5) * math.sin(angle)
        x2 = CX + (LENS_OUTER + 2) * math.cos(angle)
        y2 = CY + (LENS_OUTER + 2) * math.sin(angle)
        c.setStrokeColor(PURPLE_500)
        c.setLineWidth(1.2)
        c.setStrokeAlpha(0.75)
        c.line(x1, y1, x2, y2)
    c.setStrokeAlpha(1.0)

    # ── 10. Lens core — radial glow ────────────────────────────────────────
    for frac, alpha in [(1.6, 0.03), (1.3, 0.06), (1.0, 0.10)]:
        c.setFillColor(PURPLE_500)
        c.setFillAlpha(alpha)
        c.circle(CX, CY, CORE_R * frac, fill=1, stroke=0)

    # Core solid
    c.setFillColor(PURPLE_500)
    c.setFillAlpha(0.80)
    c.circle(CX, CY, CORE_R, fill=1, stroke=0)
    c.setFillAlpha(1.0)

    # ── 11. Core crosshair ─────────────────────────────────────────────────
    c.setStrokeColor(WHITE)
    c.setLineWidth(1.0)
    c.setStrokeAlpha(0.85)
    arm = CORE_R * 0.55
    c.line(CX - arm, CY, CX + arm, CY)
    c.line(CX, CY - arm, CX, CY + arm)

    # Core dot
    c.setFillColor(WHITE)
    c.setFillAlpha(0.90)
    c.circle(CX, CY, 2.5, fill=1, stroke=0)
    c.setFillAlpha(1.0)
    c.setStrokeAlpha(1.0)

    # ── 12. "S2" monogram (lower arc) ─────────────────────────────────────
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        font_path = "/Users/shahidster/.trae/skills/canvas-design/canvas-fonts/JetBrainsMono-Regular.ttf"
        pdfmetrics.registerFont(TTFont("JB", font_path))
        c.setFont("JB", 30)
        has_font = True
    except Exception:
        has_font = False

    c.setFillColor(OFF_WHITE)
    c.setFillAlpha(0.88)
    if has_font:
        c.drawCentredString(CX, CY - OUTER_R + 40, "S2")
    else:
        c.setFont("Helvetica", 28)
        c.drawCentredString(CX, CY - OUTER_R + 40, "S2")
    c.setFillAlpha(1.0)

    # ── 13. Thin bottom rule ───────────────────────────────────────────────
    bar_top = PAD + 2
    c.setFillColor(PURPLE_700)
    c.setFillAlpha(0.35)
    c.rect(PAD, bar_top, SIZE - 2 * PAD, 1.0, fill=1, stroke=0)
    c.setFillAlpha(1.0)

    # ── 14. Corner brackets (technical precision marks) ─────────────────
    bracket_size = 14
    bracket_w    = 1.2
    corners = [
        (PAD + 4,              SIZE - PAD - 4,              1,  1),
        (SIZE - PAD - 4,      SIZE - PAD - 4,             -1,  1),
        (PAD + 4,             PAD + 4,                      1, -1),
        (SIZE - PAD - 4,      PAD + 4,                     -1, -1),
    ]
    for bx, by, dx, dy in corners:
        c.setStrokeColor(PURPLE_700)
        c.setLineWidth(bracket_w)
        c.setStrokeAlpha(0.45)
        # Horizontal arm
        c.line(bx, by, bx + dx * bracket_size, by)
        # Vertical arm
        c.line(bx, by, bx, by + dy * bracket_size)
    c.setStrokeAlpha(1.0)


def build(output_pdf: str, output_png: str):
    c = canvas.Canvas(output_pdf, pagesize=(SIZE, SIZE))
    c.setTitle("S2 Report Sniffer — App Icon v2")
    c.setAuthor("S2 Report Sniffer")
    c.setSubject("Radiant Signal — Cluster Diagnostic Instrument")
    draw(c)
    c.save()
    print(f"PDF → {output_pdf}")

    try:
        import fitz
        doc = fitz.open(output_pdf)
        page = doc[0]
        mat  = fitz.Matrix(2.5, 2.5)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(output_png)
        print(f"PNG → {output_png}  ({pix.width}×{pix.height})")
    except Exception as e:
        print(f"PDF generated; PNG conversion skipped ({e})")


if __name__ == "__main__":
    import os
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(repo, "docs", "s2rs-icon-v2.pdf")
    png_path = os.path.join(repo, "docs", "s2rs-icon-v2.png")
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    build(pdf_path, png_path)