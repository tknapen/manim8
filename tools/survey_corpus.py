"""Count the animation idioms of a ManimGL video corpus, read as data: nothing in it is imported or run.

The survey behind the pattern library (docs/ANIMATION_PATTERNS.md) ran this on the 3Blue1Brown videos
repository (https://github.com/3b1b/videos, CC BY-NC-SA 4.0):

    python -I tools/survey_corpus.py <corpus checkout> <out.json>

Each year folder (`_2015` ... `_2026`) is parsed with `ast`; files that do not parse as Python 3 (some of the
oldest projects are Python 2) are counted and skipped. A scene is a class with at least one `self.play` call.
Every argument of a play is reduced to a token: an animation class (`FadeIn`), an `.animate` method
(`animate.shift`; `camera.reorient` when the receiver is the camera frame; `tracker.set_value` for a value
tracker), an old-style method passed with its arguments (`method.shift`), or a helper call. Animations inside
`LaggedStart`, `LaggedStartMap`, `AnimationGroup` and `Succession` count as themselves and as staggered or
grouped. Per scene, the script also records constructs that matter to an idiom (value trackers, updaters,
traced paths, braces, colour-linked terms) and derives idiom flags from them. The output holds counts per era,
timing statistics (run times, lag ratios, waits, rate functions) and, per idiom, the scenes that use it most.

Counts describe one author's practice over eleven years. They say what he reaches for, not what works for a
viewer; the library weighs them against the research cited in docs/ANIMATION_PATTERNS.md.
"""

from __future__ import annotations

import ast
import json
import statistics
import subprocess
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

ERAS = {"2015-2019": range(2015, 2020), "2020-2022": range(2020, 2023), "2023-2026": range(2023, 2027)}

WRAPPERS = {"LaggedStart", "LaggedStartMap", "AnimationGroup", "Succession"}
STAGGERS = {"LaggedStart", "LaggedStartMap"}
CHARACTER_METHODS = {"change", "says", "thinks", "debubble", "change_mode", "look_at", "blink", "shrug"}
TRACKER_METHODS = {"set_value", "increment_value"}
CAMERA_3D_METHODS = {
    "reorient",
    "set_euler_angles",
    "increment_euler_angles",
    "increment_theta",
    "increment_phi",
    "increment_gamma",
    "set_theta",
    "set_phi",
    "set_gamma",
    "set_field_of_view",
}
SPACE_METHODS = {"apply_matrix", "apply_complex_function", "apply_function", "apply_points_function"}

