"""§MCPTEST30 (tester batch 2 item 4, agentvault2-d3, Guild order gwo_e3bad842b1a5943022b01d40): two peer-only reads,
read by a peer (federation_suite/tests/test_federation_peer_reads.py), through the registry-card feed's probe
generalised to an answer that is one object (peer_feed_probe: `want_keys`, `echo`, `check`).

Offline: the probe's lines are scripted (it runs inside sandbox-B's registry, with its SVID, on a pair) and the rig
answers sandbox-A's card, sandbox-B's peer rows and sandbox-A's own policy self-check. RED on the code before: the two
tests and the probe's keys do not exist.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.federation_suite import peer_feed_probe as P

HASH = "ab" * 32


def _lines(peer, stranger=None):
    stranger = stranger or {"name": "stranger", "error": "SSLError", "msg": "certificate required"}
    return "\n".join(json.dumps(x) for x in ({"name": "peer", **peer}, stranger))


def test_a_one_object_answer_is_held_to_its_keys():
    rows = P.read_answers(_lines({"status": 200, "items": None, "keys": ["policy_hash", "registry_did"]}))
    ok, why, ev = P.verdict(rows, "policy-compliance answer", ("registry_did", "policy_hash"))
    assert ok and "2 named key(s)" in why and ev["peer"]["keys"] == ["policy_hash", "registry_did"]
    ok, why, _ev = P.verdict(rows, "policy-compliance answer", ("registry_did", "policy_hash", "policy_version"))
    assert not ok and "['policy_version']" in why
    # without want_keys a feed still needs a list
    ok, why, _ev = P.verdict(rows, "registry-card feed")
    assert not ok and "without a list" in why


def test_a_stranger_answered_is_a_finding_and_a_closed_door_is_red():
    rows = P.read_answers(_lines({"status": 200, "keys": ["policy_hash"]},
                                 {"name": "stranger", "status": 200, "keys": ["policy_hash"]}))
    ok, why, _ev = P.verdict(rows, "policy-compliance answer", ("policy_hash",))
    assert not ok and why.startswith("BUG-FIND") and "no client certificate" in why
    rows = P.read_answers(_lines({"status": 401, "detail": "peer identity required"}))
    ok, why, _ev = P.verdict(rows, "sync status", ("total_peers",))
    assert not ok and "could not read" in why


class _Rig:
    def __init__(self, own_hash=HASH):
        self.own_hash = own_hash

    def mcp(self, label):
        rig = self

        class _M:
            async def call(self, tool, **_k):
                if tool == "getRegistryCard":
                    return {"identity": {"registry_name": "nt261031a"}}
                if tool == "listFederationPeers":
                    return [{"name": "nt261031a", "status": "ACTIVE", "base_url": "https://nt261031a-fed:8443"}]
                if tool == "getAdminFederationPolicyCompliance":
                    assert label == "sandbox-A-admin"
                    return {"policy_hash": rig.own_hash}
                raise AssertionError(tool)
        return _M()


def _run_test(monkeypatch, fn, peer_line, own_hash=HASH):
    seen = []

    def fake_exec(container, args, timeout=30):
        seen.append(args)
        return 0, _lines(peer_line)
    monkeypatch.setattr(P, "exec_in_container", fake_exec)
    res = asyncio.run(fn(_Rig(own_hash)))
    return res, seen


@pytest.fixture
def T():
    from agentvault_registry.api_tests.federation_suite.tests import test_federation_peer_reads as mod
    return mod


def test_the_policy_hash_a_peer_reads_is_the_registrys_own(monkeypatch, T):
    peer = {"status": 200, "keys": ["policy_hash", "policy_version", "registry_did"], "values": {"policy_hash": HASH}}
    res, seen = _run_test(monkeypatch, T.test_policy_compliance_read_by_a_peer, peer)
    assert res.passed, res.description
    assert seen[0][-3:] == ["https://nt261031a-fed:8443", "/api/v1/federation/policy-compliance", "policy_hash"], \
        "the probe is asked for the policy hash by name, nothing else"
    res, _seen = _run_test(monkeypatch, T.test_policy_compliance_read_by_a_peer, peer, own_hash="cd" * 32)
    assert not res.passed and "disagree" in res.description


def test_the_sync_status_counts_its_peer(monkeypatch, T):
    peer = {"status": 200, "keys": ["federation_enabled", "peer_status", "total_peers"],
            "values": {"federation_enabled": True, "total_peers": 2}}
    res, _seen = _run_test(monkeypatch, T.test_sync_status_read_by_a_peer, peer)
    assert res.passed, res.description
    res, _seen = _run_test(monkeypatch, T.test_sync_status_read_by_a_peer,
                           {**peer, "values": {"federation_enabled": True, "total_peers": 0}})
    assert not res.passed and "total_peers=0" in res.description


def test_both_are_registered_as_peer_reads():
    from agentvault_registry.api_tests.federation_suite import decorator as dec
    from agentvault_registry.api_tests.federation_suite import runner
    runner._discover_tests()
    names = {s.name: s for s in dec.REGISTRY}
    for n in ("federation_policy_compliance_read_by_a_peer", "federation_sync_status_read_by_a_peer"):
        assert n in names and set(names[n].requires) == {"sandbox-A", "sandbox-B"}, n


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
