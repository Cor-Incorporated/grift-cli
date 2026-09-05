"""Release-facing v0.6.0 contracts must agree with the version SSOT.

This gate intentionally inspects only current release surfaces.  Historical
CHANGELOG entries and archived evidence may accurately describe older network
and contribution behaviour, so they are not searched for current claims.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "tep_core" / "version.py"
def _migration_relative(version: str) -> str:
    """docs/migration-vXYZ.md for version X.Y.Z.

    Derived rather than written out: a literal pins the previous release and
    keeps passing after a bump, which is the failure mode these gates exist to
    catch.
    """
    return f"docs/migration-v{version.replace('.', '')}.md"
CURRENT_CLAIM_CODE = (
    ROOT / "src" / "tep_cli" / "options.py",
    ROOT / "src" / "tep_cli" / "__main__.py",
    ROOT / "src" / "tep_core" / "contribute.py",
)


def _current_public_docs() -> tuple[Path, ...]:
    return (
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / _migration_relative(_source_version()),
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _source_version() -> str:
    tree = ast.parse(_read(VERSION_FILE), filename=str(VERSION_FILE))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in targets
        ):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    raise AssertionError("src/tep_core/version.py must define a literal __version__")


def _package_smoke_main_invokes_build(path: Path) -> bool:
    """Require an executable ``python -m build`` argv in package_smoke.main."""

    tree = ast.parse(_read(path), filename=str(path))
    main = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        ),
        None,
    )
    if main is None:
        return False
    for node in ast.walk(main):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_run"
            and node.args
            and isinstance(node.args[0], (ast.List, ast.Tuple))
        ):
            continue
        tokens: list[str | None] = []
        for item in node.args[0].elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                tokens.append(item.value)
            elif (
                isinstance(item, ast.Attribute)
                and isinstance(item.value, ast.Name)
                and item.value.id == "sys"
                and item.attr == "executable"
            ):
                tokens.append("<python>")
            else:
                tokens.append(None)
        if tokens[:7] == [
            "<python>",
            "-m",
            "build",
            "--sdist",
            "--wheel",
            "--outdir",
            None,
        ]:
            return True
    return False


def _require_fragments(path: Path, fragments: tuple[str, ...]) -> None:
    text = _read(path)
    missing = [fragment for fragment in fragments if fragment not in text]
    assert not missing, f"{path.relative_to(ROOT)} is missing current-contract text: {missing}"


def _current_changelog_section(text: str) -> tuple[str, str]:
    headers = list(re.finditer(r"(?m)^## \[(\d+\.\d+\.\d+)]", text))
    assert headers, "CHANGELOG.md has no SemVer release heading"
    first = headers[0]
    end = headers[1].start() if len(headers) > 1 else len(text)
    return first.group(1), text[first.start() : end]


def _action_version_default(action: str) -> str:
    block = re.search(
        r"(?ms)^  version:\s*\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\s*\n|\Z)",
        action,
    )
    assert block, "action.yml must expose an inputs.version block"
    default = re.search(r'(?m)^    default:\s*["\']?([^"\'\s#]+)', block.group("body"))
    assert default, "action.yml inputs.version must have a pinned default"
    return default.group(1)


def test_version_py_is_the_only_project_version_source() -> None:
    """No literal version here.

    Asserting `version == "0.6.0"` pinned the release into the gate, so the gate
    went on passing while everything around it moved to the next one. What
    matters is that one file is the source and everything else agrees with it.
    """
    version = _source_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version

    pyproject = tomllib.loads(_read(ROOT / "pyproject.toml"))
    project = pyproject["project"]
    assert "version" not in project, "pyproject must not duplicate the version literal"
    assert "version" in project.get("dynamic", []), "project version must be dynamic"
    assert pyproject["tool"]["hatch"]["version"]["path"] == "src/tep_core/version.py"
    assert f'DEFINITION_VERSION = "tep-v{version}-' in _read(VERSION_FILE)


def test_current_changelog_and_migration_lead_with_the_source_version() -> None:
    version = _source_version()
    changelog_version, current = _current_changelog_section(_read(ROOT / "CHANGELOG.md"))
    assert changelog_version == version
    for fragment in (
        "provider-neutral Forge証跡",
        "GitHub/GitLab/self-managed",
        "PARTIAL/resume",
        "attest / portfolio",
        "contribution-v2",
        "暗黙 PyPI update check",
    ):
        assert fragment in current, f"current CHANGELOG section is missing {fragment!r}"

    migration = _read(ROOT / _migration_relative(version))
    assert migration.startswith(f"# v{version} 移行\n")


@pytest.mark.parametrize(
    ("relative", "fragments"),
    [
        (
            "README.md",
            (
                "## 公開 Forge 取得",
                "--fetch-public",
                "--public-evidence",
                "--resume-public-evidence",
                "GitHub",
                "GitLab",
                "provider-neutral",
                "self-managed",
                "exit 3",
                "PARTIAL",
                "aggregate",
                "named-public",
                "masked",
                "raw",
                "local",
                "controlled",
                "public-pr",
                "grift attest",
                "OpenSSH",
                "cosign",
                "--allowed-signers",
                "report hash",
                "grift portfolio",
                "eligible",
                "included",
                "開示率",
                "score",
                "rank",
            ),
        ),
        (
            "README.en.md",
            (
                "## Public forge fetch",
                "--fetch-public",
                "--public-evidence",
                "--resume-public-evidence",
                "GitHub",
                "GitLab",
                "provider-neutral",
                "self-managed",
                "exit 3",
                "PARTIAL",
                "aggregate",
                "named-public",
                "masked",
                "raw",
                "local",
                "controlled",
                "public-pr",
                "grift attest",
                "OpenSSH",
                "cosign",
                "--allowed-signers",
                "report hash",
                "grift portfolio",
                "eligible",
                "included",
                "disclosure",
                "scores",
                "ranks",
            ),
        ),
        (
            _migration_relative(_source_version()),
            (
                # v0.7.0 surfaces. The v0.6.0 fragments below still apply
                # because those surfaces did not go away.
                "library_context",
                "outcome",
                "align --team",
                "--purpose",
                "history_incomplete",
                "fetch-depth: 1",
                "## 固定revisionと公開Forge証跡",
                "--fetch-public",
                "--public-evidence",
                "--resume-public-evidence",
                "GitHub",
                "GitLab",
                "provider-neutral",
                "exit 3",
                "PARTIAL",
                "## contribution-v2",
                "aggregate",
                "named-public",
                "masked",
                "raw",
                "local",
                "controlled",
                "public-pr",
                "## attest / portfolio",
                "grift attest",
                "ssh|cosign",
                "signature",
                "report hash",
                "repository recomputation",
                "grift portfolio",
                "email/handle",
                "score",
                "rank",
            ),
        ),
    ],
)
def test_public_docs_explain_the_v060_surfaces(
    relative: str,
    fragments: tuple[str, ...],
) -> None:
    _require_fragments(ROOT / relative, fragments)


def test_readmes_scope_network_and_public_pr_disclosure_precisely() -> None:
    ja = _read(ROOT / "README.md")
    en = _read(ROOT / "README.en.md")

    for fragment in (
        "`analyze` / `report` はofflineです",
        "`repo` / `actor` は既定offline",
        "ほかの明示network経路",
        "暗黙update checkはありません",
        "代理PR経路は提出者identityを非公開にしてもpayload自体は公開されます",
        "完全撤回できません",
    ):
        assert fragment in ja, f"README.md is missing scoped disclosure {fragment!r}"
    for fragment in (
        "`analyze` and `report` are offline",
        "`repo` and `actor` are offline by default",
        "other explicit network paths",
        "there is no implicit update check",
        "A proxy PR may hide submitter identity, but its payload still becomes public",
        "cannot be fully withdrawn",
    ):
        assert fragment in en, f"README.en.md is missing scoped disclosure {fragment!r}"

    contribution_code = _read(ROOT / "src" / "tep_core" / "contribute.py")
    assert "payload自体は公開されます" in contribution_code
    assert "it is not a private-payload door" in contribution_code
    assert "cannot be fully withdrawn" in contribution_code


def test_readmes_distinguish_bare_and_explicit_path_scope_defaults() -> None:
    ja = _read(ROOT / "README.md")
    en = _read(ROOT / "README.en.md")
    assert "`grift analyze`" in ja and "report-v1・repo スコープ" in ja
    assert "`grift analyze`" in en and "report-v1; repo scope" in en

    scoped_default_lines = [
        (ROOT / "README.md", line)
        for line in ja.splitlines()
        if "`--scope tenant`" in line and "（既定）" in line
    ] + [
        (ROOT / "README.en.md", line)
        for line in en.splitlines()
        if "`--scope tenant`" in line and "(default)" in line
    ]
    for path, line in scoped_default_lines:
        assert "明示" in line or "explicit" in line.lower(), (
            f"{path.name} calls tenant the unqualified default although bare analyze/report "
            f"default to repo scope: {line}"
        )


def test_contribution_module_docstring_describes_all_v2_profiles_and_doors() -> None:
    source = _read(ROOT / "src" / "tep_core" / "contribute.py")
    module_doc = ast.get_docstring(ast.parse(source), clean=False)
    assert module_doc is not None
    obsolete = (
        r"repo-scope aggregate values.*?ONLY",
        r"canonical_id, actors, emails, paths, repo name.*?NEVER included",
    )
    matches = [pattern for pattern in obsolete if re.search(pattern, module_doc, re.DOTALL)]
    assert not matches, f"contribute module still documents the removed v1-only contract: {matches}"
    for fragment in (
        "aggregate",
        "named-public",
        "masked",
        "raw",
        "local",
        "controlled",
        "public-pr",
    ):
        assert fragment in module_doc, f"contribute module docstring is missing {fragment!r}"


@pytest.mark.parametrize("path", _current_public_docs() + CURRENT_CLAIM_CODE)
def test_current_docs_and_code_reject_obsolete_universal_claims(path: Path) -> None:
    text = _read(path)
    forbidden = (
        r"\bthe measurement commands (?:always )?never touch the network\b",
        r"測定コマンド[^\n]{0,100}ネットワークに触れません",
        r"\bcontribut(?:e|ion)[^\n]{0,140}\(never sends\)",
        r"\bthe CLI never sends anything\b",
        r"CLI\s*は何も送信しません",
        r"(?:public\s+)?forge[^\n]{0,140}(?:github[- ]only|only github)",
        r"(?:公開\s*)?Forge[^\n]{0,140}(?:GitHubのみ|GitHubだけ|GitHub専用)",
        r"(?<!not a )\bprivate door\b",
        r"非公開ドア(?![^\n]{0,40}では(?:ありません|ない))",
        r"private door[^\n]{0,140}(?:payload|data)[^\n]{0,80}(?:is|stays|remains) private",
        r"(?:payload|data)[^\n]{0,100}(?:is|stays|remains) fully private",
        r"非公開ドア[^\n]{0,140}(?:payload|データ)[^\n]{0,80}(?:非公開|公開されません)",
        r"(?:fully anonymous|完全匿名)",
    )
    matches = [pattern for pattern in forbidden if re.search(pattern, text, re.IGNORECASE)]
    assert not matches, (
        f"{path.relative_to(ROOT)} reintroduced an obsolete universal/public-only claim: {matches}"
    )


def test_update_check_can_only_run_through_the_explicit_update_handler() -> None:
    path = ROOT / "src" / "tep_cli" / "__main__.py"
    source = _read(path)
    assert "_maybe_update_notice" not in source
    assert "GRIFT_NO_UPDATE_NOTICE" not in source
    assert 'if args.command == "update":\n        return _run_update(args)' in source

    tree = ast.parse(source, filename=str(path))
    urlopen_owners: list[str] = []

    class NetworkCallVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.functions: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.functions.append(node.name)
            self.generic_visit(node)
            self.functions.pop()

        def visit_Call(self, node: ast.Call) -> None:
            name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name == "urlopen":
                urlopen_owners.append(self.functions[-1] if self.functions else "<module>")
            self.generic_visit(node)

    NetworkCallVisitor().visit(tree)
    assert urlopen_owners == ["_run_update"], (
        "PyPI/update urlopen must remain reachable only from explicit `grift update`"
    )


def test_partial_public_collection_documentation_matches_exit_code_3() -> None:
    subject = _read(ROOT / "src" / "tep_cli" / "subject.py")
    assert re.search(
        r'elif state_status == "partial".{0,300}?exit_code = 3',
        subject,
        re.DOTALL,
    ), "safe partial public collection must map to exit 3"
    assert "return evidence.exit_code" in subject


def test_action_and_release_workflows_do_not_pin_a_different_grift_version() -> None:
    from test_package_contract import _publish_admission_errors

    version = _source_version()
    action = _read(ROOT / "action.yml")
    assert _action_version_default(action) == version
    assert "GRIFT_ACTION_VERSION: ${{ inputs.version }}" in action
    assert 'python -m pip install --no-input "grift-cli==$GRIFT_ACTION_VERSION"' in action

    for readme in (ROOT / "README.md", ROOT / "README.en.md"):
        refs = re.findall(r"Cor-Incorporated/grift-cli@v(\d+\.\d+\.\d+)", _read(readme))
        assert refs, f"{readme.name} must show the current composite-action pin"
        assert set(refs) == {version}, f"{readme.name} has stale action refs: {refs}"

    workflows = (
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / ".github" / "workflows" / "publish.yml",
    )
    for workflow in workflows:
        text = _read(workflow)
        package_pins = re.findall(r"grift-cli==([0-9]+\.[0-9]+\.[0-9]+)", text)
        action_refs = re.findall(
            r"Cor-Incorporated/grift-cli@v([0-9]+\.[0-9]+\.[0-9]+)",
            text,
        )
        assert set(package_pins + action_refs) <= {version}, (
            f"{workflow.relative_to(ROOT)} pins a release other than {version}: "
            f"{package_pins + action_refs}"
        )
        assert "python -m pytest" in text, f"{workflow.name} must run the consistency gate"
    publish_errors = _publish_admission_errors(_read(workflows[1]))
    assert publish_errors == [], publish_errors
    assert _package_smoke_main_invokes_build(ROOT / "scripts" / "package_smoke.py")
