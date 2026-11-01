"""§MCPTEST30 (V0652, tester batch 4, agentvault2-d3, Guild order gwo_39e726e914785352bfdc9557): earn_chat_tools_v0652,
the ten chat tools V0652 adds ((w) the phone set, (aa) the progress card, (ac) the room's status board), earned on an
organization room of the run's own, only where the target is torn down after its run (MCP_TESTER_EPHEMERAL_TARGET).

Offline: a scripted world answers as the V0652 routes do (an organization, an invited member, its room opened by the
owner, the agent and the member, unread counts per principal, a read mark, a shared file served to participants only,
approval requests listed per room and waiting per decider, a progress card its author keeps current until its verdict
closes it, a board written against its revision by the owner or a named member). Each defect a rule guards is planted
once and must turn its own row red. RED on V0651 (the module and its rows do not exist).
"""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_ad_chat_tools as C

DEV, MEMBER, STRANGER, AGENT = "dev-jwt", "member-jwt", "stranger-jwt", "agent-jwt"
DID = "did:theprotocol:sandbox-a:tools-agent"
ROOM = "conv-org-room-7"


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                   "structuredContent": obj}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


def _no(status: str, error: str):
    return False, _body({"error": error}), status


class _World:
    def __init__(self, **defects: bool):
        self.d = defects
        self.calls: List[Tuple[str, Dict[str, Any], str]] = []
        self.opened: List[str] = []
        self.org_deleted = False
        self.unread = {DEV: 0, MEMBER: 0}
        self.seq = itertools.count(1)
        self.files: Dict[str, str] = {}
        self.approvals: Dict[str, str] = {}
        self.card: Optional[Dict[str, Any]] = None
        self.board = {"text": "", "rev": 0}
        self.member_joined = False

    def who(self, args: Dict[str, Any], jwt: str) -> str:
        return args.get("agent_jwt") or jwt

    async def public(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args), jwt))
        me = self.who(args, jwt)
        if tool == "theprotocol_createOrganization":
            return True, _body({"id": "org-7", "name": args["name"]}), "200"
        if tool == "theprotocol_assignAgentToOrg":
            assert args == {"org_id": "org-7", "agent_did": DID} and jwt == DEV
            return True, _body({"ok": True}), "200"
        if tool == "theprotocol_inviteOrganizationMember":
            assert jwt == DEV and args["role"] == "member"
            return True, _body({"token": "inv-token-1", "expires_at": "2026-11-08T00:00:00Z"}), "200"
        if tool == "theprotocol_acceptOrgInvitation":
            assert jwt == MEMBER and args == {"token": "inv-token-1"}
            self.member_joined = True
            return True, _body({"ok": True}), "200"
        if tool == "theprotocol_deleteOrganization":
            self.org_deleted = True
            return True, _body({"deleted": True}), "200"
        if tool == "theprotocol_sendChatMessage":
            assert me == AGENT and args["conversation_id"] == ROOM and "kind" not in args
            if not self.d.get("unread_stuck"):
                self.unread[DEV] += 1
                self.unread[MEMBER] += 1
            return True, _body({"message": {"id": "m-line", "seq": next(self.seq)}, "my_state": "active"}), "201"
        if tool == C.UNREAD:
            return True, _body({"messages": self.unread.get(me, 0), "threads": 1}), "200"
        if tool == C.MARK:
            assert me == DEV and args["conversation_id"] == ROOM
            if not self.d.get("mark_ignored"):
                self.unread[DEV] = 0
            return True, _body({"conversation_id": ROOM, "read_seq": args["seq"]}), "200"
        if tool == C.ATTACH:
            text = self.files.get(args["attachment_id"])
            if text is None:
                return _no("404", "getChatAttachment returned HTTP 404: no such attachment")
            if me == STRANGER and not self.d.get("file_leaks"):
                return _no("403", "getChatAttachment returned HTTP 403: not a participant in this conversation")
            if self.d.get("file_mangled"):
                text = text.upper()
            return True, _body({"attachment_id": args["attachment_id"], "name": "f.txt", "bytes": len(text),
                                "text": text, "truncated": False}), "200"
        if tool == "theprotocol_requestChatApproval":
            assert me == AGENT
            aid = f"apr_{len(self.approvals) + 1}"
            self.approvals[aid] = "pending"
            return True, _body({"approval": {"id": aid, "status": "pending"}, "duplicate": False}), "201"
        if tool == C.LISTA:
            items = [{"id": a, "status": s} for a, s in self.approvals.items() if s == "pending"]
            can = me == DEV or (me == MEMBER and bool(self.d.get("member_decides")))
            return True, _body({"conversation_id": ROOM, "items": items, "can_decide": can}), "200"
        if tool == C.WAITING:
            if me == AGENT and not self.d.get("agent_waits"):
                return False, _body({"error": "This tool requires developer authentication."}), "401"
            mine = me == DEV or (me == MEMBER and self.d.get("member_waits"))
            items = [{"id": a} for a, s in self.approvals.items() if s == "pending"] if mine else []
            return True, _body({"items": items, "count": len(items)}), "200"
        if tool == "theprotocol_decideChatApproval":
            assert jwt == DEV and args["decision"] == "deny"
            for a in args["approval_ids"]:
                self.approvals[a] = "denied"
            return True, _body({"decided": args["approval_ids"]}), "200"
        if tool == C.POSTP:
            assert me == AGENT and args["state"] == "running" and len(args["steps"]) == 2
            self.card = {"id": "m-card", "author": AGENT, "state": "running", "rev": 0, "updates": []}
            return True, _body({"message": {"id": "m-card", "seq": next(self.seq)}, "my_state": "active"}), "201"
        if tool == C.UPDP:
            c = self.card
            assert c and args["message_id"] == c["id"]
            if me != c["author"] and not self.d.get("anyone_updates"):
                return _no("403", "updateChatProgress returned HTTP 403: only whoever posted this card updates it")
            if c["state"] in ("passed", "failed", "cancelled") and not self.d.get("closed_updates"):
                return _no("409", f"updateChatProgress returned HTTP 409: this card is closed ({c['state']}): post a "
                                  f"new card")
            c["state"] = args["state"]
            c["rev"] += 1
            if not self.d.get("history_lost"):
                c["updates"].append({"rev": c["rev"], "by": me})
            return True, _body({"message": {"id": c["id"]}, "changed": True}), "200"
        if tool == C.HIST:
            c = self.card or {}
            return True, _body({"message_id": c.get("id"), "card_rev": 0 if self.d.get("history_lost") else c["rev"],
                                "updates": c.get("updates", [])}), "200"
        if tool == C.BOARD:
            can = me == DEV or (me == MEMBER and bool(self.d.get("member_edits")))
            return True, _body({**self.board, "can_edit": can, "conversation_id": ROOM}), "200"
        if tool == C.WBOARD:
            if me != DEV and not self.d.get("member_edits"):
                return _no("403", "updateChatBoard returned HTTP 403: the room's owner, or a member the owner named, "
                                  "keeps its status board")
            if args["base_rev"] != self.board["rev"] and not self.d.get("stale_wins"):
                return _no("409", f"updateChatBoard returned HTTP 409: the board changed since you read it (now "
                                  f"revision {self.board['rev']}): read it again")
            self.board = {"text": args["text"], "rev": self.board["rev"] + 1}
            return True, _body({"board": self.board, "changed": True}), "200"
        raise AssertionError(tool)

    async def admin(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        assert tool == "theprotocol_adminRequest" and args["method"] == "POST"
        assert args["endpoint"] == "/api/v1/chat/org-rooms/org-7/open"
        self.opened.append(args["developer_jwt"])
        return True, _body({"status_code": 201, "ok": True, "response": {"conversation_id": ROOM}}), "200"

    async def http_in(self, method: str, path: str, *, body: bytes = b"", content_type: str = "", bearer: str = "",
                      **_kw: Any):
        assert method == "POST" and path == f"/api/v1/chat/conversations/{ROOM}/attachments" and bearer == DEV
        assert content_type.startswith("multipart/form-data; boundary=")
        boundary = content_type.split("boundary=", 1)[1]
        part = body.split(f"--{boundary}".encode())[1]
        assert b'name="file"' in part and b"Content-Type: text/plain" in part
        text = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0].decode()
        self.files["att_1"] = text
        return "201", json.dumps({"attachment_id": "att_1", "filename": "f.txt", "mime": "text/plain"})


