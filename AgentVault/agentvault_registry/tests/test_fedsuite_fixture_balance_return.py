"""§SUITES1018 V0639 (agentvault2-aa, 2026-10-24): the federation suite returns what its throwaway agents hold before it
deletes them, and its operator money rails clear their pair.

The suite's agent helper (test_ironkey_authority_clamp._new_agent) is shared by ten test files, and its _cleanup deleted
without returning anything: the owner's delete is a soft delete that keeps the balance. agentvault2-66's census on
sbx-alpha found 741 deleted fedsuite-ironkey agents holding 151,339; mine found 1,071 never deleted holding 167,872 (most
from before §TWOAGENT G1 fixed the delete's argument on 2026-09-23; the operator money rails never cleared their pair at
all, 296 agents holding 5,876.73). Now each balance is read error-first by the owner and returned in full through the
frame's admin bridge (tegTreasuryReceive) before the delete, as agentvault2-66's Throwaways.close does (71de4e40), and
both money rails clear their pair once their verdict is in. The first three tests and the send-early ones fail on V0638's
modules (the control).
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, DeferredCheck, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_ironkey_authority_clamp as clamp
from agentvault_registry.api_tests.federation_suite.tests import test_operator_money_rails as money

DID = "did:theprotocol:0f0e0d0c-aaaa-bbbb-cccc-0123456789ab"


class _Client:
    def __init__(self, label: str, rig: "_Rig"):
        self.label, self.rig = label, rig

    async def call(self, tool: str, args: Dict[str, Any], timeout: int = 60):
        self.rig.calls.append((self.label, tool, dict(args)))
        return self.rig.answers.get((self.label, tool), {"ok": True})


class _Rig:
    """A rig whose MCP clients answer from a script, recording every call as (label, tool, args)."""

    def __init__(self, answers: Dict[Tuple[str, str], Any]):
        self.answers, self.calls = answers, []

    def mcp(self, label: str) -> _Client:
        return _Client(label, self)


def _batch(balance: Any = None, error: str = "") -> Dict[str, Any]:
    entry: Dict[str, Any] = {"balance": balance, "currency": "SBXA"}
    if error:
        entry["error"] = error
    return {"balances": {DID: entry}}


def _tools(rig: _Rig) -> List[Tuple[str, str]]:
    return [(label, tool) for label, tool, _ in rig.calls]


def test_a_balance_goes_back_in_full_before_the_delete():
    rig = _Rig({("sandbox-B", "getBatchAgentBalances"): _batch("96.985")})
    asyncio.run(clamp._cleanup(rig, [DID], label="sandbox-B"))
    assert _tools(rig) == [("sandbox-B", "getBatchAgentBalances"), ("sandbox-B-admin", "tegTreasuryReceive"),
                           ("sandbox-B", "deleteMyAgentByDev")]
    receive = rig.calls[1][2]
    assert receive["source_agent_did"] == DID and receive["amount"] == "96.985"
    assert receive["reason"] == "federation_suite_fixture_retired"


def test_an_unread_balance_is_never_a_zero_and_the_delete_still_runs(caplog):
    rig = _Rig({("sandbox-A", "getBatchAgentBalances"): _batch("0", error="TEG timeout")})
    with caplog.at_level("WARNING"):
        asyncio.run(clamp._cleanup(rig, [DID]))
    assert ("sandbox-A-admin", "tegTreasuryReceive") not in _tools(rig)
    assert _tools(rig)[-1] == ("sandbox-A", "deleteMyAgentByDev")
    assert "could not be read (TEG timeout)" in caplog.text and DID in caplog.text


def test_a_refused_return_is_said(caplog):
    rig = _Rig({("sandbox-A", "getBatchAgentBalances"): _batch("40.0"),
                ("sandbox-A-admin", "tegTreasuryReceive"): {"status_code": 400, "response": {"detail": "insufficient"}}})
    with caplog.at_level("WARNING"):
        asyncio.run(clamp._cleanup(rig, [DID]))
    assert "40.0 held, not returned" in caplog.text
    assert _tools(rig)[-1] == ("sandbox-A", "deleteMyAgentByDev")


@pytest.mark.parametrize("held", ["0", "0.000000"])
def test_nothing_held_moves_nothing(held):
    rig = _Rig({("sandbox-A", "getBatchAgentBalances"): _batch(held)})
    asyncio.run(clamp._cleanup(rig, [DID]))
    assert _tools(rig) == [("sandbox-A", "getBatchAgentBalances"), ("sandbox-A", "deleteMyAgentByDev")]


def _send_early_rig(monkeypatch, act):
    rig = _Rig({})
    cleared: List[Dict[str, Any]] = []

    async def clear(_rig, send, recv, state):
        cleared.append(dict(state))
    monkeypatch.setattr(money, "_send_early_act", act)
    monkeypatch.setattr(money, "_clear_pair", clear)
    return rig, cleared


def test_a_deferred_verdict_clears_its_pair_only_once_judged(monkeypatch):
    verdict = AssertionResult(passed=True, description="arrives", budget_sec=0.0, elapsed_sec=0.0,
                              polling_attempts=1, last_state={})

    async def act(rig, send, recv, state):
        state.update(sender="did:a", receiver="did:b")

        async def judge():
            return verdict
        return DeferredCheck(check=judge)
    rig, cleared = _send_early_rig(monkeypatch, act)
    state: Dict[str, Any] = {}
    out = asyncio.run(money._send_early(rig, "sandboxalpha", "sandboxdelta", state))
    assert isinstance(out, DeferredCheck) and cleared == []          # nothing cleared while the payment is on its way
    assert asyncio.run(out.check()) is verdict and len(cleared) == 1


def test_a_refusal_clears_its_pair_at_once(monkeypatch):
    async def act(rig, send, recv, state):
        state.update(sender="did:a", receiver="did:b")
        raise PreconditionUnmet("never reached the converting frame")
    rig, cleared = _send_early_rig(monkeypatch, act)
    with pytest.raises(PreconditionUnmet):
        asyncio.run(money._send_early(rig, "sandboxalpha", "sandboxdelta", {}))
    assert len(cleared) == 1


def test_both_drive_rails_clear_their_pair_in_a_finally():
    for test in (money.test_frame_to_operator, money.test_operator_to_frame):
        fn = getattr(test, "__wrapped__", test)
        src = inspect.getsource(fn)
        assert "finally:" in src and "await _clear_pair(rig, " in src.split("finally:", 1)[1]


def test_the_pair_is_cleared_on_its_own_frames(monkeypatch):
    seen: List[Tuple[List[str], str]] = []

    async def cleanup(rig, dids, label="sandbox-A"):
        seen.append((list(dids), label))
    monkeypatch.setattr(money, "_cleanup", cleanup)
    asyncio.run(money._clear_pair(None, "sandboxalpha", "sandbox-A", {"sender": "did:s", "receiver": "did:r"}))
    assert seen == [(["did:s"], "sandboxalpha"), (["did:r"], "sandbox-A")]
