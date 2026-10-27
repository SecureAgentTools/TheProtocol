"""§FEFRAME W3 (V0504): which token each route takes comes from the FastAPI dependency tree (core/auth_tiers.py), and
the console's copy of it (src/services/api/authTiers.generated.json) and the OpenAPI labels follow the same walk.

Controls: the routes the old rules got wrong (`POST /agora/orders` and `POST /agents/spawn` labelled developer;
`/developers/me/exchange/portfolio` sent an AGENT token by a substring match) and the FastAPI 0.141 nesting that made a
plain `isinstance(route, APIRoute)` walk find 0 agent routes.
"""
import json
import os

import pytest

from agentvault_registry.core import auth_tiers

_FE_CANDIDATES = (
    "/w/fe/authTiers.generated.json",  # staged by the CI step
    os.path.join(os.path.dirname(__file__), "..", "src", "agentvault_registry", "static", "new_registry_frontend",
                 "src", "services", "api", "authTiers.generated.json"),
)


@pytest.fixture(scope="module")
def app():
    from agentvault_registry.main import app as _app
    return _app


@pytest.fixture(scope="module")
def tiers(app):
    return {(r["method"], r["path"]): r["tier"] for r in auth_tiers.tier_map(app)}


def test_the_walk_sees_the_nested_routers(app):
    # FastAPI 0.141 keeps included routers nested: the walk must reach their routes, not only the app's own ~50
    assert sum(1 for _ in auth_tiers.api_routes(app)) > 1000


def test_the_routes_the_old_rules_got_wrong(tiers):
    assert tiers.get(("POST", "/api/v1/agora/orders")) == "agent"
    assert tiers.get(("POST", "/api/v1/agents/spawn")) == "agent"
    assert tiers.get(("POST", "/api/v1/teg/transfer")) == "agent"
    assert tiers.get(("GET", "/api/v1/exchange/portfolio")) == "agent"
    # the §COCKPITBOOK collision: a developer route whose path CONTAINS an agent route's path
    assert ("GET", "/api/v1/developers/me/exchange/portfolio") not in tiers
    assert ("GET", "/api/v1/developers/me") not in tiers
    # either token: the read-actor resolvers
    assert tiers.get(("GET", "/api/v1/chat/conversations")) == "either"
    # the owner rail itself is a DEVELOPER route (a developer mints the agent token)
    assert ("POST", "/api/v1/developers/me/agents/{agent_did}/session-token") not in tiers


def test_template_intersection_is_the_router_s_own_notion():
    ti = auth_tiers.templates_intersect
    assert ti("/api/v1/agents/{did}", "/api/v1/agents/spawn")          # a literal beside a template: one URL hits both
    assert ti("/api/v1/agents/{did}/x", "/api/v1/agents/spawn/x")
    assert not ti("/api/v1/agents/spawn", "/api/v1/agents/act-token")   # two literals never meet
    assert not ti("/api/v1/agents/{did}", "/api/v1/agents/{did}/logs")  # different depth
    assert ti("/static/{p:path}", "/static/a/b/c")                      # a path tail swallows the rest
    assert ti("/api/v1/x/{a}", "/api/v1/x/{b}")


def test_the_document_is_in_registration_order_and_carries_the_shadowing_routes(app):
    doc = auth_tiers.document(app)
    codes = {code for (_m, _p, code) in doc["routes"]}
    assert codes <= {"a", "e", "d"} and doc["counts"]["a"] > 100
    order = [(m, p) for (m, p, _t) in auth_tiers.operations(app)]
    idx = [order.index((m, p)) for (m, p, _c) in doc["routes"]]
    assert idx == sorted(idx), "the console takes the FIRST match, so the copy must keep FastAPI's order"
    # every `d` row is there because it can meet an agent/either template of the same method
    tiered = [(m, p) for (m, p, c) in doc["routes"] if c != "d"]
    for (m, p, c) in doc["routes"]:
        if c == "d":
            assert any(m == m2 and auth_tiers.templates_intersect(p, p2) for (m2, p2) in tiered), (m, p)


def test_the_consoles_copy_matches_the_running_app(app):
    path = next((c for c in _FE_CANDIDATES if os.path.exists(c)), None)
    if path is None:
        pytest.skip("authTiers.generated.json not present (the image ships dist, not src): gate NOT run")
    with open(path, encoding="utf-8") as f:
        committed = json.load(f)
    live = auth_tiers.document(app)
    assert committed == live, (
        "the console's auth-tier map is stale: regenerate it with "
        "`python -m agentvault_registry.core.auth_tiers --write <new_registry_frontend>/src/services/api/"
        "authTiers.generated.json` (in an image with this source) and commit it; "
        f"committed counts {committed.get('counts')} vs live {live['counts']}")


def test_the_openapi_labels_follow_the_same_walk(app):
    app.openapi_schema = None
    try:
        schema = app.openapi()
    finally:
        app.openapi_schema = None

    def schemes(path, verb):
        return {k for e in (schema["paths"][path][verb].get("security") or []) for k in e}

    assert "AgentJWT" in schemes("/api/v1/agora/orders", "post")
    assert "AgentJWT" in schemes("/api/v1/agents/spawn", "post")
    assert "AgentJWT" not in schemes("/api/v1/developers/me", "get")
    assert "DeveloperJWT" in schemes("/api/v1/developers/me", "get")
    either = schemes("/api/v1/chat/conversations", "get")
    assert {"AgentJWT", "DeveloperJWT"} <= either
    labelled = sum(1 for p, ops in schema["paths"].items() for v, op in ops.items()
                   if isinstance(op, dict) and any("AgentJWT" in e for e in (op.get("security") or [])))
    assert labelled > 100, f"only {labelled} operations labelled AgentJWT (the hand list labelled 14)"
