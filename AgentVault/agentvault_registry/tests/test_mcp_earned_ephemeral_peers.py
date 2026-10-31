"""§MCPTEST30 (V0650, tester batch 1 item 1b, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6):
earn_ephemeral_peers, the federation enforcement tools on a peer registry row of the run's own, only where the target is
torn down after its run (MCP_TESTER_EPHEMERAL_TARGET, the nightly and proof pairs).

Offline: a scripted admin bridge keeps peer rows the way routers/federation_admission.py and the compliance monitor do
(request-admission makes a PENDING_APPROVAL row and a pending compliance record; quarantine, lift and blacklist move the
compliance record and emit their events; blacklist marks the row REJECTED; a lift of a row not in quarantine is a 409;
a policy update finds the row by its operator DID, only while federated, and refuses a locked parameter's change),
and validates with the target's own FederationPolicyValidator. RED control: on V0649's code the lifecycle does not exist
(the attribute is missing), and the four tools' only rows are refusals or skips.
"""
from __future__ import annotations

import asyncio
import itertools
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_ad_ephemeral as eph
from agentvault_registry.api_tests.contracts.earned_fixtures import effect_name
from agentvault_registry.services.federation_policy_validator import FederationPolicyValidator


class _Peers:
    """The admin bridge, answering as the admission and enforcement routes answer."""

    def __init__(self, *, stale_quarantine: bool = False, refuse: Optional[str] = None, drop_event: str = "",
                 invalid_policy: bool = False, raise_on: Optional[str] = None, stale_policy: bool = False):
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.compliance: Dict[str, Dict[str, Any]] = {}
        self.events: List[str] = []
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.stale_quarantine, self.refuse, self.drop_event = stale_quarantine, refuse, drop_event
        self.invalid_policy, self.raise_on, self.stale_policy = invalid_policy, raise_on, stale_policy
        self._n = itertools.count(1)

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args)))
        if tool == self.raise_on:
            raise RuntimeError("the scripted bridge broke")
        ok, result, code = self._answer(tool, dict(args))
        return ok, {"result": result}, code

    def _emit(self, event_type: str) -> None:
        if event_type != self.drop_event:
            self.events.append(event_type)

    def _answer(self, tool: str, a: Dict[str, Any]) -> Tuple[bool, Any, str]:
        if tool == self.refuse:
            return False, {"_text": "Error: HTTP 500: the scripted refusal"}, "500"
        if tool == eph.VALIDATE:
            r = FederationPolicyValidator().validate(a["policy"])
            if self.invalid_policy:
                return True, {"valid": False, "violations": [{"path": "supply_integrity.genesis_only_minting"}]}, "200"
            return True, {"valid": r.valid, "violations": [v.to_dict() for v in r.violations]}, "200"
        if tool == eph.ADMIT:
            for k in ("registry_name", "registry_operator_did", "registry_public_url", "admin_contact_email"):
                assert a.get(k), k
            assert FederationPolicyValidator().validate(a["policy_json"]).valid, "admitted an invalid policy"
            n = next(self._n)
            pid, aid = str(n), f"adm-{n}"
            self.peers[pid] = {"id": pid, "name": a["registry_name"], "base_url": a["registry_public_url"],
                               "status": "PENDING_APPROVAL", "operator_did": a["registry_operator_did"]}
            self.compliance[aid] = {"admission_id": aid, "peer_registry_id": n, "peer_name": a["registry_name"],
                                    "federation_status": "pending", "policy_hash": "a" * 64, "quarantine_reason": None,
                                    "policy_json": a["policy_json"], "policy_version": 1}
            return True, {"admission_id": aid, "peer_registry_id": n, "status": "pending_approval",
                          "policy_hash": "a" * 64, "violations": [], "warnings": [], "message": "ok"}, "201"
        if tool == eph.ADMISSION:
            c = self.compliance.get(str(a.get("admission_id")))
            return (True, dict(c), "200") if c else (False, {"_text": "Error: HTTP 404: admission not found"}, "404")
        if tool == eph.POLICY_UPDATE:
            peer = next((p for p in self.peers.values() if p["operator_did"] == a.get("peer_did")), None)
            if peer is None:
                return False, {"_text": "Error: HTTP 404: No peer registry found for that DID"}, "404"
            c = next(x for x in self.compliance.values() if str(x["peer_registry_id"]) == peer["id"])
            if c["federation_status"] not in ("federated", "soft_quarantined"):
                return False, {"_text": f"Error: HTTP 409: Policy updates not allowed in state: "
                                        f"{c['federation_status']}"}, "409"
            r = FederationPolicyValidator().validate(a["proposed_policy_json"])
            if not r.valid:
                return False, {"_text": "Error: HTTP 422: Proposed policy failed validation"}, "422"
            from agentvault_registry.core.base_network_params import LOCKED_PARAMS
            from agentvault_registry.services.federation_policy_validator import deep_get
            if any(deep_get(c["policy_json"], k) != deep_get(a["proposed_policy_json"], k) for k in LOCKED_PARAMS):
                return False, {"_text": "Error: HTTP 422: Cannot modify locked parameters"}, "422"
            c["policy_version"] += 1
            if not self.stale_policy:
                c["policy_json"], c["policy_hash"] = a["proposed_policy_json"], r.submitted_hash
            self._emit("FederationPolicyUpdated")
            return True, {"status": "auto_approved", "peer_did": a["peer_did"], "new_policy_hash": r.submitted_hash,
                          "policy_version": c["policy_version"]}, "200"
        pid = str(a.get("peer_id") or "")
        c = next((x for x in self.compliance.values() if str(x["peer_registry_id"]) == pid), None)
        if c is None:
            return False, {"_text": f"Error: HTTP 404: peer {pid} not found"}, "404"
        if tool == eph.QUARANTINE:
            if not self.stale_quarantine:
                c["federation_status"], c["quarantine_reason"] = "quarantined", a.get("reason")
            self._emit("RegistryQuarantined")
            return True, {"peer_registry_id": int(pid), "federation_status": "quarantined",
                          "grace_hours": a.get("grace_hours")}, "200"
        if tool == eph.LIFT:
            if c["federation_status"] != "quarantined":
                return False, {"_text": f"Error: HTTP 409: not_quarantined: peer {pid} is {c['federation_status']}"}, "409"
            c["federation_status"], c["quarantine_reason"] = "federated", None
            self._emit("RegistryQuarantineLifted")
            return True, {"peer_registry_id": int(pid), "federation_status": "federated",
                          "new_policy_hash": a.get("new_policy_hash")}, "200"
        if tool == eph.BLACKLIST:
            c["federation_status"], c["quarantine_reason"] = "blacklisted", None
            self.peers[pid]["status"] = "REJECTED"
            self._emit("RegistryBlacklisted")
            return True, {"peer_registry_id": int(pid), "federation_status": "blacklisted"}, "200"
        return False, {"_text": f"Error: HTTP 404: no such tool {tool}"}, "404"


