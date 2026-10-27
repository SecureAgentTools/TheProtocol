"""§MCPTEST30 V0640 (agentvault2-aa, 2026-10-24): the API tester's broadcast row sends a notice to its own developer only.

base withholds a broadcast send ("mass-broadcast send"), but a row's AAA+ contract runs before base's gate, and
contracts/misc_admin.CreateBroadcast composed a broadcast to EVERY developer that nothing retracted: "AAA+ contract test
broadcast" #1257, #1259, #1269 and #1279 on sbx-alpha (2026-10-18/19), live and copied to every peer (agentvault2-66's
census of the copies). The row runs no contract now; it sends the catalog's body, a direct notice to the sweep's own
throwaway developer (__SWEEP_DEVELOPER_ID__; a direct notice is never copied to a peer), and base lets it through only
when the router verified that, for that one call. Every test_red_* fails on d0363c18 (the control).
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests import base as B
from agentvault_registry.api_tests.contracts import misc_admin  # noqa: F401  (registers CreateBroadcast)
from agentvault_registry.api_tests.core.contract import get_contract
from agentvault_registry.routers.admin_broadcast import BroadcastCreate


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


def _router(monkeypatch, **values):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(**values))
    return R


def test_red_the_broadcast_row_runs_no_contract(monkeypatch):
    R = _router(monkeypatch)
    assert get_contract("POST", "/admin/broadcasts") is not None      # the contract is still there...
    assert R._contract_for("POST", "/admin/broadcasts") is None       # ...and the row does not run it
    assert R._contract_for("GET", "/admin/broadcasts") is not None    # control: the list row keeps its own


def test_red_its_body_is_a_direct_notice_to_the_sweeps_own_developer(monkeypatch):
    R = _router(monkeypatch, target_dev_id="9001", target_dev_own=True)
    body = R.request_bodies.get_body("/admin/broadcasts")
    assert body["target_developer_id"] == "__SWEEP_DEVELOPER_ID__"
    resolved = asyncio.run(R._resolve_body_markers(json.loads(json.dumps(body)), "admin-token"))
    sent = BroadcastCreate(**resolved)                                  # the route's own schema
    assert sent.target_developer_id == 9001 and sent.target_org_id is None and sent.send_email is False


def test_red_the_row_is_the_sweeps_own_only_for_its_own_developer(monkeypatch):
    R = _router(monkeypatch, target_dev_id="9001", target_dev_own=True)
    own = {"title": "t", "body": "b", "target_developer_id": 9001}
    assert R._mark_own_notice("POST", "/admin/broadcasts", own) is True
    assert B._classify_destructive("POST", "/admin/broadcasts") == ""
    for body in ({**own, "target_developer_id": 9002},                   # another developer
                 {**own, "target_developer_id": "__SWEEP_DEVELOPER_ID__"},   # the marker unresolved
                 {"title": "t", "body": "b"},                            # everyone
                 {**own, "target_org_id": "org-1"},                      # an organization
                 None):
        assert R._mark_own_notice("POST", "/admin/broadcasts", body) is False
        assert B._classify_destructive("POST", "/admin/broadcasts").startswith("mass-broadcast")   # no earlier verdict
    R2 = _router(monkeypatch, target_dev_id="9001")                     # an id the sweep did not make
    assert R2._mark_own_notice("POST", "/admin/broadcasts", own) is False


def test_control_base_withholds_an_unverified_broadcast_send():
    B._VERIFIED_SWEEP_OWN.clear()
    assert B._classify_destructive("POST", "/admin/broadcasts").startswith("mass-broadcast")
    assert B._classify_destructive("GET", "/admin/broadcasts") == ""
