"""§MEMBERSHIP (2026-10-02) — the rewards switch reaches every rail that showed a rate or paid a reward.

agentvault2-15 found, read-only against V0549, the places where STAKING_REWARDS_ENABLED=false still let a rate or a
reward through, while the BaFin letter says no rate is published and no reward is paid:
  1. the staking history returned each position's stored rate;
  2. the owner's re-drive of an undelivered staking reward paid it regardless;
  3. /staking/status printed staking as always on, a 7-day cooldown nothing enforces and daily rewards;
  4. the legacy /teg/rewards/claim proxy had no switch (its ledger handler credits from no account);
  5. every TokensStaked event said 7 days, the helper's default.
Structural tests, each with a control that must fail on the planted defect.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "agentvault_registry"


def _src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def _ungated_rates(source: str) -> list:
    """Every float(<x>.apy_rate) that is NOT the body of `... if staking_rewards_enabled() else ...`."""
    tree = ast.parse(source)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float"
                and node.args and isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "apy_rate"):
            p = parents.get(node)
            gated = (isinstance(p, ast.IfExp) and p.body is node and isinstance(p.test, ast.Call)
                     and isinstance(p.test.func, ast.Name) and p.test.func.id == "staking_rewards_enabled")
            if not gated:
                bad.append(node.lineno)
    return bad


@pytest.mark.parametrize("rel", sorted(str(p.relative_to(SRC)) for p in (SRC / "routers").glob("*.py")))
def test_no_router_returns_a_stored_rate_without_the_switch(rel):
    assert _ungated_rates(_src(rel)) == [], f"{rel}: a stored rate leaves without the rewards switch"


def test_the_rate_scanner_can_fail():
    assert _ungated_rates('x = {"apy": float(stake.apy_rate)}\n') == [1]
    assert _ungated_rates('x = {"apy": float(stake.apy_rate) if staking_rewards_enabled() else 0.0}\n') == []
    assert _ungated_rates('x = {"apy": float(stake.apy_rate) if other() else 0.0}\n') == [1]


def _func_source(rel: str, name: str) -> str:
    src = _src(rel)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    pytest.fail(f"{name} is missing from {rel}")


def test_the_reward_redrive_refuses_while_rewards_are_off():
    body = _func_source("routers/developers.py", "redrive_reward")
    assert "_rewards_on()" in body and "fund_reward_via_waterfall" in body
    assert body.index("_rewards_on()") < body.index("fund_reward_via_waterfall"), \
        "the switch must be read before any money can move"
    assert "HTTP_403_FORBIDDEN, _REWARDS_OFF" in body


def test_the_legacy_claim_proxy_carries_the_rewards_dependency():
    src = _src("routers/teg_integration.py")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "claim_rewards_proxy")
    deco = " ".join(ast.get_source_segment(src, d) or "" for d in fn.decorator_list)
    assert "require_staking_rewards_enabled" in deco


def test_staking_status_reports_the_switches_not_literals():
    body = _func_source("routers/staking_enhanced.py", "get_staking_status")
    assert '"staking_enabled": True' not in body and '"staking_enabled": staking_enabled()' in body
    assert '"unstake_cooldown_days": 7' not in body
    assert '"staking_rewards_enabled": staking_rewards_enabled()' in body


def _stake_event_calls(source: str) -> list:
    """The add_task(...) calls that emit "stake.completed", as {keyword: source} dicts."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_task":
            kws = {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg}
            if kws.get("event_type") == "'stake.completed'":
                out.append(kws)
    return out


def test_the_stake_event_carries_the_real_lock_period():
    calls = _stake_event_calls(_src("routers/staking_enhanced.py"))
    assert calls, "no add_task emits stake.completed: the scan lost its subject"
    for kws in calls:
        assert kws.get("lock_period_days") == "stake.lock_period_days", kws


def test_the_stake_event_scan_can_fail():
    planted = "background_tasks.add_task(emit, event_type='stake.completed', stake_id=stake.id)\n"
    assert _stake_event_calls(planted) == [{"event_type": "'stake.completed'", "stake_id": "stake.id"}]
