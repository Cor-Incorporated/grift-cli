"""grift CLI (method = TEP)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tep_core.analyze import analyze_repository
from tep_core.export import build_export, write_export
from tep_core.identity import IdentityValidationError, discover_identity
from tep_core.lineage import Lineage
from tep_core.report import render_markdown
from tep_core.verify import CANNOT_VERIFY, MISMATCH, VERIFIED, verify_report
from tep_core.version import __version__

_EPILOG = """examples:
  grift analyze             # analyze the current repo → .grift/report.{json,md}
  grift report              # same as bare analyze: always re-analyzes HEAD
  grift verify              # verify .grift/report.json against the current repo
  grift contribute          # build an opt-in payload from .grift/report.json (never sends)
  grift analyze PATH --scope tenant --identity .tep/identity.toml   # custom
詳細: README"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grift",
        description="grift — deterministic TEP evidence from a git repository. No LLM.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"grift {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser(
        "analyze",
        help="Analyze one git repository",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    analyze.add_argument(
        "repo",
        type=Path,
        nargs="?",
        default=None,
        help="Path to a git working tree (default: current directory)",
    )
    analyze.add_argument(
        "--identity",
        type=Path,
        default=None,
        help="Path to identity.toml (default: <repo>/.tep/identity.toml)",
    )
    analyze.add_argument(
        "--parent",
        default="",
        help="Upstream parent full name (owner/name). Implies lineage.",
    )
    analyze.add_argument(
        "--fork",
        action="store_true",
        help="Declare the repository as a fork (lineage).",
    )
    analyze.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Path to a template repository (enables template_inherited).",
    )
    analyze.add_argument(
        "--parent-repo",
        type=Path,
        default=None,
        help="Local path to the parent repository (enables derivative classes).",
    )
    analyze.add_argument(
        "--format",
        choices=("md", "json", "both"),
        default="both",
        help="Output format (default: both, markdown first)",
    )
    analyze.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory to write report.md and report.json",
    )
    analyze.add_argument(
        "--vendor-scan",
        action="store_true",
        help="Classify generated_or_vendor from commit path names (slower).",
    )
    analyze.add_argument(
        "--include-local-path",
        action="store_true",
        help="Include the absolute local path in report.json (off by default).",
    )
    analyze.add_argument(
        "--survival",
        action="store_true",
        help="Enable EIS-style blame sampling (tau=180d). Slow; git I/O bound.",
    )
    analyze.add_argument(
        "--scope",
        choices=("tenant", "repo"),
        default="tenant",
        help="tenant: identity-matched evidence. repo: all human commits (reference distribution).",
    )
    analyze.add_argument(
        "--reference-version",
        default=None,
        metavar="VER",
        help="Reference distribution version (default: latest; e.g. v2026.09 is still selectable and immutable).",
    )
    analyze.add_argument(
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

    verify = sub.add_parser(
        "verify",
        help="Recompute a report.json under its recorded provenance and diff it",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    verify.add_argument(
        "report",
        type=Path,
        nargs="?",
        default=None,
        help="Path to report.json (default: .grift/report.json — or run a bare verify after report)",
    )
    verify.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Path to the target repository (default: current directory)",
    )
    verify.add_argument(
        "--identity",
        type=Path,
        default=None,
        help="Optional identity.toml used for the original analysis (attribution re-verification).",
    )

    render = sub.add_parser(
        "report",
        help="Analyze the current repo and write ./out/report.{json,md}; or re-render md from an existing report.json",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    render.add_argument(
        "report_json",
        type=Path,
        nargs="?",
        default=None,
        help="Path to an existing report.json to re-render (default: analyze the current repo into ./out)",
    )
    render.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write report.md here (default: stdout)",
    )

    contribute = sub.add_parser(
        "contribute",
        help="Build an opt-in contribution payload from a repo-scope report (never sends)",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    contribute.add_argument(
        "report_json",
        type=Path,
        nargs="?",
        default=None,
        help="Path to a repo-scope report.json (default: .grift/, then legacy locations)",
    )
    contribute.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the payload JSON here (default: stdout prints payload + confirmation)",
    )
    contribute.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation (payload is still printed in full)",
    )
    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    repo: Path = args.repo if args.repo is not None else Path(".")
    if not (repo / ".git").exists() and not repo.joinpath("HEAD").exists():
        sys.stderr.write(f"not a git repository: {repo}\n")
        return 2
    try:
        identity = discover_identity(repo, args.identity)
    except IdentityValidationError as exc:
        sys.stderr.write(f"identity validation error: {exc}\n")
        return 2
    lineage = Lineage(is_fork=bool(args.fork), parent=args.parent or None)
    report = analyze_repository(
        repo,
        identity,
        lineage,
        template_provided=args.template is not None,
        parent_repo_provided=args.parent_repo is not None,
        include_files=bool(args.vendor_scan),
        include_local_path=bool(args.include_local_path),
        survival=bool(args.survival),
        scope=str(args.scope),
        reference_version=str(args.reference_version) if args.reference_version else None,
    )
    markdown = render_markdown(report)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(markdown, encoding="utf-8")
        (args.out / "report.json").write_text(encoded, encoding="utf-8")
    if args.format in {"md", "both"}:
        sys.stdout.write(markdown)
        if args.format == "both":
            sys.stdout.write("\n")
    if args.format in {"json", "both"}:
        sys.stdout.write(encoded)
    if args.export is not None:
        export = build_export(
            repo,
            identity,
            lineage,
            template_provided=args.template is not None,
            parent_repo_provided=args.parent_repo is not None,
            include_files=bool(args.vendor_scan),
            scope=str(args.scope),
        )
        write_export(export, args.export)
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    repo = args.repo if args.repo is not None else Path(".")
    report = args.report if args.report is not None else GRIFT_DIR / "report.json"
    if not report.is_file():
        sys.stderr.write(
            f"verify: {report} not found — run `grift report` first "
            "(bare verify checks .grift/report.json against the current repo)\n"
        )
        return 2
    result = verify_report(report, repo, args.identity)
    if result.status == VERIFIED:
        sys.stdout.write(f"{VERIFIED}: all fields match recomputation under recorded provenance\n")
        return 0
    if result.status == MISMATCH:
        sys.stdout.write(f"{MISMATCH}: {len(result.differences)} field(s) differ\n")
        for line in result.differences:
            sys.stdout.write(f"  - {line}\n")
        return 1
    sys.stdout.write(f"{CANNOT_VERIFY}:\n")
    for note in result.notes:
        sys.stdout.write(f"  - {note}\n")
    return 2


