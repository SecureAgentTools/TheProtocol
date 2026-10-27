"""§MCPTEST30 V0645 (agentvault2-66, 2026-10-26): every broadcast the MCP tester composes is a direct notice to the run's
own developer.

V0644's operator read (2026-10-26 15:48-15:56Z, both sandbox operators) composed four broadcasts to everyone ("MCP
tester: a broadcast of its own" from earned_ad_platform, "phase6 sweep" from the admin sweep), and the federation's
fan-out copied each onto both sandbox frames' consoles (foreign-<id>) while agentvault2-5b's console proof ran there. The
route has taken a developer-targeted notice since V0397 (shown to its developer alone, never copied to a peer, §SECFIX
D6-305), and the API tester's sweep has sent one since V0640; the MCP tool composeBroadcast could not, so it now takes
target_developer_id, and both tester call sites address the run's own developer. Where the run names none, nothing is
composed and the rows say why. RED on V0644 (cd78fd1f2): the tool drops the field, both call sites send a broadcast to
everyone, and a run with no developer id still composes.
"""
import asyncio
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests.contracts import earned_ad_platform as P
from agentvault_registry.api_tests.contracts import earned_fixtures as ef
from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as M
from agentvault_registry.mcp import tools_admin

COMPOSE = "theprotocol_composeBroadcast"


# ── the tool ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_tool_sends_a_direct_notice_when_asked(monkeypatch):
    sent = []

    async def admin_post(auth, path, json_body=None, **kw):
        sent.append((path, dict(json_body or {})))
        return {"id": 1}

    monkeypatch.setattr(tools_admin, "_admin_post", admin_post)
    asyncio.run(tools_admin.compose_broadcast(None, title="t", body="b", target_developer_id=7))
    asyncio.run(tools_admin.compose_broadcast(None, title="t", body="b"))
    assert sent[0] == ("/api/v1/admin/broadcasts", {"title": "t", "body": "b", "broadcast_type": "info",
                                                    "send_email": False, "requires_ack": False,
                                                    "target_developer_id": 7})
    assert "target_developer_id" not in sent[1][1], "without it the broadcast is the route's default, as before"


def test_the_tool_advertises_the_field():
    (schema,) = [s for s in tools_admin.ADMIN_TOOL_SCHEMAS if s.get("name") == COMPOSE]
    prop = schema["inputSchema"]["properties"]["target_developer_id"]
    assert prop["type"] == "integer" and prop["minimum"] == 1


# ── the lifecycle's own broadcast ───────────────────────────────────────────────────────────────────────────────────

def _lifecycle(monkeypatch, developer_id):
    calls, unmeasured = [], []

    async def admin_read(bag, parse, tool, args):
        calls.append((tool, dict(args)))
        return True, {"id": 42}, "200"

    async def effect(*a, **k):
        return True, {}

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(P, "_admin_read", admin_read)
    monkeypatch.setattr(P, "effect", effect)
    monkeypatch.setattr(P, "_broadcast_row", nothing)
    monkeypatch.setattr(P, "_settle_retracted", nothing)
    monkeypatch.setattr(P, "effect_unmeasured", lambda outcomes, tool, why: unmeasured.append((tool, why)))
    bag = SimpleNamespace(developer_id=developer_id)
    asyncio.run(P._broadcast(None, None, bag, {}))
    return calls, unmeasured


def test_the_lifecycles_broadcast_is_a_direct_notice_to_the_runs_developer(monkeypatch):
    calls, unmeasured = _lifecycle(monkeypatch, "7")
    composes = [args for tool, args in calls if tool == COMPOSE]
    assert len(composes) == 1 and composes[0]["target_developer_id"] == 7 and unmeasured == []


@pytest.mark.parametrize("developer_id", [None, "", "admin", "0"])
def test_a_run_with_no_developer_of_its_own_composes_nothing(monkeypatch, developer_id):
    calls, unmeasured = _lifecycle(monkeypatch, developer_id)
    assert [t for t, _a in calls if t == COMPOSE] == []
    assert [t for t, _w in unmeasured] == list(P.TOOLS[:3])
    assert all("not the run's to send" in w for _t, w in unmeasured)


# ── the admin sweep's broadcast ─────────────────────────────────────────────────────────────────────────────────────

def _sweep(monkeypatch, developer_id):
    calls, unmeasured = [], []

    async def exec_step(rpc, parse, tool, tier, args, jwt, outcomes, **kw):
        calls.append((tool, dict(args or {})))
        return False, {}

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(M, "_exec_step", exec_step)
    monkeypatch.setattr(M, "_projection_snapshot_step", nothing)
    monkeypatch.setattr(M._ef, "refusal_step", nothing)
    monkeypatch.setattr(M._ef, "unmeasured", lambda outcomes, tool, tier, why: unmeasured.append((tool, why)))
    bag = SimpleNamespace(developer_id=developer_id, developer_jwt="d", sentinel_did="did:theprotocol:sentinel")
    asyncio.run(M.lifecycle_admin_destructive_safe(None, None, bag, {}))
    return calls, unmeasured


def test_the_sweeps_broadcast_is_a_direct_notice_to_the_runs_developer(monkeypatch):
    calls, _u = _sweep(monkeypatch, "7")
    composes = [args for tool, args in calls if tool == COMPOSE]
    assert len(composes) == 1 and composes[0]["target_developer_id"] == 7


def test_a_sweep_with_no_developer_of_its_own_composes_nothing(monkeypatch):
    calls, unmeasured = _sweep(monkeypatch, None)
    assert [t for t, _a in calls if t == COMPOSE] == []
    assert [w for t, w in unmeasured if t == COMPOSE] and "not the run's to send" in [w for t, w in unmeasured
                                                                                         if t == COMPOSE][0]


def test_own_developer_id_reads_only_a_positive_number():
    assert [ef.own_developer_id(SimpleNamespace(developer_id=v)) for v in ("7", 7, None, "", "admin", "0", "-3")] == \
           [7, 7, None, None, None, None, None]
