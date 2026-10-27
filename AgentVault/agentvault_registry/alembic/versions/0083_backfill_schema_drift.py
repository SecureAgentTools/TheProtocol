"""§pass68.2 (2026-05-23) — Backfill 9 tables + 1 enum + 2 sequences + FKs missing on cloud-op DBs.

DISCOVERY: cloud-op registries (op-london/tokyo/seoul/singapore/sydney/berlin/paris/washington
plus qatest16) are at alembic head 0081_federation_shadow_flag — past the 0001_squash
squash — but their public schema is missing 9 tables that the squash creates. Empirically
confirmed 2026-05-23 by Claude during §pass68 rollout: cloud-op-tokyo had 87 tables vs.
registry-a's 96.

The 9 missing tables (all created by `0001_squash_initial.py` but somehow not present
on cloud-op DBs — root cause: cloud-ops were initialized from a pre-squash snapshot
+ stamped forward without re-running 0001):

  - agent_deployments         (CI/CD pipeline deployments)
  - agent_pipelines           (CI/CD pipeline definitions)
  - beta_access_requests      (beta signup queue)
  - deployment_webhooks       (CI/CD deployment webhook log)
  - game_results              (arena game match results)
  - pipeline_purchases        (purchases of pipeline templates)
  - pipeline_templates        (marketplace pipeline templates)
  - security_audit_logs       (OAuth/security audit trail — THE one that blocked
                               §pass68 fleet rollout for MCP per-tool audit)
  - token_revocations         (OAuth refresh-token JTI revocation list)

Plus the supporting enum + sequences:
  - public.security_event_type ENUM (14 values, used by security_audit_logs.event_type)
  - public.beta_access_requests_id_seq + public.game_results_id_seq (SERIAL backing)

This migration is FULLY IDEMPOTENT — every object is created only if missing.
On registry-a / Frame B (already complete), it's a no-op. On cloud-ops, it
creates exactly what's missing.

Foreign keys: agent_deployments + agent_pipelines + pipeline_purchases +
pipeline_templates reference `agents(did)` and `developers(id)` which DO exist
on cloud-ops. Constraints are added in DO-blocks that check `pg_constraint`
first to stay idempotent.

After this lands, migration 0082_mcp_audit_event_types (schema-aware skip
already in place) will then proceed normally on cloud-ops too — adding the
3 MCP enum values + 2 partial indexes that §pass68's audit hook expects.
"""
from alembic import op
import sqlalchemy as sa


revision: str = "0083_backfill_schema_drift"
down_revision: str = "0082_mcp_audit_event_types"
branch_labels = None
depends_on = None


# ── Enum (only one missing on cloud-ops) ─────────────────────────────────
_CREATE_ENUM = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'security_event_type') THEN
        CREATE TYPE public.security_event_type AS ENUM (
            'token_exchange_request',
            'token_exchange_success',
            'token_exchange_failure',
            'token_introspection',
            'token_revocation',
            'rate_limit_exceeded',
            'invalid_scope',
            'jti_reuse_attempt',
            'unauthorized_access',
            'cross_teg_transfer_initiated',
            'cross_teg_transfer_completed',
            'cross_teg_transfer_failed',
            'suspicious_activity',
            -- §pass68 — MCP audit event types. Included here so a fresh cloud-op
            -- DB doesn't need a second migration to add them.
            'mcp_tool_invoked',
            'mcp_tool_failed',
            'admin_read_mcp_audit'
        );
    ELSE
        -- Enum exists — add the §pass68 values if missing (idempotent).
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'mcp_tool_invoked' AND enumtypid = 'public.security_event_type'::regtype) THEN
            ALTER TYPE public.security_event_type ADD VALUE 'mcp_tool_invoked';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'mcp_tool_failed' AND enumtypid = 'public.security_event_type'::regtype) THEN
            ALTER TYPE public.security_event_type ADD VALUE 'mcp_tool_failed';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'admin_read_mcp_audit' AND enumtypid = 'public.security_event_type'::regtype) THEN
            ALTER TYPE public.security_event_type ADD VALUE 'admin_read_mcp_audit';
        END IF;
    END IF;
