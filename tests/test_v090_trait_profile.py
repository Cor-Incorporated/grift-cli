"""v0.9.0 (b): plain sentences and interview questions, chosen by the decision tables.

ADR-0002 T1-T7 and trait-profile design §6.4. Every case runs the CLI on real
git repositories. The sentences are rebuilt here from the JSON numbers with the
published tables, so a sentence that drifts from its numbers fails (§6.3, the
verifier itself: `grift verify` never reads Markdown).

Boundaries (PR body): declaration ↔ artifact (tables in docs and code),
short ↔ long-lived (the periods named in the text match the JSON windows),
single repository ↔ collection (`--all` gets no sentences), real git ↔ Markdown.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from git_fixture import git, init_repo

from tep_cli.__main__ import main
from tep_core import trait_tables as tables
from tep_core.report import render_markdown
from tep_core.trait_profile import own_total, role_in_scope, work_sentences

AS_OF = "2026-08-31"
SPAN_START = date(2026, 6, 1)
CLAIMED = "claimed"


def _identity(state: str, *, consent: bool = True) -> str:
    lines = [
        'schema_version = "identity-v2"',
        "",
        "[[actors]]",
        'canonical_id = "alice"',
        'emails = ["alice@example.com"]',
        f'attribution_state = "{state}"',
    ]
    if consent:
        lines.append('consent = "recorded-explicit-consent"')
        lines.append('authority = "subject-authorization"')
    return "\n".join(lines) + "\n"


def _bulk_repo(path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    """(email, day, subject, path) rows as commits, in one `git fast-import`."""

    repo = init_repo(path)
    contents: dict[str, str] = {}
    stream = bytearray()
    for email, day, subject, filename in rows:
        contents[filename] = contents.get(filename, "") + subject + "\n"
        when = datetime.fromisoformat(day).replace(hour=12, tzinfo=timezone.utc)
        stamp = int(when.timestamp())
        message = subject.encode("utf-8")
        body = contents[filename].encode("utf-8")
        stream += b"commit refs/heads/main\n"
        stream += f"author Alice <{email}> {stamp} +0000\n".encode()
        stream += f"committer Alice <{email}> {stamp} +0000\n".encode()
        stream += f"data {len(message)}\n".encode() + message + b"\n"
        stream += f"M 100644 inline {filename}\n".encode()
        stream += f"data {len(body)}\n".encode() + body + b"\n"
    subprocess.run(
        ["git", "-C", str(repo), "fast-import", "--quiet"],
        input=bytes(stream),
        check=True,
        capture_output=True,
    )
    git(repo, "reset", "-q", "--hard", "main")
    return repo


def _day(offset: int) -> str:
    return (SPAN_START + timedelta(days=offset)).isoformat()


def _mix(index: int) -> tuple[str, str]:
    """Five in ten backend (one in ten a fix), two in ten docs, three in ten unit tests."""

    slot = index % 10
    if slot < 5:
        kind = "fix" if slot == 4 else "feat"
        return f"{kind}: api {index}", "src/api/svc.py"
    if slot < 7:
        return f"docs: guide {index}", "docs/guide.md"
    return f"test: api {index}", f"tests/test_api_{index}.py"


def _person_rows(count: int, spacing: float) -> list[tuple[str, str, str, str]]:
    rows = []
    for index in range(count):
        subject, filename = _mix(index)
        rows.append(("alice@example.com", _day(int(index * spacing)), subject, filename))
    return rows


def _cli(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, (argv[0], err.getvalue())
    return out.getvalue()


def _actor(repo: Path, identity: Path, fmt: str) -> str:
    return _cli(
        [
            "actor",
            "alice",
            str(repo),
            "--identity",
            str(identity),
            "--as-of",
            AS_OF,
            "--format",
            fmt,
        ]
    )


PROJECT_TOML = """schema_version = "tep-project-v1"
project_id = "payments-api"
title = "決済 API の保守"

[requirements.change_rhythm]
active_days_180d_min = 40
median_gap_days_max = 7

