"""§MCPTEST30 (V0649): the admin tools a run drives only where its target is torn down after the run (agentvault2-d3,
2026-10-31; his words in d3's session that morning: "continue with big batch of tester improvements before proofing
whole image", and step 2 of sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md, where his reading of a pass
on a refusal alone is "completly cheated").

A target says it is one with MCP_TESTER_EPHEMERAL_TARGET=true in its registry's environment: the two frames of the
nightly pair and of every proof pair carry it (the stack's scripts/nightly/nightly_pair.py, NIGHTLY_FLAGS), and both
are torn down after their runs. A standing frame (the sandbox, production) never carries it; there every step below is
NOT MEASURED, named, and nothing is asked of the frame. The flag is read in the process that runs the flow, which is
the target's own registry (the console starts a run through the target's /admin/api-test/test-flow), so a flow run
anywhere else reads it unset: the safe answer.

  licences   a federation licence of the run's own, for a licensee that cannot exist (operator_name
             mcp-earn-licence-<tag>, operator_did did:theprotocol:mcp-earn-licence-<tag>), through every state its tools
             change, each read back by getFederationLicenseDetail:
               generateFederationLicense   active (the key is in the answer once: a row's excerpt redacts any key's
                                           value, result_excerpt, and the lifecycle reads nothing of it)
               suspendFederationLicense    suspended
               reinstateFederationLicense  active
               revokeFederationLicense     revoked, with the run's reason
               deleteFederationLicense     gone: the detail answers 404 and listFederationLicenses no longer names it
             A licence left by a step that failed is deleted at the end, whatever happened.
             Why only there: a licence is a credential the frame's event store honours; a suspension and a revocation go
             out to the frame's peers (the cross-frame replicator) and to its TEG's partner reactor; and a deleted
             licence leaves the store's row closed as revoked (the store has no deleted state), one more row a run on a
             standing frame.

  peers      (V0650, tester batch 1 item 1b, Guild order gwo_2015b757c94ce69138500df6) a peer registry row of the run's
             own, for a network that cannot exist (registry_name mcp-earn-peer-<tag>, its URL on the reserved .invalid
             TLD), with a policy built from the target's own locked and bounded parameters
             (core/base_network_params.py) and checked first by validateFederationPolicy (a dry run, no row). Each step
             is read back by getAdmissionStatus (the admission id is the compliance record) and, from quarantine on,
             checked for its event on the ledger:
               federationRequestAdmission   pending: a PeerRegistry row in PENDING_APPROVAL and its compliance record
               quarantineRegistry           quarantined, with the run's reason (RegistryQuarantined)
               liftQuarantine               federated again, with the admission's policy hash (RegistryQuarantineLifted)
               federationPolicyUpdateRequest  its stored policy, one bounded parameter moved inside its bounds (validated
                                            first): auto-approved, the admission's policy hash now the new policy's
                                            (FederationPolicyUpdated; V0650, tester batch 1 item 1b)
               blacklistRegistry            blacklisted, the row REJECTED (RegistryBlacklisted)
             The row is never ACTIVE (completeAdmission is not run here), so the registry-card fan-out never exports it
             to the pair's other frame while the suites run, and nothing dials its address. A row left by a step that
             failed is blacklisted at the end, whatever happened: the closed state (no route removes a peer row).
             Why only there: no route removes a peer registry row, so a run on a standing frame would leave one row and
             one compliance record per run; a quarantine sends the registry's operators a critical notice
             (registry.quarantined) and every roll driver refuses while one is held.

  value      (V0650, tester batch 1 item 1a, the same order) units moved by hand to and from an agent of the run's own
             (Throwaways), funded first with 1 unit from the treasury (fund-agent, the canonical rail: it moves units,
             it creates none). Each step is read back twice: the registry's balance (getBatchAgentBalances, as its
             owner) AND the ledger's own projection of it (adminQueryEventStore /api/v1/projections/balance/<did>,
             refresh): a move the registry shows and the event store never recorded is the drift a delta of 0.0 cannot
             see (CLAUDE.md PART 4):
               tegTreasuryReceive           1 unit back to the treasury (TreasurySlashReceived)
               distributeFromFeeCollector   0.01 from the fee account to the agent, only where the fee account holds it
             What the agent holds at the end goes back to the treasury, and the agent and its developer are removed
             (Throwaways.close). tegTreasuryIssue is not run, here or anywhere: minting is never automated (his decision
             D9), so its row keeps that reason (the by-design reasons table). Why only there: a payout from the fee account is
             paid out of what the frame's agents paid in fees; the supply stays whole (the pair proof reads both frames'
             supply audit after the suites).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, effect, effect_name, effect_unmeasured, lc)

EPHEMERAL_ENV = "MCP_TESTER_EPHEMERAL_TARGET"
GENERATE = "theprotocol_generateFederationLicense"
SUSPEND = "theprotocol_suspendFederationLicense"
REINSTATE = "theprotocol_reinstateFederationLicense"
REVOKE = "theprotocol_revokeFederationLicense"
DELETE = "theprotocol_deleteFederationLicense"
DETAIL = "theprotocol_getFederationLicenseDetail"
LIST = "theprotocol_listFederationLicenses"
LICENCE_TOOLS = (GENERATE, SUSPEND, REINSTATE, REVOKE, DELETE)
REVOKE_REASON = "MCP tester: a licence of the run's own, revoked by its run"
NOT_EPHEMERAL = (f"the run acts on a frame's federation licences only where its target is torn down after the run "
                 f"({EPHEMERAL_ENV}=true: the nightly and proof pairs); on a standing frame a licence leaves its event "
                 f"store row and its peers' events behind")


ADMIT = "theprotocol_federationRequestAdmission"
QUARANTINE = "theprotocol_quarantineRegistry"
LIFT = "theprotocol_liftQuarantine"
BLACKLIST = "theprotocol_blacklistRegistry"
POLICY_UPDATE = "theprotocol_federationPolicyUpdateRequest"
VALIDATE = "theprotocol_validateFederationPolicy"
ADMISSION = "theprotocol_getAdmissionStatus"
PEER_TOOLS = (ADMIT, QUARANTINE, LIFT, POLICY_UPDATE, BLACKLIST)
QUARANTINE_REASON = "MCP tester: a peer row of the run's own, quarantined by its run"
BLACKLIST_REASON = "MCP tester: a peer row of the run's own, closed by its run"
NOT_EPHEMERAL_PEERS = (f"the run plants a peer registry row of its own only where its target is torn down after the run "
                       f"({EPHEMERAL_ENV}=true: the nightly and proof pairs); on a standing frame the row and its "
                       f"compliance record would stay (no route removes a peer row)")


RECEIVE = "theprotocol_tegTreasuryReceive"
DISTRIBUTE = "theprotocol_distributeFromFeeCollector"
FEE_INFO = "theprotocol_getFeeCollectorInfo"
ES_QUERY = "theprotocol_adminQueryEventStore"
BALANCES = "theprotocol_getBatchAgentBalances"
FUND = "theprotocol_adminRequest"   # POST /api/v1/teg/treasury/fund-agent: the setup, recorded on no row
VALUE_TOOLS = (RECEIVE, DISTRIBUTE)
VALUE_REASON = "mcp_tester_ephemeral"
ONE = Decimal("1")
FEE_UNIT = Decimal("0.01")
NOT_EPHEMERAL_VALUE = (f"the run returns and pays out units by hand only where its target is torn down after the run "
                       f"({EPHEMERAL_ENV}=true: the nightly and proof pairs); on a standing frame a payout spends the "
                       f"fees its agents paid")


def ephemeral_target() -> bool:
    """True where the registry running this flow says it is torn down after the run."""
    return str(os.environ.get(EPHEMERAL_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


async def _admin(bag: Any, parse: Any, tool: str, args: Dict[str, Any]) -> Tuple[bool, Any, str]:
    """An admin read or clean-up that records no row: (ok, the answer as parsed, the code)."""
    ok, body, code = await bag.rpc_admin(tool, args, jwt=bag.developer_jwt, timeout=30)
    return bool(ok), (parse(body) if isinstance(body, dict) else {}), str(code)


def _status(want: str) -> Callable[[Any], Optional[str]]:
    def check(a: Any) -> Optional[str]:
        got = a.get("status") if isinstance(a, dict) else None
        return None if str(got or "").lower() == want else f"the answer reads status={got!r}, not {want!r}"
    return check


def _listed_ids(v: Any) -> Optional[List[str]]:
    """The licence ids a list answer names, or None when the answer is no list at all (unreadable, never 'empty')."""
    rows = v if isinstance(v, list) else None
    if rows is None and isinstance(v, dict):
        for k in ("items", "licenses", "licences", "results", "data"):
            if isinstance(v.get(k), list):
                rows = v[k]
                break
    if rows is None:
        return None
    return [str(r.get("id") or r.get("license_id")) for r in rows if isinstance(r, dict)]


def _gone(ok: bool, answer: Any, code: str) -> bool:
    text = answer.get("_text", "") if isinstance(answer, dict) else ""
    return not ok and (code == "404" or "HTTP 404" in str(text) or "not found" in str(text).lower())


async def _read_back(bag: Any, parse: Any, outcomes: Dict[str, dict], tool: str, lid: str, want: str,
                     extra: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None) -> None:
    """The detail must read the state `tool` answered it put the licence in; anything else downgrades its row."""
    name = effect_name(tool)
    row = outcomes.get(name)
    if not (row and row.get("healthy")):
        return
    ok, a, code = await _admin(bag, parse, DETAIL, {"license_id": lid})
    got = a.get("status") if ok and isinstance(a, dict) else None
    why = None
    if not ok:
        why = f"getFederationLicenseDetail answered HTTP {code} for the licence afterwards"
    elif str(got or "").lower() != want:
        why = f"getFederationLicenseDetail reads status={got!r} afterwards, not {want!r}"
    elif extra is not None:
        why = extra(a)
    if why:
        lc()._bugfind(outcomes, name, "admin_effect", f"{tool.replace('theprotocol_', '')}: {why}")


async def lifecycle_earn_ephemeral_licences(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """A federation licence of the run's own, through every state (the module docstring)."""
    if not ephemeral_target():
        for tool in LICENCE_TOOLS:
            effect_unmeasured(outcomes, tool, NOT_EPHEMERAL)
        return
    if getattr(bag, "rpc_admin", None) is None:
        for tool in LICENCE_TOOLS:
            effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    tag = f"{int(time.time())}-{secrets.token_hex(3)}"
    lid: Optional[str] = None
    deleted = False
    try:
        ok, made = await effect(bag, parse, GENERATE, {
            "operator_name": f"mcp-earn-licence-{tag}", "operator_did": f"did:theprotocol:mcp-earn-licence-{tag}",
            "licensee_type": "operator", "federation_tier": "standard", "max_agents": 1, "max_events_per_minute": 1,
        }, outcomes, check=_status("active"))
        lid = str(made.get("license_id") or made.get("id") or "") if ok and isinstance(made, dict) else ""
        if not lid:
            if ok:
                lc()._bugfind(outcomes, effect_name(GENERATE), "admin_effect",
                              "generateFederationLicense answered 2xx without a license_id")
            for tool in LICENCE_TOOLS[1:]:
                effect_unmeasured(outcomes, tool, "no licence of the run's own could be generated")
            return
        await _read_back(bag, parse, outcomes, GENERATE, lid, "active")
        for tool, args, want in (
                (SUSPEND, {"license_id": lid, "reason": "MCP tester: a licence of the run's own"}, "suspended"),
                (REINSTATE, {"license_id": lid}, "active")):
            await effect(bag, parse, tool, args, outcomes, check=_status(want))
            await _read_back(bag, parse, outcomes, tool, lid, want)
        await effect(bag, parse, REVOKE, {"license_id": lid, "reason": REVOKE_REASON}, outcomes,
                     check=_status("revoked"))
        await _read_back(bag, parse, outcomes, REVOKE, lid, "revoked",
                         extra=lambda a: None if a.get("revoked_reason") == REVOKE_REASON
                         else f"the revoked licence reads revoked_reason={a.get('revoked_reason')!r}")
        ok_d, _ = await effect(bag, parse, DELETE, {"license_id": lid}, outcomes)
        if ok_d:
            deleted = True
            ok_g, a_g, code_g = await _admin(bag, parse, DETAIL, {"license_id": lid})
            ok_l, a_l, code_l = await _admin(bag, parse, LIST, {})
            ids = _listed_ids(a_l) if ok_l else None
            if not _gone(ok_g, a_g, code_g):
                lc()._bugfind(outcomes, effect_name(DELETE), "admin_effect",
                              f"deleteFederationLicense: getFederationLicenseDetail answered HTTP {code_g} for the "
                              f"deleted licence, not 404")
            elif ids is None:
                lc()._bugfind(outcomes, effect_name(DELETE), "admin_effect",
                              f"deleteFederationLicense: listFederationLicenses could not be read afterwards "
                              f"(HTTP {code_l}), so the deletion is not shown")
            elif lid in ids:
                lc()._bugfind(outcomes, effect_name(DELETE), "admin_effect",
                              "deleteFederationLicense: listFederationLicenses still names the deleted licence")
    finally:
        if lid and not deleted:
            # never leave a licence of the run's own behind, in whatever state a failed step left it
            await _admin(bag, parse, DELETE, {"license_id": lid})


