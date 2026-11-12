# Design Philosophy: Signal Lens

S2 Report Sniffer reads a SingleStore Cluster Report and surfaces what matters. The mark says exactly that: a **database cylinder** (the cluster) with a **lens** laid over its lower-right corner (the inspection). The cylinder is left open where the lens overlaps it, so the two read as one instrument rather than two stacked icons.

## Geometry

The glyph is drawn on a 256-unit grid with uniform round-capped strokes, no fills:

- Cylinder: top ellipse `cx=108 cy=64 rx=76 ry=24`, left wall, two ring arcs, and a short right wall that stops above the lens.
- Lens: circle `cx=160 cy=160 r=48` with a 45° handle to `(232, 232)`.

Stroke width is 16 units in the app icon. At favicon sizes the cylinder collapses to a single ring beside the lens ring (`docs/s2rs-icon-compact.svg`), because ellipse detail disappears below ~32px.

## Palette

Colors are taken from the SingleStore brand palette ([singlestore.com/brand](https://www.singlestore.com/brand/)):

| Role | Color |
|------|-------|
| Cylinder stroke | Purple 500 `#D199FF` |
| Tile tint (top-left, 18% fading to 0) | Purple 700 `#820DDF` |
| Lens stroke | Black 100 `#F2F2F2` |
| Tile | `#141414`, border `#363636` |

The purple identifies the product as SingleStore; the neutral lens keeps the "inspection" element distinct and high-contrast.

## Sources

| File | Purpose |
|------|---------|
| `docs/assets/logo.svg` | Canonical app icon (README logo, desktop icon source) |
| `docs/s2rs-icon-compact.svg` | Favicon / small-size variant |
| `scripts/icon_render.py` | Pillow renderer mirroring both SVGs |
| `scripts/generate_icon.py` | Builds `desktop/assets/icon.{png,icns,ico}` |
| `scripts/generate_favicon.py` | Builds `frontend/public/assets/favicon.{ico,svg}` |

The mark originates from the Superdesign "S2 Report Sniffer — Logo Design" project.
