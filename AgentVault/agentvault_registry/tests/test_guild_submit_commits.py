"""V0650 (f) (2026-10-31, agentvault2-14): a Guild delivery links its commits, and the verify view lists them.

Order gwo_754cf6912ebece4f1487363a. POST /api/v1/guild/orders/{oid}/submit (and MCP guildSubmitWork) takes an optional
typed list `commits` of {repo, commit}, up to 20: a commit id is 7 to 64 hex characters, a repository is named without
credentials (the commons EvidenceItem precedent). The list is stored with the delivery as `deliverable.commits`, so the
existing rules carry it: the parties read it in the order detail (the verify view), anyone else sees `deliverable:
null`, `deliverable_withheld` and the key name only. A deliverable that already carries a `commits` key, sent together
with the field, is a 422.

The route functions run directly over a recording fake database. Cases marked BASE fail on V0649 (6c1f036b), where
SubmitIn silently drops the field (pydantic's extra='ignore'), so nothing is validated and nothing is stored, and the MCP
tool has no such argument; the test_control_* cases pass on both trees.
"""
from __future__ import annotations

import asyncio
import json
import types

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

POSTER = "did:theprotocol:eu.test:poster"
WORKER = "did:theprotocol:eu.test:worker"
STRANGER = "did:theprotocol:eu.test:stranger"
OID = "gwo_test0f02"
C1 = {"repo": "https://git.example.invalid/team/project", "commit": "a1b2c3d4"}
C2 = {"repo": "team/project", "commit": "0123456789abcdef0123456789abcdef01234567"}


class _Result:
    def __init__(self, rows=(), rowcount=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar(self):
        r = self.first()
        if r is None:
            return None
        return r[0] if isinstance(r, (tuple, list)) else r

    def mappings(self):
        return self


class _Db:
    def __init__(self, handlers=()):
        self.handlers = list(handlers)
        self.calls = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, params or {}))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, params or {}) if callable(res) else res
        return _Result([], rowcount=0)

    async def commit(self):
        return None

    def params_of(self, needle):
        return [p for s, p in self.calls if needle in s]


@pytest.fixture
def g(monkeypatch):
    """The guild router with every side effect stubbed, over ONE stateful order the fake database writes."""
    from agentvault_registry.routers import guild
    from agentvault_registry.background_tasks import reactor_helpers as rh
    from agentvault_registry.background_tasks import push_notify
    state = {"id": OID, "poster_did": POSTER, "title": "Fix the board", "spec": "", "bounty": "3.0",
             "currency": "ECU", "fee_bps": 250, "status": "awarded", "worker_did": WORKER,
             "worker_home_registry": None, "deliverable": None, "intended_worker_did": None}

    async def _nothing(*a, **k):
        return None

    async def _load(db, oid):
        return dict(state)
    monkeypatch.setenv("GUILD_ENABLED", "true")
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", _nothing)
    monkeypatch.setattr(push_notify, "notify_agent_owners", _nothing)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(guild, "_load", _load)
    monkeypatch.setattr(guild.guild_contract_mirror, "sync_from_order", _nothing)
    guild._state = state
    return guild


def _db(state):
    def _store(sql, params):
        state["deliverable"], state["status"] = json.loads(params["d"]), "submitted"
        return _Result([], rowcount=1)
    return _Db([("SET status='submitted', deliverable", _store),
                ("SELECT COALESCE(MAX(seq),0)+1", _Result([(3,)])),
                # the poster's developer owns the poster agent (the parties' view)
                ("FROM agents WHERE did = ANY", lambda sql, p: _Result([(1,)]) if p.get("dev") == 7 else _Result([]))])


POSTER_DEV = types.SimpleNamespace(id=7, is_admin=False)


async def test_a_delivery_links_its_commits_and_the_posters_view_lists_them(g):
    # BASE: the commits are dropped, so the stored deliverable has none
    db = _db(g._state)
    await g.submit(OID, g.SubmitIn(deliverable={"text": "done"}, commits=[C1, C2]),
                   agent=types.SimpleNamespace(did=WORKER), db=db)
    assert g._state["deliverable"] == {"text": "done", "commits": [C1, C2]}
    out = await g.order_detail(OID, db=db, dev=POSTER_DEV)
    assert out["order"]["deliverable"]["commits"] == [C1, C2] and not out["order"].get("deliverable_withheld")


async def test_a_stranger_reads_that_commits_were_linked_never_which(g):
    # BASE: no 'commits' key reaches the stored deliverable
    db = _db(g._state)
    await g.submit(OID, g.SubmitIn(deliverable={"text": "done"}, commits=[C1]),
                   agent=types.SimpleNamespace(did=WORKER), db=db)
    for dev in (None, types.SimpleNamespace(id=99, is_admin=False)):
        o = (await g.order_detail(OID, db=db, dev=dev))["order"]
        assert o["deliverable"] is None and o["deliverable_withheld"] is True
        assert "commits" in o["deliverable_keys"] and C1["commit"] not in json.dumps(o)


async def test_control_a_delivery_without_commits_is_stored_as_given(g):
    # control: passes on both trees
    db = _db(g._state)
    await g.submit(OID, g.SubmitIn(deliverable={"uri": "https://example.invalid/report"}),
                   agent=types.SimpleNamespace(did=WORKER), db=db)
    assert g._state["deliverable"] == {"uri": "https://example.invalid/report"}


