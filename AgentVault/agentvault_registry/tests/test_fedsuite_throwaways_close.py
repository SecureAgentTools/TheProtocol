"""§MCPTEST30 V0641 (agentvault2-aa, 2026-10-25): what a federation-suite test makes, the suite retires.

agentvault2-66's census on sbx-beta (2026-10-24 23:3xZ): 1,105 ACTIVE fedsuite-* agents under the suite's developer
(ironkey 531, mech 231, xfr 172, esping 145, ctr 20, ev 4, a2a 2), 485 of them holding about 29,748 liquid and 440
staked. V0639 returned what the ironkey helper's agents held before their delete; every other helper made agents and
left them, and the cleanups that did delete kept the balance on the deleted agent (the owner's delete is a soft delete,
and the balance read refuses a revoked agent afterwards). Now each helper names an agent the moment its DID is known
(throwaways.made), the cleanups that delete return first (throwaways.retire), and the decorator retires what a test did
not retire itself once its verdict is in, a deferred check's after its judgment. The close never changes a verdict.
Every test_red_* fails on 448efaac (the control: no throwaways module, and no helper names its agent).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from typing import Any, Dict, List, Tuple

import pytest

from agentvault_registry.api_tests import probe_meter as pm
from agentvault_registry.api_tests.federation_suite import decorator as dec
from agentvault_registry.api_tests.federation_suite import rig as rig_mod
from agentvault_registry.api_tests.federation_suite import throwaways as tw
from agentvault_registry.api_tests.federation_suite.tests import test_cross_frame_transfer_economic as xfr
from agentvault_registry.api_tests.federation_suite.tests import test_ironkey_authority_clamp as clamp

SUITE = pathlib.Path(tw.__file__).parent
DID_A = "did:theprotocol:0a0a0a0a-1111-2222-3333-444455556666"
DID_B = "did:theprotocol:0b0b0b0b-1111-2222-3333-444455556666"
RETIRE = ["getBatchAgentBalances", "tegTreasuryReceive", "deleteMyAgentByDev"]


class _Client:
    def __init__(self, label: str, rig: "_Rig"):
        self.label, self.rig = label, rig

    async def call(self, tool: str, arguments: Any = None, timeout: int = 60, **_kw):
        args = dict(arguments or {})
        self.rig.calls.append((self.label, tool, args))
        if self.rig.delay:
            await asyncio.sleep(self.rig.delay)
        answer = self.rig.answers.get((self.label, tool))
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(args)
        return answer if answer is not None else {"ok": True}


class _Rig:
    """A rig whose MCP clients answer from a script, recording every call as (label, tool, args)."""

    def __init__(self, answers: Dict[Tuple[str, str], Any], delay: float = 0.0):
        self.answers, self.calls, self.delay = answers, [], delay

    def mcp(self, label: str) -> _Client:
        return _Client(label, self)


def _balances(held: Dict[str, str]):
    """getBatchAgentBalances answering each asked DID from `held`."""
    return lambda args: {"balances": {d: {"balance": held.get(d, "0"), "currency": "SBXB"}
                                      for d in args.get("agent_dids") or []}}


def _tools(rig: _Rig) -> List[str]:
    return [tool for _label, tool, _args in rig.calls]


def _spec(runner, start_first: bool = False):
    return dec.FederationTestSpec(name="t", category="c", budget_sec=1.0, severity="low", requires=[], tags=[],
                                  runner=runner, start_first=start_first)


def _result(passed: bool = True, detail: str = None):
    return rig_mod.AssertionResult(passed=passed, description="the thing under test", budget_sec=1.0, elapsed_sec=0.0,
                                   polling_attempts=1, failure_detail=detail)


@pytest.fixture(autouse=True)
def _fresh_bond_config(monkeypatch):
    # ensure_bonded caches each label's bond posture for the process; these rigs answer it "off" (no mode)
    monkeypatch.setattr(rig_mod, "_BOND_CONFIG", {})


def test_red_an_agent_a_helper_made_goes_back_and_is_deleted_after_the_verdict():
    rig = _Rig({("sandbox-B", "createAgent"): {"did": DID_B, "client_id": "c", "client_secret": "s"},
                ("sandbox-B", "getAgentToken"): {"access_token": "agent-jwt"},
                ("sandbox-B", "getBatchAgentBalances"): _balances({DID_B: "12.5"})})
    at_verdict: List[str] = []

    async def runner(r):
        pm.record_probe()
        await xfr._new_agent_on(r, "sandbox-B", "rx")              # the real helper: xfr's receivers were 172 of them
        at_verdict.extend(_tools(r))
        return _result(True)

    o = asyncio.run(dec.execute_test(_spec(runner), rig))
    assert o.state == "passed"
    assert "deleteMyAgentByDev" not in at_verdict                 # nothing retired before the verdict
    after = rig.calls[len(at_verdict):]
    assert [(label, tool) for label, tool, _ in after] == [
        ("sandbox-B", "getBatchAgentBalances"), ("sandbox-B-admin", "tegTreasuryReceive"),
        ("sandbox-B", "deleteMyAgentByDev")]
    receive = after[1][2]
    assert receive["source_agent_did"] == DID_B and receive["amount"] == "12.5"
    assert receive["reason"] == "federation_suite_fixture_retired"
    assert o.throwaways == {"closed": 1, "left": {}} and o.to_dict()["throwaways"] == o.throwaways


def test_red_a_deferred_tests_agents_wait_for_its_judgment():
    rig = _Rig({("sandbox-A", "getBatchAgentBalances"): _balances({DID_A: "3"})})

    async def runner(r):
        pm.record_probe()
        tw.made("sandbox-A", DID_A)

        async def check():
            r.calls.append(("-", "judged", {}))
            return _result(True)
        return rig_mod.DeferredCheck(check=check)

    o = asyncio.run(dec.execute_test(_spec(runner, start_first=True), rig))
    assert o.state == "deferred" and rig.calls == []              # its check still needs the agent
    done = asyncio.run(dec.finish_deferred(o))
    assert done.state == "passed"
    assert _tools(rig) == ["judged"] + RETIRE
    assert done.throwaways == {"closed": 1, "left": {}}


def test_red_what_a_test_retires_itself_is_not_closed_again():
    rig = _Rig({("sandbox-A", "createAgent"): {"did": DID_A, "client_id": "c", "client_secret": "s"},
                ("sandbox-A", "getAgentToken"): {"access_token": "agent-jwt"},
                ("sandbox-A", "getBatchAgentBalances"): _balances({DID_A: "5"})})

    async def runner(r):
        pm.record_probe()
        agent = await clamp._new_agent(r, "probe")                 # names it
        await clamp._cleanup(r, [agent["did"]])                    # and retires it: return, then delete
        return _result(True)

    o = asyncio.run(dec.execute_test(_spec(runner), rig))
    assert o.state == "passed" and _tools(rig).count("deleteMyAgentByDev") == 1
    assert _tools(rig).count("tegTreasuryReceive") == 1 and o.throwaways is None


def test_red_a_deferred_check_that_retires_its_agent_is_seen():
    rig = _Rig({("sandbox-A", "getBatchAgentBalances"): _balances({DID_A: "0"})})

    async def runner(r):
        pm.record_probe()
        tw.made("sandbox-A", DID_A)

        async def check():
            await clamp._cleanup(r, [DID_A])                       # in the runner's Task, not the test's
            return _result(True)
        return rig_mod.DeferredCheck(check=check)

    o = asyncio.run(dec.execute_test(_spec(runner, start_first=True), rig))
    done = asyncio.run(dec.finish_deferred(o))
    assert done.state == "passed" and _tools(rig) == ["getBatchAgentBalances", "deleteMyAgentByDev"]
    assert done.throwaways is None


@pytest.mark.parametrize("passed", [True, False])
def test_the_close_never_costs_a_verdict(passed, caplog):
    rig = _Rig({("sandbox-A", "getBatchAgentBalances"): RuntimeError("TEG down"),
                ("sandbox-A", "deleteMyAgentByDev"): RuntimeError("registry down")})

    async def runner(r):
        pm.record_probe()
        tw.made("sandbox-A", DID_A)
        return _result(passed, None if passed else "the thing did not happen")

    with caplog.at_level("WARNING"):
        o = asyncio.run(dec.execute_test(_spec(runner), rig))
    assert o.state == ("passed" if passed else "failed")
    assert o.failure_detail == (None if passed else "the thing did not happen")
    said = o.throwaways["left"][DID_A]
    assert said[0].startswith("its balance could not be read (RuntimeError: TEG down)")
    assert said[1].startswith("not deleted (RuntimeError: registry down")
    assert DID_A in caplog.text and "left something behind" in caplog.text


def test_the_close_is_bounded(monkeypatch):
    monkeypatch.setattr(tw, "CLOSE_BUDGET_SEC", 0.25)
    rig = _Rig({}, delay=0.1)                                       # each retire takes at least 0.2 s here
    dids = [f"did:theprotocol:{i:08x}-0000-0000-0000-000000000000" for i in range(4)]

    async def runner(r):
        pm.record_probe()
        for d in dids:
            tw.made("sandbox-A", d)
        return _result(True)

    o = asyncio.run(dec.execute_test(_spec(runner), rig))
    assert o.state == "passed"
    unreached = [d for d, said in o.throwaways["left"].items() if said == ["not retired: the close's 0.25 s ran out"]]
    assert o.throwaways["closed"] < 4 and len(unreached) == 4 - o.throwaways["closed"]


def test_a_skipped_tests_agents_are_retired_too():
    rig = _Rig({("sandbox-B", "getBatchAgentBalances"): _balances({DID_B: "1"})})

    async def runner(r):
        tw.made("sandbox-B", DID_B)
        raise rig_mod.PreconditionUnmet("frame A could not resolve the receiver")

    o = asyncio.run(dec.execute_test(_spec(runner), rig))
    assert o.state == "skipped" and _tools(rig) == RETIRE


def test_made_outside_a_run_is_ignored():
    asyncio.run(asyncio.sleep(0))
    tw.made("sandbox-A", DID_A)                                     # a unit test calling a helper directly
    tw.retired(DID_A)
    assert asyncio.run(tw.close(None)) == {"closed": 0, "left": {}}


# ─── the gates: every helper names what it makes, every owner delete returns first ───

_MAKERS = ("createAgent", "theprotocol_createAgent", "/api/v1/agents/spawn")
# kept on purpose, with the reason: its own bond holds the suite developer's membership, which every later run's ballot
# leans on (test_federation_mechanisms_driven._member_voter's docstring); retiring it would bond 300 again each run
_KEPT = {("test_federation_mechanisms_driven.py", "_member_voter")}


def _functions(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _innermost_makers(path: pathlib.Path):
    """(function name, node) for each innermost function that names a maker constant."""
    out = []
    for fn in _functions(path):
        inner = [n for n in ast.walk(fn) if n is not fn and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        own = [n for n in ast.walk(fn) if isinstance(n, ast.Constant) and n.value in _MAKERS
               and not any(n in set(ast.walk(i)) for i in inner)]
        if own:
            out.append((fn.name, fn))
    return out


def _calls(fn, attr: str) -> int:
    return sum(1 for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == attr and isinstance(n.func.value, ast.Name) and n.func.value.id == "throwaways")


def test_red_every_helper_that_makes_an_agent_names_it():
    seen, unnamed = [], []
    for path in sorted((SUITE / "tests").glob("test_*.py")):
        for name, fn in _innermost_makers(path):
            seen.append((path.name, name))
            if (path.name, name) not in _KEPT and _calls(fn, "made") == 0:
                unnamed.append(f"{path.name}:{name}")
    assert len(seen) >= 18, seen                                    # a scan that finds nothing proves nothing
    assert unnamed == [], unnamed


def test_the_ballot_member_is_kept():
    path = SUITE / "tests" / "test_federation_mechanisms_driven.py"
    voter = next(fn for fn in _functions(path) if fn.name == "_member_voter")
    assert _calls(voter, "made") == 0 and _calls(voter, "retire") == 0


def test_red_every_owner_delete_returns_first():
    raw = []
    for path in sorted(SUITE.rglob("*.py")):
        for fn in _functions(path):
            if any(isinstance(n, ast.Constant) and n.value == "deleteMyAgentByDev" for n in ast.walk(fn)):
                raw.append(f"{path.relative_to(SUITE)}:{fn.name}")
    # the two that delete: the module's retire (it returns first) and V0639's _cleanup (its _return_balance first)
    assert sorted(raw) == ["tests/test_ironkey_authority_clamp.py:_cleanup", "throwaways.py:retire"], raw
