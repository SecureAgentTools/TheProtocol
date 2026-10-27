"""The cross-frame contract (§TWOAGENT G2, V0428-V0437): the hand-run proofs as flows the nightly re-runs.

Rows F7 (the whole lifecycle across the frames), F10 (the provider's owner is told by the replica) and F14 (the provider's
frame hears each milestone the home releases) of `sessionlogs2026/TESTPLAN_2026-09-23_TWOAGENT.md`, proven by hand on the
sandbox pair and on production (`ctr_58f55ded04fbd42df5ad4882`), plus V0437's one rail: the provider acts on its OWN
registry, as itself, through the tools a client uses (acceptContractFederated / submitContractWorkFederated are the v2
provider rail since V0437), and the legacy peer routes that let a peer act in an agent's name answer 410.

HOW A FLOW REACHES AN AGENT ROUTE. `adminRequest` takes an agent JWT as `developer_jwt` (the contract spine is agent-tier
throughout), the same way test_contract_spine_economic.py drives it. HOW IT HEARS AN OWNER: a webhook whose host is
`.invalid` (RFC 6761, it never resolves) and the dispatcher's own record (`getWebhookDeliveries`), the technique
test_chat_g1_federation.py established. An unreadable record is never read as silence.

⚠ Writes: throwaway agents named `fedsuite-xc-*` (soft-deleted at the end; what one holds goes back to its frame's
treasury first, throwaways, V0641), one contract per run (there is no delete-contract rail), a
treasury-backstopped bond on the provider (moves no money), and ONE funding of the client (0.5 of sandbox-A's currency)
through the canonical admin rail (FLOW 4). The contract itself moves 0.1 across the frames.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult, PreconditionUnmet, ensure_bonded,
)

_TAG = "fedsuite-xc"
_A, _B = "sandbox-A", "sandbox-B"
_ADMIN = {_A: "sandbox-A-admin", _B: "sandbox-B-admin"}
_REQUIRES = [_A, _B, _ADMIN[_A], _ADMIN[_B]]
_FUND = "0.5"
_TOTAL = "0.1"
_POLL = 4.0
_MIRROR_SEC = 240.0     # a fresh card reached the peer in 21.6-92.2 s on the sandbox (TESTPLAN F5)
_REPLICA_SEC = 150.0
_HEAR_SEC = 90.0
_BONDED = ("locked", "matured")


# ─── plumbing (the suite's house style: every file carries its own) ─────────

def _soft(r: Any) -> Optional[str]:
    if isinstance(r, dict) and set(r.keys()) == {"_text"} and isinstance(r["_text"], str):
        return r["_text"]
    if isinstance(r, str):
        return r
    return None


async def _call(rig, label: str, tool: str, args: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """MCP call -> (result, refusal). A non-None refusal carries the reason in the tool's own words."""
    try:
        r = await rig.mcp(label).call(tool, args, timeout=60)
    except Exception as e:  # noqa: BLE001 (MCPError included: a refusal, with its words)
        return None, f"{type(e).__name__}: {e}"
    if isinstance(r, dict) and r.get("error"):
        return r, str(r.get("error"))
    return r, _soft(r)


async def _rest(rig, method: str, endpoint: str, label: str, body: Optional[Dict[str, Any]] = None,
                jwt: Optional[str] = None) -> Tuple[int, Any]:
    """One REST call through adminRequest -> (status_code, body). `jwt` reaches an agent-tier route."""
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if jwt:
        args["developer_jwt"] = jwt
    try:
        r = await rig.mcp(label).call("adminRequest", args, timeout=60)
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"
    if not isinstance(r, dict):
        return -1, r
    code = r.get("status_code")
    return (code if isinstance(code, int) else -1), r.get("response")


def _num(v: Any) -> Optional[float]:
    """Balances come back in scientific notation ('1E+3'); None when absent."""
    try:
        return None if v is None else float(str(v))
    except (TypeError, ValueError):
        return None


