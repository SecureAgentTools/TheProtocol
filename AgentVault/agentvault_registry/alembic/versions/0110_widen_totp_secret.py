"""0110 — widen developers.totp_secret 64→255 for Fernet-encrypted TOTP secrets (2026-07-05).

Fernet tokens are ~120-180 chars; the original varchar(64) only fits plaintext base32
secrets. Widening activates the at-rest encryption path in TwoFactorAuthService
(encrypt_secret/decrypt_secret) once TWO_FACTOR_ENCRYPTION_KEY is set — legacy plaintext
rows keep working via decrypt_secret's fallback and re-encrypt on next write.

Pure column widen: NO data touched, NO money path → Δ-irrelevant. Inert until the env
key is set (frame-c first).

IDEMPOTENT — replays every boot via migration_bridge. Chains 0109.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0110_widen_totp_secret"
down_revision: str = "0109_agent_capability_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Widen only if currently narrower — idempotent on replay.
    bind.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'developers'
                  AND column_name = 'totp_secret'
                  AND character_maximum_length IS NOT NULL
                  AND character_maximum_length < 255
            ) THEN
                ALTER TABLE developers ALTER COLUMN totp_secret TYPE VARCHAR(255);
            END IF;
        END $$;
    """))


def downgrade() -> None:
    # Never narrow back — a narrower column would truncate Fernet tokens and brick 2FA.
    # (House rule: additive migrations stay in place on rollback.)
    pass
