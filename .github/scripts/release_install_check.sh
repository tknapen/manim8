#!/usr/bin/env bash
# Build the three wheels, install the control plane into an empty environment, and render from the installed
# `manim8` command with a family environment that takes the bridge from the built wheels (ADR-037). The local
# wheel directory stands in for the package index.
set -euo pipefail
work="${1:-$(mktemp -d)}"
mkdir -p "$work"
uv build --wheel -o "$work/dist" .
uv build --wheel -o "$work/dist" packages/scianim_core
uv build --wheel -o "$work/dist" packages/scianim_bridge
version="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
uv venv "$work/venv" --python 3.12
uv pip install --python "$work/venv/bin/python" --find-links "$work/dist" "manim8==$version"
export UV_FIND_LINKS="$work/dist"
cd "$work"
m8="$work/venv/bin/manim8"
"$m8" workspace init ws --with-example
"$m8" patterns check  # the pattern library and its recipe examples come from the wheel's data (ADR-040)
"$m8" skill install --to "$work/skills"  # the agent skill comes from the wheel too (ADR-042)
test -f "$work/skills/manim8/SKILL.md" && test ! -e "$work/skills/manim8/checkout.txt"
family="ws/families/computational_neuroscience"
project="$family/divisive_normalization"
grep -q "manim8-bridge==$version" "$family/pyproject.toml"
"$m8" family env sync "$family"
"$m8" doctor --project "$project"
"$m8" codegen "$project"
"$m8" snapshot "$project" --all
"$m8" render "$project" --profile storyboard --workers 2
echo "release install check passed for manim8 $version"
