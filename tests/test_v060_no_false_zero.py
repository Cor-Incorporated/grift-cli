"""R9 — an unmeasurable quantity must never be reported as an observed zero.

On a partial clone `git log --name-only` yields no paths. `surface_profile` and
`test_cochange` correctly report `not_observed / commit_paths_unavailable`, but
`context_profile` coerced the same missing input to zero and labelled it
`observed`:

    "surface_profile": {"kind": "not_observed", "reason": "commit_paths_unavailable"}
    "docs_share":      {"kind": "observed", "value": 0}

Across the 162-repository corpus this produced `test_file_ratio = 0` for
`pytest`, `pip` and `poetry`, and `docs_share = 0` for `curl`, which carries
1,090 documentation files. That is exactly what norms §1 forbids: absence of
data read as absence of the thing.

A zero measured from real paths is still a valid observation and must survive.
"""

from __future__ import annotations

import pytest

from tep_core.context_profile import build_context_profile
from tep_core.gitutil import GitCommit
from tep_core.origin import OriginResult

PATH_DEPENDENT = (
    "test_file_ratio",
    "docs_share",
    "language_composition",
    "dependency_manifests",
    "monorepo_markers",
)


def _commit(sha: str, files: tuple[str, ...], subject: str = "feat: work") -> GitCommit:
    return GitCommit(
        sha=sha,
        author_email="a@example.test",
        parents=(),
        date="2026-01-01",
        subject=subject,
        files=files,
        author_iso="2026-01-01T00:00:00+00:00",
        author_name="A",
    )


def _profile(commits, tmp_path):
    import subprocess

    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    return build_context_profile(tmp_path, commits, OriginResult())


@pytest.fixture
def pathless(tmp_path):
    """What a partial clone looks like: commits exist, no path list."""
    return _profile([_commit(f"{i:040x}", ()) for i in range(8)], tmp_path)


@pytest.fixture
def with_paths(tmp_path):
    """Real paths, none of which are docs or tests: a legitimate zero."""
    return _profile(
        [_commit(f"{i:040x}", (f"src/module_{i}.py",)) for i in range(8)],
        tmp_path,
    )


@pytest.mark.parametrize("field", PATH_DEPENDENT)
def test_path_dependent_fields_are_not_observed_without_paths(pathless, field: str) -> None:
    node = pathless[field]
    assert node["kind"] == "not_observed", (
        f"{field} claims an observation with no path data: {node}"
    )
    assert node["reason"] == "commit_paths_unavailable"


@pytest.mark.parametrize("field", ("test_file_ratio", "docs_share"))
def test_a_real_zero_is_still_an_observation(with_paths, field: str) -> None:
    """The fix must not turn a measured zero into not_observed."""
    node = with_paths[field]
    assert node["kind"] == "observed", f"{field} lost a legitimate zero: {node}"
    assert node["value"] == 0


def test_subject_derived_fields_still_observed_without_paths(pathless) -> None:
    """conventional_commit_share reads commit subjects, not paths."""
    assert pathless["conventional_commit_share"]["kind"] == "observed"


def test_no_nonmerge_population_is_not_observed(tmp_path) -> None:
    """Merges only: the non-merge denominator is empty, so a share is
    unmeasurable rather than zero."""
    merges = [
        GitCommit(
            sha=f"{i:040x}",
            author_email="a@example.test",
            parents=(f"{i + 100:040x}", f"{i + 200:040x}"),
            date="2026-01-01",
            subject="Merge branch 'x'",
            files=("src/a.py",),
            author_iso="2026-01-01T00:00:00+00:00",
            author_name="A",
        )
        for i in range(6)
    ]
    profile = _profile(merges, tmp_path)
    for field in ("conventional_commit_share", "issue_link_density"):
        node = profile[field]
        assert node["kind"] == "not_observed", f"{field} divided by nothing: {node}"
        assert node["reason"] == "no_nonmerge_commits"


def test_empty_history_is_wholly_not_observed(tmp_path) -> None:
    profile = _profile([], tmp_path)
    assert profile["kind"] == "not_observed"
    assert profile["reason"] == "no_human_commits"


def test_predicate_matches_surface_profile(tmp_path) -> None:
    """Both modules must decide 'paths unavailable' the same way (no drift)."""
    from tep_core.surface_profile import surface_profile

    commits = [_commit(f"{i:040x}", ()) for i in range(8)]
    surface = surface_profile(commits, empty_reason="no_commits")
    context = _profile(commits, tmp_path)
    assert surface["kind"] == "not_observed"
    assert surface["reason"] == context["docs_share"]["reason"], (
        "surface_profile and context_profile disagree on the missing-path reason:\n"
        f"  surface_profile: {surface['reason']}\n"
        f"  context_profile: {context['docs_share']['reason']}"
    )
