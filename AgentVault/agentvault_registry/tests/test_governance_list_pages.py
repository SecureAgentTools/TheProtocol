"""§DOCSFIX D6-570 (2026-10-16): GET /api/v1/governance/proposals pages its default (open) listing too.

The route declares `limit` (1 to 200, default 50) and `offset`, and applied them only with `include_closed=true`: the
default listing of open proposals returned every open proposal whatever `limit` and `offset` said. Driven through
FastAPI's TestClient with a session that records the statement it is asked; the statement is compiled with its values.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from agentvault_registry.database import get_db
from agentvault_registry.routers import governance as GOV


class _Session:
    def __init__(self):
        self.sql = []

    async def execute(self, stmt):
        self.sql.append(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


@pytest.fixture
def rig():
    db = _Session()
    app = FastAPI()
    app.include_router(GOV.router, prefix="/api/v1/governance")

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app), db


@pytest.mark.parametrize("closed", ["false", "true"])
def test_limit_and_offset_bind_both_listings(rig, closed):
    client, db = rig
    r = client.get(f"/api/v1/governance/proposals?include_closed={closed}&limit=2&offset=1")
    assert r.status_code == 200, r.text
    listing = db.sql[0]
    assert "FROM governance_proposals" in listing
    assert "LIMIT 2" in listing and "OFFSET 1" in listing, listing


def test_the_default_listing_still_reads_only_open_proposals(rig):
    client, db = rig
    assert client.get("/api/v1/governance/proposals").status_code == 200
    listing = db.sql[0]
    assert "governance_proposals.status = 'VOTING'" in listing and "LIMIT 50" in listing, listing
