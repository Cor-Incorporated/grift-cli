"""The #50 turnover and tag-frequency rows, read from real repositories.

The fixture in test_ux50_context_display.py has one author in one year, and its
span, repo age and tag count coincide. Five regressions of report.py kept it
green (PR #112 review): the turnover row printing `joined` as `last_active`, the
tag row dividing by the repo age, a measured 0 tags/year shown as not observed,
a shallow clone's turnover reason replaced by an invented one, and a rate basis
printed from a report that does not carry it.

It also let a rate over a one-day span through: `3 tags / 1 days × 365.25 =
1095.75 tags/year`. A rate whose denominator is below MIN_POPULATION_FOR_RATE is
not shown (CONTRIBUTING.md §7), so a span shorter than that many days shows the
counts only. report.json is not changed by any of this.

Every case builds a git repository with fixed dates and reads the row through
analyze_repository and render_markdown, the report-v1 path that `grift analyze` and a bare
`grift report` take. `grift repo` renders report-v2, whose Markdown has no context rows
(nor had it before this change).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from git_fixture import commit, git, init_repo

from tep_cli.__main__ import main
from tep_core.analyze import analyze_repository
from tep_core.cochange import MIN_POPULATION_FOR_RATE
from tep_core.identity import empty_identity
from tep_core.lineage import Lineage
from tep_core.report import render_markdown

ALICE = "alice@example.com"
BOB = "bob@example.com"
BOT = "ci[bot]@users.noreply.github.com"
_PREFIX = {
    "actor_turnover": "- actor_turnover (actors/year): ",
    "release_cadence": "- tag frequency (release_cadence): ",
}
_BASIS = re.compile(
    r"^(?P<rate>\d+(?:\.\d+)?) tags/year \((?P<tags>\d+) tags / (?P<days>\d+) days × 365\.25\)$"
)


def _repo(path: Path, commits: list[tuple[str, str]], *, tags: int = 0) -> Path:
    repo = init_repo(path)
    for index, (email, day) in enumerate(commits):
        commit(repo, email=email, date=day, message=f"work {index}", filename=f"src/m{index}.py")
    for index in range(tags):
        git(repo, "tag", f"v{index}")
    return repo


def _report(repo: Path) -> dict[str, Any]:
    return analyze_repository(repo, empty_identity(), Lineage(), scope="repo")


def _row(markdown: str, key: str) -> str:
    """The value of one context row, without its bilingual gloss."""
    prefix = _PREFIX[key]
    lines = [line for line in markdown.splitlines() if line.startswith(prefix)]
    assert len(lines) == 1, f"expected one {key} row, found {lines}"
    return lines[0][len(prefix) :].split(" — ", 1)[0]


def _days_after(start: str, days: int) -> str:
    return (date.fromisoformat(start) + timedelta(days=days)).isoformat()


def test_turnover_row_prints_last_active_not_joined(tmp_path: Path) -> None:
    """Alice joins in 2024 and is last active in 2025; Bob joins in 2025."""
    repo = _repo(
        tmp_path / "repo",
        [(ALICE, "2024-12-01"), (BOB, "2025-01-20"), (ALICE, "2025-02-15")],
    )
    report = _report(repo)
    turnover = report["context_profile"]["actor_turnover"]
    assert turnover["value"] == {
        "2024": {"joined": 1, "last_active": 0},
        "2025": {"joined": 1, "last_active": 2},
    }, "fixture no longer separates first and last activity years"
    row = _row(render_markdown(report), "actor_turnover")
    assert row == "2024: joined 1, last_active 0; 2025: joined 1, last_active 2", (
        f"the row disagrees with report.json {turnover['value']}: {row!r}"
    )


def test_turnover_row_names_the_reason_a_shallow_clone_is_not_observed(tmp_path: Path) -> None:
    source = _repo(
        tmp_path / "source",
        [(ALICE, "2026-01-01"), (BOB, "2026-02-01"), (ALICE, "2026-03-12")],
        tags=2,
    )
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{source}", str(shallow)],
        check=True,
        capture_output=True,
    )
    report = _report(shallow)
    ctx = report["context_profile"]
    assert ctx["actor_turnover"] == {"kind": "not_observed", "reason": "history_incomplete"}
    markdown = render_markdown(report)
    turnover = _row(markdown, "actor_turnover")
    assert turnover == "not observed (history_incomplete)", (
        f"report.json says {ctx['actor_turnover']}, the row says {turnover!r}"
    )
    assert _row(markdown, "release_cadence") == "not observed (history_incomplete)"


def test_rate_divides_by_the_human_span_not_the_repo_age(tmp_path: Path) -> None:
    """A bot commit 30 days after the last human commit stretches the repo age only."""
    repo = _repo(
        tmp_path / "repo",
        [(ALICE, "2026-01-01"), (ALICE, "2026-03-12"), (BOT, "2026-04-11")],
        tags=7,
    )
    report = _report(repo)
    ctx = report["context_profile"]
    assert ctx["scale"]["active_span_days"]["value"] == 70
    assert ctx["repo_age_days"]["value"] == 100, "fixture no longer separates span and age"
    rate = ctx["release_cadence"]["value"]
    row = _row(render_markdown(report), "release_cadence")
    assert row == f"{rate} tags/year (7 tags / 70 days × 365.25)", row
    basis = _BASIS.match(row)
    assert basis, row
    recomputed = int(basis["tags"]) / int(basis["days"]) * 365.25
    assert abs(recomputed - float(basis["rate"])) < 0.006, (
        f"the row's own arithmetic does not hold: {row!r} recomputes to {recomputed:.4f}"
    )


def test_zero_tags_over_a_measured_span_is_a_measured_zero(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo", [(ALICE, "2026-01-01"), (ALICE, "2026-03-12")])
    report = _report(repo)
    assert report["context_profile"]["release_cadence"] == {
        "kind": "observed",
        "value": 0.0,
        "unit": "tags/year",
    }
    row = _row(render_markdown(report), "release_cadence")
    assert row == "0.0 tags/year (0 tags / 70 days × 365.25)", (
        f"0 tags over 70 days was measured; `not observed` means it could not be: {row!r}"
    )


_SHORT = f"(not annualized: span < {MIN_POPULATION_FOR_RATE} days)"


@pytest.mark.parametrize(
    ("span", "tags", "expected"),
    [
        pytest.param(0, 3, "not observed (zero_activity_span)", id="0-day"),
        pytest.param(1, 3, f"3 tags over 1 days {_SHORT}", id="1-day"),
        pytest.param(2, 1, f"1 tags over 2 days {_SHORT}", id="2-day"),
        pytest.param(
            MIN_POPULATION_FOR_RATE - 1,
            2,
            f"2 tags over {MIN_POPULATION_FOR_RATE - 1} days {_SHORT}",
            id="span-below-minimum",
        ),
        pytest.param(MIN_POPULATION_FOR_RATE, 2, None, id="span-at-minimum"),
    ],
)
def test_a_span_below_the_rate_minimum_is_not_annualized(
    tmp_path: Path, span: int, tags: int, expected: str | None
) -> None:
    assert MIN_POPULATION_FOR_RATE == 20, "the boundary ids and the docs name 20 days"
    first = "2026-01-01"
    repo = _repo(tmp_path / "repo", [(ALICE, first), (ALICE, _days_after(first, span))], tags=tags)
    report = _report(repo)
    ctx = report["context_profile"]
    assert ctx["scale"]["active_span_days"]["value"] == span
    rate = ctx["release_cadence"]["value"]
    if span:
        # report.json keeps the annualized value; only the Markdown row withholds it.
        assert rate == round(tags / (span / 365.25), 2)
    row = _row(render_markdown(report), "release_cadence")
    if expected is None:
        assert row == f"{rate} tags/year ({tags} tags / {span} days × 365.25)", row
    else:
        assert row == expected, f"{tags} tags over {span} days rendered as {row!r}"
        assert "tags/year" not in row


def test_a_report_json_without_the_rate_basis_renders_without_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`grift report <file>` re-renders any report.json, not only a fresh one.

    Every report grift writes carries `scale.tags` and `scale.active_span_days`
    next to `release_cadence`, and a shallow clone degrades all three together.
    A trimmed or hand-made file need not; the row must neither invent a basis nor
    show a rate it cannot check against the population rule.
    """
    repo = _repo(tmp_path / "repo", [(ALICE, "2026-01-01"), (ALICE, "2026-03-12")], tags=7)
    report = json.loads(json.dumps(_report(repo)))
    scale = report["context_profile"]["scale"]
    del scale["tags"], scale["active_span_days"]
    path = tmp_path / "trimmed.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert main(["report", str(path)]) == 0
    row = _row(capsys.readouterr().out, "release_cadence")
    assert row == "not annualized (no tag count or active_span_days in this report)", row


