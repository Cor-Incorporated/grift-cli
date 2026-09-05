"""CLI parsers. Subject commands do not share the analyze parser object."""

from __future__ import annotations

import argparse
from pathlib import Path

from tep_core.contribution_v2 import PURPOSES

from tep_core.v2_constants import ROLE_LENSES
from tep_core.version import __version__

_EPILOG = """examples:
  grift repo                # repo evidence (report-v2, repo scope)
  grift actor ID            # one canonical_id (report-v2, tenant scope)
  grift project             # observed operating signature (project-v1)
  grift actor ID REPO --identity F --format both --out actor-report.json
  grift project REPO --requirements P --format both --out project-out
  grift align --actor-report actor-report.json --project-report project-out/project.json
  grift actor ID REPO --identity F --format both --out actor-collection
  grift verify actor-collection --repo REPO --identity F
  grift align --repo R --identity F --actor ID --project P  # compatibility; no project observed
  grift analyze             # legacy report-v1 display (bare = repo scope)
  grift report --scope tenant   # record a tenant-scope report (needs .tep/identity.toml)
  grift report              # record .grift/report.{json,md} (always re-analyzes)
  grift verify              # verify .grift/report.json
  grift contribute          # local by default; --open is an explicit network action

norms: TEP is evidence, not a verdict. Actor basis may be public, claimed,
admin-authorized, nonconsenting, or unknown; the CLI proves neither consent nor personhood.
Experience/role requires consent=recorded-explicit-consent; state or authority alone is insufficient.
詳細: README"""

_FORMATS = ("md", "json", "both")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def add_format_out(parser: argparse.ArgumentParser, *, default_format: str) -> None:
    parser.add_argument(
        "--format",
        choices=_FORMATS,
        default=default_format,
        help=f"Output format (default: {default_format}). json = one JSON on stdout; diagnostics on stderr",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write artifact to this file, or to a directory under a fixed name. Does not create .grift/",
    )


def add_as_of(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="Observation-window date for rhythm. Default: history HEAD date (window_basis=legacy_head_date)",
    )


def add_reference_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--reference",
        default=None,
        metavar="ID",
        help=(
            "Local benchmark pack source id for comparison metadata. "
            "Does not enable pass/fail, ranking, or hiring"
        ),
    )
    parser.add_argument(
        "--reference-manifest",
        type=Path,
        default=None,
        metavar="FILE",
        help="Path to sources.json so subject commands can load the pack from any cwd",
    )
    parser.add_argument(
        "--event-window",
        nargs=2,
        metavar=("START", "END"),
        default=None,
        help="Forge/tracker UTC date window YYYY-MM-DD YYYY-MM-DD. Must match input windows",
    )


def add_role_lens(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--role-lens",
        choices=ROLE_LENSES,
        default=None,
        help="Display preset only. Does not classify a job or person",
    )


def add_local_exports(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--forge-export",
        type=Path,
        default=None,
        metavar="FILE",
        help="Local target-bound tep-forge-export-v2 file. No API connection",
    )
    parser.add_argument(
        "--tracker-export",
        type=Path,
        default=None,
        metavar="FILE",
        help="Local target-bound tep-tracker-export-v2 file. No API connection",
    )


def add_outcome_declaration(parser: argparse.ArgumentParser) -> None:
    """Attach `--outcome-declaration` to the scopes that can carry it.

    Kept out of :func:`add_local_exports` because the two other parsers that
    call it -- `project` and `align` -- have nowhere to put the block: a
    project report describes declared requirements and an alignment report is
    a view over two saved reports, so neither emits `report_outcome`. Offering
    the flag there accepted a file, read nothing from it, and returned a report
    with no outcome in it, which reads as "nothing was declared" (norms §1).
    """
    parser.add_argument(
        "--outcome-declaration",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "Local tep-outcome-declaration-v1 file: what happened after the "
            "work. Recorded as a declaration, never as an observation, and "
            "never verified by this tool"
        ),
    )


def add_lineage_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--parent", default="", help="Upstream parent full name (owner/name)")
    parser.add_argument("--fork", action="store_true", help="Declare the repository as a fork")
    parser.add_argument("--template", type=Path, default=None, help="Path to a template repository")
    parser.add_argument(
        "--parent-repo",
        type=Path,
        default=None,
        help="Local path to the parent repository",
    )
    parser.add_argument(
        "--vendor-scan",
        action="store_true",
        help="Classify generated_or_vendor from commit path names (slower)",
    )
    parser.add_argument(
        "--survival",
        action="store_true",
        help="Enable EIS-style blame sampling (tau=180d). Slow; git I/O bound",
    )


