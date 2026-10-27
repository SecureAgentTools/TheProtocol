"""B4 (RBAC plan) — richer spend-policy axes: rate_per_hour + geo_allow.

Two new NULLABLE columns on agent_spend_policies (the per-agent policy half of B4;
the capability-token half is pure JSONB caveats and needs no schema):

- rate_per_hour: max spend ATTEMPTS per rolling hour, counted in a Redis window at the
  gate (velocity_metrics only materializes completed hours — an hour of lag guts a
  burst limiter, so the live counter lives in Redis, not here).
- geo_allow: registry names where this agent's spends may EXECUTE — each registry
  checks its own name, which is what gives the axis teeth for authority that travels
  cross-frame. NULL = unconstrained.

Additive only. Revision ID: 0148_spend_caveats
Revises: 0147_spend_approvals
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0148_spend_caveats"
down_revision = "0147_spend_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_spend_policies",
                  sa.Column("rate_per_hour", sa.Integer, nullable=True))
    op.add_column("agent_spend_policies",
                  sa.Column("geo_allow", postgresql.ARRAY(sa.Text), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_spend_policies", "geo_allow")
    op.drop_column("agent_spend_policies", "rate_per_hour")
