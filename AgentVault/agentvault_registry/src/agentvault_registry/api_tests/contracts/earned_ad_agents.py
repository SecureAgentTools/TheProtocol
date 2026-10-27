"""§MCPTEST30 (V0636): the admin agent tools on the run's own agents (agentvault2-aa; step 2 of
sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md).

On V0635 each of these passed on one refusal: a 404 for `did:theprotocol:phase6-no-such-agent`. Here a throwaway
developer of this run owns three agents (the first holds the frame's grant for a developer's first agent; the second
and third hold nothing) and every tool does its job on one of them, through the admin bridge, with a read that shows
the effect (`admin_effect: <tool>`):

  credentials   rotateAgentCredentials: the old secret is refused afterwards and the new one gets a token
  signing key   rotateAgentSigningKey: the new kid is the current key, every older one expiring
  ownership     transferAgentOwnership: the agent's creator is the second developer of this run
  hard delete   deleteAdminAgent on the agent that holds nothing: the detail read answers 404 afterwards
  mTLS          forceMtlsEnroll, ironhandRevokeAgent, ironhandEnrollAgent: mtls_enabled reads each state
  SPIRE         deleteSpireOrphan on the entry the enrolment made: "deleted", and the agent is revoked after it
  card drift    refreshAgentCardDrift (a pull outcome for the card), forceRegisterAgentCard (flagged, its event)
  enforcement   suspendAgent and reinstateAgentEnforcement (status), pauseAgentPayouts and resumeAgentPayouts
                (rewards_paused_until), recordAgentOffense up to the level whose action waits for an administrator,
                then rejectPendingEnforcement and approvePendingEnforcement on those actions (getEnforcementPending)
  disputes      updateDisputeRuling on a dispute the third agent filed against the first: DISMISSED, read back by
                getDisputeById as the owner, and a second ruling refused 409; before the ruling,
                previewSlashReductionAttestation on it (it references no attestation: the factor is 1.0; a sandbox
                read with ZKP phase 3 on, NOT MEASURED, named, where the target has either off)
  stake         slashAgent of 1 unit the first agent locked for this (a burn of dust, on the run's own agent)
  policy        updateEnforcementPolicy writes the active policy back unchanged: a new version, the same rules

Not here, each for its own reason: acknowledgeAgentFlag (a flag is raised only by the card-drift and signature
reactors, never by a rail the run can call); blockFederationAgent, unblockFederationAgent, ironhandRegisterAgentProxy
and ironhandDeleteAgentProxy (their routes take only a peer registry's federation identity, which an admin's call
does not carry: each answers 401 "Federation authentication required" to the admin bridge).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts import mcp_switches as _switches
from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, effect, effect_name, effect_unmeasured, lc, refusal_step, said, step,
)

_TAG = "agent-admin"
ADMIN = "admin"


async def _admin_read(bag: Any, parse: Any, tool: str, args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    """An admin read through the admin bridge, recorded nowhere: (ok, answer, http code)."""
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return False, {}, ""
    ok, body, code = await rpc_admin(tool, args, jwt=bag.developer_jwt, timeout=20)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner if isinstance(inner, dict) else {}, str(code)


def _bug(outcomes: Dict[str, dict], tool: str, why: str) -> None:
    """The `admin_effect: <tool>` row fails with a BUG-FIND naming what the read showed."""
    lc()._bugfind(outcomes, effect_name(tool), "admin_effect", f"{tool.replace('theprotocol_', '')}: {why}")


def _reads(key: str, *want: Any):
    def check(answer: Dict[str, Any]) -> Optional[str]:
        return None if answer.get(key) in want else f"the answer reads {key}={answer.get(key)!r}, not {list(want)}"
    return check


async def _detail(bag: Any, parse: Any, did: str) -> Tuple[bool, Dict[str, Any], str]:
    return await _admin_read(bag, parse, "theprotocol_getAdminAgentDetail", {"agent_did": did})


async def _detail_shows(bag: Any, parse: Any, outcomes: Dict[str, dict], tool: str, did: str, key: str,
                        want: Any, *, present: Optional[bool] = None) -> None:
    """After a step that passed, the agent's admin detail must read `key` == `want` (or, with `present`, be set or
    unset); otherwise the step's row is a BUG-FIND."""
    row = outcomes.get(effect_name(tool))
    if not (row and row.get("healthy")):
        return
    ok, d, code = await _detail(bag, parse, did)
    if not ok:
        _bug(outcomes, tool, f"the agent's detail could not be read afterwards (HTTP {code})")
        return
    v = d.get(key)
    if present is not None:
        if bool(v) != present:
            _bug(outcomes, tool, f"the agent's detail reads {key}={v!r} afterwards")
    elif v != want:
        _bug(outcomes, tool, f"the agent's detail reads {key}={v!r} afterwards, not {want!r}")


