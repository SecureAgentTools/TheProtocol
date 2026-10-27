"""Create registry_self singleton table for canonical federation identity (§pass34).

Revision ID: 0061_registry_self
Revises: 0060_canary_paths_transport
Create Date: 2026-05-17

§pass34 — Decouple federation identity from developer profile.

Problem
-------
Until now `federation_sync._get_display_name()` returned the first admin
developer's `display_name` field, which was DUAL-PURPOSED as both:
  1. Personal handle exposed in Settings.vue (user-editable via PUT /developers/me)
  2. Federation identity used to stamp `card_data.federation_metadata.origin_registry_name`
     and check `is_native_card` on export

When a mainframe admin edits their personal display_name (Commander → 'Commander'),
the federation identity drifts. `is_native_card` evaluates False on every
pre-drift card → flare never re-stamped → peers see no flare on native agents.

Fix
---
New singleton table `registry_self` holds the canonical federation identity
of this specific registry. Cannot drift with developer profile changes.

  - Cloud-ops: provisioner inserts the row with safe_name from OperatorApplication.name
  - Mainframes: env REGISTRY_FEDERATION_NAME seeds the row at first boot
  - Existing live registries: this migration seeds from REGISTRY_FEDERATION_NAME
    env if set; falls back to first admin's display_name (current behaviour);
    final fallback to REGISTRY_NAME env.

Idempotency
-----------
`migration_bridge.py` resets alembic_version to `0001_squash` on every container
boot (post-squash design — see `project_migration_idempotency.md`). Every
post-squash migration MUST therefore be replay-safe. This migration uses raw
SQL with `IF NOT EXISTS` / `ON CONFLICT DO NOTHING` per the 0011/0060 precedent.
"""
import os
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '0061_registry_self'
down_revision = '0060_canary_paths_transport'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create the table. IF NOT EXISTS makes this replay-safe — required because
    #    migration_bridge resets alembic_version on every boot (see module docstring).
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS registry_self (
            id              INTEGER PRIMARY KEY DEFAULT 1,
            federation_name VARCHAR(64) NOT NULL,
            created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT registry_self_singleton_chk CHECK (id = 1)
        )
    """))

    # 2. Unique index on federation_name (idempotent).
    bind.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_registry_self_federation_name
        ON registry_self (federation_name)
    """))

    # 3. Seed exactly one row. Resolution order mirrors the new _get_display_name
    #    fallback chain:
    #      a) REGISTRY_FEDERATION_NAME env (the right answer going forward)
    #      b) first admin developer's display_name (legacy behaviour — what
    #         _get_display_name used to return)
    #      c) REGISTRY_NAME env (compose-level identity)
    #      d) literal 'Unknown Registry' (last resort)
    seed = os.environ.get('REGISTRY_FEDERATION_NAME', '').strip()

    if not seed:
        try:
            result = bind.execute(text(
                "SELECT display_name FROM developers "
                "WHERE is_admin = true AND display_name IS NOT NULL AND display_name != '' "
                "ORDER BY id LIMIT 1"
            )).first()
            if result and result[0]:
                seed = str(result[0]).strip()
        except Exception:
            seed = ''

    if not seed:
        seed = os.environ.get('REGISTRY_NAME', '').strip()

    if not seed:
        seed = 'Unknown Registry'

    # Idempotent INSERT — re-running the migration is a no-op once the singleton
    # row exists. Does NOT update federation_name if the row is already there;
    # renames must go through an explicit admin endpoint with proper cascade.
    bind.execute(
        text(
            "INSERT INTO registry_self (id, federation_name) VALUES (1, :name) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(name=seed)
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS uq_registry_self_federation_name"))
    bind.execute(text("DROP TABLE IF EXISTS registry_self"))
