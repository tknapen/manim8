"""The segment store's link-on-hit and atomic publish (ADR-033), with a stand-in for Manim's file writer."""

from __future__ import annotations

from pathlib import Path

from scianim_bridge import segment_store as store_module


def test_store_module_links_hits_and_publishes_atomically(tmp_path: Path) -> None:
    class Spec:
        is_video = True

    class Plan:
        def __init__(self, directory: Path) -> None:
            self.directory = directory

        def segment_path(self, key: str) -> Path:
            return self.directory / f"{key}.mp4"

    class Writer:
        def __init__(self, directory: Path) -> None:
            self.output_spec = Spec()
            self.output_plan = Plan(directory)

        def is_already_cached(self, key: str) -> bool:
            return self.output_plan.segment_path(key).exists()

    store = tmp_path / "store"
    first = tmp_path / "a" / "abc.mp4"
    first.parent.mkdir()
    first.write_bytes(b"segment")
    assert store_module.publish([first, tmp_path / "missing.mp4"], store) == 1
    assert (store / "abc.mp4").read_bytes() == b"segment" and store_module.publish([first], store) == 0
    assert not list(store.glob(".*tmp"))
    writer, hits = Writer(tmp_path / "b"), []
    store_module.install(writer, store, hits)
    assert writer.is_already_cached("abc") and hits == ["abc"]
    assert (tmp_path / "b" / "abc.mp4").read_bytes() == b"segment"
    assert not writer.is_already_cached("other") and hits == ["abc"]


def test_code_fingerprint_is_stable_and_names_the_libraries() -> None:
    first, second = store_module.code_fingerprint(), store_module.code_fingerprint()
    assert first == second and len(first) == 64
    assert "manim" in store_module.FINGERPRINT_LIBRARIES
