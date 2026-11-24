#!/usr/bin/env python3
"""Bootstrap a reference distribution from public repositories, without `contribute`.

The shipped distributions (v2026.09, v2026.11) were built by hand-run admission
scripts. This tool turns that into three offline-reviewable steps, so a new version
(for example the first with a `survival` block) can be built from public repositories
alone, as docs/validation.md and docs/corpus-protocol.md describe:

    plan     candidates (TOML or JSON) and/or existing pins -> a reviewed plan JSON.
             Offline. Drops duplicates, excluded heavy repos and non-public URLs.
    observe  clone each planned repo, run the repo-scope analysis (optionally with
             --survival), keep a slim per-repo row in corpus/runs-<version>/results.jsonl
             (gitignored) and write the public pin file (url + sha + group only).
    build    results.jsonl -> corpus/<version>/distributions.json. Deciles are issued
             only for metrics with n >= MIN_N. Refuses the shipped versions.

Nothing here reads a person's identity, posts anything, or opens a pull request.
A repo is observed as a repo (empty identity, scope=repo): no named person enters
the corpus, and results.jsonl carries aggregate rates only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_dist_v2026_11 import MIN_N, deciles, rate_of  # noqa: E402

SHIPPED_VERSIONS = frozenset({"v2026.09", "v2026.11"})
VERSION_PATTERN = re.compile(r"^v\d{4}\.\d{2}(\.\d+)?$")
PLAN_SCHEMA = "tep-corpus-bootstrap-plan-v1"
PINS_SCHEMA = "tep-corpus-pins-v1"
PUBLIC_HOSTS = ("github.com", "gitlab.com")
# Repositories research found too heavy to clone for a corpus run.
EXCLUDE_REPOS = frozenset({"wrtnlabs/autobe", "datawhalechina/vibe-vibe"})
SURVIVAL_MIN_LINES = 20
DEFAULT_LIMIT = 100
_URL = re.compile(r"^https://(?P<host>[^/@:]+)/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$")


class BootstrapError(ValueError):
    """The candidate list or the version is not acceptable."""


def repo_key(url: str) -> str | None:
    """`owner/repo` for a credential-free https URL on a public host, else None."""
    match = _URL.match(url.strip())
    if match is None or match.group("host") not in PUBLIC_HOSTS:
        return None
    return f"{match.group('owner')}/{match.group('repo')}".lower()


def validate_version(version: str) -> str:
    if not VERSION_PATTERN.match(version):
        raise BootstrapError(f"version must look like v2026.12, got {version!r}")
    if version in SHIPPED_VERSIONS:
        raise BootstrapError(f"{version} is shipped and immutable; choose a new version")
    return version


def load_candidates(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
        rows = data["candidates"] if isinstance(data, dict) else data
    else:
        data = tomllib.loads(text)
        rows = data.get("candidates") or data.get("repos") or []
    if not isinstance(rows, list):
        raise BootstrapError(f"{path}: expected a list of candidates")
    return [dict(row) for row in rows]


def load_pin_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open("rb") as handle:
            rows.extend(dict(row) for row in tomllib.load(handle).get("repos", []))
    return rows


def build_plan(
    candidates: Sequence[dict[str, Any]],
    *,
    known: Iterable[dict[str, Any]],
    version: str,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Pure function: which candidates are observed, which are dropped and why.

    A repo already in `known` is a duplicate. To re-observe existing pins, pass them
    as candidates with `known=[]`; their pinned sha is kept.
    """
    validate_version(version)
    if limit < 1:
        raise BootstrapError("limit must be positive")
    seen = {key for row in known if (key := repo_key(str(row.get("url", ""))))}
    planned: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for row in candidates:
        url = str(row.get("url", "")).strip()
        key = repo_key(url)
        if key is None:
            dropped.append({"url": url, "reason": "not_a_public_https_url"})
        elif key in EXCLUDE_REPOS:
            dropped.append({"url": url, "reason": "excluded_heavy_clone"})
        elif key in seen:
            dropped.append({"url": url, "reason": "duplicate"})
        elif len(planned) >= limit:
            dropped.append({"url": url, "reason": "over_limit"})
        else:
            entry = {
                "key": key,
                "url": url if url.endswith(".git") else f"{url.rstrip('/')}.git",
                "group": str(row.get("group") or "X"),
            }
            if row.get("sha"):
                entry["sha"] = str(row["sha"])
            planned.append(entry)
            seen.add(key)
    return {
        "schema_version": PLAN_SCHEMA,
        "version": version,
        "limit": limit,
        "planned": planned,
        "dropped": dropped,
    }