[requirements.surfaces]
required = ["backend", "data", "test"]

[requirements.verification]
required = ["unit", "e2e"]

[requirements.inputs]
required = ["git", "forge"]
"""


def _write_identity(tmp: Path, state: str, consent: bool) -> Path:
    path = tmp / f"identity-{state}-{consent}.toml"
    path.write_text(_identity(state, consent=consent), encoding="utf-8")
    return path


def _actor_runs(tmp: Path, person: Path) -> dict[str, str]:
    out = {}
    for state, consent in (("claimed", True), ("verified", True), ("claimed", False)):
        identity = _write_identity(tmp, state, consent)
        key = f"{state}{'' if consent else '-noconsent'}"
        out[f"{key}_md"] = _actor(person, identity, "md")
        out[f"{key}_json"] = _actor(person, identity, "json")
    return out


def _project_run(tmp: Path, team: Path) -> tuple[dict[str, str], Path]:
    requirements = tmp / "requirements.toml"
    requirements.write_text(PROJECT_TOML, encoding="utf-8")
    project_dir = tmp / "project-out"
    project = ["project", str(team), "--requirements", str(requirements), "--as-of", AS_OF]
    _cli([*project, "--format", "both", "--out", str(project_dir)])
    files = {
        "project_md": (project_dir / "project.md").read_text(encoding="utf-8"),
        "project_json": (project_dir / "project.json").read_text(encoding="utf-8"),
    }
    return files, project_dir / "project.json"


def _align_runs(tmp: Path, project_json: Path, reports: dict[str, str]) -> dict[str, str]:
    """One alignment per actor basis, from saved actor reports."""
    out = {}
    for basis, report in reports.items():
        actor_json = tmp / f"actor-{basis}.json"
        actor_json.write_text(report, encoding="utf-8")
        align = ["align", "--actor-report", str(actor_json), "--project-report", str(project_json)]
        suffix = "" if basis == "claimed" else f"_{basis}"
        out[f"alignment{suffix}_md"] = _cli([*align, "--format", "md"])
        out[f"alignment{suffix}_json"] = _cli([*align, "--format", "json"])
    return out


def _collection_run(tmp: Path, person: Path) -> tuple[str, str]:
    collection = tmp / "collection"
    _cli(
        [
            "actor",
            "--all",
            str(person),
            "--as-of",
            AS_OF,
            "--format",
            "both",
            "--out",
            str(collection),
        ]
    )
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(collection.rglob("*")) if path.is_file()
    )
    index = json.loads((collection / "actor-index.json").read_text(encoding="utf-8"))
    return text, index["actors"][0]["actor_id"]


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Thirty commits by one person every two days, and every artifact the tests read."""
    tmp = tmp_path_factory.mktemp("v090b")
    person = _bulk_repo(tmp / "person", _person_rows(30, 2))
    team_rows = [
        (f"{who}@example.com", _day(index), *_mix(index))
        for index, who in zip(range(60), "pqr" * 20, strict=True)
    ]
    team = _bulk_repo(tmp / "team", team_rows)
    out = _actor_runs(tmp, person)
    project, project_json = _project_run(tmp, team)
    out.update(project)
    out["collection"], inferred = _collection_run(tmp, person)
    out["inferred_md"] = _cli(["actor", inferred, str(person), "--as-of", AS_OF, "--format", "md"])
    inferred_json = _cli(["actor", inferred, str(person), "--as-of", AS_OF, "--format", "json"])
    reports = {
        "claimed": out["claimed_json"],
        "verified": out["verified_json"],
        "inferred": inferred_json,
    }
    out.update(_align_runs(tmp, project_json, reports))
    return out


def _section(markdown: str) -> str:
    """The opening part: from the first heading to the 0.8.0 report."""
    return markdown.split("# TEP ", 1)[0]


def _render(key: str, **values: object) -> str:
    template = {**tables.SENTENCES, **tables.QUESTIONS, **tables.ALIGNMENT_TEXTS}[key]
    return template.format(**values)


