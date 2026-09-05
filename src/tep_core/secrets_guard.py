"""Refuse raw emails and secret-shaped bytes in v0.6 local inputs.

The guard matches credential-shaped **values**, never identifiers that merely
contain credential vocabulary. A contributor whose GitHub login is
``secrett2633`` and a repository named ``cookiecutter-flask`` are ordinary
public identifiers; refusing them made 18 of 181 real repositories
unanalysable while letting an actual ``ghp_`` token through untouched.

``HIGH_CONFIDENCE_CREDENTIAL_RE`` is the single source for provider credential
formats; ``contribution_v2`` imports it rather than keeping a second copy, and
``tests/test_v060_emit_robustness.py`` fails if the two ever diverge.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)

# Provider credential formats. Keep in sync with nothing — this is the source.
HIGH_CONFIDENCE_CREDENTIAL_RE = re.compile(
    r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")

_BEARER_RE = re.compile(r"(?i)authorization\s*[:=]\s*\"?bearer\s+\S{8,}")

# A secret-named key bound to a value long enough to be a credential. The key
# must be the whole key: `actor_id`, `token_count` and `secret_scanning` are
# identifiers, not assignments of a secret.
_KEYED_SECRET_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])"
    r"(?:api[_-]?key|secret[_-]?(?:access[_-]?)?key|client[_-]?secret|access[_-]?token|"
    r"auth[_-]?token|refresh[_-]?token|password|passwd|passphrase|dsn)"
    r"\"?\s*[:=]\s*\"?"
    r"(?![\"']?(?:null|none|true|false|0|\{)\b)"
    r"[^\"'\s,}\]]{12,}"
)

_ABS_PATH_RE = re.compile(r"(^|[\s\"'])(/Users/|/home/|[A-Za-z]:\\)")

_CREDENTIAL_CHECKS = (
    HIGH_CONFIDENCE_CREDENTIAL_RE,
    _PRIVATE_KEY_RE,
    _BEARER_RE,
    _KEYED_SECRET_RE,
)


class InputValidationError(ValueError):
    """Malformed or unsafe local input. CLI maps this to exit 2."""


def has_credential_shape(text: str) -> bool:
    """True when the text carries a credential-shaped value, not merely the word."""
    return any(rx.search(text) for rx in _CREDENTIAL_CHECKS)


def assert_no_secrets(text: str, *, source: str) -> None:
    if _EMAIL_RE.search(text):
        raise InputValidationError(f"{source}: raw email is not allowed")
    if has_credential_shape(text):
        raise InputValidationError(f"{source}: secret-shaped field is not allowed")


def artifact_leaks(text: str) -> list[str]:
    found: list[str] = []
    if _EMAIL_RE.search(text):
        found.append("raw email")
    if has_credential_shape(text):
        found.append("secret-shaped field")
    if _ABS_PATH_RE.search(text):
        found.append("absolute path")
    if "git@github.com:" in text or "git@gitlab.com:" in text:
        found.append("ssh remote")
    if re.search(r"https://[^/@\s:]+:[^/@\s]+@", text):
        found.append("url userinfo")
    return found
