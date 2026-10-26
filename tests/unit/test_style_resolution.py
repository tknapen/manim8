"""Theme cascade: precedence, provenance, hashing, allowlists and failure modes."""

from __future__ import annotations

from pathlib import Path

import pytest

from scianim.styles.resolve import StyleResolutionError, resolve_style
from scianim_core import StyleSelection


def selection(**overrides: object) -> StyleSelection:
    return StyleSelection(name="tomas_scientific", version="0.1.0", overrides=overrides)


def test_theme_chain_and_provenance(styles_copy: Path) -> None:
    style = resolve_style(selection(), [styles_copy])
    assert style.layers == ["theme:default@0.1.0", "theme:tomas_scientific@0.1.0"]
    assert style.tokens.palette["primary_signal"] == "#56B4E9"
    assert style.provenance["palette.primary_signal"] == "theme:tomas_scientific@0.1.0"
    assert style.tokens.typography.equation.engine == "typst"
    assert style.hash.startswith("sha256:")


def test_partial_child_inherits_everything_else(styles_copy: Path) -> None:
    child = styles_copy / "minimal" / "style.yaml"
    child.parent.mkdir()
    child.write_text(
        'schema_version: "1.0"\nname: minimal\nversion: "0.2.0"\ninherits: default\n'
        'palette:\n  primary_signal: "#FF0000"\n'
    )
    style = resolve_style(StyleSelection(name="minimal", version="0.2.0"), [styles_copy])
    assert style.tokens.palette["primary_signal"] == "#FF0000"
    assert style.provenance["palette.primary_signal"] == "theme:minimal@0.2.0"
    assert style.provenance["palette.background"] == "theme:default@0.1.0"
    assert style.provenance["typography.body.font_family"] == "theme:default@0.1.0"


def test_project_override_applies_and_changes_hash(styles_copy: Path) -> None:
    base = resolve_style(selection(), [styles_copy])
    changed = resolve_style(selection(**{"palette.primary_signal": "#000000"}), [styles_copy])
    assert changed.tokens.palette["primary_signal"] == "#000000"
    assert changed.provenance["palette.primary_signal"] == "project"
    assert changed.hash != base.hash
    assert changed.layers[-1] == "project"


def test_project_override_outside_allowlist_rejected(styles_copy: Path) -> None:
    with pytest.raises(StyleResolutionError, match="not allowed"):
        resolve_style(selection(**{"typography.minimum_body_px_at_1080p": 4}), [styles_copy])


def test_override_of_unknown_path_rejected(styles_copy: Path) -> None:
    with pytest.raises(StyleResolutionError, match="does not exist"):
        resolve_style(selection(**{"charts.sparkle": True}), [styles_copy])


def test_new_palette_role_may_be_added(styles_copy: Path) -> None:
    style = resolve_style(selection(**{"palette.inhibition": "#123456"}), [styles_copy])
    assert style.tokens.palette["inhibition"] == "#123456"


def test_incomplete_root_theme_fails(styles_copy: Path) -> None:
    root = styles_copy / "bare" / "style.yaml"
    root.parent.mkdir()
    root.write_text('schema_version: "1.0"\nname: bare\nversion: "0.1.0"\npalette:\n  background: "#000000"\n')
    with pytest.raises(StyleResolutionError, match="complete token set"):
        resolve_style(StyleSelection(name="bare", version="0.1.0"), [styles_copy])


def test_missing_required_palette_role_fails(styles_copy: Path) -> None:
    text = (styles_copy / "default" / "style.yaml").read_text().replace('  comparison: "#B698D9"\n', "")
    (styles_copy / "default" / "style.yaml").write_text(text)
    child = (styles_copy / "tomas_scientific" / "style.yaml").read_text().replace('  comparison: "#CC79A7"\n', "")
    (styles_copy / "tomas_scientific" / "style.yaml").write_text(child)
    with pytest.raises(StyleResolutionError, match="required palette roles"):
        resolve_style(selection(), [styles_copy])


def test_version_pin_mismatch_fails(styles_copy: Path) -> None:
    with pytest.raises(StyleResolutionError, match="pins style"):
        resolve_style(StyleSelection(name="tomas_scientific", version="9.9.9"), [styles_copy])


def test_unknown_theme_fails(styles_copy: Path) -> None:
    with pytest.raises(StyleResolutionError, match="not found"):
        resolve_style(StyleSelection(name="nope", version="0.1.0"), [styles_copy])