def test_claimed_actor_with_consent_gets_sentences_rebuilt_from_its_json(runs) -> None:
    """T3 and §6.4 「文と数字が一致する」: every number in the text comes from the JSON."""
    section = _section(runs["claimed_md"])
    report = json.loads(runs["claimed_json"])
    surface = report["surface_profile"]
    counts, n = surface["surface_commit_counts"]["values"], surface["population"]
    assert section.startswith("# `alice` の記録から見える進め方"), section[:80]
    lead = _render(
        "place_lead", place="サーバー側の処理", scope="自分の変更", n=n, c=counts["backend"]
    )
    assert lead in section
    assert _render("place_following", items=f"文書（{counts['docs']} 件）") in section
    gaps = report["change_rhythm"]["interval_sample_size"]["value"]
    assert tables.SENTENCES["rhythm_steady"] in section
    assert _render("rhythm_detail", median="2.0", p90="2.0", n=gaps, burst=gaps, long=0) in section
    verification = report["verification_profile"]
    touch = verification["test_touch_share"]
    assert _render("verify_lead", n=touch["sample_size"], c=touch["test_touch"]) in section
    unit = verification["test_type_distribution"]["values"]["unit"]
    assert _render("verify_types", types=f"部品ごとに確かめる単体テスト（{unit} 件）") in section
    assert (
        _render("verify_fix_few", s=verification["fix_with_test_pairing"]["population"]) in section
    )
    work = report["role_profile"]["dimensions"]["work_type"]
    create, modify = work["create"]["numerator"], work["modify"]["numerator"]
    assert modify > create, work
    assert _render("work_modify_more", m=modify, c=create) in section


def test_claimed_actor_questions_follow_the_table_order(runs) -> None:
    section = _section(runs["claimed_md"])
    report = json.loads(runs["claimed_json"])
    unit = report["verification_profile"]["test_type_distribution"]["values"]["unit"]
    questions = re.findall(r"^\d+\. (.+)$", section.split("## 面談で確かめたいこと", 1)[1], re.M)
    assert questions[:3] == [
        _render("ask_outside", place="サーバー側の処理"),
        tables.QUESTIONS["ask_rhythm_steady"],
        _render("ask_test_type", type="単体テスト", c=unit),
    ], questions
    assert len(questions) <= tables.THRESHOLDS["max_questions"]


def test_periods_in_the_text_match_the_json_windows(runs) -> None:
    """§6.3 短時間 ↔ 長寿命: the as-of history and the 180-day window are named apart."""
    section = _section(runs["claimed_md"])
    report = json.loads(runs["claimed_json"])
    prov, total = report["provenance"], report["verification_profile"]["sample_size"]
    assert (
        tables.SECTION_TEXTS["record_scope"].format(end=prov["observation_date"], total=total)
        in section
    )
    window, population = prov["git_window"], report["change_rhythm"]["window_population"]
    expected = tables.SECTION_TEXTS["rhythm_period"].format(
        start=window["start"], end=window["end"], days=window["days"], n=population
    )
    assert expected in section


def test_the_selectivity_notice_appears_once_for_a_claimed_actor(runs) -> None:
    """norms §6 once per Markdown: in the opening section, not again below."""
    from tep_core.v2_constants import SELECTIVITY_NOTICE_JA

    assert runs["claimed_md"].count(SELECTIVITY_NOTICE_JA) == 1
    assert SELECTIVITY_NOTICE_JA in _section(runs["claimed_md"])


