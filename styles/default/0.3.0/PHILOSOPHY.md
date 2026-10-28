# Line and wash (default@0.3.0)

The look to aim for is the one in Keenan Crane's geometry figures: an object on a white page, drawn with a thin
dark line and filled with a flat pale wash, a single warm accent where the eye should go, and air around it.
Nothing in the picture exists for decoration; what remains is drawn lightly and consistently. The tokens
beside this file are our own values chosen to produce that feeling; they are not a copy of anyone's colours.

**The page.** White, always. Objects sit on it with at least six percent of the frame as margin on every side.
A margin is not wasted space; it is what lets a single object read as the subject.

**Line.** Every edge, axis, spine, tick and mesh line is drawn in one dark indigo ink, never black, at a
hairline weight (axes at 1.5 px, mesh lines at 0.6 px at 1080p). Curves carrying data are only a little
heavier (2.8 px). The line is the drawing; the fill is a wash laid under it.

**Wash.** Fills are flat and pale: the primary blue laid at sixty percent over white for a surface, a lighter
blue for soft regions, apricot for the opposite sign. A surface shows its mesh through the wash. There are no
gradients for their own sake, no specular highlights, no drop shadows.

**Two inks and a grey.** Blue is the working colour for signal; orange is the accent for attention and the
second condition; everything else (axes, text, ticks, the mesh) is the indigo line or a grey-blue derived
from it. A third hue appears only when a third thing must be told apart, and then it is a muted ochre.

**Type.** Helvetica for every label, in a scale of named sizes with nothing below 26 px at 1080p; equations in a
Palatino-lineage math face so they read as mathematics beside sans-serif prose. Titles are rare in a clip and
small when present: the object is the title.

**Axes.** Despined: only the left and bottom spines, drawn along the data box, ticks pointing outward, labels set
just beyond them. No frame, no grid, no top or right line. In three dimensions the floor is a rectangle with
one vertical edge for the third axis, and labels keep facing the viewer while they follow their anchors.

**Motion.** When a quantity changes, three things agree at once: the term in the equation, the number beside it
and the picture. The term grows by a third for most of a second and settles back; the readout counts; the
picture follows with the same easing as everything else. Axes and boxes never rescale while something varies.
The camera, when it turns, turns slowly and from a little above the floor.

**Three dimensions.** A surface is a fine mesh in the indigo line under a pale wash, lit softly, never solid.
Flat objects, equations and readouts belong to the page and do not turn with the camera.

The specimen beside this file is rendered from the example clips with these tokens (fallback fonts where
Helvetica is absent), so what it shows is what the renderer does.
