"""§BAFIN (2026-10-01) — STAKING_ENABLED / STAKING_REWARDS_ENABLED switch staking, or only its rewards, off per
registry without stranding anyone's units or breaking governance's count of the positions that exist.

What the switches must do (core/staking_gate.py):
  * STAKING_ENABLED off: the rails that START a position (stake, on both rails) answer 403 "staking_disabled: ...";
  * rewards off (either switch): the rails that GROW a reward (claim, estimate, auto-compound, the manual
    distribution) answer 403, every APY-tier read answers no tiers, every APY figure is 0, and the daily
    distributor returns 'skipped' before it opens a database session;
  * unstake and every read keep working on both rails, so a switched-off registry never strands a position;
  * /api/v1/public/registry-config says staking_enabled and staking_rewards_enabled.
Both default ON (unset, or any unknown value), so a node that sets neither is byte-identical.

Behavioural where it is cheap (the gate module itself), structural where an import would need the whole app
(routers are closures over settings; the AST is the honest reader of which dependency a route declares).
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import HTTPException

from agentvault_registry.core import staking_gate as sg

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


# ── the gate itself ─────────────────────────────────────────────────────────────────────────────────────────

def test_default_on_and_only_an_explicit_off_disables(monkeypatch):
    for name, fn in (("STAKING_ENABLED", sg.staking_enabled), ("STAKING_REWARDS_ENABLED", sg.staking_rewards_enabled)):
        monkeypatch.delenv("STAKING_ENABLED", raising=False)
        monkeypatch.delenv("STAKING_REWARDS_ENABLED", raising=False)
        assert fn() is True, name
        for off in ("false", "FALSE", "0", "no", "off", " Off "):
            monkeypatch.setenv(name, off)
            assert fn() is False, (name, off)
        for on in ("true", "1", "yes", "nonsense", ""):
            monkeypatch.setenv(name, on)
            assert fn() is True, f"{name}={on!r} must not switch anything off (a typo never retires a surface)"


def test_rewards_can_go_off_alone_but_never_outlive_staking(monkeypatch):
    monkeypatch.setenv("STAKING_ENABLED", "true"); monkeypatch.setenv("STAKING_REWARDS_ENABLED", "false")
    assert sg.staking_enabled() is True and sg.staking_rewards_enabled() is False, "locks for governance, no rate"
    monkeypatch.setenv("STAKING_ENABLED", "false"); monkeypatch.setenv("STAKING_REWARDS_ENABLED", "true")
    assert sg.staking_enabled() is False and sg.staking_rewards_enabled() is False, "no staking means no reward"


def test_the_dependencies_refuse_with_the_code_word_first(monkeypatch):
    monkeypatch.setenv("STAKING_ENABLED", "false")
    with pytest.raises(HTTPException) as exc:
        sg.require_staking_enabled()
    assert exc.value.status_code == 403
    assert str(exc.value.detail).startswith("staking_disabled:")
    assert "unlocked" in str(exc.value.detail), "the refusal must say that existing positions can still leave"
    # agentvault2-30's tester reads a 403 carrying this phrase as flag-gated (NOT MEASURED), never as a failure
    assert "is not enabled on this registry" in sg.STAKING_DISABLED_SENTENCE
    assert "is not enabled on this registry" in sg.REWARDS_DISABLED_SENTENCE
    with pytest.raises(HTTPException) as exc:
        sg.require_staking_rewards_enabled()
    assert str(exc.value.detail).startswith("staking_disabled:"), "with staking off the reward refusal names the bigger switch"

    monkeypatch.setenv("STAKING_ENABLED", "true"); monkeypatch.setenv("STAKING_REWARDS_ENABLED", "false")
    assert sg.require_staking_enabled() is None  # control: positions still open
    with pytest.raises(HTTPException) as exc:
        sg.require_staking_rewards_enabled()
    assert exc.value.status_code == 403 and str(exc.value.detail).startswith("staking_rewards_disabled:")

    monkeypatch.setenv("STAKING_REWARDS_ENABLED", "true")
    assert sg.require_staking_rewards_enabled() is None  # control: everything on means no refusal


def test_the_disabled_tiers_payload_has_no_rate(monkeypatch):
    monkeypatch.setenv("STAKING_ENABLED", "true"); monkeypatch.setenv("STAKING_REWARDS_ENABLED", "false")
    eng = sg.disabled_tiers_payload()
    assert eng["tiers"] == [] and eng["metadata"]["staking_rewards_enabled"] is False
    assert eng["metadata"]["staking_enabled"] is True
    assert sg.disabled_tiers_payload("list") == []


# ── which routes carry the gate (and which must NOT) ───────────────────────────────────────────────────────

def _route_decorators(path: pathlib.Path) -> dict[tuple[str, str], str]:
    """(METHOD, path) -> the decorator call's source, for every @router.<method>(...) in a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in fn.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router"
                    and dec.args and isinstance(dec.args[0], ast.Constant)):
                out[(dec.func.attr.upper(), dec.args[0].value)] = ast.unparse(dec)
    return out