CATEGORIES = {
    "draw on": {
        "ShowCreation",
        "Write",
        "DrawBorderThenFill",
        "ShowIncreasingSubsets",
        "ShowSubmobjectsOneByOne",
        "AddTextWordByWord",
        "ShowPartial",
        "Create",
        "Uncreate",
        "Unwrite",
    },
    "fade": {
        "FadeIn",
        "FadeOut",
        "FadeInFromPoint",
        "FadeOutToPoint",
        "VFadeIn",
        "VFadeOut",
        "VFadeInThenOut",
        "FadeInFrom",
        "FadeOutAndShift",
        "FadeInFromDown",
        "FadeInFromLarge",
        "FadeOutAndShiftDown",
    },
    "grow": {"GrowFromPoint", "GrowFromCenter", "GrowFromEdge", "GrowArrow", "SpinInFromNothing"},
    "morph": {
        "Transform",
        "ReplacementTransform",
        "FadeTransform",
        "FadeTransformPieces",
        "MoveToTarget",
        "Restore",
        "CyclicReplace",
        "Swap",
        "ClockwiseTransform",
        "CounterclockwiseTransform",
    },
    "derive by copy": {"TransformFromCopy"},
    "rewrite": {
        "TransformMatchingTex",
        "TransformMatchingStrings",
        "TransformMatchingShapes",
        "TransformMatchingParts",
    },
    "space transform": {
        "ApplyMatrix",
        "ApplyComplexFunction",
        "ApplyPointwiseFunction",
        "ApplyFunction",
        "Homotopy",
        "ComplexHomotopy",
        "SmoothedVectorizedHomotopy",
        "PhaseFlow",
        "ApplyPointwiseFunctionToCenter",
    },
    "indicate": {
        "Indicate",
        "Flash",
        "FlashAround",
        "FlashUnder",
        "CircleIndicate",
        "FocusOn",
        "ApplyWave",
        "WiggleOutThenIn",
        "ShowCreationThenDestruction",
        "ShowCreationThenFadeOut",
        "ShowCreationThenDestructionAround",
        "ShowCreationThenFadeAround",
        "AnimationOnSurroundingRectangle",
        "FlashyFadeIn",
        "TurnInsideOut",
        "Broadcast",
        "Wiggle",
        "Circumscribe",
    },
    "passing flash": {"ShowPassingFlash", "VShowPassingFlash", "ShowPassingFlashAround"},
    "move along path": {"MoveAlongPath"},
    "rotate": {"Rotate", "Rotating"},
    "count": {"ChangeDecimalToValue", "ChangingDecimal", "CountInFrom"},
    "update in play": {"UpdateFromFunc", "UpdateFromAlphaFunc", "MaintainPositionRelativeTo"},
}
ANIMATE_CATEGORIES = {
    "move": {
        "shift",
        "move_to",
        "next_to",
        "to_edge",
        "to_corner",
        "align_to",
        "set_x",
        "set_y",
        "set_z",
        "center",
        "arrange",
        "arrange_in_grid",
        "match_x",
        "match_y",
        "set_y_and_x",
    },
    "scale": {"scale", "set_width", "set_height", "stretch", "match_width", "match_height", "set_depth"},
    "style": {
        "set_color",
        "set_fill",
        "set_stroke",
        "set_opacity",
        "fade",
        "set_backstroke",
        "set_submobject_colors_by_gradient",
        "set_color_by_gradient",
        "match_color",
        "set_gloss",
        "set_shading",
        "set_flat_stroke",
        "set_fill_opacity",
        "set_stroke_opacity",
    },
    "rotate": {"rotate", "flip"},
    "reshape": {"become", "put_start_and_end_on", "set_points", "pointwise_become_partial", "match_points"},
}

CONSTRUCTS = {
    "value tracker": {"ValueTracker", "ComplexValueTracker", "ExponentialValueTracker"},
    "number readout": {"DecimalNumber", "Integer", "DecimalMatrix"},
    "traced path": {"TracedPath", "TracingTail"},
    "brace": {"Brace", "BraceLabel", "BraceText", "LineBrace"},
    "surrounding box": {"SurroundingRectangle"},
    "backdrop": {"BackgroundRectangle"},
    "axes": {"Axes", "ThreeDAxes", "NumberPlane", "ComplexPlane", "NumberLine", "PolarPlane", "UnitInterval"},
    "surface": {
        "Surface",
        "ParametricSurface",
        "SurfaceMesh",
        "TexturedSurface",
        "Sphere",
        "Torus",
        "ParametricSurface3D",
    },
    "field": {"VectorField", "StreamLines", "AnimatedStreamLines", "ArrowField"},
    "point cloud": {"DotCloud", "GlowDot", "GlowDots", "TrueDot"},
    "image": {"ImageMobject"},
    "character": {"Randolph", "Mortimer", "PiCreature", "TeacherStudentsScene", "PiCreatureScene", "PiCreatureSays"},
    "inset screen": {"ScreenRectangle", "FullScreenRectangle", "FullScreenFadeRectangle"},
    "function graph": {"FunctionGraph", "ParametricCurve"},
    "arrow": {"Arrow", "Vector", "FillArrow", "StrokeArrow", "CurvedArrow"},
}
ATTR_CONSTRUCTS = {
    "function graph": {"get_graph", "get_parametric_curve"},
    "area under graph": {"get_riemann_rectangles", "get_area_under_graph", "get_area"},
    "fixed in frame": {"fix_in_frame"},
}
UNWRAP = {"list", "tuple", "chain"}  # `*list(map(FadeIn, mobs))`, `*it.chain(...)`
UPDATER_ATTRS = {"add_updater", "always", "f_always"}
UPDATER_FUNCS = {"always", "f_always", "always_redraw", "always_shift", "always_rotate"}
COLOR_LINK_KEYWORDS = {"t2c", "tex_to_color_map", "isolate", "t2s", "t2w"}
COLOR_LINK_ATTRS = {"set_color_by_tex", "set_color_by_tex_to_color_map", "set_color_by_string"}


def dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        parts.append(dotted(node.func) + "()")
    return ".".join(reversed(parts))


def animate_chain(node: ast.AST) -> tuple[ast.AST, list[str]] | None:
    """For `mob.animate.m1(...).m2(...)`, the receiver and [m1, m2]; None for anything else."""
    methods: list[str] = []
    while True:
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute):
            if node.attr == "animate":
                return node.value, methods[::-1]
            methods.append(node.attr)
            node = node.value
        else:
            return None


def flat_reorient(node: ast.AST) -> bool:
    """Whether a `frame.animate.reorient(...)` only pans and zooms: no angles, or zero theta and phi."""
    while isinstance(node, ast.Call | ast.Attribute):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "reorient":
            if any(k.arg and k.arg.endswith("_degrees") for k in node.keywords):
                return False
            return all(literal(angle) == 0 for angle in node.args[:2])
        node = node.func if isinstance(node, ast.Call) else node.value
    return False


def is_camera(receiver: ast.AST) -> bool:
    name = dotted(receiver)
    return name.endswith("frame") or name.endswith("camera_frame")


def literal(node: ast.AST | None) -> float | None:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def rate_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return rate_name(node.func) + "(...)"
    if isinstance(node, ast.Lambda):
        return "lambda"
    return dotted(node).split(".")[-1] or type(node).__name__


class PlayTokens:
    """The tokens of one play's arguments, with the keyword values found inside them."""

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.staggered: list[str] = []
        self.lag_ratios: list[float] = []
        self.rate_funcs: list[str] = []
        self.run_times: list[float] = []

    def keywords(self, call: ast.Call) -> None:
        for keyword in call.keywords:
            if keyword.arg == "lag_ratio" and (value := literal(keyword.value)) is not None:
                self.lag_ratios.append(value)
            elif keyword.arg == "rate_func":
                self.rate_funcs.append(rate_name(keyword.value))
            elif keyword.arg == "run_time" and (value := literal(keyword.value)) is not None:
                self.run_times.append(value)

    def add(self, token: str, *, staggered: bool) -> None:
        self.tokens.append(token)
        if staggered:
            self.staggered.append(token)

    def classify(self, node: ast.AST, *, staggered: bool = False) -> None:
        if isinstance(node, ast.Starred):
            self.classify(node.value, staggered=staggered)
        elif isinstance(node, ast.ListComp | ast.GeneratorExp | ast.SetComp):
            self.classify(node.elt, staggered=staggered)
        elif isinstance(node, ast.List | ast.Tuple):
            for element in node.elts:
                self.classify(element, staggered=staggered)
        elif isinstance(node, ast.IfExp):
            self.classify(node.body, staggered=staggered)
        elif isinstance(node, ast.Call):
            self.call(node, staggered=staggered)
        elif isinstance(node, ast.Attribute):
            if node.attr == "animate":
                self.add("animate.(property)", staggered=staggered)
            else:
                self.add("method." + node.attr, staggered=staggered)
        elif isinstance(node, ast.Name):
            self.add("variable", staggered=staggered)
        else:
            self.add("other", staggered=staggered)

    def call(self, node: ast.Call, *, staggered: bool) -> None:
        self.keywords(node)
        chain = animate_chain(node)
        if chain is not None:
            receiver, methods = chain
            first = methods[0] if methods else "(property)"
            if is_camera(receiver):
                flat = first == "reorient" and flat_reorient(node)
                self.add("camera." + first + (" (flat)" if flat else ""), staggered=staggered)
            elif first in TRACKER_METHODS:
                self.add("tracker." + first, staggered=staggered)
            else:
                self.add("animate." + first, staggered=staggered)
            return
        func = node.func
        if dotted(func).split(".")[-1] in UNWRAP and isinstance(func, ast.Name | ast.Attribute):
            for argument in node.args:
                self.classify(argument, staggered=staggered)
            return
        if (
            isinstance(func, ast.Name)
            and func.id == "ApplyMethod"
            and node.args
            and isinstance(node.args[0], ast.Attribute)
        ):
            self.add("method." + node.args[0].attr, staggered=staggered)  # old style: ApplyMethod(mob.shift, UP)
            return
        if isinstance(func, ast.Name) and func.id == "map" and node.args:
            self.classify(ast.Call(func=node.args[0], args=[], keywords=[]), staggered=staggered)
            return
        if isinstance(func, ast.Name) and func.id[:1].isupper():
            self.add(func.id, staggered=staggered)
            if func.id in WRAPPERS:
                inner_stagger = func.id in STAGGERS or any(
                    k.arg == "lag_ratio" and (literal(k.value) or 0) > 0 for k in node.keywords
                )
                arguments = node.args
                if func.id == "LaggedStartMap" and arguments:
                    self.classify(ast.Call(func=arguments[0], args=[], keywords=[]), staggered=True)
                    arguments = []
                for argument in arguments:
                    self.classify(argument, staggered=inner_stagger)
            return
        name = dotted(func).split(".")[-1]
        if isinstance(func, ast.Attribute) and name in CHARACTER_METHODS:
            self.add("character." + name, staggered=staggered)
        else:
            self.add("helper." + name, staggered=staggered)