ALL_TOOLS = (
    "theprotocol_rotateAgentCredentials", "theprotocol_rotateAgentSigningKey", "theprotocol_transferAgentOwnership",
    "theprotocol_deleteAdminAgent", "theprotocol_forceMtlsEnroll", "theprotocol_ironhandRevokeAgent",
    "theprotocol_ironhandEnrollAgent", "theprotocol_deleteSpireOrphan", "theprotocol_refreshAgentCardDrift",
    "theprotocol_forceRegisterAgentCard", "theprotocol_suspendAgent", "theprotocol_reinstateAgentEnforcement",
    "theprotocol_pauseAgentPayouts", "theprotocol_resumeAgentPayouts", "theprotocol_recordAgentOffense",
    "theprotocol_rejectPendingEnforcement", "theprotocol_approvePendingEnforcement", "theprotocol_updateDisputeRuling",
    "theprotocol_slashAgent", "theprotocol_updateEnforcementPolicy",
)


async def lifecycle_earn_agent_admin(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The admin agent tools, each on an agent of this run's own throwaway developer (the module docstring)."""
    if getattr(bag, "rpc_admin", None) is None:
        for t in ALL_TOOLS:
            effect_unmeasured(outcomes, t, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    t = Throwaways(rpc, parse, bag, _TAG)
    done: List[str] = []
    try:
        await _steps(rpc, parse, bag, outcomes, t, done)
    except Exception as e:                                             # noqa: BLE001 — a raise names every tool it left
        for tool in ALL_TOOLS:
            if effect_name(tool) not in outcomes:
                effect_unmeasured(outcomes, tool, f"the lifecycle raised {type(e).__name__}: {str(e)[:160]} before it "
                                                  f"reached this tool")
    finally:
        await t.close()


async def _steps(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], t: Throwaways, done: List[str]) -> None:
    dev = await t.developer(_TAG)
    first = await t.agent(dev, "a")
    if first.get("why"):
        for tool in ALL_TOOLS:
            effect_unmeasured(outcomes, tool, f"no agent of this run's own could be made: {first['why']}")
        return
    did = first["did"]

    # ── credentials ──────────────────────────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_rotateAgentCredentials"
    ok, ans = await effect(bag, parse, tool, {"agent_did": did}, outcomes,
                           check=lambda a: None if a.get("new_client_secret") and a.get("did") == did
                           else f"the answer carries no new secret for {did[-12:]} ({sorted(a)[:6]})")
    if ok:
        new_secret = ans.get("new_client_secret")
        okt, body, codet = await rpc("theprotocol_getAgentToken",
                                     {"client_id": first["client_id"], "client_secret": first["client_secret"]},
                                     jwt=first["owner_jwt"], timeout=20)
        if okt and (parse(body) or {}).get("access_token"):
            _bug(outcomes, tool, "the OLD secret still gets an agent token after the rotation")
        okn, body, coden = await rpc("theprotocol_getAgentToken",
                                     {"client_id": first["client_id"], "client_secret": new_secret},
                                     jwt=first["owner_jwt"], timeout=20)
        fresh = (parse(body) or {}).get("access_token") if okn else None
        if not fresh:
            _bug(outcomes, tool, f"the NEW secret gets no agent token (HTTP {coden})")
        else:
            first["client_secret"], first["agent_jwt"] = new_secret, fresh

    # ── signing key ──────────────────────────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_rotateAgentSigningKey"
    ok, ans = await effect(bag, parse, tool, {"agent_did": did}, outcomes,
                           check=lambda a: None if str(a.get("new_kid") or "").startswith(f"{did}#")
                           else f"the answer names no new kid of the agent ({a.get('new_kid')!r})")
    if ok:
        okk, keys, codek = await _admin_read(bag, parse, "theprotocol_getAdminAgentSigningKeys", {"agent_did": did})
        rows = keys.get("keys") if isinstance(keys.get("keys"), list) else []
        current = [k.get("kid") for k in rows if isinstance(k, dict) and k.get("is_current")]
        if not okk:
            _bug(outcomes, tool, f"the agent's signing keys could not be read afterwards (HTTP {codek})")
        elif current != [ans.get("new_kid")]:
            _bug(outcomes, tool, f"the current signing keys read {current}, not only {ans.get('new_kid')!r}")

    # ── mTLS: enrol, revoke, enrol again; the SPIRE entry removed as an orphan; revoked again ───────────────────
    tool = "theprotocol_forceMtlsEnroll"
    ok, _ = await effect(bag, parse, tool, {"agent_did": did}, outcomes, check=_reads("status", "enrolled"))
    await _detail_shows(bag, parse, outcomes, tool, did, "mtls_enabled", True)
    tool = "theprotocol_ironhandRevokeAgent"
    ok, _ = await effect(bag, parse, tool, {"agent_did": did}, outcomes, check=_reads("status", "revoked"))
    await _detail_shows(bag, parse, outcomes, tool, did, "mtls_enabled", False)
    tool = "theprotocol_ironhandEnrollAgent"
    ok, ans = await effect(bag, parse, tool, {"agent_did": did}, outcomes,
                           check=lambda a: None if a.get("status") == "enrolled" and str(a.get("spiffe_id") or "").startswith("spiffe://")
                           else f"the answer reads status={a.get('status')!r} spiffe_id={a.get('spiffe_id')!r}")
    await _detail_shows(bag, parse, outcomes, tool, did, "mtls_enabled", True)
    spiffe = ans.get("spiffe_id") if ok else None
    tool = "theprotocol_deleteSpireOrphan"
    if spiffe:
        await effect(bag, parse, tool, {"spiffe_id": spiffe}, outcomes, check=_reads("status", "deleted"))
        await refusal_step(bag.rpc_admin, parse, tool, ADMIN, {"spiffe_id": "spiffe://mcp-earn.invalid/service/x"},
                           bag.developer_jwt, outcomes, "a SPIFFE id that names no agent entry", codes=(400,),
                           text="agent entries")
    else:
        effect_unmeasured(outcomes, tool, "the enrolment named no SPIFFE id, so there was no entry of the run's own")
    # the agent's record still says enrolled; a revoke now clears it (its SPIRE delete finds nothing, as it should)
    await _admin_read(bag, parse, "theprotocol_ironhandRevokeAgent", {"agent_did": did})

    # ── the card ─────────────────────────────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_refreshAgentCardDrift"
    await effect(bag, parse, tool, {"did": did}, outcomes,
                 check=lambda a: None if a.get("agent_did") == did and "outcome" in a
                 else f"the answer names no pull outcome for the agent ({sorted(a)[:6]})")
    tool = "theprotocol_forceRegisterAgentCard"
    await effect(bag, parse, tool, {"did": did}, outcomes, check=_reads("flagged", True),
                 expect_events=["CommanderFlaggedDrift"])

    # ── suspension and the rewards hold ──────────────────────────────────────────────────────────────────────────
    tool = "theprotocol_suspendAgent"
    await effect(bag, parse, tool, {"agent_did": did, "reason": "MCP tester: its own agent, suspended to measure it"},
                 outcomes, check=_reads("enforcement_status", "suspended"))
    await _detail_shows(bag, parse, outcomes, tool, did, "status", "suspended")
    tool = "theprotocol_reinstateAgentEnforcement"
    await effect(bag, parse, tool, {"agent_did": did, "reason": "MCP tester: its own agent, reinstated"}, outcomes,
                 check=lambda a: None if a.get("enforcement_status") in ("active", None) and a.get("agent_did", did) == did
                 else f"the answer reads enforcement_status={a.get('enforcement_status')!r}")
    await _detail_shows(bag, parse, outcomes, tool, did, "status", "active")
    tool = "theprotocol_pauseAgentPayouts"
    await effect(bag, parse, tool, {"agent_did": did, "reason": "MCP tester: its own agent", "duration_days": 1},
                 outcomes, check=lambda a: None if a.get("rewards_paused_until") else "the answer sets no pause")
    await _detail_shows(bag, parse, outcomes, tool, did, "rewards_paused_until", None, present=True)
    tool = "theprotocol_resumeAgentPayouts"
    await effect(bag, parse, tool, {"agent_did": did}, outcomes,
                 check=lambda a: None if "rewards_paused_until" in a and a.get("rewards_paused_until") is None
                 else f"the answer reads rewards_paused_until={a.get('rewards_paused_until')!r}")
    await _detail_shows(bag, parse, outcomes, tool, did, "rewards_paused_until", None, present=False)

    # ── offenses, up to the level whose action waits for an administrator ────────────────────────────────────────
    await _offenses(bag, parse, outcomes, did)

    # ── a dispute between two agents of the run, ruled DISMISSED ─────────────────────────────────────────────────
    third = await t.agent(dev, "c")
    await _dispute(rpc, parse, bag, outcomes, did, third)

    # ── a stake of 1 unit, slashed ───────────────────────────────────────────────────────────────────────────────
    await _slash(rpc, parse, bag, outcomes, first)

    # ── the enforcement policy, written back unchanged ───────────────────────────────────────────────────────────
    await _policy_unchanged(bag, parse, outcomes)

    # ── ownership and the hard delete, on the second agent (it holds nothing) ───────────────────────────────────
    second = await t.agent(dev, "b")
    other = await t.developer(_TAG + "-new-owner")
    tool = "theprotocol_transferAgentOwnership"
    if second.get("why") or other.get("why"):
        why = second.get("why") or other.get("why")
        effect_unmeasured(outcomes, tool, f"no second agent or developer of the run's own: {why}")
        effect_unmeasured(outcomes, "theprotocol_deleteAdminAgent", f"no second agent of the run's own: {why}")
        return
    did2 = second["did"]
    ok, _ = await effect(bag, parse, tool, {"agent_did": did2, "new_creator_developer_id": other["developer_id"],
                                            "reason": "MCP tester: between two developers of its own"},
                         outcomes, check=_reads("status", "transferred"))
    await _detail_shows(bag, parse, outcomes, tool, did2, "creator_developer_id", other["developer_id"])
    if ok:
        t.owner_changed(did2, other["access_token"])
    await refusal_step(bag.rpc_admin, parse, tool, ADMIN,
                       {"agent_did": did2, "new_creator_developer_id": other["developer_id"],
                        "reason": "MCP tester: to the owner it already has"},
                       bag.developer_jwt, outcomes, "to the developer that already owns it", codes=(400,),
                       text="already owned")
    tool = "theprotocol_deleteAdminAgent"
    okd, d, coded = await _detail(bag, parse, did2)
    held = (float(d.get("liquid_balance") or 0), float(d.get("staked_balance") or 0)) if okd else None
    if held is None:
        effect_unmeasured(outcomes, tool, f"the second agent's detail could not be read (HTTP {coded})")
        return
    if held != (0.0, 0.0):
        effect_unmeasured(outcomes, tool, f"the second agent holds {held[0]} liquid and {held[1]} locked; a hard "
                                          f"delete refuses a balance, and the run moves none away")
        return
    await refusal_step(bag.rpc_admin, parse, tool, ADMIN,
                       {"agent_did": did2, "reason": "MCP tester: a confirmation that names another DID",
                        "confirm_did": did}, bag.developer_jwt, outcomes, "with a confirmation naming another agent",
                       codes=(400,), text="confirm_did")
    ok, _ = await effect(bag, parse, tool, {"agent_did": did2, "reason": "MCP tester: its own agent, removed",
                                            "confirm_did": did2}, outcomes,
                         check=lambda a: None if a.get("did", did2) == did2 else f"the answer names {a.get('did')!r}")
    if ok:
        t.forget_agent(did2)
        okg, _d, codeg = await _detail(bag, parse, did2)
        if okg or codeg != "404":
            _bug(outcomes, tool, f"the agent's detail still answers HTTP {codeg} after the hard delete")


async def _action_status(bag: Any, parse: Any, did: str, aid: str) -> Optional[str]:
    """The status getEnforcementAgentStatus reads for the agent's action `aid` (its ten newest), or None."""
    ok, ans, _code = await _admin_read(bag, parse, "theprotocol_getEnforcementAgentStatus", {"agent_did": did})
    rows = ans.get("recent_actions") if ok and isinstance(ans.get("recent_actions"), list) else []
    for r in rows:
        if isinstance(r, dict) and str(r.get("id")) == aid:
            return str(r.get("status"))
    return None


async def _offenses(bag: Any, parse: Any, outcomes: Dict[str, dict], did: str) -> None:
    """recordAgentOffense until an action waits for an administrator (the default policy's level 3), then that action
    rejected; one more offense (a rejected action does not count, so it waits again), then that one approved. With no
    disputed amount every action is a warning: nothing is slashed."""
    rec = "theprotocol_recordAgentOffense"
    pending: List[str] = []
    for n in range(1, 6):
        args = {"agent_did": did, "reference": f"mcp-earn-offense-{n}", "disputed_amount": 0}
        if n == 1:
            ok, ans = await effect(bag, parse, rec, args, outcomes,
                                   check=lambda a: None if a.get("action_id") and a.get("status") in ("executed", "pending_approval")
                                   else f"the answer reads action_id={a.get('action_id')!r} status={a.get('status')!r}")
            if not ok:
                break
        else:
            ok, ans, _c = await _admin_read(bag, parse, rec, args)
            if not ok:
                break
        if ans.get("status") == "pending_approval" and ans.get("action_id"):
            pending.append(str(ans["action_id"]))
            break
    for tool in ("theprotocol_rejectPendingEnforcement", "theprotocol_approvePendingEnforcement"):
        if not pending:
            effect_unmeasured(outcomes, tool, "no offense of the run's own agent waited for an administrator (this "
                                              "target's policy reviews no level the run reached)")
            continue
        aid = pending.pop()
        before = await _action_status(bag, parse, did, aid)
        if before != "pending_approval":
            _bug(outcomes, rec, f"the agent's enforcement status reads its action {aid} as {before!r}, not waiting")
        if tool.endswith("rejectPendingEnforcement"):
            await effect(bag, parse, tool, {"action_id": aid, "reason": "MCP tester: its own agent's warning"},
                         outcomes, check=_reads("status", "rejected"))
            ok, ans, _c = await _admin_read(bag, parse, rec, {"agent_did": did, "reference": "mcp-earn-offense-again",
                                                              "disputed_amount": 0})
            if ok and ans.get("status") == "pending_approval" and ans.get("action_id"):
                pending.append(str(ans["action_id"]))
        else:
            await effect(bag, parse, tool, {"action_id": aid}, outcomes, check=_reads("status", "executed"))
        after = await _action_status(bag, parse, did, aid)
        row = outcomes.get(effect_name(tool))
        want = "rejected" if tool.endswith("rejectPendingEnforcement") else "executed"
        if row and row.get("healthy") and after != want:
            _bug(outcomes, tool, f"the agent's enforcement status reads its action {aid} as {after!r}, not {want!r}")


async def _dispute(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], defendant: str,
                   complainant: Dict[str, Any]) -> None:
    tool = "theprotocol_updateDisputeRuling"
    if complainant.get("why"):
        effect_unmeasured(outcomes, tool, f"no second agent of the run's own to file the dispute: {complainant['why']}")
        outcomes[_PREVIEW] = lc()._not_measured(_PREVIEW, "3", "NOT MEASURED: no dispute of the run's own was filed")
        return
    ok, body, code = await rpc("theprotocol_submitDispute",
                               {"agent_jwt": complainant["agent_jwt"], "defendant_did": defendant,
                                "description": "MCP tester: between two agents of its own, ruled DISMISSED"},
                               jwt=complainant["owner_jwt"], timeout=30)
    filed = parse(body) if isinstance(body, dict) else {}
    dispute_id = (filed.get("id") or filed.get("dispute_id")) if ok and isinstance(filed, dict) else None
    if dispute_id is None:
        effect_unmeasured(outcomes, tool, f"the run's own dispute could not be filed (HTTP {code}: {said(filed)})")
        outcomes[_PREVIEW] = lc()._not_measured(_PREVIEW, "3", "NOT MEASURED: no dispute of the run's own was filed")
        return
    await _preview(rpc, parse, outcomes, int(dispute_id), defendant, complainant["owner_jwt"])
    ok, _ = await effect(bag, parse, tool, {"dispute_id": int(dispute_id), "ruling": "DISMISSED"}, outcomes)
    if not ok:
        return
    # getDisputeById, as the developer who owns both parties: the dispute is closed, DISMISSED
    await step(rpc, parse, "theprotocol_getDisputeById", "3", {"dispute_id": str(dispute_id)},
               complainant["owner_jwt"], outcomes, verify_against=effect_name(tool),
               verify_against_check=lambda a: None if str(a.get("ruling") or "").upper() == "DISMISSED"
               else f"getDisputeById reads ruling={a.get('ruling')!r} status={a.get('status')!r}")
    await refusal_step(bag.rpc_admin, parse, tool, ADMIN, {"dispute_id": int(dispute_id), "ruling": "DISMISSED"},
                       bag.developer_jwt, outcomes, "a second ruling on a closed dispute", codes=(409,),
                       text="already closed")


