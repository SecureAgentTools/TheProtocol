"""§pass52 Phase C — backfill event_emission_policies for the 39+ rogue event types.

Revision ID: 0077_em_backfill_policies
Revises: 0076_bdl_seed_templates
Create Date: 2026-05-20

Context:
    EventStore-A has 89 distinct event_types in the events table. Before §pass51
    the policy table held 87 rows; after §pass51 it holds 102 (the bundles team
    added 15 BundleXxx rows). But the 89 ES-distinct types and the 102 policy
    rows OVERLAP imperfectly — sandbox-A is missing 47, prod-A is missing 39
    (auditor.theprotocol.cloud breach history shows 6 incidents in 2026-04-10/11
    correlated with this exact class of gap).

    Source-of-truth analysis is in `sessionlogs2026/AUDIT_2026-05-20_EVENT_EMISSION_
    POLICY_CODIFICATION.md` and the AAA design doc at
    `sessionlogs2026/DESIGN_2026-05-20_EVENT_EMISSION_POLICY_CONSOLIDATION_AAA.md`.

    This migration adds policy rows for every rogue event type, with conservative
    defaults: emit_from_teg=false (Registry is canonical), emit_from_registry=true,
    skip_in_projection=true for AUDIT-ONLY events; false for BALANCE-MOVING events.

    Idempotent: ON CONFLICT (event_type) DO NOTHING. Safe to re-run.

Decision matrix (see design doc §4.2):
    BALANCE-MOVING (skip_in_projection=false, never skip):
        TokensIssued, TokensTransferred, TokensStaked, TokensUnstaked,
        BalanceCorrected, DisputeSlash, DisputeCompensationMinted,
        TransactionFeeCollected, RewardsAutoCompounded, ProjectionSnapshot
    AUDIT-ONLY (skip_in_projection=true, balance already counted elsewhere):
        CrossRegistryTransferCompleted, RewardsDistributed, A2APayment*,
        FundingRequest*, Bundle*, lifecycle events
    GOVERNANCE / LIFECYCLE (skip_in_projection=true, no balance impact):
        ProposalCreated, VoteCast, ProposalAutoTallied, Dispute*, Contract*,
        Hagrid*, WitnessIssued, AgentCreated, AgentOnboarded, AgentMtls*

Downgrade: removes only the rows this migration inserted (preserves rows that
existed before this migration ran).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0077_em_backfill_policies"
down_revision: Union[str, None] = "0076_bdl_seed_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description)
POLICY_BACKFILL = [
    # ── BALANCE-MOVING (skip_in_projection=false) ──────────────────────────
    ("TokensIssued",                  False, True, False,
     "Mint operation; creates supply. Counts toward tokens_issued."),
    ("TokensTransferred",             False, True, False,
     "Agent-to-agent transfer. Zero-sum but balance projection consumes it."),
    ("TokensStaked",                  False, True, False,
     "Rebases liquid → staked."),
    ("TokensUnstaked",                False, True, False,
     "Rebases staked → liquid."),
    ("BalanceCorrected",              False, True, False,
     "Admin balance correction. Counts toward tokens_issued (positive) or "
     "tokens_destroyed (negative)."),
    ("DisputeCompensationMinted",     False, True, False,
     "Dispute payout from treasury. Counts toward tokens_issued."),
    ("TransactionFeeCollected",       False, True, False,
     "Fee credited to fee_collector. Zero-sum but projection consumes it."),
    ("RewardsAutoCompounded",         False, True, False,
     "Staking reward rebased into staked balance."),
    ("ProjectionSnapshot",            False, True, False,
     "Supply audit baseline event. CRITICAL — used as tokens_issued baseline "
     "in EventStore projection."),

    # ── SELF-DESCRIBING AUDIT (skip_in_projection=true; meta-event) ──────────
    ("EventEmissionPolicyUpdated",    False, True, True,
     "Audit-trail event when admin changes a row in event_emission_policies. "
     "Discovered during §pass52 Phase J live validation — was emitted by "
     "admin_health.py:update_event_emission_policy but had no policy row. "
     "Phase J's fail-closed mode caught it; this row fixes it. "
     "Note: emit_from_registry=true so the admin endpoint's audit trail survives "
     "the fail-closed flip."),

    # ── AUDIT-ONLY (skip_in_projection=true; balance already counted) ──────
    ("CrossRegistryTransferCompleted", False, True, True,
     "Audit-trail event for cross-registry transfers. Underlying "
     "TokensTransferred already counted; this is for forensics."),
    ("RewardsDistributed",            False, True, True,
     "Audit-trail event for reward distribution. Underlying TokensTransferred "
     "from staking_distributor already counted."),
    ("A2APaymentAuthorized",          False, True, True,
     "A2A payment authorization event (token reserved, not transferred yet). "
     "Underlying token motion via TokensTransferred at settle time."),
    ("FundingRequestApproved",        False, True, True,
     "Funding request approval audit-trail. Treasury motion via "
     "TokensTransferred separately."),
    ("FundingRequestCreated",         False, True, True,
     "Funding request lifecycle event."),
    ("CrossTEGTreasuryFunded",        False, True, True,
     "Cross-frame treasury funding audit-trail. Balance motion via "
     "TokensTransferred separately."),
    ("DailyDistributionCompleted",    False, True, True,
     "Distribution worker completion event. Individual transfers already "
     "counted via TokensTransferred."),
    ("TreasurySlashReceived",         False, True, True,
     "Treasury receive-side of slash. Balance motion via TokensTransferred."),
    ("AdminBulkRefreshCards",         False, True, True,
     "Admin bulk operation lifecycle event."),
    ("WebhookRetryExhausted",         False, True, True,
     "Webhook delivery exhaustion audit-trail."),
    ("TokensBridgeLocked",            False, True, True,
     "Bridge lock audit-trail. Balance motion via TokensTransferred."),
    ("SupplyInvariantBreach",         False, True, True,
     "Critical audit alert. Emitted by supply_auditor worker on detected "
     "invariant violation."),

    # ── LIFECYCLE (skip_in_projection=true; no balance impact) ─────────────
    ("AgentCreated",                  False, True, True,
     "Agent creation lifecycle. No balance impact."),
    ("AgentOnboarded",                False, True, True,
     "Agent onboarding completed via /onboard/create_agent."),
    ("AgentCredentialReset",          False, True, True,
     "Agent credential rotation."),
    ("AgentMtlsEnrolled",             False, True, True,
     "IRONHAND mTLS enrollment (f052)."),
    ("AgentMtlsRevoked",              False, True, True,
     "IRONHAND mTLS revocation."),
    ("EnforcementActionCreated",      False, True, True,
     "Enforcement action lifecycle."),
    ("ReputationChanged",             False, True, True,
     "EigenTrust reputation update. No balance impact."),
    ("ReputationBondDeposited",       False, True, True,
     "Reputation bond audit. Balance motion via TokensTransferred separately."),

    # ── GOVERNANCE (skip_in_projection=true) ────────────────────────────────
    ("ProposalCreated",               False, True, True,
     "Governance proposal lifecycle."),
    ("VoteCast",                      False, True, True,
     "Governance vote lifecycle."),
    ("ProposalAutoTallied",           False, True, True,
     "Auto-tally worker completion."),
    ("DisputeFiled",                  False, True, True,
     "Dispute lifecycle. Balance motion via DisputeSlash + DisputeCompensation."),
    ("DisputeResolved",               False, True, True,
     "Dispute lifecycle."),
    ("DisputeCompensationRequest",    False, True, True,
     "Dispute compensation lifecycle."),
    ("EvidenceSubmitted",             False, True, True,
     "Dispute evidence lifecycle."),

    # ── CONTRACTS (skip_in_projection=true) ────────────────────────────────
    ("ContractCreated",               False, True, True,
     "Contract subsystem lifecycle."),
    ("ContractAccepted",              False, True, True,
     "Contract subsystem lifecycle."),
    ("ContractWorkSubmitted",         False, True, True,
     "Contract subsystem lifecycle."),
    ("ContractCompleted",             False, True, True,
     "Contract subsystem lifecycle."),
    ("ContractFailed",                False, True, True,
     "Contract subsystem lifecycle."),

    # ── ASTRAEUS / SOVEREIGN (skip_in_projection=true) ─────────────────────
    ("HagridGiniSnapshot",            False, True, True,
     "Hagrid Astraeus wealth metric (Path C agent direct-POST)."),
    ("HagridSybilRing",               False, True, True,
     "Hagrid Astraeus sybil-ring alert (Path C)."),
    ("HagridCemeteryCensus",          False, True, True,
     "Hagrid Astraeus lifecycle census (Path C)."),
    ("HagridLifecycle",               False, True, True,
     "Hagrid Astraeus lifecycle event (Path C)."),
    ("HagridManifesto",               False, True, True,
     "Hagrid Astraeus profile (Path C)."),
    ("WitnessIssued",                 False, True, True,
     "VERIDIAN agent witness event (Path C agent direct-POST)."),

    # ── TEST / HISTORICAL (skip_in_projection=true) ────────────────────────
    ("TestEvent",                     False, True, True,
     "Historical test fixture. Kept for ledger immutability; skipped from "
     "projection. Flag candidate for future cleanup."),
]


def upgrade() -> None:
    """Insert ~47 policy rows. ON CONFLICT DO NOTHING — preserves existing rows.

    Note: schema has `updated_at` (default NOW()) but no `created_at`. Description
    column is varchar(500) — auto-truncated by Postgres if longer (kept short here).
    """
    for event_type, teg, reg, skip, desc in POLICY_BACKFILL:
        # Truncate desc to 500 chars to fit the column
        desc_trunc = desc[:500] if desc else None
        op.execute(
            text(
                """
                INSERT INTO event_emission_policies
                    (event_type, emit_from_teg, emit_from_registry, skip_in_projection,
                     description, updated_at)
                VALUES
                    (:event_type, :teg, :reg, :skip, :desc, NOW())
                ON CONFLICT (event_type) DO NOTHING
                """
            ).bindparams(
                event_type=event_type, teg=teg, reg=reg, skip=skip, desc=desc_trunc,
            )
        )


def downgrade() -> None:
    """Remove ONLY the rows this migration inserted.

    Safety note: this migration is idempotent on upgrade (ON CONFLICT DO NOTHING),
    so a downgrade can't determine which rows it actually inserted vs which
    pre-existed. To be safe, we delete only rows with the description text we
    set above — which is unique to this migration.
    """
    for event_type, _teg, _reg, _skip, desc in POLICY_BACKFILL:
        op.execute(
            text(
                """
                DELETE FROM event_emission_policies
                WHERE event_type = :event_type AND description = :desc
                """
            ).bindparams(event_type=event_type, desc=desc)
        )
