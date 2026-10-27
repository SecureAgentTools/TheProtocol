"""§FESUITE V0595 (2026-10-11, his word "also correct the avt prose in the docs"): the Herald template's public description
names the registry's own unit, not AVT.

0076 seeded the official "Sovereign Pattern - Herald (Bounty Board)" template with "Periodic bounty evaluator, AVT payout
via /teg/transfer.", and the public template page (/templates) prints the description as seeded on every registry
(lifecycle 51, public wording, fes-20261011T032003Z-17e0). This rewrites it where it is still the seeded text and only
there, so a description its registry changed is left alone; 0076's blueprint carries the same words for a fresh frame.
The bundle file's own manifest (its capability lines) is not rewritten: its sha256 is the bundle's identity. The
downgrade restores the seeded text where this one stands.
"""
from alembic import op
import sqlalchemy as sa

revision = "0187_template_unit_prose"
down_revision = "0186_operator_application_env"
branch_labels = None
depends_on = None

SLUG = "sovereign-herald-v1"
SEEDED = ("Bounty coordinator / quest-giver pattern. Periodic bounty evaluator, AVT payout via /teg/transfer. "
          "Fork to build your own community bounty system.")
NOW = ("Bounty coordinator / quest-giver pattern. Periodic bounty evaluator, payout in the registry's own unit via "
       "/teg/transfer. Fork to build your own community bounty system.")


def _swap(was: str, now: str) -> None:
    op.get_bind().execute(
        sa.text("UPDATE agent_bundles SET description = :now WHERE slug = :slug AND is_official = TRUE AND description = :was"),
        {"now": now, "slug": SLUG, "was": was},
    )


def upgrade() -> None:
    _swap(SEEDED, NOW)


def downgrade() -> None:
    _swap(NOW, SEEDED)