_PREVIEW = "theprotocol_previewSlashReductionAttestation"


async def _preview(rpc: Any, parse: Any, outcomes: Dict[str, dict], dispute_id: int, defendant: str, jwt: str) -> None:
    """The slash-reduction factor of the run's own dispute, computed and never applied: it references no attestation,
    so the factor is 1.0. The route serves a sandbox with ZKP phase 3 on (403 / 503 otherwise: NOT MEASURED, named)."""
    args = {"dispute_id": str(dispute_id)}
    ok, body, code = await rpc(_PREVIEW, args, jwt=jwt, timeout=20)
    if not ok and str(code) in ("403", "503"):
        why = said(parse(body) if isinstance(body, dict) else {})
        if "sandbox-only" in why.lower() or "zkp_phase_3" in why.lower():
            outcomes[_PREVIEW] = lc()._not_measured(_PREVIEW, "3", f"NOT MEASURED: the target serves no preview ({why})")
            return
    ok, got = await step(rpc, parse, _PREVIEW, "3", args, jwt, outcomes)
    if ok and (int(got.get("dispute_id") or 0) != dispute_id or got.get("defendant_did") != defendant
               or got.get("referenced_attestations_total") != 0 or float(got.get("slash_factor") or 0) != 1.0):
        lc()._bugfind(outcomes, _PREVIEW, "3",
                      f"previewSlashReductionAttestation: the preview reads dispute {got.get('dispute_id')!r}, "
                      f"factor {got.get('slash_factor')!r}, {got.get('referenced_attestations_total')!r} referenced, "
                      f"not the run's own dispute with none")


