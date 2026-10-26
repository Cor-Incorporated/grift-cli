"""Doc enum/regex parity with implementation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tep_cli.options import build_parser
from tep_core.identity import CANONICAL_ID_PATTERN
from tep_core.schema_v2 import validate_alignment, validate_report_v2
from tep_core.v2_constants import ROLE_LENSES, SURFACES, VERIFICATION_TYPES

ROOT = Path(__file__).resolve().parents[1]


def _fences(path: Path, lang: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(rf"```{lang}\n(.*?)```", text, re.DOTALL)


def test_project_schema_enums_in_docs() -> None:
    text = (ROOT / "docs" / "project-schema.md").read_text(encoding="utf-8")
    for name in SURFACES:
        assert name in text
    for name in VERIFICATION_TYPES:
        assert name in text
    for name in ROLE_LENSES:
        assert name in text
    assert CANONICAL_ID_PATTERN in text or "canonical_id" in text


def test_report_v2_example_validates() -> None:
    blocks = _fences(ROOT / "docs" / "report-v2.md", "json")
    assert blocks
    payload = json.loads(blocks[0])
    errors = validate_report_v2(payload)
    # example is a subset; additive validator may still require sections
    assert payload["schema_version"] == "report-v2"
    assert "score" not in payload
    assert isinstance(errors, list)


def test_alignment_example_has_no_verdict_keys() -> None:
    blocks = _fences(ROOT / "docs" / "alignment-schema.md", "json")
    assert blocks
    payload = json.loads(blocks[0])
    errors = validate_alignment(payload)
    assert errors == []
    assert "score" not in payload
    assert "overall" not in payload


def test_project_toml_example_has_schema() -> None:
    blocks = _fences(ROOT / "docs" / "project-schema.md", "toml")
    assert blocks
    assert 'schema_version = "tep-project-v1"' in blocks[0]


def test_actor_basis_docs_and_help_are_fail_closed_and_bilingual() -> None:
    docs = {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            # The actor-basis paragraph moved from the READMEs to the usage guides.
            "docs/usage.md",
            "docs/en/usage.md",
            "docs/norms.md",
            "docs/en/norms.md",
            "docs/report-v2.md",
        )
    }
    for relative, text in docs.items():
        for state in ("claimed", "verified", "inferred", "external", "unknown"):
            assert state in text, f"{relative} does not document actor basis {state!r}"

    assert "本人向け表示、`verified` は管理権限に基づく非本人向け表示" in docs["docs/usage.md"]
    assert "Only explicit `claimed` gets personal-view wording" in docs["docs/en/usage.md"]
    assert "only basis that gets personal-view" in docs["docs/en/norms.md"]
    for path in ("docs/norms.md", "docs/en/norms.md"):
        assert "--all" in docs[path]
        assert "--top N" in docs[path]
        assert "mutually exclusive" in docs[path] or "排他" in docs[path]
        assert "quality rank" in docs[path] or "品質rank" in docs[path]
    assert "対象にできるのは1つの canonical_idだけ" not in docs["docs/norms.md"]
    assert "observes one `canonical_id`" not in docs["docs/en/norms.md"]
    assert "本人向け表示" in docs["docs/report-v2.md"]

    stale_claims = (
        "canonical_id の本人証拠（report-v2, tenant）",
        "from a consenting identity",
        "subject basisに応じて2種類",
        "同意済みtenant観測",
    )
    joined = "\n".join(docs.values())
    for claim in stale_claims:
        assert claim not in joined

    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    top_help = parser.format_help()
    actor_help = choices["actor"].format_help()
    align_help = choices["align"].format_help()
    assert "Actor basis may be public, claimed" in top_help
    assert "basis-aware detailed report" in actor_help
    assert "not consent proof" in actor_help
    assert "missing/contradictory basis fails closed" in align_help
    assert "Use a consenting identity for actor views" not in "\n".join(
        (top_help, actor_help, align_help)
    )


# --- 0.8.0 #3: TEP expansion and the site-term glossary -----------------------
#
# The public site (griftai.org / cor-jp.com) names observations in Japanese
# (検査値 / テスト併修率 / 手戻り率 / 磨き直し / コードの新しさ); the CLI names them in
# English with report-v1 JSON keys. The one correspondence table lives in
# docs/metrics-guide.md. These tests bind the declared side (the table) to the
# enforced side (a report-v1 produced from a real git repository) so that
# editing either without the other fails and names both values.

GLOSSARY_HEADING = "## サイトの訳語と CLI の語の対応表"
GLOSSARY_ANCHOR = "metrics-guide.md#サイトの訳語と-cli-の語の対応表"
TEP_EXPANSIONS = ("TEP（Technical Evidence Pipeline）", "TEP (Technical Evidence Pipeline)")
SITE_TERMS = frozenset({"検査値", "テスト併修率", "手戻り率", "磨き直し", "コードの新しさ"})
DOCS_LINKING_TO_GLOSSARY = ("README.md", "README.en.md", "docs/en/metrics-guide.md")
DOCS_THAT_MUST_NOT_COPY_GLOSSARY = (
    "README.md",
    "README.en.md",
    "docs/usage.md",
    "docs/en/usage.md",
    "docs/validation.md",
    "docs/en/validation.md",
    "docs/norms.md",
    "docs/en/norms.md",
    "docs/en/metrics-guide.md",
    "docs/report-v2.md",
    "docs/report-schema.md",
)
DOCS_EXPANDING_TEP_AT_FIRST_MENTION = (
    "README.md",
    "README.en.md",
    "docs/usage.md",
    "docs/en/usage.md",
    "docs/norms.md",
    "docs/en/norms.md",
    "docs/metrics-guide.md",
    "docs/en/metrics-guide.md",
)


def _glossary_rows() -> list[tuple[str, str, str]]:
    text = (ROOT / "docs" / "metrics-guide.md").read_text(encoding="utf-8")
    assert text.count(GLOSSARY_HEADING) == 1, "the glossary heading must appear exactly once"
    section = text.split(GLOSSARY_HEADING, 1)[1].split("\n## ", 1)[0]
    rows: list[tuple[str, str, str]] = []
    for line in section.splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-"}:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == "サイトの訳語":
            continue
        site, cli, key = cells[0], cells[1], cells[2]
        rows.append((site, cli, key))
    return rows


def _glossary_fixture_report(tmp_path: Path) -> dict:
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from git_fixture import commit, init_repo

    from tep_core.analyze import analyze_repository
    from tep_core.identity import empty_identity
    from tep_core.lineage import Lineage

    repo = init_repo(tmp_path / "repo")
    repo.joinpath("pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_smoke.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    for index in range(30):
        commit(
            repo,
            email="a@example.com",
            date="2026-01-02",
            message=f"work {index}",
            filename="app.py",
            content=f"print({index})\n",
        )
        if index % 2 == 0:
            commit(
                repo,
                email="a@example.com",
                date="2026-01-02",
                message=f"test {index}",
                filename="tests/test_app.py",
            )
    # A fix inside the 21-day window makes corrective rework observed.
    commit(repo, email="a@example.com", date="2026-01-03", message="fix: typo", filename="app.py")
    return analyze_repository(repo, empty_identity(), Lineage(), scope="repo", survival=True)


def _resolve(report: dict, dotted: str) -> tuple[dict, object]:
    node: object = report
    parent: dict = report
    for segment in dotted.split("."):
        assert isinstance(node, dict), f"{dotted}: {segment!r} is reached through a non-object"
        assert segment in node, (
            f"glossary declares JSON key {dotted!r} but the report has no {segment!r} "
            f"at that level; keys present: {sorted(node)}"
        )
        parent, node = node, node[segment]
    return parent, node


def test_site_glossary_rows_resolve_to_real_report_keys(tmp_path: Path) -> None:
    rows = _glossary_rows()
    assert {site for site, _, _ in rows} == SITE_TERMS, (
        f"glossary site terms {sorted(site for site, _, _ in rows)} != "
        f"expected {sorted(SITE_TERMS)} (GAP-site-vs-cli row 16)"
    )
    report = _glossary_fixture_report(tmp_path)
    dotted_rows = [(site, cli, key) for site, cli, key in rows if not key.startswith("`kind:")]
    generic_rows = [row for row in rows if row[2].startswith("`kind:")]
    assert len(generic_rows) == 1 and generic_rows[0][0] == "検査値"
    assert dotted_rows, "glossary has no dotted JSON key rows"
    for site, cli, key_cell in dotted_rows:
        match = re.fullmatch(r"`([a-z0-9_.]+)`", key_cell)
        assert match, (
            f"{site}: JSON key cell must be a single backticked dotted path, got {key_cell!r}"
        )
        dotted = match.group(1)
        parent, value = _resolve(report, dotted)
        assert isinstance(value, (int, float)), (
            f"{site} ({cli}) -> {dotted} = {value!r} is not a number"
        )
        # The 検査値 row describes the shape every dotted row must sit in.
        assert parent.get("kind") == "observed", (
            f"{site} ({cli}) -> {dotted} sits in a block with kind={parent.get('kind')!r}, "
            'but the 検査値 row declares `kind: "observed"`'
        )
        assert "unit" in parent, (
            f"{site} ({cli}) -> {dotted}: block has no `unit`; keys: {sorted(parent)}"
        )


def test_site_glossary_cli_terms_are_explained_in_the_guide() -> None:
    text = (ROOT / "docs" / "metrics-guide.md").read_text(encoding="utf-8")
    outside = (
        text.split(GLOSSARY_HEADING, 1)[0] + text.split(GLOSSARY_HEADING, 1)[1].split("\n## ", 1)[1]
    )
    for site, cli, _ in _glossary_rows():
        term = cli.split("（", 1)[0].strip()
        assert term in outside, (
            f"glossary maps {site!r} to CLI term {term!r}, but metrics-guide.md never uses that term "
            "outside the table"
        )


def test_site_glossary_is_linked_not_copied() -> None:
    row_pattern = re.compile(r"^\|\s*(" + "|".join(sorted(SITE_TERMS)) + r")\s*\|", re.MULTILINE)
    for relative in DOCS_THAT_MUST_NOT_COPY_GLOSSARY:
        text = (ROOT / relative).read_text(encoding="utf-8")
        hits = row_pattern.findall(text)
        assert not hits, (
            f"{relative} copies glossary rows {hits}; link to {GLOSSARY_ANCHOR} instead"
        )
    for relative in DOCS_LINKING_TO_GLOSSARY:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert GLOSSARY_ANCHOR in text, f"{relative} does not link to {GLOSSARY_ANCHOR}"


def test_tep_is_expanded_at_first_mention() -> None:
    for relative in DOCS_EXPANDING_TEP_AT_FIRST_MENTION:
        lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
        first = next((line for line in lines if "TEP" in line), None)
        assert first is not None, f"{relative} never mentions TEP"
        assert any(expansion in first for expansion in TEP_EXPANSIONS), (
            f"{relative}: first mention of TEP is {first!r}; expected one of {TEP_EXPANSIONS} "
            "(GAP-site-vs-cli row 14)"
        )