def add_revision_and_public_evidence(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--rev",
        default=None,
        metavar="REV",
        help="Resolve and observe this revision as one fixed Git OID (default: HEAD)",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--fetch-public",
        action="store_true",
        help="Explicitly collect provider API evidence for the fixed OID",
    )
    source.add_argument(
        "--public-evidence",
        type=Path,
        default=None,
        metavar="DIR",
        help="Replay a saved public-evidence bundle without network access",
    )
    source.add_argument(
        "--resume-public-evidence",
        type=Path,
        default=None,
        metavar="DIR",
        help="Resume an explicitly started partial public-evidence collection",
    )
    parser.add_argument(
        "--forge-provider",
        choices=("auto", "github", "gitlab"),
        default="auto",
        help="Forge adapter (auto only recognizes unambiguous github.com/gitlab.com remotes)",
    )
    parser.add_argument(
        "--forge-api-base",
        default=None,
        metavar="URL",
        help="Explicit API base; required for self-managed GitLab",
    )
    parser.add_argument(
        "--auth-token-env",
        default=None,
        metavar="NAME",
        help="Name of an environment variable containing the API token; its value is never recorded",
    )
    parser.add_argument(
        "--public-evidence-out",
        type=Path,
        default=None,
        metavar="DIR",
        help="CAS evidence bundle destination for --fetch-public",
    )
    parser.add_argument(
        "--max-public-pages",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Safe pagination ceiling; reaching it returns PARTIAL instead of claiming completeness",
    )


def _add_repo_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "repo",
        help="Observe one git repository (report-v2, repo scope)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Does not create .grift/ unless --out is set. TEP is not a ranking tool.",
    )
    parser.add_argument(
        "repo",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Git working tree (default: .)",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help=(
            "Explicit identity.toml; otherwise read only the fixed repository "
            "blob at .tep/identity.toml"
        ),
    )
    add_format_out(parser, default_format="md")
    add_as_of(parser)
    add_role_lens(parser)
    add_local_exports(parser)
    add_outcome_declaration(parser)
    add_lineage_options(parser)
    add_reference_id(parser)
    add_revision_and_public_evidence(parser)
    parser.add_argument(
        "--reference-version",
        default=None,
        metavar="VER",
        help="Reference distribution version (repo scope only)",
    )
    parser.add_argument(
        "--include-local-path",
        action="store_true",
        help="Include the absolute local path in JSON (off by default)",
    )
    parser.add_argument(
        "--actors",
        action="store_true",
        help=(
            "Write a closed actor collection: repo-report, actor-index, "
            "selected cards, and manifest"
        ),
    )


def _add_actor_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "actor",
        help="Observe actors (report-v2). identity.toml is optional",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "identity.toml is optional (alias merge / display names).\n"
            "--all and --top extract by observed commit count, not quality rank.\n"
            "ACTOR_ID with --out DIR writes an explicit closed collection; "
            "stdout or --out FILE.json|FILE.md keeps the basis-aware detailed report "
            "(machine scope is tenant for verified/claimed, actor_cluster otherwise; "
            "scope is not consent proof); "
            "FILE.toml is rejected.\n"
            "--export is not accepted. Not observed is not a lack of skill."
        ),
    )
    parser.add_argument(
        "actor_id", nargs="?", default=None, help="actor id (optional with --all/--top)"
    )
    parser.add_argument(
        "repo",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Git working tree (default: .)",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help=(
            "Explicit identity.toml; experience/role requires "
            "consent=recorded-explicit-consent. Otherwise read .tep/identity.toml "
            "from the fixed target OID"
        ),
    )
    add_format_out(parser, default_format="md")
    add_as_of(parser)
    add_role_lens(parser)
    add_local_exports(parser)
    add_outcome_declaration(parser)
    add_lineage_options(parser)
    add_revision_and_public_evidence(parser)
    parser.add_argument(
        "--include-local-path",
        action="store_true",
        help="Include the absolute local path in JSON (off by default)",
    )
    parser.add_argument("--export", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--reference-version", default=None, help=argparse.SUPPRESS)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--all", dest="all_actors", action="store_true", help="Observe every inferred actor"
    )
    selection.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Observe the N actors with the most commits (not a quality ranking)",
    )
    add_reference_id(parser)


