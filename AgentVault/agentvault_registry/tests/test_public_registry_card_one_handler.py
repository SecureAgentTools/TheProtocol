"""§DOCSFIX D6-710: GET /api/v1/public/registry-card has one handler, and the API documentation describes that one.

Two handlers shared the path: routers/registry_card.py's (`peer`, an envelope around the card), included first, and a
later one in main.py (`registry`, the bare card). Starlette answers with the first route that matches, so the second
was never reached; FastAPI's OpenAPI document keeps the last operation it sees for a path and method, so every
registry's /docs described the handler that never answered.
"""
import pytest

from agentvault_registry.core import auth_tiers

PATH = "/api/v1/public/registry-card"


@pytest.fixture(scope="module")
def app():
    from agentvault_registry.main import app as _app
    return _app


def test_one_route_serves_the_path(app):
    handlers = [r.endpoint for r in auth_tiers.api_routes(app)
                if getattr(r, "path_format", None) == PATH and "GET" in (r.methods or ())]
    assert len(handlers) == 1, [f"{h.__module__}.{h.__name__}" for h in handlers]
    assert handlers[0].__module__ == "agentvault_registry.routers.registry_card"


def test_the_documentation_describes_the_handler_that_answers(app):
    op = app.openapi()["paths"][PATH]["get"]
    assert [p["name"] for p in op.get("parameters", [])] == ["peer"]
