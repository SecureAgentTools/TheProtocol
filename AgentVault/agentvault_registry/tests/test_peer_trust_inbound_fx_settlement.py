"""§SUITES1018 / §FEDPROOF F2 (2026-10-18): the RECEIVING frame records its side of an inbound FX settlement.

The federation suite's `peer_trust_counters_move_on_both_sides_after_one_settlement` failed on the sandbox once the
AGORA sim was stopped: sbx-alpha's row for Sandbox Beta moved, sbx-beta's row for Sandbox Alpha did not. The
settlement (FxSwapSettled f68c7693, 12:29:50Z) reached sbx-beta's foreign_events at 12:30:04Z and its polling backstop
dispatched it at 12:30:21Z, and the reactor filed it as a third party's: the payload names the destination TEG
`teg-layer-sandbox-beta` (key `sandbox-beta`), the frame's own name is REGISTRY_NAME `Sandbox Beta` (key `sandbox
beta`) and its TEG id the bare `teg-layer` (no key), so neither side read as local. Every nightly passed it only
because the sim's own beta -> alpha settlements moved the same counter inside the test's budget.

Through the reactor's real handler with today's live payload; only the database, Redis and the recorder are replaced.
RED on 9ac0925c (the tests named test_red_*): the inbound settlement is never recorded. The controls pass on both.
"""
from __future__ import annotations

import itertools
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import agentvault_registry.background_tasks.reactor_peer_trust_observed as mod

ALPHA = SimpleNamespace(id=11, name="Sandbox Alpha", status="ACTIVE", peer_type="frame",
                        trust_domain="sandbox-a.theprotocol.cloud")
GAMMA = SimpleNamespace(id=12, name="Sandbox Gamma", status="ACTIVE", peer_type="frame",
                        trust_domain="sandbox-g.theprotocol.cloud")
BETAOP = SimpleNamespace(id=13, name="sbxbetaop", status="ACTIVE", peer_type="cloud_operator",
                         trust_domain="sandbox-b.theprotocol.cloud")
BETA = SimpleNamespace(id=21, name="Sandbox Beta", status="ACTIVE", peer_type="frame",
                       trust_domain="sandbox-b.theprotocol.cloud")

# FxSwapSettled f68c7693 as sbx-alpha's store holds it (2026-10-18 12:29:50Z), the fields the reactor reads
INBOUND = {"swap_id": "f68c7693-708c-4910-a332-49d10020cd16",
           "from": "did:theprotocol:sandbox-a.theprotocol.cloud:7b711a8d-8e79-411d-9092-c310b335cda6",
           "to": "did:theprotocol:sandbox-b.theprotocol.cloud:8270290f-c2d3-4769-b028-6801b53d4f20",
           "source_teg": "teg-layer", "source_frame": "sandbox-a.theprotocol.cloud",
           "dest_teg": "teg-layer-sandbox-beta", "dest_frame": "sandbox-b.theprotocol.cloud",
           "_foreign_frame_id": "sandbox-a.theprotocol.cloud"}

_n = itertools.count()


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Db:
    """Answers the reactor's two peer reads: every ACTIVE row, or the ACTIVE frames (the WHERE names peer_type)."""

    def __init__(self, peers):
        self.peers = peers

    async def execute(self, stmt, *a, **k):
        rows = [p for p in self.peers if p.status == "ACTIVE"]
        if "peer_type" in str(stmt):
            rows = [p for p in rows if p.peer_type == "frame"]
        return _Rows(rows)


class _Redis:
    def __init__(self):
        self.kv = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True


@pytest.fixture()
def node(monkeypatch):
    """A registry configured like one of the live nodes; returns (configure, recorded)."""
    recorded = []
    redis = _Redis()

    async def _get_redis():
        return redis

    class _Svc:
        async def record_interaction(self, db, peer_id, success=True):
            recorded.append((peer_id, success))

    import agentvault_registry.services.bayesian_trust as bt
    monkeypatch.setattr(mod, "get_redis", _get_redis)
    monkeypatch.setattr(bt, "get_bayesian_trust_service", lambda: _Svc())

    def configure(*, name, trust_domain, teg_id, peers, federation_name=None):
        monkeypatch.setenv("REGISTRY_NAME", name)
        monkeypatch.setenv("SPIRE_TRUST_DOMAIN", trust_domain)
        if federation_name:
            monkeypatch.setenv("REGISTRY_FEDERATION_NAME", federation_name)
        else:
            monkeypatch.delenv("REGISTRY_FEDERATION_NAME", raising=False)
        import agentvault_registry.routers.teg_integration as ti
        monkeypatch.setattr(ti, "_get_local_teg_id", lambda: teg_id)
        monkeypatch.setattr(mod, "_local_keys_cache", None)
        monkeypatch.setattr(mod, "_local_teg_named_cache", None)

        @asynccontextmanager
        async def _ctx():
            yield _Db(peers)
        monkeypatch.setattr(mod, "get_db_context", _ctx)
        cls = type("FxReactorUnderTest", (mod.FxSwapSettledTrustReactor,), {"leader_key": f"test_peer_trust_{next(_n)}"})
        return cls()

    return configure, recorded


