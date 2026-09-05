#!/usr/bin/env python3
"""P0/P1 falsification runner for v0.6.0. Exit 1 on any P0 FAIL."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def resolve_v059_root(
    *, root: Path = ROOT, environ: Mapping[str, str] | None = None
) -> Path | None:
    """Resolve the comparison worktree without assuming the current worktree is primary.

    An explicit override is authoritative.  Otherwise ``--git-common-dir``
    identifies the primary repository that owns all linked worktrees.  Any
    malformed/non-Git environment returns ``None`` so ``main`` fails closed
    before attempting the compatibility comparison.
    """

    active_environ = os.environ if environ is None else environ
    override = active_environ.get("GRIFT_V059_ROOT")
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate.resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    raw_common_dir = result.stdout.strip()
    if not raw_common_dir:
        return None
    common_dir = Path(raw_common_dir)
    if not common_dir.is_absolute():
        common_dir = root / common_dir
    common_dir = common_dir.resolve()
    if common_dir.name != ".git" or not common_dir.is_dir():
        return None
    return common_dir.parent / ".worktrees" / "grok" / "v059"


V059 = resolve_v059_root()
LOG = Path(os.environ.get("GRIFT_FALSIFY_LOG", "/tmp/grift-v060-falsify"))
LOG.mkdir(parents=True, exist_ok=True)

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
VERDICT = (
    "overall",
    "score",
    "rank",
    "fit",
    "recommendation",
    "hire",
    "pass",
    "fail",
    "適性",
    "向き",
    "不十分",
    "能力不足",
    "未経験",
    "弱い",
)
RESULTS: list[dict] = []
PERSISTED_TMP_ROOT = "${TMP_ROOT}"


def git(repo: Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.com")
    git(path, "config", "commit.gpgsign", "false")
    return path


def commit(
    repo: Path,
    *,
    email: str,
    date: str,
    message: str,
    filename: str = "file.txt",
    content: str | None = None,
    name: str = "Author",
    time: str = "12:00:00",
) -> None:
    target = repo / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        content = message + "\n"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    target.write_text(existing + content, encoding="utf-8")
    git(repo, "add", filename)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": f"{date}T{time}",
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": f"{date}T{time}",
    }
    git(repo, "commit", "-m", message, env=env)


def identity(path: Path, rows: str, patterns: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = 'schema_version = "identity-v1"\n\n'
    if patterns:
        body += f"[tenant]\nemail_patterns = [{patterns}]\n\n"
    path.write_text(body + rows, encoding="utf-8")
    return path


def stage_fixed_identity(repo: Path, rows: str, patterns: str = "") -> Path:
    """Stage the repo-local identity so the next fixture commit fixes it in-tree."""

    path = identity(repo / ".tep" / "identity.toml", rows, patterns)
    git(repo, "add", ".tep/identity.toml")
    return path


ALICE = (
    '[[actors]]\ncanonical_id = "alice"\nemails = ["alice@example.com"]\n'
    'attribution_state = "verified"\n'
)
BOB = (
    '[[actors]]\ncanonical_id = "bob"\nemails = ["bob@example.com"]\n'
    'attribution_state = "claimed"\n'
)


def alice_bob(root: Path, *, tests: bool = True, extra_bob: bool = True) -> Path:
    repo = init_repo(root / "repo")
    stage_fixed_identity(repo, ALICE + "\n" + BOB)
    if tests:
        (repo / "tests").mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "demo"\ndependencies = ["pytest"]\n', encoding="utf-8"
        )
        (repo / "tests" / "test_app.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        git(repo, "add", "pyproject.toml")
    (repo / "src" / "api").mkdir(parents=True)
    for index in range(12):
        commit(
            repo,
            email="alice@example.com",
            date="2026-08-01",
            message=f"feat: alice {index}",
            filename="src/api/app.py",
            name="Alice",
        )
        if tests and index % 2 == 0:
            commit(
                repo,
                email="alice@example.com",
                date="2026-08-01",
                message=f"test: alice {index}",
                filename="tests/test_app.py",
                name="Alice",
            )
    if extra_bob:
        commit(
            repo,
            email="bob@example.com",
            date="2026-08-02",
            message="feat: bob secret-marker BOBONLY",
            filename="src/api/bob.py",
            content="print('BOBONLY')\n",
            name="Bob",
        )
    return repo


def run_cli(
    args: list[str],
    *,
    cwd: Path,
    src: Path = ROOT / "src",
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    merged = {**os.environ, "PYTHONPATH": str(src), "GRIFT_NO_UPDATE_NOTICE": "1"}
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "-m", "tep_cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=merged,
    )


def parse_json(text: str) -> dict:
    text = text.strip()
    if not text:
        raise json.JSONDecodeError("empty", text, 0)
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("no object", text, 0)
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise json.JSONDecodeError("root not object", text, start)
    return obj


def strip_volatile(node: dict) -> dict:
    payload = copy.deepcopy(node)
    prov = payload.get("provenance") or {}
    for key in ("analyzed_at", "tool_version", "definition_version"):
        prov.pop(key, None)
    if "input_digests" in prov:
        pass
    payload["provenance"] = prov
    return payload


def record(
    name: str,
    hypothesis: str,
    counter: str,
    fixture: str,
    command: str,
    expected: str,
    actual: str,
    verdict: str,
    evidence: str,
) -> None:
    RESULTS.append(
        {
            "name": name,
            "hypothesis": hypothesis,
            "counter": counter,
            "fixture": fixture,
            "command": command,
            "expected": expected,
            "actual": actual,
            "verdict": verdict,
            "evidence": evidence,
        }
    )


def sanitize_results_for_persistence(results: list[dict], *, tmp_root: Path) -> list[dict]:
    """Replace this run's temporary root without changing live assertions/output.

    The falsification runner intentionally exercises real files below a fresh
    platform temporary directory.  That host-specific prefix is useful while
    the process is running, but it must not enter the checked-in result fixture
    or a source distribution.
    """

    prefixes = sorted({str(tmp_root), str(tmp_root.resolve())}, key=len, reverse=True)

    def sanitize(node):
        if isinstance(node, str):
            for prefix in prefixes:
                node = node.replace(prefix, PERSISTED_TMP_ROOT)
            return node
        if isinstance(node, dict):
            return {key: sanitize(value) for key, value in node.items()}
        if isinstance(node, list):
            return [sanitize(value) for value in node]
        return node

    return sanitize(results)


def fail_if(cond: bool, **kwargs) -> None:
    kwargs["verdict"] = "FAIL" if cond else "PASS"
    record(**kwargs)


def drop_volatile_origin(report: dict) -> dict:
    keep = copy.deepcopy(report)
    for path in (
        ["provenance", "analyzed_at"],
        ["provenance", "tool_version"],
        ["provenance", "definition_version"],
        ["provenance", "activity_definition_version"],
        ["provenance", "origin_definition_version"],
    ):
        node = keep
        for key in path[:-1]:
            node = node.get(key) or {}
        if path[-1] in node:
            node.pop(path[-1], None)
    return keep


def p0_legacy(tmp: Path) -> None:
    repo = alice_bob(tmp / "legacy")
    old = run_cli(["analyze", str(repo), "--format", "json"], cwd=repo, src=V059 / "src")
    new = run_cli(["analyze", str(repo), "--format", "json"], cwd=repo)
    fail_if(
        old.returncode != 0 or new.returncode != 0,
        name="P0-legacy-analyze-exit",
        hypothesis="v0.6 analyze は v0.5.9 と同じ exit 0 で動く",
        counter="analyze が非ゼロになる",
        fixture=str(repo),
        command="analyze PATH --format json (v059 vs v060)",
        expected="both exit 0",
        actual=f"v059={old.returncode} v060={new.returncode} err={new.stderr[:200]}",
        evidence="legacy analyze comparison",
    )
    old_j, new_j = parse_json(old.stdout), parse_json(new.stdout)
    fail_if(
        old_j.get("schema_version") != "report-v1" or new_j.get("schema_version") != "report-v1",
        name="P0-legacy-analyze-schema",
        hypothesis="analyze の schema は report-v1 のまま",
        counter="schema_version が変わる",
        fixture=str(repo),
        command="analyze PATH --format json",
        expected="report-v1 / report-v1",
        actual=f"{old_j.get('schema_version')} / {new_j.get('schema_version')}",
        evidence="schema_version field",
    )
    fail_if(
        old_j["provenance"]["analysis_scope"] != new_j["provenance"]["analysis_scope"],
        name="P0-legacy-explicit-path-tenant",
        hypothesis="明示パス analyze は tenant default のまま",
        counter="tenant と repo が混ざる",
        fixture=str(repo),
        command="analyze PATH --format json",
        expected="both tenant",
        actual=f"{old_j['provenance']['analysis_scope']} vs {new_j['provenance']['analysis_scope']}",
        evidence="analysis_scope",
    )
    origin_old = json.dumps(old_j["origin"], sort_keys=True)
    origin_new = json.dumps(new_j["origin"], sort_keys=True)
    fail_if(
        origin_old != origin_new,
        name="P0-legacy-origin-parity",
        hypothesis="origin 分類の数値は v0.5.9 と同じ",
        counter="既存 origin 数値が変わる",
        fixture=str(repo),
        command="analyze PATH --format json origin",
        expected="identical origin objects",
        actual="mismatch" if origin_old != origin_new else "match",
        evidence=f"old={origin_old[:180]} new={origin_new[:180]}",
    )
    act_old = json.dumps(old_j["activity"], sort_keys=True)
    act_new = json.dumps(new_j["activity"], sort_keys=True)
    fail_if(
        act_old != act_new,
        name="P0-legacy-activity-parity",
        hypothesis="activity 数値は v0.5.9 と同じ",
        counter="activity が変わる",
        fixture=str(repo),
        command="analyze PATH activity",
        expected="identical activity",
        actual="mismatch" if act_old != act_new else "match",
        evidence="activity block",
    )

    bare_old = run_cli(["analyze", "--format", "json"], cwd=repo, src=V059 / "src")
    bare_new = run_cli(["analyze", "--format", "json"], cwd=repo)
    fail_if(
        json.loads(bare_old.stdout)["provenance"]["analysis_scope"] != "repo"
        or json.loads(bare_new.stdout)["provenance"]["analysis_scope"] != "repo",
        name="P0-legacy-bare-repo-scope",
        hypothesis="裸 analyze は repo scope",
        counter="裸実行の scope が変わる",
        fixture=str(repo),
        command="analyze --format json (cwd=repo)",
        expected="repo / repo",
        actual=(
            f"{json.loads(bare_old.stdout)['provenance']['analysis_scope']} / "
            f"{json.loads(bare_new.stdout)['provenance']['analysis_scope']}"
        ),
        evidence="bare analyze",
    )

    exp = tmp / "legacy-export"
    e_old = run_cli(
        ["analyze", "--format", "json", "--export", str(exp / "old")], cwd=repo, src=V059 / "src"
    )
    e_new = run_cli(["analyze", "--format", "json", "--export", str(exp / "new")], cwd=repo)
    meta_old = json.loads((exp / "old" / "export-meta.json").read_text())
    meta_new = json.loads((exp / "new" / "export-meta.json").read_text())
    nd_old = (exp / "old" / "commits.ndjson").read_text()
    nd_new = (exp / "new" / "commits.ndjson").read_text()
    # v0.5.9 wrote analysis_scope="None" when --scope was omitted (bug).
    # v0.6 writes the resolved scope. Per-commit rows must stay identical.
    fail_if(
        e_old.returncode != 0
        or e_new.returncode != 0
        or meta_new.get("analysis_scope") != "repo"
        or nd_old != nd_new,
        name="P0-legacy-export-v1",
        hypothesis="export-v1 の per-commit 行は不変。省略 --scope は解決後 repo であり None ではない",
        counter="export 数値が変わる / 新実装が None を書く",
        fixture=str(repo),
        command="analyze --export DIR (bare, resolved repo scope)",
        expected="ndjson identical; new analysis_scope=repo (v059 None は既知バグ)",
        actual=(
            f"scope old={meta_old.get('analysis_scope')!r} new={meta_new.get('analysis_scope')!r} "
            f"ndjson_equal={nd_old == nd_new} rc={e_old.returncode}/{e_new.returncode}"
        ),
        evidence="export-meta + commits.ndjson",
    )
    fail_if(
        "@" in nd_new or "@" in (exp / "new" / "actors.json").read_text(),
        name="P0-legacy-export-no-email",
        hypothesis="export に raw email は出ない",
        counter="export に @ が混入",
        fixture=str(repo),
        command="analyze --export",
        expected="no @",
        actual="email leak" if "@" in nd_new else "clean",
        evidence="commits.ndjson/actors.json",
    )

    # report records .grift; repo command must not overwrite it
    shutil.rmtree(repo / ".grift", ignore_errors=True)
    rep = run_cli(["report"], cwd=repo)
    marker = (repo / ".grift" / "report.json").read_text()
    repo_cmd = run_cli(["repo", ".", "--format", "json"], cwd=repo)
    after = (repo / ".grift" / "report.json").read_text()
    fail_if(
        rep.returncode != 0
        or '"schema_version": "report-v1"' not in marker
        or after != marker
        or repo_cmd.returncode != 0
        or '"schema_version": "report-v2"' not in repo_cmd.stdout,
        name="P0-legacy-grift-not-overwritten",
        hypothesis="grift repo は .grift/report.json を上書きしない",
        counter=".grift/report.json が report-v2 で上書きされる",
        fixture=str(repo),
        command="report ; repo . --format json",
        expected="report-v1 file unchanged, stdout report-v2",
        actual=(
            f"report_rc={rep.returncode} repo_rc={repo_cmd.returncode} "
            f"file_unchanged={after == marker} file_schema_v1={'report-v1' in after}"
        ),
        evidence=".grift/report.json vs stdout",
    )

    v2_path = tmp / "actor.json"
    actor = run_cli(
        ["actor", "alice", str(repo), "--format", "json", "--out", str(v2_path)],
        cwd=repo,
    )
    contrib = run_cli(["contribute", str(v2_path), "--yes"], cwd=repo)
    fail_if(
        actor.returncode != 0 or contrib.returncode == 0,
        name="P0-legacy-contribute-rejects-v2",
        hypothesis="contribute は report-v2 actor を拒否し repo-v2 masked は受け入れる",
        counter="actor report から payload が作られる",
        fixture=str(repo),
        command="actor alice --out FILE; contribute FILE --yes",
        expected="contribute exit 2",
        actual=f"actor={actor.returncode} contribute={contrib.returncode} err={contrib.stderr[:180]}",
        evidence="contribute stderr",
    )


def p0_separation(tmp: Path) -> None:
    repo = alice_bob(tmp / "sep")
    project = tmp / "sep" / "project.toml"
    project.write_text(
        """schema_version = "tep-project-v1"
