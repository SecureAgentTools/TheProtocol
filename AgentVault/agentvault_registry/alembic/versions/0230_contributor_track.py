"""V0665 the contributor track (order gwo_5e0701efdef9d3989491bc37; room seq 4063, 4070, 4081).

  cosmetic_unlocks   one row per developer and earned item: kind (corner | encirclement | overlay | title), the item's key, its tier (NULL off the
                     main row), when it was unlocked and by what (a code change id, a season, or the backfill). UNIQUE (developer_id, kind,
                     item_key): the evaluator writes each item once (INSERT ... ON CONFLICT DO NOTHING). Written by services/contributor_track
                     and by nothing else.
  developers.flare_title   the equipped title's key (NULL = none): one at a time, shown under the name.

The closed word `kind` carries a CHECK (a new word needs a migration widening it: memory, V0659). Additive; rolling back drops the column and the
table (the equipped title and the unlock records go with them). The two-step rule applies: downgrade first from an image that has it, then the
older image.

Revision ID: 0230_contributor_track
Revises: 0229_proxy_status
"""
from alembic import op
import sqlalchemy as sa

revision = "0230_contributor_track"
down_revision = "0229_proxy_status"
branch_labels = None
depends_on = None

KINDS = ("corner", "encirclement", "overlay", "title")


def upgrade() -> None:
    op.create_table(
        "cosmetic_unlocks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("developer_id", sa.Integer, sa.ForeignKey("developers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("item_key", sa.String(64), nullable=False),
        sa.Column("tier", sa.Integer, nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.UniqueConstraint("developer_id", "kind", "item_key", name="uq_cosmetic_unlock"),
        sa.CheckConstraint("kind IN ('corner', 'encirclement', 'overlay', 'title')", name="ck_cosmetic_unlocks_kind"),
    )
    op.create_index("ix_cosmetic_unlocks_developer", "cosmetic_unlocks", ["developer_id"])
    op.add_column("developers", sa.Column("flare_title", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("developers", "flare_title")
    op.drop_index("ix_cosmetic_unlocks_developer", table_name="cosmetic_unlocks")
    op.drop_table("cosmetic_unlocks")