async def _until(fn: Callable[[], Awaitable[Any]], budget: float, every: float = _POLL) -> Any:
    end = time.monotonic() + budget
    while True:
        last = await fn()
        if last or time.monotonic() >= end:
            return last
        await asyncio.sleep(every)


class _Legs:
    """Named legs with evidence. A flow passes only when EVERY planned leg ran and held; a leg that never ran fails."""

    def __init__(self, planned: List[str]):
        self.planned, self.got, self.evidence = list(planned), {}, {}

    def check(self, name: str, ok: bool, evidence: Any = None) -> bool:
        assert name in self.planned, f"unplanned leg {name}"
        self.got[name] = bool(ok)
        self.evidence[name] = evidence
        return bool(ok)

    def result(self, description: str, t0: float) -> AssertionResult:
        missing = [n for n in self.planned if n not in self.got]
        failed = [n for n, ok in self.got.items() if not ok]
        passed = not missing and not failed
        detail = None if passed else json.dumps({"failed": failed, "not_run": missing,
                                                 "evidence": {n: self.evidence.get(n) for n in failed}},
                                                default=str)[:700]
        return AssertionResult(passed=passed, description=description, budget_sec=0.0,
                               elapsed_sec=time.monotonic() - t0, polling_attempts=1,
                               last_state={"legs": self.got, "not_run": missing, "evidence": self.evidence},
                               failure_detail=detail)


async def _agent(rig, label: str, tag: str, made: List[Tuple[str, str]]) -> Dict[str, str]:
    name = f"{_TAG}-{tag}-{uuid.uuid4().hex[:8]}"
    r, refused = await _call(rig, label, "createAgent", {"name": name, "description": "federation suite cross-frame contract probe"})
    if refused or not isinstance(r, dict):
        raise PreconditionUnmet(f"createAgent refused on {label}: {refused}")
    creds = r.get("credentials") or {}
    cid, sec = r.get("client_id") or creds.get("client_id"), r.get("client_secret") or creds.get("client_secret")
    did = r.get("did") or r.get("agent_did") or (r.get("agent") or {}).get("did")
    throwaways.made(label, did)  # V0641: retired once its test's verdict is in (throwaways)
    if not (cid and sec and did):
        raise PreconditionUnmet(f"createAgent on {label}: no credential triple (keys={sorted(r)[:8]})")
    made.append((label, did))
    t, tref = await _call(rig, label, "getAgentToken", {"client_id": cid, "client_secret": sec})
    jwt = ((t or {}).get("access_token") or (t or {}).get("agent_jwt")) if isinstance(t, dict) else None
    if tref or not jwt:
        raise PreconditionUnmet(f"getAgentToken refused on {label}: {tref}")
    return {"did": did, "jwt": jwt, "name": name, "label": label}


async def _hook(rig, label: str, events: List[str], hooks: List[Tuple[str, str]]) -> str:
    r, refused = await _call(rig, label, "createWebhook", {
        "url": f"https://{_TAG}-{uuid.uuid4().hex[:10]}.invalid/hook", "events": events,
        "description": "federation suite cross-frame contract: a host that never resolves; the flow reads the record"})
    if refused or not isinstance(r, dict) or not r.get("id"):
        raise PreconditionUnmet(f"createWebhook refused on {label}: {refused or str(r)[:160]}")
    hooks.append((label, r["id"]))
    return r["id"]


async def _told(rig, label: str, hook_id: str, event: str, cid: str) -> Optional[List[Dict[str, Any]]]:
    """What the dispatcher sent this hook for `event` on contract `cid`, or None when the record could not be read."""
    r, refused = await _call(rig, label, "getWebhookDeliveries", {"webhook_id": hook_id, "limit": 100})
    if refused or not isinstance(r, dict) or not isinstance(r.get("deliveries"), list):
        return None
    out, seen = [], set()
    for d in r["deliveries"]:
        if not isinstance(d, dict) or d.get("event_type") != event:
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        data = p.get("data") if isinstance(p.get("data"), dict) else p
        if str(data.get("contract_id") or data.get("id") or "") != cid:
            continue
        ident = p.get("id") or d.get("id")
        if ident not in seen:
            seen.add(ident)
            out.append(data)
    return out