async def _slash(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], agent: Dict[str, Any]) -> None:
    tool = "theprotocol_slashAgent"
    if _switches.switched_off("theprotocol_lockUnits") is not None:
        effect_unmeasured(outcomes, tool, "locks are switched off on this target, so there is no lock to slash")
        return
    # the frame's minimum stake (10 units on the sandbox) from the first agent's grant; 1 unit of it is slashed
    ok, body, code = await rpc("theprotocol_lockUnits",
                               {"agent_jwt": agent["agent_jwt"], "amount": "10", "lock_period_days": 0},
                               jwt=agent["owner_jwt"], timeout=30)
    if not ok:
        effect_unmeasured(outcomes, tool, f"the run's own agent could not lock 10 units (HTTP {code}: "
                                          f"{said(parse(body) if isinstance(body, dict) else {})})")
        return
    okb, before, _c = await _detail(bag, parse, agent["did"])
    ok, _ = await effect(bag, parse, tool, {"agent_did": agent["did"], "amount": 1,
                                            "reason": "MCP tester: 1 of the 10 units its own agent locked for this"},
                         outcomes)
    if ok and okb:
        oka, after, _c = await _detail(bag, parse, agent["did"])
        if oka and float(after.get("staked_balance") or 0) >= float(before.get("staked_balance") or 0):
            _bug(outcomes, tool, f"the agent's locked balance reads {after.get('staked_balance')} after the slash, "
                                 f"as before it ({before.get('staked_balance')})")


