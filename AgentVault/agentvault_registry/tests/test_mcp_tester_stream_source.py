"""§MCPTEST30 (V0541): the MCP tester's live EventStore panel streams the TARGET's store.

The panel built its websocket URL from the console's own EVENT_STORE_URL, so on EU's console, whose sweeps run against
sbx-alpha, the card headed "Sandbox EventStore — live" streamed EU's own production store (its agents' heartbeats) while
the sweep's events landed in sbx-alpha's store. The target's store is the one the emission check already polls
(`_EMIT_ES_URL`: API_TEST_EVENT_STORE_URL, else derived from API_TEST_TARGET_URL); the console's own store is the
fallback only where no target store can be named. The panel is told the store's host:port, never its URL (a token rides
the query).
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from agentvault_registry.routers import mcp_tester as mt


def test_the_panel_streams_the_target_store_with_the_key_the_emission_check_reads_it_with(monkeypatch):
    monkeypatch.setattr(mt, "_EMIT_ES_URL", "http://sbx-alpha-event-store:8200")
    monkeypatch.setattr(mt, "_EMIT_ES_KEY", "k-target")
    monkeypatch.setenv("EVENT_STORE_URL", "https://eu-nginx-event-store:8443")
    assert mt._es_stream_source() == ("http://sbx-alpha-event-store:8200", "target")
    u = urlsplit(mt._build_es_ws_url())
    assert (u.scheme, u.hostname, u.port, u.path) == ("ws", "sbx-alpha-event-store", 8200, "/ws/events")
    assert parse_qs(u.query) == {"token": ["k-target"]}


def test_the_console_own_store_is_the_fallback_only_without_a_target_store(monkeypatch):
    """The control: with no target store named, the old path (the node's own store) still answers."""
    monkeypatch.setattr(mt, "_EMIT_ES_URL", "")
    monkeypatch.setenv("EVENT_STORE_URL", "https://eu-nginx-event-store:8443")
    monkeypatch.setenv("EVENTSTORE_WS_AUTH_MODE", "shared-secret")
    monkeypatch.setenv("EVENT_STORE_INTERNAL_API_KEY", "k-own")
    assert mt._es_stream_source() == ("https://eu-nginx-event-store:8443", "own")
    u = urlsplit(mt._build_es_ws_url())
    assert (u.scheme, u.hostname, u.port) == ("wss", "eu-nginx-event-store", 8443)
    assert parse_qs(u.query) == {"token": ["k-own"]}


def test_a_target_store_without_a_key_is_dialled_without_a_token(monkeypatch):
    monkeypatch.setattr(mt, "_EMIT_ES_URL", "http://sbx-alpha-event-store:8200")
    monkeypatch.setattr(mt, "_EMIT_ES_KEY", "")
    assert mt._build_es_ws_url() == "ws://sbx-alpha-event-store:8200/ws/events"


def test_the_host_the_panel_and_the_log_see_carries_no_url_query():
    assert mt._es_stream_host("ws://sbx-alpha-event-store:8200/ws/events?token=secret") == "sbx-alpha-event-store:8200"
    assert mt._es_stream_host("https://eu-nginx-event-store:8443") == "eu-nginx-event-store:8443"
    assert mt._es_stream_host("") == "?"


async def test_the_console_states_its_own_target_and_posture(monkeypatch):
    """§MCPTEST30 (V0541): GET /flows answers this console's target and whether it is a sandbox. The page read both from
    the newest run in History that had a summary, and a console suite run there (summary.target "Sandbox Alpha", no
    is_sandbox) made it print "Refusing to run ... not a sandbox endpoint" over a sweep running against sbx-alpha."""
    from types import SimpleNamespace
    monkeypatch.setattr(mt, "API_TEST_TARGET_URL", "http://sbx-alpha-registry:8000")
    out = await mt.list_flows(current_developer=SimpleNamespace(is_admin=True))
    assert out["target"] == "http://sbx-alpha-registry:8000"
    assert out["is_sandbox"] is mt._is_sandbox_target() is True
    assert out["flows"] and out["default"]
    # the control: a production target reads as one
    monkeypatch.setattr(mt, "API_TEST_TARGET_URL", "https://api.theprotocol.cloud")
    out = await mt.list_flows(current_developer=SimpleNamespace(is_admin=True))
    assert out["is_sandbox"] is False
