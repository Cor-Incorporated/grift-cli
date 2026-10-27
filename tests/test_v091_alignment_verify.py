"""v0.9.1: alignment verification, its contract and its documents (#96, #88 follow-ups).

`grift verify <alignment.json> --repo --identity --project` recomputes the actor
report from the repository and compares every field. The subject must be built
from that recomputation and the project TOML, the same way `grift align --repo`
builds it, and never copied from the saved JSON: a copied field verifies whatever
the file says (M8; L18 for `project_id`, copied before; `mode`, which this path
never writes).

The contract catalog (`v060-contracts.schema.json`) holds the same consent rule
as the runtime validator, and is checked with good and bad payloads (L19).

The documented relationship kinds and Markdown heading order are read from
`docs/alignment-schema.md` and compared with the code (L12).

`grift report <alignment.json>` only re-renders the saved file, so the Markdown
says the consent record behind the questions is checked by `grift verify` (L17).
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from git_fixture import commit, init_repo

from tep_cli.__main__ import main
from tep_core import trait_tables as tables
from tep_core.identity import RECORDED_EXPLICIT_CONSENT
from tep_core.report import render_markdown
from tep_core.schema import load_schema, validate_schema
from tep_core.schema_v2 import validate_alignment
from tep_core.v2_constants import RELATIONSHIPS

AS_OF = "2026-08-31"
PROJECT_TOML = """schema_version = "tep-project-v1"
project_id = "payments-api"

