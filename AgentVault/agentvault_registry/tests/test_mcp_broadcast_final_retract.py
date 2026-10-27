"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): the broadcast lifecycle's final retract is read back, and said.

earned_ad_platform._broadcast composes a broadcast of the run's own, updates, retracts and reinstates it, then retracts
it once more in a finally. That last answer was never read: after the reinstate, a retract that missed left the broadcast
live on the console's header (six on the two sandbox operators, one per run, while every run read clean; asked again by
hand each answered 204 and read inactive). Now the final retract is read back, asked once more, and a broadcast still
live is a red on the retract's row naming it. The tests drive _settle_retracted with an admin bridge from a script; the
first two fail on V0637's module, which has no such step (the control).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from agentvault_registry.api_tests.contracts import earned_ad_platform as plat
from agentvault_registry.api_tests.contracts.earned_fixtures import effect_name

BID = 4242
RETRACT = "theprotocol_retractBroadcast"


class _Bag:
    """An admin bridge whose broadcast turns inactive after `lands_on` retracts (never, when 0)."""
    developer_jwt = "admin-jwt"

    def __init__(self, lands_on: int):
        self.lands_on, self.retracts, self.calls = lands_on, 0, []

        async def rpc_admin(tool: str, args: Dict[str, Any], jwt: str = "", timeout: int = 30):
            self.calls.append(tool)
            if tool == RETRACT:
                self.retracts += 1
                return True, {"result": {}}, "204"
            if tool == "theprotocol_getAdminBroadcasts":
                live = not (self.lands_on and self.retracts >= self.lands_on)
                return True, {"result": {"broadcasts": [{"id": BID, "is_active": live}]}}, "200"
            return False, {"result": {"_text": "Error: not in this script"}}, "404"
        self.rpc_admin = rpc_admin


def _parse(body: Dict[str, Any]) -> Dict[str, Any]:
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, dict) else {}


def _settle(bag, monkeypatch) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    monkeypatch.setattr(plat.asyncio, "sleep", _no_sleep)      # the retry's pause, without waiting; restored after
    asyncio.run(plat._settle_retracted(bag, _parse, BID, out))
    return out


async def _no_sleep(_s):
    return None


def test_a_retract_that_lands_says_nothing(monkeypatch):
    bag = _Bag(lands_on=1)
    assert _settle(bag, monkeypatch) == {} and bag.retracts == 1


def test_a_retract_that_lands_on_the_second_ask_says_nothing(monkeypatch):
    bag = _Bag(lands_on=2)
    assert _settle(bag, monkeypatch) == {} and bag.retracts == 2


def test_a_broadcast_still_live_after_two_asks_is_a_red_naming_it(monkeypatch):
    bag = _Bag(lands_on=0)
    out = _settle(bag, monkeypatch)
    assert bag.retracts == 2
    row = out[effect_name(RETRACT)]
    assert row["healthy"] is False and f"broadcast {BID}" in str(row) and "is_active=True" in str(row)


def test_the_lifecycle_ends_with_the_judged_retract():
    import inspect
    src = inspect.getsource(plat._broadcast)
    assert "await _settle_retracted(bag, parse, bid, outcomes)" in src
    finally_part = src.split("finally:", 1)[1]
    assert '"theprotocol_retractBroadcast"' not in finally_part      # no unread retract left in the finally