def _parse(body: Dict[str, Any]) -> Any:
    return body.get("result") if isinstance(body, dict) else {}


def _bag(bridge: _Peers) -> Any:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    bag.rpc_admin = bridge                 # type: ignore[attr-defined]
    bag.admin_lifecycle_rows = {}          # type: ignore[attr-defined]

    async def event_verifier(types: List[str], tool: str) -> Tuple[bool, Optional[str]]:
        missing = [t for t in types if t not in bridge.events]
        return (not missing), (f"no {missing} on the ledger after {tool}" if missing else None)
    bag.event_verifier = event_verifier    # type: ignore[attr-defined]
    return bag


async def _no_public(tool: str, args: dict, jwt: str = "", timeout: int = 20):
    raise AssertionError(f"the peer lifecycle called {tool} on the public bridge")


def _run(bridge: _Peers) -> Dict[str, dict]:
    outcomes: Dict[str, dict] = {}
    asyncio.run(eph.lifecycle_earn_ephemeral_peers(_no_public, _parse, _bag(bridge), outcomes))
    return outcomes


def test_it_is_registered_with_the_earned_admin_lifecycles():
    assert "earn_ephemeral_peers" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]


def test_the_built_policy_is_one_the_target_admits():
    r = FederationPolicyValidator().validate(eph.compliant_policy())
    assert r.valid, [v.to_dict() for v in r.violations]


