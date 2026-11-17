"""V0664 "Migrate a system", M4 (order gwo_e97a483512cfaf2151f17b7a): the library's routes, its flag, its table and its
MCP tools.

  flag      WORKFLOW_TEMPLATES_ENABLED (default false): every route answers 503 while it is off, and the public
            registry-config field workflow_templates_enabled says the same (one reading of the flag: the frame_kit pattern)
  routes    /api/v1/workflow-templates (list, detail, versions, kit, create, versions, publish, patch, fork, purchase,
            instantiate, certified); a refusal answers its status with {"code", "detail"}; the anonymous kit download is
            rate-limited (slowapi: the route declares request and response)
  migration 0228_workflow_templates: the four tables, CHECKs on the closed words, the one certified count per agent,
            agent_workflows' three provenance columns; additive
  MCP       public listWorkflowTemplates, getWorkflowTemplate; agent tier getWorkflowTemplateVersion,
            purchaseWorkflowTemplate, forkWorkflowTemplate, instantiateWorkflowTemplate, createWorkflowTemplate,
            publishWorkflowTemplateVersion: dispatch, schemas and both tier sets (CLAUDE.md PART 11)
Red on v0663/cut b7ca684e9.
"""
from __future__ import annotations

import asyncio
import pathlib

import httpx
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
PUBLIC_TOOLS = ("theprotocol_listWorkflowTemplates", "theprotocol_getWorkflowTemplate")
AGENT_TOOLS = ("theprotocol_getWorkflowTemplateVersion", "theprotocol_purchaseWorkflowTemplate",
               "theprotocol_forkWorkflowTemplate", "theprotocol_instantiateWorkflowTemplate",
               "theprotocol_createWorkflowTemplate", "theprotocol_publishWorkflowTemplateVersion",
               "theprotocol_listMyWorkflowTemplates")


def _app(store=None):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import workflow_templates as route
    from agentvault_registry.services import workflow_templates as wt
    app = FastAPI()
    app.include_router(route.router)

    async def get_db():
        yield None
    app.dependency_overrides[database.get_db] = get_db
    if store is not None:
        route.store_for = lambda db: store          # noqa: E731  the test's store
    return app, wt


