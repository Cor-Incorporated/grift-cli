"""How common a library is in a declared reference corpus.

This is the second axis of W4: it sits *beside* an actor's observations and is
never combined with them. It describes libraries, not people. "asyncpg is
declared by 3 of 53 Python projects in this corpus" is a fact about asyncpg; it
becomes a fact about a person only if someone multiplies it by their work, and
nothing here does that (norms §7).

Three refusals are load-bearing:

* **Absence is not rarity.** A library missing from the table was not observed
  in 152 local repositories. Almost every library ever published is missing.
  Emitting a low share for an absent name would turn ignorance into a finding
  (norms §1), so absence returns not_observed with its own reason.
* **A small corpus states nothing.** Ecosystems below the minimum are refused
  outright rather than reported with a caveat, matching `reference.MIN_N`.
  This corpus has 4 Rust and 1 PHP project; no honest share comes out of that.
* **No bands.** The raw numerator, denominator and share are emitted and the
  reader judges. A label like "rare" or "commodity" is a compression that
  invites exactly the ranking this tool refuses to produce.

The table is bundled and version-pinned, so lookup is offline, deterministic
and unchanged by anything happening in a package registry today.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from tep_core.observation import NotObserved

PREVALENCE_VERSION = "v2026.09"
PREVALENCE_SCHEMA_VERSION = "tep-library-prevalence-v1"

# Same discipline as reference.MIN_N: below this an ecosystem's share is noise
# dressed as a measurement.
MIN_CORPUS_REPOSITORIES = 30

_DATA_DIR = Path(__file__).resolve().parent / "data" / "prevalence"

ABSENT_REASON = "absent_from_reference_corpus"
SMALL_CORPUS_REASON = "reference_corpus_too_small"
AMBIGUOUS_REASON = "ambiguous_ecosystem"
UNKNOWN_ECOSYSTEM_REASON = "ecosystem_not_in_reference_corpus"

ABSENCE_LIMITATION = (
    "Not observed in the reference corpus. Most published libraries are absent "
    "from it; this is not evidence that the library is rare or specialised."
)
CORPUS_LIMITATION = (
    "Shares describe a convenience sample of locally available repositories, "
    "not a market. They say how common a library is among these projects and "
    "nothing about demand, price, or difficulty."
)
PERSON_LIMITATION = (
    "These figures describe libraries, not the actor. They are reported beside "
    "the actor's observations and are never combined with them."
)


def available_versions() -> tuple[str, ...]:
    if not _DATA_DIR.is_dir():
        return ()
    return tuple(sorted(p.name for p in _DATA_DIR.iterdir() if p.is_dir()))


def table_path(version: str | None = None) -> Path:
    return _DATA_DIR / (version or PREVALENCE_VERSION) / "library_prevalence.json"


@lru_cache(maxsize=4)
def load_table(version: str | None = None) -> dict[str, Any]:
    """Load a pinned table, or an empty one when the version is not bundled.

    An empty table makes every lookup not_observed, which is the correct
    degradation: a missing table is a missing measurement, never a zero share.
    """
    path = table_path(version)
    if not path.is_file():
        return {
            "schema_version": PREVALENCE_SCHEMA_VERSION,
            "prevalence_version": version or PREVALENCE_VERSION,
            "corpus": {"repositories_scanned": 0, "repositories_with_manifest": 0},
            "ecosystems": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_ecosystem(found: Iterable[str] | None) -> tuple[str | None, str | None]:
    """Pick the one registry a name was declared under, or say why we cannot."""
    registries = sorted(found or ())
    if not registries:
        return None, UNKNOWN_ECOSYSTEM_REASON
    if len(registries) > 1:
        return None, AMBIGUOUS_REASON
    return registries[0], None


def library_prevalence(
    name: str,
    *,
    ecosystems: Iterable[str] | None,
    version: str | None = None,
) -> dict[str, Any]:
    """Prevalence of one library, or the reason it could not be stated."""
    table = load_table(version)
    registry, refusal = _resolve_ecosystem(ecosystems)
    if refusal is not None:
        return NotObserved(refusal).to_dict()

    block = (table.get("ecosystems") or {}).get(registry)
    if not isinstance(block, Mapping):
        return NotObserved(UNKNOWN_ECOSYSTEM_REASON).to_dict()

    denominator = block.get("repositories")
    if not isinstance(denominator, int) or denominator < MIN_CORPUS_REPOSITORIES:
        return NotObserved(SMALL_CORPUS_REASON).to_dict()

    declaring = (block.get("libraries") or {}).get(name)
    if not isinstance(declaring, int):
        return {
            "kind": "not_observed",
            "reason": ABSENT_REASON,
            "ecosystem": registry,
            "corpus_repositories": denominator,
            "limitations": [ABSENCE_LIMITATION],
        }
    return {
        "kind": "observed",
        "ecosystem": registry,
        "declaring_repositories": declaring,
        "corpus_repositories": denominator,
        "share": round(declaring / denominator, 4),
        "unit": "repository_share",
        "prevalence_version": table.get("prevalence_version", PREVALENCE_VERSION),
        "limitations": [CORPUS_LIMITATION],
    }


def library_context(
    names: Iterable[str],
    *,
    ecosystems_by_name: Mapping[str, Iterable[str]] | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """The prevalence axis for a set of libraries, as a sibling observation.

    Emitted whole rather than per-name inside the actor's metrics, so that a
    reader meets it as a statement about libraries. There is no aggregate: no
    mean share, no count of "rare" choices, nothing that collapses the set into
    a number about the person.
    """
    lookup = ecosystems_by_name or {}
    libraries = {
        name: library_prevalence(name, ecosystems=lookup.get(name), version=version)
        for name in sorted(set(names))
    }
    if not libraries:
        return NotObserved("no_introduced_dependencies").to_dict()
    table = load_table(version)
    corpus = table.get("corpus") or {}
    return {
        "kind": "observed",
        "prevalence_version": table.get("prevalence_version", PREVALENCE_VERSION),
        "corpus_repositories_scanned": corpus.get("repositories_scanned", 0),
        "corpus_repositories_with_manifest": corpus.get("repositories_with_manifest", 0),
        "libraries": libraries,
        "limitations": [PERSON_LIMITATION, CORPUS_LIMITATION, ABSENCE_LIMITATION],
    }
