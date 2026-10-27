"""REGAUTH (SPEC 2026-08-15) — recorded regulatory authorizations.

Jurisdiction Profiles v1 can deny a feature outright; this table adds the third
state: allowed only with a recorded state authorization. One row = one attested
approval (the state's reference id + optional evidence hash + optional
countersigned contract ref). Expiry is computed from valid_until at read time
(self-retiring, no sweeper); revocation is status-only. Renewals are NEW rows.

Additive only. Revision ID: 0150_regulatory_auth
Revises: 0149_org_owner_transfer
"""
from alembic import op
import sqlalchemy as sa

revision = "0150_regulatory_auth"
down_revision = "0149_org_owner_transfer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regulatory_authorizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("subject_ref", sa.String(255), nullable=True),  # NULL = registry scope
        sa.Column("authority", sa.String(200), nullable=False),
        sa.Column("jurisdiction", sa.String(120), nullable=False),
        sa.Column("reference_id", sa.String(255), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_hash", sa.String(80), nullable=True),
        sa.Column("evidence_note", sa.Text, nullable=True),
        sa.Column("contract_ref", sa.String(255), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),  # active|revoked
        sa.Column("recorded_by_dev_id", sa.Integer, sa.ForeignKey("developers.id"), nullable=False),
        sa.Column("presence_method", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_regauth_action_subject_status",
        "regulatory_authorizations",
        ["action", "subject_ref", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_regauth_action_subject_status", table_name="regulatory_authorizations")
    op.drop_table("regulatory_authorizations")
