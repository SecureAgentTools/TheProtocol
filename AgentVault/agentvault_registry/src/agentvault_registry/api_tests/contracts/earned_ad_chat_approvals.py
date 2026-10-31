"""§MCPTEST30 (V0650, tester batch 1, Guild order gwo_2015b757c94ce69138500df6): approvals in the chat, session-release's
order (l) gwo_dafb543e979a689b21ae69de, on a room of the run's own (agentvault2-d3, 2026-10-31; asked for in the sessions'
room, seq 74: "three new MCP tools need tester contracts").

Only where the target is torn down after its run (MCP_TESTER_EPHEMERAL_TARGET: the nightly and proof pairs): the run
makes an organization, adds an agent of its own and opens the organization's room, and a room stays after its
organization is deleted, so a standing frame would keep one per run. There every row below is NOT MEASURED with the
reason, and the sweep's contracts (mcp_contracts.py) still pin each tool's refusal of a room or a request that is not the
caller's.
  decideChatApproval      an agent context is refused (agents never decide: "requires developer authentication")
  requestChatApproval     the run's agent asks in the room: pending; the same client_ref again answers the same request
                          (duplicate)
  getChatApprovalStatus   the agent reads it pending
  decideChatApproval      the owner (the run's developer) approves it; the agent reads it approved, in the role owner,
                          with the registry's signed statement; a second request is denied and reads denied
The organization is deleted after, and the agent and its developer are removed (Throwaways)."""
from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_ad_ephemeral import EPHEMERAL_ENV, ephemeral_target
from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, lc, refusal_step, said, step, unmeasured,
)

REQUEST = "theprotocol_requestChatApproval"
STATUS = "theprotocol_getChatApprovalStatus"
DECIDE = "theprotocol_decideChatApproval"
TIERS = {REQUEST: "2", STATUS: "2", DECIDE: "3"}
NOT_EPHEMERAL = (f"the run opens an organization room of its own only where its target is torn down after the run "
                 f"({EPHEMERAL_ENV}=true: the nightly and proof pairs); a room stays after its organization is deleted")


def _nm(outcomes: Dict[str, dict], why: str) -> None:
    for tool, tier in TIERS.items():
        unmeasured(outcomes, tool, tier, why)