_NO_BASIS = "not annualized (no tag count or active_span_days in this report)"


def _rerender(tmp_path: Path, repo: Path, edit: Callable[[dict[str, Any]], object]) -> str:
    """Write the repository's report.json after `edit` changes its context_profile."""
    report = json.loads(json.dumps(_report(repo)))
    edit(report["context_profile"])
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("drop", ["tags", "active_span_days"])
def test_a_report_json_missing_one_half_of_the_rate_basis_renders_without_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], drop: str
) -> None:
    """Either half alone cannot check the rate: `None tags / 70 days` must not be shown."""
    repo = _repo(tmp_path / "repo", [(ALICE, "2026-01-01"), (ALICE, "2026-03-12")], tags=7)
    path = _rerender(tmp_path, repo, lambda ctx: ctx["scale"].pop(drop))
    assert main(["report", path]) == 0
    row = _row(capsys.readouterr().out, "release_cadence")
    assert row == _NO_BASIS, row


@pytest.mark.parametrize(
    "bad",
    [None, "70", [], {}, -5, True, 1.5, 70.0],
    ids=["None", "str", "list", "dict", "neg", "bool", "float", "whole-float"],
)
@pytest.mark.parametrize("field", ["tags", "active_span_days"])
def test_a_malformed_basis_value_renders_without_a_rate_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str, bad: object
) -> None:
    """`grift report <file>` is fed hand-edited files: only whole, non-negative ints are a basis.

    Both halves are checked, so `True tags / 70 days` is no more a basis than
    `2 tags / None days`. grift writes ints, so a float is no basis even when it
    is whole: `70.0` is rejected like `1.5`.
    """
    repo = _repo(tmp_path / "repo", [(ALICE, "2026-01-01"), (ALICE, "2026-03-12")], tags=2)

    def edit(ctx: dict[str, Any]) -> None:
        ctx["scale"][field]["value"] = bad

    assert main(["report", _rerender(tmp_path, repo, edit)]) == 0
    row = _row(capsys.readouterr().out, "release_cadence")
    assert row == _NO_BASIS, f"{field}={bad!r} rendered as {row!r}"


