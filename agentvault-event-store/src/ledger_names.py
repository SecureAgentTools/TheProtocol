"""W4 phase 1 (agentvault2-aa, 2026-10-25): the ledger's event names, old and new, read as one, in the event store.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger, "just
use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W4). The
store cannot import the registry, so this is the registry's map (agentvault_registry/core/ledger_names.py) held here, data
for data; tests/test_ledger_names_store.py pins it.

PHASE 1: every reader accepts both names of an event; nothing emits a new name yet. PHASE 2 (later, one switch per emitter,
default the old names) lets the emitters write the new names once every reader on every node knows them. No stored event
is ever rewritten, so the readers keep both names for good.

The store's balance and supply code asks `live_old(t)`: a NEW name reads as its old one, every other name stays exactly as
it is. A legacy spelling (TokenTransferred, StakeRewardDistributed) is never re-read as its event here: the projection has
never applied one, and a reader that started to would move a replayed balance. Sets and SQL IN lists ask `expand_live`.
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

# older spellings some stores still hold, as the registry's map names them (the store's balance code leaves them alone)
LEGACY: Dict[str, str] = {
    "TokenTransferred": "TokensTransferred",
    "RewardDistributed": "RewardsDistributed",
    "StakeRewardDistributed": "RewardsDistributed",
}

_ALL_RENAMED: Dict[str, str] = {**RENAMED, **AGORA_RENAMED}
_NEW_TO_OLD: Dict[str, str] = {new: old for old, new in _ALL_RENAMED.items()}
assert len(_NEW_TO_OLD) == len(_ALL_RENAMED), "a new name must name exactly one event"
assert not set(_NEW_TO_OLD) & set(_ALL_RENAMED), "a new name must not be an old one"


def live_old(name: str) -> str:
    """A new name as its old one; any other name (an old name, a legacy spelling, an unrenamed event) as it is."""
    return _NEW_TO_OLD.get(name, name)


def live_names(name: str) -> Tuple[str, ...]:
    """The names an emitter may write for an event, today or in phase 2: the old name and its new one."""
    old = live_old(name)
    return (old, _ALL_RENAMED[old]) if old in _ALL_RENAMED else (old,)


def expand_live(names: Iterable[str]) -> FrozenSet[str]:
    """Every live name of every event in `names` (a membership set or an SQL IN list); legacy spellings are not added."""
    out = set()
    for n in names:
        out.update(live_names(n))
    return frozenset(out)


def old_name(name: str) -> str:
    """As the registry's map: a new or a legacy name maps back to the old one (for labels and lookups, never balances)."""
    if name in _NEW_TO_OLD:
        return _NEW_TO_OLD[name]
    return LEGACY.get(name, name)


def new_name(name: str) -> str:
    """The name phase 2 writes for an event (an unrenamed name is its own new name)."""
    old = old_name(name)
    return _ALL_RENAMED.get(old, old)
