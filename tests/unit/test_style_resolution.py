"""Theme cascade: versioned sheets, pinned inheritance, groups, provenance, hashing and failures."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scianim.styles.resolve import StyleResolutionError, list_styles, resolve_style
from scianim_core import GroupManifest, StyleSelection
from scianim_core.style import StyleTokens


def selection(**overrides: object) -> StyleSelection:
    return StyleSelection(name="tomas_scientific", version="0.1.0", overrides=overrides)


def write_sheet(styles: Path, name: str, version: str, body: str) -> Path:
    target = styles / name / version / "style.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(f'schema_version: "1.0"\nname: {name}\nversion: "{version}"\n{body}')
    return target


def test_versioned_layout_is_listed(styles_copy: Path) -> None:
    found = list_styles([styles_copy])
    assert set(found) == {"default", "tomas_scientific"}
    assert set(found["tomas_scientific"]) == {"0.1.0", "0.2.0", "0.3.0", "0.3.1"}
    assert set(found["default"]) == {"0.1.0", "0.2.0", "0.3.0", "0.3.1"}


def test_theme_chain_and_provenance(styles_copy: Path) -> None:
    style = resolve_style(selection(), [styles_copy])
    assert style.layers == ["theme:default@0.1.0", "theme:tomas_scientific@0.1.0"]
    assert style.tokens.palette["primary_signal"] == "#56B4E9"
    assert style.provenance["palette.primary_signal"] == "theme:tomas_scientific@0.1.0"
    assert style.tokens.typography.equation.engine == "typst"
    assert style.hash.startswith("sha256:")


def test_two_versions_of_a_theme_coexist(styles_copy: Path) -> None:
    write_sheet(
        styles_copy,
        "tomas_scientific",
        "0.9.0",
        'inherits: tomas_scientific@0.1.0\npalette:\n  primary_signal: "#00FF00"\n',
    )
    old = resolve_style(StyleSelection(name="tomas_scientific", version="0.1.0"), [styles_copy])
    new = resolve_style(StyleSelection(name="tomas_scientific", version="0.9.0"), [styles_copy])
    assert old.tokens.palette["primary_signal"] == "#56B4E9"
    assert new.tokens.palette["primary_signal"] == "#00FF00"
    assert new.tokens.typography == old.tokens.typography  # inherited from its predecessor
    assert new.layers == ["theme:default@0.1.0", "theme:tomas_scientific@0.1.0", "theme:tomas_scientific@0.9.0"]
    assert old.hash != new.hash


def test_partial_child_inherits_everything_else(styles_copy: Path) -> None:
    write_sheet(styles_copy, "minimal", "0.2.0", 'inherits: default@0.1.0\npalette:\n  primary_signal: "#FF0000"\n')
    style = resolve_style(StyleSelection(name="minimal", version="0.2.0"), [styles_copy])
    assert style.tokens.palette["primary_signal"] == "#FF0000"
    assert style.provenance["palette.primary_signal"] == "theme:minimal@0.2.0"
    assert style.provenance["palette.background"] == "theme:default@0.1.0"
    assert style.provenance["typography.body.font_family"] == "theme:default@0.1.0"


def test_sheet_must_match_its_directory(styles_copy: Path) -> None:
    write_sheet(styles_copy, "mislabeled", "0.1.0", "inherits: default@0.1.0\n").write_text(
        'schema_version: "1.0"\nname: mislabeled\nversion: "0.9.0"\ninherits: default@0.1.0\n'
    )
    with pytest.raises(StyleResolutionError, match=r"lives at a path for mislabeled@0\.1\.0"):
        resolve_style(StyleSelection(name="mislabeled", version="0.1.0"), [styles_copy])


def test_group_layer_applies_between_family_and_project(styles_copy: Path) -> None:
    group = GroupManifest.model_validate(
        {"schema_version": "1.0", "id": "perception", "style": {"overrides": {"palette.emphasis": "#ABCDEF"}}}
    )
    style = resolve_style(selection(**{"palette.primary_signal": "#000000"}), [styles_copy], groups=[group])
    assert style.layers == ["theme:default@0.1.0", "theme:tomas_scientific@0.1.0", "group:perception", "project"]
    assert style.tokens.palette["emphasis"] == "#ABCDEF"
    assert style.provenance["palette.emphasis"] == "group:perception"
    assert style.provenance["palette.primary_signal"] == "project"


def test_project_override_applies_and_changes_hash(styles_copy: Path) -> None:
    base = resolve_style(selection(), [styles_copy])
    changed = resolve_style(selection(**{"palette.primary_signal": "#000000"}), [styles_copy])
    assert changed.tokens.palette["primary_signal"] == "#000000"
    assert changed.provenance["palette.primary_signal"] == "project"
    assert changed.hash != base.hash
    assert changed.layers[-1] == "project"


def test_project_override_outside_allowlist_rejected(styles_copy: Path) -> None:
    with pytest.raises(StyleResolutionError, match="not allowed"):
        resolve_style(selection(**{"typography.minimum_text_px_at_1080p": 4}), [styles_copy])


def test_override_of_unknown_path_rejected(styles_copy: Path) -> None:
    with pytest.raises(StyleResolutionError, match="does not exist"):
        resolve_style(selection(**{"charts.sparkle": True}), [styles_copy])


def test_new_palette_role_may_be_added(styles_copy: Path) -> None:
    style = resolve_style(selection(**{"palette.inhibition": "#123456"}), [styles_copy])
    assert style.tokens.palette["inhibition"] == "#123456"


def test_incomplete_root_theme_fails(styles_copy: Path) -> None:
    write_sheet(styles_copy, "bare", "0.1.0", 'palette:\n  background: "#000000"\n')
    with pytest.raises(StyleResolutionError, match="complete token set"):
        resolve_style(StyleSelection(name="bare", version="0.1.0"), [styles_copy])


def test_missing_required_palette_role_fails(styles_copy: Path) -> None:
    for name, line in (("default", '  comparison: "#B698D9"\n'), ("tomas_scientific", '  comparison: "#CC79A7"\n')):
        sheet = styles_copy / name / "0.1.0" / "style.yaml"
        sheet.write_text(sheet.read_text().replace(line, ""))
    with pytest.raises(StyleResolutionError, match="required palette roles"):
        resolve_style(selection(), [styles_copy])


def test_unknown_version_lists_available_ones(styles_copy: Path) -> None:
    with pytest.raises(
        StyleResolutionError,
        match=r"not found.*available versions of 'tomas_scientific': \['0\.1\.0', '0\.2\.0', '0\.3\.0', '0\.3\.1'\]",
    ):
        resolve_style(StyleSelection(name="tomas_scientific", version="9.9.9"), [styles_copy])


def test_unversioned_sheet_gets_a_migration_hint(styles_copy: Path) -> None:
    flat = styles_copy / "legacy" / "style.yaml"
    flat.parent.mkdir()
    flat.write_text('schema_version: "1.0"\nname: legacy\nversion: "0.1.0"\n')
    with pytest.raises(StyleResolutionError, match="unversioned sheet"):
        resolve_style(StyleSelection(name="legacy", version="0.1.0"), [styles_copy])


def test_unknown_theme_fails(styles_copy: Path) -> None:
    with pytest.raises(StyleResolutionError, match="not found"):
        resolve_style(StyleSelection(name="nope", version="0.1.0"), [styles_copy])


def test_every_text_role_is_a_token_at_or_above_the_minimum(styles_copy: Path) -> None:
    style = resolve_style(selection(), [styles_copy])
    typography = style.tokens.typography
    minimum = typography.minimum_text_px_at_1080p
    for role in ("title", "body", "annotation", "axis_label", "tick_label", "caption"):
        assert getattr(typography, role).size_px_at_1080p >= minimum, role
    assert typography.equation.label_size_px_at_1080p >= minimum
    assert style.tokens.charts.spines == ["left", "bottom"]  # despined by default

    too_small = style.tokens.model_dump()
    too_small["typography"]["tick_label"]["size_px_at_1080p"] = minimum - 1
    with pytest.raises(ValidationError, match="below minimum_text_px_at_1080p"):
        StyleTokens.model_validate(too_small)
