"""§MCPTEST30 (V0650, tester batch 1, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6): earn_chat_approvals,
the three tools of session-release's order (l) on an organization room of the run's own, only where the target is torn
down after its run (MCP_TESTER_EPHEMERAL_TARGET), and their sweep contracts.

Offline: a scripted world answers as (l)'s routes do (an organization, its room opened by the developer and the agent,
requests with client_ref idempotency, decisions by the owner, a decision's role and signed statement on the status read,
an agent context refused on decide). RED on (l)'s own head without this change: the lifecycle and the contracts do not
exist (the import fails, the three tools fall to default contracts).
"""
from __future__ import annotations

import asyncio
import itertools
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agentvault_registry.api_tests.contracts import earned_admin_dev
from agentvault_registry.api_tests.contracts import earned_ad_chat_approvals as C
from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS

DEV, AGENT, DID = "dev-jwt", "agent-jwt", "did:theprotocol:sandbox-a:approvals-agent"
ROOM = "conv-org-room-1"


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                   "structuredContent": obj}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


class _World:
    def __init__(self, *, stale: bool = False, role: str = "owner", statement: bool = True, deny_sticks: bool = True,
                 duplicate_ok: bool = True):
        self.stale, self.role, self.statement = stale, role, statement
        self.deny_sticks, self.duplicate_ok = deny_sticks, duplicate_ok
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.refs: Dict[str, str] = {}
        self.calls: List[Tuple[str, Dict[str, Any], str]] = []
        self.org_deleted = False
        self.opened: List[str] = []
        self._n = itertools.count(1)

    def _ser(self, r: Dict[str, Any]) -> Dict[str, Any]:
        out = {"id": r["id"], "status": r["status"], "conversation_id": ROOM}
        if r["status"] in ("approved", "denied"):
            out["decision"] = {"decision": r["status"], "decided_by": {"developer_id": 9, "role": self.role},
                               **({"statement": {"signature": "s"}} if self.statement else {})}
        return out

    async def public(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        self.calls.append((tool, dict(args), jwt))
        if tool == "theprotocol_createOrganization":
            return True, _body({"id": "org-1", "name": args["name"]}), "201"
        if tool == "theprotocol_assignAgentToOrg":
            assert args == {"org_id": "org-1", "agent_did": DID}
            return True, _body({"ok": True}), "200"
        if tool == "theprotocol_deleteOrganization":
            self.org_deleted = True
            return True, _body({"deleted": True}), "200"
        if tool == C.DECIDE and jwt != DEV:
            return False, _body({"error": "This tool requires developer authentication. Provide a developer JWT"}), "401"
        if tool == C.REQUEST:
            assert args["agent_jwt"] == AGENT and args["conversation_id"] == ROOM
            ref = args["client_ref"]
            if ref in self.refs and self.duplicate_ok:
                return True, _body({"approval": self._ser(self.rows[self.refs[ref]]), "duplicate": True}), "200"
            aid = f"apr_{next(self._n)}"
            self.rows[aid] = {"id": aid, "status": "pending"}
            self.refs[ref] = aid
            return True, _body({"approval": self._ser(self.rows[aid]), "duplicate": False}), "201"
        if tool == C.STATUS:
            r = self.rows.get(args["approval_id"])
            if r is None:
                return False, _body({"error": "approval request not found"}), "404"
            return True, _body(self._ser(r)), "200"
        if tool == C.DECIDE:
            decided = []
            for aid in args.get("approval_ids") or []:
                r = self.rows[aid]
                if args["decision"] == "approve" and not self.stale:
                    r["status"] = "approved"
                if args["decision"] == "deny" and self.deny_sticks:
                    r["status"] = "denied"
                decided.append(aid)
            return True, _body({"decision": args["decision"], "decided": decided, "skipped": {}}), "200"
        raise AssertionError(tool)

    async def admin(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        assert tool == "theprotocol_adminRequest" and args["endpoint"] == "/api/v1/chat/org-rooms/org-1/open"
        self.opened.append(args["developer_jwt"])
        return True, _body({"status_code": 200, "ok": True, "response": {"conversation_id": ROOM}}), "200"


class _Throwaways:
    closed = 0

    def __init__(self, rpc, parse, bag, tag):
        pass

    async def developer(self, role: str, verify: bool = True) -> Dict[str, Any]:
        return {"developer_id": 9, "access_token": DEV}

    async def agent(self, dev: Dict[str, Any], label: str = "") -> Dict[str, Any]:
        return {"did": DID, "agent_jwt": AGENT, "owner_jwt": DEV}

    async def close(self) -> None:
        type(self).closed += 1


def _run(w: _World, monkeypatch) -> Dict[str, dict]:
    from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag
    monkeypatch.setattr(C, "Throwaways", _Throwaways)
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline-sentinel", sentinel_jwt="sentinel-jwt",
                        developer_jwt="runner-dev-jwt", developer_id="1")
    bag.rpc_admin = w.admin                # type: ignore[attr-defined]
    out: Dict[str, dict] = {}
    asyncio.run(C.lifecycle_earn_chat_approvals(w.public, _parse, bag, out))
    return out


def _ok(row: Optional[dict]) -> bool:
    return bool(row) and bool(row.get("healthy")) and not row.get("skip_reason") and not row.get("fail_reason")


def test_it_is_registered_and_the_sweep_pins_each_tools_refusal():
    assert "earn_chat_approvals" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]
    for tool in (C.REQUEST, C.STATUS, C.DECIDE):
        c = MCP_CONTRACTS[tool]
        assert c.expect_status == "error_4xx" and c.expect_error_message_contains, tool
        assert "earned_ad_chat_approvals" in str(c.success_path_unmeasured), tool


def test_a_standing_frame_asks_nothing_and_says_why(monkeypatch):
    monkeypatch.delenv(C.EPHEMERAL_ENV, raising=False)
    w = _World()
    out = _run(w, monkeypatch)
    assert w.calls == [] and sorted(out) == sorted((C.REQUEST, C.STATUS, C.DECIDE))
    assert all(C.EPHEMERAL_ENV in str(r.get("skip_reason")) for r in out.values())


def test_a_pair_earns_all_three_and_leaves_nothing(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    _Throwaways.closed = 0
    w = _World()
    out = _run(w, monkeypatch)
    for tool in (C.REQUEST, C.STATUS, C.DECIDE):
        assert _ok(out.get(tool)), (tool, out.get(tool))
    refusal = next(v for k, v in out.items() if k.startswith("refusal: decideChatApproval"))
    assert refusal["healthy"], refusal
    assert w.opened == [DEV, AGENT], "the room opened by the developer, then joined by the agent"
    assert sorted(r["status"] for r in w.rows.values()) == ["approved", "denied"]
    assert w.org_deleted and _Throwaways.closed == 1


@pytest.mark.parametrize("defect,tool,needle", [
    ({"stale": True}, C.DECIDE, "reads 'pending' after the approval"),
    ({"role": "approver"}, C.DECIDE, "role 'approver', not 'owner'"),
    ({"statement": False}, C.DECIDE, "no signed statement"),
    ({"deny_sticks": False}, C.DECIDE, "a denial reads 'pending'"),
    ({"duplicate_ok": False}, C.REQUEST, "did not answer the same request"),
])
def test_each_defect_is_a_finding_on_its_tool(monkeypatch, defect, tool, needle):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    out = _run(_World(**defect), monkeypatch)
    row = out[tool]
    assert not row["healthy"] and needle in str(row.get("fail_reason")), row


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