def _evidence(section: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in section.split(tables.HEADINGS["evidence"], 1)[1].splitlines()[4:]:
        if line.startswith("| "):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            rows[cells[1]] = cells
    return rows


def test_every_evidence_row_is_rebuilt_from_the_json(runs) -> None:
    """§6.3 検証器自身: verify never reads Markdown, so each row is checked here."""
    report = json.loads(runs["claimed_json"])
    rows = _evidence(_section(runs["claimed_md"]))
    surface, rhythm = report["surface_profile"], report["change_rhythm"]
    counts, n = surface["surface_commit_counts"]["values"], surface["population"]
    history = tables.SECTION_TEXTS["history"].format(end=report["provenance"]["observation_date"])
    assert rows["サーバー側の処理に触れた変更"][2:] == [f"{n} 件中 {counts['backend']} 件", history]
    assert rows["文書に触れた変更"][2] == f"{n} 件中 {counts['docs']} 件"
    gaps = rhythm["interval_sample_size"]["value"]
    assert rows[tables.EVIDENCE_ROWS["rhythm_median"]][2] == f"2.0 日（間隔 {gaps} 回）"
    assert rows[tables.EVIDENCE_ROWS["rhythm_p90"]][2] == f"2.0 日（間隔 {gaps} 回）"
    assert rows[tables.EVIDENCE_ROWS["rhythm_long"]][2] == f"間隔 {gaps} 回中 0 回"
    touch = report["verification_profile"]["test_touch_share"]
    assert (
        rows[tables.EVIDENCE_ROWS["verify_touch"]][2]
        == f"{touch['sample_size']} 件中 {touch['test_touch']} 件"
    )
    work = report["role_profile"]["dimensions"]["work_type"]
    make = rows[tables.EVIDENCE_ROWS["work_modify_create"]][2]
    expected = f"{work['create']['denominator']} 件中 {work['modify']['numerator']} 件 / {work['create']['numerator']} 件"
    assert make == expected + tables.SECTION_TEXTS["overlapping_counts"]


@pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("verified_md", "admin_verified"),
        ("claimed-noconsent_md", "no_consent"),
        ("inferred_md", "public_inferred"),
    ],
)
def test_sentences_need_a_claimed_identity_and_a_consent_record(
    runs, key: str, reason: str
) -> None:
    """T7: verified, claimed without consent and public inferred actors get the reason only."""
    section = _section(runs[key])
    assert tables.NOT_SHOWN_TEMPLATE.format(reason=tables.NOT_SHOWN[reason]) in section, section[
        :400
    ]
    for text in (tables.SENTENCES["rhythm_steady"], "いちばん多いのは", "## 面談で確かめたいこと"):
        assert text not in section, (key, text)


def test_collection_output_carries_no_sentences(runs) -> None:
    """T7 and §6.3 単リポ ↔ 結合: `--all` describes a population, never one person in words."""
    for phrase in (
        "この記録から見える進め方",
        "いちばん多いのは",
        "面談で確かめたいこと",
        "進め方です",
    ):
        assert phrase not in runs["collection"], phrase


