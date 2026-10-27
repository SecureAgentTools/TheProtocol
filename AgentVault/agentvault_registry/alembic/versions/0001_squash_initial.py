"""Squashed initial schema — all tables from production pg_dump.

Replaces all 56 prior migrations with a single, authoritative schema
generated from the production database (agentvault_registry_a).

Handles two scenarios:
  1. Fresh DB  → creates everything from scratch (69 tables)
  2. Existing DB (production/operator) → no-op, skips all DDL

Revision ID: 0001_squash
Revises: None
Create Date: 2026-03-29
"""
from alembic import op
from sqlalchemy import text

revision = '0001_squash'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Detect existing database — if developers table exists, this DB was
    # already built by old migrations. Skip all DDL.
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'developers')"
    )).scalar()

    if result:
        return

    # ── Fresh database: create everything from scratch ──
    # Source: pg_dump --schema-only from agentvault_registry_a (2026-03-29)

    # ── Enum types ──
    op.execute(text('''CREATE TYPE public.security_event_type AS ENUM (
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
    'suspicious_activity'
);'''))


    # ── Sequences ──
    op.execute(text('''CREATE SEQUENCE public.achievement_rewards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.admin_broadcasts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.agent_daily_stats_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.agent_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.agent_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.agent_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.agents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.auditor_flag_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.beta_access_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.bootstrap_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.developer_achievements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.developer_api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.developer_notification_reads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.developers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.disputes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.event_emission_policies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.evidence_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.funding_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.game_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.governance_proposals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.invite_codes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.peer_registries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.refactoring_upgrade_contracts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.registry_enforcement_policies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.staking_apy_tiers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.staking_rewards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.support_messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.support_tickets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.system_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.velocity_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE SEQUENCE public.votes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))


    # ── Tables ──
    op.execute(text('''CREATE TABLE public.a2a_payment_authorizations (
    id character varying(36) DEFAULT (gen_random_uuid())::text NOT NULL,
    caller_did character varying(255) NOT NULL,
    target_agent_did character varying(255) NOT NULL,
    amount numeric(30,6) NOT NULL,
    token_hash character varying(64) NOT NULL,
    token_prefix character varying(12) NOT NULL,
    status character varying(20) DEFAULT 'authorized'::character varying NOT NULL,
    contract_id integer,
    task_id character varying(255),
    settlement_tx_id character varying(255),
    idempotency_key character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    settled_at timestamp with time zone
);'''))

    op.execute(text('''CREATE TABLE public.achievement_rewards (
    id integer NOT NULL,
    achievement_type character varying(100) NOT NULL,
    achievement_name character varying(200) NOT NULL,
    payout_avt double precision DEFAULT 0 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    description character varying(500)
);'''))

    op.execute(text('''CREATE TABLE public.admin_broadcasts (
    id integer NOT NULL,
    title character varying(200) NOT NULL,
    body text NOT NULL,
    broadcast_type character varying(20) DEFAULT 'info'::character varying NOT NULL,
    created_by integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    send_email boolean DEFAULT false NOT NULL,
    email_sent_at timestamp with time zone,
    ws_recipients integer DEFAULT 0 NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.agent_capabilities (
    id character varying NOT NULL,
    agent_did character varying NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    category character varying(50),
    version character varying(20),
    parameters json,
    is_active boolean,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.agent_cards (
    id uuid NOT NULL,
    developer_id integer NOT NULL,
    card_data jsonb NOT NULL,
    name character varying NOT NULL,
    description character varying,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    agent_did character varying
);'''))

    op.execute(text('''CREATE TABLE public.agent_daily_stats (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    date date NOT NULL,
    requests_count integer DEFAULT 0 NOT NULL,
    success_count integer DEFAULT 0 NOT NULL,
    error_count integer DEFAULT 0 NOT NULL,
    avg_response_time_ms double precision DEFAULT '0'::double precision NOT NULL,
    unique_endpoints integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.agent_deployments (
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
);'''))

    op.execute(text('''CREATE TABLE public.agent_endpoints (
    id character varying NOT NULL,
    agent_did character varying NOT NULL,
    path character varying(255) NOT NULL,
    method character varying(10) NOT NULL,
    description text,
    parameters json,
    response_schema json,
    is_active boolean,
    rate_limit integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.agent_logs (
    id integer NOT NULL,
    agent_did character varying NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    level character varying NOT NULL,
    message text NOT NULL,
    source character varying,
    log_metadata json
);'''))

    op.execute(text('''CREATE TABLE public.agent_metrics (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    agent_did character varying NOT NULL,
    total_requests bigint DEFAULT '0'::bigint NOT NULL,
    successful_requests bigint DEFAULT '0'::bigint NOT NULL,
    failed_requests bigint DEFAULT '0'::bigint NOT NULL,
    total_response_time_ms bigint DEFAULT '0'::bigint NOT NULL,
    last_request_at timestamp with time zone,
    last_updated timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.agent_pipelines (
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
);'''))

    op.execute(text('''CREATE TABLE public.agent_requests (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    agent_did character varying NOT NULL,
    endpoint character varying NOT NULL,
    method character varying NOT NULL,
    status_code integer NOT NULL,
    response_time_ms integer NOT NULL,
    error_message text,
    request_metadata json,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_agent_requests_method CHECK (((method)::text = ANY ((ARRAY['GET'::character varying, 'POST'::character varying, 'PUT'::character varying, 'DELETE'::character varying, 'PATCH'::character varying, 'OPTIONS'::character varying, 'HEAD'::character varying])::text[]))),
    CONSTRAINT ck_agent_requests_status_code CHECK (((status_code >= 100) AND (status_code < 600)))
);'''))

    op.execute(text('''CREATE TABLE public.agent_tags (
    id character varying NOT NULL,
    agent_did character varying NOT NULL,
    tag character varying(50) NOT NULL,
    created_at timestamp with time zone NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.agent_versions (
    id character varying NOT NULL,
    agent_did character varying NOT NULL,
    version character varying(20) NOT NULL,
    changelog text,
    configuration json,
    is_current boolean,
    published_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    config_snapshot json,
    deployment_count integer,
    rollback_count integer,
    is_stable boolean
);'''))

    op.execute(text('''CREATE TABLE public.agents (
    id integer NOT NULL,
    did character varying NOT NULL,
    client_id character varying NOT NULL,
    hashed_client_secret character varying NOT NULL,
    creator_developer_id integer NOT NULL,
    public_key_jwk json,
    status character varying DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_active_at timestamp with time zone,
    reputation_score integer DEFAULT 0 NOT NULL,
    liquid_balance numeric(30,6) DEFAULT 0 NOT NULL,
    staked_balance numeric(30,6) DEFAULT 0 NOT NULL,
    last_exported_at timestamp with time zone,
    last_imported_at timestamp with time zone,
    import_source character varying(255),
    last_reward_distribution timestamp with time zone,
    total_rewards_earned numeric(36,18) DEFAULT '0'::numeric,
    auto_compound_enabled boolean DEFAULT false,
    staking_tier character varying(50),
    cicd_enabled boolean DEFAULT false,
    last_deployment_at timestamp with time zone,
    deployment_success_rate numeric(5,2),
    total_deployments integer DEFAULT 0,
    offense_count integer DEFAULT 0 NOT NULL,
    enforcement_level integer DEFAULT 0 NOT NULL,
    rewards_paused_until timestamp with time zone,
    enforcement_status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    last_offense_at timestamp with time zone,
    reputation_bond_amount integer DEFAULT 0 NOT NULL,
    reputation_bond_status character varying(20) DEFAULT 'none'::character varying NOT NULL,
    latitude double precision,
    longitude double precision,
    location_label character varying(255),
    organization_id character varying(255),
    team_id character varying(255)
);'''))

    op.execute(text('''CREATE TABLE public.auditor_flag_logs (
    id integer NOT NULL,
    flagged_agent_did character varying NOT NULL,
    flag_type character varying NOT NULL,
    severity character varying NOT NULL,
    details json NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.beta_access_requests (
    id integer NOT NULL,
    email character varying(200) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    sent_at timestamp with time zone,
    invite_code character varying(30),
    created_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.bootstrap_tokens (
    id integer NOT NULL,
    token_value character varying NOT NULL,
    creator_developer_id integer NOT NULL,
    agent_type_hint character varying,
    requested_by character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    used_by_agent_did character varying,
    is_used boolean DEFAULT false NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.cross_registry_settlements (
    id character varying NOT NULL,
    dispute_id integer NOT NULL,
    origin_registry_url character varying(500) NOT NULL,
    defendant_registry_url character varying(500),
    complainant_did character varying(255) NOT NULL,
    defendant_did character varying(255) NOT NULL,
    requested_amount integer NOT NULL,
    slashed_amount integer DEFAULT 0 NOT NULL,
    minted_amount integer DEFAULT 0 NOT NULL,
    status character varying(50) DEFAULT 'PENDING_SLASH'::character varying NOT NULL,
    ruling character varying(100) NOT NULL,
    evidence_hash character varying(255),
    request_event_id character varying(255),
    slash_event_id character varying(255),
    mint_event_id character varying(255),
    slash_tx_id character varying(255),
    mint_tx_id character varying(255),
    callback_url character varying(500),
    error_message text,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    slashed_at timestamp with time zone,
    settled_at timestamp with time zone,
    saga_state character varying(30) DEFAULT 'LEGACY'::character varying NOT NULL,
    saga_timeout_at timestamp with time zone,
    saga_last_step_at timestamp with time zone,
    saga_retry_count integer DEFAULT 0 NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.deployment_webhooks (
    id uuid NOT NULL,
    deployment_id uuid NOT NULL,
    webhook_type character varying(50) NOT NULL,
    payload json NOT NULL,
    received_at timestamp with time zone DEFAULT now(),
    processed boolean
);'''))

    op.execute(text('''CREATE TABLE public.developer_achievements (
    id integer NOT NULL,
    developer_id integer NOT NULL,
    achievement_type character varying(100) NOT NULL,
    achievement_name character varying(200) NOT NULL,
    awarded_at timestamp with time zone DEFAULT now() NOT NULL,
    payout_avt double precision DEFAULT 0 NOT NULL,
    payout_transaction_id character varying(255),
    metadata_json jsonb,
    payout_status character varying(20) DEFAULT 'pending'::character varying NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.developer_api_keys (
    id integer NOT NULL,
    developer_id integer NOT NULL,
    key_prefix character varying(10) NOT NULL,
    hashed_key character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    description character varying
);'''))

    op.execute(text('''CREATE TABLE public.developer_notification_reads (
    id integer NOT NULL,
    broadcast_id integer NOT NULL,
    developer_id integer NOT NULL,
    read_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.developer_webhooks (
    id character varying NOT NULL,
    developer_id integer NOT NULL,
    url character varying(500) NOT NULL,
    events jsonb NOT NULL,
    secret character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_triggered_at timestamp with time zone,
    failure_count integer DEFAULT 0 NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.developers (
    id integer NOT NULL,
    name character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_verified boolean NOT NULL,
    email character varying NOT NULL,
    hashed_password character varying NOT NULL,
    email_verification_token character varying,
    verification_token_expires timestamp with time zone,
    hashed_recovery_key character varying,
    totp_secret character varying(64),
    two_fa_enabled boolean DEFAULT false NOT NULL,
    backup_codes jsonb,
    two_fa_verified_at timestamp without time zone,
    two_fa_recovery_attempts integer DEFAULT 0 NOT NULL,
    two_fa_last_failure timestamp without time zone,
    trusted_devices jsonb,
    latitude double precision,
    longitude double precision,
    location_label character varying(255),
    display_name character varying(100),
    bio text,
    avatar_url character varying(500),
    website_url character varying(500),
    github_url character varying(200),
    twitter_handle character varying(100),
    company character varying(255),
    timezone character varying(100),
    notification_prefs json,
    last_login_at timestamp with time zone,
    profile_visibility character varying(20) DEFAULT 'public'::character varying NOT NULL,
    password_reset_token character varying,
    password_reset_token_expires timestamp with time zone,
    is_admin boolean DEFAULT false NOT NULL,
    must_change_password boolean DEFAULT false NOT NULL,
    is_federation_operator boolean DEFAULT false NOT NULL,
    federation_operator_status character varying(20)
);'''))

    op.execute(text('''CREATE TABLE public.disputes (
    id integer NOT NULL,
    status character varying NOT NULL,
    ruling character varying,
    complainant_did character varying NOT NULL,
    defendant_did character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.enforcement_actions (
    id character varying NOT NULL,
    agent_did character varying NOT NULL,
    action_type character varying(30) NOT NULL,
    trigger character varying(30) NOT NULL,
    trigger_reference character varying(200),
    amount integer,
    status character varying(20) DEFAULT 'pending_approval'::character varying NOT NULL,
    escalation_level integer DEFAULT 1 NOT NULL,
    policy_version integer NOT NULL,
    correlation_count integer DEFAULT 0 NOT NULL,
    correlation_multi double precision DEFAULT '1'::double precision NOT NULL,
    approved_by character varying,
    rejected_reason text,
    executed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.event_emission_policies (
    id integer NOT NULL,
    event_type character varying(100) NOT NULL,
    emit_from_teg boolean DEFAULT false NOT NULL,
    emit_from_registry boolean DEFAULT true NOT NULL,
    skip_in_projection boolean DEFAULT false NOT NULL,
    description character varying(500),
    updated_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.evidence (
    id integer NOT NULL,
    dispute_id integer NOT NULL,
    submitter_did character varying NOT NULL,
    evidence_data json NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.federated_registry_compliance (
    id uuid NOT NULL,
    peer_registry_id integer NOT NULL,
    policy_json json NOT NULL,
    policy_hash character varying(64) NOT NULL,
    policy_version integer DEFAULT 1 NOT NULL,
    federation_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    compliance_score double precision DEFAULT '100'::double precision NOT NULL,
    drift_events_count integer DEFAULT 0 NOT NULL,
    quarantine_reason text,
    quarantine_since timestamp with time zone,
    quarantine_grace_expires timestamp with time zone,
    quarantine_events json DEFAULT '[]'::json,
    blacklist_reason text,
    blacklisted_at timestamp with time zone,
    blacklisted_by character varying(128),
    last_poll_at timestamp with time zone,
    last_hash_mismatch_at timestamp with time zone,
    consecutive_poll_failures integer DEFAULT 0 NOT NULL,
    admitted_at timestamp with time zone,
    admitted_by character varying(128),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.federation_licenses (
    id character varying(36) NOT NULL,
    operator_name character varying(200) NOT NULL,
    operator_did character varying(255) NOT NULL,
    license_key_hash character varying(64) NOT NULL,
    license_key_prefix character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone,
    revoked_reason character varying(500),
    max_agents integer DEFAULT 100 NOT NULL,
    max_events_per_minute integer DEFAULT 1000 NOT NULL,
    federation_tier character varying(50) DEFAULT 'standard'::character varying NOT NULL,
    last_seen_at timestamp with time zone,
    event_count integer DEFAULT 0 NOT NULL,
    min_image_version character varying(20)
);'''))

    op.execute(text('''CREATE TABLE public.funding_requests (
    id integer NOT NULL,
    requester_did character varying(255) NOT NULL,
    requester_name character varying(255),
    requested_amount numeric(30,6) NOT NULL,
    reason text NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    reviewed_by character varying(255),
    reviewed_at timestamp with time zone,
    approved_amount numeric(30,6),
    rejection_reason character varying(1000),
    funded_at timestamp with time zone,
    funding_transaction_id character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.game_results (
    id integer NOT NULL,
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
);'''))

    op.execute(text('''CREATE TABLE public.global_trust_vectors (
    id character varying NOT NULL,
    agent_did character varying NOT NULL,
    global_trust double precision NOT NULL,
    similarity_score double precision DEFAULT '0'::double precision NOT NULL,
    epoch integer NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    computation_time_ms integer
);'''))

    op.execute(text('''CREATE TABLE public.governance_proposals (
    id integer NOT NULL,
    proposer_did character varying NOT NULL,
    title character varying NOT NULL,
    description character varying NOT NULL,
    status character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    end_timestamp timestamp with time zone NOT NULL,
    proposal_type character varying(20) DEFAULT 'standard'::character varying NOT NULL,
    policy_diff json,
    quorum_percent double precision,
    pass_percent double precision
);'''))

    op.execute(text('''CREATE TABLE public.idempotency_keys (
    key character varying NOT NULL,
    agent_id character varying NOT NULL,
    response_data json NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.invite_codes (
    id integer NOT NULL,
    code character varying(64) NOT NULL,
    created_by integer NOT NULL,
    used_by integer,
    used_at timestamp with time zone,
    max_uses integer DEFAULT 1 NOT NULL,
    use_count integer DEFAULT 0 NOT NULL,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    note character varying(255)
);'''))

    op.execute(text('''CREATE TABLE public.local_trust_scores (
    id character varying NOT NULL,
    from_did character varying NOT NULL,
    to_did character varying NOT NULL,
    satisfactory integer DEFAULT 0 NOT NULL,
    unsatisfactory integer DEFAULT 0 NOT NULL,
    local_trust double precision DEFAULT '0'::double precision NOT NULL,
    normalized double precision DEFAULT '0'::double precision NOT NULL,
    tx_volume bigint DEFAULT '0'::bigint NOT NULL,
    last_updated timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.oauth_token_exchanges (
    id uuid NOT NULL,
    source_token_jti character varying(255) NOT NULL,
    issued_token_jti character varying(255) NOT NULL,
    source_registry character varying(255) NOT NULL,
    agent_did character varying(255) NOT NULL,
    scope character varying(500),
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    security_metadata jsonb,
    token_jti character varying(255)
);'''))

    op.execute(text('''CREATE TABLE public.operator_applications (
    id character varying(36) NOT NULL,
    developer_id integer,
    name character varying(200) NOT NULL,
    email character varying(200) NOT NULL,
    organization character varying(255),
    deployment character varying(50) DEFAULT 'undecided'::character varying NOT NULL,
    experience character varying(50) DEFAULT 'beginner'::character varying NOT NULL,
    use_case text,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    reviewed_by integer,
    reviewed_at timestamp with time zone,
    review_notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    bundle_path character varying(500),
    bundle_generated_at timestamp with time zone,
    bundle_download_count integer DEFAULT 0 NOT NULL,
    bundle_expires_at timestamp with time zone,
    docker_registry_username character varying(100),
    spire_fingerprint character varying(64),
    revoked_at timestamp with time zone,
    revoked_reason text,
    revoked_by integer,
    activation_code_hash character varying(64),
    activation_code_expires_at timestamp with time zone,
    activated_at timestamp with time zone,
    activated_developer_id integer,
    docker_pull_token_hash character varying(64),
    docker_pull_token_prefix character varying(16),
    docker_pull_token_issued_at timestamp with time zone,
    docker_pull_allowed_repos text
);'''))

    op.execute(text('''CREATE TABLE public.organization_invitations (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    email character varying(255) NOT NULL,
    role character varying(50) DEFAULT 'member'::character varying NOT NULL,
    token character varying(255) NOT NULL,
    invited_by integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone,
    status character varying(50) DEFAULT 'pending'::character varying NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.organization_members (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    developer_id integer NOT NULL,
    role character varying(50) DEFAULT 'member'::character varying NOT NULL,
    joined_at timestamp with time zone DEFAULT now() NOT NULL,
    invited_by integer,
    is_active boolean DEFAULT true NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.organizations (
    id character varying NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    owner_id integer NOT NULL,
    description text,
    website character varying(500),
    logo_url character varying(500),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    settings json,
    limits json
);'''))

    op.execute(text('''CREATE TABLE public.peer_registries (
    id integer NOT NULL,
    owner_developer_id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    base_url character varying NOT NULL,
    admin_contact_email character varying NOT NULL,
    status character varying DEFAULT 'PENDING_APPROVAL'::character varying NOT NULL,
    hashed_shared_secret character varying,
    public_key character varying,
    discovery_auth_info json NOT NULL,
    interaction_auth_info json,
    registered_at timestamp with time zone DEFAULT now() NOT NULL,
    approved_at timestamp with time zone,
    approved_by_developer_id integer,
    last_synced_at timestamp with time zone,
    health_check_failure_count integer DEFAULT 0 NOT NULL,
    last_health_check_attempt_at timestamp with time zone,
    federation_access_token character varying,
    auto_slash_enabled boolean DEFAULT false NOT NULL,
    auto_slash_max_avt integer DEFAULT 0 NOT NULL,
    total_interactions integer DEFAULT 0 NOT NULL,
    disputes_lost_with integer DEFAULT 0 NOT NULL,
    bayesian_discount double precision DEFAULT '1'::double precision NOT NULL,
    last_interaction_at timestamp with time zone,
    inactivity_leak_start timestamp with time zone
);'''))

    op.execute(text('''CREATE TABLE public.pipeline_purchases (
    id uuid NOT NULL,
    template_id uuid NOT NULL,
    buyer_did character varying(255) NOT NULL,
    price_paid_teg integer NOT NULL,
    transaction_id character varying(255),
    purchased_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.pipeline_templates (
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
);'''))

    op.execute(text('''CREATE TABLE public.refactoring_upgrade_contracts (
    id integer NOT NULL,
    client_agent_did character varying NOT NULL,
    upgrader_agent_did character varying,
    status character varying NOT NULL,
    scope_description character varying NOT NULL,
    source_code_repo_url character varying NOT NULL,
    source_code_branch character varying NOT NULL,
    acceptance_criteria json NOT NULL,
    payment_amount integer NOT NULL,
    access_credentials_id character varying,
    pr_url character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    accepted_at timestamp with time zone,
    completed_at timestamp with time zone,
    payment_transaction_id character varying(255)
);'''))

    op.execute(text('''CREATE TABLE public.registry_enforcement_policies (
    id integer NOT NULL,
    policy_json json NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    modified_by character varying(200) DEFAULT 'system'::character varying NOT NULL,
    modified_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    previous_version integer
);'''))

    op.execute(text('''CREATE TABLE public.registry_operating_state (
    id uuid NOT NULL,
    treasury_zero_days integer DEFAULT 0 NOT NULL,
    treasury_max_fee_locked boolean DEFAULT false NOT NULL,
    treasury_quarantine_triggered boolean DEFAULT false NOT NULL,
    last_treasury_check_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.registry_trust_config (
    id uuid NOT NULL,
    registry_name character varying(255) NOT NULL,
    registry_url character varying(500) NOT NULL,
    public_key text NOT NULL,
    client_id character varying(255),
    encrypted_client_secret text,
    allowed_operations json DEFAULT '[]'::json NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by_developer_id integer
);'''))

    op.execute(text('''CREATE TABLE public.reputation_bonds (
    id character varying NOT NULL,
    agent_did character varying NOT NULL,
    amount integer DEFAULT 50 NOT NULL,
    locked_at timestamp with time zone DEFAULT now() NOT NULL,
    status character varying(20) DEFAULT 'locked'::character varying NOT NULL,
    matured_at timestamp with time zone,
    forfeited_at timestamp with time zone,
    forfeit_reason character varying(100)
);'''))

    op.execute(text('''CREATE TABLE public.security_audit_logs (
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
);'''))

    op.execute(text('''CREATE TABLE public.stake_transactions (
    id character varying NOT NULL,
    agent_id integer NOT NULL,
    stake_id character varying,
    transaction_type character varying NOT NULL,
    amount numeric(20,2) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL,
    teg_transaction_id character varying,
    status character varying DEFAULT 'completed'::character varying NOT NULL,
    metadata json
);'''))

    op.execute(text('''CREATE TABLE public.stakes (
    id character varying NOT NULL,
    agent_id integer NOT NULL,
    agent_did character varying NOT NULL,
    amount numeric(20,2) NOT NULL,
    staked_at timestamp with time zone NOT NULL,
    unstaked_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    teg_stake_id character varying,
    lock_period_days integer DEFAULT 30 NOT NULL,
    apy_rate numeric(5,2) DEFAULT 12.5 NOT NULL,
    lock_expiry_at timestamp with time zone,
    ve_power_snapshot double precision DEFAULT '0'::double precision NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.staking_apy_config (
    id character varying NOT NULL,
    tier_name character varying(50) NOT NULL,
    min_stake numeric(36,18) NOT NULL,
    max_stake numeric(36,18),
    base_apy numeric(5,2) NOT NULL,
    lock_period_days integer,
    lock_bonus_apy numeric(5,2),
    is_active boolean,
    effective_from timestamp with time zone NOT NULL,
    effective_until timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.staking_apy_tiers (
    id integer NOT NULL,
    lock_period_days integer NOT NULL,
    apy_rate numeric(5,2) NOT NULL,
    min_amount numeric(20,2) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.staking_distributions (
    id character varying NOT NULL,
    distribution_date date NOT NULL,
    distribution_type character varying(50) NOT NULL,
    total_distributed numeric(36,18) NOT NULL,
    total_stakers integer NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone,
    status character varying(50) NOT NULL,
    error_message text,
    initiated_by character varying(255),
    distribution_metadata json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.staking_reward_records (
    id character varying NOT NULL,
    distribution_id character varying NOT NULL,
    agent_did character varying(255) NOT NULL,
    staked_amount numeric(36,18) NOT NULL,
    apy_rate numeric(5,2) NOT NULL,
    reward_amount numeric(36,18) NOT NULL,
    days_staked integer NOT NULL,
    tier_name character varying(50),
    distributed_at timestamp with time zone,
    teg_transaction_id character varying,
    status character varying(50) NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.staking_rewards (
    id integer NOT NULL,
    agent_id integer NOT NULL,
    stake_id character varying NOT NULL,
    amount numeric(20,2) NOT NULL,
    earned_at timestamp with time zone DEFAULT now() NOT NULL,
    claimed_at timestamp with time zone,
    is_claimed boolean DEFAULT false NOT NULL,
    claim_transaction_id character varying
);'''))

    op.execute(text('''CREATE TABLE public.support_messages (
    id integer NOT NULL,
    ticket_id integer NOT NULL,
    sender_type character varying(20) NOT NULL,
    sender_name character varying(100),
    message text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.support_tickets (
    id integer NOT NULL,
    developer_id integer NOT NULL,
    subject character varying(200) NOT NULL,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    status character varying(50) DEFAULT 'open'::character varying NOT NULL,
    priority character varying(20) DEFAULT 'normal'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.system_events (
    id integer NOT NULL,
    event_type character varying NOT NULL,
    title character varying NOT NULL,
    description character varying NOT NULL,
    event_metadata json,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.team_members (
    id character varying NOT NULL,
    team_id character varying NOT NULL,
    developer_id integer NOT NULL,
    role character varying(50) DEFAULT 'member'::character varying NOT NULL,
    joined_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.teams (
    id character varying NOT NULL,
    organization_id character varying NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    permissions json
);'''))

    op.execute(text('''CREATE TABLE public.token_revocations (
    id character varying(36) NOT NULL,
    token_jti character varying(255) NOT NULL,
    revoked_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    revoked_by character varying(255),
    reason character varying(500),
    token_exp timestamp without time zone
);'''))

    op.execute(text('''CREATE TABLE public.transaction_fee_records (
    id character varying NOT NULL,
    transaction_id character varying NOT NULL,
    agent_did character varying NOT NULL,
    amount numeric(30,6) NOT NULL,
    fee_rate_percent double precision NOT NULL,
    destination character varying(30) DEFAULT 'treasury_recycle'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    transfer_amount numeric(30,6),
    velocity_index double precision
);'''))

    op.execute(text('''CREATE TABLE public.velocity_metrics (
    id integer NOT NULL,
    agent_did character varying NOT NULL,
    window_start timestamp with time zone NOT NULL,
    tx_count integer DEFAULT 0 NOT NULL,
    tx_volume bigint DEFAULT '0'::bigint NOT NULL,
    velocity_index double precision DEFAULT '0'::double precision NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.votes (
    id integer NOT NULL,
    proposal_id integer NOT NULL,
    voter_did character varying NOT NULL,
    vote boolean NOT NULL,
    voting_power integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reason character varying
);'''))

    op.execute(text('''CREATE TABLE public.webhook_deliveries (
    id character varying NOT NULL,
    webhook_id character varying NOT NULL,
    event_type character varying(100) NOT NULL,
    payload json NOT NULL,
    response_status integer,
    response_body text,
    delivered_at timestamp with time zone DEFAULT now() NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    next_retry_at timestamp with time zone,
    error_message text
);'''))


    # ── Sequence ownership and column defaults ──
    op.execute(text('''ALTER SEQUENCE public.achievement_rewards_id_seq OWNED BY public.achievement_rewards.id;'''))

    op.execute(text('''ALTER SEQUENCE public.admin_broadcasts_id_seq OWNED BY public.admin_broadcasts.id;'''))

    op.execute(text('''ALTER SEQUENCE public.agent_daily_stats_id_seq OWNED BY public.agent_daily_stats.id;'''))

    op.execute(text('''ALTER SEQUENCE public.agent_logs_id_seq OWNED BY public.agent_logs.id;'''))

    op.execute(text('''ALTER SEQUENCE public.agent_metrics_id_seq OWNED BY public.agent_metrics.id;'''))

    op.execute(text('''ALTER SEQUENCE public.agent_requests_id_seq OWNED BY public.agent_requests.id;'''))

    op.execute(text('''ALTER SEQUENCE public.agents_id_seq OWNED BY public.agents.id;'''))

    op.execute(text('''ALTER SEQUENCE public.auditor_flag_logs_id_seq OWNED BY public.auditor_flag_logs.id;'''))

    op.execute(text('''ALTER SEQUENCE public.beta_access_requests_id_seq OWNED BY public.beta_access_requests.id;'''))

    op.execute(text('''ALTER SEQUENCE public.bootstrap_tokens_id_seq OWNED BY public.bootstrap_tokens.id;'''))

    op.execute(text('''ALTER SEQUENCE public.developer_achievements_id_seq OWNED BY public.developer_achievements.id;'''))

    op.execute(text('''ALTER SEQUENCE public.developer_api_keys_id_seq OWNED BY public.developer_api_keys.id;'''))

    op.execute(text('''ALTER SEQUENCE public.developer_notification_reads_id_seq OWNED BY public.developer_notification_reads.id;'''))

    op.execute(text('''ALTER SEQUENCE public.developers_id_seq OWNED BY public.developers.id;'''))

    op.execute(text('''ALTER SEQUENCE public.disputes_id_seq OWNED BY public.disputes.id;'''))

    op.execute(text('''ALTER SEQUENCE public.event_emission_policies_id_seq OWNED BY public.event_emission_policies.id;'''))

    op.execute(text('''ALTER SEQUENCE public.evidence_id_seq OWNED BY public.evidence.id;'''))

    op.execute(text('''ALTER SEQUENCE public.funding_requests_id_seq OWNED BY public.funding_requests.id;'''))

    op.execute(text('''ALTER SEQUENCE public.game_results_id_seq OWNED BY public.game_results.id;'''))

    op.execute(text('''ALTER SEQUENCE public.governance_proposals_id_seq OWNED BY public.governance_proposals.id;'''))

    op.execute(text('''ALTER SEQUENCE public.invite_codes_id_seq OWNED BY public.invite_codes.id;'''))

    op.execute(text('''ALTER SEQUENCE public.peer_registries_id_seq OWNED BY public.peer_registries.id;'''))

    op.execute(text('''ALTER SEQUENCE public.refactoring_upgrade_contracts_id_seq OWNED BY public.refactoring_upgrade_contracts.id;'''))

    op.execute(text('''ALTER SEQUENCE public.registry_enforcement_policies_id_seq OWNED BY public.registry_enforcement_policies.id;'''))

    op.execute(text('''ALTER SEQUENCE public.staking_apy_tiers_id_seq OWNED BY public.staking_apy_tiers.id;'''))

    op.execute(text('''ALTER SEQUENCE public.staking_rewards_id_seq OWNED BY public.staking_rewards.id;'''))

    op.execute(text('''ALTER SEQUENCE public.support_messages_id_seq OWNED BY public.support_messages.id;'''))

    op.execute(text('''ALTER SEQUENCE public.support_tickets_id_seq OWNED BY public.support_tickets.id;'''))

    op.execute(text('''ALTER SEQUENCE public.system_events_id_seq OWNED BY public.system_events.id;'''))

    op.execute(text('''ALTER SEQUENCE public.velocity_metrics_id_seq OWNED BY public.velocity_metrics.id;'''))

    op.execute(text('''ALTER SEQUENCE public.votes_id_seq OWNED BY public.votes.id;'''))

    op.execute(text('''ALTER TABLE ONLY public.achievement_rewards ALTER COLUMN id SET DEFAULT nextval('public.achievement_rewards_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.admin_broadcasts ALTER COLUMN id SET DEFAULT nextval('public.admin_broadcasts_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_daily_stats ALTER COLUMN id SET DEFAULT nextval('public.agent_daily_stats_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_logs ALTER COLUMN id SET DEFAULT nextval('public.agent_logs_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_metrics ALTER COLUMN id SET DEFAULT nextval('public.agent_metrics_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_requests ALTER COLUMN id SET DEFAULT nextval('public.agent_requests_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.agents ALTER COLUMN id SET DEFAULT nextval('public.agents_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.auditor_flag_logs ALTER COLUMN id SET DEFAULT nextval('public.auditor_flag_logs_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.beta_access_requests ALTER COLUMN id SET DEFAULT nextval('public.beta_access_requests_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.bootstrap_tokens ALTER COLUMN id SET DEFAULT nextval('public.bootstrap_tokens_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_achievements ALTER COLUMN id SET DEFAULT nextval('public.developer_achievements_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_api_keys ALTER COLUMN id SET DEFAULT nextval('public.developer_api_keys_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_notification_reads ALTER COLUMN id SET DEFAULT nextval('public.developer_notification_reads_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.developers ALTER COLUMN id SET DEFAULT nextval('public.developers_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.disputes ALTER COLUMN id SET DEFAULT nextval('public.disputes_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.event_emission_policies ALTER COLUMN id SET DEFAULT nextval('public.event_emission_policies_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.evidence ALTER COLUMN id SET DEFAULT nextval('public.evidence_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.funding_requests ALTER COLUMN id SET DEFAULT nextval('public.funding_requests_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.game_results ALTER COLUMN id SET DEFAULT nextval('public.game_results_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.governance_proposals ALTER COLUMN id SET DEFAULT nextval('public.governance_proposals_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.invite_codes ALTER COLUMN id SET DEFAULT nextval('public.invite_codes_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.peer_registries ALTER COLUMN id SET DEFAULT nextval('public.peer_registries_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.refactoring_upgrade_contracts ALTER COLUMN id SET DEFAULT nextval('public.refactoring_upgrade_contracts_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_enforcement_policies ALTER COLUMN id SET DEFAULT nextval('public.registry_enforcement_policies_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_apy_tiers ALTER COLUMN id SET DEFAULT nextval('public.staking_apy_tiers_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_rewards ALTER COLUMN id SET DEFAULT nextval('public.staking_rewards_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.support_messages ALTER COLUMN id SET DEFAULT nextval('public.support_messages_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.support_tickets ALTER COLUMN id SET DEFAULT nextval('public.support_tickets_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.system_events ALTER COLUMN id SET DEFAULT nextval('public.system_events_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.velocity_metrics ALTER COLUMN id SET DEFAULT nextval('public.velocity_metrics_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.votes ALTER COLUMN id SET DEFAULT nextval('public.votes_id_seq'::regclass);'''))


    # ── Primary keys ──
    op.execute(text('''ALTER TABLE ONLY public.a2a_payment_authorizations
    ADD CONSTRAINT a2a_payment_authorizations_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.achievement_rewards
    ADD CONSTRAINT achievement_rewards_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.admin_broadcasts
    ADD CONSTRAINT admin_broadcasts_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_capabilities
    ADD CONSTRAINT agent_capabilities_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_cards
    ADD CONSTRAINT agent_cards_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_daily_stats
    ADD CONSTRAINT agent_daily_stats_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_deployments
    ADD CONSTRAINT agent_deployments_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_endpoints
    ADD CONSTRAINT agent_endpoints_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_logs
    ADD CONSTRAINT agent_logs_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_metrics
    ADD CONSTRAINT agent_metrics_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_pipelines
    ADD CONSTRAINT agent_pipelines_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_requests
    ADD CONSTRAINT agent_requests_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_tags
    ADD CONSTRAINT agent_tags_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.auditor_flag_logs
    ADD CONSTRAINT auditor_flag_logs_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.beta_access_requests
    ADD CONSTRAINT beta_access_requests_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.bootstrap_tokens
    ADD CONSTRAINT bootstrap_tokens_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.cross_registry_settlements
    ADD CONSTRAINT cross_registry_settlements_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.deployment_webhooks
    ADD CONSTRAINT deployment_webhooks_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_achievements
    ADD CONSTRAINT developer_achievements_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_api_keys
    ADD CONSTRAINT developer_api_keys_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_notification_reads
    ADD CONSTRAINT developer_notification_reads_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_webhooks
    ADD CONSTRAINT developer_webhooks_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.developers
    ADD CONSTRAINT developers_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.disputes
    ADD CONSTRAINT disputes_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.enforcement_actions
    ADD CONSTRAINT enforcement_actions_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.event_emission_policies
    ADD CONSTRAINT event_emission_policies_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT evidence_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.federated_registry_compliance
    ADD CONSTRAINT federated_registry_compliance_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.federation_licenses
    ADD CONSTRAINT federation_licenses_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.funding_requests
    ADD CONSTRAINT funding_requests_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.game_results
    ADD CONSTRAINT game_results_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.global_trust_vectors
    ADD CONSTRAINT global_trust_vectors_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.governance_proposals
    ADD CONSTRAINT governance_proposals_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.idempotency_keys
    ADD CONSTRAINT idempotency_keys_pkey PRIMARY KEY (key);'''))

    op.execute(text('''ALTER TABLE ONLY public.invite_codes
    ADD CONSTRAINT invite_codes_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.local_trust_scores
    ADD CONSTRAINT local_trust_scores_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.oauth_token_exchanges
    ADD CONSTRAINT oauth_token_exchanges_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.operator_applications
    ADD CONSTRAINT operator_applications_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_invitations
    ADD CONSTRAINT organization_invitations_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT organization_members_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.peer_registries
    ADD CONSTRAINT peer_registries_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.pipeline_purchases
    ADD CONSTRAINT pipeline_purchases_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.pipeline_templates
    ADD CONSTRAINT pipeline_templates_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.refactoring_upgrade_contracts
    ADD CONSTRAINT refactoring_upgrade_contracts_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_enforcement_policies
    ADD CONSTRAINT registry_enforcement_policies_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_operating_state
    ADD CONSTRAINT registry_operating_state_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_trust_config
    ADD CONSTRAINT registry_trust_config_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.reputation_bonds
    ADD CONSTRAINT reputation_bonds_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.security_audit_logs
    ADD CONSTRAINT security_audit_logs_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.stake_transactions
    ADD CONSTRAINT stake_transactions_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.stakes
    ADD CONSTRAINT stakes_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_apy_config
    ADD CONSTRAINT staking_apy_config_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_apy_tiers
    ADD CONSTRAINT staking_apy_tiers_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_distributions
    ADD CONSTRAINT staking_distributions_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_reward_records
    ADD CONSTRAINT staking_reward_records_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_rewards
    ADD CONSTRAINT staking_rewards_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.support_messages
    ADD CONSTRAINT support_messages_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.support_tickets
    ADD CONSTRAINT support_tickets_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.system_events
    ADD CONSTRAINT system_events_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT team_members_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.token_revocations
    ADD CONSTRAINT token_revocations_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.transaction_fee_records
    ADD CONSTRAINT transaction_fee_records_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.velocity_metrics
    ADD CONSTRAINT velocity_metrics_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.votes
    ADD CONSTRAINT votes_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT webhook_deliveries_pkey PRIMARY KEY (id);'''))


    # ── Unique constraints ──
    op.execute(text('''ALTER TABLE ONLY public.a2a_payment_authorizations
    ADD CONSTRAINT a2a_payment_authorizations_idempotency_key_key UNIQUE (idempotency_key);'''))

    op.execute(text('''ALTER TABLE ONLY public.a2a_payment_authorizations
    ADD CONSTRAINT a2a_payment_authorizations_token_hash_key UNIQUE (token_hash);'''))

    op.execute(text('''ALTER TABLE ONLY public.achievement_rewards
    ADD CONSTRAINT achievement_rewards_achievement_type_key UNIQUE (achievement_type);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_metrics
    ADD CONSTRAINT agent_metrics_agent_id_key UNIQUE (agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.beta_access_requests
    ADD CONSTRAINT beta_access_requests_email_key UNIQUE (email);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_api_keys
    ADD CONSTRAINT developer_api_keys_hashed_key_key UNIQUE (hashed_key);'''))

    op.execute(text('''ALTER TABLE ONLY public.event_emission_policies
    ADD CONSTRAINT event_emission_policies_event_type_key UNIQUE (event_type);'''))

    op.execute(text('''ALTER TABLE ONLY public.federated_registry_compliance
    ADD CONSTRAINT federated_registry_compliance_peer_registry_id_key UNIQUE (peer_registry_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.federation_licenses
    ADD CONSTRAINT federation_licenses_operator_did_key UNIQUE (operator_did);'''))

    op.execute(text('''ALTER TABLE ONLY public.peer_registries
    ADD CONSTRAINT peer_registries_base_url_key UNIQUE (base_url);'''))

    op.execute(text('''ALTER TABLE ONLY public.peer_registries
    ADD CONSTRAINT peer_registries_name_key UNIQUE (name);'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_trust_config
    ADD CONSTRAINT registry_trust_config_registry_name_key UNIQUE (registry_name);'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_trust_config
    ADD CONSTRAINT registry_trust_config_registry_url_key UNIQUE (registry_url);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_apy_tiers
    ADD CONSTRAINT staking_apy_tiers_lock_period_days_key UNIQUE (lock_period_days);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_distributions
    ADD CONSTRAINT staking_distributions_distribution_date_key UNIQUE (distribution_date);'''))

    op.execute(text('''ALTER TABLE ONLY public.token_revocations
    ADD CONSTRAINT token_revocations_token_jti_key UNIQUE (token_jti);'''))

    op.execute(text('''ALTER TABLE ONLY public.reputation_bonds
    ADD CONSTRAINT uix_bond_agent_did UNIQUE (agent_did);'''))

    op.execute(text('''ALTER TABLE ONLY public.global_trust_vectors
    ADD CONSTRAINT uix_gtv_agent UNIQUE (agent_did);'''))

    op.execute(text('''ALTER TABLE ONLY public.local_trust_scores
    ADD CONSTRAINT uix_lt_pair UNIQUE (from_did, to_did);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_notification_reads
    ADD CONSTRAINT uix_notif_read_pair UNIQUE (broadcast_id, developer_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.votes
    ADD CONSTRAINT uix_votes_proposal_voter UNIQUE (proposal_id, voter_did);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_capabilities
    ADD CONSTRAINT uq_agent_capabilities_agent_did_name UNIQUE (agent_did, name);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_daily_stats
    ADD CONSTRAINT uq_agent_daily_stats_agent_date UNIQUE (agent_id, date);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_endpoints
    ADD CONSTRAINT uq_agent_endpoints_agent_did_path_method UNIQUE (agent_did, path, method);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_pipelines
    ADD CONSTRAINT uq_agent_pipeline_name UNIQUE (agent_did, pipeline_name);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_tags
    ADD CONSTRAINT uq_agent_tags_agent_did_tag UNIQUE (agent_did, tag);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT uq_agent_versions_agent_did_version UNIQUE (agent_did, version);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_achievements
    ADD CONSTRAINT uq_dev_achievement_type UNIQUE (developer_id, achievement_type);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_invitations
    ADD CONSTRAINT uq_org_invitations_token UNIQUE (token);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT uq_org_members UNIQUE (organization_id, developer_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT uq_organizations_slug UNIQUE (slug);'''))

    op.execute(text('''ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT uq_team_members UNIQUE (team_id, developer_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teams
    ADD CONSTRAINT uq_teams_org_name UNIQUE (organization_id, name);'''))

    op.execute(text('''ALTER TABLE ONLY public.pipeline_purchases
    ADD CONSTRAINT uq_template_buyer UNIQUE (template_id, buyer_did);'''))


    # ── Indexes ──
    op.execute(text('''CREATE INDEX idx_agent_deployments_agent ON public.agent_deployments USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX idx_agent_deployments_environment ON public.agent_deployments USING btree (environment);'''))

    op.execute(text('''CREATE INDEX idx_agent_deployments_started ON public.agent_deployments USING btree (started_at);'''))

    op.execute(text('''CREATE INDEX idx_agent_deployments_status ON public.agent_deployments USING btree (status);'''))

    op.execute(text('''CREATE INDEX idx_agent_pipelines_active ON public.agent_pipelines USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX idx_agent_pipelines_agent ON public.agent_pipelines USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX idx_agents_cicd_enabled ON public.agents USING btree (cicd_enabled);'''))

    op.execute(text('''CREATE INDEX idx_agents_last_deployment ON public.agents USING btree (last_deployment_at);'''))

    op.execute(text('''CREATE INDEX idx_agents_org ON public.agents USING btree (organization_id) WHERE (organization_id IS NOT NULL);'''))

    op.execute(text('''CREATE INDEX idx_agents_team ON public.agents USING btree (team_id) WHERE (team_id IS NOT NULL);'''))

    op.execute(text('''CREATE INDEX idx_apy_config_active ON public.staking_apy_config USING btree (is_active, tier_name);'''))

    op.execute(text('''CREATE INDEX idx_beta_requests_status ON public.beta_access_requests USING btree (status);'''))

    op.execute(text('''CREATE INDEX idx_deployment_webhooks_deployment ON public.deployment_webhooks USING btree (deployment_id);'''))

    op.execute(text('''CREATE INDEX idx_deployment_webhooks_processed ON public.deployment_webhooks USING btree (processed);'''))

    op.execute(text('''CREATE INDEX idx_developers_two_fa_active ON public.developers USING btree (id) WHERE (two_fa_enabled = true);'''))

    op.execute(text('''CREATE INDEX idx_developers_two_fa_enabled ON public.developers USING btree (two_fa_enabled);'''))

    op.execute(text('''CREATE INDEX idx_distributions_date ON public.staking_distributions USING btree (distribution_date);'''))

    op.execute(text('''CREATE INDEX idx_distributions_status ON public.staking_distributions USING btree (status);'''))

    op.execute(text('''CREATE INDEX idx_gr_agent ON public.game_results USING btree (agent_did) WHERE (agent_did IS NOT NULL);'''))

    op.execute(text('''CREATE INDEX idx_gr_created ON public.game_results USING btree (created_at DESC);'''))

    op.execute(text('''CREATE INDEX idx_gr_score ON public.game_results USING btree (game_type, score DESC);'''))

    op.execute(text('''CREATE INDEX idx_gr_type ON public.game_results USING btree (game_type);'''))

    op.execute(text('''CREATE INDEX idx_pipeline_purchases_buyer ON public.pipeline_purchases USING btree (buyer_did);'''))

    op.execute(text('''CREATE INDEX idx_pipeline_purchases_template ON public.pipeline_purchases USING btree (template_id);'''))

    op.execute(text('''CREATE INDEX idx_pipeline_templates_category ON public.pipeline_templates USING btree (category);'''))

    op.execute(text('''CREATE INDEX idx_pipeline_templates_price ON public.pipeline_templates USING btree (price_teg);'''))

    op.execute(text('''CREATE INDEX idx_pipeline_templates_rating ON public.pipeline_templates USING btree (rating);'''))

    op.execute(text('''CREATE INDEX idx_reward_records_agent ON public.staking_reward_records USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX idx_reward_records_distribution ON public.staking_reward_records USING btree (distribution_id);'''))

    op.execute(text('''CREATE INDEX idx_reward_records_status ON public.staking_reward_records USING btree (status);'''))

    op.execute(text('''CREATE INDEX idx_security_audit_actor_id ON public.security_audit_logs USING btree (actor_id);'''))

    op.execute(text('''CREATE INDEX idx_security_audit_correlation_id ON public.security_audit_logs USING btree (correlation_id);'''))

    op.execute(text('''CREATE INDEX idx_security_audit_event_type ON public.security_audit_logs USING btree (event_type);'''))

    op.execute(text('''CREATE INDEX idx_security_audit_severity ON public.security_audit_logs USING btree (severity, "timestamp");'''))

    op.execute(text('''CREATE INDEX idx_security_audit_timestamp ON public.security_audit_logs USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX idx_token_revocation_exp ON public.token_revocations USING btree (token_exp);'''))

    op.execute(text('''CREATE INDEX idx_token_revocation_jti ON public.token_revocations USING btree (token_jti);'''))

    op.execute(text('''CREATE INDEX ix_a2a_pay_caller ON public.a2a_payment_authorizations USING btree (caller_did);'''))

    op.execute(text('''CREATE INDEX ix_a2a_pay_status ON public.a2a_payment_authorizations USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_a2a_pay_target ON public.a2a_payment_authorizations USING btree (target_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_agent_capabilities_agent_did ON public.agent_capabilities USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_agent_capabilities_category ON public.agent_capabilities USING btree (category);'''))

    op.execute(text('''CREATE INDEX ix_agent_capabilities_is_active ON public.agent_capabilities USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_agent_capabilities_name ON public.agent_capabilities USING btree (name);'''))

    op.execute(text('''CREATE INDEX ix_agent_cards_card_data_tags_gin ON public.agent_cards USING gin (card_data jsonb_path_ops);'''))

    op.execute(text('''CREATE INDEX ix_agent_cards_description ON public.agent_cards USING btree (description);'''))

    op.execute(text('''CREATE INDEX ix_agent_cards_developer_id ON public.agent_cards USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_agent_cards_is_active ON public.agent_cards USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_agent_cards_name ON public.agent_cards USING btree (name);'''))

    op.execute(text('''CREATE INDEX ix_agent_daily_stats_agent_date ON public.agent_daily_stats USING btree (agent_id, date);'''))

    op.execute(text('''CREATE INDEX ix_agent_daily_stats_agent_id ON public.agent_daily_stats USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_agent_daily_stats_date ON public.agent_daily_stats USING btree (date);'''))

    op.execute(text('''CREATE INDEX ix_agent_endpoints_agent_did ON public.agent_endpoints USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_agent_endpoints_is_active ON public.agent_endpoints USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_agent_endpoints_method ON public.agent_endpoints USING btree (method);'''))

    op.execute(text('''CREATE INDEX ix_agent_endpoints_path ON public.agent_endpoints USING btree (path);'''))

    op.execute(text('''CREATE INDEX ix_agent_logs_agent_did ON public.agent_logs USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_agent_logs_agent_did_timestamp ON public.agent_logs USING btree (agent_did, "timestamp");'''))

    op.execute(text('''CREATE INDEX ix_agent_logs_level ON public.agent_logs USING btree (level);'''))

    op.execute(text('''CREATE INDEX ix_agent_logs_timestamp ON public.agent_logs USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX ix_agent_metrics_agent_did ON public.agent_metrics USING btree (agent_did);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_agent_metrics_agent_id ON public.agent_metrics USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_agent_requests_agent_did ON public.agent_requests USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_agent_requests_agent_id ON public.agent_requests USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_agent_requests_agent_time ON public.agent_requests USING btree (agent_id, created_at);'''))

    op.execute(text('''CREATE INDEX ix_agent_requests_created_at ON public.agent_requests USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_agent_requests_endpoint ON public.agent_requests USING btree (endpoint);'''))

    op.execute(text('''CREATE INDEX ix_agent_requests_status_code ON public.agent_requests USING btree (status_code);'''))

    op.execute(text('''CREATE INDEX ix_agent_requests_status_time ON public.agent_requests USING btree (status_code, created_at);'''))

    op.execute(text('''CREATE INDEX ix_agent_tags_agent_did ON public.agent_tags USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_agent_tags_tag ON public.agent_tags USING btree (tag);'''))

    op.execute(text('''CREATE INDEX ix_agent_versions_agent_did ON public.agent_versions USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_agent_versions_created_at ON public.agent_versions USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_agent_versions_is_current ON public.agent_versions USING btree (is_current);'''))

    op.execute(text('''CREATE INDEX ix_agent_versions_version ON public.agent_versions USING btree (version);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_agents_client_id ON public.agents USING btree (client_id);'''))

    op.execute(text('''CREATE INDEX ix_agents_creator_developer_id ON public.agents USING btree (creator_developer_id);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_agents_did ON public.agents USING btree (did);'''))

    op.execute(text('''CREATE INDEX ix_agents_enforcement_level ON public.agents USING btree (enforcement_level);'''))

    op.execute(text('''CREATE INDEX ix_agents_enforcement_status ON public.agents USING btree (enforcement_status);'''))

    op.execute(text('''CREATE INDEX ix_agents_id ON public.agents USING btree (id);'''))

    op.execute(text('''CREATE INDEX ix_agents_latitude ON public.agents USING btree (latitude);'''))

    op.execute(text('''CREATE INDEX ix_agents_liquid_balance ON public.agents USING btree (liquid_balance);'''))

    op.execute(text('''CREATE INDEX ix_agents_longitude ON public.agents USING btree (longitude);'''))

    op.execute(text('''CREATE INDEX ix_agents_reputation_score ON public.agents USING btree (reputation_score);'''))

    op.execute(text('''CREATE INDEX ix_agents_staked_balance ON public.agents USING btree (staked_balance);'''))

    op.execute(text('''CREATE INDEX ix_agents_status ON public.agents USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_auditor_flag_logs_created_at ON public.auditor_flag_logs USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_auditor_flag_logs_flag_type ON public.auditor_flag_logs USING btree (flag_type);'''))

    op.execute(text('''CREATE INDEX ix_auditor_flag_logs_flagged_agent_did ON public.auditor_flag_logs USING btree (flagged_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_auditor_flag_logs_severity ON public.auditor_flag_logs USING btree (severity);'''))

    op.execute(text('''CREATE INDEX ix_bond_agent ON public.reputation_bonds USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_bond_status ON public.reputation_bonds USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_bootstrap_tokens_creator_developer_id ON public.bootstrap_tokens USING btree (creator_developer_id);'''))

    op.execute(text('''CREATE INDEX ix_bootstrap_tokens_expires_at ON public.bootstrap_tokens USING btree (expires_at);'''))

    op.execute(text('''CREATE INDEX ix_bootstrap_tokens_id ON public.bootstrap_tokens USING btree (id);'''))

    op.execute(text('''CREATE INDEX ix_bootstrap_tokens_is_used ON public.bootstrap_tokens USING btree (is_used);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_bootstrap_tokens_token_value ON public.bootstrap_tokens USING btree (token_value);'''))

    op.execute(text('''CREATE INDEX ix_broadcasts_active_created ON public.admin_broadcasts USING btree (is_active, created_at);'''))

    op.execute(text('''CREATE INDEX ix_cross_registry_settlements_complainant_did ON public.cross_registry_settlements USING btree (complainant_did);'''))

    op.execute(text('''CREATE INDEX ix_cross_registry_settlements_defendant_did ON public.cross_registry_settlements USING btree (defendant_did);'''))

    op.execute(text('''CREATE INDEX ix_cross_registry_settlements_dispute_id ON public.cross_registry_settlements USING btree (dispute_id);'''))

    op.execute(text('''CREATE INDEX ix_cross_registry_settlements_status ON public.cross_registry_settlements USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_crs_saga_state ON public.cross_registry_settlements USING btree (saga_state);'''))

    op.execute(text('''CREATE INDEX ix_crs_saga_timeout ON public.cross_registry_settlements USING btree (saga_timeout_at);'''))

    op.execute(text('''CREATE INDEX ix_dev_achievements_dev_id ON public.developer_achievements USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_developer_api_keys_developer_id ON public.developer_api_keys USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_developer_api_keys_id ON public.developer_api_keys USING btree (id);'''))

    op.execute(text('''CREATE INDEX ix_developer_api_keys_is_active ON public.developer_api_keys USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_developer_api_keys_key_prefix ON public.developer_api_keys USING btree (key_prefix);'''))

    op.execute(text('''CREATE INDEX ix_developer_webhooks_developer_active ON public.developer_webhooks USING btree (developer_id, is_active);'''))

    op.execute(text('''CREATE INDEX ix_developer_webhooks_developer_id ON public.developer_webhooks USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_developer_webhooks_is_active ON public.developer_webhooks USING btree (is_active);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_developers_email ON public.developers USING btree (email);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_developers_email_verification_token ON public.developers USING btree (email_verification_token);'''))

    op.execute(text('''CREATE INDEX ix_developers_id ON public.developers USING btree (id);'''))

    op.execute(text('''CREATE INDEX ix_developers_is_admin ON public.developers USING btree (is_admin);'''))

    op.execute(text('''CREATE INDEX ix_developers_is_verified ON public.developers USING btree (is_verified);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_developers_name ON public.developers USING btree (name);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_developers_password_reset_token ON public.developers USING btree (password_reset_token);'''))

    op.execute(text('''CREATE INDEX ix_disputes_complainant_did ON public.disputes USING btree (complainant_did);'''))

    op.execute(text('''CREATE INDEX ix_disputes_created_at ON public.disputes USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_disputes_defendant_did ON public.disputes USING btree (defendant_did);'''))

    op.execute(text('''CREATE INDEX ix_disputes_status ON public.disputes USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_enforcement_agent ON public.enforcement_actions USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_enforcement_created ON public.enforcement_actions USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_enforcement_pending ON public.enforcement_actions USING btree (status) WHERE ((status)::text = 'pending_approval'::text);'''))

    op.execute(text('''CREATE INDEX ix_enforcement_status ON public.enforcement_actions USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_event_emission_policies_event_type ON public.event_emission_policies USING btree (event_type);'''))

    op.execute(text('''CREATE INDEX ix_evidence_created_at ON public.evidence USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_evidence_dispute_id ON public.evidence USING btree (dispute_id);'''))

    op.execute(text('''CREATE INDEX ix_evidence_submitter_did ON public.evidence USING btree (submitter_did);'''))

    op.execute(text('''CREATE INDEX ix_federation_licenses_license_key_hash ON public.federation_licenses USING btree (license_key_hash);'''))

    op.execute(text('''CREATE INDEX ix_federation_licenses_operator_did ON public.federation_licenses USING btree (operator_did);'''))

    op.execute(text('''CREATE INDEX ix_federation_licenses_status ON public.federation_licenses USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_fee_agent ON public.transaction_fee_records USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_fee_created ON public.transaction_fee_records USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_fee_transaction ON public.transaction_fee_records USING btree (transaction_id);'''))

    op.execute(text('''CREATE INDEX ix_frc_peer ON public.federated_registry_compliance USING btree (peer_registry_id);'''))

    op.execute(text('''CREATE INDEX ix_frc_status ON public.federated_registry_compliance USING btree (federation_status);'''))

    op.execute(text('''CREATE INDEX ix_funding_requests_requester_did ON public.funding_requests USING btree (requester_did);'''))

    op.execute(text('''CREATE INDEX ix_funding_requests_status ON public.funding_requests USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_governance_proposals_created_at ON public.governance_proposals USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_governance_proposals_end_timestamp ON public.governance_proposals USING btree (end_timestamp);'''))

    op.execute(text('''CREATE INDEX ix_governance_proposals_proposal_type ON public.governance_proposals USING btree (proposal_type);'''))

    op.execute(text('''CREATE INDEX ix_governance_proposals_proposer_did ON public.governance_proposals USING btree (proposer_did);'''))

    op.execute(text('''CREATE INDEX ix_governance_proposals_status ON public.governance_proposals USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_gtv_epoch ON public.global_trust_vectors USING btree (epoch);'''))

    op.execute(text('''CREATE INDEX ix_idempotency_keys_agent_id ON public.idempotency_keys USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_idempotency_keys_created_at ON public.idempotency_keys USING btree (created_at);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_invite_codes_code ON public.invite_codes USING btree (code);'''))

    op.execute(text('''CREATE INDEX ix_invite_codes_id ON public.invite_codes USING btree (id);'''))

    op.execute(text('''CREATE INDEX ix_lt_from ON public.local_trust_scores USING btree (from_did);'''))

    op.execute(text('''CREATE INDEX ix_lt_to ON public.local_trust_scores USING btree (to_did);'''))

    op.execute(text('''CREATE INDEX ix_lt_updated ON public.local_trust_scores USING btree (last_updated);'''))

    op.execute(text('''CREATE INDEX ix_notif_read_dev ON public.developer_notification_reads USING btree (developer_id, broadcast_id);'''))

    op.execute(text('''CREATE INDEX ix_oauth_exchanges_agent_registry ON public.oauth_token_exchanges USING btree (agent_did, source_registry);'''))

    op.execute(text('''CREATE INDEX ix_oauth_exchanges_expires ON public.oauth_token_exchanges USING btree (expires_at);'''))

    op.execute(text('''CREATE INDEX ix_oauth_token_exchanges_agent_did ON public.oauth_token_exchanges USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_oauth_token_exchanges_expires_at ON public.oauth_token_exchanges USING btree (expires_at);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_oauth_token_exchanges_issued_token_jti ON public.oauth_token_exchanges USING btree (issued_token_jti);'''))

    op.execute(text('''CREATE INDEX ix_oauth_token_exchanges_source_registry ON public.oauth_token_exchanges USING btree (source_registry);'''))

    op.execute(text('''CREATE INDEX ix_oauth_token_exchanges_source_token_jti ON public.oauth_token_exchanges USING btree (source_token_jti);'''))

    op.execute(text('''CREATE INDEX ix_operator_applications_developer_id ON public.operator_applications USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_operator_applications_docker_pull_token_hash ON public.operator_applications USING btree (docker_pull_token_hash) WHERE (docker_pull_token_hash IS NOT NULL);'''))

    op.execute(text('''CREATE INDEX ix_operator_applications_email ON public.operator_applications USING btree (email);'''))

    op.execute(text('''CREATE INDEX ix_operator_applications_status ON public.operator_applications USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_org_invitations_email ON public.organization_invitations USING btree (email);'''))

    op.execute(text('''CREATE INDEX ix_org_invitations_org_id ON public.organization_invitations USING btree (organization_id);'''))

    op.execute(text('''CREATE INDEX ix_org_invitations_status ON public.organization_invitations USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_org_invitations_token ON public.organization_invitations USING btree (token);'''))

    op.execute(text('''CREATE INDEX ix_organization_members_dev_id ON public.organization_members USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_organization_members_org_id ON public.organization_members USING btree (organization_id);'''))

    op.execute(text('''CREATE INDEX ix_organization_members_role ON public.organization_members USING btree (role);'''))

    op.execute(text('''CREATE INDEX ix_organizations_is_active ON public.organizations USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_organizations_owner_id ON public.organizations USING btree (owner_id);'''))

    op.execute(text('''CREATE INDEX ix_organizations_slug ON public.organizations USING btree (slug);'''))

    op.execute(text('''CREATE INDEX ix_peer_bayesian_discount ON public.peer_registries USING btree (bayesian_discount);'''))

    op.execute(text('''CREATE INDEX ix_peer_last_interaction ON public.peer_registries USING btree (last_interaction_at);'''))

    op.execute(text('''CREATE INDEX ix_peer_registries_base_url ON public.peer_registries USING btree (base_url);'''))

    op.execute(text('''CREATE INDEX ix_peer_registries_id ON public.peer_registries USING btree (id);'''))

    op.execute(text('''CREATE INDEX ix_peer_registries_name ON public.peer_registries USING btree (name);'''))

    op.execute(text('''CREATE INDEX ix_peer_registries_owner_developer_id ON public.peer_registries USING btree (owner_developer_id);'''))

    op.execute(text('''CREATE INDEX ix_peer_registries_status ON public.peer_registries USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_policy_version ON public.registry_enforcement_policies USING btree (version);'''))

    op.execute(text('''CREATE INDEX ix_registry_trust_config_is_active ON public.registry_trust_config USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_registry_trust_config_registry_url ON public.registry_trust_config USING btree (registry_url);'''))

    op.execute(text('''CREATE INDEX ix_ruc_client_agent_did ON public.refactoring_upgrade_contracts USING btree (client_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_ruc_created_at ON public.refactoring_upgrade_contracts USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_ruc_status ON public.refactoring_upgrade_contracts USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_ruc_upgrader_agent_did ON public.refactoring_upgrade_contracts USING btree (upgrader_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_stake_transactions_agent_id ON public.stake_transactions USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_stake_transactions_stake_id ON public.stake_transactions USING btree (stake_id);'''))

    op.execute(text('''CREATE INDEX ix_stake_transactions_status ON public.stake_transactions USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_stake_transactions_timestamp ON public.stake_transactions USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX ix_stake_transactions_transaction_type ON public.stake_transactions USING btree (transaction_type);'''))

    op.execute(text('''CREATE INDEX ix_stakes_active_by_agent ON public.stakes USING btree (agent_id, is_active);'''))

    op.execute(text('''CREATE INDEX ix_stakes_agent_did ON public.stakes USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_stakes_agent_id ON public.stakes USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_stakes_is_active ON public.stakes USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_stakes_lock_expiry ON public.stakes USING btree (lock_expiry_at);'''))

    op.execute(text('''CREATE INDEX ix_stakes_staked_at ON public.stakes USING btree (staked_at);'''))

    op.execute(text('''CREATE INDEX ix_staking_apy_tiers_is_active ON public.staking_apy_tiers USING btree (is_active);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_staking_apy_tiers_lock_period ON public.staking_apy_tiers USING btree (lock_period_days);'''))

    op.execute(text('''CREATE INDEX ix_staking_rewards_agent_id ON public.staking_rewards USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_staking_rewards_earned_at ON public.staking_rewards USING btree (earned_at);'''))

    op.execute(text('''CREATE INDEX ix_staking_rewards_is_claimed ON public.staking_rewards USING btree (is_claimed);'''))

    op.execute(text('''CREATE INDEX ix_staking_rewards_stake_id ON public.staking_rewards USING btree (stake_id);'''))

    op.execute(text('''CREATE INDEX ix_support_messages_ticket_id ON public.support_messages USING btree (ticket_id);'''))

    op.execute(text('''CREATE INDEX ix_support_tickets_developer_id ON public.support_tickets USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_support_tickets_status ON public.support_tickets USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_system_events_created_at ON public.system_events USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_system_events_event_type ON public.system_events USING btree (event_type);'''))

    op.execute(text('''CREATE INDEX ix_system_events_id ON public.system_events USING btree (id);'''))

    op.execute(text('''CREATE INDEX ix_team_members_dev_id ON public.team_members USING btree (developer_id);'''))

    op.execute(text('''CREATE INDEX ix_team_members_team_id ON public.team_members USING btree (team_id);'''))

    op.execute(text('''CREATE INDEX ix_teams_is_active ON public.teams USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_teams_organization_id ON public.teams USING btree (organization_id);'''))

    op.execute(text('''CREATE INDEX ix_velocity_agent ON public.velocity_metrics USING btree (agent_did);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_velocity_agent_window ON public.velocity_metrics USING btree (agent_did, window_start);'''))

    op.execute(text('''CREATE INDEX ix_velocity_window ON public.velocity_metrics USING btree (window_start);'''))

    op.execute(text('''CREATE INDEX ix_votes_created_at ON public.votes USING btree (created_at);'''))

    op.execute(text('''CREATE INDEX ix_votes_proposal_id ON public.votes USING btree (proposal_id);'''))

    op.execute(text('''CREATE INDEX ix_votes_voter_did ON public.votes USING btree (voter_did);'''))

    op.execute(text('''CREATE INDEX ix_webhook_deliveries_delivered_at ON public.webhook_deliveries USING btree (delivered_at);'''))

    op.execute(text('''CREATE INDEX ix_webhook_deliveries_event_type ON public.webhook_deliveries USING btree (event_type);'''))

    op.execute(text('''CREATE INDEX ix_webhook_deliveries_next_retry ON public.webhook_deliveries USING btree (next_retry_at);'''))

    op.execute(text('''CREATE INDEX ix_webhook_deliveries_webhook_event ON public.webhook_deliveries USING btree (webhook_id, event_type);'''))

    op.execute(text('''CREATE INDEX ix_webhook_deliveries_webhook_id ON public.webhook_deliveries USING btree (webhook_id);'''))

    op.execute(text('''CREATE UNIQUE INDEX uix_agent_cards_agent_did ON public.agent_cards USING btree (agent_did) WHERE (agent_did IS NOT NULL);'''))

    op.execute(text('''CREATE UNIQUE INDEX uix_policy_active ON public.registry_enforcement_policies USING btree (is_active) WHERE (is_active = true);'''))


    # ── Foreign keys ──
    op.execute(text('''ALTER TABLE ONLY public.admin_broadcasts
    ADD CONSTRAINT admin_broadcasts_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_capabilities
    ADD CONSTRAINT agent_capabilities_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_cards
    ADD CONSTRAINT agent_cards_developer_id_fkey FOREIGN KEY (developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_daily_stats
    ADD CONSTRAINT agent_daily_stats_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_deployments
    ADD CONSTRAINT agent_deployments_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_deployments
    ADD CONSTRAINT agent_deployments_pipeline_id_fkey FOREIGN KEY (pipeline_id) REFERENCES public.agent_pipelines(id) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_deployments
    ADD CONSTRAINT agent_deployments_rollback_of_fkey FOREIGN KEY (rollback_of) REFERENCES public.agent_deployments(id) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_deployments
    ADD CONSTRAINT agent_deployments_triggered_by_fkey FOREIGN KEY (triggered_by) REFERENCES public.developers(id) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_deployments
    ADD CONSTRAINT agent_deployments_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.agent_versions(id) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_endpoints
    ADD CONSTRAINT agent_endpoints_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_metrics
    ADD CONSTRAINT agent_metrics_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_pipelines
    ADD CONSTRAINT agent_pipelines_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_pipelines
    ADD CONSTRAINT agent_pipelines_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.developers(id) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_pipelines
    ADD CONSTRAINT agent_pipelines_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.pipeline_templates(id) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_requests
    ADD CONSTRAINT agent_requests_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_tags
    ADD CONSTRAINT agent_tags_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_versions
    ADD CONSTRAINT agent_versions_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_creator_developer_id_fkey FOREIGN KEY (creator_developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES public.organizations(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.bootstrap_tokens
    ADD CONSTRAINT bootstrap_tokens_creator_developer_id_fkey FOREIGN KEY (creator_developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.deployment_webhooks
    ADD CONSTRAINT deployment_webhooks_deployment_id_fkey FOREIGN KEY (deployment_id) REFERENCES public.agent_deployments(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_achievements
    ADD CONSTRAINT developer_achievements_developer_id_fkey FOREIGN KEY (developer_id) REFERENCES public.developers(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_api_keys
    ADD CONSTRAINT developer_api_keys_developer_id_fkey FOREIGN KEY (developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_notification_reads
    ADD CONSTRAINT developer_notification_reads_broadcast_id_fkey FOREIGN KEY (broadcast_id) REFERENCES public.admin_broadcasts(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_notification_reads
    ADD CONSTRAINT developer_notification_reads_developer_id_fkey FOREIGN KEY (developer_id) REFERENCES public.developers(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.developer_webhooks
    ADD CONSTRAINT developer_webhooks_developer_id_fkey FOREIGN KEY (developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT evidence_dispute_id_fkey FOREIGN KEY (dispute_id) REFERENCES public.disputes(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.federated_registry_compliance
    ADD CONSTRAINT federated_registry_compliance_peer_registry_id_fkey FOREIGN KEY (peer_registry_id) REFERENCES public.peer_registries(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_invitations
    ADD CONSTRAINT fk_org_invitations_inviter FOREIGN KEY (invited_by) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_invitations
    ADD CONSTRAINT fk_org_invitations_organization FOREIGN KEY (organization_id) REFERENCES public.organizations(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT fk_org_members_developer FOREIGN KEY (developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT fk_org_members_inviter FOREIGN KEY (invited_by) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organization_members
    ADD CONSTRAINT fk_org_members_organization FOREIGN KEY (organization_id) REFERENCES public.organizations(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT fk_organizations_owner FOREIGN KEY (owner_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.stake_transactions
    ADD CONSTRAINT fk_stake_transactions_agent_id FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.stakes
    ADD CONSTRAINT fk_stakes_agent_id FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_rewards
    ADD CONSTRAINT fk_staking_rewards_agent_id FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_rewards
    ADD CONSTRAINT fk_staking_rewards_stake_id FOREIGN KEY (stake_id) REFERENCES public.stakes(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT fk_team_members_developer FOREIGN KEY (developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT fk_team_members_team FOREIGN KEY (team_id) REFERENCES public.teams(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teams
    ADD CONSTRAINT fk_teams_organization FOREIGN KEY (organization_id) REFERENCES public.organizations(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.invite_codes
    ADD CONSTRAINT invite_codes_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.invite_codes
    ADD CONSTRAINT invite_codes_used_by_fkey FOREIGN KEY (used_by) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.operator_applications
    ADD CONSTRAINT operator_applications_activated_developer_id_fkey FOREIGN KEY (activated_developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.operator_applications
    ADD CONSTRAINT operator_applications_developer_id_fkey FOREIGN KEY (developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.operator_applications
    ADD CONSTRAINT operator_applications_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.operator_applications
    ADD CONSTRAINT operator_applications_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.peer_registries
    ADD CONSTRAINT peer_registries_approved_by_developer_id_fkey FOREIGN KEY (approved_by_developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.peer_registries
    ADD CONSTRAINT peer_registries_owner_developer_id_fkey FOREIGN KEY (owner_developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.pipeline_purchases
    ADD CONSTRAINT pipeline_purchases_buyer_did_fkey FOREIGN KEY (buyer_did) REFERENCES public.agents(did) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.pipeline_purchases
    ADD CONSTRAINT pipeline_purchases_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.pipeline_templates(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.pipeline_templates
    ADD CONSTRAINT pipeline_templates_author_did_fkey FOREIGN KEY (author_did) REFERENCES public.agents(did) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_enforcement_policies
    ADD CONSTRAINT registry_enforcement_policies_previous_version_fkey FOREIGN KEY (previous_version) REFERENCES public.registry_enforcement_policies(id) ON DELETE SET NULL;'''))

    op.execute(text('''ALTER TABLE ONLY public.registry_trust_config
    ADD CONSTRAINT registry_trust_config_created_by_developer_id_fkey FOREIGN KEY (created_by_developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_reward_records
    ADD CONSTRAINT staking_reward_records_agent_did_fkey FOREIGN KEY (agent_did) REFERENCES public.agents(did);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_reward_records
    ADD CONSTRAINT staking_reward_records_distribution_id_fkey FOREIGN KEY (distribution_id) REFERENCES public.staking_distributions(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.support_messages
    ADD CONSTRAINT support_messages_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.support_tickets(id) ON DELETE CASCADE;'''))

    op.execute(text('''ALTER TABLE ONLY public.support_tickets
    ADD CONSTRAINT support_tickets_developer_id_fkey FOREIGN KEY (developer_id) REFERENCES public.developers(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.votes
    ADD CONSTRAINT votes_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.governance_proposals(id);'''))

    op.execute(text('''ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT webhook_deliveries_webhook_id_fkey FOREIGN KEY (webhook_id) REFERENCES public.developer_webhooks(id);'''))



def downgrade() -> None:
    # Full downgrade is not supported for the squashed migration.
    # To start over, drop and recreate the database.
    pass
