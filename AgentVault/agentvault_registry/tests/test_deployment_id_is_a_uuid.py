"""§DEPS V0477 (2026-09-28): a deployment id is a UUID in the path, so a malformed one never reaches Postgres.

`agent_deployments.id` is a uuid column and the three routes took the id as a plain str: a malformed id went to the
database, which raised a DataError that the global handler turned into a 422 after a round trip and a log line
(agentvault2-a4 traced the lifecycle sweep's DataError noise to it). Now the path's own validation answers 422 and
the handler never runs; a well-formed id still reaches the query as the same string it always was.
RED on the V0476 code: a malformed id there passes validation and the stub database is asked (404, not 422); the
control (a well-formed id reaches the query as a string) passes on both.
"""
from __future__ import annotations

import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_cicd

DID = "did:theprotocol:00000000-0000-4000-8000-000000000001"
GOOD = "3f2b8c1e-5d4a-4f6b-9c0d-1e2f3a4b5c6d"


class _DB:
    def __init__(self):
        self.asked = []

    async def execute(self, stmt, params=None):
        self.asked.append(params)
        return types.SimpleNamespace(first=lambda: None)

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def wired(monkeypatch):
    db = _DB()
    seen = {"service": []}

    async def _permission(_db, _did, _dev_id):
        return None

    async def _update(_db, deployment_id, update, agent_did=None):
        # §MCPTEST30 (2026-10-01): the route names the agent whose permission it checked, and the service binds to it
        seen["service"].append(deployment_id)
        seen.setdefault("agent_did", []).append(agent_did)
        return {"deployment_id": deployment_id, "status": update.get("status")}

    monkeypatch.setattr(agent_cicd.agent_cicd_service, "_get_agent_with_permission", _permission)
    monkeypatch.setattr(agent_cicd.agent_cicd_service, "update_deployment_status", _update)
    app = FastAPI()
    app.include_router(agent_cicd.router, prefix="/api/v1")
    app.dependency_overrides[security.get_current_developer] = lambda: types.SimpleNamespace(id=7, is_admin=False)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False), db, seen


ROUTES = [
    ("get", "/api/v1/agents/{did}/deployments/{dep}", None),
    ("post", "/api/v1/agents/{did}/deployments/{dep}/status", {"status": "running"}),
    ("post", "/api/v1/agents/{did}/deployments/{dep}/logs", {"logs": "a line"}),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
@pytest.mark.parametrize("bad", ["phase5-no-such-deployment", "999999", "not-a-uuid"])
def test_a_malformed_id_is_a_422_before_the_database(wired, method, path, body, bad):
    client, db, seen = wired
    r = getattr(client, method)(path.format(did=DID, dep=bad), **({"json": body} if body is not None else {}))
    assert r.status_code == 422, r.text
    assert "deployment_id" in r.text
    assert db.asked == [] and seen["service"] == []


def test_control_a_well_formed_id_reaches_the_query_as_a_string(wired):
    client, db, seen = wired
    r = client.get(f"/api/v1/agents/{DID}/deployments/{GOOD}")
    assert r.status_code == 404, r.text  # the stub database holds no such deployment
    assert db.asked and db.asked[-1]["deployment_id"] == GOOD and isinstance(db.asked[-1]["deployment_id"], str)
    r = client.post(f"/api/v1/agents/{DID}/deployments/{GOOD}/status", json={"status": "running"})
    assert r.status_code == 200, r.text
    assert seen["service"] == [GOOD] and seen["agent_did"] == [DID]
    r = client.post(f"/api/v1/agents/{DID}/deployments/{GOOD}/logs", json={"logs": "a line"})
    assert r.status_code == 404, r.text
    assert db.asked[-1]["deployment_id"] == GOOD


def test_an_upper_case_id_reaches_the_query_in_its_canonical_form(wired):
    # Postgres compares uuids by value, so this changes no answer; it pins what the query now receives
    client, db, _ = wired
    r = client.post(f"/api/v1/agents/{DID}/deployments/{GOOD.upper()}/logs", json={"logs": "a line"})
    assert r.status_code == 404, r.text
    assert db.asked[-1]["deployment_id"] == str(uuid.UUID(GOOD)) == GOOD
