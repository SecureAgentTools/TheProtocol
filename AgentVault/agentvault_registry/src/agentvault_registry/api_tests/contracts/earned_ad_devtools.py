"""§MCPTEST30 (V0636): developer tools on objects of the run's own (agentvault2-aa; step 2 of
sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md).

On V0635 each of these passed on one refusal (an id that names nothing, or a body the route refuses). Here:

  CI/CD          a throwaway developer's agent gets two versions and the second made current: deleteVersion removes
                 the first (getMyCicdVersions no longer lists it; deleting the current one is refused 409);
                 triggerDeployment records a manual deployment (no pipeline, so no webhook leaves the frame; the
                 record is born `success`), getDeployment reads it, appendDeploymentLogs and updateDeploymentStatus
                 write it (read back: the log line kept, status cancelled, the error message kept);
                 downloadPipelineTemplate fetches a free template the frame lists, and purchasePipelineTemplate
                 buys a free official one (no author) for the throwaway's agent (V0641, agentvault2-66: price 0, so no
                 TEG call). Each run leaves two things on a persistent frame such as the sandbox: one
                 pipeline_purchases row for its throwaway agent, and +1 on that official template's downloads (no
                 route lowers it); on the nightly pairs and the proofs both go with the teardown
  organizations  an organization of one throwaway developer invites a second one: listOrganizationInvitations
                 lists the invitation, acceptOrgInvitation (the token the invite answers to its inviter) makes a
                 member, removeOrganizationMember removes it (the member list no longer names it); a second
                 invitation is withdrawn (withdrawOrganizationInvitation: status cancelled); the organization is
                 deleted after
  support desk   the first developer's direct message to the second (readThread reads it) and an open ticket of its
                 own: grantSupportReview, getSupportReviewState (the grant live), revokeSupportReview (the grant no
                 longer live); the ticket is closed after through the admin bridge
  agents         resetAgentCredentialsOnboard (a new client id and secret: the old pair refused afterwards, the new
                 one gets a token; a wrong password refused 403), getTegTransactionDetail on a transfer between two
                 agents of the run, recordAchievement (an enabled achievement, no agent named, so nothing is paid;
                 a second record answers already_earned), agentBuilderGenerate (a zip), agentBuilderGenerateTemplate
                 (a template bundle for the first agent, a zip: the route leaves the client secret out of it)

Not here: createTegPolicy and createTegPoliciesBatch (a TEG policy sets rules and rewards on the TEG every agent of the
frame uses, and the tool cannot create one inactive; both since V0641 the setups' own creates), a priced pipeline
template (its price goes to the seller, and nothing brings it back), oauthIntrospect, oauthRevoke and
oauthTokenExchange (the sandbox frames hold no trusted OAuth registry: the routes answer 501), the operator portal
reads (getOperatorMyBundle, getOperatorMyLifecycle, operatorPortalSelfLogs: an approved operator's own account),
relayAction and getRelayStatus (they relay to an agent's own https endpoint, which no agent of the run serves),
downloadBundleViaOnboard (its bundle carries the agent's client secret, and a tool row keeps the first 300 bytes of a
zip answer: the run does not put a credential into a row), getTrustScore (it reads an EigenTrust epoch, which no agent
of the run has yet).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, lc, refusal_step, said, step, tool_row, unmeasured, zip_answer,
)

CICD = ("theprotocol_deleteVersion", "theprotocol_triggerDeployment", "theprotocol_getDeployment",
        "theprotocol_appendDeploymentLogs", "theprotocol_updateDeploymentStatus", "theprotocol_downloadPipelineTemplate",
        "theprotocol_purchasePipelineTemplate")   # §MCPTEST30 (V0641, agentvault2-66): the free template bought too
ORG = ("theprotocol_listOrganizationInvitations", "theprotocol_acceptOrgInvitation",
       "theprotocol_removeOrganizationMember", "theprotocol_withdrawOrganizationInvitation")
SUPPORT = ("theprotocol_readThread", "theprotocol_grantSupportReview", "theprotocol_getSupportReviewState",
           "theprotocol_revokeSupportReview")
AGENTS = ("theprotocol_resetAgentCredentialsOnboard", "theprotocol_getTegTransactionDetail",
          "theprotocol_recordAchievement", "theprotocol_agentBuilderGenerate", "theprotocol_agentBuilderGenerateTemplate")


def _nm(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    unmeasured(outcomes, tool, "3", why)


def _bug(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    lc()._bugfind(outcomes, tool, "3", f"{tool.replace('theprotocol_', '')}: {why}")


def _rows(v: Any, *keys: str) -> List[Dict[str, Any]]:
    if isinstance(v, list):
        return [r for r in v if isinstance(r, dict)]
    if isinstance(v, dict):
        for k in keys:
            if isinstance(v.get(k), list):
                return [r for r in v[k] if isinstance(r, dict)]
    return []


async def _call(rpc: Any, parse: Any, tool: str, args: Dict[str, Any], jwt: str) -> Tuple[bool, Dict[str, Any], str]:
    """A setup or read-back call, recorded nowhere."""
    ok, body, code = await rpc(tool, args, jwt=jwt, timeout=60)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner if isinstance(inner, dict) else {}, str(code)


def _guarded(tools: Tuple[str, ...]):
    """Runs a part; a raise names every tool of it the part had not recorded yet."""
    def wrap(fn):
        async def run(rpc, parse, bag, outcomes, *a):
            try:
                await fn(rpc, parse, bag, outcomes, *a)
            except Exception as e:                                     # noqa: BLE001
                for tool in tools:
                    if tool not in outcomes:
                        _nm(outcomes, tool, f"the lifecycle raised {type(e).__name__}: {str(e)[:160]} before it "
                                            f"reached this tool")
        return run
    return wrap


# ── CI/CD ─────────────────────────────────────────────────────────────────────────────────────────────────────────

async def lifecycle_earn_cicd(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    t = Throwaways(rpc, parse, bag, "cicd")
    try:
        dev = await t.developer("cicd")
        ag = await t.agent(dev, "a")
        if ag.get("why"):
            for tool in CICD:
                _nm(outcomes, tool, f"no agent of the run's own: {ag['why']}")
            return
        await _cicd(rpc, parse, bag, outcomes, dev, ag)
    finally:
        await t.close()


@_guarded(CICD)
async def _cicd(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], dev: Dict[str, Any],
                ag: Dict[str, Any]) -> None:
    jwt, did = dev["access_token"], ag["did"]
    tool = "theprotocol_deleteVersion"
    v_ids: List[str] = []
    ans: Dict[str, Any] = {}
    code = ""
    for v in ("1.0.0", "1.0.1"):
        ok, ans, code = await _call(rpc, parse, "theprotocol_createVersion",
                                    {"agent_did": did, "version": v, "release_notes": "MCP tester: its own version"}, jwt)
        if not (ok and ans.get("version_id")):
            break
        v_ids.append(str(ans["version_id"]))
    if len(v_ids) < 2:
        _nm(outcomes, tool, f"the run's own two versions could not be made (HTTP {code}: {said(ans)})")
    else:
        ok, ans, code = await _call(rpc, parse, "theprotocol_activateVersion",
                                    {"agent_did": did, "version_id": v_ids[1]}, jwt)
        if not ok:
            _nm(outcomes, tool, f"the second version could not be made current (HTTP {code}: {said(ans)})")
        else:
            await refusal_step(rpc, parse, tool, "3", {"agent_did": did, "version_id": v_ids[1]}, jwt, outcomes,
                               "the current version", codes=(409,), text="current version")
            ok, _ = await step(rpc, parse, tool, "3", {"agent_did": did, "version_id": v_ids[0]}, jwt, outcomes)
            if ok:
                ok2, lst, code2 = await _call(rpc, parse, "theprotocol_getMyCicdVersions", {"agent_did": did}, jwt)
                ids = {str(r.get("id")) for r in _rows(lst, "versions")}
                if not ok2:
                    _bug(outcomes, tool, f"getMyCicdVersions could not be read afterwards (HTTP {code2})")
                elif v_ids[0] in ids:
                    _bug(outcomes, tool, "getMyCicdVersions still lists the deleted version")
                elif v_ids[1] not in ids:
                    _bug(outcomes, tool, "getMyCicdVersions no longer lists the current version either")
    # a manual deployment (no pipeline: nothing leaves the frame), born `success`
    ok, dep = await step(rpc, parse, "theprotocol_triggerDeployment", "3", {"agent_did": did, "environment": "staging"},
                         jwt, outcomes)
    dep_id = str(dep.get("deployment_id")) if ok and dep.get("deployment_id") else None
    if not dep_id:
        for t in CICD[2:5]:
            _nm(outcomes, t, "no deployment of the run's own was recorded")
    else:
        tag = secrets.token_hex(4)
        ok, got = await step(rpc, parse, "theprotocol_getDeployment", "3", {"agent_did": did, "deployment_id": dep_id},
                             jwt, outcomes)
        if ok and (str(got.get("id")) != dep_id or got.get("environment") != "staging"):
            _bug(outcomes, "theprotocol_getDeployment",
                 f"the answer reads id={got.get('id')!r} environment={got.get('environment')!r}, not the run's own")
        line = f"MCP tester log line {tag}"
        ok_l, _ = await step(rpc, parse, "theprotocol_appendDeploymentLogs", "3",
                             {"agent_did": did, "deployment_id": dep_id, "logs": line}, jwt, outcomes)
        why = f"MCP tester: its own deployment, cancelled ({tag})"
        ok_s, _ = await step(rpc, parse, "theprotocol_updateDeploymentStatus", "3",
                             {"agent_did": did, "deployment_id": dep_id, "status": "cancelled", "error_message": why},
                             jwt, outcomes)
        if ok_l or ok_s:
            ok2, back, code2 = await _call(rpc, parse, "theprotocol_getDeployment",
                                           {"agent_did": did, "deployment_id": dep_id}, jwt)
            if not ok2:
                for t in ("theprotocol_appendDeploymentLogs", "theprotocol_updateDeploymentStatus"):
                    _bug(outcomes, t, f"getDeployment could not be read afterwards (HTTP {code2})")
            else:
                if ok_l and tag not in str(back.get("logs") or ""):
                    _bug(outcomes, "theprotocol_appendDeploymentLogs", "getDeployment does not carry the appended line")
                if ok_s and (str(back.get("status") or "").lower() != "cancelled" or tag not in str(
                        back.get("error_message") or "")):
                    _bug(outcomes, "theprotocol_updateDeploymentStatus",
                         f"getDeployment reads status={back.get('status')!r} and not the error message just written")
    # a free template the frame lists (a priced one answers 402 until bought)
    ok, tpl, code = await _call(rpc, parse, "theprotocol_getPipelineTemplates", {}, jwt)
    free = [r for r in _rows(tpl, "templates") if r.get("id") and not float(r.get("price_teg") or 0)]
    # §MCPTEST30 (V0641, agentvault2-66, with agentvault2-aa's two conditions): a free OFFICIAL template (no author, so no
    # developer's listing statistics move) bought by the run's own agent, which is fresh each run. Price 0, so
    # purchase_template makes no TEG call and emits nothing; it writes a pipeline_purchases row and counts a download on
    # the template, which no route lowers. A priced one is never bought: its price goes to the seller, and nothing
    # brings it back.
    official = [r for r in free if not r.get("author_did")]
    if not official:
        _nm(outcomes, "theprotocol_purchasePipelineTemplate",
            f"this frame lists no free official pipeline template (HTTP {code}, {len(free)} free, none without an "
            "author); a purchase counts a download on its template, so the run buys only an official one")
    else:
        ok_p, got_p = await step(rpc, parse, "theprotocol_purchasePipelineTemplate", "3",
                                 {"template_id": str(official[0]["id"]), "buyer_did": did}, jwt, outcomes)
        if ok_p and ("template_config" not in got_p or got_p.get("transaction_id")):
            _bug(outcomes, "theprotocol_purchasePipelineTemplate",
                 f"the free template's purchase answered {sorted(got_p)} with transaction_id "
                 f"{got_p.get('transaction_id')!r}: a free one carries its config and moves nothing")
    if not free:
        _nm(outcomes, "theprotocol_downloadPipelineTemplate",
            f"this frame lists no free pipeline template (HTTP {code}, {len(_rows(tpl, 'templates'))} listed)")
    else:
        ok, got = await step(rpc, parse, "theprotocol_downloadPipelineTemplate", "3", {"template_id": str(free[0]["id"])},
                             jwt, outcomes)
        if ok and got.get("name") != free[0].get("name"):
            _bug(outcomes, "theprotocol_downloadPipelineTemplate",
                 f"the download names {got.get('name')!r}, not the template asked for")


# ── organizations ────────────────────────────────────────────────────────────────────────────────────────────────

async def lifecycle_earn_org(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    t = Throwaways(rpc, parse, bag, "org")
    try:
        owner = await t.developer("org-owner")
        member = await t.developer("org-member")
        why = owner.get("why") or member.get("why")
        if why:
            for tool in ORG:
                _nm(outcomes, tool, f"no two developers of the run's own: {why}")
            return
        await _org(rpc, parse, bag, outcomes, owner, member)
    finally:
        await t.close()


def _member_ids(lst: Dict[str, Any]) -> set:
    return {str(r.get("developer_id")) for r in _rows(lst, "members")}


@_guarded(ORG)
async def _org(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], owner: Dict[str, Any],
               member: Dict[str, Any]) -> None:
    jwt = owner["access_token"]
    ok, org, code = await _call(rpc, parse, "theprotocol_createOrganization",
                                {"name": f"mcp-earn-org-{int(time.time())}-{secrets.token_hex(2)}",
                                 "description": "The MCP tester's organization: deleted after its run."}, jwt)
    oid = str(org.get("id")) if ok and org.get("id") else None
    if not oid:
        for tool in ORG:
            _nm(outcomes, tool, f"no organization of the run's own could be made (HTTP {code}: {said(org)})")
        return
    try:
        ok, inv, code = await _call(rpc, parse, "theprotocol_inviteOrganizationMember",
                                    {"org_id": oid, "email": member["email"], "role": "member"}, jwt)
        token = inv.get("token") if ok else None
        ok, lst = await step(rpc, parse, "theprotocol_listOrganizationInvitations", "3", {"org_id": oid}, jwt, outcomes)
        if ok and not any(str(r.get("email") or "").lower() == member["email"].lower()
                          for r in _rows(lst, "invitations")):
            _bug(outcomes, "theprotocol_listOrganizationInvitations", "the invitation just sent is not listed")
        if not token:
            _nm(outcomes, "theprotocol_acceptOrgInvitation", f"the invite answered no token (HTTP {code}: {said(inv)})")
            _nm(outcomes, "theprotocol_removeOrganizationMember", "no member of the run's own joined")
        else:
            ok, _ = await step(rpc, parse, "theprotocol_acceptOrgInvitation", "3", {"token": token},
                               member["access_token"], outcomes)
            if not ok:
                _nm(outcomes, "theprotocol_removeOrganizationMember", "no member of the run's own joined")
            else:
                ok_m, mem, _c = await _call(rpc, parse, "theprotocol_listOrganizationMembers", {"org_id": oid}, jwt)
                if ok_m and str(member["developer_id"]) not in _member_ids(mem):
                    _bug(outcomes, "theprotocol_acceptOrgInvitation", "the member list does not name the new member")
                ok, _ = await step(rpc, parse, "theprotocol_removeOrganizationMember", "3",
                                   {"org_id": oid, "developer_id": int(member["developer_id"])}, jwt, outcomes)
                if ok:
                    ok_m, mem, code_m = await _call(rpc, parse, "theprotocol_listOrganizationMembers", {"org_id": oid},
                                                    jwt)
                    if not ok_m:
                        _bug(outcomes, "theprotocol_removeOrganizationMember",
                             f"the member list could not be read afterwards (HTTP {code_m})")
                    elif str(member["developer_id"]) in _member_ids(mem):
                        _bug(outcomes, "theprotocol_removeOrganizationMember", "the removed member is still listed")
        other = f"mcp-earn-invitee-{secrets.token_hex(3)}@throwaway-pl.example.com"
        ok, inv2, code = await _call(rpc, parse, "theprotocol_inviteOrganizationMember",
                                     {"org_id": oid, "email": other, "role": "member"}, jwt)
        iid = (inv2.get("invitation_id") or inv2.get("id")) if ok else None
        if not iid:
            _nm(outcomes, "theprotocol_withdrawOrganizationInvitation",
                f"no second invitation could be sent (HTTP {code}: {said(inv2)})")
        else:
            ok, ans = await step(rpc, parse, "theprotocol_withdrawOrganizationInvitation", "3",
                                 {"org_id": oid, "invitation_id": str(iid)}, jwt, outcomes)
            if ok and str(ans.get("status") or "").lower() != "cancelled":
                _bug(outcomes, "theprotocol_withdrawOrganizationInvitation",
                     f"the withdrawal answered status={ans.get('status')!r}")
            elif ok:
                ok_l, lst, _c = await _call(rpc, parse, "theprotocol_listOrganizationInvitations", {"org_id": oid}, jwt)
                row = next((r for r in _rows(lst, "invitations") if str(r.get("id")) == str(iid)), None)
                if ok_l and row is not None and str(row.get("status") or "").lower() == "pending":
                    _bug(outcomes, "theprotocol_withdrawOrganizationInvitation", "the list still reads it pending")
    finally:
        await _call(rpc, parse, "theprotocol_deleteOrganization", {"org_id": oid}, jwt)


# ── the support desk ─────────────────────────────────────────────────────────────────────────────────────────────

async def lifecycle_earn_support_review(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    t = Throwaways(rpc, parse, bag, "support")
    try:
        owner = await t.developer("support-owner")
        other = await t.developer("support-other")
        why = owner.get("why") or other.get("why")
        if why:
            for tool in SUPPORT:
                _nm(outcomes, tool, f"no two developers of the run's own: {why}")
            return
        await _support(rpc, parse, bag, outcomes, owner, other)
    finally:
        await t.close()


def _grant(st: Dict[str, Any], gid: str) -> Dict[str, Any]:
    return next((g for g in _rows(st, "grants") if str(g.get("grant_id")) == gid), {})


@_guarded(SUPPORT)
async def _support(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], owner: Dict[str, Any],
                   other: Dict[str, Any]) -> None:
    jwt, tag = owner["access_token"], secrets.token_hex(4)
    ok, msg, code = await _call(rpc, parse, "theprotocol_sendChatMessage",
                                {"body": f"MCP tester: a message of its own ({tag})",
                                 "target_developer_id": int(other["developer_id"]),
                                 "client_ref": f"mcp-earn-{secrets.token_hex(6)}"}, jwt)
    conv = str(msg.get("conversation_id")) if ok and msg.get("conversation_id") else None
    if not conv:
        for tool in SUPPORT:
            _nm(outcomes, tool, f"no conversation of the run's own could be opened (HTTP {code}: {said(msg)})")
        return
    ok, page = await step(rpc, parse, "theprotocol_readThread", "3", {"conversation_id": conv}, jwt, outcomes)
    if ok and tag not in json.dumps(_rows(page, "messages"), default=str):
        _bug(outcomes, "theprotocol_readThread", "the thread does not carry the message just sent")
    ok, tk, code = await _call(rpc, parse, "theprotocol_submitSupportTicket",
                               {"subject": "MCP tester: its own ticket",
                                "message": "Made to grant a review of the run's own conversation, then closed.",
                                "category": "general", "priority": "low"}, jwt)
    ticket = tk.get("id") if ok else None
    if not isinstance(ticket, int):
        for tool in SUPPORT[1:]:
            _nm(outcomes, tool, f"no support ticket of the run's own could be opened (HTTP {code}: {said(tk)})")
        return
    try:
        ok, gr = await step(rpc, parse, "theprotocol_grantSupportReview", "3",
                            {"conversation_id": conv, "ticket_id": ticket}, jwt, outcomes)
        gid = str(gr.get("grant_id")) if ok and gr.get("grant_id") else None
        if ok and not gid:
            _bug(outcomes, "theprotocol_grantSupportReview", "answered 2xx without a grant id")
        ok, st = await step(rpc, parse, "theprotocol_getSupportReviewState", "3", {"conversation_id": conv}, jwt,
                            outcomes)
        if ok and gid and _grant(st, gid).get("live") is not True:
            _bug(outcomes, "theprotocol_getSupportReviewState", "the state does not read the grant just issued as live")
        if not gid:
            _nm(outcomes, "theprotocol_revokeSupportReview", "no grant of the run's own was issued")
        else:
            ok, ans = await step(rpc, parse, "theprotocol_revokeSupportReview", "3",
                                 {"conversation_id": conv, "grant_id": gid}, jwt, outcomes)
            if ok:
                ok2, st2, code2 = await _call(rpc, parse, "theprotocol_getSupportReviewState",
                                              {"conversation_id": conv}, jwt)
                g = _grant(st2, gid) if ok2 else {}
                if not ok2:
                    _bug(outcomes, "theprotocol_revokeSupportReview",
                         f"the review state could not be read afterwards (HTTP {code2})")
                elif g.get("live") is not False or not g.get("revoked_at"):
                    _bug(outcomes, "theprotocol_revokeSupportReview",
                         f"the state reads live={g.get('live')!r} revoked_at={g.get('revoked_at')!r} afterwards")
    finally:
        rpc_admin = getattr(bag, "rpc_admin", None)
        if rpc_admin is not None:
            await rpc_admin("theprotocol_supportCloseTicket",
                            {"ticket_id": ticket, "status": "closed",
                             "message": "The MCP tester's own ticket, closed after its run."},
                            jwt=bag.developer_jwt, timeout=20)


# ── agents ───────────────────────────────────────────────────────────────────────────────────────────────────────

async def lifecycle_earn_dev_agents(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    t = Throwaways(rpc, parse, bag, "dev-agents")
    try:
        dev = await t.developer("dev-agents")
        a1 = await t.agent(dev, "a")
        a2 = await t.agent(dev, "b")
        why = a1.get("why") or a2.get("why")
        if why:
            for tool in AGENTS:
                _nm(outcomes, tool, f"no two agents of the run's own: {why}")
            return
        await _dev_agents(rpc, parse, bag, outcomes, dev, a1, a2)
    finally:
        await t.close()


async def _token_for(rpc: Any, parse: Any, cid: str, secret: str, jwt: str) -> Tuple[bool, str]:
    ok, body, code = await rpc("theprotocol_getAgentToken", {"client_id": cid, "client_secret": secret}, jwt=jwt,
                               timeout=20)
    tok = parse(body) if isinstance(body, dict) else {}
    return bool(ok and isinstance(tok, dict) and tok.get("access_token")), str(code)


@_guarded(AGENTS)
async def _dev_agents(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], dev: Dict[str, Any],
                      a1: Dict[str, Any], a2: Dict[str, Any]) -> None:
    jwt = dev["access_token"]
    # a transfer between the run's two agents (the first holds the frame's grant), then its ledger record
    tool = "theprotocol_getTegTransactionDetail"
    ok, tx, code = await _call(rpc, parse, "theprotocol_transferUnits",
                               {"recipient_did": a2["did"], "amount": "0.5",
                                "message": "MCP tester: between two agents of its own"}, a1["agent_jwt"])
    txid = str(tx.get("transaction_id")) if ok and tx.get("transaction_id") else None
    if not txid:
        _nm(outcomes, tool, f"no transfer of the run's own could be made (HTTP {code}: {said(tx)})")
    else:
        for _ in range(8):                                     # the ledger records the transfer a moment later
            seen, _ans, _c = await _call(rpc, parse, tool, {"transaction_id": txid}, jwt)
            if seen:
                break
            await asyncio.sleep(2)
        ok, got = await step(rpc, parse, tool, "3", {"transaction_id": txid}, jwt, outcomes)
        if ok and (str(got.get("transaction_id")) != txid or str(got.get("to")) != a2["did"]):
            _bug(outcomes, tool, f"the record reads transaction_id={got.get('transaction_id')!r} to={got.get('to')!r}, "
                                 f"not the run's own transfer")
    # the second agent's credentials reset with the owner's password: a new client id and secret
    tool = "theprotocol_resetAgentCredentialsOnboard"
    await refusal_step(rpc, parse, tool, "3", {"agent_did": a2["did"], "password": dev["password"] + "-not-it"}, jwt,
                       outcomes, "with a wrong password", codes=(403,), text="invalid password")
    ok, ans = await step(rpc, parse, tool, "3", {"agent_did": a2["did"], "password": dev["password"]}, jwt, outcomes)
    if ok:
        cid, secret = ans.get("client_id"), ans.get("client_secret")
        if not (cid and secret) or cid == a2["client_id"]:
            _bug(outcomes, tool, "answered 2xx without a new client id and secret")
        else:
            old_ok, _c = await _token_for(rpc, parse, a2["client_id"], a2["client_secret"], jwt)
            new_ok, code_n = await _token_for(rpc, parse, cid, secret, jwt)
            if old_ok:
                _bug(outcomes, tool, "the OLD credentials still get an agent token after the reset")
            elif not new_ok:
                _bug(outcomes, tool, f"the NEW credentials get no agent token (HTTP {code_n})")
    # an enabled achievement, no agent named: recorded, nothing paid (the cheapest one, a free one where listed)
    tool = "theprotocol_recordAchievement"
    ok, cat, code = await _call(rpc, parse, "theprotocol_getAchievementCatalog", {}, jwt)
    rows = sorted((r for r in _rows(cat, "achievements") if r.get("type")),
                  key=lambda r: float(r.get("payout_avt") or 0))
    if not rows:
        _nm(outcomes, tool, f"the catalog lists no enabled achievement (HTTP {code})")
    else:
        kind = str(rows[0]["type"])
        ok, rec = await step(rpc, parse, tool, "3", {"achievement_type": kind}, jwt, outcomes)
        got = rec.get("achievement") if isinstance(rec.get("achievement"), dict) else {}
        if ok and (rec.get("status") != "awarded" or got.get("type") != kind or float(got.get("payout_avt") or 0)):
            _bug(outcomes, tool, f"the answer reads status={rec.get('status')!r} type={got.get('type')!r} "
                                 f"payout={got.get('payout_avt')!r}, not a fresh award that paid nothing")
        elif ok:
            ok2, again, _c = await _call(rpc, parse, tool, {"achievement_type": kind}, jwt)
            if ok2 and again.get("status") != "already_earned":
                _bug(outcomes, tool, f"a second record answered status={again.get('status')!r}, not already_earned")
    # the agent builder: a package for a simple wrapper, a zip
    tool = "theprotocol_agentBuilderGenerate"
    ok, pkg = await step(rpc, parse, tool, "3", {"spec": {
        "agent_name": "MCP Earn Builder", "agent_description": "The MCP tester's generated package, discarded.",
        "agent_builder_type": "simple_wrapper", "wrapper_llm_backend_type": "local_openai_compatible",
        "wrapper_model_name": "mcp-earn-model", "wrapper_system_prompt": "Answer briefly."}}, jwt, outcomes)
    if ok and not zip_answer(pkg)[0]:          # V0640: the PK signature in raw, or the manifest's files
        _bug(outcomes, tool, "answered 2xx without a zip archive")
    # the template bundle for the first agent (its DID and client id; the route leaves the secret out), a zip
    tool = "theprotocol_agentBuilderGenerateTemplate"
    ok, lst, code = await _call(rpc, parse, "theprotocol_listAgentBuilderTemplates", {}, jwt)
    avail = [r for r in _rows(lst, "templates") if r.get("available") and r.get("template_id")]
    if not avail:
        _nm(outcomes, tool, f"this frame lists no available agent template (HTTP {code})")
    else:
        ok, pkg = await step(rpc, parse, tool, "3", {"template_spec": {
            "template_id": str(avail[0]["template_id"]), "agent_name": "MCP Earn Template",
            "human_readable_id": "mcp-earn-template", "agent_did": a1["did"], "client_id": a1["client_id"]}},
            jwt, outcomes)
        if ok and not zip_answer(pkg)[0]:
            _bug(outcomes, tool, "answered 2xx without a zip archive")


# ── what the outside view found (V0650, tester batch 1 item 3, Guild order gwo_2015b757c94ce69138500df6) ─────────────

ONBOARD_NAMED = "onboarding: create_agent names its placeholder card after agent_name"
# §MCPTEST30 (V0650, tester batch 2 item 5, Guild order gwo_e3bad842b1a5943022b01d40): the outside view's V0649 re-check
# (the dev machine, 2026-10-31; order (n), session-release's 19a504ab8) found the credential and the manual naming two
# addresses for one registry (on EU: https://theprotocol.cloud and https://eu.theprotocol.cloud)
ONBOARD_MANUAL = "onboarding: the operator manual names the registry address its credentials name"
_MANUAL_URL = re.compile(r"`REGISTRY_URL`\s*(?:\|\s*|=\s*)`([^`\s]+)`")


def manual_registry_url(text: str) -> Optional[str]:
    """The registry URL the served operator manual was filled in with: its live-facts line (`REGISTRY_URL` | `<url>`,
    or the degraded `REGISTRY_URL` = `<url>`); None when it carries neither."""
    m = _MANUAL_URL.search(text or "")
    return m.group(1).rstrip("/") if m else None


async def _manual_names_the_credential_home(http: Any, outcomes: Dict[str, dict], home: Any, t0: float) -> None:
    """The manual a client downloads names the address the credential create_agent just issued names: the console decides
    "this registry or another" by a credential's origin, so two addresses for one registry split one client in two
    (routers/downloads._manual_base_url, V0650). Public reads only; the row keeps the two addresses, which are public."""
    if not home:
        return _nm(outcomes, ONBOARD_MANUAL, "create_agent's answer names no registry_url, so no credential named a "
                                             "home to compare the manual with")
    code, text = await http("GET", "/api/v1/downloads/CLAUDE.md")
    ms = int((time.time() - t0) * 1000)
    if not str(code).startswith("2"):
        return tool_row(ONBOARD_MANUAL, outcomes, "3", False, code, ms,
                        f"the operator manual (/api/v1/downloads/CLAUDE.md) answered HTTP {code or '?'}", {})
    named = manual_registry_url(text)
    if named is None:
        return _nm(outcomes, ONBOARD_MANUAL, "the operator manual carries no REGISTRY_URL line (its live-facts block is "
                                             "gone), so the address it was filled in with cannot be read")
    want = str(home).rstrip("/")
    fail = None if named == want else (
        f"the operator manual names {named!r} as REGISTRY_URL while the credential create_agent issued names {want!r}: "
        f"a client that reads both meets two addresses for one registry (the outside view's V0649 re-check)")
    tool_row(ONBOARD_MANUAL, outcomes, "3", fail is None, code, ms, fail,
             {"manual_registry_url": named, "credential_registry_url": want})


async def lifecycle_earn_onboard_agent_name(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The external test's run 1 (a newcomer from outside, 2026-10-30) created its agents the manuals' way, POST
    /api/v1/onboard/create_agent with agent_host and agent_name, and the placeholder card came out named after the host:
    the schema dropped agent_name silently (fixed in V0649). A developer of the run's own asks for a bootstrap token
    and creates an agent that way; the card the registry built (getAgentCardById) must carry the agent_name sent. Its
    host is a name under theprotocol.cloud that no DNS record answers (NXDOMAIN, and no one else can make it answer):
    from V0650 this rail refuses a special-use name such as .invalid (session-release's order (e), 4aba8d0e3), and a
    domain someone else owns could one day serve a card the pull-sync would read. The agent's balance goes back to the treasury and
    it is deleted with its developer (Throwaways.adopt, close). The row keeps the two names and the card id, never the
    credentials the creation answers."""
    http = getattr(bag, "http_in_target", None)
    if http is None:
        return _nm(outcomes, ONBOARD_NAMED, "this flow has no in-target transport (bag.http_in_target): the onboarding "
                                            "route takes a Bootstrap-Token header, which the MCP bridges cannot send")
    tag = secrets.token_hex(3)
    t0 = time.time()
    t = Throwaways(rpc, parse, bag, "onboard-agent-name")
    try:
        dev = await t.developer("onboard-agent-name")
        if dev.get("why"):
            return _nm(outcomes, ONBOARD_NAMED, f"no developer of the run's own: {dev['why']}")
        jwt = dev["access_token"]
        code, text = await http("POST", "/api/v1/onboard/bootstrap/request-token", bearer=jwt, body=json.dumps(
            {"agent_type_hint": "mcp_tester", "requested_by": "mcp_tester_onboard_agent_name"}).encode())
        try:
            token = (json.loads(text) or {}).get("bootstrap_token") if str(code).startswith("2") else None
        except ValueError:
            token = None
        if not token:
            return _nm(outcomes, ONBOARD_NAMED, f"the run's developer got no bootstrap token (HTTP {code or '?'})")
        name = f"MCP tester named card {tag}"
        code, text = await http("POST", "/api/v1/onboard/create_agent", headers={"Bootstrap-Token": token},
                                body=json.dumps({"agent_did_method": "theprotocol", "agent_name": name,
                                                 "agent_host": f"https://mcp-earn-{tag}.tester.theprotocol.cloud"}).encode())
        try:
            made = json.loads(text) if str(code).startswith("2") else {}
        except ValueError:
            made = {}
        made = made if isinstance(made, dict) else {}
        did, card_id = made.get("agent_did"), made.get("agent_card_id")
        if did:
            t.adopt(did, jwt)
        await _manual_names_the_credential_home(http, outcomes, made.get("registry_url"), t0)
        if not (did and card_id):
            return tool_row(ONBOARD_NAMED, outcomes, "3", False, code, int((time.time() - t0) * 1000),
                            f"create_agent with agent_host and agent_name answered HTTP {code or '?'} without an "
                            f"agent_did and an agent_card_id", {"agent_name": name})
        ok, body, c2 = await rpc("theprotocol_getAgentCardById", {"card_id": str(card_id)}, jwt=jwt, timeout=20)
        card = parse(body) if isinstance(body, dict) else {}
        got = (card.get("card_data") or {}).get("name") if ok and isinstance(card, dict) else None
        fail = None if got == name else (
            f"the placeholder card is named {got!r}, not the agent_name sent ({name!r}): the outside view's run 1 "
            f"found it named after the host" if ok else f"getAgentCardById answered HTTP {c2} for the new card")
        tool_row(ONBOARD_NAMED, outcomes, "3", fail is None, code, int((time.time() - t0) * 1000), fail,
                 {"agent_name": name, "card_name": got, "agent_card_id": str(card_id)})
    finally:
        await t.close()
        if ONBOARD_MANUAL not in outcomes:
            _nm(outcomes, ONBOARD_MANUAL, "the onboarding lifecycle created no agent, so no credential named a home")


