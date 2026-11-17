"""§MCPTEST30 V0662 Wave 1 (gwo_fe22d7e8c391ce1abedc10c7, session-tester): refusal-only slice 1, the success legs of
the tools sessionlogs2026/CLASSIFICATION_2026-11-13_MCP_REFUSAL_ONLY.md found with no 2xx row in either nightly run
of 2026-11-13 (sbx-alpha 27c26bffae1b47e4, registry-test af9acb641ba64fe6).

The three earned without a decision (A1 and C):
  quantum workload  getQuantumWorkload on the DID discoverQuantumAgents answers in the same run (a card that states a
                    workload: sbx-alpha holds the V0660 (i) drive provider's), its answer read for that DID, the
                    extension's URI and its params; the refusal on a card that states none is kept beside it. Where
                    quantum workloads are off the tool is not listed and nothing is written.
  slash order       updateSlashOrder: getSlashOrder, one step's max_percent changed by one, the new version and the
                    order read back, SlashWaterfallChanged on the ledger, then the order written back as it was and read
                    back again. Only where the target itself states "sandbox": a slash in the seconds between the
                    change and its write-back would drain the interim order (Δ-neutral either way: an order is policy).
  order room        guildSetOrderRoom: an agent of the run's admin posts one order of DUST without a room, opens a
                    conversation with a second agent of the run (the room it takes part in and may post in), names it
                    the order's room; guildGetOrder reads announce_conversation_id, the room reads the order's card.
                    The order is cancelled (the bounty refunded), the agents' balances go back to the treasury
                    (Throwaways). Only where the target itself states "sandbox" (a bounty is escrowed).

And the first of the three states his seq 3182 allowed (A2; the other two: earned_ad_developers' unverified account,
mcp_lifecycles' failed commons payment):
  drift flag        acknowledgeAgentFlag: a persistent_drift flag raised by hand, through the target's database, on an
                    agent of the run's own (source `mcp_tester`), read in getAdminAgentFlags, acknowledged, read back
                    acknowledged, then deleted with the agent. Only where the target itself states "sandbox".

And the OAuth federation surface (A7), on a trust entry of the run's own rather than a setting: the entry is added
through the admin route (POST /oauth/federation/trust, no MCP tool) for an issuer at a `.invalid` host, so no subject
token can ever verify against it while it stands; then
  oauthIntrospect   the route authenticates the entry's client and answers RFC 7662 for a token it never issued:
                    active false (a wrong secret is a refusal row: 401);
  oauthRevoke       RFC 7009 for a jti it never issued: 200, revoked false;
  deleteOauthFederationTrust   removes the entry (oauthFederationTrustList no longer names it).
  oauthTokenExchange is NOT MEASURED, said: a subject token must be signed by a trusted peer's federation key, and a
                    registry signs with it only when it answers an exchange itself, so no registry of this network can
                    give a run the first one. Its refusal of a token no peer signed is kept as a refusal row.
Only where the target itself states "sandbox"; the entry lives seconds and is deleted in a finally.
"""
from __future__ import annotations

import copy
import json
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts import earned_fixtures as ef
from agentvault_registry.api_tests.contracts.earned_agent_public import (
    DUST, _admin_dev, _d, _rest, _tag, close_guild_orders, sandbox_stated,
)

QUANTUM = "theprotocol_getQuantumWorkload"
SLASH = "theprotocol_updateSlashOrder"
ROOM = "theprotocol_guildSetOrderRoom"
FLAG = "theprotocol_acknowledgeAgentFlag"
INTROSPECT, REVOKE = "theprotocol_oauthIntrospect", "theprotocol_oauthRevoke"
EXCHANGE, TRUST_DEL = "theprotocol_oauthTokenExchange", "theprotocol_deleteOauthFederationTrust"
OAUTH_TOOLS = ((INTROSPECT, "3"), (REVOKE, "3"), (EXCHANGE, "3"))
NO_DID = "did:theprotocol:00000000-0000-4000-8000-0000000000aa"
_OWN_STEPS = ("bond", "stake", "liquid")


