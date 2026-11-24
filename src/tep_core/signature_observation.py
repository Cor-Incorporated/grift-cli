"""Signed-commit presence, read from the commit objects at one fixed revision.

Only the presence of a signature header (``gpgsig`` / ``gpgsig-sha256``) is
counted. Whether a signature verifies depends on the reader's keyring and
allowed-signers file, so ``git log --format=%G?`` gives a different answer on
each machine and could not be replayed by ``grift verify``. Validity is left to
the reader (``git verify-commit``); a signature header proves neither who signed
nor that the history is genuine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tep_core.gitutil import GitCommit, GitError, _run_git
from tep_core.observation import NotObserved
from tep_core.v2_constants import MIN_POPULATION_FOR_RATES
from tep_core.version import SIGNATURE_DEFINITION_VERSION

_SIGNATURE_HEADERS = ("gpgsig ", "gpgsig-sha256 ")
_COMMIT_PREFIX = "commit "

SIGNATURE_LIMITATIONS = (
    "Counts commits that carry a signature header. Signature validity is not checked: "
    "it depends on the reader's trusted keys, so it cannot be replayed by grift verify. "
    "Use git verify-commit with your own allowed signers.",
    "A signature header does not show who signed, and unsigned commits are common in "
    "legitimate history. This is a presence count, not a score.",
)


def signed_commit_shas(repo: Path, revision: str) -> frozenset[str]:
    """Commit ids under ``revision`` whose object has a signature header.

    ``--pretty=raw`` prints header lines at column 0 and indents every line of
    the message by four spaces, so a message cannot imitate a header.
    """

    raw = _run_git(repo, ["log", "--pretty=raw", "--no-color", revision])
    signed: set[str] = set()
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith(_COMMIT_PREFIX):
            current = line[len(_COMMIT_PREFIX) :].split()[0]
        elif current is not None and line.startswith(_SIGNATURE_HEADERS):
            signed.add(current)
    return frozenset(signed)


def signature_observation(
    repo: Path,
    revision: str,
    commits: list[GitCommit],
    *,
    empty_reason: str,
) -> dict[str, Any]:
    """Share of the selected commits that carry a signature header."""

    if not commits:
        payload = NotObserved(empty_reason).to_dict()
        payload["definition_version"] = SIGNATURE_DEFINITION_VERSION
        return payload
    try:
        signed = signed_commit_shas(repo, revision)
    except GitError:
        payload = NotObserved("git_unavailable").to_dict()
        payload["definition_version"] = SIGNATURE_DEFINITION_VERSION
        return payload
    population = len(commits)
    count = sum(1 for commit in commits if commit.sha in signed)
    if population < MIN_POPULATION_FOR_RATES:
        payload = NotObserved("insufficient_population").to_dict()
        payload.update(
            {
                "definition_version": SIGNATURE_DEFINITION_VERSION,
                "population": population,
                "count": count,
                "limitations": list(SIGNATURE_LIMITATIONS),
            }
        )
        return payload
    return {
        "kind": "observed",
        "definition_version": SIGNATURE_DEFINITION_VERSION,
        "value": round(count / population, 4),
        "unit": "ratio",
        "sample_size": population,
        "count": count,
        "limitations": list(SIGNATURE_LIMITATIONS),
    }
