"""W4 — how common a library is, reported beside the person and never inside.

The axis exists because "introduced asyncpg" means little without knowing
whether asyncpg is everywhere or almost nowhere. It is deliberately weaker than
it could be: it describes libraries, states a corpus that is openly a
convenience sample, and refuses to speak at all where the corpus cannot
support it.

Three refusals carry the design, and each has a test that fails if it is
relaxed:

* absence in the corpus must never read as rarity (norms §1)
* an ecosystem below the minimum must refuse, not caveat
* no aggregate over the set may exist, because an aggregate is a number about
  the person (norms §7)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tep_core.prevalence import (
    ABSENT_REASON,
    AMBIGUOUS_REASON,
    MIN_CORPUS_REPOSITORIES,
    PREVALENCE_VERSION,
    SMALL_CORPUS_REASON,
    UNKNOWN_ECOSYSTEM_REASON,
    library_context,
    library_prevalence,
    load_table,
    table_path,
)

SCHEMA = Path(__file__).resolve().parents[1] / "src/tep_core/schemas/v060-contracts.schema.json"


def _pypi(name: str) -> dict:
    return library_prevalence(name, ecosystems=["pypi"])


# --------------------------------------------------------------------------
# The table is bundled, pinned, and describes its own limits
# --------------------------------------------------------------------------


def test_the_table_ships_with_the_package() -> None:
    assert table_path().is_file(), (
        f"the pinned prevalence table is missing; lookup would silently degrade "
        f"to not_observed for every library: {table_path()}"
    )


def test_the_corpus_states_that_it_is_not_a_market() -> None:
    """An artifact that travels must carry its own caveat (norms §6)."""
    corpus = load_table()["corpus"]
    text = " ".join(corpus["limitations"]).lower()
    assert "not a market" in text or "not a sample of the software industry" in text, text
    assert "not evidence that it is rare" in text, text
    assert corpus["repositories_scanned"] > 0


def test_ecosystems_are_counted_separately() -> None:
    """A share over every repository would count projects that could not declare it."""
    ecosystems = load_table()["ecosystems"]
    assert len(ecosystems) > 1
    for name, block in ecosystems.items():
        assert block["repositories"] > 0, name
        for library, count in block["libraries"].items():
            assert count <= block["repositories"], (
                f"{name}/{library} is declared by {count} of {block['repositories']} "
                "repositories, which is impossible"
            )


# --------------------------------------------------------------------------
# Refusal 1: absence is not rarity
# --------------------------------------------------------------------------


def test_a_library_absent_from_the_corpus_is_not_observed() -> None:
    result = _pypi("a-package-nobody-in-this-corpus-declares")
    assert result["kind"] == "not_observed"
    assert result["reason"] == ABSENT_REASON


def test_absence_never_produces_a_share() -> None:
    """A zero share would turn 'we did not see it' into 'almost nobody uses it'."""
    result = _pypi("a-package-nobody-in-this-corpus-declares")
    assert "share" not in result, result
    assert "declaring_repositories" not in result, result


def test_absence_says_in_words_that_it_is_not_rarity() -> None:
    text = " ".join(_pypi("a-package-nobody-in-this-corpus-declares")["limitations"]).lower()
    assert "not evidence that the library is rare" in text, text


# --------------------------------------------------------------------------
# Refusal 2: a corpus too small refuses outright
# --------------------------------------------------------------------------


def test_an_ecosystem_below_the_minimum_refuses() -> None:
    table = load_table()
    small = [
        name
        for name, block in table["ecosystems"].items()
        if block["repositories"] < MIN_CORPUS_REPOSITORIES
    ]
    assert small, "no ecosystem is below the minimum; this test proves nothing here"
    ecosystem = small[0]
    library = next(iter(table["ecosystems"][ecosystem]["libraries"]))
    result = library_prevalence(library, ecosystems=[ecosystem])
    assert result["kind"] == "not_observed"
    assert result["reason"] == SMALL_CORPUS_REASON, (
        f"{ecosystem} has {table['ecosystems'][ecosystem]['repositories']} repositories "
        f"and still reported a share for {library}"
    )


def test_an_ecosystem_above_the_minimum_reports() -> None:
    table = load_table()
    large = [
        name
        for name, block in table["ecosystems"].items()
        if block["repositories"] >= MIN_CORPUS_REPOSITORIES
    ]
    assert large, "no ecosystem is large enough; the table cannot answer anything"
    ecosystem = large[0]
    library = next(iter(table["ecosystems"][ecosystem]["libraries"]))
    result = library_prevalence(library, ecosystems=[ecosystem])
    assert result["kind"] == "observed"
    assert 0.0 < result["share"] <= 1.0
    assert result["declaring_repositories"] <= result["corpus_repositories"]


def test_a_missing_table_version_degrades_instead_of_inventing() -> None:
    result = library_prevalence("anything", ecosystems=["pypi"], version="v1999.01")
    assert result["kind"] == "not_observed"


# --------------------------------------------------------------------------
# Refusal 3: nothing aggregates the set into a number about the person
# --------------------------------------------------------------------------

FORBIDDEN = {
    "score",
    "rank",
    "rating",
    "percentile",
    "mean_share",
    "average_share",
    "total_share",
    "rarity",
    "rare_count",
    "seniority",
    "level",
    "band",
}


def test_no_aggregate_over_the_libraries_is_emitted() -> None:
    context = library_context(
        ["pytest", "click", "jinja2"],
        ecosystems_by_name={n: ["pypi"] for n in ("pytest", "click", "jinja2")},
    )
    assert FORBIDDEN.isdisjoint(context), sorted(FORBIDDEN & set(context))
    for entry in context["libraries"].values():
        assert FORBIDDEN.isdisjoint(entry), sorted(FORBIDDEN & set(entry))


def test_the_schema_forbids_an_aggregate_being_added_later() -> None:
    """additionalProperties false is what keeps this true after I stop looking."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    block = schema["$defs"]["report_library_context"]["oneOf"][0]
    assert block["additionalProperties"] is False
    assert FORBIDDEN.isdisjoint(block["properties"]), sorted(FORBIDDEN & set(block["properties"]))