class _Throwaways:
    closed = 0
    made: List[str] = []

    def __init__(self, rpc, parse, bag, tag):
        pass

    async def developer(self, role: str, verify: bool = True) -> Dict[str, Any]:
        type(self).made.append(role)
        token = {"chat-tools-owner": DEV, "chat-tools-member": MEMBER, "chat-tools-stranger": STRANGER}[role]
        return {"developer_id": len(type(self).made), "access_token": token, "email": f"{role}@probe.invalid"}

    async def agent(self, dev: Dict[str, Any], label: str = "") -> Dict[str, Any]:
        return {"did": DID, "agent_jwt": AGENT, "owner_jwt": DEV}

    async def close(self) -> None:
        type(self).closed += 1


def _run(w: _World, monkeypatch, *, transport: bool = True) -> Dict[str, dict]:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    monkeypatch.setattr(C, "Throwaways", _Throwaways)
    _Throwaways.made = []
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    bag.rpc_admin = w.admin                # type: ignore[attr-defined]
    if transport:
        bag.http_in_target = w.http_in     # type: ignore[attr-defined]
    out: Dict[str, dict] = {}
    asyncio.run(C.lifecycle_earn_chat_tools(w.public, _parse, bag, out))
    return out


def _ok(row: Optional[dict]) -> bool:
    return bool(row) and bool(row.get("healthy")) and not row.get("skip_reason") and not row.get("fail_reason")


