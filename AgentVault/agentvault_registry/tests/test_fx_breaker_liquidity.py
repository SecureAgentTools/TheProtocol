"""§MCPTEST30 (2026-10-15) — the FX breaker counts only the part of a price move that the pool's liquidity did not change.

Measured on the sandbox (the MCP tester's federation nightly, 2026-10-15 03:03-03:06Z): sbx-beta's FX reserve keeper
topped its reserve up 10,462.56 SBXB in one move (195,632.93 -> 206,095.49, +5.35%), and sbx-alpha's breaker (5% within
300 s) refused every cross-frame send for the next window ("spot price moved 5.29%"): three federation checks red, no
funds moved. The pool is a constant-product curve: a swap moves the price and leaves k = x*y as it was, while a top-up or
sweep moves the price and k by the same factor. The breaker now judges what is left of a move once the liquidity change
is taken out, so a reserve move re-sets the baseline and a market move still trips it, beside a reserve move too.
"""
import ast
import asyncio
import inspect
import json
from decimal import Decimal

import pytest
from fastapi import HTTPException

from agentvault_registry.background_tasks import leader
from agentvault_registry.routers import teg_integration as ti

PAIR = "SBXA:SBXB"


class FakeRedis:
    def __init__(self):
        self.d = {}

    async def get(self, k):
        return self.d.get(k)

    async def set(self, k, v, ex=None):
        self.d[k] = v


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()

    async def _get():
        return r

    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setenv("FX_BREAKER_PCT", "0.05")
    monkeypatch.setenv("FX_BREAKER_WINDOW_SEC", "300")
    return r


def check(x, y, pair=PAIR):
    """One swap's breaker check at reserves (x, y): spot = x/y, k = x*y, as the pool quote gives them."""
    x, y = Decimal(str(x)), Decimal(str(y))
    asyncio.run(ti._fx_breaker_check_and_update(x / y, k_now=x * y, pair=pair))


def swap(x, y, amount_in, sell="x"):
    """Sell `amount_in` of one side's currency along the curve: (x + a) * y' = x * y (or the same with y)."""
    x, y, a = Decimal(str(x)), Decimal(str(y)), Decimal(str(amount_in))
    if sell == "x":
        return x + a, (x * y) / (x + a)
    return (x * y) / (y + a), y + a


def test_a_market_move_beyond_the_threshold_still_trips(redis):
    check(200000, 200000)
    x, y = swap(200000, 200000, 6000)          # the price moves ~6.1% along the curve, k unchanged
    with pytest.raises(HTTPException) as e:
        check(x, y)
    assert e.value.status_code == 409
    assert "FX circuit breaker" in str(e.value.detail)


def test_the_measured_keeper_top_up_moves_the_baseline_instead(redis):
    # sbx-alpha prices SBXA -> SBXB with x = the peer's SBXB reserve, y = its own SBXA reserve
    check("195632.926612", "206095.486018")
    check("206095.486018", "206095.486018")   # sbx-beta's keeper: +10,462.56 SBXB in one move (+5.35%)
    base = json.loads(redis.d[f"fx:breaker:{PAIR}"])
    assert Decimal(base["p"]) == Decimal("1")  # the baseline moved with the reserve
    x, y = swap("206095.486018", "206095.486018", 300)
    check(x, y)                                # the next ordinary swap passes


def test_a_keeper_move_does_not_hide_a_market_move_beside_it(redis):
    check(200000, 200000)
    x, y = swap(200000, 200000, 6000)          # a ~6.1% market move ...
    with pytest.raises(HTTPException):
        check(x * Decimal("1.01"), y)          # ... beside a 1% top-up of x the same way: 6.1% stays unexplained


def test_a_small_market_move_beside_a_reserve_move_passes(redis):
    check(200000, 200000)
    y = Decimal("200000") * Decimal("1.06")    # a 6% top-up of y: the price falls 5.7% ...
    x, y = swap(200000, y, 1000, sell="y")     # ... and a ~1% swap the same way: 6.5% in all, about 1% of it the market's
    assert abs(x / y - 1) > Decimal("0.05")    # the whole move is past the threshold
    check(x, y)


def test_a_baseline_written_before_the_rule_is_judged_as_before(redis):
    redis.d[f"fx:breaker:{PAIR}"] = json.dumps({"p": "1", "ts": __import__("time").time()})
    with pytest.raises(HTTPException):
        check(206000, 195600)                  # +5.3% on a baseline without k: not judged against the liquidity


def test_each_pair_keeps_its_own_baseline(redis):
    check(200000, 200000, pair="SBXA:SBXB")
    check(230000, 200000, pair="SBXA:SBXC")    # another pair's spot is no move of this one
    assert set(redis.d) == {"fx:breaker:SBXA:SBXB", "fx:breaker:SBXA:SBXC"}


def test_off_when_no_threshold_is_set(redis, monkeypatch):
    monkeypatch.setenv("FX_BREAKER_PCT", "0")
    check(200000, 200000)
    check(300000, 200000)
    assert redis.d == {}


def test_the_swap_path_hands_the_breaker_k_and_the_pair():
    calls = [n for n in ast.walk(ast.parse(inspect.getsource(ti)))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_fx_breaker_check_and_update"]
    assert calls, "the swap path no longer calls the breaker"
    for c in calls:
        assert {kw.arg for kw in c.keywords} >= {"k_now", "pair"}
