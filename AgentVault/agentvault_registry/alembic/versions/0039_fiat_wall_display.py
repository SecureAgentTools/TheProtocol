"""Founders Wall personalization — display_name + display_country + show_on_wall (2026-05-10).

Revision ID: 0039_fiat_wall_display
Revises: 0038_fiat_routed

Adds opt-in personalization fields to fiat_purchases so backers can choose
what shows on the public Founders Wall chip:

  • display_name     VARCHAR(32) NULLABLE
      Buyer-supplied public handle. Server sanitizes (URL strip, char
      allowlist, length cap) before persisting. NULL = anonymous chip.
  • display_country  CHAR(2)     NULLABLE
      ISO 3166-1 alpha-2 country code. Prefilled browser-side from the user's
      locale (Intl.Locale.region) — never IP-derived on the backend, so no
      GDPR-relevant geolocation processing happens server-side. NULL = no flag.
  • show_on_wall     BOOLEAN     NOT NULL DEFAULT TRUE
      Master opt-out. When false, the row is filtered out of /fiat/stats/public
      and the FoundersWall feed entirely (still kept in DB for accounting).

All defaults preserve existing rows' anonymized behavior. Backward-compatible
across the cluster: older registry code that doesn't read these columns
keeps working; newer code reads NULL/true safely.

The new index on show_on_wall powers the WHERE-filter on the public stats
+ FoundersWall list endpoints — most rows have show_on_wall=true so the
index is selective enough to be useful when a non-trivial fraction opt out.
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0039_fiat_wall_display'
down_revision: Union[str, None] = '0038_fiat_routed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IDEMPOTENT — every post-squash migration MUST replay cleanly because
    # migration_bridge.py resets alembic_version to 0001_squash on every
    # container boot (deliberate post-squash design). Use raw SQL with
    # IF NOT EXISTS guards rather than op.add_column() / op.create_index()
    # which are NOT idempotent and crash with DuplicateColumn / DuplicateTable
    # on second boot. Reference: project_migration_idempotency.md (memory).
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE fiat_purchases "
        "ADD COLUMN IF NOT EXISTS display_name VARCHAR(32) NULL"
    ))
    bind.execute(text(
        "ALTER TABLE fiat_purchases "
        "ADD COLUMN IF NOT EXISTS display_country VARCHAR(2) NULL"
    ))
    bind.execute(text(
        "ALTER TABLE fiat_purchases "
        "ADD COLUMN IF NOT EXISTS show_on_wall BOOLEAN NOT NULL DEFAULT TRUE"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_fiat_purchases_show_on_wall "
        "ON fiat_purchases (show_on_wall)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ix_fiat_purchases_show_on_wall"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS show_on_wall"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS display_country"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS display_name"))
