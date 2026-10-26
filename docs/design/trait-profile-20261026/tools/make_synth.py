"""Build four deterministic synthetic git repositories for the trait-profile design.

ledger-api  : candidate-a, backend/test-heavy, small commits every 1-5 days, tags.
shop-front  : candidate-b, frontend/docs/e2e, bursts of work then 2-5 weeks quiet.
payments-api: project repo for case P1 (three anonymous members, steady cadence).
storefront  : project repo for case P2 (two anonymous members, sprint cadence).

Every name, email and date is synthetic. Emails use example.com.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

TZ = "+09:00"


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return result.stdout


def init(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    git(path, "config", "user.name", "Fixture")
    git(path, "config", "user.email", "fixture@example.com")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "tag.gpgsign", "false")
    return path


def who_env(name: str, email: str, stamp: str) -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": stamp,
    }


def stamp(day: date, hour: int) -> str:
    return f"{day.isoformat()}T{hour:02d}:{(hour * 7) % 60:02d}:00{TZ}"


PACKAGE_JSON = (
    '{{\n  "name": "{name}",\n  "version": "0.{rev}.0",\n'
    '  "dependencies": {{"react": "^19.0.0"}},\n'
    '  "devDependencies": {{"@playwright/test": "^1.50.0", "vitest": "^3.0.0"}}\n}}\n'
)


_REVISIONS: dict[str, int] = {}


def write_file(repo: Path, rel: str, line: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    if rel.endswith("package.json"):
        key = f"{repo}/{rel}"
        _REVISIONS[key] = _REVISIONS.get(key, 0) + 1
        target.write_text(
            PACKAGE_JSON.format(name=repo.name, rev=_REVISIONS[key]), encoding="utf-8"
        )
        return
    target.write_text(old + line, encoding="utf-8")


def commit(repo: Path, person: tuple[str, str], when: str, message: str, files: list[str]) -> None:
    for rel in files:
        write_file(repo, rel, f"# {message} @ {when}\n")
        git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", message, env=who_env(*person, when))


def merge(
    repo: Path, person: tuple[str, str], when: str, branch: str, message: str, files: list[str]
) -> None:
    git(repo, "checkout", "-q", "-b", branch)
    commit(repo, person, when, f"feat: {branch} work", files)
    git(repo, "checkout", "-q", "main")
    later = when.replace("T", "T").rsplit(":", 2)[0] + ":59:00" + TZ
    git(repo, "merge", "-q", "--no-ff", "-m", message, branch, env=who_env(*person, later))
    git(repo, "branch", "-q", "-d", branch)


def tag(repo: Path, person: tuple[str, str], when: str, name: str) -> None:
    git(repo, "tag", "-a", name, "-m", f"release {name}", env=who_env(*person, when))


def days(start: str, gaps: list[int], until: str) -> list[date]:
    out: list[date] = []
    day = date.fromisoformat(start)
    end = date.fromisoformat(until)
    index = 0
    while day <= end:
        out.append(day)
        day += timedelta(days=gaps[index % len(gaps)])
        index += 1
    return out


CAND_A = ("Candidate A", "cand-a@example.com")
CAND_B = ("Candidate B", "cand-b@example.com")
KEN = ("Collaborator K", "collab-k@example.com")
MIKA = ("Collaborator M", "collab-m@example.com")
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")

# candidate-a: one work pattern per commit, cycled. Paths are chosen so the
# surface / verification / domain classifiers in tep_core see what the name says.
A_PLAN: list[tuple[str, list[str]]] = [
    ("feat: add {n} endpoint", ["api/routes/{n}.py", "tests/unit/test_{n}.py"]),
    ("feat: {n} service rules", ["services/{n}.py"]),
    ("test: cover {n} flow end to end", ["tests/integration/test_{n}_flow.py"]),
    ("fix: rounding in {n}", ["services/{n}.py", "tests/unit/test_{n}.py"]),
    ("refactor: split {n} helpers", ["services/{n}.py", "services/common.py"]),
    ("feat(db): add {n} table", ["migrations/{m}_{n}.sql", "services/{n}.py"]),
    ("fix: validate {n} input", ["api/routes/{n}.py", "tests/unit/test_{n}.py"]),
    ("docs: describe {n} api", ["docs/api.md"]),
    ("fix: null handling in {n}", ["api/routes/{n}.py"]),
    ("ci: run integration tests", [".github/workflows/ci.yml"]),
    ("chore(deps): bump client libs", ["requirements.txt"]),
    ("test: edge cases for {n}", ["tests/unit/test_{n}.py", "tests/integration/test_{n}_flow.py"]),
]
A_TOPICS = ["ledger", "invoice", "refund", "payout", "account", "statement"]

B_PLAN: list[tuple[str, list[str]]] = [
    ("feat: {n} page layout", ["web/src/pages/{n}.tsx", "web/src/components/{N}Header.tsx"]),
    (
        "feat: {N} card component",
        ["web/src/components/{N}Card.tsx", "web/src/components/{N}Card.module.css"],
    ),
    ("docs: ui decision for {n}", ["docs/decisions/{n}.md"]),
    ("test: e2e for {n} checkout path", ["e2e/{n}.spec.ts"]),
    ("fix: {n} layout on small screens", ["web/src/components/{N}Card.module.css"]),
    (
        "feat: {n} form states",
        ["web/src/components/{N}Form.tsx", "web/src/components/__tests__/{N}Form.test.tsx"],
    ),
    ("refactor: {n} price formatting", ["web/src/lib/format.ts"]),
    ("docs: update ui guidelines", ["docs/ui-guidelines.md"]),
    ("fix: {n} focus order", ["web/src/components/{N}Form.tsx", "e2e/{n}.spec.ts"]),
    ("chore: bump ui packages", ["package.json"]),
]
B_TOPICS = ["cart", "search", "product", "account", "wishlist", "checkout"]


def fill(paths: list[str], topic: str, serial: int) -> list[str]:
    return [p.format(n=topic, N=topic.capitalize(), m=f"{serial:04d}") for p in paths]


def build_ledger(root: Path) -> None:
    repo = init(root / "ledger-api")
    commit(
        repo,
        CAND_A,
        stamp(date(2025, 11, 3), 10),
        "chore: scaffold ledger api",
        ["README.md", "pyproject.toml", "api/__init__.py", "services/__init__.py"],
    )
    early = days("2025-11-07", [5, 7, 6, 8], "2026-04-20")
    window = days("2026-04-24", [2, 3, 1, 4, 2, 3, 5, 2], "2026-10-18")
    serial = 0
    for index, day in enumerate(early + window):
        message, paths = A_PLAN[index % len(A_PLAN)]
        topic = A_TOPICS[(index // len(A_PLAN)) % len(A_TOPICS)]
        serial += 1
        commit(
            repo,
            CAND_A,
            stamp(day, 9 + index % 9),
            message.format(n=topic),
            fill(paths, topic, serial),
        )
        if day == date(2026, 1, 15) or (index > 0 and index % 23 == 0):
            tag(repo, CAND_A, stamp(day, 19), f"v0.{1 + index // 23}.0")
    # collaborator K: creates two files, later adopts one of candidate-a's files
    for when, msg, paths in [
        (date(2025, 12, 2), "feat: fx rates loader", ["services/fx_rates.py"]),
        (date(2026, 2, 10), "feat: reports endpoint", ["api/routes/reports.py"]),
        (date(2026, 3, 18), "fix: ledger cutoff", ["services/ledger.py"]),
        (date(2026, 6, 9), "feat: reports export", ["api/routes/reports.py"]),
        (date(2026, 8, 4), "test: fx rates", ["tests/unit/test_fx_rates.py"]),
    ]:
        commit(repo, KEN, stamp(when, 15), msg, paths)
    for when, msg, paths in [
        (date(2026, 5, 13), "refactor: share fx loader", ["services/fx_rates.py"]),
        (
            date(2026, 7, 15),
            "fix: reports totals",
            ["api/routes/reports.py", "tests/unit/test_reports.py"],
        ),
    ]:
        commit(repo, CAND_A, stamp(when, 18), msg, paths)
    for when in [date(2026, 3, 2), date(2026, 6, 1), date(2026, 9, 7)]:
        commit(repo, BOT, stamp(when, 6), "chore(deps): bump httpx", ["requirements.txt"])
    for when, branch in [
        (date(2026, 5, 27), "refund-v2"),
        (date(2026, 8, 19), "payout-batch"),
        (date(2026, 10, 7), "statement-pdf"),
    ]:
        merge(
            repo,
            CAND_A,
            stamp(when, 11),
            branch,
            f"Merge branch '{branch}'",
            [
                f"services/{branch.replace('-', '_')}.py",
                f"tests/unit/test_{branch.replace('-', '_')}.py",
            ],
        )


def b_days() -> list[tuple[date, int]]:
    early = [(date(2026, 1, d), 1) for d in (12, 13, 15, 19, 20, 22, 26, 28, 30)]
    bursts = {
        date(2026, 5, 7): 2,
        date(2026, 5, 8): 2,
        date(2026, 5, 11): 1,
        date(2026, 5, 28): 2,
        date(2026, 5, 29): 2,
        date(2026, 6, 1): 1,
        date(2026, 6, 24): 3,
        date(2026, 6, 25): 2,
        date(2026, 7, 21): 2,
        date(2026, 7, 22): 2,
        date(2026, 7, 23): 1,
        date(2026, 8, 25): 2,
        date(2026, 8, 26): 2,
        date(2026, 8, 27): 1,
        date(2026, 8, 28): 1,
        date(2026, 9, 29): 2,
        date(2026, 9, 30): 2,
        date(2026, 10, 1): 1,
        date(2026, 10, 2): 1,
        date(2026, 10, 14): 2,
        date(2026, 10, 15): 1,
    }
    return early + sorted(bursts.items())


def build_shop(root: Path) -> None:
    repo = init(root / "shop-front")
    commit(
        repo,
        CAND_B,
        stamp(date(2026, 1, 9), 10),
        "chore: scaffold storefront",
        ["README.md", "package.json", "web/src/pages/index.tsx"],
    )
    index = 0
    for day, count in b_days():
        for slot in range(count):
            message, paths = B_PLAN[index % len(B_PLAN)]
            topic = B_TOPICS[(index // len(B_PLAN)) % len(B_TOPICS)]
            commit(
                repo,
                CAND_B,
                stamp(day, 10 + slot * 4),
                message.format(n=topic, N=topic.capitalize()),
                fill(paths, topic, index),
            )
            index += 1
    for when, msg, paths in [
        (date(2026, 2, 3), "docs: brand voice", ["docs/brand.md"]),
        (date(2026, 3, 9), "feat: design tokens", ["web/src/styles/tokens.css"]),
        (date(2026, 6, 10), "fix: token contrast", ["web/src/styles/tokens.css"]),
        (date(2026, 8, 6), "docs: copy review notes", ["docs/brand.md"]),
    ]:
        commit(repo, MIKA, stamp(when, 14), msg, paths)
    for when, branch in [
        (date(2026, 5, 11), "cart-redesign"),
        (date(2026, 6, 25), "search-ui"),
        (date(2026, 8, 28), "product-gallery"),
        (date(2026, 10, 2), "account-pages"),
    ]:
        merge(
            repo,
            CAND_B,
            stamp(when, 17),
            branch,
            f"Merge branch '{branch}'",
            [f"web/src/components/{branch.split('-')[0].capitalize()}Panel.tsx"],
        )


def build_project(
    root: Path,
    name: str,
    people: list[tuple[str, str]],
    gaps: list[int],
    plan: list[tuple[str, list[str]]],
    topics: list[str],
) -> None:
    repo = init(root / name)
    commit(repo, people[0], stamp(date(2025, 10, 1), 10), f"chore: scaffold {name}", ["README.md"])
    for index, day in enumerate(days("2025-10-06", gaps, "2026-10-16")):
        message, paths = plan[index % len(plan)]
        topic = topics[(index // len(plan)) % len(topics)]
        commit(
            repo,
            people[index % len(people)],
            stamp(day, 9 + index % 8),
            message.format(n=topic, N=topic.capitalize()),
            fill(paths, topic, index),
        )


def main(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    build_ledger(root)
    build_shop(root)
    build_project(
        root,
        "payments-api",
        [
            ("Member P", "member-p@example.com"),
            ("Member Q", "member-q@example.com"),
            ("Member R", "member-r@example.com"),
        ],
        [1, 2, 1, 3, 1, 2],
        A_PLAN,
        ["charge", "capture", "settle"],
    )
    build_project(
        root,
        "storefront",
        [("Member S", "member-s@example.com"), ("Member T", "member-t@example.com")],
        [1, 1, 2, 1, 12],
        B_PLAN,
        ["home", "catalog", "basket"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
