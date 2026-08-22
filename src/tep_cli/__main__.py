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
from tep_core.version import __version__

_EPILOG = """examples:
  grift analyze . --scope repo
  grift analyze ./repo --format md --out ./out
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
    analyze.add_argument("repo", type=Path, help="Path to a git working tree")
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
    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    repo: Path = args.repo
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "analyze":
        return _run_analyze(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
