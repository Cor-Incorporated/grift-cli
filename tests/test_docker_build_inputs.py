"""The Docker build context names the same wheel inputs as pyproject.toml.

The first build of the Dockerfile failed with `Readme file does not exist:
README.en.md`. pyproject.toml names README.en.md as the package readme, while
the Dockerfile copied README.md and `.dockerignore` only let README.md through.
The same fact lived in three places (pyproject.toml, the build stage's COPY and
the .dockerignore allowlist) and only a Docker build could notice, which the
unit-test job never runs. This test reads all three, so a pyproject change that
the image does not follow is red in the ordinary suite.

The wheel inputs are derived from pyproject.toml (readme, version file, force-
included files, and every file under the wheel packages), not listed here, and
`.dockerignore` is read the way Docker reads it: the last pattern that matches a
path or one of its parents decides.

This is an early warning, not an emulator of Docker. It does not check where a
COPY puts a file, and it does not read every Dockerfile spelling. The ground
truth is the `docker` job in ci.yml, which builds the image and compares the
files inside its wheel with the tracked package files.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
PYPROJECT = ROOT / "pyproject.toml"
CI = ROOT / ".github" / "workflows" / "ci.yml"

# The Dockerfile as first written: pyproject.toml already named README.en.md.
README_MISMATCH_DOCKERFILE = (
    "FROM python:3.12-slim AS build\n"
    "COPY pyproject.toml README.md LICENSE ./\n"
    "COPY src ./src\n"
    "RUN python -m build --wheel --outdir /dist\n"
    "FROM python:3.12-slim\n"
    "COPY --from=build /dist/*.whl /tmp/\n"
)
README_MISMATCH_DOCKERIGNORE = "*\n!pyproject.toml\n!README.md\n!LICENSE\n!src/\n"


def _wheel_inputs(pyproject: str, root: Path) -> set[str]:
    """Paths the wheel build reads, taken from pyproject.toml and the checkout."""
    config = tomllib.loads(pyproject)
    readme = config["project"]["readme"]
    hatch = config["tool"]["hatch"]
    wheel = hatch["build"]["targets"]["wheel"]
    inputs = {
        "pyproject.toml",
        readme if isinstance(readme, str) else readme["file"],
        hatch["version"]["path"],
        *wheel.get("force-include", {}),
    }
    for package in wheel["packages"]:
        inputs |= {
            path.relative_to(root).as_posix()
            for path in (root / package).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
    # hatchling ships license files and honours .gitignore when they are present.
    return inputs | {name for name in ("LICENSE", ".gitignore") if (root / name).exists()}


def _build_stage_copy_sources(dockerfile: str) -> set[str]:
    """Sources of the COPY/ADD lines up to the wheel build (`COPY --from` is later)."""
    stage, found, _ = dockerfile.partition("RUN python -m build")
    assert found, "the wheel build line moved; this test reads the stage before it"
    sources: set[str] = set()
    for line in stage.replace("\\\n", " ").splitlines():
        words = line.split()
        if len(words) < 3 or words[0].upper() not in ("COPY", "ADD"):
            continue
        assert not words[1].startswith("["), "JSON-form COPY is not read by this test"
        arguments = [word for word in words[1:] if not word.startswith("--")]
        sources.update(name.rstrip("/") for name in arguments[:-1])
    return sources


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """A .dockerignore glob: `*` and `?` stay inside one path segment, `**` crosses them."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        elif pattern[i] == "[" and "]" in pattern[i:]:
            end = pattern.index("]", i)
            out, i = out + pattern[i : end + 1], end + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def _ignored(path: str, dockerignore: str) -> bool:
    """Docker's rule: the last pattern matching the path or one of its parents wins."""
    parts = path.split("/")
    candidates = ["/".join(parts[: depth + 1]) for depth in range(len(parts))]
    ignored = False
    for raw in dockerignore.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern = line.lstrip("!").strip().lstrip("/").removeprefix("./").rstrip("/")
        if any(_pattern_regex(pattern).match(candidate) for candidate in candidates):
            ignored = not line.startswith("!")
    return ignored


