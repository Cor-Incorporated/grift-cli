"""Generate identity-v2 material for `grift identity --init`.

The generator is deliberately narrow:

- it never writes a raw email to the output file.  identity-v2 records only
  the domain-separated ``email_sha256`` digests, and this module reuses
  :func:`tep_core.identity.email_identity_sha256` verbatim, so a generated
  file always loads and matches exactly the emails the loader matches;
- ``canonical_id`` stays inside ``CANONICAL_ID_PATTERN`` and outside the
  reserved hash-id shape, reusing the loader's rules instead of inventing
  parallel ones (the reserved shape exists so a declared id can never equal
  another cluster's hash id, v0.9.1 M5);
- ``author_email_counts`` reads only the local repository through
  ``git log --format=%ae``; nothing leaves the machine.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from tep_core.gitutil import _run_git
from tep_core.identity import (
    CANONICAL_ID_PATTERN,
    CANONICAL_ID_RE,
    RESERVED_ACTOR_HASH_RE,
    email_identity_sha256,
    normalize_email,
)

__all__ = [
    "author_email_counts",
    "derive_canonical_id",
    "dedupe_emails",
    "render_empty_template",
    "render_identity_template",
]


def derive_canonical_id(email: str) -> str | None:
    """Return the local part of ``email`` as a canonical_id, or ``None``.

    ``None`` means the CLI must ask for an explicit ``--id``: the local part
    is empty, violates ``CANONICAL_ID_PATTERN``, or has the reserved hash-id
    shape.  A hash-id-shaped id would let one actor row absorb another
    cluster's commits, so deriving into that shape is refused here too.
    """

    local = normalize_email(email).split("@")[0]
    if not local or not CANONICAL_ID_RE.fullmatch(local) or RESERVED_ACTOR_HASH_RE.fullmatch(local):
        return None
    return local


def dedupe_emails(emails: Sequence[str]) -> list[str]:
    """Normalize and deduplicate, keeping the first-seen order."""

    seen: set[str] = set()
    result: list[str] = []
    for email in emails:
        normalized = normalize_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _require_valid_canonical_id(canonical_id: str) -> None:
    if not CANONICAL_ID_RE.fullmatch(canonical_id):
        raise ValueError(f"canonical_id {canonical_id!r} must fullmatch {CANONICAL_ID_PATTERN}")
    if RESERVED_ACTOR_HASH_RE.fullmatch(canonical_id):
        raise ValueError(
            f"canonical_id {canonical_id!r} has the reserved hash-id shape "
            f"({re.escape('actor_') + '[a-f0-9]{12,32}'}); declare a readable id instead"
        )


def render_identity_template(canonical_id: str, emails: Sequence[str]) -> str:
    """Render an identity-v2 document that records only email digests.

    Raises ``ValueError`` on an invalid ``canonical_id`` or when no email
    survives normalisation, so the CLI can refuse before writing anything.
    """

    _require_valid_canonical_id(canonical_id)
    normalized = dedupe_emails(emails)
    if not normalized:
        raise ValueError("at least one non-empty --email is required")
    digests = "\n".join(f'  "{email_identity_sha256(email)}",' for email in normalized)
    return (
        "# grift identity-v2 テンプレート（grift identity --init が生成）\n"
        "# - 生のメールアドレスは書きません。email_sha256 だけを記録します\n"
        '# - attribution_state = "claimed" は自己申告の印です（v1 の emails とは違い、\n'
        "#   記録した digest は同じ正規化・同じ digest 計算で照合されます）\n"
        "# - experience / role を観測するには consent と authority が要ります\n"
        "#   （省略のままだとその観測は not_observed になります）\n"
        'schema_version = "identity-v2"\n'
        "\n"
        "[[actors]]\n"
        f'canonical_id = "{canonical_id}"\n'
        "email_sha256 = [\n"
        f"{digests}\n"
        "]\n"
        'attribution_state = "claimed"\n'
        '# consent = "recorded-explicit-consent"\n'
        '# authority = "subject-authorization"\n'
        '# github_login = ""\n'
    )


def render_empty_template() -> str:
    """Render an identity-v2 document with no actor rows."""

    return (
        "# grift identity-v2 空テンプレート（grift identity --init）\n"
        "# 次の手順:\n"
        "#   1. grift identity --list REPO     # author email を件数つきで一覧\n"
        "#   2. grift identity --init --out .tep/identity.toml --email you@example.com\n"
        "# consent / authority は experience / role の観測に必要なときだけ追記します\n"
        'schema_version = "identity-v2"\n'
    )


def author_email_counts(repo: Path) -> list[tuple[str, int]]:
    """Return ``(normalized_email, commit_count)`` for every author email.

    Sorted by count descending, then email ascending, so the output is
    deterministic for a given history and never leaks a ranking intent
    beyond "how many commits this email authored in this repository".
    Raises :class:`tep_core.gitutil.GitError` when ``git log`` fails.
    """

    output = _run_git(repo, ["log", "--format=%ae"])
    counts = Counter(normalize_email(line) for line in output.splitlines() if line.strip())
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))
