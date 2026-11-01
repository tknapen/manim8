"""The raster surface renderer (ADR-032): a `surface_plot` painted by the bridge as one image.

The Cairo path hands Manim thousands of small polygons and pays about a millisecond per cell per frame. Here
the component keeps its vertex grid in world coordinates and, when the camera asks for the picture, projects
the grid through the scene's own camera (`camera.project_to_pixels`, the exact path every other point takes to
the screen), sorts the cells by view depth so the far ones are painted first, fills each quad with its shaded
wash and strokes its mesh, paints the floor frame and the ticks into the same image with a depth test against
the surface so the pieces it covers are left out, and reduces a twice-supersampled canvas to output pixels
with a box filter. The result is an `ImageMobject` fixed in the frame, placed on whole output pixels and
cropped to what it draws, so Manim composes it without resampling.

The image repaints lazily: a sweep (`rebuild`), an orbit (`on_camera`) and a fade of the frame mark it dirty,
and the next request for its pixels paints once, so a frame in which several of these happen costs one
painting. Nothing else triggers a repaint.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np
from manim import ImageMobject, config
from PIL import Image, ImageDraw

from scianim_bridge.camera import eye_position, project_to_pixels, view_depth
from scianim_core import BBox

SUPERSAMPLE = 2
"""The canvas is painted at this multiple of the output size and reduced with a box filter."""

PIECES_PER_EDGE = 48
"""How many pieces a floor-frame edge is cut into for the depth test; a tick is one piece."""

RAY_SAMPLES = 48
"""Points along the line of sight from a frame piece to the eye at which the surface height is checked."""


class RasterImage(ImageMobject):
    """The image a `RasterSurface` paints: placed on whole output pixels, fading as one piece.

    Three things differ from a plain `ImageMobject`. The pixels are fetched through `refresh` the moment the
    camera asks for them, so the painting happens once per frame however many triggers fired. `set_opacity`
    remembers its factor, so a repaint in the middle of a fade keeps the fade. And under a reveal the image
    interpolates only its opacity, because its content is painted for the current camera, not transformed
    from a copy; a copy of the image (which animations take) carries no refresh and stays a still picture.
    """

    refresh: Callable[[], None] | None = None
    fade_factor: float = 1.0

    def __init__(self) -> None:
        super().__init__(np.zeros((2, 2, 4), dtype=np.uint8), scale_to_resolution=int(config.pixel_height))
        self.set_resampling_algorithm(Image.Resampling.NEAREST)
        self.fade_factor = 1.0
        self.refresh = None

    def __deepcopy__(self, clone_from_id: dict[int, Any]) -> RasterImage:
        refresh, self.refresh = self.refresh, None
        try:
            return super().__deepcopy__(clone_from_id)
        finally:
            self.refresh = refresh

    def get_pixel_array(self) -> np.ndarray:
        if self.refresh is not None:
            self.refresh()
        return self.pixel_array

    def show(self, rgba: np.ndarray, left_px: int, top_px: int) -> None:
        """Take a painted RGBA array whose top-left pixel is output pixel (`left_px`, `top_px`)."""
        self.orig_alpha_pixel_array = rgba[:, :, 3].copy()
        self.pixel_array = np.array(rgba, dtype=np.uint8)
        self._apply_fade()
        h, w = rgba.shape[:2]
        fw, fh = float(config.frame_width), float(config.frame_height)
        pw, ph = float(config.pixel_width), float(config.pixel_height)
        x0, x1 = (left_px - pw / 2) * fw / pw, (left_px + w - pw / 2) * fw / pw
        y0, y1 = (ph / 2 - top_px) * fh / ph, (ph / 2 - top_px - h) * fh / ph
        self.points = np.array([[x0, y0, 0.0], [x1, y0, 0.0], [x0, y1, 0.0], [x1, y1, 0.0]])

    def set_opacity(self, alpha: float) -> RasterImage:
        self.fade_factor = float(alpha)
        self._apply_fade()
        self.stroke_opacity = float(alpha)
        return self

    def _apply_fade(self) -> None:
        self.pixel_array[:, :, 3] = (self.orig_alpha_pixel_array * self.fade_factor).astype(np.uint8)

    def interpolate(self, mobject1: Any, mobject2: Any, alpha: float, path_func: Any = None) -> RasterImage:
        a, b = float(mobject1.stroke_opacity), float(mobject2.stroke_opacity)
        self.set_opacity(a + (b - a) * alpha)
        return self


class RasterSurface:
    """What the image shows: the vertex grid, the cell washes, the frame strokes, and the painting of them.

    Colours are floats in 0..1 as the tokens give them; stroke widths are output pixels. The owner sets the
    cells (`set_cells`) when its parameters change, the strokes once, the frame alpha when a `fade_axes`
    runs, and calls `invalidate` when the camera moves; `refresh` paints if anything changed.
    """

    def __init__(
        self,
        camera: Any,
        image: RasterImage,
        *,
        page_rgb: np.ndarray,
        mesh_rgb: np.ndarray,
        mesh_px: float,
        frame_rgb: np.ndarray,
        frame_px: float,
        round_caps: bool,
        supersample: int = SUPERSAMPLE,
    ) -> None:
        self.camera = camera
        self.image = image
        self.page = tuple(round(c * 255) for c in page_rgb)
        self.mesh = (*(round(c * 255) for c in mesh_rgb), 255)
        self.mesh_px = float(mesh_px)
        self.frame_rgb = tuple(round(c * 255) for c in frame_rgb)
        self.frame_px = float(frame_px)
        self.round_caps = round_caps
        self.supersample = int(supersample)
        self.vertices: np.ndarray = np.zeros((2, 2, 3))
        self.cell_rgb: np.ndarray = np.zeros((1, 1, 3))
        self.cell_alpha: np.ndarray = np.ones((1, 1))
        self.strokes: list[np.ndarray] = []
        """Each stroke an (m, 3) polyline in world coordinates: the pieces of one frame edge or one tick."""
        self.frame_alpha = 1.0
        self.dirty = True
        self.last_seconds = 0.0
        """How long the last painting took, for the timing checks."""
        self.hidden_pieces = 0
        """How many frame pieces the last painting left out, for the occlusion checks."""
        image.refresh = self.refresh

    # --- what to draw -----------------------------------------------------------------------
    def set_cells(self, vertices: np.ndarray, rgb: np.ndarray, alpha: np.ndarray) -> None:
        """`vertices` (n+1, n+1, 3) in world coordinates on a grid aligned with the world x and y axes; `rgb`
        (n, n, 3) in 0..1 and `alpha` (n, n) in 0..1 for the cell between vertices (i, j) and (i+1, j+1)."""
        self.vertices = np.asarray(vertices, dtype=float)
        self.cell_rgb = np.asarray(rgb, dtype=float)
        self.cell_alpha = np.asarray(alpha, dtype=float)
        self.dirty = True

    def set_strokes(self, strokes: list[np.ndarray]) -> None:
        self.strokes = [np.asarray(s, dtype=float) for s in strokes]
        self.dirty = True

    def set_frame_alpha(self, alpha: float) -> None:
        if alpha != self.frame_alpha:
            self.frame_alpha = float(alpha)
            self.dirty = True

    def invalidate(self) -> None:
        self.dirty = True

    def refresh(self) -> None:
        if self.dirty:
            self.paint()

    # --- geometry ---------------------------------------------------------------------------
    def _world_points(self) -> np.ndarray:
        """Every world point the picture draws: the vertices, and the frame pieces when the frame shows."""
        parts = [self.vertices.reshape(-1, 3)]
        if self.frame_alpha > 0:
            parts.extend(self.strokes)
        return np.vstack(parts)

    def extents_px(self) -> tuple[float, float, float, float]:
        """The projected extents of what the picture draws, in output pixels (x0, y0, x1, y1), unclipped."""
        px = project_to_pixels(self.camera, self._world_points())
        return float(px[:, 0].min()), float(px[:, 1].min()), float(px[:, 0].max()), float(px[:, 1].max())

    def bbox(self) -> BBox:
        """The extents as the layout report wants them: normalized to the frame, origin at the top left."""
        x0, y0, x1, y1 = self.extents_px()
        pw, ph = float(config.pixel_width), float(config.pixel_height)
        return BBox(x=x0 / pw, y=y0 / ph, width=max(0.0, (x1 - x0) / pw), height=max(0.0, (y1 - y0) / ph))

    def height_at(self, xy: np.ndarray, margin: float = 0.0) -> np.ndarray:
        """The surface's world z over world (x, y) points (m, 2) by bilinear interpolation; NaN outside the box,
        and NaN within `margin` (a fraction of the box) of its edge."""
        xs, ys = self.vertices[:, 0, 0], self.vertices[0, :, 1]
        zs = self.vertices[:, :, 2]
        x, y = xy[:, 0], xy[:, 1]
        fi = np.interp(x, xs, np.arange(len(xs)), left=np.nan, right=np.nan)
        fj = np.interp(y, ys, np.arange(len(ys)), left=np.nan, right=np.nan)
        out = np.full(len(x), np.nan)
        inside = np.isfinite(fi) & np.isfinite(fj)
        if margin > 0:
            dx, dy = margin * (xs[-1] - xs[0]), margin * (ys[-1] - ys[0])
            inside &= (x > xs[0] + dx) & (x < xs[-1] - dx) & (y > ys[0] + dy) & (y < ys[-1] - dy)
        i = np.clip(np.floor(fi[inside]).astype(int), 0, len(xs) - 2)
        j = np.clip(np.floor(fj[inside]).astype(int), 0, len(ys) - 2)
        u, v = fi[inside] - i, fj[inside] - j
        out[inside] = (
            zs[i, j] * (1 - u) * (1 - v)
            + zs[i + 1, j] * u * (1 - v)
            + zs[i, j + 1] * (1 - u) * v
            + zs[i + 1, j + 1] * u * v
        )
        return out

    def cell_depth(self) -> np.ndarray:
        """Each cell's nearness to the viewer (the sum over its four corners of `view_depth`), row-major."""
        n_u, n_v = self.vertices.shape[0] - 1, self.vertices.shape[1] - 1
        depth = view_depth(self.camera, self.vertices.reshape(-1, 3)).reshape(n_u + 1, n_v + 1)
        return (depth[:-1, :-1] + depth[1:, :-1] + depth[1:, 1:] + depth[:-1, 1:]).reshape(-1)

    def cell_order(self) -> np.ndarray:
        """Row-major cell indices from the farthest to the nearest: the painter's order."""
        return np.argsort(self.cell_depth(), kind="stable")

    def hidden(self, points: np.ndarray) -> np.ndarray:
        """True for each world point whose line of sight to the eye passes under the surface.

        The sight line is sampled from the point to where it leaves the box's footprint; a sample inside the
        footprint and below the surface's height there means the surface stands between the point and the
        viewer. A point whose sight line leaves the footprint at once (the front edges of the frame) is seen.
        """
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        eye = eye_position(self.camera)
        direction = eye - points
        xs, ys = self.vertices[:, 0, 0], self.vertices[0, :, 1]
        lo = np.array([xs.min(), ys.min()])
        hi = np.array([xs.max(), ys.max()])
        # Slab test in x and y: the parameter at which each sight line leaves the footprint.
        with np.errstate(divide="ignore", invalid="ignore"):
            t_lo = (lo - points[:, :2]) / direction[:, :2]
            t_hi = (hi - points[:, :2]) / direction[:, :2]
        t_far = np.maximum(t_lo, t_hi)
        t_far[np.isnan(t_far)] = np.inf  # a sight line parallel to a slab never leaves through it
        t_exit = np.minimum(t_far.min(axis=1), 1.0)
        fractions = (np.arange(RAY_SAMPLES) + 0.5) / RAY_SAMPLES
        t = t_exit[:, None] * fractions[None, :]  # (m, k)
        samples = points[:, None, :] + direction[:, None, :] * t[:, :, None]
        flat = samples.reshape(-1, 3)
        # The frame lies on the footprint's edge; a sample a rounding error inside it must not count.
        height = self.height_at(flat[:, :2], margin=1e-6).reshape(samples.shape[:2])
        below = np.isfinite(height) & (samples[:, :, 2] < height - 1e-9) & (t > 0)
        return np.any(below, axis=1)

    # --- painting ---------------------------------------------------------------------------
    def paint(self) -> None:
        started = time.perf_counter()
        s = self.supersample
        pw, ph = int(config.pixel_width), int(config.pixel_height)
        pad = 0.5 * max(self.mesh_px, self.frame_px if self.frame_alpha > 0 else 0.0) + 1.0
        x0, y0, x1, y1 = self.extents_px()
        left, top = max(0, int(np.floor(x0 - pad))), max(0, int(np.floor(y0 - pad)))
        right, bottom = min(pw, int(np.ceil(x1 + pad))), min(ph, int(np.ceil(y1 + pad)))
        self.hidden_pieces = 0
        if right <= left or bottom <= top:
            self.image.show(np.zeros((1, 1, 4), dtype=np.uint8), 0, 0)
            self.dirty = False
            self.last_seconds = time.perf_counter() - started
            return
        size = ((right - left) * s, (bottom - top) * s)
        colour = Image.new("RGB", size, self.page)
        coverage = Image.new("L", size, 0)
        draw_colour = ImageDraw.Draw(colour, "RGBA")
        draw_coverage = ImageDraw.Draw(coverage)
        origin = np.array([left, top], dtype=float)

        def to_canvas(points: np.ndarray) -> np.ndarray:
            return (project_to_pixels(self.camera, points) - origin) * s

        self._paint_cells(draw_colour, draw_coverage, to_canvas)
        frame_coverage: Image.Image | None = None
        if self.frame_alpha > 0 and self.strokes:
            if self.frame_alpha >= 1.0:
                self._paint_frame(draw_colour, draw_coverage, to_canvas, 255)
            else:
                frame_coverage = Image.new("L", size, 0)
                self._paint_frame(draw_colour, ImageDraw.Draw(frame_coverage), to_canvas, round(255 * self.frame_alpha))
        rgb = np.asarray(colour.reduce(s))
        alpha = np.asarray(coverage.reduce(s))
        if frame_coverage is not None:
            faded = (np.asarray(frame_coverage.reduce(s)).astype(float) * self.frame_alpha).astype(np.uint8)
            alpha = np.maximum(alpha, faded)
        self.image.show(np.dstack([rgb, alpha]), left, top)
        self.dirty = False
        self.last_seconds = time.perf_counter() - started

    def _paint_cells(self, draw_colour: Any, draw_coverage: Any, to_canvas: Callable[[np.ndarray], np.ndarray]) -> None:
        n_u, n_v = self.vertices.shape[0] - 1, self.vertices.shape[1] - 1
        if n_u < 1 or n_v < 1:
            return
        canvas = to_canvas(self.vertices.reshape(-1, 3)).reshape(n_u + 1, n_v + 1, 2)
        quads = np.concatenate([canvas[:-1, :-1], canvas[1:, :-1], canvas[1:, 1:], canvas[:-1, 1:]], axis=-1).reshape(
            -1, 8
        )
        order = self.cell_order()
        rgba = np.concatenate([self.cell_rgb.reshape(-1, 3), self.cell_alpha.reshape(-1, 1)], axis=1)
        rgba = np.clip(np.round(rgba * 255), 0, 255).astype(int)
        width = max(1, round(self.mesh_px * self.supersample))
        polygons = quads[order].tolist()
        fills = rgba[order].tolist()
        mesh = self.mesh
        for xy, fill in zip(polygons, fills, strict=True):
            draw_colour.polygon(xy, fill=tuple(fill), outline=mesh, width=width)
            draw_coverage.polygon(xy, fill=255, outline=255, width=width)

    def _paint_frame(
        self, draw_colour: Any, draw_coverage: Any, to_canvas: Callable[[np.ndarray], np.ndarray], coverage: int
    ) -> None:
        ink = (*self.frame_rgb, round(255 * self.frame_alpha))
        width = max(1, round(self.frame_px * self.supersample))
        for stroke in self.strokes:
            midpoints = (stroke[:-1] + stroke[1:]) / 2
            seen = ~self.hidden(midpoints)
            self.hidden_pieces += int((~seen).sum())
            canvas = to_canvas(stroke)
            start = 0
            for index in range(len(seen) + 1):
                if index < len(seen) and seen[index]:
                    continue
                if index > start:  # pieces start..index-1 are seen: one polyline
                    run = [tuple(p) for p in canvas[start : index + 1].tolist()]
                    draw_colour.line(run, fill=ink, width=width, joint="curve")
                    draw_coverage.line(run, fill=coverage, width=width, joint="curve")
                    if self.round_caps and width > 2:
                        for x, y in (run[0], run[-1]):
                            box = [x - width / 2, y - width / 2, x + width / 2, y + width / 2]
                            draw_colour.ellipse(box, fill=ink)
                            draw_coverage.ellipse(box, fill=coverage)
                start = index + 1


def split(start: np.ndarray, end: np.ndarray, pieces: int) -> np.ndarray:
    """A straight stroke as `pieces` collinear pieces: (pieces + 1, 3) points from `start` to `end`."""
    fractions = np.linspace(0.0, 1.0, max(1, pieces) + 1)
    return (
        np.asarray(start, dtype=float)[None, :]
        + fractions[:, None] * (np.asarray(end, dtype=float) - np.asarray(start, dtype=float))[None, :]
    )
