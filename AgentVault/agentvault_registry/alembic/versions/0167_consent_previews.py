"""§COCKPIT P4 (§POSTURE) — the pre-flight preview, so the read floor can be honest.

P4 adds a READ FLOOR: a signature that arrives sooner than the posture's floor after
the human could first have seen the facts is refused 425, and the challenge stays
pending. The naive version of that rule measures from `delivery_acked_at` — and it
FIGHTS P8, which exists so the human has already read and decided BEFORE the ask is
minted. Under the naive rule a human who did exactly what the design intends touches
the moment the ask lands and is told to wait 0.8 s, so pre-flight buys nothing on the
critical path because the floor taxes it straight back (R9).

The rule instead: the clock starts at the earliest moment the human demonstrably had
THESE facts in front of them. A preview whose comparable fields match the challenge's
exactly starts it; ANY divergence resets the clock to the challenge's own ack, because
a changed amount is a new thing to read and that is precisely when a floor should bite.

⚠ The clock is `created_at` — SERVER-attested, stamped when this row was minted — not
`first_presented_at`, which the client supplies. R9 as written named the client's
timestamp; §8 says the read floor is "enforced against the server's own ... timestamp,
never the client's clock", and honouring a client-asserted time here would let any
caller claim it previewed an hour ago and skip the floor entirely. Both columns exist;
only one decides.

Revision id 21 chars (<=32, the §NOTIFV2 varchar law). Additive only: the previous
image simply never writes or reads this table (the registry_rollback law).
"""
from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa

revision = "0167_consent_previews"
down_revision = "0166_cockpit_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consent_previews",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("developer_id", sa.Integer, nullable=False),
        # String(44) matches liability_mandates.id exactly (the 0166 lesson: a FK
        # across differing varchar widths is legal and invites a later mismatch).
        sa.Column("mandate_id", sa.String(44), sa.ForeignKey("liability_mandates.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("verb", sa.String(64), nullable=False),
        sa.Column("action_ref", sa.String(128), nullable=True),
        # The full facts.v2 blob, built by the SAME builder a challenge uses — which is
        # what makes the digest comparison mean anything.
        sa.Column("facts", postgresql.JSONB, nullable=False),
        # sha256 over the COMPARABLE subset only (see liability.facts_comparable).
        sa.Column("facts_digest", sa.String(64), nullable=False),
        # SERVER-ATTESTED. This is the read-floor clock.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # CLIENT-ASSERTED, kept and labelled: the only signal of how long the facts
        # were actually on screen. Never decides a refusal.
        sa.Column("first_presented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presentation_hash", sa.String(64), nullable=True),
        sa.Column("render_version", sa.String(64), nullable=True),
        sa.Column("locale", sa.String(16), nullable=True),
    )
    # The approve-path lookup: "has this developer already previewed exactly this?"
    op.create_index("ix_consent_previews_match", "consent_previews",
                    ["developer_id", "facts_digest", "created_at"])
    # For the retention sweep a long-lived deployment will want (not built here —
    # a sweeper nobody has measured the need for is speculative).
    op.create_index("ix_consent_previews_age", "consent_previews", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_consent_previews_age", table_name="consent_previews")
    op.drop_index("ix_consent_previews_match", table_name="consent_previews")
    op.drop_table("consent_previews")
