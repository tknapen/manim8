"""Feedback records: typed review annotations stored as `feedback/*.yaml` (spec section 9.2).

A record binds a comment or a review status to a project revision, a scene, a snapshot and
optionally an object from the layout report. Regions are normalized to [0, 1] so they do not depend
on preview pixel dimensions. A status record names the image hash that was actually displayed;
`approved` is refused on the mutable working copy (spec section 9.3: never approve a mutable path).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from scianim_core.common import SchemaVersion, Sha256, Slug, StrictModel

FeedbackKind = Literal["region_comment", "object_comment", "general_comment", "status"]
Severity = Literal["visual", "scientific", "timing", "other"]
ReviewStatus = Literal["approved", "needs_revision", "scientific_concern"]
FEEDBACK_ID_PATTERN = r"^fb_\d{8}T\d{6}_[0-9a-f]{6}$"
REVISION_REF_PATTERN = r"^(working|rev_\d{4})$"
WORKING = "working"


class Region(StrictModel):
    """A rectangle in normalized image coordinates, origin top-left."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _inside_the_frame(self) -> Region:
        if self.x + self.width > 1 + 1e-6 or self.y + self.height > 1 + 1e-6:
            raise ValueError("region extends beyond the image (x + width or y + height > 1)")
        return self


class FeedbackRecord(StrictModel):
    schema_version: SchemaVersion = "1.0"
    id: str = Field(pattern=FEEDBACK_ID_PATTERN)
    created_at: str
    author: str | None = None
    project_id: Slug
    revision_id: str = Field(pattern=REVISION_REF_PATTERN)
    """`working` or an immutable `rev_NNNN`."""
    job_id: str | None = None
    """The render job whose image the reviewer looked at, when known."""
    scene_id: Slug | None = None
    snapshot_id: Slug | None = None
    object_id: Slug | None = None
    """Resolved from the layout report when the reviewer clicked an object; a region is stored as well."""
    kind: FeedbackKind
    region: Region | None = None
    text: str = ""
    severity: Severity = "visual"
    status: ReviewStatus | None = None
    image_sha256: Sha256 | None = None
    """Hash of the checkpoint PNG that was displayed: what a status actually refers to."""
    image_width_px: int | None = Field(default=None, gt=0)
    image_height_px: int | None = Field(default=None, gt=0)
    time_seconds: float | None = Field(default=None, ge=0)
    """For comments on a video frame rather than a named checkpoint."""

    @model_validator(mode="after")
    def _shape_by_kind(self) -> FeedbackRecord:
        if self.kind == "status":
            if self.status is None:
                raise ValueError("a status record needs `status`")
            if self.snapshot_id is None or self.image_sha256 is None:
                raise ValueError("a status record needs `snapshot_id` and the `image_sha256` that was displayed")
            if self.status == "approved" and self.revision_id == WORKING:
                raise ValueError("approval needs an immutable revision (rev_NNNN); the working copy may change")
            return self
        if self.status is not None:
            raise ValueError("only `kind: status` records carry `status`")
        if not self.text.strip():
            raise ValueError("a comment needs `text`")
        if self.kind == "region_comment" and self.region is None:
            raise ValueError("a region_comment needs `region`")
        if self.kind == "object_comment" and (self.object_id is None or self.region is None):
            raise ValueError("an object_comment needs `object_id` and the object's `region`")
        if self.kind in ("region_comment", "object_comment") and self.snapshot_id is None:
            raise ValueError(f"a {self.kind} needs `snapshot_id`")
        return self


__all__ = [
    "FEEDBACK_ID_PATTERN",
    "REVISION_REF_PATTERN",
    "WORKING",
    "FeedbackKind",
    "FeedbackRecord",
    "Region",
    "ReviewStatus",
    "Severity",
]
