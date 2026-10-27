"""§pass58 Phase C completion — backfill remaining 27 rogue event types.

Revision ID: 0078_pass58_policy_completion
Revises: 0077_em_backfill_policies
Create Date: 2026-05-20

Context:
    Migration 0077 (§pass52 Phase C) backfilled 49 of the 89 known live event
    types into `event_emission_policies`. Sandbox-A audit on 2026-05-20 found
    27 additional types in `events` table that still lack a policy row:

        27 = (89 ES-A distinct types) - (62 already covered by pre-existing
              rows + 0077's 49 inserts, accounting for overlap)

    This migration closes the residual gap so the `_is_known_event_type()`
    helper in `agentvault-event-store/src/services/projections.py` returns
    True for every live event type. Required precursor to PR-11b (declare
    `Event.event_type: Literal[<closed set>]` enum at EventStore-receive).

    Conservative defaults match 0077:
        emit_from_teg=false   — Registry is the canonical emitter
        emit_from_registry=true — fail-open at registry layer (current contract)
        skip_in_projection — false for balance-moving, true for audit/lifecycle

Decision matrix (matches DESIGN_2026-05-20 §4.2):
    BALANCE-MOVING (skip_in_projection=false):
        DisputeSlash         — destroys staked balance; affects total_supply
        StakeForceUnstaked   — rebase liquid → staked or vice versa
    AUDIT-ONLY (skip_in_projection=true, underlying balance already counted):
        BridgeTransferExpired, FiatRoutedSettlement*, SettlementTimeout
    LIFECYCLE (skip_in_projection=true, no balance impact):
        AccountDeletionRequested, AgentExported, AgentHeartbeat,
        AgentReinstated, AgentStatusChanged, Attestation*, EigenTrustSignal,
        FundingRequestRejected, PeerSlashConfigUpdated, ProposalTallied,
        Registry{Blacklisted,Federated,Quarantined,QuarantineLifted}
    TEST CRUFT (skip_in_projection=true):
        AAATestSmoke, BogusType_pass53_test, TestEventAAATest1

Idempotent: ON CONFLICT (event_type) DO NOTHING. Safe to re-run.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0078_pass58_policy_complete"
down_revision: Union[str, None] = "0077_em_backfill_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description)
POLICY_BACKFILL = [
    # ── BALANCE-MOVING (skip_in_projection=false) ──────────────────────────
    ("DisputeSlash", False, True, False,
     "Slash on losing party in dispute. Destroys balance; affects total_circulating."),
    ("StakeForceUnstaked", False, True, False,
     "Admin/system force-unstake. Rebases liquid ↔ staked."),

    # ── AUDIT-ONLY (skip_in_projection=true, balance counted elsewhere) ────
    ("BridgeTransferExpired", False, True, True,
     "Cross-frame bridge transfer expired. Refund TokensTransferred already counts."),
    ("FiatRoutedSettlementInitiated", False, True, True,
     "Fiat routed settlement audit start. Underlying transfer counts."),
    ("FiatRoutedSettlementCompleted", False, True, True,
     "Fiat routed settlement audit complete. Underlying transfer counts."),
    ("SettlementTimeout", False, True, True,
     "Saga timeout marker. Underlying refund event counts."),

    # ── LIFECYCLE (skip_in_projection=true, no balance impact) ─────────────
    ("AccountDeletionRequested", False, True, True,
     "Developer/agent account deletion request lifecycle."),
    ("AgentExported", False, True, True,
     "Agent exported to bundle/file. Lifecycle event."),
    ("AgentHeartbeat", False, True, True,
     "Operational heartbeat ping. Lifecycle/health event."),
    ("AgentReinstated", False, True, True,
     "Agent reinstated from suspension. Lifecycle."),
    ("AgentStatusChanged", False, True, True,
     "Agent status field change. Lifecycle."),
    ("AttestationDueReminder", False, True, True,
     "ZKP attestation due-soon reminder. Lifecycle."),
    ("AttestationExpired", False, True, True,
     "ZKP attestation expired. Lifecycle."),
    ("AttestationReputationClawed", False, True, True,
     "Reputation claw-back after expired attestation. Reputation change, not balance."),
    ("AttestationRevoked", False, True, True,
     "ZKP attestation revoked. Lifecycle."),
    ("AttestationSubmitted", False, True, True,
     "ZKP attestation submitted. Lifecycle."),
    ("EigenTrustSignal", False, True, True,
     "EigenTrust++ reputation signal. Not balance-affecting."),
    ("FundingRequestRejected", False, True, True,
     "Funding request denied. Lifecycle, no balance motion."),
    ("PeerSlashConfigUpdated", False, True, True,
     "Federation peer slash config change. Admin/config."),
    ("ProposalTallied", False, True, True,
     "Governance proposal tally complete. Lifecycle."),
    ("RegistryBlacklisted", False, True, True,
     "Federation peer blacklisted. Lifecycle."),
    ("RegistryFederated", False, True, True,
     "Federation peer added. Lifecycle."),
    ("RegistryQuarantined", False, True, True,
     "Federation peer quarantined (license invalid). Lifecycle."),
    ("RegistryQuarantineLifted", False, True, True,
     "Federation peer quarantine lifted. Lifecycle."),

    # ── TEST CRUFT (skip_in_projection=true) ───────────────────────────────
    # These exist only because §pass53 testing left them; documenting so the
    # closed-set Literal[] still accepts them.
    ("AAATestSmoke", False, True, True,
     "Test smoke event. Test cruft, harmless."),
    ("BogusType_pass53_test", False, True, True,
     "§pass53 strict-mode test event. Test cruft."),
    ("TestEventAAATest1", False, True, True,
     "AAA test stress event. Test cruft."),
]


def upgrade() -> None:
    """Insert all 27 rows. ON CONFLICT (event_type) DO NOTHING — idempotent."""
    for et, teg, reg, skip, desc in POLICY_BACKFILL:
        op.execute(
            text("""
                INSERT INTO event_emission_policies
                    (event_type, emit_from_teg, emit_from_registry,
                     skip_in_projection, description, updated_at)
                VALUES (:et, :teg, :reg, :skip, :desc, NOW())
                ON CONFLICT (event_type) DO NOTHING
            """).bindparams(et=et, teg=teg, reg=reg, skip=skip, desc=desc)
        )


def downgrade() -> None:
    """Remove only the rows this migration inserted (the 27 in POLICY_BACKFILL).

    Preserves any pre-existing rows added through admin UI or earlier migrations.
    """
    event_types = [row[0] for row in POLICY_BACKFILL]
    op.execute(
        text("""
            DELETE FROM event_emission_policies
            WHERE event_type = ANY(:types)
        """).bindparams(types=event_types)
    )