GRIFT_DIR = Path(".grift")
_DEFAULT_REPORT_SEARCH = (
    GRIFT_DIR / "report.json",
    Path("out") / "report.json",   # legacy pre-0.5.5 locations, read-only compat
    Path(".grift-out") / "report.json",
    Path("report.json"),
)


def _resolve_report_path(explicit: Path | None) -> tuple[Path | None, str]:
    """Return (path, guidance). Search .grift, then legacy ./out, .grift-out, ./."""
    if explicit is not None:
        return explicit, ""
    for candidate in _DEFAULT_REPORT_SEARCH:
        if candidate.is_file():
            return candidate, ""
    return None, ""


def _run_report(args: argparse.Namespace) -> int:
    if args.report_json is None:
        # UX (代表 2026-08-23): bare `grift report` ALWAYS re-analyzes the
        # current HEAD and rewrites .grift/report.{json,md}. It never falls
        # back to a stale report.json — "report で測ったつもりが古い
        # SHA のまま" は自己証明の罠になるため、既存ファイルは無条件に
        # 上書きする。再分析なしの再レンダリングは引数指定時のみ。
        return _analyze_to_grift_dir(scope="repo")
    try:
        payload = json.loads(args.report_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"report unreadable ({args.report_json}): {exc}\n")
        return 2
    try:
        markdown = render_markdown(payload)
    except KeyError as exc:
        sys.stderr.write(f"report is missing a required field: {exc}\n")
        return 2
    if args.out is not None:
        target = args.out / "report.md" if args.out.is_dir() else args.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 0


def _analyze_to_grift_dir(*, scope: str = "repo") -> int:
    """Run the analysis in the current directory and write ./out/report.{json,md}.

    UX (v0.5.5): bare verbs write into .grift/ (auto-created, gitignored
    by convention). Reuses the analyze pipeline on '.'.
    """
    repo = Path(".")
    if not (repo / ".git").exists():
        sys.stderr.write("grift: not a git repository (run inside the repo you want to analyze)\n")
        return 2
    identity = discover_identity(repo, None)
    report = analyze_repository(repo, identity, Lineage(), scope=scope)
    markdown = render_markdown(report)
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    out_dir = GRIFT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(encoded, encoding="utf-8")
    (out_dir / "report.md").write_text(markdown, encoding="utf-8")
    sys.stdout.write(markdown)
    sys.stderr.write(f"\nwrote {out_dir / 'report.json'} and {out_dir / 'report.md'}\n")
    return 0


def _run_contribute(args: argparse.Namespace) -> int:
    from tep_core.contribute import CONFIRMATION_TEXT, build_contribution, render_confirmation

    report_path, _guidance = _resolve_report_path(args.report_json)
    if report_path is None:
        sys.stderr.write(
            "contribute: no report.json found (searched .grift/report.json, then legacy ./out, .grift-out, ./). "
            "Run `grift report` first — it will analyze the repo and write .grift/report.json.\n"
        )
        return 2
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"report unreadable ({report_path}): {exc}\n")
        return 2
    try:
        payload = build_contribution(report)
    except ValueError as exc:
        sys.stderr.write(f"contribute: {exc}\n")
        return 2
    text = render_confirmation(payload)
    if not args.yes:
        # F-C1: consent gate is enforced on EVERY path. Non-TTY without --yes
        # is refused (exit 2) with the disclosure on stderr — never a silent write.
        if not sys.stdin.isatty():
            sys.stderr.write(
                "contribute: interactive confirmation required.\n\n"
                + CONFIRMATION_TEXT
                + "\n非対話環境では --yes を明示してください。--yes でも開示文と payload 全文を表示してから書き出します。\n"
            )
            return 2
        sys.stdout.write(text)
        answer = input(
            "提出payloadを確認しましたか？ 公開されることに同意して書き出しますか? [yes/No] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            sys.stderr.write("aborted: nothing was written or sent\n")
            return 1
    else:
        # F-C1: --yes still prints disclosure + payload summary BEFORE writing
        # (consent leaves a trace even in non-interactive use).
        sys.stderr.write(CONFIRMATION_TEXT)
        sys.stderr.write(
            f"payload summary: schema={payload['contribution_schema']} "
            f"purpose={payload['purpose']} "
            f"definition={payload['provenance']['definition_version']} "
            f"metric_sections={sorted(payload['metrics'])}\n"
            f"payload full text follows on stdout.\n"
        )
        sys.stdout.write(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        sys.stderr.write(f"payload written to {args.out} (nothing was sent)\n")
    elif args.yes:
        pass  # full text already on stdout above
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "analyze":
        return _run_analyze(args)
    if args.command == "verify":
        return _run_verify(args)
    if args.command == "report":
        return _run_report(args)
    if args.command == "contribute":
        return _run_contribute(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
