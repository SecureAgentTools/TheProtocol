"""§MCPTEST30 (V0652, agentvault2-d3, 2026-11-01): earn_support_played_v0652, a support ticket played through on a pair,
every notice counted (order (ai) gwo_b13813d486f28d456a324293; sessionlogs2026/FINDINGS_2026-10-31_SUPPORT_TICKET_EU.md).

Offline: a scripted target answers as V0652's support routes do, or, with v0651=True, as V0651's did when session-tester's
EU run found the defects: a desk reply wrote three notices to the requester (one of them the raw support.in_progress), a
resolve two, a reopen left no status row in the thread, and the desk was told nothing durable. RED on V0651's behaviour:
all four rows fail. Each defect planted alone turns its own row red, and only it.
"""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_ad_support_played as S

REQ, DESK = "req-dev-jwt", "runner-dev-jwt"
REQ_ID = 601
TID = 41
CONV = "conv-support-0123abcd"


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                   "structuredContent": obj}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


class _World:
    def __init__(self, v0651: bool = False, **defects: bool):
        self.old, self.d = v0651, defects
        self.feed: Dict[str, List[Dict[str, Any]]] = {REQ: [], DESK: []}
        self.nid = itertools.count(100)
        self.seq = itertools.count(1)
        self.status: Optional[str] = None
        self.msgs: List[Dict[str, Any]] = []
        self.calls: List[Tuple[str, Dict[str, Any], str]] = []
        self.owner_closed = False

    def note(self, who: str, type_key: str, title: str, body: str, click: str) -> None:
        self.feed[who].insert(0, {"id": next(self.nid), "type_key": type_key, "title": title, "body": body,
                                  "click": click, "read": False})

    def row(self, kind: str, body: str, ptype: str, sid: Any) -> None:
        self.msgs.append({"seq": next(self.seq), "kind": kind, "body": body, "sender_ptype": ptype, "sender_id": sid})

    def tell_requester(self, title: str, body: str, raw_extra: int = 0) -> None:
        self.note(REQ, "support.reply", title, body, f"/ui#/pocket/ourchat/{CONV}")
        for i in range(raw_extra):   # V0651: the chat fan-out's notices beside the typed one, one of them a raw key
            self.note(REQ, "chat.message", "Support", "support.in_progress" if i == 0 else body, f"/ui#/pocket/ourchat/{CONV}")

    async def public(self, tool: str, args: Dict[str, Any], jwt: str = "", timeout: int = 15):
        self.calls.append((tool, dict(args), jwt))
        if tool == "theprotocol_submitSupportTicket":
            assert jwt == REQ
            self.status = "open"
            self.row("text", args["message"], "developer", REQ_ID)
            if not (self.old or self.d.get("no_desk_new")):
                self.note(DESK, "support.desk", f"New support ticket #{TID}", args["message"],
                          f"/ui#/admin/chatdesk?ticket={TID}")
            return True, _body({"id": TID, "status": "open"}), "201"
        if tool == "theprotocol_replySupportTicket":
            assert jwt == REQ and args["ticket_id"] == str(TID)
            reopened = self.status in ("resolved", "closed")
            self.row("text", args["message"], "developer", REQ_ID)
            if reopened:
                self.status = "open"
                if not (self.old or self.d.get("no_reopen_row")):
                    self.row("system", "support.open", "developer", REQ_ID)
                if self.d.get("reopen_row_by_rail"):
                    self.row("system", "support.open", "system", "support")
            if not (self.old or self.d.get("no_desk_reopen")):
                self.note(DESK, "support.desk", f"Ticket #{TID} reopened by the requester" if reopened
                          else f"Ticket #{TID}: the requester replied", args["message"],
                          f"/ui#/admin/chatdesk?ticket={TID}")
            return True, _body({"id": TID, "status": self.status}), "200"
        if tool == "theprotocol_getSupportTicketDetail":
            return True, _body({"id": TID, "status": self.status, "messages": []}), "200"
        raise AssertionError(f"public: {tool}")

    async def admin(self, tool: str, args: Dict[str, Any], jwt: str = "", timeout: int = 15):
        self.calls.append((tool, dict(args), jwt))
        if tool == "theprotocol_supportReplyTicket":
            assert jwt == DESK and args["ticket_id"] == TID
            self.status = "in_progress"
            self.row("text", args["message"], "system", "support")
            extra = 2 if (self.old or self.d.get("triple_reply")) else 0
            words = args["message"] if not self.d.get("reply_without_words") else "Support answered"
            self.tell_requester("Support replied to your ticket", words, raw_extra=extra)
            return True, _body({"id": TID, "status": self.status}), "200"
        if tool == "theprotocol_supportCloseTicket":
            assert jwt == DESK
            self.status = args["status"]
            self.row("system", f"support.{args['status']}", "system", "support")
            self.tell_requester(f"Your ticket #{TID} is {args['status']}", "The desk marked it resolved.",
                                raw_extra=1 if self.old else 0)
            return True, _body({"id": TID, "status": self.status}), "200"
        if tool == "theprotocol_adminRequest":
            who, ep, method = args.get("developer_jwt"), args["endpoint"], args["method"]
            if (method, ep) == ("GET", "/api/v1/notifications/feed"):
                return True, _body({"status_code": 200, "response": {"available": True,
                                                                     "entries": list(self.feed[who])}}), "200"
            if (method, ep) == ("GET", f"/api/v1/chat/conversations/{CONV}/messages"):
                assert who == REQ
                return True, _body({"status_code": 200, "response": {"messages": list(self.msgs)}}), "200"
            if (method, ep) == ("POST", f"/api/v1/support/tickets/{TID}/status"):
                assert who == REQ and args["body"] == {"status": "closed"}
                self.owner_closed = True
                return True, _body({"status_code": 200, "response": {"id": TID, "status": "closed"}}), "200"
        raise AssertionError(f"admin: {tool} {args.get('endpoint')}")


