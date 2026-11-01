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
        first = many.component.group.submobjects[0]
        stale_family = list(first.get_family())
        assert any(len(m.points) for m in stale_family)
        for value in np.linspace(0.0, 101.9, 90):
            scene.set_readout_text(many, f"θ = {value:.1f} deg")
        # Manim keeps drawing the play's moving family as it was when the play began: a replaced text must be
        # empty, or its glyphs would be drawn as a ghost of the first value, projected through the 3D camera.
        assert all(len(m.points) == 0 for m in stale_family) and not first.submobjects
        once = readout("θ = 0.0 deg")
        scene.set_readout_text(once, "θ = 101.9 deg")
        assert many.component.text == once.component.text == "θ = 101.9 deg"
        assert len(many.component.group.submobjects) == len(once.component.group.submobjects) == 1
        assert outline(many.component.group).shape == outline(once.component.group).shape
        assert np.allclose(outline(many.component.group), outline(once.component.group))
        fixed = scene.renderer.camera.fixed_in_frame_mobjects
        assert all(m in fixed for m in many.component.group.get_family())  # the fresh text stays fixed in frame


def test_track_segment_pieces_apply_the_same_fractions_per_frame_as_the_whole_play() -> None:
    """A play of 90 frames cut at frames 27 and 63 (ADR-031): driven as Manim drives it, frame k of every piece
    lands exactly where frame k of the whole play would, each piece's finish lands on the next piece's first
    frame, and only the last piece's finish reaches f1."""
    from dataclasses import dataclass

    from scianim_bridge.scene import Track, TrackSegment

    @dataclass
    class Recording(Track):
        seen: list[float] | None = None

        def apply(self, fraction: float) -> None:
            assert self.seen is not None
            self.seen.append(fraction)

    def drive(segment: TrackSegment) -> list[float]:
        """What Manim does with a play of `segment.frames` frames: alpha k / (frames - 0.5), then the finish."""
        track = segment.track
        track.seen = []  # type: ignore[attr-defined]
        for k in range(segment.frames):
            segment.interpolate_mobject(k / (segment.frames - 0.5))
        rendered = list(track.seen)  # type: ignore[attr-defined]
        segment.interpolate_mobject(1.0)
        return [*rendered, track.seen[-1]]  # type: ignore[attr-defined]

    track = Recording(scene=None, track_id="t", at_seconds=0.0, duration_seconds=3.0, seen=[])  # type: ignore[arg-type]
    whole = TrackSegment(track, 0.2, 0.8, 90)
    assert (whole.offset, whole.total) == (0, 90)
    whole_frames = drive(whole)
    assert whole_frames[0] == pytest.approx(0.2) and whole_frames[-1] == pytest.approx(0.8)
    assert whole_frames[1] - whole_frames[0] == pytest.approx(0.6 / 90)

    pieces = [whole.piece(0, 27), whole.piece(27, 36), whole.piece(63, 27)]
    assert [(p.offset, p.frames, p.total, p.f0, p.f1) for p in pieces] == [
        (0, 27, 90, 0.2, 0.8),
        (27, 36, 90, 0.2, 0.8),
        (63, 27, 90, 0.2, 0.8),
    ]
    piece_frames = [drive(piece) for piece in pieces]
    # Frame for frame, the pieces render what the whole play renders.
    rendered = [f for frames in piece_frames for f in frames[:-1]]
    assert len(rendered) == 90
    assert rendered == pytest.approx(whole_frames[:-1], abs=1e-12)
    # A piece's finish is the next piece's first frame; the last piece finishes on f1.
    assert piece_frames[0][-1] == pytest.approx(piece_frames[1][0], abs=1e-12)
    assert piece_frames[1][-1] == pytest.approx(piece_frames[2][0], abs=1e-12)
    assert piece_frames[2][-1] == pytest.approx(0.8)
    assert piece_frames[0][-1] == pytest.approx(0.2 + 0.6 * 27 / 90)
    # A piece of a piece keeps counting from the whole play.
    nested = pieces[1].piece(10, 5)
    assert (nested.offset, nested.frames, nested.total) == (37, 5, 90)
    assert drive(nested)[0] == pytest.approx(whole_frames[37], abs=1e-12)


def test_play_frames_cuts_plays_at_the_split_frames(tmp_path: Path) -> None:
    """With window boundaries set, a track play and a static wait are played as pieces numbered as Manim
    numbers them; a play of arbitrary animations is drawn whole and logged as unsplittable."""
    from dataclasses import dataclass

    from manim import FadeIn, Square, config

    from scianim_bridge.scene import SnapshotScene, Track
    from scianim_bridge.tokens import Tokens

    @dataclass
    class Recording(Track):
        seen: list[float] | None = None

        def apply(self, fraction: float) -> None:
            assert self.seen is not None
            self.seen.append(fraction)

    class Tiny(SnapshotScene):
        def construct(self) -> None:
            self.begin_scene("one", 0.0)
            self.track = Recording(scene=self, track_id="t", at_seconds=0.0, duration_seconds=0.9, seen=[])
            self.run_until(0.9, [self.track])  # 9 frames at 10 fps, cut at frame 3
            self.wait_until(2.0)  # a static wait of 11 frames, cut at frame 15
            self.play_frames(6, FadeIn(Square()))  # arbitrary Manim animation: frame 22 falls inside, no cut
            self.finish(3.0)  # 4 frames

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
        scene.split_frames = [3, 15, 22, 26]  # 26 is the edge between the FadeIn and the last wait
        scene.render()
    log = scene.play_log
    assert [(e["index"], e["source_index"], e["piece"], e["frames"], e["time"]) for e in log] == [
        (0, 0, 0, 3, pytest.approx(0.0)),
        (1, 0, 1, 6, pytest.approx(0.3)),
        (2, 1, 0, 6, pytest.approx(0.9)),
        (3, 1, 1, 5, pytest.approx(1.5)),
        (4, 2, 0, 6, pytest.approx(2.0)),
        (5, 3, 0, 4, pytest.approx(2.6)),
    ]
    assert [e["splittable"] for e in log] == [True, True, True, True, False, True]
    assert [e["static"] for e in log] == [False, False, True, True, False, True]
    assert scene.clock == pytest.approx(3.0)
    # In fast-forward every piece applies its first frame and its finish: 0, 3/9, 3/9, 1 for the cut track play.
    assert sorted({round(f, 9) for f in scene.track.seen}) == pytest.approx([0.0, 1 / 3, 1.0])
    assert scene.track.fraction == 1.0
    # Without boundaries the same scene logs whole plays, numbered as the planning pass sees them.
    with manim.tempconfig(settings):
        config.frame_width = config.frame_height * 16 / 9
        plain = Tiny()
        plain._tokens = Tokens(_style())
        plain.render()
    assert [(e["index"], e["source_index"], e["piece"], e["frames"]) for e in plain.play_log] == [
        (0, 0, 0, 9),
        (1, 1, 0, 11),
        (2, 2, 0, 6),
        (3, 3, 0, 4),
    ]