def play_tokens(call: ast.Call) -> PlayTokens:
    result = PlayTokens()
    result.keywords(call)
    skipping = False  # old style: `self.play(mob.shift, UP)` passes a method followed by its arguments
    for argument in call.args:
        if isinstance(argument, ast.Attribute) and argument.attr != "animate":
            result.classify(argument)
            skipping = True
            continue
        if skipping and not (
            isinstance(argument, ast.Starred)
            or (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Name)
                and argument.func.id[:1].isupper()
            )
            or (isinstance(argument, ast.Call) and animate_chain(argument) is not None)
        ):
            continue
        skipping = False
        result.classify(argument)
    return result


def category(token: str) -> str:
    for name, classes in CATEGORIES.items():
        if token in classes:
            return name
    if token in WRAPPERS:
        return "group or stagger"
    prefix, _, method = token.partition(".")
    if prefix == "camera":
        return "camera 3d" if method in CAMERA_3D_METHODS else "camera 2d"  # "reorient (flat)" is 2d
    if prefix == "tracker":
        return "tracker sweep"
    if prefix == "character":
        return "character"
    if prefix in {"animate", "method"}:
        if method in SPACE_METHODS:
            return "space transform"
        if method == "surround":  # a box moved on to the next thing it points at
            return "indicate"
        if method == "restore":
            return "morph"
        for name, methods in ANIMATE_CATEGORIES.items():
            if method in methods:
                return "property " + name
        if method in TRACKER_METHODS:
            return "tracker sweep"
        if method in CHARACTER_METHODS:
            return "character"
        return "property other"
    if prefix == "helper":
        return "helper"
    return "unresolved"


class SceneSurvey(ast.NodeVisitor):
    """Everything counted inside one scene class."""

    def __init__(self) -> None:
        self.plays: list[PlayTokens] = []
        self.waits: list[float] = []
        self.constructs: Counter[str] = Counter()
        self.updaters = 0
        self.camera_updaters = 0
        self.color_links = 0
        self.randomness = 0
        self.targets = 0
        self.saved_states = 0

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
            if func.attr == "play":
                self.plays.append(play_tokens(node))
            elif func.attr == "wait":
                value = literal(node.args[0]) if node.args else 1.0
                if value is not None:
                    self.waits.append(value)
        if isinstance(func, ast.Name):
            for name, classes in CONSTRUCTS.items():
                if func.id in classes:
                    self.constructs[name] += 1
            if func.id in UPDATER_FUNCS:
                self.updaters += 1
        if dotted(func).startswith(("np.random.", "random.")):
            self.randomness += 1
        if isinstance(func, ast.Attribute):
            for name, attrs in ATTR_CONSTRUCTS.items():
                if func.attr in attrs:
                    self.constructs[name] += 1
            # `mob.add_updater(f)`, and the builders `mob.always.next_to(...)`, `mob.f_always.set_x(...)`
            builder = isinstance(func.value, ast.Attribute) and func.value.attr in {"always", "f_always"}
            if func.attr in UPDATER_ATTRS or builder:
                self.updaters += 1
                if is_camera(func.value):
                    self.camera_updaters += 1
            if func.attr in COLOR_LINK_ATTRS:
                self.color_links += 1
            if func.attr == "generate_target":
                self.targets += 1
            if func.attr == "save_state":
                self.saved_states += 1
        if any(keyword.arg in COLOR_LINK_KEYWORDS for keyword in node.keywords):
            self.color_links += 1
        self.generic_visit(node)


