"""§OURSTATE-6 — an org room exists because someone WANTED it.

OURSTATE-2a listed a room for every org a person belongs to, opened or not, so
the rooms section filled with empty conversations nobody had asked for and the
one real room was lost among them. The fix is an explicit act: an org turns its
chat on, and only then does it appear.

Two columns, because the Commander asked for both halves to be configurable:

  * `chat_enabled` — off by default, so nothing changes for any existing org
    until its owner decides otherwise.
  * `chat_open_policy` — who may turn it on and open it: `owner_admin` (the
    default, the conservative reading) or `members`, for orgs that want anyone
    inside to be able to start the room.

⚠ This is a DISPLAY and ACTIVATION setting, never an authority one. Membership,
roles and room powers still come from `organization_members`, live, on every
request — an org that disables chat does not thereby change who is in it.
"""
from alembic import op
import sqlalchemy as sa

revision = "0162_org_chat_settings"
down_revision = "0161_chat_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column(
        "chat_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")))
    op.add_column("organizations", sa.Column(
        "chat_open_policy", sa.String(16), nullable=False,
        server_default="owner_admin"))
    # varchar + CHECK, never a PG enum: this vocabulary will grow (teams,
    # guests), and growing an enum is a lock plus a redeploy.
    op.create_check_constraint(
        "ck_org_chat_open_policy", "organizations",
        "chat_open_policy IN ('owner_admin','members')")


def downgrade() -> None:
    op.drop_constraint("ck_org_chat_open_policy", "organizations", type_="check")
    op.drop_column("organizations", "chat_open_policy")
    op.drop_column("organizations", "chat_enabled")