MANIFEST = "theprotocol_getDownloadsManifest"
_HEX64 = re.compile(r"[0-9a-f]{64}")


def manifest_findings(files: List[Dict[str, Any]], served: Dict[str, Optional[bytes]]
                      ) -> Tuple[List[str], List[str], int]:
    """(findings, unread, checked): each listed file held to its download (`served`: url -> the bytes, None when they
    could not be read). A file served as stored matches the size and sha256 the manifest gives; a file rendered per
    request gives neither (no download of it equals the stored file) and keeps its template's under keys of its own
    (routers/downloads.downloads_manifest, V0650)."""
    findings: List[str] = []
    unread: List[str] = []
    checked = 0
    for e in files:
        name, url = str(e.get("filename") or "?"), str(e.get("url") or "")
        if e.get("available") is False:
            continue
        raw = served.get(url)
        if raw is None:
            unread.append(name)
            continue
        checked += 1
        if e.get("rendered_per_request") is True:
            if e.get("size_bytes") is not None or e.get("sha256") is not None:
                findings.append(f"{name} is rendered per request, yet the manifest gives it a size or a sha256 "
                                f"(size_bytes={e.get('size_bytes')!r}) that no download of it matches")
            if not (isinstance(e.get("template_size_bytes"), int)
                    and _HEX64.fullmatch(str(e.get("template_sha256") or ""))):
                findings.append(f"{name} is rendered per request and the manifest names no template_size_bytes and "
                                f"template_sha256")
            continue
        size, digest = e.get("size_bytes"), str(e.get("sha256") or "")
        if size != len(raw):
            findings.append(f"the manifest says {name} has {size!r} bytes, its download has {len(raw)}")
        if digest != hashlib.sha256(raw).hexdigest():
            findings.append(f"the manifest's sha256 for {name} ({digest[:12] or 'none'}) is not its download's")
    return findings, unread, checked