def test_the_block_says_it_describes_libraries_not_the_actor() -> None:
    context = library_context(["pytest"], ecosystems_by_name={"pytest": ["pypi"]})
    text = " ".join(context["limitations"]).lower()
    assert "describe libraries, not the actor" in text, text
    assert "never combined" in text, text


# --------------------------------------------------------------------------
# Ecosystem resolution is stated, never guessed
# --------------------------------------------------------------------------


def test_a_name_in_two_ecosystems_is_ambiguous_not_guessed() -> None:
    result = library_prevalence("pytest", ecosystems=["pypi", "npm"])
    assert result["kind"] == "not_observed"
    assert result["reason"] == AMBIGUOUS_REASON


def test_a_name_with_no_ecosystem_is_not_looked_up() -> None:
    result = library_prevalence("pytest", ecosystems=[])
    assert result["kind"] == "not_observed"
    assert result["reason"] == UNKNOWN_ECOSYSTEM_REASON


def test_an_empty_set_of_names_is_not_observed() -> None:
    context = library_context([], ecosystems_by_name={})
    assert context["kind"] == "not_observed"
    assert context["reason"] == "no_introduced_dependencies"


# --------------------------------------------------------------------------
# Determinism: the pinned version is what pins the answer
# --------------------------------------------------------------------------


def test_repeated_lookup_is_identical() -> None:
    first = library_context(
        ["pytest", "click"], ecosystems_by_name={"pytest": ["pypi"], "click": ["pypi"]}
    )
    second = library_context(
        ["click", "pytest"], ecosystems_by_name={"pytest": ["pypi"], "click": ["pypi"]}
    )
    assert first == second, "lookup depends on input order"


