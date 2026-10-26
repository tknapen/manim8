"""`SnapshotScene`: a Manim scene with a clock, registered objects and scene sections."""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING, Any

from manim import FadeOut, Scene, config

from scianim_bridge import context as _context
from scianim_bridge.tokens import Tokens
from scianim_core.timing import frames_for

if TYPE_CHECKING:
    from scianim_bridge.components.base import Component

_MARKS = re.compile(r'<mark\s+name="[A-Za-z0-9_]+"\s*/>')


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
        self._tokens: Tokens | None = None

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

    def narrate(self, text: str) -> None:
        plain = re.sub(r"\s+", " ", _MARKS.sub(" ", text)).strip()
        words = len(plain.split())
        duration = words / self.tokens.t.motion.narration_words_per_minute * 60.0
        self.narration_log.append({"time": self.clock, "scene": self.scene_id, "text": plain, "seconds": duration})
        with contextlib.suppress(Exception):  # subcaptions matter only in video mode
            self.add_subcaption(plain, duration=max(duration, self.frame_seconds))

    def finish(self, total_seconds: float) -> None:
        self.wait_until(total_seconds)
