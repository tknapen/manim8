"""`checkpoint()`: capture a named frame from the real animation flow (spec 8.2, ADR-002)."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from scianim_bridge.layout import layout_report
from scianim_core import CheckpointRecord

if TYPE_CHECKING:
    from scianim_bridge.scene import SnapshotScene


def checkpoint(scene: SnapshotScene, snapshot_id: str, expected_time: float | None = None) -> None:
    """Mark a named visual state. In snapshot mode this writes a PNG and a checkpoint record."""
    renderer = scene.renderer
    entry = {
        "snapshot_id": snapshot_id,
        "animation_index": int(renderer.num_plays),
        "time": scene.clock,
    }
    scene.checkpoint_log.append(entry)
    ctx = scene.ctx
    if ctx is None or ctx.mode != "snapshot":
        return
    if ctx.job.snapshot_ids and snapshot_id not in ctx.job.snapshot_ids:
        return
    if snapshot_id in ctx.captured:
        raise RuntimeError(f"checkpoint '{snapshot_id}' reached twice")

    renderer.update_frame(scene)
    frame = np.asarray(renderer.get_frame())
    image = Image.fromarray(frame)
    png_path = ctx.output_dir / f"{snapshot_id}.png"
    image.save(png_path, format="PNG")
    digest = hashlib.sha256(png_path.read_bytes()).hexdigest()

    items, warnings = layout_report(scene)
    time_based = sorted(
        {type(m).__name__ for mob in scene.mobjects for m in mob.get_family() if m.has_time_based_updater()}
    )
    target = ctx.job.snapshots.get(snapshot_id)
    scene_id = scene.scene_id or (target.scene_id if target else "unknown")
    expected = expected_time if expected_time is not None else (target.expected_time_seconds if target else scene.clock)
    record = CheckpointRecord(
        snapshot_id=snapshot_id,
        scene_id=scene_id,
        kind="manim_checkpoint",
        png=(ctx.job.output_dir.rstrip("/") + "/" + png_path.name),
        width_px=int(frame.shape[1]),
        height_px=int(frame.shape[0]),
        sha256=digest,
        animation_index=int(renderer.num_plays),
        expected_time_seconds=float(expected),
        renderer_time_seconds=scene.clock,
        fidelity="approximate" if time_based else "exact",
        fidelity_note=(
            f"time-based updaters present on {time_based}; fast-forward advances each play in one step. "
            "Confirm with a sampled video frame."
            if time_based
            else None
        ),
        layout=items,
        warnings=warnings,
    )
    ctx.records.append(record)
    ctx.captured.add(snapshot_id)
    print(
        json.dumps(
            {
                "event": "checkpoint",
                "snapshot_id": snapshot_id,
                "png": record.png,
                "animation_index": record.animation_index,
                "time": scene.clock,
                "warnings": len(warnings),
            }
        ),
        file=sys.stdout,
        flush=True,
    )
