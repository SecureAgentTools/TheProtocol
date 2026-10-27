"""§ORGTREASURY (Track C, C1) — the org-level keyless money account (2026-08-14).

Adds organizations.treasury_agent_did: the org's OWN treasury Agent DID, independent of
whether the org is listed on AGORA.

WHY a new column instead of reusing exchange_listings.treasury_agent_did: today an org has
money ONLY if it is AGORA-listed, and "where does this org's money live" is answered by four
separate copies of the same query — two of which use LIMIT 1 with no ORDER BY, so a
multi-listing org would get a nondeterministic purse (no such org exists yet; this closes it
before it can). C1 introduces ONE resolver (services/org_treasury.resolve_org_treasury_did)
that prefers this column and falls back to the org's FIRST listing by created_at, so every
existing org keeps its exact current payee.

Additive + nullable ⇒ safe on a live fleet and byte-inert until an org opts in: no org has
this set at migration time, so every resolver call still returns the listing treasury.
UNIQUE because two organizations must never share a purse (a shared purse would make the
"who owns this money" question unanswerable after the fact). Δ-irrelevant: this migration
moves no tokens and creates no account.
"""

from alembic import op
import sqlalchemy as sa

revision = "0146_org_treasury"
down_revision = "0145_fxdl_remote_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("treasury_agent_did", sa.String(120), nullable=True),
    )
    # Unique but nullable: Postgres allows many NULLs under a UNIQUE constraint, so orgs
    # without a treasury are unaffected while two orgs can never claim the same DID.
    op.create_unique_constraint(
        "uq_organizations_treasury_agent_did", "organizations", ["treasury_agent_did"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_organizations_treasury_agent_did", "organizations", type_="unique"
    )
    op.drop_column("organizations", "treasury_agent_did")
