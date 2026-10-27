"""§MCPTEST30 (2026-10-01) — the federation rig asks a READ once more when the transport lost its answer.

The suite marks a test that lost an answer NOT MEASURED (§MCPSWEEP: a lost answer can read as a refusal as easily as a
failure), and rounds 5 and 6 from EU's console each lost one (an exec that came back rc 0 with no HTTP status marker).
A read asked twice cannot change what it measures; a write is never repeated, so its lost answer stays NOT MEASURED."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests.federation_suite import rig as R


def _answer(payload):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}})
    return 0, f"{body}\n{R._HTTP_MARKER}200--"


def _client(monkeypatch, answers):
    calls = []

    def _exec(container, argv, timeout):
        calls.append(container)
        return answers.pop(0)
    monkeypatch.setattr(R, "exec_in_container", _exec)
    lost = []
    monkeypatch.setattr(R, "record_transport_lost", lambda: lost.append(1))
    c = R.MCPClient(SimpleNamespace(container="sbx-alpha-registry", label="sandbox-A", rpc_path="/mcp/rpc"))

    async def _jwt():
        return "jwt"
    c._ensure_jwt = _jwt
    return c, calls, lost


def test_a_lost_read_is_asked_once_more_and_measured(monkeypatch):
    c, calls, lost = _client(monkeypatch, [(0, ""), _answer({"agents": []})])
    out = asyncio.run(c.call("getMcpStdioBridgeJs"))
    assert len(calls) == 2 and lost == [], "the read came back on the second ask: nothing was lost"
    assert out is not None


def test_a_read_lost_twice_is_not_measured(monkeypatch):
    c, calls, lost = _client(monkeypatch, [(0, ""), (0, "")])
    with pytest.raises(R.MCPError):
        asyncio.run(c.call("getAgentProfile", {"agent_did": "did:theprotocol:x"}))
    assert len(calls) == 2 and lost == [1]


def test_a_lost_write_is_never_repeated(monkeypatch):
    c, calls, lost = _client(monkeypatch, [(0, ""), _answer({"transaction_id": "tx"})])
    with pytest.raises(R.MCPError):
        asyncio.run(c.call("transferUnits", {"recipient_did": "did:theprotocol:r", "amount": "1"}))
    assert len(calls) == 1 and lost == [1]
    assert R.read_only_tool("theprotocol_getMyBalance") is True and R.read_only_tool("transferUnits") is False


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