@pytest.mark.parametrize(
    ("path", "bad", "expected"),
    [
        pytest.param(("scale",), "x", _NO_BASIS, id="scale-str"),
        pytest.param(("scale",), [1], _NO_BASIS, id="scale-list"),
        pytest.param(("scale", "tags"), "x", _NO_BASIS, id="tags-str"),
        pytest.param(("scale", "active_span_days"), [70], _NO_BASIS, id="span-list"),
        pytest.param(("scale", "active_span_days"), 70, _NO_BASIS, id="span-int"),
        pytest.param(("release_cadence",), "x", "not observed (missing)", id="cadence-str"),
    ],
)
def test_a_node_that_is_not_an_object_renders_without_a_rate_instead_of_crashing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    path: tuple[str, ...],
    bad: object,
    expected: str,
) -> None:
    """A hand-edited report.json can put any JSON value where an object belongs.

    `grift report <file>` rendered these with rc 0 before the tag-frequency row
    read `scale`; reading them must not raise AttributeError on `.get`.
    """
    repo = _repo(tmp_path / "repo", [(ALICE, "2026-01-01"), (ALICE, "2026-03-12")], tags=2)
    *parents, leaf = path

    def edit(ctx: dict[str, Any]) -> None:
        node = ctx
        for key in parents:
            node = node[key]
        node[leaf] = bad

    assert main(["report", _rerender(tmp_path, repo, edit)]) == 0
    row = _row(capsys.readouterr().out, "release_cadence")
    assert row == expected, f"{'.'.join(path)}={bad!r} rendered as {row!r}"


