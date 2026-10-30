"""Worker protocol: what the control plane sends to the bridge and what comes back.

Files cross the process boundary, never Python objects (spec section 10.1, ADR-001).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from scianim_core.animation import Equation, OutputSpec
from scianim_core.common import HexColor, RelPath, SchemaVersion, Sha256, Slug, StrictModel
from scianim_core.style import EquationEngine, ResolvedStyle
from scianim_core.timing import TimingReport

Operation = Literal["render_snapshots", "render_video", "plan_video", "render_video_part", "merge_video", "probe"]
"""`plan_video`, `render_video_part` and `merge_video` are the three stages of a parallel video render (ADR-029);
the control plane derives them from one `render_video` job with `workers` above one."""
QualityProfile = Literal["storyboard", "snapshot", "draft", "final"]
PreviewKind = Literal["manim_checkpoint", "sampled_video_frame", "storyboard_schematic"]
Fidelity = Literal["exact", "approximate"]
WarningCode = Literal["outside_safe_zone", "text_too_small", "overlap"]


class ManimSettings(StrictModel):
    """The subset of Manim configuration the worker applies. All of it enters the cache key."""

    renderer: Literal["cairo", "opengl"] = "cairo"
    pixel_width: int = Field(gt=0)
    pixel_height: int = Field(gt=0)
    frame_rate: float = Field(gt=0)
    background_color: HexColor
    media_dir: RelPath
    equation_engine: EquationEngine = "typst"
    seed: int = 0
    disable_caching: bool = False
    pixel_format: str = "yuv420p"
    video_codec: str = "libx264"
    save_sections: bool = False


class SnapshotTarget(StrictModel):
    scene_id: Slug
    expected_time_seconds: float = Field(ge=0)
    description: str


class SceneTarget(StrictModel):
    """A storyboard scene's interval, so a video job can verify its section against the storyboard."""

    scene_id: Slug
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class PlayRecord(StrictModel):
    """One `play` of the generated scene, as the planning pass saw it in fast-forward."""

    index: int = Field(ge=0)
    """Manim's animation number: `renderer.num_plays` when the play began."""
    scene_id: Slug | None = None
    """The storyboard scene (one Manim section each) the play belongs to."""
    start_seconds: float = Field(ge=0)
    frames: int = Field(ge=1)
    static: bool = False
    """A wait with nothing moving: Manim draws one frame and repeats it, so it costs little."""
    drawn: bool = False
    """Manim drew the play's frames in the worker that reported it: not fast-forwarded, not served from its
    per-play cache. Only then is `seconds` the cost of drawing."""
    seconds: float = Field(default=0, ge=0)
    """Wall time the play took in the worker that reported it. A later parallel render of the same clip balances
    its parts by the times of the plays that were drawn."""


class ReachedCheckpoint(StrictModel):
    """A checkpoint the scene reached, with the clock and the animation number at that moment."""

    snapshot_id: Slug
    animation_index: int = Field(ge=0)
    time_seconds: float = Field(ge=0)


class PartRange(StrictModel):
    """The plays one worker of a parallel render draws; it fast-forwards through all the others."""

    index: int = Field(ge=0)
    count: int = Field(ge=1)
    first_play: int = Field(ge=0)
    last_play: int = Field(ge=0)
    """Inclusive."""
    frames: int = Field(ge=0)
    """Planned frames in the range."""


class SegmentRecord(StrictModel):
    """One play's encoded video segment, as a part worker left it in its media directory."""

    play_index: int = Field(ge=0)
    scene_id: Slug | None = None
    path: RelPath
    frames: int = Field(ge=1)


class MergeInputs(StrictModel):
    """What `merge_video` joins: every play's segment in order, plus the plan's checkpoints and subtitles."""

    plays: list[PlayRecord]
    segments: list[SegmentRecord]
    checkpoints: list[ReachedCheckpoint] = []
    subtitles: RelPath | None = None
    parts: list[PartRange] = []


