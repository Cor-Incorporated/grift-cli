"""Deterministic digest of release tags reachable from one fixed Git OID.

Only the aggregate SHA-256 leaves this module.  In particular, tag names,
tagger names, and tagger e-mail addresses are never placed in report
provenance.  For annotated tags the Git tag-object OID binds the complete tag
object (including its tagger metadata) without copying that metadata into a
Grift artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Mapping


class TagsetError(RuntimeError):
    """The fixed-revision reachable tag set could not be collected."""


_OID_RE = {
    "sha1": re.compile(rb"^[0-9a-f]{40}$"),
    "sha256": re.compile(rb"^[0-9a-f]{64}$"),
}
_DIGEST_DOMAIN = b"tep-reachable-tagset-v1\0"
_REF_DOMAIN = b"tep-tag-ref-v1\0"


def reachable_tagset_digest(repo: Path, target_oid: Mapping[str, str]) -> str:
    """Return the SHA-256 of tags whose commit is reachable from ``target_oid``.

    Git's ``--merged=<oid>`` relation fixes the commit-history boundary while
    the tag refs remain an explicit external input.  Verification repeats this
    collection, so adding, deleting, moving, or replacing a reachable tag is a
    report mismatch.  ``GIT_NO_LAZY_FETCH`` prevents promisor repositories from
    silently filling missing objects during either analysis or verification.
    """

    repository = repo.resolve()
    algorithm = str(target_oid.get("algorithm") or "")
    target = str(target_oid.get("value") or "")
    pattern = _OID_RE.get(algorithm)
    if pattern is None or not pattern.fullmatch(target.encode("ascii", "strict")):
        raise TagsetError("tagset: target OID does not match its object format")
    observed_format = _git(repository, "rev-parse", "--show-object-format").strip()
    if observed_format != algorithm.encode("ascii"):
        raise TagsetError("tagset: repository object format differs from target OID")

    fields = b"%00".join(
        (
            b"%(refname)",
            b"%(objecttype)",
            b"%(objectname)",
            b"%(*objectname)",
        )
    ).decode("ascii")
    output = _git(
        repository,
        "for-each-ref",
        f"--merged={target}",
        "--sort=refname",
        f"--format={fields}",
        "refs/tags/",
    )

    members: list[dict[str, object]] = []
    for raw_record in output.splitlines():
        if not raw_record:
            continue
        parts = raw_record.split(b"\0")
        if len(parts) != 4:
            raise TagsetError("tagset: git returned an invalid tag record")
        refname, object_type, object_oid, peeled_oid = parts
        if object_type == b"tag":
            commit_oid = peeled_oid
            kind = "annotated"
        elif object_type == b"commit":
            commit_oid = object_oid
            kind = "lightweight"
        else:
            # Non-commit tag targets are not release boundaries for the fixed
            # commit history and are intentionally outside this tag set.
            continue
        if not pattern.fullmatch(object_oid) or not pattern.fullmatch(commit_oid):
            raise TagsetError("tagset: tag OID does not match repository object format")
        members.append(
            {
                "kind": kind,
                "refname_digest": hashlib.sha256(_REF_DOMAIN + refname).hexdigest(),
                "object_oid": {
                    "algorithm": algorithm,
                    "value": object_oid.decode("ascii"),
                },
                "commit_oid": {
                    "algorithm": algorithm,
                    "value": commit_oid.decode("ascii"),
                },
            }
        )

    payload = {
        "definition": "reachable-tagset-v1",
        "object_format": algorithm,
        "target_oid": {"algorithm": algorithm, "value": target},
        "members": members,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(_DIGEST_DOMAIN + encoded).hexdigest()


def _git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-c", "safe.directory=*", "-C", str(repo), *args],
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TagsetError("tagset: Git collection failed") from exc
    if result.returncode != 0:
        raise TagsetError("tagset: Git collection failed")
    return result.stdout.strip()