REFUSALS = ("refusal: getChatAttachment a file in a room the caller is not in",
            "refusal: listWaitingChatApprovals an agent's own token",
            "refusal: updateChatProgress a card someone else posted",
            "refusal: updateChatProgress a closed card",
            "refusal: updateChatBoard a write against a revision already replaced",
            "refusal: updateChatBoard a member the owner did not name")


def test_it_is_registered():
    assert "earn_chat_tools_v0652" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]


def test_a_standing_frame_asks_nothing_and_says_why(monkeypatch):
    monkeypatch.delenv(C.EPHEMERAL_ENV, raising=False)
    w = _World()
    out = _run(w, monkeypatch)
    assert w.calls == [] and sorted(out) == sorted(list(C.TIERS) + list(C.ROWS))
    assert all(C.EPHEMERAL_ENV in str(r.get("skip_reason")) for r in out.values())


def test_a_pair_earns_all_ten_holds_every_rule_and_leaves_nothing(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    _Throwaways.closed = 0
    w = _World()
    out = _run(w, monkeypatch)
    for tool in C.TIERS:
        assert _ok(out.get(tool)), (tool, out.get(tool))
    for row in C.ROWS:
        assert _ok(out.get(row)), (row, out.get(row))
    for name in REFUSALS:
        assert out.get(name) and out[name]["healthy"], (name, out.get(name))
    assert w.opened == [DEV, AGENT, MEMBER] and w.member_joined
    assert w.board["rev"] == 1 and w.board["text"].startswith("MCP tester board ")
    assert w.card["state"] == "passed" and list(w.approvals.values()) == ["denied"]
    assert w.org_deleted and _Throwaways.closed == 1
    assert _Throwaways.made == ["chat-tools-owner", "chat-tools-member", "chat-tools-stranger"]


@pytest.mark.parametrize("defect,row,needle", [
    ("unread_stuck", C.UNREAD, "the count did not grow"),
    ("mark_ignored", C.MARK, "did not fall"),
    ("file_mangled", C.ATTACH, "not the text shared"),
    ("history_lost", C.HIST, "holds 0 update(s)"),
    ("stale_wins", "refusal: updateChatBoard a write against a revision already replaced", "expected 4xx, got 200"),
    ("member_edits", "refusal: updateChatBoard a member the owner did not name", "expected 4xx, got 200"),
    ("member_edits", C.MEMBER_BOARD_ROW, "reads can_edit True"),
    ("member_decides", C.MEMBER_LIST_ROW, "can_decide: True"),
    ("member_waits", C.MEMBER_WAIT_ROW, "waits on the room's request"),
    ("anyone_updates", "refusal: updateChatProgress a card someone else posted", "expected 4xx, got 200"),
    ("closed_updates", "refusal: updateChatProgress a closed card", "expected 4xx, got 200"),
    ("file_leaks", "refusal: getChatAttachment a file in a room the caller is not in", "expected 4xx, got 200"),
])
def test_each_defect_is_red_on_its_own_row(monkeypatch, defect, row, needle):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    out = _run(_World(**{defect: True}), monkeypatch)
    r = out[row]
    assert not r["healthy"] and needle in str(r.get("fail_reason")), (defect, r)


def test_an_agent_reading_the_waiting_list_is_red(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    r = _run(_World(agent_waits=True), monkeypatch)["refusal: listWaitingChatApprovals an agent's own token"]
    assert not r["healthy"], r


def test_without_a_transport_into_the_target_the_file_is_not_measured_and_says_so(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    out = _run(_World(), monkeypatch, transport=False)
    assert not _ok(out[C.ATTACH]) and "bag.http_in_target" in str(out[C.ATTACH].get("skip_reason"))
    for tool in (C.UNREAD, C.MARK, C.LISTA, C.WAITING, C.POSTP, C.UPDP, C.HIST, C.BOARD, C.WBOARD):
        assert _ok(out.get(tool)), (tool, out.get(tool))


def test_the_multipart_body_carries_one_file_whole():
    body, ctype = C.multipart("file", "a.txt", "text/plain", b"line one\nline two\n")
    boundary = ctype.split("boundary=", 1)[1]
    assert body.startswith(f"--{boundary}\r\n".encode()) and body.endswith(f"\r\n--{boundary}--\r\n".encode())
    assert b"\r\n\r\nline one\nline two\n\r\n" in body


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