GATED = {  # (module, route) -> the dependency it must declare
    "routers/staking_enhanced.py": [(("POST", "/stake"), "require_staking_enabled"),
                                    (("POST", "/claim-rewards"), "require_staking_rewards_enabled")],
    "routers/staking_rewards.py": [(("GET", "/estimate/{agent_did}"), "require_staking_rewards_enabled"),
                                   (("POST", "/distribute/manual"), "require_staking_rewards_enabled"),
                                   (("PUT", "/agents/{agent_did}/auto-compound"), "require_staking_rewards_enabled")],
    "routers/teg_integration.py": [(("POST", "/staking/stake"), "require_staking_enabled")],
}
NEVER_GATED = {
    "routers/staking_enhanced.py": [("POST", "/unstake"), ("GET", "/balance"), ("GET", "/my-positions"),
                                    ("GET", "/history")],
    "routers/teg_integration.py": [("POST", "/staking/unstake"), ("GET", "/staking/balance/{agent_did}")],
}


@pytest.mark.parametrize("module,route,dep", [(m, r, d) for m, rs in GATED.items() for r, d in rs])
def test_rails_that_start_a_position_or_grow_a_reward_are_gated(module, route, dep):
    decs = _route_decorators(SRC / module)
    assert route in decs, f"{module} no longer serves {route}"
    assert f"Depends({dep})" in decs[route], decs[route]


@pytest.mark.parametrize("module,route", [(m, r) for m, rs in NEVER_GATED.items() for r in rs])
def test_exit_and_read_rails_are_never_gated(module, route):
    decs = _route_decorators(SRC / module)
    assert route in decs, f"{module} no longer serves {route}"
    assert "require_staking_enabled" not in decs[route], (
        f"{route} must keep working with staking off, or a locked position is stranded")


def _function_source(path: pathlib.Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(fns) == 1, (path.name, name, len(fns))
    return ast.unparse(fns[0])


@pytest.mark.parametrize("module,fn", [
    ("routers/staking_enhanced.py", "get_apy_tiers"),
    ("routers/staking_rewards.py", "get_apy_tiers"),
    ("routers/teg_integration.py", "get_apy_tiers_proxy"),
])
def test_every_tier_read_answers_no_rate_when_off(module, fn):
    body = _function_source(SRC / module, fn)
    assert "if not staking_rewards_enabled()" in body, f"{module}:{fn} would still publish a rate with rewards off"
    # the check must come before any rate is computed or fetched
    first_rate = min(i for i in (body.find("get_dynamic_apy_engine"), body.find("policy_apy_engine"),
                                 body.find("select(StakingApyConfig"), body.find("httpx.AsyncClient")) if i != -1)
    assert body.find("if not staking_rewards_enabled()") < first_rate


def test_the_distributor_skips_before_it_opens_a_session():
    body = _function_source(SRC / "background_tasks/staking_distributor.py", "run_distribution")
    gate = body.find("if not staking_rewards_enabled()")
    assert gate != -1 and gate < body.find("get_db_context()"), "the distributor must not touch the ledger when off"
    assert "return 'skipped'" in body[gate:body.find("get_db_context()")]


def test_registry_config_says_whether_staking_is_live():
    tree = ast.parse((SRC / "main.py").read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "public_registry_config"]
    assert len(fns) == 1
    keys = {}
    for n in ast.walk(fns[0]):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant):
                    keys[k.value] = ast.unparse(v)
    assert "staking_enabled" in keys and "_staking_enabled()" in keys["staking_enabled"], sorted(keys)
    assert "staking_rewards_enabled" in keys and "_staking_rewards_enabled()" in keys["staking_rewards_enabled"]


# ── what the public surfaces say about a rate or a price ───────────────────────────────────────────────────

def test_the_signed_card_publishes_no_staking_rate_while_rewards_are_off(monkeypatch):
    from agentvault_registry.services import registry_card_builder as rcb

    monkeypatch.setenv("STAKING_ENABLED", "false")
    off = rcb._build_policy_block(None)
    assert not [k for k in off["declared_params"] if k.startswith("staking_rewards.")], off["declared_params"]
    assert not [k for k in off["bounded_params"] if k.startswith("staking_rewards.")]
    assert "governance.standard_quorum_percent" in off["declared_params"], "only the staking entry may go"

    monkeypatch.setenv("STAKING_ENABLED", "true"); monkeypatch.setenv("STAKING_REWARDS_ENABLED", "false")
    assert "staking_rewards.max_apy_percent" not in rcb._build_policy_block(None)["declared_params"]

    monkeypatch.delenv("STAKING_ENABLED"); monkeypatch.delenv("STAKING_REWARDS_ENABLED")
    on = rcb._build_policy_block(None)  # control: a node that sets neither card is unchanged
    assert on["declared_params"]["staking_rewards.max_apy_percent"]["value"] == 15.0


def test_the_price_route_names_no_price_and_no_peg():
    """Reads the RETURNED dict only: the docstring quotes the old sentence on purpose, and a gate that reads the
    whole function finds its own documentation first."""
    tree = ast.parse((SRC / "routers/teg_transactions.py").read_text(encoding="utf-8"))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_teg_price"]
    assert len(fn) == 1
    rets = [n.value for n in ast.walk(fn[0]) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    assert len(rets) == 1
    out = {k.value: v for k, v in zip(rets[0].keys, rets[0].values)}
    assert set(out) == {"symbol", "name", "usd", "note", "change_24h", "source"}, "the tester's expected keys stay"
    assert isinstance(out["usd"], ast.Constant) and out["usd"].value is None
    assert isinstance(out["change_24h"], ast.Constant) and out["change_24h"].value is None
    said = ast.unparse(rets[0]).lower()
    assert "pegged" not in said and "pre-market" not in said and "usd" not in said.replace("'usd': none", "")
