"""`SnapshotScene`: a Manim scene with a clock, registered objects, scene sections and concurrent tracks.

A track is anything that unfolds over a storyboard window: a reveal, a parameter sweep, a camera orbit, an
axes fade, a move, a fade of an object, the transform of one equation into another.
Generated code begins tracks at their start times and calls `run_until(t, tracks)` for each segment between
breakpoints (track starts and ends, checkpoints), so several tracks advance together and a checkpoint inside
any of them is reached by the real animation flow at the exact frame. Every track exposes `apply(fraction)`
over its own window, so a segment can stop and resume without a seam. Flat objects are fixed in the frame of
a three-dimensional camera; only surfaces turn when the camera orbits.
"""

from __future__ import annotations

import contextlib
import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np
from manim import (
    DOWN,
    LEFT,
    UP,
    Animation,
    FadeIn,
    FadeOut,
    ManimColor,
    Mobject,
    Text,
    ThreeDScene,
    Transform,
    VGroup,
    config,
)
from manim.utils.rate_functions import ease_in_out_sine, ease_in_quad, ease_out_cubic, ease_out_quad, linear, smooth

from scianim_bridge import context as _context
from scianim_bridge.camera import SnapshotCamera
from scianim_bridge.components.base import Component, ParametricComponent, pretty_symbol
from scianim_bridge.components.equations import Correspondence, EquationComponent, match_equations, typeset_equation
from scianim_bridge.placement import Placement
from scianim_bridge.tokens import Tokens
from scianim_core.timing import frames_for

if TYPE_CHECKING:
    from scianim_core.style import Easing

_MARKS = re.compile(r'<mark\s+name="[A-Za-z0-9_]+"\s*/>')

EASINGS: dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_in_out_sine": ease_in_out_sine,
    "smooth": smooth,
    "ease_out_cubic": ease_out_cubic,
    "ease_in_quad": ease_in_quad,
    "ease_out_quad": ease_out_quad,
}


def eased_linear(ramp_fraction: float) -> Callable[[float], float]:
    """Constant speed with a slow-in and a slow-out of `ramp_fraction` of the window each.

    The position is the integral of a trapezoidal velocity whose ramps are smoothstep-shaped, so both velocity
    and acceleration are continuous: no kick at the start, no jolt at the stop, and no racing in the middle,
    which is what an ease over the whole window does to a long motion. Ramps of half the window or more leave
    no constant part, and the profile becomes a plain symmetric ease.
    """
    r = min(0.5, max(1e-6, ramp_fraction))

    def ramp_area(u: float) -> float:  # integral of smoothstep 3u^2 - 2u^3 from 0 to u
        return u**3 - u**4 / 2

    def area(t: float) -> float:
        if t <= r:
            return r * ramp_area(t / r)
        if t <= 1.0 - r:
            return r / 2 + (t - r)
        return (1.0 - r) - r * ramp_area((1.0 - t) / r)

    total = 1.0 - r

    def profile(t: float) -> float:
        if t <= 0.0:
            return 0.0
        if t >= 1.0:
            return 1.0
        return area(t) / total

    return profile


def rate_function(name: str, duration_seconds: float, ramp_seconds: float) -> Callable[[float], float]:
    """The rate profile named by a token or an action, as a function of the window fraction."""
    if name == "eased_linear":
        return eased_linear(ramp_seconds / duration_seconds if duration_seconds > 0 else 0.5)
    return EASINGS[name]


def state_easing(name: str) -> Callable[[float], float]:
    """The profile for a change of state (a colour, an opacity) that has no speed to keep constant."""
    return EASINGS.get(name, smooth)


@dataclass
class Track:
    """Something that unfolds over the storyboard window [at_seconds, at_seconds + duration_seconds]."""

    scene: SnapshotScene
    track_id: str
    at_seconds: float
    duration_seconds: float
    fraction: float = 0.0

    @property
    def mobject(self) -> Mobject:
        return Mobject()

    def apply(self, fraction: float) -> None:
        raise NotImplementedError

    def finish(self) -> None:
        return None

    def target_fraction(self, seconds: float) -> float:
        """The fraction of the window reached at `seconds`; a value within rounding of the end is the end, so a
        segment that stops exactly at a track's end completes it (and calls `finish`) despite floating point."""
        raw = (seconds - self.at_seconds) / self.duration_seconds
        if raw >= 1.0 - 1e-9:
            return 1.0
        return min(1.0, max(self.fraction, raw))


class TrackSegment(Animation):
    """Plays the part [f0, f1] of a track's window over `frames` frames. The rate profile lives in the track,
    so split segments continue the same curve.

    Manim renders frame k of a play as alpha = k / (frames - 0.5), the half frame that makes the frame count
    exact (see `play_frames`); mapped back to k / frames, every rendered frame is one full step and the last
    frame of a segment sits one step short of the breakpoint, where the next segment's first frame lands, so
    motion crosses breakpoints without a hitch. Alpha 1 (the finish, and the single step of fast-forward mode)
    lands exactly on f1, which is what a checkpoint at the breakpoint captures.

    A piece of a play cut at a window boundary (ADR-031) covers `frames` of a whole play of `total` frames,
    starting `offset` frames into it: frame j of the piece is frame `offset + j` of the whole play, so it lands
    at progress `(offset + j) / total`, exactly where the whole play would have put it, and alpha 1 lands at
    `(offset + frames) / total`, the first frame of the next piece (and f1 for the last piece). The whole play
    is the case `offset = 0, total = frames`.
    """

    def __init__(
        self, track: Track, f0: float, f1: float, frames: int = 0, offset: int = 0, total: int | None = None
    ) -> None:
        super().__init__(track.mobject, rate_func=linear, introducer=True)
        self.track, self.f0, self.f1, self.frames = track, f0, f1, frames
        self.offset = offset
        self.total = frames if total is None else total

    def progress(self, alpha: float) -> float:
        if self.frames <= 0 or self.total <= 0:
            return min(1.0, max(0.0, alpha))
        if alpha >= 1.0:
            return min(1.0, (self.offset + self.frames) / self.total)
        return (self.offset + max(0.0, alpha) * (self.frames - 0.5)) / self.total

    def interpolate_mobject(self, alpha: float) -> None:
        self.track.apply(self.f0 + (self.f1 - self.f0) * self.progress(alpha))

    def piece(self, offset: int, frames: int) -> TrackSegment:
        """The same segment over the frames [offset, offset + frames) of the whole play this one stands for."""
        return TrackSegment(self.track, self.f0, self.f1, frames, offset=self.offset + offset, total=self.total)