[requirements.surfaces]
required = ["backend", "test", "data"]
"""
IDENTITIES = {"claimed": True, "claimed-noconsent": False}
_DROP = object()


def _identity(consent: bool) -> str:
    lines = [
        'schema_version = "identity-v2"',
        "",
        "[[actors]]",
        'canonical_id = "alice"',
        'emails = ["alice@example.com"]',
        'attribution_state = "claimed"',
    ]
    if consent:
        lines += [f'consent = "{RECORDED_EXPLICIT_CONSENT}"', 'authority = "subject-authorization"']
    return "\n".join(lines) + "\n"


def _run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue()


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Path]]:
    tmp = tmp_path_factory.mktemp("v091alignverify")
    repo = init_repo(tmp / "person")
    start = date(2026, 6, 1)
    for index in range(30):
        day = (start + timedelta(days=index * 2)).isoformat()
        filename = "src/api/svc.py" if index % 3 else f"tests/test_svc_{index}.py"
        commit(
            repo, email="alice@example.com", date=day, message=f"feat: {index}", filename=filename
        )
    project = tmp / "project.toml"
    project.write_text(PROJECT_TOML, encoding="utf-8")
    out: dict[str, dict[str, Path]] = {}
    for name, consent in IDENTITIES.items():
        identity = tmp / f"identity-{name}.toml"
        identity.write_text(_identity(consent), encoding="utf-8")
        alignment = tmp / f"alignment-{name}.json"
        code, text = _run(
            [
                "align",
                *("--repo", str(repo), "--identity", str(identity), "--actor", "alice"),
                *("--project", str(project), "--as-of", AS_OF),
                *("--format", "json", "--out", str(alignment)),
            ]
        )
        assert code == 0, text
        out[name] = {"repo": repo, "identity": identity, "project": project, "alignment": alignment}
    return out


def _verify(run: dict[str, Path], alignment: Path) -> tuple[int, str]:
    return _run(
        [
            "verify",
            str(alignment),
            *("--repo", str(run["repo"]), "--identity", str(run["identity"])),
            *("--project", str(run["project"])),
        ]
    )


def _tampered(run: dict[str, Path], tmp_path: Path, key: str, value: object) -> Path:
    payload = json.loads(run["alignment"].read_text(encoding="utf-8"))
    if value is _DROP:
        payload["subject"].pop(key)
    else:
        payload["subject"][key] = value
    path = tmp_path / f"tampered-{key}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("name", list(IDENTITIES))
def test_a_repo_alignment_verifies_as_written(runs, name: str) -> None:
    payload = json.loads(runs[name]["alignment"].read_text(encoding="utf-8"))
    code, out = _verify(runs[name], runs[name]["alignment"])
    facts = {
        "mode": payload["subject"].get("mode"),
        "actor_consent": payload["subject"].get("actor_consent"),
        "project_id": payload["subject"].get("project_id"),
        "code": code,
        "verified": out.startswith("VERIFIED"),
    }
    assert facts == {
        "mode": None,
        "actor_consent": RECORDED_EXPLICIT_CONSENT if IDENTITIES[name] else None,
        "project_id": "payments-api",
        "code": 0,
        "verified": True,
    }, (facts, out)


@pytest.mark.parametrize(
    ("name", "value"),
    [("claimed", _DROP), ("claimed-noconsent", RECORDED_EXPLICIT_CONSENT)],
    ids=["consent-dropped", "consent-added"],
)
def test_repo_verify_rebuilds_the_consent_record(runs, tmp_path: Path, name, value) -> None:
    tampered = _tampered(runs[name], tmp_path, "actor_consent", value)
    assert validate_alignment(json.loads(tampered.read_text(encoding="utf-8"))) == []
    code, out = _verify(runs[name], tampered)
    assert code == 1 and out.startswith("MISMATCH"), out
    assert "subject.actor_consent" in out, out


@pytest.mark.parametrize("value", ["other-api", None], ids=["other-id", "null"])
def test_repo_verify_rebuilds_the_project_id_from_the_project_toml(
    runs, tmp_path: Path, value
) -> None:
    tampered = _tampered(runs["claimed"], tmp_path, "project_id", value)
    code, out = _verify(runs["claimed"], tampered)
    assert code == 1 and out.startswith("MISMATCH"), out
    assert "subject.project_id: report=" in out and "recomputed='payments-api'" in out, out


@pytest.mark.parametrize("value", ["repo", "saved_reports"])
def test_repo_verify_does_not_take_a_mode_from_the_saved_subject(
    runs, tmp_path: Path, value: str
) -> None:
    # `grift align --repo` writes no mode; only saved-report alignments carry one.
    # Given repo inputs, a written `saved_reports` is a difference to report, not
    # a switch to the saved-report path that ends in CANNOT_VERIFY (#102 review).
    tampered = _tampered(runs["claimed"], tmp_path, "mode", value)
    assert validate_alignment(json.loads(tampered.read_text(encoding="utf-8"))) == []
    code, out = _verify(runs["claimed"], tampered)
    assert code == 1 and f"subject.mode: report={value!r} recomputed=None" in out, out


# --- #102 review: provenance, limitations and options are rebuilt, not copied ---

_PROVENANCE_TAMPERS: dict[str, tuple[str, object]] = {
    "analysis_scope": ("analysis_scope", "repo"),
    "actor_commit_sha": ("actor_commit_sha", "f" * 40),
    "project_commit_sha": ("project_commit_sha", "e" * 40),
    "tool_version": ("tool_version", "9.9.9"),
    "git_window-added": ("git_window", {"start": "2020-01-01", "end": AS_OF}),
    "reference_manifest-added": ("reference_manifest", "forged.json"),
}


def _write(tmp_path: Path, payload: dict[str, Any], tag: str) -> Path:
    path = tmp_path / f"{tag}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("case", list(_PROVENANCE_TAMPERS))
def test_repo_verify_rebuilds_the_provenance(runs, tmp_path: Path, case: str) -> None:
    key, value = _PROVENANCE_TAMPERS[case]
    payload = json.loads(runs["claimed"]["alignment"].read_text(encoding="utf-8"))
    payload["provenance"][key] = value
    code, out = _verify(runs["claimed"], _write(tmp_path, payload, case))
    assert code == 1 and f"provenance.{key}" in out, out


def test_repo_verify_rebuilds_the_limitations(runs, tmp_path: Path) -> None:
    payload = json.loads(runs["claimed"]["alignment"].read_text(encoding="utf-8"))
    payload["limitations"] = ["anything"]
    code, out = _verify(runs["claimed"], _write(tmp_path, payload, "limitations"))
    assert code == 1 and "limitations: report=['anything']" in out, out


_REFERENCE = "gharchive-2024-01-15-to-21-selected-repos"
_OPTIONS = {
    "survival": (["--survival"], "survival", True),
    "vendor-scan": (["--vendor-scan"], "vendor_scan", True),
    "reference": (["--reference", _REFERENCE], "reference_id", _REFERENCE),
}


@pytest.mark.parametrize("case", list(_OPTIONS))
def test_repo_verify_recomputes_with_the_options_align_recorded(
    runs, tmp_path: Path, case: str
) -> None:
    # `grift align --repo` records these options in `actor_provenance` only.
    flags, key, value = _OPTIONS[case]
    run = runs["claimed"]
    alignment = tmp_path / "alignment.json"
    code, text = _run(
        [
            "align",
            *("--repo", str(run["repo"]), "--identity", str(run["identity"]), "--actor", "alice"),
            *("--project", str(run["project"]), "--as-of", AS_OF, *flags),
            *("--format", "json", "--out", str(alignment)),
        ]
    )
    assert code == 0, text
    payload = json.loads(alignment.read_text(encoding="utf-8"))
    assert payload["actor_provenance"][key] == value, payload["actor_provenance"]
    code, out = _verify(run, alignment)
    assert code == 0 and out.startswith("VERIFIED"), out


def test_repo_verify_reports_a_non_object_actor_provenance_as_a_difference(
    runs, tmp_path: Path
) -> None:
    payload = json.loads(runs["claimed"]["alignment"].read_text(encoding="utf-8"))
    payload["actor_provenance"] = "edited"
    code, out = _verify(runs["claimed"], _write(tmp_path, payload, "actor-provenance"))
    assert code == 1 and "actor_provenance: report='edited'" in out, out


@pytest.fixture(scope="module")
def saved(runs, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A saved-report alignment of the claimed identity without a consent record."""

    tmp = tmp_path_factory.mktemp("v091alignsaved")
    run = runs["claimed-noconsent"]
    project_dir = tmp / "project-out"
    actor = tmp / "actor-report.json"
    alignment = tmp / "alignment.json"
    for argv in (
        ["project", str(run["repo"]), "--requirements", str(run["project"]), "--as-of", AS_OF],
        ["actor", "alice", str(run["repo"]), "--identity", str(run["identity"]), "--as-of", AS_OF],
        [
            "align",
            "--actor-report",
            str(actor),
            "--project-report",
            str(project_dir / "project.json"),
        ],
    ):
        out = {"project": project_dir, "actor": actor, "align": alignment}[argv[0]]
        code, text = _run([*argv, "--format", "json", "--out", str(out)])
        assert code == 0, (argv[0], text)
    return {
        **run,
        "actor": actor,
        "project_report": project_dir / "project.json",
        "alignment": alignment,
    }


