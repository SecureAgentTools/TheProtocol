"""D6-802 (2026-10-17) — an administrator's IRONHAND revoke is recorded on the agent.

The admin revoke (POST /api/v1/admin/ironhand/revoke/{did}) cleared the agent's mTLS state exactly as the agent's own
unenrol does, and the agent stays active, so its own POST /api/v1/agent/enable-mtls enrolled it again at once. No column
could tell the two apart: `spiffe_id` is the identity (and, with mtls_enabled false, a coordinated suspension's restore
marker), `status` and `enforcement_status` stop the agent's whole economic life, and the agent card is the owner's.

ONE nullable column on `agents`, nothing else touched: `mtls_revoked_at`, set by the admin revoke, cleared by an
administrator's enrolment (POST /api/v1/admin/ironhand/enroll/{did}, POST /api/v1/admin/agents/{did}/force-mtls-enrol).
No backfill: a revoke made before this migration is not recorded (the agents an administrator revoked earlier can be
revoked again to record it).

Rolling back past this is the two-step rule (downgrade first from an image that has it, then the older image). Dropping
the column drops the record of those revokes.

Revision ID: 0192_agent_mtls_revoked_at
Revises: 0191_idempotency_kept
"""
from alembic import op
import sqlalchemy as sa

revision = "0192_agent_mtls_revoked_at"
down_revision = "0191_idempotency_kept"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("mtls_revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "mtls_revoked_at")