def flags(scene: SceneSurvey) -> dict[str, int]:
    """Idiom flags of a scene, each with an intensity (how many plays or constructs carry it)."""
    categories = Counter(category(token) for play in scene.plays for token in play.tokens)
    tokens = Counter(token for play in scene.plays for token in play.tokens)
    staggered = sum(1 for play in scene.plays if play.staggered)
    result = {
        "parameter sweep": categories["tracker sweep"] + tokens["ChangeDecimalToValue"],
        "number readout tied to a value": scene.constructs["number readout"] if scene.updaters else 0,
        "morph": categories["morph"] + tokens["animate.become"],
        "rewrite with matching parts": categories["rewrite"],
        "derive by copy": categories["derive by copy"],
        "draw on": categories["draw on"],
        "fade": categories["fade"],
        "grow": categories["grow"],
        "staggered": staggered,
        "indicate": categories["indicate"] + (scene.constructs["surrounding box"] if categories["indicate"] else 0),
        "surrounding box": scene.constructs["surrounding box"],
        "brace": scene.constructs["brace"],
        "colour-linked terms": scene.color_links,
        "camera 2d": categories["camera 2d"],
        "camera 3d": categories["camera 3d"] + scene.camera_updaters,
        "ambient camera motion": scene.camera_updaters,
        "trail": scene.constructs["traced path"],
        "move along path": categories["move along path"],
        "space transform": categories["space transform"],
        "flow field": scene.constructs["field"],
        "passing flash": categories["passing flash"],
        "point cloud": scene.constructs["point cloud"],
        "dim others": tokens["animate.set_opacity"] + tokens["animate.fade"] + tokens["method.fade"],
        "rearrange to target": tokens["MoveToTarget"] if scene.targets else 0,
        "restore saved state": tokens["Restore"] if scene.saved_states else 0,
        "characters": categories["character"] + scene.constructs["character"],
        "axes or number line": scene.constructs["axes"],
        "surface": scene.constructs["surface"],
        "updaters": scene.updaters,
        "one value drives several objects": scene.updaters
        if scene.constructs["value tracker"] and scene.updaters >= 2
        else 0,
        "function graph": scene.constructs["function graph"],
        "area under graph": scene.constructs["area under graph"],
        "random samples": scene.randomness,
        "labels fixed in frame": scene.constructs["fixed in frame"],
        "arrow": scene.constructs["arrow"],
    }
    return {name: value for name, value in result.items() if value}


def era_of(year: int) -> str:
    return next(name for name, years in ERAS.items() if year in years)


def summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    quartiles = statistics.quantiles(values, n=4) if len(values) > 1 else [values[0]] * 3
    return {
        "n": len(values),
        "q1": quartiles[0],
        "median": statistics.median(values),
        "q3": quartiles[2],
        "mean": round(statistics.fmean(values), 3),
    }


