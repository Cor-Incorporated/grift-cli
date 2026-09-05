"""identity-v2 falsification and v1 compatibility."""

from __future__ import annotations

from pathlib import Path

import pytest

from tep_core.identity import (
    RECORDED_EXPLICIT_CONSENT,
    IdentityValidationError,
    email_identity_sha256,
    has_recorded_explicit_consent,
    identity_digest,
    load_identity,
    select_actor,
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "identity.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_email_sha256_has_fixed_domain_and_normalization() -> None:
    expected = "b6b35853407040af2b8ad9c5570e64511c9a760ab0b65ce10339120f3727aff0"
    assert email_identity_sha256(" User@Example.COM ") == expected
    assert email_identity_sha256("user@example.com") == expected


def test_v2_hashed_email_resolves_without_plaintext(tmp_path: Path) -> None:
    digest = email_identity_sha256("alice@example.com")
    identity = load_identity(
        _write(
            tmp_path,
            'schema_version = "identity-v2"\n\n'
            '[[actors]]\ncanonical_id = "alice"\n'
            f'email_sha256 = ["{digest}"]\nattribution_state = "verified"\n',
        )
    )
    actor = identity.actor_for_email(" ALICE@example.com ")
    assert actor is not None
    assert actor.canonical_id == "alice"
    assert actor.emails == ()
    assert actor.email_sha256 == (digest,)
    assert identity.is_tenant_email("alice@example.com") is True
    selected = select_actor(identity, "alice")
    assert selected.actor_for_email("alice@example.com") is not None
    assert identity_digest(selected) == identity_digest(identity)


def test_identity_v1_remains_read_compatible(tmp_path: Path) -> None:
    identity = load_identity(
        _write(
            tmp_path,
            'schema_version = "identity-v1"\nlegacy_extension = "preserved-tolerance"\n\n'
            '[[actors]]\ncanonical_id = "alice"\n'
            'emails = [" Alice@Example.COM "]\ngithub_login = "alice"\n'
            'attribution_state = "claimed"\n',
        )
    )
    assert identity.schema_version == "identity-v1"
    assert identity.actor_for_email("alice@example.com").canonical_id == "alice"  # type: ignore[union-attr]
    assert identity_digest(identity) == (
        "1c10f14c1e62c6fc4c073cd70eb4000e173c68fb68d91c6637929ab66a3e763b"
    )


def test_explicit_consent_and_authority_are_closed_and_digest_bound(tmp_path: Path) -> None:
    base = (
        'schema_version = "identity-v2"\n\n'
        '[[actors]]\ncanonical_id = "alice"\n'
        'emails = ["alice@example.com"]\nattribution_state = "claimed"\n'
    )
    without_consent = load_identity(_write(tmp_path, base))
    with_consent = load_identity(
        _write(
            tmp_path,
            base
            + 'consent = "recorded-explicit-consent"\n'
            + 'authority = "subject-authorization"\n',
        )
    )

    actor = with_consent.actors[0]
    assert actor.consent == RECORDED_EXPLICIT_CONSENT
    assert actor.authority == "subject-authorization"
    assert has_recorded_explicit_consent(actor) is True
    assert identity_digest(with_consent) != identity_digest(without_consent)


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ('consent = "assumed"\n', "consent must be"),
        ('consent = "recorded-explicit-consent"\n', "requires an explicit authority"),
        ('authority = "github-login"\n', "authority must be one of"),
        (
            'attribution_state = "inferred"\nconsent = "recorded-explicit-consent"\n'
            'authority = "subject-authorization"\n',
            "consent requires attribution_state",
        ),
    ],
)
def test_identity_consent_contract_rejects_unknown_or_incoherent_values(
    tmp_path: Path, fields: str, match: str
) -> None:
    state = "" if fields.startswith("attribution_state") else 'attribution_state = "verified"\n'
    with pytest.raises(IdentityValidationError, match=match):
        load_identity(
            _write(
                tmp_path,
                'schema_version = "identity-v2"\n\n'
                '[[actors]]\ncanonical_id = "alice"\n'
                'emails = ["alice@example.com"]\n' + state + fields,
            )
        )


def test_identity_v1_consent_extension_remains_readable_but_never_unlocks_observation(
    tmp_path: Path,
) -> None:
    identity = load_identity(
        _write(
            tmp_path,
            'schema_version = "identity-v1"\n\n'
            '[[actors]]\ncanonical_id = "alice"\n'
            'emails = ["alice@example.com"]\nattribution_state = "verified"\n'
            'consent = "recorded-explicit-consent"\n'
            'authority = "subject-authorization"\n',
        )
    )

    assert identity.actors[0].consent == RECORDED_EXPLICIT_CONSENT
    assert has_recorded_explicit_consent(identity.actors[0]) is False


def test_v2_rejects_plaintext_and_digest_in_same_actor(tmp_path: Path) -> None:
    digest = email_identity_sha256("alice@example.com")
    with pytest.raises(IdentityValidationError, match="not both"):
        load_identity(
            _write(
                tmp_path,
                'schema_version = "identity-v2"\n\n'
                '[[actors]]\ncanonical_id = "alice"\n'
                f'emails = ["alice@example.com"]\nemail_sha256 = ["{digest}"]\n',
            )
        )


def test_v2_rejects_duplicate_normalized_plaintext(tmp_path: Path) -> None:
    with pytest.raises(IdentityValidationError, match="duplicate normalized"):
        load_identity(
            _write(
                tmp_path,
                'schema_version = "identity-v2"\n\n'
                '[[actors]]\ncanonical_id = "alice"\n'
                'emails = ["Alice@example.com", " alice@EXAMPLE.com "]\n',
            )
        )


def test_v2_rejects_digest_reuse_across_actors_and_forms(tmp_path: Path) -> None:
    digest = email_identity_sha256("alice@example.com")
    with pytest.raises(IdentityValidationError, match="multiple actors"):
        load_identity(
            _write(
                tmp_path,
                'schema_version = "identity-v2"\n\n'
                '[[actors]]\ncanonical_id = "alice"\nemails = ["alice@example.com"]\n\n'
                '[[actors]]\ncanonical_id = "other"\n'
                f'email_sha256 = ["{digest}"]\n',
            )
        )


@pytest.mark.parametrize(
    "body,match",
    [
        ('schema_version = "identity-v2"\nextra = true\n', "unknown key"),
        (
            'schema_version = "identity-v2"\n[tenant]\nemail_patterns = []\nextra = true\n',
            "unknown key",
        ),
        (
            'schema_version = "identity-v2"\n[[actors]]\ncanonical_id = "alice"\nextra = true\n',
            "unknown key",
        ),
        (
            'schema_version = "identity-v2"\n[[actors]]\ncanonical_id = "alice"\n'
            'email_sha256 = ["NOT-A-DIGEST"]\n',
            "64 lowercase hex",
        ),
        (
            'schema_version = "identity-v2"\n[[actors]]\ncanonical_id = "alice"\n'
            f'email_sha256 = ["{"A" * 64}"]\n',
            "64 lowercase hex",
        ),
        ('schema_version = "identity-v9"\n', "unsupported"),
    ],
)
def test_v2_closed_shape_and_digest_validation(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(IdentityValidationError, match=match):
        load_identity(_write(tmp_path, body))