@dataclass
class Readout:
    component: Component
    place: Callable[[], None]
    typeface: Any
    color: Any


@dataclass
class Sweep(Track):
    """One `vary_parameter` action: the value curve, the emphasized glyphs with pristine copies, the readout.

    With a lead-in, the first `lead_fraction` of the window holds the start value while the term lights up.
    In an equation's `active` highlight mode the emphasized glyphs take `active_color` as the pulse rises and
    the glyphs this action `released` (the term of the previous action on that equation) return to
    `base_color` at the same time.
    """

    component: ParametricComponent = field(kw_only=True)
    parameter: str = field(kw_only=True)
    start_value: float = field(kw_only=True)
    end_value: float = field(kw_only=True)
    easing: Callable[[float], float] = field(kw_only=True)
    emphasized: list[tuple[Mobject, Mobject]] = field(kw_only=True)
    pulse_fraction: float = field(kw_only=True)
    pulse_scale: float = field(kw_only=True)
    readout: Readout | None = field(kw_only=True)
    readout_text: Callable[[float], str] | None = field(kw_only=True)
    lead_fraction: float = field(default=0.0, kw_only=True)
    released: list[tuple[Mobject, Mobject]] = field(default_factory=list, kw_only=True)
    released_readouts: list[tuple[Readout, ManimColor, ManimColor]] = field(default_factory=list, kw_only=True)
    """Readouts of released terms, each with the ink it leaves and the ink it settles into."""
    base_color: ManimColor | None = field(default=None, kw_only=True)
    active_color: ManimColor | None = field(default=None, kw_only=True)
    blend: Callable[[float], float] = field(default=smooth, kw_only=True)
    """Profile of the colour hand-over during the pulse's rise."""
    readouts_settled: bool = field(default=False, kw_only=True)
    emphasis_sources: list[tuple[EquationComponent, str]] = field(default_factory=list, kw_only=True)
    """For each entry of `emphasized`, the equation object and symbol it came from, so a `transform_equation`
    that replaces the glyphs can point the sweep at the new ones (ADR-034)."""
    released_sources: list[EquationComponent] = field(default_factory=list, kw_only=True)
    """For each entry of `released`, the equation object it belongs to."""

    @property
    def mobject(self) -> Mobject:
        return self.component.group

    def retarget(self, equation: EquationComponent) -> None:
        """The equation object was transformed: emphasize the new occurrences of the same symbol, in colour."""
        if not self.emphasis_sources and not self.released_sources:
            return
        emphasized: list[tuple[Mobject, Mobject]] = []
        sources: list[tuple[EquationComponent, str]] = []
        for (part, pristine), (source, symbol) in zip(self.emphasized, self.emphasis_sources, strict=True):
            if source is not equation:
                emphasized.append((part, pristine))
                sources.append((source, symbol))
                continue
            fresh = equation.highlights.get(symbol)
            if fresh is None:  # not shown right now (a transform is replacing the glyphs): an empty placeholder
                fresh = VGroup()
            elif self.active_color is not None:
                fresh.set_color(self.active_color)
            emphasized.append((fresh, fresh.copy()))
            sources.append((source, symbol))
        self.emphasized, self.emphasis_sources = emphasized, sources
        kept = [
            (entry, source)
            for entry, source in zip(self.released, self.released_sources, strict=True)
            if source is not equation
        ]
        self.released = [entry for entry, _ in kept]
        self.released_sources = [source for _, source in kept]

    def progress_at(self, fraction: float) -> float:
        """Progress of the value in [0, 1] at a window fraction: zero through the lead-in, then linear in time."""
        if self.lead_fraction <= 0.0:
            return min(1.0, max(0.0, fraction))
        return min(1.0, max(0.0, (fraction - self.lead_fraction) / (1.0 - self.lead_fraction)))

    def value_at(self, fraction: float) -> float:
        return self.start_value + (self.end_value - self.start_value) * self.easing(self.progress_at(fraction))

    def apply(self, fraction: float) -> None:
        fraction = min(1.0, max(0.0, fraction))
        value = self.value_at(fraction)
        for warning in self.component.set_parameters(**{self.parameter: value}):
            if warning not in self.scene.render_warnings:
                self.scene.render_warnings.append(warning)
        if self.readout is not None and self.readout_text is not None:
            self.scene.set_readout_text(self.readout, self.readout_text(value))
        if self.emphasized or self.released:
            progress = fraction / self.pulse_fraction if self.pulse_fraction > 0 else 1.0
            # A raised cosine: the term grows and settles with zero speed at both ends of the pulse.
            lift = math.sin(math.pi * progress) ** 2 if 0.0 < progress < 1.0 else 0.0
            scale = 1.0 + (self.pulse_scale - 1.0) * lift
            # The colour arrives, and leaves the released term, as the pulse rises; a readout fades the same way.
            rise = self.blend(min(1.0, max(0.0, 2.0 * progress)))
            recolor = self.base_color is not None and self.active_color is not None
            if self.released_readouts and not self.readouts_settled:
                for readout, leaving, settling in self.released_readouts:
                    self.scene.recolor_readout(readout, leaving.interpolate(settling, rise))
                self.readouts_settled = rise >= 1.0
            for part, pristine in self.emphasized:
                part.become(pristine)
                if recolor:
                    part.set_color(self.base_color.interpolate(self.active_color, rise))  # type: ignore[union-attr]
                if scale != 1.0:
                    for occurrence in part.submobjects or [part]:  # each occurrence grows about its own centre
                        occurrence.scale(scale)
                self.scene.fix_in_frame(part)
            for part, pristine in self.released:
                part.become(pristine)
                if recolor:
                    part.set_color(self.active_color.interpolate(self.base_color, rise))  # type: ignore[union-attr]
                self.scene.fix_in_frame(part)


@dataclass
class CameraOrbit(Track):
    """One `orbit_camera` action: the azimuth and elevation move from where they were to the targets.

    The track animates a pointless mobject that sits at the back of the scene: Manim re-draws only the
    mobjects from the first animated one onward and repeats a cached frame for the rest, so without it a
    segment in which only the camera moves would show a frozen picture while the angle silently advanced,
    and the surface would jump to catch up when the next sweep began.
    """

    to_theta: float | None = field(kw_only=True)
    to_phi: float | None = field(kw_only=True)
    start_theta: float = field(kw_only=True)
    start_phi: float = field(kw_only=True)
    easing: Callable[[float], float] = field(kw_only=True)
    dummy: Mobject = field(default_factory=Mobject)

    @property
    def mobject(self) -> Mobject:
        return self.dummy

    def apply(self, fraction: float) -> None:
        eased = self.easing(min(1.0, max(0.0, fraction)))
        camera = self.scene.renderer.camera
        if self.to_theta is not None:
            camera.set_theta(self.start_theta + (self.to_theta - self.start_theta) * eased)
        if self.to_phi is not None:
            camera.set_phi(self.start_phi + (self.to_phi - self.start_phi) * eased)
        self.scene.camera_moved()