END
$$;
"""

# ── Sequences for SERIAL-backed tables ───────────────────────────────────
_CREATE_SEQUENCES = """
CREATE SEQUENCE IF NOT EXISTS public.beta_access_requests_id_seq
    AS integer START WITH 1 INCREMENT BY 1
    NO MINVALUE NO MAXVALUE CACHE 1;

CREATE SEQUENCE IF NOT EXISTS public.game_results_id_seq
    AS integer START WITH 1 INCREMENT BY 1
    NO MINVALUE NO MAXVALUE CACHE 1;
"""

# ── 9 tables (every column nullable-permissive matches the squash exactly) ──
_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS public.agent_deployments (
    id uuid NOT NULL,
    agent_did character varying(255) NOT NULL,
    pipeline_id uuid,
    version_id character varying(255),
    deployment_type character varying(50) NOT NULL,
    environment character varying(50) NOT NULL,
    status character varying(50) NOT NULL,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    duration_seconds integer,
    logs text,
    error_message text,
    webhook_response json,
    rollback_of uuid,
    triggered_by integer,
    trigger_source character varying(50),
    deployment_metadata json
);

CREATE TABLE IF NOT EXISTS public.agent_pipelines (
    id uuid NOT NULL,
    agent_did character varying(255) NOT NULL,
    pipeline_name character varying(255) NOT NULL,
    pipeline_config json NOT NULL,
    trigger_type character varying(50) NOT NULL,
    webhook_url character varying(500),
    webhook_secret character varying(255),
    is_active boolean,
    template_id uuid,
    environment_vars json,
    notification_config json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    created_by integer
);

CREATE TABLE IF NOT EXISTS public.beta_access_requests (
    id integer NOT NULL DEFAULT nextval('public.beta_access_requests_id_seq'::regclass),
    email character varying(200) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    sent_at timestamp with time zone,
    invite_code character varying(30),
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.deployment_webhooks (
    id uuid NOT NULL,
    deployment_id uuid NOT NULL,
    webhook_type character varying(50) NOT NULL,
    payload json NOT NULL,
    received_at timestamp with time zone DEFAULT now(),
    processed boolean
);

CREATE TABLE IF NOT EXISTS public.game_results (
    id integer NOT NULL DEFAULT nextval('public.game_results_id_seq'::regclass),
    match_id character varying(20) NOT NULL,
    game_type character varying(20) NOT NULL,
    agent_did character varying(255),
    agent_name character varying(100) NOT NULL,
    score integer DEFAULT 0 NOT NULL,
    placement integer,
    turns integer DEFAULT 0 NOT NULL,
    stats jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_bot boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.pipeline_purchases (
    id uuid NOT NULL,
    template_id uuid NOT NULL,
    buyer_did character varying(255) NOT NULL,
    price_paid_teg integer NOT NULL,
    transaction_id character varying(255),
    purchased_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.pipeline_templates (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    category character varying(100) NOT NULL,
    template_config json NOT NULL,
    price_teg integer,
    author_did character varying(255),
    downloads integer,
    rating numeric(3,2),
    tags character varying[],
    is_official boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.security_audit_logs (
    id character varying(36) NOT NULL,
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    event_type public.security_event_type NOT NULL,
    correlation_id character varying(36),
    actor_type character varying(50),
    actor_id character varying(255),
    actor_ip character varying(45),
    target_type character varying(50),
    target_id character varying(255),
    action character varying(100) NOT NULL,
    outcome character varying(50) NOT NULL,
    severity character varying(20) NOT NULL,
    details text,
    error_message character varying(500),
    request_id character varying(36),
    user_agent character varying(500)
);

CREATE TABLE IF NOT EXISTS public.token_revocations (
    id character varying(36) NOT NULL,
    token_jti character varying(255) NOT NULL,
    revoked_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    revoked_by character varying(255),
    reason character varying(500),
    token_exp timestamp without time zone
);
"""

