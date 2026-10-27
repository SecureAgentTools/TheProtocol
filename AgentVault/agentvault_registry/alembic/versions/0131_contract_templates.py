"""0131 — CONTRACT TEMPLATES: frozen, versioned agreements that mint contracts (P4, 2026-07-25).

One library serving every origination surface. Free AND paid: `pricing_model` free | purchase
(up-front, the CICD paid-template rail re-keyed `ctpl-…`) | royalty (carved from the payout at
settle via the proven legs-sum-exactly forge carve → Δ=0 by construction). `terms_schema` (JSON
Schema) turns a template into a FORM — the institutional scale (§P4.5): a government org/NGO
maintains its procurement forms here, versioned + immutable + hash-provable, while its CRM/ERP
stays the system of record for documents (annexes ride as {name,url,sha256} references only).

SAFETY (I-C7): a published version is IMMUTABLE and instantiation COPIES — a contract never
dereferences its template at runtime. `visibility='unlisted'` = instantiable by anyone holding the
id, never listed (invited-contractor institutional forms).

IDEMPOTENT — replays every boot. Chains 0130.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0131_contract_templates"
down_revision: str = "0130_guild_contract_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_templates (
            id                  VARCHAR(44) PRIMARY KEY,          -- ctpl_<hex>
            slug                VARCHAR(120) NOT NULL,
            title               VARCHAR(200) NOT NULL,
            summary             VARCHAR(500),
            owner_agent_did     VARCHAR(120) NOT NULL,
            source_org_id       VARCHAR(64),
            maintained_by_org_id VARCHAR(64),
            contract_type       VARCHAR(32) NOT NULL DEFAULT 'work_order',
            visibility          VARCHAR(12) NOT NULL DEFAULT 'private',
                                -- private | org | unlisted | public
            pricing_model       VARCHAR(12) NOT NULL DEFAULT 'free',
                                -- free | purchase | royalty
            price               NUMERIC(30,10),
            price_currency      VARCHAR(12),
            royalty_bps         INTEGER NOT NULL DEFAULT 0 CHECK (royalty_bps BETWEEN 0 AND 500),
            verified            BOOLEAN NOT NULL DEFAULT FALSE,   -- Commander-only, rare
            forked_from_template_id VARCHAR(44),
            current_version_id  VARCHAR(48),
            usage_count         INTEGER NOT NULL DEFAULT 0,       -- increments at AGREED, not click
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ,
            CONSTRAINT uq_ctpl_owner_slug UNIQUE (owner_agent_did, slug)
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_ctpl_visibility ON contract_templates (visibility, contract_type)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_ctpl_org ON contract_templates (source_org_id)"))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_template_versions (
            id            VARCHAR(48) PRIMARY KEY,                -- ctpv_<hex>
            template_id   VARCHAR(44) NOT NULL REFERENCES contract_templates(id) ON DELETE CASCADE,
            version       INTEGER NOT NULL,
            title_tpl     VARCHAR(200),
            terms         JSONB,
            terms_schema  JSONB,                                  -- JSON Schema ⇒ this is a FORM
            milestones    JSONB,                                  -- [{title, amount_pct|amount, terms?, due_days?}]
            suggested_amount NUMERIC(30,10),
            suggested_currency VARCHAR(12),
            suggested_deadline_seconds INTEGER,
            changelog     VARCHAR(500),
            content_hash  CHAR(64) NOT NULL,                      -- sha256(canonical(terms,terms_schema,milestones))
            published_at  TIMESTAMPTZ,                            -- NULL = draft; set once, then FROZEN
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ctpv_template_version UNIQUE (template_id, version)
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_ctpv_template ON contract_template_versions (template_id, version)"))

    # purchase receipts (rail key ctpl:{template}:{buyer} is the exactly-once truth on the TEG;
    # this table is the queryable receipt + "already bought → instantiate free" check)
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_template_purchases (
            id BIGSERIAL PRIMARY KEY,
            template_id VARCHAR(44) NOT NULL REFERENCES contract_templates(id) ON DELETE CASCADE,
            buyer_did   VARCHAR(120) NOT NULL,
            price       NUMERIC(30,10) NOT NULL,
            currency    VARCHAR(12) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ctpl_purchase_once UNIQUE (template_id, buyer_did)
        )
    """))


def downgrade() -> None:
    pass