def compliant_policy() -> Dict[str, Any]:
    """A federation policy the target's own validator admits: every locked parameter at its value, every bounded one
    inside its bounds (the middle, or the one bound there is), and the escalation floor the validator asks for (a
    level-1 slash of at least 5 %, a level 4 that suspends). Built from the target's tables, so it follows them."""
    from agentvault_registry.core.base_network_params import BOUNDED_PARAMS, LOCKED_PARAMS
    policy: Dict[str, Any] = {}

    def put(path: str, value: Any) -> None:
        cur = policy
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    for path, value in LOCKED_PARAMS.items():
        put(path, value)
    for path, b in BOUNDED_PARAMS.items():
        lo, hi = b.get("min"), b.get("max")
        put(path, (lo + hi) / 2 if lo is not None and hi is not None else (lo if lo is not None else hi))
    put("dispute_escalation.levels", {"1": {"slash_percent": 5}, "4": {"action_types": ["suspend"]}})
    return policy


def moved_policy(policy: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """`policy` with one bounded parameter moved from the middle of its bounds to its quarter point: a change inside the
    bounds that no locked parameter takes part in. (the new policy, the path moved); (a copy, None) where no bounded
    parameter has two bounds apart."""
    from agentvault_registry.core.base_network_params import BOUNDED_PARAMS
    new = json.loads(json.dumps(policy))
    for path, b in sorted(BOUNDED_PARAMS.items()):
        lo, hi = b.get("min"), b.get("max")
        if lo is None or hi is None or lo == hi:
            continue
        cur = new
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = lo + (hi - lo) / 4
        return new, path
    return new, None


def _policy_updated(old_hash: str) -> Callable[[Any], Optional[str]]:
    def check(a: Any) -> Optional[str]:
        a = a if isinstance(a, dict) else {}
        new = a.get("new_policy_hash")
        if str(a.get("status")) != "auto_approved" or not new or new == old_hash:
            return (f"the answer reads status={a.get('status')!r}, new_policy_hash "
                    + ("unchanged" if new == old_hash else repr(new)))
        return None
    return check


def _fed_status(want: str) -> Callable[[Any], Optional[str]]:
    def check(a: Any) -> Optional[str]:
        got = a.get("federation_status") if isinstance(a, dict) else None
        return None if str(got or "").lower() == want else f"the answer reads federation_status={got!r}, not {want!r}"
    return check


def _admitted(a: Any) -> Optional[str]:
    if not isinstance(a, dict):
        return "the answer is no object"
    if str(a.get("status") or "").lower() != "pending_approval":
        return f"the answer reads status={a.get('status')!r}, not 'pending_approval'"
    if not a.get("admission_id") or not a.get("peer_registry_id"):
        return "the answer carries no admission_id or peer_registry_id"
    return None


async def _admission_read_back(bag: Any, parse: Any, outcomes: Dict[str, dict], tool: str, aid: str, want: str,
                               extra: Optional[Callable[[Dict[str, Any]], Optional[str]]] = None) -> None:
    """getAdmissionStatus must read the state `tool` answered it put the row in; anything else downgrades its row."""
    name = effect_name(tool)
    row = outcomes.get(name)
    if not (row and row.get("healthy")):
        return
    ok, a, code = await _admin(bag, parse, ADMISSION, {"admission_id": aid})
    got = a.get("federation_status") if ok and isinstance(a, dict) else None
    why = None
    if not ok:
        why = f"getAdmissionStatus answered HTTP {code} for the run's admission afterwards"
    elif str(got or "").lower() != want:
        why = f"getAdmissionStatus reads federation_status={got!r} afterwards, not {want!r}"
    elif extra is not None:
        why = extra(a)
    if why:
        lc()._bugfind(outcomes, name, "admin_effect", f"{tool.replace('theprotocol_', '')}: {why}")


async def _policy_update(bag: Any, parse: Any, outcomes: Dict[str, dict], aid: str, name: str, policy: Dict[str, Any],
                         phash: str) -> None:
    """The run's own row, federated: its stored policy updated through the admin route, read back by its hash."""
    ok_a, a, code_a = await _admin(bag, parse, ADMISSION, {"admission_id": aid})
    state = a.get("federation_status") if ok_a and isinstance(a, dict) else None
    if state not in ("federated", "soft_quarantined"):
        return effect_unmeasured(outcomes, POLICY_UPDATE, f"the run's own peer row reads federation_status={state!r} "
                                                          f"(HTTP {code_a}), and an update is allowed only while it is "
                                                          f"federated")
    proposed, moved = moved_policy(policy)
    ok_v, v, code_v = await _admin(bag, parse, VALIDATE, {"policy": proposed}) if moved else (False, {}, "-")
    if not (moved and ok_v and isinstance(v, dict) and v.get("valid") is True):
        return effect_unmeasured(outcomes, POLICY_UPDATE, "no bounded parameter has two bounds apart" if not moved else
                                 f"the moved policy ({moved}) did not validate on the target (HTTP {code_v})")
    ok, upd = await effect(bag, parse, POLICY_UPDATE, {
        "peer_did": f"did:theprotocol:{name}", "proposed_policy_json": proposed,
        "change_summary": f"The MCP tester moves {moved} of its own peer row inside its bounds."}, outcomes,
        check=_policy_updated(phash), expect_events=["FederationPolicyUpdated"])
    if ok:
        new_hash = upd.get("new_policy_hash")
        await _admission_read_back(bag, parse, outcomes, POLICY_UPDATE, aid, "federated",
                                   extra=lambda a: None if a.get("policy_hash") == new_hash
                                   else f"getAdmissionStatus reads policy_hash={a.get('policy_hash')!r}, not the "
                                        f"updated policy's")


async def lifecycle_earn_ephemeral_peers(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """A peer registry row of the run's own, PENDING_APPROVAL and never ACTIVE, through every state the enforcement
    tools give it (the module docstring)."""
    if not ephemeral_target():
        for tool in PEER_TOOLS:
            effect_unmeasured(outcomes, tool, NOT_EPHEMERAL_PEERS)
        return
    if getattr(bag, "rpc_admin", None) is None:
        for tool in PEER_TOOLS:
            effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    policy = compliant_policy()
    ok_v, v, code_v = await _admin(bag, parse, VALIDATE, {"policy": policy})
    if not (ok_v and isinstance(v, dict) and v.get("valid") is True):
        found = [x.get("path") for x in (v.get("violations") or []) if isinstance(x, dict)] if isinstance(v, dict) else []
        for tool in PEER_TOOLS:
            effect_unmeasured(outcomes, tool, f"the run's own policy did not validate on the target "
                                              f"(validateFederationPolicy HTTP {code_v}"
                                              + (f", violations {found[:5]}" if found else "") + ")")
        return
    name = f"mcp-earn-peer-{int(time.time())}-{secrets.token_hex(3)}"
    pid: Optional[str] = None
    closed = False
    try:
        ok, made = await effect(bag, parse, ADMIT, {
            "registry_name": name, "registry_operator_did": f"did:theprotocol:{name}",
            "registry_public_url": f"https://{name}.invalid", "admin_contact_email": f"{name}@example.invalid",
            "policy_json": policy,
        }, outcomes, check=_admitted)
        aid = str(made.get("admission_id") or "") if ok and isinstance(made, dict) else ""
        pid = str(made.get("peer_registry_id") or "") if ok and isinstance(made, dict) else ""
        phash = str(made.get("policy_hash") or "") if ok and isinstance(made, dict) else ""
        if not (aid and pid and phash):
            if ok:
                lc()._bugfind(outcomes, effect_name(ADMIT), "admin_effect",
                              "federationRequestAdmission answered 2xx without an admission_id, a peer_registry_id or "
                              "a policy_hash")
            for tool in PEER_TOOLS[1:]:
                effect_unmeasured(outcomes, tool, "no peer row of the run's own could be admitted")
            return
        await _admission_read_back(bag, parse, outcomes, ADMIT, aid, "pending",
                                   extra=lambda a: None if str(a.get("peer_registry_id")) == pid
                                   else f"the admission names peer {a.get('peer_registry_id')!r}, not {pid!r}")
        await effect(bag, parse, QUARANTINE, {"peer_id": pid, "reason": QUARANTINE_REASON, "grace_hours": 1}, outcomes,
                     check=_fed_status("quarantined"), expect_events=["RegistryQuarantined"])
        await _admission_read_back(bag, parse, outcomes, QUARANTINE, aid, "quarantined",
                                   extra=lambda a: None if a.get("quarantine_reason") == QUARANTINE_REASON
                                   else f"the quarantined row reads quarantine_reason={a.get('quarantine_reason')!r}")
        await effect(bag, parse, LIFT, {"peer_id": pid, "new_policy_hash": phash}, outcomes,
                     check=_fed_status("federated"), expect_events=["RegistryQuarantineLifted"])
        await _admission_read_back(bag, parse, outcomes, LIFT, aid, "federated")
        await _policy_update(bag, parse, outcomes, aid, name, policy, phash)
        ok_b, _ = await effect(bag, parse, BLACKLIST, {"peer_id": pid, "reason": BLACKLIST_REASON}, outcomes,
                               check=_fed_status("blacklisted"), expect_events=["RegistryBlacklisted"])
        closed = bool(ok_b)
        await _admission_read_back(bag, parse, outcomes, BLACKLIST, aid, "blacklisted")
    finally:
        if pid and not closed:
            # never leave a peer row of the run's own pending, quarantined or federated: blacklisted is its closed state
            await _admin(bag, parse, BLACKLIST, {"peer_id": pid, "reason": BLACKLIST_REASON})


def _dec(v: Any) -> Optional[Decimal]:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


async def _held(rpc: Any, parse: Any, bag: Any, did: str, owner_jwt: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """(the registry's balance of `did`, the ledger's projection of it); None where a read failed (never a zero)."""
    ok, body, _code = await rpc(BALANCES, {"agent_dids": [did]}, jwt=owner_jwt, timeout=20)
    inner = parse(body) if isinstance(body, dict) else {}
    entry = (inner.get("balances") or {}).get(did) if isinstance(inner, dict) else None
    reg = _dec(entry.get("balance")) if ok and isinstance(entry, dict) and not entry.get("error") else None
    ok2, a, _c2 = await _admin(bag, parse, ES_QUERY, {"path": f"/api/v1/projections/balance/{did}",
                                                     "params": {"refresh": "true"}})
    inner2 = a.get("response") if isinstance(a, dict) and isinstance(a.get("response"), dict) else a
    led = _dec(inner2.get("liquid_balance")) if ok2 and isinstance(inner2, dict) else None
    return reg, led


async def _moved(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], tool: str, did: str, owner_jwt: str,
                 before: Tuple[Optional[Decimal], Optional[Decimal]], delta: Decimal, tries: int = 6,
                 pause: float = 4.0) -> None:
    """Both reads must show `delta` on `did` after `tool`; the ledger's projection may lag a few seconds (it is read
    again). A read that failed before or after is said, never counted as a move."""
    name = effect_name(tool)
    row = outcomes.get(name)
    if not (row and row.get("healthy")):
        return
    reg0, led0 = before
    why = None
    for i in range(tries):
        reg1, led1 = await _held(rpc, parse, bag, did, owner_jwt)
        if None in (reg0, led0, reg1, led1):
            why = (f"a balance could not be read (registry {reg0} -> {reg1}, ledger {led0} -> {led1}), so the move "
                   f"is not shown")
        elif abs((reg1 - reg0) - delta) > Decimal("0.000001"):
            why = f"the registry's balance moved {reg1 - reg0}, not {delta}"
        elif abs((led1 - led0) - delta) > Decimal("0.000001"):
            why = (f"the registry's balance moved {delta}, but the ledger's projection moved {led1 - led0}: a move the "
                   f"event store did not record")
        else:
            row["read_back"] = f"the registry's balance and the ledger's projection both moved {delta}"
            return
        if i < tries - 1:
            await asyncio.sleep(pause)
    lc()._bugfind(outcomes, name, "admin_effect", f"{tool.replace('theprotocol_', '')}: {why}")


async def _fee_held(bag: Any, parse: Any) -> Optional[Decimal]:
    ok, a, _code = await _admin(bag, parse, FEE_INFO, {})
    if not ok or not isinstance(a, dict):
        return None
    for k in ("balance", "fee_collector_balance", "liquid_balance"):
        if a.get(k) is not None:
            return _dec(a.get(k))
    return None


async def lifecycle_earn_ephemeral_value(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """Units moved by hand to and from an agent of the run's own, each read back on the registry AND on the ledger's
    projection (the module docstring)."""
    if not ephemeral_target():
        for tool in VALUE_TOOLS:
            effect_unmeasured(outcomes, tool, NOT_EPHEMERAL_VALUE)
        return
    if getattr(bag, "rpc_admin", None) is None:
        for tool in VALUE_TOOLS:
            effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    tag = f"{int(time.time())}-{secrets.token_hex(3)}"
    t = Throwaways(rpc, parse, bag, "ephemeral-value")
    try:
        dev = await t.developer("ephemeral-value")
        ag = await t.agent(dev) if not dev.get("why") else dev
        if ag.get("why"):
            for tool in VALUE_TOOLS:
                effect_unmeasured(outcomes, tool, f"no agent of the run's own: {ag.get('why')}")
            return
        did, owner = ag["did"], ag["owner_jwt"]
        # the setup: 1 unit from the treasury, so the return below never depends on a genesis grant
        await _admin(bag, parse, FUND, {"method": "POST", "endpoint": "/api/v1/teg/treasury/fund-agent",
                                        "body": {"target_agent_did": did, "amount": "1", "reason": "admin_grant",
                                                 "reference_id": f"mcp-earn-fund-{tag}"}})
        before = await _held(rpc, parse, bag, did, owner)
        if before[0] is None or before[0] < ONE:
            effect_unmeasured(outcomes, RECEIVE, f"the run's agent holds {before[0]}, under the 1 unit the step returns")
        else:
            ok, _ = await effect(bag, parse, RECEIVE, {"source_agent_did": did, "amount": "1", "reason": VALUE_REASON,
                                                       "reference_id": f"mcp-earn-receive-{tag}"},
                                 outcomes, expect_events=["TreasurySlashReceived"])
            if ok:
                await _moved(rpc, parse, bag, outcomes, RECEIVE, did, owner, before, -ONE)
        fee = await _fee_held(bag, parse)
        if fee is None or fee < FEE_UNIT:
            effect_unmeasured(outcomes, DISTRIBUTE, f"this frame's fee account holds {fee} (read by getFeeCollectorInfo), "
                                                    f"under the {FEE_UNIT} the step pays out")
        else:
            before = await _held(rpc, parse, bag, did, owner)
            ok, _ = await effect(bag, parse, DISTRIBUTE, {"target_agent_did": did, "amount": str(FEE_UNIT),
                                                          "reason": "manual_payout",
                                                          "reference_id": f"mcp-earn-payout-{tag}"}, outcomes)
            if ok:
                await _moved(rpc, parse, bag, outcomes, DISTRIBUTE, did, owner, before, FEE_UNIT)
                after_fee = await _fee_held(bag, parse)
                row = outcomes.get(effect_name(DISTRIBUTE)) or {}
                if row.get("healthy") and (after_fee is None or abs((fee - after_fee) - FEE_UNIT) > Decimal("0.000001")):
                    # other agents pay fees beside the run, so only a fee account that did not fall is a finding
                    if after_fee is None or after_fee >= fee:
                        lc()._bugfind(outcomes, effect_name(DISTRIBUTE), "admin_effect",
                                      f"distributeFromFeeCollector: the fee account read {fee} before and {after_fee} "
                                      f"after paying {FEE_UNIT} out")
    finally:
        await t.close()


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_ephemeral_licences", "runner": lifecycle_earn_ephemeral_licences},
    {"name": "earn_ephemeral_peers", "runner": lifecycle_earn_ephemeral_peers},
    {"name": "earn_ephemeral_value", "runner": lifecycle_earn_ephemeral_value},
]
