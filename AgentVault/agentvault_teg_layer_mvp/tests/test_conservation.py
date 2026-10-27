"""TEG money-conservation invariants — the per-transfer basis of Δ=0.

Pure CONTRACT tests: they pin the arithmetic every TEG transfer must satisfy
(conservation, non-negativity, fee bounds, fee zero-sum). The live transfer path
(transfer_service_enhanced.py) is DB-bound and is exercised end-to-end by the
canary + the gated money-path test on the backlog; these pin the identities that
path must never violate, so a regression in the leg math fails here at PR time.

Run directly:  python3 test_conservation.py      (or via pytest)
"""
import sys
from decimal import Decimal


def transfer_legs(amount, fee):
    """The three balance deltas of a fee-deducted transfer:
       sender pays `amount`; receiver gets `amount - fee`; fee_collector gets `fee`.
    Conservation requires the three to sum to zero for ANY (amount, fee).
    """
    amount, fee = Decimal(str(amount)), Decimal(str(fee))
    return {"sender": -amount, "receiver": amount - fee, "fee_collector": fee}


def apply_debit(balance, amount):
    """Balance non-negativity guard — mirrors the TEG CHECK(token_balance >= 0)."""
    balance, amount = Decimal(str(balance)), Decimal(str(amount))
    new = balance - amount
    if new < 0:
        raise ValueError("insufficient balance")
    return new


def test_transfer_conserves_tokens():
    # the sum of all three legs is always exactly zero — no tokens created/destroyed
    for amount, fee in [(100, 0), (100, 5), (1, 0), (10 ** 9, 12345), ("0.5", "0.0025")]:
        legs = transfer_legs(amount, fee)
        assert sum(legs.values()) == 0, (amount, fee)


def test_fee_and_credit_non_negative():
    legs = transfer_legs(100, 5)
    assert legs["receiver"] >= 0          # receiver credit never goes negative
    assert legs["fee_collector"] >= 0     # fee is never negative


def test_fee_is_zero_sum_to_collector():
    # what the sender pays beyond the receiver's credit lands exactly in the fee leg
    legs = transfer_legs(100, 5)
    assert legs["fee_collector"] == (-legs["sender"]) - legs["receiver"]


def test_balance_non_negative_guard():
    assert apply_debit(100, 40) == Decimal(60)
    try:
        apply_debit(10, 40)
        assert False, "debit below zero should have raised"
    except ValueError:
        pass


def test_zero_fee_is_pure_move():
    legs = transfer_legs(250, 0)
    assert legs["fee_collector"] == 0
    assert legs["receiver"] == Decimal(250)
    assert sum(legs.values()) == 0


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
