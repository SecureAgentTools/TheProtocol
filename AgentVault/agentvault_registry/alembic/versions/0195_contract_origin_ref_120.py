"""D6-815 (2026-10-24) — contracts.origin_ref holds a DID as long as the DID columns beside it.

routers/contracts_v2.engage_agent passes the engaged agent's DID as origin_ref, and contracts.origin_ref was String(80)
while client_did and provider_did are String(120). A DID with an issuer segment can pass 80 characters: agentvault2-aa's
V0636 pair proof (nt261024x2, 2026-10-24) engaged agents whose DIDs are 82 characters
(did:theprotocol:nt261024x2a.theprotocol.cloud:<uuid4>) and the insert failed, "value too long for type character
varying(80)", HTTP 500 on engageAgent. No production DID passes 80 today (73-75 on EU, ASIA and the operators, 52 on
Frame A), so production never hit it.

ONE column widened to 120, the DID columns' width. In Postgres a varchar(80) to varchar(120) is a catalog change: no
rewrite and no scan; its ACCESS EXCLUSIVE lock lasts the migration's short transaction. The downgrade narrows it back to
80 only while no origin_ref is longer than 80, and refuses otherwise (the narrowing would fail on such a row anyway,
inside the downgrade's transaction).

Behind pgbouncer (the operators and Frame A: transaction pooling, prepared statements kept on its server connections and
shared by their text), the type change leaves every pooled statement that returns contracts planned for varchar(80), and
Postgres refuses to re-plan one ("cached plan must not change result type"). This release's statements carry their
release in a leading comment (core/release_sql_tag.py), so they are new texts that pgbouncer prepares afresh, and a
rollback's older release meets its own plans again: no pooled session needs recycling. Measured on a throwaway database
behind pgbouncer 1.25.2 (2026-10-24): after the widening, 6 of 6 reads failed for a new client sending the old text, 12 of
12 passed sending the new release's text, and the old text passed again after the narrowing back.

Revision ID: 0195_contract_origin_ref_120
Revises: 0194_delivery_xreg_revoke
"""
from alembic import op
import sqlalchemy as sa

revision = "0195_contract_origin_ref_120"
down_revision = "0194_delivery_xreg_revoke"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("contracts", "origin_ref", existing_type=sa.String(length=80), type_=sa.String(length=120),
                    existing_nullable=True)


def downgrade() -> None:
    longer = op.get_bind().execute(sa.text("SELECT count(*) FROM contracts WHERE length(origin_ref) > 80")).scalar() or 0
    if longer:
        raise RuntimeError(f"0195 downgrade refused: {longer} contract(s) carry an origin_ref longer than 80 characters, "
                           "which the narrowed column could not hold")
    op.alter_column("contracts", "origin_ref", existing_type=sa.String(length=120), type_=sa.String(length=80),
                    existing_nullable=True)
