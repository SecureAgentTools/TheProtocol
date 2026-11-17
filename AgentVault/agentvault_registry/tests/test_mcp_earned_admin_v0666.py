"""V0666 Tests package A (gwo_0d88f8965ddc8d5c2566fa6c, session-tester): admin tools the V0664 pair still read
refusal-only although a success leg for each was already written. Each leg asked a different question from the one the
product answers, so it never reached its success path (scratchpad/tests666/SPLIT_2026-11-15.md):

1. forceEmailVerify: the runner registers its throwaway developer at `<name>@throwaway-pl.example.com`
   (test_flow_mcp_lifecycle._mint_throwaway_developer, a subdomain of the reserved example.com), and
   earned_ad_developers._unverified_own accepted only an address ending `@example.com`; its own test used that
   shape, never the runner's. Every pair run read "carries no reserved example.com address".
2. updateSlashOrder: the product treats a step with no `enabled` key as enabled (services/slash_order.enabled), and the
   factory default order (crud_enforcement.DEFAULT_POLICY_JSON) carries no such key on any step; earned_refusal_slice1
   ._changed asked for `enabled is True`, so on a frame running the default order it found no step to move ("no
   enabled bond, stake or liquid step"). Its fixture spelled `enabled: true` on every step.
3. triggerDiagnosticAction (in test_mcp_admin_lifecycles_v0561_v0562.py beside its siblings).

Red on 146acef6c (v0664/cut-6).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import pytest

from agentvault_registry.api_tests.contracts import earned_ad_developers as DEVS
from agentvault_registry.api_tests.contracts import earned_agent_public as EAP
from agentvault_registry.api_tests.contracts import earned_refusal_slice1 as S
from agentvault_registry.crud import crud_enforcement
from agentvault_registry.services import slash_order


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                   "structuredContent": obj}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


class _Bag:
    developer_jwt, developer_id = "dev-jwt", 1


def _world(monkeypatch, env="sandbox"):
    state = {"verified": True, "writes": []}

    async def detail(bag, parse, dev_id):
        return True, {"is_verified": state["verified"]}, "200"

    async def db_write(bag, sql, params):
        state["writes"].append((sql, dict(params)))
        state["verified"] = False
        return 1, None

    async def rpc(tool, args, jwt="", timeout=20):
        assert tool == "theprotocol_getPublicRegistryConfig"
        return True, _body({"environment": env}), "200"
    monkeypatch.setattr(DEVS, "_dev_detail", detail)
    monkeypatch.setattr(EAP, "_db_write", db_write)
    return state, rpc


# ── 1. forceEmailVerify on the address the runner really gives its throwaway ───────────────────────────────────────

RUNNER_DEV = {"email": "mcp-throwaway-developer-admin-1794716000-a1b2c3@throwaway-pl.example.com",
              "name": "mcp-throwaway-developer-admin-1794716000-a1b2c3"}


def test_the_runners_own_throwaway_address_is_the_reserved_domain(monkeypatch):
    state, rpc = _world(monkeypatch)
    why = asyncio.run(DEVS._unverified_own(rpc, _parse, _Bag(), RUNNER_DEV, 42))
    assert why is None, why
    assert len(state["writes"]) == 1 and state["writes"][0][1] == {"id": 42, "email": RUNNER_DEV["email"]}


@pytest.mark.parametrize("email", [
    "someone@mail.example.org",                              # a real-looking address outside the reserved name: never
    "mcp-throwaway-x@example.com.evil.dev",                  # the reserved name inside another domain: never
    "mcp-throwaway-x@notexample.com",                        # a domain that only ends in the same letters: never
])
def test_an_address_outside_the_reserved_domain_is_never_set_unverified(monkeypatch, email):
    state, rpc = _world(monkeypatch)
    why = asyncio.run(DEVS._unverified_own(rpc, _parse, _Bag(), {**RUNNER_DEV, "email": email}, 42))
    assert why and "example.com" in why and state["writes"] == []


def test_the_runner_mints_on_the_domain_the_leg_accepts():
    import inspect
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as runner
    src = inspect.getsource(runner._mint_throwaway_developer)
    assert '@throwaway-pl.example.com"' in src
    assert DEVS._reserved_example_address("a@throwaway-pl.example.com")


# ── 2. updateSlashOrder on the factory default order ───────────────────────────────────────────────────────────────

def test_the_factory_default_order_has_a_step_to_move_by_one():
    default = crud_enforcement.DEFAULT_POLICY_JSON["slash_waterfall"]
    assert all("enabled" not in s for s in default), "the default order spells no enabled key (the case under test)"
    new, what = S._changed(default)
    assert new is not None, "a frame on the default order has a step the leg can change"
    assert what == "bond 100 -> 99"
    assert [s.get("max_percent") for s in default] == [100, 100, 100], "the original is not changed in place"


def test_a_switched_off_step_is_never_the_one_moved_and_the_rule_is_the_products():
    order = [{"source": "bond", "max_percent": 100, "enabled": False}, {"source": "stake", "max_percent": 40},
             {"source": "liquid", "max_percent": 100}]
    new, what = S._changed(order)
    assert what == "stake 40 -> 39" and new[0] == order[0]
    for step in order:
        assert S._step_enabled(step) is slash_order.enabled(step)
    assert S._changed([{"source": "bond", "max_percent": 100, "enabled": False}]) == (None, "")