@dataclass
class FadeTrack(Track):
    """An object's ink eased between two opacities: every member keeps its own fill and stroke opacity scaled by
    the same factor, so a surface's wash and a label's text fade together. With `remove`, the group leaves the
    scene when the fade reaches zero. `end_scene` fades with it; `fade_object` (ADR-034) is its storyboard face.
    """

    component: Component = field(kw_only=True)
    start_factor: float = field(kw_only=True)
    end_factor: float = field(kw_only=True)
    easing: Callable[[float], float] = field(kw_only=True)
    remove: bool = field(default=False, kw_only=True)
    originals: list[tuple[Mobject, Any, Any, Any]] | None = None

    @property
    def mobject(self) -> Mobject:
        return self.component.group

    def _capture(self) -> None:
        if self.component.ink_originals is not None:
            self.originals = self.component.ink_originals
            return
        self.originals = []
        for member in self.component.group.get_family():
            if hasattr(member, "get_fill_opacities"):
                self.originals.append(
                    (
                        member,
                        member.get_fill_opacities().copy(),
                        member.get_stroke_opacities().copy(),
                        member.get_stroke_opacities(background=True).copy(),
                    )
                )
            elif hasattr(member, "set_opacity"):
                self.originals.append((member, float(getattr(member, "fill_opacity", 1.0)), None, None))
        self.component.ink_originals = self.originals

    def apply(self, fraction: float) -> None:
        if self.originals is None:
            self._capture()
        eased = self.easing(min(1.0, max(0.0, fraction)))
        factor = self.start_factor + (self.end_factor - self.start_factor) * eased
        for member, fill, stroke, background in self.originals or []:
            if stroke is None:
                member.set_opacity(fill * factor)
            else:
                member.set_fill(opacity=fill * factor, family=False)
                member.set_stroke(opacity=stroke * factor, family=False)
                member.set_stroke(opacity=background * factor, family=False, background=True)
        self.component.ink_factor = factor
        if self.component.on_ink is not None:
            self.component.on_ink()

    def finish(self) -> None:
        if self.end_factor <= 0.0:
            self.component.visible = False
            if self.remove:
                self.scene.remove(self.component.group)
        else:
            self.component.visible = True


@dataclass
class AxesFade(Track):
    """One `fade_axes` action: the object's frame, ticks and labels go to invisible, or back to full ink. Once
    gone they leave the object's group, so the layout report sees the shape alone until a fade brings them back."""

    component: Component = field(kw_only=True)
    visible: bool = field(kw_only=True)
    start_opacity: float = field(kw_only=True)
    easing: Callable[[float], float] = field(kw_only=True)

    @property
    def mobject(self) -> Mobject:
        return self.component.axes if self.component.axes is not None else Mobject()

    def apply(self, fraction: float) -> None:
        axes = self.component.axes
        if axes is None:
            return
        eased = self.easing(min(1.0, max(0.0, fraction)))
        target = 1.0 if self.visible else 0.0
        opacity = self.start_opacity + (target - self.start_opacity) * eased
        axes.set_opacity(opacity)
        self.scene._axes_opacity[self.component.object_id] = opacity

    def finish(self) -> None:
        axes = self.component.axes
        if axes is not None and not self.visible and axes in self.component.group.submobjects:
            self.component.group.remove(axes)


@dataclass
class RevealTrack(Track):
    """A reveal as a track, so it can play beside sweeps and orbits in the same segment."""

    component: Component = field(kw_only=True)
    animation: Animation = field(kw_only=True)
    started: bool = False

    @property
    def mobject(self) -> Mobject:
        return self.component.group

    def apply(self, fraction: float) -> None:
        if not self.started:
            self.animation.begin()
            self.started = True
        self.animation.interpolate(min(1.0, max(0.0, fraction)))

    def finish(self) -> None:
        if self.started:
            self.animation.finish()


@dataclass
class MoveTrack(Track):
    """One `move_object` action: a position eased from where the object was when the window opened to an absolute
    target. For a flat object the position is its centre in the frame; for an anchored solid it is a point in the
    anchor surface's data coordinates, which `setter` places (ADR-034)."""

    component: Component = field(kw_only=True)
    start: np.ndarray = field(kw_only=True)
    target: np.ndarray = field(kw_only=True)
    setter: Callable[[np.ndarray], Any] = field(kw_only=True)
    easing: Callable[[float], float] = field(kw_only=True)

    @property
    def mobject(self) -> Mobject:
        return self.component.group

    def position_at(self, fraction: float) -> np.ndarray:
        eased = self.easing(min(1.0, max(0.0, fraction)))
        return self.start + (self.target - self.start) * eased

    def apply(self, fraction: float) -> None:
        self.setter(self.position_at(fraction))


