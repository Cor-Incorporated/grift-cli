"""Explicit self-upgrade; analysis commands never import or call this module."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def run_update(args: argparse.Namespace, *, installed_version: str) -> int:
    sys.stdout.write(f"installed: {installed_version}\n")
    if args.check:
        # The metadata request belongs only to this explicit read-only path.
        # It contains no report, repository, actor or local path information.
        try:
            with urllib.request.urlopen(
                "https://pypi.org/pypi/grift-cli/json", timeout=10
            ) as response:
                data = json.loads(response.read())
            latest = data["info"]["version"]
            if not isinstance(latest, str) or not latest.strip():
                raise ValueError("missing version in PyPI response")
        except (
            OSError,
            urllib.error.URLError,
            http.client.HTTPException,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            sys.stderr.write(f"version check unavailable (offline or PyPI unreachable): {exc}\n")
            sys.stderr.write("Use `grift --version` for the installed version (offline).\n")
            return 2
        sys.stdout.write(f"latest:    {latest}\n")
        if latest == installed_version:
            sys.stdout.write("up to date\n")
        return 0

    # A pipx executable somewhere on PATH does not mean this grift belongs to
    # pipx. Identify the running environment from pipx's on-disk metadata.
    env = os.environ.copy()
    # The installer must not import pip (or anything else) from the working directory or from a
    # source-checkout override: `grift update` is typically run inside someone's repository.
    env.pop("PYTHONPATH", None)
    # The running environment is the only target: pip must not be redirected elsewhere.
    for name in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT"):
        env.pop(name, None)
    # Python children (including the ones pipx starts) keep the working directory off sys.path.
    env["PYTHONSAFEPATH"] = "1"
    prefix = Path(sys.prefix)
    metadata_path = prefix / "pipx_metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            package = metadata["main_package"]["package"]
            if (
                package.lower().replace("_", "-") != "grift-cli"
                or prefix.parent.name != "venvs"
            ):
                raise ValueError("the running pipx environment is not a grift-cli environment")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            sys.stderr.write(f"update: cannot identify the running pipx installation: {exc}\n")
            return 2
        pipx = shutil.which("pipx")
        if pipx is None:
            sys.stderr.write(
                "update: this installation is managed by pipx, but pipx is not on PATH\n"
            )
            return 2
        # Bind even a suffixed/custom-home installation to its own pipx home,
        # rather than updating a different grift-cli found by the PATH pipx.
        env["PIPX_HOME"] = str(prefix.parent.parent)
        command = [pipx, "upgrade", prefix.name]
    else:
        command = [sys.executable, "-P", "-m", "pip", "install", "--upgrade", "grift-cli"]
    sys.stdout.write(f"running: {shlex.join(command)}\n")
    sys.stdout.flush()
    try:
        # Start outside the user's repository: grift is usually run inside someone else's checkout.
        result = subprocess.run(command, env=env, cwd=str(prefix))
    except OSError as exc:
        sys.stderr.write(f"update: could not start the package manager: {exc}\n")
        return 2
    if result.returncode:
        return result.returncode

    # Import afresh after installation. Remove source-checkout overrides while
    # preserving the user site, so pip --user installations can be checked too.
    version_env = os.environ.copy()
    version_env.pop("PYTHONPATH", None)
    try:
        checked = subprocess.run(
            [sys.executable, "-P", "-m", "tep_cli", "--version"],
            env=version_env,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        sys.stderr.write(
            f"update: upgrade finished but installed version could not be checked: {exc}\n"
        )
        return 2
    if checked.returncode or not checked.stdout.strip():
        sys.stderr.write("update: upgrade finished but installed version could not be checked\n")
        sys.stderr.write("Run `grift --version` to inspect the installed version.\n")
        return 2
    sys.stdout.write(f"installed after update: {checked.stdout.strip()}\n")
    return 0