async def lifecycle_earn_downloads_as_served(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """§MCPTEST30 (V0650, tester batch 2 item 5, Guild order gwo_e3bad842b1a5943022b01d40): the outside view's V0649
    re-check (the dev machine, 2026-10-31; order (n), session-release's 19a504ab8) checked each download against the
    manifest and refused an honest CLAUDE.md: the manifest named 35621 bytes and the download had 36733, since the
    manual is rendered per request. getDownloadsManifest is read and every file it lists downloaded inside the target:
    a file served as stored must match its size and sha256, a file rendered per request must claim neither. Read only;
    the row keeps file names and counts, never a file's bytes."""
    b64 = getattr(bag, "http_b64_in_target", None)
    if b64 is None:
        return unmeasured(outcomes, MANIFEST, "1", "this flow carries no transport for a file's bytes from inside the "
                                                   "target (bag.http_b64_in_target), so no download was read")
    t0 = time.time()
    # a public tool, with the run's developer token: the MCP endpoint answers 401 to a call without one (the trial pair
    # nt261031x4: "answered HTTP 401 and lists 0 files")
    ok, body, code = await rpc(MANIFEST, {}, jwt=bag.developer_jwt, timeout=30)
    man = parse(body) if isinstance(body, dict) else {}
    files = _rows(man, "files")
    if not (ok and files):
        return tool_row(MANIFEST, outcomes, "1", False, code, int((time.time() - t0) * 1000),
                        f"getDownloadsManifest answered HTTP {code} and lists {len(files)} files", {})
    served: Dict[str, Optional[bytes]] = {}
    for e in files:
        url = str(e.get("url") or "")
        if e.get("available") is False or not url.startswith("/api/v1/downloads/"):
            continue
        st, enc = await b64(url)
        try:
            served[url] = base64.b64decode((enc or "").strip(), validate=True) if st == "200" else None
        except (binascii.Error, ValueError):
            served[url] = None
    findings, unread, checked = manifest_findings(files, served)
    ms = int((time.time() - t0) * 1000)
    if not checked:
        return unmeasured(outcomes, MANIFEST, "1", f"no file the manifest lists could be downloaded inside the target "
                                                   f"({', '.join(unread) or 'none listed as available'})")
    tool_row(MANIFEST, outcomes, "1", True, code, ms, None,
             {"files": [str(e.get("filename")) for e in files], "checked": checked, "unread": unread,
              "rendered_per_request": [str(e.get("filename")) for e in files if e.get("rendered_per_request") is True]})
    if findings:
        lc()._bugfind(outcomes, MANIFEST, "1", "getDownloadsManifest: " + "; ".join(findings))


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_onboard_agent_name", "runner": lifecycle_earn_onboard_agent_name},
    {"name": "earn_downloads_as_served", "runner": lifecycle_earn_downloads_as_served},
    {"name": "earn_cicd", "runner": lifecycle_earn_cicd},
    {"name": "earn_org", "runner": lifecycle_earn_org},
    {"name": "earn_support_review", "runner": lifecycle_earn_support_review},
    {"name": "earn_dev_agents", "runner": lifecycle_earn_dev_agents},
]
