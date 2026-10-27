"""§FESUITE (2026-10-01): a pipeline's webhook secret changes only with its address, and the new one is returned once.

`update_pipeline` generated a new `webhook_secret` whenever the payload carried a non-empty `webhook_url`, changed or
not, and returned only `{message, pipeline_id}`: every save of an edited pipeline (the console sends its URL back
unchanged) silently rotated the secret its webhook was configured with, and nobody could ever read the new one.

DB-free: a fake session answers the pipeline lookup and records the UPDATE; the ownership rule and the event emit
are patched.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.services import agent_cicd_service as svc_mod

DID, PID = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-000000000002", "pipe-1"
CURRENT = "https://ci.example.test/hook"


class _DB:
    def __init__(self, current_url=CURRENT, exists=True):
        self.current_url, self.exists = current_url, exists
        self.updates, self.commits = [], 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "SELECT webhook_url FROM agent_pipelines" in sql:
            row = (self.current_url,) if self.exists else None
            return SimpleNamespace(first=lambda: row)
        if "UPDATE agent_pipelines" in sql:
            self.updates.append((sql, dict(params or {})))
        return SimpleNamespace(first=lambda: None, scalar=lambda: None)

    async def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    async def permission(db, agent_did, developer_id):
        return SimpleNamespace(did=agent_did)

    async def emit(*a, **k):
        return None

    monkeypatch.setattr(svc_mod.agent_cicd_service, "_get_agent_with_permission", permission)
    monkeypatch.setattr(svc_mod, "_emit_cicd_event", emit)


async def _update(db, **data):
    return await svc_mod.agent_cicd_service.update_pipeline(db, DID, PID, data, 7)


@pytest.mark.asyncio
async def test_saving_the_same_address_keeps_the_secret():
    db = _DB()
    out = await _update(db, pipeline_name="build", webhook_url=CURRENT)
    sql, params = db.updates[0]
    assert "webhook_secret" not in params and "webhook_secret" not in sql
    assert "webhook_secret" not in out


@pytest.mark.asyncio
async def test_a_new_address_gets_a_new_secret_returned_once():
    db = _DB()
    out = await _update(db, webhook_url="https://ci.example.test/other")
    sql, params = db.updates[0]
    assert params["webhook_secret"] and out["webhook_secret"] == params["webhook_secret"]


@pytest.mark.asyncio
async def test_clearing_the_address_mints_nothing():
    db = _DB()
    out = await _update(db, webhook_url="")
    assert "webhook_secret" not in db.updates[0][1] and "webhook_secret" not in out


@pytest.mark.asyncio
async def test_a_missing_pipeline_is_a_404_and_writes_nothing():
    db = _DB(exists=False)
    with pytest.raises(HTTPException) as ei:
        await _update(db, webhook_url="https://ci.example.test/other")
    assert ei.value.status_code == 404 and db.updates == [] and db.commits == 0
