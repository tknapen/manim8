"""`SnapshotScene`: a Manim scene with a clock, registered objects, scene sections and parameter sweeps."""

from __future__ import annotations

import contextlib
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from manim import DOWN, LEFT, UP, Animation, FadeOut, Mobject, Scene, Text, VGroup, config
from manim.utils.rate_functions import ease_in_out_sine, ease_out_cubic, linear, smooth

from scianim_bridge import context as _context
from scianim_bridge.components.base import Component, pretty_symbol
from scianim_bridge.components.equations import EquationComponent
from scianim_bridge.components.plots import FunctionPlotComponent
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
class Sweep:
    """One `vary_parameter` action in flight: its value curve over the storyboard window, the emphasized
    equation glyphs with pristine copies, and the readout. `apply(fraction)` sets every part of the picture
    for a point of the window, so a segment can stop at a checkpoint and resume without a seam."""

    scene: SnapshotScene
    action_id: str
    component: FunctionPlotComponent
    parameter: str
    start_value: float
    end_value: float
    at_seconds: float
    duration_seconds: float
    easing: Callable[[float], float]
    emphasized: list[tuple[Mobject, Mobject]]
    pulse_fraction: float
    pulse_scale: float
    readout: Component | None
    readout_text: Callable[[float], str] | None
    readout_place: Callable[[], None] | None
    fraction: float = 0.0

    def value_at(self, fraction: float) -> float:
        return self.start_value + (self.end_value - self.start_value) * self.easing(fraction)

    def apply(self, fraction: float) -> None:
        fraction = min(1.0, max(0.0, fraction))
        value = self.value_at(fraction)
        for warning in self.component.set_parameters(**{self.parameter: value}):
            if warning not in self.scene.render_warnings:
                self.scene.render_warnings.append(warning)
        if self.readout is not None and self.readout_text and self.readout_place:
            text = self.readout_text(value)
            inner = self.readout.group[0]
            inner.become(Text(text, **self.scene.tokens.text_kwargs(*self.scene.readout_face)))
            self.readout_place()
            self.readout.text = text
        if self.emphasized:
            progress = fraction / self.pulse_fraction if self.pulse_fraction > 0 else 1.0
            scale = 1.0 + (self.pulse_scale - 1.0) * math.sin(math.pi * progress) if 0.0 < progress < 1.0 else 1.0
            for part, base in self.emphasized:
                part.become(base)
                if scale != 1.0:
                    part.scale(scale)


class ParameterSweep(Animation):
    """Plays a segment [f0, f1] of a sweep's window; the rate profile lives in the sweep, so split segments
    continue the same curve. In fast-forward mode Manim evaluates alpha = 1 once, which lands on f1."""

    def __init__(self, sweep: Sweep, f0: float, f1: float) -> None:
        super().__init__(sweep.component.group, rate_func=linear)
        self.sweep, self.f0, self.f1 = sweep, f0, f1

    def interpolate_mobject(self, alpha: float) -> None:
        alpha = self.rate_func(alpha)
        self.sweep.apply(self.f0 + (self.f1 - self.f0) * alpha)


