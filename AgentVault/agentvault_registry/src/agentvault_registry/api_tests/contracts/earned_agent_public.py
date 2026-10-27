"""§MCPTEST30 (V0636): the agent and public tools that passed on a refusal alone, earning their success path
(agentvault2-66; sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md, step 2; his words of 2026-10-24: "all
mcp-tester and fe tester suites are targets. you guys keep going until the gaps are closed").

Lifecycles only, on the subjects and row helpers of earned_fixtures. mcp_lifecycles.py extends its LIFECYCLES with
this module's at its end; this module never imports mcp_lifecycles at module level (earned_fixtures.lc()).

Each lifecycle makes its own subjects (agents of the runner's admin developer, which draw no genesis grant, or a
throwaway developer where the tool acts on a developer's own account), calls the tool on them for real, reads the
effect back, and clears them away. Money moved is dust (0.01) except where a route sets a higher minimum: a legacy
contract's 1 (refunded in the same run) and a stake's 10 (unstaked in the same run). The refusals the old safe-path
lifecycles measured stay, each under `refusal: <tool> <what>` (earned_fixtures.refusal_step).

A tool no MCP caller can ever succeed with is said so on its own row, NOT MEASURED with the reason (a federation peer's
route, a 410 route, a retired rail, a route that refuses every caller by design), never a pass on its refusal.

Measured by hand on sbx-alpha (V0635, 2026-10-24 ~01:00Z) before it was written: the legacy and v2 contract doors
(an offer of 0.01, accept, read, submit, approve; and accept, submit, the provider withdraws, the client is refunded),
the transparency fixture's track record, an arena match's state and map.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts import earned_fixtures as ef

RpcCall = ef.RpcCall
ParseResult = ef.ParseResult

DUST = "0.01"
_GH_PR = "https://github.com/theprotocol/mcp-tester/pull/{n}"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _tag() -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:6]}"


def _d(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _ev(bag: Any) -> Any:
    return getattr(bag, "event_verifier", None)


async def _rest(bag: Any, parse: ParseResult, method: str, endpoint: str, body: Any = None, *,
                as_jwt: Optional[str] = None, params: Optional[Dict[str, Any]] = None,
                timeout: int = 30) -> Tuple[int, Any]:
    """One REST call through the admin bridge's adminRequest, sent with `as_jwt` when given (an agent's or a
    developer's own token: the pattern mcp_lifecycles._withdraw_private_offer uses), else with the runner's admin
    token. Returns (status, response); 0 and {"why"} when the call could not be made. Never raises."""
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return 0, {"why": "the runner injected no admin bridge"}
    args: Dict[str, Any] = {"method": method, "endpoint": endpoint}
    if body is not None:
        args["body"] = body
    if params:
        args["params"] = params
    if as_jwt:
        args["developer_jwt"] = as_jwt
    try:
        _ok, raw, code = await rpc_admin("theprotocol_adminRequest", args, jwt=bag.developer_jwt, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return 0, {"why": f"adminRequest raised {type(e).__name__}"}
    got = _d(parse(raw) if isinstance(raw, dict) else {})
    try:
        st = int(got.get("status_code"))
    except (TypeError, ValueError):
        st = int(code) if str(code).isdigit() else 0
    return st, (got.get("response") if "response" in got else got)


async def _db_one(bag: Any, sql: str, params: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
    """One scalar from the target's own database (mcp_lifecycles._target_db: in-process where the lifecycle runs in the
    target's registry, as the runner's phase 5c does; a cloud operator's in its own database container). (value, None)
    or (None, why). The value is never logged."""
    from agentvault_registry.api_tests.contracts.mcp_lifecycles import _target_db
    return await _target_db(bag, sql, params)


async def _db_write(bag: Any, sql: str, params: Dict[str, Any]) -> Tuple[int, Optional[str]]:
    """One guarded write on the target's own database (never the TEG's); (rows changed, None) or (0, why)."""
    from agentvault_registry.api_tests.contracts.mcp_lifecycles import _target_db
    n, why = await _target_db(bag, sql, params, write=True)
    return int(n or 0), why


async def _config(rpc: RpcCall, parse: ParseResult, bag: Any) -> Dict[str, Any]:
    """The target's /public/registry-config (its switches), {} when unreadable."""
    try:
        ok, body, _ = await rpc("theprotocol_getPublicRegistryConfig", {}, jwt=bag.developer_jwt, timeout=30)
        return _d(parse(body)) if ok else {}
    except Exception:  # noqa: BLE001
        return {}


def _admin_dev(bag: Any) -> Dict[str, Any]:
    """The runner's admin developer as a Throwaways owner: its agents draw no genesis grant (its first agent is long
    gone), and the owner deletes them in close()."""
    return {"access_token": getattr(bag, "developer_jwt", "") or "", "developer_id": getattr(bag, "developer_id", "")}


def _unmeasured_all(outcomes: Dict[str, dict], tools: Tuple[Tuple[str, str], ...], why: str) -> None:
    for tool, tier in tools:
        if tool not in outcomes:
            ef.unmeasured(outcomes, tool, tier, why)


def _check(outcomes: Dict[str, dict], tool: str, why: Optional[str]) -> None:
    """Downgrade the tool's own row when its answer does not say what the step did (a BUG-FIND)."""
    row = outcomes.get(tool)
    if why and row is not None and row.get("healthy"):
        row["healthy"] = False
        row["fail_reason"] = f"BUG-FIND: {ef.bare(tool)}: {why}"


def _status_is(*want: str):
    def _c(inner: dict) -> Optional[str]:
        st = str(_d(inner).get("status") or "")
        return None if st.lower() in {w.lower() for w in want} else f"status {st!r}, not {' or '.join(want)}"
    return _c


async def _backstop(bag: Any, parse: ParseResult, did: str) -> Optional[str]:
    """A treasury-backed bond for an agent of the runner's (it moves no money; REPUTATION_BOND_TREASURY_BACKSTOP): a
    provider needs one to accept under REPUTATION_BOND_MODE=enforce. None, or why it failed."""
    st, resp = await _rest(bag, parse, "POST", f"/api/v1/developers/me/agents/{did}/reputation-bond/backstop", {})
    if st == 200 and _d(resp).get("status") == "locked":
        return None
    return f"the provider's backstop bond answered HTTP {st}: {ef.said(resp)}"


async def _v2_offer(bag: Any, parse: ParseResult, client_jwt: str, provider_did: str, title: str,
                    amount: str = DUST) -> Tuple[Optional[str], str]:
    """A v2 work order offered to a named provider, made with the client's own agent token."""
    st, resp = await _rest(bag, parse, "POST", "/api/v1/contracts/v2",
                           {"title": title, "contract_type": "work_order", "total_amount": amount,
                            "provider_did": provider_did}, as_jwt=client_jwt)
    cid = _d(resp).get("id")
    if st == 200 and isinstance(cid, str) and cid.startswith("ctr_"):
        return cid, ""
    return None, f"no v2 offer could be made (HTTP {st}: {ef.said(resp)})"


async def _cancel_v2(bag: Any, parse: ParseResult, cid: Optional[str], client_jwt: str) -> None:
    if cid:
        await _rest(bag, parse, "POST", f"/api/v1/contracts/v2/{cid}/cancel", None, as_jwt=client_jwt)


# ── contracts: the legacy doors and the v2 doors (the provider an agent of the runner's, bonded by the backstop) ──

CONTRACT_TOOLS = (
    ("theprotocol_acceptContract", "2"), ("theprotocol_getContractById", "2"),
    ("theprotocol_submitContractWork", "2"), ("theprotocol_approveContractCompletion", "2"),
    ("theprotocol_acceptContractFederated", "2"), ("theprotocol_submitContractWorkFederated", "2"),
    ("theprotocol_markContractFailed", "2"), ("theprotocol_crossRegistryContractProxy", "2"),
    ("theprotocol_createMalpracticeDispute", "2"),
)
_LEGACY_TOOLS = ("theprotocol_acceptContract", "theprotocol_getContractById", "theprotocol_submitContractWork",
                 "theprotocol_approveContractCompletion", "theprotocol_markContractFailed",
                 "theprotocol_createMalpracticeDispute")


def _only(*names: str) -> Tuple[Tuple[str, str], ...]:
    return tuple(x for x in CONTRACT_TOOLS if x[0] in names)


