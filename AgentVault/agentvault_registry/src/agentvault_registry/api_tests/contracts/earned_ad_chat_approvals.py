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
  consumeChatApproval     (V0651, order (o): his approval click as the production word, one approval opens one act)
                          refused for the approval asked without production_impact, for the denied one, and for a
                          third, asked with production_impact and naming an act's sha256, while it is undecided;
                          once the owner approves it, refused for an act it does not name; then it opens its act
                          (the answer records the use: the act and its sha256), and a second use is refused naming
                          the act it opened
  the approvals list      (V0651, order (y): Pocket's Approvals reads GET /api/v1/chat/approvals, the requests waiting for
                          the caller's decision) names the pending request for its owner and not once it is decided;
                          an agent's token is refused (agents never decide). Rows under chat: (no MCP tool reads it)
The organization is deleted after, and the agent and its developer are removed (Throwaways)."""
from __future__ import annotations

import hashlib
import json
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
CONSUME = "theprotocol_consumeChatApproval"   # V0651 (o)
TIERS = {REQUEST: "2", STATUS: "2", DECIDE: "3", CONSUME: "2"}
LIST = "/api/v1/chat/approvals"                    # V0651 (y), Pocket's Approvals
LIST_OWNER_ROW = "chat: the owner's approvals list holds a pending request until it is decided"
LIST_AGENT_ROW = "chat: an agent's token is refused on the approvals list"
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


async def _listed(bag: Any, parse: Any, as_jwt: str, aid: str) -> Tuple[int, bool, Dict[str, Any]]:
    """The approvals list as `as_jwt` reads it: (status, whether it names `aid`, the body)."""
    st, body = await _rest(bag, parse, "GET", LIST, as_jwt)
    items = body.get("items") if isinstance(body.get("items"), list) else []
    return st, any(isinstance(i, dict) and str(i.get("id")) == aid for i in items), body


async def _list_while_pending(bag: Any, parse: Any, djwt: str, ajwt: str, aid: str,
                              outcomes: Dict[str, dict]) -> bool:
    """V0651 (y): while the run's request is pending its owner's list names it, and an agent's token is refused (agents
    never decide). Returns whether the owner's list named it; where the route is not served, both rows are NOT
    MEASURED, said. The owner's row is written after the decision (_list_after_decision) or here when it failed."""
    t0 = time.time()
    st, named, _b = await _listed(bag, parse, djwt, aid)
    if st in (0, 404, 405):
        why = f"the approvals list (V0651 order (y), GET {LIST}) is not served here (HTTP {st or 'none'})"
        unmeasured(outcomes, LIST_OWNER_ROW, "3", why)
        unmeasured(outcomes, LIST_AGENT_ROW, "2", why)
        return False
    sta, abody = await _rest(bag, parse, "GET", LIST, ajwt)
    ok_a = sta == 403 and "agents never decide approvals" in json.dumps(abody, default=str)[:800].lower()
    outcomes[LIST_AGENT_ROW] = lc()._make_outcome(
        LIST_AGENT_ROW, "2", ok_a, str(sta), int((time.time() - t0) * 1000),
        None if ok_a else f"an agent's token read the approvals list with HTTP {sta}, not the 403 'agents never decide "
                          f"approvals'", {"status": sta}, expect_status="error_4xx")
    if st != 200 or not named:
        outcomes[LIST_OWNER_ROW] = lc()._make_outcome(
            LIST_OWNER_ROW, "3", False, str(st), int((time.time() - t0) * 1000),
            f"the owner's approvals list (HTTP {st}) does not name the pending request {aid}",
            {"named_while_pending": named}, expect_status="success")
        return False
    return True