project_id = "checkout-api"
title = "Checkout API"
[requirements.surfaces]
required = ["backend"]
[requirements.inputs]
required = ["git"]
""",
        encoding="utf-8",
    )
    r = run_cli(["repo", str(repo), "--format", "json"], cwd=repo)
    a = run_cli(["actor", "alice", str(repo), "--format", "json"], cwd=repo)
    p = run_cli(["project", str(repo), "--format", "json"], cwd=repo)
    g = run_cli(
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--actor",
            "alice",
            "--project",
            str(project),
            "--format",
            "json",
        ],
        cwd=repo,
    )
    rj, aj, pj, gj = map(parse_json, (r.stdout, a.stdout, p.stdout, g.stdout))
    fail_if(
        any(c.returncode != 0 for c in (r, a, p, g)),
        name="P0-separation-exit",
        hypothesis="4 subject command がそれぞれ成功する",
        counter="どれかが失敗し出力が混ざる/欠ける",
        fixture=str(repo),
        command="repo / actor alice / project / align",
        expected="all exit 0",
        actual=f"{r.returncode},{a.returncode},{p.returncode},{g.returncode} {a.stderr[:120]}",
        evidence="return codes",
    )
    fail_if(
        rj.get("schema_version") != "report-v2"
        or rj.get("subject", {}).get("kind") != "repo"
        or rj["provenance"]["analysis_scope"] != "repo"
        or "canonical_id" in (rj.get("subject") or {}),
        name="P0-separation-repo-schema",
        hypothesis="repo 出力は report-v2 subject=repo で個人IDを持たない",
        counter="repo に actor が混ざる",
        fixture=str(repo),
        command="repo --format json",
        expected="report-v2 / repo / no canonical_id",
        actual=str(rj.get("subject")),
        evidence="subject block",
    )
    fail_if(
        aj.get("subject", {}).get("kind") != "actor"
        or aj.get("subject", {}).get("canonical_id") != "alice"
        or aj["provenance"]["analysis_scope"] != "tenant"
        or "bob" in json.dumps(aj),
        name="P0-separation-actor-schema",
        hypothesis="actor は alice のみで bob を含まない",
        counter="actor report に bob が入る",
        fixture=str(repo),
        command="actor alice --format json",
        expected="kind=actor canonical_id=alice no bob",
        actual=f"{aj.get('subject')} bob_in={('bob' in json.dumps(aj))}",
        evidence="actor json",
    )
    # repo v2 surface must include Bob's backend file even though identity has both
    repo_counts = ((rj.get("surface_profile") or {}).get("surface_commit_counts") or {}).get(
        "values"
    ) or {}
    actor_counts = ((aj.get("surface_profile") or {}).get("surface_commit_counts") or {}).get(
        "values"
    ) or {}
    fail_if(
        repo_counts.get("backend", 0) <= actor_counts.get("backend", 0)
        and extra_bob_present(rj, aj),
        name="P0-separation-repo-not-identity-filtered",
        hypothesis="repo の v2 surface は identity で個人に絞られない",
        counter="repo全体の数字に個人 identity が影響して Bob が消える",
        fixture=str(repo),
        command="repo vs actor alice surface_commit_counts.backend",
        expected="repo backend count > actor alice backend count",
        actual=f"repo={repo_counts.get('backend')} actor={actor_counts.get('backend')}",
        evidence="surface_commit_counts",
    )
    fail_if(
        pj.get("schema_version") != "project-v1"
        or pj.get("report_kind") != "project"
        or "alice" in json.dumps(pj.get("declared") or {}),
        name="P0-separation-project",
        hypothesis="project は宣言/運用署名であり actor 要求を推測しない",
        counter="project が observed に identity 要求を混ぜる",
        fixture=str(repo),
        command="project REPO --format json",
        expected="project-v1, no actor id in declared",
        actual=f"{pj.get('schema_version')} {pj.get('report_kind')}",
        evidence="project json",
    )
    fail_if(
        gj.get("schema_version") != "alignment-v1" or "axes" not in gj or "overall" in gj,
        name="P0-separation-align",
        hypothesis="align は alignment-v1 の軸配列のみ",
        counter="align が repo/actor schema や overall を出す",
        fixture=str(repo),
        command="align --format json",
        expected="alignment-v1 axes, no overall",
        actual=f"{gj.get('schema_version')} keys={sorted(gj)[:12]}",
        evidence="alignment json",
    )


def extra_bob_present(repo_j: dict, actor_j: dict) -> bool:
    return True


def p0_actor_mix(tmp: Path) -> None:
    repo = alice_bob(tmp / "mix")
    out = run_cli(["actor", "alice", str(repo), "--format", "json"], cwd=repo)
    payload = parse_json(out.stdout) if out.returncode == 0 else {}
    blob = out.stdout + out.stderr
    fail_if(
        out.returncode != 0
        or "BOBONLY" in blob
        or "bob@example.com" in blob
        or payload.get("identity", {}).get("actor_count") != 1
        or payload.get("subject", {}).get("canonical_id") != "alice",
        name="P0-actor-no-bob",
        hypothesis="alice の明示メールだけが対象で Bob の commit は 0 件",
        counter="Bob のファイル/メール/canonical_id が混ざる",
        fixture=str(repo),
        command="actor alice --format json",
        expected="actor_count=1, no BOBONLY, no bob@",
        actual=(
            f"rc={out.returncode} actor_count={payload.get('identity', {}).get('actor_count')} "
            f"bobonly={'BOBONLY' in blob} email={'bob@example.com' in blob}"
        ),
        evidence="stdout/stderr scan",
    )
    ident = tmp / "mix" / "pattern.toml"
    identity(ident, ALICE, patterns='"@example\\\\.com$"')
    patterned = run_cli(
        ["actor", "alice", str(repo), "--identity", str(ident), "--format", "json"],
        cwd=repo,
    )
    fail_if(
        patterned.returncode != 2 or "email_patterns" not in patterned.stderr,
        name="P0-actor-no-pattern-guess",
        hypothesis="email_patterns は一人へ配分せず exit 2",
        counter="pattern を Alice に推測割当する",
        fixture=str(ident),
        command="actor alice --identity pattern.toml",
        expected="exit 2, email_patterns in stderr, no raw email",
        actual=f"rc={patterned.returncode} err={patterned.stderr[:200]}",
        evidence="stderr",
    )
    fail_if(
        "alice@example.com" in patterned.stderr or "bob@example.com" in patterned.stderr,
        name="P0-actor-error-no-raw-email",
        hypothesis="identity エラーに raw email を出さない",
        counter="stderr にメールが出る",
        fixture=str(ident),
        command="actor alice --identity pattern.toml",
        expected="no @email in stderr",
        actual=patterned.stderr[:240],
        evidence="stderr",
    )


def p0_consent(tmp: Path) -> None:
    repo = alice_bob(tmp / "consent")
    help_out = run_cli(["actor", "--help"], cwd=repo)
    admin = run_cli(["actor", "alice", str(repo), "--format", "both"], cwd=repo)
    claimed = run_cli(["actor", "bob", str(repo), "--format", "both"], cwd=repo)

    public_repo = init_repo(tmp / "consent-public" / "repo")
    commit(
        public_repo,
        email="public@example.com",
        date="2026-08-01",
        message="feat: public actor cluster",
        filename="app.py",
        name="Public Alias",
    )
    public_repo_report = run_cli(["repo", str(public_repo), "--format", "json"], cwd=public_repo)
    public_actor_id = None
    if public_repo_report.returncode == 0:
        actors = (parse_json(public_repo_report.stdout).get("actor_directory") or {}).get(
            "actors"
        ) or []
        if len(actors) == 1:
            public_actor_id = actors[0].get("actor_id")
    public = run_cli(
        [
            "actor",
            public_actor_id or "missing-public-actor",
            str(public_repo),
            "--format",
            "both",
        ],
        cwd=public_repo,
    )

    outputs = (admin, claimed, public)
    blob = help_out.stdout + "".join(out.stdout + out.stderr for out in outputs)
    # JSON may follow Markdown in `--format both` output.
    payloads = []
    for output in outputs:
        if output.returncode != 0:
            continue
        idx = output.stdout.rfind("\n{")
        payloads.append(
            json.loads(
                output.stdout[idx + 1 :] if idx >= 0 else output.stdout[output.stdout.find("{") :]
            )
        )
    banned = [w for w in ("ランキング", "比較表", "採用推奨") if w in blob]
    verdict_claim = "合否" in blob and "ではありません" not in blob
    export = run_cli(
        ["actor", "alice", str(repo), "--export", str(tmp / "consent" / "ex")],
        cwd=repo,
    )
    admin_blob = admin.stdout + admin.stderr
    claimed_blob = claimed.stdout + claimed.stderr
    public_blob = public.stdout + public.stderr
    admin_basis = (
        "管理対象リポジトリ" in admin_blob
        and "attribution_state=verified" in admin_blob
        and "本人向け証拠ビューとは呼びません" in admin_blob
    )
    claimed_basis = (
        "attribution_state=claimed" in claimed_blob
        and "本人向けactor観測" in claimed_blob
        and "申告者" in claimed_blob
        and "本人性を証明しません" in claimed_blob
    )
    public_basis = (
        "公開 Git / 公開 Forge の観測" in public_blob
        and "公開Git上のactor cluster観測" in public_blob
        and "実在人物との同一性は証明していません" in public_blob
    )
    fail_if(
        not admin_basis
        or not claimed_basis
        or not public_basis
        or banned
        or verdict_claim
        or help_out.returncode != 0
        or any(output.returncode != 0 for output in outputs)
        or export.returncode != 2
        or any(any(key in payload for key in ("score", "rank", "overall")) for payload in payloads),
        name="P0-actor-not-profiling",
        hypothesis=(
            "admin/claimed/public actor の表示根拠を分離し、"
            "複数人比較・ランキング・export・合否を出さない"
        ),
        counter=(
            "表示根拠が混ざる、比較表/ランキング/export/合否が出る、またはいずれかのactor注意が無い"
        ),
        fixture=f"explicit={repo}; public={public_repo}",
        command=(
            "actor --help; actor alice/bob --format both; "
            "identity-less actor ID --format both; actor --export"
        ),
        expected=(
            "verified=admin notice; claimed=self-claimed notice; "
            "identity-less=public cluster notice; export exit 2; no verdict keys"
        ),
        actual=(
            f"admin_basis={admin_basis} claimed_basis={claimed_basis} "
            f"public_basis={public_basis} banned={banned} "
            f"actor_rc={[output.returncode for output in outputs]} "
            f"export_rc={export.returncode} help_rc={help_out.returncode}"
        ),
        evidence="basis-separated help/stderr/markdown/json/export",
    )


def p0_not_observed(tmp: Path) -> None:
    cases = []
    # identity missing
    repo = init_repo(tmp / "noid" / "repo")
    commit(repo, email="x@example.com", date="2026-08-01", message="feat", filename="app.py")
    r = run_cli(["actor", "alice", str(repo), "--format", "json"], cwd=repo)
    cases.append(("identityなし", r, r.returncode == 2))
    # actor no commits
    repo2 = alice_bob(tmp / "nocommits", extra_bob=True)
    identity(repo2 / ".tep" / "identity.toml", ALICE + "\n" + BOB)
    commit(  # charlie only extra already bob/alice present; use unused id
        repo2,
        email="carol@example.com",
        date="2026-08-03",
        message="feat carol",
        filename="src/api/carol.py",
        name="Carol",
    )
    identity(
        repo2 / ".tep" / "identity.toml",
        ALICE
        + "\n"
        + BOB
        + '\n[[actors]]\ncanonical_id = "carol"\nemails = ["carol@example.com"]\nattribution_state = "verified"\n',
    )
    # Use an actor with zero commits
    identity(
        repo2 / ".tep" / "empty-actor.toml",
        ALICE
        + '\n[[actors]]\ncanonical_id = "empty"\nemails = ["empty@example.com"]\nattribution_state = "verified"\n',
    )
    r2 = run_cli(
        [
            "actor",
            "empty",
            str(repo2),
            "--identity",
            str(repo2 / ".tep" / "empty-actor.toml"),
            "--format",
            "json",
        ],
        cwd=repo2,
    )
    j2 = parse_json(r2.stdout) if r2.returncode == 0 else {}
    rhythm = j2.get("change_rhythm") or {}
    cases.append(
        (
            "actorのcommitなし",
            r2,
            r2.returncode == 0
            and rhythm.get("kind") == "not_observed"
            and rhythm.get("reason") == "no_actor_commits",
        )
    )
    # no test framework
    repo3 = init_repo(tmp / "notest" / "repo")
    stage_fixed_identity(repo3, ALICE)
    commit(repo3, email="alice@example.com", date="2026-08-01", message="feat", filename="app.py")
    r3 = run_cli(["actor", "alice", str(repo3), "--format", "json"], cwd=repo3)
    j3 = parse_json(r3.stdout) if r3.returncode == 0 else {}
    vf = j3.get("verification_profile") or {}
    cases.append(
        (
            "test frameworkなし",
            r3,
            vf.get("kind") == "not_observed"
            and vf.get("reason") == "no_test_framework_or_directory",
        )
    )
    # no forge/tracker
    repo4 = alice_bob(tmp / "noforge")
    r4 = run_cli(["actor", "alice", str(repo4), "--format", "json"], cwd=repo4)
    j4 = parse_json(r4.stdout) if r4.returncode == 0 else {}
    coord = j4.get("coordination_profile") or {}
    cases.append(
        (
            "forge/trackerなし",
            r4,
            (coord.get("review") or {}).get("reason") == "forge_export_not_provided"
            and (coord.get("tracker") or {}).get("reason") == "tracker_export_not_provided",
        )
    )
    # insufficient population
    repo5 = init_repo(tmp / "small" / "repo")
    (repo5 / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n', encoding="utf-8")
    (repo5 / "tests").mkdir()
    (repo5 / "tests" / "t.py").write_text("def test_o():\n pass\n", encoding="utf-8")
    stage_fixed_identity(repo5, ALICE)
    for i in range(3):
        commit(
            repo5, email="alice@example.com", date="2026-08-01", message=f"f{i}", filename="app.py"
        )
    r5 = run_cli(["actor", "alice", str(repo5), "--format", "json"], cwd=repo5)
    j5 = parse_json(r5.stdout) if r5.returncode == 0 else {}
    med = (j5.get("change_rhythm") or {}).get("median_gap_days") or {}
    cases.append(
        (
            "commit数不足",
            r5,
            med.get("kind") == "not_observed" and med.get("reason") == "insufficient_population",
        )
    )
    bad_words = [
        w
        for w in ("能力不足", "未経験", "弱い")
        if any(w in (c.stdout + c.stderr) for _, c, _ in cases)
    ]
    zeros_as_skill = False
    all_ok = all(ok for _, _, ok in cases) and not bad_words and not zeros_as_skill
    fail_if(
        not all_ok,
        name="P0-not-observed-not-absence",
        hypothesis="入力不足・履歴なしは理由付き not_observed であり能力否定ではない",
        counter="0 / 弱い / 未経験 / 能力不足 と表示される",
        fixture="noid, empty actor, notest, noforge, small",
        command="actor variants",
        expected="not_observed + reason, no skill language",
        actual=str(
            [
                (
                    n,
                    ok,
                    (
                        c.returncode,
                        (
                            parse_json(c.stdout)
                            if c.returncode == 0 and c.stdout.strip().startswith("{")
                            else None
                        ),
                    ),
                )
                for n, c, ok in cases
            ]
        )[:500],
        evidence="per-case kinds/reasons",
    )
    # private history: documented limitation on actor view
    md = run_cli(["actor", "alice", str(repo4), "--format", "md"], cwd=repo4)
    fail_if(
        "実績がないことを意味しません" not in md.stdout and "未観測" not in md.stdout,
        name="P0-not-observed-private-history-copy",
        hypothesis="private history / 未観測は実績なしと読ませない文がある",
        counter="説明がなく 0 に読める",
        fixture=str(repo4),
        command="actor alice --format md",
        expected="未観測は実績がないことを意味しません",
        actual=md.stdout[md.stdout.find("言えること") : md.stdout.find("言えること") + 200]
        if "言えること" in md.stdout
        else md.stdout[:200],
        evidence="markdown 言えること/言えないこと",
    )


def p0_determinism(tmp: Path) -> None:
    repo = alice_bob(tmp / "det")
    git(repo, "remote", "add", "origin", "https://github.com/acme/determinism.git")
    target_oid = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    forge = tmp / "det" / "forge.json"
    forge.write_text(
        json.dumps(
            {
                "schema_version": "tep-forge-export-v2",
                "binding": {
                    "provider": "github",
                    "host": "github.com",
                    "project_id": "R_determinism",
                    "project_path": "acme/determinism",
                    "target_oid": {"algorithm": "sha1", "value": target_oid},
                    "window": {
                        "start": "2026-08-01T00:00:00Z",
                        "end": "2026-09-01T00:00:00Z",
                    },
                    "coverage": {
                        "status": "complete",
                        "observed": 2,
                        "expected": 2,
                        "missing": 0,
                        "unit": "events",
                    },
                },
                "events": [
                    {
                        "event_id": "b",
                        "kind": "pull_request_review",
                        "timestamp": "2026-08-02T00:00:00Z",
                        "actor_canonical_id": "alice",
                        "pr_number": 2,
                        "commit_sha": target_oid,
                        "project_id": "R_determinism",
                        "project_path": "acme/determinism",
                    },
                    {
                        "event_id": "a",
                        "kind": "pull_request_review",
                        "timestamp": "2026-08-01T00:00:00Z",
                        "actor_canonical_id": "alice",
                        "pr_number": 1,
                        "commit_sha": target_oid,
                        "project_id": "R_determinism",
                        "project_path": "acme/determinism",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    args = [
        "actor",
        "alice",
        str(repo),
        "--format",
        "json",
        "--as-of",
        "2026-08-29",
        "--forge-export",
        str(forge),
    ]
    a = run_cli(args, cwd=repo)
    b = run_cli(args, cwd=repo)
    ja, jb = parse_json(a.stdout), parse_json(b.stdout)
    ja["provenance"].pop("analyzed_at", None)
    jb["provenance"].pop("analyzed_at", None)
    fail_if(
        a.returncode != 0 or b.returncode != 0 or ja != jb,
        name="P0-determinism-as-of",
        hypothesis="同一 SHA/identity/export/as-of なら analyzed_at 以外は一致",
        counter="実行時刻や並びで観測値が変わる",
        fixture=str(repo),
        command="actor alice --as-of 2026-08-29 --forge-export FILE x2",
        expected="equal after dropping analyzed_at",
        actual=f"equal={ja == jb} rc={a.returncode}/{b.returncode}",
        evidence="json diff excluding analyzed_at",
    )
    # event order already in file unsorted; sorted internally
    rev = json.loads(forge.read_text())
    rev["events"] = list(reversed(rev["events"]))
    forge2 = tmp / "det" / "forge2.json"
    forge2.write_text(json.dumps(rev), encoding="utf-8")
    c = run_cli(
        [
            "actor",
            "alice",
            str(repo),
            "--format",
            "json",
            "--as-of",
            "2026-08-29",
            "--forge-export",
            str(forge2),
        ],
        cwd=repo,
    )
    jc = parse_json(c.stdout)
    jc["provenance"].pop("analyzed_at", None)
    ja2 = copy.deepcopy(ja)
    ja2["provenance"].get("input_digests", {}).pop("forge", None)
    jc["provenance"].get("input_digests", {}).pop("forge", None)
    fail_if(
        (jc.get("coordination_profile") or {}).get("review")
        != (ja.get("coordination_profile") or {}).get("review"),
        name="P1-forge-order-stable",
        hypothesis="forge event の入力順を変えても review 集計は同じ",
        counter="入力順で結果が変わる",
        fixture=str(forge2),
        command="actor --forge-export reversed",
        expected="same review block",
        actual="mismatch"
        if (jc.get("coordination_profile") or {}).get("review")
        != (ja.get("coordination_profile") or {}).get("review")
        else "match",
        evidence="coordination.review",
    )


def p0_rhythm(tmp: Path) -> None:
    split = init_repo(tmp / "rhythm-split")
    stage_fixed_identity(split, ALICE)
    for i in range(10):
        commit(
            split,
            email="alice@example.com",
            date=f"2026-08-{i + 1:02d}",
            message=f"feat {i}",
            filename="app.py",
        )
    squash = init_repo(tmp / "rhythm-squash")
    stage_fixed_identity(squash, ALICE)
    commit(
        squash,
        email="alice@example.com",
        date="2026-08-10",
        message="feat all",
        filename="app.py",
        content="x" * 10,
    )
    botm = init_repo(tmp / "rhythm-bot")
    stage_fixed_identity(botm, ALICE)
    commit(botm, email="alice@example.com", date="2026-08-01", message="feat", filename="app.py")
    commit(
        botm,
        email="bot[bot]@users.noreply.github.com",
        date="2026-08-02",
        message="chore",
        filename="app.py",
    )
    tz = init_repo(tmp / "rhythm-tz")
    stage_fixed_identity(tz, ALICE)
    commit(
        tz,
        email="alice@example.com",
        date="2026-08-01",
        message="feat tz",
        filename="app.py",
        time="12:00:00+09:00",
    )
    rs = run_cli(
        ["actor", "alice", str(split), "--format", "json", "--as-of", "2026-08-29"], cwd=split
    )
    rq = run_cli(
        ["actor", "alice", str(squash), "--format", "json", "--as-of", "2026-08-29"], cwd=squash
    )
    rb = run_cli(
        ["actor", "alice", str(botm), "--format", "json", "--as-of", "2026-08-29"], cwd=botm
    )
    js, jq = parse_json(rs.stdout), parse_json(rq.stdout)
    split_n = (js.get("change_rhythm") or {}).get("sample_size")
    squash_n = (jq.get("change_rhythm") or {}).get("sample_size")
    md = run_cli(["actor", "alice", str(split), "--format", "md"], cwd=split)
    blob = md.stdout + json.dumps(js)
    claims_labor = "労働時間" in blob and "測るものではありません" not in blob
    fail_if(
        split_n == squash_n
        or claims_labor
        or ("git_author_timestamp" not in blob and "変更提出" not in blob),
        name="P0-rhythm-not-work-speed",
        hypothesis="rhythm は Git author timestamp の提出間隔であり、squash で値が変わる",
        counter="10 commit と squash が同じ『速さ』として出る / 労働時間と呼ぶ",
        fixture="split vs squash vs bot",
        command="actor alice --format json/md",
        expected="sample_size differs; disclaimer present; not labor time",
        actual=f"split_n={split_n} squash_n={squash_n} disclaimer={'測るものではありません' in blob}",
        evidence="change_rhythm sample_size + markdown",
    )
    jb = parse_json(rb.stdout)
    fail_if(
        (jb.get("change_rhythm") or {}).get("sample_size") != 1,
        name="P0-rhythm-excludes-bot",
        hypothesis="bot commit は rhythm 母集団に入らない",
        counter="bot を人の速さとして数える",
        fixture=str(botm),
        command="actor alice bot-repo",
        expected="sample_size=1",
        actual=str((jb.get("change_rhythm") or {}).get("sample_size")),
        evidence="change_rhythm.sample_size",
    )


def p0_surface_and_lens(tmp: Path) -> None:
    from tep_core.path_surface import classify_surface, surface_flags

    cases = {
        "src/api/app.py": "backend",
        "src/components/Button.tsx": "frontend",
        "terraform/main.tf": "platform",
        "terraform/main.py": "platform",
        "tests/test_app.py": "test",
        "src/components/Button.test.tsx": "test",
        "migrations/001.sql": "data",
        "random.bin": "other",
    }
    wrong = {p: classify_surface(p) for p, exp in cases.items() if classify_surface(p) != exp}
    amb = surface_flags("src/components/Button.test.tsx")
    repo = init_repo(tmp / "surf")
    stage_fixed_identity(repo, ALICE)
    commit(
        repo,
        email="alice@example.com",
        date="2026-08-01",
        message="tf",
        filename="terraform/main.tf",
    )
    commit(
        repo, email="alice@example.com", date="2026-08-01", message="py", filename="src/api/app.py"
    )
    commit(
        repo,
        email="alice@example.com",
        date="2026-08-01",
        message="test",
        filename="tests/test_app.py",
    )
    (repo / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n', encoding="utf-8")
    md = run_cli(
        ["actor", "alice", str(repo), "--role-lens", "backend", "--format", "md"], cwd=repo
    )
    js = run_cli(
        ["actor", "alice", str(repo), "--role-lens", "backend", "--format", "json"], cwd=repo
    )
    payload = parse_json(js.stdout) if js.returncode == 0 else {}
    lens = payload.get("role_lens") or {}
    blob = md.stdout + js.stdout
    fail_if(
        bool(wrong) or amb[0] != "test" or not amb[1],
        name="P0-surface-heuristic-not-job",
        hypothesis="surface は path/拡張子ヒューリスティックで職種断定しない",
        counter="Terraform を backend にする / test-only を見落とす / 根拠なし",
        fixture="path_surface cases",
        command="classify_surface + actor --role-lens backend",
        expected="tf=platform, test wins over frontend, ambiguous=true",
        actual=f"wrong={wrong} amb={amb}",
        evidence="path_surface",
    )
    fail_if(
        lens.get("classifies_role") is True
        or any(
            w in blob
            for w in (
                "backend適性",
                "85点",
                "QA向き",
                "PMとして不十分",
                "full-stack engineerと判定",
            )
        )
        or "display_preset" != lens.get("kind"),
        name="P0-role-lens-not-classifier",
        hypothesis="role-lens は表示プリセットであり職種分類器ではない",
        counter="backend適性 85点 / QA向き / 判定が出る",
        fixture=str(repo),
        command="actor --role-lens backend --format both",
        expected="classifies_role=false, kind=display_preset, no aptitude language",
        actual=f"lens={lens} banned={[w for w in ('適性', '85点', 'QA向き', '不十分', 'と判定') if w in blob]}",
        evidence="role_lens + markdown",
    )


def p0_project_align(tmp: Path) -> None:
    dest = tmp / "proj" / "p.toml"
    dest.parent.mkdir(parents=True)
    init = run_cli(["project", "--init", "--out", str(dest)], cwd=tmp)
    text = dest.read_text(encoding="utf-8") if dest.exists() else ""
    assigned = [
        line
        for line in text.splitlines()
        if not line.strip().startswith("#")
        and any(k in line and "=" in line for k in ("active_days", 'required = ["', "name ="))
        and "required = []" not in line
        and 'project_id = ""' not in line
        and 'title = ""' not in line
        and "schema_version" not in line
    ]
    req = run_cli(["project", "--requirements", str(dest), "--format", "json"], cwd=tmp)
    payload = parse_json(req.stdout) if req.returncode == 0 else {}
    fail_if(
        init.returncode != 0
        or assigned
        or "高速" in text
        or "人材" in text
        or payload.get("declared", {})
        .get("change_rhythm", {})
        .get("active_days_180d_min", {})
        .get("kind")
        != "not_declared",
        name="P0-project-no-guess",
        hypothesis="--init は空 template で要求を推測しない",
        counter="高速開発向き / backend人材が必要 などを埋める",
        fixture=str(dest),
        command="project --init --out FILE; project --requirements FILE",
        expected="empty required=[], not_declared rhythm",
        actual=f"assigned={assigned} kind={payload.get('declared', {}).get('change_rhythm')}",
        evidence="template + declared json",
    )
    repo = alice_bob(tmp / "al")
    project = tmp / "al" / "req.toml"
    project.write_text(
        """schema_version = "tep-project-v1"