def _strings(node: object, path: str = "$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", str(key)
            yield from _strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def test_json_carries_no_sentence_id_or_type_key(runs) -> None:
    """T4: the text lives in Markdown only, so JSON cannot be filtered by a label."""
    banned_keys = ("trait", "sentence", "question", "persona", "archetype")
    phrases = ("いちばん多いのは", "進め方です", "面談で", "この記録から見える")
    for name in ("claimed_json", "project_json", "alignment_json"):
        for path, text in _strings(json.loads(runs[name])):
            is_key = path.endswith(text)
            assert not (is_key and any(word in text.lower() for word in banned_keys)), (name, path)
            assert not any(phrase in text for phrase in phrases), (name, path, text[:80])


def test_project_report_describes_the_repository_without_people(runs) -> None:
    section = _section(runs["project_md"])
    surface = json.loads(runs["project_json"])["observed"]["surface_profile"]
    counts = surface["surface_commit_counts"]["values"]
    assert section.startswith("# 案件「決済 API の保守」の要望と記録"), section[:80]
    lead = _render(
        "place_lead",
        place="サーバー側の処理",
        scope="変更",
        n=surface["population"],
        c=counts["backend"],
    )
    assert lead in section
    assert "## 案件のリポジトリから見える進め方" in section
    assert tables.HEADINGS["make"] not in section  # role_profile is per person and consented only
    assert "人ごとの数字は出しません。" in section


def test_a_role_profile_put_into_the_project_payload_is_still_not_rendered(runs) -> None:
    """0.9.1 L15: project-v1 has no role_profile, so the check above cannot fail by itself.

    A consented actor's role_profile, sized to the project's own total so that it
    would render for a person, is put into the payload; the project section still
    has no 「関わり方」 block and no role rows in its evidence table.
    """
    project = json.loads(runs["project_json"])
    role = json.loads(runs["claimed_json"])["role_profile"]
    total = own_total(project["observed"])
    for node in role["dimensions"]["work_type"].values():
        node["denominator"] = total
    project["observed"]["role_profile"] = role
    project["role_profile"] = role
    sentences = work_sentences(project["observed"])
    assert sentences and role_in_scope(project["observed"]), (total, sentences)  # it would render
    section = _section(render_markdown(project))
    assert "## 案件のリポジトリから見える進め方" in section
    for text in (
        tables.HEADINGS["make"],
        *sentences,
        tables.EVIDENCE_ROWS["work_modify_create"],
        tables.EVIDENCE_ROWS["work_merges"],
        tables.EVIDENCE_ROWS["work_releases"],
    ):
        assert text not in section, text


def test_alignment_lists_overlaps_and_questions_without_counting_them(runs) -> None:
    """T5: no 「N 項目中」 and no overlap count; zero means absent from this record."""
    section = _section(runs["alignment_md"])
    assert section.startswith("# `alice` の記録と、案件「決済 API の保守」の照らし合わせ"), section[
        :80
    ]
    overlap = section.split("## 要望と記録が重なっている点", 1)[1].split("## ", 1)[0]
    assert "| サーバー側の処理 | 記録の変更 30 件のうち 15 件 |" in overlap
    asks = section.split("## 面談で確かめたい点", 1)[1].split("## ", 1)[0]
    assert tables.ALIGNMENT_TEXTS["zero_note"] in asks
    assert _render("ask_zero_places", places="データベースの定義") in asks
    assert _render("ask_zero_tests", types="E2E テスト") in asks
    assert tables.ALIGNMENT_TEXTS["ask_forge"] in asks
    days = json.loads(runs["claimed_json"])["change_rhythm"]["active_days_180d"]["value"]
    assert _render("ask_outside_days", declared=40, observed=days) in asks
    assert not re.search(r"\d+\s*項目中|重なり\s*\d+|重なった項目の数は\s*\d", section), section


@pytest.mark.parametrize(
    "key", ["claimed_md", "project_md", "alignment_md", "alignment_verified_md"]
)
def test_opening_section_headings_carry_no_number(runs, key: str) -> None:
    """T5: a count in a heading (「（3 項目）」) is a total by another name."""
    headings = [line for line in _section(runs[key]).splitlines() if line.startswith("#")]
    assert headings and not [line for line in headings if re.search(r"\d", line)], headings


def test_alignment_lists_what_the_project_did_not_declare(runs) -> None:
    rest = (
        _section(runs["alignment_md"])
        .split("## 案件側が書いていないこと（参考）", 1)[1]
        .split("## ", 1)[0]
    )
    item = tables.RHYTHM_ITEM_NAMES["p90_gap_days"]
    assert _render("not_declared_gap", item=item, observed="2.0") in rest


def test_alignment_questions_follow_the_actor_basis(runs) -> None:
    """T7: questions need a claimed identity and the consent record, like the actor report.

    0.9.0 first asked an administrator-registered identity too (M8); the user's
    decision (2026-10-26) is to ask nothing when the consent record cannot be confirmed.
    """
    claimed = _section(runs["alignment_md"])
    assert tables.ALIGNMENT_TEXTS["ask_forge"] in claimed
    for key, reason in (
        ("alignment_verified_md", "admin_verified"),
        ("alignment_inferred_md", "public_inferred"),
    ):
        text = _section(runs[key])
        assert tables.ALIGNMENT_TEXTS["ask_forge"] not in text, key
        not_shown = tables.ALIGNMENT_TEXTS["questions_not_shown"].format(
            reason=tables.NOT_SHOWN[reason]
        )
        assert not_shown in text, key
        assert "が共有した" not in text and "自分の変更" not in text, key


def _pattern_rows(scale: int) -> list[tuple[str, str, str, str]]:
    """The same work mix at `scale` times the volume, packed into the same 60 days."""
    return [
        ("alice@example.com", _day((index * 3) // scale), *_mix(index))
        for index in range(20 * scale)
    ]


def test_sentences_do_not_change_with_volume(tmp_path: Path) -> None:
    """T1 and §6.4 「量で文が変わらない」: ten times the commits, the same place sentences."""
    identity = _write_identity(tmp_path, CLAIMED, True)
    skeletons = []
    for scale in (1, 10):
        repo = _bulk_repo(tmp_path / f"scale-{scale}", _pattern_rows(scale))
        where = (
            _section(_actor(repo, identity, "md"))
            .split(tables.HEADINGS["places"], 1)[1]
            .split("###", 1)[0]
        )
        skeletons.append(re.sub(r"\d+", "N", where.strip()))
    assert skeletons[0] == skeletons[1], skeletons
    assert skeletons[0].startswith("いちばん多いのはサーバー側の処理で"), skeletons[0]


def test_a_late_joiner_with_later_work_is_described_up_to_the_observation_date(
    tmp_path: Path,
) -> None:
    """H1: later work is not described; role_profile is cut at --as-of too (0.9.0)."""
    early = [("bob@example.com", "2025-01-01", "feat: start", "src/api/app.py")]
    own = _person_rows(40, 2)
    later = [
        (
            "alice@example.com",
            f"2026-09-{index + 6:02d}",
            f"feat: page {index}",
            f"web/page_{index}.tsx",
        )
        for index in range(20)
    ]
    repo = _bulk_repo(tmp_path / "late", early + own + later)
    identity = _write_identity(tmp_path, CLAIMED, True)
    section = _section(_actor(repo, identity, "md"))
    report = json.loads(_actor(repo, identity, "json"))
    total = report["verification_profile"]["sample_size"]
    assert total == 40, total
    assert tables.SECTION_TEXTS["record_scope"].format(end=AS_OF, total=40) in section
    assert "2025-01-01" not in section and "2026-09-" not in section
    # role_profile stops at the --as-of date too (0.9.0), so the make block is in range.
    denominator = report["role_profile"]["dimensions"]["work_type"]["create"]["denominator"]
    assert denominator == 40, denominator
    assert "観測日のあとの変更も含めて" not in section


def test_a_shallow_clone_gets_the_reason_instead_of_sentences(tmp_path: Path) -> None:
    """R7: the oldest fetched commit adds every file, so places and gaps would be wrong."""
    source = _bulk_repo(tmp_path / "full", _person_rows(30, 2))
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "10", f"file://{source}", str(shallow)], check=True
    )
    identity = _write_identity(tmp_path, CLAIMED, True)
    section = _section(_actor(shallow, identity, "md"))
    report = json.loads(_actor(shallow, identity, "json"))
    assert report["provenance"]["revision_completeness"]["shallow"] is True
    assert report["role_profile"].get("reason") == "history_incomplete"
    reason = tables.NOT_SHOWN["shallow_history"]
    assert tables.NOT_SHOWN_SHALLOW_TEMPLATE.format(reason=reason) in section
    for text in ("いちばん多いのは", "数えた範囲", tables.HEADINGS["questions"]):
        assert text not in section, text


def _as(name: str, email: str, day: str) -> dict[str, str]:
    import os

    stamp = f"{day}T12:00:00+00:00"
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": stamp,
    }


