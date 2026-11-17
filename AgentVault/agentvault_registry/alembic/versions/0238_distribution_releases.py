"""V0667 D6 part 3 (order gwo_fa3b8d7611f2573a2e63ac1c): the scoped release channel of an organization's code distribution.

`distribution_releases` holds one row per distribution BUILD our pipeline reports (session-release, room seq 5534 and 5540): the line's release
name '<release>_<slug>', its base and head, the merged change set, the protected-set verdict, the carry-forward outcome, the image, and its
state (built, refused or failed by the build; published or withdrawn later). Publishing stores the signed index (schema
theprotocol-distribution/1), the image digests and the registries it names; at most ONE row per name is published at a time. A withdrawn
row keeps its index for the record and answers no one.
`distribution_pull_grants` holds the short-lived pull credentials the index route gives a listed registry (only the secret's hash): the
token server grants pull on distributions/<tag>/* to such a grant alone, re-reading the registry's licence at every token.
Nothing moves value. Downgrade drops both tables.

Revision ID: 0238_distribution_releases
Revises: 0237_code_change_upstream
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0238_distribution_releases"
down_revision = "0237_code_change_upstream"
branch_labels = None
depends_on = None

STATES = ("built", "refused", "failed", "published", "withdrawn")


def upgrade() -> None:
    op.create_table(
        "distribution_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code_distribution_id", sa.String(40), sa.ForeignKey("code_distributions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("release", sa.String(8), nullable=False),
        sa.Column("tag", sa.String(80), nullable=False),
        sa.Column("base_commit", sa.String(64), nullable=False),
        sa.Column("base_tree", sa.String(64), nullable=True),
        sa.Column("head", sa.String(64), nullable=False),
        sa.Column("head_tree", sa.String(64), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("protected", postgresql.JSONB(), nullable=False),
        sa.Column("carry", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("image_id", sa.String(80), nullable=True),
        sa.Column("build_rc", sa.Integer(), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("index", postgresql.JSONB(), nullable=True),
        sa.Column("image_digests", postgresql.JSONB(), nullable=True),
        sa.Column("registries", postgresql.JSONB(), nullable=True),
        sa.Column("publish_word", sa.String(500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_developer_id", sa.Integer(), sa.ForeignKey("developers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_reason", sa.String(500), nullable=True),
        sa.Column("recorded_by_developer_id", sa.Integer(), sa.ForeignKey("developers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("state IN (" + ", ".join(f"'{s}'" for s in STATES) + ")", name="ck_distribution_releases_state"),
        sa.CheckConstraint("name ~ '^V[0-9]{4}_[a-z][a-z0-9-]{1,39}$'", name="ck_distribution_releases_name"),
        sa.CheckConstraint("state NOT IN ('published', 'withdrawn') OR (index IS NOT NULL AND registries IS NOT NULL AND published_at IS NOT NULL)",
                           name="ck_distribution_releases_published_has_index"),
    )
    op.create_index("ix_distribution_releases_name", "distribution_releases", ["name"])
    op.create_index("uq_distribution_releases_published", "distribution_releases", ["name"], unique=True,
                    postgresql_where=sa.text("state = 'published'"))
    op.create_table(
        "distribution_pull_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_id", sa.String(36), sa.ForeignKey("distribution_releases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("registry_name", sa.String(200), nullable=False),
        sa.Column("trust_domain", sa.String(255), nullable=False),
        sa.Column("licence_id", sa.String(36), sa.ForeignKey("federation_licenses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_distribution_pull_grants_release_id", "distribution_pull_grants", ["release_id"])


def downgrade() -> None:
    op.drop_index("ix_distribution_pull_grants_release_id", table_name="distribution_pull_grants")
    op.drop_table("distribution_pull_grants")
    op.drop_index("uq_distribution_releases_published", table_name="distribution_releases")
    op.drop_index("ix_distribution_releases_name", table_name="distribution_releases")
    op.drop_table("distribution_releases")
