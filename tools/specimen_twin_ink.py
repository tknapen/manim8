"""Generate the Twin Ink specimen plate (styles/default/0.2.0/specimen.{typ,pdf,png}).

Run inside a family environment, which has the `typst` package:
    uv run --project workspace/families/computational_neuroscience python tools/specimen_twin_ink.py
The plate is a 16:9 page drawn in Typst: a family of divisive-normalization curves in blue ink,
one reference condition in red, the equation in a Palatino-lineage math face, and the palette and
type of the `default@0.2.0` theme as reference markers. Fonts: TeX Gyre Heros (Helvetica) and
TeX Gyre Pagella Math (Palatino) with fallbacks.
"""

from __future__ import annotations

import sys
from pathlib import Path

W, H = 320.0, 180.0  # page in mm, 16:9
INK = "#1C2230"
SECONDARY = "#5B6677"
MUTED = "#96A0AD"
NEUTRAL = "#D6DBE2"
GRID = "#EEF1F5"
BLUE = "#1F5FBF"
BLUE_SOFT = "#9BBCE9"
RED = "#D0342C"
RED_DEEP = "#9E2A25"
RED_SOFT = "#E9B3AF"
UNCERTAINTY = "#D3E1F6"
SELECTION = "#E8F0FB"

SIGMA = 1.0
POOLS = [i * 0.25 for i in range(0, 21)]  # P from 0 to 5
E_MAX, R_MAX = 10.0, 10.0
LEFT, RIGHT, TOP, BOTTOM = 52.0, 262.0, 26.0, 142.0  # plot box in mm


def lerp_hex(a: str, b: str, t: float) -> str:
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb, strict=True))


def x_of(e: float) -> float:
    return LEFT + (RIGHT - LEFT) * e / E_MAX


def y_of(r: float) -> float:
    return BOTTOM - (BOTTOM - TOP) * r / R_MAX


def curve(points: list[tuple[float, float]], paint: str, thickness: float) -> str:
    segs = [f"curve.move(({points[0][0]:.3f}mm, {points[0][1]:.3f}mm))"]
    segs += [f"curve.line(({x:.3f}mm, {y:.3f}mm))" for x, y in points[1:]]
    return (
        f'#place(top + left, curve(stroke: (paint: rgb("{paint}"), thickness: {thickness}mm, cap: "round", join: "round"), '
        + ", ".join(segs)
        + "))\n"
    )


def dot(x: float, y: float, r: float, paint: str) -> str:
    return f'#place(top + left, dx: {x - r:.3f}mm, dy: {y - r:.3f}mm, circle(radius: {r}mm, fill: rgb("{paint}"), stroke: none))\n'


def hline(x1: float, x2: float, y: float, paint: str, thickness: float) -> str:
    return f'#place(top + left, line(start: ({x1:.3f}mm, {y:.3f}mm), end: ({x2:.3f}mm, {y:.3f}mm), stroke: (paint: rgb("{paint}"), thickness: {thickness}mm)))\n'


def vline(x: float, y1: float, y2: float, paint: str, thickness: float) -> str:
    return f'#place(top + left, line(start: ({x:.3f}mm, {y1:.3f}mm), end: ({x:.3f}mm, {y2:.3f}mm), stroke: (paint: rgb("{paint}"), thickness: {thickness}mm)))\n'


def label(
    x: float,
    y: float,
    body: str,
    size: float,
    paint: str = SECONDARY,
    tracking: float = 0.06,
    weight: str = "regular",
    align: str = "left",
) -> str:
    anchor = {"left": "top + left", "right": "top + right", "center": "top + center"}[align]
    dx = (
        f"dx: {x:.3f}mm"
        if align == "left"
        else (f"dx: {x - W:.3f}mm" if align == "right" else f"dx: {x - W / 2:.3f}mm")
    )
    return f'#place({anchor}, {dx}, dy: {y:.3f}mm, text(size: {size}pt, fill: rgb("{paint}"), tracking: {tracking}em, weight: "{weight}")[{body}])\n'


