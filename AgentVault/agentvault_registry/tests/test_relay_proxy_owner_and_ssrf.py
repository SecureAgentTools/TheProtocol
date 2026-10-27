"""§FESUITE (2026-10-01): the CI/CD relay proxy acts only for the agent's owner and never dials an internal address.

`GET /{agent_did}/relay/status` and `POST /{agent_did}/relay/action` (relay_start / relay_stop / relay_restart)
required a signed-in developer and checked nothing else: any developer reached any agent's relay through the
registry, and the registry POSTed to whatever the agent card declared, an internal docker hostname included. Now:
the CI/CD service's own ownership rule first (`_get_agent_with_permission`), then the buy rail's SSRF guard
(`assert_callable_endpoint`); a relay that does not answer is a 502 whose detail carries no exception text.

DB-free: the route functions are called directly; the ownership rule, the card lookup, DNS and the HTTP client are
patched, and every refusal asserts that NO outbound call was made.
"""
import socket
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import agent_cicd
from agentvault_registry.services import service_purchase

OWNER, STRANGER = SimpleNamespace(id=7), SimpleNamespace(id=8)
DID = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-000000000001"


class _Calls:
    def __init__(self, fail=False):
        self.posted, self.fail = [], fail

    def client(self, *a, **k):
        calls = self

        class _C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None):
                calls.posted.append(url)
                if calls.fail:
                    raise ConnectionError("connect to 10.1.2.3:8000 refused")
                return SimpleNamespace(status_code=200, json=lambda: {"result": {"content": [{"text": '{"healthy": true}'}]}})
        return _C()


@pytest.fixture
def wire(monkeypatch):
    import httpx

    state = {"url": "https://relay.example.test/a2a", "calls": _Calls(), "public": True}

    async def permission(db, agent_did, developer_id):
        if developer_id != OWNER.id:
            raise HTTPException(status_code=403, detail="Pipeline operations on this agent require ownership or organization membership")

    async def relay_url(agent_did, db):
        url = state["url"]
        for suffix in ("/a2a/", "/a2a", "/"):
            if url and url.endswith(suffix):
                return url[:-len(suffix)]
        return url

    def resolve(host, *a, **k):
        ip = "93.184.216.34" if state["public"] and host == "relay.example.test" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    monkeypatch.setattr(agent_cicd.agent_cicd_service, "_get_agent_with_permission", permission)
    monkeypatch.setattr(agent_cicd, "_get_relay_url", relay_url)
    monkeypatch.setattr(service_purchase.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: state["calls"].client())
    return state


@pytest.mark.asyncio
async def test_a_stranger_is_refused_before_any_call(wire):
    for call in (agent_cicd.relay_status(agent_did=DID, developer=STRANGER, db=None),
                 agent_cicd.relay_action(agent_did=DID, body={"tool": "relay_stop"}, developer=STRANGER, db=None)):
        with pytest.raises(HTTPException) as ei:
            await call
        assert ei.value.status_code == 403
    assert wire["calls"].posted == []


@pytest.mark.asyncio
async def test_an_internal_or_plain_http_endpoint_is_never_dialled(wire):
    for url, public in (("http://sbx-alpha-registry:8000/a2a", True), ("https://relay.example.test/a2a", False)):
        wire["url"], wire["public"] = url, public
        with pytest.raises(HTTPException) as ei:
            await agent_cicd.relay_status(agent_did=DID, developer=OWNER, db=None)
        assert ei.value.status_code == 422
    assert wire["calls"].posted == []


@pytest.mark.asyncio
async def test_the_owner_reaches_a_public_relay(wire):
    assert await agent_cicd.relay_status(agent_did=DID, developer=OWNER, db=None) == {"healthy": True}
    assert await agent_cicd.relay_action(agent_did=DID, body={"tool": "relay_restart"}, developer=OWNER, db=None) == {"healthy": True}
    assert wire["calls"].posted == ["https://relay.example.test/mcp/relay/rpc"] * 2


@pytest.mark.asyncio
async def test_a_silent_relay_is_a_502_without_its_exception_text(wire):
    wire["calls"] = _Calls(fail=True)
    with pytest.raises(HTTPException) as ei:
        await agent_cicd.relay_status(agent_did=DID, developer=OWNER, db=None)
    assert ei.value.status_code == 502
    assert "10.1.2.3" not in str(ei.value.detail)


@pytest.mark.asyncio
async def test_an_unknown_tool_is_refused_first(wire):
    with pytest.raises(HTTPException) as ei:
        await agent_cicd.relay_action(agent_did=DID, body={"tool": "rm -rf"}, developer=OWNER, db=None)
    assert ei.value.status_code == 400
    assert wire["calls"].posted == []
