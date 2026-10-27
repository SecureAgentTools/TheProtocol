"""§FEFRAME W4 (V0509): the retired frames' stats aliases are gone.

/api/v1/public/eventstore-stats-b and -c read EVENT_STORE_B_URL / EVENT_STORE_C_URL, set on no live registry, so every call
(and every boot's prewarm) logged a warning and answered zeros. The console has read each frame's stats at the keyed
route since V0503, and the MCP tool that wrapped -b left in V0508. Pinned: neither alias is routed, the keyed route and
this frame's own route stay, the prewarm asks only this frame's store, and the API tester's catalog no longer lists a
route the registry stopped serving (a sweep would read the 404 as a defect).
"""
import inspect

import pytest

from agentvault_registry.core import auth_tiers


@pytest.fixture(scope="module")
def app():
    from agentvault_registry.main import app as _app
    return _app


def test_the_aliases_are_not_routed(app):
    paths = {c.path_format for c in auth_tiers.api_routes(app)}
    assert len(paths) > 1000                                          # the walk reached the nested routers (the control)
    assert "/api/v1/public/eventstore-stats-b" not in paths
    assert "/api/v1/public/eventstore-stats-c" not in paths
    assert "/api/v1/public/eventstore-stats" in paths                 # this frame's own
    assert "/api/v1/public/eventstore-stats/{key}" in paths           # each frame's, by its manifest key (V0503)


def test_no_mcp_tool_calls_an_alias():
    from agentvault_registry.mcp import tools_discovery
    src = inspect.getsource(tools_discovery)
    assert "/api/v1/public/eventstore-stats-b" not in src and "/api/v1/public/eventstore-stats-c" not in src


def test_the_boot_prewarm_asks_only_this_frames_store():
    from agentvault_registry import main
    src = inspect.getsource(main)
    i = src.index("async def _prewarm_es_stats():")
    body = src[i:src.index("asyncio.create_task(_prewarm_es_stats())", i)]
    assert "await public_eventstore_stats()" in body
    assert "public_eventstore_stats_b" not in body and "public_eventstore_stats_c" not in body


def test_the_api_tester_catalog_lists_no_alias():
    from agentvault_registry.api_tests.endpoints_registry import endpoints_registry
    eps = endpoints_registry.get_all_endpoints()
    flat = [e for v in (eps.values() if isinstance(eps, dict) else [eps]) for e in (v if isinstance(v, list) else [])]
    paths = {e.get("path") for e in flat if isinstance(e, dict)}
    assert "/public/eventstore-stats" in paths                        # the control: the catalog was read
    assert "/public/eventstore-stats-b" not in paths and "/public/eventstore-stats-c" not in paths