def _add_project_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "project",
        help="Declared requirements and/or observed operating signature (project-v1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Does not evaluate a company. Empty requirements stay not_declared.\n"
            "Git-only observed signatures do not include review or issue operations.\n"
            "Pass --forge-export / --tracker-export to observe those locally. No API."
        ),
    )
    parser.add_argument(
        "repo",
        type=Path,
        nargs="?",
        default=None,
        help="Git working tree for the observed signature",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Write an empty project-v1 template. Requires --out. Refuses overwrite",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=None,
        metavar="FILE",
        help="Declared requirements TOML (tep-project-v1)",
    )
    add_format_out(parser, default_format="md")
    add_as_of(parser)
    add_local_exports(parser)
    add_reference_id(parser)


def _add_align_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "align",
        help="Axis-by-axis declared vs observed view (alignment-v1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "No overall score, rank, or recommendation is computed.\n"
            "Actor basis may be a public cluster or an explicit identity; "
            "missing/contradictory basis fails closed.\n"
            "Formal collection path:\n"
            "  grift repo REPO --actors --format both --out DIR\n"
            "  grift project PROJECT_REPO --requirements FILE --format both --out PROJECT\n"
            "  grift align --actor-dir DIR --actor-id ACTOR_ID "
            "--project-report PROJECT/project.json --format both --out ALIGN\n"
            "Multiple actor cards require --actor-id (alias --actor). "
            "No implicit first-card selection.\n"
            "Compatibility: --repo --identity --actor --project."
        ),
    )
    parser.add_argument("--repo", type=Path, default=None, help="Git working tree")
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help="Explicit identity.toml; otherwise use the fixed repository blob",
    )
    parser.add_argument(
        "--actor",
        default=None,
        dest="actor_id",
        help="actor id (required when --actor-dir has multiple cards)",
    )
    parser.add_argument(
        "--actor-id",
        default=None,
        dest="actor_id",
        help="alias of --actor: select one actor id from --actor-dir",
    )
    parser.add_argument("--project", type=Path, default=None, help="project TOML")
    parser.add_argument(
        "--actor-report",
        type=Path,
        default=None,
        help="Saved report-v2 actor JSON from a possibly different repo",
    )
    parser.add_argument(
        "--project-report",
        type=Path,
        default=None,
        help="Saved project-v1 JSON from the target repo",
    )
    parser.add_argument(
        "--actor-dir",
        type=Path,
        default=None,
        help="Directory of actor cards (actors/*.json) for saved-report alignment",
    )
    parser.add_argument(
        "--team",
        action="store_true",
        help=(
            "Read every actor in --actor-dir and report which declared "
            "requirements the team collectively does not cover. Emits counts "
            "only: no per-actor value, no ranking, no identity."
        ),
    )
    add_format_out(parser, default_format="md")
    add_as_of(parser)
    add_role_lens(parser)
    add_local_exports(parser)
    add_lineage_options(parser)
    add_reference_id(parser)
    parser.add_argument("--reference-version", default=None, help=argparse.SUPPRESS)


def _add_analyze_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "analyze",
        help="Analyze one git repository (legacy report-v1 display)",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "repo",
        type=Path,
        nargs="?",
        default=None,
        help="Path to a git working tree (default: current directory)",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help="Path to identity.toml (default: <repo>/.tep/identity.toml)",
    )
    add_lineage_options(parser)
    parser.add_argument(
        "--format",
        choices=_FORMATS,
        default="both",
        help="Output format (default: both, markdown first)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory to write report.md and report.json",
    )
    parser.add_argument(
        "--include-local-path",
        action="store_true",
        help="Include the absolute local path in report.json (off by default)",
    )
    parser.add_argument(
        "--scope",
        choices=("tenant", "repo"),
        default=None,
        help=(
            "tenant: identity-matched evidence. repo: all human commits. "
            "Bare `grift analyze` defaults to repo; explicit-path invocations default to tenant. "
            "`--scope actor` is not accepted; use `grift actor ACTOR_ID`."
        ),
    )
    parser.add_argument(
        "--reference-version",
        default=None,
        metavar="VER",
        help="Reference distribution version (default: latest; e.g. v2026.09 is still selectable and immutable).",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "Also write machine-ingestible export-v1 files "
            "(commits.ndjson, actors.json, export-meta.json) into DIR. "
            "No raw emails are exported."
        ),
    )
    parser.add_argument(
        "--actor",
        default=None,
        metavar="ACTOR_ID",
        help=(
            "Deprecated alias for `grift actor`. Emits report-v2 and does not "
            "overwrite .grift/report.json"
        ),
    )