def test_a_standing_frame_asks_nothing_and_says_why(monkeypatch):
    monkeypatch.delenv(eph.EPHEMERAL_ENV, raising=False)
    bridge = _Peers()
    out = _run(bridge)
    assert bridge.calls == []
    assert sorted(out) == sorted(effect_name(t) for t in eph.PEER_TOOLS)
    for row in out.values():
        assert row.get("skip_reason") and eph.EPHEMERAL_ENV in str(row.get("skip_reason")), row


def test_an_ephemeral_target_earns_all_four_and_closes_its_row(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Peers()
    out = _run(bridge)
    for tool in eph.PEER_TOOLS:
        row = out[effect_name(tool)]
        assert row["healthy"] and not row.get("skip_reason") and not row.get("fail_reason"), (tool, row)
    assert [t for t, _a in bridge.calls if t in eph.PEER_TOOLS] == list(eph.PEER_TOOLS)
    assert bridge.events == ["RegistryQuarantined", "RegistryQuarantineLifted", "FederationPolicyUpdated",
                             "RegistryBlacklisted"]
    (peer,) = bridge.peers.values()
    assert peer["status"] == "REJECTED" and peer["base_url"].endswith(".invalid")
    assert peer["name"].startswith("mcp-earn-peer-")
    assert "theprotocol_completeAdmission" not in [t for t, _a in bridge.calls], "the row must never be made ACTIVE"
    (c,) = bridge.compliance.values()
    assert c["federation_status"] == "blacklisted"


def test_a_policy_the_target_refuses_admits_nothing_and_says_so(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Peers(invalid_policy=True)
    out = _run(bridge)
    assert bridge.peers == {}
    for tool in eph.PEER_TOOLS:
        why = str(out[effect_name(tool)].get("skip_reason"))
        assert "did not validate" in why and "genesis_only_minting" in why, why


def test_the_moved_policy_is_one_the_target_admits_and_differs():
    base = eph.compliant_policy()
    moved, path = eph.moved_policy(base)
    assert path and moved != base
    assert FederationPolicyValidator().validate(moved).valid


def test_a_policy_update_the_admission_does_not_show_is_a_bug_find(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_Peers(stale_policy=True))
    row = out[effect_name(eph.POLICY_UPDATE)]
    assert not row["healthy"] and "not the updated policy's" in str(row.get("fail_reason")), row
    assert out[effect_name(eph.BLACKLIST)]["healthy"]


def test_a_row_the_lift_left_quarantined_gets_no_update_and_says_why(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Peers(refuse=eph.LIFT)
    out = _run(bridge)
    assert "federation_status='quarantined'" in str(out[effect_name(eph.POLICY_UPDATE)].get("skip_reason"))
    assert eph.POLICY_UPDATE not in [t for t, _a in bridge.calls]


def test_a_quarantine_the_status_does_not_show_is_a_bug_find(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_Peers(stale_quarantine=True))
    row = out[effect_name(eph.QUARANTINE)]
    assert not row["healthy"] and "federation_status='pending'" in str(row.get("fail_reason")), row


def test_a_step_whose_event_never_reaches_the_ledger_is_red(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    out = _run(_Peers(drop_event="RegistryQuarantineLifted"))
    assert not out[effect_name(eph.LIFT)]["healthy"], out[effect_name(eph.LIFT)]
    assert out[effect_name(eph.QUARANTINE)]["healthy"] and out[effect_name(eph.BLACKLIST)]["healthy"]


def test_a_refused_step_still_closes_the_row(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Peers(refuse=eph.QUARANTINE)
    out = _run(bridge)
    assert not out[effect_name(eph.QUARANTINE)]["healthy"]
    assert not out[effect_name(eph.LIFT)]["healthy"], "a lift of a row never quarantined is a 409, never a pass"
    assert out[effect_name(eph.BLACKLIST)]["healthy"]
    assert next(iter(bridge.peers.values()))["status"] == "REJECTED"


def test_a_bridge_that_breaks_mid_run_still_closes_the_row(monkeypatch):
    monkeypatch.setenv(eph.EPHEMERAL_ENV, "true")
    bridge = _Peers(raise_on=eph.LIFT)
    with pytest.raises(RuntimeError):
        _run(bridge)
    assert next(iter(bridge.peers.values()))["status"] == "REJECTED", "the run's own row outlived a broken step"
    assert bridge.calls[-1][0] == eph.BLACKLIST


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
