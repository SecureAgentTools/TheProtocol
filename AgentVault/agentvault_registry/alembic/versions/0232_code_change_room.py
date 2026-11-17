"""V0666 D3 (order gwo_542285271416c653ca39af3f): a code distribution's change in its organization's room.

code_changes gains the room a line's change is announced in (a conversation of the line's organization; SET NULL when the
room is deleted), the message of the change's live card there (`code.change.live`, written by services/code_change_card)
and the state that room last saw (a state line is posted when it changes; a CHECK keeps it a change's state). Nothing
moves value. Downgrade drops the three columns and the constraint.

Revision ID: 0232_code_change_room
Revises: 0231_code_distributions
"""
from alembic import op
import sqlalchemy as sa

revision = "0232_code_change_room"
down_revision = "0231_code_distributions"
branch_labels = None
depends_on = None

STATES = ("proposed", "accepted", "balloting", "passed", "failed", "vetoed", "merged", "withdrawn")
CHECKS = {
    "ck_code_changes_announce_state": "announce_state IS NULL OR announce_state IN ("
                                      + ", ".join(f"'{s}'" for s in STATES) + ")",
}


def upgrade() -> None:
    op.add_column("code_changes", sa.Column("announce_conversation_id", sa.String(36),
                                            sa.ForeignKey("conversations.id", ondelete="SET NULL",
                                                          name="fk_code_changes_announce_conversation_id"),
                                            nullable=True))
    op.add_column("code_changes", sa.Column("announce_message_id", sa.String(36), nullable=True))
    op.add_column("code_changes", sa.Column("announce_state", sa.String(16), nullable=True))
    for name, sql in CHECKS.items():
        op.create_check_constraint(name, "code_changes", sql)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(name, "code_changes", type_="check")
    op.drop_constraint("fk_code_changes_announce_conversation_id", "code_changes", type_="foreignkey")
    op.drop_column("code_changes", "announce_state")
    op.drop_column("code_changes", "announce_message_id")
    op.drop_column("code_changes", "announce_conversation_id")