def _git(*args: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout)


def ensure_clone(url: str, dest: Path, sha: str | None) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        done = _git("clone", "--filter=blob:none", url, str(dest))
        if done.returncode != 0:
            raise RuntimeError(f"clone failed: {done.stderr[:200]}")
    if sha:
        if _git("-C", str(dest), "cat-file", "-t", sha).returncode != 0:
            _git("-C", str(dest), "fetch", "--filter=blob:none", "origin", sha)
        target = sha
    else:
        target = "HEAD"
    done = _git("-C", str(dest), "checkout", "--force", "--detach", target, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"checkout failed: {done.stderr[:200]}")
    head = _git("-C", str(dest), "rev-parse", "HEAD")
    return head.stdout.strip()


def slim_row(entry: dict[str, Any], sha: str, report: dict[str, Any]) -> dict[str, Any]:
    context = report.get("context_profile") or {}
    return {
        "id": f"{entry['group']}-{entry['key'].split('/')[-1]}",
        "group": entry["group"],
        "name": entry["key"].split("/")[-1],
        "sha": sha,
        "source": "bootstrap",
        "context": {
            "collaboration_class": (context.get("collaboration_class") or {}).get("value"),
            "lifecycle_stage": (context.get("lifecycle_stage") or {}).get("value"),
        },
        "test_cochange": report.get("test_cochange"),
        "rework": report.get("rework"),
        "survival": report.get("survival"),
    }


def survival_rate(row: dict[str, Any]) -> float | None:
    block = row.get("survival") or {}
    lines = block.get("lines_sampled")
    if block.get("kind") != "observed" or block.get("survival_index") is None:
        return None
    if not isinstance(lines, int) or lines < SURVIVAL_MIN_LINES:
        return None
    return float(block["survival_index"])


def build_distributions(
    rows: Sequence[dict[str, Any]], *, version: str, definition_version: str
) -> dict[str, Any]:
    validate_version(version)
    metrics: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    extractors = {
        "test_cochange": lambda row: rate_of(row, "test_cochange"),
        "corrective_rework": lambda row: rate_of(row, "corrective_rework"),
        "survival": survival_rate,
    }
    for metric_id, extract in extractors.items():
        values = [value for row in rows if (value := extract(row)) is not None]
        if len(values) >= MIN_N:
            metrics[metric_id] = {"n": len(values), "deciles": deciles(values)}
        else:
            notes.append(
                f"{metric_id}: n={len(values)} < MIN_N {MIN_N} — no deciles issued "
                "(reference_too_small)"
            )
    return {
        "version": version,
        "analysis_scope": "repo",
        "definition_version": definition_version,
        "metrics": metrics,
        "notes": notes,
        "sources": {"bootstrap": len(rows)},
    }


def render_pins(version: str, entries: Sequence[dict[str, str]]) -> str:
    lines = [
        f"# Public corpus pins for reference distribution {version} (repo scope).",
        "# url + sha + group only: results stay in the gitignored results.jsonl.",
        "",
        f'schema_version = "{PINS_SCHEMA}"',
        'analysis_scope = "repo"',
        "",
    ]
    for entry in entries:
        lines += [
            "[[repos]]",
            f'id = "{entry["group"]}-{entry["key"].split("/")[-1]}"',
            f'group = "{entry["group"]}"',
            f'name = "{entry["key"].split("/")[-1]}"',
            f'url = "{entry["url"]}"',
            f'sha = "{entry["sha"]}"',
            "",
        ]
    return "\n".join(lines)