@dataclass
class TransformTrack(Track):
    """One `transform_equation` action. When it starts, the shown formula leaves the object's group and a group
    of transitional pieces takes its place: a copy of every old glyph (or symbol occurrence) that has a partner
    glides and recolours into a copy of that partner, unpaired old glyphs fade out, unpaired new glyphs fade in.
    When it finishes, the pieces leave and the freshly typeset new formula is installed, so the object ends in
    the same state in fast-forward and when rendered frame by frame (ADR-029), and its highlights are the new
    per-symbol groups (ADR-034)."""

    component: EquationComponent = field(kw_only=True)
    new_formula: Mobject = field(kw_only=True)
    new_parts: dict[str, Mobject] = field(kw_only=True)
    new_equation_id: str = field(kw_only=True)
    new_text: str | None = field(kw_only=True)
    correspondence: Correspondence = field(kw_only=True)
    easing: Callable[[float], float] = field(kw_only=True)
    transition: VGroup = field(default_factory=VGroup)
    animations: list[Animation] = field(default_factory=list)
    started: bool = False
    done: bool = False
    index: int = 0

    @property
    def mobject(self) -> Mobject:
        return self.component.group

    def _start(self) -> None:
        self.started = True
        group = self.component.group
        old = self.component.formula
        self.index = (
            group.submobjects.index(old) if old is not None and old in group.submobjects else len(group.submobjects)
        )
        for old_piece, new_piece in self.correspondence.pairs:
            piece, target = old_piece.copy(), new_piece.copy()
            self.transition.add(piece)
            self.animations.append(Transform(piece, target, rate_func=linear))
        for old_piece in self.correspondence.vanishing:
            piece = old_piece.copy()
            self.transition.add(piece)
            self.animations.append(FadeOut(piece, rate_func=linear))
        for new_piece in self.correspondence.appearing:
            piece = new_piece.copy()
            self.transition.add(piece)
            self.animations.append(FadeIn(piece, rate_func=linear))
        if old is not None and old in group.submobjects:
            group.remove(old)
            self.scene.retire(old)
        group.insert(self.index, self.transition)
        for animation in self.animations:
            animation.begin()
        self.scene.fix_in_frame(group)
        # Sweeps that emphasize this object hold placeholders until the new glyphs are installed; otherwise
        # their per-frame `become` would bring the retired glyphs back.
        self.component.highlights = {}
        for sweep in self.scene._sweeps:
            sweep.retarget(self.component)

    def apply(self, fraction: float) -> None:
        if self.done:
            return
        if not self.started:
            self._start()
        eased = self.easing(min(1.0, max(0.0, fraction)))
        for animation in self.animations:
            animation.interpolate(eased)

    def finish(self) -> None:
        if self.done:
            return
        if not self.started:
            self._start()
        for animation in self.animations:
            animation.finish()
        group = self.component.group
        group.remove(self.transition)
        self.scene.retire(self.transition)
        group.insert(self.index, self.new_formula)
        self.component.formula = self.new_formula
        self.component.highlights = self.new_parts
        self.component.equation_id = self.new_equation_id
        if self.component.text_is_formula:
            self.component.text = self.new_text
        self.scene.fix_in_frame(group)
        self.scene.equation_replaced(self.component)
        self.done = True


