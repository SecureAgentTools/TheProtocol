"""STEP-UP CHALLENGES (2026-08-23, §DISCREFINE) — presence confirms without a mandate.

Commander: "for resetting agent credentials it would be best to have 2fa enabled."

Everything that ask needs already exists and is proven: `liability_challenges`
carries server-canonical facts, a nonce and a single-use status; `PocketApprovals.vue`
already lists pending challenges and approves them with either a WebAuthn assertion
or a TOTP code; `services/webauthn.py` verifies the assertion against the enrolled
device key and REQUIRES the user-verification bit, so "a human approved this" is
checked server-side rather than asserted by the page.

The only thing in the way was the schema: `mandate_id` was NOT NULL, because the
table was born for Cockpit Card mandates. Resetting an agent's credentials is a
sensitive action with no mandate behind it. Making the column nullable lets that
action mint a challenge on the SAME rail, which means the phone surface, the
crypto, the single-use semantics and the expiry-is-a-denial rule are inherited
rather than reimplemented — and a second, subtly different confirm flow never
comes into existence.

Mandate challenges are unaffected: they still carry their mandate_id, still append
to the evidence chain, and still require LIABILITY_MODE to be on.

Additive and reversible: existing rows all have a mandate_id, so the downgrade can
restore NOT NULL as long as no mandate-less challenge is outstanding (it deletes
those first, which is safe — a challenge is single-use and expires in 120s).

Revision ID: 0154_stepup_challenges
Revises: 0153_agent_card_unlisted
"""
from alembic import op
import sqlalchemy as sa

revision = "0154_stepup_challenges"
down_revision = "0153_agent_card_unlisted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "liability_challenges",
        "mandate_id",
        existing_type=sa.String(44),
        nullable=True,
        comment="NULL for a step-up confirm that is not backed by a liability mandate "
                "(e.g. agent credential reset).",
    )


def downgrade() -> None:
    # Mandate-less challenges cannot satisfy a NOT NULL; they are single-use and
    # live 120 seconds, so dropping them costs nothing but an unfinished confirm.
    op.execute("DELETE FROM liability_challenges WHERE mandate_id IS NULL")
    op.alter_column(
        "liability_challenges",
        "mandate_id",
        existing_type=sa.String(44),
        nullable=False,
    )