class RenderJob(StrictModel):
    schema_version: SchemaVersion = "1.0"
    job_id: str = Field(min_length=1)
    project_id: Slug
    revision_id: str = Field(min_length=1)
    family_id: Slug
    operation: Operation
    quality_profile: QualityProfile
    scene_module: RelPath
    scene_class: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    snapshot_ids: list[Slug] = []
    """Subset to capture; empty means every checkpoint the scene reaches."""
    snapshots: dict[Slug, SnapshotTarget] = {}
    scenes: list[SceneTarget] = []
    """Scene intervals in storyboard order (video jobs)."""
    samples: dict[Slug, float] = {}
    """Extra video frames to extract, by id and time in seconds (video jobs)."""
    output: OutputSpec
    resolved_style: ResolvedStyle
    data_files: dict[Slug, RelPath] = {}
    equations: dict[Slug, Equation] = {}
    citations: dict[Slug, str] = {}
    """Citation text per source id (the source's `citation`, else its path), for captions that cite."""
    manim: ManimSettings
    output_dir: RelPath
    cache_key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    workers: int = Field(default=1, ge=1)
    """Worker processes for a video. Above one, the plays are split into ranges rendered at the same time and
    the segments are joined without re-encoding; the result is the same movie (ADR-029)."""
    part: PartRange | None = None
    """`render_video_part` only: the range this worker draws."""
    merge: MergeInputs | None = None
    """`merge_video` only: the segments to join."""

    @model_validator(mode="after")
    def _stage_fields_match_operation(self) -> RenderJob:
        if (self.operation == "render_video_part") != (self.part is not None):
            raise ValueError("`part` belongs to operation render_video_part, and only there")
        if (self.operation == "merge_video") != (self.merge is not None):
            raise ValueError("`merge` belongs to operation merge_video, and only there")
        return self


class BBox(StrictModel):
    """Normalized frame coordinates, origin top-left. Values may leave [0, 1] when off-frame."""

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)

    @property
    def x2(self) -> float:
        return self.x + self.width

    @property
    def y2(self) -> float:
        return self.y + self.height

    def intersects(self, other: BBox) -> bool:
        return self.x < other.x2 and other.x < self.x2 and self.y < other.y2 and other.y < self.y2


class LayoutItem(StrictModel):
    object_id: Slug
    kind: str
    bbox: BBox
    text: str | None = None
    text_height_px: float | None = None


class LayoutWarning(StrictModel):
    code: WarningCode
    object_ids: list[Slug]
    detail: str


class CheckpointRecord(StrictModel):
    snapshot_id: Slug
    scene_id: Slug
    kind: PreviewKind
    png: RelPath
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    sha256: Sha256
    animation_index: int = Field(ge=0)
    expected_time_seconds: float = Field(ge=0)
    renderer_time_seconds: float | None = None
    fidelity: Fidelity = "exact"
    fidelity_note: str | None = None
    layout: list[LayoutItem] = []
    warnings: list[LayoutWarning] = []


class SectionRecord(StrictModel):
    name: str
    type: str
    video: str | None = None
    metadata: dict[str, Any] = {}


class VideoRecord(StrictModel):
    path: RelPath
    width_px: int
    height_px: int
    fps: float
    duration_seconds: float
    frame_count: int | None = None
    codec: str | None = None
    sha256: Sha256


class PartReport(StrictModel):
    """One part of a parallel render: its range and how long its worker took."""

    part: PartRange
    status: Literal["succeeded", "failed", "canceled"]
    elapsed_seconds: float = Field(ge=0)


class ToolVersions(StrictModel):
    python: str
    platform: str
    manim: str | None = None
    scianim_bridge: str | None = None
    scianim_core: str | None = None
    typst: str | None = None
    av: str | None = None


class WorkerResult(StrictModel):
    schema_version: SchemaVersion = "1.0"
    job_id: str
    status: Literal["succeeded", "failed", "canceled"]
    checkpoints: list[CheckpointRecord] = []
    videos: list[VideoRecord] = []
    sections: list[SectionRecord] = []
    subtitles: RelPath | None = None
    timing: TimingReport | None = None
    """Per-scene and total frame counts of a video against the storyboard."""
    plays: list[PlayRecord] = []
    """Every play of the scene (`plan_video`; a part lists the plays up to the end of its range; a merge
    repeats the plan)."""
    reached: list[ReachedCheckpoint] = []
    """Checkpoints reached, with their clock (`plan_video`)."""
    segments: list[SegmentRecord] = []
    """Encoded segments, one per play drawn (`render_video_part`; a merge lists what it joined)."""
    parts: list[PartReport] = []
    """How each part of a parallel render went (filled in by the control plane on the merged result)."""
    tool_versions: ToolVersions | None = None
    elapsed_seconds: float = Field(ge=0)
    errors: list[str] = []
    warnings: list[str] = []


class InputHashes(StrictModel):
    animation_spec: Sha256
    storyboard: Sha256
    scene_code: Sha256
    resolved_style: str
    data_files: dict[Slug, Sha256] = {}
    custom_code: dict[str, Sha256] = {}
    lockfile: Sha256 | None = None


class ArtifactManifest(StrictModel):
    """`manifest.json`: one per job, written by the control plane after the worker returns."""

    schema_version: SchemaVersion = "1.0"
    created_at: str
    job: RenderJob
    result: WorkerResult
    inputs: InputHashes
    cache_hit: bool = False
