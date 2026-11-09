#!/usr/bin/env bash
# Install manim8 from git, not editable, into an empty environment, as another tool would (ADR-043). The example
# family's render environment must take manim8-bridge and manim8-core from the same commit through uv git sources;
# then render the example twice with --json (the second a cache hit, with the same movie) and once under another
# published style. Usage: git_install_check.sh [WORK_DIR] [GIT_URL] [REF]; the defaults are a temporary directory,
# this checkout as a file:// URL, and its HEAD commit. PROFILE (default final) sets the render profile.
set -euo pipefail
work="${1:-$(mktemp -d)}"
url="${2:-file://$PWD}"
ref="${3:-$(git rev-parse HEAD)}"
profile="${PROFILE:-final}"
commit="$(git rev-parse "$ref^{commit}" 2>/dev/null || echo "$ref")"
mkdir -p "$work"
uv venv "$work/venv" --python 3.12
uv pip install --python "$work/venv/bin/python" "manim8 @ git+$url@$ref"
m8="$work/venv/bin/manim8"
check="$work/venv/bin/python"
cd "$work"
rm -rf ws
"$m8" workspace init ws --with-example
test -f ws/.gitignore && grep -qx "renders/" ws/.gitignore
family="ws/families/computational_neuroscience"
project="$family/divisive_normalization"
"$check" - "$family/pyproject.toml" "$url" "$commit" <<'PY'
import sys, tomllib
sources = tomllib.load(open(sys.argv[1], "rb"))["tool"]["uv"]["sources"]
for name, directory in (("manim8-bridge", "scianim_bridge"), ("manim8-core", "scianim_core")):
    want = {"git": sys.argv[2], "rev": sys.argv[3], "subdirectory": f"packages/{directory}"}
    assert sources[name] == want, (name, sources[name], want)
print("family sources: git at", sys.argv[3])
PY
"$m8" family env sync "$family"
"$m8" doctor --project "$project"
"$m8" codegen "$project"
"$m8" render "$project" --profile "$profile" --json > first.json
"$m8" render "$project" --profile "$profile" --json > second.json
"$m8" render "$project" --profile "$profile" --style default@0.5.0 --json > styled.json
"$check" - "$project" <<'PY'
import hashlib, json, sys
from pathlib import Path
project = Path(sys.argv[1])
first, second, styled = (json.loads(Path(name).read_text()) for name in ("first.json", "second.json", "styled.json"))
assert first["cache_hit"] is False and second["cache_hit"] is True, (first["cache_hit"], second["cache_hit"])
assert first["job"]["job_id"] == second["job"]["job_id"] and first["result"]["videos"] == second["result"]["videos"]
video = first["result"]["videos"][0]
assert abs(video["duration_seconds"] - first["job"]["output"]["duration_seconds"]) < 1e-6, video
assert hashlib.sha256((project / video["path"]).read_bytes()).hexdigest() == video["sha256"]
style = styled["job"]["resolved_style"]
assert (style["theme"], style["theme_version"]) == ("default", "0.5.0") and not styled["cache_hit"]
assert styled["job"]["cache_key"] != first["job"]["cache_key"]
print(f"render --json: {video['path']}, {video['duration_seconds']}s, {video['width_px']}x{video['height_px']}; "
      f"cache hit on the second run; --style rendered under default@0.5.0")
PY
echo "git install check passed for manim8 at $commit"