async def test_red_the_receiving_frame_records_an_inbound_fx_settlement(node):   # BASE: third_party, nothing recorded
    configure, recorded = node
    r = configure(name="Sandbox Beta", trust_domain="sandbox-b.theprotocol.cloud", teg_id="teg-layer",
                  peers=[ALPHA, BETAOP])
    await r.handle_event(dict(INBOUND))
    assert recorded == [(ALPHA.id, True)], (recorded, r._counts)
    assert r._counts["third_party"] == 0, r._counts


OUTBOUND = {"swap_id": "a58ad61e-d108-413d-a1f1-514f57437530", "source_teg": "teg-layer",
            "source_frame": "sandbox-b.theprotocol.cloud", "dest_teg": "teg-layer-sandbox-alpha",
            "dest_frame": "sandbox-a.theprotocol.cloud"}


async def test_red_an_inbound_settlement_seen_twice_is_counted_once(node):   # BASE: never counted at all
    configure, recorded = node
    r = configure(name="Sandbox Beta", trust_domain="sandbox-b.theprotocol.cloud", teg_id="teg-layer",
                  peers=[ALPHA, BETAOP])
    await r.handle_event(dict(INBOUND))
    await r.handle_event(dict(INBOUND))
    assert recorded == [(ALPHA.id, True)], recorded
    assert r._counts["duplicate"] == 1, r._counts


async def test_control_an_outbound_settlement_seen_twice_is_counted_once(node):
    configure, recorded = node
    r = configure(name="Sandbox Beta", trust_domain="sandbox-b.theprotocol.cloud", teg_id="teg-layer",
                  peers=[ALPHA, BETAOP])
    await r.handle_event(dict(OUTBOUND))
    await r.handle_event(dict(OUTBOUND))
    assert recorded == [(ALPHA.id, True)], recorded
    assert r._counts["duplicate"] == 1, r._counts


async def test_control_the_frames_operator_does_not_claim_the_frames_settlement(node):
    """sbxbetaop shares sbx-beta's trust domain and reads its parent's store: the settlement names the FRAME's TEG, so
    the operator records nothing (the §FRAMELIC rule the reactor keeps: a node the payload could name claims only a side
    that names it)."""
    configure, recorded = node
    r = configure(name="cloud-op-sbxbetaop", federation_name="sbxbetaop", trust_domain="sandbox-b.theprotocol.cloud",
                  teg_id="teg-sbxbetaop", peers=[ALPHA, BETA])
    await r.handle_event(dict(INBOUND))
    assert recorded == [], (recorded, r._counts)
    assert r._counts["third_party"] == 1, r._counts


async def test_control_a_settlement_between_two_other_frames_stays_third_party(node):
    configure, recorded = node
    r = configure(name="Sandbox Beta", trust_domain="sandbox-b.theprotocol.cloud", teg_id="teg-layer",
                  peers=[ALPHA, GAMMA])
    overheard = dict(INBOUND, dest_teg="teg-layer-sandbox-gamma", dest_frame="sandbox-g.theprotocol.cloud",
                     swap_id="0a0a0a0a-0000-4000-8000-000000000001")
    await r.handle_event(overheard)
    assert recorded == [], (recorded, r._counts)
    assert r._counts["third_party"] == 1, r._counts


async def test_control_the_sending_frame_still_records_its_outbound_settlement(node):
    """The direction that always worked: sbx-beta emitted it (no _foreign_frame_id), its own side is the bare teg-layer
    in its own trust domain, the destination is Sandbox Alpha."""
    configure, recorded = node
    r = configure(name="Sandbox Beta", trust_domain="sandbox-b.theprotocol.cloud", teg_id="teg-layer",
                  peers=[ALPHA, BETAOP])
    await r.handle_event(dict(OUTBOUND))
    assert recorded == [(ALPHA.id, True)], (recorded, r._counts)


async def test_control_a_production_frame_name_still_matches(node):
    """EU's REGISTRY_NAME is `EU`; ASIA's settlements to it name `teg-layer-eu`: the one key keeps that match."""
    configure, recorded = node
    asia = SimpleNamespace(id=31, name="asia", status="ACTIVE", peer_type="frame", trust_domain="asia.theprotocol.cloud")
    r = configure(name="EU", trust_domain="eu.theprotocol.cloud", teg_id="teg-layer", peers=[asia])
    inbound = {"swap_id": "0b0b0b0b-0000-4000-8000-000000000002", "source_teg": "teg-layer",
               "source_frame": "asia.theprotocol.cloud", "dest_teg": "teg-layer-eu", "dest_frame": "eu.theprotocol.cloud",
               "_foreign_frame_id": "asia.theprotocol.cloud"}
    await r.handle_event(inbound)
    assert recorded == [(asia.id, True)], (recorded, r._counts)