async def _cleanup(rig, made: List[Tuple[str, str]], hooks: List[Tuple[str, str]]) -> List[str]:
    left: List[str] = []
    for label, hook_id in hooks:
        _, refused = await _call(rig, label, "deleteWebhook", {"webhook_id": hook_id})
        if refused:
            left.append(f"webhook {hook_id} on {label}: {refused[:120]}")
    for label, did in made:
        _, refused = await throwaways.retire(rig, label, did)      # V0641: what it holds goes back first
        if refused:
            left.append(f"agent {did} on {label}: {refused[:120]}")
    return left


async def _run(rig, planned: List[str], description: str,
               body: Callable[[_Legs, List[Tuple[str, str]], List[Tuple[str, str]]], Awaitable[None]]) -> AssertionResult:
    t0 = time.monotonic()
    legs = _Legs(planned + ["the_flow_removed_what_it_made"])
    made: List[Tuple[str, str]] = []
    hooks: List[Tuple[str, str]] = []
    ran = False
    try:
        await body(legs, made, hooks)
        ran = True
    finally:
        left = await _cleanup(rig, made, hooks)
        if ran:
            legs.check("the_flow_removed_what_it_made", not left, {"left": left})
    return legs.result(description, t0)


async def _balance(rig, label: str, jwt: str) -> Optional[float]:
    r, refused = await _call(rig, label, "getMyBalance", {"agent_jwt": jwt})
    if refused or not isinstance(r, dict):
        return None
    for k in ("balance", "liquid_balance", "token_balance", "available"):
        if r.get(k) is not None:
            return _num(r[k])
    return None


async def _delta(rig, label: str) -> Optional[float]:
    r, refused = await _call(rig, _ADMIN[label], "adminQueryEventStore", {"path": "/api/v1/projections/supply-audit"})
    if refused or not isinstance(r, dict):
        return None
    body = r.get("response") if isinstance(r.get("response"), dict) else r
    return _num(body.get("delta"))


def _ext(card_data: Any, uri: str) -> Optional[Dict[str, Any]]:
    for e in ((card_data or {}).get("extensions") or []) if isinstance(card_data, dict) else []:
        if isinstance(e, dict) and e.get("uri") == uri:
            return e.get("params") or {}
    return None


_BOND_URI = "https://theprotocol.cloud/extensions/v1/reputation-bond"


# ─── F7 + F10 + F14 + V0437 ────────────────────────────────────────────────