# ── Constraints (PK + UNIQUE + FK) — DO-block idempotent ──────────────────
_ADD_CONSTRAINTS = """
DO $$
BEGIN
    -- Primary keys
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_deployments_pkey') THEN
        ALTER TABLE ONLY public.agent_deployments ADD CONSTRAINT agent_deployments_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_pipelines_pkey') THEN
        ALTER TABLE ONLY public.agent_pipelines ADD CONSTRAINT agent_pipelines_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='beta_access_requests_pkey') THEN
        ALTER TABLE ONLY public.beta_access_requests ADD CONSTRAINT beta_access_requests_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='deployment_webhooks_pkey') THEN
        ALTER TABLE ONLY public.deployment_webhooks ADD CONSTRAINT deployment_webhooks_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='game_results_pkey') THEN
        ALTER TABLE ONLY public.game_results ADD CONSTRAINT game_results_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='pipeline_purchases_pkey') THEN
        ALTER TABLE ONLY public.pipeline_purchases ADD CONSTRAINT pipeline_purchases_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='pipeline_templates_pkey') THEN
        ALTER TABLE ONLY public.pipeline_templates ADD CONSTRAINT pipeline_templates_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='security_audit_logs_pkey') THEN
        ALTER TABLE ONLY public.security_audit_logs ADD CONSTRAINT security_audit_logs_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='token_revocations_pkey') THEN
        ALTER TABLE ONLY public.token_revocations ADD CONSTRAINT token_revocations_pkey PRIMARY KEY (id);
    END IF;

    -- Unique constraints
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='beta_access_requests_email_key') THEN
        ALTER TABLE ONLY public.beta_access_requests ADD CONSTRAINT beta_access_requests_email_key UNIQUE (email);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='token_revocations_token_jti_key') THEN
        ALTER TABLE ONLY public.token_revocations ADD CONSTRAINT token_revocations_token_jti_key UNIQUE (token_jti);
    END IF;

    -- Foreign keys — verify referenced tables exist before adding
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='agents') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_deployments_agent_did_fkey') THEN
            ALTER TABLE ONLY public.agent_deployments ADD CONSTRAINT agent_deployments_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_pipelines_agent_did_fkey') THEN
            ALTER TABLE ONLY public.agent_pipelines ADD CONSTRAINT agent_pipelines_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='pipeline_purchases_buyer_did_fkey') THEN
            ALTER TABLE ONLY public.pipeline_purchases ADD CONSTRAINT pipeline_purchases_buyer_did_fkey FOREIGN KEY (buyer_did) REFERENCES public.agents(did) ON DELETE CASCADE;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='pipeline_templates_author_did_fkey') THEN
            ALTER TABLE ONLY public.pipeline_templates ADD CONSTRAINT pipeline_templates_author_did_fkey FOREIGN KEY (author_did) REFERENCES public.agents(did) ON DELETE SET NULL;
        END IF;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_deployments_pipeline_id_fkey') THEN
        ALTER TABLE ONLY public.agent_deployments ADD CONSTRAINT agent_deployments_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.agent_pipelines(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_deployments_rollback_of_fkey') THEN
        ALTER TABLE ONLY public.agent_deployments ADD CONSTRAINT agent_deployments_rollback_of_fkey FOREIGN KEY (rollback_of) REFERENCES public.agent_deployments(id) ON DELETE SET NULL;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='developers') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_deployments_triggered_by_fkey') THEN
            ALTER TABLE ONLY public.agent_deployments ADD CONSTRAINT agent_deployments_triggered_by_fkey FOREIGN KEY (triggered_by) REFERENCES public.developers(id) ON DELETE SET NULL;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_pipelines_created_by_fkey') THEN
            ALTER TABLE ONLY public.agent_pipelines ADD CONSTRAINT agent_pipelines_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.developers(id) ON DELETE SET NULL;
        END IF;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='agent_versions') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_deployments_version_id_fkey') THEN
            ALTER TABLE ONLY public.agent_deployments ADD CONSTRAINT agent_deployments_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.agent_versions(id) ON DELETE SET NULL;
        END IF;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='agent_pipelines_template_id_fkey') THEN
        ALTER TABLE ONLY public.agent_pipelines ADD CONSTRAINT agent_pipelines_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.pipeline_templates(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='deployment_webhooks_deployment_id_fkey') THEN
        ALTER TABLE ONLY public.deployment_webhooks ADD CONSTRAINT deployment_webhooks_deployment_id_fkey FOREIGN KEY (deployment_id) REFERENCES public.agent_deployments(id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='pipeline_purchases_template_id_fkey') THEN
        ALTER TABLE ONLY public.pipeline_purchases ADD CONSTRAINT pipeline_purchases_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.pipeline_templates(id) ON DELETE CASCADE;
    END IF;
END
$$;
"""

