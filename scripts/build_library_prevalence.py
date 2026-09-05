#!/usr/bin/env python3
"""Build the bundled library-prevalence reference table.

The table answers exactly one question: *of the repositories in this declared
corpus, how many declare library X?* It is not a market survey, and the output
is named so that it cannot be mistaken for one. A local corpus of a few hundred
repositories -- assembled from one developer's checkouts plus a hand-picked
slice of OSS -- is not a sample of the software industry, and the corpus block
this script writes says so in the artifact itself rather than in a README that
travels separately.

Determinism: the table is built from manifests at each repository's recorded
commit, sorted, and written with sorted keys. Re-running against the same
corpus at the same commits reproduces the file byte for byte.

Usage:
    python scripts/build_library_prevalence.py --root DIR [--root DIR ...] \
        --version v2026.09 --note "..."
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tep_core.dependency_manifest import (  # noqa: E402
    ECOSYSTEM_BY_MANIFEST,
    SUPPORTED_MANIFESTS,
    ManifestParseError,
    declared_dependencies,
)

SCHEMA_VERSION = "tep-library-prevalence-v1"

def _git(repo: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(repo), *args],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _repositories(roots: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if (child / ".git").exists():
                found.append(child)
    return found


def _manifests(repo: Path) -> list[Path]:
    """Manifests at the repository root only.

    Vendored and example manifests deeper in the tree describe someone else's
    dependency choices, and a monorepo would otherwise count one library many
    times from a single repository.
    """
    return [
        path
        for path in sorted(repo.iterdir())
        if path.is_file() and path.name.casefold() in SUPPORTED_MANIFESTS
    ]


def build(roots: list[Path], *, version: str, note: str) -> dict:
    repositories = _repositories(roots)
    # ecosystem -> library -> number of repositories declaring it
    declared: dict[str, Counter[str]] = {}
    # ecosystem -> how many repositories could have declared anything at all
    denominators: Counter[str] = Counter()
    unparseable: Counter[str] = Counter()
    scanned: list[dict[str, str]] = []

    for repo in repositories:
        manifests = _manifests(repo)
        if not manifests:
            continue
        head = _git(repo, "rev-parse", "HEAD")
        seen_ecosystems: set[str] = set()
        names_by_ecosystem: dict[str, set[str]] = {}
        for manifest in manifests:
            ecosystem = ECOSYSTEM_BY_MANIFEST[manifest.name.casefold()]
            seen_ecosystems.add(ecosystem)
            try:
                names = declared_dependencies(
                    manifest.name, manifest.read_text(encoding="utf-8", errors="replace")
                )
            except (ManifestParseError, OSError):
                unparseable[ecosystem] += 1
                continue
            names_by_ecosystem.setdefault(ecosystem, set()).update(names)

        # One repository counts once per library per ecosystem, however many
        # manifests of that ecosystem it holds.
        for ecosystem in seen_ecosystems:
            denominators[ecosystem] += 1
            bucket = declared.setdefault(ecosystem, Counter())
            for name in names_by_ecosystem.get(ecosystem, set()):
                bucket[name] += 1

        scanned.append(
            {
                "repository": repo.name,
                "commit": head or "unknown",
                "ecosystems": ",".join(sorted(seen_ecosystems)),
            }
        )

    ecosystems = {
        ecosystem: {
            "repositories": denominators[ecosystem],
            "unparseable_manifests": unparseable[ecosystem],
            "libraries": dict(sorted(counts.items())),
        }
        for ecosystem, counts in sorted(declared.items())
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "prevalence_version": version,
        "corpus": {
            "repositories_scanned": len(repositories),
            "repositories_with_manifest": len(scanned),
            "selection_note": note,
            "limitations": [
                "This corpus is a convenience sample of locally available "
                "repositories. It is not a sample of the software industry, and "
                "a share computed from it is not a market share.",
                "A library absent from this table was not observed in this "
                "corpus. That is not evidence that it is rare, niche, or "
                "specialised; most libraries in existence are absent.",
                "Counts are per repository, not per download, per commit, or "
                "per user. A library declared by one widely used repository "
                "counts once.",
            ],
            "members": scanned,
        },
        "ecosystems": ecosystems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    table = build(args.root, version=args.version, note=args.note)
    destination = args.out or (
        Path(__file__).resolve().parents[1]
        / "src/tep_core/data/prevalence"
        / args.version
        / "library_prevalence.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(table, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    corpus = table["corpus"]
    print(f"wrote {destination}")
    print(
        f"  scanned {corpus['repositories_scanned']} repositories, "
        f"{corpus['repositories_with_manifest']} carried a root manifest"
    )
    for ecosystem, block in table["ecosystems"].items():
        print(
            f"  {ecosystem:10s} n={block['repositories']:3d} "
            f"libraries={len(block['libraries']):5d} "
            f"unparseable={block['unparseable_manifests']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
