"""§DOCSFIX D6-108 (2026-10-16): GET /api/v1/public/registry-card has one handler, the one that answers.

Two handlers were registered for the path: routers/registry_card.py's (query parameter `peer`, an envelope around the
card), mounted first and so the one that answers, and a second in main.py (parameter `registry`, the bare card) that
never ran but was the one the OpenAPI document described. The globe asked `?registry=<peer>` of the live route, which
ignored it and answered this registry's own envelope for every peer. The dead handler is gone (the OpenAPI describes
`peer` now) and the globe asks `peer` (pinned in the console's tests).
"""
from __future__ import annotations

import pytest

from agentvault_registry.core import auth_tiers

PATH = "/api/v1/public/registry-card"


@pytest.fixture(scope="module")
def app():
    from agentvault_registry.main import app as _app
    return _app


def test_one_handler_serves_the_path(app):
    routes = [r for r in auth_tiers.api_routes(app) if r.path_format == PATH and "GET" in (r.methods or set())]
    assert len(routes) == 1, [getattr(r.endpoint, "__module__", "?") for r in routes]
    assert routes[0].endpoint.__module__.endswith("routers.registry_card")


def test_the_openapi_describes_the_parameter_that_works(app):
    params = {p["name"] for p in app.openapi()["paths"][PATH]["get"].get("parameters", [])}
    assert "peer" in params and "registry" not in params, params