# ── Indexes (all IF NOT EXISTS-safe natively) ────────────────────────────
_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_agent_deployments_agent ON public.agent_deployments USING btree (agent_did);
CREATE INDEX IF NOT EXISTS idx_agent_deployments_environment ON public.agent_deployments USING btree (environment);
CREATE INDEX IF NOT EXISTS idx_agent_deployments_started ON public.agent_deployments USING btree (started_at);
CREATE INDEX IF NOT EXISTS idx_agent_deployments_status ON public.agent_deployments USING btree (status);
CREATE INDEX IF NOT EXISTS idx_agent_pipelines_active ON public.agent_pipelines USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_agent_pipelines_agent ON public.agent_pipelines USING btree (agent_did);
CREATE INDEX IF NOT EXISTS idx_beta_requests_status ON public.beta_access_requests USING btree (status);
CREATE INDEX IF NOT EXISTS idx_deployment_webhooks_deployment ON public.deployment_webhooks USING btree (deployment_id);
CREATE INDEX IF NOT EXISTS idx_deployment_webhooks_processed ON public.deployment_webhooks USING btree (processed);
CREATE INDEX IF NOT EXISTS idx_gr_agent ON public.game_results USING btree (agent_did) WHERE (agent_did IS NOT NULL);
CREATE INDEX IF NOT EXISTS idx_gr_created ON public.game_results USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gr_score ON public.game_results USING btree (game_type, score DESC);
CREATE INDEX IF NOT EXISTS idx_gr_type ON public.game_results USING btree (game_type);
CREATE INDEX IF NOT EXISTS idx_pipeline_purchases_buyer ON public.pipeline_purchases USING btree (buyer_did);
CREATE INDEX IF NOT EXISTS idx_pipeline_purchases_template ON public.pipeline_purchases USING btree (template_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_templates_category ON public.pipeline_templates USING btree (category);
CREATE INDEX IF NOT EXISTS idx_pipeline_templates_price ON public.pipeline_templates USING btree (price_teg);
CREATE INDEX IF NOT EXISTS idx_pipeline_templates_rating ON public.pipeline_templates USING btree (rating);
CREATE INDEX IF NOT EXISTS idx_security_audit_actor_id ON public.security_audit_logs USING btree (actor_id);
CREATE INDEX IF NOT EXISTS idx_security_audit_correlation_id ON public.security_audit_logs USING btree (correlation_id);
CREATE INDEX IF NOT EXISTS idx_security_audit_event_type ON public.security_audit_logs USING btree (event_type);
CREATE INDEX IF NOT EXISTS idx_security_audit_severity ON public.security_audit_logs USING btree (severity, "timestamp");
CREATE INDEX IF NOT EXISTS idx_security_audit_timestamp ON public.security_audit_logs USING btree ("timestamp");
CREATE INDEX IF NOT EXISTS idx_token_revocation_exp ON public.token_revocations USING btree (token_exp);
CREATE INDEX IF NOT EXISTS idx_token_revocation_jti ON public.token_revocations USING btree (token_jti);

-- §pass68 — partial indexes for the MCP audit query pattern (also added by 0082;
-- repeated here so a fresh cloud-op DB picks them up in a single migration).
CREATE INDEX IF NOT EXISTS idx_security_audit_target_id_ts
    ON public.security_audit_logs (target_id, "timestamp" DESC)
    WHERE target_type = 'mcp_tool';
CREATE INDEX IF NOT EXISTS idx_security_audit_actor_id_ts
    ON public.security_audit_logs (actor_id, "timestamp" DESC)
    WHERE event_type IN ('mcp_tool_invoked', 'mcp_tool_failed', 'admin_read_mcp_audit');
"""


def upgrade() -> None:
    # Order is: enum → sequences → tables → constraints → indexes
    # Each block is independently idempotent so any subset can be present already.
    op.execute(_CREATE_ENUM)
    op.execute(_CREATE_SEQUENCES)
    op.execute(_CREATE_TABLES)
    op.execute(_ADD_CONSTRAINTS)
    op.execute(_CREATE_INDEXES)


def downgrade() -> None:
    # We never want to drop these — they may be holding live data on registry-a
    # / Frame B that pre-existed this migration. Operators wanting to clean up
    # an op stack should use the operator-teardown flow, not alembic downgrade.
    pass