class _Throwaways:
    closed = 0

    def __init__(self, rpc, parse, bag, tag):
        pass

    async def developer(self, role: str, verify: bool = True) -> Dict[str, Any]:
        assert role == "support-requester"
        return {"developer_id": REQ_ID, "access_token": REQ, "email": "req@probe.invalid"}

    async def close(self) -> None:
        type(self).closed += 1


def _run(w: _World, monkeypatch, *, pair: bool = True) -> Dict[str, dict]:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    if pair:
        monkeypatch.setenv(S.EPHEMERAL_ENV, "true")
    else:
        monkeypatch.delenv(S.EPHEMERAL_ENV, raising=False)
    monkeypatch.setattr(S, "Throwaways", _Throwaways)
    monkeypatch.setattr(S, "WAIT_S", 0.05)
    monkeypatch.setattr(S, "SETTLE_S", 0.0)
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt=DESK, developer_id="1")
    bag.rpc_admin = w.admin                # type: ignore[attr-defined]
    out: Dict[str, dict] = {}
    asyncio.run(S.lifecycle_earn_support_played(w.public, _parse, bag, out))
    return out


def _ok(row: Optional[dict]) -> bool:
    return bool(row) and bool(row.get("healthy")) and not row.get("skip_reason") and not row.get("fail_reason")


def test_it_is_registered():
    assert "earn_support_played_v0652" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]


def test_v0652_plays_through_clean(monkeypatch):
    w = _World()
    out = _run(w, monkeypatch)
    for name in S.ROWS:
        assert _ok(out.get(name)), (name, out.get(name))
    assert w.owner_closed, "the requester closes its own ticket at the end"
    assert _Throwaways.closed >= 1


def test_v0651_is_red_on_every_row(monkeypatch):
    out = _run(_World(v0651=True), monkeypatch)
    for name in S.ROWS:
        row = out.get(name) or {}
        assert not row.get("healthy") and str(row.get("fail_reason") or "").startswith("BUG-FIND: support:"), (name, row)
    assert "3 new notice(s)" in out[S.ONE_PER_ACT]["fail_reason"]
    assert "support.in_progress" in out[S.ONE_PER_ACT]["fail_reason"]


@pytest.mark.parametrize("defect,row,needle", [
    ("no_desk_new", S.DESK_NEW, "no support.desk entry for ticket #41"),
    ("triple_reply", S.ONE_PER_ACT, "left the requester 3 new notice(s)"),
    ("reply_without_words", S.ONE_PER_ACT, "does not carry its first words"),
    ("no_reopen_row", S.REOPEN_ROW, "holds no support.open row"),
    ("no_desk_reopen", S.DESK_REOPEN, "no support.desk entry for the reopen of #41"),
])
def test_each_defect_turns_its_own_row_red(monkeypatch, defect, row, needle):
    out = _run(_World(**{defect: True}), monkeypatch)
    assert not out[row].get("healthy") and needle in str(out[row].get("fail_reason")), out[row]
    for other in set(S.ROWS) - {row}:
        assert _ok(out.get(other)), (defect, other, out.get(other))


def test_a_reopen_row_by_the_rail_is_not_the_requesters(monkeypatch):
    out = _run(_World(no_reopen_row=True, reopen_row_by_rail=True), monkeypatch)
    assert "authored by system:support, not by the requester" in str(out[S.REOPEN_ROW].get("fail_reason"))


def test_a_standing_frame_files_nothing_and_says_why(monkeypatch):
    w = _World()
    out = _run(w, monkeypatch, pair=False)
    assert w.calls == [] and set(out) == set(S.ROWS)
    assert all(S.EPHEMERAL_ENV in str(r.get("skip_reason")) for r in out.values())


def test_the_pure_rules():
    assert S.raw_keys([{"title": "x", "body": "support.in_progress"}]) == ["support.in_progress"]
    assert S.raw_keys([{"title": "Support replied", "body": "we are on it"}]) == []
    assert S.thread_of("/ui#/pocket/ourchat/conv-support-0123abcd") == CONV
    assert S.thread_of("/ui#/settings?tab=support&ticket=41") is None
    assert S.newest_id([]) == 0 and S.newest_id([{"id": 3}, {"id": "7"}]) == 7
    assert S.one_notice_verdict("reply", []) is not None
    assert S.one_notice_verdict("reply", [{"type_key": "support.reply", "title": "t", "body": "the words"}], "words") is None


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
