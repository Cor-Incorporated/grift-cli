"""`grift identity` — generate/list identity-v2 material (issue #26, v0.9.3).

Verb semantics follow the CLI table: exit 0 on success, exit 2 on usage or
input errors.  Raw emails are accepted on the command line (they already
appear in the repository's own git log) but are never written to the output
file: the template records only ``email_sha256`` digests.
"""

from __future__ import annotations

import errno
import os
import sys
import tempfile
import tomllib
from argparse import Namespace
from pathlib import Path

from tep_core.gitutil import GitError
from tep_core.identity import (
    CANONICAL_ID_PATTERN,
    CANONICAL_ID_RE,
    RESERVED_ACTOR_HASH_RE,
    load_identity,
)
from tep_core.identity_init import (
    author_email_counts,
    derive_canonical_id,
    dedupe_emails,
    render_empty_template,
    render_identity_template,
)


def _fail(message: str) -> int:
    sys.stderr.write(f"identity: {message}\n")
    return 2


def run_identity(args: Namespace) -> int:
    init = bool(getattr(args, "init", False))
    list_emails = bool(getattr(args, "list_emails", False))
    if init and list_emails:
        return _fail("--init and --list cannot be combined")
    if not init and not list_emails:
        return _fail("specify --init or --list")
    repo: Path = args.repo if args.repo is not None else Path(".")
    if list_emails:
        return _run_list(repo)
    return _run_init(args, out=getattr(args, "out", None))


def _run_init(args: Namespace, *, out: Path | None) -> int:
    if out is None:
        return _fail("--init requires --out")
    try:
        if out.exists():
            return _fail(f"refusing to overwrite existing file: {out}")
    except OSError as exc:
        return _write_error(out, exc)
    emails = dedupe_emails(getattr(args, "emails", None) or [])
    if not emails:
        return _write(out, render_empty_template(), "wrote empty identity template")
    canonical_id = getattr(args, "canonical_id", None) or derive_canonical_id(emails[0])
    if not canonical_id:
        return _fail(
            f"could not derive canonical_id from {emails[0]!r}; pass --id ID "
            f"(it must fullmatch {CANONICAL_ID_PATTERN})"
        )
    if not CANONICAL_ID_RE.fullmatch(canonical_id) or RESERVED_ACTOR_HASH_RE.fullmatch(
        canonical_id
    ):
        return _fail(
            f"invalid canonical_id {canonical_id!r}; it must fullmatch "
            f"{CANONICAL_ID_PATTERN} and must not have the reserved hash-id shape"
        )
    try:
        text = render_identity_template(canonical_id, emails)
        # Round-trip contract: what we are about to write must load.
        load_identity(None, _document=tomllib.loads(text))
    except ValueError as exc:
        return _fail(str(exc))
    return _write(out, text, f"wrote identity-v2 template ({len(emails)} email digest(s))")


def _write(out: Path, text: str, message: str) -> int:
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _write_error(out, exc)
    try:
        with tempfile.TemporaryDirectory(
            dir=out.parent, prefix=".grift-identity-", ignore_cleanup_errors=True
        ) as temporary:
            staged = Path(temporary) / "identity.toml"
            with staged.open("x", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            # Windows rename fails if the target exists. On POSIX, rename can
            # replace it, so publish by linking the already complete file.
            if os.name == "nt":
                staged.rename(out)
            else:
                os.link(staged, out)
    except FileExistsError:
        return _fail(f"refusing to overwrite existing file: {out}")
    except OSError as exc:
        if errno.errorcode.get(exc.errno) in {"ENOTSUP", "EOPNOTSUPP", "ENOSYS", "EPERM"}:
            return _fail(
                f"could not create identity file without overwriting at {out}: "
                "retry with --out on a writable filesystem that supports atomic creation"
            )
        return _write_error(out, exc)
    sys.stderr.write(f"{message} to {out}\n")
    return 0


def _write_error(out: Path, exc: OSError) -> int:
    detail = exc.strerror or str(exc)
    return _fail(f"could not write identity file {out}: {detail}")


def _run_list(repo: Path) -> int:
    if not (repo / ".git").exists() and not repo.joinpath("HEAD").exists():
        return _fail(f"not a git repository: {repo}")
    try:
        counts = author_email_counts(repo)
    except GitError as exc:
        return _fail(str(exc))
    for email, count in counts:
        sys.stdout.write(f"{count}\t{email}\n")
    return 0


__all__ = ["run_identity"]
