"""Scene durations proposed from narration (spec section 8.4): a proposal and a conflict report, never a silent edit."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

from scianim.config.loader import SpecError
from scianim_core import AnimationSpec, Storyboard
from scianim_core.timing import frames_for

PADDING_FACTOR = 1.25
"""Speaking time times this is the proposed scene duration: room for reveals and a pause."""
MIN_SCENE_SECONDS = 3.0


@dataclass
class SceneProposal:
    scene_id: str
    current_start: float
    current_end: float
    narration_seconds: float | None
    proposed_start: float
    proposed_end: float
    conflicts: list[str] = field(default_factory=list)

    @property
    def current_duration(self) -> float:
        return self.current_end - self.current_start

    @property
    def proposed_duration(self) -> float:
        return self.proposed_end - self.proposed_start


@dataclass
class TimingProposal:
    words_per_minute: float
    padding_factor: float
    fps: float
    output_duration: float
    scenes: list[SceneProposal]
    conflicts: list[str] = field(default_factory=list)

    @property
    def proposed_end(self) -> float:
        return self.scenes[-1].proposed_end if self.scenes else 0.0

    @property
    def ok(self) -> bool:
        return not self.conflicts and not any(s.conflicts for s in self.scenes)


def _snap(seconds: float, fps: float) -> float:
    return frames_for(seconds, fps) / fps


def propose_timing(
    animation: AnimationSpec,
    storyboard: Storyboard,
    words_per_minute: float,
    padding_factor: float = PADDING_FACTOR,
    min_scene_seconds: float = MIN_SCENE_SECONDS,
) -> TimingProposal:
    """Durations from narration at the style's speaking rate; scenes without narration keep their length.

    The proposal keeps scene order and the first scene's start. Conflicts are reported when the
    proposal overruns the output duration, moves a hard milestone out of its scene, or leaves a
    snapshot, a timed reveal or an action outside its scene.
    """
    fps = animation.output.fps
    proposals: list[SceneProposal] = []
    cursor = storyboard.scenes[0].start_seconds
    for scene in storyboard.scenes:
        narration_seconds = scene.narration.estimated_seconds(words_per_minute) if scene.narration else None
        if narration_seconds is None:
            duration = scene.duration_seconds
        else:
            duration = max(min_scene_seconds, narration_seconds * padding_factor)
        duration = _snap(duration, fps)
        proposal = SceneProposal(
            scene_id=scene.id,
            current_start=scene.start_seconds,
            current_end=scene.end_seconds,
            narration_seconds=narration_seconds,
            proposed_start=cursor,
            proposed_end=_snap(cursor + duration, fps),
        )
        for snapshot in scene.snapshots:
            if not proposal.proposed_start <= snapshot.at_seconds <= proposal.proposed_end:
                proposal.conflicts.append(
                    f"snapshot '{snapshot.id}' at {snapshot.at_seconds:g}s falls outside the proposed "
                    f"{proposal.proposed_start:g}-{proposal.proposed_end:g}s"
                )
        for obj in scene.objects:
            if obj.reveal_at_seconds is not None and not (
                proposal.proposed_start <= obj.reveal_at_seconds <= proposal.proposed_end
            ):
                proposal.conflicts.append(
                    f"object '{obj.id}' revealed at {obj.reveal_at_seconds:g}s falls outside the proposed "
                    f"{proposal.proposed_start:g}-{proposal.proposed_end:g}s"
                )
        for action in scene.actions:
            if not (proposal.proposed_start <= action.at_seconds and action.end_seconds <= proposal.proposed_end):
                proposal.conflicts.append(
                    f"action '{action.id}' ({action.at_seconds:g}-{action.end_seconds:g}s) falls outside the "
                    f"proposed {proposal.proposed_start:g}-{proposal.proposed_end:g}s"
                )
        proposals.append(proposal)
        cursor = proposal.proposed_end
    result = TimingProposal(words_per_minute, padding_factor, fps, animation.output.duration_seconds, proposals)
    if result.proposed_end > animation.output.duration_seconds + 1e-9:
        result.conflicts.append(
            f"the proposal ends at {result.proposed_end:g}s but the output lasts {animation.output.duration_seconds:g}s; "
            "shorten narration or extend the output"
        )
    for milestone in animation.hard_milestones():
        holder = next((s for s in storyboard.scenes if s.start_seconds <= milestone.at_seconds <= s.end_seconds), None)
        if holder is None:
            result.conflicts.append(
                f"hard milestone '{milestone.id}' at {milestone.at_seconds:g}s is in no scene today"
            )
            continue
        proposed = next(p for p in proposals if p.scene_id == holder.id)
        low = proposed.proposed_start - milestone.tolerance_seconds
        high = proposed.proposed_end + milestone.tolerance_seconds
        if not low <= milestone.at_seconds <= high:
            result.conflicts.append(
                f"hard milestone '{milestone.id}' at {milestone.at_seconds:g}s would leave scene '{holder.id}' "
                f"(proposed {proposed.proposed_start:g}-{proposed.proposed_end:g}s)"
            )
    return result


def write_proposed_storyboard(source: Path, proposal: TimingProposal, target: Path) -> Path:
    """Copy the storyboard with the proposed scene boundaries; everything else is preserved verbatim.

    A proposal with conflicts would not validate (snapshots or reveals outside their scenes), so it is
    refused: resolve the conflicts in the storyboard first.
    """
    if not proposal.ok:
        conflicts = [*proposal.conflicts, *(c for s in proposal.scenes for c in s.conflicts)]
        raise SpecError(source, "the proposal has conflicts and would not validate:\n  - " + "\n  - ".join(conflicts))
    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(source.read_text(encoding="utf-8"))
    by_id = {p.scene_id: p for p in proposal.scenes}
    for scene in data["scenes"]:
        p = by_id[scene["id"]]
        scene["start_seconds"] = _number(p.proposed_start)
        scene["end_seconds"] = _number(p.proposed_end)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)
    return target


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 4)


__all__ = [
    "MIN_SCENE_SECONDS",
    "PADDING_FACTOR",
    "SceneProposal",
    "TimingProposal",
    "propose_timing",
    "write_proposed_storyboard",
]
