"""Flare-gated cloud-op provisioning — eligibility ledger on Developer (2026-05-11).

Revision ID: 0040_provisioning_eligibility
Revises: 0039_fiat_wall_display

Adds two opt-in eligibility fields to `developers` so the fiat onramp can
credit cloud-op self-provisioning unlock-time as a side-effect of backing
the network. The math is kept on the Developer row (no separate ledger
table) because purchase history already lives in `fiat_purchases` — the
summary fields here are just the rolling state needed for the gate.

  • provisioning_unlocked_until  TIMESTAMPTZ   NULLABLE
      Cutoff timestamp. NULL = never backed → not eligible. Past timestamp
      = eligibility expired → not eligible. Future timestamp = eligible.
      Stacking math at credit time: max(unlocked_until, NOW) + months×30d.

  • provisioning_months_total    INT NOT NULL DEFAULT 0
      Cumulative months credited across the developer's lifetime — used by
      the Eligibility tab to show "you've extended N months total" + as a
      tiny audit trail. Never decremented (refunds don't claw eligibility).

A partial index over rows that have a non-null `provisioning_unlocked_until`
keeps the eligibility-check query cheap as the table grows.

All defaults preserve existing rows' behavior — every dev starts NULL/0,
so the gate yields 402 by default until they back the network. Older code
that doesn't read these fields keeps working (same backward-compat shape
as 0039_fiat_wall_display).
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0040_provisioning_eligibility'
down_revision: Union[str, None] = '0039_fiat_wall_display'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IDEMPOTENT — every post-squash migration MUST replay cleanly because
    # migration_bridge.py resets alembic_version to 0001_squash on every
    # container boot (deliberate post-squash design). Use raw SQL with
    # IF NOT EXISTS guards rather than op.add_column() / op.create_index()
    # which are NOT idempotent and crash with DuplicateColumn / DuplicateTable
    # on second boot. Reference: project_migration_idempotency.md (memory),
    # 0039_fiat_wall_display.py (most recent precedent).
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE developers "
        "ADD COLUMN IF NOT EXISTS provisioning_unlocked_until TIMESTAMPTZ NULL"
    ))
    bind.execute(text(
        "ALTER TABLE developers "
        "ADD COLUMN IF NOT EXISTS provisioning_months_total INTEGER NOT NULL DEFAULT 0"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_developers_provisioning_unlocked "
        "ON developers (provisioning_unlocked_until) "
        "WHERE provisioning_unlocked_until IS NOT NULL"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ix_developers_provisioning_unlocked"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS provisioning_months_total"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS provisioning_unlocked_until"))
