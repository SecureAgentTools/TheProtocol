"""0134 — WEBAUTHN: biometric-enforced device credentials (2026-07-25).

The Cockpit Card's confirmation signature moves from a WebCrypto key (which signs silently) to a
WebAuthn platform credential (which the OS refuses to use without a fingerprint or device PIN, and
which proves it via the UV flag inside the signed authenticator data).

Rides the same device row: `credential_id` + COSE public key + `sign_count` (monotonic clone
detector). The old `pubkey_jwk`/`key_alg` columns stay for rollback and are simply unused once a
device re-enrols.

IDEMPOTENT — replays every boot. Chains 0133.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0134_webauthn_credentials"
down_revision: str = "0133_webpush_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for col, ddl in (
        ("webauthn_credential_id", "TEXT"),
        ("webauthn_public_key", "TEXT"),      # COSE_Key, base64url
        ("webauthn_sign_count", "BIGINT"),
        ("webauthn_enrolled_at", "TIMESTAMPTZ"),
    ):
        bind.execute(text(f"ALTER TABLE device_push_registrations ADD COLUMN IF NOT EXISTS {col} {ddl}"))


def downgrade() -> None:
    pass
