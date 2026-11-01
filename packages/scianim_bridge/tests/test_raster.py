"""The raster surface renderer (ADR-032) beside the Cairo one: projection, painter's order, occlusion, hooks."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

manim = pytest.importorskip("manim")

sys.path.insert(0, str(Path(__file__).parent))
from test_sweeps import PALETTE, _scene, _style  # noqa: E402  (the shared minimal style of the bridge tests)

RIDGE = {
    "x_label": "x",
    "y_label": "y",
    "z_label": "g",
    "x_range": [-3, 3],
    "y_range": [-3, 3],
    "z_range": [0, 1],
    "expression": "exp(-(x^2) / 0.5)",  # a ridge along y, standing on the floor
    "parameters": {},
    "resolution": 24,
    "fill": "by_sign",
}

GABOR = {
    "x_label": "x (deg)",
    "y_label": "y (deg)",
    "z_label": "g",
    "x_range": [-3, 3],
    "y_range": [-3, 3],
    "z_range": [-1, 1],
    "expression": (
        "exp(-(((x - x_0) * cos(theta * pi / 180) + (y - y_0) * sin(theta * pi / 180))^2"
        " + (-(x - x_0) * sin(theta * pi / 180) + (y - y_0) * cos(theta * pi / 180))^2) / (2 * sigma^2))"
        " * cos(2 * pi * f * ((x - x_0) * cos(theta * pi / 180) + (y - y_0) * sin(theta * pi / 180)) + phi)"
    ),
    "parameters": {"theta": 0, "f": 0.6, "x_0": 0, "y_0": 0, "sigma": 1.2, "phi": 0},
    "resolution": 80,
    "fill": "diverging",
    "data_label": "analytic surface from the equation",
    "size_fraction": 0.85,
    "lift_fraction": 0.08,
}


def _lit_scene(renderer: str, **three_d):
    """A scene under the line-and-wash tokens that matter here: the light, a quiet mesh, opaque cells."""
    from scianim_bridge.tokens import Tokens

    scene = _scene()
    style = _style()
    tokens = style.tokens.model_copy(
        update={
            "three_d": style.tokens.three_d.model_copy(
                update={
                    "shading_strength": 0.45,
                    "mesh_role": "muted",
                    "surface_opacity": 1.0,
                    "mesh_stroke_px_at_1080p": 0.5,
                    **three_d,
                }
            ),
            "geometry": style.tokens.geometry.model_copy(update={"line_cap": "round"}),
        }
    )
    scene._tokens = Tokens(style.model_copy(update={"tokens": tokens}))
    scene.surface_renderer = renderer
    scene.begin_scene("s")
    return scene


def _frame(scene) -> np.ndarray:
    scene.renderer.update_frame(scene)
    return np.asarray(scene.renderer.get_frame()).copy()


def test_projection_matches_manim_for_three_known_points() -> None:
    """`project_to_pixels` is Manim's own path from a world point to an output pixel."""
    from manim import Mobject, config

    from scianim_bridge.camera import eye_position, project_to_pixels, view_depth
    from scianim_bridge.scene import SnapshotScene

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = SnapshotScene()
        camera = scene.renderer.camera
        camera.set_phi(math.radians(62))
        camera.set_theta(math.radians(-50))
        points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 1.0]])
        ours = project_to_pixels(camera, points)
        # Manim: the rotation matrix refreshed as `capture_mobjects` does, then the pixel mapping of an
        # ordinary (not fixed) mobject.
        camera.reset_rotation_matrix()
        theirs = camera.points_to_subpixel_coords(Mobject(), points.copy())
        assert np.allclose(ours, theirs, atol=1e-9)
        # The origin sits at the centre of the frame, whatever the angles.
        assert np.allclose(ours[0], [480.0, 270.0], atol=1e-6)
        # Nearness grows toward the eye, which lies `focal_distance` away along the view axis.
        depth = view_depth(camera, points)
        eye = eye_position(camera)
        distance = np.linalg.norm(points - eye, axis=1)
        assert np.argmax(depth) == np.argmin(distance)
        assert np.isclose(np.linalg.norm(eye - camera.frame_center), camera.get_focal_distance())
        assert np.isclose(view_depth(camera, eye[None, :])[0], camera.get_focal_distance())


