"""V0667 D4 (order gwo_b12f07e4c5adaa1f5bf4d115): a change merged in an organization's line is proposed upstream, with its history.

code_changes gains, on the main-line change that carries a line's change upstream, `upstream_of` (the line change it carries; UNIQUE, so a
line change goes upstream once; RESTRICT, so the history it names cannot be deleted) and `provenance` (the line, its ballot and result, its reviews and the
checker's record, as they stood when it was proposed); on the line's own copy `upstream_since` (the change that landed it upstream and when: the
mark the carry-forward reads). The room's last-seen state may also be `upstreaming` or `upstream` (the line's card says when its change went
upstream and when it landed). Nothing moves value. Downgrade drops the columns and restores the narrower check.

Revision ID: 0237_code_change_upstream
Revises: 0236_content_changes
(D5 takes 0236_content_changes on this base; whichever merges second into V0667's cut re-chains: 0237 then revises 0236. Re-chained at
the D6 base merge, v0667/d6-distributions, session-release 2026-11-16, after session-code's report seq 5545.)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0237_code_change_upstream"
down_revision = "0236_content_changes"
branch_labels = None
depends_on = None

OLD = ("proposed", "accepted", "balloting", "passed", "failed", "vetoed", "merged", "withdrawn")
NEW = OLD + ("upstreaming", "upstream")


def _check(states) -> str:
    return "announce_state IS NULL OR announce_state IN (" + ", ".join(f"'{s}'" for s in states) + ")"


def upgrade() -> None:
    op.add_column("code_changes", sa.Column("upstream_of", sa.String(40), nullable=True))
    op.add_column("code_changes", sa.Column("provenance", postgresql.JSONB(), nullable=True))
    op.add_column("code_changes", sa.Column("upstream_since", postgresql.JSONB(), nullable=True))
    op.create_foreign_key("fk_code_changes_upstream_of", "code_changes", "code_changes", ["upstream_of"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_code_changes_upstream_of", "code_changes", ["upstream_of"])
    op.drop_constraint("ck_code_changes_announce_state", "code_changes", type_="check")
    op.create_check_constraint("ck_code_changes_announce_state", "code_changes", _check(NEW))


def downgrade() -> None:
    op.execute("UPDATE code_changes SET announce_state = 'merged' WHERE announce_state IN ('upstreaming', 'upstream')")
    op.drop_constraint("ck_code_changes_announce_state", "code_changes", type_="check")
    op.create_check_constraint("ck_code_changes_announce_state", "code_changes", _check(OLD))
    op.drop_constraint("uq_code_changes_upstream_of", "code_changes", type_="unique")
    op.drop_constraint("fk_code_changes_upstream_of", "code_changes", type_="foreignkey")
    op.drop_column("code_changes", "upstream_since")
    op.drop_column("code_changes", "provenance")
    op.drop_column("code_changes", "upstream_of")