@pytest.mark.parametrize("bad", [
    {"repo": "team/project", "commit": "HEAD"},
    {"repo": "team/project", "commit": "abc"},
    {"repo": "team/project", "commit": "a" * 65},
    {"repo": "https://alice@git.example.invalid/team/project", "commit": "a1b2c3d4"},
    {"repo": "https://alice:x@git.example.invalid/team/project", "commit": "a1b2c3d4"},
    {"repo": "https://git.example.invalid/team/project?access=1", "commit": "a1b2c3d4"},
    {"repo": "", "commit": "a1b2c3d4"},
    {"repo": "team project", "commit": "a1b2c3d4"},
    {"commit": "a1b2c3d4"},
])
def test_a_commit_id_is_hex_and_a_repository_carries_no_credentials(bad):
    # BASE: SubmitIn ignores the field, so nothing is refused
    from agentvault_registry.routers import guild
    with pytest.raises(ValidationError):
        guild.SubmitIn(deliverable={"text": "done"}, commits=[bad])


def test_more_than_twenty_commits_are_refused():
    # BASE: nothing is refused
    from agentvault_registry.routers import guild
    with pytest.raises(ValidationError):
        guild.SubmitIn(deliverable={}, commits=[C1] * 21)
    assert len(guild.SubmitIn(deliverable={}, commits=[C1] * 20).commits) == 20


async def test_commits_are_given_once(g):
    # BASE: the doubled key is stored as the caller wrote it
    db = _db(g._state)
    with pytest.raises(HTTPException) as e:
        await g.submit(OID, g.SubmitIn(deliverable={"text": "done", "commits": ["x"]}, commits=[C1]),
                       agent=types.SimpleNamespace(did=WORKER), db=db)
    assert e.value.status_code == 422 and "commits" in str(e.value.detail)
    assert not db.params_of("SET status='submitted', deliverable") and g._state["deliverable"] is None


async def test_control_only_the_awarded_worker_delivers(g):
    # control: passes on both trees
    db = _db(g._state)
    with pytest.raises(HTTPException) as e:
        await g.submit(OID, g.SubmitIn(deliverable={"text": "done"}), agent=types.SimpleNamespace(did=STRANGER), db=db)
    assert e.value.status_code == 403 and g._state["deliverable"] is None


# ─────────────────────────────── MCP ───────────────────────────────

@pytest.fixture
def sent(monkeypatch):
    from agentvault_registry.mcp import tools_guild as G
    calls = []

    async def _post(path, payload, token):
        calls.append((path, payload))
        return {"ok": True}
    monkeypatch.setattr(G, "_guild_post", _post)
    return calls


def _agent_auth():
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext
    return MCPAuthContext(auth_type="agent", agent_did=WORKER, agent_id=1, raw_token="phase6-agent-token")


def test_guildSubmitWork_sends_the_commits(sent):
    # BASE: TypeError on the new keyword
    from agentvault_registry.mcp import tools_guild as G
    asyncio.run(G.guild_submit_work(_agent_auth(), order_id=OID, deliverable_text="done", commits=[C1]))
    assert sent[-1] == (f"/api/v1/guild/orders/{OID}/submit", {"deliverable": {"text": "done"}, "commits": [C1]})


def test_guildSubmitWork_takes_commits_alone_or_as_json_text(sent):
    # BASE: TypeError on the new keyword
    from agentvault_registry.mcp import tools_guild as G
    asyncio.run(G.guild_submit_work(_agent_auth(), order_id=OID, commits=[C1, C2]))
    assert sent[-1][1] == {"deliverable": {}, "commits": [C1, C2]}
    asyncio.run(G.guild_submit_work(_agent_auth(), order_id=OID, deliverable_uri="u", commits=json.dumps([C2])))
    assert sent[-1][1] == {"deliverable": {"uri": "u"}, "commits": [C2]}


@pytest.mark.parametrize("bad", ["not json", json.dumps({"repo": "r", "commit": "a1b2c3d4"}), 5])
def test_guildSubmitWork_refuses_commits_that_are_not_a_list_before_any_request(sent, bad):
    # BASE: TypeError on the new keyword
    from agentvault_registry.mcp import tools_guild as G
    out = asyncio.run(G.guild_submit_work(_agent_auth(), order_id=OID, deliverable_text="done", commits=bad))
    assert "commits must be a list" in out["error"] and sent == []


def test_control_guildSubmitWork_with_nothing_to_deliver_is_refused(sent):
    # control: passes on both trees (the refusal keeps its old words as its start)
    from agentvault_registry.mcp import tools_guild as G
    out = asyncio.run(G.guild_submit_work(_agent_auth(), order_id=OID))
    assert out["error"].startswith("Provide deliverable_uri and/or deliverable_text") and sent == []


def test_guildSubmitWork_advertises_commits():
    # BASE: the property is absent
    from agentvault_registry.mcp import tools_guild as G
    from agentvault_registry.mcp import server
    for schemas in (G.GUILD_TOOL_SCHEMAS, server.ALL_TOOL_SCHEMAS):
        s = next(x for x in schemas if x["name"] == "theprotocol_guildSubmitWork")
        prop = s["inputSchema"]["properties"]["commits"]
        assert prop["type"] == "array" and prop["maxItems"] == 20
        items = prop["items"]
        assert items["type"] == "object" and set(items["required"]) == {"repo", "commit"}
        assert items["properties"]["commit"]["pattern"] == "^[0-9a-fA-F]{7,64}$"