class SnapshotScene(ThreeDScene):
    """Base class for generated scenes.

    The scene keeps a registry of storyboard objects (for layout reports), opens one Manim section per
    storyboard scene, and exposes `wait_until` and `run_until` so generated code reaches each checkpoint at
    its requested time. The clock is Manim's own `renderer.time`, which advances in fast-forward mode as well.
    The camera is three-dimensional; flat objects are fixed in the frame when they register.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("camera_class", SnapshotCamera)
        super().__init__(**kwargs)
        self.ctx = _context.current()
        self.objects: dict[str, Component] = {}
        self.scene_objects: list[Component] = []
        self.scene_id: str | None = None
        self.checkpoint_log: list[dict[str, Any]] = []
        self.play_log: list[dict[str, Any]] = []
        """Every play or wait: Manim's animation number, the storyboard scene, the clock at its start and its
        frames. The same in every mode, so a planning pass can split a video into ranges of plays (ADR-029).
        A play cut at a window boundary logs one entry per piece, each with the play's `source_index` and its
        `piece` number (ADR-031)."""
        self.split_frames: list[int] = []
        """Global frame indices at which plays are cut into pieces: the window boundaries of a parallel render,
        the same list in every part, so every worker numbers the pieces alike. Empty outside a part."""
        self._source_plays = 0
        """How many plays `play_frames` has been asked for: the index of the next one in the planning pass's
        numbering, whatever pieces it is cut into."""
        self.narration_log: list[dict[str, Any]] = []
        self.timing_warnings: list[str] = []
        self.render_warnings: list[str] = []
        self._tokens: Tokens | None = None
        self._readouts: dict[tuple[str, str], Readout] = {}
        self._readout_anchors: dict[str, Mobject] = {}
        self._active_terms: dict[str, dict[str, tuple[float, Readout | None]]] = {}
        """Per equation object in `active` highlight mode: the symbols holding the colour, with the end of the
        action that lit each one and its readout."""
        self._axes_opacity: dict[str, float] = {}
        self._camera_set = False
        self._sweeps: list[Sweep] = []
        """The sweeps begun in the current storyboard scene, so a transformed equation can retarget them."""

    def setup(self) -> None:
        """Before `construct`: in a video or part render with a segment store, let Manim's per-play cache look
        plays up in the store as well (ADR-033)."""
        super().setup()
        self.store_hits: list[str] = []
        ctx = self.ctx
        store = ctx.job.segment_store if ctx is not None else None
        if store and ctx is not None and ctx.mode in ("video", "part"):
            from scianim_bridge.segment_store import install

            install(self.renderer.file_writer, ctx.project_root / store, self.store_hits)

    # --- context ------------------------------------------------------------------------------
    @property
    def tokens(self) -> Tokens:
        if self._tokens is None:
            if self.ctx is None:
                raise RuntimeError(
                    "SnapshotScene needs a job context: run through `scianim snapshot`, or set "
                    "SCIANIM_JOB_FILE to a job.json it wrote"
                )
            self._tokens = Tokens(self.ctx.style)
        return self._tokens

    @property
    def clock(self) -> float:
        return float(self.renderer.time)

    @property
    def frame_seconds(self) -> float:
        return 1.0 / float(config.frame_rate)

    def frames(self, seconds: float) -> int:
        return frames_for(seconds, float(config.frame_rate))

    def play_frames(self, frames: int, *animations: Any, **kwargs: Any) -> None:
        """Play (or wait) for exactly `frames` frames and pin the clock to the frame grid.

        Manim's time progression `np.arange(0, run_time, 1/fps)` rounds a run time up to the next
        frame; asking for half a frame less yields exactly `frames` frames. The clock is then set
        explicitly, so it stays exact whether the play was rendered, skipped or served from Manim's
        cache, and every storyboard time maps to one frame index (spec section 8.4).

        This is where a parallel render's window boundaries cut a play (ADR-031). A play that crosses one of
        `split_frames` is played as pieces, one Manim play each: a static wait becomes two waits, a play of
        tracks becomes `TrackSegment` pieces that know their offset in the whole play, so every piece renders
        the frames the whole play would have. A play of arbitrary Manim animations, or one with updaters (whose
        first frame sees a zero time step), cannot be cut; it is logged `splittable = False` and the planner
        keeps boundaries out of it.
        """
        if frames < 1:
            return
        fps = float(config.frame_rate)
        source = self._source_plays
        self._source_plays += 1
        family = [m for mob in self.mobjects for m in mob.get_family()]
        has_updaters = bool(self.updaters) or any(m.get_updaters() for m in family)
        static = not animations and not has_updaters
        splittable = (
            not kwargs and not has_updaters and (static or all(isinstance(a, TrackSegment) for a in animations))
        )
        start = round(self.clock * fps)
        cuts = [b - start for b in sorted(set(self.split_frames)) if start < b < start + frames] if splittable else []
        edges = [0, *cuts, frames]
        for piece, (a, b) in enumerate(pairwise(edges)):
            pieces = [segment.piece(a, b - a) for segment in animations] if cuts else list(animations)
            self._play_piece(b - a, pieces, kwargs, static=static)
            self.play_log[-1].update({"splittable": splittable, "source_index": source, "piece": piece})

    def _play_piece(self, frames: int, animations: Sequence[Any], kwargs: dict[str, Any], *, static: bool) -> None:
        """One Manim play of exactly `frames` frames, logged with its animation number, clock and cost.

        The clock is pinned from the integer frame index, `(start + frames) / fps`, not by adding to the previous
        value: the float is then the same in every mode however the frame was reached, whereas a sum reached
        through pieces differs in the last bits and can round a half-frame storyboard gap the other way.
        """
        fps = float(config.frame_rate)
        before = self.clock
        start = round(before * fps)
        index = int(self.renderer.num_plays)
        started = time.perf_counter()
        if animations:
            # Animated plays render `len(np.arange(0, run_time, 1/fps))` frames: half a frame less rounds up.
            self.play(*animations, run_time=(frames - 0.5) / fps, **kwargs)
        else:
            # A static wait repeats one frame `int(run_time * fps)` times: half a frame more truncates down.
            # A wait with updaters renders frame by frame like an animation.
            run_time = (frames + 0.5) / fps if static else (frames - 0.5) / fps
            self.wait(run_time, frozen_frame=static)
        self.renderer.time = (start + frames) / fps
        # Manim leaves `skip_animations` set when it fast-forwarded the play or served it from its per-play cache.
        drawn = not bool(getattr(self.renderer, "skip_animations", False))
        hashes = getattr(self.renderer, "animations_hashes", None) or [None]
        self.play_log.append(
            {
                "index": index,
                "scene_id": self.scene_id,
                "time": before,
                "frames": frames,
                "static": static,
                "drawn": drawn,
                "hash": hashes[index] if len(hashes) > index else None,
                "seconds": time.perf_counter() - started,
            }
        )

    # --- the three-dimensional camera ---------------------------------------------------------
    def ensure_camera(self) -> None:
        """Point the camera as the style says, once; orbits move it from there."""
        if self._camera_set:
            return
        three_d = self.tokens.t.three_d
        self.set_camera_orientation(
            phi=math.radians(three_d.camera_phi_degrees), theta=math.radians(three_d.camera_theta_degrees)
        )
        self._camera_set = True

    def fix_in_frame(self, mobject: Mobject) -> None:
        """Keep a flat object facing the viewer whatever the camera does (re-run after `become`)."""
        self.renderer.camera.add_fixed_in_frame_mobjects(mobject)

    # --- storyboard structure -----------------------------------------------------------------
    def begin_scene(self, scene_id: str, start_seconds: float | None = None) -> None:
        self.ensure_camera()
        self.scene_id = scene_id
        self.scene_objects = []
        self._readouts = {}
        self._readout_anchors = {}
        self._active_terms = {}
        self._axes_opacity = {}
        self._sweeps = []
        self.next_section(scene_id)
        if start_seconds is not None and abs(self.clock - start_seconds) > self.frame_seconds:
            self.timing_warnings.append(
                f"scene '{scene_id}' begins at clock {self.clock:.3f}s, storyboard says {start_seconds:g}s"
            )

    def register(self, component: Component) -> None:
        if component.object_id in self.objects:
            raise ValueError(f"object id '{component.object_id}' registered twice")
        self.objects[component.object_id] = component
        self.scene_objects.append(component)
        if not component.three_d:
            self.fix_in_frame(component.group)

    def wait_until(self, seconds: float) -> None:
        delta = seconds - self.clock
        frames = self.frames(delta)
        if frames >= 1:
            self.play_frames(frames)
        elif delta < -self.frame_seconds:
            self.timing_warnings.append(
                f"clock is {self.clock:.3f}s, already past the requested {seconds:g}s in scene '{self.scene_id}'"
            )

    def end_scene(self, end_seconds: float, keep: bool = False, carry: Sequence[Track] = ()) -> None:
        """Close a scene: fade its objects out over `motion.transition_seconds` unless it keeps them, while the
        tracks in `carry`, still moving when the fade begins (an orbit to the scene's end), run on to their end
        instead of stopping at speed; then rest until `end_seconds`."""
        visible = [c for c in self.scene_objects if c.visible]
        tracks: list[Track] = [t for t in carry if t.fraction < 1.0]
        until = end_seconds
        if visible and not keep:
            transition = self.tokens.t.motion.transition_seconds
            frames = max(1, min(self.frames(transition), self.frames(end_seconds - self.clock)))
            seconds = frames / float(config.frame_rate)
            tracks += [self.begin_fade(c, visible=False, duration_seconds=seconds, remove=True) for c in visible]
            until = self.clock + seconds
        if tracks:
            self.run_until(until, tracks)
        self.wait_until(end_seconds)

    def camera_moved(self) -> None:
        """The camera has a new viewpoint: objects that draw themselves for one (raster surfaces) redraw."""
        for component in self.objects.values():
            if component.on_camera is not None:
                component.on_camera()

    # --- tracks -------------------------------------------------------------------------------
    def begin_fade(
        self,
        component: Component,
        *,
        visible: bool,
        duration_seconds: float | None = None,
        remove: bool = False,
        easing: str | None = None,
        action_id: str | None = None,
    ) -> FadeTrack:
        """Start fading an object out (or back in) now; `run_until` plays it, alone or beside other tracks."""
        motion = self.tokens.t.motion
        duration = duration_seconds if duration_seconds is not None else motion.transition_seconds
        track = FadeTrack(
            scene=self,
            track_id=action_id or f"fade:{component.object_id}",
            at_seconds=self.clock,
            duration_seconds=max(duration, self.frame_seconds),
            component=component,
            start_factor=0.0 if visible else 1.0,
            end_factor=1.0 if visible else 0.0,
            easing=state_easing(easing or motion.easing),
            remove=remove,
        )
        if visible and component.group not in self.mobjects:
            self.add(component.group)
        track.apply(0.0)
        return track

    def begin_reveal(self, component: Component, duration_seconds: float | None = None) -> RevealTrack:
        """Start revealing an object now; `run_until` plays the fade, alone or beside other tracks."""
        duration = duration_seconds if duration_seconds is not None else self.tokens.t.motion.reveal_seconds
        track = RevealTrack(
            scene=self,
            track_id=f"reveal:{component.object_id}",
            at_seconds=self.clock,
            duration_seconds=max(duration, self.frame_seconds),
            component=component,
            animation=FadeIn(component.group),
        )
        self.add(component.group)
        component.visible = True
        track.apply(0.0)
        return track

    def reveal(self, component: Component, run_time: float | None = None) -> None:
        """Reveal one object on its own (the pre-track form; generated code uses tracks)."""
        track = self.begin_reveal(component, run_time)
        self.run_until(track.at_seconds + track.duration_seconds, [track])

    def begin_vary(
        self,
        component: Component,
        parameter: str,
        *,
        to: float,
        at_seconds: float,
        duration_seconds: float,
        action_id: str,
        easing: Easing | None = None,
        emphasize: Sequence[Component] = (),
        show_value: bool = True,
        value_decimals: int = 1,
        value_label: str | None = None,
        lead_in_seconds: float = 0.0,
    ) -> Sweep:
        """Start a `vary_parameter` action: set up the readout and the emphasized glyphs, draw the initial state.

        The sweep's time axis is the storyboard window, lead-in included, so `run_until(end, ...)` always
        completes it even when the clock reached the start late. A later action on the same parameter reuses
        the readout. On an equation in `active` highlight mode, the term of every earlier action on it that has
        ended gives the colour up as this one takes it, and that term's readout recedes to the secondary ink.
        """
        if not isinstance(component, ParametricComponent):
            raise TypeError(
                f"action '{action_id}': '{component.object_id}' is a {component.kind}, which has no parameters"
            )
        if parameter not in component.parameters:
            raise ValueError(
                f"action '{action_id}': '{component.object_id}' has no parameter '{parameter}' "
                f"(declared: {sorted(component.parameters)})"
            )
        tokens = self.tokens
        motion = tokens.t.motion
        total = lead_in_seconds + duration_seconds
        emphasized: list[tuple[Mobject, Mobject]] = []
        emphasis_sources: list[tuple[EquationComponent, str]] = []
        released: list[tuple[Mobject, Mobject]] = []
        released_sources: list[EquationComponent] = []
        released_readouts: list[tuple[Readout, ManimColor, ManimColor]] = []
        base_color: ManimColor | None = None
        active_color: ManimColor | None = None
        units: str | None = None
        color = tokens.color("foreground")
        for eq in emphasize:
            if not isinstance(eq, EquationComponent) or parameter not in eq.highlights:
                raise ValueError(
                    f"action '{action_id}': '{eq.object_id}' does not highlight '{parameter}', so it cannot be emphasized"
                )
            part = eq.highlights[parameter]
            emphasized.append((part, part.copy()))
            emphasis_sources.append((eq, parameter))
            if units is None:
                units = eq.symbol_units.get(parameter)
            if eq.highlight_color is not None and not emphasized[:-1]:
                color = eq.highlight_color
            if eq.highlight_mode == "active" and eq.highlight_color is not None and eq.base_color is not None:
                base_color, active_color = eq.base_color, eq.highlight_color
                terms = self._active_terms.setdefault(eq.object_id, {})
                for symbol, (ends, earlier) in list(terms.items()):
                    if symbol != parameter and ends > at_seconds + 1e-9:
                        continue  # still at work beside this action; it keeps the colour
                    del terms[symbol]
                    if symbol != parameter:
                        prior = eq.highlights[symbol]
                        released.append((prior, prior.copy().set_color(eq.base_color)))
                        released_sources.append(eq)
                    if earlier is not None:
                        released_readouts.append((earlier, earlier.color, tokens.color("secondary_text")))
        readout: Readout | None = None
        readout_text: Callable[[float], str] | None = None
        if show_value:
            label = value_label if value_label is not None else pretty_symbol(parameter)

            def readout_text(value: float, label: str = label, units: str | None = units) -> str:
                return f"{label} = {value:.{value_decimals}f}" + (f" {units}" if units else "")

            reference_id = emphasize[0].object_id if emphasize else component.object_id
            key = (component.object_id, parameter)
            if key in self._readouts:
                readout = self._readouts[key]
                readout.color = color
            else:
                annotation = tokens.typeface("annotation")
                text = Text(readout_text(component.parameters[parameter]), **tokens.text_kwargs(annotation, color))
                group = VGroup(text)
                # Readouts of successive actions on the same reference stack away from it, newest last.
                reference = self._readout_anchors.get(
                    reference_id, emphasize[0].group if emphasize else component.group
                )
                self._readout_anchors[reference_id] = group

                def place(
                    group: VGroup = group, reference: Mobject = reference, beside: bool = bool(emphasize)
                ) -> None:
                    if beside:
                        group.next_to(reference, DOWN, buff=tokens.baseline, aligned_edge=LEFT)
                    else:
                        group.next_to(reference, UP, buff=tokens.baseline, aligned_edge=LEFT)

                place()
                readout_component = Component(
                    action_id,
                    "value_readout",
                    group,
                    text=text.text,
                    font_px=tokens.smallest_text_px("annotation"),
                    text_like=True,
                    visible=True,
                )
                self.register(readout_component)
                self.add(group)
                readout = Readout(readout_component, place, annotation, color)
                self._readouts[key] = readout
        if active_color is not None:
            for eq in emphasize:
                if isinstance(eq, EquationComponent) and eq.highlight_mode == "active":
                    self._active_terms.setdefault(eq.object_id, {})[parameter] = (at_seconds + total, readout)
        pulse_seconds = min(motion.emphasis_seconds, total)
        sweep = Sweep(
            scene=self,
            track_id=action_id,
            at_seconds=at_seconds,
            duration_seconds=total,
            component=component,
            parameter=parameter,
            start_value=component.parameters[parameter],
            end_value=float(to),
            easing=rate_function(easing or motion.easing, duration_seconds, motion.ramp_seconds),
            emphasized=emphasized,
            pulse_fraction=pulse_seconds / total,
            pulse_scale=motion.emphasis_scale,
            readout=readout,
            readout_text=readout_text,
            lead_fraction=lead_in_seconds / total,
            released=released,
            released_readouts=released_readouts,
            base_color=base_color,
            active_color=active_color,
            blend=state_easing(motion.easing),
            emphasis_sources=emphasis_sources,
            released_sources=released_sources,
        )
        self._sweeps.append(sweep)
        sweep.apply(0.0)
        return sweep

    def set_readout_text(self, readout: Readout, text: str) -> None:
        """Show `text` in a readout, as a fresh `Text` in the readout's group.

        A fresh object rather than `become`: `become` aligns the glyph outlines' point counts with the text shown
        before, so the outlines would carry the history of every value displayed, and a scene fast-forwarded
        through a sweep (one value) would not match the same scene rendered frame by frame (ninety values). The
        checkpoints, Manim's per-play cache and the parts of a parallel render all rely on that match (ADR-029).

        The replaced text is emptied, not just removed: Manim draws the family of a play's moving mobjects as
        it was when the play began, so glyphs replaced during a sweep were still drawn, and once out of the
        fixed-in-frame set they were projected through the three-dimensional camera as a faint slanted ghost
        of the play's first value. Found by comparing a play rendered whole with the same play rendered as
        pieces (ADR-031), whose ghosts differed; without points the stale glyphs draw nothing.
        """
        group = readout.component.group
        fresh = Text(text, **self.tokens.text_kwargs(readout.typeface, readout.color))
        for old in list(group.submobjects):
            group.remove(old)
            self.retire(old)
        group.add(fresh)
        readout.place()
        readout.component.text = text
        self.fix_in_frame(group)

    def recolor_readout(self, readout: Readout, color: ManimColor) -> None:
        """Redraw a readout in another ink, in place."""
        readout.color = color
        self.set_readout_text(readout, readout.component.text or "")

    def begin_fade_axes(
        self,
        component: Component,
        *,
        visible: bool,
        at_seconds: float,
        duration_seconds: float,
        action_id: str,
        easing: Easing | None = None,
    ) -> AxesFade:
        """Start a `fade_axes` action on an object that draws its frame, ticks and labels as a separable group."""
        axes = component.axes
        if axes is None:
            raise ValueError(
                f"action '{action_id}': '{component.object_id}' is a {component.kind}, which has no axes to fade"
            )
        if visible and axes not in component.group.submobjects:
            component.group.add(axes)
        fade = AxesFade(
            scene=self,
            track_id=action_id,
            at_seconds=at_seconds,
            duration_seconds=duration_seconds,
            component=component,
            visible=visible,
            start_opacity=self._axes_opacity.get(component.object_id, 1.0),
            easing=rate_function(
                easing or self.tokens.t.motion.easing, duration_seconds, self.tokens.t.motion.ramp_seconds
            ),
        )
        fade.apply(0.0)
        return fade

    def begin_orbit(
        self,
        *,
        to_theta_degrees: float | None,
        to_phi_degrees: float | None,
        at_seconds: float,
        duration_seconds: float,
        action_id: str,
        easing: Easing | None = None,
    ) -> CameraOrbit:
        """Start an `orbit_camera` action from the camera's current angles, with the style's camera profile."""
        self.ensure_camera()
        camera = self.renderer.camera
        motion = self.tokens.t.motion
        orbit = CameraOrbit(
            scene=self,
            track_id=action_id,
            at_seconds=at_seconds,
            duration_seconds=duration_seconds,
            to_theta=math.radians(to_theta_degrees) if to_theta_degrees is not None else None,
            to_phi=math.radians(to_phi_degrees) if to_phi_degrees is not None else None,
            start_theta=float(camera.get_theta()),
            start_phi=float(camera.get_phi()),
            easing=rate_function(
                easing or motion.camera_easing or motion.easing, duration_seconds, motion.ramp_seconds
            ),
        )
        self.add(orbit.dummy)
        self.bring_to_back(orbit.dummy)  # everything after it in draw order, which is everything, re-draws per frame
        orbit.apply(0.0)
        return orbit

    def begin_move(
        self,
        component: Component,
        *,
        to_anchor: str | None = None,
        by: Sequence[float] | None = None,
        to_point: Sequence[float] | None = None,
        at_seconds: float,
        duration_seconds: float,
        action_id: str,
        easing: Easing | None = None,
    ) -> MoveTrack:
        """Start a `move_object` action from where the object is now: a flat object to an anchor of the safe area
        or by an offset in fractions of it, an anchored solid to a point in its surface's coordinates."""
        motion = self.tokens.t.motion
        setter: Callable[[np.ndarray], Any]
        if to_point is not None:
            place_at = getattr(component, "place_at", None)
            if place_at is None or getattr(component, "to_world", None) is None:
                raise ValueError(
                    f"action '{action_id}': '{component.object_id}' is a {component.kind}, which is not anchored in a "
                    "surface's coordinates; to_point moves a sphere"
                )
            start = np.asarray(component.data_point, dtype=float)  # type: ignore[attr-defined]
            target = np.asarray(to_point, dtype=float)
            setter = place_at
        else:
            if component.three_d:
                raise ValueError(
                    f"action '{action_id}': '{component.object_id}' is a {component.kind}, which turns with the camera; "
                    "to_anchor and by move flat objects in the frame"
                )
            group = component.group
            start = np.asarray(group.get_center(), dtype=float)
            if to_anchor is not None:
                probe = group.copy()
                self.tokens.place(probe, to_anchor)  # type: ignore[arg-type]
                target = np.asarray(probe.get_center(), dtype=float)
            else:
                if by is None:
                    raise ValueError(f"action '{action_id}': move_object needs to_anchor, by or to_point")
                x0, y0, x1, y1 = self.tokens.safe_rect()
                target = start + np.array([by[0] * (x1 - x0), by[1] * (y1 - y0), 0.0])
            if component.placement is None:
                component.placement = Placement(group, origin=start)
            placement: Placement = component.placement

            def place(position: np.ndarray) -> None:
                # Base points plus one offset, not `move_to`, which shifts the points by whatever is left (ADR-039).
                placement.place(position - placement.origin)

            setter = place
        track = MoveTrack(
            scene=self,
            track_id=action_id,
            at_seconds=at_seconds,
            duration_seconds=duration_seconds,
            component=component,
            start=start,
            target=target,
            setter=setter,
            easing=rate_function(easing or motion.easing, duration_seconds, motion.ramp_seconds),
        )
        track.apply(0.0)
        return track

    def begin_fade_object(
        self,
        component: Component,
        *,
        visible: bool,
        at_seconds: float,
        duration_seconds: float,
        action_id: str,
        easing: Easing | None = None,
    ) -> FadeTrack:
        """Start a `fade_object` action on the storyboard window: the object's ink goes to nothing and the group
        leaves the scene (it stays registered, invisible), or comes back to full ink."""
        motion = self.tokens.t.motion
        track = FadeTrack(
            scene=self,
            track_id=action_id,
            at_seconds=at_seconds,
            duration_seconds=max(duration_seconds, self.frame_seconds),
            component=component,
            start_factor=0.0 if visible else 1.0,
            end_factor=1.0 if visible else 0.0,
            easing=state_easing(easing or motion.easing),
            remove=True,
        )
        if visible and component.group not in self.mobjects:
            self.add(component.group)
        track.apply(0.0)
        return track

    def begin_transform(
        self,
        component: Component,
        *,
        to: str,
        at_seconds: float,
        duration_seconds: float,
        action_id: str,
        match: str = "by_symbol",
        easing: Easing | None = None,
    ) -> TransformTrack:
        """Start a `transform_equation` action: typeset the target equation with the object's highlighted symbols,
        place it where the formula belongs, pair the glyphs (`match_equations`) and glide between them."""
        if not isinstance(component, EquationComponent) or component.formula is None or component.place_formula is None:
            raise ValueError(
                f"action '{action_id}': '{component.object_id}' is a {component.kind} that shows no equation to transform"
            )
        if self.ctx is None:
            raise RuntimeError("no job context")
        try:
            equation = self.ctx.equations[to]
        except KeyError:
            raise KeyError(
                f"action '{action_id}': equation '{to}' is not in the job; known: {sorted(self.ctx.equations)}"
            ) from None
        tokens = self.tokens
        if component.base_color is None or component.highlight_color is None:
            raise ValueError(f"action '{action_id}': '{component.object_id}' has no inks recorded")
        new_formula, new_parts = typeset_equation(
            tokens,
            equation,
            component.highlight_names,
            component.base_color,
            component.highlight_color,
            component.px_at_1080p,
            component.highlight_mode,
        )
        component.place_formula(new_formula)
        correspondence = match_equations(component.formula, component.highlights, new_formula, new_parts, match)
        # A paired occurrence keeps the colour it has now (lit or not) while it glides.
        for old_piece, new_piece in correspondence.pairs[: sum(correspondence.matched_symbols.values())]:
            new_piece.set_color(old_piece.get_fill_color())
        motion = tokens.t.motion
        track = TransformTrack(
            scene=self,
            track_id=action_id,
            at_seconds=at_seconds,
            duration_seconds=duration_seconds,
            component=component,
            new_formula=new_formula,
            new_parts=new_parts,
            new_equation_id=to,
            new_text=equation.source_for(tokens.t.typography.equation.engine),
            correspondence=correspondence,
            easing=state_easing(easing or motion.easing),
        )
        track.apply(0.0)
        return track

    def retire(self, mobject: Mobject) -> None:
        """Make a mobject that has just left a group draw nothing. Manim's Cairo renderer lists every family
        member once at the start of a play and keeps drawing that list until the play ends, so a member removed
        mid-play is still drawn, and once out of the fixed-in-frame set it is projected through the camera as a
        faint ghost (found twice, by comparing fast-forward with frame-by-frame renders, ADR-034, and a play drawn
        whole with the same play drawn as pieces, ADR-031). Its points are emptied, so the stale reference
        draws nothing wherever it is listed, and it leaves the fixed set, which would otherwise grow by a text
        per frame of every sweep with a readout. A retired mobject is never used again."""
        fixed = getattr(self.renderer.camera, "fixed_in_frame_mobjects", None)
        for member in mobject.get_family():
            if fixed is not None:
                fixed.discard(member)
            member.reset_points()
        mobject.submobjects = []

    def swap_member(self, group: Mobject, old: Mobject, new: Mobject) -> None:
        """Replace one member of a registered object's group by a fresh one, in place and fixed like the group."""
        index = group.submobjects.index(old)
        group.remove(old)
        self.retire(old)
        group.insert(index, new)
        if group in getattr(self.renderer.camera, "fixed_in_frame_mobjects", set()):
            self.fix_in_frame(group)

    def equation_replaced(self, component: EquationComponent) -> None:
        """An equation object shows a new equation: terms that hold the colour keep it where the symbol still
        occurs, running sweeps that emphasize the object move to the new glyphs, vanished symbols are forgotten."""
        terms = self._active_terms.get(component.object_id, {})
        for symbol in list(terms):
            part = component.highlights.get(symbol)
            if part is None:
                del terms[symbol]
            elif component.highlight_color is not None:
                part.set_color(component.highlight_color)
        for sweep in self._sweeps:
            sweep.retarget(component)

    def run_until(self, seconds: float, tracks: Sequence[Track]) -> None:
        """Advance every track to the storyboard time `seconds` in one play, frame-exact.

        Moves apply first in every frame, so a sweep of the same object redraws its curves and markers from the
        moved axes, and the play ends in the same state whether Manim drew it or applied it once (ADR-039). An
        object that a segment brings into the scene still joins it in the order the tracks were given, which is
        its drawing order."""
        targets = [(track, track.target_fraction(seconds)) for track in tracks]
        frames = self.frames(seconds - self.clock)
        if frames >= 1:
            segments = [TrackSegment(track, track.fraction, f1, frames) for track, f1 in targets]
            present = self.get_mobject_family_members()
            for segment in segments:  # as Manim would add them when the play begins, in this order
                if segment.mobject not in present:
                    self.add(segment.mobject)
                    present += segment.mobject.get_family()
            self.play_frames(frames, *sorted(segments, key=lambda segment: not isinstance(segment.track, MoveTrack)))
        else:
            if seconds < self.clock - self.frame_seconds:
                names = ", ".join(track.track_id for track in tracks)
                self.timing_warnings.append(
                    f"tracks {names} should reach {seconds:g}s but the clock is already {self.clock:.3f}s"
                )
            for track, f1 in sorted(targets, key=lambda target: not isinstance(target[0], MoveTrack)):
                track.apply(f1)
        for track, f1 in targets:
            track.fraction = f1
            if f1 >= 1.0:
                track.finish()

    def vary_until(self, sweep: Sweep, seconds: float) -> None:
        """Play one sweep up to `seconds` (the pre-track form; generated code uses `run_until`)."""
        self.run_until(seconds, [sweep])

    def narrate(self, text: str) -> None:
        plain = re.sub(r"\s+", " ", _MARKS.sub(" ", text)).strip()
        words = len(plain.split())
        duration = words / self.tokens.t.motion.narration_words_per_minute * 60.0
        self.narration_log.append({"time": self.clock, "scene": self.scene_id, "text": plain, "seconds": duration})
        with contextlib.suppress(Exception):  # subcaptions matter only in video mode
            self.add_subcaption(plain, duration=max(duration, self.frame_seconds))

    def finish(self, total_seconds: float) -> None:
        self.wait_until(total_seconds)
