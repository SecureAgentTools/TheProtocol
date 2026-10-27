"""D6-309 (2026-10-16): strict peer binding refuses an unbound identity on every registry, stamped rows or not.

`_assert_peer_spiffe_binding` returned early ("binding not enforced") whenever no peer row carried a spiffe_id and no
canonical row matched, BEFORE it read FEDERATION_REQUIRE_PEER_SPIFFE_BIND. A frame stamps spiffe_id only on its own
cloud operators' rows, so on a frame without operators, and on every cloud operator (whose own rows are never
stamped), the strict switch the templates set did nothing for a caller bound to no row. Now strict mode refuses such
a caller there too; without the switch the quiet legacy path is unchanged, and a caller bound to an ACTIVE row of its
trust domain passes in both.

Through FastAPI on a real federation route (GET /api/v1/federation/governance/open, behind
require_peer_registry_identity); the mTLS identity is supplied (get_federation_identity), the peer table is a double
and the route's own event-store read is stubbed.
RED on 7140a4a6: test_strict_refuses_an_unbound_peer_with_no_stamped_rows (200 on the base).
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import database
from agentvault_registry.core import federation_auth as fa
from agentvault_registry.routers import federation_ballots

STRANGER = "spiffe://stranger.example.invalid/service/registry"
PEER = "spiffe://asia.example.invalid/service/registry"


class _Session:
    """The three reads the binding makes: the exact spiffe_id row, the canonical rows, the stamped count."""

    def __init__(self, canonical=(), stamped=0):
        self.canonical, self.stamped = list(canonical), stamped

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        sql = str(stmt).lower()
        if "count(" in sql:
            return SimpleNamespace(scalar=lambda: self.stamped)
        if "peer_registries.spiffe_id =" in sql:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.canonical)))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    fa._S3_CACHE.clear()
    fa._S3_WARNED.clear()

    async def _nothing_open():
        return []
    monkeypatch.setattr(federation_ballots, "_open_here", _nothing_open)
    yield
    fa._S3_CACHE.clear()
    fa._S3_WARNED.clear()


def _get(monkeypatch, identity, session, strict):
    if strict:
        monkeypatch.setenv("FEDERATION_REQUIRE_PEER_SPIFFE_BIND", "true")
    else:
        monkeypatch.delenv("FEDERATION_REQUIRE_PEER_SPIFFE_BIND", raising=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: session)
    app = FastAPI()
    app.include_router(federation_ballots.router)
    app.dependency_overrides[fa.get_federation_identity] = lambda: identity
    return TestClient(app, raise_server_exceptions=False).get("/api/v1/federation/governance/open")


def test_strict_refuses_an_unbound_peer_with_no_stamped_rows(monkeypatch):
    r = _get(monkeypatch, STRANGER, _Session(canonical=[], stamped=0), strict=True)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert "not bound to a known registry" in r.text


def test_control_strict_passes_a_peer_bound_to_its_active_frame_row(monkeypatch):
    row = SimpleNamespace(name="asia", status="ACTIVE", spiffe_id=None)
    r = _get(monkeypatch, PEER, _Session(canonical=[row], stamped=0), strict=True)
    assert r.status_code == 200, (r.status_code, r.text[:300])


def test_control_without_the_switch_the_legacy_path_stays_quiet(monkeypatch):
    r = _get(monkeypatch, STRANGER, _Session(canonical=[], stamped=0), strict=False)
    assert r.status_code == 200, (r.status_code, r.text[:300])


def test_control_strict_with_stamped_rows_refused_as_before(monkeypatch):
    r = _get(monkeypatch, STRANGER, _Session(canonical=[], stamped=3), strict=True)
    assert r.status_code == 403, (r.status_code, r.text[:300])
