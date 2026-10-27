"""§FRAMELIC (2026-09-07) — a FRAME gets a licence like an operator does, and a service account hides its agents.

TWO columns, one migration, because both are birth-time properties of the standup his 2026-09-07 word ordered:

  federation_licenses.licensee_type   'operator' | 'frame'  (default 'operator')
      `federation_licenses` was already generic except for its column NAMES (`operator_name`,
      `operator_did`) and its docstring: a key, a hash, a status, a tier, limits, a last-seen clock and a
      revoke/suspend/reinstate lifecycle. A second table would have meant a second lifecycle, a second
      audit trail and a second revoke path that could drift from this one. A discriminator keeps ONE of
      each and lets `verify_federation_license` refuse a frame key presented by an operator (and back).
      Every existing row IS an operator licence — that is what the backfill default says.

  developers.agents_unlisted_by_default  bool (default false)
      His: "we also need an option to hide system agents like eigentrust sim agents fx router etc from
      discovery. we might need a flag for service accounts to hide their agents if no other option
      exists." The other option DOES exist — `agent_cards.unlisted` (§DISCREFINE, mig 0153) already
      removes a card from the page, the facets AND the tag counts while leaving a direct DID lookup
      working. What was missing is the thing that SETS it. This flag rides on the owning developer, so
      a service account (svc-sim, svc-canary, svc-provisioning, svc-market) hides its agents by
      construction and nobody has to remember at each mint. Owner and admin can still flip either.

Revision ID: 0176_frame_licence_and_svc
Revises: 0175_teg_audit_policy_rows
"""
from alembic import op
import sqlalchemy as sa

revision = "0176_frame_licence_and_svc"
down_revision = "0175_teg_audit_policy_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "federation_licenses",
        sa.Column(
            "licensee_type", sa.String(20), nullable=False, server_default="operator",
            comment="Who this licence is for: 'operator' (a cloud operator) or 'frame' (a sovereign frame)",
        ),
    )
    op.create_index(
        "ix_federation_licenses_licensee_type", "federation_licenses", ["licensee_type"],
    )
    op.add_column(
        "developers",
        sa.Column(
            "agents_unlisted_by_default", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
            comment="Service-account flag: every agent card this developer mints starts unlisted",
        ),
    )


def downgrade() -> None:
    op.drop_column("developers", "agents_unlisted_by_default")
    op.drop_index("ix_federation_licenses_licensee_type", table_name="federation_licenses")
    op.drop_column("federation_licenses", "licensee_type")