class SnapshotScene(Scene):
    """Base class for generated scenes.

    The scene keeps a registry of storyboard objects (for layout reports), opens one Manim
    section per storyboard scene, and exposes `wait_until` so generated code reaches each
    checkpoint at its requested time. The clock is Manim's own `renderer.time`, which advances
    in fast-forward mode as well.
    """

    def __init__(self, **kwargs: Any) -> None:
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
        self._readout_face: tuple[Any, Any] = (None, None)

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

    # --- storyboard structure -----------------------------------------------------------------
    def begin_scene(self, scene_id: str, start_seconds: float | None = None) -> None:
        self.scene_id = scene_id
        self.scene_objects = []
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

    def reveal(self, component: Component, run_time: float | None = None) -> None:
        duration = run_time if run_time is not None else self.tokens.t.motion.reveal_seconds
        self.play_frames(max(1, self.frames(duration)), component.reveal_animation())
        component.visible = True

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

    # --- parameter sweeps ---------------------------------------------------------------------
    @property
    def readout_face(self) -> tuple[Any, Any]:
        """Typeface and colour of the current sweep's readout (set by `begin_vary`)."""
        return self._readout_face

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
    ) -> Sweep:
        """Start a `vary_parameter` action: set up the readout and the emphasized glyphs, draw the initial state.

        The sweep's time axis is the storyboard window [at_seconds, at_seconds + duration_seconds], so
        `vary_until(end)` always completes it even when the clock reached the start late.
        """
        if not isinstance(component, FunctionPlotComponent):
            raise TypeError(f"action '{action_id}': '{component.object_id}' is a {component.kind}, not a function_plot")
        if parameter not in component.parameters:
            raise ValueError(
                f"action '{action_id}': '{component.object_id}' has no parameter '{parameter}' "
                f"(declared: {sorted(component.parameters)})"
            )
        tokens = self.tokens
        motion = tokens.t.motion
        emphasized: list[tuple[Mobject, Mobject]] = []
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
        readout: Component | None = None
        readout_text: Callable[[float], str] | None = None
        readout_place: Callable[[], None] | None = None
        if show_value:
            label = value_label if value_label is not None else pretty_symbol(parameter)
            annotation = tokens.typeface("annotation")
            self._readout_face = (annotation, color)

            def readout_text(value: float, label: str = label, units: str | None = units) -> str:
                return f"{label} = {value:.{value_decimals}f}" + (f" {units}" if units else "")

            text = Text(readout_text(component.parameters[parameter]), **tokens.text_kwargs(annotation, color))
            group = VGroup(text)
            reference = emphasize[0].group if emphasize else component.group

            def readout_place(
                group: VGroup = group, reference: Mobject = reference, beside: bool = bool(emphasize)
            ) -> None:
                if beside:
                    group.next_to(reference, DOWN, buff=tokens.baseline, aligned_edge=LEFT)
                else:
                    group.next_to(reference, UP, buff=tokens.baseline, aligned_edge=LEFT)

            readout_place()
            readout = Component(
                action_id,
                "value_readout",
                group,
                text=text.text,
                font_px=tokens.smallest_text_px("annotation"),
                text_like=True,
                visible=True,
            )
            self.register(readout)
            self.add(group)
        pulse_seconds = min(motion.emphasis_seconds, duration_seconds)
        sweep = Sweep(
            scene=self,
            action_id=action_id,
            component=component,
            parameter=parameter,
            start_value=component.parameters[parameter],
            end_value=float(to),
            at_seconds=at_seconds,
            duration_seconds=duration_seconds,
            easing=EASINGS[easing or motion.easing],
            emphasized=emphasized,
            pulse_fraction=pulse_seconds / duration_seconds,
            pulse_scale=motion.emphasis_scale,
            readout=readout,
            readout_text=readout_text,
            readout_place=readout_place,
        )
        sweep.apply(0.0)
        return sweep

    def vary_until(self, sweep: Sweep, seconds: float) -> None:
        """Play the sweep up to the storyboard time `seconds` (its end at the latest), frame-exact."""
        target = min(1.0, max(sweep.fraction, (seconds - sweep.at_seconds) / sweep.duration_seconds))
        frames = self.frames(seconds - self.clock)
        if frames >= 1:
            self.play_frames(frames, ParameterSweep(sweep, sweep.fraction, target))
        else:
            if seconds < self.clock - self.frame_seconds:
                self.timing_warnings.append(
                    f"action '{sweep.action_id}' should reach {seconds:g}s but the clock is already {self.clock:.3f}s"
                )
            sweep.apply(target)
        sweep.fraction = target

    def narrate(self, text: str) -> None:
        plain = re.sub(r"\s+", " ", _MARKS.sub(" ", text)).strip()
        words = len(plain.split())
        duration = words / self.tokens.t.motion.narration_words_per_minute * 60.0
        self.narration_log.append({"time": self.clock, "scene": self.scene_id, "text": plain, "seconds": duration})
        with contextlib.suppress(Exception):  # subcaptions matter only in video mode
            self.add_subcaption(plain, duration=max(duration, self.frame_seconds))

    def finish(self, total_seconds: float) -> None:
        self.wait_until(total_seconds)