async def _policy_unchanged(bag: Any, parse: Any, outcomes: Dict[str, dict]) -> None:
    """updateEnforcementPolicy with the active policy as it reads: a new version, nothing else changed."""
    tool = "theprotocol_updateEnforcementPolicy"
    ok, cur, code = await _admin_read(bag, parse, "theprotocol_getEnforcementPolicy", {})
    pj = cur.get("policy_json") if ok else None
    # §MCPTEST30 V0644 (agentvault2-66, 2026-10-26): an empty document is a policy row too (the frame runs the factory
    # default through it: the three sandbox rows cleaned of `phase6` on 2026-10-26 are {}), so it is written back as it
    # reads; only an answer that is not a policy is unreadable. `not pj` read {} as unreadable on V0643's operator read.
    if not isinstance(pj, dict):
        effect_unmeasured(outcomes, tool, f"the active policy could not be read (HTTP {code}), so it is not written back")
        return
    if not isinstance(cur.get("version"), int) or cur["version"] < 1:
        # the frame runs its factory defaults: a first policy row, however equal, turns every value the console
        # shows as "default" into one the frame amended
        effect_unmeasured(outcomes, tool, "this target runs the factory defaults (no policy row); writing them back "
                                          "would make every default an amendment on screen")
        return
    ok, ans = await effect(bag, parse, tool, {"policy_json": pj, "reason": "MCP tester: the active policy written "
                                                                           "back unchanged"}, outcomes)
    if not ok and "unknown policy key" in said(ans).lower():
        # the active policy itself carries keys the validator now refuses (sbx-alpha's held `phase6`, an old probe's
        # litter): written back unchanged it is refused, and the run never edits a frame's policy
        effect_unmeasured(outcomes, tool, f"the active policy carries keys the validator refuses ({said(ans)[-80:]}), "
                                          f"so written back unchanged it is refused; the run does not edit it")
        return
    if not ok:
        return
    ok2, now, code2 = await _admin_read(bag, parse, "theprotocol_getEnforcementPolicy", {})
    if not ok2:
        _bug(outcomes, tool, f"the policy could not be read afterwards (HTTP {code2})")
    elif now.get("policy_json") != pj:
        _bug(outcomes, tool, "the policy reads differently after it was written back unchanged")


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_agent_admin", "runner": lifecycle_earn_agent_admin},
]