def test_painters_order_puts_near_cells_last_and_hides_the_frame_behind_a_ridge() -> None:
    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.camera import view_depth

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _lit_scene("raster")
        surface = C.surface_plot(scene, "ridge", params=RIDGE)
        raster = surface.raster
        order = raster.cell_order()
        depth = raster.cell_depth()
        assert len(order) == 24 * 24
        assert depth[order[0]] <= depth[order[-1]]
        assert np.all(np.diff(depth[order]) >= 0)  # far to near, monotone
        # The frame: four floor edges and the vertical edge, each cut into pieces, then the ticks.
        edges = raster.strokes[:5]
        midpoints = [(s[:-1] + s[1:]) / 2 for s in edges]
        nearness = [float(view_depth(scene.renderer.camera, m).mean()) for m in midpoints[:4]]
        front, back = int(np.argmax(nearness)), int(np.argmin(nearness))
        hidden_front = raster.hidden(midpoints[front])
        hidden_back = raster.hidden(midpoints[back])
        assert not hidden_front.any(), "a front edge is seen whole"
        # The ridge stands between the viewer and the middle of the back edge: that piece goes.
        assert hidden_back[len(hidden_back) // 2]
        raster.paint()
        assert raster.hidden_pieces == sum(int(raster.hidden((s[:-1] + s[1:]) / 2).sum()) for s in raster.strokes)
        assert raster.hidden_pieces > 0
        # With the frame faded away nothing is tested or drawn for it.
        raster.set_frame_alpha(0.0)
        raster.paint()
        assert raster.hidden_pieces == 0
        # A surface lying flat on the floor hides nothing: the back edges stay, as in a drawn figure.
        flat = C.surface_plot(scene, "flat", params={**RIDGE, "expression": "0 * x * y"})
        flat.raster.paint()
        assert flat.raster.hidden_pieces == 0


def test_raster_component_repaints_on_sweep_and_orbit_and_fades_as_one() -> None:
    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.raster import RasterImage

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _lit_scene("raster")
        surface = C.surface_plot(scene, "gabor", params=GABOR)
        image = surface.group[0]
        assert isinstance(image, RasterImage) and surface.three_d and surface.axes is surface.group[1]
        assert image in scene.renderer.camera.fixed_in_frame_mobjects
        scene.add(surface.group)
        surface.visible = True
        raster = surface.raster
        first = _frame(scene)
        painted = raster.last_seconds
        assert not raster.dirty and painted > 0
        before = image.pixel_array.copy()
        # Nothing changed: the next frame reuses the picture.
        _frame(scene)
        assert raster.last_seconds == painted
        # A sweep marks it dirty and the next frame paints once.
        assert surface.set_parameters(theta=40.0) == []
        assert raster.dirty
        second = _frame(scene)
        assert not raster.dirty and not np.array_equal(image.pixel_array, before)
        assert not np.array_equal(first, second)
        # An orbit step does the same through the camera hook.
        scene.renderer.camera.set_theta(math.radians(10))
        scene.camera_moved()
        assert raster.dirty
        third = _frame(scene)
        assert not np.array_equal(second, third)
        # The whole image fades as one piece and keeps its fade through a repaint.
        full = image.orig_alpha_pixel_array.max()
        assert full == 255
        image.set_opacity(0.5)
        assert image.pixel_array[:, :, 3].max() == 127
        surface.set_parameters(theta=60.0)
        _frame(scene)
        assert image.pixel_array[:, :, 3].max() == 127 and image.fade_factor == 0.5
        image.set_opacity(1.0)
        # A copy (what a reveal animates) is a still picture without the refresh.
        copy = image.copy()
        assert copy.refresh is None and image.refresh is not None
        # `fade_axes` fades the labels and the frame together: the labels through Manim, the frame in the raster.
        track = scene.begin_fade_axes(surface, visible=False, at_seconds=0, duration_seconds=1, action_id="away")
        track.apply(0.5)
        assert 0.0 < raster.frame_alpha < 1.0 and raster.dirty
        label = surface.axes.submobjects[0].submobjects[0]
        assert 0.0 < float(label.get_fill_opacity()) < 1.0
        track.apply(1.0)
        track.finish()
        assert raster.frame_alpha == 0.0 and surface.axes not in surface.group.submobjects
        _frame(scene)
        assert raster.hidden_pieces == 0


def test_raster_frame_paints_under_the_budget_at_snapshot_size() -> None:
    from manim import config

    from scianim_bridge import components as C

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _lit_scene("raster")
        surface = C.surface_plot(scene, "gabor", params=GABOR)
        scene.add(surface.group)
        surface.visible = True
        import time

        seconds = []
        for theta in (-50, -20, 10):
            scene.renderer.camera.set_theta(math.radians(theta))
            scene.camera_moved()
            started = time.perf_counter()
            _frame(scene)
            seconds.append(time.perf_counter() - started)
        assert min(seconds) < 0.4, seconds


def test_both_renderers_report_the_same_box_within_two_percent() -> None:
    """The raster path's box comes from projected vertex extents, the Cairo path's from projected ink."""
    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.layout import layout_report

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        boxes = {}
        for renderer in ("cairo", "raster"):
            scene = _lit_scene(renderer)
            surface = C.surface_plot(scene, "gabor", params=GABOR)
            scene.add(surface.group)
            surface.visible = True
            scene.renderer.camera.set_theta(math.radians(-20))
            scene.camera_moved()
            _frame(scene)
            items, _ = layout_report(scene)
            boxes[renderer] = next(i for i in items if i.object_id == "gabor").bbox
            # Without the axes group the box is the shape (and the caption) alone.
            track = scene.begin_fade_axes(surface, visible=False, at_seconds=0, duration_seconds=1, action_id="a")
            track.apply(1.0)
            track.finish()
            items, _ = layout_report(scene)
            boxes[renderer + "_bare"] = next(i for i in items if i.object_id == "gabor").bbox
        for suffix in ("", "_bare"):
            a, b = boxes["cairo" + suffix], boxes["raster" + suffix]
            for name in ("x", "y", "x2", "y2"):
                assert abs(getattr(a, name) - getattr(b, name)) < 0.02, (suffix, name, a, b)
        assert boxes["raster_bare"].width < boxes["raster"].width


def test_raster_lift_raises_the_box_without_moving_it_sideways() -> None:
    """The layout test of the Cairo path, on the raster path: the vertices lift straight up."""
    from manim import config

    from scianim_bridge import components as C

    params = {
        **RIDGE,
        "expression": "x * y",
        "z_range": [-1, 1],
        "x_range": [-1, 1],
        "y_range": [-1, 1],
        "resolution": 4,
    }
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _lit_scene("raster")
        flat = C.surface_plot(scene, "flat", params=params)
        lifted = C.surface_plot(scene, "lifted", params={**params, "lift_fraction": 0.1})
        a = flat.raster.vertices.reshape(-1, 3).mean(axis=0)
        b = lifted.raster.vertices.reshape(-1, 3).mean(axis=0)
        assert b[2] > a[2] + 0.5 and abs(b[0] - a[0]) < 1e-6 and abs(b[1] - a[1]) < 1e-6
        # And the Cairo path places the same surface at the same spot.
        cairo = _lit_scene("cairo")
        c = C.surface_plot(cairo, "flat", params=params).group[1].get_center()
        assert np.allclose(c, a, atol=0.05)


def test_shading_is_one_function_for_both_paths() -> None:
    """`shaded_rgb` gives the Cairo faces and the raster cells the same shade for the same normal."""
    from manim import config

    from scianim_bridge import components as C
    from scianim_bridge.tokens import shaded_rgb

    plane = {
        **RIDGE,
        "expression": "0.8 * x",
        "z_range": [-1, 1],
        "x_range": [-1, 1],
        "y_range": [-1, 1],
        "resolution": 4,
    }
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        cairo = C.surface_plot(_lit_scene("cairo", light_azimuth_degrees=-60), "c", params=plane)
        raster = C.surface_plot(_lit_scene("raster", light_azimuth_degrees=-60), "r", params=plane)
        faces = cairo.group[1].submobjects
        cells = raster.raster.cell_rgb.reshape(-1, 3)
        for face, cell in zip(faces, cells, strict=True):
            assert np.allclose(np.array(face.get_fill_color().to_rgb()), cell, atol=1e-3)
        # The function itself: square to the light lightens toward the page, edge-on darkens toward the ink.
        page, ink, wash = np.array([1.0, 1.0, 1.0]), np.zeros(3), np.array([0.2, 0.4, 0.8])
        light = np.array([0.0, 0.0, 1.0])
        square = shaded_rgb(wash[None], np.array([[0.0, 0.0, 2.0]]), light, 0.5, page, ink)[0]
        edge = shaded_rgb(wash[None], np.array([[1.0, 0.0, 0.0]]), light, 0.5, page, ink)[0]
        assert np.allclose(square, wash * 0.75 + page * 0.25) and np.allclose(edge, wash * 0.5)
        assert np.allclose(shaded_rgb(wash[None], np.zeros((1, 3)), light, 0.5, page, ink)[0], wash * 0.5)


def test_array_expressions_agree_with_scalar_evaluation_on_a_grid() -> None:
    from scianim_core.expressions import compile_expression

    expression = "exp(-(x^2 + y^2) / (2 * s^2)) * cos(2 * pi * f * x) + log(x) / max(y, 0.5) + sqrt(y - x)"
    scalar = compile_expression(expression, ("x", "y", "s", "f"))
    vector = compile_expression(expression, ("x", "y", "s", "f"), arrays=True)
    xs, ys = np.meshgrid(np.linspace(-1, 1, 7), np.linspace(-1, 1, 5), indexing="ij")
    grid = vector(x=xs, y=ys, s=0.7, f=1.5)
    assert grid.shape == xs.shape
    for i in range(xs.shape[0]):
        for j in range(xs.shape[1]):
            a, b = scalar(x=float(xs[i, j]), y=float(ys[i, j]), s=0.7, f=1.5), grid[i, j]
            assert (math.isnan(a) and math.isnan(b)) or math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
    assert np.isnan(grid).any()  # the log and the root leave their domains on this grid
    constant = compile_expression("2 + 0 * x", ("x", "y"), arrays=True)(x=xs, y=ys)
    assert constant.shape == xs.shape and np.all(constant == 2.0)
    assert compile_expression("3", ("x",), arrays=True)(x=np.zeros(4)).shape == (4,)


def test_function_image_samples_in_one_call_and_the_cairo_frame_is_cut_into_pieces() -> None:
    from manim import Line, config

    from scianim_bridge import components as C
    from scianim_bridge.components.surfaces import CAIRO_FRAME_PIECES

    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        scene = _scene()
        image = C.function_image(
            scene,
            "grating",
            params={
                "expression": "cos(2 * pi * f * x)",
                "parameters": {"f": 1},
                "x_range": [-1, 1],
                "y_range": [-1, 1],
                "resolution": 8,
                "colors": "two_ink",
            },
        )
        pixels = image.group[0].pixel_array
        ink = np.array(manim.ManimColor(PALETTE["primary_signal"]).to_rgb()) * 255
        assert pixels.shape == (8, 8, 4) and np.allclose(pixels[0, 0, :3], ink, atol=1) and pixels[0, 0, 3] == 255
        # The Cairo frame: five edges in pieces plus one piece per tick, in Manim's depth sort only without
        # the sheet's light (the cells leave the sort when it is on).
        unlit = C.surface_plot(_scene(), "u", params=RIDGE)
        lit = C.surface_plot(_lit_scene("cairo"), "l", params=RIDGE)
        for component in (unlit, lit):
            frame = component.axes.submobjects[0]
            lines = [m for m in frame.submobjects if isinstance(m, Line)]
            assert len(lines) > 5 * CAIRO_FRAME_PIECES
        assert all(m.shade_in_3d for m in unlit.axes.submobjects[0].submobjects)
        assert not any(m.shade_in_3d for m in lit.axes.submobjects[0].submobjects)


def test_a_sphere_anchors_to_either_renderer_at_the_same_world_point() -> None:
    """ADR-034's `sphere` reads its position through the anchor surface's data-to-world map; both renderers expose
    the same map, so a drop over raster water sits where it sits over Cairo water."""
    from manim import config

    from scianim_bridge import components as C

    points = [(0.0, 0.0, 0.5), (1.0, -1.5, 0.0), (-2.0, 2.0, 1.0)]
    placed: dict[str, list[np.ndarray]] = {}
    with manim.tempconfig({"pixel_width": 960, "pixel_height": 540}):
        config.frame_width = config.frame_height * 16 / 9
        for renderer in ("cairo", "raster"):
            scene = _lit_scene(renderer)
            water = C.surface_plot(scene, "water", params=GABOR)
            assert water.to_world is not None
            placed[renderer] = [np.asarray(water.to_world(p), dtype=float) for p in points]
            drop = C.sphere(scene, "drop", params={"anchor": "water", "position": [0.0, 0.0, 0.5]})
            assert np.allclose(drop.group.get_center(), placed[renderer][0], atol=1e-6)
    for a, b in zip(placed["cairo"], placed["raster"], strict=True):
        assert np.allclose(a, b, atol=1e-6)
