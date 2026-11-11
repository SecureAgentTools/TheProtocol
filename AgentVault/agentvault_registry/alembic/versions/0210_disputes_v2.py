"""V0657 (a) (2026-11-06, session-code): disputes v2, the record a ruler needs and the correction rail.

Order gwo_b16c7d6b52f7e48b825e1264 (the discovery: room seq 1441, disputes_v2_discovery_2026-11-06.md). The Commander's
approval: room seq 1409, 1473 and 1482.

`disputes` gains what the record never carried (every column nullable; a record filed before this revision reads as
before):
- guild_order_id: the Guild order the dispute is about. With it a ruling settles the order's escrow and the Guild's own
  resolve closes the record, one settlement authority (the contract spine has had it for contracts since mig 0129).
- reason, filed_by: why it opened (deadline_missed, rejected_by_poster, poster_silent, stuck_payout, filed_by_party)
  and who filed it ('party' or 'system'). A system-filed dispute has outcome rules of its own: nobody accused anybody.
- amount_claimed: the amount a complainant claims, set when filing. A ruling's wallet compensation and the
  enforcement step's slash read it, never a key in free-form evidence.
- ruled_by, ruled_at, ruling_note, outcome: who ruled, when, why, and what the ruling did (the money, each reputation
  change, the enforcement step), so a reload still shows the consequences.

`dispute_corrections`: an administrator's correction of a ruling, one row each: the rulings before and after, the
reason (required), who and when, what was reversed and what was applied. A correction moves no money. It is claimed
before any effect: its row says 'applying' with the plan from the claim on, each effect is recorded as a step in the
same commit, and 'applied' when the last is done (a failure midway is finished, never redone).

Backfill: a record a Guild order points at (guild_work_orders.dispute_id) gets its guild_order_id, and, from the order's
events, why it opened: a 'disputed' event by the reaper says stuck_payout or poster_silent, one by an agent says
rejected_by_poster; an order disputed with no 'disputed' event was the deadline sweep's (it wrote none before V0657).

The policy row for DisputeRulingCorrected (the registry emits it, audit only; no balance moves).

Additive; rolling back drops the table and the columns (the two-step rule as for every additive revision: downgrade
first from an image that has it, then the older image).

Revision ID: 0210_disputes_v2
Revises: 0209_chat_participant_wake_mode
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0210_disputes_v2"
down_revision = "0209_chat_participant_wake_mode"
branch_labels = None
depends_on = None

# event_type -> (emit_from_registry, emit_from_teg, skip_in_projection)
EMISSION_POLICY_ROWS = {
    "DisputeRulingCorrected": (True, False, False),
}
_POLICY_NOTE = "Emitted by the registry; row seeded by migration 0210 (disputes v2)"

_COLUMNS = (
    ("guild_order_id", sa.String(40)),
    ("reason", sa.String(32)),
    ("filed_by", sa.String(16)),
    ("amount_claimed", sa.Numeric(38, 18)),
    ("ruled_by", sa.Integer()),
    ("ruled_at", sa.DateTime(timezone=True)),
    ("ruling_note", sa.Text()),
    ("outcome", JSONB()),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("disputes", sa.Column(name, type_, nullable=True))
    op.create_index("ix_disputes_guild_order_id", "disputes", ["guild_order_id"])
    op.create_table(
        "dispute_corrections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dispute_id", sa.Integer(), nullable=False, index=True),
        sa.Column("from_ruling", sa.String(32), nullable=False),
        sa.Column("to_ruling", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("corrected_by", sa.Integer(), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reversed", JSONB(), nullable=True),
        sa.Column("applied", JSONB(), nullable=True),
        # claim first (session-lead's review, seq 1597): 'applying' from the claim until every step is done
        sa.Column("status", sa.String(16), nullable=False, server_default="applying"),
        sa.Column("plan", JSONB(), nullable=True),
        sa.Column("steps", JSONB(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    conn = op.get_bind()
    # the records the Guild points at: their order, and why they opened (from the order's own events)
    conn.execute(sa.text(
        "UPDATE disputes d SET guild_order_id = o.id FROM guild_work_orders o "
        "WHERE o.dispute_id = CAST(d.id AS TEXT) AND d.guild_order_id IS NULL"))
    conn.execute(sa.text("""
        UPDATE disputes d SET
          filed_by = CASE WHEN e.actor_did IS NULL OR e.actor_did = 'reaper' THEN 'system' ELSE 'party' END,
          reason = CASE
            WHEN e.actor_did IS NULL THEN 'deadline_missed'
            WHEN e.actor_did <> 'reaper' THEN 'rejected_by_poster'
            WHEN e.payload ->> 'reason' = 'submitted_timeout' THEN 'poster_silent'
            ELSE 'stuck_payout' END
        FROM (
          SELECT o.id AS order_id,
                 (SELECT ev.actor_did FROM guild_order_events ev
                   WHERE ev.order_id = o.id AND ev.event_type = 'disputed' ORDER BY ev.seq LIMIT 1) AS actor_did,
                 (SELECT ev.payload FROM guild_order_events ev
                   WHERE ev.order_id = o.id AND ev.event_type = 'disputed' ORDER BY ev.seq LIMIT 1) AS payload
          FROM guild_work_orders o
        ) e
        WHERE d.guild_order_id = e.order_id AND d.filed_by IS NULL"""))
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
    op.drop_table("dispute_corrections")
    op.drop_index("ix_disputes_guild_order_id", table_name="disputes")
    for name, _ in reversed(_COLUMNS):
        op.drop_column("disputes", name)
