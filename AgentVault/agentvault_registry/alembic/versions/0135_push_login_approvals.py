"""0135 — PUSH LOGIN: approve a sign-in from your phone with a fingerprint (2026-07-25).

A second factor that is faster than typing a code and strictly stronger than one: instead of a
6-digit TOTP, the account holder's enrolled phone gets a push, and approving it requires the same
WebAuthn user-verification (fingerprint / device PIN) the Cockpit Card uses. The desktop never
sees a secret, and a stolen password alone gets nobody in.

`login_approvals` is deliberately its own table rather than a reuse of `liability_challenges`:
those are bound to a mandate by foreign key, and a sign-in has no mandate. Same shape though —
short-lived, single-use, expiry counts as refusal.

`developers.push_login_enabled` opts an account in; default false, so nothing changes for anyone
who has not asked for it.

IDEMPOTENT — replays every boot. Chains 0134.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0135_push_login_approvals"
down_revision: str = "0134_webauthn_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS login_approvals (
            id              VARCHAR(44) PRIMARY KEY,           -- lgn_<hex>
            developer_id    INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            challenge_hash  VARCHAR(64) NOT NULL,              -- what the phone signs
            nonce           VARCHAR(32) NOT NULL,
            status          VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending|approved|denied|expired|consumed
            method          VARCHAR(16),                       -- webauthn_uv
            device_id       INTEGER,
            requested_ip    VARCHAR(64),
            requested_ua    VARCHAR(255),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at      TIMESTAMPTZ NOT NULL,
            resolved_at     TIMESTAMPTZ
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_login_approvals_dev ON login_approvals (developer_id, status)"))
    bind.execute(text("ALTER TABLE developers ADD COLUMN IF NOT EXISTS push_login_enabled BOOLEAN NOT NULL DEFAULT false"))


def downgrade() -> None:
    pass
