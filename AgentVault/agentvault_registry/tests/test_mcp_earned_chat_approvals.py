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
                 duplicate_ok: bool = True, reuse_ok: bool = False, wrong_use: bool = False, step_up: bool = False,
                 list_served: bool = True, agent_reads_list: bool = False, stale_list: bool = False):
        # V0651 (y): the approvals list (GET /chat/approvals): absent, read by an agent, or keeping decided requests
        self.list_served, self.agent_reads_list, self.stale_list = list_served, agent_reads_list, stale_list
        self.stale, self.role, self.statement = stale, role, statement
        # V0651 (o): a second use let through, a use recorded for another act, a room asking a phone confirmation
        self.reuse_ok, self.wrong_use, self.step_up = reuse_ok, wrong_use, step_up
        self.deny_sticks, self.duplicate_ok = deny_sticks, duplicate_ok
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.refs: Dict[str, str] = {}
        self.calls: List[Tuple[str, Dict[str, Any], str]] = []
        self.org_deleted = False
        self.opened: List[str] = []
        self._n = itertools.count(1)

    def _ser(self, r: Dict[str, Any]) -> Dict[str, Any]:
        out = {"id": r["id"], "status": r["status"], "conversation_id": ROOM, "consumed": r.get("consumed")}
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
            self.rows[aid] = {"id": aid, "status": "pending", "production_impact": bool(args.get("production_impact")),
                              "artifact_sha256": args.get("artifact_sha256", "")}
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
                if self.step_up and r["production_impact"] and args["decision"] == "approve":
                    return True, _body({"status": "step_up_required", "challenge": {"id": "ch_1"}}), "200"
                if args["decision"] == "approve" and not self.stale:
                    r["status"] = "approved"
                if args["decision"] == "deny" and self.deny_sticks:
                    r["status"] = "denied"
                decided.append(aid)
            return True, _body({"decision": args["decision"], "decided": decided, "skipped": {}}), "200"
        if tool == C.CONSUME:
            assert args["agent_jwt"] == AGENT and jwt == DEV, "the agent that asked uses it"
            r = self.rows.get(args["approval_id"])
            if r is None:
                return False, _body({"error": "approval request not found"}), "404"
            if r.get("consumed") and not self.reuse_ok:
                u = r["consumed"]
                return False, _body({"error": f"this approval was already used: it opened {u['act']!r} (sha256 "
                                              f"{u['act_sha256'][:12]}...) at 2026-10-31T17:00:00Z for {DID}. One "
                                              f"approval opens one act: ask again"}), "409"
            if r["status"] != "approved":
                return False, _body({"error": f"this approval is {r['status']}, not approved: nothing opened"}), "409"
            if not r["production_impact"]:
                return False, _body({"error": "this approval was asked without production_impact, so it cannot open "
                                              "a production act: ask again"}), "409"
            if r["artifact_sha256"] != args["act_sha256"]:
                return False, _body({"error": f"this approval names {r['artifact_sha256'][:12]}..., this act "
                                              f"{args['act_sha256'][:12]}...: nothing opened"}), "409"
            r["consumed"] = {"at": "2026-10-31T17:00:00Z", "by_agent_did": DID, "act_sha256": args["act_sha256"],
                             "act": "another act" if self.wrong_use else args["act_label"]}
            return True, _body({"approval": self._ser(r)}), "200"
        raise AssertionError(tool)

    async def admin(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        assert tool == "theprotocol_adminRequest"
        if args["endpoint"] == C.LIST:
            assert args["method"] == "GET"
            if not self.list_served:
                return True, _body({"status_code": 404, "ok": False, "response": {"detail": "Not Found"}}), "200"
            if args["developer_jwt"] == AGENT and not self.agent_reads_list:
                return True, _body({"status_code": 403, "ok": False, "response": {
                    "detail": "agents never decide approvals: this list is for the organization's owner and its "
                              "named approvers"}}), "200"
            items = [self._ser(r) for r in self.rows.values() if r["status"] == "pending" or self.stale_list]
            return True, _body({"status_code": 200, "ok": True, "response": {"items": items, "count": len(items)}}), "200"
        assert args["endpoint"] == "/api/v1/chat/org-rooms/org-1/open"
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
    assert w.calls == [] and sorted(out) == sorted(C.TIERS)
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
    assert sorted(r["status"] for r in w.rows.values()) == ["approved", "approved", "denied"]
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


# ── V0651 (o): his approval click as the production word, one approval opens one act ──────────────────────────────────
CONSUME_REFUSALS = ("an approval asked without production_impact", "a denied approval", "an approval not yet decided",
                    "an act its approval does not name", "a second use of one approval")


def test_one_approval_opens_one_act_and_every_other_use_is_refused(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    w = _World()
    out = _run(w, monkeypatch)
    assert _ok(out.get(C.CONSUME)), out.get(C.CONSUME)
    for what in CONSUME_REFUSALS:
        row = out.get(f"refusal: consumeChatApproval {what}")
        assert row and row["healthy"] and row.get("status_code") == 409, (what, row)
    used = [r for r in w.rows.values() if r.get("consumed")]
    assert len(used) == 1 and used[0]["production_impact"] and used[0]["consumed"]["act"].startswith("MCP tester act ")
    assert len(used[0]["artifact_sha256"]) == 64 and used[0]["consumed"]["act_sha256"] == used[0]["artifact_sha256"]
    assert [t for t, _a, _j in w.calls].count(C.CONSUME) == 6


def test_a_second_use_let_through_is_red(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    row = _run(_World(reuse_ok=True), monkeypatch)["refusal: consumeChatApproval a second use of one approval"]
    assert not row["healthy"], row


def test_a_use_recorded_for_another_act_is_a_finding(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    row = _run(_World(wrong_use=True), monkeypatch)[C.CONSUME]
    assert not row["healthy"] and "the use names 'another act'" in str(row.get("fail_reason")), row


def test_a_room_asking_a_phone_confirmation_is_not_measured_and_says_so(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    out = _run(_World(step_up=True), monkeypatch)
    row = out[C.CONSUME]
    assert not _ok(row) and "step_up_required" in str(row.get("skip_reason")), row
    assert out["refusal: consumeChatApproval an approval not yet decided"]["healthy"]


# ── V0651 (y): Pocket's Approvals list, GET /chat/approvals ─────────────────────────────────────────────────────────────
def test_the_owners_list_holds_the_pending_request_until_it_is_decided_and_refuses_an_agent(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    out = _run(_World(), monkeypatch)
    assert _ok(out.get(C.LIST_OWNER_ROW)), out.get(C.LIST_OWNER_ROW)
    assert out[C.LIST_OWNER_ROW]["result_excerpt"]["named_after_the_decision"] is False
    agent = out.get(C.LIST_AGENT_ROW)
    assert agent and agent["healthy"] and agent["status_code"] == 403, agent


@pytest.mark.parametrize("defect,row,needle", [
    ({"agent_reads_list": True}, C.LIST_AGENT_ROW, "not the 403"),
    ({"stale_list": True}, C.LIST_OWNER_ROW, "still names"),
])
def test_each_list_defect_is_red_on_its_row(monkeypatch, defect, row, needle):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    r = _run(_World(**defect), monkeypatch)[row]
    assert not r["healthy"] and needle in str(r.get("fail_reason")), r


def test_a_registry_without_the_list_is_not_measured_and_says_so(monkeypatch):
    monkeypatch.setenv(C.EPHEMERAL_ENV, "true")
    out = _run(_World(list_served=False), monkeypatch)
    for row in (C.LIST_OWNER_ROW, C.LIST_AGENT_ROW):
        assert not _ok(out[row]) and "not served here (HTTP 404)" in str(out[row].get("skip_reason")), out[row]


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
