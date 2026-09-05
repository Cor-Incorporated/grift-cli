"""Read declared dependency names out of a package manifest.

`surface_profile` can say a commit touched the `deps` surface and
`dependency_update_share` can say how often; neither says *which* library. The
name is what carries domain evidence: "introduced Stripe" is a statement about
payments work, "touched a manifest" is not.

Only manifests are parsed, never lock files. A lock file is derived from the
manifest, churns on every transitive bump, and lists thousands of names nobody
chose — parsing it would swamp the declaration with noise.

Parsing runs on file bytes at a fixed OID, so the result is deterministic and
recomputable, and no source code is read: only the dependency declaration.

A manifest that cannot be parsed raises rather than returning an empty set. An
empty set means "declared nothing", which under norms §1 must never be produced
by a failure to read.
"""

from __future__ import annotations

import json
import re
import tomllib

__all__ = [
    "SUPPORTED_MANIFESTS",
    "ManifestParseError",
    "declared_dependencies",
    "is_supported_manifest",
]


class ManifestParseError(ValueError):
    """The manifest exists but its declaration could not be read."""


SUPPORTED_MANIFESTS = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "go.mod",
        "cargo.toml",
        "composer.json",
    }
)

# PEP 508 / pip requirement line: name, then any of the version or marker
# punctuation. Options (-r, --index-url) and VCS URLs are not declarations of a
# named package and are skipped.
_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:[<>=!~\[;]|$)")
# `require path v1.2.3`, with or without a trailing `// indirect`.
_GO_REQUIRE = re.compile(r"^(?:require\s+)?(?P<path>[^\s()]+)\s+v[^\s]+")
_PYPROJECT_SPEC = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


# Which package registry each manifest declares against. Prevalence is only
# comparable inside one ecosystem: "react is declared by 21 of 39 npm projects"
# says something; the same count over every repository silently includes Go and
# Rust projects that could never have declared it.
ECOSYSTEM_BY_MANIFEST = {
    "package.json": "npm",
    "pyproject.toml": "pypi",
    "requirements.txt": "pypi",
    "go.mod": "go",
    "cargo.toml": "crates",
    "composer.json": "packagist",
}


def is_supported_manifest(basename: str) -> bool:
    return basename.casefold() in SUPPORTED_MANIFESTS


def ecosystem_for(basename: str) -> str | None:
    """The registry a manifest declares against, or None if unsupported."""
    return ECOSYSTEM_BY_MANIFEST.get(basename.casefold())


def _json_object(body: str, basename: str) -> dict:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ManifestParseError(f"{basename}: invalid JSON ({exc})") from exc
    if not isinstance(parsed, dict):
        raise ManifestParseError(f"{basename}: top level must be an object")
    return parsed


def _toml_object(body: str, basename: str) -> dict:
    try:
        return tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestParseError(f"{basename}: invalid TOML ({exc})") from exc


def _from_package_json(body: str, basename: str) -> set[str]:
    data = _json_object(body, basename)
    names: set[str] = set()
    for section in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "require",
        "require-dev",
    ):
        block = data.get(section)
        if isinstance(block, dict):
            names.update(str(key) for key in block)
    return names


def _from_pyproject(body: str, basename: str) -> set[str]:
    data = _toml_object(body, basename)
    names: set[str] = set()

    def add_specs(specs: object) -> None:
        if isinstance(specs, list):
            for spec in specs:
                if isinstance(spec, str):
                    match = _PYPROJECT_SPEC.match(spec.strip())
                    if match:
                        names.add(match.group(1))

    project = data.get("project")
    if isinstance(project, dict):
        add_specs(project.get("dependencies"))
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                add_specs(group)
    poetry = (
        ((data.get("tool") or {}).get("poetry")) if isinstance(data.get("tool"), dict) else None
    )
    if isinstance(poetry, dict):
        for section in ("dependencies", "dev-dependencies"):
            block = poetry.get(section)
            if isinstance(block, dict):
                names.update(str(key) for key in block if str(key).lower() != "python")
    return names


def _from_requirements(body: str, _basename: str) -> set[str]:
    names: set[str] = set()
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if "://" in line or line.startswith(("git+", "hg+", "svn+", "bzr+")):
            continue
        match = _REQUIREMENT_NAME.match(line)
        if match:
            names.add(match.group(1))
    return names


def _from_go_mod(body: str, _basename: str) -> set[str]:
    names: set[str] = set()
    in_block = False
    for raw in body.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if line.startswith("require (") or line == "require(":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if in_block or line.startswith("require "):
            match = _GO_REQUIRE.match(line)
            if match:
                names.add(match.group("path"))
    return names


def _from_cargo(body: str, basename: str) -> set[str]:
    data = _toml_object(body, basename)
    names: set[str] = set()
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        block = data.get(section)
        if isinstance(block, dict):
            names.update(str(key) for key in block)
    target = data.get("target")
    if isinstance(target, dict):
        for platform in target.values():
            if isinstance(platform, dict):
                for section in ("dependencies", "dev-dependencies"):
                    block = platform.get(section)
                    if isinstance(block, dict):
                        names.update(str(key) for key in block)
    return names


_PARSERS = {
    "package.json": _from_package_json,
    "composer.json": _from_package_json,
    "pyproject.toml": _from_pyproject,
    "requirements.txt": _from_requirements,
    "go.mod": _from_go_mod,
    "cargo.toml": _from_cargo,
}


def declared_dependencies(basename: str, body: str) -> set[str]:
    """Names declared in `body`, which must be the contents of `basename`.

    Raises ManifestParseError when the manifest is present but unreadable.
    """
    key = basename.casefold()
    parser = _PARSERS.get(key)
    if parser is None:
        raise ManifestParseError(f"{basename}: not a supported manifest")
    return parser(body, basename)
