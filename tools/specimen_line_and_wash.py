"""Compose the line-and-wash specimen (styles/default/0.3.0/specimen.{pdf,png}) from real renders.

The plate is not drawn by hand: every frame on it is a checkpoint PNG that the Manim bridge rendered
from one of the example clips, read from the newest successful snapshot job of each workspace project.
The palette strip, the type sample and the theme name come from the ``resolved_style`` block those
manifests carry, so the plate shows the tokens the renderer actually received, and the footnote lists
the font fallbacks the renderer reported. Run inside a family environment, which has the ``typst``
package:

    uv run --project workspace/families/computational_neuroscience python tools/specimen_line_and_wash.py

Options: ``--workspace DIR`` (default ``workspace``), ``--family ID`` (default
``computational_neuroscience``), ``--theme NAME@VERSION`` (default ``default@0.3.0``; manifests whose
resolved style does not carry that layer are refused) and ``--out DIR`` (default
``styles/default/0.3.0``).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

W = 320.0  # page width in mm; the height follows the content

# Two checkpoints per example, in reading order; a missing id falls back to the first checkpoints of the job.
FRAMES: list[tuple[str, list[str]]] = [
    ("gabor_filter", ["rotating", "smaller"]),
    ("prf_tuning", ["moving", "grown"]),
    ("divisive_normalization", ["excitation_visible", "pool_raised"]),
    ("orientation_tuning", ["circuit_shown", "model_complete"]),
]

PALETTE_ROLES = [
    "foreground",
    "secondary_text",
    "muted",
    "neutral",
    "primary_signal",
    "primary_signal_soft",
    "uncertainty",
    "selection",
    "emphasis",
    "comparison",
    "comparison_soft",
    "warning",
]


def newest_manifest(project_dir: Path, theme_layer: str) -> dict[str, Any]:
    """The newest succeeded snapshot manifest of the working copy whose style carries the theme layer."""
    candidates = sorted((project_dir / "renders" / "working").glob("job_*/manifest.json"), reverse=True)
    for path in candidates:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        job, result = manifest["job"], manifest["result"]
        if job.get("operation") != "render_snapshots" or result.get("status") != "succeeded":
            continue
        if theme_layer not in job["resolved_style"]["layers"]:
            continue
        manifest["_dir"] = path.parent
        return manifest
    raise SystemExit(
        f"{project_dir}: no succeeded snapshot job rendered with {theme_layer}; run `scianim snapshot` first"
    )


def pick_frames(manifest: dict[str, Any], wanted: list[str]) -> list[dict[str, Any]]:
    by_id = {c["snapshot_id"]: c for c in manifest["result"]["checkpoints"]}
    chosen = [by_id[i] for i in wanted if i in by_id]
    for record in manifest["result"]["checkpoints"]:
        if len(chosen) >= len(wanted):
            break
        if record not in chosen:
            chosen.append(record)
    return chosen


def typ_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace("#", "\\#").replace("@", "\\@").replace("_", "\\_").replace("*", "\\*")


def build(theme: str, frames: list[tuple[str, dict[str, Any], Path]], style: dict[str, Any], notes: list[str]) -> str:
    pal = style["tokens"]["palette"]
    typo = style["tokens"]["typography"]
    body_fonts = [typo["body"]["font_family"], *typo["body"]["font_fallbacks"]]
    math_fonts = [typo["equation"]["math_font"], *typo["equation"]["math_font_fallbacks"]]
    fonts_typ = ", ".join(f'"{f}"' for f in body_fonts if f != "sans-serif")
    math_typ = ", ".join(f'"{f}"' for f in math_fonts)
    ink, secondary, muted, neutral = pal["foreground"], pal["secondary_text"], pal["muted"], pal["neutral"]
    layers = ", ".join(style["layers"])
    overridden = sorted({layer for layer in style["provenance"].values() if layer != f"theme:{theme}"})
    override_note = (
        " Every token comes from this theme." if not overridden else f" Tokens also set by: {', '.join(overridden)}."
    )

    cols, gutter, left, top = 4, 6.0, 12.0, 28.0
    fw = (W - 2 * left - (cols - 1) * gutter) / cols
    fh = fw * 9 / 16
    row_h = fh + 12.0
    sy = top + 2 * row_h + 2.0  # palette strip
    height = sy + 13.0 + left

    out: list[str] = []
    out.append(f'#set page(width: {W}mm, height: {height:.3f}mm, margin: 0mm, fill: rgb("{pal["background"]}"))\n')
    out.append(f'#set text(font: ({fonts_typ}), fill: rgb("{ink}"), size: 7pt)\n')
    out.append(f"#show math.equation: set text(font: ({math_typ}))\n")
    out.append(
        f'#place(top + left, dx: 12mm, dy: 10mm, text(size: 15pt, weight: "bold")[{typ_text(theme)}] + text(size: 15pt)[  ·  line and wash])\n'
    )
    out.append(
        f'#place(top + left, dx: 12mm, dy: 18.5mm, text(size: 6.2pt, fill: rgb("{secondary}"))'
        "[Eight checkpoints rendered by the Manim bridge from the example clips, unretouched, at the snapshot profile. "
        f"Resolved layers: {typ_text(layers)}; style hash {typ_text(style['hash'][:19])}.{typ_text(override_note)}])\n"
    )

    # 4 x 2 grid of frames with captions.
    for i, (project, record, png) in enumerate(frames):
        r, c = divmod(i, cols)
        x, y = left + c * (fw + gutter), top + r * row_h
        out.append(
            f"#place(top + left, dx: {x:.3f}mm, dy: {y:.3f}mm, rect(width: {fw:.3f}mm, height: {fh:.3f}mm, "
            f'stroke: (paint: rgb("{neutral}"), thickness: 0.15mm), inset: 0mm, image("{png.name}", width: {fw:.3f}mm)))\n'
        )
        caption = (
            f"{project} · {record['snapshot_id']} · t = {record['expected_time_seconds']:g} s · {record['fidelity']}"
        )
        out.append(
            f'#place(top + left, dx: {x:.3f}mm, dy: {y + fh + 2.2:.3f}mm, text(size: 5.6pt, fill: rgb("{secondary}"))[{typ_text(caption)}])\n'
        )
        if record.get("layout"):
            ids = ", ".join(entry["object_id"] for entry in record["layout"])
            out.append(
                f'#place(top + left, dx: {x:.3f}mm, dy: {y + fh + 5.6:.3f}mm, text(size: 4.8pt, fill: rgb("{muted}"))[{typ_text(ids)}])\n'
            )

    # Palette strip and type sample.
    sw = 14.0
    for i, role in enumerate(PALETTE_ROLES):
        paint = pal[role]
        x = left + i * (sw + 1.6)
        out.append(
            f'#place(top + left, dx: {x:.3f}mm, dy: {sy:.3f}mm, rect(width: {sw:.3f}mm, height: 6.4mm, fill: rgb("{paint}"), '
            f'stroke: (paint: rgb("{neutral}"), thickness: 0.15mm)))\n'
        )
        out.append(
            f'#place(top + left, dx: {x:.3f}mm, dy: {sy + 7.4:.3f}mm, text(size: 4.6pt, fill: rgb("{secondary}"))[{typ_text(role.replace("_", " "))}])\n'
        )
        out.append(
            f'#place(top + left, dx: {x:.3f}mm, dy: {sy + 10.2:.3f}mm, text(size: 4.2pt, fill: rgb("{muted}"))[{typ_text(paint.upper())}])\n'
        )
    tx = left + len(PALETTE_ROLES) * (sw + 1.6) + 4.0
    out.append(f"#place(top + left, dx: {tx:.3f}mm, dy: {sy - 1.6:.3f}mm, text(size: 20pt)[Aa])\n")
    out.append(
        f"#place(top + left, dx: {tx + 13.0:.3f}mm, dy: {sy - 1.6:.3f}mm, text(size: 20pt)[$ integral sigma partial infinity $])\n"
    )
    out.append(
        f'#place(top + left, dx: {tx:.3f}mm, dy: {sy + 7.4:.3f}mm, text(size: 4.6pt, fill: rgb("{secondary}"))'
        f"[{typ_text(typo['body']['font_family'])} · {typ_text(typo['equation']['math_font'])}])\n"
    )
    for j, note in enumerate(notes):
        out.append(
            f'#place(top + left, dx: {tx:.3f}mm, dy: {sy + 10.2 + j * 2.8:.3f}mm, text(size: 4.2pt, fill: rgb("{muted}"))[{typ_text(note)}])\n'
        )
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--family", default="computational_neuroscience")
    parser.add_argument("--theme", default="default@0.3.0")
    parser.add_argument("--out", type=Path, default=Path("styles/default/0.3.0"))
    args = parser.parse_args()

    theme_layer = f"theme:{args.theme}"
    frames: list[tuple[str, dict[str, Any], Path]] = []
    style: dict[str, Any] | None = None
    notes: list[str] = []
    for project, wanted in FRAMES:
        project_dir = args.workspace / "families" / args.family / project
        manifest = newest_manifest(project_dir, theme_layer)
        style = style or manifest["job"]["resolved_style"]
        for record in pick_frames(manifest, wanted):
            frames.append((project, record, project_dir / record["png"]))
        for warning in manifest["result"].get("warnings", []):
            if warning not in notes:
                notes.append(warning)
    assert style is not None

    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        staged: list[tuple[str, dict[str, Any], Path]] = []
        for i, (project, record, png) in enumerate(frames):
            target = root / f"frame_{i:02d}_{project}_{record['snapshot_id']}.png"
            shutil.copyfile(png, target)
            staged.append((project, record, target))
        source = root / "specimen.typ"
        source.write_text(build(args.theme, staged, style, notes), encoding="utf-8")
        import typst

        typst.compile(str(source), output=str(args.out / "specimen.pdf"), format="pdf", root=str(root))
        typst.compile(str(source), output=str(args.out / "specimen.png"), format="png", ppi=190.5, root=str(root))
    for name in ("specimen.pdf", "specimen.png"):
        print(name, (args.out / name).stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
