"""D6-272 (2026-10-17) — a cross-registry delegation revoke that did not reach the delegate's registry is OWED, not dropped.

DELETE /api/v1/agents/delegate-cross-registry/{credential_id} sends the revoke to the delegate's registry once. Since
V0620 the issuer side records the revoke whatever became of that send (the `ironkey.xreg_delegation_revoke` audit row,
which the issuer-authority answer reads), so the delegate's registry is told the delegation is revoked when it checks.
The send itself had no retry: a delegate registry that was down kept its grant row live until the next check, and one
that does not check (shadow or off) kept honouring it until the delegation expired. The route now writes the revoke it
could not deliver into xreg_revokes_owed IN THE SAME TRANSACTION as the issuer-side record, and
background_tasks/xreg_revoke_retry sends it again with backoff until the delegate's registry takes it, refuses it for
good, the attempt budget is spent, or the delegation expires (nothing left to revoke there).

ONE table, nothing else touched. One row per credential (the credential id is the key). The partial index is the
worker's whole question: what is owed and due.

Downgrade drops the table and its two indexes: an open row at that moment is a revoke whose delivery is no longer
retried. The issuer-side record is not touched, so the revoke still stands at the delegate's registry's next check;
send the revoke again from the older image to deliver it there.

Revision ID: 0194_delivery_xreg_revoke
Revises: 0193_bootstrap_plain_scrub
"""
from alembic import op
import sqlalchemy as sa

revision = "0194_delivery_xreg_revoke"
down_revision = "0193_bootstrap_plain_scrub"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "xreg_revokes_owed",
        sa.Column("credential_id", sa.String(length=64), primary_key=True),
        sa.Column("issuer_did", sa.String(length=255), nullable=False),
        sa.Column("delegate_registry", sa.Text(), nullable=False),
        sa.Column("credential_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_xreg_revokes_owed_issuer_did", "xreg_revokes_owed", ["issuer_did"])
    op.create_index(
        "ix_xreg_revokes_owed_due", "xreg_revokes_owed", ["next_attempt_at"],
        postgresql_where=sa.text("done_at IS NULL AND dead_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_xreg_revokes_owed_due", table_name="xreg_revokes_owed")
    op.drop_index("ix_xreg_revokes_owed_issuer_did", table_name="xreg_revokes_owed")
    op.drop_table("xreg_revokes_owed")
