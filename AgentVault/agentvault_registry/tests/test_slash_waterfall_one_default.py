"""§BATCH0911 item 2a — the slash waterfall has ONE default, and the engine reads it.

`enforcement_engine._slash_waterfall` held a second inline literal of the factory waterfall
(`policy.get("slash_waterfall") or [bond, stake, liquid]`). Measured on V0346 before the change:

  * the literal equals `DEFAULT_POLICY_JSON["slash_waterfall"]` byte for byte (so removing it is inert);
  * it is REACHABLE: `validate_document({"slash_waterfall": None})` returns [] (admission skips a null),
    `resolve()` lets the stored null replace the default, and the engine's `or` then fires;
  * in that state `explain("slash_waterfall")` reports the frame as running the DEFAULT, so the readout
    and the engine agreed only because the two copies happened to be equal.

A money path: under ENFORCEMENT_SLASH_MODE=enforce the order decides what a slash drains (live on EU
and ASIA). The fallback stays, because a corrupt row must not silently switch off the money half of
enforcement, but it is now the SAME object the readout reports, and it says so when it fires.

RED control: run this file against the pre-change tree (`REPBOND_SRC=<git archive HEAD>`); the
no-second-copy test and the follows-the-one-default test must both fail.
"""
from __future__ import annotations

import ast
import copy
import os
import pathlib
import sys
import types
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ["REPBOND_SRC"]) if os.environ.get("REPBOND_SRC") else HERE.parent / "src" / "agentvault_registry"


@pytest.fixture(scope="module")
def mods():
    sys.path.insert(0, str(SRC.parent))
    from agentvault_registry.services import enforcement_engine as ee
    from agentvault_registry.services import reputation_bond as rb
    from agentvault_registry.crud import crud_enforcement as ce
    return types.SimpleNamespace(ee=ee, rb=rb, ce=ce)


def _waterfall_literals(tree: ast.AST):
    """Every list literal whose elements are dicts carrying a "source" key: the shape of a waterfall."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts and all(isinstance(e, ast.Dict) for e in node.elts):
            keys = {k.value for e in node.elts for k in e.keys if isinstance(k, ast.Constant)}
            if "source" in keys:
                found.append(node.lineno)
    return found


def test_the_engine_holds_no_second_copy_of_the_waterfall():
    tree = ast.parse((SRC / "services" / "enforcement_engine.py").read_text(encoding="utf-8"))
    lines = _waterfall_literals(tree)
    assert not lines, (
        f"enforcement_engine.py carries a waterfall literal at line(s) {lines}: the default lives in "
        f"crud_enforcement.DEFAULT_POLICY_JSON and nowhere else"
    )
    # the instrument itself must be able to see one: the factory default IS such a literal
    ce_tree = ast.parse((SRC / "crud" / "crud_enforcement.py").read_text(encoding="utf-8"))
    assert _waterfall_literals(ce_tree), "the literal detector found nothing where the default lives"


class _Emitter:
    """Records what it RECEIVED; the doubles gate (test_doubles_assert_receipt) reads the name."""
    def __init__(self):
        self.received = []

    async def emit(self, **kw):
        self.received.append(kw)


def _agent(staked="50", liquid="1000"):
    return types.SimpleNamespace(did="did:theprotocol:test:wf", staked_balance=Decimal(staked),
                                 liquid_balance=Decimal(liquid))


def _action(amount="100"):
    return types.SimpleNamespace(id=4242, agent_did="did:theprotocol:test:wf", amount=Decimal(amount),
                                 action_type="slash_liquid", escalation_level=2)


async def _plan(mods, monkeypatch, policy, bond_amount="10"):
    """Run the waterfall in SHADOW (computes and reports, moves nothing) and return the plan it reports."""
    async def _policy(db):
        return policy

    async def _load_bond(db, did):
        return types.SimpleNamespace(amount=Decimal(bond_amount), status="locked")

    em = _Emitter()
    monkeypatch.setattr(mods.rb, "policy_json", _policy)
    monkeypatch.setattr(mods.rb, "load_bond", _load_bond)
    monkeypatch.setattr(mods.ee, "get_event_emitter", lambda: em)
    handled = await mods.ee.EnforcementEngine()._slash_waterfall(None, _agent(), _action(), mode="shadow")
    assert handled is False, "shadow must fall through to the cache-only branches"
    # shadow must emit exactly one event, and it must be the PLANNED one (never Applied)
    assert [c.get("event_type") for c in em.received] == ["EnforcementSlashWaterfallPlanned"], em.received
    return em.received[0]["data"]["plan"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, [], "<absent>"])
async def test_a_frame_with_no_waterfall_drains_in_the_one_default_order(mods, monkeypatch, stored):
    """The discriminating half: change the ONE default and the engine must follow it. A second copy
    cannot follow, so the pre-change tree drains bond -> stake -> liquid here whatever the default says."""
    patched = [{"source": "liquid", "max_percent": 30},
               {"source": "stake", "max_percent": 100},
               {"source": "bond", "max_percent": 100}]
    monkeypatch.setitem(mods.ce.DEFAULT_POLICY_JSON, "slash_waterfall", patched)
    policy = {} if stored == "<absent>" else {"slash_waterfall": copy.deepcopy(stored)}
    plan = await _plan(mods, monkeypatch, policy)
    assert [p["source"] for p in plan] == ["liquid", "stake", "bond"], plan
    assert [p["absorbed"] for p in plan] == ["30", "50", "10"], plan


@pytest.mark.asyncio
async def test_the_shipped_default_order_is_unchanged(mods, monkeypatch):
    """Byte-inert: with the factory default as shipped, a frame with no waterfall drains exactly as before."""
    plan = await _plan(mods, monkeypatch, {"slash_waterfall": None})
    assert [p["source"] for p in plan] == ["bond", "stake", "liquid"]
    assert [p["absorbed"] for p in plan] == ["10", "50", "40"]


@pytest.mark.asyncio
async def test_a_declared_waterfall_is_followed_not_the_default(mods, monkeypatch):
    """Control the other way: the fallback must never override an order the frame actually declared."""
    plan = await _plan(mods, monkeypatch, {"slash_waterfall": [{"source": "stake", "max_percent": 100},
                                                               {"source": "bond", "max_percent": 100}]})
    assert [p["source"] for p in plan] == ["stake", "bond"]
    assert [p["absorbed"] for p in plan] == ["50", "10"]


def test_admission_refuses_an_empty_waterfall_and_passes_a_null(mods):
    """Pins why the fallback is reachable at all: an empty list is refused, a null is not."""
    assert mods.ce.validate_policy_json({"slash_waterfall": []})
    assert mods.ce.validate_policy_json({"slash_waterfall": None}) == []
