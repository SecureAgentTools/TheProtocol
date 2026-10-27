"""§TRUSTCHAIN P4.4 (2026-09-12) — SUSPENDED acts; RESTRICTED withholds; observe reports.

§TRUSTPOLICY named it: `suspend_below` and `restrict_below` did the same thing at the ingest gate,
because the quarantine rail had no compliance rows to act on. With P4.2's baseline rows the sweep
can act. Measured before wiring: a compliance quarantine is recorded, notified and listed, and
withholds nothing economic (no money or ingest rail reads `federation_status`); the licence's
`suspended` has ONE admin writer by design. So the wiring is: enforce + SUSPENDED -> the monitor's
`trigger_quarantine` with a `peer_trust:` marker; recovery (or the frame no longer enforcing) ->
`lift_quarantine`, ONLY for a quarantine that marker identifies as trust's own.

Pinned: the pure planner's table; the applier's two calls and its refusal to act without a row;
the sweep planning on every pass and applying through the applier (AST). RED on the pre-change
tree (`TRUSTCHAIN_SRC`).
"""
from __future__ import annotations

import ast
import os
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("TRUSTCHAIN_SRC", HERE.parent / "src" / "agentvault_registry"))


def _v(state: str, mode: str, **kw):
    from agentvault_registry.services import peer_trust_policy as ptp
    return ptp.PeerTrustVerdict(
        state=state, reason=kw.get("reason", "r"), discount=kw.get("discount", 0.2),
        interactions=kw.get("interactions", 24), threshold_key=kw.get("threshold_key", "peer_trust.suspend_below"),
        threshold=kw.get("threshold", 0.30), mode=mode,
    )


# ── the planner ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("state,mode,status,reason,expected", [
    ("suspended", "enforce", "federated", None, "quarantine"),
    ("suspended", "observe", "federated", None, None),                       # observe: reported only
    ("suspended", "enforce", "quarantined", "peer_trust:x", None),           # already ours: hold
    ("suspended", "enforce", "quarantined", "drift poller", None),           # somebody else's: leave it
    ("suspended", "enforce", "blacklisted", None, None),
    ("suspended", "enforce", None, None, None),                              # no row yet: nothing to act on
    ("restricted", "enforce", "federated", None, None),                      # ingest gate is the whole action
    ("warn", "enforce", "federated", None, None),
    ("ok", "enforce", "quarantined", "peer_trust:x", "lift"),                # recovered: lift ours
    ("unmeasured", "enforce", "quarantined", "peer_trust:x", "lift"),
    ("ok", "observe", "quarantined", "peer_trust:x", "lift"),                # frame stopped enforcing: release
    ("ok", "enforce", "quarantined", "Policy hash mismatch detected by compliance poller", None),  # never lift an admin's or the poller's
    ("ok", "enforce", "federated", None, None),
])
def test_plan_action_table(state, mode, status, reason, expected):
    from agentvault_registry.services import peer_trust_policy as ptp
    assert ptp.plan_action(_v(state, mode), status, reason) == expected


# ── the applier ────────────────────────────────────────────────────────────────
def _db_with(row):
    scalar = MagicMock(); scalar.scalar_one_or_none.return_value = row
    db = MagicMock(); db.execute = AsyncMock(return_value=scalar)
    return db


@pytest.mark.asyncio
async def test_apply_quarantine_names_the_policy_and_the_number_and_tags_it():
    from agentvault_registry.services import peer_trust_policy as ptp
    peer = SimpleNamespace(id=9, name="throwaway")
    row = SimpleNamespace(policy_hash="abc", federation_status="federated", quarantine_reason=None)
    monitor = MagicMock(); monitor.trigger_quarantine = AsyncMock(); monitor.lift_quarantine = AsyncMock()
    with patch("agentvault_registry.services.federation_compliance_monitor.get_federation_compliance_monitor",
               return_value=monitor):
        out = await ptp._apply_trust_action(_db_with(row), peer, _v("suspended", "enforce", discount=0.1923), "quarantine")
    assert out["applied"] is True
    kw = monitor.trigger_quarantine.await_args.kwargs
    assert kw["peer_id"] == 9 and kw["grace_hours"] == 0 and kw["admin_email"] == ptp.ACTOR
    assert kw["reason"].startswith(ptp.TRUST_QUARANTINE_MARKER)
    assert "peer_trust.suspend_below" in kw["reason"] and "0.1923" in kw["reason"] and "24" in kw["reason"]
    monitor.lift_quarantine.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_lift_keeps_the_baseline_hash():
    from agentvault_registry.services import peer_trust_policy as ptp
    peer = SimpleNamespace(id=9, name="throwaway")
    row = SimpleNamespace(policy_hash="d2f2040f", federation_status="quarantined", quarantine_reason="peer_trust:x")
    monitor = MagicMock(); monitor.trigger_quarantine = AsyncMock(); monitor.lift_quarantine = AsyncMock()
    with patch("agentvault_registry.services.federation_compliance_monitor.get_federation_compliance_monitor",
               return_value=monitor):
        out = await ptp._apply_trust_action(_db_with(row), peer, _v("ok", "enforce", discount=0.86), "lift")
    assert out["applied"] is True
    kw = monitor.lift_quarantine.await_args.kwargs
    assert kw["new_policy_hash"] == "d2f2040f", "a lift must not move the baseline the drift check compares against"
    assert kw["admin_email"] == ptp.ACTOR
    monitor.trigger_quarantine.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_without_a_row_does_nothing_and_says_why():
    from agentvault_registry.services import peer_trust_policy as ptp
    peer = SimpleNamespace(id=9, name="throwaway")
    monitor = MagicMock(); monitor.trigger_quarantine = AsyncMock()
    with patch("agentvault_registry.services.federation_compliance_monitor.get_federation_compliance_monitor",
               return_value=monitor):
        out = await ptp._apply_trust_action(_db_with(None), peer, _v("suspended", "enforce"), "quarantine")
    assert out["applied"] is False and out["why"] == "no_compliance_row"
    monitor.trigger_quarantine.assert_not_awaited()


# ── the sweep plans every pass and applies through the applier ─────────────────
def test_sweep_plans_and_applies_by_ast():
    tree = ast.parse((SRC / "services" / "peer_trust_policy.py").read_text(encoding="utf-8"))
    sweep = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "sweep")
    names = {n.func.id for n in ast.walk(sweep) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "plan_action" in names, "sweep does not plan an action"
    assert "_apply_trust_action" in names, "sweep does not apply the action"
    # planning must not be nested under the transition test: a mode flip has no transition
    for n in ast.walk(sweep):
        if isinstance(n, ast.If):
            t = ast.dump(n.test)
            if "prev" in t and "verdict" in t:
                inner = {c.func.id for c in ast.walk(n) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
                assert "plan_action" not in inner, "plan_action sits under the transition branch"


def test_transition_event_declares_the_action():
    src = (SRC / "services" / "peer_trust_policy.py").read_text(encoding="utf-8")
    assert '"action":' in src and '"action_applied":' in src
