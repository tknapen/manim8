"""`SnapshotScene`: a Manim scene with a clock, registered objects, scene sections and concurrent tracks.

A track is anything that unfolds over a storyboard window: a reveal, a parameter sweep, a camera orbit, an
axes fade.
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from manim import DOWN, LEFT, UP, Animation, FadeIn, FadeOut, ManimColor, Mobject, Text, ThreeDScene, VGroup, config
from manim.utils.rate_functions import ease_in_out_sine, ease_out_cubic, linear, smooth

from scianim_bridge import context as _context
from scianim_bridge.camera import SnapshotCamera
from scianim_bridge.components.base import Component, ParametricComponent, pretty_symbol
from scianim_bridge.components.equations import EquationComponent
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
}


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
        return min(1.0, max(self.fraction, (seconds - self.at_seconds) / self.duration_seconds))


class TrackSegment(Animation):
    """Plays the part [f0, f1] of a track's window. The rate profile lives in the track, so split segments
    continue the same curve; in fast-forward mode Manim evaluates alpha = 1 once, which lands on f1."""

    def __init__(self, track: Track, f0: float, f1: float) -> None:
        super().__init__(track.mobject, rate_func=linear, introducer=True)
        self.track, self.f0, self.f1 = track, f0, f1

    def interpolate_mobject(self, alpha: float) -> None:
        self.track.apply(self.f0 + (self.f1 - self.f0) * self.rate_func(alpha))


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
    base_color: ManimColor | None = field(default=None, kw_only=True)
    active_color: ManimColor | None = field(default=None, kw_only=True)

    @property
    def mobject(self) -> Mobject:
        return self.component.group

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
            text = self.readout_text(value)
            inner = self.readout.component.group[0]
            inner.become(Text(text, **self.scene.tokens.text_kwargs(self.readout.typeface, self.readout.color)))
            self.readout.place()
            self.readout.component.text = text
            self.scene.fix_in_frame(self.readout.component.group)
        if self.emphasized or self.released:
            progress = fraction / self.pulse_fraction if self.pulse_fraction > 0 else 1.0
            scale = 1.0 + (self.pulse_scale - 1.0) * math.sin(math.pi * progress) if 0.0 < progress < 1.0 else 1.0
            rise = min(
                1.0, max(0.0, 2.0 * progress)
            )  # the colour arrives, and leaves the released term, as the pulse rises
            recolor = self.base_color is not None and self.active_color is not None
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
    """One `orbit_camera` action: the azimuth and elevation move from where they were to the targets."""

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
        """
        if frames < 1:
            return
        fps = float(config.frame_rate)
        before = self.clock
        if animations:
            # Animated plays render `len(np.arange(0, run_time, 1/fps))` frames: half a frame less rounds up.
            self.play(*animations, run_time=(frames - 0.5) / fps, **kwargs)
        else:
            # A static wait repeats one frame `int(run_time * fps)` times: half a frame more truncates down.
            # A wait with updaters renders frame by frame like an animation.
            static = not self.updaters and not any(m.get_updaters() for mob in self.mobjects for m in mob.get_family())
            run_time = (frames + 0.5) / fps if static else (frames - 0.5) / fps
            self.wait(run_time, frozen_frame=static)
        self.renderer.time = before + frames / fps

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

    def end_scene(self, end_seconds: float, keep: bool = False) -> None:
        visible = [c for c in self.scene_objects if c.visible]
        if visible and not keep:
            transition = self.tokens.t.motion.transition_seconds
            frames = max(1, min(self.frames(transition), self.frames(end_seconds - self.clock)))
            self.play_frames(frames, *[FadeOut(c.group) for c in visible])
            for component in visible:
                component.visible = False
        self.wait_until(end_seconds)

    # --- tracks -------------------------------------------------------------------------------
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
        released: list[tuple[Mobject, Mobject]] = []
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
                    if earlier is not None:
                        self._recolor_readout(earlier, tokens.color("secondary_text"))
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
            easing=EASINGS[easing or motion.easing],
            emphasized=emphasized,
            pulse_fraction=pulse_seconds / total,
            pulse_scale=motion.emphasis_scale,
            readout=readout,
            readout_text=readout_text,
            lead_fraction=lead_in_seconds / total,
            released=released,
            base_color=base_color,
            active_color=active_color,
        )
        sweep.apply(0.0)
        return sweep

    def _recolor_readout(self, readout: Readout, color: ManimColor) -> None:
        """Redraw a readout in another ink, in place."""
        readout.color = color
        inner = readout.component.group[0]
        inner.become(Text(readout.component.text or "", **self.tokens.text_kwargs(readout.typeface, color)))
        readout.place()
        self.fix_in_frame(readout.component.group)

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
            easing=EASINGS[easing or self.tokens.t.motion.easing],
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
        """Start an `orbit_camera` action from the camera's current angles."""
        self.ensure_camera()
        camera = self.renderer.camera
        orbit = CameraOrbit(
            scene=self,
            track_id=action_id,
            at_seconds=at_seconds,
            duration_seconds=duration_seconds,
            to_theta=math.radians(to_theta_degrees) if to_theta_degrees is not None else None,
            to_phi=math.radians(to_phi_degrees) if to_phi_degrees is not None else None,
            start_theta=float(camera.get_theta()),
            start_phi=float(camera.get_phi()),
            easing=EASINGS[easing or self.tokens.t.motion.easing],
        )
        orbit.apply(0.0)
        return orbit

    def run_until(self, seconds: float, tracks: Sequence[Track]) -> None:
        """Advance every track to the storyboard time `seconds` in one play, frame-exact."""
        targets = [(track, track.target_fraction(seconds)) for track in tracks]
        frames = self.frames(seconds - self.clock)
        if frames >= 1:
            self.play_frames(frames, *[TrackSegment(track, track.fraction, f1) for track, f1 in targets])
        else:
            if seconds < self.clock - self.frame_seconds:
                names = ", ".join(track.track_id for track in tracks)
                self.timing_warnings.append(
                    f"tracks {names} should reach {seconds:g}s but the clock is already {self.clock:.3f}s"
                )
            for track, f1 in targets:
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
