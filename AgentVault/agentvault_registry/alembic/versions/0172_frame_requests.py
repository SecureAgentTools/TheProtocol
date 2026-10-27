"""§FRAMEFORM — the public "I want a frame" intake becomes a persisted row.

Until now `/operator/request-frame` had NO backend: the form composed a
`mailto:` and opened the visitor's mail client (RequestFrame.vue, documented as
a deliberate choice to avoid a half-built review queue). That works right up to
the moment somebody's mail client mangles it, or the answers arrive as prose
that has to be re-typed into the provisioning form by hand. This table is the
structured landing place for the same questions the `frame_request_intake`
email asks.

**Why scalar columns AND an `answers` JSONB, rather than one or the other:**
the columns are exactly the fields the admin list filters/sorts on and the ones
that feed `FrameProvisionRequest` directly, so provisioning can read a row
without parsing anything. Everything else (the ~25 feature switches, the
optional registry-card prefill) lives in `answers`, because that questionnaire
WILL change and a schema migration per added question is how intake forms rot.
Adding or removing a question is a frontend edit after this.

Nothing existing reads this table, and nothing writes it except the new public
endpoint. Applying it on a node whose image predates the feature creates an
empty table and changes no behaviour, which matters because two other sessions
share this tree and a committed migration rides into builds they make (§VITALS).

Revision id is 20 chars (<= the 32-char varchar law that crash-loops alembic's
own version UPDATE).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0172_frame_requests"
down_revision = "0171_local_trust_volume_numeric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frame_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending", index=True),
        # --- who is asking -------------------------------------------------
        sa.Column("contact_name", sa.String(120), nullable=False),
        sa.Column("contact_email", sa.String(200), nullable=False, index=True),
        sa.Column("organization", sa.String(200), nullable=True),
        # --- the seven the email asks for; every one optional here so a
        #     half-filled form still lands instead of 422-ing a stranger away.
        sa.Column("frame_name", sa.String(64), nullable=True),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("trust_domain", sa.String(255), nullable=True),
        sa.Column("ticker", sa.String(8), nullable=True),
        sa.Column("currency_name", sa.String(64), nullable=True),
        sa.Column("federation_choice", sa.String(1), nullable=True),
        # --- free text ------------------------------------------------------
        sa.Column("use_case", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # --- everything that can change without a migration -----------------
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        # --- provenance + review --------------------------------------------
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("developer_id", sa.Integer(),
                  sa.ForeignKey("developers.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("reviewed_by", sa.Integer(),
                  sa.ForeignKey("developers.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("provisioned_frame", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(),
                  nullable=False),
    )
    # The admin list is "pending, newest first"; the public POST dedupes on
    # (email, pending). Both are this one index.
    op.create_index("ix_frame_requests_status_created",
                    "frame_requests", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_frame_requests_status_created", table_name="frame_requests")
    op.drop_table("frame_requests")
