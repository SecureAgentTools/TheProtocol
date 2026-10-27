"""§DOCSFIX D6-655 (2026-10-16): the signed solvency card has its API alias under the AGORA name.

Since §AGORAWORDS every AGORA route is documented under /api/v1/agora (the older /api/v1/exchange stays live, out of
the schema), and the AGORA card follows it (/api/v1/agora/card). The solvency card's alias existed only as
/api/v1/exchange/solvency-card. It now answers at /api/v1/agora/solvency-card too, documented, and the older path keeps
answering. Driven through FastAPI's TestClient; the card itself is stood in for (its builder needs a database).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.routers import solvency_card as SC


@pytest.fixture
def app(monkeypatch):
    async def _card(if_none_match, db):
        return Response(content=b'{"card":"solvency"}', media_type="application/json", headers={"ETag": '"e1"'})

    monkeypatch.setattr(SC, "_serve_solvency_card", _card)
    app = FastAPI()
    app.include_router(SC.router)

    async def _db():
        yield None

    app.dependency_overrides[get_db] = _db
    return app


@pytest.mark.parametrize("path", ["/api/v1/agora/solvency-card", "/api/v1/exchange/solvency-card",
                                  "/.well-known/solvency-card.json"])
def test_every_name_serves_the_card(app, path):
    r = TestClient(app).get(path)
    assert r.status_code == 200 and r.json() == {"card": "solvency"}, (path, r.status_code)


def test_the_schema_documents_the_agora_name(app):
    paths = app.openapi()["paths"]
    assert "/api/v1/agora/solvency-card" in paths
    assert "/api/v1/exchange/solvency-card" not in paths, "the older name stays live, out of the schema"
