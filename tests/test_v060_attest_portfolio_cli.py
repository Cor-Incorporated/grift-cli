"""CLI-level attestation and portfolio falsification with real external tools."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

import tep_core.portfolio as portfolio_module
from git_fixture import commit, git, init_repo
from tep_core.portfolio import PortfolioValidationError, publish_portfolio_artifacts

ROOT = Path(__file__).resolve().parents[1]


def _cli(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    process_env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        **(env or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "tep_cli", *args],
        cwd=cwd or ROOT,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _write_identity(path: Path, email: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                'schema_version = "identity-v1"',
                "",
                "[[actors]]",
                'canonical_id = "subject_01"',
                f'emails = ["{email}"]',
                'attribution_state = "verified"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _repository(root: Path, name: str, *, email: str, remote: str) -> tuple[Path, Path]:
    repo = init_repo(root / name)
    git(repo, "remote", "add", "origin", remote)
    commit(
        repo,
        email=email,
        date="2026-01-02",
        message=f"feat: initialize {name}",
        filename="app.py",
        content=f"VALUE = {name!r}\n",
        name="Consenting Actor",
    )
    identity = _write_identity(repo / ".tep" / "identity.toml", email)
    return repo, identity


def _report(repo: Path, identity: Path, destination: Path) -> Path:
    result = _cli(
        "analyze",
        str(repo),
        "--scope",
        "tenant",
        "--identity",
        str(identity),
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "report-v1"
    assert payload["identity"] == {"pending_attribution": False, "actor_count": 1}
    destination.write_text(result.stdout, encoding="utf-8")
    return destination


def _actor_report(repo: Path, identity: Path, destination: Path) -> Path:
    result = _cli(
        "actor",
        "subject_01",
        str(repo),
        "--identity",
        str(identity),
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "report-v2"
    assert payload["subject"]["canonical_id"] == "subject_01"
    destination.write_text(result.stdout, encoding="utf-8")
    return destination


def _ssh_material(root: Path) -> tuple[Path, Path]:
    ssh_keygen = shutil.which("ssh-keygen")
    assert ssh_keygen, "OpenSSH ssh-keygen is required for attestation CLI E2E"
    private_key = root / "id_ed25519"
    subprocess.run(
        [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    os.chmod(private_key, 0o600)
    public_key = private_key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    allowed_signers = root / "allowed_signers"
    allowed_signers.write_text(f"trusted-builder {public_key}\n", encoding="utf-8")
    return private_key, allowed_signers


def _attest_ssh(
    report: Path,
    repo: Path,
    identity: Path,
    bundle: Path,
    private_key: Path,
    *,
    repo_hint: str | None = None,
) -> dict[str, Any]:
    arguments = [
        "attest",
        str(report),
        "--repo",
        str(repo),
        "--identity",
        str(identity),
        "--out",
        str(bundle),
        "--sign",
        "ssh",
        "--ssh-key",
        str(private_key),
        "--principal",
        "trusted-builder",
    ]
    if repo_hint is not None:
        arguments.extend(["--repo-hint", repo_hint])
    result = _cli(*arguments)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _verify_ssh(
    report: Path,
    repo: Path,
    bundle: Path,
    allowed_signers: Path,
    *,
    principal: str = "trusted-builder",
    identity: Path | None = None,
):
    arguments = [
        "verify",
        "--report",
        str(report),
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--allowed-signers",
        str(allowed_signers),
        "--principal",
        principal,
    ]
    if identity is not None:
        arguments.extend(["--identity", str(identity)])
    return _cli(*arguments)


def _assert_component(payload: dict[str, Any], name: str, status: str) -> None:
    assert payload[name]["status"] == status, payload


def _forbidden_keys(node: Any) -> set[str]:
    forbidden = {
        "score",
        "scores",
        "rank",
        "ranking",
        "grade",
        "rating",
        "average",
        "mean",
        "weight",
        "weighted",
        "percentile",
    }
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower().replace("-", "_") in forbidden:
                found.add(str(key))
            found |= _forbidden_keys(value)
    elif isinstance(node, list):
        for value in node:
            found |= _forbidden_keys(value)
    return found


def test_cli_ssh_attestation_success_and_five_independent_falsifications(
    tmp_path: Path,
) -> None:
    repo, identity = _repository(
        tmp_path,
        "signed-repo",
        email="actor-one@example.test",
        remote="https://github.com/example/private-observation.git",
    )
    report = _report(repo, identity, tmp_path / "report.json")
    private_key, allowed_signers = _ssh_material(tmp_path)
    bundle = tmp_path / "attestation"
    created = _attest_ssh(report, repo, identity, bundle, private_key)
    assert created["schema_version"] == "tep-attest-bundle-v1"
    statement = json.loads((bundle / "statement.json").read_text(encoding="utf-8"))
    assert "repo_hint" not in statement
    assert str(repo) not in json.dumps(statement)

    # 1. The real OpenSSH signature, report bytes, and repository recomputation all verify.
    valid = _verify_ssh(report, repo, bundle, allowed_signers, identity=identity)
    assert valid.returncode == 0, valid.stderr + valid.stdout
    valid_payload = json.loads(valid.stdout)
    assert valid_payload["overall"] == "VERIFIED"
    for component in ("statement", "signature", "report_hash", "recompute"):
        _assert_component(valid_payload, component, "VERIFIED")
    assert "数値の正しさ" in valid_payload["notice"]

    # 2. Exactly one appended byte changes only the signed report-byte binding.
    original_report = report.read_bytes()
    report.write_bytes(original_report + b" ")
    assert report.stat().st_size == len(original_report) + 1
    report_tamper = _verify_ssh(report, repo, bundle, allowed_signers, identity=identity)
    assert report_tamper.returncode == 1
    report_payload = json.loads(report_tamper.stdout)
    _assert_component(report_payload, "signature", "VERIFIED")
    _assert_component(report_payload, "report_hash", "MISMATCH")
    _assert_component(report_payload, "recompute", "VERIFIED")
    report.write_bytes(original_report)

    # 3. A statement byte change remains separate from report and repository checks.
    statement_bundle = tmp_path / "statement-tamper"
    shutil.copytree(bundle, statement_bundle)
    statement_path = statement_bundle / "statement.json"
    statement_payload = json.loads(statement_path.read_text(encoding="utf-8"))
    statement_payload["executed_at"] = "2026-08-31T00:00:01Z"
    statement_bytes = json.dumps(
        statement_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    statement_path.write_bytes(statement_bytes)
    manifest_path = statement_bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["statement"]["digest"]["value"] = hashlib.sha256(statement_bytes).hexdigest()
    manifest_path.write_bytes(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    statement_tamper = _verify_ssh(
        report, repo, statement_bundle, allowed_signers, identity=identity
    )
    assert statement_tamper.returncode == 1
    statement_payload = json.loads(statement_tamper.stdout)
    _assert_component(statement_payload, "statement", "VERIFIED")
    _assert_component(statement_payload, "signature", "INVALID")
    _assert_component(statement_payload, "report_hash", "VERIFIED")
    _assert_component(statement_payload, "recompute", "VERIFIED")

    # 4. A signature byte change affects only detached-signature integrity.
    signature_bundle = tmp_path / "signature-tamper"
    shutil.copytree(bundle, signature_bundle)
    signature = signature_bundle / "statement.json.sig"
    signature_bytes = signature.read_bytes()
    signature.write_bytes(signature_bytes[:-1] + bytes([signature_bytes[-1] ^ 1]))
    signature_tamper = _verify_ssh(
        report, repo, signature_bundle, allowed_signers, identity=identity
    )
    assert signature_tamper.returncode == 1
    signature_payload = json.loads(signature_tamper.stdout)
    _assert_component(signature_payload, "statement", "VERIFIED")
    _assert_component(signature_payload, "signature", "INVALID")
    _assert_component(signature_payload, "report_hash", "VERIFIED")
    _assert_component(signature_payload, "recompute", "VERIFIED")

    # 5. A different recipient principal cannot inherit trust from allowed_signers.
    trust_tamper = _verify_ssh(
        report,
        repo,
        bundle,
        allowed_signers,
        principal="other-builder",
        identity=identity,
    )
    assert trust_tamper.returncode == 1
    trust_payload = json.loads(trust_tamper.stdout)
    _assert_component(trust_payload, "signature", "MISMATCH")
    _assert_component(trust_payload, "report_hash", "VERIFIED")

    # 6. Another repository cannot be used for recomputation, even with valid bytes/signature.
    other_repo, _ = _repository(
        tmp_path,
        "other-repo",
        email="actor-two@example.test",
        remote="https://gitlab.com/example/other.git",
    )
    repo_tamper = _verify_ssh(report, other_repo, bundle, allowed_signers, identity=identity)
    assert repo_tamper.returncode == 2
    repo_payload = json.loads(repo_tamper.stdout)
    _assert_component(repo_payload, "signature", "VERIFIED")
    _assert_component(repo_payload, "report_hash", "VERIFIED")
    _assert_component(repo_payload, "recompute", "CANNOT_VERIFY")


def test_cli_missing_report_still_verifies_statement_and_signature(tmp_path: Path) -> None:
    repo, identity = _repository(
        tmp_path,
        "missing-report-repo",
        email="missing-report@example.test",
        remote="https://github.com/example/missing-report.git",
    )
    report = _report(repo, identity, tmp_path / "report.json")
    private_key, allowed_signers = _ssh_material(tmp_path)
    bundle = tmp_path / "attestation"
    _attest_ssh(report, repo, identity, bundle, private_key)
    report.unlink()

    result = _verify_ssh(report, repo, bundle, allowed_signers, identity=identity)

    assert result.returncode == 2, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    _assert_component(payload, "statement", "VERIFIED")
    _assert_component(payload, "signature", "VERIFIED")
    _assert_component(payload, "report_hash", "CANNOT_VERIFY")
    _assert_component(payload, "recompute", "CANNOT_VERIFY")


def test_cli_verify_honors_explicit_external_identity_for_recomputation(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "external-identity-repo")
    email = "external-actor@example.test"
    commit(
        repo,
        email=email,
        date="2026-01-02",
        message="feat: external identity",
        filename="app.py",
        name="External Actor",
    )
    identity = _write_identity(tmp_path / "identity.toml", email)
    report = _report(repo, identity, tmp_path / "external-report.json")
    private_key, allowed_signers = _ssh_material(tmp_path)
    bundle = tmp_path / "external-attestation"
    _attest_ssh(report, repo, identity, bundle, private_key)

    verified = _verify_ssh(
        report,
        repo,
        bundle,
        allowed_signers,
        identity=identity,
    )

    assert verified.returncode == 0, verified.stderr + verified.stdout
    payload = json.loads(verified.stdout)
    assert payload["overall"] == "VERIFIED"
    _assert_component(payload, "recompute", "VERIFIED")


def _portfolio_manifest(
    path: Path,
    *,
    binding: str = "self_declared",
    second_report: str = "two.json",
    second_bundle: str = "two-attestation",
    second_subject: str = "subject_01",
) -> Path:
    path.write_text(
        f'''schema_version = "tep-portfolio-manifest-v1"
portfolio_id = "portfolio_cli"
subject_id = "subject_01"
subject_binding = "{binding}"
eligible_repository_count = 3

[[entries]]
entry_id = "one"
subject_id = "subject_01"
context = "product"
role = "maintainer"
period_start = "2025-01-01"
period_end = "2025-06-30"
activity_month_count = 5
report = "one.json"
attestation_bundle = "one-attestation"

[[entries]]
entry_id = "two"
subject_id = "{second_subject}"
context = "infrastructure"
role = "creator"
period_start = "2025-07-01"
period_end = "2026-02-28"
activity_month_count = 7
report = "{second_report}"
attestation_bundle = "{second_bundle}"
''',
        encoding="utf-8",
    )
    return path


def _self_declared_portfolio_fixture(tmp_path: Path) -> Path:
    evidence = tmp_path / "secure-output-evidence"
    evidence.mkdir()
    private_key, _allowed_signers = _ssh_material(tmp_path)
    first_repo, first_identity = _repository(
        tmp_path,
        "secure-output-one",
        email="secure-output-one@example.test",
        remote="https://github.com/example/secure-output-one.git",
    )
    second_repo, second_identity = _repository(
        tmp_path,
        "secure-output-two",
        email="secure-output-two@example.test",
        remote="https://gitlab.com/example/secure-output-two.git",
    )
    first_report = _report(first_repo, first_identity, evidence / "one.json")
    second_report = _report(second_repo, second_identity, evidence / "two.json")
    _attest_ssh(
        first_report,
        first_repo,
        first_identity,
        evidence / "one-attestation",
        private_key,
        repo_hint="github.com/example/secure-output-one",
    )
    _attest_ssh(
        second_report,
        second_repo,
        second_identity,
        evidence / "two-attestation",
        private_key,
        repo_hint="gitlab.com/example/secure-output-two",
    )
    return _portfolio_manifest(evidence / "portfolio.toml")


def test_cli_attested_portfolio_requires_recipient_trust_and_signed_subjects(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "attested-evidence"
    evidence.mkdir()
    private_key, allowed_signers = _ssh_material(tmp_path)
    first_repo, first_identity = _repository(
        tmp_path,
        "attested-one",
        email="attested-one@example.test",
        remote="https://github.com/example/attested-one.git",
    )
    second_repo, second_identity = _repository(
        tmp_path,
        "attested-two",
        email="attested-two@example.test",
        remote="https://gitlab.com/example/attested-two.git",
    )
    first_report = _actor_report(first_repo, first_identity, evidence / "one.json")
    second_report = _actor_report(second_repo, second_identity, evidence / "two.json")
    _attest_ssh(
        first_report,
        first_repo,
        first_identity,
        evidence / "one-attestation",
        private_key,
    )
    _attest_ssh(
        second_report,
        second_repo,
        second_identity,
        evidence / "two-attestation",
        private_key,
    )
    manifest = _portfolio_manifest(evidence / "attested.toml", binding="attested")

    missing = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--out",
        str(tmp_path / "missing-trust"),
    )
    assert missing.returncode == 2
    assert "recipient-supplied trust policy" in missing.stderr
    assert not (tmp_path / "missing-trust").exists()

    incomplete_cosign = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--certificate-identity",
        "https://github.com/example/workflow",
        "--out",
        str(tmp_path / "incomplete-cosign"),
    )
    assert incomplete_cosign.returncode == 2
    assert "requires certificate identity and OIDC issuer" in incomplete_cosign.stderr
    assert not (tmp_path / "incomplete-cosign").exists()

    output = tmp_path / "attested-output"
    verified = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--allowed-signers",
        str(allowed_signers),
        "--principal",
        "trusted-builder",
        "--format",
        "both",
        "--out",
        str(output),
    )
    assert verified.returncode == 0, verified.stderr
    payload = json.loads((output / "portfolio.json").read_text(encoding="utf-8"))
    assert payload["subject_binding"] == {
        "method": "attested",
        "subject_id": "subject_01",
    }
    assert all(
        entry["evidence"]["attestation"]["signature_verification"] == "recipient_trust_verified"
        and entry["evidence"]["attestation"]["bound_subject_id"] == "subject_01"
        for entry in payload["entries"]
    )
    serialized = json.dumps(payload, ensure_ascii=False)
    markdown = (output / "portfolio.md").read_text(encoding="utf-8")
    assert "recipient_trust_verified" in markdown
    assert "signed report subject: `subject_01`" in markdown
    assert str(allowed_signers) not in serialized
    assert str(allowed_signers) not in markdown
    assert str(first_repo) not in serialized
    assert str(second_repo) not in serialized

    wrong = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--allowed-signers",
        str(allowed_signers),
        "--principal",
        "wrong-builder",
        "--out",
        str(tmp_path / "wrong-trust"),
    )
    assert wrong.returncode == 2
    assert "recipient trust verification failed" in wrong.stderr
    assert not (tmp_path / "wrong-trust").exists()


def test_cli_two_repo_portfolio_and_fail_closed_manifest_variants(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    private_key, _ = _ssh_material(tmp_path)
    first_repo, first_identity = _repository(
        tmp_path,
        "portfolio-one",
        email="portfolio-one@example.test",
        remote="https://github.com/example/portfolio-one.git",
    )
    second_repo, second_identity = _repository(
        tmp_path,
        "portfolio-two",
        email="portfolio-two@example.test",
        remote="https://gitlab.com/example/portfolio-two.git",
    )
    first_report = _report(first_repo, first_identity, evidence / "one.json")
    second_report = _report(second_repo, second_identity, evidence / "two.json")
    _attest_ssh(
        first_report,
        first_repo,
        first_identity,
        evidence / "one-attestation",
        private_key,
        repo_hint="github.com/example/portfolio-one",
    )
    _attest_ssh(
        second_report,
        second_repo,
        second_identity,
        evidence / "two-attestation",
        private_key,
        repo_hint="gitlab.com/example/portfolio-two",
    )
    manifest = _portfolio_manifest(evidence / "portfolio.toml")
    output = tmp_path / "portfolio-output"

    result = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--format",
        "both",
        "--out",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads((output / "portfolio.json").read_text(encoding="utf-8"))
    assert (output / "portfolio.md").is_file()
    assert payload["summary"]["eligible_repository_count"] == 3
    assert payload["summary"]["included_repository_count"] == 2
    assert payload["summary"]["disclosure"] == {
        "kind": "declared",
        "numerator": 2,
        "denominator": 3,
        "value": 0.666666666667,
        "unit": "ratio",
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    markdown = (output / "portfolio.md").read_text(encoding="utf-8")
    assert "repo_hint" not in serialized
    assert "github.com/example/portfolio-one" not in serialized + markdown
    assert "gitlab.com/example/portfolio-two" not in serialized + markdown
    assert str(first_repo) not in serialized + markdown
    assert _forbidden_keys(payload) == set()
    for word in ("score", "ranking", "average", "weighted", "percentile"):
        assert word not in (serialized + markdown).lower()

    duplicate = _portfolio_manifest(
        evidence / "duplicate.toml",
        second_report="one.json",
        second_bundle="one-attestation",
    )
    duplicate_result = _cli(
        "portfolio",
        "--manifest",
        str(duplicate),
        "--out",
        str(tmp_path / "duplicate-output"),
    )
    assert duplicate_result.returncode == 2
    assert "same report path" in duplicate_result.stderr
    assert not (tmp_path / "duplicate-output").exists()

    mismatch = _portfolio_manifest(
        evidence / "subject-mismatch.toml",
        second_subject="other_subject",
    )
    mismatch_result = _cli(
        "portfolio",
        "--manifest",
        str(mismatch),
        "--out",
        str(tmp_path / "subject-mismatch-output"),
    )
    assert mismatch_result.returncode == 2
    assert "differs from the portfolio subject" in mismatch_result.stderr
    assert not (tmp_path / "subject-mismatch-output").exists()


def test_cli_portfolio_rejects_parent_and_leaf_symlinks_without_partial_pair(
    tmp_path: Path,
) -> None:
    manifest = _self_declared_portfolio_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    escaped = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--format",
        "both",
        "--out",
        str(linked_parent / "portfolio"),
    )
    assert escaped.returncode == 2
    assert "parent must not be a symlink" in escaped.stderr
    assert list(outside.iterdir()) == []

    output_link = tmp_path / "output-link"
    output_link.symlink_to(outside, target_is_directory=True)
    linked_leaf = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--format",
        "both",
        "--out",
        str(output_link),
    )
    assert linked_leaf.returncode == 2
    assert list(outside.iterdir()) == []

    output = tmp_path / "portfolio-output"
    output.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("do-not-overwrite", encoding="utf-8")
    (output / "portfolio.json").symlink_to(victim)
    leaf = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--format",
        "both",
        "--out",
        str(output),
    )
    assert leaf.returncode == 2
    assert victim.read_text(encoding="utf-8") == "do-not-overwrite"
    assert not (output / "portfolio.md").exists()
    assert not any(path.name.startswith(".grift-portfolio-") for path in tmp_path.iterdir())


def test_portfolio_pair_publish_rolls_back_on_second_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "portfolio-output"
    output.mkdir(mode=0o700)
    (output / "portfolio.json").write_text("old-json", encoding="utf-8")
    (output / "portfolio.md").write_text("old-markdown", encoding="utf-8")
    original_rename = portfolio_module.os.rename
    calls = 0

    def fail_publish(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second rename failure")
        original_rename(*args, **kwargs)

    monkeypatch.setattr(portfolio_module.os, "rename", fail_publish)
    with pytest.raises(PortfolioValidationError, match="previous directory was restored"):
        publish_portfolio_artifacts(
            output,
            json_text="new-json",
            markdown_text="new-markdown",
        )

    assert (output / "portfolio.json").read_text(encoding="utf-8") == "old-json"
    assert (output / "portfolio.md").read_text(encoding="utf-8") == "old-markdown"
    assert not any(path.name.startswith(".grift-portfolio-") for path in tmp_path.iterdir())


def test_portfolio_private_modes_and_system_tmp_alias_are_supported() -> None:
    root = Path(tempfile.mkdtemp(prefix="grift-v060-secure-", dir="/tmp"))
    try:
        output = root / "portfolio"
        publish_portfolio_artifacts(
            output,
            json_text="{}\n",
            markdown_text="# portfolio\n",
        )
        assert (output.stat().st_mode & 0o777) == 0o700
        assert all((member.stat().st_mode & 0o777) == 0o600 for member in output.iterdir())
    finally:
        shutil.rmtree(root)


def test_cli_keyful_cosign_when_binary_is_available(tmp_path: Path) -> None:
    cosign = shutil.which("cosign")
    if cosign is None:
        pytest.skip("NOT_PROVEN: cosign binary is not installed on this host")
    repo, identity = _repository(
        tmp_path,
        "cosign-repo",
        email="cosign-actor@example.test",
        remote="https://github.com/example/cosign-repo.git",
    )
    report = _actor_report(repo, identity, tmp_path / "cosign-report.json")
    prefix = tmp_path / "cosign-test"
    generated = subprocess.run(
        [cosign, "generate-key-pair", "--output-key-prefix", str(prefix)],
        env={**os.environ, "COSIGN_PASSWORD": ""},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert generated.returncode == 0, generated.stderr
    private_key = prefix.with_suffix(".key")
    public_key = prefix.with_suffix(".pub")
    os.chmod(private_key, 0o600)
    bundle = tmp_path / "cosign-attestation"

    signed = _cli(
        "attest",
        str(report),
        "--repo",
        str(repo),
        "--identity",
        str(identity),
        "--out",
        str(bundle),
        "--sign",
        "cosign",
        "--cosign-key",
        str(private_key),
        "--cosign-public-key",
        str(public_key),
        env={"COSIGN_PASSWORD": ""},
    )
    assert signed.returncode == 0, signed.stderr
    verified = _cli(
        "verify",
        "--report",
        str(report),
        "--bundle",
        str(bundle),
        "--repo",
        str(repo),
        "--identity",
        str(identity),
        "--cosign-public-key",
        str(public_key),
    )
    assert verified.returncode == 0, verified.stderr + verified.stdout
    payload = json.loads(verified.stdout)
    _assert_component(payload, "signature", "VERIFIED")
    _assert_component(payload, "report_hash", "VERIFIED")
    _assert_component(payload, "recompute", "VERIFIED")

    manifest = tmp_path / "cosign-portfolio.toml"
    manifest.write_text(
        """schema_version = "tep-portfolio-manifest-v1"
portfolio_id = "cosign_portfolio"
subject_id = "subject_01"
subject_binding = "attested"
eligible_repository_count = 1

[[entries]]
entry_id = "cosign"
subject_id = "subject_01"
context = "product"
role = "maintainer"
period_start = "2026-01-01"
period_end = "2026-01-31"
activity_month_count = 1
report = "cosign-report.json"
attestation_bundle = "cosign-attestation"
""",
        encoding="utf-8",
    )
    portfolio_out = tmp_path / "cosign-portfolio-out"
    portfolio = _cli(
        "portfolio",
        "--manifest",
        str(manifest),
        "--cosign-public-key",
        str(public_key),
        "--format",
        "json",
        "--out",
        str(portfolio_out),
    )
    assert portfolio.returncode == 0, portfolio.stderr
    portfolio_payload = json.loads(portfolio.stdout)
    assert portfolio_payload["subject_binding"]["method"] == "attested"
    assert (
        portfolio_payload["entries"][0]["evidence"]["attestation"]["signature_verification"]
        == "recipient_trust_verified"
    )
