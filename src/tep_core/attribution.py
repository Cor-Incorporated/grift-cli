"""Resolve repo-local Git actors before attaching optional forge identities.

An ``InferredActor`` is a deterministic cluster of primary-author records in one
repository snapshot. It is not a claim that the cluster is a natural person.
Public forge data may decorate a cluster, but it must never create, merge, or
split one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tep_core.gitutil import GitCommit
from tep_core.identity import Actor, IdentityConfig, empty_identity
from tep_core.observation import Observed
from tep_core.origin import OriginResult, is_bot_email

ACTOR_ID_PATTERN = (
    r"^(github:[A-Za-z0-9._-]+|[a-z0-9][a-z0-9._-]{0,63}|"
    r"actor_[a-f0-9]{12,32}|actor_unknown)$"
)
ACTOR_ID_RE = re.compile(ACTOR_ID_PATTERN)
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_OID_RE = re.compile(r"^[0-9a-fA-F]+$")
_MAILMAP_EMAIL_RE = re.compile(r"<([^<>]+)>")


@dataclass(frozen=True)
class GitObjectId:
    """A Git object name with an explicit hash algorithm."""

    algorithm: str
    value: str


@dataclass(frozen=True)
class MailmapEntry:
    """One parsed, fixed-tree mailmap rule."""

    canonical_email: str
    alias_email: str
    canonical_name: str | None = None
    alias_name: str | None = None


@dataclass(frozen=True)
class MailmapSnapshot:
    """Mailmap bytes resolved from a commit, never from the working tree."""

    target_oid: GitObjectId
    blob_oid: GitObjectId | None
    present: bool
    entries: tuple[MailmapEntry, ...] = ()


@dataclass(frozen=True)
class PublicAccount:
    """Provider-neutral account evidence attached after actor resolution."""

    provider: str
    host: str
    account_id: str
    handle: str | None = None
    profile_url: str | None = None
    evidence: str | None = None

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        host = self.host.strip().lower().rstrip(".")
        account_id = self.account_id.strip()
        handle = self.handle.strip() if self.handle and self.handle.strip() else None
        if not provider or not host or not account_id:
            raise ValueError("public account requires provider, host, and stable account_id")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "account_id", account_id)
        object.__setattr__(self, "handle", handle)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.provider, self.host, self.account_id)


@dataclass
class InferredActor:
    actor_id: str
    display_name: str
    display_status: str
    internal_actor_id: str = ""
    emails: tuple[str, ...] = ()
    canonical_emails: tuple[str, ...] = ()
    github_login: str | None = None
    commit_shas: tuple[str, ...] = ()
    merge_count: int = 0
    coauthored_count: int = 0
    nonmerge_count: int = 0
    public_handle_basis: str | None = None
    resolution_basis: str = "unresolved"
    public_accounts: tuple[PublicAccount, ...] = ()
    public_account_status: str = "not_requested"


@dataclass
class AttributionIndex:
    actors: tuple[InferredActor, ...]
    sha_to_actor: dict[str, str] = field(default_factory=dict)
    unresolved_shas: tuple[str, ...] = ()
    bot_count: int = 0
    merge_count: int = 0
    coauthored_count: int = 0
    mailmap_present: bool = False
    join_matched: int = 0
    join_unmatched: int = 0
    join_ambiguous: int = 0
    commit_login_count: int = 0
    manifest_login_count: int | None = None
    repo_scope_digest: str = ""
    object_format: str = "sha1"
    partition_digest: str = ""
    sha_to_actor_digest: str = ""
    account_conflicts: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class _Resolution:
    partition_key: str
    actor_id: str
    display_name: str
    display_status: str
    resolution_basis: str
    canonical_email: str | None
    identity_login: str | None = None


def parse_git_oid(value: str) -> GitObjectId:
    normalized = value.strip().lower()
    if not _OID_RE.fullmatch(normalized):
        raise ValueError(f"invalid Git object id: {value!r}")
    if len(normalized) == 40:
        algorithm = "sha1"
    elif len(normalized) == 64:
        algorithm = "sha256"
    else:
        raise ValueError(f"unsupported Git object id length: {len(normalized)}")
    return GitObjectId(algorithm=algorithm, value=normalized)


def _run_git(
    repo: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_NO_LAZY_FETCH"] = "1"
    result = subprocess.run(  # noqa: S603
        [
            "git",
            "--no-replace-objects",
            "-c",
            "safe.directory=*",
            "-C",
            str(repo),
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=environment,
    )
    if check and result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def read_mailmap_at_revision(repo: Path, revision: str) -> MailmapSnapshot:
    """Read ``.mailmap`` from ``revision`` without consulting the checkout."""

    resolved = _run_git(
        repo,
        ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
    )
    target_oid = parse_git_oid(resolved.stdout.strip())
    blob_result = _run_git(
        repo,
        ["rev-parse", "--verify", "--end-of-options", f"{target_oid.value}:.mailmap"],
        check=False,
    )
    if blob_result.returncode != 0:
        return MailmapSnapshot(target_oid=target_oid, blob_oid=None, present=False)
    blob_oid = parse_git_oid(blob_result.stdout.strip())
    text = _run_git(repo, ["cat-file", "-p", blob_oid.value]).stdout
    return MailmapSnapshot(
        target_oid=target_oid,
        blob_oid=blob_oid,
        present=True,
        entries=parse_mailmap(text),
    )


def _without_comment(line: str) -> str:
    in_address = False
    for index, char in enumerate(line):
        if char == "<":
            in_address = True
        elif char == ">":
            in_address = False
        elif char == "#" and not in_address:
            return line[:index]
    return line


def _normal_email(value: str) -> str:
    return value.strip().lower()


def _normal_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def parse_mailmap(text: str) -> tuple[MailmapEntry, ...]:
    """Parse the four documented ``.mailmap`` forms."""

    entries: list[MailmapEntry] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = _without_comment(raw_line).strip()
        if not line:
            continue
        matches = list(_MAILMAP_EMAIL_RE.finditer(line))
        if len(matches) not in {1, 2}:
            raise ValueError(f"invalid .mailmap line {line_number}: expected one or two emails")
        suffix = line[matches[-1].end() :].strip()
        if suffix:
            raise ValueError(f"invalid .mailmap line {line_number}: trailing content")
        canonical_name = line[: matches[0].start()].strip() or None
        canonical_email = _normal_email(matches[0].group(1))
        if not canonical_email:
            raise ValueError(f"invalid .mailmap line {line_number}: empty canonical email")
        if len(matches) == 1:
            alias_email = canonical_email
            alias_name = None
        else:
            alias_name = line[matches[0].end() : matches[1].start()].strip() or None
            alias_email = _normal_email(matches[1].group(1))
            if not alias_email:
                raise ValueError(f"invalid .mailmap line {line_number}: empty alias email")
        entries.append(
            MailmapEntry(
                canonical_email=canonical_email,
                alias_email=alias_email,
                canonical_name=canonical_name,
                alias_name=alias_name,
            )
        )
    return tuple(entries)


def _mailmap_entries(
    mailmap: MailmapSnapshot | str | Iterable[MailmapEntry] | None,
) -> tuple[MailmapEntry, ...]:
    if mailmap is None:
        return ()
    if isinstance(mailmap, MailmapSnapshot):
        return mailmap.entries
    if isinstance(mailmap, str):
        return parse_mailmap(mailmap)
    return tuple(mailmap)


def canonicalize_author(
    *, name: str, email: str, entries: Iterable[MailmapEntry]
) -> tuple[str, str, bool]:
    """Apply mailmap rules using case-insensitive author matching."""

    original_name = name.strip()
    original_email = _normal_email(email)
    selected: MailmapEntry | None = None
    rows = tuple(entries)
    # Later lines override earlier lines. Name+email rules are more specific.
    for row in rows:
        if row.alias_name is None:
            continue
        if _normal_email(row.alias_email) == original_email and _normal_name(
            row.alias_name
        ) == _normal_name(original_name):
            selected = row
    if selected is None:
        for row in rows:
            if row.alias_name is None and _normal_email(row.alias_email) == original_email:
                selected = row
    if selected is None:
        return original_name, original_email, False
    return (
        selected.canonical_name or original_name,
        _normal_email(selected.canonical_email),
        True,
    )


def stable_actor_hash(seed: str, *, repo_scope_digest: str | None = None) -> str:
    """Return a 128-bit display-safe actor id from a resolution seed."""

    scope = repo_scope_digest or "unscoped"
    digest = hashlib.sha256(f"tep-actor-v2\0{scope}\0{seed}".encode("utf-8")).hexdigest()
    return f"actor_{digest[:32]}"


def slug_author(name: str) -> str | None:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-._")
    if not slug:
        return None
    return slug[:64]


def _identity_match(identity: IdentityConfig, email: str) -> Actor | None:
    return identity.actor_for_email(email)


def _infer_object_format(commits: Sequence[GitCommit]) -> str:
    formats = {parse_git_oid(item.sha).algorithm for item in commits}
    if len(formats) > 1:
        raise ValueError("mixed Git object formats are not a valid repository snapshot")
    return next(iter(formats), "sha1")


def derive_repo_scope_digest(
    commits: Sequence[GitCommit], canonical_origin: str | None = None
) -> tuple[str, str]:
    """Derive a repo-local namespace from roots and a pre-sanitized origin.

    URL parsing and credential removal belong to the caller's forge locator.
    ``canonical_origin`` is therefore hashed exactly as supplied, including an
    explicit JSON ``null`` when no remote identity is available.
    """

    object_format = _infer_object_format(commits)
    commit_oids = {item.sha.lower() for item in commits}
    roots = sorted(
        item.sha.lower()
        for item in commits
        if not any(parent.lower() in commit_oids for parent in item.parents)
    )
    payload = {
        "domain": "tep-repo-scope-v1",
        "object_format": object_format,
        "canonical_origin": canonical_origin,
        "roots": roots,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest(), object_format


def _resolve_actor(
    *,
    email: str,
    name: str,
    identity: IdentityConfig,
    mailmap: tuple[MailmapEntry, ...],
    repo_scope_digest: str,
) -> _Resolution | None:
    raw_email = _normal_email(email)
    raw_name = name.strip()
    identity_match = _identity_match(identity, raw_email) if raw_email else None
    canonical_name, canonical_email, mapped = canonicalize_author(
        name=raw_name,
        email=raw_email,
        entries=mailmap,
    )
    if identity_match is None and canonical_email:
        identity_match = _identity_match(identity, canonical_email)
    if identity_match is not None:
        login = identity_match.github_login
        return _Resolution(
            partition_key=f"identity\0{identity_match.canonical_id}",
            actor_id=identity_match.canonical_id,
            display_name=login or identity_match.canonical_id,
            display_status="public_handle" if login else "identity_alias",
            resolution_basis="explicit_identity",
            canonical_email=canonical_email or raw_email or None,
            identity_login=login,
        )
    if canonical_email:
        basis = "mailmap" if mapped else "email"
        # A canonical address and an alias mapped to that address are the same
        # partition. ``basis`` remains evidence metadata, not part of the key.
        seed = f"email\0{canonical_email}"
        actor_id = stable_actor_hash(seed, repo_scope_digest=repo_scope_digest)
        safe_name = canonical_name if canonical_name and "@" not in canonical_name else ""
        return _Resolution(
            partition_key=seed,
            actor_id=actor_id,
            display_name=safe_name or actor_id,
            display_status="git_author_name" if safe_name else "stable_hash",
            resolution_basis=basis,
            canonical_email=canonical_email,
        )
    if raw_name:
        name_key = _normal_name(raw_name)
        seed = f"name\0{name_key}"
        actor_id = stable_actor_hash(seed, repo_scope_digest=repo_scope_digest)
        safe_name = raw_name if "@" not in raw_name else actor_id
        return _Resolution(
            partition_key=seed,
            actor_id=actor_id,
            display_name=safe_name,
            display_status="git_author_name" if safe_name != actor_id else "stable_hash",
            resolution_basis="missing_email_name",
            canonical_email=None,
        )
    return None


def infer_actor_key(
    *,
    email: str,
    name: str,
    identity: IdentityConfig,
    sha_login: str | None,
    repo_scope_digest: str | None = None,
    mailmap: MailmapSnapshot | str | Iterable[MailmapEntry] | None = None,
) -> tuple[str, str, str]:
    """Compatibility helper for one author record.

    ``sha_login`` is deliberately ignored for partitioning. Callers that have
    forge evidence must attach it with :func:`attach_public_identities`.
    """

    del sha_login
    resolved = _resolve_actor(
        email=email,
        name=name,
        identity=identity,
        mailmap=_mailmap_entries(mailmap),
        repo_scope_digest=repo_scope_digest or hashlib.sha256(b"tep-unscoped").hexdigest(),
    )
    if resolved is None:
        return "actor_unknown", "actor_unknown", "actor_unknown"
    return resolved.actor_id, resolved.display_name, resolved.display_status


def _digest_mapping(mapping: Mapping[str, str], *, domain: str) -> str:
    payload = {
        "domain": domain,
        "mapping": sorted((key.lower(), value) for key, value in mapping.items()),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve_git_actor_partition(
    commits: list[GitCommit],
    origin: OriginResult,
    identity: IdentityConfig | None = None,
    *,
    mailmap: MailmapSnapshot | str | Iterable[MailmapEntry] | None = None,
    mailmap_present: bool = False,
    coauthor_shas: set[str] | None = None,
    repo_scope_digest: str | None = None,
    canonical_origin: str | None = None,
) -> AttributionIndex:
    """Resolve the Git-only actor partition before any provider lookup."""

    identity = identity or empty_identity()
    rows = _mailmap_entries(mailmap)
    if isinstance(mailmap, MailmapSnapshot):
        mailmap_present = mailmap.present
    elif mailmap is not None:
        mailmap_present = bool(rows)
    derived_scope, object_format = derive_repo_scope_digest(commits, canonical_origin)
    scope = (repo_scope_digest or derived_scope).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", scope):
        raise ValueError("repo_scope_digest must be a lowercase SHA-256 digest")
    coauthors = {item.lower() for item in (coauthor_shas or set())}
    buckets: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    bot_count = 0
    merge_count = 0
    coauthored_count = 0
    for item in commits:
        parse_git_oid(item.sha)
        klass = origin.classes_by_sha.get(item.sha)
        if klass == "bot" or is_bot_email(item.author_email):
            bot_count += 1
            continue
        if item.is_merge:
            merge_count += 1
        if item.sha.lower() in coauthors:
            coauthored_count += 1
        resolution = _resolve_actor(
            email=item.author_email,
            name=item.author_name,
            identity=identity,
            mailmap=rows,
            repo_scope_digest=scope,
        )
        if resolution is None:
            unresolved.append(item.sha)
            continue
        bucket = buckets.setdefault(
            resolution.partition_key,
            {
                "actor_id": resolution.actor_id,
                "internal_actor_id": stable_actor_hash(
                    resolution.partition_key,
                    repo_scope_digest=scope,
                ),
                "display_names": {},
                "display_status": resolution.display_status,
                "resolution_basis": resolution.resolution_basis,
                "emails": set(),
                "canonical_emails": set(),
                "shas": [],
                "merge_count": 0,
                "coauthored_count": 0,
                "nonmerge": 0,
                "identity_login": resolution.identity_login,
            },
        )
        if resolution.resolution_basis == "mailmap":
            bucket["resolution_basis"] = "mailmap"
        if resolution.display_name:
            display_names = bucket["display_names"]
            display_names[resolution.display_name] = (
                display_names.get(resolution.display_name, 0) + 1
            )
        raw_email = _normal_email(item.author_email)
        if raw_email:
            bucket["emails"].add(raw_email)
        if resolution.canonical_email:
            bucket["canonical_emails"].add(resolution.canonical_email)
        bucket["shas"].append(item.sha)
        if item.is_merge:
            bucket["merge_count"] += 1
        else:
            bucket["nonmerge"] += 1
        if item.sha.lower() in coauthors:
            bucket["coauthored_count"] += 1

    # Preserve the v0.5 identityless ``actor alice`` UX only when an author-name
    # slug is unambiguous inside this partition. Same-name actors with different
    # emails all fall back to repo-scoped hashes; traversal order cannot decide
    # which actor receives the readable id.
    chosen_names: dict[str, str] = {}
    slug_counts: dict[str, int] = {}
    explicit_ids = {
        str(bucket["actor_id"])
        for bucket in buckets.values()
        if bucket["resolution_basis"] == "explicit_identity"
    }
    for partition_key, bucket in buckets.items():
        name_counts = bucket["display_names"]
        names = sorted(
            name_counts,
            key=lambda item: (-name_counts[item], item.casefold(), item),
        )
        chosen = names[0] if names else str(bucket["actor_id"])
        chosen_names[partition_key] = chosen
        if bucket["resolution_basis"] == "explicit_identity" or "@" in chosen:
            continue
        slug = slug_author(chosen)
        if slug:
            slug_counts[slug] = slug_counts.get(slug, 0) + 1

    actors: list[InferredActor] = []
    sha_to_actor: dict[str, str] = {}
    assigned_ids: set[str] = set()
    for partition_key, bucket in buckets.items():
        actor_id = str(bucket["actor_id"])
        identity_login = bucket["identity_login"]
        display_name = identity_login or chosen_names[partition_key]
        if bucket["resolution_basis"] != "explicit_identity" and "@" not in display_name:
            slug = slug_author(display_name)
            if slug and slug_counts.get(slug) == 1 and slug not in explicit_ids:
                actor_id = slug
        if actor_id in assigned_ids:
            raise ValueError("actor id collision across distinct resolution seeds")
        assigned_ids.add(actor_id)
        shas = tuple(bucket["shas"])
        actor = InferredActor(
            actor_id=actor_id,
            display_name=display_name,
            display_status=str(bucket["display_status"]),
            internal_actor_id=str(bucket["internal_actor_id"]),
            emails=tuple(sorted(bucket["emails"])),
            canonical_emails=tuple(sorted(bucket["canonical_emails"])),
            github_login=identity_login,
            commit_shas=shas,
            merge_count=int(bucket["merge_count"]),
            coauthored_count=int(bucket["coauthored_count"]),
            nonmerge_count=int(bucket["nonmerge"]),
            public_handle_basis="identity_declared" if identity_login else None,
            resolution_basis=str(bucket["resolution_basis"]),
        )
        actors.append(actor)
        for sha in shas:
            sha_to_actor[sha] = actor_id
    actors.sort(key=lambda item: (-len(item.commit_shas), item.actor_id))
    sha_digest = _digest_mapping(sha_to_actor, domain="tep-sha-to-actor-v1")
    partition_digest = _digest_mapping(sha_to_actor, domain="tep-actor-partition-v1")
    return AttributionIndex(
        actors=tuple(actors),
        sha_to_actor=sha_to_actor,
        unresolved_shas=tuple(unresolved),
        bot_count=bot_count,
        merge_count=merge_count,
        coauthored_count=coauthored_count,
        mailmap_present=mailmap_present,
        repo_scope_digest=scope,
        object_format=object_format,
        partition_digest=partition_digest,
        sha_to_actor_digest=sha_digest,
    )


def _coerce_public_account(value: PublicAccount | Mapping[str, Any] | str) -> PublicAccount:
    if isinstance(value, PublicAccount):
        return value
    if isinstance(value, str):
        handle = value.strip()
        if not handle:
            raise ValueError("legacy public login must not be empty")
        return PublicAccount(
            provider="github",
            host="github.com",
            account_id=f"legacy-login:{handle.casefold()}",
            handle=handle,
            evidence="commit_sha_to_login",
        )
    raw_evidence = value.get("evidence")
    if isinstance(raw_evidence, Mapping):
        basis = raw_evidence.get("basis")
        evidence = str(basis) if isinstance(basis, str) and basis else None
    else:
        evidence = str(raw_evidence) if raw_evidence is not None else None
    return PublicAccount(
        provider=str(value.get("provider") or ""),
        host=str(value.get("host") or ""),
        account_id=str(value.get("account_id") or ""),
        handle=(str(value["handle"]) if value.get("handle") is not None else None),
        profile_url=(str(value["profile_url"]) if value.get("profile_url") is not None else None),
        evidence=evidence,
    )


def _coerce_public_accounts(value: Any) -> tuple[PublicAccount, ...]:
    if value is None:
        return ()
    if isinstance(value, (PublicAccount, str, Mapping)):
        candidates = (value,)
    elif isinstance(value, Sequence):
        candidates = tuple(value)
    else:
        raise ValueError("public account join must be an account or sequence of accounts")
    by_key: dict[tuple[str, str, str], PublicAccount] = {}
    for candidate in candidates:
        account = _coerce_public_account(candidate)
        previous = by_key.get(account.key)
        if previous is not None and previous != account:
            raise ValueError("conflicting metadata for the same public account id")
        by_key[account.key] = account
    return tuple(by_key[key] for key in sorted(by_key))


def _account_label(key: tuple[str, str, str]) -> str:
    return "|".join(key)


def attach_public_identities(
    index: AttributionIndex,
    sha_to_accounts: Mapping[str, Any] | None,
    *,
    fetched_login_count: int | None = None,
) -> AttributionIndex:
    """Decorate a partition with account evidence without changing clusters."""

    before_partition = index.partition_digest
    before_mapping = dict(index.sha_to_actor)
    normalized = {
        sha.strip().lower(): _coerce_public_accounts(value)
        for sha, value in (sha_to_accounts or {}).items()
    }
    requested = sha_to_accounts is not None
    matched = 0
    unmatched = 0
    ambiguous_joins = 0
    actor_accounts: dict[str, dict[tuple[str, str, str], PublicAccount]] = {
        actor.actor_id: {} for actor in index.actors
    }
    account_actors: dict[tuple[str, str, str], set[str]] = {}
    for sha, actor_id in index.sha_to_actor.items():
        accounts = normalized.get(sha.lower(), ())
        if requested:
            if not accounts:
                unmatched += 1
            elif len(accounts) == 1:
                matched += 1
            else:
                ambiguous_joins += 1
        for account in accounts:
            actor_accounts[actor_id][account.key] = account
            account_actors.setdefault(account.key, set()).add(actor_id)
    conflict_keys = {key for key, actors in account_actors.items() if len(actors) > 1}
    conflicts = {
        _account_label(key): tuple(sorted(account_actors[key])) for key in sorted(conflict_keys)
    }
    actors: list[InferredActor] = []
    ambiguous_actors = 0
    for actor in index.actors:
        accounts = tuple(
            actor_accounts[actor.actor_id][key] for key in sorted(actor_accounts[actor.actor_id])
        )
        actor_conflict = any(account.key in conflict_keys for account in accounts)
        if actor_conflict:
            status = "conflict"
        elif len(accounts) > 1:
            status = "ambiguous"
            ambiguous_actors += 1
        elif len(accounts) == 1:
            status = "linked"
        else:
            status = "unlinked" if requested else "not_requested"
        display_name = actor.display_name
        display_status = actor.display_status
        github_login = actor.github_login
        basis = actor.public_handle_basis
        if status == "linked":
            account = accounts[0]
            if account.handle:
                display_name = account.handle
                display_status = "public_handle"
            if account.provider == "github":
                github_login = account.handle
            join_basis = (
                "commit_sha_to_login"
                if account.evidence == "commit_sha_to_login"
                else "commit_sha_to_account"
            )
            basis = f"{basis}+{join_basis}" if basis else join_basis
        actors.append(
            replace(
                actor,
                display_name=display_name,
                display_status=display_status,
                github_login=github_login,
                public_handle_basis=basis,
                public_accounts=accounts,
                public_account_status=status,
            )
        )
    result = replace(
        index,
        actors=tuple(actors),
        join_matched=matched,
        join_unmatched=unmatched,
        join_ambiguous=ambiguous_joins + ambiguous_actors + len(conflicts),
        commit_login_count=len(
            {account.key for accounts in normalized.values() for account in accounts}
        ),
        manifest_login_count=fetched_login_count,
        account_conflicts=conflicts,
    )
    if result.partition_digest != before_partition or result.sha_to_actor != before_mapping:
        raise AssertionError("public identity enrichment changed the Git actor partition")
    return result


def build_attribution_index(
    commits: list[GitCommit],
    origin: OriginResult,
    identity: IdentityConfig | None = None,
    *,
    public_handles: dict[str, str] | None = None,
    sha_to_login: dict[str, str] | None = None,
    sha_to_accounts: Mapping[str, Any] | None = None,
    mailmap: MailmapSnapshot | str | Iterable[MailmapEntry] | None = None,
    mailmap_present: bool = False,
    coauthor_shas: set[str] | None = None,
    fetched_login_count: int | None = None,
    repo_scope_digest: str | None = None,
    canonical_origin: str | None = None,
) -> AttributionIndex:
    """Resolve the partition, then attach provider-neutral account evidence."""

    del public_handles  # Login lists without commit/account evidence are not a join.
    if sha_to_login is not None and sha_to_accounts is not None:
        raise ValueError("sha_to_login and sha_to_accounts are mutually exclusive")
    account_mapping: Mapping[str, Any] | None = sha_to_accounts
    if account_mapping is None and sha_to_login is not None:
        account_mapping = sha_to_login
    partition = resolve_git_actor_partition(
        commits,
        origin,
        identity,
        mailmap=mailmap,
        mailmap_present=mailmap_present,
        coauthor_shas=coauthor_shas,
        repo_scope_digest=repo_scope_digest,
        canonical_origin=canonical_origin,
    )
    return attach_public_identities(
        partition,
        account_mapping,
        fetched_login_count=fetched_login_count,
    )


def attribution_payload(index: AttributionIndex, human_commit_count: int) -> dict[str, Any]:
    attributed = sum(len(actor.commit_shas) for actor in index.actors)
    unresolved = len(index.unresolved_shas)
    total = attributed + unresolved
    coverage = round(attributed / total, 4) if total else 0.0
    public_n = sum(1 for actor in index.actors if actor.display_status == "public_handle")
    return {
        "observed_actor_count": len(index.actors),
        "attributed_commit_count": attributed,
        "attribution_human_including_merges": attributed,
        "repo_human_nonmerge_commits": human_commit_count,
        "unresolved_commit_count": unresolved,
        "attribution_unresolved_commit_count": unresolved,
        "attribution_coverage": Observed(coverage, "ratio", sample_size=total).to_dict(),
        "bot_count": index.bot_count,
        "merge_count": index.merge_count,
        "coauthored_count": index.coauthored_count,
        "mailmap_present": index.mailmap_present,
        "human_commit_count": human_commit_count,
        "population_identity": (
            "repo_human_nonmerge_commits + merge_count = "
            "attribution_human_including_merges + attribution_unresolved_commit_count"
        ),
        "unresolved_definitions": {
            "origin_unresolved": "origin class unresolved (undecidable email)",
            "attribution_unresolved": "no stable actor key after bot exclusion",
        },
        "actor_partition": {
            "definition": "repo_local_git_primary_author_cluster",
            "repo_scope_digest": index.repo_scope_digest,
            "object_format": index.object_format,
            "partition_digest": index.partition_digest,
            "sha_to_actor_digest": index.sha_to_actor_digest,
            "provider_enrichment_changes_partition": False,
        },
        "public_join": {
            "matched": index.join_matched,
            "unmatched": index.join_unmatched,
            "ambiguous": index.join_ambiguous,
            "public_handle_actors": public_n,
            "fetched_login_count": index.manifest_login_count,
            "commit_login_count": index.commit_login_count,
            "account_conflict_count": len(index.account_conflicts),
            "count_note": (
                "fetched_login_count is a legacy unbound account-list count and is not "
                "a commit-author join; production CAS collection leaves it null; "
                "commit_login_count = distinct stable accounts proven by CAS commit "
                "OID evidence"
            ),
        },
    }


def synthetic_identity(actor: InferredActor) -> IdentityConfig:
    row = Actor(
        canonical_id=(
            actor.actor_id
            if ACTOR_ID_RE.fullmatch(actor.actor_id) and not actor.actor_id.startswith("github:")
            else stable_actor_hash(actor.actor_id)
        ),
        emails=actor.emails,
        github_login=actor.github_login,
        attribution_state="inferred",
    )
    return IdentityConfig(
        actors=(row,),
        pending_attribution=False,
    )


def find_actor(index: AttributionIndex, actor_id: str) -> InferredActor | None:
    for actor in index.actors:
        if actor.actor_id == actor_id:
            return actor
    return None