async def lifecycle_earned_contracts(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The sentinel (the client, funded by the run) offers three contracts to a provider of the runner's:

    C_A 0.01: acceptContract (the legacy door) -> getContractById -> submitContractWork -> approveContractCompletion:
              the 0.01 moves from the client's escrow to the provider.
    C_B 0.01: acceptContractFederated -> submitContractWorkFederated -> markContractFailed by the provider: the
              escrow comes back to the client.
    C_C 1 (a legacy contract, the route's minimum, the only kind with the integer id the malpractice route takes):
              crossRegistryContractProxy accept -> createMalpracticeDispute -> the provider withdraws (refund) -> the
              admin dismisses the dispute (nothing moves: the contract is already cancelled).
    The legacy surface (LEGACY_CONTRACTS_ENABLED) decides whether the legacy doors exist here; where it is off they
    say so. The old unknown-contract probes stay as refusal rows (mcp_lifecycles: contract_safe_paths and
    contract_submit_paths)."""
    tag = _tag()
    S_jwt, S_did = bag.sentinel_jwt, bag.sentinel_did
    cfg = await _config(rpc, parse, bag)
    legacy_on = cfg.get("legacy_contracts_enabled") is not False
    t = ef.Throwaways(rpc, parse, bag, "contracts")
    try:
        P = await t.agent(_admin_dev(bag), "provider")
        if P.get("why"):
            return _unmeasured_all(outcomes, CONTRACT_TOOLS, f"no provider agent ({P['why']})")
        why = await _backstop(bag, parse, P["did"])
        if why:
            return _unmeasured_all(outcomes, CONTRACT_TOOLS, why)
        P_jwt, P_did = P["agent_jwt"], P["did"]

        # C_A: the legacy doors on a v2 offer (the legacy routes take its ctr_ ref)
        if not legacy_on:
            _unmeasured_all(outcomes, _only(*_LEGACY_TOOLS),
                            "the legacy contracts surface is not mounted on this target (LEGACY_CONTRACTS_ENABLED "
                            "false, D8): its routes answer 404 by design")
        else:
            cid, why = await _v2_offer(bag, parse, S_jwt, P_did, f"MCP tester legacy doors {tag}")
            if not cid:
                _unmeasured_all(outcomes, _only(*_LEGACY_TOOLS[:4]), why)
            else:
                ok, r = await ef.step(rpc, parse, "theprotocol_acceptContract", "2",
                                      {"agent_jwt": P_jwt, "contract_id": cid, "upgrader_agent_did": P_did},
                                      bag.developer_jwt, outcomes, expect_events=["ContractAccepted"],
                                      event_verifier=_ev(bag))
                if not ok:
                    _unmeasured_all(outcomes, _only(*_LEGACY_TOOLS[1:4]), "the provider could not accept the offer")
                    await _cancel_v2(bag, parse, cid, S_jwt)
                else:
                    _check(outcomes, "theprotocol_acceptContract",
                           _status_is("ACCEPTED")(r) or (None if _d(r).get("upgrader_agent_did") == P_did else
                                                         "the answer does not name the provider who accepted"))
                    ok2, r2 = await ef.step(rpc, parse, "theprotocol_getContractById", "2",
                                            {"agent_jwt": S_jwt, "contract_id": cid}, bag.developer_jwt, outcomes)
                    if ok2:
                        _check(outcomes, "theprotocol_getContractById",
                               None if (_d(r2).get("ref") == cid and _d(r2).get("client_agent_did") == S_did) else
                               "the contract read back is not the one the client made")
                    ok3, r3 = await ef.step(rpc, parse, "theprotocol_submitContractWork", "2",
                                            {"agent_jwt": P_jwt, "contract_id": cid, "pr_url": _GH_PR.format(n=1)},
                                            bag.developer_jwt, outcomes, expect_events=["ContractWorkSubmitted"],
                                            event_verifier=_ev(bag))
                    if not ok3:
                        ef.unmeasured(outcomes, "theprotocol_approveContractCompletion", "2",
                                      "the work was not submitted, so there was nothing to approve")
                        await ef.step(rpc, parse, "theprotocol_markContractFailed", "2",
                                      {"agent_jwt": S_jwt, "contract_id": cid, "reason": "MCP tester cleanup"},
                                      bag.developer_jwt, {}, record_as_separate=False)
                    else:
                        _check(outcomes, "theprotocol_submitContractWork", _status_is("PENDING_MERGE")(r3))
                        ok4, r4 = await ef.step(rpc, parse, "theprotocol_approveContractCompletion", "2",
                                                {"agent_jwt": S_jwt, "contract_id": cid}, bag.developer_jwt, outcomes,
                                                expect_events=["ContractCompleted"], event_verifier=_ev(bag))
                        if ok4:
                            _check(outcomes, "theprotocol_approveContractCompletion", _status_is("COMPLETED")(r4))
                            await ef.step(rpc, parse, "theprotocol_getContractV2", "2",
                                          {"agent_jwt": S_jwt, "contract_id": cid}, bag.developer_jwt, outcomes,
                                          record_as_separate=False,
                                          verify_against="theprotocol_approveContractCompletion",
                                          verify_against_check=_status_is("completed"))

        # C_B: the v2 doors, then the provider withdraws and the client gets the escrow back
        cid, why = await _v2_offer(bag, parse, S_jwt, P_did, f"MCP tester v2 doors {tag}")
        if not cid:
            _unmeasured_all(outcomes, _only("theprotocol_acceptContractFederated",
                                            "theprotocol_submitContractWorkFederated",
                                            "theprotocol_markContractFailed"), why)
        else:
            ok, r = await ef.step(rpc, parse, "theprotocol_acceptContractFederated", "2",
                                  {"agent_jwt": P_jwt, "contract_id": cid}, bag.developer_jwt, outcomes,
                                  expect_events=["ContractAgreed"], event_verifier=_ev(bag))
            if not ok:
                _unmeasured_all(outcomes, _only("theprotocol_submitContractWorkFederated",
                                                "theprotocol_markContractFailed"),
                                "the provider could not accept the run's v2 offer")
                await _cancel_v2(bag, parse, cid, S_jwt)
            else:
                _check(outcomes, "theprotocol_acceptContractFederated",
                       _status_is("agreed")(r) or (None if _d(r).get("provider_did") == P_did else
                                                   "the answer does not name the provider who accepted"))
                ok2, r2 = await ef.step(rpc, parse, "theprotocol_submitContractWorkFederated", "2",
                                        {"agent_jwt": P_jwt, "contract_id": cid, "pr_url": _GH_PR.format(n=2),
                                         "seq": 1}, bag.developer_jwt, outcomes,
                                        expect_events=["ContractMilestoneSubmitted"], event_verifier=_ev(bag))
                if ok2:
                    _check(outcomes, "theprotocol_submitContractWorkFederated",
                           None if (_d(r2).get("ok") is True and _d(r2).get("status") == "submitted") else
                           "the answer does not say milestone 1 was submitted")
                if legacy_on:
                    ok3, r3 = await ef.step(rpc, parse, "theprotocol_markContractFailed", "2",
                                            {"agent_jwt": P_jwt, "contract_id": cid,
                                             "reason": "MCP tester: the provider withdraws, the client is refunded"},
                                            bag.developer_jwt, outcomes, expect_events=["ContractFailed"],
                                            event_verifier=_ev(bag))
                    if ok3:
                        _check(outcomes, "theprotocol_markContractFailed", _status_is("FAILED")(r3))
                        await ef.step(rpc, parse, "theprotocol_getContractV2", "2",
                                      {"agent_jwt": S_jwt, "contract_id": cid}, bag.developer_jwt, outcomes,
                                      record_as_separate=False, verify_against="theprotocol_markContractFailed",
                                      verify_against_check=_status_is("cancelled"))
                else:
                    # no legacy door to withdraw through: the provider's delivery is released instead (0.01 moves)
                    await ef.step(rpc, parse, "theprotocol_releaseContractMilestone", "2",
                                  {"agent_jwt": S_jwt, "contract_id": cid, "seq": 1}, bag.developer_jwt, {},
                                  record_as_separate=False)

        # C_C: a legacy-born contract (integer id), accepted through the proxy, disputed, withdrawn, dismissed
        if legacy_on:
            st, resp = await _rest(bag, parse, "POST", "/api/v1/contracts/", {
                "client_agent_did": S_did, "scope_description": f"MCP tester malpractice probe {tag}",
                "source_code_repo_url": "https://github.com/theprotocol/mcp-tester", "source_code_branch": "main",
                "acceptance_criteria": {"probe": "malpractice, withdrawn in the same run"}, "payment_amount": 1},
                as_jwt=S_jwt)
            legacy_id, ref = _d(resp).get("id"), _d(resp).get("ref")
            if st not in (200, 201) or not isinstance(legacy_id, int) or not ref:
                _unmeasured_all(outcomes, _only("theprotocol_crossRegistryContractProxy",
                                                "theprotocol_createMalpracticeDispute"),
                                f"no legacy contract could be made (HTTP {st}: {ef.said(resp)})")
            else:
                ok, r = await ef.step(rpc, parse, "theprotocol_crossRegistryContractProxy", "2",
                                      {"agent_jwt": P_jwt, "action_data": {"contract_id": ref, "action": "accept"}},
                                      bag.developer_jwt, outcomes)
                if not ok:
                    ef.unmeasured(outcomes, "theprotocol_createMalpracticeDispute", "2",
                                  "the legacy contract was not accepted, so it could not be disputed")
                    await _cancel_v2(bag, parse, ref, S_jwt)
                else:
                    _check(outcomes, "theprotocol_crossRegistryContractProxy", _status_is("agreed")(r))
                    ok2, r2 = await ef.step(rpc, parse, "theprotocol_createMalpracticeDispute", "2",
                                            {"agent_jwt": S_jwt, "contract_id": str(legacy_id),
                                             "reason": "MCP tester malpractice probe, withdrawn in the same run"},
                                            bag.developer_jwt, outcomes, expect_events=["DisputeFiled"],
                                            event_verifier=_ev(bag))
                    dispute_id = _d(r2).get("dispute_id") if ok2 else None
                    if ok2:
                        _check(outcomes, "theprotocol_createMalpracticeDispute",
                               None if (dispute_id and _d(r2).get("defendant_did") == P_did) else
                               "the answer names no dispute against the provider")
                    # cleanup: the provider withdraws (the 1 comes back to the client), then the admin dismisses
                    await ef.step(rpc, parse, "theprotocol_markContractFailed", "2",
                                  {"agent_jwt": P_jwt, "contract_id": ref, "reason": "MCP tester cleanup: refund"},
                                  bag.developer_jwt, {}, record_as_separate=False)
                    if dispute_id and getattr(bag, "rpc_admin", None) is not None:
                        try:
                            await bag.rpc_admin("theprotocol_updateDisputeRuling",
                                                {"dispute_id": int(dispute_id), "ruling": "DISMISSED"},
                                                jwt=bag.developer_jwt, timeout=30)
                        except Exception:  # noqa: BLE001 — cleanup is never a finding
                            pass
    finally:
        await t.close()


# ── engagement terms, milestones and a template (contracts v2) ───────────────────────────────────────────────────

ENGAGE_TOOLS = (("theprotocol_engageAgent", "2"), ("theprotocol_submitContractMilestone", "2"),
                ("theprotocol_releaseContractMilestone", "2"), ("theprotocol_instantiateContractTemplate", "2"))


async def lifecycle_earned_engagement(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """A provider of the runner's advertises engagement terms on its card (price 0.01) and holds a backstop bond; the
    sentinel engages it (engageAgent), the provider accepts and submits milestone 1 (submitContractMilestone), the
    sentinel releases it (releaseContractMilestone: 0.01 to the provider, the contract completes). An author of the
    runner's (the legacy-full role for an hour: the only role that may publish a template) publishes a free unlisted
    template, the sentinel instantiates it for that provider (instantiateContractTemplate), withdraws the offer, and
    the template is made private."""
    tag = _tag()
    S_jwt = bag.sentinel_jwt
    cfg = await _config(rpc, parse, bag)
    t = ef.Throwaways(rpc, parse, bag, "engage")
    template_offer: Optional[str] = None
    tpl: Optional[str] = None
    A: Dict[str, Any] = {}
    try:
        P = await t.agent(_admin_dev(bag), "provider")
        if P.get("why"):
            return _unmeasured_all(outcomes, ENGAGE_TOOLS, f"no provider agent ({P['why']})")
        P_jwt, P_did = P["agent_jwt"], P["did"]
        why = await _backstop(bag, parse, P_did)
        if not why:
            st, card = await _rest(bag, parse, "GET", f"/api/v1/agent-cards/{P_did}")
            card_data = _d(card).get("card_data")
            if not isinstance(card_data, dict):
                why = f"the provider's card could not be read (HTTP {st})"
            else:
                terms = {"title": f"MCP tester engagement {tag}", "price": float(DUST), "contract_type": "service",
                         "deadline_seconds": 3600, "terms": {"probe": "MCP tester, completed in the same run"}}
                st, _ = await _rest(bag, parse, "PUT", f"/api/v1/agent-cards/{P_did}",
                                    {"card_data": {**card_data, "engagement": terms}})
                if st != 200:
                    why = f"the provider's card took no engagement terms (HTTP {st})"
        if why:
            _unmeasured_all(outcomes, ENGAGE_TOOLS[:3], why)
        else:
            ok, r = await ef.step(rpc, parse, "theprotocol_engageAgent", "2",
                                  {"agent_jwt": S_jwt, "provider_did": P_did, "total_amount": float(DUST),
                                   "message": f"MCP tester engage {tag}"}, bag.developer_jwt, outcomes,
                                  expect_events=["ContractOffered"], event_verifier=_ev(bag))
            cid = _d(r).get("id") if ok else None
            if ok:
                _check(outcomes, "theprotocol_engageAgent",
                       None if (_d(r).get("provider_did") == P_did and _d(r).get("status") == "offered") else
                       "the offer does not name the provider in status offered")
            if not cid:
                _unmeasured_all(outcomes, ENGAGE_TOOLS[1:3], "no engagement offer was made")
            else:
                okA, _ = await ef.step(rpc, parse, "theprotocol_acceptContractFederated", "2",
                                       {"agent_jwt": P_jwt, "contract_id": cid}, bag.developer_jwt, {},
                                       record_as_separate=False)
                if not okA:
                    _unmeasured_all(outcomes, ENGAGE_TOOLS[1:3], "the provider could not accept the engagement")
                    await _cancel_v2(bag, parse, cid, S_jwt)
                else:
                    ok2, r2 = await ef.step(rpc, parse, "theprotocol_submitContractMilestone", "2",
                                            {"agent_jwt": P_jwt, "contract_id": cid, "seq": 1,
                                             "deliverable": {"note": f"MCP tester delivery {tag}"}},
                                            bag.developer_jwt, outcomes, expect_events=["ContractMilestoneSubmitted"],
                                            event_verifier=_ev(bag))
                    if not ok2:
                        ef.unmeasured(outcomes, "theprotocol_releaseContractMilestone", "2",
                                      "milestone 1 was not submitted, so there was nothing to release")
                        await ef.step(rpc, parse, "theprotocol_markContractFailed", "2",
                                      {"agent_jwt": P_jwt, "contract_id": cid, "reason": "MCP tester cleanup"},
                                      bag.developer_jwt, {}, record_as_separate=False)
                    else:
                        _check(outcomes, "theprotocol_submitContractMilestone",
                               None if _d(r2).get("status") == "submitted" else "milestone 1 was not submitted")
                        ok3, r3 = await ef.step(rpc, parse, "theprotocol_releaseContractMilestone", "2",
                                                {"agent_jwt": S_jwt, "contract_id": cid, "seq": 1},
                                                bag.developer_jwt, outcomes,
                                                expect_events=["ContractMilestoneReleased"], event_verifier=_ev(bag))
                        if ok3:
                            _check(outcomes, "theprotocol_releaseContractMilestone",
                                   None if (_d(r3).get("completed") is True and _d(r3).get("released_seq") == 1) else
                                   "the release does not say milestone 1 was released and the contract completed")
                            await ef.step(rpc, parse, "theprotocol_getContractV2", "2",
                                          {"agent_jwt": S_jwt, "contract_id": cid}, bag.developer_jwt, outcomes,
                                          record_as_separate=False,
                                          verify_against="theprotocol_releaseContractMilestone",
                                          verify_against_check=_status_is("completed"))

        # the template: an author with the legacy-full role publishes it, the sentinel instantiates it
        if cfg.get("contract_templates_enabled") is False:
            ef.unmeasured(outcomes, "theprotocol_instantiateContractTemplate", "2",
                          "contract templates are switched off on this target (CONTRACT_TEMPLATES_ENABLED)")
            return
        A = await t.agent(_admin_dev(bag), "author")
        why = A.get("why")
        if not why:
            st, resp = await _rest(bag, parse, "POST", f"/api/v1/agents/{A['did']}/authz/roles",
                                   {"role": "legacy-full",
                                    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
            if st not in (200, 201):
                why = f"the author could not be given the publishing role (HTTP {st}: {ef.said(resp)})"
        if not why:
            st, resp = await _rest(bag, parse, "POST", "/api/v1/contracts/templates", {
                "slug": f"mcp-tester-tpl-{tag}"[:60], "title": f"MCP tester template {tag}",
                "contract_type": "service", "visibility": "unlisted", "pricing_model": "free",
                "suggested_amount": "0", "terms": {"probe": "MCP tester, withdrawn in the same run"}},
                as_jwt=A["agent_jwt"])
            tpl = _d(resp).get("template_id")
            if st not in (200, 201) or not tpl:
                why = f"the author could not create a template (HTTP {st}: {ef.said(resp)})"
        if not why:
            st, resp = await _rest(bag, parse, "POST", f"/api/v1/contracts/templates/{tpl}/versions/1/publish", {},
                                   as_jwt=A["agent_jwt"])
            if st not in (200, 201):
                why = f"the author could not publish the template (HTTP {st}: {ef.said(resp)})"
        if why:
            ef.unmeasured(outcomes, "theprotocol_instantiateContractTemplate", "2", why)
        else:
            ok, r = await ef.step(rpc, parse, "theprotocol_instantiateContractTemplate", "2",
                                  {"agent_jwt": S_jwt, "template_id": tpl, "total_amount": 0,
                                   "provider_did": P_did}, bag.developer_jwt, outcomes,
                                  expect_events=["ContractOffered"], event_verifier=_ev(bag))
            if ok:
                template_offer = _d(r).get("id")
                prov = _d(_d(r).get("terms")).get("template_provenance")
                _check(outcomes, "theprotocol_instantiateContractTemplate",
                       None if (_d(r).get("origin_surface") == "template" and _d(prov).get("template_id") == tpl)
                       else "the offer does not carry the template it was made from")
    finally:
        await _cancel_v2(bag, parse, template_offer, S_jwt)
        if tpl and A.get("agent_jwt"):
            await _rest(bag, parse, "PATCH", f"/api/v1/contracts/templates/{tpl}", {"visibility": "private"},
                        as_jwt=A["agent_jwt"])
        await t.close()


# ── disputes ─────────────────────────────────────────────────────────────────────────────────────────────────────

DISPUTE_TOOLS = (("theprotocol_submitDispute", "2"), ("theprotocol_submitDisputeEvidence", "2"),
                 ("theprotocol_logEnhancedDispute", "2"))


async def lifecycle_earned_disputes(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """Two agents of the runner's: A files a dispute against B (submitDispute), adds evidence (submitDisputeEvidence)
    and files an enhanced one (logEnhancedDispute); the admin dismisses both and the agents are deleted. The sentinel
    reads the TEG dispute phase 4 filed for it (getTegDisputeDetail); a run with no phase 4 (a cloud operator's) has A
    file that TEG dispute against B itself (logTegDispute) and read it back. resolveTegDispute refuses every caller by
    design (who may resolve is his decision, routers/teg_integration.py): its row says so, and the refusal is kept
    beside it."""
    tag = _tag()
    t = ef.Throwaways(rpc, parse, bag, "disputes")
    to_dismiss: List[str] = []
    try:
        A = await t.agent(_admin_dev(bag), "complainant")
        B = await t.agent(_admin_dev(bag), "defendant")
        why = A.get("why") or B.get("why")
        if why:
            _unmeasured_all(outcomes, DISPUTE_TOOLS, f"no complainant and defendant ({why})")
        else:
            ok, r = await ef.step(rpc, parse, "theprotocol_submitDispute", "2",
                                  {"agent_jwt": A["agent_jwt"], "defendant_did": B["did"],
                                   "description": f"MCP tester dispute {tag}, dismissed in the same run"},
                                  bag.developer_jwt, outcomes, expect_events=["DisputeFiled"], event_verifier=_ev(bag))
            dsp = _d(r).get("dispute_id") or _d(r).get("id")
            if not ok or not dsp:
                ef.unmeasured(outcomes, "theprotocol_submitDisputeEvidence", "2",
                              "no dispute was filed, so there was nothing to add evidence to")
            else:
                to_dismiss.append(str(dsp))
                _check(outcomes, "theprotocol_submitDispute",
                       None if _d(r).get("complainant_did") in (None, A["did"]) else
                       "the dispute was filed for another complainant than the caller")
                ok2, r2 = await ef.step(rpc, parse, "theprotocol_submitDisputeEvidence", "2",
                                        {"agent_jwt": A["agent_jwt"], "dispute_id": str(dsp),
                                         "evidence_data": {"note": "MCP tester evidence", "run": tag}},
                                        bag.developer_jwt, outcomes, expect_events=["EvidenceSubmitted"],
                                        event_verifier=_ev(bag))
                if ok2:
                    _check(outcomes, "theprotocol_submitDisputeEvidence",
                           None if str(_d(r2).get("dispute_id")) == str(dsp) else
                           "the evidence answer does not name the dispute it was added to")
            ok3, r3 = await ef.step(rpc, parse, "theprotocol_logEnhancedDispute", "2",
                                    {"agent_jwt": A["agent_jwt"], "defendant_agent_id": B["did"],
                                     "reason_code": "OTHER",
                                     "brief_description": f"MCP tester enhanced dispute {tag}, dismissed in the same run"},
                                    bag.developer_jwt, outcomes, expect_events=["DisputeFiled"], event_verifier=_ev(bag))
            if ok3 and _d(r3).get("id"):
                to_dismiss.append(str(_d(r3).get("id")))
        # the TEG dispute phase 4 filed with the sentinel as its claimant (its id is a UUID in flow_values). §MCPTEST30
        # (V0644): a cloud operator's run has no phase 4, so logTegDispute read "refusal only" there (a defendant no
        # registry knows) and this read went unmeasured; there A files the same dispute against B and reads it back. A
        # TEG dispute has no resolution route (resolveTegDispute below), so it stays, as phase 4's does on a frame.
        log_id = str(bag.flow_values.get("teg_dispute_log_id") or bag.flow_values.get("dispute_id") or "")
        reader_jwt = bag.sentinel_jwt
        if not _UUID.match(log_id) and not why:
            ok, r = await ef.step(rpc, parse, "theprotocol_logTegDispute", "2",
                                  {"agent_jwt": A["agent_jwt"], "defendant_agent_did": B["did"],
                                   "reason_code": "test_dispute",
                                   "brief_description": f"MCP tester TEG dispute {tag}, a run with no phase 4"},
                                  bag.developer_jwt, outcomes)
            got = str(_d(r).get("dispute_log_id") or _d(r).get("dispute_id") or _d(r).get("id") or "")
            if ok and _UUID.match(got):
                log_id, reader_jwt = got, A["agent_jwt"]
            elif ok:
                _check(outcomes, "theprotocol_logTegDispute", f"the answer names no dispute log id ({got!r:.60})")
        if _UUID.match(log_id):
            ok, r = await ef.step(rpc, parse, "theprotocol_getTegDisputeDetail", "2",
                                  {"agent_jwt": reader_jwt, "dispute_log_id": log_id}, bag.developer_jwt,
                                  outcomes)
            if ok:
                _check(outcomes, "theprotocol_getTegDisputeDetail",
                       None if str(_d(r).get("dispute_log_id") or _d(r).get("id") or log_id) == log_id else
                       "the TEG answered another dispute than the one asked for")
        else:
            ef.unmeasured(outcomes, "theprotocol_getTegDisputeDetail", "2",
                          "no TEG dispute was filed this run (phase 4's, or here logTegDispute's), so there is none to "
                          "read" + (f" ({why})" if why else ""))
        ef.unmeasured(outcomes, "theprotocol_resolveTegDispute", "2",
                      "this registry forwards a TEG dispute resolution for no caller, by design (who may resolve is "
                      "his decision, routers/teg_integration.py); the refusal is kept as its own row")
        await ef.refusal_step(rpc, parse, "theprotocol_resolveTegDispute", "2",
                              {"agent_jwt": bag.sentinel_jwt, "dispute_id": "00000000-0000-4000-8000-000000000000",
                               "resolution": "RESOLVED_NO_ACTION"}, bag.developer_jwt, outcomes,
                              "for any caller (the route forwards no resolution)", codes=(403,), text="Not authorized")
    finally:
        rpc_admin = getattr(bag, "rpc_admin", None)
        for d in to_dismiss:
            if rpc_admin is not None and str(d).isdigit():   # the tool's schema takes the dispute id as an integer
                try:
                    await rpc_admin("theprotocol_updateDisputeRuling", {"dispute_id": int(d), "ruling": "DISMISSED"},
                                    jwt=bag.developer_jwt, timeout=30)
                except Exception:  # noqa: BLE001 — cleanup is never a finding
                    pass
        await t.close()


# ── reputation signals on the sentinel's own transfers ───────────────────────────────────────────────────────────

async def _dust_to(rpc: RpcCall, parse: ParseResult, bag: Any, receiver_did: str, tag: str) -> Optional[str]:
    ok, body, _ = await rpc("theprotocol_transferUnits",
                            {"agent_jwt": bag.sentinel_jwt, "recipient_did": receiver_did, "amount": DUST,
                             "message": f"MCP tester signal transfer {tag}",
                             "idempotency_key": f"mcp-earn-signal-{tag}-{uuid.uuid4().hex[:8]}"},
                            jwt=bag.developer_jwt, timeout=40)
    inner = _d(parse(body))
    return str(inner.get("transaction_id")) if ok and inner.get("transaction_id") else None


async def lifecycle_earned_reputation_signals(rpc: RpcCall, parse: ParseResult, bag: Any,
                                              outcomes: Dict[str, dict]) -> None:
    """The sentinel sends 0.01 twice to an agent of the runner's and signals each transfer once, through each of the
    two signal tools (applyReputationSignal, tegReputationSignal: they share the per-transaction flag, so each
    gets its own transfer). A second signal of the same transfer is refused (a refusal row each)."""
    tag = _tag()
    t = ef.Throwaways(rpc, parse, bag, "signals")
    tools = (("theprotocol_applyReputationSignal", "2"), ("theprotocol_tegReputationSignal", "2"))
    try:
        B = await t.agent(_admin_dev(bag), "receiver")
        if B.get("why"):
            return _unmeasured_all(outcomes, tools, f"no receiver agent ({B['why']})")
        t1 = await _dust_to(rpc, parse, bag, B["did"], tag)
        if not t1:
            # another lifecycle may have measured the tool already (mcp_lifecycles._signal_own_seed_transfer): a skip
            # here never replaces its row
            _unmeasured_all(outcomes, tools[:1], "the sentinel's 0.01 transfer to the receiver did not complete")
        else:
            ok, r = await ef.step(rpc, parse, "theprotocol_applyReputationSignal", "2",
                                  {"agent_jwt": bag.sentinel_jwt, "transaction_id": t1, "signal_value": 1},
                                  bag.developer_jwt, outcomes, expect_events=["ReputationChanged"],
                                  event_verifier=_ev(bag))
            if ok:
                _check(outcomes, "theprotocol_applyReputationSignal",
                       None if _d(r).get("receiver_agent_id") in (None, B["did"]) else
                       "the signal was applied to another agent than the transfer's receiver")
                await ef.refusal_step(rpc, parse, "theprotocol_applyReputationSignal", "2",
                                      {"agent_jwt": bag.sentinel_jwt, "transaction_id": t1, "signal_value": 1},
                                      bag.developer_jwt, outcomes, "a transfer already signalled", codes=(400, 409))
        t2 = await _dust_to(rpc, parse, bag, B["did"], tag + "b")
        if not t2:
            _unmeasured_all(outcomes, tools[1:], "the sentinel's second 0.01 transfer did not complete")
        else:
            ok, r = await ef.step(rpc, parse, "theprotocol_tegReputationSignal", "2",
                                  {"agent_jwt": bag.sentinel_jwt, "transaction_id": t2, "signal_value": 1},
                                  bag.developer_jwt, outcomes)
            if ok:
                _check(outcomes, "theprotocol_tegReputationSignal",
                       None if _d(r).get("affected_agent") in (None, B["did"]) else
                       "the signal moved another agent than the transfer's receiver")
                await ef.refusal_step(rpc, parse, "theprotocol_tegReputationSignal", "2",
                                      {"agent_jwt": bag.sentinel_jwt, "transaction_id": t2, "signal_value": 1},
                                      bag.developer_jwt, outcomes, "a transfer already signalled", codes=(400, 409))
    finally:
        await t.close()


# ── a TEG attestation by an agent that holds reputation.signal ───────────────────────────────────────────────────

async def lifecycle_earned_teg_attestation(rpc: RpcCall, parse: ParseResult, bag: Any,
                                           outcomes: Dict[str, dict]) -> None:
    """An agent of the runner's is given the service-provider role for an hour (reputation.signal) and submits a TEG
    attestation about the sentinel (submitTegAttestation); getTegAttestations lists it. The sentinel, which holds no
    such role, is refused (a refusal row)."""
    tag = _tag()
    tool = "theprotocol_submitTegAttestation"
    t = ef.Throwaways(rpc, parse, bag, "tegattest")
    try:
        # §MCPTEST30 (V0637): the refusal is the agent permission check's (AGENT_RBAC_MODE=enforce, PART 14); where the
        # target does not enforce it (the sandbox operators set neither mode, read 2026-10-24; production's four enforce
        # both) nothing refuses a missing permission, so the refusal is not measured there. A run that does not say its
        # target's posture (bag.target_posture unset: the frame sweep, frames that enforce) asks as before.
        rbac = str((getattr(bag, "target_posture", None) or {}).get("AGENT_RBAC_MODE", "enforce") or "").lower()
        if rbac != "enforce":
            ef.unmeasured(outcomes, ef.refusal_row(tool, "an agent without reputation.signal"), "2",
                          f"this registry does not enforce agent permissions (AGENT_RBAC_MODE {rbac or 'unset'}): "
                          f"nothing refuses an agent a permission it lacks here")
        else:
            await ef.refusal_step(rpc, parse, tool, "2",
                                  {"agent_jwt": bag.sentinel_jwt,
                                   "attestation_data": {"target_agent_did": bag.sentinel_did,
                                                        "attestation_type": "mcp_tester_probe",
                                                        "attestation_data": {"run": tag}}},
                                  bag.developer_jwt, outcomes, "an agent without reputation.signal", codes=(403,),
                                  text="reputation.signal")
        A = await t.agent(_admin_dev(bag), "attester")
        if A.get("why"):
            return ef.unmeasured(outcomes, tool, "2", f"no attesting agent ({A['why']})")
        st, resp = await _rest(bag, parse, "POST", f"/api/v1/agents/{A['did']}/authz/roles",
                               {"role": "service-provider",
                                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
        if st not in (200, 201):
            return ef.unmeasured(outcomes, tool, "2", f"the attesting agent could not be given reputation.signal "
                                                      f"(HTTP {st}: {ef.said(resp)})")
        ok, r = await ef.step(rpc, parse, tool, "2",
                              {"agent_jwt": A["agent_jwt"],
                               "attestation_data": {"target_agent_did": bag.sentinel_did,
                                                    "attestation_type": "mcp_tester_probe",
                                                    "attestation_data": {"run": tag, "nonce": uuid.uuid4().hex},
                                                    "evidence_url": "https://docs.theprotocol.cloud/"}},
                              bag.developer_jwt, outcomes, expect_events=["AttestationSubmitted"],
                              event_verifier=_ev(bag))
        aid = _d(r).get("attestation_id") if ok else None

        def _listed(inner: dict) -> Optional[str]:
            rows = inner.get("attestations") or inner.get("items") or inner.get("submissions") or []
            ids = [str(_d(x).get("attestation_id") or _d(x).get("id") or _d(x).get("submission_id")) for x in rows]
            return None if (not aid or not rows or str(aid) in ids) else (
                f"getTegAttestations does not list the attestation {aid} its agent just submitted")
        if ok:
            await ef.step(rpc, parse, "theprotocol_getTegAttestations", "2", {"agent_jwt": A["agent_jwt"]},
                          bag.developer_jwt, outcomes, record_as_separate=False, verify_against=tool,
                          verify_against_check=_listed)
    finally:
        await t.close()


# ── staking: a lock-0 position staked and unstaked (both rails), 10 and back ─────────────────────────────────────

async def lifecycle_earned_staking(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The sentinel stakes the minimum (10) with no lock and unstakes it at once, on the registry rail
    (lockUnits -> unlockUnits) and on the TEG's direct rail (tegLockDirect -> tegUnlockDirect: the TEG's own
    stake id, which the old step never passed). Where staking is switched off the stake step meets its switch and
    the unstake says why it was not measured."""
    S_jwt = bag.sentinel_jwt
    ok, r = await ef.step(rpc, parse, "theprotocol_lockUnits", "2",
                          {"agent_jwt": S_jwt, "amount": "10", "lock_period_days": 0}, bag.developer_jwt, {},
                          record_as_separate=False)
    sid = _d(r).get("stake_id") if ok else None
    if not sid:
        ef.unmeasured(outcomes, "theprotocol_unlockUnits", "2",
                      f"no unlocked position to unlock: the lock-0 position was not made ({ef.said(r)})")
    else:
        ok2, r2 = await ef.step(rpc, parse, "theprotocol_unlockUnits", "2", {"agent_jwt": S_jwt, "stake_id": sid},
                                bag.developer_jwt, outcomes, expect_events=["TokensUnstaked"], event_verifier=_ev(bag))
        if ok2:
            _check(outcomes, "theprotocol_unlockUnits",
                   None if str(_d(r2).get("status") or "unstaked").lower() == "unstaked" else
                   f"the unlock answered status {_d(r2).get('status')!r}")
    ok, r = await ef.step(rpc, parse, "theprotocol_tegLockDirect", "2",
                          {"agent_jwt": S_jwt, "amount": "10", "lock_period_days": 0}, bag.developer_jwt, {},
                          record_as_separate=False)
    tsid = _d(r).get("stake_id") if ok else None
    if not tsid:
        ef.unmeasured(outcomes, "theprotocol_tegUnlockDirect", "2",
                      f"no TEG position to unlock: the lock-0 TEG position was not made ({ef.said(r)})")
    else:
        ok2, r2 = await ef.step(rpc, parse, "theprotocol_tegUnlockDirect", "2",
                                {"agent_jwt": S_jwt, "stake_id": str(tsid)}, bag.developer_jwt, outcomes)
        if ok2:
            _check(outcomes, "theprotocol_tegUnlockDirect",
                   None if str(_d(r2).get("stake_id") or tsid) == str(tsid) else
                   "the TEG unlocked another position than the one asked for")


# ── the reputation bond: the frame's own amount (the sentinel's bond, idempotent) ────────────────────────────────

async def lifecycle_earned_bond(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """depositReputationBond with the amount this frame asks (GET /reputation-bond/config): phase 3 already bonded the
    sentinel, so the deposit answers its existing locked bond and moves nothing; where phase 3's bond is missing it
    makes it. The under-minimum deposit stays as a refusal row."""
    tool = "theprotocol_depositReputationBond"
    st, conf = await _rest(bag, parse, "GET", "/api/v1/reputation-bond/config")
    try:
        amt = float(_d(conf).get("amount"))
    except (TypeError, ValueError):
        return ef.unmeasured(outcomes, tool, "2", f"the frame's bond amount could not be read (HTTP {st})")
    await ef.refusal_step(rpc, parse, tool, "2", {"agent_jwt": bag.sentinel_jwt, "amount": 1.0}, bag.developer_jwt,
                          outcomes, "an amount under the frame's minimum", codes=(400,), text="at least")
    ok, r = await ef.step(rpc, parse, tool, "2", {"agent_jwt": bag.sentinel_jwt, "amount": amt}, bag.developer_jwt,
                          outcomes)
    if ok:
        _check(outcomes, tool, None if (_d(r).get("bond_id") and str(_d(r).get("status")) == "locked") else
               f"the answer is not a locked bond (status {_d(r).get('status')!r})")

        def _locked(inner: dict) -> Optional[str]:
            return None if str(inner.get("status") or "") == "locked" else (
                f"getMyReputationBondStatus reads status {inner.get('status')!r} after the deposit")
        await ef.step(rpc, parse, "theprotocol_getMyReputationBondStatus", "2", {"agent_jwt": bag.sentinel_jwt},
                      bag.developer_jwt, outcomes, record_as_separate=False, verify_against=tool,
                      verify_against_check=_locked)


# ── governance: a five-second proposal, voted and tallied ────────────────────────────────────────────────────────

async def lifecycle_earned_tally(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The sentinel opens a standard proposal with a five-second window (POST /governance/proposals takes
    duration_seconds; the createProposal tool's floor is one day), votes for it, and tallies it once the window has
    closed (tallyProposal). The premature tally of the phase-3 proposal stays as a refusal row (mcp_lifecycles)."""
    tool = "theprotocol_tallyProposal"
    tag = _tag()
    st, resp = await _rest(bag, parse, "POST", "/api/v1/governance/proposals", {
        "title": f"MCP tester five-second proposal {tag}",
        "description": "Opened, voted and tallied by the MCP tester in one run; it changes nothing.",
        "duration_seconds": 5, "proposal_type": "standard"}, as_jwt=bag.sentinel_jwt)
    pid = _d(resp).get("id") or _d(resp).get("proposal_id")
    if st not in (200, 201) or not pid:
        return ef.unmeasured(outcomes, tool, "2", f"the sentinel could not open a short proposal (HTTP {st}: "
                                                  f"{ef.said(resp)})")
    pid_arg = int(pid) if str(pid).isdigit() else pid
    await ef.step(rpc, parse, "theprotocol_castVote", "2",
                  {"agent_jwt": bag.sentinel_jwt, "proposal_id": pid_arg, "vote_in_favor": True},
                  bag.developer_jwt, {}, record_as_separate=False)
    await asyncio.sleep(7)
    ok, r = await ef.step(rpc, parse, tool, "2", {"agent_jwt": bag.sentinel_jwt, "proposal_id": str(pid)},
                          bag.developer_jwt, outcomes, expect_events=["ProposalTallied"], event_verifier=_ev(bag))
    if ok:
        _check(outcomes, tool, None if str(_d(r).get("status") or "").upper() in ("PASSED", "FAILED", "REJECTED",
                                                                                  "EXECUTED") else
               f"the tally answered status {_d(r).get('status')!r}")

        # the proposal reads closed after the tally. Read here, not recorded: getProposalDetail's own row is the
        # governance lifecycle's (two writers of one row, the last to finish winning, said nothing either would not)
        ok_d, body_d, _ = await rpc("theprotocol_getProposalDetail", {"proposal_id": pid_arg}, jwt=bag.developer_jwt,
                                    timeout=30)
        st_d = str(_d(parse(body_d)).get("status") or "") if ok_d else ""
        _check(outcomes, tool, f"getProposalDetail still reads status {st_d!r} after the tally"
               if st_d.upper() in ("VOTING", "ACTIVE", "PENDING") else None)


# ── public reads with a real subject ─────────────────────────────────────────────────────────────────────────────

_FIAT_FIXTURE_EMAIL = "mcp-throwaway-fiat-fixture@throwaway-pl.example.com"


async def lifecycle_earned_public_reads(rpc: RpcCall, parse: ParseResult, bag: Any,
                                        outcomes: Dict[str, dict]) -> None:
    """getOrgTrackRecord on the kept transparency fixture organization; getFiatPurchaseSession on the tester's own
    fixture purchase row (one, kept across nights: a checkout asked with provider 'phase-none', which the route writes
    and then marks failed before any payment provider is reached: no money, no account). The arena reads earn their
    rows in mcp_lifecycles.lifecycle_arena_safe_paths, on the match its createArenaMatch makes."""
    m = ef.lc()
    await m._ensure_transparent_org(rpc, parse, bag)
    ok, body, _ = await rpc("theprotocol_listTransparentOrganizations", {"limit": 20}, jwt=bag.developer_jwt, timeout=30)
    orgs = _d(parse(body)).get("organizations") if ok else None
    org = next((o for o in (orgs or []) if isinstance(o, dict) and o.get("org_id")), None)
    org_id = (org or {}).get("org_id") or bag.flow_values.get("organization_id")
    if not org_id:
        ef.unmeasured(outcomes, "theprotocol_getOrgTrackRecord", "1", "no organization to read a track record of")
    else:
        ok, r = await ef.step(rpc, parse, "theprotocol_getOrgTrackRecord", "1", {"org_id": str(org_id)},
                              bag.developer_jwt, outcomes)
        if ok:
            _check(outcomes, "theprotocol_getOrgTrackRecord",
                   None if (str(_d(r).get("org_id")) == str(org_id) and isinstance(_d(r).get("verified_jobs"), int))
                   else "the track record does not belong to the organization asked for")

    tool = "theprotocol_getFiatPurchaseSession"
    cfg = await _config(rpc, parse, bag)
    if cfg.get("fiat_onramp_enabled") is not True:
        return ef.unmeasured(outcomes, tool, "1", "the fiat lane is switched off on this target (fiat_onramp_enabled)")
    sql = ("SELECT stripe_session_id FROM fiat_purchases WHERE customer_email = :e "
           "ORDER BY created_at DESC LIMIT 1")
    sid, why = await _db_one(bag, sql, {"e": _FIAT_FIXTURE_EMAIL})
    if not sid and not why:
        _st, reg = await _rest(bag, parse, "GET", "/api/v1/auth/registration-config")
        checkout = {"eur_amount": "1.00", "customer_email": _FIAT_FIXTURE_EMAIL, "tos_accepted": True,
                    "tos_version": str(_d(reg).get("tos_version") or ""), "provider": "phase-none"}
        http = getattr(bag, "http_in_target", None)
        if http is not None:   # anonymous, as a visitor asks it: the failed fixture row belongs to no developer
            await http("POST", "/api/v1/fiat/checkout-session", body=json.dumps(checkout).encode())
        else:
            await _rest(bag, parse, "POST", "/api/v1/fiat/checkout-session", checkout)
        sid, why = await _db_one(bag, sql, {"e": _FIAT_FIXTURE_EMAIL})
    if not sid:
        return ef.unmeasured(outcomes, tool, "1", f"no fixture purchase row could be read or made ({why or 'none'})")
    ok, r = await ef.step(rpc, parse, tool, "1", {"session_id": str(sid)}, bag.developer_jwt, outcomes)
    if ok:
        _check(outcomes, tool, None if str(_d(r).get("stripe_session_id")) == str(sid) else
               "the answer is not the purchase session asked for")


# ── the account recovery chain on a throwaway developer ──────────────────────────────────────────────────────────

AUTH_TOOLS = (("theprotocol_authVerifyEmail", "1"), ("theprotocol_authRecoverAccount", "1"),
              ("theprotocol_authSetNewPassword", "1"), ("theprotocol_authResetPassword", "1"))


async def lifecycle_earned_auth_chain(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """One throwaway developer T, registered here (authRegister's answer carries its recovery keys, which the runner's
    mint does not keep), walks the four public account tools in order, each on T alone:

      authVerifyEmail      a verification token written onto T's own row (this frame verifies at registration, so no
                           developer holds one; the write is guarded by T's id and its throwaway email);
      authRecoverAccount   T's first recovery key, then the same key again (burned: a refusal row);
      authSetNewPassword   the password-set token the recovery answered; T logs in with the new password only;
      authResetPassword    the reset token forgot-password stored for T, read from T's row; then again (cleared: a
                           refusal row).
    T asks for its own deletion with its final password. No value moves. Where the target registers only with an
    invite (a cloud operator: beta_invite_required), T registers with one the run asks its admin for
    (bag.registration_invite)."""
    tag = _tag()
    m = ef.lc()
    email = f"mcp-throwaway-authchain-{tag}@throwaway-pl.example.com"
    p1 = m._fresh_password()
    reg_args = {"name": f"mcp-throwaway-authchain-{tag}", "email": email, "password": p1}
    invite = getattr(bag, "registration_invite", None)
    if invite is not None:
        code, why = await invite()
        if not code:
            return _unmeasured_all(outcomes, AUTH_TOOLS, f"the target registers only with an invite, and none was "
                                                         f"had ({why})")
        reg_args["invite_code"] = code
    ok, reg = await ef.step(rpc, parse, "theprotocol_authRegister", "1", reg_args,
                            bag.developer_jwt, {}, record_as_separate=False)
    if not ok:
        return _unmeasured_all(outcomes, AUTH_TOOLS, f"no throwaway developer could be registered ({ef.said(reg)})")
    keys = _d(reg).get("recovery_keys")
    final = p1
    login = getattr(bag, "dev_login", None)
    try:
        dev_id, why = await _db_one(bag, "SELECT id FROM developers WHERE email = :e", {"e": email})
        if not dev_id:
            return _unmeasured_all(outcomes, AUTH_TOOLS, f"the throwaway developer's row was not found ({why})")
        # 1. verify: a token written onto T's own row (guarded: its id AND its throwaway email)
        vt = uuid.uuid4().hex
        n, why = await _db_write(
            bag, "UPDATE developers SET is_verified = false, email_verification_token = :t, "
            "verification_token_expires = now() + interval '1 hour' "
            "WHERE id = :i AND email = :e AND email LIKE 'mcp-throwaway-%@throwaway-pl.example.com'",
            {"t": vt, "i": int(dev_id), "e": email})
        if n != 1:
            ef.unmeasured(outcomes, "theprotocol_authVerifyEmail", "1",
                          f"no verification token could be put on the throwaway's row ({why or f'{n} rows'})")
        else:
            okv, _rv = await ef.step(rpc, parse, "theprotocol_authVerifyEmail", "1", {"token": vt},
                                     bag.developer_jwt, outcomes)
            if okv:
                verified, why = await _db_one(bag, "SELECT is_verified FROM developers WHERE id = :i",
                                              {"i": int(dev_id)})
                if why:   # the read failed, which says nothing about the product: the effect is not measured
                    ef.unmeasured(outcomes, "theprotocol_authVerifyEmail", "1",
                                  f"the throwaway's row could not be read back after its token was used ({why})")
                else:
                    _check(outcomes, "theprotocol_authVerifyEmail",
                           None if verified is True else "the throwaway's row is not verified after its token was used")
        # 2. recover with the first recovery key; 3. set the new password with the token it answers
        if not (isinstance(keys, list) and keys):
            _unmeasured_all(outcomes, AUTH_TOOLS[1:3], "authRegister's answer carried no recovery keys")
        else:
            okr, rr = await ef.step(rpc, parse, "theprotocol_authRecoverAccount", "1",
                                    {"email": email, "recovery_key": keys[0]}, bag.developer_jwt, outcomes)
            set_tok = _d(rr).get("access_token") if okr else None
            if okr:
                await ef.refusal_step(rpc, parse, "theprotocol_authRecoverAccount", "1",
                                      {"email": email, "recovery_key": keys[0]}, bag.developer_jwt, outcomes,
                                      "a recovery key already used", codes=(400,),
                                      text="Invalid email or recovery key")
            if not set_tok:
                ef.unmeasured(outcomes, "theprotocol_authSetNewPassword", "1",
                              "the recovery answered no password-set token")
            else:
                p2 = m._fresh_password(avoid=p1)
                oks, _ = await ef.step(rpc, parse, "theprotocol_authSetNewPassword", "1",
                                       {"token": set_tok, "new_password": p2}, bag.developer_jwt, outcomes)
                if oks:
                    final = p2
                    # the token sets a password once: the route refuses it once the account's version has moved
                    await ef.refusal_step(rpc, parse, "theprotocol_authSetNewPassword", "1",
                                          {"token": set_tok, "new_password": m._fresh_password(avoid=p2)},
                                          bag.developer_jwt, outcomes, "a password-set token already used",
                                          codes=(401,), text="Invalid or expired")
                    if login is not None:
                        c_new, _t1 = await login(email, p2)
                        c_old, _t2 = await login(email, p1)
                        _check(outcomes, "theprotocol_authSetNewPassword",
                               None if (str(c_new).startswith("2") and not str(c_old).startswith("2")) else
                               f"after the change the new password logs in {c_new}, the old one {c_old}")
        # 4. reset with the token forgot-password stored for T
        await rpc("theprotocol_authForgotPassword", {"email": email}, jwt=bag.developer_jwt, timeout=30)
        rt, why = await _db_one(bag, "SELECT password_reset_token FROM developers WHERE id = :i", {"i": int(dev_id)})
        if not rt:
            ef.unmeasured(outcomes, "theprotocol_authResetPassword", "1",
                          f"forgot-password stored no reset token for the throwaway ({why or 'none'})")
        else:
            p3 = m._fresh_password(avoid=final)
            okp, _ = await ef.step(rpc, parse, "theprotocol_authResetPassword", "1",
                                   {"token": str(rt), "new_password": p3}, bag.developer_jwt, outcomes)
            if okp:
                final = p3
                if login is not None:
                    c_new, _t1 = await login(email, p3)
                    _check(outcomes, "theprotocol_authResetPassword",
                           None if str(c_new).startswith("2") else
                           f"after the reset the new password logs in {c_new}")
                await ef.refusal_step(rpc, parse, "theprotocol_authResetPassword", "1",
                                      {"token": str(rt), "new_password": m._fresh_password(avoid=p3)},
                                      bag.developer_jwt, outcomes, "a reset token already used", codes=(400,))
    finally:
        await m._schedule_own_deletion(rpc, bag, email, final, "the earned auth chain's throwaway")


# ── the forge: an eval suite of the run's own, run by the sentinel on itself ─────────────────────────────────────

async def lifecycle_earned_forge_eval(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """runForgeEval where the target lets an agent trigger a run (getForgeStatus reports flags.evals_agent_trigger):
    the admin makes a disabled throwaway suite with one health task (no pay, no reputation signal), the sentinel runs
    it on itself, the admin deletes the suite. Where the trigger is switched off, the switch's refusal is a refusal row
    and the tool's own row says the run is switched off here."""
    tool = "theprotocol_runForgeEval"
    tag = _tag()
    ok, body, _ = await rpc("theprotocol_getForgeStatus", {}, jwt=bag.developer_jwt, timeout=30)
    status = _d(parse(body)) if ok else {}
    if status.get("enabled") is not True:
        return ef.unmeasured(outcomes, tool, "2", "the forge is switched off on this target (FORGE_ENABLED)")
    if _d(status.get("flags")).get("evals_agent_trigger") is not True:
        await ef.refusal_step(rpc, parse, tool, "2", {"agent_jwt": bag.sentinel_jwt, "suite_id": 999999999},
                              bag.developer_jwt, outcomes, "while agent-triggered runs are switched off",
                              codes=(403,), text="EVALS_AGENT_TRIGGER_ENABLED")
        return ef.unmeasured(outcomes, tool, "2", "agent-triggered eval runs are switched off on this target "
                                                  "(EVALS_AGENT_TRIGGER_ENABLED); the switch's refusal is a refusal row")
    sid = None
    try:
        st, resp = await _rest(bag, parse, "POST", "/api/v1/admin/evals/suites", {
            "key": f"mcp-tester-forge-{tag}"[:80], "name": "MCP tester forge probe, deleted in the same run",
            "task_type": "http_probe", "enabled": False, "pay_per_task": "0", "emit_reputation_signal": False})
        sid = _d(resp).get("id")
        if st != 200 or not isinstance(sid, int):
            return ef.unmeasured(outcomes, tool, "2", f"no eval suite could be made (HTTP {st}: {ef.said(resp)})")
        st, resp = await _rest(bag, parse, "POST", f"/api/v1/admin/evals/suites/{sid}/tasks",
                               {"name": "health", "input": {"path": "/health"}, "scorer": "status_ok"})
        if st not in (200, 201):
            return ef.unmeasured(outcomes, tool, "2", f"the suite took no task (HTTP {st}: {ef.said(resp)})")
        ok, r = await ef.step(rpc, parse, tool, "2", {"agent_jwt": bag.sentinel_jwt, "suite_id": sid},
                              bag.developer_jwt, outcomes)
        if ok:
            _check(outcomes, tool, None if (_d(r).get("suite_id") == sid and _d(r).get("run_id")) else
                   "the answer names no run of the suite asked for")
    finally:
        if isinstance(sid, int):
            await _rest(bag, parse, "DELETE", f"/api/v1/admin/evals/suites/{sid}")


# ── a bid on the peer frame: an order the run posts there, a bidder bonded here ───────────────────────────────────

class _Peer:
    """The peer frame's registry, reached inside its own container (API_TEST_FED_B_CONTAINER, as the federation suite's
    rig names it) over this registry's docker socket: curl to the container's own localhost:8000, the body through
    stdin. None where no peer is named or no docker socket is mounted."""

    def __init__(self, container: str):
        self.container = container

    @classmethod
    def from_env(cls) -> Optional["_Peer"]:
        c = os.environ.get("API_TEST_FED_B_CONTAINER", "")
        return cls(c) if c and os.path.exists("/var/run/docker.sock") else None

    async def rest(self, method: str, path: str, body: Any = None, *, bearer: str = "", form: bool = False,
                   timeout: int = 30) -> Tuple[int, Any]:
        from urllib.parse import urlencode
        from agentvault_registry.api_tests.multiframe_helpers import _HTTP_MARKER, _split_http_body_code, \
            exec_in_container
        data = (urlencode(body or {}) if form else json.dumps(body)) if body is not None else ""
        ctype = "application/x-www-form-urlencoded" if form else "application/json"
        script = ((f"echo '{base64.b64encode(data.encode()).decode()}' | base64 -d | " if data else "")
                  + f"curl -sS --connect-timeout 5 --max-time {timeout} -X {method} "
                  + (f"-H 'Authorization: Bearer {bearer}' " if bearer else "")
                  + f"-H 'Content-Type: {ctype}' " + ("--data-binary @- " if data else "")
                  + f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' 'http://localhost:8000{path}'")
        rc, out = await asyncio.to_thread(exec_in_container, self.container, ["sh", "-c", script], timeout + 10)
        text, code = _split_http_body_code(out or "")
        try:
            parsed = json.loads(text) if text.strip() else {}
        except ValueError:
            parsed = {"_text": text[:300]}
        return (int(code) if code.isdigit() else 0), parsed

    async def mcp(self, parse: ParseResult, tool: str, args: Dict[str, Any], jwt: str) -> Tuple[int, Dict[str, Any]]:
        st, env = await self.rest("POST", "/mcp/rpc", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                       "params": {"name": tool, "arguments": args}}, bearer=jwt)
        return st, _d(parse(env)) if st == 200 and not _d(env).get("error") else _d(env)


GUILD_XREG = "theprotocol_guildCrossRegistryBid"


async def lifecycle_earned_guild_cross_registry(rpc: RpcCall, parse: ParseResult, bag: Any,
                                                outcomes: Dict[str, dict]) -> None:
    """guildCrossRegistryBid on an order the run posts at the peer frame. There an agent of the peer admin's, given
    0.01 from the peer's treasury, posts a 0.01 task; here an agent of the runner's with a backstop bond bids on it
    through this registry, once the peer's mirror of its card reads bonded (the peer gates a remote bid on its mirror;
    a fresh bonded card reached sbx-beta within 30 s, measured 2026-10-24). The peer's order must list the bid. The
    poster then cancels (the bounty comes back to it) and both agents are deleted: a bid cannot be withdrawn, so it is
    only ever placed on the run's own order."""
    tag = _tag()
    peer = _Peer.from_env()
    if peer is None:
        return ef.unmeasured(outcomes, GUILD_XREG, "2", "needs the peer frame: no peer registry container is named "
                             "here (API_TEST_FED_B_CONTAINER), or this process has no docker socket to reach it")
    creds = {"username": os.environ.get("API_TEST_FED_B_EMAIL", ""), "password": os.environ.get("API_TEST_FED_B_PASSWORD", "")}
    st, tok = await peer.rest("POST", "/api/v1/auth/login", creds, form=True)
    creds = {}
    dev_b = _d(tok).get("access_token") if st == 200 else None
    if not dev_b:
        return ef.unmeasured(outcomes, GUILD_XREG, "2", f"the peer admin could not sign in (HTTP {st})")
    _st, pcfg = await peer.rest("GET", "/api/v1/public/registry-config")
    name = str(_d(pcfg).get("registry_name") or "")
    row, why = (await _db_one(bag, "SELECT name FROM peer_registries WHERE status = 'ACTIVE' "
                                   "AND lower(name) = lower(:n)", {"n": name})) if name else (
        None, "the peer named no registry_name")
    if not row:
        return ef.unmeasured(outcomes, GUILD_XREG, "2", f"this registry holds no ACTIVE peer row for the peer frame "
                             f"{name!r} ({why or 'no row'})")
    t = ef.Throwaways(rpc, parse, bag, "xbid")
    poster: Dict[str, Any] = {}
    oid: Optional[str] = None
    try:
        st, made = await peer.mcp(parse, "theprotocol_createAgent", {
            "name": f"mcp-xbid-poster-{tag}", "description": "MCP tester: posts one task for a cross-registry bid "
                                                             "(cancelled and deleted after)"}, dev_b)
        poster = {"did": made.get("did") or made.get("agent_did"), "cid": made.get("client_id"),
                  "sec": made.get("client_secret")}
        if not all(poster.values()):
            return ef.unmeasured(outcomes, GUILD_XREG, "2", f"no poster agent at the peer (HTTP {st}: {ef.said(made)})")
        st, ptok = await peer.rest("POST", "/api/v1/auth/agent/token",
                                   {"username": poster["cid"], "password": poster["sec"]}, form=True)
        poster["sec"] = None
        p_jwt = _d(ptok).get("access_token")
        st_f, fund = await peer.rest("POST", "/api/v1/teg/treasury/fund-agent", {
            "target_agent_did": poster["did"], "amount": DUST, "reason": "admin_grant",
            "reference_id": f"mcp-xbid-{tag}"}, bearer=dev_b)
        if not p_jwt or st_f != 200:
            return ef.unmeasured(outcomes, GUILD_XREG, "2", f"the peer's poster could not be funded (token "
                                 f"{bool(p_jwt)}, fund HTTP {st_f}: {ef.said(fund)})")
        st, order = await peer.rest("POST", "/api/v1/guild/orders", {
            "title": f"MCP tester cross-registry bid {tag}", "bounty": float(DUST), "deadline_seconds": 3600,
            "spec": "Posted by the MCP tester for one bid from another registry; cancelled in the same run."},
            bearer=p_jwt)
        oid = _d(order).get("id") or _d(order).get("order_id")
        if not oid:
            return ef.unmeasured(outcomes, GUILD_XREG, "2", f"the peer took no order (HTTP {st}: {ef.said(order)})")
        B = await t.agent(_admin_dev(bag), "bidder")
        if B.get("why"):
            return ef.unmeasured(outcomes, GUILD_XREG, "2", f"no bidder agent here ({B['why']})")
        why = await _backstop(bag, parse, B["did"])
        if why:
            return ef.unmeasured(outcomes, GUILD_XREG, "2", why.replace("provider", "bidder"))
        mirrored = False
        for _ in range(12):     # up to two minutes for the peer's mirror of the bidder's card to read bonded
            _st, found = await peer.rest("GET", f"/api/v1/agent-cards/discover?q={B['did']}&limit=3")
            mirrored = any(_d(i).get("agent_did") == B["did"] and _d(i).get("is_bonded") is True
                           for i in (_d(found).get("items") or []))
            if mirrored:
                break
            await asyncio.sleep(10)
        if not mirrored:
            return ef.unmeasured(outcomes, GUILD_XREG, "2", "the peer's mirror of the bidder's card did not read bonded "
                                 "within two minutes (the peer gates a remote bid on it)")
        ok, r = await ef.step(rpc, parse, GUILD_XREG, "2", {
            "agent_jwt": B["agent_jwt"], "target_registry_url": str(row), "order_id": str(oid), "action": "bid",
            "price": DUST, "eta_seconds": 3600, "pitch": f"MCP tester cross-registry bid {tag}"},
            bag.developer_jwt, outcomes)
        if ok:
            _st, held = await peer.rest("GET", f"/api/v1/guild/orders/{oid}")
            bids = _d(held).get("bids") or []
            _check(outcomes, GUILD_XREG, None if any(_d(b).get("bidder_did") == B["did"] for b in bids) else
                   f"the peer's order lists no bid by the bidder ({len(bids)} bid(s))")
    finally:
        if oid and poster.get("did"):
            await peer.rest("POST", f"/api/v1/guild/orders/{oid}/cancel", {}, bearer=p_jwt or "")
        if poster.get("did"):
            await peer.rest("DELETE", f"/api/v1/developers/me/agents/{poster['did']}", bearer=dev_b)
        await t.close()


# ── the local Guild where phase 3 staged no orders (a cloud operator's run) ───────────────────────────────────────

GUILD_LOCAL_TOOLS = (
    ("theprotocol_guildPostOrder", "2"), ("theprotocol_guildGetOrder", "1"), ("theprotocol_guildBid", "2"),
    ("theprotocol_guildAward", "2"), ("theprotocol_guildSubmitWork", "2"), ("theprotocol_guildVerify", "2"),
    ("theprotocol_guildCancelOrder", "2"),
)
# the five orders the lifecycle opens, by the tool each one is parked for
GUILD_LOCAL_ORDERS = ("read", "award", "submit", "verify", "cancel")
# what every one of them must end as: settled (verified and paid) or cancelled (the bounty refunded)
GUILD_TERMINAL = ("settled", "cancelled")
GUILD_CLOSED_ROW = "guild: every order the run opened ends settled or cancelled"


def sandbox_stated(read: bool, code: Any, cfg: Any) -> Tuple[bool, str]:
    """Whether the target ITSELF states "sandbox" (registry-config's `environment`, core/registry_environment.py, V0644).
    Only that exact string stages a money-moving fixture (agentvault2-aa, 2026-10-26); everything else is no sandbox
    and is named: "production", a field the target does not state, another value or another case, a config not read."""
    if not read or not isinstance(cfg, dict):
        return False, f"the target's registry-config could not be read (HTTP {code})"
    if "environment" not in cfg:
        return False, "the target's registry-config states no environment (a release before V0644)"
    env = cfg.get("environment")
    if env == "sandbox":
        return True, ""
    return False, f"the target states environment {env!r}, not 'sandbox'"


async def _guild_held(rpc: RpcCall, parse: ParseResult, did: str, owner_jwt: str) -> Optional[Decimal]:
    """What `did` holds, read as Throwaways reads it before returning it; None when unread (never a zero)."""
    ok, body, _code = await rpc("theprotocol_getBatchAgentBalances", {"agent_dids": [did]}, jwt=owner_jwt, timeout=20)
    entry = _d(_d(_d(parse(body)).get("balances")).get(did)) if ok else {}
    if not entry or entry.get("error"):
        return None
    try:
        held = Decimal(str(entry.get("balance")))
    except (InvalidOperation, ValueError):
        return None
    return held if held.is_finite() else None


async def _guild_status(rpc: RpcCall, parse: ParseResult, oid: str, jwt: str) -> str:
    ok, body, _code = await rpc("theprotocol_guildGetOrder", {"order_id": oid}, jwt=jwt, timeout=20)
    return str(_d(_d(parse(body)).get("order")).get("status") or "") if ok else ""


async def close_guild_orders(rpc: RpcCall, parse: ParseResult, oids: List[str], poster_jwt: str, worker_jwt: str,
                             jwt: str) -> Dict[str, str]:
    """Every order in `oids` driven to settled or cancelled through the guild's own routes, then read back: an open one
    cancelled by its poster (the bounty refunded), an awarded one delivered by its worker and verified by its poster, a
    submitted one verified. Returns each order's status as read back after the pass (empty when unread); one only an
    admin can move (disputed) is left as it is and reads so."""
    for oid in oids:
        st = await _guild_status(rpc, parse, oid, jwt)
        if st == "open":
            await rpc("theprotocol_guildCancelOrder", {"order_id": oid, "agent_jwt": poster_jwt}, jwt=jwt, timeout=30)
            continue
        if st == "awarded":
            await rpc("theprotocol_guildSubmitWork", {"order_id": oid, "deliverable_text": "MCP tester: closing the "
                      "run's own order", "agent_jwt": worker_jwt}, jwt=jwt, timeout=30)
            st = await _guild_status(rpc, parse, oid, jwt)
        if st == "submitted":
            await rpc("theprotocol_guildVerify", {"order_id": oid, "accept": True, "stars": 5,
                      "agent_jwt": poster_jwt}, jwt=jwt, timeout=30)
    return {oid: await _guild_status(rpc, parse, oid, jwt) for oid in oids}


async def lifecycle_earned_guild_local(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The local Guild on a run whose phase 3 staged no orders (a cloud operator's). A frame's phase 3 posts its own and
    its contracts measure them, so there this does nothing. agentvault2-aa's conditions (2026-10-26): it stages only where
    the target itself states "sandbox" (sandbox_stated), where the treasury funds the poster and the poster then holds
    every bounty; otherwise every guild row stays NOT MEASURED with what was read. A poster and a worker of the runner's
    (the worker bonded by the backstop, which a bid needs) open five orders of DUST each, every leg on the guild's own
    routes: one read and bid on (guildGetOrder, guildBid), one awarded (guildAward), one delivered (guildSubmitWork), one
    verified and paid (guildVerify), one cancelled (guildCancelOrder). Then every order is closed in the same run and
    read back, and the run's own row says whether each ends settled or cancelled (GUILD_CLOSED_ROW). What the two
    agents hold goes back to the treasury when they are deleted (Throwaways)."""
    if _d(getattr(bag, "flow_values", None)).get("guild_order_id"):
        return
    ok, body, code = await rpc("theprotocol_getPublicRegistryConfig", {}, jwt=bag.developer_jwt, timeout=30)
    staged, why = sandbox_stated(bool(ok), code, _d(parse(body)) if ok else None)
    if not staged:
        return _unmeasured_all(outcomes, GUILD_LOCAL_TOOLS, "guild orders are staged only where the target itself "
                               f"states 'sandbox': {why}")
    ok, body, code = await rpc("theprotocol_guildListOrders", {"limit": 1}, jwt=bag.developer_jwt, timeout=20)
    if not ok:
        said = ef.said(_d(parse(body)))
        return _unmeasured_all(outcomes, GUILD_LOCAL_TOOLS, "the Guild's order list answered HTTP "
                               f"{code} ({said}): the Guild is not usable here")
    tag = _tag()
    t = ef.Throwaways(rpc, parse, bag, "guild")
    P: Dict[str, Any] = {}
    W: Dict[str, Any] = {}
    oids: Dict[str, str] = {}
    try:
        P = await t.agent(_admin_dev(bag), "poster")
        W = await t.agent(_admin_dev(bag), "worker")
        if P.get("why") or W.get("why"):
            return _unmeasured_all(outcomes, GUILD_LOCAL_TOOLS, f"no poster or worker agent ({P.get('why') or W.get('why')})")
        need = Decimal(DUST) * len(GUILD_LOCAL_ORDERS)
        st, resp = await _rest(bag, parse, "POST", "/api/v1/teg/treasury/fund-agent", {
            "target_agent_did": P["did"], "amount": format(need * 2, "f"), "reason": "admin_grant",
            "reference_id": f"mcp-guild-{tag}"})
        if st != 200:
            return _unmeasured_all(outcomes, GUILD_LOCAL_TOOLS, f"the treasury could not fund the poster (HTTP {st}: "
                                   f"{ef.said(resp)})")
        held = await _guild_held(rpc, parse, P["did"], bag.developer_jwt)
        if held is None or held < need:
            shown = "an unread balance" if held is None else format(held, "f")
            return _unmeasured_all(outcomes, GUILD_LOCAL_TOOLS, f"the poster holds {shown} after funding, and the "
                                   f"{len(GUILD_LOCAL_ORDERS)} bounties need {need}")
        why = await _backstop(bag, parse, W["did"])
        if why:
            return _unmeasured_all(outcomes, GUILD_LOCAL_TOOLS, why.replace("provider", "worker"))
        for i, role in enumerate(GUILD_LOCAL_ORDERS):
            ok, r = await ef.step(rpc, parse, "theprotocol_guildPostOrder", "2", {
                "title": f"MCP tester guild {role} {tag}", "bounty": DUST, "agent_jwt": P["agent_jwt"]},
                bag.developer_jwt, outcomes, record_as_separate=(i == 0))
            oid = str(_d(r).get("order_id") or "")
            if i == 0 and ok:
                _check(outcomes, "theprotocol_guildPostOrder",
                       "the answer names no order id" if not oid else _status_is("open")(r))
            if not (ok and oid):
                return _unmeasured_all(outcomes, GUILD_LOCAL_TOOLS, f"only {len(oids)} of the "
                                       f"{len(GUILD_LOCAL_ORDERS)} orders could be posted ({ef.said(r)})")
            oids[role] = oid

        async def bid(oid: str) -> Optional[str]:
            """The worker bids (a staging leg, no row); the bid's own id, from its answer."""
            okb, body_b, _c = await rpc("theprotocol_guildBid", {"order_id": oid, "price": DUST,
                                        "agent_jwt": W["agent_jwt"]}, jwt=bag.developer_jwt, timeout=30)
            got = _d(parse(body_b)) if okb else {}
            return str(got.get("bid_id")) if got.get("bid_id") is not None else None

        async def stage(tool: str, args: Dict[str, Any]) -> bool:
            oks, _b, _c = await rpc(tool, args, jwt=bag.developer_jwt, timeout=30)
            return bool(oks)

        # read + bid: the order the worker bids on, and the bid names the worker
        ok, r = await ef.step(rpc, parse, "theprotocol_guildGetOrder", "1", {"order_id": oids["read"]},
                              bag.developer_jwt, outcomes)
        if ok:
            _check(outcomes, "theprotocol_guildGetOrder", None if str(_d(_d(r).get("order")).get("id")) == oids["read"]
                   else "the answer is another order than the one asked for")
        ok, r = await ef.step(rpc, parse, "theprotocol_guildBid", "2", {
            "order_id": oids["read"], "price": DUST, "agent_jwt": W["agent_jwt"]}, bag.developer_jwt, outcomes)
        if ok:
            _check(outcomes, "theprotocol_guildBid", None if _d(r).get("bidder") == W["did"] else
                   f"the bid names {_d(r).get('bidder')!r}, not the worker")
        # award: the poster awards the worker's bid
        bid_award = await bid(oids["award"])
        if bid_award:
            ok, r = await ef.step(rpc, parse, "theprotocol_guildAward", "2", {
                "order_id": oids["award"], "bid_id": bid_award, "agent_jwt": P["agent_jwt"]}, bag.developer_jwt, outcomes)
            if ok:
                _check(outcomes, "theprotocol_guildAward", _status_is("awarded")(r))
        else:
            ef.unmeasured(outcomes, "theprotocol_guildAward", "2", "the worker's bid on the award order named no bid id")
        # submit: an awarded order, delivered by the worker
        bid_submit = await bid(oids["submit"])
        if bid_submit and await stage("theprotocol_guildAward", {"order_id": oids["submit"], "bid_id": bid_submit,
                                                                  "agent_jwt": P["agent_jwt"]}):
            ok, r = await ef.step(rpc, parse, "theprotocol_guildSubmitWork", "2", {
                "order_id": oids["submit"], "deliverable_text": f"MCP tester deliverable {tag}",
                "agent_jwt": W["agent_jwt"]}, bag.developer_jwt, outcomes)
            if ok:
                _check(outcomes, "theprotocol_guildSubmitWork", _status_is("submitted")(r))
        else:
            ef.unmeasured(outcomes, "theprotocol_guildSubmitWork", "2", "the submit order could not be awarded first")
        # verify: a delivered order, accepted and paid by the poster
        bid_verify = await bid(oids["verify"])
        if (bid_verify and await stage("theprotocol_guildAward", {"order_id": oids["verify"], "bid_id": bid_verify,
                                                                   "agent_jwt": P["agent_jwt"]})
                and await stage("theprotocol_guildSubmitWork", {"order_id": oids["verify"], "deliverable_text":
                                f"MCP tester deliverable {tag}", "agent_jwt": W["agent_jwt"]})):
            ok, r = await ef.step(rpc, parse, "theprotocol_guildVerify", "2", {
                "order_id": oids["verify"], "accept": True, "stars": 5, "agent_jwt": P["agent_jwt"]},
                bag.developer_jwt, outcomes)
            if ok:
                _check(outcomes, "theprotocol_guildVerify", _status_is("settled")(r))
        else:
            ef.unmeasured(outcomes, "theprotocol_guildVerify", "2", "the verify order could not be awarded and delivered first")
        # cancel: an open order, cancelled by its poster
        ok, r = await ef.step(rpc, parse, "theprotocol_guildCancelOrder", "2", {
            "order_id": oids["cancel"], "agent_jwt": P["agent_jwt"]}, bag.developer_jwt, outcomes)
        if ok:
            _check(outcomes, "theprotocol_guildCancelOrder", _status_is("cancelled")(r))
    finally:
        if oids:
            final = await close_guild_orders(rpc, parse, list(oids.values()), P.get("agent_jwt") or "",
                                             W.get("agent_jwt") or "", bag.developer_jwt)
            left = {o: s for o, s in final.items() if s not in GUILD_TERMINAL}
            ef.tool_row(GUILD_CLOSED_ROW, outcomes, "2", not left, 200 if not left else 409, 0,
                        (f"{len(left)} of the {len(final)} orders the run opened did not end settled or cancelled: "
                         + ", ".join(f"{o} {s or 'unread'}" for o, s in left.items())) if left else None,
                        {"orders": dict(final)})
        await t.close()


# ── a payment to the frame's own treasury ─────────────────────────────────────────────────────────────────────

SYSTEM_TRANSFER = "theprotocol_tegSystemTransfer"


async def lifecycle_earned_system_transfer(rpc: RpcCall, parse: ParseResult, bag: Any,
                                           outcomes: Dict[str, dict]) -> None:
    """tegSystemTransfer: a run agent, given 0.01 from the treasury and the legacy-full role for an hour (the only role
    that carries teg.system_transfer: IRONKEY keeps it out of every normal role), pays the 0.01 back to the frame's
    system treasury. The answer must name the treasury and a transaction, and the payer's new balance must read 0: the
    units went back where they came from. The TEG journals both legs, and its outbox writes them to the store."""
    tag = _tag()
    t = ef.Throwaways(rpc, parse, bag, "systx")
    try:
        A = await t.agent(_admin_dev(bag), "payer")
        if A.get("why"):
            return ef.unmeasured(outcomes, SYSTEM_TRANSFER, "2", f"no payer agent ({A['why']})")
        st, resp = await _rest(bag, parse, "POST", "/api/v1/teg/treasury/fund-agent", {
            "target_agent_did": A["did"], "amount": DUST, "reason": "admin_grant", "reference_id": f"mcp-systx-{tag}"})
        if st != 200:
            return ef.unmeasured(outcomes, SYSTEM_TRANSFER, "2", f"the payer could not be given {DUST} from the "
                                 f"treasury (HTTP {st}: {ef.said(resp)})")
        st, resp = await _rest(bag, parse, "POST", f"/api/v1/agents/{A['did']}/authz/roles", {
            "role": "legacy-full", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
        if st not in (200, 201):
            return ef.unmeasured(outcomes, SYSTEM_TRANSFER, "2", f"the payer could not be given the role that carries "
                                 f"teg.system_transfer (HTTP {st}: {ef.said(resp)})")
        ok, r = await ef.step(rpc, parse, SYSTEM_TRANSFER, "2", {
            "agent_jwt": A["agent_jwt"], "amount": DUST,
            "purpose": f"MCP tester {tag}: the {DUST} the treasury gave this run agent, paid back"},
            bag.developer_jwt, outcomes)
        if ok:
            r = _d(r)
            try:
                left = float(str(r.get("new_sender_balance")))
            except ValueError:
                left = None
            _check(outcomes, SYSTEM_TRANSFER,
                   None if (r.get("transaction_id") and r.get("system_receiver_id") and left == 0.0) else
                   f"the answer names transaction {r.get('transaction_id')!r}, receiver "
                   f"{r.get('system_receiver_id')!r} and a new balance of {r.get('new_sender_balance')!r}, not 0")
    finally:
        await t.close()


# ── the onboarding bundle: a zip its owner downloads with the agent's own credentials ────────────────────────────────

ONBOARD_BUNDLE = "theprotocol_downloadBundleViaOnboard"
# the route's default, "full-capacity", has no template directory on any frame stood up since 2026-09-07 (it was a
# host bind mount on Frame A): a product question (agentvault2-d6, V0640); "minimal" ships in the image everywhere
ONBOARD_BUNDLE_TEMPLATE = "minimal"
_NO_SUCH_DID = "did:theprotocol:00000000-0000-4000-8000-000000000000"


async def lifecycle_earned_onboard_bundle(rpc: RpcCall, parse: ParseResult, bag: Any,
                                          outcomes: Dict[str, dict]) -> None:
    """downloadBundleViaOnboard: a throwaway developer's throwaway agent, its bundle downloaded with its own DID, client
    id and secret, then both deleted (Throwaways). The request carries the agent's secret and the zip embeds it
    (.env.secret), so the tool's row is written by hand: no argument and no byte of the answer, only whether a zip came
    back and, where the answer lists them, its entries' names and sizes (agentvault2-aa's constraints for V0640). Its
    refusals: an agent that does not exist (404), a client id that is not the agent's (400), a secret that is not the
    agent's (400, nothing built: V0640's fix/onboard-bundle-secret) and a template no registry has (404 naming the
    ones this one has, never a 500: fix/forge-template-choice)."""
    t = ef.Throwaways(rpc, parse, bag, "bundle")
    try:
        dev = await t.developer("bundle")
        A = {"why": dev["why"]} if dev.get("why") else await t.agent(dev, "bundle")
        if A.get("why"):
            return ef.unmeasured(outcomes, ONBOARD_BUNDLE, "3", f"no throwaway agent to download a bundle for "
                                                                f"({A['why']})")
        jwt = dev["access_token"]

        def ask(did: str, client_id: str, secret: str, template: str = ONBOARD_BUNDLE_TEMPLATE) -> Dict[str, Any]:
            return {"bundle_data": {"agent_did": did, "client_id": client_id, "client_secret": secret,
                                    "template_type": template}}

        await ef.refusal_step(rpc, parse, ONBOARD_BUNDLE, "3", ask(_NO_SUCH_DID, A["client_id"], "not-its-secret"),
                              jwt, outcomes, "for an agent that does not exist", codes=(404,), text="not found")
        await ef.refusal_step(rpc, parse, ONBOARD_BUNDLE, "3",
                              ask(A["did"], "agent-not-its-client-id", "not-its-secret"), jwt, outcomes,
                              "with a client id that is not the agent's", codes=(400,), text="client_id does not match")
        await ef.refusal_step(rpc, parse, ONBOARD_BUNDLE, "3",
                              ask(A["did"], A["client_id"], "tp_secret_not-its-secret"), jwt, outcomes,
                              "with a secret that is not the agent's", codes=(400,),
                              text="client_secret does not match")
        await ef.refusal_step(rpc, parse, ONBOARD_BUNDLE, "3",
                              ask(A["did"], A["client_id"], A["client_secret"], "apitest-no-such-template"), jwt,
                              outcomes, "for a template no registry has", codes=(404,),
                              text="is not available on this registry")
        t0 = time.time()
        ok, body, code = await rpc(ONBOARD_BUNDLE, ask(A["did"], A["client_id"], A["client_secret"]), jwt=jwt,
                                   timeout=60)
        ans = parse(body) if isinstance(body, dict) else {}
        is_zip, entries = ef.zip_answer(ans)
        fail = None
        if not ok:
            fail = f"the agent's own credentials were refused (HTTP {code}: {ef.said(ans)})"
        elif not is_zip:
            fail = "BUG-FIND: answered 2xx without a zip archive"
        elif entries and ".env.secret" not in {e["name"] for e in entries}:
            fail = f"BUG-FIND: the bundle carries no .env.secret ({len(entries)} entries)"
        ef.tool_row(ONBOARD_BUNDLE, outcomes, "3", ok, code, int((time.time() - t0) * 1000), fail,
                    {"zip": is_zip, "entries": len(entries), "files": entries[:20],
                     "template_type": ONBOARD_BUNDLE_TEMPLATE})
    finally:
        await t.close()


# ── tools no MCP caller can succeed with: said on their own row ──────────────────────────────────────────────────

BY_DESIGN = (
    ("theprotocol_crossTegBalanceSync", "2",
     "a registry-to-registry callback after a cross-TEG transfer: the route takes only a federation peer's identity "
     "(mTLS, the internal secret or a licence), which no MCP caller carries, by design (PEER_ROUTE_BASELINE)"),
    ("theprotocol_federationSyncRequest", "2",
     "a peer registry pushes its cards here: the route takes only a federation peer's identity, which no MCP caller "
     "carries, by design (an open door would let any caller write cards into the mirror)"),
    ("theprotocol_submitOnboardRegister", "2",
     "POST /onboard/register is 410 GONE (the bootstrap and create_agent flow replaced it; createAgent covers it)"),
    ("theprotocol_claimLockPayouts", "2",
     "the claim rail is retired (§MONEY-R22, D9): the distributor makes the payouts, and the route answers 404 unless "
     "REGISTRY_STAKING_CLAIM_REWARDS_ENABLED, which would book the payouts a second time"),
    # §MCPTEST30 (V0640): the two public federation reads said "refusal only" (the router's generic sentence) where
    # their contracts' success_path_unmeasured named why; said on their own rows now, their 401 a refusal row
    ("theprotocol_getFederationPolicyCompliance", "1",
     "a federation peer reads this registry's policy compliance: the route takes only a federation peer's identity "
     "(mTLS, the internal secret or a licence), which no MCP caller carries, by design (an admin reads the same answer "
     "through getAdminFederationPolicyCompliance). Its refusal is a refusal row"),
    ("theprotocol_listFederationRegistryCards", "1",
     "a federation peer reads the registry cards this registry federates: the route takes only a federation peer's "
     "identity, which no MCP caller carries, by design (anyone reads the federation's registries through "
     "listFederationRegistries or discoverRegistries). Its refusal is a refusal row"),
    # §MCPTEST30 (V0641): three developer-tier tools on routes that take only a federation peer's identity
    # (core/federation_auth.get_federation_identity, 401 to a developer token) read "refusal only" on both sandbox
    # operators in V0639's read (2026-10-25), as on the frames
    ("theprotocol_getFederationSyncStatusDev", "3",
     "a federation peer reads this registry's sync status with its peers: the route takes only a federation peer's "
     "identity (mTLS, the internal secret or a licence), which no MCP caller carries, by design (an admin reads the "
     "same through getFederationSyncStatus). Its refusal is a refusal row"),
    ("theprotocol_federationSlashRequest", "3",
     "a complainant's home registry asks this one, the defendant's home, to slash: the route takes only the origin "
     "registry's federation identity (mTLS), which no MCP caller carries, by design (a slash moves the defendant's "
     "units). Its refusal is a refusal row"),
    ("theprotocol_federationSlashConfirmation", "3",
     "the defendant's home registry confirms a slash to the complainant's home: the route takes only that registry's "
     "federation identity (mTLS), which no MCP caller carries, by design (a confirmation pays the complainant). Its "
     "refusal is a refusal row"),
)

# the public peer-only reads in BY_DESIGN whose refusal is kept as a refusal row (lifecycle_earned_by_design)
PEER_ONLY_READS = ("theprotocol_getFederationPolicyCompliance", "theprotocol_listFederationRegistryCards")
# §MCPTEST30 (V0641): the developer-tier peer-only tools in BY_DESIGN, with what their refusal row sends: the arguments
# their tools require, made-up values, so the call reaches the route and its peer-identity check refuses it first
PEER_ONLY_DEV_TOOLS: Tuple[Tuple[str, Dict[str, Any]], ...] = (
    ("theprotocol_getFederationSyncStatusDev", {}),
    ("theprotocol_federationSlashRequest",
     {"settlement_id": "00000000-0000-4000-8000-000000000000", "dispute_id": 999999999, "ruling": "apitest-probe",
      "amount": 999999999, "complainant_did": "did:theprotocol:00000000-0000-4000-8000-000000000000",
      "defendant_did": "did:theprotocol:00000000-0000-4000-8000-000000000000",
      "origin_registry_url": "https://nonexistent.invalid", "callback_url": "https://nonexistent.invalid"}),
    ("theprotocol_federationSlashConfirmation",
     {"settlement_id": "00000000-0000-4000-8000-000000000000", "status": "apitest-probe", "amount": 999999999}),
)


# a tool that can succeed, held back on purpose where it is switched on (where it is off, its switch's verdict stands)
HELD_BACK = (
    ("theprotocol_bridgeTransfer", "2", "token_bridge_enabled",
     "held back on purpose: a transfer locks units here and mints wrapped units on the peer frame, and no MCP tool "
     "brings them back (bridgeRedeem is an admin tool on an agent-only route); the bridge family is on his D8 retire "
     "list. Its refusal (an amount of 0) is a refusal row"),
)


# a tool whose success needs the peer frame in a way no lifecycle can reach yet: said, with what it needs (the cross-
# registry guild bid has its own lifecycle since V0636: lifecycle_earned_guild_cross_registry)
NEEDS_PEER: Tuple[Tuple[str, str, str], ...] = ()


# §MCPTEST30 (V0641): tools whose success no tester run should drive or can reach, on every node class: NOT MEASURED on
# their own rows with the reason, their refusal a refusal row held to what each node class answers (agentvault2-aa's
# frame pair nt261025x1a on V0639, 2026-10-25 07:04-07:11Z, and V0639's operator read). Their probes were in
# lifecycle_misc_safe, which an operator run does not take, so on the operators each passed on its contract's refusal
# alone; on the frames on the probe's.
NOT_DRIVEN: Tuple[Tuple[str, str, str], ...] = (
    ("theprotocol_finalizeFrameInvitation", "3",
     "held back on purpose: finalizing an approved frame invitation federates two frames, which no tester run does. "
     "Its refusal (an invitation that does not exist) is a refusal row"),
    ("theprotocol_approveDisputeSettlement", "3",
     "held back on purpose: a settlement exists only for a dispute against another registry's agent that an admin has "
     "ruled, and approving it slashes that agent's units on its home registry, which no tester run does. Its refusal "
     "(a settlement that does not exist) is a refusal row"),
    ("theprotocol_rejectDisputeSettlement", "3",
     "held back on purpose: a settlement exists only for a dispute against another registry's agent that an admin has "
     "ruled, which no tester run makes (approving one slashes that agent). Its refusal (a settlement that does not "
     "exist) is a refusal row"),
    ("theprotocol_getFederationDisputeSettlement", "3",
     "a settlement exists only for a dispute against another registry's agent that an admin has ruled, which no tester "
     "run makes (approving one slashes that agent). Its refusal (a settlement that does not exist) is a refusal row"),
    ("theprotocol_getRelayStatus", "3",
     "a relay's status needs an agent that runs a relay, which no run's agent does (the sentinel declares none). Its "
     "refusal (the sentinel, an agent with no relay) is a refusal row"),
    ("theprotocol_relayAction", "3",
     "starting, stopping or restarting a relay needs an agent that declares one, which no run's agent does. Its refusal "
     "(a relay tool the route does not offer) is a refusal row"),
    # §MCPTEST30 (V0641): refusal-only on both node classes (the V0641 operator preview, aa's frame pair nt261025x1a)
    ("theprotocol_getOperatorMyLifecycle", "3",
     "an operator's lifecycle is read on its parent frame by the developer who owns its operator application (the "
     "operator's applicant), which no run's developer is; the federation suite measures it there, as the applicant "
     "(test_cloud_op_self_logs). Its refusal (a developer with no application) is a refusal row"),
)

_NO_ID = "00000000-0000-4000-8000-000000000000"


def not_driven_refusals(bag: Any) -> List[Tuple[str, Dict[str, Any], str, Tuple[int, ...], Tuple[str, ...]]]:
    """The refusal rows of NOT_DRIVEN, as (tool, arguments, what, codes, the words that say the rule on either node
    class). Each input is refused before anything is written or dialled: an id that names nothing, a relay tool the
    route does not offer, and the sentinel's relay status (its card declares no relay)."""
    rows: List[Tuple[str, Dict[str, Any], str, Tuple[int, ...], Tuple[str, ...]]] = [
        ("theprotocol_finalizeFrameInvitation",
         {"invitation_id": _NO_ID, "approver_trust_domain": "phase6.invalid",
          "approver_bundle_endpoint_url": "https://phase6.invalid/bundle", "approver_name": "phase6",
          "approver_bundle_pem": "phase6-not-a-bundle-pem", "nonce_echo": "0" * 32},
         "an invitation that does not exist", (404,), ("invitation not found",)),
        ("theprotocol_approveDisputeSettlement", {"settlement_id": _NO_ID}, "a settlement that does not exist", (404,),
         ("settlement not found",)),
        ("theprotocol_rejectDisputeSettlement", {"settlement_id": _NO_ID}, "a settlement that does not exist", (404,),
         ("settlement not found",)),
        ("theprotocol_getFederationDisputeSettlement", {"settlement_id": _NO_ID}, "a settlement that does not exist",
         (404,), ("not found",)),
        ("theprotocol_getOperatorMyLifecycle", {}, "a developer with no operator application", (404,),
         ("no operator application found",)),
    ]
    sentinel = str(getattr(bag, "sentinel_did", "") or "")
    if sentinel:
        rows += [
            # a frame's sentinel card declares http (the route's https precondition, 422); an operator's its own public
            # page, which answers the relay path, but not as a relay (502); an agent declaring no relay at all, 404
            ("theprotocol_getRelayStatus", {"agent_did": sentinel}, "an agent with no relay", (404, 422, 502),
             ("no relay configured", "agent endpoint must be https", "not as a relay")),
            ("theprotocol_relayAction",
             {"agent_did": sentinel, "action_payload": {"tool": "relay_phase6", "arguments": {}}},
             "a relay tool the route does not offer", (400,), ("invalid relay tool",)),
        ]
    return rows


async def lifecycle_earned_by_design(rpc: RpcCall, parse: ParseResult, bag: Any, outcomes: Dict[str, dict]) -> None:
    """Each tool whose success no MCP caller can reach is NOT MEASURED on its own row, with the reason; the old
    safe-path steps keep its refusal as a refusal row. The two public federation reads (getFederationPolicyCompliance,
    listFederationRegistryCards) are among them since V0640, their 401 a refusal row here (before, their contracts'
    rows read "refusal only", the router's generic sentence, in the History). A tool held back on purpose says so where
    its switch is on."""
    for tool, tier, why in BY_DESIGN:
        ef.unmeasured(outcomes, tool, tier, why)
    cfg = await _config(rpc, parse, bag)
    for tool, tier, switch, why in HELD_BACK:
        if cfg.get(switch) is True:
            ef.unmeasured(outcomes, tool, tier, why)
    for tool, tier, why in NEEDS_PEER:
        ef.unmeasured(outcomes, tool, tier, why)
    for tool, tier, why in NOT_DRIVEN:
        ef.unmeasured(outcomes, tool, tier, why)
    for tool, args, what, codes, words in not_driven_refusals(bag):
        await ef.refusal_step(rpc, parse, tool, "3", args, bag.developer_jwt, outcomes, what, codes=codes, text=words)
    # an agent's federation vote counts only where agents' locked units decide federation proposals (no ballots, lock
    # mode); where registries decide by ballot, or votes count by membership, the route answers 409 to every agent
    ballots, members = cfg.get("federation_ballot_mode") is True, cfg.get("governance_weight_mode") == "member"
    if ballots or members:
        ef.unmeasured(outcomes, "theprotocol_federationVoteProposal", "2",
                      "an agent votes in a federation proposal only where agents' locked units decide it; here "
                      + ("registries decide by one ballot each (FEDERATION_BALLOT_MODE)" if ballots else
                         "votes count by membership (GOVERNANCE_WEIGHT_MODE=member)")
                      + ", so the route answers 409 to every agent by design (a member votes on the linked local "
                        "proposal). Its refusal is a refusal row")
        await ef.refusal_step(rpc, parse, "theprotocol_federationVoteProposal", "2",
                              {"agent_jwt": bag.sentinel_jwt, "proposal_id": str(uuid.uuid4()), "vote": "FOR"},
                              bag.developer_jwt, outcomes, "an agent's vote where registries or members decide",
                              codes=(409,), text="ballot", permission_first_unmeasured=True)
    await ef.refusal_step(rpc, parse, "theprotocol_guildCrossRegistryBid", "2",
                          {"agent_jwt": bag.sentinel_jwt, "target_registry_url": "https://phase5-no-such-peer.invalid",
                           "order_id": "1"}, bag.developer_jwt, outcomes, "a bid without a price", codes=(400,),
                          text="price is required")
    for tool in PEER_ONLY_READS:
        await ef.refusal_step(rpc, parse, tool, "1", {}, bag.developer_jwt, outcomes,
                              "a caller without a federation peer's identity", codes=(401,),
                              text="federation authentication required")
    for tool, args in PEER_ONLY_DEV_TOOLS:
        await ef.refusal_step(rpc, parse, tool, "3", dict(args), bag.developer_jwt, outcomes,
                              "a caller without a federation peer's identity", codes=(401,),
                              text="federation authentication required")
    # §MCPTEST30 (V0640): where agents' locked units decide federation proposals (neither ballots nor members), the vote
    # needs a federation proposal no run can hold: raising one (federationProposeRaise) elevates a PASSED local proposal
    # to every frame of the federation, which no tester does. aa's pair nt261024x5a read it "refusal only" (a vote on a
    # made-up proposal, 400 "Federation proposal not found")
    if not (ballots or members):
        ef.unmeasured(outcomes, "theprotocol_federationVoteProposal", "2",
                      "an agent votes in a federation proposal where agents' locked units decide it, as here, but "
                      "no run can hold one: raising a federation proposal (federationProposeRaise) elevates a passed "
                      "local proposal to every frame of the federation, which no tester does. Its refusal is a "
                      "refusal row")
        await ef.refusal_step(rpc, parse, "theprotocol_federationVoteProposal", "2",
                              {"agent_jwt": bag.sentinel_jwt, "proposal_id": str(uuid.uuid4()), "vote": "FOR"},
                              bag.developer_jwt, outcomes,
                              "an agent's vote on a federation proposal that does not exist", codes=(400, 404),
                              text="not found")


# "needs" (§MCPTEST30 V0637): what a lifecycle takes beyond the target's two MCP bridges; a run that cannot give it
# (test_flow_mcp_lifecycle.operator_lifecycles) does not run it and says why. "target_db": _db_one or _db_write, the
# target's database (a cloud operator's since V0638, in its own database container); "peer": _Peer, the target's
# second frame (API_TEST_FED_B_*), which a cloud operator does not have.
LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earned_contracts",          "runner": lifecycle_earned_contracts},
    {"name": "earned_engagement",         "runner": lifecycle_earned_engagement},
    {"name": "earned_disputes",           "runner": lifecycle_earned_disputes},
    {"name": "earned_reputation_signals", "runner": lifecycle_earned_reputation_signals},
    {"name": "earned_teg_attestation",    "runner": lifecycle_earned_teg_attestation},
    {"name": "earned_staking",            "runner": lifecycle_earned_staking},
    {"name": "earned_bond",               "runner": lifecycle_earned_bond},
    {"name": "earned_tally",              "runner": lifecycle_earned_tally},
    {"name": "earned_public_reads",       "runner": lifecycle_earned_public_reads, "needs": ("target_db",)},
    {"name": "earned_auth_chain",         "runner": lifecycle_earned_auth_chain, "needs": ("target_db",)},
    {"name": "earned_forge_eval",         "runner": lifecycle_earned_forge_eval},
    {"name": "earned_by_design",          "runner": lifecycle_earned_by_design},
    {"name": "earned_guild_cross_registry", "runner": lifecycle_earned_guild_cross_registry,
     "needs": ("target_db", "peer")},
    {"name": "earned_guild_local",        "runner": lifecycle_earned_guild_local},
    {"name": "earned_system_transfer",    "runner": lifecycle_earned_system_transfer},
    {"name": "earned_onboard_bundle",     "runner": lifecycle_earned_onboard_bundle},
]