async def _list_after_decision(bag: Any, parse: Any, djwt: str, aid: str, outcomes: Dict[str, dict], t0: float) -> None:
    st, named, _b = await _listed(bag, parse, djwt, aid)
    ok = st == 200 and not named
    outcomes[LIST_OWNER_ROW] = lc()._make_outcome(
        LIST_OWNER_ROW, "3", ok, str(st), int((time.time() - t0) * 1000),
        None if ok else f"after its approval the owner's approvals list (HTTP {st}) still names {aid}",
        {"named_while_pending": True, "named_after_the_decision": named}, expect_status="success")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _consume_path(rpc: Any, parse: Any, ajwt: str, djwt: str, conv: str, tag: str, plain_aid: str,
                        denied_aid: str, outcomes: Dict[str, dict]) -> None:
    """V0651 (o), session-release's order gwo_b81bd6234ac6d6b30b1f9759: his approval click as the production word. One
    approval opens one act, named by its sha256, for the agent that asked (the module docstring). Nothing here is a
    production act: the act is a sha256 of the run's own, and the use is recorded on the pair's registry."""
    label = f"MCP tester act {tag}"
    sha = _sha(f"mcp-tester-act-{tag}")
    base = {"agent_jwt": ajwt, "act_label": label, "act_sha256": sha}
    if plain_aid:
        await refusal_step(rpc, parse, CONSUME, "2", dict(base, approval_id=plain_aid), djwt, outcomes,
                           "an approval asked without production_impact", codes=(409,),
                           text="asked without production_impact")
    if denied_aid:
        await refusal_step(rpc, parse, CONSUME, "2", dict(base, approval_id=denied_aid), djwt, outcomes,
                           "a denied approval", codes=(409,), text="denied, not approved")
    ok, r, code = await _call(rpc, parse, REQUEST, {
        "agent_jwt": ajwt, "conversation_id": conv, "title": f"MCP tester: open {label}",
        "client_ref": f"mcp-earn-{tag}-3", "reason": "The MCP tester asks for one act of its own, named by its sha256.",
        "artifact_sha256": sha, "artifact_label": label, "production_impact": True, "expires_in_seconds": 600}, djwt)
    aid = str(_approval(r).get("id") or "")
    if not ok or not aid:
        return unmeasured(outcomes, CONSUME, "2", f"no approval request of the run's own for an act (requestChatApproval "
                                                  f"answered HTTP {code}: {said(r)})")
    await refusal_step(rpc, parse, CONSUME, "2", dict(base, approval_id=aid), djwt, outcomes,
                       "an approval not yet decided", codes=(409,), text="pending, not approved")
    okd, d, cd = await _call(rpc, parse, DECIDE, {"conversation_id": conv, "decision": "approve",
                                                  "approval_ids": [aid], "note": "one act of its own run"}, djwt)
    oks, s, _c = await _call(rpc, parse, STATUS, {"agent_jwt": ajwt, "approval_id": aid}, djwt)
    st = str(_approval(s).get("status"))
    if not (okd and oks and st == "approved"):
        why = ("the room asks for a phone confirmation of a production-impacting request (step_up_required), which no "
               "run can give" if "step_up" in json.dumps(d, default=str) else
               f"the owner's approval reads {st!r} (decide answered HTTP {cd})")
        return unmeasured(outcomes, CONSUME, "2", f"no approved request to open an act with: {why}")
    await refusal_step(rpc, parse, CONSUME, "2", dict(base, approval_id=aid, act_sha256=_sha(f"mcp-tester-other-{tag}")),
                       djwt, outcomes, "an act its approval does not name", codes=(409,), text="this approval names")

    def _opened(inner: Dict[str, Any]) -> Optional[str]:
        used = _approval(inner).get("consumed")
        if not isinstance(used, dict):
            return "the answer records no use (approval.consumed)"
        if used.get("act") != label or used.get("act_sha256") != sha:
            return f"the use names {used.get('act')!r} ({str(used.get('act_sha256'))[:12]}), not {label!r} ({sha[:12]})"
        return None
    ok, c = await step(rpc, parse, CONSUME, "2", dict(base, approval_id=aid), djwt, outcomes)
    if ok:
        why = _opened(c)
        if why:
            _bug(outcomes, CONSUME, why)
        await refusal_step(rpc, parse, CONSUME, "2", dict(base, approval_id=aid), djwt, outcomes,
                           "a second use of one approval", codes=(409,), text=f"already used: it opened '{label}'")


async def lifecycle_earn_chat_approvals(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """Approvals in an organization room of the run's own (the module docstring)."""
    if not ephemeral_target():
        return _nm(outcomes, NOT_EPHEMERAL)
    if getattr(bag, "rpc_admin", None) is None:
        return _nm(outcomes, "this flow carries no admin bridge (bag.rpc_admin): the organization room opens through "
                             "a route no MCP tool wraps")
    tag = f"{int(time.time())}-{secrets.token_hex(2)}"
    t = Throwaways(rpc, parse, bag, "chat-approvals")
    djwt, oid, denied = "", None, ""
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
            unmeasured(outcomes, CONSUME, "2", "no approval request of the run's own")
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

        # V0651 (y): the request waits in its owner's approvals list, and an agent cannot read that list
        t_list = time.time()
        listed = await _list_while_pending(bag, parse, djwt, ajwt, aid, outcomes)
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
        if listed:
            if ok:
                await _list_after_decision(bag, parse, djwt, aid, outcomes, t_list)
            else:
                unmeasured(outcomes, LIST_OWNER_ROW, "3", "the run's request was not decided, so the list was not read "
                                                           "after a decision")
        if ok:
            await step(rpc, parse, STATUS, "2", {"agent_jwt": ajwt, "approval_id": aid}, djwt, outcomes,
                       record_as_separate=False, verify_against=DECIDE, verify_against_check=_approved)
            # a second request, denied
            ok2, r2, _c = await _call(rpc, parse, REQUEST, {"agent_jwt": ajwt, "conversation_id": conv,
                                                            "title": f"MCP tester approval {tag} (denied)",
                                                            "client_ref": f"mcp-earn-{tag}-2"}, djwt)
            aid2 = str(_approval(r2).get("id") or "")
            if ok2 and aid2:
                denied = aid2
                okd, _dd, cd = await _call(rpc, parse, DECIDE, {"conversation_id": conv, "decision": "deny",
                                                                "approval_ids": [aid2]}, djwt)
                okr, s2, _c2 = await _call(rpc, parse, STATUS, {"agent_jwt": ajwt, "approval_id": aid2}, djwt)
                if not (okd and okr and str(_approval(s2).get("status")) == "denied"):
                    denied = ""
                    _bug(outcomes, DECIDE, f"a denial reads {_approval(s2).get('status')!r} afterwards (deny answered "
                                           f"HTTP {cd})")
        # V0651 (o): one approval opens one act
        await _consume_path(rpc, parse, ajwt, djwt, conv, tag, aid if ok else "", denied, outcomes)
    finally:
        if oid:
            await _call(rpc, parse, "theprotocol_deleteOrganization", {"org_id": oid}, djwt)
        await t.close()


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_chat_approvals", "runner": lifecycle_earn_chat_approvals},
]