def test_the_emitted_version_matches_the_pinned_one() -> None:
    context = library_context(["pytest"], ecosystems_by_name={"pytest": ["pypi"]})
    assert context["prevalence_version"] == PREVALENCE_VERSION
    assert load_table()["prevalence_version"] == PREVALENCE_VERSION, (
        "the bundled table and the pinned constant disagree; a report would "
        "name a version it did not use"
    )


# --------------------------------------------------------------------------
# Declaration <-> enforcement
# --------------------------------------------------------------------------


def test_the_schema_accepts_every_shape_the_module_emits() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    definition = {**schema["$defs"]["report_library_context"], "$defs": schema["$defs"]}
    shapes = [
        library_context(["pytest"], ecosystems_by_name={"pytest": ["pypi"]}),
        library_context(
            ["pytest", "a-package-nobody-in-this-corpus-declares"],
            ecosystems_by_name={
                "pytest": ["pypi"],
                "a-package-nobody-in-this-corpus-declares": ["pypi"],
            },
        ),
        library_context([], ecosystems_by_name={}),
    ]
    for shape in shapes:
        jsonschema.validate(shape, definition)


def test_a_contribution_never_carries_the_library_names(tmp_path: Path) -> None:
    """The set of libraries a person chose is about that person.

    Prevalence describes libraries and is safe to show the actor. The *set* one
    actor introduced is not: published alongside a repository it narrows who the
    contributor is, and `contribute` exists to widen that, not narrow it.
    `metrics` was assembled by denylist until this change, so a new top-level
    report key rode along by default; `library_context` did exactly that when
    first wired up, and this test is what caught it. A fully observed block is
    injected here rather than relying on the field happening to be not_observed
    at repo scope -- a guard that is never exercised is not a guard.
    """
    from tep_core.analyze import analyze_repository
    from tep_core.contribute import build_contribution
    from tep_core.identity import empty_identity
    from tep_core.lineage import Lineage

    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    for index in range(24):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )
    report = analyze_repository(repo, empty_identity(), Lineage(), scope="repo")

    # Names chosen so a hit cannot come from `test_frameworks`, which legitimately
    # reports detected frameworks such as pytest by name.
    injected = ("click", "jinja2")
    report["library_context"] = library_context(
        injected, ecosystems_by_name={n: ["pypi"] for n in injected}
    )
    assert report["library_context"]["kind"] == "observed", "the guard was not exercised"

    payload = json.dumps(build_contribution(report), ensure_ascii=False)
    assert "library_context" not in payload
    for name in injected:
        assert f'"{name}"' not in payload, f"{name} reached a contribution payload"


def test_every_report_key_is_classified(tmp_path: Path) -> None:
    """A new report field must be published or withheld on purpose, not by default.

    The failure this prevents is silent: under the old denylist, adding a
    top-level observation shipped it to every contribution recipient with no
    diff in `contribute.py` to review. This fails on the next unclassified key
    and names it, so the decision happens once, deliberately, here.
    """
    from tep_core.analyze import analyze_repository
    from tep_core.contribute import _METRICS_ALLOWED, _WITHHELD_TOP_LEVEL
    from tep_core.identity import empty_identity
    from tep_core.lineage import Lineage

    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "repo")
    for index in range(24):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-05",
            message=f"feat: {index}",
            filename="app.py",
        )

    classified = _METRICS_ALLOWED | _WITHHELD_TOP_LEVEL
    assert not (_METRICS_ALLOWED & _WITHHELD_TOP_LEVEL), sorted(
        _METRICS_ALLOWED & _WITHHELD_TOP_LEVEL
    )
    for scope in ("repo", "tenant"):
        report = analyze_repository(repo, empty_identity(), Lineage(), scope=scope)
        unclassified = sorted(set(report) - classified)
        assert not unclassified, (
            f"{scope}-scope report carries {unclassified}, which is in neither "
            "_METRICS_ALLOWED nor _WITHHELD_TOP_LEVEL. Decide whether a "
            "contribution recipient should see it before it ships."
        )


