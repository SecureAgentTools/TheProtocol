"""V0650 (f) (2026-10-31) — a Guild order may name the agent it is meant for.

Order gwo_754cf6912ebece4f1487363a. ONE nullable column on `guild_work_orders`, nothing else touched:
`intended_worker_did`, written by POST /api/v1/guild/orders (and the organization door that posts through it) when the
poster names an agent DID. It is a flag, never a gate: anyone may still bid, and a bid from another agent is accepted
and marked `not_intended_worker`, derived at read time from this column and the bid's `bidder_did`, so nothing is
stored on `guild_bids`. The commits a delivery links ride the existing `deliverable` JSONB (`deliverable.commits`) and
need no column. No index, no default, no backfill: an order posted before this migration names nobody.

The column is added to a table several readers select with `SELECT *` (routers/guild.py `_load`, the contract mirror,
the organization door). Recreate the registries right after the pre-apply: behind pgbouncer, a prepared `SELECT *` of
the image before can fail with "cached plan must not change result type" until then (§JSONCAST-3); the new image's
statements are new texts through the per-release statement tag (core/release_sql_tag.py, D6-815).

Rolling back past this is the two-step rule (downgrade first from an image that has it, then the older image).
Dropping the column drops which orders named a worker; commits already stored stay in the deliverable, and the image
before shows them as part of it.

Revision ID: 0200_guild_intended_worker
Revises: 0199_agent_status_lines
"""
from alembic import op
import sqlalchemy as sa

revision = "0200_guild_intended_worker"
down_revision = "0199_agent_status_lines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guild_work_orders", sa.Column("intended_worker_did", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("guild_work_orders", "intended_worker_did")