def _runs_dir(version: str) -> Path:
    return ROOT / "corpus" / f"runs-{version}"


def cmd_plan(args: argparse.Namespace) -> int:
    validate_version(args.version)
    candidates: list[dict[str, Any]] = []
    for path in args.candidates:
        candidates.extend(load_candidates(path))
    candidates.extend(load_pin_rows(args.from_pins))
    known = [] if args.from_pins else load_pin_rows(args.known_pins)
    plan = build_plan(candidates, known=known, version=args.version, limit=args.limit)
    body = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(body, encoding="utf-8")
    sys.stdout.write(
        body if not args.out else f"planned={len(plan['planned'])} dropped={len(plan['dropped'])}\n"
    )
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    from tep_core.analyze import analyze_repository
    from tep_core.identity import empty_identity
    from tep_core.lineage import Lineage

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    version = validate_version(plan["version"])
    runs = _runs_dir(version)
    runs.mkdir(parents=True, exist_ok=True)
    results = runs / "results.jsonl"
    failures = runs / "failures.jsonl"
    results.write_text("", encoding="utf-8")
    failures.write_text("", encoding="utf-8")
    pinned: list[dict[str, str]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for entry in plan["planned"]:
        dest = args.cache / entry["key"].replace("/", "__")
        try:
            sha = ensure_clone(entry["url"], dest, entry.get("sha"))
            report = analyze_repository(
                dest, empty_identity(), Lineage(), survival=args.survival, scope="repo"
            )
        except Exception as exc:  # noqa: BLE001 - one bad repo must not stop the run
            with failures.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"run": stamp, "key": entry["key"], "error": str(exc)[:300]}) + "\n"
                )
            print(f"fail {entry['key']}: {str(exc)[:80]}")
            continue
        row = slim_row(entry, sha, report)
        with results.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        pinned.append({**entry, "sha": sha})
        print(f"ok {entry['key']} {sha[:10]}")
    pins_path = ROOT / "corpus" / f"pins-{version}.toml"
    pins_path.write_text(render_pins(version, pinned), encoding="utf-8")
    print(f"observed={len(pinned)} pins={pins_path}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from tep_core.version import DEFINITION_VERSION

    version = validate_version(args.version)
    results = _runs_dir(version) / "results.jsonl"
    rows = [
        json.loads(line)
        for line in results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dist = build_distributions(rows, version=version, definition_version=DEFINITION_VERSION)
    out = ROOT / "corpus" / version / "distributions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(dist, indent=2, ensure_ascii=False) + "\n"
    out.write_text(body, encoding="utf-8")
    print(f"wrote {out}")
    for metric_id, block in dist["metrics"].items():
        print(f"{metric_id}: n={block['n']}")
    for note in dist["notes"]:
        print("NOTE:", note)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="offline: review which repos would be observed")
    plan.add_argument("--version", required=True, help="new reference version, e.g. v2026.12")
    plan.add_argument("--candidates", type=Path, action="append", default=[])
    plan.add_argument(
        "--from-pins",
        type=Path,
        action="append",
        default=[],
        help="re-observe the repos of an existing pin file at their pinned sha\n"
        "(then --known-pins is not used for duplicates)",
    )
    plan.add_argument(
        "--known-pins",
        type=Path,
        action="append",
        default=sorted((ROOT / "corpus").glob("pins-v*.toml")),
        help="pin files whose repos count as duplicates (default: every corpus/pins-v*.toml)",
    )
    plan.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    plan.add_argument("--out", type=Path)
    plan.set_defaults(handler=cmd_plan)

    observe = sub.add_parser("observe", help="clone and analyze (network)")
    observe.add_argument("--plan", type=Path, required=True)
    observe.add_argument("--cache", type=Path, default=ROOT / ".corpus-cache")
    observe.add_argument("--survival", action="store_true", help="also record the survival index")
    observe.set_defaults(handler=cmd_observe)

    build = sub.add_parser("build", help="results.jsonl -> corpus/<version>/distributions.json")
    build.add_argument("--version", required=True)
    build.set_defaults(handler=cmd_build)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
