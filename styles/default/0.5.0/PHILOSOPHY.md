# Line and wash, after Keenan Crane (default@0.5.0)

The look to aim for is the one in Keenan Crane's geometry figures: an object on a white page, drawn with a thin
dark line, filled with a pale wash and modelled by one soft light, so that it reads as a matte solid rather
than a diagram; a single warm accent where the eye should go; labels in the same serif as the mathematics; and
air around everything. This version inherits every token of `default@0.4.0` (line and wash with solid
surfaces and slow-in, slow-out motion) and sets the tokens that make a surface a lit object, the mesh a
quiet texture, the type one family, and every line end a pen stroke. The tokens are our own values chosen to
produce that feeling; they are not a copy of anyone's colours or drawings.

**The page.** White, always. Objects sit on it with at least six percent of the frame as margin on every side.
A margin is not wasted space; it is what lets a single object read as the subject.

**Line.** Every edge, axis, spine, tick and curve is drawn in one dark indigo ink, never black, at a hairline
weight (axes at 1.5 px, curves at 2.8 px at 1080p). Lines end and bend in a half circle (`geometry.line_cap:
round`): a pen leaves a round end, and at these weights a square end looks cut. A dashed line is a construction
line or an inhibitory connection, never decoration.

**Wash and light.** A surface is a solid, opaque object (`surface_opacity: 1`) washed in the primary blue, or
in the two inks about a grey zero on a diverging scale, and modelled by one soft light that stands at the
viewer's upper left at the start of a clip and stays in the room while the camera turns
(`light_azimuth_degrees: -60`, `light_elevation_degrees: 55`, relative to the camera's starting azimuth).
Cells that face the light lighten a little toward the page; cells that turn away darken toward the ink, by at
most `shading_strength: 0.45` of the way. There is no specular highlight, no cast shadow and no gradient that
the geometry did not cause: the shade exists so that a ridge reads as a ridge from any angle, as it does on a
clay model under a window.

**Mesh.** The mesh is a texture on the object, not a drawing of it: hairline (0.5 px) in the muted grey-blue
(`mesh_role: muted`), so the light does the modelling and the lines only say that the surface is a surface.

**Two inks and a grey.** Blue is the working colour for signal; orange is the accent for attention and the
second condition; everything else (axes, text, ticks, the mesh) is the indigo line or a grey-blue derived
from it. A third hue appears only when a third thing must be told apart, and then it is a muted ochre.

**Type.** One family on the page: labels, readouts, axis names, tick numbers and captions are set in a
Palatino-lineage serif (Palatino where installed, TeX Gyre Pagella otherwise), the same lineage as the math
face, so a symbol in a label and the same symbol in the equation are recognisably one letter. Sizes are tokens
in a scale of named roles with nothing below 26 px at 1080p. Titles are rare in a clip and small when present:
the object is the title.

**Dots.** A filled dot carries a rim of the page colour (`marker_rim_px_at_1080p: 1.5`), so where it crosses a
line or sits on a wash it stays a dot. A hollow node is a line like any other.

**Axes.** Despined: only the left and bottom spines, drawn along the data box, ticks pointing outward, labels set
just beyond them. No frame, no grid, no top or right line. In three dimensions the floor is a rectangle with
one vertical edge for the third axis, and labels keep facing the viewer while they follow their anchors. Once
the viewer has read the box, the axes may leave: a shape that is understood needs no frame.

**Motion.** Unchanged from `default@0.4.0`, whose philosophy writes out the seven rules: slow in and slow out
for everything that moves between two states; constant speed only for the camera, and ramped; announce a
change before it happens; rest between motions; hand the colour over rather than cut; let the term, the
number and the picture follow one value; and move nothing else.

The specimen beside this file is rendered from the example clips with these tokens (fallback fonts where
Palatino is absent), so what it shows is what the renderer does.
