"""§DOCSFIX CB-396 / D6-711: the card route's version metadata says what it serves.

Every registry serves a version 0.6 card, but GET /.well-known/registry-card.json answered with
`X-Registry-Card-Version: 0.4` (a literal in the router), its OpenAPI description promised "24 signed canonical paths"
while the signer signs 28, and the envelope route's description spoke of "a v0.4 registry card". The header now
repeats the card's own `registry_card_version`, on a fresh build and on a cache hit alike, and the descriptions name
no stale version or count.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.routers import registry_card as rc
from agentvault_registry.services import registry_card_builder as rcb
from agentvault_registry.services.registry_card_signer import SIGNED_CANONICAL_PATHS


@pytest.fixture
def client(monkeypatch):
    builds = []

    async def _build(db, sign=True):
        builds.append(1)
        return {"registry_card_version": "0.6", "lifecycle": {"card_etag": "sha256:" + "a" * 64}}

    async def _etag(db):
        return "sha256:" + "a" * 64

    async def _db():
        yield None

    monkeypatch.setattr(rc, "build_registry_card", _build)
    monkeypatch.setattr(rcb, "compute_serve_etag", _etag)
    monkeypatch.setattr(rc, "_CARD_CACHE", {"etag": None, "body": None, "ts": 0.0, "version": None})
    app = FastAPI()
    app.include_router(rc.router)
    app.dependency_overrides[get_db] = _db
    c = TestClient(app)
    c.builds = builds
    return c


def test_the_header_repeats_the_cards_own_version(client):
    first = client.get("/.well-known/registry-card.json")
    assert first.status_code == 200
    assert first.headers["x-registry-card-version"] == first.json()["registry_card_version"] == "0.6"
    second = client.get("/.well-known/registry-card.json")   # served from the per-worker body cache
    assert client.builds == [1]
    assert second.headers["x-registry-card-version"] == "0.6"


def test_the_descriptions_name_no_stale_version_or_count(client):
    paths = client.app.openapi()["paths"]
    card = paths["/.well-known/registry-card.json"]["get"]["description"]
    assert "24 signed" not in card and f"{len(SIGNED_CANONICAL_PATHS)} in this release" in card
    assert len(SIGNED_CANONICAL_PATHS) == 28
    envelope = paths["/api/v1/public/registry-card"]["get"]["description"]
    assert "v0.4" not in envelope