def test_a_merge_and_a_tag_after_the_observation_date_are_not_counted_in(tmp_path: Path) -> None:
    """R1: a merge and a tag after the date are not counted, nor stated (cut since 0.9.0)."""
    repo = _bulk_repo(tmp_path / "later-merge", _person_rows(25, 2))
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "src" / "bob.py").write_text("x = 1\n", encoding="utf-8")
    bob = _as("Bob", "bob@example.com", "2026-09-08")
    git(repo, "add", "src/bob.py", env=bob)
    git(repo, "commit", "-q", "-m", "feat: bob", env=bob)
    git(repo, "checkout", "-q", "main")
    alice = _as("Alice", "alice@example.com", "2026-09-10")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge feature", "feature", env=alice)
    release = _as("Alice", "alice@example.com", "2026-09-11")
    git(repo, "tag", "-a", "v2.0.0", "-m", "release v2.0.0", env=release)
    identity = _write_identity(tmp_path, CLAIMED, True)
    report = json.loads(_actor(repo, identity, "json"))
    process = report["role_profile"]["dimensions"]["process_position"]
    # role_profile is cut at the --as-of date (0.9.0): the later merge and tag are not counted.
    assert (process["integrator"]["numerator"], process["release"]["numerator"]) == (0, 0)
    section = _section(_actor(repo, identity, "md"))
    for text in (
        tables.SENTENCES["work_process"].format(i=1, r=1),
        tables.SENTENCES["work_merge_only"].format(i=1),
        tables.SENTENCES["work_release_only"].format(r=1),
        tables.QUESTIONS["ask_release"].format(r=1),
    ):
        assert text not in section, text
    assert tables.HEADINGS["make"] in section  # the 25 own non-merge commits are in range
    none = tables.SECTION_TEXTS["count_times"].format(c=0)
    assert f"| {tables.EVIDENCE_ROWS['work_releases']} | {none} |" in section
    assert tables.SECTION_TEXTS["unseen_no_release"] in section  # none up to the date