@federation_test(
    name="xframe_contract_the_provider_acts_as_itself_and_hears_the_release",
    category="contracts_xframe",
    budget_sec=720.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["contracts", "xframe", "g2", "cross_frame", "webhooks", "money", "v0437"],
)
async def test_xframe_contract_lifecycle(rig: FederationTestRig) -> AssertionResult:
    """A client on sandbox-A hires a provider homed on sandbox-B; everything the provider does, it does on its own frame.

    F7: offer on A -> a signed replica on B -> the provider accepts and delivers on B, each carried to A -> the client
    releases on A -> the provider is paid across the frames. F10/F14: the provider's owner hears the offer and the release
    FROM ITS OWN FRAME (replica: true). V0437: the provider acts through acceptContractFederated /
    submitContractWorkFederated, which are the v2 provider rail acting as the caller, and a DID that is not the caller's
    is refused before anything is attempted; the replica read names the milestone the home paid.
    """
    planned = ["the_provider_is_bonded_at_home", "the_client_frame_mirrors_the_bonded_provider", "the_client_is_funded",
               "the_offer_is_minted_at_the_clients_home", "the_replica_lands_where_the_provider_lives",
               "the_providers_owner_hears_the_offer_from_its_own_frame", "a_did_that_is_not_the_callers_is_refused",
               "the_provider_accepts_as_itself", "the_providers_owner_hears_the_agreement_from_its_own_frame", "the_provider_delivers_as_itself", "the_home_sees_the_delivery",
               "the_client_releases_at_home", "the_replica_names_the_paid_milestone",
               "the_providers_owner_hears_the_release_from_its_own_frame", "the_provider_is_paid", "delta_zero_on_both_frames"]

    async def body(legs: _Legs, made, hooks) -> None:
        client = await _agent(rig, _A, "client", made)
        provider = await _agent(rig, _B, "provider", made)
        status = await ensure_bonded(rig, _B, provider["did"])
        if not legs.check("the_provider_is_bonded_at_home", status in _BONDED or str(status).startswith("skipped:"),
                          {"status": status}):
            return
        hook = await _hook(rig, _B, ["contract.offered", "contract.agreed", "contract.milestone_released",
                                     "contract.completed"], hooks)

        async def mirrored():
            code, card = await _rest(rig, "GET", f"/api/v1/agent-cards/{provider['did']}", _ADMIN[_A])
            if code != 200 or not isinstance(card, dict):
                return None
            b = _ext(card.get("card_data"), _BOND_URI)
            return card if (status not in _BONDED or (b or {}).get("status") in _BONDED) else None
        seen = await _until(mirrored, _MIRROR_SEC)
        if not legs.check("the_client_frame_mirrors_the_bonded_provider", bool(seen),
                          {"bond_on_the_mirror": (_ext((seen or {}).get("card_data"), _BOND_URI) or {}).get("status")}):
            return
        d0 = {_A: await _delta(rig, _A), _B: await _delta(rig, _B)}
        code, resp = await _rest(rig, "POST", "/api/v1/teg/treasury/fund-agent", _ADMIN[_A],
                                 body={"target_agent_did": client["did"], "amount": _FUND,
                                       "reason": "federation suite cross-frame contract probe"})
        if not legs.check("the_client_is_funded", code == 200, {"status": code, "body": str(resp)[:160]}):
            return
        p0 = await _balance(rig, _B, provider["jwt"])
        code, offer = await _rest(rig, "POST", "/api/v1/contracts/v2", _ADMIN[_A], jwt=client["jwt"], body={
            "title": f"{_TAG} one milestone across the frames", "contract_type": "work_order", "total_amount": _TOTAL,
            "milestones": [{"title": "the deliverable", "amount": _TOTAL}], "provider_did": provider["did"]})
        cid = (offer or {}).get("id") if isinstance(offer, dict) else None
        if not legs.check("the_offer_is_minted_at_the_clients_home",
                          code == 200 and bool(cid) and bool((offer or {}).get("counterparty_home_registry")),
                          {"status": code, "answer": str(offer)[:200]}):
            return

        async def replica():
            r, refused = await _call(rig, _B, "getContractV2", {"contract_id": cid, "agent_jwt": provider["jwt"]})
            return r if (not refused and isinstance(r, dict) and r.get("replica") is True) else None
        rep = await _until(replica, _REPLICA_SEC)
        if not legs.check("the_replica_lands_where_the_provider_lives", bool(rep),
                          {"home": (rep or {}).get("home_registry"), "status": (rep or {}).get("status")}):
            return
        offered = await _until(lambda: _told(rig, _B, hook, "contract.offered", cid), _HEAR_SEC)
        legs.check("the_providers_owner_hears_the_offer_from_its_own_frame",
                   bool(offered) and any(d.get("replica") is True for d in offered), {"deliveries": offered})

        r, refused = await _call(rig, _B, "acceptContractFederated",
                                 {"contract_id": cid, "upgrader_agent_did": client["did"], "agent_jwt": provider["jwt"]})
        still, _ = await _call(rig, _B, "getContractV2", {"contract_id": cid, "agent_jwt": provider["jwt"]})
        legs.check("a_did_that_is_not_the_callers_is_refused",
                   bool(refused) and "you act as yourself" in refused and (still or {}).get("status") == "offered",
                   {"refusal": refused, "replica_status_after": (still or {}).get("status")})

        r, refused = await _call(rig, _B, "acceptContractFederated", {"contract_id": cid, "agent_jwt": provider["jwt"]})
        if not legs.check("the_provider_accepts_as_itself", not refused and isinstance(r, dict) and bool(r.get("relayed_to"))
                          and r.get("status") == "agreed", {"refusal": refused, "answer": str(r)[:200]}):
            return
        # TESTPLAN F10's second half: the replica's offered -> agreed transition is announced on the provider's frame
        agreed = await _until(lambda: _told(rig, _B, hook, "contract.agreed", cid), _HEAR_SEC)
        legs.check("the_providers_owner_hears_the_agreement_from_its_own_frame",
                   bool(agreed) and any(d.get("replica") is True for d in agreed), {"deliveries": agreed})
        r, refused = await _call(rig, _B, "submitContractWorkFederated", {
            "contract_id": cid, "pr_url": f"https://{_TAG}.invalid/deliverable/1", "agent_jwt": provider["jwt"]})
        if not legs.check("the_provider_delivers_as_itself", not refused and isinstance(r, dict) and bool(r.get("relayed_to")),
                          {"refusal": refused, "answer": str(r)[:200]}):
            return

        async def submitted():
            r2, ref2 = await _call(rig, _A, "getContractV2", {"contract_id": cid, "agent_jwt": client["jwt"]})
            ms = {m.get("seq"): m.get("status") for m in ((r2 or {}).get("milestones") or []) if isinstance(m, dict)}
            return ms.get(1) == "submitted"
        if not legs.check("the_home_sees_the_delivery", bool(await _until(submitted, _REPLICA_SEC))):
            return
        r, refused = await _call(rig, _A, "releaseContractMilestone", {"contract_id": cid, "seq": 1, "agent_jwt": client["jwt"]})
        if not legs.check("the_client_releases_at_home", not refused, {"refusal": refused, "answer": str(r)[:200]}):
            return

        async def paid_replica():
            r2, ref2 = await _call(rig, _B, "getContractV2", {"contract_id": cid, "agent_jwt": provider["jwt"]})
            return r2 if (not ref2 and isinstance(r2, dict) and r2.get("released_milestones") == [1]) else None
        rep2 = await _until(paid_replica, _REPLICA_SEC)
        legs.check("the_replica_names_the_paid_milestone", bool(rep2),
                   {"released": (rep2 or {}).get("released_milestones"), "status": (rep2 or {}).get("status")})
        heard = await _until(lambda: _told(rig, _B, hook, "contract.milestone_released", cid), _HEAR_SEC)
        legs.check("the_providers_owner_hears_the_release_from_its_own_frame",
                   bool(heard) and any(d.get("replica") is True and int(d.get("seq") or 0) == 1 for d in heard),
                   {"deliveries": heard})

        async def paid():
            p1 = await _balance(rig, _B, provider["jwt"])
            return p1 if (p0 is not None and p1 is not None and p1 > p0) else None
        p1 = await _until(paid, _HEAR_SEC)
        legs.check("the_provider_is_paid", p1 is not None, {"before": p0, "after": p1})
        d1 = {_A: await _delta(rig, _A), _B: await _delta(rig, _B)}
        legs.check("delta_zero_on_both_frames", all(v == 0.0 for v in d1.values()), {"before": d0, "after": d1})

    return await _run(rig, planned, "a cross-frame contract, the provider acting as itself on its own frame", body)