def _call(app, method, path, body=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.request(method, path, json=body)
    return asyncio.run(go())


def test_off_by_default_every_route_answers_503(monkeypatch):
    monkeypatch.delenv("WORKFLOW_TEMPLATES_ENABLED", raising=False)
    app, wt = _app()
    assert wt.templates_enabled() is False
    for method, path in (("GET", "/api/v1/workflow-templates"), ("GET", "/api/v1/workflow-templates/wtpl_x"),
                         ("GET", "/api/v1/workflow-templates/wtpl_x/versions/1/kit")):
        r = _call(app, method, path)
        assert r.status_code == 503, (path, r.status_code)


def test_the_public_registry_config_reads_the_same_flag():
    main = (SRC / "main.py").read_text()
    assert '"workflow_templates_enabled": _workflow_templates_enabled()' in main
    assert "from agentvault_registry.services.workflow_templates import templates_enabled as _workflow_templates_enabled" in main
    assert "workflow_templates as workflow_templates_router" in main and "include_router(workflow_templates_router.router)" in main


def test_a_refusal_answers_its_status_and_code(monkeypatch):
    monkeypatch.setenv("WORKFLOW_TEMPLATES_ENABLED", "true")
    from tests.test_workflow_templates_library_v0664 import FakeStore, make
    s = FakeStore()
    paid = make(s, pricing="purchase", price="5")
    free = make(s, slug="free")
    app, _ = _app(s)
    r = _call(app, "GET", f"/api/v1/workflow-templates/{paid}/versions/1/kit")
    assert r.status_code == 402 and r.json()["code"] == "payment_required"
    r = _call(app, "GET", f"/api/v1/workflow-templates/{free}/versions/1/kit")
    assert r.status_code == 200 and r.json()["files"]["README.md"]
    r = _call(app, "GET", "/api/v1/workflow-templates")
    assert r.status_code == 200 and {i["id"] for i in r.json()["items"]} == {paid, free}
    assert "files" not in str(r.json())


def test_the_routes_their_gates_and_the_rate_limit():
    src = (SRC / "routers" / "workflow_templates.py").read_text()
    for method, path in (("get", ""), ("get", "/mine"), ("get", "/{tid}"), ("get", "/{tid}/versions/{n}"), ("get", "/{tid}/versions/{n}/kit"),
                         ("post", ""), ("post", "/{tid}/versions"), ("post", "/{tid}/versions/{n}/publish"),
                         ("patch", "/{tid}"), ("post", "/{tid}/fork"), ("post", "/{tid}/purchase"),
                         ("post", "/{tid}/instantiate"), ("post", "/{tid}/certified")):
        assert f'@router.{method}("/api/v1/workflow-templates{path}"' in src, (method, path)
    # gwo_2dc9f93f (session-lead seq 3957): any agent drafts and forks; publishing passes the reputation bond gate instead
    assert "contract.template.publish" not in src, "the workflow-template routes need no permission an owner cannot grant"
    i = src.index('"/api/v1/workflow-templates/{tid}/versions/{n}/kit"')
    head = src[src.rindex("@limiter.limit", 0, i + 400) if "@limiter.limit" in src[:i + 400] else i:i + 600]
    assert "@limiter.limit" in head and "request: Request" in head and "response: Response" in head


def test_the_migration_adds_the_tables_and_the_provenance():
    mig = (ALEMBIC / "0228_workflow_templates.py").read_text()
    assert 'revision = "0228_workflow_templates"' in mig and len("0228_workflow_templates") <= 32
    for table in ("workflow_templates", "workflow_template_versions", "workflow_template_purchases",
                  "workflow_template_uses"):
        assert f'"{table}"' in mig, table
    for col in ("template_id", "template_version", "template_content_hash"):
        assert f'"agent_workflows", sa.Column("{col}"' in mig, col
    for check in ("visibility IN ('private', 'org', 'unlisted', 'public')", "pricing_model IN ('free', 'purchase')",
                  "fork_share_bps BETWEEN 0 AND 5000", "kind IN ('kit', 'instantiate', 'certified')"):
        assert check in mig, check
    assert "uq_wtpl_uses_certified" in mig and "kind = 'certified'" in mig


def test_the_mcp_tools_are_wired_in_their_three_places():
    from agentvault_registry.mcp import audit, server, tool_categories
    schemas = {t.get("name") for t in server.ALL_TOOL_SCHEMAS if isinstance(t, dict)}
    for name in PUBLIC_TOOLS + AGENT_TOOLS:
        assert name in server.TOOL_DISPATCH and name in schemas, name
        assert name.replace("theprotocol_", "") in tool_categories.PUBLIC_TOOL_CATEGORIES, name
    for name in PUBLIC_TOOLS:          # tier 1 by absence from TIER2/TIER3, and named in the audit's tier 1 set
        assert name not in server.TIER2_TOOLS and name not in server.TIER3_TOOLS and name in audit._TIER_1_TOOLS, name
    for name in AGENT_TOOLS:
        assert name in server.TIER2_TOOLS and name in server.AUTH_REQUIRED_TOOLS and name in audit._TIER_2_TOOLS, name


def test_mine_is_its_own_route_not_a_template_called_mine(monkeypatch):
    """gwo_ef4d9981: registered before /{tid} (FastAPI matches in registration order), so /mine is never read as an id."""
    import types
    monkeypatch.setenv("WORKFLOW_TEMPLATES_ENABLED", "true")
    from agentvault_registry import security
    from tests.test_workflow_templates_library_v0664 import FakeStore, OWNER, make
    src = (SRC / "routers" / "workflow_templates.py").read_text()
    assert src.index('"/api/v1/workflow-templates/mine"') < src.index('"/api/v1/workflow-templates/{tid}"')
    s = FakeStore()
    tid = make(s, visibility="private", publish=False)
    app, _ = _app(s)
    app.dependency_overrides[security.get_current_actor_for_read_optional] = lambda: {
        "kind": "agent", "agent_did": OWNER, "agent": types.SimpleNamespace(creator_developer_id=1, organization_id="org-1")}
    r = _call(app, "GET", "/api/v1/workflow-templates/mine")
    assert r.status_code == 200 and [i["id"] for i in r.json()["items"]] == [tid], r.text
    app.dependency_overrides[security.get_current_actor_for_read_optional] = lambda: None
    r = _call(app, "GET", "/api/v1/workflow-templates/mine")
    assert r.status_code == 401 and r.json()["code"] == "signed_in"


def test_a_fork_posted_with_no_body_at_all_answers_201_and_names_the_slug_it_chose(monkeypatch):
    """gwo_04e1334c (M8 step 4): the CLI and the MCP tool may send no slug, or no body; the route derives the slug."""
    import types
    monkeypatch.setenv("WORKFLOW_TEMPLATES_ENABLED", "true")
    from agentvault_registry import security
    from tests.test_workflow_templates_library_v0664 import FakeStore, OWNER, PARENT_AUTHOR, make
    s = FakeStore()
    parent = make(s, by=PARENT_AUTHOR, slug="crm-to-pg")
    app, _ = _app(s)
    app.dependency_overrides[security.get_current_agent] = lambda: types.SimpleNamespace(did=OWNER, creator_developer_id=1, organization_id=None)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return [await c.post(f"/api/v1/workflow-templates/{parent}/fork"),
                    await c.post(f"/api/v1/workflow-templates/{parent}/fork", json={})]
    bare, empty = asyncio.run(go())
    assert bare.status_code == 201 and bare.json()["slug"] == "crm-to-pg-fork", bare.text
    assert empty.status_code == 201 and empty.json()["slug"] == "crm-to-pg-fork-2", empty.text


def test_the_mcp_fork_tool_asks_no_slug_and_sends_none_when_none_is_given(monkeypatch):
    from agentvault_registry.mcp import tools_workflow_templates as tools
    schema = next(t for t in tools.WORKFLOW_TEMPLATE_AGENT_TOOL_SCHEMAS if t["name"] == "theprotocol_forkWorkflowTemplate")["inputSchema"]
    assert schema["required"] == ["template_id"]
    sent = {}

    async def fake(auth, method, path, json_body=None, **kw):
        sent.update(method=method, path=path, body=json_body)
        return {"ok": True}
    monkeypatch.setattr(tools, "_chat_request", fake)
    monkeypatch.setattr(tools, "require_agent_auth", lambda auth: None)
    asyncio.run(tools.fork_workflow_template(object(), "wtpl_x"))
    assert sent["body"] == {} and sent["path"].endswith("/wtpl_x/fork")
