"""README entry points: language switch, PyPI-safe links, project URLs.

PyPI renders the file named by ``[project].readme`` with no repository around it,
so a relative link there points at pypi.org and breaks. The English README is
that file; these tests bind the declaration in pyproject.toml to the README's
actual links, and every link that points into this repository to a file and
heading that exist.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_BLOB = "https://github.com/Cor-Incorporated/grift-cli/blob/main/"
README_JA = ROOT / "README.md"
README_EN = ROOT / "README.en.md"
DOCS_LINKED_FROM_READMES = (
    README_JA,
    README_EN,
    ROOT / "docs" / "usage.md",
    ROOT / "docs" / "en" / "usage.md",
    ROOT / "docs" / "validation.md",
    ROOT / "docs" / "en" / "validation.md",
)
REQUIRED_PROJECT_URLS = (
    "Homepage",
    "Documentation",
    "Japanese README",
    "Changelog",
    "Source",
    "Issues",
)
_LINK = re.compile(r"(?<!\\)\[[^\]]*\]\(([^)\s]+)\)")
_REFERENCE_LINK = re.compile(r"(?m)^ {0,3}\[[^\]]+\]:\s*<?([^>\s]+)>?")
_HTML_LINK = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
# The design table moved from the READMEs to the validation guides; these limits
# must stay next to the reproducibility claim the READMEs make.
DESIGN_BOUNDARIES = {
    ROOT / "docs" / "validation.md": (
        "定義版や入力revisionが変われば結果も変わる",
        "再現できることは、数値の正しさ・品質・優秀さの証明ではない",
        "private履歴やgit外の成果を補完・推測しない",
    ),
    ROOT / "docs" / "en" / "validation.md": (
        "A new definition version or input revision can change it",
        "Reproducibility is not proof of correctness, quality, or superiority",
        "Private history and outcomes outside git are not filled in or inferred",
    ),
    README_JA: ("同じ値が出ることは、値の正しさや、仕事の質や優秀さの証明にはなりません",),
    README_EN: ("Getting the same number again is not proof that the number is correct",),
}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _links(path: Path) -> list[str]:
    """Inline, reference-style and HTML links outside code fences."""
    text = _FENCE.sub("", path.read_text(encoding="utf-8"))
    return [*_LINK.findall(text), *_REFERENCE_LINK.findall(text), *_HTML_LINK.findall(text)]


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    text = _FENCE.sub("", path.read_text(encoding="utf-8"))
    return {_slug(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")}


def _local_target(source: Path, link: str) -> tuple[Path, str] | None:
    """Resolve a link into this repository, or None for an external URL."""
    target, _, anchor = link.partition("#")
    if target.startswith(REPO_BLOB):
        return ROOT / target.removeprefix(REPO_BLOB), anchor
    if re.match(r"^[a-z]+:", target):
        return None
    if not target:
        return source, anchor
    return (source.parent / target).resolve(), anchor


def test_pypi_readme_is_the_english_readme() -> None:
    assert _pyproject()["project"]["readme"] == "README.en.md"


def test_pypi_readme_has_only_absolute_links() -> None:
    readme = ROOT / _pyproject()["project"]["readme"]
    relative = [link for link in _links(readme) if not link.startswith("https://")]
    assert not relative, (
        f"{readme.name} is the PyPI description; these links break there: {relative}"
    )


@pytest.mark.parametrize(
    ("readme", "other", "own_label"),
    [(README_JA, README_EN, "**日本語**"), (README_EN, README_JA, "**English**")],
)
def test_readme_first_line_switches_language(readme: Path, other: Path, own_label: str) -> None:
    first = readme.read_text(encoding="utf-8").splitlines()[0]
    assert own_label in first, f"{readme.name} line 1 is {first!r}"
    assert f"]({REPO_BLOB}{other.name})" in first, (
        f"{readme.name} line 1 must link {other.name} by absolute URL; got {first!r}"
    )


def test_project_urls_are_complete_and_resolve() -> None:
    urls = _pyproject()["project"]["urls"]
    missing = [key for key in REQUIRED_PROJECT_URLS if key not in urls]
    assert not missing, f"project.urls is missing {missing}; has {sorted(urls)}"
    assert urls["Homepage"] == "https://griftai.org"
    for key, url in urls.items():
        assert url.startswith("https://"), f"project.urls[{key!r}] = {url!r}"
        if url.startswith(REPO_BLOB):
            path = ROOT / url.removeprefix(REPO_BLOB)
            assert path.is_file(), f"project.urls[{key!r}] -> {url} has no file {path}"


@pytest.mark.parametrize("doc", DOCS_LINKED_FROM_READMES, ids=lambda p: str(p.relative_to(ROOT)))
def test_links_into_the_repository_resolve(doc: Path) -> None:
    broken: list[str] = []
    for link in _links(doc):
        resolved = _local_target(doc, link)
        if resolved is None:
            continue
        path, anchor = resolved
        if not path.exists():
            broken.append(f"{link} (no file {path})")
        elif anchor and path.suffix == ".md" and anchor not in _anchors(path):
            broken.append(f"{link} (no heading #{anchor} in {path.name})")
    assert not broken, f"{doc.relative_to(ROOT)} has broken links: {broken}"


@pytest.mark.parametrize("readme", [README_JA, README_EN], ids=lambda p: p.name)
def test_readme_links_to_moved_details_instead_of_carrying_release_notes(readme: Path) -> None:
    text = readme.read_text(encoding="utf-8")
    release_headings = re.findall(r"(?m)^## (?:v\d+\.\d+|What v\d+\.\d+).*$", text)
    assert not release_headings, (
        f"{readme.name} carries release notes {release_headings}; link CHANGELOG.md instead"
    )
    usage = "docs/en/usage.md" if readme == README_EN else "docs/usage.md"
    validation = "docs/en/validation.md" if readme == README_EN else "docs/validation.md"
    for target in (usage, validation, "CHANGELOG.md"):
        assert target in text, f"{readme.name} does not link {target}"


@pytest.mark.parametrize(
    ("doc", "fragments"), DESIGN_BOUNDARIES.items(), ids=lambda v: getattr(v, "name", "")
)
def test_design_boundaries_stay_documented(doc: Path, fragments: tuple[str, ...]) -> None:
    text = doc.read_text(encoding="utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    assert not missing, f"{doc.relative_to(ROOT)} lost the design boundaries {missing}"