# ─── V0437: one rail, and on it every party acts as itself ─────────────────

@federation_test(
    name="contract_rail_the_legacy_peer_routes_are_retired_and_the_tools_act_as_the_caller",
    category="contracts_xframe",
    budget_sec=120.0,
    severity="critical",
    requires=[_A, _ADMIN[_A]],
    tags=["contracts", "authority", "v0437"],
)
async def test_contract_rail_retired(rig: FederationTestRig) -> AssertionResult:
    """V0437: `accept-federated` / `submit-federated` let a peer registry accept or deliver in any agent's name (no bond
    or enforcement gate, the provider taken from the body); they answer 410 now and name the v2 rail. The proxy and the
    three MCP tools act only as their caller: a DID that is not the caller's is refused before any call, and a contract no
    registry holds is the v2 route's own 404. Nothing is accepted: every contract id here is made up."""
    planned = ["accept_federated_answers_410_and_names_the_v2_rail", "submit_federated_answers_410_and_names_the_v2_rail",
               "accept_tool_refuses_another_agents_did_before_any_call", "accept_tool_reaches_the_v2_route",
               "submit_tool_reaches_the_v2_route", "proxy_tool_reaches_the_v2_route",
               "proxy_tool_refuses_another_agents_did_before_any_call"]

    async def body(legs: _Legs, made, hooks) -> None:
        x = await _agent(rig, _A, "rail", made)
        other = f"did:theprotocol:{uuid.uuid4()}"
        ghost = "ctr_" + uuid.uuid4().hex[:24]
        for route, leg in (("accept-federated", "accept_federated_answers_410_and_names_the_v2_rail"),
                           ("submit-federated", "submit_federated_answers_410_and_names_the_v2_rail")):
            code, resp = await _rest(rig, "POST", f"/api/v1/contracts/{ghost}/{route}", _ADMIN[_A],
                                     body={"upgrader_agent_did": other, "pr_url": f"https://{_TAG}.invalid/pr"})
            if code == 404:
                raise PreconditionUnmet(f"POST /contracts/{{id}}/{route} is 404 on {_A}: the legacy contracts surface is not "
                                        f"mounted here (LEGACY_CONTRACTS_ENABLED=false), nothing to measure")
            d = str((resp or {}).get("detail") if isinstance(resp, dict) else resp)
            legs.check(leg, code == 410 and "/api/v1/contracts/v2/" in d and "contract-command" in d,
                       {"status": code, "detail": d[:200]})
        r, refused = await _call(rig, _A, "acceptContractFederated",
                                 {"contract_id": ghost, "upgrader_agent_did": other, "agent_jwt": x["jwt"]})
        legs.check("accept_tool_refuses_another_agents_did_before_any_call",
                   bool(refused) and "you act as yourself" in refused, {"refusal": refused})
        for tool, args, leg in (
                ("acceptContractFederated", {"contract_id": ghost}, "accept_tool_reaches_the_v2_route"),
                ("submitContractWorkFederated", {"contract_id": ghost, "pr_url": f"https://{_TAG}.invalid/pr"},
                 "submit_tool_reaches_the_v2_route"),
                ("crossRegistryContractProxy", {"action_data": {"contract_id": ghost, "action": "accept"}},
                 "proxy_tool_reaches_the_v2_route")):
            r, refused = await _call(rig, _A, tool, dict(args, agent_jwt=x["jwt"]))
            legs.check(leg, bool(refused) and "returned HTTP 404" in refused, {"refusal": refused})
        r, refused = await _call(rig, _A, "crossRegistryContractProxy", {
            "action_data": {"contract_id": ghost, "action": "accept", "upgrader_agent_did": other}, "agent_jwt": x["jwt"]})
        legs.check("proxy_tool_refuses_another_agents_did_before_any_call",
                   bool(refused) and "you act as yourself" in refused, {"refusal": refused})

    return await _run(rig, planned, "one cross-frame contract rail; the tools act only as their caller", body)