project_id = "checkout-api"
[requirements.change_rhythm]
active_days_180d_min = 1
[requirements.surfaces]
required = ["backend"]
[requirements.inputs]
required = ["git", "tracker"]
""",
        encoding="utf-8",
    )
    al = run_cli(
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--actor",
            "alice",
            "--project",
            str(project),
            "--format",
            "json",
        ],
        cwd=repo,
    )
    al_md = run_cli(
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--actor",
            "alice",
            "--project",
            str(project),
            "--format",
            "md",
        ],
        cwd=repo,
    )
    blob = al.stdout + al.stderr + al_md.stdout
    js = parse_json(al.stdout) if al.returncode == 0 else {}
    hits = [k for k in VERDICT if k in blob and k not in ("pass", "fail")]
    # pass/fail as JSON keys
    key_hits = [k for k in ("overall", "score", "rank", "fit", "recommendation", "hire") if k in js]
    comparisons = {ax.get("comparison") for ax in js.get("axes") or []}
    fail_if(
        al.returncode != 0
        or key_hits
        or "axes" not in js
        or not comparisons
        <= set(
            {"overlap", "outside_declared_range", "observed_zero", "not_observed", "not_declared"}
        ),
        name="P0-alignment-no-overall",
        hypothesis="alignment は軸比較のみで総合点を持たない",
        counter="overall/score/rank/fit/recommendation が出る",
        fixture=str(project),
        command="align --format json + md",
        expected="axes only, comparisons in enum",
        actual=(f"rc={al.returncode} keys={key_hits} copy_hits={hits} comparisons={comparisons}"),
        evidence="alignment json/md",
    )
    # git-only no PM/review
    repo2 = alice_bob(tmp / "gitonly")
    g = run_cli(["actor", "alice", str(repo2), "--role-lens", "pm", "--format", "json"], cwd=repo2)
    gmd = run_cli(["actor", "alice", str(repo2), "--role-lens", "pm", "--format", "md"], cwd=repo2)
    gb = g.stdout + g.stderr + gmd.stdout
    gj = parse_json(g.stdout) if g.returncode == 0 else {}
    review = (gj.get("coordination_profile") or {}).get("review") or {}
    fail_if(
        review.get("kind") != "not_observed"
        or any(
            w in gb
            for w in ("PM能力", "Tech Lead能力", "stakeholder", "PR review経験", "issue triage経験")
        )
        or "review" in gb.lower()
        and "観測できません" not in gb
        and review.get("reason") != "forge_export_not_provided",
        name="P0-git-only-no-pm-guess",
        hypothesis="forge/tracker なしで PM/review 経験を推測しない",
        counter="Git-only で PR review/PM 能力を表示する",
        fixture=str(repo2),
        command="actor alice --role-lens pm --format both",
        expected="review not_observed forge_export_not_provided",
        actual=f"review={review} rc={g.returncode}",
        evidence="coordination.review + markdown",
    )


def p0_pii(tmp: Path) -> None:
    repo = alice_bob(tmp / "pii")
    cmds = [
        ["actor", "missing", str(repo), "--format", "json"],
        ["actor", "alice", str(repo), "--format", "json"],
        ["repo", str(repo), "--format", "json"],
        ["project", str(repo), "--format", "json"],
    ]
    leaks = []
    for args in cmds:
        r = run_cli(args, cwd=repo)
        blob = r.stdout + r.stderr
        if EMAIL_RE.search(blob):
            leaks.append((args[0], "email"))
        if (
            any(w in blob.lower() for w in ("token", "cookie", "dsn", "secret"))
            and "token" in blob.lower()
            and "timestamp_basis" not in blob
        ):
            if re.search(r"\b(token|cookie|dsn)\b", blob, re.I):
                leaks.append((args[0], "secret-word"))
        if "/Users/" in blob and "--include-local-path" not in args:
            leaks.append((args[0], "abs-path"))
    unknown = run_cli(["actor", "missing", str(repo), "--format", "json"], cwd=repo)
    fail_if(
        bool(leaks) or "alice@example.com" in unknown.stderr,
        name="P0-pii-no-leak",
        hypothesis="stdout/stderr/json に raw email / secret / 絶対パス / 他人IDエラーメールを出さない",
        counter="identity エラーでメールを表示する",
        fixture=str(repo),
        command="actor missing; actor alice; repo; project",
        expected="no email regex, unknown actor lists ids without emails",
        actual=f"leaks={leaks} unknown_err={unknown.stderr[:200]}",
        evidence="blob scan",
    )


def p0_verify(tmp: Path) -> None:
    repo = alice_bob(tmp / "ver")
    out = tmp / "ver" / "out"
    r = run_cli(["repo", str(repo), "--format", "json", "--out", str(out)], cwd=repo)
    path = out / "report.json"
    ok = run_cli(["verify", str(path), "--repo", str(repo)], cwd=repo)
    payload = json.loads(path.read_text())
    tampered = copy.deepcopy(payload)
    if (tampered.get("activity") or {}).get("tenant_commits", {}).get("value") is not None:
        tampered["activity"]["tenant_commits"]["value"] = 99999
    else:
        tampered["surface_profile"]["unclassified_count"] = 99999
    tpath = tmp / "ver" / "tampered.json"
    tpath.write_text(json.dumps(tampered), encoding="utf-8")
    mismatch = run_cli(["verify", str(tpath), "--repo", str(repo)], cwd=repo)
    sha_t = copy.deepcopy(payload)
    sha_t["provenance"]["analyzed_commit_sha"] = "b" * 40
    spath = tmp / "ver" / "sha.json"
    spath.write_text(json.dumps(sha_t), encoding="utf-8")
    sha_r = run_cli(["verify", str(spath), "--repo", str(repo)], cwd=repo)
    digest_t = copy.deepcopy(payload)
    digest_t["provenance"]["input_digests"]["forge"] = "a" * 64
    dpath = tmp / "ver" / "digest.json"
    dpath.write_text(json.dumps(digest_t), encoding="utf-8")
    digest_r = run_cli(["verify", str(dpath), "--repo", str(repo)], cwd=repo)
    actor_json_path = tmp / "ver" / "actor-detail.json"
    run_cli(
        ["actor", "alice", str(repo), "--format", "json", "--out", str(actor_json_path)],
        cwd=repo,
    )
    ap = json.loads(actor_json_path.read_text())
    ap["subject"]["canonical_id"] = "bob"
    aidp = tmp / "ver" / "actor-id.json"
    aidp.write_text(json.dumps(ap), encoding="utf-8")
    actor_id_r = run_cli(
        [
            "verify",
            str(aidp),
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
        ],
        cwd=repo,
    )
    proj = tmp / "ver" / "p.toml"
    run_cli(["project", "--init", "--out", str(proj)], cwd=tmp)
    pjson_dir = tmp / "ver" / "pdir"
    run_cli(
        ["project", "--requirements", str(proj), "--format", "json", "--out", str(pjson_dir)],
        cwd=tmp,
    )
    p_verify = run_cli(["verify", str(pjson_dir / "project.json"), "--repo", str(repo)], cwd=repo)
    fail_if(
        r.returncode != 0
        or ok.returncode != 0
        or "VERIFIED" not in ok.stdout
        or mismatch.returncode != 1
        or "MISMATCH" not in mismatch.stdout
        or sha_r.returncode != 1
        or "MISMATCH" not in sha_r.stdout
        or digest_r.returncode != 1
        or "MISMATCH" not in digest_r.stdout
        or actor_id_r.returncode != 1
        or "MISMATCH" not in actor_id_r.stdout
        or p_verify.returncode != 2
        or "CANNOT_VERIFY" not in p_verify.stdout,
        name="P0-verify-tamper",
        hypothesis="数値改ざんは MISMATCH、再計算不能は CANNOT_VERIFY、正常は VERIFIED",
        counter="改ざんを検出できない / project を false-VERIFIED する",
        fixture=str(repo),
        command="verify original/tampered/sha/digest/actor-id/project",
        expected="VERIFIED; tamper MISMATCH(exit 1); project CANNOT_VERIFY(exit 2)",
        actual=(
            f"ok={ok.returncode}:{ok.stdout[:40]!r} mismatch={mismatch.returncode}:{mismatch.stdout[:40]!r} "
            f"sha={sha_r.returncode} digest={digest_r.returncode} actorid={actor_id_r.returncode} "
            f"project={p_verify.returncode}:{p_verify.stdout[:80]!r}"
        ),
        evidence="verify stdout",
    )


def p0_noneng(tmp: Path) -> None:
    repo = alice_bob(tmp / "read")
    project = tmp / "read" / "p.toml"
    project.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "checkout-api"\n[requirements.surfaces]\nrequired=["backend"]\n',
        encoding="utf-8",
    )
    repo_md = run_cli(["repo", str(repo), "--format", "md"], cwd=repo)
    act_md = run_cli(["actor", "alice", str(repo), "--format", "md"], cwd=repo)
    al_md = run_cli(
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--actor",
            "alice",
            "--project",
            str(project),
            "--format",
            "md",
        ],
        cwd=repo,
    )
    texts = repo_md.stdout + act_md.stdout + al_md.stdout
    needed = [
        "このレポートは誰・何を対象にしたか",
        "何を入力として見たか",
        "何を見ていないか",
        "観測された数値",
        "基準値・比較材料",
        "傾向",
        "傾向の強さと確からしさ",
        "比較不能・未観測・未証明",
        "言えること / 言えないこと",
        "再現情報",
        "優劣",
        "not_observed",
    ]
    missing = [n for n in needed if n not in texts]
    fail_if(
        repo_md.returncode != 0 or act_md.returncode != 0 or al_md.returncode != 0 or missing,
        name="P0-nonengineer-copy",
        hypothesis="非エンジニアが観測/未観測/分母/禁則/not_observed を読める",
        counter="説明節が無く数値だけが並ぶ",
        fixture=str(repo),
        command="repo/actor/align --format md",
        expected="固定10節のうち説明節が揃う",
        actual=f"missing={missing}",
        evidence="markdown headings",
    )


def p1_extras(tmp: Path) -> None:
    # project key order
    a = tmp / "p1" / "a.toml"
    b = tmp / "p1" / "b.toml"
    a.parent.mkdir(parents=True)
    a.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "checkout-api"\n[requirements.surfaces]\nrequired=["data","backend"]\n[requirements.inputs]\nrequired=["tracker","git"]\n',
        encoding="utf-8",
    )
    b.write_text(
        'schema_version = "tep-project-v1"\nproject_id = "checkout-api"\n[requirements.inputs]\nrequired=["git","tracker"]\n[requirements.surfaces]\nrequired=["backend","data"]\n',
        encoding="utf-8",
    )
    ja = parse_json(
        run_cli(["project", "--requirements", str(a), "--format", "json"], cwd=tmp).stdout
    )
    jb = parse_json(
        run_cli(["project", "--requirements", str(b), "--format", "json"], cwd=tmp).stdout
    )
    ja["provenance"].pop("analyzed_at", None)
    jb["provenance"].pop("analyzed_at", None)
    fail_if(
        ja["declared"]["surfaces"]["value"] != jb["declared"]["surfaces"]["value"]
        and set(ja["declared"]["surfaces"]["value"]) != set(jb["declared"]["surfaces"]["value"]),
        name="P1-project-key-order",
        hypothesis="TOML の入力順を変えても宣言集合は同じ",
        counter="配列順の差で意味が変わる（集合として不一致）",
        fixture=str(a),
        command="project --requirements A/B",
        expected="same required sets",
        actual=f"{ja['declared']['surfaces']} vs {jb['declared']['surfaces']}",
        evidence="declared.surfaces",
    )
    # suppression <20
    repo = init_repo(tmp / "p1small")
    stage_fixed_identity(repo, ALICE)
    for i in range(5):
        commit(
            repo, email="alice@example.com", date="2026-08-01", message=f"f{i}", filename="app.py"
        )
    j = parse_json(run_cli(["actor", "alice", str(repo), "--format", "json"], cwd=repo).stdout)
    fail_if(
        (j.get("change_rhythm") or {}).get("median_gap_days", {}).get("kind") != "not_observed",
        name="P1-suppression-under-20",
        hypothesis="20 commit 未満の率・分位は抑制される",
        counter="n<20 で median_gap が出る",
        fixture=str(repo),
        command="actor alice 5 commits",
        expected="median_gap_days not_observed insufficient_population",
        actual=str((j.get("change_rhythm") or {}).get("median_gap_days")),
        evidence="change_rhythm",
    )
    # pr_flow_share not called PR review in v2
    repo2 = alice_bob(tmp / "p1pr")
    md = run_cli(["repo", str(repo2), "--format", "md"], cwd=repo2)
    fail_if(
        "本物の PR review" in md.stdout or "pull-request review 比率" in md.stdout,
        name="P1-pr-flow-not-review",
        hypothesis="Git-only merge を本物の PR review 率と呼ばない",
        counter="pr_flow_share を review 率として説明する",
        fixture=str(repo2),
        command="repo --format md",
        expected="merge_commit であり PR review ではない",
        actual=("review mislabel" if "PR review 率" in md.stdout else "ok"),
        evidence="markdown coordination",
    )


def p0_followup(tmp: Path) -> None:
    from tep_core.path_surface import classify_surface, surface_flags
    from tep_core.schema_v2 import validate_project, validate_report_v2
    from tep_core.gitutil import GitCommit
    from tep_core.rhythm import change_rhythm

    fail_if(
        classify_surface("docs/api/overview.md") != "docs"
        or classify_surface("tests/components/Button.tsx") != "test"
        or classify_surface("terraform/main.py") != "platform"
        or not surface_flags("components/api.py")[1],
        name="P0-surface-precedence-conflicts",
        hypothesis="衝突 path は固定優先順位で、職種推定ではない",
        counter="docs/api を backend にする / test を frontend にする / terraform を backend にする",
        fixture="path_surface",
        command="classify_surface",
        expected="docs, test, platform, ambiguous components/api.py",
        actual=(
            f"{classify_surface('docs/api/overview.md')} "
            f"{classify_surface('tests/components/Button.tsx')} "
            f"{classify_surface('terraform/main.py')} "
            f"amb={surface_flags('components/api.py')}"
        ),
        evidence="path_surface",
    )
    repo = alice_bob(tmp / "follow")
    md = run_cli(
        ["actor", "alice", str(repo), "--role-lens", "backend", "--format", "md"],
        cwd=repo,
    )
    blob = md.stdout
    has_dict = "{'kind'" in blob
    has_job_note = "職種分類ではありません" in blob or "職種の確定ではありません" in blob
    fail_if(
        md.returncode != 0
        or has_dict
        or "表示プリセット: `backend`" not in blob
        or not has_job_note
        or blob.count("人の優劣") > 1,
        name="P0-readable-markdown",
        hypothesis="Markdown に raw dict がなく、lens と分母が読める",
        counter="raw dict が出る / lens 非表示 / 注意書きの重複",
        fixture=str(repo),
        command="actor alice --role-lens backend --format md",
        expected="preset line, no dict repr, disclaimer once",
        actual=f"rc={md.returncode} dict={has_dict} lens={'表示プリセット' in blob} disc={blob.count('人の優劣')}",
        evidence="markdown",
    )
    old = [
        GitCommit(
            f"o{i:039d}",
            "a@x",
            ("p",),
            "2025-01-02",
            "a",
            author_iso=f"2025-01-{(i % 27) + 1:02d}T12:00:00Z",
        )
        for i in range(25)
    ]
    new = [
        GitCommit(
            f"n{i:039d}",
            "a@x",
            ("p",),
            "2026-08-02",
            "a",
            author_iso=f"2026-08-{(i % 27) + 1:02d}T12:00:00Z",
        )
        for i in range(25)
    ]
    mixed = change_rhythm(old + new, observation_date="2026-08-29", empty_reason="x")
    only = change_rhythm(new, observation_date="2026-08-29", empty_reason="x")
    fail_if(
        mixed["median_gap_days"] != only["median_gap_days"]
        or mixed["history_outside_window_commit_count"]["value"] != 25,
        name="P0-rhythm-window-no-leak",
        hypothesis="180日窓の外の gap は窓内統計に混入しない",
        counter="古い25 commit の間隔が median を動かす",
        fixture="25 old + 25 new",
        command="change_rhythm mixed vs new",
        expected="same median, outside=25",
        actual=(
            f"outside={mixed['history_outside_window_commit_count']} "
            f"median_equal={mixed['median_gap_days'] == only['median_gap_days']}"
        ),
        evidence="rhythm window",
    )
    js = run_cli(["repo", str(repo), "--format", "json"], cwd=repo)
    payload = parse_json(js.stdout)
    hollow = dict(payload)
    hollow["surface_profile"] = {"kind": "observed"}
    errors = validate_report_v2(hollow)
    fail_if(
        not errors,
        name="P0-schema-rejects-empty-observed",
        hypothesis="kind=observed だけの空オブジェクトは validator が拒否する",
        counter="空 observed が通る",
        fixture="mutated report-v2",
        command="validate_report_v2({kind: observed})",
        expected="errors non-empty",
        actual=str(errors[:5]),
        evidence="schema_v2",
    )
    need = tmp / "follow" / "need.toml"
    need.write_text(
        'schema_version="tep-project-v1"\nproject_id="checkout-api"\n'
        '[requirements.surfaces]\nrequired=["backend"]\n',
        encoding="utf-8",
    )
    al = run_cli(
        [
            "align",
            "--repo",
            str(repo),
            "--identity",
            str(repo / ".tep" / "identity.toml"),
            "--actor",
            "alice",
            "--project",
            str(need),
            "--format",
            "json",
        ],
        cwd=repo,
    )
    axes = parse_json(al.stdout).get("axes") if al.returncode == 0 else []
    paths = " ".join(" ".join(ax.get("evidence_paths") or []) for ax in axes)
    fail_if(
        al.returncode != 0 or "actor." not in paths or "project.declared." not in paths,
        name="P0-align-evidence-paths-boundary",
        hypothesis="alignment は actor 観測と project 宣言の根拠を分けて書く",
        counter="どちら側の入力か分からない",
        fixture=str(need),
        command="align --format json",
        expected="evidence_paths contain actor. and project.declared.",
        actual=f"rc={al.returncode} paths={paths[:200]}",
        evidence="alignment axes",
    )
    proj_md = run_cli(
        ["project", str(repo), "--requirements", str(need), "--format", "md"],
        cwd=repo,
    )
    proj_js = run_cli(["project", str(repo), "--format", "json"], cwd=repo)
    proj_payload = parse_json(proj_js.stdout) if proj_js.returncode == 0 else {}
    hollow_project = {
        "schema_version": "project-v1",
        "report_kind": "project",
        "declared": {
            "change_rhythm": {},
            "surfaces": {"kind": "not_declared", "reason": "requirement_not_provided"},
            "verification": {"kind": "not_declared", "reason": "requirement_not_provided"},
            "inputs": {"kind": "not_declared", "reason": "requirement_not_provided"},
        },
        "observed": {"kind": "observed", "unit": "profile", "definition_version": "1.0.0"},
    }
    fail_if(
        proj_md.returncode != 0
        or "{'kind'" in proj_md.stdout
        or "['backend'" in proj_md.stdout
        or "調整の観測" not in proj_md.stdout
        or not (proj_payload.get("provenance") or {}).get("observation_date")
        or not validate_project(hollow_project),
        name="P0-project-markdown-and-hollow-profile",
        hypothesis="project MD は coordination を出し、list repr も空 profile も通さない",
        counter="coordination 欠落 / Python list / 空洞 profile が通る",
        fixture=str(need),
        command="project --format md|json + validate_project hollow",
        expected="coordination section, no list repr, hollow rejected, observation_date set",
        actual=(
            f"rc={proj_md.returncode} coord={'調整の観測' in proj_md.stdout} "
            f"date={(proj_payload.get('provenance') or {}).get('observation_date')} "
            f"hollow={validate_project(hollow_project)[:3]}"
        ),
        evidence="project markdown/schema",
    )


def main() -> int:
    if V059 is None or not (V059 / "src" / "tep_cli").is_dir():
        print("v0.5.9 worktree missing", file=sys.stderr)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="grift-p0-"))
    steps = (
        p0_legacy,
        p0_separation,
        p0_actor_mix,
        p0_consent,
        p0_not_observed,
        p0_determinism,
        p0_rhythm,
        p0_surface_and_lens,
        p0_project_align,
        p0_pii,
        p0_verify,
        p0_noneng,
        p0_followup,
        p1_extras,
    )
    for step in steps:
        try:
            step(tmp)
        except Exception as exc:  # noqa: BLE001
            record(
                name=f"runner-crash-{step.__name__}",
                hypothesis="runner completes",
                counter=repr(exc),
                fixture=str(tmp),
                command=step.__name__,
                expected="no exception",
                actual=repr(exc),
                verdict="FAIL",
                evidence="exception",
            )
    out = LOG / "p0-results.json"
    persisted_results = sanitize_results_for_persistence(RESULTS, tmp_root=tmp)
    out.write_text(
        json.dumps(persisted_results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    failed = [r for r in RESULTS if r["verdict"] == "FAIL"]
    for row in RESULTS:
        print("=" * 72)
        print(f"[{row['verdict']}] {row['name']}")
        print(f"仮説: {row['hypothesis']}")
        print(f"反証しようとした反例: {row['counter']}")
        print(f"使用したfixture: {row['fixture']}")
        print(f"実行コマンド: {row['command']}")
        print(f"期待結果: {row['expected']}")
        print(f"実測結果: {row['actual']}")
        print(f"判定: {row['verdict']}")
        print(f"証跡: {row['evidence']}")
    print("=" * 72)
    print(
        f"summary PASS={sum(1 for r in RESULTS if r['verdict'] == 'PASS')} FAIL={len(failed)} total={len(RESULTS)}"
    )
    print(f"log={out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
