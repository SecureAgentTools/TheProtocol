"""Unit tests for the supply invariant — the Δ=0 prime directive.

Pins the classifier + delta arithmetic that the SQL trigger
(migrations/materialized_balances.sql) and the projections rely on. This is the
math that, until now, was only ever verified in production by the auditor.

Run directly:  python3 test_supply_invariant.py      (or via pytest)
"""
import os
import sys
from decimal import Decimal

# Import the pure module directly (bypass services/__init__, which pulls in sqlalchemy).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "services"))

from supply_invariant import classify_kind, compute_supply, supply_delta  # noqa: E402


def test_classify_kind():
    assert classify_kind("mint") == "issued"
    assert classify_kind("dispute_comp") == "issued"
    assert classify_kind("slash") == "destroyed"
    assert classify_kind("burn") == "destroyed"
    # everything else — including untagged / unknown — is supply-neutral transit
    for k in ("transfer", "fee", "escrow", "cross_frame", "stake", "unknown", "", None):
        assert classify_kind(k) == "transit", k


def test_mint_increases_supply():
    s = compute_supply([{"kind": "mint", "amount": 100}])
    assert s["tokens_issued"] == Decimal(100)
    assert s["net_supply"] == Decimal(100)
    assert supply_delta(s["net_supply"], 100) == 0


def test_burn_destroys_supply():
    # a burn arrives as a negative balance change; destroyed uses ABS (mirrors SQL)
    s = compute_supply([{"kind": "mint", "amount": 100}, {"kind": "burn", "amount": -30}])
    assert s["tokens_destroyed"] == Decimal(30)
    assert s["net_supply"] == Decimal(70)
    assert supply_delta(s["net_supply"], 70) == 0


def test_transfer_is_supply_neutral():
    # a transfer is two single-sided legs that net to zero in transit_net
    s = compute_supply([
        {"kind": "mint", "amount": 100},
        {"kind": "transfer", "amount": -50},
        {"kind": "transfer", "amount": 50},
    ])
    assert s["transit_net"] == 0
    assert s["net_supply"] == Decimal(100)          # unchanged by the transfer
    assert supply_delta(s["net_supply"], 100) == 0


def test_fees_are_zero_sum():
    s = compute_supply([{"kind": "fee", "amount": -1}, {"kind": "fee", "amount": 1}])
    assert s["transit_net"] == 0
    assert s["net_supply"] == 0


def test_breach_is_detected():
    # a circulating total that doesn't match net_supply yields a non-zero delta
    # (this is exactly what the auditor flags as a BREACH)
    s = compute_supply([{"kind": "mint", "amount": 100}])
    assert supply_delta(s["net_supply"], 99) == Decimal(1)


def test_full_invariant_balanced():
    legs = [
        {"kind": "mint", "amount": 1000},
        {"kind": "transfer", "amount": -200}, {"kind": "transfer", "amount": 200},
        {"kind": "fee", "amount": -5}, {"kind": "fee", "amount": 5},
        {"kind": "slash", "amount": -50},
        {"kind": "dispute_comp", "amount": 10},
    ]
    s = compute_supply(legs)
    assert s["tokens_issued"] == Decimal(1010)      # 1000 mint + 10 dispute_comp
    assert s["tokens_destroyed"] == Decimal(50)     # slash
    assert s["transit_net"] == Decimal(0)           # transfers + fees net out
    assert s["net_supply"] == Decimal(960)
    assert supply_delta(s["net_supply"], 960) == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
