"""W4 phase 1 (agentvault2-aa, 2026-10-25): the ledger's event names, old and new, read as one.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger, "just
use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W4). The
names a reader meets in the ledger carry the critical words (TokensTransferred, TokensStaked, RewardsDistributed); their
new names say units, locks and lock payouts, as agentvault2-d6's W3 named the MCP tools (lockUnits, claimLockPayouts,
getMyPayoutRelock).

PHASE 1 (this module, V0643 and the event store, TEG and auditor images beside it): every reader accepts both names of an
event; nothing emits a new name. PHASE 2 (later, behind one switch per emitter, default the old names): the emitters write
the new names, once every reader on every node knows them. No stored event is ever rewritten: a ledger keeps its history
under the names it was written with, so readers keep both names for good.

A reader asks this module, never a literal: `names_of(t)` for every name of t's event, `expand(types)` for a set or an SQL
IN list, `same(a, b)` for a comparison, `old_name(t)` to look a new or legacy name up in a table keyed by the old name.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, Tuple

# old name -> new name (the names the emitters write today -> the names phase 2 writes)
RENAMED: Dict[str, str] = {
    "TokensTransferred": "UnitsTransferred",
    "TokensIssued": "UnitsIssued",
    "TokensStaked": "UnitsLocked",
    "TokensUnstaked": "UnitsUnlocked",
    "StakeForceUnstaked": "LockForceUnlocked",
    "RewardsDistributed": "LockPayoutsDistributed",
    "RewardsAutoCompounded": "LockPayoutsRelocked",
    "RewardsAutoCompoundSkipped": "LockPayoutRelockSkipped",
    "TokensBridgeLocked": "UnitsBridgeLocked",
    "TokensBridgeUnlocked": "UnitsBridgeUnlocked",
}

# AGORA's (his AGORA call decides whether phase 2 writes them; readers know them from phase 1 on)
AGORA_RENAMED: Dict[str, str] = {
    "ExchangeDividendDeclared": "ExchangeDistributionDeclared",
    "ExchangeDividendPaid": "ExchangeDistributionPaid",
    "ExchangeSharesIssued": "ExchangePointsIssued",
    "ExchangeSharesSplit": "ExchangePointsSplit",
    "ExchangeShareRefloated": "ExchangePointsRefloated",
}

# older spellings some stores still hold or some code still names, read as their event (no emitter writes them)
LEGACY: Dict[str, str] = {
    "TokenTransferred": "TokensTransferred",
    "RewardDistributed": "RewardsDistributed",
    "StakeRewardDistributed": "RewardsDistributed",
}

_ALL_RENAMED: Dict[str, str] = {**RENAMED, **AGORA_RENAMED}
_NEW_TO_OLD: Dict[str, str] = {new: old for old, new in _ALL_RENAMED.items()}
assert len(_NEW_TO_OLD) == len(_ALL_RENAMED), "a new name must name exactly one event"
assert not set(_NEW_TO_OLD) & set(_ALL_RENAMED), "a new name must not be an old one"


def old_name(name: str) -> str:
    """The name an event has had since before W4 (the key existing tables use): a new or a legacy name maps back to it,
    any other name is returned as it is."""
    if name in _NEW_TO_OLD:
        return _NEW_TO_OLD[name]
    return LEGACY.get(name, name)


def new_name(name: str) -> str:
    """The name phase 2 writes for an event (an unrenamed name is its own new name)."""
    old = old_name(name)
    return _ALL_RENAMED.get(old, old)


def names_of(name: str) -> Tuple[str, ...]:
    """Every name an event is stored under: the old name first, then the new one, then the legacy spellings. An unrenamed
    name is a one-tuple of itself, so a reader that asks for every name behaves exactly as before for every other event."""
    old = old_name(name)
    out = [old]
    if old in _ALL_RENAMED:
        out.append(_ALL_RENAMED[old])
    out.extend(sorted(k for k, v in LEGACY.items() if v == old))
    return tuple(out)


def expand(names: Iterable[str]) -> FrozenSet[str]:
    """Every name of every event in `names` (for a membership test or an SQL IN list)."""
    out = set()
    for n in names:
        out.update(names_of(n))
    return frozenset(out)


def same(a: str, b: str) -> bool:
    """Whether two names name the same event."""
    if not a or not b:
        return a == b
    return old_name(a) == old_name(b)


def live_names(name: str) -> Tuple[str, ...]:
    """The names an emitter may write for an event, today or in phase 2: the old name and its new one, never a legacy
    spelling (nothing writes those any more). What a live subscriber listens for and polls."""
    old = old_name(name)
    return (old, _ALL_RENAMED[old]) if old in _ALL_RENAMED else (old,)