def _bug(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    lc()._bugfind(outcomes, tool, TIERS[tool], f"{tool.replace('theprotocol_', '')}: {why}")


async def _call(rpc: Any, parse: Any, tool: str, args: Dict[str, Any], jwt: str) -> Tuple[bool, Dict[str, Any], str]:
    """A setup or read-back call, recorded nowhere."""
    ok, body, code = await rpc(tool, args, jwt=jwt, timeout=60)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner if isinstance(inner, dict) else {}, str(code)


async def _rest(bag: Any, parse: Any, method: str, endpoint: str, as_jwt: str) -> Tuple[int, Dict[str, Any]]:
    """One REST call sent with `as_jwt`, through the admin bridge's adminRequest; (0, {}) when it cannot be made."""
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return 0, {}
    try:
        _ok, raw, code = await rpc_admin("theprotocol_adminRequest", {"method": method, "endpoint": endpoint,
                                                                      "body": {}, "developer_jwt": as_jwt},
                                         jwt=bag.developer_jwt, timeout=60)
    except Exception:                                                  # noqa: BLE001
        return 0, {}
    got = parse(raw) if isinstance(raw, dict) else {}
    got = got if isinstance(got, dict) else {}
    try:
        st = int(got.get("status_code"))
    except (TypeError, ValueError):
        st = int(code) if str(code).isdigit() else 0
    inner = got.get("response") if "response" in got else got
    return st, inner if isinstance(inner, dict) else {}


def _approval(answer: Dict[str, Any]) -> Dict[str, Any]:
    a = answer.get("approval") if isinstance(answer.get("approval"), dict) else answer
    return a if isinstance(a, dict) else {}


async def lifecycle_earn_chat_approvals(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """Approvals in an organization room of the run's own (the module docstring)."""
    if not ephemeral_target():
        return _nm(outcomes, NOT_EPHEMERAL)
    if getattr(bag, "rpc_admin", None) is None:
        return _nm(outcomes, "this flow carries no admin bridge (bag.rpc_admin): the organization room opens through "
                             "a route no MCP tool wraps")
    tag = f"{int(time.time())}-{secrets.token_hex(2)}"
    t = Throwaways(rpc, parse, bag, "chat-approvals")
    djwt, oid = "", None
    try:
        dev = await t.developer("chat-approvals")
        ag = await t.agent(dev) if not dev.get("why") else dev
        if ag.get("why"):
            return _nm(outcomes, f"no agent of the run's own: {ag.get('why')}")
        djwt, ajwt, did = dev["access_token"], ag["agent_jwt"], ag["did"]
        ok, org, code = await _call(rpc, parse, "theprotocol_createOrganization", {
            "name": f"mcp-earn-approvals-{tag}", "description": "The MCP tester's organization: deleted after its run."},
            djwt)
        oid = str(org.get("id")) if ok and org.get("id") else None
        if not oid:
            return _nm(outcomes, f"no organization of the run's own could be made (HTTP {code}: {said(org)})")
        ok, _a, code = await _call(rpc, parse, "theprotocol_assignAgentToOrg", {"org_id": oid, "agent_did": did}, djwt)
        if not ok:
            return _nm(outcomes, f"the run's agent could not join its organization (HTTP {code})")
        st, room = await _rest(bag, parse, "POST", f"/api/v1/chat/org-rooms/{oid}/open", djwt)
        conv = str(room.get("conversation_id") or "")
        st2, _r = await _rest(bag, parse, "POST", f"/api/v1/chat/org-rooms/{oid}/open", ajwt)
        if not conv or not (200 <= st2 < 300):
            return _nm(outcomes, f"the organization room did not open for both (HTTP {st} and {st2})")

        # agents never decide
        await refusal_step(rpc, parse, DECIDE, "3", {"conversation_id": conv, "decision": "approve"}, ajwt, outcomes,
                           "an agent's own token", text="requires developer authentication")
        # the agent asks
        ref = f"mcp-earn-{tag}-1"
        ok, r = await step(rpc, parse, REQUEST, "2", {
            "agent_jwt": ajwt, "conversation_id": conv, "title": f"MCP tester approval {tag}", "client_ref": ref,
            "reason": "The MCP tester asks its own developer, in a room of its own.", "expires_in_seconds": 600},
            djwt, outcomes)
        a1 = _approval(r) if ok else {}
        aid = str(a1.get("id") or "")
        if not ok or not aid:
            if ok:
                _bug(outcomes, REQUEST, "the answer carries no approval id")
            unmeasured(outcomes, STATUS, "2", "no approval request of the run's own")
            unmeasured(outcomes, DECIDE, "3", "no approval request of the run's own")
            return
        if str(a1.get("status")) != "pending":
            _bug(outcomes, REQUEST, f"a new request reads status {a1.get('status')!r}, not 'pending'")
        ok_d, again, _c = await _call(rpc, parse, REQUEST, {"agent_jwt": ajwt, "conversation_id": conv,
                                                            "title": f"MCP tester approval {tag}", "client_ref": ref},
                                      djwt)
        if not (ok_d and again.get("duplicate") is True and str(_approval(again).get("id")) == aid):
            _bug(outcomes, REQUEST, "the same client_ref again did not answer the same request (duplicate)")
        # the agent reads it pending
        ok, s = await step(rpc, parse, STATUS, "2", {"agent_jwt": ajwt, "approval_id": aid, "wait_seconds": 0}, djwt,
                           outcomes)
        if ok and str(_approval(s).get("status")) != "pending":
            _bug(outcomes, STATUS, f"the undecided request reads {_approval(s).get('status')!r}, not 'pending'")

        # the owner approves it, the agent reads it approved
        def _approved(inner: Dict[str, Any]) -> Optional[str]:
            a = _approval(inner)
            if str(a.get("status")) != "approved":
                return f"getChatApprovalStatus reads {a.get('status')!r} after the approval"
            dec = a.get("decision") if isinstance(a.get("decision"), dict) else {}
            role = (dec.get("decided_by") or {}).get("role") if isinstance(dec.get("decided_by"), dict) else None
            if str(role or "") != "owner":
                return f"the approved request names the decider's role {role!r}, not 'owner'"
            if not dec.get("statement"):
                return "the approved request carries no signed statement of the registry's"
            return None
        ok, d = await step(rpc, parse, DECIDE, "3", {"conversation_id": conv, "decision": "approve",
                                                     "approval_ids": [aid], "note": "approved by its own run"},
                           djwt, outcomes)
        if ok:
            await step(rpc, parse, STATUS, "2", {"agent_jwt": ajwt, "approval_id": aid}, djwt, outcomes,
                       record_as_separate=False, verify_against=DECIDE, verify_against_check=_approved)
            # a second request, denied
            ok2, r2, _c = await _call(rpc, parse, REQUEST, {"agent_jwt": ajwt, "conversation_id": conv,
                                                            "title": f"MCP tester approval {tag} (denied)",
                                                            "client_ref": f"mcp-earn-{tag}-2"}, djwt)
            aid2 = str(_approval(r2).get("id") or "")
            if ok2 and aid2:
                okd, _dd, cd = await _call(rpc, parse, DECIDE, {"conversation_id": conv, "decision": "deny",
                                                                "approval_ids": [aid2]}, djwt)
                okr, s2, _c2 = await _call(rpc, parse, STATUS, {"agent_jwt": ajwt, "approval_id": aid2}, djwt)
                if not (okd and okr and str(_approval(s2).get("status")) == "denied"):
                    _bug(outcomes, DECIDE, f"a denial reads {_approval(s2).get('status')!r} afterwards (deny answered "
                                           f"HTTP {cd})")
    finally:
        if oid:
            await _call(rpc, parse, "theprotocol_deleteOrganization", {"org_id": oid}, djwt)
        await t.close()


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_chat_approvals", "runner": lifecycle_earn_chat_approvals},
]
