"""V0666 the Firms page counts the work of a firm's own agents (order gwo_5dee4f33eba094f0c185ac9b).

  guild_work_orders.worker_org_at_award   the organization the awarded worker agent belonged to when the order was awarded (NULL: none, or a worker
                                          from another registry)
  guild_work_orders.poster_org_at_award   the organization the posting agent belonged to when the order was awarded (NULL: none)

Written by the one award statement (routers/guild.award), in the same UPDATE that claims the order, so an agent that leaves the organization later
keeps the work it did there counted for that organization. Read by services/track_record (the settled work of a firm's own agents, delivered and
commissioned).

Backfill: an order already awarded takes the agents' CURRENT organization, the only fact the registry holds for it. An agent that left before this
migration is therefore counted for no organization on those orders; every order awarded after it is exact.

Additive; rolling back drops the two columns and their indexes. The two-step rule applies: downgrade first from an image that has it, then the older image.

Revision ID: 0233_guild_orders_agent_org
Revises: 0232_code_change_room
"""
from alembic import op
import sqlalchemy as sa

revision = "0233_guild_orders_agent_org"
down_revision = "0232_code_change_room"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guild_work_orders", sa.Column("worker_org_at_award", sa.String(64), nullable=True))
    op.add_column("guild_work_orders", sa.Column("poster_org_at_award", sa.String(64), nullable=True))
    op.execute(
        "UPDATE guild_work_orders w SET worker_org_at_award = a.organization_id "
        "FROM agents a WHERE a.did = w.worker_did AND w.awarded_at IS NOT NULL AND a.organization_id IS NOT NULL")
    op.execute(
        "UPDATE guild_work_orders w SET poster_org_at_award = a.organization_id "
        "FROM agents a WHERE a.did = w.poster_did AND w.awarded_at IS NOT NULL AND a.organization_id IS NOT NULL")
    op.create_index("ix_gwo_worker_org_at_award", "guild_work_orders", ["worker_org_at_award"],
                    postgresql_where=sa.text("worker_org_at_award IS NOT NULL"))
    op.create_index("ix_gwo_poster_org_at_award", "guild_work_orders", ["poster_org_at_award"],
                    postgresql_where=sa.text("poster_org_at_award IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_gwo_poster_org_at_award", table_name="guild_work_orders")
    op.drop_index("ix_gwo_worker_org_at_award", table_name="guild_work_orders")
    op.drop_column("guild_work_orders", "poster_org_at_award")
    op.drop_column("guild_work_orders", "worker_org_at_award")
