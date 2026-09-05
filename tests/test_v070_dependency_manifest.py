"""W2 — read declared dependency names out of a manifest.

`surface_profile` classifies a path as `deps` and `dependency_update_share`
counts commits that touched one, but neither says *which* library. For
staffing that is the difference between "touched backend" and "introduced
Stripe": the second is domain evidence, the first is not.

Only manifests are parsed, never lock files: a lock file is derived, churns on
every transitive bump, and would drown the signal. Parsing happens on file
bytes at a fixed OID, so the result stays deterministic and recomputable.
"""

from __future__ import annotations

import pytest

from tep_core.dependency_manifest import (
    SUPPORTED_MANIFESTS,
    ManifestParseError,
    declared_dependencies,
    is_supported_manifest,
)

# --------------------------------------------------------------------------
# Each ecosystem's declaration form
# --------------------------------------------------------------------------

CASES = {
    "package.json": (
        """
        {
          "name": "widget",
          "dependencies": {"stripe": "^14.0.0", "express": "~4.18.0"},
          "devDependencies": {"vitest": "^1.0.0"},
          "peerDependencies": {"react": ">=18"}
        }
        """,
        {"stripe", "express", "vitest", "react"},
    ),
    "pyproject.toml": (
        """
        [project]
        name = "widget"
        dependencies = ["torch>=2.1", "httpx ~= 0.27", "pydantic"]

        [project.optional-dependencies]
        dev = ["pytest>=8"]
        """,
        {"torch", "httpx", "pydantic", "pytest"},
    ),
    "requirements.txt": (
        """
        # comment
        opencv-python==4.9.0.80
        numpy>=1.26

        -r other.txt
        git+https://example.test/pkg.git#egg=vendored
        """,
        {"opencv-python", "numpy"},
    ),
    "go.mod": (
        """
        module example.test/widget

        go 1.22

        require (
            github.com/stripe/stripe-go/v76 v76.0.0
            github.com/gin-gonic/gin v1.9.1
        )

        require github.com/pkg/errors v0.9.1 // indirect
        """,
        {
            "github.com/stripe/stripe-go/v76",
            "github.com/gin-gonic/gin",
            "github.com/pkg/errors",
        },
    ),
    "cargo.toml": (
        """
        [package]
        name = "widget"

        [dependencies]
        serde = { version = "1.0", features = ["derive"] }
        tokio = "1.35"

        [dev-dependencies]
        criterion = "0.5"
        """,
        {"serde", "tokio", "criterion"},
    ),
}


@pytest.mark.parametrize("basename", sorted(CASES))
def test_declared_names_are_extracted(basename: str) -> None:
    body, expected = CASES[basename]
    assert declared_dependencies(basename, body) == expected


@pytest.mark.parametrize("basename", sorted(CASES))
def test_supported_manifests_covers_every_parsed_form(basename: str) -> None:
    assert is_supported_manifest(basename)
    assert basename in SUPPORTED_MANIFESTS


# --------------------------------------------------------------------------
# Lock files are deliberately out of scope
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "basename",
    ["package-lock.json", "poetry.lock", "cargo.lock", "yarn.lock", "go.sum", "uv.lock"],
)
def test_lock_files_are_not_parsed(basename: str) -> None:
    assert not is_supported_manifest(basename)


# --------------------------------------------------------------------------
# Malformed input must not be reported as "no dependencies"
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("basename", "body"),
    [
        ("package.json", "{not json"),
        ("pyproject.toml", "[project\nbroken"),
        ("cargo.toml", "[dependencies\n="),
    ],
)
def test_unparseable_manifest_raises_rather_than_returning_empty(basename: str, body: str) -> None:
    """An empty set would read as 'this person declared nothing' (norms §1)."""
    with pytest.raises(ManifestParseError):
        declared_dependencies(basename, body)


def test_absent_dependency_section_is_an_empty_set_not_an_error() -> None:
    """A manifest that genuinely declares nothing is a real observation."""
    assert declared_dependencies("package.json", '{"name": "widget"}') == set()


def test_case_is_normalised_but_names_are_preserved() -> None:
    """Basenames are matched case-insensitively; package names are not folded."""
    assert is_supported_manifest("Package.json")
    assert declared_dependencies("Package.json", '{"dependencies": {"React-DOM": "^18"}}') == {
        "React-DOM"
    }
