"""§FEDLICENCE (2026-09-28, his word "cross-teg cut off also approved on revoke") — the registry publishes what it decided
about each peer, so its own TEG can refuse the same frames on the cross-TEG legs.

GET /api/v1/federation/licence/verdicts answers the mode, this registry's trust domain, every peer verdict, and the
domains it REFUSES. The TEG copies `refused` rather than re-deriving it from the states, so REFUSED_STATES keeps one home.
RED control: on the tree before the change, the route and licence_verdicts_snapshot do not exist.
"""
from __future__ import annotations

import pytest

from agentvault_registry.core import mtls_auth
from agentvault_registry.services.federation_licence import REFUSED_STATES

EU = "eu.theprotocol.cloud"


@pytest.fixture(autouse=True)
def _verdicts(monkeypatch):
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", EU)
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", "enforce")
    saved = dict(mtls_auth._LICENCE_STATE_BY_TD)
    mtls_auth._LICENCE_STATE_BY_TD.clear()
    mtls_auth._LICENCE_STATE_BY_TD.update({
        "asia.theprotocol.cloud": "licensed",
        "revoked.example": "revoked",
        "suspended.example": "suspended",
        "pending.example": "unverified",
    })
    yield
    mtls_auth._LICENCE_STATE_BY_TD.clear()
    mtls_auth._LICENCE_STATE_BY_TD.update(saved)


def test_the_snapshot_lists_exactly_the_refused_domains():
    s = mtls_auth.licence_verdicts_snapshot()
    assert s["mode"] == "enforce" and s["local_trust_domain"] == EU
    assert s["refused"] == ["revoked.example", "suspended.example"]
    assert s["verdicts"]["pending.example"] == "unverified"   # reported, never refused
    assert all(s["verdicts"][td] in REFUSED_STATES for td in s["refused"])
    assert not any(v in REFUSED_STATES for td, v in s["verdicts"].items() if td not in s["refused"])


@pytest.mark.parametrize("raw,mode", [("observe", "observe"), (" ENFORCE ", "enforce"), ("", "off"),
                                      ("bogus", "off"), ("off", "off")])
def test_the_mode_is_the_one_the_trust_check_acts_on(monkeypatch, raw, mode):
    monkeypatch.setenv("FEDERATION_LICENCE_MODE", raw)
    assert mtls_auth.licence_verdicts_snapshot()["mode"] == mode


@pytest.mark.asyncio
async def test_the_route_is_public_and_refreshes_first(monkeypatch):
    from agentvault_registry.routers import federation_licence as r
    routes = [x for x in r.router.routes if getattr(x, "path", "") == "/api/v1/federation/licence/verdicts"]
    assert len(routes) == 1 and routes[0].methods == {"GET"}
    assert not routes[0].dependencies   # public: the TEG reads it with no credential

    calls = []

    async def fake_refresh(**kw):
        calls.append(kw)
        return frozenset()

    monkeypatch.setattr(mtls_auth, "refresh_peer_trust_domains", fake_refresh)
    out = await r.licence_verdicts()
    assert calls == [{}]
    assert out["refused"] == ["revoked.example", "suspended.example"] and out["mode"] == "enforce"
