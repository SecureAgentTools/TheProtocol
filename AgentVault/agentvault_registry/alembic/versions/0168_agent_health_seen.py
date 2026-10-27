"""§COCKPITA R2 (§RUNTIME) — when the health verdict was last EARNED, not just what it says.

`agents.last_health` has held a word ("healthy"/"unhealthy"/"unreachable") since
migration 0055, with nothing recording WHEN that word was written. Two defects follow
from the missing timestamp, and both were measured on registry-a before this migration
was written:

  1. A VERDICT WITH NO AGE IS INDISTINGUISHABLE FROM A FOSSIL. Greedy Gregory read
     `unreachable` while serving traffic on :8048 and answering 200 at
     https://gregory.theprotocol.cloud/health. Six of the eleven sovereign agents were
     misreported the same way. The words were not wrong when written; they simply could
     never be rewritten, because `agent_health_checker` selects its candidates on
     `card_data->>'url'` and the canonicalized A2A cards carry no such key — their
     address lives in `supportedInterfaces[].url`. The checker could see 4,098 sim
     agents and ZERO of the eleven real ones. This is the §CARDPULLTICK class: alert on
     the AGE of the last completed check, never on the value it left behind.

  2. `LIMIT 100` WITH NO `ORDER BY` IS NOT A SWEEP, IT IS A LOTTERY. Over a candidate
     set of ~4,098 the same rows can be probed forever while others are never probed at
     all. Ordering by this column NULLS FIRST turns the same limit into fair
     round-robin: never-checked first, then least-recently-checked.

Additive and nullable: the older image neither writes nor reads it, so this can be
pre-applied while the previous version still serves.
"""
from alembic import op
import sqlalchemy as sa

revision = "0168_agent_health_seen"
down_revision = "0167_consent_previews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True))
    # NULLS FIRST ordering is the point of the index: the sweep must reach the agents it
    # has never reached before it re-probes the ones it just did.
    op.create_index("ix_agents_last_health_at", "agents", ["last_health_at"])


def downgrade() -> None:
    op.drop_index("ix_agents_last_health_at", table_name="agents")
    op.drop_column("agents", "last_health_at")
