from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tep_core.attest import SSHSigningConfig, SSHTrustPolicy, create_attestation_bundle
from tep_core.portfolio import (
    PortfolioValidationError,
    build_portfolio,
    load_portfolio_manifest,
    render_portfolio_markdown,
    validate_portfolio_payload,
)


def _ssh_key(root: Path) -> Path:
    executable = shutil.which("ssh-keygen")
    assert executable, "OpenSSH ssh-keygen is required for portfolio attestation fixtures"
    private_key = root / "portfolio_ed25519"
    subprocess.run(
        [executable, "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    os.chmod(private_key, 0o600)
    return private_key


def _report(
    path: Path,
    oid: str,
    *,
    subject: str = "subject_01",
    repo_subject_id: str | None = None,
) -> Path:
    payload = {
        "schema_version": "report-v1",
        "repo_subject_id": repo_subject_id or f"repo_{path.stem.replace('-', '_')}",
        "subject": {"kind": "actor", "canonical_id": subject},
        "provenance": {
            "tool_name": "grift",
            "tool_version": "0.6.0",
            "definition_version": "tep-v0.6.0-test",
            "analysis_scope": "tenant",
            "analyzed_commit_sha": oid,
        },
        "identity": {"pending_attribution": False, "actor_count": 1},
        "activity": {"tenant_commits": {"kind": "observed", "value": 3, "unit": "commits"}},
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _signed_report(
    root: Path,
    name: str,
    oid: str,
    key: Path,
    *,
    repo_subject_id: str | None = None,
    repo_hint: str | None = None,
) -> tuple[Path, Path]:
    report = _report(root / f"{name}.json", oid, repo_subject_id=repo_subject_id)
    bundle = root / f"{name}-attestation"
    if repo_hint is None and name == "two":
        repo_hint = "gitlab.example.com/group/two"
    create_attestation_bundle(
        report,
        bundle,
        signing=SSHSigningConfig(key, "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
        repo_hint=repo_hint,
    )
    return report, bundle


def _manifest(
    root: Path,
    *,
    binding: str = "self_declared",
    first_report: str = "one.json",
    first_bundle: str = "one-attestation",
    second_subject: str = "subject_01",
    extra_root: str = "",
    extra_first: str = "",
) -> Path:
    text = f'''schema_version = "tep-portfolio-manifest-v1"
portfolio_id = "portfolio_01"
subject_id = "subject_01"
subject_binding = "{binding}"
eligible_repository_count = 3
{extra_root}

[[entries]]
entry_id = "one"
subject_id = "subject_01"
context = "product"
role = "maintainer"
period_start = "2025-01-01"
period_end = "2025-06-30"
activity_month_count = 5
report = "{first_report}"
attestation_bundle = "{first_bundle}"
{extra_first}

[[entries]]
entry_id = "two"
subject_id = "{second_subject}"
context = "infrastructure"
role = "creator"
period_start = "2025-07-01"
period_end = "2026-02-28"
activity_month_count = 7
report = "two.json"
attestation_bundle = "two-attestation"
repo_hint = "gitlab.example.com/group/two.git"
'''
    path = root / "portfolio.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _allowed_signers(root: Path, key: Path, principal: str = "portfolio-builder") -> Path:
    allowed = root / f"allowed-signers-{key.name}"
    public = key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    allowed.write_text(f"{principal} {public}\n", encoding="utf-8")
    return allowed


def _fixture(root: Path) -> Path:
    key = _ssh_key(root)
    _signed_report(root, "one", "a" * 40, key)
    _signed_report(root, "two", "b" * 40, key)
    return _manifest(root)


def _keys(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(str(key))
            found |= _keys(value)
    elif isinstance(node, list):
        for value in node:
            found |= _keys(value)
    return found


def test_build_portfolio_binds_entries_and_reports_disclosure(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)

    portfolio = build_portfolio(manifest)

    assert portfolio["schema_version"] == "tep-portfolio-v1"
    assert portfolio["subject_binding"] == {
        "method": "self_declared",
        "subject_id": "subject_01",
    }
    assert portfolio["summary"] == {
        "eligible_repository_count": 3,
        "included_repository_count": 2,
        "disclosure": {
            "kind": "declared",
            "numerator": 2,
            "denominator": 3,
            "value": 0.666666666667,
            "unit": "ratio",
        },
        "period": {"start": "2025-01-01", "end": "2026-02-28", "unit": "date-range"},
    }
    assert [entry["entry_id"] for entry in portfolio["entries"]] == ["one", "two"]
    assert "repo_hint" not in portfolio["entries"][0]
    assert portfolio["entries"][1]["repo_hint"] == "gitlab.example.com/group/two"
    assert portfolio["entries"][0]["evidence"]["report"]["target_oid"] == {
        "algorithm": "sha1",
        "value": "a" * 40,
    }
    assert all(entry["repository_bindings"] for entry in portfolio["entries"])
    assert all(
        binding["algorithm"] == "sha256" and len(binding["value"]) == 64
        for entry in portfolio["entries"]
        for binding in entry["repository_bindings"]
    )
    assert not _keys(portfolio) & {
        "score",
        "scores",
        "rank",
        "ranking",
        "average",
        "weight",
    }
    assert any("選択性注意" in notice for notice in portfolio["notices"])


def test_markdown_carries_per_entry_evidence_without_aggregate_judgment(tmp_path: Path) -> None:
    portfolio = build_portfolio(_fixture(tmp_path))

    markdown = render_portfolio_markdown(portfolio)

    assert "2 of 3 declared eligible repositories" in markdown
    assert "report SHA-256" in markdown
    assert "attestation statement SHA-256" in markdown
    assert "not_verified_self_declared" in markdown
    assert "gitlab.example.com/group/two" in markdown
    assert "選択性注意" in markdown


def test_attested_binding_requires_and_verifies_recipient_trust(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path, binding="attested")

    with pytest.raises(PortfolioValidationError, match="recipient-supplied trust policy"):
        build_portfolio(manifest)

    allowed = _allowed_signers(tmp_path, key)
    portfolio = build_portfolio(
        manifest,
        trust_policy=SSHTrustPolicy(allowed, "portfolio-builder"),
    )

    assert portfolio["subject_binding"] == {
        "method": "attested",
        "subject_id": "subject_01",
    }
    assert all(
        entry["evidence"]["attestation"]["signature_verification"] == "recipient_trust_verified"
        and entry["evidence"]["attestation"]["bound_subject_id"] == "subject_01"
        for entry in portfolio["entries"]
    )
    serialized = json.dumps(portfolio, ensure_ascii=False)
    assert str(allowed) not in serialized
    assert str(key) not in serialized

    portfolio["entries"][1]["evidence"]["attestation"]["signer_policy"]["principal"] = (
        "other-builder"
    )
    with pytest.raises(PortfolioValidationError, match="one recipient trust policy"):
        validate_portfolio_payload(portfolio)


def test_attested_binding_rejects_wrong_signer_and_mixed_methods(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path, binding="attested")
    wrong_root = tmp_path / "wrong"
    wrong_root.mkdir()
    wrong_key = _ssh_key(wrong_root)
    wrong_allowed = _allowed_signers(wrong_root, wrong_key)

    with pytest.raises(PortfolioValidationError, match="recipient trust verification failed"):
        build_portfolio(
            manifest,
            trust_policy=SSHTrustPolicy(wrong_allowed, "portfolio-builder"),
        )

    mixed = _manifest(
        tmp_path,
        binding="attested",
        extra_first='subject_binding = "self_declared"',
    )
    with pytest.raises(PortfolioValidationError, match="subject_binding differs"):
        load_portfolio_manifest(mixed)


def test_self_declared_binding_rejects_mixed_trust_policy(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    allowed = _allowed_signers(tmp_path, key)

    with pytest.raises(PortfolioValidationError, match="cannot be mixed"):
        build_portfolio(
            _manifest(tmp_path),
            trust_policy=SSHTrustPolicy(allowed, "portfolio-builder"),
        )


def test_attested_binding_requires_same_subject_inside_each_signed_report(
    tmp_path: Path,
) -> None:
    key = _ssh_key(tmp_path)
    report = _report(tmp_path / "one.json", "a" * 40, subject="other_subject")
    create_attestation_bundle(
        report,
        tmp_path / "one-attestation",
        signing=SSHSigningConfig(key, "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
    )
    _signed_report(tmp_path, "two", "b" * 40, key)
    allowed = _allowed_signers(tmp_path, key)

    with pytest.raises(PortfolioValidationError, match="report subject differs"):
        build_portfolio(
            _manifest(tmp_path, binding="attested"),
            trust_policy=SSHTrustPolicy(allowed, "portfolio-builder"),
        )


def test_manifest_subject_binding_must_be_identical_for_every_entry(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path, second_subject="other_subject")

    with pytest.raises(PortfolioValidationError, match="differs from the portfolio subject"):
        load_portfolio_manifest(manifest)


def test_report_embedded_subject_mismatch_is_rejected(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    report = _report(tmp_path / "one.json", "a" * 40, subject="other_subject")
    create_attestation_bundle(
        report,
        tmp_path / "one-attestation",
        signing=SSHSigningConfig(key, "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
    )
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path)

    with pytest.raises(PortfolioValidationError, match="report subject differs"):
        build_portfolio(manifest)


def test_same_report_cannot_be_counted_twice(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path, first_report="two.json")

    with pytest.raises(PortfolioValidationError, match="same report path"):
        load_portfolio_manifest(manifest)


def test_semantically_identical_reports_cannot_bypass_duplicate_detection_with_whitespace(
    tmp_path: Path,
) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    second = _report(tmp_path / "two.json", "a" * 40, repo_subject_id="repo_one")
    payload = json.loads(second.read_text(encoding="utf-8"))
    second.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    create_attestation_bundle(
        second,
        tmp_path / "two-attestation",
        signing=SSHSigningConfig(key, "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
        repo_hint="gitlab.example.com/group/two",
    )

    with pytest.raises(PortfolioValidationError, match="same canonical report"):
        build_portfolio(_manifest(tmp_path))


def test_duplicate_repo_scope_and_opt_in_hint_are_independent_invariants(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    for name, oid, value in (("one", "a" * 40, 3), ("two", "b" * 40, 4)):
        report = _report(tmp_path / f"{name}.json", oid)
        payload = json.loads(report.read_text(encoding="utf-8"))
        payload["activity"]["tenant_commits"]["value"] = value
        payload["attribution"] = {"actor_partition": {"repo_scope_digest": "c" * 64}}
        report.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        create_attestation_bundle(
            report,
            tmp_path / f"{name}-attestation",
            signing=SSHSigningConfig(key, "portfolio-builder"),
            executed_at="2026-08-31T02:03:04Z",
            repo_hint=("gitlab.example.com/group/two" if name == "two" else None),
        )

    with pytest.raises(PortfolioValidationError, match="same repository scope"):
        build_portfolio(_manifest(tmp_path))

    second = tmp_path / "two.json"
    payload = json.loads(second.read_text(encoding="utf-8"))
    payload["attribution"]["actor_partition"]["repo_scope_digest"] = "d" * 64
    second.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    shutil.rmtree(tmp_path / "two-attestation")
    create_attestation_bundle(
        second,
        tmp_path / "two-attestation",
        signing=SSHSigningConfig(key, "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
        repo_hint="gitlab.example.com/group/two",
    )
    shutil.rmtree(tmp_path / "one-attestation")
    create_attestation_bundle(
        tmp_path / "one.json",
        tmp_path / "one-attestation",
        signing=SSHSigningConfig(key, "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
        repo_hint="gitlab.example.com/group/two.git/",
    )
    duplicate_hint = _manifest(
        tmp_path,
        extra_first='repo_hint = "gitlab.example.com/group/two.git/"',
    )
    with pytest.raises(PortfolioValidationError, match="same repository hint"):
        build_portfolio(duplicate_hint)


def test_report_v1_without_repo_subject_or_attested_hint_is_rejected(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    first = tmp_path / "one.json"
    payload = json.loads(first.read_text(encoding="utf-8"))
    payload.pop("repo_subject_id")
    first.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    shutil.rmtree(tmp_path / "one-attestation")
    create_attestation_bundle(
        first,
        tmp_path / "one-attestation",
        signing=SSHSigningConfig(tmp_path / "portfolio_ed25519", "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
    )

    with pytest.raises(
        PortfolioValidationError,
        match="report-v1 entries require repo_subject_id or an attested repo_hint",
    ):
        build_portfolio(manifest)


def test_same_repo_subject_cannot_be_counted_at_two_different_oids(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(
        tmp_path,
        "one",
        "a" * 40,
        key,
        repo_subject_id="opaque_repo_01",
    )
    _signed_report(
        tmp_path,
        "two",
        "b" * 40,
        key,
        repo_subject_id="opaque_repo_01",
    )

    with pytest.raises(PortfolioValidationError, match="same repository subject"):
        build_portfolio(_manifest(tmp_path))


def test_manifest_repo_hint_must_match_the_attested_hint(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(
        tmp_path,
        extra_first='repo_hint = "github.com/example/one"',
    )

    with pytest.raises(PortfolioValidationError, match="repository hint is not attested"):
        build_portfolio(manifest)


def test_same_target_oid_is_allowed_when_repository_invariants_differ(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    second = _report(tmp_path / "two.json", "a" * 40)
    payload = json.loads(second.read_text(encoding="utf-8"))
    payload["activity"]["tenant_commits"]["value"] = 4
    second.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    create_attestation_bundle(
        second,
        tmp_path / "two-attestation",
        signing=SSHSigningConfig(key, "portfolio-builder"),
        executed_at="2026-08-31T02:03:04Z",
        repo_hint="gitlab.example.com/group/two",
    )

    portfolio = build_portfolio(_manifest(tmp_path))

    assert portfolio["summary"]["included_repository_count"] == 2
    assert {
        entry["evidence"]["report"]["target_oid"]["value"] for entry in portfolio["entries"]
    } == {"a" * 40}


def test_attestation_cannot_be_reused_for_another_report(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path, first_bundle="two-attestation")

    with pytest.raises(PortfolioValidationError, match="report digest is not attested"):
        build_portfolio(manifest)


def test_attestation_statement_tamper_is_rejected(tmp_path: Path) -> None:
    manifest = _fixture(tmp_path)
    statement = tmp_path / "one-attestation" / "statement.json"
    payload = json.loads(statement.read_text(encoding="utf-8"))
    payload["measurement"]["tool_version"] = "tampered"
    statement.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PortfolioValidationError, match="statement digest mismatch"):
        build_portfolio(manifest)


def test_path_traversal_is_rejected_before_evidence_is_read(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path, first_report="../outside.json")

    with pytest.raises(PortfolioValidationError, match="must stay under"):
        load_portfolio_manifest(manifest)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    key = _ssh_key(base)
    _signed_report(base, "one", "a" * 40, key)
    _signed_report(base, "two", "b" * 40, key)
    manifest = _manifest(base)
    (base / "one.json").unlink()
    _report(external / "outside.json", "a" * 40)
    (base / "one.json").symlink_to(external / "outside.json")

    with pytest.raises(PortfolioValidationError, match="escapes"):
        build_portfolio(manifest)


def test_forbidden_aggregate_field_is_rejected_as_unknown_input(tmp_path: Path) -> None:
    key = _ssh_key(tmp_path)
    _signed_report(tmp_path, "one", "a" * 40, key)
    _signed_report(tmp_path, "two", "b" * 40, key)
    manifest = _manifest(tmp_path, extra_root="score = 100")

    with pytest.raises(PortfolioValidationError, match="unknown keys: score"):
        load_portfolio_manifest(manifest)


def test_output_arithmetic_tamper_is_rejected(tmp_path: Path) -> None:
    portfolio = build_portfolio(_fixture(tmp_path))
    portfolio["summary"]["included_repository_count"] = 1

    with pytest.raises(PortfolioValidationError, match="counts are inconsistent"):
        validate_portfolio_payload(portfolio)


def test_output_duplicate_digest_period_and_activity_arithmetic_fail_closed(
    tmp_path: Path,
) -> None:
    portfolio = build_portfolio(_fixture(tmp_path))
    duplicate_digest = json.loads(json.dumps(portfolio))
    duplicate_digest["entries"][1]["evidence"]["report"]["digest"] = duplicate_digest["entries"][0][
        "evidence"
    ]["report"]["digest"]
    with pytest.raises(PortfolioValidationError, match="report digests must be unique"):
        validate_portfolio_payload(duplicate_digest)

    duplicate_hint = json.loads(json.dumps(portfolio))
    duplicate_hint["entries"][0]["repo_hint"] = duplicate_hint["entries"][1]["repo_hint"]
    with pytest.raises(PortfolioValidationError, match="repository hints must be unique"):
        validate_portfolio_payload(duplicate_hint)

    missing_binding = json.loads(json.dumps(portfolio))
    missing_binding["entries"][0].pop("repository_bindings")
    with pytest.raises(PortfolioValidationError, match="repository_bindings"):
        validate_portfolio_payload(missing_binding)

    duplicate_binding = json.loads(json.dumps(portfolio))
    duplicate_binding["entries"][1]["repository_bindings"] = duplicate_binding["entries"][0][
        "repository_bindings"
    ]
    with pytest.raises(PortfolioValidationError, match="repository bindings must be unique"):
        validate_portfolio_payload(duplicate_binding)

    wrong_period = json.loads(json.dumps(portfolio))
    wrong_period["summary"]["period"] = {
        "start": "2030-01-01",
        "end": "2030-12-31",
        "unit": "date-range",
    }
    with pytest.raises(PortfolioValidationError, match="exact entry span"):
        validate_portfolio_payload(wrong_period)

    impossible_months = json.loads(json.dumps(portfolio))
    impossible_months["entries"][0]["activity_month_count"] = 7
    with pytest.raises(PortfolioValidationError, match="activity_month_count is invalid"):
        validate_portfolio_payload(impossible_months)
