"""The bridge side of a parallel render: the play log, joining segments, the merge inputs (ADR-029)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

manim = pytest.importorskip("manim")
av = pytest.importorskip("av")

from test_sweeps import _style  # noqa: E402  (the shared minimal style of the bridge tests)


def _encode(path: Path, frames: int, level: int, fps: int = 10, size: int = 64) -> None:
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = size
        stream.height = size
        stream.pix_fmt = "yuv420p"
        for _ in range(frames):
            array = np.full((size, size, 3), level, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(array, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_concat_segments_keeps_every_frame_in_order(tmp_path: Path) -> None:
    from scianim_bridge.video import concat_segments, probe_video

    first, second = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _encode(first, 4, 40)
    _encode(second, 5, 200)
    joined = tmp_path / "joined.mp4"
    concat_segments([first, second], joined)
    probe = probe_video(joined)
    assert probe.frames == 9 and probe.fps == 10 and (probe.width, probe.height) == (64, 64)
    levels = []
    with av.open(str(joined)) as container:
        for frame in container.decode(video=0):
            levels.append(float(frame.to_ndarray(format="rgb24").mean()))
    assert len(levels) == 9
    assert all(level < 100 for level in levels[:4]) and all(level > 150 for level in levels[4:])
    with pytest.raises(ValueError):
        concat_segments([], joined)
    with pytest.raises(FileNotFoundError):
        concat_segments([tmp_path / "missing.mp4"], joined)


def test_play_log_lists_every_play_with_its_frames_and_kind(tmp_path: Path) -> None:
    """In fast-forward (a still output) the scene logs the same plays a video render would draw."""
    from manim import RIGHT, FadeIn, Square, config

    from scianim_bridge.scene import SnapshotScene
    from scianim_bridge.tokens import Tokens

    class Tiny(SnapshotScene):
        def construct(self) -> None:
            self.begin_scene("one", 0.0)
            square = Square()
            self.play_frames(6, FadeIn(square))
            self.wait_until(1.0)
            self.play_frames(3, square.animate.shift(RIGHT))
            self.finish(1.5)

    settings = {
        "media_dir": str(tmp_path),
        "format": "png",
        "preview": False,
        "progress_bar": "none",
        "verbosity": "WARNING",
        "log_to_file": False,
        "frame_rate": 10,
        "pixel_width": 64,
        "pixel_height": 36,
        "output_file": "tiny",
    }
    with manim.tempconfig(settings):
        config.frame_width = config.frame_height * 16 / 9
        scene = Tiny()
        scene._tokens = Tokens(_style())
        scene.render()
    log = scene.play_log
    assert [entry["index"] for entry in log] == [0, 1, 2, 3]
    assert [entry["frames"] for entry in log] == [6, 4, 3, 2]
    assert [entry["static"] for entry in log] == [False, True, False, True]
    assert [entry["time"] for entry in log] == pytest.approx([0.0, 0.6, 1.0, 1.3])
    assert all(entry["scene_id"] == "one" and entry["seconds"] >= 0 for entry in log)
    assert scene.clock == pytest.approx(1.5)


def test_worker_modes_follow_the_operation() -> None:
    from scianim_bridge.context import MODES

    assert MODES == {
        "render_snapshots": "snapshot",
        "render_video": "video",
        "plan_video": "plan",
        "render_video_part": "part",
        "merge_video": "merge",
    }


def test_readout_text_does_not_carry_the_history_of_earlier_values(tmp_path: Path) -> None:
    """Ninety values shown in turn leave exactly the glyphs one value would: fast-forward matches a render."""
    import numpy as np
    from manim import Text, VGroup, config

    from scianim_bridge.components.base import Component
    from scianim_bridge.scene import Readout, SnapshotScene
    from scianim_bridge.tokens import Tokens

    def outline(group: VGroup) -> np.ndarray:
        return np.vstack([m.points for m in group.get_family() if len(m.points)])

    with manim.tempconfig({"pixel_width": 480, "pixel_height": 270, "media_dir": str(tmp_path)}):
        config.frame_width = config.frame_height * 16 / 9
        scene = SnapshotScene()
        scene._tokens = Tokens(_style())
        tokens = scene.tokens
        typeface = tokens.typeface("annotation")
        ink = tokens.color("foreground")

        def readout(initial: str) -> Readout:
            text = Text(initial, **tokens.text_kwargs(typeface, ink))
            group = VGroup(text)
            component = Component("r", "value_readout", group, text=initial, font_px=20, text_like=True, visible=True)
            return Readout(component, lambda group=group: group.move_to([1.0, 2.0, 0.0]), typeface, ink)

        many = readout("θ = 0.0 deg")
        for value in np.linspace(0.0, 101.9, 90):
            scene.set_readout_text(many, f"θ = {value:.1f} deg")
        once = readout("θ = 0.0 deg")
        scene.set_readout_text(once, "θ = 101.9 deg")
        assert many.component.text == once.component.text == "θ = 101.9 deg"
        assert len(many.component.group.submobjects) == len(once.component.group.submobjects) == 1
        assert outline(many.component.group).shape == outline(once.component.group).shape
        assert np.allclose(outline(many.component.group), outline(once.component.group))
        fixed = scene.renderer.camera.fixed_in_frame_mobjects
        assert all(m in fixed for m in many.component.group.get_family())  # the fresh text stays fixed in frame
