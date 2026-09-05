"""R1/R2 — emit-time robustness.

R1: the leak guard matched secret-*vocabulary* anywhere in the artifact, so a
contributor named ``secrett2633`` or a repository named ``cookiecutter-flask``
refused the whole report. 18 of 181 real repositories could not be analysed.
The guard must match credential-shaped *values*, never identifiers that merely
contain the word.

R2: git stores the author timezone verbatim. ``requests`` carries
``2011-09-08T02:38:50+518:00``; ``datetime.fromisoformat`` rejects offsets of
24 hours or more, so the run aborted. The instant is still recoverable:
``UTC = printed local time - offset``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tep_core.dates import parse_iso_utc
from tep_core.secrets_guard import InputValidationError, artifact_leaks, assert_no_secrets

# --------------------------------------------------------------------------
# R1 — identifiers that merely contain the vocabulary must not be refused
# --------------------------------------------------------------------------

BENIGN = {
    # real GitHub logins observed in fastapi / starlette / axios / jinja
    "actor_id_secret": '{"actor_id": "secrett2633", "display_name": "secrett2633"}',
    "actor_id_cookie": '{"actor_id": "cookiemr", "display_name": "CookieMr"}',
    "actor_id_cookie2": '{"actor_id": "samycookie", "display_name": "SamyCookie"}',
    "actor_id_token": '{"actor_id": "katoken54321go", "commit_count": 1}',
    # the repository's own name and remote
    "repo_name": '{"repository": {"name": "cookiecutter-flask", '
    '"remote": "github.com/cookiecutter-flask/cookiecutter-flask"}}',
    # template directory listings
    "template_dir": '{"kind": "observed", "value": ["{{cookiecutter.project_slug}}", "tests"]}',
    # ordinary prose that names the concept
    "prose": '{"limit": "session cookie handling is out of scope for this metric"}',
    # a source path that names the domain
    "path": '{"directories": ["fastapi/security/api_key.py", "tests/test_cookie_params.py"]}',
}


@pytest.mark.parametrize("case", sorted(BENIGN))
def test_identifier_containing_secret_word_is_not_a_leak(case: str) -> None:
    assert artifact_leaks(BENIGN[case]) == [], f"{case} must not be refused: {BENIGN[case]}"


@pytest.mark.parametrize("case", sorted(BENIGN))
def test_identifier_containing_secret_word_passes_input_validation(case: str) -> None:
    assert_no_secrets(BENIGN[case], source="unit")


# --------------------------------------------------------------------------
# R1 — credential-shaped values must still be refused (negative controls)
# --------------------------------------------------------------------------

# Negative controls are generated from the guard's own patterns, so no
# credential-shaped literal is stored in the repository and no string is
# assembled to slip past a scanner (tests/test_hygiene.py forbids both).
# A format added to a pattern is covered here automatically.

try:  # Python 3.11+ moved the regex parser
    from re import _parser as _sre
except ImportError:  # pragma: no cover
    import sre_parse as _sre  # type: ignore[no-redef]


_CATEGORY_SAMPLE = {
    "CATEGORY_SPACE": " ",
    "CATEGORY_DIGIT": "0",
    "CATEGORY_WORD": "a",
    "CATEGORY_NOT_SPACE": "a",
    "CATEGORY_NOT_DIGIT": "a",
    "CATEGORY_NOT_WORD": "-",
}


def _members(items) -> set[str]:
    out: set[str] = set()
    for op, arg in items:
        name = op.name if hasattr(op, "name") else str(op)
        if name == "LITERAL":
            out.add(chr(arg))
        elif name == "RANGE":
            out.update(chr(code) for code in range(arg[0], arg[1] + 1))
        elif name == "CATEGORY":
            label = arg.name if hasattr(arg, "name") else str(arg)
            if label == "CATEGORY_SPACE":
                out.update(" \t\n\r\f\v")
            elif label == "CATEGORY_DIGIT":
                out.update("0123456789")
            elif label == "CATEGORY_WORD":
                out.update("abcdefghijklmnopqrstuvwxyz0123456789_")
    return out


def _pick(items) -> str:
    """One character the set accepts, honouring negation."""
    head = items[0][0] if items else None
    head_name = head.name if hasattr(head, "name") else str(head)
    if head_name == "NEGATE":
        excluded = _members(items[1:])
        for candidate in "aA0zZ9x":
            if candidate not in excluded:
                return candidate
        return "a"
    for op, arg in items:
        name = op.name if hasattr(op, "name") else str(op)
        if name == "LITERAL":
            return chr(arg)
        if name == "RANGE":
            return chr(arg[0])
        if name == "CATEGORY":
            label = arg.name if hasattr(arg, "name") else str(arg)
            return _CATEGORY_SAMPLE.get(label, "a")
    return "a"


def _expand(node) -> list[str]:
    """Every string the parsed pattern can produce, one per branch choice.

    Repeats emit their declared minimum, so `\\s*` contributes nothing and
    `{20,}` contributes twenty. Assertions and lookarounds are skipped.
    """
    results = [""]
    for op, arg in node:
        name = op.name if hasattr(op, "name") else str(op)
        pieces: list[str]
        if name == "LITERAL":
            pieces = [chr(arg)]
        elif name == "IN":
            pieces = [_pick(arg)]
        elif name == "ANY":
            pieces = ["a"]
        elif name == "MAX_REPEAT" or name == "MIN_REPEAT":
            low, _high, sub = arg
            inner = _expand(sub)
            pieces = [text * low for text in inner]
        elif name == "SUBPATTERN":
            pieces = _expand(arg[3])
        elif name == "BRANCH":
            pieces = []
            for alternative in arg[1]:
                pieces.extend(_expand(alternative))
        else:
            continue
        results = [prefix + piece for prefix in results for piece in pieces]
    return results


def _samples(pattern) -> list[str]:
    """Every distinct string the pattern accepts, one per alternative."""
    return [text for text in _expand(_sre.parse(pattern.pattern)) if text]


def _leak_cases() -> dict[str, str]:
    from tep_core import secrets_guard as guard

    cases: dict[str, str] = {}
    for index, sample in enumerate(_samples(guard.HIGH_CONFIDENCE_CREDENTIAL_RE)):
        cases[f"provider_format_{index}"] = '{"note": "%s"}' % sample
    for label, pattern in (
        ("private_key", guard._PRIVATE_KEY_RE),
        ("bearer_header", guard._BEARER_RE),
        ("keyed_value", guard._KEYED_SECRET_RE),
    ):
        cases[label] = '{"note": "%s"}' % _samples(pattern)[0]
    return cases


LEAKS = _leak_cases()


def test_every_declared_credential_format_has_a_control() -> None:
    """The provider list must not grow without growing this test."""
    from tep_core import secrets_guard as guard

    declared = len(_samples(guard.HIGH_CONFIDENCE_CREDENTIAL_RE))
    covered = sum(1 for key in LEAKS if key.startswith("provider_format_"))
    assert covered == declared, (
        f"declared provider formats: {declared}, generated controls: {covered}"
    )
    assert declared >= 7, f"credential format list shrank to {declared}"


@pytest.mark.parametrize("case", sorted(LEAKS))
def test_credential_shaped_value_is_still_refused(case: str) -> None:
    found = artifact_leaks(LEAKS[case])
    assert found, f"{case} must be refused but was allowed: {LEAKS[case]}"
    assert "secret-shaped field" in found


@pytest.mark.parametrize("case", sorted(LEAKS))
def test_credential_shaped_value_is_still_refused_on_input(case: str) -> None:
    with pytest.raises(InputValidationError):
        assert_no_secrets(LEAKS[case], source="unit")


def test_raw_email_is_still_refused() -> None:
    assert "raw email" in artifact_leaks('{"author": "alice@example.com"}')


# --------------------------------------------------------------------------
# R1 — declaration <-> enforcement link (CLAUDE.md: no silent drift)
# --------------------------------------------------------------------------


def test_credential_formats_have_a_single_source() -> None:
    """secrets_guard and contribution_v2 must not carry two drifting copies."""
    from tep_core import contribution_v2, secrets_guard

    assert (
        secrets_guard.HIGH_CONFIDENCE_CREDENTIAL_RE.pattern
        == contribution_v2._HIGH_CONFIDENCE_TOKEN_RE.pattern
    ), (
        "credential formats diverged:\n"
        f"  secrets_guard:    {secrets_guard.HIGH_CONFIDENCE_CREDENTIAL_RE.pattern}\n"
        f"  contribution_v2:  {contribution_v2._HIGH_CONFIDENCE_TOKEN_RE.pattern}"
    )


# --------------------------------------------------------------------------
# R2 — out-of-range timezone offsets
# --------------------------------------------------------------------------


def test_out_of_range_offset_resolves_to_the_recorded_instant() -> None:
    """requests@5e6ecdad: UTC == printed local time minus the recorded offset."""
    got = parse_iso_utc("2011-09-08T02:38:50+518:00")
    expected = datetime(2011, 9, 8, 2, 38, 50, tzinfo=timezone.utc) - timedelta(hours=518)
    assert got == expected


def test_out_of_range_negative_offset_resolves() -> None:
    got = parse_iso_utc("2011-09-08T02:38:50-100:00")
    expected = datetime(2011, 9, 8, 2, 38, 50, tzinfo=timezone.utc) + timedelta(hours=100)
    assert got == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-08-20T12:00:00Z", datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)),
        ("2026-08-20T12:00:00+00:00", datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)),
        ("2026-08-20T21:00:00+09:00", datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)),
        ("2026-08-20T07:00:00-05:00", datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)),
    ],
)
def test_valid_offsets_are_unchanged(text: str, expected: datetime) -> None:
    assert parse_iso_utc(text) == expected


@pytest.mark.parametrize(
    "text",
    ["not-a-date", "2011-13-45T99:99:99+00:00", "2011-09-08T02:38:50+abc:00", ""],
)
def test_genuinely_malformed_input_still_raises(text: str) -> None:
    with pytest.raises(ValueError):
        parse_iso_utc(text)
