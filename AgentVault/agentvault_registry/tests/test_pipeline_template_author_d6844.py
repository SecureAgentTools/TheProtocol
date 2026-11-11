"""D6-844 (V0657 (e), agentvault2-d3, 2026-11-06): a pipeline template records its author.

POST /pipeline-templates never set author_did (the router's TODO), so a developer's PAID template paid its buyers'
units to the treasury (agent_cicd_service._pay_for_template's author-NULL branch, the frame's own template) and its
author could not download it without buying it. The payout rule: the price goes to the author agent over the standard
transfer (less the frame's transfer fee); a template with no author is the frame's own and pays the treasury. So:
  - a developer names `author_did`, an active agent the developer created, and it is stored as the author
  - a developer's paid template without one is refused (422) and nothing is created
  - naming an agent the developer did not create is refused (403) and nothing is created
  - a free template may leave it out, as before; an administrator may leave it out for the frame's own
Through FastAPI on the real router, the service's create recorded. RED on v0656/cut's router: the author is dropped,
the paid template without one and the foreign author are both created.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_cicd
from agentvault_registry.security import get_current_developer

PAID = {"name": "deploy", "category": "python", "template_config": {"stages": []}, "price_teg": 5}
DEVELOPER = SimpleNamespace(id=7, is_admin=False)
ADMIN = SimpleNamespace(id=1, is_admin=True)
MINE, THEIRS = "did:theprotocol:mine", "did:theprotocol:someone-elses"


@pytest.fixture
def post(monkeypatch):
    created = []

    async def create_template(db, data, author_did=None):
        created.append({"data": dict(data), "author_did": author_did})
        return {"template_id": "tpl-1", "message": "Template created successfully"}

    async def owned(db, did, developer_id):
        return did == MINE and developer_id == DEVELOPER.id

    monkeypatch.setattr(agent_cicd.agent_cicd_service, "create_template", create_template)
    monkeypatch.setattr(agent_cicd, "author_agent_owned", owned, raising=False)
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


async def test_a_developers_paid_template_records_its_author(post):
    r = await post(DEVELOPER, {**PAID, "author_did": MINE})
    assert r.status_code == 200, r.text
    assert post.created == [{"data": {k: v for k, v in PAID.items()}, "author_did": MINE}]


async def test_a_developers_paid_template_without_an_author_is_refused(post):
    r = await post(DEVELOPER, PAID)
    assert r.status_code == 422 and "author_did" in r.text, r.text
    assert post.created == [], "nothing is created, so no buyer's price goes to the treasury"


async def test_an_agent_the_developer_did_not_create_is_not_its_author(post):
    r = await post(DEVELOPER, {**PAID, "author_did": THEIRS})
    assert r.status_code == 403 and "author_did" in r.text, r.text
    assert post.created == []


async def test_a_free_template_may_leave_the_author_out_as_before(post):
    r = await post(DEVELOPER, {**PAID, "price_teg": 0})
    assert r.status_code == 200, r.text
    assert post.created[0]["author_did"] is None


async def test_an_administrator_may_leave_it_out_for_the_frames_own(post):
    r = await post(ADMIN, PAID)
    assert r.status_code == 200, r.text
    assert post.created[0]["author_did"] is None


def test_the_author_check_asks_for_the_creator_and_an_active_agent():
    import inspect
    src = inspect.getsource(agent_cicd.author_agent_owned)
    assert "creator_developer_id = :dev" in src and "status = 'active'" in src
