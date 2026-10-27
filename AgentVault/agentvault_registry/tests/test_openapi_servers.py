"""§DOCSFIX D6-062 / D6-713: the API documentation a registry serves names one server, the registry serving it.

The OpenAPI `servers` list put a relative "/" first (§OPGUIDE-5: every registry ships the same image, so an absolute
first entry pointed every operator's Swagger at another registry) and then named the former network as production:
api.theprotocol.cloud as "Frame A (mainframe, prod)", frame-b, frame-c, the Hetzner frame and two sandboxes. Every
registry's /docs offered them as servers to try requests against. The relative entry is right on every registry, so it
is the only one.
"""
import pytest


@pytest.fixture(scope="module")
def servers():
    from agentvault_registry.main import app
    return app.openapi().get("servers") or []


def test_the_first_server_is_the_registry_serving_the_docs(servers):
    assert servers, "the documentation names no server at all"
    assert servers[0]["url"] == "/"


def test_no_server_is_another_registrys_address(servers):
    absolute = [s["url"] for s in servers if "://" in s["url"]]
    assert absolute == [], f"servers that name a host: {absolute}"


def test_the_descriptions_follow_the_writing_rules(servers):
    for s in servers:
        text = s.get("description", "")
        assert "—" not in text, text
        for word in ("Frame A", "Frame B", "Frame C", "Hetzner", "mainframe"):
            assert word not in text, text
