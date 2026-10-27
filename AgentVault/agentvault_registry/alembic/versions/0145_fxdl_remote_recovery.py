"""§FXSELFHEAL — remote parked-route self-healing (2026-08-10).

Adds to fx_route_dead_letters:
  receiver_did — the intended RECIPIENT, captured AT PARKING TIME. Until now the receiver
                 lived only in the FxRouteRefunded event (admin search caps at 1000 rows —
                 the 08-04 near-miss); storing it on the row removes the ES join entirely.
  claimed_by / claimed_at — the claim-before-sweep CAS (pending → sweeping) that makes the
                 destination-frame keeper, the manual runbook and any future actor mutually
                 exclusive per route. The sweep rail has NO per-route idempotency; this CAS
                 is the double-pay guard.

Additive + nullable ⇒ safe on a live fleet; old resolved rows simply keep NULLs.
Partial index serves the origin-side /federation/fx/parked-at listing.
"""

from alembic import op
import sqlalchemy as sa

revision = "0145_fxdl_remote_recovery"
down_revision = "0144_agent_cards_updated_at_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fx_route_dead_letters",
                  sa.Column("receiver_did", sa.String(120), nullable=True))
    op.add_column("fx_route_dead_letters",
                  sa.Column("claimed_by", sa.String(200), nullable=True))
    op.add_column("fx_route_dead_letters",
                  sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "idx_fxdl_pending_parked_at",
        "fx_route_dead_letters",
        ["parked_at_did", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # The DESTINATION frame's durable record that a route was delivered FROM here. The
    # already-delivered guard needs a local answer: the delivery truth otherwise lives only
    # in the TEG's cross_teg_transfers/teg_transactions memo, which the registry cannot
    # query. Two live cases on 2026-08-10 had their egress COMPLETE 4-6 s AFTER the origin
    # wrote its dead-letter row — an age gate cannot catch those, only a delivery ledger can.
    # UNIQUE(route_id) makes re-delivery structurally impossible to record twice.
    op.create_table(
        "fx_route_deliveries",
        sa.Column("route_id", sa.String(64), primary_key=True),
        sa.Column("receiver_did", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(36, 18), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),  # egress | egress-local | recovery
        sa.Column("tx_id", sa.String(120), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("fx_route_deliveries")
    op.drop_index("idx_fxdl_pending_parked_at", table_name="fx_route_dead_letters")
    op.drop_column("fx_route_dead_letters", "claimed_at")
    op.drop_column("fx_route_dead_letters", "claimed_by")
    op.drop_column("fx_route_dead_letters", "receiver_did")
