"""§DOCSFIX D6-109 (2026-10-16): the public peer list's total counts the peers the list publishes.

GET /api/v1/federation/peers/ lists this registry's DIRECT peers only (active, of type frame, direct_peer or
cloud_operator, with no parent: never a chain-discovered one), while `pagination.total_items` counted every ACTIVE row,
the discovered and chain-child peers included (EU, 2026-10-16: 3 items, total 5). The count now asks the same question
as the list. Driven through FastAPI's TestClient with a session that answers the list and the count from one set of
rows by the conditions each statement carries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from agentvault_registry.database import get_db
from agentvault_registry.routers import federation_peers as FP

ROWS = [  # (name, status, peer_type, parent_registry_id)
    ("asia", "ACTIVE", "frame", None),
    ("amsterdam", "ACTIVE", "cloud_operator", None),
    ("lisbon", "ACTIVE", "cloud_operator", None),
    ("shenzhen", "ACTIVE", "cloud_operator", 1),          # a chain child of asia
    ("op-singapore", "ACTIVE", "discovered", None),       # BFS-derived
    ("old", "INACTIVE", "frame", None),
]


def _matches(sql: str, row) -> bool:
    name, status, peer_type, parent = row
    if "peer_registries.status = 'ACTIVE'" in sql and status != "ACTIVE":
        return False
    if "peer_registries.peer_type IN" in sql and peer_type not in ("frame", "direct_peer", "cloud_operator"):
        return False
    if "peer_registries.parent_registry_id IS NULL" in sql and parent is not None:
        return False
    return True


def _row(i, name, status, peer_type, parent):
    return SimpleNamespace(id=i, owner_developer_id=1, name=name, description=None, base_url=f"https://{name}.example",
                           admin_contact_email="ops@example.org", status=status, discovery_auth_info={},
                           interaction_auth_info=None, registered_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                           approved_at=None, approved_by_developer_id=None, last_synced_at=None, peer_type=peer_type,
                           hop_distance=None, parent_registry_id=parent, trust_domain=None)


class _Session:
    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        hits = [(i, r) for i, r in enumerate(ROWS, 1) if _matches(sql, r)]
        if "count(*)" in sql:
            return SimpleNamespace(scalar=lambda: len(hits))
        rows = [_row(i, *r) for i, r in hits]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(FP.router, prefix="/api/v1")

    async def _db():
        yield _Session()

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_the_total_counts_what_the_list_lists(client):
    r = client.get("/api/v1/federation/peers/")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["name"] for i in body["items"]] == ["asia", "amsterdam", "lisbon"]
    assert body["pagination"]["total_items"] == 3 and body["pagination"]["total_pages"] == 1
