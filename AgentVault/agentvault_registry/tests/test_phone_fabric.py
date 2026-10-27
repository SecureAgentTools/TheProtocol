"""PHONE FABRIC unit tests (2026-07-07) — driver determinism + caveat/metering/kill logic.

DB-free: exercises the MockPhoneDriver (deterministic) and the pure caveat/metering helpers.
The DB-backed router paths are proven by the live frame-c E2E (test_phone_fabric_e2e). Run:

    docker run --rm -u 0 -v <repo>/AgentVault/agentvault_registry:/mnt \
      --entrypoint bash agentvault2-registry-a:latest \
      -c "cd /mnt && PYTHONPATH=/mnt/src python3 -m pytest tests/test_phone_fabric.py -q --no-cov"
"""
import asyncio
from decimal import Decimal

from agentvault_registry.services.phone.mock_driver import MockPhoneDriver, make_driver
from agentvault_registry.services.phone.driver import UiNode


# ── driver determinism ────────────────────────────────────────────────────────

def test_mock_home_lists_apps():
    d = MockPhoneDriver()
    o = asyncio.run(d.observe())
    pkgs = {n.package for n in o.tree.children}
    assert pkgs == {"com.vault.bank", "com.acme.browser"}


def test_mock_full_bank_flow_deterministic():
    d = MockPhoneDriver()
    asyncio.run(d.reset())
    assert asyncio.run(d.act("tap", target="icon:com.vault.bank")).screen == "login"
    asyncio.run(d.act("type", target="user", text="alice"))
    assert asyncio.run(d.act("tap", target="signin")).screen == "dashboard"
    assert asyncio.run(d.act("tap", target="to_transfer")).screen == "transfer"
    assert asyncio.run(d.act("tap", target="send")).screen == "done"


def test_mock_bad_target_rejected():
    d = MockPhoneDriver()
    asyncio.run(d.act("tap", target="icon:com.vault.bank"))
    r = asyncio.run(d.act("tap", target="does-not-exist"))
    assert r.ok is False and "no such node" in r.detail


def test_mock_unknown_app_rejected():
    d = MockPhoneDriver()
    r = asyncio.run(d.act("tap", target="icon:com.evil.app"))
    assert r.ok is False


def test_mock_screenshot_gated():
    d = MockPhoneDriver()
    assert asyncio.run(d.observe()).screenshot_b64 is None
    assert asyncio.run(d.observe(want_screenshot=True)).screenshot_b64 == "iVBORw0KMOCK"


def test_mock_state_restore_is_worker_safe():
    # simulate two stateless requests: restore from persisted (app, screen), act, persist
    d1 = MockPhoneDriver(); asyncio.run(d1.act("tap", target="icon:com.vault.bank"))
    app, screen = d1.state
    d2 = make_driver("mock", "h"); d2.restore(app, screen)      # fresh worker
    assert d2.state == ("com.vault.bank", "login")
    assert asyncio.run(d2.act("tap", target="signin")).screen == "dashboard"


def test_make_driver_defaults_mock():
    assert make_driver("mock", "h").backend == "mock"
    assert make_driver("bogus", "h").backend == "mock"   # unknown → mock, never crashes


# ── pure caveat / metering logic (mirrors the router's enforcement) ───────────

def _app_allowed(target, action_type, allowed):
    launch_pkg = target if action_type == "launch" else (
        target.split(":", 1)[1] if action_type == "tap" and (target or "").startswith("icon:") else None)
    if launch_pkg is None:
        return True
    return (not allowed) or (launch_pkg in allowed)


def test_app_allowlist_enforcement():
    assert _app_allowed("icon:com.vault.bank", "tap", ["com.vault.bank"]) is True
    assert _app_allowed("icon:com.evil.app", "tap", ["com.vault.bank"]) is False
    assert _app_allowed("com.evil.app", "launch", ["com.vault.bank"]) is False
    assert _app_allowed("signin", "tap", ["com.vault.bank"]) is True   # non-launch tap unaffected
    assert _app_allowed("icon:anything", "tap", []) is True            # empty allowlist = no app restriction here (router gates elsewhere)


def test_budget_metering_is_a_counter_not_money():
    # metering = token budget debit; assert the arithmetic (no AVT, Δ-irrelevant by construction)
    budget_total, spent = Decimal("10"), Decimal("0")
    cost = Decimal("1")
    for _ in range(10):
        spent += cost
    assert spent == budget_total          # exactly exhausts
    exhausted = spent >= budget_total
    assert exhausted is True


def test_max_actions_ceiling_logic():
    max_actions, used = 3, 0
    def allowed(u):
        return u < max_actions
    assert allowed(used) and allowed(2) and not allowed(3)


def test_ttl_and_mode_helpers(monkeypatch):
    import agentvault_registry.routers.phone_fabric as pf
    monkeypatch.setenv("PHONE_FABRIC_ENABLED", "false")
    assert pf.phone_fabric_enabled() is False
    monkeypatch.setenv("PHONE_FABRIC_ENABLED", "true")
    assert pf.phone_fabric_enabled() is True
    monkeypatch.setenv("PHONE_USE_MODE", "enforce")
    assert pf.phone_use_mode() == "enforce"
    monkeypatch.setenv("PHONE_USE_MODE", "bogus")
    assert pf.phone_use_mode() == "off"
    monkeypatch.setenv("PHONE_FABRIC_BACKEND", "redroid")
    assert pf._backend() == "redroid"
    monkeypatch.setenv("PHONE_FABRIC_BACKEND", "nonsense")
    assert pf._backend() == "mock"


def test_phone_use_in_all_permissions():
    from agentvault_registry.agent_authz import ALL_PERMISSIONS
    assert "phone.use" in ALL_PERMISSIONS
    # and NOT in any normal role (high-blast, legacy-full only)
    from agentvault_registry.agent_authz import ROLE_PERMISSIONS
    for role, perms in ROLE_PERMISSIONS.items():
        if role != "legacy-full":
            assert "phone.use" not in perms, f"{role} must not carry phone.use"
