"""§pass63 (2026-05-22) — Drop Astraeus subsystem table.

The Astraeus space-MMO subsystem was removed entirely in §pass63. It only
ever materialized ONE Postgres table — `astraeus_game_events` (audit log of
ship/base/mission events; all other game state lived in Redis). This
migration drops it.

Idempotent — `DROP TABLE IF EXISTS ... CASCADE` so re-runs are safe (e.g.,
on a fresh DB where the table never existed). `downgrade()` intentionally
left as a no-op: we will not recreate.

Sovereign-immunity note ([[migration-safety-grandfather]]): this migration
touches Astraeus tables only, NOT `agent_cards`/`peer_registries`/etc., so
the §pass39+ sovereign-flare immunity guards are inapplicable here.

Backout chain: drop the migration row + recreate the table via
`alembic downgrade -1` if absolutely needed — but the source code defining
the table schema is also gone post-§pass63, so re-creation requires reverting
the code rip first.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0080_astraeus_drop"
down_revision = "0079_rc_v03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS astraeus_game_events CASCADE;")


def downgrade() -> None:
    # Intentional no-op. Astraeus is gone; we never want it back.
    pass
