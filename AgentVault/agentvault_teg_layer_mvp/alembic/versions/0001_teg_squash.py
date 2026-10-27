"""Squashed initial TEG schema — all tables from production pg_dump.

Replaces all 14 prior migrations with a single schema.
Handles fresh DB (creates everything) and existing DB (no-op).

Revision ID: 0001_teg_squash
Revises: None
Create Date: 2026-03-29
"""
from alembic import op
from sqlalchemy import text

revision = '0001_teg_squash'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'agent_teg_profiles')"
    )).scalar()

    if result:
        return

    op.execute(text('''CREATE TYPE public.crosstegtransferstatus AS ENUM (
    'INITIATED',
    'FUNDS_LOCKED',
    'PREPARED',
    'COMMITTED',
    'COMPLETED',
    'FAILED',
    'COMPENSATED'
);'''))

    op.execute(text('''CREATE TYPE public.dispute_status_enum AS ENUM (
    'OPEN',
    'UNDER_REVIEW',
    'RESOLVED_FAVOR_INITIATOR',
    'RESOLVED_FAVOR_RESPONDENT',
    'REJECTED',
    'logged_manual_review',
    'resolved_no_action',
    'resolved_penalty_applied'
);'''))

    op.execute(text('''CREATE TYPE public.disputestatus AS ENUM (
    'OPEN',
    'UNDER_REVIEW',
    'RESOLVED_FAVOR_INITIATOR',
    'RESOLVED_FAVOR_RESPONDENT',
    'REJECTED',
    'LOGGED_MANUAL_REVIEW',
    'RESOLVED_NO_ACTION',
    'RESOLVED_PENALTY_APPLIED'
);'''))

    op.execute(text('''CREATE TYPE public.flag_severity_enum AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL'
);'''))

    op.execute(text('''CREATE TYPE public.flag_status_enum AS ENUM (
    'NEW',
    'ACKNOWLEDGED',
    'RESOLVED',
    'new_manual_review',
    'manual_review_confirmed',
    'resolved_false_positive',
    'resolved_action_taken_critical_flag',
    'auto_flagged_manual_review'
);'''))

    op.execute(text('''CREATE TYPE public.flagseverity AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL'
);'''))

    op.execute(text('''CREATE TYPE public.flagstatus AS ENUM (
    'NEW',
    'ACKNOWLEDGED',
    'RESOLVED',
    'NEW_MANUAL_REVIEW',
    'MANUAL_REVIEW_CONFIRMED',
    'RESOLVED_FALSE_POSITIVE',
    'RESOLVED_ACTION_TAKEN_CRITICAL_FLAG',
    'AUTO_FLAGGED_MANUAL_REVIEW',
    'RESOLVED_NO_ACTION',
    'RESOLVED_WARNING_ISSUED'
);'''))

    op.execute(text('''CREATE TYPE public.transactionstatus AS ENUM (
    'pending',
    'completed',
    'failed',
    'reversed'
);'''))

    op.execute(text('''CREATE SEQUENCE public.system_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;'''))

    op.execute(text('''CREATE TABLE public.agent_teg_profiles (
    agent_id character varying(255) NOT NULL,
    token_balance numeric(36,18) DEFAULT '0'::numeric NOT NULL,
    reputation_score integer DEFAULT 0 NOT NULL,
    last_reputation_update timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    account_status character varying(50) DEFAULT 'active'::character varying NOT NULL,
    reputation_signal_count integer,
    positive_signals integer,
    negative_signals integer,
    transaction_count integer DEFAULT 0,
    locked_balance numeric(36,18) DEFAULT '0'::numeric NOT NULL,
    audited_balance numeric(30,18) DEFAULT '0'::numeric NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.auditor_flag_logs (
    flag_id character varying(36) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now(),
    flagged_agent_did character varying(255) NOT NULL,
    rule_violated_code character varying(100) NOT NULL,
    flag_reason character varying(1000) NOT NULL,
    severity character varying(50) DEFAULT 'medium'::character varying NOT NULL,
    related_avtp_transaction_id character varying(255),
    related_attestation_id character varying(36),
    status character varying(50) DEFAULT 'new_manual_review'::character varying NOT NULL,
    flagged_by character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    flag_type character varying(100),
    related_agent_id character varying(255),
    related_transaction_id character varying(36),
    details text
);'''))

    op.execute(text('''CREATE TABLE public.avtp_transaction_summary_logs (
    log_id character varying(36) NOT NULL,
    avtp_transaction_id character varying(255) NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now(),
    agent_did character varying(255) NOT NULL,
    initiating_agent_did character varying(255) NOT NULL,
    responding_agent_did character varying(255) NOT NULL,
    service_identifier character varying(255),
    price_avt numeric(36,18),
    transaction_value character varying(100),
    currency_type character varying(50),
    outcome_status character varying(50) NOT NULL,
    sla_identifier_referenced character varying(255),
    raw_log_pointer character varying(500),
    created_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.bootstrap_tokens (
    token_id character varying(36) NOT NULL,
    token_value character varying(255) NOT NULL,
    agent_type_hint character varying(255),
    requested_by character varying(255),
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone NOT NULL,
    is_used boolean NOT NULL,
    used_at timestamp with time zone,
    used_by_agent_did character varying(255)
);'''))

    op.execute(text('''CREATE TABLE public.cross_teg_transfers (
    transfer_id character varying(36) NOT NULL,
    correlation_id character varying(36) NOT NULL,
    source_teg_id character varying(255) NOT NULL,
    source_registry_id character varying(255) NOT NULL,
    source_agent_id character varying(255) NOT NULL,
    target_teg_id character varying(255) NOT NULL,
    target_registry_id character varying(255) NOT NULL,
    target_agent_id character varying(255) NOT NULL,
    amount numeric(36,18) NOT NULL,
    currency character varying(10) NOT NULL,
    status public.crosstegtransferstatus NOT NULL,
    role character varying(20) NOT NULL,
    phase character varying(20),
    lock_transaction_id character varying(36),
    debit_transaction_id character varying(36),
    credit_transaction_id character varying(36),
    compensation_transaction_id character varying(36),
    memo character varying(500),
    error_message character varying(1000),
    initiated_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.delegations (
    delegation_id character varying(36) NOT NULL,
    delegator_agent_id character varying(255) NOT NULL,
    validator_agent_id character varying(255) NOT NULL,
    stake_id character varying(36) NOT NULL,
    delegated_amount numeric(36,18) NOT NULL,
    delegation_start timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    delegation_end timestamp with time zone,
    is_active boolean NOT NULL,
    reward_share_percentage numeric(5,2) NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.reputation_signals (
    signal_id character varying(36) NOT NULL,
    transaction_id character varying(36) NOT NULL,
    sender_agent_id character varying(255) NOT NULL,
    receiver_agent_id character varying(255) NOT NULL,
    signal_value integer NOT NULL,
    reason character varying(200),
    "timestamp" timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.stakes (
    stake_id character varying(36) NOT NULL,
    agent_id character varying(255) NOT NULL,
    amount numeric(36,18) NOT NULL,
    staked_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    unstaked_at timestamp with time zone,
    is_active boolean NOT NULL,
    last_reward_claim timestamp with time zone,
    lock_period_days integer DEFAULT 0,
    unlock_date timestamp with time zone
);'''))

    op.execute(text('''CREATE TABLE public.staking_reward_distributions (
    distribution_id character varying(36) NOT NULL,
    stake_id character varying(36) NOT NULL,
    agent_id character varying(255) NOT NULL,
    amount numeric(36,18) NOT NULL,
    reward_type character varying(50) NOT NULL,
    transaction_id character varying(36),
    distributed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    reward_cycle_id character varying(36)
);'''))

    op.execute(text('''CREATE TABLE public.system_config (
    id integer NOT NULL,
    key character varying(100) NOT NULL,
    value text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.teg_apy_tiers (
    tier_id character varying(36) NOT NULL,
    tier_name character varying(50) NOT NULL,
    min_stake numeric(36,18) NOT NULL,
    max_stake numeric(36,18),
    base_apy numeric(5,2) NOT NULL,
    lock_period_days integer DEFAULT 0 NOT NULL,
    lock_bonus_apy numeric(5,2) DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    effective_from timestamp with time zone DEFAULT now() NOT NULL,
    effective_until timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.teg_attestation_logs (
    submission_id character varying(36) NOT NULL,
    agent_did character varying(255) NOT NULL,
    attestation_type character varying(100) NOT NULL,
    attestation_hash character varying(255) NOT NULL,
    storage_pointer character varying(500) NOT NULL,
    submitted_at timestamp with time zone DEFAULT now(),
    status character varying(50) DEFAULT 'logged'::character varying NOT NULL,
    reward_issued_tx_id character varying(36),
    circuit_id character varying(255),
    zkp_public_inputs_json character varying(2000),
    zkp_proof_value character varying(5000),
    policy_id character varying(36)
);'''))

    op.execute(text('''CREATE TABLE public.teg_dispute_logs (
    dispute_log_id character varying(36) NOT NULL,
    claimant_agent_did character varying(255) NOT NULL,
    defendant_agent_did character varying(255) NOT NULL,
    avtp_transaction_id character varying(255),
    reason_code character varying(100) NOT NULL,
    brief_description character varying(1000) NOT NULL,
    evidence_pointer character varying(500),
    resolution_notes character varying(2000),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    status public.dispute_status_enum DEFAULT 'OPEN'::public.dispute_status_enum NOT NULL,
    dispute_reason_category character varying(100),
    related_transaction_id character varying(36),
    evidence_description_or_url character varying(1000),
    admin_reviewer_id character varying(255),
    resolved_by character varying(255),
    resolved_at timestamp with time zone,
    resolution_details text
);'''))

    op.execute(text('''CREATE TABLE public.teg_governance_proposals (
    proposal_id character varying(36) NOT NULL,
    title character varying(255) NOT NULL,
    description text NOT NULL,
    proposal_type character varying(50) NOT NULL,
    proposer_id character varying(255),
    status character varying(50) DEFAULT 'active'::character varying NOT NULL,
    voting_starts_at timestamp with time zone NOT NULL,
    voting_ends_at timestamp with time zone NOT NULL,
    min_votes_required integer DEFAULT 1,
    quorum_percentage numeric(5,2) DEFAULT 10.0,
    yes_votes integer DEFAULT 0,
    no_votes integer DEFAULT 0,
    abstain_votes integer DEFAULT 0,
    total_vote_weight numeric(36,18) DEFAULT 0,
    execution_data jsonb,
    result character varying(50),
    executed boolean DEFAULT false,
    executed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.teg_governance_votes (
    vote_id character varying(36) NOT NULL,
    proposal_id character varying(36),
    agent_id character varying(255),
    vote_option character varying(50) NOT NULL,
    vote_weight numeric(36,18) DEFAULT 1 NOT NULL,
    comment text,
    voted_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.teg_idempotency_records (
    idempotency_key character varying(255) NOT NULL,
    operation_type character varying(50) NOT NULL,
    request_hash character varying(64) NOT NULL,
    response_data text,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    completed_at timestamp without time zone,
    expires_at timestamp without time zone NOT NULL
);'''))

    op.execute(text('''CREATE TABLE public.teg_policies (
    policy_id character varying(36) NOT NULL,
    policy_name character varying(255) NOT NULL,
    policy_version character varying(50) NOT NULL,
    description text,
    rules_document_url character varying(500),
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    policy_code character varying(255) NOT NULL,
    policy_type character varying(100) NOT NULL,
    parameters text,
    circuit_identifier character varying(255),
    enforcement_level character varying(50),
    reward_amount numeric(36,18)
);'''))

    op.execute(text('''CREATE TABLE public.teg_reward_configs (
    reward_id character varying(36) NOT NULL,
    reward_type character varying(100) NOT NULL,
    reward_code character varying(255) NOT NULL,
    description text,
    amount numeric(36,18) NOT NULL,
    policy_code character varying(255),
    conditions text,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.teg_reward_cycles (
    cycle_id character varying(36) NOT NULL,
    cycle_start timestamp with time zone NOT NULL,
    cycle_end timestamp with time zone NOT NULL,
    total_rewards_distributed numeric(36,18) DEFAULT 0 NOT NULL,
    total_stakers integer DEFAULT 0 NOT NULL,
    status character varying(50) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);'''))

    op.execute(text('''CREATE TABLE public.teg_reward_distributions (
    distribution_id character varying(36) NOT NULL,
    agent_id character varying(255) NOT NULL,
    reward_type character varying(100) NOT NULL,
    amount numeric(36,18) NOT NULL,
    policy_code character varying(255),
    transaction_id character varying(36),
    "timestamp" timestamp with time zone DEFAULT now()
);'''))

    op.execute(text('''CREATE TABLE public.teg_transactions (
    transaction_id character varying(36) NOT NULL,
    sender_agent_id character varying(255),
    receiver_agent_id character varying(255) NOT NULL,
    amount numeric(36,18) NOT NULL,
    fee_amount numeric(36,18) DEFAULT '0'::numeric,
    status public.transactionstatus DEFAULT 'pending'::public.transactionstatus NOT NULL,
    transaction_type character varying(50) DEFAULT 'transfer'::character varying NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now(),
    error_message character varying(500),
    reputation_signal_applied boolean,
    attached_message character varying(256)
);'''))

    op.execute(text('''ALTER SEQUENCE public.system_config_id_seq OWNED BY public.system_config.id;'''))

    op.execute(text('''ALTER TABLE ONLY public.system_config ALTER COLUMN id SET DEFAULT nextval('public.system_config_id_seq'::regclass);'''))

    op.execute(text('''ALTER TABLE ONLY public.agent_teg_profiles
    ADD CONSTRAINT agent_teg_profiles_pkey PRIMARY KEY (agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.auditor_flag_logs
    ADD CONSTRAINT auditor_flag_logs_pkey PRIMARY KEY (flag_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.avtp_transaction_summary_logs
    ADD CONSTRAINT avtp_transaction_summary_logs_pkey PRIMARY KEY (log_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.bootstrap_tokens
    ADD CONSTRAINT bootstrap_tokens_pkey PRIMARY KEY (token_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.cross_teg_transfers
    ADD CONSTRAINT cross_teg_transfers_pkey PRIMARY KEY (transfer_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.delegations
    ADD CONSTRAINT delegations_pkey PRIMARY KEY (delegation_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.reputation_signals
    ADD CONSTRAINT reputation_signals_pkey PRIMARY KEY (signal_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.stakes
    ADD CONSTRAINT stakes_pkey PRIMARY KEY (stake_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_reward_distributions
    ADD CONSTRAINT staking_reward_distributions_pkey PRIMARY KEY (distribution_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_pkey PRIMARY KEY (id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_apy_tiers
    ADD CONSTRAINT teg_apy_tiers_pkey PRIMARY KEY (tier_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_attestation_logs
    ADD CONSTRAINT teg_attestation_logs_pkey PRIMARY KEY (submission_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_dispute_logs
    ADD CONSTRAINT teg_dispute_logs_pkey PRIMARY KEY (dispute_log_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_governance_proposals
    ADD CONSTRAINT teg_governance_proposals_pkey PRIMARY KEY (proposal_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_governance_votes
    ADD CONSTRAINT teg_governance_votes_pkey PRIMARY KEY (vote_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_idempotency_records
    ADD CONSTRAINT teg_idempotency_records_pkey PRIMARY KEY (idempotency_key);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_policies
    ADD CONSTRAINT teg_policies_pkey PRIMARY KEY (policy_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_reward_configs
    ADD CONSTRAINT teg_reward_configs_pkey PRIMARY KEY (reward_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_reward_cycles
    ADD CONSTRAINT teg_reward_cycles_pkey PRIMARY KEY (cycle_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_reward_distributions
    ADD CONSTRAINT teg_reward_distributions_pkey PRIMARY KEY (distribution_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_transactions
    ADD CONSTRAINT teg_transactions_pkey PRIMARY KEY (transaction_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.avtp_transaction_summary_logs
    ADD CONSTRAINT avtp_transaction_summary_logs_avtp_transaction_id_key UNIQUE (avtp_transaction_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_key_key UNIQUE (key);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_apy_tiers
    ADD CONSTRAINT teg_apy_tiers_tier_name_key UNIQUE (tier_name);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_governance_votes
    ADD CONSTRAINT teg_governance_votes_proposal_id_agent_id_key UNIQUE (proposal_id, agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_reward_configs
    ADD CONSTRAINT teg_reward_configs_reward_code_key UNIQUE (reward_code);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_attestation_logs
    ADD CONSTRAINT uq_agent_attestation UNIQUE (agent_did, attestation_type, attestation_hash);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_policies
    ADD CONSTRAINT uq_policy_code UNIQUE (policy_code);'''))

    op.execute(text('''ALTER TABLE ONLY public.reputation_signals
    ADD CONSTRAINT uq_reputation_signal_transaction_sender UNIQUE (transaction_id, sender_agent_id);'''))

    op.execute(text('''CREATE INDEX idx_agent_account_status ON public.agent_teg_profiles USING btree (account_status);'''))

    op.execute(text('''CREATE INDEX idx_agent_balance ON public.agent_teg_profiles USING btree (agent_id, token_balance);'''))

    op.execute(text('''CREATE INDEX idx_agent_locked_balance ON public.agent_teg_profiles USING btree (agent_id, locked_balance);'''))

    op.execute(text('''CREATE INDEX idx_attestation_agent ON public.teg_attestation_logs USING btree (agent_did, submitted_at);'''))

    op.execute(text('''CREATE INDEX idx_attestation_policy ON public.teg_attestation_logs USING btree (policy_id);'''))

    op.execute(text('''CREATE INDEX idx_avtp_agents_outcome ON public.avtp_transaction_summary_logs USING btree (initiating_agent_did, responding_agent_did, outcome_status);'''))

    op.execute(text('''CREATE INDEX idx_avtp_initiating_agent ON public.avtp_transaction_summary_logs USING btree (initiating_agent_did, "timestamp");'''))

    op.execute(text('''CREATE INDEX idx_avtp_outcome ON public.avtp_transaction_summary_logs USING btree (outcome_status, "timestamp");'''))

    op.execute(text('''CREATE INDEX idx_avtp_responding_agent ON public.avtp_transaction_summary_logs USING btree (responding_agent_did, "timestamp");'''))

    op.execute(text('''CREATE INDEX idx_bootstrap_token_status ON public.bootstrap_tokens USING btree (is_used, expires_at);'''))

    op.execute(text('''CREATE INDEX idx_cross_teg_correlation ON public.cross_teg_transfers USING btree (correlation_id);'''))

    op.execute(text('''CREATE INDEX idx_cross_teg_source ON public.cross_teg_transfers USING btree (source_agent_id, initiated_at);'''))

    op.execute(text('''CREATE INDEX idx_cross_teg_status ON public.cross_teg_transfers USING btree (status, initiated_at);'''))

    op.execute(text('''CREATE INDEX idx_cross_teg_target ON public.cross_teg_transfers USING btree (target_agent_id, initiated_at);'''))

    op.execute(text('''CREATE INDEX idx_delegation_delegator_active ON public.delegations USING btree (delegator_agent_id, is_active);'''))

    op.execute(text('''CREATE INDEX idx_delegation_validator_active ON public.delegations USING btree (validator_agent_id, is_active);'''))

    op.execute(text('''CREATE INDEX idx_dispute_category ON public.teg_dispute_logs USING btree (dispute_reason_category);'''))

    op.execute(text('''CREATE INDEX idx_dispute_claimant ON public.teg_dispute_logs USING btree (claimant_agent_did, created_at);'''))

    op.execute(text('''CREATE INDEX idx_dispute_defendant ON public.teg_dispute_logs USING btree (defendant_agent_did, created_at);'''))

    op.execute(text('''CREATE INDEX idx_dispute_transaction ON public.teg_dispute_logs USING btree (related_transaction_id);'''))

    op.execute(text('''CREATE INDEX idx_flag_agent_status ON public.auditor_flag_logs USING btree (flagged_agent_did, status);'''))

    op.execute(text('''CREATE INDEX idx_flag_timestamp ON public.auditor_flag_logs USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX idx_flags_agent ON public.auditor_flag_logs USING btree (related_agent_id);'''))

    op.execute(text('''CREATE INDEX idx_flags_type_severity ON public.auditor_flag_logs USING btree (flag_type, severity);'''))

    op.execute(text('''CREATE INDEX idx_governance_proposals_dates ON public.teg_governance_proposals USING btree (voting_starts_at, voting_ends_at);'''))

    op.execute(text('''CREATE INDEX idx_governance_proposals_proposer ON public.teg_governance_proposals USING btree (proposer_id);'''))

    op.execute(text('''CREATE INDEX idx_governance_proposals_status ON public.teg_governance_proposals USING btree (status);'''))

    op.execute(text('''CREATE INDEX idx_governance_votes_proposal_option ON public.teg_governance_votes USING btree (proposal_id, vote_option);'''))

    op.execute(text('''CREATE INDEX idx_idempotency_expires_at ON public.teg_idempotency_records USING btree (expires_at);'''))

    op.execute(text('''CREATE INDEX idx_idempotency_status ON public.teg_idempotency_records USING btree (status);'''))

    op.execute(text('''CREATE INDEX idx_receiver_timestamp ON public.teg_transactions USING btree (receiver_agent_id, "timestamp");'''))

    op.execute(text('''CREATE MATERIALIZED VIEW public.reputation_rankings AS
 SELECT agent_teg_profiles.agent_id,
    agent_teg_profiles.reputation_score,
        CASE
            WHEN (agent_teg_profiles.reputation_score >= 1000) THEN 'legendary'::text
            WHEN (agent_teg_profiles.reputation_score >= 500) THEN 'expert'::text
            WHEN (agent_teg_profiles.reputation_score >= 100) THEN 'trusted'::text
            WHEN (agent_teg_profiles.reputation_score >= 0) THEN 'standard'::text
            ELSE 'restricted'::text
        END AS reputation_tier,
    COALESCE(agent_teg_profiles.transaction_count, 0) AS transaction_count,
    row_number() OVER (ORDER BY agent_teg_profiles.reputation_score DESC) AS rank
   FROM public.agent_teg_profiles
  WHERE (agent_teg_profiles.reputation_score IS NOT NULL)
  ORDER BY agent_teg_profiles.reputation_score DESC
  WITH NO DATA;'''))

    op.execute(text('''CREATE INDEX idx_reputation_rankings_score ON public.reputation_rankings USING btree (reputation_score DESC);'''))

    op.execute(text('''REFRESH MATERIALIZED VIEW public.reputation_rankings;'''))

    op.execute(text('''CREATE INDEX idx_reputation_signal_receiver ON public.reputation_signals USING btree (receiver_agent_id);'''))

    op.execute(text('''CREATE INDEX idx_reputation_signal_sender ON public.reputation_signals USING btree (sender_agent_id);'''))

    op.execute(text('''CREATE INDEX idx_reputation_signal_status ON public.teg_transactions USING btree (reputation_signal_applied, transaction_type, status);'''))

    op.execute(text('''CREATE INDEX idx_reputation_signal_timestamp ON public.reputation_signals USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX idx_reputation_signal_transaction ON public.reputation_signals USING btree (transaction_id);'''))

    op.execute(text('''CREATE INDEX idx_reward_agent_timestamp ON public.teg_reward_distributions USING btree (agent_id, "timestamp");'''))

    op.execute(text('''CREATE INDEX idx_reward_cycles_dates ON public.teg_reward_cycles USING btree (cycle_start, cycle_end);'''))

    op.execute(text('''CREATE INDEX idx_reward_cycles_status ON public.teg_reward_cycles USING btree (status);'''))

    op.execute(text('''CREATE INDEX idx_sender_timestamp ON public.teg_transactions USING btree (sender_agent_id, "timestamp");'''))

    op.execute(text('''CREATE INDEX idx_stake_active_amount ON public.stakes USING btree (is_active, amount);'''))

    op.execute(text('''CREATE INDEX idx_stake_agent_active ON public.stakes USING btree (agent_id, is_active);'''))

    op.execute(text('''CREATE INDEX idx_staking_reward_agent_time ON public.staking_reward_distributions USING btree (agent_id, distributed_at);'''))

    op.execute(text('''CREATE INDEX idx_staking_reward_cycle ON public.staking_reward_distributions USING btree (reward_cycle_id);'''))

    op.execute(text('''CREATE INDEX idx_status_timestamp ON public.teg_transactions USING btree (status, "timestamp");'''))

    op.execute(text('''CREATE INDEX ix_agent_teg_profiles_agent_id ON public.agent_teg_profiles USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_auditor_flag_logs_flag_id ON public.auditor_flag_logs USING btree (flag_id);'''))

    op.execute(text('''CREATE INDEX ix_auditor_flag_logs_flagged_agent_did ON public.auditor_flag_logs USING btree (flagged_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_auditor_flag_logs_status ON public.auditor_flag_logs USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_avtp_transaction_summary_logs_agent_did ON public.avtp_transaction_summary_logs USING btree (agent_did);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_avtp_transaction_summary_logs_avtp_transaction_id ON public.avtp_transaction_summary_logs USING btree (avtp_transaction_id);'''))

    op.execute(text('''CREATE INDEX ix_avtp_transaction_summary_logs_initiating_agent_did ON public.avtp_transaction_summary_logs USING btree (initiating_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_avtp_transaction_summary_logs_log_id ON public.avtp_transaction_summary_logs USING btree (log_id);'''))

    op.execute(text('''CREATE INDEX ix_avtp_transaction_summary_logs_outcome_status ON public.avtp_transaction_summary_logs USING btree (outcome_status);'''))

    op.execute(text('''CREATE INDEX ix_avtp_transaction_summary_logs_responding_agent_did ON public.avtp_transaction_summary_logs USING btree (responding_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_avtp_transaction_summary_logs_timestamp ON public.avtp_transaction_summary_logs USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX ix_bootstrap_tokens_expires_at ON public.bootstrap_tokens USING btree (expires_at);'''))

    op.execute(text('''CREATE INDEX ix_bootstrap_tokens_token_id ON public.bootstrap_tokens USING btree (token_id);'''))

    op.execute(text('''CREATE UNIQUE INDEX ix_bootstrap_tokens_token_value ON public.bootstrap_tokens USING btree (token_value);'''))

    op.execute(text('''CREATE INDEX ix_bootstrap_tokens_used_by_agent_did ON public.bootstrap_tokens USING btree (used_by_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_cross_teg_transfers_correlation_id ON public.cross_teg_transfers USING btree (correlation_id);'''))

    op.execute(text('''CREATE INDEX ix_cross_teg_transfers_source_agent_id ON public.cross_teg_transfers USING btree (source_agent_id);'''))

    op.execute(text('''CREATE INDEX ix_cross_teg_transfers_status ON public.cross_teg_transfers USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_cross_teg_transfers_target_agent_id ON public.cross_teg_transfers USING btree (target_agent_id);'''))

    op.execute(text('''CREATE INDEX ix_cross_teg_transfers_transfer_id ON public.cross_teg_transfers USING btree (transfer_id);'''))

    op.execute(text('''CREATE INDEX ix_delegations_delegation_id ON public.delegations USING btree (delegation_id);'''))

    op.execute(text('''CREATE INDEX ix_delegations_delegator_agent_id ON public.delegations USING btree (delegator_agent_id);'''))

    op.execute(text('''CREATE INDEX ix_delegations_is_active ON public.delegations USING btree (is_active);'''))

    op.execute(text('''CREATE INDEX ix_delegations_stake_id ON public.delegations USING btree (stake_id);'''))

    op.execute(text('''CREATE INDEX ix_delegations_validator_agent_id ON public.delegations USING btree (validator_agent_id);'''))

    op.execute(text('''CREATE INDEX ix_stakes_stake_id ON public.stakes USING btree (stake_id);'''))

    op.execute(text('''CREATE INDEX ix_staking_reward_distributions_agent_id ON public.staking_reward_distributions USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_staking_reward_distributions_distribution_id ON public.staking_reward_distributions USING btree (distribution_id);'''))

    op.execute(text('''CREATE INDEX ix_staking_reward_distributions_stake_id ON public.staking_reward_distributions USING btree (stake_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_attestation_logs_agent_did ON public.teg_attestation_logs USING btree (agent_did);'''))

    op.execute(text('''CREATE INDEX ix_teg_attestation_logs_submission_id ON public.teg_attestation_logs USING btree (submission_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_dispute_logs_claimant_agent_did ON public.teg_dispute_logs USING btree (claimant_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_teg_dispute_logs_defendant_agent_did ON public.teg_dispute_logs USING btree (defendant_agent_did);'''))

    op.execute(text('''CREATE INDEX ix_teg_dispute_logs_dispute_log_id ON public.teg_dispute_logs USING btree (dispute_log_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_reward_configs_reward_id ON public.teg_reward_configs USING btree (reward_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_reward_distributions_agent_id ON public.teg_reward_distributions USING btree (agent_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_reward_distributions_distribution_id ON public.teg_reward_distributions USING btree (distribution_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_reward_distributions_timestamp ON public.teg_reward_distributions USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX ix_teg_transactions_receiver_agent_id ON public.teg_transactions USING btree (receiver_agent_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_transactions_sender_agent_id ON public.teg_transactions USING btree (sender_agent_id);'''))

    op.execute(text('''CREATE INDEX ix_teg_transactions_status ON public.teg_transactions USING btree (status);'''))

    op.execute(text('''CREATE INDEX ix_teg_transactions_timestamp ON public.teg_transactions USING btree ("timestamp");'''))

    op.execute(text('''CREATE INDEX ix_teg_transactions_transaction_id ON public.teg_transactions USING btree (transaction_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.delegations
    ADD CONSTRAINT delegations_delegator_agent_id_fkey FOREIGN KEY (delegator_agent_id) REFERENCES public.agent_teg_profiles(agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.delegations
    ADD CONSTRAINT delegations_stake_id_fkey FOREIGN KEY (stake_id) REFERENCES public.stakes(stake_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.delegations
    ADD CONSTRAINT delegations_validator_agent_id_fkey FOREIGN KEY (validator_agent_id) REFERENCES public.agent_teg_profiles(agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_attestation_logs
    ADD CONSTRAINT fk_attestation_policy FOREIGN KEY (policy_id) REFERENCES public.teg_policies(policy_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.stakes
    ADD CONSTRAINT stakes_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent_teg_profiles(agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_reward_distributions
    ADD CONSTRAINT staking_reward_distributions_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent_teg_profiles(agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.staking_reward_distributions
    ADD CONSTRAINT staking_reward_distributions_stake_id_fkey FOREIGN KEY (stake_id) REFERENCES public.stakes(stake_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_governance_proposals
    ADD CONSTRAINT teg_governance_proposals_proposer_id_fkey FOREIGN KEY (proposer_id) REFERENCES public.agent_teg_profiles(agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_governance_votes
    ADD CONSTRAINT teg_governance_votes_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agent_teg_profiles(agent_id);'''))

    op.execute(text('''ALTER TABLE ONLY public.teg_governance_votes
    ADD CONSTRAINT teg_governance_votes_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES public.teg_governance_proposals(proposal_id);'''))



def downgrade() -> None:
    pass