def build() -> str:
    out: list[str] = []
    out.append(
        f"#set page(width: {W}mm, height: {H}mm, margin: 0pt, fill: white)\n"
        f'#set text(font: ("TeX Gyre Heros", "Nimbus Sans", "Helvetica", "Liberation Sans"), fill: rgb("{INK}"))\n'
        '#show math.equation: set text(font: ("TeX Gyre Pagella Math", "New Computer Modern Math"))\n'
        "#set par(leading: 0.5em)\n"
    )
    # --- hairline grid inside the plot box (graph-paper memory)
    for e in range(0, 11):
        out.append(vline(x_of(e), TOP, BOTTOM, GRID if e % 2 else NEUTRAL, 0.12 if e % 2 else 0.18))
    for r in range(0, 11):
        out.append(hline(LEFT, RIGHT, y_of(r), GRID if r % 2 else NEUTRAL, 0.12 if r % 2 else 0.18))
    # --- axes
    out.append(hline(LEFT, RIGHT, BOTTOM, INK, 0.3))
    out.append(vline(LEFT, TOP, BOTTOM, INK, 0.3))
    for e in range(0, 11, 2):
        out.append(vline(x_of(e), BOTTOM, BOTTOM + 1.6, INK, 0.3))
        out.append(label(x_of(e), BOTTOM + 3.2, str(e), 6.5, SECONDARY, align="center"))
    for r in range(0, 11, 2):
        out.append(hline(LEFT - 1.6, LEFT, y_of(r), INK, 0.3))
        out.append(label(LEFT - 3.4, y_of(r) - 1.6, str(r), 6.5, SECONDARY, align="right"))
    # --- the family of ratios r = E / (sigma + P), deep blue to pale blue as P grows
    n = len(POOLS)
    for i, pool in enumerate(POOLS):
        t = i / (n - 1)
        paint = lerp_hex(BLUE, BLUE_SOFT, t**0.8)
        pts = []
        for k in range(0, 201):
            e = E_MAX * k / 200
            r = e / (SIGMA + pool)
            if r > R_MAX:
                break
            pts.append((x_of(e), y_of(r)))
        if len(pts) > 1:
            out.append(curve(pts, paint, 0.28))
    # --- two observed conditions: low pool (blue) and high pool (red), dots at integer E
    for pool, paint, deep in ((1.0, BLUE, BLUE), (4.0, RED, RED_DEEP)):
        pts = [(x_of(E_MAX * k / 200), y_of(E_MAX * k / 200 / (SIGMA + pool))) for k in range(0, 201)]
        out.append(curve(pts, paint, 0.75))
        for e in range(0, 11):
            out.append(dot(x_of(e), y_of(e / (SIGMA + pool)), 0.95, deep))
    # --- reference ladder at the right edge: one tick per curve at its terminal height
    lx = RIGHT + 5.0
    for i, pool in enumerate(POOLS):
        r_end = min(E_MAX / (SIGMA + pool), R_MAX)
        y = y_of(r_end)
        highlighted = pool in (1.0, 4.0)
        paint = RED if pool == 4.0 else (BLUE if pool == 1.0 else MUTED)
        out.append(hline(lx, lx + (3.2 if highlighted else 1.8), y, paint, 0.35 if highlighted else 0.2))
        if highlighted or i % 4 == 0:
            out.append(label(lx + 4.6, y - 1.55, f"P = {pool:g}", 6.0, paint if highlighted else MUTED, tracking=0.04))
    out.append(label(lx + 4.6, TOP - 6.0, "σ + P", 6.5, SECONDARY, tracking=0.1))
    # --- axis titles
    out.append(label(x_of(5), BOTTOM + 8.6, "excitatory drive  E", 7.5, INK, tracking=0.08, align="center"))
    out.append(
        f'#place(top + left, dx: {LEFT - 13.5:.3f}mm, dy: {y_of(5) + 12.0:.3f}mm, rotate(-90deg, origin: top + left, reflow: true, text(size: 7.5pt, fill: rgb("{INK}"), tracking: 0.08em)[response  r]))\n'
    )
    # --- marginalia: name, equation, condition notes (top-left, inside the plot's upper margin)
    out.append(label(LEFT, 9.0, "TWIN INK", 8.0, INK, tracking=0.32, weight="bold"))
    out.append(label(LEFT + 26.0, 9.1, "default 0.2.0  ·  specimen plate 01", 6.5, SECONDARY, tracking=0.08))
    out.append(
        f'#place(top + left, dx: {x_of(4) + 1.5:.3f}mm, dy: {TOP + 6.0:.3f}mm, text(size: 21pt, fill: rgb("{INK}"))[$ r = E / (sigma + P) $])\n'
    )
    out.append(label(x_of(4) + 1.5, TOP + 21.0, "σ = 1", 6.5, SECONDARY, tracking=0.08))
    out.append(hline(x_of(4) + 1.5, x_of(4) + 9.5, TOP + 27.6, BLUE, 0.75))
    out.append(label(x_of(4) + 12.5, TOP + 26.2, "P = 1   observed", 6.5, BLUE, tracking=0.08))
    out.append(hline(x_of(4) + 1.5, x_of(4) + 9.5, TOP + 32.6, RED, 0.75))
    out.append(label(x_of(4) + 12.5, TOP + 31.2, "P = 4   observed", 6.5, RED, tracking=0.08))
    out.append(label(x_of(4) + 1.5, TOP + 37.4, "synthetic values · not measurements", 6.0, MUTED, tracking=0.06))
    # --- bottom strip: palette plate (left) and type specimen (right)
    sy = 156.0
    roles = [
        ("foreground", INK),
        ("secondary", SECONDARY),
        ("muted", MUTED),
        ("neutral", NEUTRAL),
        ("grid", GRID),
        ("signal", BLUE),
        ("signal soft", BLUE_SOFT),
        ("uncertainty", UNCERTAINTY),
        ("selection", SELECTION),
        ("emphasis", RED),
        ("comparison", RED_DEEP),
        ("comparison soft", RED_SOFT),
    ]
    for i, (name, paint) in enumerate(roles):
        x = LEFT + i * 15.2
        out.append(
            f'#place(top + left, dx: {x:.3f}mm, dy: {sy:.3f}mm, rect(width: 11.5mm, height: 7.2mm, fill: rgb("{paint}"), stroke: (paint: rgb("{NEUTRAL}"), thickness: 0.15mm)))\n'
        )
        out.append(label(x, sy + 8.4, name, 5.2, SECONDARY, tracking=0.05))
        out.append(label(x, sy + 11.6, paint.upper().replace("#", "\\#"), 4.6, MUTED, tracking=0.03))
    tx = LEFT + 12 * 15.2 + 8.0
    out.append(f'#place(top + left, dx: {tx:.3f}mm, dy: {sy - 2.2:.3f}mm, text(size: 22pt, fill: rgb("{INK}"))[Aa])\n')
    out.append(
        f'#place(top + left, dx: {tx + 16.0:.3f}mm, dy: {sy - 2.2:.3f}mm, text(size: 22pt, fill: rgb("{INK}"))[$ integral sigma partial infinity $])\n'
    )
    out.append(label(tx, sy + 8.4, "Helvetica · TeX Gyre Heros", 5.2, SECONDARY, tracking=0.05))
    out.append(label(tx, sy + 11.6, "Palatino math · TeX Gyre Pagella Math", 5.2, SECONDARY, tracking=0.05))
    return "".join(out)


def main() -> int:
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("styles/default/0.2.0")
    target_dir.mkdir(parents=True, exist_ok=True)
    source = target_dir / "specimen.typ"
    source.write_text(build(), encoding="utf-8")
    import typst

    typst.compile(str(source), output=str(target_dir / "specimen.pdf"), format="pdf")
    typst.compile(str(source), output=str(target_dir / "specimen.png"), format="png", ppi=190.5)
    for name in ("specimen.typ", "specimen.pdf", "specimen.png"):
        print(name, (target_dir / name).stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
