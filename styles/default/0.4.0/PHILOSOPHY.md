# Line and wash, slow in and slow out (default@0.4.0)

The look to aim for is the one in Keenan Crane's geometry figures: an object on a white page, drawn with a thin
dark line and filled with a flat pale wash, a single warm accent where the eye should go, and air around it.
Nothing in the picture exists for decoration; what remains is drawn lightly and consistently. This version
inherits every token of `default@0.3.1` (line and wash with solid surfaces) and sets the motion tokens, so
that a clip moves the way the drawing looks: calmly. The rules of motion are written out below, each tied to
a token or a check. The tokens are our own values chosen to produce that feeling; they are not a copy of
anyone's colours.

**The page.** White, always. Objects sit on it with at least six percent of the frame as margin on every side.
A margin is not wasted space; it is what lets a single object read as the subject.

**Line.** Every edge, axis, spine, tick and mesh line is drawn in one dark indigo ink, never black, at a
hairline weight (axes at 1.5 px, mesh lines at 0.6 px at 1080p). Curves carrying data are only a little
heavier (2.8 px). The line is the drawing; the fill is a wash laid under it.

**Wash.** Fills are flat and pale: the primary blue over white for a surface, a lighter blue for soft regions,
apricot for the opposite sign. A surface is nearly solid: its near side hides its far side, as an object
would, and the mesh is a drawing on that side alone. There are no gradients for their own sake, no specular
highlights, no drop shadows.

**Two inks and a grey.** Blue is the working colour for signal; orange is the accent for attention and the
second condition; everything else (axes, text, ticks, the mesh) is the indigo line or a grey-blue derived
from it. A third hue appears only when a third thing must be told apart, and then it is a muted ochre.

**Type.** Helvetica for every label, in a scale of named sizes with nothing below 26 px at 1080p; equations in a
Palatino-lineage math face so they read as mathematics beside sans-serif prose. Titles are rare in a clip and
small when present: the object is the title.

**Axes.** Despined: only the left and bottom spines, drawn along the data box, ticks pointing outward, labels set
just beyond them. No frame, no grid, no top or right line. In three dimensions the floor is a rectangle with
one vertical edge for the third axis, and labels keep facing the viewer while they follow their anchors. Once
the viewer has read the box, the axes may leave: a shape that is understood needs no frame.

**Motion.** A clip feels smooth when nothing in it starts or stops at speed, and when the eye always knows
what will move next. Seven rules, each tied to a token or a check:

1. *Slow in, slow out.* Every motion begins and ends at rest. Sweeps, fades and colour changes ease over
   their whole length with a profile whose speed and acceleration are both continuous (`motion.easing:
   smooth`). The sine ease is not used: its speed rises from zero, but its acceleration starts at full
   strength, and that onset is the kick the eye reads as mechanical. A storyboard that asks for `easing:
   linear` on any action draws a warning from `scianim validate`.
2. *Constant speed only for the camera, and ramped.* The orbit is the one motion allowed to run at constant
   speed, because it is long and the viewer should forget it is there. It ramps up over `motion.ramp_seconds`,
   holds its speed and ramps down (`camera_easing: eased_linear`). An orbit eased over its whole length would
   race in the middle, and a camera already turning on the first frame reads as a machine switched on. A few
   degrees per second is enough; the orbit never carries meaning.
3. *Announce, then move.* Before a value changes, the term that governs it lights up and the readout shows
   where it stands; the picture moves only afterwards. That lead-in is at least as long as the pulse
   (`emphasis_seconds`), so the term has settled when the motion begins; a shorter lead-in draws a warning.
4. *Rest between motions.* An end state is seen before it changes again: at least `hold_seconds` between the
   end of one motion of an object and the moment the next one moves its value, so a lead-in counts as rest.
   A shorter rest draws a warning. Rests of like length give a clip a beat; a clip is a sequence of still
   pictures joined by motion, not motion interrupted by stills.
5. *Hand over, do not cut.* When the next term takes the colour, the previous term gives it up during the same
   rise, and its readout fades into the secondary ink instead of snapping. A pulse is a raised cosine: the term
   grows and settles with zero speed at both ends.
6. *Three things agree.* The term, the number and the picture follow one eased value; nothing counts at a pace
   different from what it describes, and nothing finishes before or after the rest.
7. *Nothing else moves.* No decorative motion and no idle animation; axes and boxes never rescale while
   something varies, and a change in what is shown comes as a fade, never a cut.

A note on frames: thirty per second serve eased motion well; a long slow orbit judders less at sixty, at twice
the render time (`output.fps` in `animation.yaml`).

**Three dimensions.** A surface is a fine mesh in the indigo line over a pale, nearly solid wash, with nothing
lit or shaded. Flat objects, equations and readouts belong to the page and do not turn with the camera.

The specimen beside this file is rendered from the example clips with these tokens (fallback fonts where
Helvetica is absent), so what it shows is what the renderer does.
