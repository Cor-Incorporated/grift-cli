"""Explicit contribution payload construction and opt-in submission.

Legacy ``tep-contribution-v1`` remains a repo-scope aggregate compatibility
format.  ``tep-contribution-v2`` separates four disclosure profiles:
``aggregate`` and ``named-public`` may use the reviewed ``public-pr`` door, while
``masked`` and ``raw`` are restricted to local or controlled research doors.
The latter two are never uploaded automatically because no controlled remote
destination is authorized by this package.

Payload creation is local by default. ``--open`` is a deliberate network
action that uses the submitter's GitHub credentials and public fork/PR flow;
the confirmation text states that public Git history cannot guarantee full
withdrawal. Measurement entrypoints otherwise remain offline unless users
explicitly select public Forge fetch, update check, or keyless signing.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Mapping

from tep_core.contribution_v2 import (
    ContributionBundle,
    PURPOSE,
    build_contribution_bundle as build_v2_contribution_bundle,
    validate_v2_payload,
)

CONTRIBUTE_PURPOSE = PURPOSE

# What a contribution may carry, stated positively.
#
# This was a denylist until W4: `metrics` shipped every top-level report key
# that was not explicitly excluded, so each new field joined published payloads
# by default and silence meant consent. `library_context` would have ridden
# along the moment library prevalence became a repo-scope observation, taking
# the library names with it. An allowlist makes the next field a decision
# instead of an accident; `test_every_report_key_is_classified` fails when one
# appears in neither set.
_METRICS_ALLOWED = frozenset(
    {
        "attribution",
        "core_activity_period",
        "lineage",
        "origin",
        "provenance",
        "rework",
        "survival",
        "test_cochange",
        "test_frameworks",
    }
)

# Present in reports and deliberately withheld. Kept as a named set rather than
# an absence so that "we thought about this one" is distinguishable from "we
# never saw it".
_WITHHELD_TOP_LEVEL = frozenset(
    {
        "schema_version",  # carried by the envelope, not the metrics block
        "identity",
        "interpretation",
        "repository",
        "context_profile",  # slimmed separately through _CONTEXT_ALLOWED
        "activity",
        # Tenant-scope only. `contribute` refuses tenant reports outright, so
        # these are unreachable today; they are named here so that lifting that
        # restriction cannot publish them silently.
        "experience",
        "role_profile",
        "library_context",
    }
)

_CONTEXT_ALLOWED = {
    "kind",
    "definition_version",
    "analysis_scope",
    "resolved_human_actors",
    "top_actor_share",
    "collaboration_class",
    "pr_flow_share",
    "repo_age_days",
    "lifecycle_stage",
    "conventional_commit_share",
    "language_composition",
    "test_file_ratio",
    "docs_share",
    "dependency_manifests",
    "monorepo_markers",
    "issue_link_density",
    "release_cadence",
    "actor_turnover",
}


def build_contribution(
    report: object,
    *,
    mode: str | None = None,
    privacy: str | None = None,
    door: str = "local",
    receipt_id: str | None = None,
    public_project: Mapping[str, Any] | None = None,
    public_authority: Mapping[str, Any] | None = None,
    key_file: Path | None = None,
    key_fd: int | None = None,
    controlled_context: Mapping[str, Any] | None = None,
    controlled_sidecar: Path | None = None,
    study_manifest: Path | Mapping[str, Any] | None = None,
    repo_subject_id: str | None = None,
    raw_material: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a contribution and preserve the existing library sidecar API.

    CLI callers must use :func:`prepare_contribution` so consent can be
    obtained before either controlled artifact is written.  Direct library
    callers retain the historical behavior: when ``controlled_sidecar`` is
    supplied, that sidecar is written atomically before the payload is
    returned.
    """
    bundle = prepare_contribution(
        report,
        mode=mode,
        privacy=privacy,
        door=door,
        receipt_id=receipt_id,
        public_project=public_project,
        public_authority=public_authority,
        key_file=key_file,
        key_fd=key_fd,
        controlled_context=controlled_context,
        controlled_sidecar=controlled_sidecar,
        study_manifest=study_manifest,
        repo_subject_id=repo_subject_id,
        raw_material=raw_material,
    )
    if bundle.controlled_sidecar is not None:
        assert controlled_sidecar is not None  # validated by prepare_contribution
        _write_json_atomic(controlled_sidecar, bundle.controlled_sidecar)
    return bundle.payload


