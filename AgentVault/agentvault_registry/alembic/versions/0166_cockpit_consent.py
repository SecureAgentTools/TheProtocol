"""§COCKPIT P3 (§SHOWN) — record what was SHOWN, not only what was signed.

Signing proved the FACTS existed on the server. It never proved what a human had in
front of them when they agreed. `render_version` + `locale` identify the TEMPLATE and
cannot distinguish "2.00 BVT to Acme" from "2.00 AVT to Acme" — the §FOREIGNACT
failure exactly, where the ledgers were right and the label lied.

So a receipt proves THREE separate things, each with its own trust level:

    challenge_hash      these facts existed on the server        ATTESTED
    presentation_hash   these words were on the human's screen   CLIENT-ASSERTED
    the signature       this device, this human, consented       ATTESTED

The middle row is the one that cannot be added later: every receipt cited before it
existed would be silently weaker than the ones after, and nothing in the chain would
say so.

⚠ Trust levels are not interchangeable (R5). `delivery_acked_at` is stamped by the
SERVER when the ack arrives. `first_presented_at` and `presentation_hash` are what
the CLIENT says, and the projection labels them that way. A client-asserted value is
still decisive — a mismatch between what the server would render and what the client
claims it rendered IS the finding — but it must never sit indistinguishably beside an
attested one in a chain whose whole claim is provable intent.

Revision id 20 chars (<=32, the §NOTIFV2 varchar law). Additive only: no backfill, no
rewrite, and safe to leave in place under the previous image (the registry_rollback
law — rolling an IMAGE back past a boot-applied migration crash-loops, so this one is
deliberately something the older code simply ignores).
"""
from alembic import op
import sqlalchemy as sa

revision = "0166_cockpit_consent"
down_revision = "0165_support_review_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "challenge_presentations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # String(44) matches liability_challenges.id exactly — a FK across differing
        # varchar widths is legal but invites the day someone widens one and not
        # the other.
        sa.Column("challenge_id", sa.String(44), sa.ForeignKey("liability_challenges.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("developer_id", sa.Integer, nullable=False),
        # Which surface showed it. Two today; a CHECK rather than an enum so adding a
        # third is a migration and not a type rewrite.
        sa.Column("surface", sa.String(16), nullable=False),
        # SERVER time, stamped when the ack lands. This is the ARRIVAL proof — the WS
        # cue is best-effort and a send is not a delivery (R6).
        sa.Column("delivery_acked_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # CLIENT-ASSERTED paint time. Kept because it is the only signal of how long
        # the human actually had the facts in front of them, and labelled everywhere
        # it is rendered so it never reads as attested.
        sa.Column("first_presented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("render_version", sa.String(64), nullable=True),
        sa.Column("locale", sa.String(16), nullable=True),
        # CLIENT-ASSERTED sha256 over the canonicalised list of strings actually
        # rendered to the human: post-i18n, post-number-formatting, post-unit.
        sa.Column("presentation_hash", sa.String(64), nullable=True),
        sa.CheckConstraint("surface IN ('desk','device')", name="ck_challenge_presentations_surface"),
        # FIRST ACK PER SURFACE WINS. A second ack must not overwrite the first: the
        # question a receipt answers is "what did they see when it arrived", and a
        # later re-render (a locale switch, a reload) is a different question.
        sa.UniqueConstraint("challenge_id", "surface", name="uq_challenge_presentations_surface"),
    )
    op.create_index("ix_challenge_presentations_dev", "challenge_presentations",
                    ["developer_id", "delivery_acked_at"])

    # Denormalised onto the challenge so the pending list and the read-floor check do
    # not need a join for the one timestamp they always want.
    op.add_column("liability_challenges",
                  sa.Column("delivery_acked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("liability_challenges", "delivery_acked_at")
    op.drop_index("ix_challenge_presentations_dev", table_name="challenge_presentations")
    op.drop_table("challenge_presentations")
