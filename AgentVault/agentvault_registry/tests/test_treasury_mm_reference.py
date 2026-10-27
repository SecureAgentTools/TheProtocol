"""§AGORASIM-2 (2026-09-22): the treasury market maker quotes around the MARKET's price, not its own last print.

The tape below is ALFW on sbx-alpha, 14:06Z to 14:13Z that day, read from exchange_trades (seq 1284..1316). More than
half of its prints had the treasury on one side (183 of 330 since 12:15Z), and each such fill landed one spread (3%)
from the market maker's reference, twice the drift tolerance: the old reference (the last print) made it cancel and
re-post both quotes after nearly every fill (958 of 958 treasury quotes cancelled on sbx-alpha in two hours) and walked
the price down on its own buys (about 47 to 42.79 in seven minutes).
"""
import inspect
from decimal import Decimal

from agentvault_registry.background_tasks import treasury_market_maker as mm
from agentvault_registry.background_tasks.treasury_market_maker import market_reference, quote_is_fresh

T = "did:theprotocol:org-alfw-treasury"
X = "did:theprotocol:sandbox-a.theprotocol.cloud:trader-1"
Y = "did:theprotocol:sandbox-a.theprotocol.cloud:trader-2"
# (seq, price, who), oldest first. who: "B" the treasury bought (a taker sold into its bid), "S" the treasury sold,
# "-" two traders. Taken verbatim from the sandbox tape.
TAPE = [
    (1284, "47.05", "S"), (1285, "47.05", "S"), (1286, "45.64", "B"), (1287, "45.64", "B"), (1288, "47.01", "S"),
    (1289, "47.01", "S"), (1290, "46.31", "-"), (1291, "47.70", "S"), (1292, "49.13", "S"), (1293, "46.31", "-"),
    (1294, "46.27", "B"), (1295, "47.66", "S"), (1298, "47.06", "-"), (1299, "46.23", "B"), (1300, "45.51", "-"),
    (1305, "46.88", "S"), (1306, "47.06", "-"), (1309, "45.51", "-"), (1310, "45.47", "B"), (1311, "45.57", "-"),
    (1312, "45.57", "-"), (1313, "45.30", "-"), (1314, "44.11", "B"), (1316, "42.79", "B"),
]
SPREAD = Decimal("0.03")          # the sandbox listings' spread_bps 300
TOL = SPREAD / 2                  # the worker's drift tolerance


def _row(price, who):
    if who == "B":
        return (Decimal(price), T, X)
    if who == "S":
        return (Decimal(price), X, T)
    return (Decimal(price), X, Y)


def _newest_first(k):
    """The tape as the worker reads it after the k-th print: newest first."""
    return [_row(p, w) for _, p, w in reversed(TAPE[:k])]


def test_the_reference_is_the_market_not_the_market_makers_last_print():
    ref, src = market_reference(_newest_first(len(TAPE)), T, n=9, min_external=3)
    assert ref == Decimal("45.57") and src == "market median of 9"
    last_print = Decimal(TAPE[-1][1])                     # 42.79, the treasury's own buy
    assert TAPE[-1][2] == "B" and abs(ref - last_print) / ref > SPREAD, "the control: the old reference sat a spread away"


def _requotes(reference_of):
    """Replay the tape: quotes rest at ref*(1-s) / ref*(1+s) and are replaced when either leaves the tolerance
    around the new target, with the worker's own predicate. Counted from the 9th print on (a full window)."""
    bid = ask = None
    n = 0
    for k in range(9, len(TAPE) + 1):
        ref = reference_of(k)
        tb, ta = ref * (1 - SPREAD), ref * (1 + SPREAD)
        if not (quote_is_fresh(bid, tb, TOL) and quote_is_fresh(ask, ta, TOL)):
            if bid is not None:
                n += 1
            bid, ask = tb, ta
    return n


def test_the_measured_tape_replays_to_far_fewer_requotes():
    old = _requotes(lambda k: Decimal(TAPE[k - 1][1]))
    new = _requotes(lambda k: market_reference(_newest_first(k), T, n=9, min_external=3)[0])
    # measured: the last print re-centred on 8 of 15 steps (after nearly every fill of its own quote); the market
    # median twice (47.01 -> 46.31 while only three trader prints existed, 46.31 -> 45.57 when the traders' own prints
    # slid there) and then held 45.57 while its own buys printed 44.11 and 42.79
    assert old >= 8, f"the control: the last-print reference re-quoted only {old} times on this tape"
    assert new <= 2 and new * 4 <= old, f"the market reference re-quoted {new} times (the last print {old})"


def test_a_thin_book_uses_the_median_of_all_prints_and_one_own_fill_cannot_move_it():
    own = [(Decimal("47.05"), X, T), (Decimal("45.64"), T, X), (Decimal("47.01"), X, T),
           (Decimal("45.64"), T, X), (Decimal("47.05"), X, T)]
    ref, src = market_reference(own, T, n=9, min_external=3)
    assert src == "median of 5 prints (thin book)" and ref == Decimal("47.01")
    ref2, _ = market_reference([(Decimal("42.79"), T, X)] + own, T, n=9, min_external=3)
    assert abs(ref2 - ref) / ref < TOL, "one fill of its own bid moved a thin-book reference past the tolerance"


def test_empty_and_unknown_treasury():
    assert market_reference([], T) == (None, "")
    ref, src = market_reference([(Decimal("10"), T, X), (Decimal("12"), X, T), (Decimal("11"), X, Y)], None, n=9, min_external=3)
    assert (ref, src) == (Decimal("11"), "market median of 3")


def test_quote_is_fresh():
    assert quote_is_fresh(Decimal("100"), Decimal("101"), TOL)
    assert not quote_is_fresh(Decimal("100"), Decimal("103"), TOL)
    assert not quote_is_fresh(None, Decimal("100"), TOL)
    assert not quote_is_fresh(Decimal("1"), Decimal("0"), TOL)


def test_the_worker_asks_the_market_reference_before_any_last_print():
    src = inspect.getsource(mm.TreasuryMarketMaker._reference_price)
    assert "market_reference(" in src and "_last_price(" in src
    assert src.index("market_reference(") < src.index("_last_price("), "the last print is consulted before the market"
    assert "quote_is_fresh(" in inspect.getsource(mm.TreasuryMarketMaker._quote_one)