def prepare_contribution(
    report: object,
    *,
    mode: str | None = None,
    privacy: str | None = None,
    door: str = "local",
    receipt_id: str | None = None,
    public_project: Mapping[str, Any] | None = None,
    public_authority: Mapping[str, Any] | None = None,
    key_file: Path | None = None,
    key_fd: int | None = None,
    controlled_context: Mapping[str, Any] | None = None,
    controlled_sidecar: Path | None = None,
    study_manifest: Path | Mapping[str, Any] | None = None,
    repo_subject_id: str | None = None,
    raw_material: Mapping[str, Any] | None = None,
    purpose: str | None = None,
) -> ContributionBundle:
    """Build payload and optional sidecar entirely in memory.

    Raises ValueError when the report is not repo-scope or the requested
    disclosure contract is incomplete.  This function performs no filesystem
    writes, including parent-directory creation.
    """

    if not isinstance(report, Mapping):
        raise ValueError("contribute report must be a JSON object")

    schema = report.get("schema_version")
    if schema == "alignment-v1":
        raise ValueError("contribute refuses alignment-v1")
    subject = report.get("subject")
    if isinstance(subject, Mapping) and subject.get("kind") == "actor":
        raise ValueError("contribute refuses actor reports")
    if schema == "report-v2":
        if privacy is not None and mode is not None:
            raise ValueError("use privacy, not the deprecated mode argument")
        if privacy is None:
            requested = mode or "aggregate"
            if mode == "masked" and door != "controlled":
                raise ValueError(
                    "deprecated mode=masked requires explicit door=controlled, "
                    "a key file/FD, governance, and controlled sidecar"
                )
            privacy = requested
        if repo_subject_id is not None and study_manifest is None:
            raise ValueError("repo_subject_id requires an explicit controlled study manifest")
        manifest = _load_study_manifest(study_manifest)
        context = dict(controlled_context or manifest.get("governance") or manifest)
        if repo_subject_id is not None:
            context["repo_subject_id"] = repo_subject_id
        if public_project is None and isinstance(manifest.get("public_project"), dict):
            public_project = manifest["public_project"]
        if public_authority is None and isinstance(manifest.get("public_authority"), dict):
            public_authority = manifest["public_authority"]
        if raw_material is None and isinstance(manifest.get("raw_material"), dict):
            raw_material = manifest["raw_material"]
        bundle = build_v2_contribution_bundle(
            report,
            privacy=privacy,
            door=door,
            receipt_id=receipt_id,
            public_project=public_project,
            public_authority=public_authority,
            key_file=key_file,
            key_fd=key_fd,
            controlled_context=context or None,
            raw_material=raw_material,
            # A study manifest may pin the purpose the same way it pins
            # governance; an explicit flag still wins.
            purpose=purpose or manifest.get("purpose"),
        )
        if bundle.controlled_sidecar is not None:
            if controlled_sidecar is None:
                raise ValueError(
                    "masked/raw privacy requires --controlled-sidecar so provenance is not discarded"
                )
        elif controlled_sidecar is not None:
            raise ValueError("controlled-sidecar is only valid for masked/raw privacy")
        return bundle
    if schema != "report-v1":
        raise ValueError(
            f"contribute accepts repo-scope report-v1 or report-v2; {schema} is refused"
        )
    provenance_value = report.get("provenance")
    if not isinstance(provenance_value, Mapping):
        raise ValueError("contribute requires report provenance to be an object")
    scope = provenance_value.get("analysis_scope")
    if scope != "repo":
        raise ValueError(
            "contribute requires a repo-scope report (tenant-scope values are "
            "private to the identity owner and are never included)"
        )
    provenance = provenance_value
    payload: dict[str, Any] = {
        "contribution_schema": "tep-contribution-v1",
        "purpose": CONTRIBUTE_PURPOSE,
        "provenance": {
            key: provenance.get(key)
            for key in (
                "tool_name",
                "tool_version",
                "definition_version",
                "origin_definition_version",
                "activity_definition_version",
                "analysis_scope",
            )
        },
        "metrics": {
            key: value for key, value in report.items() if key in _METRICS_ALLOWED
        },
        "context_profile": _slim_context(report.get("context_profile")),
    }
    _assert_no_private_shape(payload)
    return ContributionBundle(payload=payload, controlled_sidecar=None)