def test_a_tag_before_the_observation_date_is_stated_under_as_of(tmp_path: Path) -> None:
    """J2 (0.9.1): role_profile cuts tags at the end of the --as-of day, so its count is stated."""
    repo = _bulk_repo(tmp_path / "earlier-tag", _person_rows(25, 2))
    release = _as("Alice", "alice@example.com", "2026-08-20")
    git(repo, "tag", "-a", "v1.0.0", "-m", "release v1.0.0", env=release)
    identity = _write_identity(tmp_path, CLAIMED, True)
    report = json.loads(_actor(repo, identity, "json"))
    role = report["role_profile"]
    observed = (
        report["provenance"]["window_basis"],
        role["window"]["end"],
        role["dimensions"]["process_position"]["release"]["numerator"],
    )
    assert observed == ("explicit_as_of", f"{AS_OF}T23:59:59Z", 1), observed
    section = _section(_actor(repo, identity, "md"))
    for text in (
        tables.SENTENCES["work_release_only"].format(r=1),
        tables.QUESTIONS["ask_release"].format(r=1),
    ):
        assert text in section, text
    once = tables.SECTION_TEXTS["count_times"].format(c=1)
    assert f"| {tables.EVIDENCE_ROWS['work_releases']} | {once} |" in section
    assert tables.SECTION_TEXTS["unseen_no_release"] not in section


def test_empty_commits_count_in_the_range_without_a_test_framework(tmp_path: Path) -> None:
    """R3: no test framework and four empty commits: 34 changes in range, places count 30."""
    rows = [
        (
            "alice@example.com",
            _day(index * 2),
            f"feat: api {index}",
            "src/api/svc.py" if index % 2 else "docs/guide.md",
        )
        for index in range(30)
    ]
    repo = _bulk_repo(tmp_path / "empty", rows)
    for index in range(4):
        env = _as("Alice", "alice@example.com", _day(61 + index))
        git(repo, "commit", "-q", "--allow-empty", "-m", f"chore: empty {index}", env=env)
    identity = _write_identity(tmp_path, CLAIMED, True)
    report = json.loads(_actor(repo, identity, "json"))
    assert report["verification_profile"]["kind"] == "not_observed"
    surface = report["surface_profile"]
    assert (surface["sample_size"], surface["population"]) == (34, 30), surface
    section = _section(_actor(repo, identity, "md"))
    scope = tables.SECTION_TEXTS["record_scope_paths"].format(end=AS_OF, total=34, paths=30)
    assert scope in section
    assert "観測日のあと" not in section
