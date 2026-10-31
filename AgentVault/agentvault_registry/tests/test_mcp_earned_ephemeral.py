"""§MCPTEST30 (V0649, agentvault2-d3): earn_ephemeral_licences, the federation licence tools on a licence of the run's
own, only where the target is torn down after its run (MCP_TESTER_EPHEMERAL_TARGET, the nightly and proof pairs).

Offline: a scripted admin bridge keeps licences the way routers/federation_licenses.py does (generate active, suspend,
reinstate, revoke with its reason, delete, a detail that answers 404 for a licence that is gone). RED control: before
V0649 the lifecycle does not exist (the import fails), and every licence tool's only row is a refusal or a skip.
"""
from __future__ import annotations

import asyncio
import itertools
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_ad_ephemeral as eph
from agentvault_registry.api_tests.contracts.earned_fixtures import effect_name


class _Licences:
    """The admin bridge, answering as the licence routes answer."""

    def __init__(self, *, stale_suspend: bool = False, refuse: Optional[str] = None, keep_listing: bool = False,
                 refuse_once: bool = False):
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.stale_suspend, self.refuse, self.keep_listing = stale_suspend, refuse, keep_listing
        self.refuse_once = refuse_once
        self._n = itertools.count(1)

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        ok, result, code = self._answer(tool, dict(args))
        return ok, {"result": result}, code

    def _answer(self, tool: str, a: Dict[str, Any]) -> Tuple[bool, Any, str]:
        if tool == self.refuse:
            if self.refuse_once:
                self.refuse = None
            return False, {"_text": "Error: HTTP 500: the scripted refusal"}, "500"
        lid = str(a.get("license_id") or "")
        if tool == eph.GENERATE:
            lid = f"lic-{next(self._n)}"
            self.rows[lid] = {"id": lid, "operator_name": a["operator_name"], "operator_did": a["operator_did"],
                              "status": "active", "revoked_reason": None}
            return True, {"license_id": lid, "license_key": "avfl_secret_never_kept", "status": "active"}, "201"
        if tool == eph.LIST:
            return True, [dict(r) for r in self.rows.values()], "200"
        row = self.rows.get(lid)
        if row is None:
            return False, {"_text": f"Error: HTTP 404: Federation license not found: {lid}"}, "404"
        if tool == eph.DETAIL:
            return True, dict(row), "200"
        if tool == eph.SUSPEND:
            if not self.stale_suspend:
                row["status"] = "suspended"
            return True, dict(row, status="suspended"), "200"
        if tool == eph.REINSTATE:
            row["status"] = "active"
            return True, dict(row), "200"
        if tool == eph.REVOKE:
            row["status"], row["revoked_reason"] = "revoked", a.get("reason")
            return True, dict(row), "200"
        if tool == eph.DELETE:
            if not self.keep_listing:
                self.rows.pop(lid, None)
            else:
                row["status"] = "revoked"
            return True, {"success": True}, "204"
        return False, {"_text": f"Error: HTTP 404: no such tool {tool}"}, "404"


def _parse(body: Dict[str, Any]) -> Any:
    return body.get("result") if isinstance(body, dict) else {}


def _bag(bridge: Any) -> Any:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    bag.rpc_admin = bridge                 # type: ignore[attr-defined]
    bag.admin_lifecycle_rows = {}          # type: ignore[attr-defined]
    return bag


async def _no_public(tool: str, args: dict, jwt: str = "", timeout: int = 20):
    raise AssertionError(f"the licence lifecycle called {tool} on the public bridge")


def _run(bridge: Any) -> Dict[str, dict]:
    outcomes: Dict[str, dict] = {}
    asyncio.run(eph.lifecycle_earn_ephemeral_licences(_no_public, _parse, _bag(bridge), outcomes))
    return outcomes


def test_it_is_registered_with_the_earned_admin_lifecycles():
    assert "earn_ephemeral_licences" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]


def test_a_standing_frame_asks_nothing_and_says_why(monkeypatch):
    monkeypatch.delenv(eph.EPHEMERAL_ENV, raising=False)
    bridge = _Licences()
    out = _run(bridge)
    assert bridge.calls == []
    assert sorted(out) == sorted(effect_name(t) for t in eph.LICENCE_TOOLS)
    for row in out.values():
        assert not row.get("healthy") or row.get("skip_reason"), row
        assert eph.EPHEMERAL_ENV in str(row.get("skip_reason")), row


@pytest.mark.parametrize("value", ["false", "0", "", "no"])
def test_only_a_true_flag_opens_it(monkeypatch, value):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, value)
    assert not eph.ephemeral_target()


def test_an_ephemeral_target_earns_all_five_and_leaves_nothing(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Licences()
    out = _run(bridge)
    for tool in eph.LICENCE_TOOLS:
        row = out[effect_name(tool)]
        assert row["healthy"] and not row.get("skip_reason") and not row.get("fail_reason"), (tool, row)
    assert bridge.rows == {}, "a licence of the run's own was left behind"
    order = [t for t, _a in bridge.calls if t in eph.LICENCE_TOOLS]
    assert order == list(eph.LICENCE_TOOLS)
    gen = next(a for t, a in bridge.calls if t == eph.GENERATE)
    assert gen["operator_did"].startswith("did:theprotocol:mcp-earn-licence-")
    # the key is in the answer once and never in a row
    assert "avfl_secret_never_kept" not in repr(out)


def test_a_read_back_that_disagrees_is_a_bug_find(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_Licences(stale_suspend=True))
    row = out[effect_name(eph.SUSPEND)]
    assert not row["healthy"] and "status='active'" in str(row.get("fail_reason")), row


def test_a_delete_the_list_still_shows_is_a_bug_find(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_Licences(keep_listing=True))
    row = out[effect_name(eph.DELETE)]
    assert not row["healthy"], row


def test_a_failed_step_still_deletes_the_licence(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Licences(refuse=eph.REVOKE)
    out = _run(bridge)
    assert not out[effect_name(eph.REVOKE)]["healthy"]
    assert out[effect_name(eph.DELETE)]["healthy"]
    assert bridge.rows == {}, "the licence outlived a failed step"


def test_a_refused_delete_is_retried_at_the_end(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Licences(refuse=eph.DELETE, refuse_once=True)
    out = _run(bridge)
    assert not out[effect_name(eph.DELETE)]["healthy"]
    assert bridge.rows == {}, "the licence outlived its refused delete"
    assert bridge.calls[-1][0] == eph.DELETE
