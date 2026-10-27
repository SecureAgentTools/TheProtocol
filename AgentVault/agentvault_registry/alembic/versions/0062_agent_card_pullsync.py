"""Add last_pulled_at + last_pulled_etag to agent_cards for Option C Phase 3 pull-sync.

Revision ID: 0062_agent_card_pullsync
Revises: 0061_registry_self
Create Date: 2026-05-17

§pass36 Option C Phase 3 — pull-sync worker reads its own watermark + ETag so:
  - 304 short-circuit on unchanged cards (cheap, no body)
  - stats endpoint exposes per-agent last-pull state

Also seeds the `AgentCardPulled` event_emission_policies row so the worker can
emit drift-audit events without hitting the permissive default.

Idempotency
-----------
`migration_bridge.py` resets alembic_version to `0001_squash` on every container
boot (post-squash design — `project_migration_idempotency.md`). Every
post-squash migration MUST therefore be replay-safe. This migration uses raw
SQL with `IF NOT EXISTS` / `ON CONFLICT DO NOTHING` per the 0061 / 0060 / 0011
precedent. NEVER use plain `op.add_column()` here — crash-loop on second boot.
"""
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '0062_agent_card_pullsync'
down_revision = '0061_registry_self'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add pull-sync watermark columns to agent_cards.
    bind.execute(text("""
        ALTER TABLE agent_cards
          ADD COLUMN IF NOT EXISTS last_pulled_at   TIMESTAMP WITH TIME ZONE,
          ADD COLUMN IF NOT EXISTS last_pulled_etag VARCHAR(128)
    """))

    # 2. Index for "find agents needing a refresh" queries (cheap nulls-first).
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_agent_cards_last_pulled_at
        ON agent_cards (last_pulled_at NULLS FIRST)
    """))

    # 3. Seed event_emission_policy for `AgentCardPulled`.
    #    Registry emits (worker is registry-side), skip in projection (audit
    #    trail only — no balance impact). Permissive-default would also allow
    #    it but an explicit row keeps the policy table self-documenting.
    #    NB: event_emission_policies has no `created_at` column (verified
    #    against live schema 2026-05-17), only `updated_at`.
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection,
           description, updated_at)
        VALUES
          ('AgentCardPulled', false, true, true,
           'Option C Phase 3 — agent_card_pullsync worker fetched an agent''s well-known card. Emitted only on detected drift vs stored card_data. Audit trail; not balance-impacting.',
           NOW())
        ON CONFLICT (event_type) DO NOTHING
    """))

    # Option C Phase 6 — admin-flagged drift event. Emitted when a Commander
    # uses /admin/agent-card-drift/{did}/force-register to record concern
    # about an agent's well-known card content.
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection,
           description, updated_at)
        VALUES
          ('CommanderFlaggedDrift', false, true, true,
           'Option C Phase 6 — admin operator flagged an agent-card drift for follow-up. Recorded for audit; the registry does not push changes to the agent.',
           NOW())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "DELETE FROM event_emission_policies WHERE event_type = 'AgentCardPulled'"
    ))
    bind.execute(text("DROP INDEX IF EXISTS ix_agent_cards_last_pulled_at"))
    bind.execute(text("""
        ALTER TABLE agent_cards
          DROP COLUMN IF EXISTS last_pulled_etag,
          DROP COLUMN IF EXISTS last_pulled_at
    """))
