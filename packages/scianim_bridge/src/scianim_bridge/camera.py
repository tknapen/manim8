"""The bridge's camera: Manim's three-dimensional Cairo camera with one repair, and its projection as functions.

Manim 0.22 composes an `ImageMobject` into a float array that newer Pillow versions refuse to treat as RGBA
("Invalid mode for data type"), so sampled fields could not be drawn. `SnapshotCamera.display_image_mobject`
is Manim's routine with the canvas allocated as 8-bit RGBA. Everything else is inherited.

The module functions give the raster surface (ADR-032) the camera's own projection: `project_to_pixels` is
exactly the path a world point takes to the output image (`ThreeDCamera.project_points`, then the frame to
pixel mapping), `view_depth` is the key Manim sorts three-dimensional mobjects by, and `eye_position` is the
pinhole those projections converge on. Nothing here re-derives the camera; a raster drawn with these agrees
with everything Manim draws beside it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from manim import Mobject, ThreeDCamera
from manim.utils.space_ops import cross2d
from PIL import Image

_PROBE = Mobject()
"""A mobject that is neither fixed in frame nor of fixed orientation, so the camera projects its points."""


def project_to_pixels(camera: Any, points: np.ndarray) -> np.ndarray:
    """World points (n, 3) to output pixel coordinates (n, 2), x to the right and y down, as floats."""
    camera.reset_rotation_matrix()
    return np.asarray(camera.points_to_subpixel_coords(_PROBE, np.array(points, dtype=float)))


def view_depth(camera: Any, points: np.ndarray) -> np.ndarray:
    """How near each world point is to the viewer: larger is nearer (Manim's sort key for 3D mobjects)."""
    camera.reset_rotation_matrix()
    rotated = np.dot(np.asarray(points, dtype=float) - camera.frame_center, camera.get_rotation_matrix().T)
    return np.asarray(rotated[:, 2])


def eye_position(camera: Any) -> np.ndarray:
    """The pinhole of the camera's perspective in world coordinates: `focal_distance` along the view axis."""
    camera.reset_rotation_matrix()
    rotation = camera.get_rotation_matrix()
    return np.asarray(camera.frame_center) + rotation.T @ np.array([0.0, 0.0, float(camera.get_focal_distance())])


class SnapshotCamera(ThreeDCamera):
    def display_image_mobject(self, image_mobject: Any, pixel_array: np.ndarray) -> None:
        sub_image = Image.fromarray(image_mobject.get_pixel_array(), mode="RGBA")
        original_coords = np.array(
            [[0, 0], [sub_image.width, 0], [0, sub_image.height], [sub_image.width, sub_image.height]]
        )
        target_coords = self.points_to_subpixel_coords(image_mobject, image_mobject.points)
        int_target_coords = target_coords.astype(np.int64)
        shift_vector = np.array([min(*[x for x, _ in int_target_coords]), min(*[y for _, y in int_target_coords])])
        target_coords -= shift_vector
        int_target_coords -= shift_vector
        target_size = (max(*[x for x, _ in int_target_coords]), max(*[y for _, y in int_target_coords]))
        ordered = [target_coords[i] for i in (0, 1, 3, 2)]
        sides = [ordered[(i + 1) % 4] - ordered[i] for i in range(4)]
        lengths = np.linalg.norm(sides, axis=1)
        longest_index = int(np.argmax(lengths))
        longest = sides[longest_index]
        longest_length = lengths[longest_index]
        if longest_length == 0:
            return
        previous_side = sides[(longest_index - 1) % 4]
        height = abs(cross2d(longest, previous_side)) / longest_length
        if height < 0.5:
            return
        homography = []
        for (x, y), (big_x, big_y) in zip(target_coords, original_coords, strict=True):
            homography.append([x, y, 1, 0, 0, 0, -big_x * x, -big_x * y])
            homography.append([0, 0, 0, x, y, 1, -big_y * x, -big_y * y])
        matrix = np.array(homography, dtype=np.float64)
        vector = original_coords.reshape(8).astype(np.float64)
        try:
            coefficients = np.linalg.solve(matrix, vector)
        except np.linalg.LinAlgError:
            return
        sub_image = sub_image.transform(
            size=target_size,
            method=Image.Transform.PERSPECTIVE,
            data=coefficients,
            resample=image_mobject.resampling_algorithm,
        )
        full_image = Image.fromarray(np.zeros((self.pixel_height, self.pixel_width, 4), dtype=np.uint8), mode="RGBA")
        full_image.paste(
            sub_image,
            box=(
                int(shift_vector[0]),
                int(shift_vector[1]),
                int(shift_vector[0] + target_size[0]),
                int(shift_vector[1] + target_size[1]),
            ),
        )
        self.overlay_PIL_image(pixel_array, full_image)
