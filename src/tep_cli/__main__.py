"""grift CLI (method = TEP). Verb semantics: analyze=display (stdout), report=record (.grift/)."""

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
  grift analyze             # analyze the current repo, print to stdout (repo scope)
  grift report              # analyze and RECORD into .grift/report.{json,md} (always re-analyzes)
  grift report --scope tenant   # record a tenant-scope report (needs .tep/identity.toml)
  grift verify              # verify .grift/report.json against the current repo
  grift contribute          # build an opt-in payload from .grift/report.json (never sends)
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
        default=None,
        help="tenant: identity-matched evidence. repo: all human commits (reference distribution). Bare `grift analyze` defaults to repo; explicit-path invocations default to tenant.",
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

    update = sub.add_parser(
        "update",
        help="Upgrade grift-cli itself (pipx or pip; explicit, never automatic)",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    update.add_argument(
        "--check",
        action="store_true",
        help="Only show the latest available version from PyPI (read-only), do not upgrade",
    )
    render = sub.add_parser(
        "report",
        help="Analyze the current repo and RECORD into .grift/report.{json,md}; or re-render md from an existing report.json",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    render.add_argument(
        "report_json",
        type=Path,
        nargs="?",
        default=None,
        help="Path to an existing report.json to re-render (default: analyze the current repo into .grift/)",
    )
    render.add_argument(
        "--scope",
        choices=("tenant", "repo"),
        default="repo",
        help="Analysis scope for the bare form (default: repo)",
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
        help="Path to a repo-scope report.json (default: .grift/report.json)",
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
    contribute.add_argument(
        "--open",
        action="store_true",
        help=(
            "After writing the payload, open the submission flow: with gh + git "
            "available, fork tep-contributions and open the PR creation page with "
            "the payload already committed (you only press 'Create pull request'). "
            "Without gh, opens the browser to the intake repo's new-PR page. "
            "The grift CLI itself still sends nothing."
        ),
    )
    return parser


def _maybe_update_notice() -> None:
    """Read-only update notice (#51 extension): one stderr line when a newer
    PyPI version exists. Runs only in interactive (TTY) analyze/report/verify
    invocations; CI/non-TTY stays silent. Reads public PyPI JSON; sends nothing."""
    import os
    import urllib.request

    if not sys.stdout.isatty() or os.environ.get("GRIFT_NO_UPDATE_NOTICE"):
        return
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/grift-cli/json", timeout=2) as response:
            latest = json.loads(response.read()).get("info", {}).get("version")
    except Exception:  # noqa: BLE001 — offline/timeout: stay silent
        return
    if latest and latest != __version__:
        sys.stderr.write(
            f"grift {__version__}: 新しいバージョン {latest} があります "
            f"(grift update で更新 / GRIFT_NO_UPDATE_NOTICE=1 で非表示)\n"
        )


def _run_analyze(args: argparse.Namespace) -> int:
    _maybe_update_notice()
    repo: Path = args.repo if args.repo is not None else Path(".")
    scope = (
        str(args.scope) if args.scope is not None else ("repo" if args.repo is None else "tenant")
    )
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
        scope=scope,
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
    Path("out") / "report.json",  # legacy pre-0.5.5 locations, read-only compat
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
        return _analyze_to_grift_dir(scope=str(args.scope))
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


def _run_update(args: argparse.Namespace) -> int:
    """Explicit self-upgrade (#51). No telemetry: reads PyPI metadata (public
    JSON) only with --check; upgrade runs pipx/pip locally."""
    import shutil
    import subprocess
    import urllib.request

    latest = None
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/grift-cli/json", timeout=10) as response:
            latest = json.loads(response.read()).get("info", {}).get("version")
    except Exception as exc:  # noqa: BLE001 — offline is fine
        sys.stderr.write(f"version check skipped (offline or PyPI unreachable): {exc}\n")
    sys.stdout.write(f"installed: {__version__}\n")
    if latest:
        sys.stdout.write(f"latest:    {latest}\n")
        if latest == __version__:
            sys.stdout.write("up to date\n")
            return 0
    elif not args.check:
        sys.stderr.write("continuing with upgrade attempt anyway\n")
    if args.check:
        return 0
    pipx = shutil.which("pipx")
    if pipx:
        sys.stdout.write("running: pipx upgrade grift-cli\n")
        result = subprocess.run([pipx, "upgrade", "grift-cli"])
        return result.returncode
    pip = shutil.which("pip") or shutil.which("pip3")
    if pip:
        sys.stdout.write("running: pip install --upgrade grift-cli\n")
        result = subprocess.run([pip, "install", "--upgrade", "grift-cli"])
        return result.returncode
    sys.stderr.write("neither pipx nor pip found — upgrade manually (pipx upgrade grift-cli)\n")
    return 2


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
    import hashlib
    from datetime import datetime, timezone

    payload_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    target = args.out
    if target is None:
        # UX (#49): consented submissions always land somewhere — default to .grift/
        target = GRIFT_DIR / "contribution.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload_text, encoding="utf-8")
    digest = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    submission_id = now.strftime("%m%d-%H%M") + "-" + digest[:8]
    sys.stderr.write(f"\npayload written to {target} (nothing was sent)\n")
    sys.stderr.write(
        "\n=== 次の提出手順（あなた自身が行います・CLIは送信しません） ===\n"
        f"1. 公開ドア: https://github.com/Cor-Incorporated/tep-contributions に PR を出す\n"
        f"   - ファイル名: payloads/{now.year}/{submission_id}.json（上記 payload をそのまま）\n"
        f"   - 同じ場所に {submission_id}.meta.json も追加（--open は自動でコミット済み / Public door adds a sidecar meta file; --open commits it automatically）:\n"
        f'     {{"id":"{submission_id}","sha256":"{digest}","received_at":"{now.strftime("%Y-%m-%dT%H:%M:%SZ")}","door":"pr"}}\n'
        f"   - manifest.jsonl は main で自動生成されるため編集不要（並行提出と衝突しません）/ manifest.jsonl is generated on main; do not edit it\n"
        f"2. 非公開ドア: payload ファイルを会社へ送付（代理PR・身元は非公開 / private door: send the payload file; we open the PR anonymously）\n"
        f"   詳細: tep-contributions の README/CONTRIBUTING\n"
    )
    if getattr(args, "open", False):
        from tep_core.contribute import validate_contribution_payload

        violations = validate_contribution_payload(payload)
        if violations:
            sys.stderr.write(
                "contribute --open: payload failed the local pre-push check; not pushing:\n"
            )
            for violation in violations:
                sys.stderr.write(f"  - {violation}\n")
            return 1
        _open_submission_flow(payload_text, submission_id, digest, now)
    return 0


def _open_submission_flow(payload_text: str, submission_id: str, digest: str, now) -> None:
    """`grift contribute --open` (#49 follow-up): open the submission flow.

    Preferred path (gh + git available): create a fork branch locally with the
    payload committed (payload + manifest line), push it to the user's fork,
    and open the compare URL — the browser shows a ready PR with files already
    attached; the user only presses "Create pull request".
    Fallback: open the intake repo's new-PR page in the browser.

    grift itself performs no network call: git push goes to the USER's fork
    with the user's own gh/git credentials (the user presses the final button).
    """
    import shlex
    import shutil
    import subprocess
    import tempfile
    import urllib.parse
    import urllib.request

    INTAKE = "https://github.com/Cor-Incorporated/tep-contributions"
    received_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    branch = f"contrib/{submission_id}"
    title = f"contribution: {submission_id}"
    body = (
        f"Opt-in TEP contribution (door: pr).\n\n"
        f"- payload: `payloads/{now.year}/{submission_id}.json`\n"
        f"- sha256: `{digest}`\n"
    )
    gh = shutil.which("gh")
    git = shutil.which("git")
    if not (gh and git):
        # fallback: browser to the intake repo (manual attach)
        url = f"{INTAKE}/compare/main...new?expand=1"
        _open_browser(url)
        sys.stderr.write(
            "opened the intake repository in your browser — attach "
            f"{GRIFT_DIR / 'contribution.json'} as payloads/{now.year}/{submission_id}.json "
            "(gh CLI not found for the automated branch flow)\n"
        )
        return

    def run(
        cmd: list[str], cwd: str | None = None, check: bool = True
    ) -> subprocess.CompletedProcess:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"{' '.join(shlex.quote(c) for c in cmd)}\n{result.stderr.strip()}")
        return result

    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = str(Path(tmp) / "tep-contributions")
            run([git, "clone", "--quiet", "--depth", "1", f"{INTAKE}.git", repo_dir])
            year_dir = Path(repo_dir) / "payloads" / str(now.year)
            year_dir.mkdir(parents=True, exist_ok=True)
            (year_dir / f"{submission_id}.json").write_text(payload_text, encoding="utf-8")
            # C: PRs add payload + sidecar meta only; manifest.jsonl is
            # regenerated on main (single writer) — no append conflicts
            meta = year_dir / f"{submission_id}.meta.json"
            meta.write_text(
                json.dumps(
                    {
                        "id": submission_id,
                        "sha256": digest,
                        "received_at": received_at,
                        "door": "pr",
                    },
                    ensure_ascii=False,
                    indent=1,
                )
                + "\n",
                encoding="utf-8",
            )
            run([git, "-C", repo_dir, "config", "user.name", "grift-contribute"])
            run(
                [git, "-C", repo_dir, "config", "user.email", "contribute@users.noreply.github.com"]
            )
            run([git, "-C", repo_dir, "checkout", "--quiet", "-b", branch])
            run([git, "-C", repo_dir, "add", "-A"])
            run([git, "-C", repo_dir, "commit", "--quiet", "-m", title])
            # fork (idempotent) using the user's credentials; the intake README
            # already discloses that --open may auto-create the fork (B-3)
            run([gh, "repo", "fork", INTAKE, "--clone=false"], check=False)
            user = run([gh, "api", "user", "--jq", ".login"]).stdout.strip()
            fork_url = f"https://github.com/{user}/tep-contributions.git"
            if fork_url.rstrip(".git") == INTAKE:
                raise RuntimeError("push target resolved to the intake origin; refusing")
            # B-3: push ONLY the single contribution branch to the user's fork;
            # never push to origin (the clone's origin stays untouched).
            run([git, "-C", repo_dir, "remote", "add", "fork", fork_url])
            run([git, "-C", repo_dir, "push", "--quiet", "fork", branch])
            compare = (
                f"{INTAKE}/compare/{urllib.parse.quote(branch)}"
                f"?expand=1&title={urllib.parse.quote(title)}"
                f"&body={urllib.parse.quote(body)}"
            )
            _open_browser(compare)
            sys.stderr.write(
                f"branch `{branch}` pushed to your fork ({user}/tep-contributions).\n"
                "browser opened at the PR creation page — payload and manifest line are "
                "already committed; press 'Create pull request' to submit.\n"
            )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        sys.stderr.write(f"automated flow failed ({exc}); falling back to the browser\n")
        _open_browser(f"{INTAKE}/compare/main...new?expand=1")


def _open_browser(url: str) -> None:
    import platform
    import subprocess

    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", url], check=False)
    elif system == "Windows":
        subprocess.run(["cmd", "/c", "start", url], check=False)
    else:
        subprocess.run(["xdg-open", url], check=False)


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
    if args.command == "update":
        return _run_update(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
