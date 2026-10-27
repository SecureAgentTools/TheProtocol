"""
Reactor: ProposalTallied → governance outcome fan-out
======================================================
Both manual tally (`POST /governance/proposals/{id}/tally` in
governance.py) and the auto-tally background worker emit `ProposalTallied`
with `result: "PASSED"|"FAILED"`. This reactor turns that into developer-
facing webhook notifications.

Side effects:
- Webhook fan-out — `governance.proposal_passed` if result=PASSED,
  `governance.proposal_failed` otherwise. Single canonical event split
  into two webhook channels so subscribers can filter.

Intraregistry consequences: none. The tally path already:
- Set `proposals.status` (PASSED|FAILED).
- Auto-applied `policy_diff` for passed `policy_change` proposals (and
  emitted `GovernancePolicyChangeApplied` separately).
- Vote weights were locked at vote-time; no recalc.

No email today (could be added later as a "your vote was counted" digest
to all voting agents — separate scope).
"""
import logging
from typing import Optional

from .reactor_base import EventStoreReactor
from .reactor_helpers import dispatch_webhook_event

logger = logging.getLogger(__name__)


class ProposalTalliedReactor(EventStoreReactor):
    event_type = "ProposalTallied"
    leader_key = "reactor_proposal_tallied"
    name = "ProposalTallied"

    async def handle_event(self, event_data: dict) -> None:
        proposal_id = event_data.get("proposal_id") or "?"
        result = (event_data.get("result") or "").upper()
        votes_for = event_data.get("votes_for", "?")
        votes_against = event_data.get("votes_against", "?")
        quorum_met = event_data.get("quorum_met")

        logger.info(
            f"[Reactor:{self.name}] proposal={proposal_id} result={result} "
            f"for={votes_for} against={votes_against} quorum_met={quorum_met}"
        )

        # Map result → channel. Treat anything other than PASSED as failed
        # (covers FAILED, quorum-not-met, EXPIRED-style outcomes).
        webhook_event_type = (
            "governance.proposal_passed" if result == "PASSED"
            else "governance.proposal_failed"
        )

        await dispatch_webhook_event(
            event_type=webhook_event_type,
            event_data=event_data,
            source_label=self.name,
        )

        # E (2026-05-08): live WS notification — governance outcomes are
        # interesting to all users. Tally events are rare (per-proposal,
        # one-shot) so no throttle needed.
        try:
            from agentvault_registry.routers.websocket import broadcast_notification
            short_id = str(proposal_id)[:8]
            await broadcast_notification(
                title=f"Proposal {result.lower()}",
                message=f"Proposal {short_id}… · for: {votes_for} · against: {votes_against}",
                notification_type="info" if result == "PASSED" else "warning",
            )
        except Exception as e:
            logger.warning(f"[Reactor:{self.name}] broadcast_notification failed (non-fatal): {e}")


_instance: Optional[ProposalTalliedReactor] = None


async def start() -> None:
    global _instance
    if _instance is None:
        _instance = ProposalTalliedReactor()
    await _instance.start()


async def stop() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
