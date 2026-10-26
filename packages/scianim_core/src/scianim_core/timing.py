"""Frame accounting shared by the control plane and the render bridge (spec section 8.4).

Rounding policy: a storyboard time maps to the nearest frame at the output fps; every play and wait
in generated code lasts a whole number of frames; scene boundaries therefore land within half a frame
of the storyboard and the total frame count of a video equals `round(duration * fps)`.
"""

from __future__ import annotations

from pydantic import Field

from scianim_core.common import Slug, StrictModel


def frames_for(seconds: float, fps: float) -> int:
    """Whole frames closest to a duration (never negative)."""
    return max(0, round(seconds * fps))


class SceneTiming(StrictModel):
    scene_id: Slug
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    expected_frames: int = Field(ge=0)
    actual_frames: int | None = None
    """Frames in the section video, None when the section was not saved."""
    delta_frames: int | None = None

    @property
    def expected_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class TimingReport(StrictModel):
    fps: float = Field(gt=0)
    tolerance_frames: int = Field(default=1, ge=0)
    """Allowed difference per scene and in total: a boundary that falls between frames snaps to one."""
    expected_total_frames: int = Field(ge=0)
    actual_total_frames: int | None = None
    actual_duration_seconds: float | None = None
    scenes: list[SceneTiming] = []
    notes: list[str] = []

    @property
    def within_tolerance(self) -> bool:
        if self.actual_total_frames is None:
            return False
        if abs(self.actual_total_frames - self.expected_total_frames) > self.tolerance_frames:
            return False
        return all(s.delta_frames is None or abs(s.delta_frames) <= self.tolerance_frames for s in self.scenes)

    def problems(self) -> list[str]:
        out: list[str] = []
        if self.actual_total_frames is None:
            out.append("the video could not be probed")
        elif abs(self.actual_total_frames - self.expected_total_frames) > self.tolerance_frames:
            out.append(
                f"video has {self.actual_total_frames} frames, storyboard needs {self.expected_total_frames} "
                f"(tolerance {self.tolerance_frames})"
            )
        for scene in self.scenes:
            if scene.delta_frames is not None and abs(scene.delta_frames) > self.tolerance_frames:
                out.append(
                    f"scene '{scene.scene_id}' lasts {scene.actual_frames} frames, storyboard says "
                    f"{scene.expected_frames} ({scene.delta_frames:+d})"
                )
        return out


def verify_timing(
    scenes: list[tuple[str, float, float]],
    sections: list[tuple[str, int]],
    total_frames: int | None,
    fps: float,
    duration_seconds: float,
    tolerance_frames: int = 1,
) -> TimingReport:
    """Compare section frame counts and the total with the storyboard; sections are matched by scene id."""
    counts: dict[str, int] = {}
    for name, frames in sections:
        counts[name] = counts.get(name, 0) + frames
    timings: list[SceneTiming] = []
    for scene_id, start, end in scenes:
        expected = frames_for(end, fps) - frames_for(start, fps)
        actual = counts.get(scene_id)
        timings.append(
            SceneTiming(
                scene_id=scene_id,
                start_seconds=start,
                end_seconds=end,
                expected_frames=expected,
                actual_frames=actual,
                delta_frames=None if actual is None else actual - expected,
            )
        )
    notes: list[str] = []
    unmatched = [name for name, _ in sections if name not in {s for s, _, _ in scenes} and name != "autocreated"]
    if unmatched:
        notes.append(f"sections without a storyboard scene: {unmatched}")
    return TimingReport(
        fps=fps,
        tolerance_frames=tolerance_frames,
        expected_total_frames=frames_for(duration_seconds, fps),
        actual_total_frames=total_frames,
        actual_duration_seconds=None if total_frames is None else total_frames / fps,
        scenes=timings,
        notes=notes,
    )


__all__ = ["SceneTiming", "TimingReport", "frames_for", "verify_timing"]