def _verify_saved(
    saved: dict[str, Path], alignment: Path, actor: Path | None = None
) -> tuple[int, str]:
    return _run(
        [
            "verify",
            str(alignment),
            *("--actor-report", str(actor or saved["actor"])),
            *("--project-report", str(saved["project_report"])),
        ]
    )


@pytest.mark.parametrize("value", [_DROP, "repo"], ids=["mode-dropped", "other-mode"])
def test_saved_verify_does_not_take_the_mode_from_the_saved_subject(
    saved, tmp_path: Path, value: object
) -> None:
    code, out = _verify_saved(saved, saved["alignment"])
    assert code == 0 and out.startswith("VERIFIED"), out
    tampered = _tampered(saved, tmp_path, "mode", value)
    code, out = _verify_saved(saved, tampered)
    assert code == 1 and "subject.mode: report=" in out, out
    assert "recomputed='saved_reports'" in out, out


# --- L19: the contract catalog holds the consent rule -----------------------

_DIGEST = {"algorithm": "sha256", "value": "b" * 64}
_WINDOW = {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"}
_LIMITS = ["Observation only; not a score."]


def _metric() -> dict[str, Any]:
    return {
        "kind": "observed",
        "value": 0.5,
        "numerator": 1,
        "denominator": 2,
        "unit": "ratio",
        "window": dict(_WINDOW),
        "definition_version": "metric-v1",
        "limitations": list(_LIMITS),
    }


def _contract_alignment(subject: dict[str, Any]) -> dict[str, Any]:
    """The smallest alignment-v1 instance of the contract catalog."""

    axis = {
        "axis": "verification",
        "actor_observed": _metric(),
        "project_observed": _metric(),
        "project_declared": _metric(),
        "actor_n": 1,
        "project_n": 1,
        "actor_denominator": 2,
        "project_denominator": 2,
        "actor_source": ["git"],
        "project_source": ["git"],
        "actor_basis": "actor commits",
        "project_basis": "project commits",
        "relationship": "similar_direction",
        "coverage": "present",
        "limitations": list(_LIMITS),
    }
    return {
        "schema_version": "alignment-v1",
        "report_kind": "alignment",
        "subject": {"kind": "alignment", "actor_canonical_id": "alice", **subject},
        "actor_report_digest": dict(_DIGEST),
        "project_report_digest": dict(_DIGEST),
        "target": {"oid": {"algorithm": "sha1", "value": "a" * 40}},
        "window": dict(_WINDOW),
        "axes": [axis],
        "limitations": list(_LIMITS),
        "notices": ["No fit score."],
    }


_CLAIMED = {"actor_selection": "explicit_actor", "actor_attribution_state": "claimed"}
_PUBLIC = {"actor_selection": "inferred_actor"}
_CONTRACT_CASES = {
    "claimed-with-consent": ({**_CLAIMED, "actor_consent": RECORDED_EXPLICIT_CONSENT}, True),
    "claimed-without-consent": (dict(_CLAIMED), True),
    "public-without-consent": (dict(_PUBLIC), True),
    "other-consent-value": ({**_CLAIMED, "actor_consent": "yes"}, False),
    "public-with-consent": ({**_PUBLIC, "actor_consent": RECORDED_EXPLICIT_CONSENT}, False),
}


@pytest.mark.parametrize("case", list(_CONTRACT_CASES))
def test_contract_catalog_holds_only_the_recorded_consent_and_never_for_a_public_cluster(
    case: str,
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    subject, accepted = _CONTRACT_CASES[case]
    payload = _contract_alignment({**subject, "project_id": "payments-api"})
    validator = jsonschema.Draft202012Validator(load_schema("alignment-v1"))
    errors = {
        # tep_core.schema reads the catalog file with the stdlib; jsonschema reads it independently.
        "catalog_stdlib": validate_schema("alignment-v1", payload),
        "catalog_jsonschema": [error.message for error in validator.iter_errors(payload)],
        # The runtime validator `grift align` and `grift verify` call keeps the same rule.
        "runtime": [error for error in validate_alignment(payload) if "actor_consent" in error],
    }
    facts = {name: not found for name, found in errors.items()}
    assert facts == dict.fromkeys(errors, accepted), (case, errors)


def _catalog_alignment() -> dict[str, Any]:
    return load_schema("alignment-v1")["$defs"]["alignment-v1"]


def test_contract_catalog_consent_value_is_the_identity_constant() -> None:
    subject = _catalog_alignment()["properties"]["subject"]["properties"]
    assert subject["actor_consent"] == {"const": RECORDED_EXPLICIT_CONSENT}, subject


# --- L12: docs/alignment-schema.md against the code -------------------------

_SCHEMA_DOC = Path(__file__).resolve().parents[1] / "docs" / "alignment-schema.md"


def test_documented_relationship_kinds_are_the_code_enum() -> None:
    text = _SCHEMA_DOC.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("`relationship.kind` は "))
    documented = re.findall(r"`([a-z_]+)`", line.split(" は ", 1)[1].split("です", 1)[0])
    catalog = _catalog_alignment()["properties"]["axes"]["items"]["properties"]
    facts = {
        "docs": sorted(documented),
        "code": sorted(RELATIONSHIPS),
        "catalog": sorted(catalog["relationship"]["enum"]),
    }
    assert facts["docs"] == facts["code"] == facts["catalog"], facts


def test_documented_markdown_heading_order_is_the_rendered_order(runs) -> None:
    text = _SCHEMA_DOC.read_text(encoding="utf-8")
    block = text.split("Markdown の見出し（`## `）は次の順です", 1)[1].split("\n\n", 2)[1]
    documented = re.findall(r"^\d+\. `(.+)`$", block, flags=re.MULTILINE)
    payload = json.loads(runs["claimed"]["alignment"].read_text(encoding="utf-8"))
    rendered = [
        line[3:] for line in render_markdown(payload).splitlines() if line.startswith("## ")
    ]
    # The fixture declares only surfaces, so the conditional section is rendered too.
    assert tables.HEADINGS["not_declared"][3:] in rendered, rendered
    assert documented == rendered, {"docs": documented, "rendered": rendered}


def test_alignment_markdown_says_saved_consent_is_checked_by_verify_not_by_rerender(runs) -> None:
    payload = json.loads(runs["claimed"]["alignment"].read_text(encoding="utf-8"))
    tampered = copy.deepcopy(payload)
    tampered["subject"].pop("actor_consent")
    for item in (payload, tampered):
        markdown = render_markdown(item)
        limits = markdown.split(tables.HEADINGS["limits"], 1)[1].split("\n# ", 1)[0]
        assert f"- {tables.LIMIT_NOTES['consent']}" in limits, limits


_ACTOR_CHECK = "grift verify actor-report.json --repo REPO --identity IDENTITY"


def test_saved_verify_trusts_the_actor_report_which_is_checked_on_its_own(
    saved, tmp_path: Path
) -> None:
    # A saved-report alignment is rebuilt from the actor report it is handed, so a
    # forged actor report verifies its own alignment; only `grift verify` of the
    # actor report against the repository catches it. The docs and the Markdown
    # note say so (#102 review).
    forged = json.loads(saved["actor"].read_text(encoding="utf-8"))
    assert forged["role_profile"]["reason"] == "consenting_actor_required", forged["role_profile"]
    forged["role_profile"]["reason"] = "history_incomplete"
    forged_actor = _write(tmp_path, forged, "actor-report")
    alignment = tmp_path / "alignment.json"
    code, text = _run(
        [
            "align",
            *("--actor-report", str(forged_actor)),
            *("--project-report", str(saved["project_report"])),
            *("--format", "json", "--out", str(alignment)),
        ]
    )
    assert code == 0, text
    facts = {
        "actor_consent": json.loads(alignment.read_text(encoding="utf-8"))["subject"].get(
            "actor_consent"
        ),
        "alignment_verify": _verify_saved(saved, alignment, forged_actor)[0],
        "actor_verify": _run(
            [
                "verify",
                str(forged_actor),
                *("--repo", str(saved["repo"]), "--identity", str(saved["identity"])),
            ]
        )[0],
    }
    assert facts == {
        "actor_consent": RECORDED_EXPLICIT_CONSENT,
        "alignment_verify": 0,
        "actor_verify": 1,
    }, facts
    docs = {
        "LIMIT_NOTES": tables.LIMIT_NOTES["consent"],
        "usage": (_SCHEMA_DOC.parent / "usage.md").read_text(encoding="utf-8"),
        "usage_en": (_SCHEMA_DOC.parent / "en" / "usage.md").read_text(encoding="utf-8"),
        "alignment_schema": _SCHEMA_DOC.read_text(encoding="utf-8"),
    }
    missing = [name for name, text in docs.items() if _ACTOR_CHECK not in text]
    assert missing == [], (missing, _ACTOR_CHECK)
    assert "`subject.actor_selection`" in tables.LIMIT_NOTES["consent"]


# --- #102 re-review: the inputs pick the path; unedited files stay VERIFIED ---


def _verify_with(alignment: Path, *extra: str) -> tuple[int, str]:
    return _run(["verify", str(alignment), *extra])


def test_repo_alignment_with_both_input_sets_verifies_on_the_repo_path(runs, saved) -> None:
    run = runs["claimed"]
    repo_args = ("--repo", str(run["repo"]), "--identity", str(run["identity"]))
    repo_args += ("--project", str(run["project"]))
    both = ("--actor-report", str(saved["actor"]), "--project-report", str(saved["project_report"]))
    only_actor = ("--actor-report", str(saved["actor"]))
    facts = {
        "both_input_sets": _verify_with(run["alignment"], *repo_args, *both)[0],
        "repo_and_actor_report_only": _verify_with(run["alignment"], *repo_args, *only_actor)[0],
    }
    assert facts == {"both_input_sets": 0, "repo_and_actor_report_only": 0}, facts


def test_saved_alignment_with_both_input_sets_verifies_on_the_saved_path(saved) -> None:
    repo_args = ("--repo", str(saved["repo"]), "--identity", str(saved["identity"]))
    repo_args += ("--project", str(saved["project"]))
    both = ("--actor-report", str(saved["actor"]), "--project-report", str(saved["project_report"]))
    code, out = _verify_with(saved["alignment"], *repo_args, *both)
    assert code == 0 and out.startswith("VERIFIED"), out


def test_saved_alignment_on_the_repo_path_says_first_which_inputs_it_needs(saved) -> None:
    repo_args = ("--repo", str(saved["repo"]), "--identity", str(saved["identity"]))
    code, out = _verify_with(saved["alignment"], *repo_args, "--project", str(saved["project"]))
    lines = out.splitlines()
    assert code == 1 and lines[0].startswith("MISMATCH"), out
    assert lines[1].startswith("  note: subject.mode is 'saved_reports'"), lines[:3]
    assert "--actor-report and --project-report" in lines[1], lines[1]