async def _admin_read(bag: Any, parse: Any, tool: str, args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    """An admin call that records no row: (ok, the answer as parsed, the code)."""
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return False, {}, ""
    ok, body, code = await rpc_admin(tool, args, jwt=bag.developer_jwt, timeout=30)
    return bool(ok), _d(parse(body) if isinstance(body, dict) else {}), str(code)


async def _sandbox(rpc: Any, parse: Any, bag: Any) -> Tuple[bool, str]:
    ok, body, code = await rpc("theprotocol_getPublicRegistryConfig", {}, jwt=bag.developer_jwt, timeout=30)
    return sandbox_stated(bool(ok), code, _d(parse(body)) if ok else None)


# ── C: getQuantumWorkload on a card that states a workload ──────────────────────────────────────────────────────────

async def lifecycle_earn_quantum_workload(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """getQuantumWorkload on the first quantum agent discovery answers (the module docstring)."""
    ok, body, code = await rpc("theprotocol_discoverQuantumAgents", {"limit": 5}, jwt=bag.developer_jwt, timeout=30)
    ans = _d(parse(body) if isinstance(body, dict) else {})
    if not ok or "agents" not in ans:
        if "quantum_workloads_off" in json.dumps(ans, default=str):
            return                          # not listed here: the walker meets neither tool, nothing to write
        return ef.unmeasured(outcomes, QUANTUM, "1", f"discoverQuantumAgents answered HTTP {code} ({ef.said(ans)}), "
                                                    f"so no card that states a workload could be named")
    agents = [a for a in ans.get("agents") or [] if isinstance(a, dict) and a.get("did") and a.get("quantum")]
    if not agents:
        ef.unmeasured(outcomes, QUANTUM, "1", "discoverQuantumAgents lists no agent whose card states a quantum "
                                              "workload on this target, so there is no card to read one from")
    else:
        did = str(agents[0]["did"])
        ok, r = await ef.step(rpc, parse, QUANTUM, "1", {"did": did}, bag.developer_jwt, outcomes)
        if ok:
            got = _d(r)
            why = None
            if got.get("agent_did") != did:
                why = f"the answer is for {got.get('agent_did')!r}, not the DID asked for"
            elif not got.get("uri") or not isinstance(got.get("params"), dict):
                why = "the answer carries no extension URI or no params"
            elif not isinstance(_d(got.get("check")).get("valid"), bool):
                why = "the answer carries no check of the extension"
            if why:
                ef.lc()._bugfind(outcomes, QUANTUM, "1", f"getQuantumWorkload: {why}")
    # the contract's negative test, kept beside the success: a DID with no card here names its refusal
    await ef.refusal_step(rpc, parse, QUANTUM, "1", {"did": NO_DID}, bag.developer_jwt, outcomes,
                          "a DID with no card on this registry", codes=(404,),
                          text=("agent_card_not_found", "no_quantum_workload"))


# ── A1: updateSlashOrder, changed by one and written back ───────────────────────────────────────────────────────────

def _step_enabled(step: Any) -> bool:
    """The product's rule (services/slash_order.enabled): a step drains unless it says `"enabled": false`. V0666: this
    leg asked for `enabled is True`, which the factory default order (no `enabled` key on any step) never says, so on a
    frame running the default order it found no step to change."""
    from agentvault_registry.services.slash_order import enabled
    return enabled(step)


def _changed(order: List[Dict[str, Any]]) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """The order with one of the agent's own enabled steps' max_percent moved by one (inside 0..100), and which."""
    new = copy.deepcopy(order)
    for step in new:
        if not isinstance(step, dict) or step.get("source") not in _OWN_STEPS or not _step_enabled(step):
            continue
        mp = step.get("max_percent")
        if isinstance(mp, bool) or not isinstance(mp, (int, float)) or not 0 <= mp <= 100:
            continue
        step["max_percent"] = mp - 1 if mp >= 1 else mp + 1
        return new, f"{step['source']} {mp} -> {step['max_percent']}"
    return None, ""


async def lifecycle_earn_slash_order(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """updateSlashOrder on the target's own order, written back as it was (the module docstring)."""
    if getattr(bag, "rpc_admin", None) is None:
        return ef.effect_unmeasured(outcomes, SLASH, "this flow carries no admin bridge (bag.rpc_admin)")
    staged, why = await _sandbox(rpc, parse, bag)
    if not staged:
        return ef.effect_unmeasured(outcomes, SLASH, "the slash order is changed only where the target itself states "
                                                     "'sandbox' (a slash between the change and its write-back would "
                                                     f"drain the interim order): {why}")
    ok, cur, code = await _admin_read(bag, parse, "theprotocol_getSlashOrder", {})
    original = cur.get("value")
    if not ok or not isinstance(original, list) or not original:
        return ef.effect_unmeasured(outcomes, SLASH, f"getSlashOrder answered HTTP {code} with no order to change "
                                                     f"({ef.said(cur)})")
    new, what = _changed(original)
    if new is None:
        return ef.effect_unmeasured(outcomes, SLASH, "the order has no enabled bond, stake or liquid step whose "
                                                     "max_percent could move by one")
    before = int(cur.get("version") or 0)

    def check(a: Dict[str, Any]) -> Optional[str]:
        if a.get("slash_waterfall_changed") is not True:
            return f"the answer reads slash_waterfall_changed={a.get('slash_waterfall_changed')!r} after {what}"
        if not int(a.get("version") or 0) > before:
            return f"the answer reads version {a.get('version')!r}, not one past {before}"
        return None
    try:
        ok, _ans = await ef.effect(bag, parse, SLASH, {"order": new, "reason": f"MCP tester: {what}, written back "
                                                       f"next"}, outcomes, check=check,
                                   expect_events=["SlashWaterfallChanged"])
        if ok:
            okr, after, _c = await _admin_read(bag, parse, "theprotocol_getSlashOrder", {})
            if not okr or after.get("value") != new:
                ef.lc()._bugfind(outcomes, ef.effect_name(SLASH), "admin_effect",
                                 f"updateSlashOrder: getSlashOrder does not read the order just written ({what})")
    finally:
        okw, _b, cw = await _admin_read(bag, parse, SLASH, {"order": original, "reason": "MCP tester: the order "
                                                             "written back as it was"})
        okb, back, _c = await _admin_read(bag, parse, "theprotocol_getSlashOrder", {})
        if not (okb and back.get("value") == original):
            ef.lc()._bugfind(outcomes, ef.effect_name(SLASH), "admin_effect",
                             f"updateSlashOrder: the original order could not be written back (HTTP {cw}); the "
                             f"target's slash order now reads {back.get('value')!r}")


# ── A1: guildSetOrderRoom on an order of the run's own ──────────────────────────────────────────────────────────────

async def lifecycle_earn_guild_order_room(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """guildSetOrderRoom on an order the run posted without a room (the module docstring)."""
    staged, why = await _sandbox(rpc, parse, bag)
    if not staged:
        return ef.unmeasured(outcomes, ROOM, "2", f"an order is posted (its bounty escrowed) only where the target "
                                                  f"itself states 'sandbox': {why}")
    t = ef.Throwaways(rpc, parse, bag, "order-room")
    P: Dict[str, Any] = {}
    oid = ""
    try:
        P = await t.agent(_admin_dev(bag), "poster")
        Q = await t.agent(_admin_dev(bag), "peer")
        if P.get("why") or Q.get("why"):
            return ef.unmeasured(outcomes, ROOM, "2", f"no poster or peer agent ({P.get('why') or Q.get('why')})")
        st, resp = await _rest(bag, parse, "POST", "/api/v1/teg/treasury/fund-agent", {
            "target_agent_did": P["did"], "amount": format(Decimal(DUST) * 2, "f"), "reason": "admin_grant",
            "reference_id": f"mcp-order-room-{_tag()}"})
        if st != 200:
            return ef.unmeasured(outcomes, ROOM, "2", f"the treasury could not fund the poster (HTTP {st}: "
                                                      f"{ef.said(resp)})")
        ok, body, code = await rpc("theprotocol_guildPostOrder", {
            "title": f"MCP tester order room {_tag()}", "bounty": DUST, "agent_jwt": P["agent_jwt"]},
            jwt=bag.developer_jwt, timeout=30)
        oid = str(_d(parse(body) if isinstance(body, dict) else {}).get("order_id") or "") if ok else ""
        if not oid:
            return ef.unmeasured(outcomes, ROOM, "2", f"the order without a room could not be posted (HTTP {code})")
        ok, body, code = await rpc("theprotocol_sendChatMessage", {
            "body": f"MCP tester: the room order {oid} shows in", "target_agent_did": Q["did"],
            "client_ref": f"mcp-order-room-{uuid.uuid4().hex[:12]}", "agent_jwt": P["agent_jwt"]},
            jwt=bag.developer_jwt, timeout=30)
        room = str(_d(parse(body) if isinstance(body, dict) else {}).get("conversation_id") or "") if ok else ""
        if not room:
            return ef.unmeasured(outcomes, ROOM, "2", f"the poster could not open a conversation to name (HTTP {code})")
        ok, r = await ef.step(rpc, parse, ROOM, "2", {"order_id": oid, "room_id": room, "agent_jwt": P["agent_jwt"]},
                              bag.developer_jwt, outcomes)
        if ok:
            okg, gb, _c = await rpc("theprotocol_guildGetOrder", {"order_id": oid}, jwt=bag.developer_jwt, timeout=20)
            order = _d(_d(parse(gb) if isinstance(gb, dict) else {}).get("order")) if okg else {}
            okt, tb, _c = await rpc("theprotocol_readThread", {"conversation_id": room, "limit": 50,
                                                               "agent_jwt": P["agent_jwt"]},
                                    jwt=bag.developer_jwt, timeout=20)
            msgs = _d(parse(tb) if isinstance(tb, dict) else {}).get("messages") if okt else None
            carded = isinstance(msgs, list) and any(
                isinstance(m, dict) and m.get("kind") != "text" and oid in json.dumps(m, default=str) for m in msgs)
            why = None
            if str(order.get("announce_conversation_id") or "") != room:
                why = f"guildGetOrder reads announce_conversation_id={order.get('announce_conversation_id')!r}"
            elif not carded:
                why = "the room holds no card naming the order"
            if why:
                ef.lc()._bugfind(outcomes, ROOM, "2", f"guildSetOrderRoom: {why}")
        # the contract's negative test, kept beside the success: an order id that names nothing is refused first
        await ef.refusal_step(rpc, parse, ROOM, "2", {"order_id": "gwo_000000000000000000000000", "room_id": room,
                                                      "agent_jwt": P["agent_jwt"]}, bag.developer_jwt, outcomes,
                              "an order that does not exist", codes=(404,), text="Order not found")
    finally:
        if oid:
            await close_guild_orders(rpc, parse, [oid], P.get("agent_jwt") or "", "", bag.developer_jwt)
        await t.close()


# ── A2: acknowledgeAgentFlag on a flag the run raised on its own agent ──────────────────────────────────────────────

def _flag_of(answer: Any, fid: str) -> Optional[Dict[str, Any]]:
    rows = answer if isinstance(answer, list) else None
    if rows is None and isinstance(answer, dict):
        for k in ("flags", "items", "results"):
            if isinstance(answer.get(k), list):
                rows = answer[k]
                break
    return next((f for f in rows or [] if isinstance(f, dict) and str(f.get("id")) == fid), None)


async def lifecycle_earn_agent_flag(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """acknowledgeAgentFlag on a drift flag raised by hand on an agent of the run's own (the module docstring)."""
    from agentvault_registry.api_tests.contracts.earned_agent_public import _db_write
    if getattr(bag, "rpc_admin", None) is None:
        return ef.effect_unmeasured(outcomes, FLAG, "this flow carries no admin bridge (bag.rpc_admin)")
    staged, why = await _sandbox(rpc, parse, bag)
    if not staged:
        return ef.effect_unmeasured(outcomes, FLAG, "a flag is raised by hand only where the target itself states "
                                                    f"'sandbox': {why}")
    t = ef.Throwaways(rpc, parse, bag, "agent-flag")
    fid = str(uuid.uuid4())
    raised = False
    try:
        A = await t.agent(_admin_dev(bag), "flagged")
        if A.get("why"):
            return ef.effect_unmeasured(outcomes, FLAG, f"no agent of the run's own to flag ({A['why']})")
        n, why = await _db_write(bag, "INSERT INTO agent_flags (id, agent_did, flag_type, raised_at, reason, source) "
                                      "VALUES (CAST(:id AS uuid), :did, 'persistent_drift', now(), :reason, 'mcp_tester')",
                                 {"id": fid, "did": A["did"],
                                  "reason": "MCP tester: a drift flag raised by hand on the run's own agent (seq 3182)"})
        if why or n != 1:
            return ef.effect_unmeasured(outcomes, FLAG, f"the flag could not be raised ({why or f'{n} rows'})")
        raised = True
        ok, listed, code = await _admin_read(bag, parse, "theprotocol_getAdminAgentFlags", {"agent_did": A["did"]})
        row = _flag_of(listed, fid) if ok else None
        if row is None:
            return ef.effect_unmeasured(outcomes, FLAG, f"getAdminAgentFlags does not list the flag just raised "
                                                        f"(HTTP {code})")

        def check(a: Dict[str, Any]) -> Optional[str]:
            f = _d(a.get("flag")) or a
            if a.get("status") == "already_acknowledged":
                return "the answer reads already_acknowledged for a flag nobody had acknowledged"
            return None if f.get("acknowledged_at") else "the answer carries no acknowledged_at"
        ok, _ans = await ef.effect(bag, parse, FLAG, {"agent_did": A["did"], "flag_id": fid,
                                                      "notes": "MCP tester: acknowledged"}, outcomes, check=check,
                                   expect_events=["AgentFlagAcknowledged"])
        if ok:
            okr, again, _c = await _admin_read(bag, parse, "theprotocol_getAdminAgentFlags", {"agent_did": A["did"]})
            f2 = _flag_of(again, fid) if okr else None
            if not (f2 and f2.get("acknowledged_at")):
                ef.lc()._bugfind(outcomes, ef.effect_name(FLAG), "admin_effect",
                                 "acknowledgeAgentFlag: getAdminAgentFlags does not read the flag acknowledged")
    finally:
        if raised:
            await _db_write(bag, "DELETE FROM agent_flags WHERE id = CAST(:id AS uuid) AND source = 'mcp_tester'",
                            {"id": fid})
        await t.close()


# ── A7: the OAuth federation surface on a trust entry of the run's own ──────────────────────────────────────────────

def _trusted(listing: Any, url: str) -> Optional[bool]:
    """Whether the trust list names `url`; None when the answer is no list at all (unread, never 'absent')."""
    rows = listing if isinstance(listing, list) else None
    if rows is None and isinstance(listing, dict):
        for k in ("trusted_registries", "registries", "items", "trust"):
            if isinstance(listing.get(k), list):
                rows = listing[k]
                break
    if rows is None:
        return None
    return any(isinstance(r, dict) and str(r.get("registry_url") or "").rstrip("/") == url for r in rows)


async def lifecycle_earn_oauth_trust(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The OAuth tools on a trust entry of the run's own (the module docstring)."""
    def all_unmeasured(why: str) -> None:
        for tool, tier in OAUTH_TOOLS:
            ef.unmeasured(outcomes, tool, tier, why)
        ef.effect_unmeasured(outcomes, TRUST_DEL, why)
    if getattr(bag, "rpc_admin", None) is None:
        return all_unmeasured("this flow carries no admin bridge (bag.rpc_admin) to add a trust entry")
    staged, why = await _sandbox(rpc, parse, bag)
    if not staged:
        return all_unmeasured(f"a trust entry is added only where the target itself states 'sandbox': {why}")
    tag = uuid.uuid4().hex[:10]
    url = f"https://oauth-probe-{tag}.invalid"
    cid, secret = f"mcp-oauth-{tag}", uuid.uuid4().hex + uuid.uuid4().hex
    st, resp = await _rest(bag, parse, "POST", "/api/v1/oauth/federation/trust", {
        "registry_name": f"MCP tester {tag}", "registry_url": url, "client_id": cid, "client_secret": secret,
        "allowed_operations": ["introspect"], "public_key_url": f"{url}/oauth/.well-known/jwks.json"})
    if st not in (200, 201):
        return all_unmeasured(f"the run's own trust entry could not be added (HTTP {st}: {ef.said(resp)})")
    removed = False
    try:
        jwt = bag.developer_jwt
        ok, r = await ef.step(rpc, parse, INTROSPECT, "3", {"token": f"mcp-not-a-token-{tag}", "client_id": cid,
                                                            "client_secret": secret}, jwt, outcomes)
        if ok and _d(r).get("active") is not False:
            ef.lc()._bugfind(outcomes, INTROSPECT, "3", f"oauthIntrospect: a token this registry never issued reads "
                                                        f"active={_d(r).get('active')!r}")
        await ef.refusal_step(rpc, parse, INTROSPECT, "3", {"token": f"mcp-not-a-token-{tag}", "client_id": cid,
                                                            "client_secret": "wrong-" + secret[:20]}, jwt, outcomes,
                              "a client secret the entry does not hold", codes=(401,), text="client credentials")
        ok, r = await ef.step(rpc, parse, REVOKE, "3", {"jti": f"mcp-unknown-{tag}", "client_id": cid,
                                                        "client_secret": secret}, jwt, outcomes)
        if ok and _d(r).get("revoked") is not False:
            ef.lc()._bugfind(outcomes, REVOKE, "3", f"oauthRevoke: a jti this registry never issued reads "
                                                    f"revoked={_d(r).get('revoked')!r}")
        ef.unmeasured(outcomes, EXCHANGE, "3", "a subject token must be signed by a trusted peer's federation key, and "
                                               "a registry signs with it only when it answers an exchange itself: no "
                                               "registry of this network can give a run the first one")
        await ef.refusal_step(rpc, parse, EXCHANGE, "3", {
            "subject_token": f"mcp.not.signed-{tag}", "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "client_id": cid, "client_secret": secret}, jwt, outcomes, "a subject token no trusted peer signed",
            codes=(400, 401, 403), text=("token", "Token"))

        ok, _a = await ef.effect(bag, parse, TRUST_DEL, {"registry_url": url}, outcomes)
        removed = ok
        if ok:
            okl, body, _c = await rpc("theprotocol_oauthFederationTrustList", {}, jwt=jwt, timeout=20)
            still = _trusted(_d(parse(body)) if okl and isinstance(body, dict) else None, url)
            if still is not False:
                ef.lc()._bugfind(outcomes, ef.effect_name(TRUST_DEL), "admin_effect",
                                 "deleteOauthFederationTrust: the trust list "
                                 + ("still names the entry" if still else "could not be read afterwards"))
    finally:
        if not removed:
            await _admin_read(bag, parse, TRUST_DEL, {"registry_url": url})


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_quantum_workload", "runner": lifecycle_earn_quantum_workload},
    {"name": "earn_slash_order", "runner": lifecycle_earn_slash_order},
    {"name": "earn_guild_order_room", "runner": lifecycle_earn_guild_order_room},
    {"name": "earn_agent_flag", "runner": lifecycle_earn_agent_flag, "needs": ("target_db",)},
    {"name": "earn_oauth_trust", "runner": lifecycle_earn_oauth_trust},
]