def test_report_v2_permits_the_key() -> None:
    """The key list and the schema are separate gates; both must admit it."""
    from tep_core import schema_v2

    allowed = next(
        value
        for name, value in vars(schema_v2).items()
        if name.startswith("_REPORT_V2") and isinstance(value, frozenset) and "experience" in value
    )
    assert "library_context" in allowed


# --------------------------------------------------------------------------
# End to end: an npm manifest, through the CLI, out the other side
# --------------------------------------------------------------------------
#
# Everything above reads the table or calls `library_prevalence` directly. The
# axis had only ever been exercised against pypi manifests in this repository
# itself, so nothing proved that an npm ecosystem reaches the report: the
# manifest parser, the introduction collector, the ecosystem tag and the table
# lookup are four separate pieces and only the last was covered.


NPM_LIBRARIES = ("react", "zod", "typescript", "vitest")
ABSENT_LIBRARY = "this-library-does-not-exist-anywhere"


def _npm_actor_report(tmp_path: Path) -> dict:
    """A repository whose only manifest is `package.json`, read as one actor."""
    from tep_cli.__main__ import main

    from git_fixture import commit, init_repo

    repo = init_repo(tmp_path / "npm-repo")
    commit(
        repo,
        email="alice@example.com",
        date="2026-01-01",
        message="chore: init",
        filename="README.md",
        name="Alice",
    )
    manifest = {
        "name": "syn",
        "version": "1.0.0",
        "dependencies": {"react": "^18.0.0", "zod": "^3.0.0"},
        "devDependencies": {
            "typescript": "^5.0.0",
            "vitest": "^2.0.0",
            ABSENT_LIBRARY: "^1.0.0",
        },
    }
    commit(
        repo,
        email="alice@example.com",
        date="2026-01-02",
        message="feat: declare npm dependencies",
        filename="package.json",
        content=json.dumps(manifest),
        name="Alice",
    )
    # The introduction metric has a population floor; below it the axis reports
    # insufficient_population and never reaches the table at all.
    for index in range(3, 27):
        commit(
            repo,
            email="alice@example.com",
            date=f"2026-01-{index:02d}",
            message=f"feat: work {index}",
            filename="src/app.ts",
            name="Alice",
        )
    identity = tmp_path / "identity.toml"
    identity.write_text(
        'schema_version = "identity-v2"\n\n'
        "[[actors]]\n"
        'canonical_id = "alice"\n'
        'emails = ["alice@example.com"]\n'
        'attribution_state = "verified"\n'
        'consent = "recorded-explicit-consent"\n'
        'authority = "subject-authorization"\n',
        encoding="utf-8",
    )
    out = tmp_path / "actor.json"
    assert (
        main(
            [
                "actor",
                "alice",
                str(repo),
                "--identity",
                str(identity),
                "--format",
                "json",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    return json.loads(out.read_text(encoding="utf-8"))


def test_an_npm_manifest_reaches_the_axis_with_its_ecosystem(tmp_path: Path) -> None:
    context = _npm_actor_report(tmp_path)["library_context"]
    assert context["kind"] == "observed", context
    for name in NPM_LIBRARIES:
        entry = context["libraries"][name]
        assert entry["kind"] == "observed", entry
        assert entry["ecosystem"] == "npm", entry
        assert 0.0 < entry["share"] <= 1.0, entry
        assert entry["declaring_repositories"] <= entry["corpus_repositories"], entry


def test_an_npm_name_absent_from_the_corpus_still_names_its_ecosystem(tmp_path: Path) -> None:
    """Absence must not lose the ecosystem: a reader told only "not observed"
    cannot tell a missing lookup from a missing library (norms §1)."""
    entry = _npm_actor_report(tmp_path)["library_context"]["libraries"][ABSENT_LIBRARY]
    assert entry["kind"] == "not_observed"
    assert entry["reason"] == ABSENT_REASON
    assert entry["ecosystem"] == "npm", entry
    assert "share" not in entry, entry
