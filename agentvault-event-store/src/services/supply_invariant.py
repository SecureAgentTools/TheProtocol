"""Canonical, pure definition of the supply invariant (§B / CLAUDE.md PART 4).

This is the single Python source of truth for how each LedgerBalanceChanged
`kind` maps to the supply buckets, and for the per-frame invariant:

    net_supply = tokens_issued - tokens_destroyed + transit_net
    delta      = abs(net_supply - total_circulating)      # 0 = conserved

It mirrors the PL/pgSQL classifier in
``migrations/materialized_balances.sql`` (the IF kind IN ('mint','dispute_comp')
… ELSIF ('slash','burn') … ELSE transit block). Keeping a faithful pure copy
here makes the prime-directive math unit-testable off-database
(tests/test_supply_invariant.py); the SQL trigger and the async projections
(services/projections.py, services/materialized_projections.py) must agree
with it.
"""
from decimal import Decimal
from typing import Iterable, Mapping

# Only genuine mint / compensation create supply; only slash / burn destroy it.
# Everything else (transfers, stake legs, fees, escrow legs, cross-frame legs,
# and any untagged 'unknown') is supply-neutral and accumulates in transit_net.
ISSUED_KINDS = frozenset({"mint", "dispute_comp"})
DESTROYED_KINDS = frozenset({"slash", "burn"})


def classify_kind(kind: str) -> str:
    """Map a ledger `kind` to a supply bucket: 'issued' | 'destroyed' | 'transit'."""
    k = (kind or "").strip().lower()
    if k in ISSUED_KINDS:
        return "issued"
    if k in DESTROYED_KINDS:
        return "destroyed"
    return "transit"


def compute_supply(legs: Iterable[Mapping]) -> dict:
    """Aggregate signed ledger legs into the supply buckets.

    Each leg is a mapping with `kind` (str) and `amount` (signed number). Mirrors
    the SQL exactly: issued/transit accumulate the signed amount; destroyed
    accumulates ABS(amount) (a burn arrives as a negative balance change).
    Returns Decimals for tokens_issued, tokens_destroyed, transit_net, net_supply.
    """
    issued = destroyed = transit = Decimal(0)
    for leg in legs:
        amt = Decimal(str(leg["amount"]))
        bucket = classify_kind(leg.get("kind"))
        if bucket == "issued":
            issued += amt
        elif bucket == "destroyed":
            destroyed += abs(amt)
        else:
            transit += amt
    return {
        "tokens_issued": issued,
        "tokens_destroyed": destroyed,
        "transit_net": transit,
        "net_supply": issued - destroyed + transit,
    }


def supply_delta(net_supply, total_circulating) -> Decimal:
    """The supply-invariant delta. 0 == conserved (the prime directive)."""
    return abs(Decimal(str(net_supply)) - Decimal(str(total_circulating)))
