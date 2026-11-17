"""V0663 (order gwo_d9fa08ed4306f6ceda4fe5f3; session-tester's soak, room seq 3357): the MCP send tool waits longer than
the relay it waits for.

A message posted on a MIRROR of a thread is relayed to the thread's host before the route answers
(services/chat_federation.relay_to_host, called from routers/chat.py): two attempts, each bounded by DELIVER_TIMEOUT_S
(15 s), RELAY_RETRY_S (1 s) between them, so up to 31 s. The MCP tools that post a message called their own registry
with HTTPX_TIMEOUT_SHORT (10 s), so a relay that was slow but succeeded read as a ReadTimeout from the tool (run 103 of
the soak: every relay answered 201 and the reply reached the host). Now:
  - the relay's worst case is one named number (mcp.tools_agent.chat_relay_worst_case_s), derived from the relay's own
    constants, and a test drives the real relay to count its attempts and pauses, so a change to either breaks here;
  - every tool that posts a message (sendChatMessage both ways, postChatProgress) waits chat_send_timeout_s, longer
    than that; a read keeps the short limit;
  - the federation suite's own limit on those calls is longer than the tool's, so the suite never gives up first.
Red on b27f2ebaf: the two numbers do not exist and the tools wait 10 s.
"""
from __future__ import annotations

import asyncio
import pathlib
import re

import httpx
import pytest

from agentvault_registry.mcp import tools_agent as ta
from agentvault_registry.mcp.auth_bridge import MCPAuthContext
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_service as cs


# --- the relay, driven: how long it can take ---------------------------------------------------------------------

def test_the_relay_makes_its_attempts_each_bounded_by_the_delivery_timeout_with_one_pause(monkeypatch):
    posts, sleeps, clients = [], [], []

    class _Hangs:
        async def post(self, url, **kw):
            posts.append(url)
            raise httpx.ReadTimeout("the host did not answer in time")

    def peer_client(target, kwargs):
        clients.append(dict(kwargs))
        return _Hangs()

    async def resolve(db, base):
        return "https://host.example.org:8443"

    async def no_record(*a, **k):
        return None

    async def sleep(s):
        sleeps.append(s)

    from agentvault_registry.routers import guild
    monkeypatch.setattr(guild, "_resolve_peer_url", resolve)
    monkeypatch.setattr(guild, "_fed_client_config", lambda target: ({"timeout": 99.0}, {}))
    monkeypatch.setattr(fed, "peer_client", peer_client)
    monkeypatch.setattr(fed, "_record_relay", no_record)
    monkeypatch.setattr(fed.asyncio, "sleep", sleep)

    class _Conv:
        host_registry, remote_ref = "https://host.example.org", "thread-1"

    with pytest.raises(cs.ChatError) as e:
        asyncio.run(fed.relay_to_host(None, _Conv(), "dev:1", "Ann", "text", "hello", None, "ref-1"))
    assert e.value.status_code == 502 and "NOT sent" in e.value.detail
    assert len(posts) == ta.RELAY_ATTEMPTS, "the relay's attempts changed: chat_relay_worst_case_s must follow"
    assert sleeps == [fed.RELAY_RETRY_S] * (ta.RELAY_ATTEMPTS - 1)
    assert {c["timeout"] for c in clients} == {fed.DELIVER_TIMEOUT_S}, "each attempt is bounded by DELIVER_TIMEOUT_S"


def test_the_send_tool_waits_longer_than_the_relay_worst_case():
    worst = ta.chat_relay_worst_case_s()
    assert worst == ta.RELAY_ATTEMPTS * fed.DELIVER_TIMEOUT_S + (ta.RELAY_ATTEMPTS - 1) * fed.RELAY_RETRY_S == 31.0
    assert ta.chat_send_timeout_s() > worst


# --- the tools that post a message use it --------------------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.timeouts, self.calls = [], []

    def __call__(self, **kw):
        self.timeouts.append(kw.get("timeout"))
        rec = self

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def request(self, method, url, **k):
                rec.calls.append((method, url))
                return httpx.Response(201, json={"ok": True}, request=httpx.Request(method, url))
        return _Client()


AUTH = MCPAuthContext(auth_type="developer", developer_id=6, raw_token="tok")


@pytest.mark.parametrize("call", [
    lambda: ta.chat_send_message(AUTH, "hi", conversation_id="c-1"),
    lambda: ta.chat_send_message(AUTH, "hi", target_agent_did="did:theprotocol:x:1"),
    lambda: ta.chat_post_progress(AUTH, "c-1", "the roll"),
], ids=["send-in-thread", "send-new-thread", "post-progress"])
def test_every_tool_that_posts_a_message_waits_that_long(monkeypatch, call):
    rec = _Recorder()
    monkeypatch.setattr(ta, "mcp_http_client", rec)
    out = asyncio.run(call())
    assert out == {"ok": True}
    assert rec.timeouts == [ta.chat_send_timeout_s()]


def test_a_read_keeps_the_short_limit(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(ta, "mcp_http_client", rec)
    asyncio.run(ta.chat_read_thread(AUTH, "c-1"))
    assert rec.timeouts == [ta.HTTPX_TIMEOUT_SHORT]


# --- the federation suite waits longer than the tool ---------------------------------------------------------------

SUITE = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests" / "federation_suite" / "tests"


def test_the_suite_gives_a_send_more_time_than_the_tool_takes():
    """Each federation-suite file that sends a chat message calls the tool through its own `_call`: that call's limit
    (the rig's default is 30 s) must exceed the tool's, or the suite gives up on a send the tool is still waiting for."""
    files = [p for p in sorted(SUITE.glob("test_*.py")) if '"sendChatMessage"' in p.read_text()]
    assert files, "no suite file sends a chat message: the scan reads nothing"
    for p in files:
        src = p.read_text()
        helper = re.search(r"async def _call\([^\n]*\n(?:[ \t]+[^\n]*\n|\n)*", src)   # the whole body
        assert helper, f"{p.name}: no _call helper"
        m = re.search(r"\.call\(tool, args(?:, timeout=(\d+))?\)", helper.group(0))
        assert m, f"{p.name}: _call does not call the tool as expected"
        limit = int(m.group(1)) if m.group(1) else 30
        assert limit > ta.chat_send_timeout_s(), f"{p.name}: the suite waits {limit} s, the tool {ta.chat_send_timeout_s()} s"
