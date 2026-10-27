"""peer_registries: deactivated_reason + deactivated_at (RCA 2026-07-10 — federation-peer ratchet)

Additive, idempotent (IF NOT EXISTS), nullable — NULL = legacy/unknown, which the
revival prober treats as revivable. Reasons in the ADMIN GUARD SET
(admin_deactivated / owner_deactivated / operator_revoked / license_suspended /
federation_revoked / self_echo / duplicate_frame / rename_debris) are never
auto-revived. See RCA_2026-07-10_FEDERATION_PEER_RATCHET.md.

Revision ID: 0122_peer_deactivation_reason
Revises: 0121_exchange_read_path_indexes
"""
from alembic import op

revision: str = "0122_peer_deactivation_reason"
down_revision: str = "0121_exchange_read_path_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE peer_registries "
        "ADD COLUMN IF NOT EXISTS deactivated_reason VARCHAR(64) NULL"
    )
    op.execute(
        "ALTER TABLE peer_registries "
        "ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    # Additive-only doctrine: leave columns in place on downgrade
    # (rolling back to an older image with these columns present is harmless).
    pass