def test_the_short_span_test_uses_the_human_span_not_the_repo_age(tmp_path: Path) -> None:
    """A bot commit 40 days on stretches the repo age to 45 days; the human span stays 5."""
    repo = _repo(
        tmp_path / "repo",
        [(ALICE, "2026-01-01"), (ALICE, "2026-01-06"), (BOT, "2026-02-15")],
        tags=2,
    )
    report = _report(repo)
    ctx = report["context_profile"]
    assert ctx["scale"]["active_span_days"]["value"] == 5
    assert ctx["repo_age_days"]["value"] >= MIN_POPULATION_FOR_RATE, (
        "fixture no longer separates them"
    )
    assert _row(render_markdown(report), "release_cadence") == f"2 tags over 5 days {_SHORT}"


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        pytest.param("x", "not observed (missing)", id="node-str"),
        pytest.param(
            {"kind": "observed", "value": [1]}, "not observed (malformed)", id="value-list"
        ),
        pytest.param(
            {"kind": "observed", "value": {"2026": "x"}}, "not observed (malformed)", id="row-str"
        ),
        pytest.param(
            {"kind": "observed", "value": {"2026": {"joined": 1, "last_active": 2}}},
            "2026: joined 1, last_active 2",
            id="well-formed",
        ),
        pytest.param(
            {"kind": "observed", "value": {"2025": {"joined": 1, "last_active": 1}, "2026": "x"}},
            "not observed (malformed)",
            id="later-row-str",
        ),
        pytest.param(
            {"kind": "observed", "value": {"2025": "x", "2026": {"joined": 1, "last_active": 1}}},
            "not observed (malformed)",
            id="earlier-row-str",
        ),
        pytest.param(
            {"kind": "observed", "value": []}, "not observed (malformed)", id="empty-list"
        ),
        pytest.param({"kind": "observed"}, "not observed (malformed)", id="value-missing"),
        pytest.param(
            {"kind": "observed", "value": None}, "not observed (malformed)", id="value-null"
        ),
        pytest.param({"kind": "observed", "value": 0}, "not observed (malformed)", id="value-zero"),
        pytest.param(
            {"kind": "observed", "value": ""}, "not observed (malformed)", id="value-empty-str"
        ),
        pytest.param(
            {"kind": "observed", "value": False}, "not observed (malformed)", id="value-false"
        ),
        pytest.param(
            {"kind": "observed", "value": {}}, "not observed (no_human_commits)", id="empty-dict"
        ),
    ],
)
def test_a_malformed_turnover_node_renders_without_crashing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    replacement: object,
    expected: str,
) -> None:
    """The turnover row is new in this change, so main rendered these files with rc 0 without it."""
    repo = _repo(tmp_path / "repo", [(ALICE, "2026-01-01"), (ALICE, "2026-03-12")], tags=2)

    def edit(ctx: dict[str, Any]) -> None:
        ctx["actor_turnover"] = replacement

    assert main(["report", _rerender(tmp_path, repo, edit)]) == 0
    assert _row(capsys.readouterr().out, "actor_turnover") == expected
