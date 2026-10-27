"""§BATCH0911 post-batch residues — each pinned both ways (RED on the pre-change tree).

1. A stored `null` in the frame policy is "unset": `resolve()` keeps the default, so the resolved
   document, `explain()` and the hash agree (it used to write None over the default).
2. The enforcement engine reads the RESOLVED policy, so a partial row's missing section is the
   documented default and not the engine's own inline literal.
3. A refused websocket (bad/expired token) closes with 1008 and nothing escapes the app; `get_db`
   treats the refusal as control flow, not a database error (it logged two tracebacks per reconnect).
4. The vote summary reports the STORED quorum (None when none), never an invented 10.
"""
from __future__ import annotations

import contextlib
import logging
import types

import pytest

from agentvault_registry.services import frame_policy as fp
from agentvault_registry.crud import crud_enforcement as ce


# ── 1. null is unset ─────────────────────────────────────────────────────────────────────────────

def test_a_stored_null_keeps_the_default():
    d = fp.resolve({"governance": {"standard_quorum_percent": None}, "slash_waterfall": None})
    assert d["governance"]["standard_quorum_percent"] == ce.DEFAULT_POLICY_JSON["governance"]["standard_quorum_percent"]
    assert d["slash_waterfall"] == ce.DEFAULT_POLICY_JSON["slash_waterfall"]


def test_the_readout_and_the_document_agree_on_a_null():
    row = {"peer_trust": {"suspend_below": None}}
    rp = fp.ResolvedPolicy(doc=fp.resolve(row), version=3, source="amended", _row_json=row)
    e = rp.explain("peer_trust.suspend_below")
    assert e["source"] == "default"
    assert e["value"] == fp._get(rp.doc, "peer_trust.suspend_below") == 0.30


def test_a_null_row_hashes_like_an_empty_one():
    assert fp.policy_hash(fp.resolve({"slash_waterfall": None})) == fp.policy_hash(fp.resolve({}))


def test_control_a_real_override_still_wins_and_an_unknown_null_is_kept():
    d = fp.resolve({"governance": {"standard_quorum_percent": 15}, "not_a_default_key": None})
    assert d["governance"]["standard_quorum_percent"] == 15
    assert "not_a_default_key" in d and d["not_a_default_key"] is None


# ── 2. the engine reads the resolved document ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_engine_sees_the_default_for_a_section_its_row_lacks(monkeypatch):
    from agentvault_registry.services.enforcement_engine import EnforcementEngine
    partial = types.SimpleNamespace(policy_json={"governance": {"standard_quorum_percent": 10}},
                                    version=2, modified_at=None, modified_by="t")

    async def _row(db):
        return partial
    monkeypatch.setattr(ce, "get_active_policy", _row)
    pol = await EnforcementEngine()._load_policy(None)
    assert pol.get("dispute_escalation") == ce.DEFAULT_POLICY_JSON["dispute_escalation"], (
        "a row written before a section existed must read the documented default, not an absence")
    assert pol["correlation_penalty"] == ce.DEFAULT_POLICY_JSON["correlation_penalty"]


# ── 3. a refused websocket is handled ────────────────────────────────────────────────────────────

def test_a_refused_websocket_closes_1008_and_nothing_escapes():
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from agentvault_registry.routers import websocket as wsr
    from agentvault_registry.database import get_db

    app = FastAPI()
    app.include_router(wsr.router)

    async def _fake_db():
        yield None
    app.dependency_overrides[get_db] = _fake_db

    client = TestClient(app)   # raise_server_exceptions=True: anything escaping the app raises HERE
    # §MTLSHOPS (d), V0377: the token rides the subprotocol (the ?token= form is refused before any decode, with its own
    # reason), so the bad token that proves this refusal path is offered the way a V0367+ console offers it
    with client.websocket_connect("/ws", subprotocols=["theprotocol.v1", "theprotocol.bearer.not-a-jwt"]) as w:
        with pytest.raises(WebSocketDisconnect) as closed:
            w.receive_text()
    assert closed.value.code == 1008
    assert closed.value.reason == "invalid_token"


@pytest.mark.asyncio
async def test_get_db_treats_a_websocket_refusal_as_control_flow(caplog):
    from fastapi import WebSocketException
    from agentvault_registry.database import get_db

    gen = get_db()
    await gen.__anext__()
    with caplog.at_level(logging.ERROR, logger="agentvault_registry.database"):
        with pytest.raises(WebSocketException):
            await gen.athrow(WebSocketException(code=1008, reason="invalid_token"))
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "a websocket refusal is not a database failure and must not log a traceback")


# ── 4. the vote summary does not invent a quorum ─────────────────────────────────────────────────

class _Res:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v

    def scalar(self):
        return self.v


class _DB:
    def __init__(self, values):
        self.values = list(values)

    async def execute(self, *a, **k):
        return _Res(self.values.pop(0))


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, 20.0])
async def test_the_vote_summary_reports_the_stored_quorum(stored):
    from agentvault_registry.crud import crud_governance as cg
    import datetime as dt
    proposal = types.SimpleNamespace(id=7, title="t", status="VOTING", proposal_type="standard",
                                     quorum_percent=stored, pass_percent=50.0,
                                     end_timestamp=dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc))
    s = await cg.get_proposal_vote_summary(_DB([proposal, 3, 1, 4]), 7)
    assert s["quorum_percent"] == stored
