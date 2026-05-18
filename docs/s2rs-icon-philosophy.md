# Design Philosophy: Radiant Signal

## Aesthetic Direction

A visual language built on the principle of **signal emerging from noise** — the idea that a cluster's health is invisible until the right instrument reveals it. The icon is a technical artifact: precise, geometric, and purposeful. It should feel like the kind of diagram a senior engineer draws on a whiteboard to explain how something works — clean enough to trust, detailed enough to mean something.

## Visual Language

### Form
The icon is a circular field — a contained universe, a radar scope, a lens aperture. Within it: concentric rings that suggest temporal layers (nanoseconds compounding into meaning), radial spokes that suggest distributed nodes, and a central focal point that is the act of inspection itself. The magnifying glass is not decorative; it is the primary symbol. Everything else radiates from or toward it.

### Color
SingleStore's purple spectrum provides the entire palette — this is not a choice, it is an identity. The deepest purple (#360061) anchors the field as a near-black substrate, from which lighter purples and whites emerge as signal. The gradient from center (bright #D199FF) to edge (deep #820DDF to #360061) creates the illusion of depth — as if the lens is illuminated from within. A single accent of electric blue (#4B47FF) marks the focal point of the lens, the precise moment of examination.

### Craftsmanship
Every element is placed with the precision of an instrument. Rings are perfectly concentric. Spokes are evenly distributed. Data streams are parallel and equidistant. The magnifying glass is geometrically centered — not approximately, but exactly. The whole composition should appear as if it took a master craftsman hours to calibrate, and the viewer should sense that precision without necessarily being able to articulate it. Small deviations from mathematical regularity are worse than none at all; either everything aligns or it looks broken.

### Typography
Text is architectural, not decorative. "S2" appears in the lower arc in a restrained, technical typeface — thin strokes, wide tracking, precise alignment. The letterforms themselves echo the geometric structure of the icon: the two characters sit at different radii, creating a subtle two-ring composition within the greater whole. No unnecessary words; the icon carries the identity alone.

## Composition

The icon reads from outside in:

1. **Outer ring** — a single-pixel white stroke at maximum radius, the boundary of the system
2. **Secondary rings** — three evenly-spaced concentric rings in graduated purples, suggesting depth and temporal layering
3. **Radial spokes** — twelve thin lines from center to edge, representing the distributed cluster nodes, the physical infrastructure of SingleStore
4. **Node markers** — small circles at spoke intersections with the outer rings, suggesting active cluster members
5. **Data streams** — four horizontal lines of varying opacity traversing the center vertically, suggesting log streams, telemetry, and signal flow
6. **Lens ring** — a double-ring structure in the center, the aperture through which the signal is read
7. **Lens core** — filled circle at the absolute center, bright white-to-purple gradient, the focal point
8. **"S2" monogram** — positioned in the lower arc, rendered in thin technical type, anchoring the composition

## Technical Execution

The icon is built entirely from geometric primitives: circles, lines, and fills. No gradients that would muddy the precision. The palette is locked: four colors only. The composition is centered on a 512×512 grid with exact 50% margins. Every dimension is a multiple of 8 pixels. The result should function at 16×16 (favicon), 64×64 (taskbar), 256×256 (app icon), and beyond — the geometry must hold at every scale.