def docker_input_problems(
    *, pyproject: str, dockerfile: str, dockerignore: str, root: Path = ROOT
) -> list[str]:
    inputs = sorted(_wheel_inputs(pyproject, root))
    copied = _build_stage_copy_sources(dockerfile)
    problems = [
        f"Dockerfile build stage does not COPY {path.split('/')[0]}, which the wheel build reads"
        f" ({path}); it copies {sorted(copied)}"
        for path in inputs
        if path.split("/")[0] not in copied
    ]
    problems += [
        f".dockerignore drops {path}, which the wheel build reads"
        for path in inputs
        if _ignored(path, dockerignore)
    ]
    problems += [
        f".dockerignore drops {name}, which the Dockerfile copies"
        for name in sorted(copied)
        if _ignored(name, dockerignore)
    ]
    problems += [
        f"{name} is copied by the Dockerfile but is not in the checkout"
        for name in sorted(copied)
        if not (root / name).exists()
    ]
    return problems


def _problems(
    *,
    pyproject: str | None = None,
    dockerfile: str | None = None,
    dockerignore: str | None = None,
) -> list[str]:
    return docker_input_problems(
        pyproject=PYPROJECT.read_text(encoding="utf-8") if pyproject is None else pyproject,
        dockerfile=DOCKERFILE.read_text(encoding="utf-8") if dockerfile is None else dockerfile,
        dockerignore=(
            DOCKERIGNORE.read_text(encoding="utf-8") if dockerignore is None else dockerignore
        ),
    )


def test_docker_build_inputs_match_pyproject() -> None:
    readme = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["readme"]
    problems = _problems()
    assert not problems, f"pyproject.toml readme is {readme!r}: " + "; ".join(problems)


def test_the_first_dockerfile_is_reported_as_broken() -> None:
    # Pin the declaration side too: this must keep failing whatever the readme is today.
    pyproject = re.sub(
        r'(?m)^readme = ".*"$', 'readme = "README.en.md"', PYPROJECT.read_text(encoding="utf-8")
    )
    problems = _problems(
        pyproject=pyproject,
        dockerfile=README_MISMATCH_DOCKERFILE,
        dockerignore=README_MISMATCH_DOCKERIGNORE,
    )
    assert any("does not COPY README.en.md" in problem for problem in problems), problems
    assert any(".dockerignore drops README.en.md" in problem for problem in problems), problems


def test_a_removed_allow_line_is_reported() -> None:
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    without_readme = "\n".join(
        line for line in dockerignore.splitlines() if line.strip() != "!README.en.md"
    )
    assert without_readme != dockerignore, "the allowlist no longer names the package readme"
    problems = _problems(dockerignore=without_readme)
    assert any(".dockerignore drops README.en.md" in problem for problem in problems), problems


def test_an_exclusion_after_the_allow_lines_is_reported() -> None:
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    for later in (
        "README*",
        "/README.en.md",
        "src/tep_core",
        "src/tep_cli/**",
        "**/*.json",
        "src/tep_core/data/v2026.11/distributions.json",
    ):
        assert _problems(dockerignore=dockerignore + f"\n{later}\n"), f"{later!r} is not noticed"


def test_other_spellings_of_a_harmless_dockerignore_stay_green() -> None:
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    respelled = dockerignore.replace("!README.en.md", "!/README.en.md").replace(
        "!LICENSE", "! ./LICENSE"
    )
    assert respelled != dockerignore
    # `*` stays inside one segment: a top-level src/*.json hits nothing the wheel reads.
    assert not _problems(dockerignore=respelled + "\nsrc/*.json\n")


def test_a_dropped_license_copy_is_reported() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8").replace(" LICENSE", "", 1)
    problems = _problems(dockerfile=dockerfile)
    assert any("does not COPY LICENSE" in problem for problem in problems), problems


def test_copy_flags_continuations_and_add_are_read() -> None:
    dockerfile = (
        "FROM python:3.12-slim AS build\n"
        "copy --chown=1:1 pyproject.toml \\\n  README.en.md ./\n"
        "ADD LICENSE ./\n"
        "RUN python -m build --wheel\n"
    )
    assert _build_stage_copy_sources(dockerfile) == {"pyproject.toml", "README.en.md", "LICENSE"}


def test_ci_reads_the_version_from_the_hatch_version_path() -> None:
    version_path = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["hatch"]["version"][
        "path"
    ]
    job = CI.read_text(encoding="utf-8").split("\n  docker:\n", 1)[1]
    assert version_path in job, (
        f"the docker job does not read the version from {version_path!r}, the path"
        " pyproject.toml gives hatch"
    )
