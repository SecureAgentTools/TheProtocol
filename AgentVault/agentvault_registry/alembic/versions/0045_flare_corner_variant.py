"""Add flare_corner_variant column to developers (PB-1 §20, 2026-05-13).

Revision ID: 0045_flare_corner_variant
Revises: 0044_flare_selection_backfill

§20 ships admin-only corner badge variants (rocket / crown / vault / gavel /
atom / network) — alternate inline-SVG designs that admins can wear instead
of the default tier icon (mdi:hexagon-multiple-outline for operator,
mdi:crown for commander). Mirrors the encirclement variant axis added in
§14 / §15.3 / §18 / §19.

The variant is OPTIONAL — NULL means "use default tier icon." Only admins
(is_admin OR any admin_* sub-flag) can SET non-null values via PATCH
/fiat/flare/selection {"corner_variant": "rocket"}.

Migration uses raw SQL with IF NOT EXISTS so it's idempotent on every
sandbox boot (migration_bridge resets to 0001_squash and replays the chain).
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0045_flare_corner_variant'
down_revision: Union[str, None] = '0044_flare_selection_backfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE developers
        ADD COLUMN IF NOT EXISTS flare_corner_variant VARCHAR(20) NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE developers DROP COLUMN IF EXISTS flare_corner_variant
    """))
