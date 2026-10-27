"""AGORA pure-logic unit tests (AG-9): fee math (D19), band bounds, avg-cost.

DB-bound matching semantics are covered exhaustively by the live lifecycle
proof (/tmp/agora_lifecycle_proof.py on the canary) — these tests pin the
arithmetic identities that the money legs rely on.

Runs under pytest; also directly: python3 test_exchange_fees.py
"""
import os
import sys
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("SECRET_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("API_KEY_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("TEG_ADMIN_API_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from agentvault_registry.services.exchange_service import (  # noqa: E402
    ZERO,
    _band_bounds,
    _update_avg_cost,
    fee_split,
    q18,
)


class _Pos:  # minimal stand-in for OrgSharePosition in avg-cost math
    def __init__(self, qty=0, avg_cost=Decimal("0")):
        self.qty = qty
        self.avg_cost = avg_cost


def test_fee_split_identity():
    """fee_org + fee_proto == fee_total, always (remainder → protocol)."""
    cases = [
        (Decimal("1000"), 30, 6667),
        (Decimal("0.000000000000000001"), 30, 6667),
        (Decimal("123456.789"), 100, 5000),
        (Decimal("1"), 1, 9999),
        (Decimal("999999.999999999999999999"), 30, 6667),
        (Decimal("7"), 0, 6667),  # zero-fee listing
    ]
    for notional, bps, split in cases:
        ft, fo, fp = fee_split(notional, bps, split)
        assert fo + fp == ft, (notional, bps, split)
        assert ft >= ZERO and fo >= ZERO and fp >= ZERO
        # fee never exceeds notional at sane bps
        assert ft <= notional


def test_fee_split_rounds_down():
    """Quantization may only ever round DOWN (no fee invention)."""
    ft, fo, fp = fee_split(Decimal("1000"), 30, 6667)
    assert ft == Decimal("3.000000000000000000")
    assert fo == Decimal("2.000100000000000000")
    assert fp == Decimal("0.999900000000000000")
    raw = Decimal("1000") * Decimal(30) / Decimal(10000)
    assert ft <= raw


def test_seller_proceeds_never_negative():
    """seller_receives = notional − fee_total must be ≥ 0 at the 0–100bps clamp."""
    for bps in (0, 1, 30, 100):
        for notional in (Decimal("0.000000000000000001"), Decimal("0.01"), Decimal("1000000")):
            ft, _, _ = fee_split(notional, bps, 6667)
            assert notional - ft >= ZERO


def test_escrow_exactness_under_price_improvement():
    """BUY escrow = limit_price × qty covers any fill at maker price ≤ limit,
    and the refund residue is exactly escrow − Σ notional (D19 refined)."""
    limit = Decimal("10")
    qty = 7
    escrow = q18(limit * qty)
    fills = [(Decimal("9.5"), 3), (Decimal("9.9"), 2), (Decimal("10"), 2)]
    matched = sum((q18(px * q) for px, q in fills), ZERO)
    assert matched <= escrow
    residue = q18(escrow - matched)
    assert residue == Decimal("1.700000000000000000")
    assert matched + residue == escrow  # escrow fully accounted (I-X3 term)


def test_band_bounds():
    lo, hi = _band_bounds(Decimal("100"), 25)
    assert lo == Decimal("75") and hi == Decimal("125")
    lo, hi = _band_bounds(Decimal("0.04"), 25)
    assert lo == Decimal("0.03") and hi == Decimal("0.05")


def test_avg_cost_weighted():
    pos = _Pos(qty=0, avg_cost=ZERO)
    _update_avg_cost(pos, 10, Decimal("5")); pos.qty += 10
    assert pos.avg_cost == Decimal("5")
    _update_avg_cost(pos, 10, Decimal("7")); pos.qty += 10
    assert pos.avg_cost == Decimal("6")
    _update_avg_cost(pos, 20, Decimal("6")); pos.qty += 20
    assert pos.avg_cost == Decimal("6")


def test_q18_rounds_down_only():
    assert q18(Decimal("1.9999999999999999999")) == Decimal("1.999999999999999999")
    assert q18(Decimal("0.0000000000000000019")) == Decimal("0.000000000000000001")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"ALL_PASS ({len(fns)} tests)")
    sys.exit(0)
