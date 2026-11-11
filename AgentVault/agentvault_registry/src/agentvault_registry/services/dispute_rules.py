"""V0657 (a), session-code 2026-11-06: the rules a ruling applies, in one place, so the preview a ruler reads before the
click and the ruling itself cannot disagree. Pure: no database, no I/O.

What a ruling does (the discovery, room seq 1441, items 6, 7 and 11):
- reputation: a party-filed dispute keeps the rules it always had (the loser -10, the winner +2; a dismissal -3 for
  both, "wasting system resources"). A SYSTEM-filed dispute (the Guild's reaper: a missed deadline, a poster silent
  after a hand-in, a stuck payout) accused nobody, so nobody pays for accusing: a ruling for the worker costs the
  poster nothing, a dismissal costs nobody, and the worker loses reputation only for a deadline it missed.
- enforcement: a ruling for the complainant opens the enforcement step against the defendant (an offense, an
  escalation level, a warning or a slash), except on a system-filed dispute that was nobody's fault (a stuck payout, a
  silent poster).
- a Guild order's escrow: the ruling picks the worker's share (for the poster 0, for the worker 1; a dismissal leaves
  the status quo: paid when something was handed in, refunded when nothing was), unless the ruler sets the split.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple

RULINGS = ("IN_FAVOR_OF_COMPLAINANT", "IN_FAVOR_OF_DEFENDANT", "DISMISSED")

# why a dispute opened -> what the record says (the console's label)
REASONS = {
    "deadline_missed": "The worker handed nothing in by the deadline",
    "rejected_by_poster": "The poster rejected the work",
    "poster_silent": "The poster did not verify the hand-in in time",
    "stuck_payout": "A payout got stuck and needs a ruler",
    "filed_by_party": "Filed by a party",
}
FILED_BY = ("party", "system")

RULING_WORDS = {
    "IN_FAVOR_OF_COMPLAINANT": "in favour of the complainant",
    "IN_FAVOR_OF_DEFENDANT": "in favour of the defendant",
    "DISMISSED": "dismissed",
}


def ruling_words(ruling: Optional[str]) -> str:
    """A ruling as a person reads it ("in favour of the defendant"), never the constant."""
    return RULING_WORDS.get(ruling or "", (ruling or "").lower().replace("_", " "))


def is_system_filed(filed_by: Optional[str]) -> bool:
    return (filed_by or "").strip().lower() == "system"


def reputation_deltas(ruling: str, complainant_did: str, defendant_did: str,
                      filed_by: Optional[str] = None, reason: Optional[str] = None) -> List[Tuple[str, int, str]]:
    """(agent DID, change, why) for every reputation change a ruling makes. A record with no filed_by (filed before
    V0657) is a party's filing, as the rules always read it."""
    if not is_system_filed(filed_by):
        if ruling == "IN_FAVOR_OF_COMPLAINANT":
            return [(defendant_did, -10, "lost the dispute"), (complainant_did, 2, "won the dispute")]
        if ruling == "IN_FAVOR_OF_DEFENDANT":
            return [(complainant_did, -10, "lost the dispute (false accusation)"),
                    (defendant_did, 2, "won the dispute (vindicated)")]
        if ruling == "DISMISSED":
            return [(complainant_did, -3, "dispute dismissed"), (defendant_did, -3, "dispute dismissed")]
        return []
    # filed by the system: nobody accused anybody
    if ruling == "IN_FAVOR_OF_COMPLAINANT":
        if reason == "deadline_missed":
            return [(defendant_did, -10, "missed the deadline (the ruling)")]
        return []
    if ruling == "IN_FAVOR_OF_DEFENDANT":
        return [(defendant_did, 2, "the ruling went its way")]
    return []


def enforcement_applies(ruling: str, filed_by: Optional[str] = None, reason: Optional[str] = None) -> bool:
    """Whether the ruling opens the enforcement step against the defendant."""
    if ruling != "IN_FAVOR_OF_COMPLAINANT":
        return False
    if is_system_filed(filed_by):
        return reason == "deadline_missed"
    return True


def trust_signal_applies(ruling: str, filed_by: Optional[str] = None, reason: Optional[str] = None) -> bool:
    """Whether the ruling sends the bilateral trust signal (local_trust_updater.on_dispute_resolved). On a system-filed
    dispute a ruling for the complainant is no fault of the worker's unless it missed its deadline (a stuck payout, a
    silent poster), so no negative signal travels then, as no reputation changes."""
    return not (is_system_filed(filed_by) and ruling == "IN_FAVOR_OF_COMPLAINANT"
                and not enforcement_applies(ruling, filed_by, reason))


def guild_worker_share(ruling: str, handed_in: bool, explicit: Optional[Decimal] = None) -> Decimal:
    """The worker's share of a Guild order's escrow under a ruling (the poster is always the complainant on the Guild).
    An explicit share, between 0 and 1, is the ruler's split and wins."""
    if explicit is not None:
        share = Decimal(str(explicit))
        if share < 0 or share > 1:
            raise ValueError("worker_share must be between 0 and 1")
        return share
    if ruling == "IN_FAVOR_OF_COMPLAINANT":
        return Decimal(0)
    if ruling == "IN_FAVOR_OF_DEFENDANT":
        return Decimal(1)
    return Decimal(1) if handed_in else Decimal(0)


def implied_ruling(worker_share: Decimal) -> str:
    """The ruling a Guild resolve's split implies, for the record it closes (the contract spine's rule): the whole
    escrow to the poster is a ruling for the poster, the whole escrow to the worker one for the worker, a split
    dismisses the complaint (the split itself is kept in the record's outcome)."""
    share = Decimal(str(worker_share))
    if share <= 0:
        return "IN_FAVOR_OF_COMPLAINANT"
    if share >= 1:
        return "IN_FAVOR_OF_DEFENDANT"
    return "DISMISSED"
