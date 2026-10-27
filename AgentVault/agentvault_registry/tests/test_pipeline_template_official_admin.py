"""D6-843 (2026-10-26, agentvault2-66): only an administrator marks a pipeline template official.

POST /pipeline-templates took `is_official` from any developer's body and stored it, so any developer could publish an
"official" template (GET /pipeline-templates and the MCP getPipelineTemplates show the flag; the console's create never
sends it). A non-admin's is_official=true is now refused with a 403 naming the field, and nothing is created; a non-admin
without it, or with it false, creates as before; an administrator may set it, on an admin credential (security.
admin_credential: an admin's scoped key does not reach it, D6-057). Through FastAPI on the real router, the service's
create recorded. RED on c7531675's router: the non-admin's and the scoped key's official templates are created.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_cicd
from agentvault_registry.security import get_current_developer

BODY = {"name": "deploy", "category": "python", "template_config": {"stages": []}, "price_teg": 0}
DEVELOPER = SimpleNamespace(id=7, is_admin=False)
ADMIN = SimpleNamespace(id=1, is_admin=True)


@pytest.fixture
def post(monkeypatch):
    created = []

    async def create_template(db, data, author_did=None):
        created.append(dict(data))
        return {"template_id": "tpl-1", "message": "Template created successfully"}

    monkeypatch.setattr(agent_cicd.agent_cicd_service, "create_template", create_template)
    app = FastAPI()
    app.include_router(agent_cicd.router, prefix="/api/v1")
    caller = {}

    async def _db():
        yield None

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_developer] = lambda: caller["dev"]

    async def do(dev, body):
        caller["dev"] = dev
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post("/api/v1/pipeline-templates", json=body)

    do.created = created
    return do


async def test_a_developer_may_not_mark_a_template_official(post):
    r = await post(DEVELOPER, {**BODY, "is_official": True})
    assert r.status_code == 403 and "is_official" in r.text, r.text
    assert post.created == [], "nothing is created"


@pytest.mark.parametrize("extra", [{}, {"is_official": False}])
async def test_a_developer_creates_an_ordinary_template_as_before(post, extra):
    r = await post(DEVELOPER, {**BODY, **extra})
    assert r.status_code == 200, r.text
    assert len(post.created) == 1 and not post.created[0].get("is_official")


async def test_an_administrator_may_mark_a_template_official(post):
    r = await post(ADMIN, {**BODY, "is_official": True})
    assert r.status_code == 200, r.text
    assert post.created[0]["is_official"] is True


@pytest.mark.parametrize("scopes,status", [(["mcp:tools"], 403), (["*"], 200)])
async def test_an_administrators_scoped_key_does_not_reach_it(post, scopes, status):
    # admin_credential (D6-057): a key without mcp:admin (a paired phone's, an MCP OAuth key) is not an admin request
    token = security._PRESENTED_KEY_SCOPES.set(scopes)
    try:
        r = await post(ADMIN, {**BODY, "is_official": True})
    finally:
        security._PRESENTED_KEY_SCOPES.reset(token)
    assert r.status_code == status, r.text
    assert len(post.created) == (1 if status == 200 else 0)