def _add_verify_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "verify",
        help="Recompute a report.json under its recorded provenance and diff it",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "report_positional",
        type=Path,
        nargs="?",
        default=None,
        help="Path to report.json (default: .grift/report.json — or run a bare verify after report)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Report paired with --bundle (or explicit alternative to the positional report)",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=None,
        help="tep-attest-v1 bundle directory; signature, report hash, and recomputation are separate",
    )
    parser.add_argument(
        "--public-evidence",
        type=Path,
        default=None,
        metavar="DIR",
        help="Verify a saved public-evidence bundle without network access",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Path to the target repository (default: current directory)",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help=(
            "Explicit identity.toml used by the original analysis; otherwise use the fixed "
            "repository blob (never the caller CWD). Experience/role requires the recorded "
            "explicit-consent marker"
        ),
    )
    parser.add_argument("--project", type=Path, default=None, help="project TOML for alignment-v1")
    parser.add_argument("--forge-export", type=Path, default=None)
    parser.add_argument("--tracker-export", type=Path, default=None)
    parser.add_argument("--actor", default=None, dest="actor_id")
    parser.add_argument("--actor-report", type=Path, default=None)
    parser.add_argument("--project-report", type=Path, default=None)
    parser.add_argument("--reference-manifest", type=Path, default=None)
    parser.add_argument("--allowed-signers", type=Path, default=None)
    parser.add_argument("--principal", default=None)
    parser.add_argument("--certificate-identity", default=None)
    parser.add_argument("--certificate-oidc-issuer", default=None)
    parser.add_argument("--cosign-public-key", type=Path, default=None)


def _add_update_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "update",
        help="Upgrade grift-cli itself (pipx or pip; explicit, never automatic)",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only show the latest available version from PyPI (read-only), do not upgrade",
    )


def _add_report_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "report",
        help="Analyze the current repo and RECORD into .grift/report.{json,md}; or re-render md from an existing report.json",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "report_json",
        type=Path,
        nargs="?",
        default=None,
        help="Path to an existing report.json to re-render (default: analyze the current repo into .grift/)",
    )
    parser.add_argument(
        "--scope",
        choices=("tenant", "repo"),
        default="repo",
        help="Analysis scope for the bare form (default: repo)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write report.md here (default: stdout)",
    )


def _add_benchmark_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "benchmark",
        help="Inspect the local v0.6 reference pack (offline)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Does not rank people or classify jobs. Local fixtures only.",
    )
    bench = parser.add_subparsers(dest="benchmark_command", required=True)
    listed = bench.add_parser("list", help="List catalog entries")
    listed.add_argument("manifest", nargs="?", type=Path, default=None)
    inspect = bench.add_parser("inspect", help="Inspect one source id or compute fixture views")
    inspect.add_argument("source_id")
    inspect.add_argument("--manifest", type=Path, default=None)
    validate = bench.add_parser("validate", help="Verify local hashes")
    validate.add_argument("manifest", nargs="?", type=Path, default=None)


def _add_contribute_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "contribute",
        help=(
            "Build an opt-in contribution payload locally by default; "
            "--open is an explicit network action"
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "report_json",
        type=Path,
        nargs="?",
        default=None,
        help="Path to a repo-scope report.json (default: .grift/report.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the payload JSON here (default: stdout prints payload + confirmation)",
    )
    parser.add_argument(
        "--mode",
        choices=("masked", "named-public"),
        default=None,
        help="Legacy alias for --privacy; retained for v1 callers",
    )
    parser.add_argument(
        "--privacy",
        choices=("aggregate", "named-public", "masked", "raw"),
        default="aggregate",
        help="Disclosure profile (default: aggregate, the only public-safe aggregate form)",
    )
    parser.add_argument(
        "--purpose",
        # Sourced from the norms-linked set rather than retyped: a choice the
        # CLI offers but the validator rejects would be a dead end at the last
        # step of a consent flow.
        choices=tuple(PURPOSES),
        default=None,
        help=(
            "Purpose this submission is bound to; recorded in the payload and "
            "the only use the recipient is permitted (docs/norms.md). "
            "Default: reference-distributions, the v0.6 meaning."
        ),
    )
    parser.add_argument(
        "--door",
        choices=("local", "controlled", "public-pr"),
        default="local",
        help="Destination contract; masked/raw are rejected for public-pr",
    )
    secret = parser.add_mutually_exclusive_group()
    secret.add_argument(
        "--key-file",
        type=Path,
        default=None,
        help="Permission-checked file containing a >=32-byte HMAC key (masked only)",
    )
    secret.add_argument(
        "--key-fd",
        type=int,
        default=None,
        metavar="FD",
        help="Already-open file descriptor containing a >=32-byte HMAC key (masked only)",
    )
    parser.add_argument("--controlled-sidecar", type=Path, default=None)
    parser.add_argument("--study-manifest", type=Path, default=None)
    parser.add_argument("--repo-subject-id", default=None)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation (payload is still printed in full)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help=(
            "For public-pr only, prepare a branch in the submitter's fork and open "
            "the final PR creation page. No masked/raw controlled payload is accepted."
        ),
    )


