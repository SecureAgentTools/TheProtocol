"""V0658 (k), session-code 2026-11-07: one slash order for every slash (order gwo_3fff3b93f07d83655766db85).

The emission policy row of SlashMoved, the record of each move a slash makes (services/slash_order): which slash moved
whose units from which step (bond, locks, liquid, or another agent of the same developer in a cascade). It is an AUDIT
record: the units move on the TEG, whose own LedgerBalanceChanged is what the event store's balance projection counts,
so the row skips the projection (as RewardsDistributed's does). Counted twice, a slash would break delta 0.

No schema change. Rolling back deletes only the row this revision wrote (the same description and values).

Revision ID: 0212_slash_moved_policy
Revises: 0211_orgs_v2
"""
from alembic import op
import sqlalchemy as sa

revision = "0212_slash_moved_policy"
down_revision = "0211_orgs_v2"
branch_labels = None
depends_on = None

# event_type -> (emit_from_registry, emit_from_teg, skip_in_projection)
EMISSION_POLICY_ROWS = {
    "SlashMoved": (True, False, True),
}
_POLICY_NOTE = ("Emitted by the registry, audit only (the TEG's LedgerBalanceChanged counts the units); row seeded by "
                "migration 0212 (one slash order)")


def upgrade() -> None:
    conn = op.get_bind()
    for event_type, (reg, teg, skip) in EMISSION_POLICY_ROWS.items():
        conn.execute(
            sa.text("INSERT INTO event_emission_policies (event_type, emit_from_registry, emit_from_teg, skip_in_projection, "
                    "description) VALUES (:et, :reg, :teg, :skip, :d) ON CONFLICT (event_type) DO NOTHING"),
            {"et": event_type, "reg": reg, "teg": teg, "skip": skip, "d": _POLICY_NOTE},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for event_type, (reg, teg, skip) in EMISSION_POLICY_ROWS.items():
        conn.execute(
            sa.text("DELETE FROM event_emission_policies WHERE event_type = :et AND description = :d "
                    "AND emit_from_registry = :reg AND emit_from_teg = :teg AND skip_in_projection = :skip"),
            {"et": event_type, "reg": reg, "teg": teg, "skip": skip, "d": _POLICY_NOTE},
        )