def survey(root: Path) -> dict:
    eras: dict[str, dict] = {name: {"files": 0, "unparsed": 0, "scenes": 0, "plays": 0} for name in ERAS}
    tokens: dict[str, Counter[str]] = {name: Counter() for name in ERAS}
    categories: dict[str, Counter[str]] = {name: Counter() for name in ERAS}
    scene_flags: dict[str, Counter[str]] = {name: Counter() for name in ERAS}
    run_times: dict[str, list[float]] = defaultdict(list)
    single_plays: Counter[str] = Counter()  # single-category plays of 2023-2026, with or without a run time
    lag_ratios: list[float] = []
    rate_funcs: dict[str, Counter[str]] = {name: Counter() for name in ERAS}
    waits: list[float] = []
    plays_per_scene: list[int] = []
    scene_seconds: list[float] = []
    exemplars: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for path in sorted(root.glob("_20*/**/*.py")):
        year = int(path.relative_to(root).parts[0][1:5])
        era = era_of(year)
        eras[era]["files"] += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            eras[era]["unparsed"] += 1
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            scene = SceneSurvey()
            for statement in node.body:
                scene.visit(statement)
            if not scene.plays:
                continue
            eras[era]["scenes"] += 1
            eras[era]["plays"] += len(scene.plays)
            plays_per_scene.append(len(scene.plays))
            seconds = 0.0
            for play in scene.plays:
                tokens[era].update(play.tokens)
                kinds = {category(token) for token in play.tokens}
                categories[era].update(kinds)
                rate_funcs[era].update(play.rate_funcs)
                lag_ratios.extend(play.lag_ratios)
                duration = play.run_times[0] if play.run_times else 1.0
                seconds += duration
                if era == "2023-2026" and len(kinds) == 1:
                    single_plays[next(iter(kinds))] += 1
                    if play.run_times:
                        run_times[next(iter(kinds))].append(play.run_times[0])
            seconds += sum(scene.waits)
            scene_seconds.append(seconds)
            if era == "2023-2026":
                waits.extend(scene.waits)
            name = f"{path.relative_to(root)}::{node.name}"
            for flag, intensity in flags(scene).items():
                scene_flags[era][flag] += 1
                exemplars[flag].append((year * 10_000 + intensity, name))

    def per_thousand(counter: Counter[str], era: str) -> dict[str, float]:
        plays = eras[era]["plays"] or 1
        return {key: round(1000 * value / plays, 1) for key, value in counter.most_common()}

    def share(counter: Counter[str], era: str) -> dict[str, float]:
        scenes = eras[era]["scenes"] or 1
        return {key: round(100 * value / scenes, 1) for key, value in counter.most_common()}

    recent: dict[str, list[str]] = {}
    for flag, entries in exemplars.items():
        chosen, projects = [], set()
        # recent scenes first, the most intense within a year first, one per project
        for _, name in sorted(entries, key=lambda entry: (entry[0] // 10_000, entry[0] % 10_000), reverse=True):
            project = "/".join(name.split("/")[:2])
            if project in projects:
                continue
            projects.add(project)
            chosen.append(name)
            if len(chosen) == 8:
                break
        recent[flag] = chosen

    return {
        "eras": eras,
        "plays per scene": summary([float(n) for n in plays_per_scene]),
        "scene seconds (literal run times, default 1 s, plus waits)": summary(scene_seconds),
        "categories per 1000 plays": {era: per_thousand(categories[era], era) for era in ERAS},
        "top tokens per 1000 plays": {era: dict(list(per_thousand(tokens[era], era).items())[:60]) for era in ERAS},
        "scenes with idiom (%)": {era: share(scene_flags[era], era) for era in ERAS},
        "run time by category, single-category plays, 2023-2026": {
            name: {
                "explicit": summary(values),
                "share explicit (%)": round(100 * len(values) / single_plays[name], 1),
                "with default 1 s": summary(values + [1.0] * (single_plays[name] - len(values))),
            }
            for name, values in sorted(run_times.items())
            if len(values) >= 10
        },
        "lag ratios (all eras)": summary(lag_ratios),
        "waits, 2023-2026": summary(waits),
        "rate functions per 1000 plays": {era: per_thousand(rate_funcs[era], era) for era in ERAS},
        "exemplars (recent first, one per project)": recent,
    }


def main() -> None:
    warnings.filterwarnings("ignore", category=SyntaxWarning)  # the corpus's invalid escapes in TeX strings
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    result = {"corpus": "https://github.com/3b1b/videos", "commit": commit or None, **survey(root)}
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