def _load_study_manifest(source: Path | Mapping[str, Any] | None) -> dict[str, Any]:
    if source is None:
        return {}
    if isinstance(source, Mapping):
        return dict(source)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ValueError("study manifest is unreadable") from exc
    try:
        if source.suffix.lower() == ".json":
            parsed = json.loads(raw.decode("utf-8"))
        else:
            parsed = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("study manifest is malformed") from exc
    if not isinstance(parsed, dict):
        raise ValueError("study manifest must be an object/table")
    return parsed


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path = _prepare_output_path(path)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
            )
            handle.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _prepare_output_path(path: Path) -> Path:
    """Return a lexical absolute output path after rejecting symlink traversal.

    Contribution targets commonly live below an untrusted repository.  Both a
    symlink leaf (``contribution.json -> victim``) and a symlink parent
    (``.grift -> victim-dir``) must therefore fail before a temporary file or
    backup is created.  We intentionally inspect lexical components with
    ``lstat`` rather than calling ``resolve()``, which would silently accept
    and follow the attacker-controlled link.
    """

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(candidate))
    if candidate.name in {"", ".", ".."}:
        raise ValueError("contribution output path must name a file")

    # Check every existing lexical ancestor, not only the immediate parent.
    # A root-owned top-level alias such as macOS /var -> /private/var is outside
    # repository control and is allowed; lower/user-owned symlinks still fail.
    ancestors = list(reversed((candidate.parent, *candidate.parent.parents)))
    for directory in ancestors:
        try:
            metadata = directory.lstat()
            mode = metadata.st_mode
        except FileNotFoundError:
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                pass
            try:
                metadata = directory.lstat()
                mode = metadata.st_mode
            except OSError as exc:
                raise ValueError("contribution output parent is unavailable") from exc
        except OSError as exc:
            raise ValueError("contribution output parent is unavailable") from exc
        if stat.S_ISLNK(mode):
            system_root = Path(directory.anchor)
            root_metadata = system_root.lstat()
            trusted_system_alias = (
                directory.parent == system_root
                and metadata.st_uid == 0
                and root_metadata.st_uid == 0
                and not root_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            )
            if trusted_system_alias:
                continue
            raise ValueError("contribution output path must not traverse a symlink")
        if not stat.S_ISDIR(mode):
            raise ValueError("contribution output parent must be a directory")

    try:
        leaf_mode = candidate.lstat().st_mode
    except FileNotFoundError:
        return candidate
    except OSError as exc:
        raise ValueError("contribution output target is unavailable") from exc
    if stat.S_ISLNK(leaf_mode):
        raise ValueError("contribution output target must not be a symlink")
    if not stat.S_ISREG(leaf_mode):
        raise ValueError("contribution output target must be a regular file")
    return candidate


