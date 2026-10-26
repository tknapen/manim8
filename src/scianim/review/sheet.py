"""Static HTML review sheet: checkpoints with storyboard text, narration and layout warnings."""

from __future__ import annotations

import html
from pathlib import Path

from scianim_core import ArtifactManifest, Storyboard

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
:root {{ --bg: #ffffff; --fg: #1b1f23; --muted: #5c6670; --line: #e1e4e8; --warn: #9a3412; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #101820; --fg: #f2f4f5; --muted: #b4c0c9; --line: #2a3640; --warn: #f4a261; }} }}
body {{ margin: 0; padding: 16px; background: var(--bg); color: var(--fg); font: 15px/1.45 system-ui, sans-serif; }}
header {{ margin-bottom: 20px; }} h1 {{ font-size: 1.4rem; margin: 0 0 4px; }} .meta {{ color: var(--muted); font-size: .9rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }}
.card {{ border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
.card img {{ width: 100%; display: block; background: #000; }}
.card .body {{ padding: 12px 14px; }} .card h2 {{ font-size: 1rem; margin: 0 0 4px; }}
.kind {{ display: inline-block; font-size: .75rem; padding: 1px 6px; border: 1px solid var(--line); border-radius: 4px; color: var(--muted); }}
.warn {{ color: var(--warn); font-size: .9rem; margin: 6px 0 0; }} .narration {{ color: var(--muted); font-style: italic; margin: 6px 0 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: .8rem; margin-top: 8px; }} td, th {{ text-align: left; padding: 2px 4px; border-top: 1px solid var(--line); }}
</style></head><body>
<header><h1>{title}</h1><div class="meta">{meta}</div></header>
{video}
<section class="grid">{cards}</section>
</body></html>
"""

CARD = """<article class="card">
<img src="{src}" alt="{alt}" width="{w}" height="{h}">
<div class="body"><h2>{snapshot_id} <span class="kind">{kind}{fidelity}</span></h2>
<div class="meta">scene {scene_id} | requested {t:g}s | animation #{anim}</div>
<p>{description}</p>{narration}{warnings}{layout}</div></article>"""


def render_sheet(manifest: ArtifactManifest, storyboard: Storyboard, sheet_dir: Path) -> str:
    job = manifest.job
    cards = []
    scenes = {s.id: s for s in storyboard.scenes}
    for rec in manifest.result.checkpoints:
        src = Path(rec.png).name
        scene = scenes.get(rec.scene_id)
        narration = (
            f'<p class="narration">{html.escape(scene.narration.plain_text)}</p>' if scene and scene.narration else ""
        )
        warnings = "".join(f'<p class="warn">{html.escape(w.code)}: {html.escape(w.detail)}</p>' for w in rec.warnings)
        rows = "".join(
            f"<tr><td>{html.escape(i.object_id)}</td><td>{html.escape(i.kind)}</td>"
            f"<td>x {i.bbox.x:.2f} y {i.bbox.y:.2f} w {i.bbox.width:.2f} h {i.bbox.height:.2f}</td>"
            f"<td>{'' if i.text_height_px is None else f'{i.text_height_px:.0f}px'}</td></tr>"
            for i in rec.layout
        )
        layout = (
            f"<table><tr><th>object</th><th>kind</th><th>bbox (normalized)</th><th>text</th></tr>{rows}</table>"
            if rows
            else ""
        )
        cards.append(
            CARD.format(
                src=html.escape(src),
                alt=html.escape(rec.description if hasattr(rec, "description") else rec.snapshot_id),
                w=rec.width_px,
                h=rec.height_px,
                snapshot_id=html.escape(rec.snapshot_id),
                kind=rec.kind,
                fidelity="" if rec.fidelity == "exact" else " | approximate",
                scene_id=html.escape(rec.scene_id),
                t=rec.expected_time_seconds,
                anim=rec.animation_index,
                description=html.escape(
                    job.snapshots[rec.snapshot_id].description if rec.snapshot_id in job.snapshots else ""
                ),
                narration=narration,
                warnings=warnings,
                layout=layout,
            )
        )
    meta = (
        f"job {html.escape(job.job_id)} | revision {html.escape(job.revision_id)} | style {html.escape(job.resolved_style.theme)}@{job.resolved_style.theme_version} "
        f"· {len(manifest.result.checkpoints)} checkpoints | cache {html.escape(job.cache_key[:19])}... | created {html.escape(manifest.created_at)}"
    )
    video = ""
    for record in manifest.result.videos:
        rows = "".join(
            f"<tr><td>{html.escape(s.name)}</td><td>{s.metadata.get('frames', '?')}</td>"
            f"<td>{float(s.metadata.get('duration_seconds', 0)):.3f}</td></tr>"
            for s in manifest.result.sections
        )
        timing = manifest.result.timing
        verdict = ""
        if timing is not None:
            verdict = (
                f'<p class="{"meta" if timing.within_tolerance else "warn"}">timing: {timing.actual_total_frames} of '
                f"{timing.expected_total_frames} frames; "
                f"{'matches the storyboard' if timing.within_tolerance else '; '.join(html.escape(p) for p in timing.problems())}</p>"
            )
        subtitles = (
            f'<p class="meta"><a href="{html.escape(Path(manifest.result.subtitles).name)}">subtitles (SRT)</a></p>'
            if manifest.result.subtitles
            else ""
        )
        video += (
            f'<section class="card" style="margin-bottom:20px"><video controls preload="metadata" src="{html.escape(Path(record.path).name)}" '
            f'width="{record.width_px}" height="{record.height_px}" style="width:100%;height:auto"></video>'
            f'<div class="body"><h2>{html.escape(job.quality_profile)} video <span class="kind">{record.width_px}x{record.height_px} · '
            f"{record.fps:g} fps · {record.frame_count} frames · {record.duration_seconds:.2f}s · {html.escape(record.codec or '')}</span></h2>"
            f"{verdict}{subtitles}"
            + (f"<table><tr><th>section</th><th>frames</th><th>seconds</th></tr>{rows}</table>" if rows else "")
            + "</div></section>"
        )
    return TEMPLATE.format(
        title=f"Review sheet: {html.escape(job.project_id)}", meta=meta, video=video, cards="\n".join(cards)
    )


def write_sheet(manifest: ArtifactManifest, storyboard: Storyboard, target: Path) -> Path:
    target.write_text(render_sheet(manifest, storyboard, target.parent), encoding="utf-8")
    return target
