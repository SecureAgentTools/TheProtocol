"""§NIGHTLYTRUTH (2026-09-14) — two federation-suite gates now REPORT what they used to gate on.

Driven through the real `FederationTestRig.assert_within` with the MCP layer faked, so each test exercises the
predicate as the suite runs it.

- `peer_registry_card_cache_populated` used to fail on `attempts_24h.error > 0`; sandbox-A read red all day on a
  peer with 113 successes and 3 errors (that registry's planned restarts). The gate now asks whether the peer is
  REACHED (a success in the window, or no error at all); errors are reported in the state.
- `eventstore_stats_total_grows` used to require a newest event within the hour, read from a projection VIEW that
  lags the store; on a quiet daytime tier it was red with a healthy store. The gate now asks that the store answers,
  holds its population and reports a newest event; the age is reported as `quiet`.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig
from agentvault_registry.api_tests.federation_suite.tests import test_registry_card_visual as cardvis
from agentvault_registry.api_tests.federation_suite.tests import test_event_store_recent_event_types as esstats


class _Mcp:
    def __init__(self, answers):
        self.answers = answers

    async def call(self, tool, args=None):
        return self.answers[tool]


def _rig(per_label):
    rig = object.__new__(FederationTestRig)
    rig.mcp = lambda label: _Mcp(per_label[label])  # type: ignore[attr-defined]
    return rig


def _peer(name, ptype="frame", success=1, error=0, synced="2026-09-14T06:42:13+00:00", host="sandbox-b.theprotocol.cloud"):
    return {"name": name, "status": "ACTIVE", "peer_type": ptype, "base_url": f"https://{host}:8443",
            "last_synced_iso": synced, "attempts_24h": {"success": success, "error": error, "skipped": 0}, "card_count": 0}


async def test_a_peer_with_three_errors_and_113_successes_is_reached_and_passes():
    a = {"getFederationSyncPeers": [_peer("Sandbox Beta", success=113, error=3), _peer("sbxalphaop", "cloud_operator", 72, 0)]}
    b = {"getFederationSyncPeers": [_peer("Sandbox Alpha", success=89, error=0), _peer("sbxbetaop", "cloud_operator", 28, 0)]}
    r = await cardvis.test_peer_card_cache_populated(_rig({"sandbox-A-admin": a, "sandbox-B-admin": b}))
    assert r.passed is True
    st = r.last_state["sandbox-A-admin"]
    assert st["erroring_peers"] == [{"name": "Sandbox Beta", "errors": 3, "success": 113}], "the errors are still reported"
    assert st["unreached_peers"] == []


async def test_a_peer_never_reached_in_the_window_still_fails():
    a = {"getFederationSyncPeers": [_peer("Sandbox Beta", success=0, error=5, synced=None), _peer("sbxalphaop", "cloud_operator", 72, 0)]}
    b = {"getFederationSyncPeers": [_peer("Sandbox Alpha", success=89, error=0)]}
    r = await cardvis.test_peer_card_cache_populated(_rig({"sandbox-A-admin": a, "sandbox-B-admin": b}))
    assert r.passed is False
    assert r.last_state["sandbox-A-admin"]["unreached_peers"] == ["Sandbox Beta"]


async def test_litter_and_discovered_peers_do_not_count():
    a = {"getFederationSyncPeers": [
        _peer("Sandbox Beta", success=10, error=0),
        _peer("Test Federation Peer 1", "direct_peer", 0, 113, synced=None, host="test-peer-1.theprotocol.test"),
        _peer("sbxbetaop", "discovered", 28, 0, synced=None),
    ]}
    b = {"getFederationSyncPeers": [_peer("Sandbox Alpha", success=89, error=0)]}
    r = await cardvis.test_peer_card_cache_populated(_rig({"sandbox-A-admin": a, "sandbox-B-admin": b}))
    assert r.passed is True
    assert r.last_state["sandbox-A-admin"]["active_peers"] == 1


async def test_a_quiet_store_with_its_population_passes_and_says_quiet():
    a = {"getEventStoreStats": {"total_events": 64491, "unique_agents": 2939, "newest_event": "2026-09-14T03:05:00+00:00"}}
    r = await esstats.test_eventstore_stats(_rig({"sandbox-A-admin": a}))
    assert r.passed is True
    assert r.last_state["quiet"] is True and r.last_state["newest_age_sec"] > 3600


async def test_a_store_below_its_population_floor_or_without_a_newest_event_fails():
    small = {"getEventStoreStats": {"total_events": 500, "unique_agents": 3, "newest_event": "2026-09-14T06:35:27+00:00"}}
    r = await esstats.test_eventstore_stats(_rig({"sandbox-A-admin": small}))
    assert r.passed is False
    none = {"getEventStoreStats": {"total_events": 64491, "unique_agents": 2939, "newest_event": None}}
    r2 = await esstats.test_eventstore_stats(_rig({"sandbox-A-admin": none}))
    assert r2.passed is False