def write_contribution_text_atomic(path: Path, text: str) -> None:
    """Atomically write a non-controlled payload without following symlinks."""

    target = _prepare_output_path(path)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.stage-", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # Recheck the leaf immediately before replace.  os.replace itself
        # replaces a link rather than following it, but rejecting it keeps the
        # user-visible contract fail-closed instead of silently changing type.
        _prepare_output_path(target)
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _stage_private_text(path: Path, text: str) -> Path:
    """Write one fsynced mode-0600 temporary file beside its destination."""

    path = _prepare_output_path(path)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.stage-", dir=path.parent)
    staged = Path(temp_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        staged.unlink(missing_ok=True)
        raise
    return staged


def _reserve_backup_path(path: Path) -> Path:
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.backup-", dir=path.parent)
    os.close(descriptor)
    backup = Path(temp_name)
    backup.unlink()
    return backup


def write_controlled_contribution_atomic(
    *,
    payload_path: Path,
    payload: Mapping[str, Any],
    sidecar_path: Path,
    sidecar: Mapping[str, Any],
) -> None:
    """Commit a controlled payload and sidecar as one recoverable file pair.

    Both complete mode-0600 files are staged before either destination is
    changed.  Any process-level failure during backup, installation, or mode
    enforcement removes newly installed files and restores pre-existing ones,
    preventing a payload-only or sidecar-only result.
    """

    payload_path = _prepare_output_path(Path(payload_path))
    sidecar_path = _prepare_output_path(Path(sidecar_path))
    if payload_path == sidecar_path:
        raise ValueError("controlled payload and sidecar paths must be different")
    if payload_path.exists() and sidecar_path.exists():
        try:
            if os.path.samefile(payload_path, sidecar_path):
                raise ValueError("controlled payload and sidecar must not be the same file")
        except OSError as exc:
            raise ValueError("controlled contribution targets are unreadable") from exc

    payload_text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    sidecar_text = (
        json.dumps(
            sidecar,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    targets = ((payload_path, payload_text), (sidecar_path, sidecar_text))
    staged: list[tuple[Path, Path]] = []
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for target, text in targets:
            staged.append((target, _stage_private_text(target, text)))
        for target, _temporary in staged:
            if target.exists():
                backup = _reserve_backup_path(target)
                os.replace(target, backup)
                backups.append((target, backup))
        for target, temporary in staged:
            os.replace(temporary, target)
            installed.append(target)
        for target in installed:
            os.chmod(target, 0o600)
        for _target, backup in backups:
            backup.unlink()
    except BaseException as exc:
        rollback_errors: list[OSError] = []
        for target in reversed(installed):
            try:
                target.unlink(missing_ok=True)
            except OSError as rollback_error:
                rollback_errors.append(rollback_error)
        for target, backup in reversed(backups):
            if backup.exists():
                try:
                    os.replace(backup, target)
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
        if rollback_errors:
            raise RuntimeError(
                "controlled contribution rollback failed; inspect both explicit target paths"
            ) from exc
        raise
    finally:
        for _target, temporary in staged:
            temporary.unlink(missing_ok=True)
        for _target, backup in backups:
            backup.unlink(missing_ok=True)


def _slim_context(ctx: Any) -> Any:
    if not isinstance(ctx, dict) or ctx.get("kind") != "observed":
        return ctx
    slim = {key: ctx[key] for key in _CONTEXT_ALLOWED if key in ctx}
    return slim


_FORBIDDEN_SUBSTRINGS = ("@",)  # emails must never appear


def _assert_no_private_shape(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    if "@" in text:
        raise ValueError("payload contains an email-shaped string — refuse to build")
    for key in ("canonical_id", "actor", "emails", "path"):
        if f'"{key}"' in text:
            raise ValueError(f"payload contains forbidden key {key!r}")


INTAKE_REPO = "https://github.com/Cor-Incorporated/tep-contributions"

CONFIRMATION_TEXT = """この提出について（必読）/ About this submission (read first):
1. 上記の payload 全文が提出内容のすべてです / The payload above is the entirety of the submission
2. public-prの場合、この提出は公開コーパスに載ります（Git履歴にも残ります）。local/controlledは自動提出されません / With public-pr, this submission enters the public corpus and Git history; local/controlled payloads are not auto-submitted
3. aggregate に repo 名は含まれません。named-public は明示権限のあるproject/accountだけを含みます。特徴の組合せから推測されるリスクはゼロではありません / Aggregate contains no repo name; named-public contains only explicitly authorized project/account data. Re-identification risk from feature combinations is not zero
4. 用途は「{purpose}」に限定され、それ以外（SaaS 等への転用を含む）には使われません（docs/norms.md 保持・削除条項）/ Use is restricted to "{purpose}" — nothing else, including SaaS reuse (see the norms retention section)
5. analyze/report はofflineです。repo/actorの公開取得、update --check、contribute --open、cosign keylessだけが明示network経路です。verifyは保存証跡を再生し再接続しません / analyze/report are offline. Only explicit repo/actor public fetch, update --check, contribute --open, and cosign keyless use the network; verify replays saved evidence without reconnecting
6. door は local / controlled / public-pr です。公開受け口は {intake}。代理PR経路は提出者identityを非公開にしてもpayload自体は公開されます。「private payload door」ではありません / Doors are local, controlled, and public-pr; public intake is {intake}. A proxy PR may hide submitter identity, but the payload itself becomes public; it is not a private-payload door
7. public-pr は削除PRを出しても既存clone/forkを含むGit履歴から完全撤回できません / A public-pr cannot be fully withdrawn from existing Git history, clones, or forks
8. --open を使う場合 / If you use --open: **この方法は公開ドアです。あなたの GitHub アカウント名が PR に表示されます / this is the PUBLIC door; your GitHub account name will appear on the PR**。fork がまだ無い場合は自動作成されます / a fork under your account will be auto-created if you do not have one
""".format(purpose=CONTRIBUTE_PURPOSE, intake=INTAKE_REPO)


def render_confirmation(payload: dict[str, Any]) -> str:
    profile = payload.get("privacy_profile") or payload.get("mode") or "legacy-v1"
    door = payload.get("door") or "local"
    return (
        "=== contribution payload (full) ===\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + f"\n=== end payload ===\nprofile={profile}; door={door}\n\n"
        + CONFIRMATION_TEXT
    )


def validate_contribution_payload(payload: dict) -> list[str]:
    """Local pre-push check for --open (B-4): mirrors the intake validator's
    schema + needle rails. Returns violation list; non-empty = do not push."""
    violations: list[str] = []
    schema = payload.get("contribution_schema")
    if schema not in {"tep-contribution-v1", "tep-contribution-v2"}:
        violations.append("contribution_schema must be tep-contribution-v1 or tep-contribution-v2")
    if schema == "tep-contribution-v2":
        return validate_v2_payload(payload, for_public_intake=True)
    if payload.get("purpose") != CONTRIBUTE_PURPOSE:
        violations.append("unexpected purpose")
    prov = payload.get("provenance") or {}
    if prov.get("analysis_scope") != "repo":
        violations.append("only repo-scope contributions are accepted")
    import json as _json

    text = _json.dumps(payload, ensure_ascii=False)
    if "@" in text:
        violations.append("email-shaped string present")
    forbidden = {"canonical_id", "emails", "path", "repo", "repository"}
    if schema == "tep-contribution-v1":
        forbidden = forbidden | {"actor", "actors"}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in forbidden:
                    violations.append(f"forbidden key {key!r}")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return violations