def _add_attest_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "attest",
        help="Create a signed tep-attest-v1 statement for an existing report",
        epilog=(
            "A signature proves the executing identity and recorded conditions; "
            "it does not prove metric correctness, quality, or superiority."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("report", type=Path, help="Report JSON to hash and attest")
    parser.add_argument(
        "--repo", type=Path, required=True, help="Repository used for recomputation"
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help="Identity declaration used by a consenting tenant report",
    )
    parser.add_argument(
        "--public-evidence",
        type=Path,
        default=None,
        metavar="DIR",
        help="Saved public-evidence bundle used by the report (offline replay only)",
    )
    parser.add_argument(
        "--forge-export",
        type=Path,
        default=None,
        metavar="FILE",
        help="Target-bound forge export used by the report",
    )
    parser.add_argument(
        "--tracker-export",
        type=Path,
        default=None,
        metavar="FILE",
        help="Target-bound tracker export used by the report",
    )
    parser.add_argument(
        "--reference-manifest",
        type=Path,
        default=None,
        metavar="FILE",
        help="Benchmark reference manifest used by the report",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        metavar="FILE",
        help="Project declaration required to recompute alignment-v1",
    )
    parser.add_argument(
        "--actor",
        default=None,
        dest="actor_id",
        metavar="ACTOR_ID",
        help="Actor identifier required by compatibility alignment inputs",
    )
    parser.add_argument(
        "--actor-report",
        type=Path,
        default=None,
        help="Saved actor report/card required by saved-report alignment",
    )
    parser.add_argument(
        "--project-report",
        type=Path,
        default=None,
        help="Saved project report required by saved-report alignment",
    )
    parser.add_argument("--out", type=Path, required=True, help="New bundle directory")
    parser.add_argument("--sign", choices=("cosign", "ssh"), required=True)
    parser.add_argument("--ssh-key", type=Path, default=None, help="SSH private key for --sign ssh")
    parser.add_argument(
        "--principal",
        default=None,
        help="SSH signer principal recorded in the statement (required for --sign ssh)",
    )
    parser.add_argument("--cosign-key", type=Path, default=None)
    parser.add_argument("--cosign-public-key", type=Path, default=None)
    parser.add_argument("--certificate-identity", default=None)
    parser.add_argument("--certificate-oidc-issuer", default=None)
    parser.add_argument(
        "--repo-hint",
        default=None,
        help="Optional opt-in public repository hint; omitted by default",
    )


def _add_portfolio_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "portfolio",
        help="Build a non-scoring cross-repository evidence ledger",
        epilog="Subject links require submitter declarations or attestations; email/handle inference is forbidden.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, required=True, help="portfolio.toml")
    parser.add_argument("--format", choices=_FORMATS, default="both")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--allowed-signers",
        type=Path,
        default=None,
        help="Recipient-owned OpenSSH allowed_signers file for attested binding",
    )
    parser.add_argument(
        "--principal",
        default=None,
        help="Exact OpenSSH principal for attested binding",
    )
    parser.add_argument(
        "--certificate-identity",
        default=None,
        help="Exact cosign certificate identity for attested binding",
    )
    parser.add_argument(
        "--certificate-oidc-issuer",
        default=None,
        help="Exact cosign certificate OIDC issuer for attested binding",
    )
    parser.add_argument(
        "--cosign-public-key",
        type=Path,
        default=None,
        help="Recipient-owned cosign public key for attested binding",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grift",
        description=(
            "grift — deterministic TEP evidence from a git repository. No LLM. "
            "Subject commands: repo / actor / project / align. "
            "TEP is not a scoring, ranking, or hiring tool."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"grift {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_repo_parser(sub)
    _add_actor_parser(sub)
    _add_project_parser(sub)
    _add_align_parser(sub)
    _add_analyze_parser(sub)
    _add_verify_parser(sub)
    _add_update_parser(sub)
    _add_report_parser(sub)
    _add_contribute_parser(sub)
    _add_attest_parser(sub)
    _add_portfolio_parser(sub)
    _add_benchmark_parser(sub)
    return parser
