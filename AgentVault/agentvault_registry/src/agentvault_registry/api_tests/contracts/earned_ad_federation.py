"""§MCPTEST30 (V0636): the federation tools on peers and an invitation the run made (agentvault2-aa; step 2 of
sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md).

On V0635 each of these passed on one refusal: 404 for peer 999999. Here a throwaway developer registers two fixture
peers on the reserved `.theprotocol.test` host (no registry ever dials it), and the run drives them through every
state its tools change, each step read back:

  peer A   createFederationPeer (PENDING_APPROVAL), updateFederationPeer (the description), approvePeerRegistry
           (ACTIVE; getFederationPeerByID, the public read, now answers), getFederationRegistryHealthProfile,
           pollPeerComplianceNow, updatePeerSlashConfig (read back by getPeerSlashConfig),
           deactivatePeerRegistry (INACTIVE), reactivatePeerRegistry (ACTIVE: its TEG partner registered, and removed
           again by the deactivation that follows, since agentvault2-5b's 2026-10-18 fix), deleteFederationPeerSelf by
           its owner last (INACTIVE again, for good: a deactivated peer is never deleted, the card fan-out would add
           its name back)
  peer B   rejectPeerRegistry (REJECTED)
  invite   createFrameInvitation naming a trust domain that does not exist and the frame's own bundle endpoint (the
           intake probes the endpoint, so it must answer); rejectFrameInvitation (rejected; a second reject is 409)
  mode     setFederationComplianceEnforcementMode writes the mode it reads back unchanged
  probe    probeTopologyPeer on a real active peer of the frame (it GETs the peer's health and writes nothing; the
           fixture's reserved host is unreachable by design)

Not here, each for its own reason: quarantineRegistry and liftQuarantine (a quarantine sends a critical push to the
frame's operators, and the frame's roll drivers refuse while a registry is quarantined), blacklistRegistry
(irreversible from the API), revokeFrame (it ends a federated frame's trust), approveFrameInvitation,
finalizeRetryFrameInvitation and finalizeFrameInvitation (an approval federates the frame's SPIRE server with the
inviter's trust domain), completeAdmission (an admission exists only through federationRequestAdmission, which the
tester never invokes), resyncFrameEventStore (a federated frame's ledger only), and the peer-to-peer routes
(federationSlashRequest, federationSlashConfirmation, federationCliAudit, getFederationSyncStatusDev: they take a
peer registry's federation identity, never an administrator's).
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.earned_fixtures import (
    Throwaways, effect, effect_name, effect_unmeasured, lc, refusal_step, said, step,
)

ADMIN = "admin"
DEV_TOOLS = ("theprotocol_createFederationPeer", "theprotocol_updateFederationPeer", "theprotocol_getFederationPeerByID",
             "theprotocol_getFederationRegistryHealthProfile", "theprotocol_updatePeerSlashConfig",
             "theprotocol_deleteFederationPeerSelf", "theprotocol_createFrameInvitation")
ADMIN_TOOLS = ("theprotocol_approvePeerRegistry", "theprotocol_probeTopologyPeer", "theprotocol_pollPeerComplianceNow",
               "theprotocol_deactivatePeerRegistry", "theprotocol_reactivatePeerRegistry",
               "theprotocol_rejectPeerRegistry", "theprotocol_rejectFrameInvitation",
               "theprotocol_setFederationComplianceEnforcementMode")


async def _admin_read(bag: Any, parse: Any, tool: str, args: Dict[str, Any]) -> Tuple[bool, Any, str]:
    rpc_admin = getattr(bag, "rpc_admin", None)
    if rpc_admin is None:
        return False, {}, ""
    ok, body, code = await rpc_admin(tool, args, jwt=bag.developer_jwt, timeout=30)
    inner = parse(body) if isinstance(body, dict) else {}
    return bool(ok), inner, str(code)


def _bug(outcomes: Dict[str, dict], name: str, why: str, tier: str = "admin_effect") -> None:
    lc()._bugfind(outcomes, name, tier, why)


def _passed(outcomes: Dict[str, dict], name: str) -> bool:
    row = outcomes.get(name)
    return bool(row and row.get("healthy"))


def _status_is(*want: str):
    def check(a: Dict[str, Any]) -> Optional[str]:
        return None if str(a.get("status") or "").upper() in want else f"the answer reads status={a.get('status')!r}"
    return check


def _peer_rows(v: Any) -> List[Dict[str, Any]]:
    if isinstance(v, list):
        return [r for r in v if isinstance(r, dict)]
    if isinstance(v, dict):
        for k in ("items", "peers", "registries", "results"):
            if isinstance(v.get(k), list):
                return [r for r in v[k] if isinstance(r, dict)]
    return []


async def _admin_status(bag: Any, parse: Any, pid: int) -> Optional[str]:
    """The status the admin peer list reads for peer `pid` (it lists every state; the public read only ACTIVE)."""
    ok, ans, _c = await _admin_read(bag, parse, "theprotocol_getAllFederationPeersAdmin", {})
    for r in _peer_rows(ans):
        if str(r.get("id")) == str(pid):
            return str(r.get("status") or "")
    return None


async def _shows(bag: Any, parse: Any, outcomes: Dict[str, dict], tool: str, pid: int, want: str) -> None:
    if not _passed(outcomes, effect_name(tool)):
        return
    st = await _admin_status(bag, parse, pid)
    if st != want:
        _bug(outcomes, effect_name(tool), f"{tool.replace('theprotocol_', '')}: the admin peer list reads peer {pid} as "
                                          f"{st!r} afterwards, not {want!r}")


def _fixture(tag: str) -> Dict[str, Any]:
    return {"name": f"MCP Earn Peer {tag}", "base_url": f"https://mcp-earn-{tag}.theprotocol.test",
            "description": "The MCP tester's fixture peer: a reserved host no registry dials, retired after its run.",
            "admin_contact_email": "mcp-earn-peer@throwaway-pl.example.com",
            "discovery_auth_info": {"type": "api_key", "api_key_header_name": "X-API-Key"}}


async def lifecycle_earn_federation(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict]) -> None:
    """The federation tools on two fixture peers and one invitation of the run's own (the module docstring)."""
    if getattr(bag, "rpc_admin", None) is None:
        for tool in ADMIN_TOOLS:
            effect_unmeasured(outcomes, tool, "this flow carries no admin bridge (bag.rpc_admin)")
        return
    t = Throwaways(rpc, parse, bag, "federation")
    try:
        owner = await t.developer("peer-owner")
        for part, tools in ((_peer_a, DEV_TOOLS[:6] + ADMIN_TOOLS[:5]), (_peer_b, ADMIN_TOOLS[5:6]),
                            (_invitation, DEV_TOOLS[6:7] + ADMIN_TOOLS[6:7]), (_mode, ADMIN_TOOLS[7:8])):
            try:
                await part(rpc, parse, bag, outcomes, owner)
            except Exception as e:                                     # noqa: BLE001
                why = f"the lifecycle raised {type(e).__name__}: {str(e)[:160]} before it reached this tool"
                for tool in tools:
                    if tool in ADMIN_TOOLS and effect_name(tool) not in outcomes:
                        effect_unmeasured(outcomes, tool, why)
                    elif tool in DEV_TOOLS and tool not in outcomes:
                        outcomes[tool] = lc()._not_measured(tool, "3", f"NOT MEASURED: {why}")
    finally:
        await t.close()


async def _peer_a(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], owner: Dict[str, Any]) -> None:
    jwt = owner.get("access_token")
    if not jwt:
        for tool in DEV_TOOLS[:6]:
            outcomes[tool] = lc()._not_measured(tool, "3", f"NOT MEASURED: no developer of the run's own to register a "
                                                           f"fixture peer: {owner.get('why')}")
        for tool in ADMIN_TOOLS[:5]:
            effect_unmeasured(outcomes, tool, "no fixture peer of the run's own")
        return
    tag = f"{int(time.time())}-{secrets.token_hex(2)}"
    ok, made = await step(rpc, parse, "theprotocol_createFederationPeer", "3", {"peer_data": _fixture(tag)}, jwt,
                          outcomes)
    pid = made.get("id") if ok and isinstance(made, dict) else None
    if not isinstance(pid, int):
        if ok:
            _bug(outcomes, "theprotocol_createFederationPeer", "createFederationPeer answered 2xx without an id", "3")
        for tool in ADMIN_TOOLS[:5]:
            effect_unmeasured(outcomes, tool, "no fixture peer of the run's own could be registered")
        return
    if str(made.get("status") or "").upper() != "PENDING_APPROVAL":
        _bug(outcomes, "theprotocol_createFederationPeer",
             f"a new peer reads status={made.get('status')!r}, not PENDING_APPROVAL", "3")
    new_desc = f"The MCP tester's fixture peer {tag}, updated by its owner."
    ok, ans = await step(rpc, parse, "theprotocol_updateFederationPeer", "3",
                         {"peer_id": str(pid), "updates": {"description": new_desc}}, jwt, outcomes)
    if ok and ans.get("description") != new_desc:
        _bug(outcomes, "theprotocol_updateFederationPeer", "the answer does not carry the new description", "3")
    tool = "theprotocol_approvePeerRegistry"
    ok, _ = await effect(bag, parse, tool, {"peer_id": str(pid)}, outcomes, check=_status_is("ACTIVE"))
    if ok:
        await step(rpc, parse, "theprotocol_getFederationPeerByID", "3", {"peer_id": str(pid)}, jwt, outcomes,
                   verify_against=effect_name(tool),
                   verify_against_check=lambda a: None if str(a.get("status") or "").upper() == "ACTIVE"
                   else f"getFederationPeerByID reads status={a.get('status')!r} after the approval")
        await step(rpc, parse, "theprotocol_getFederationRegistryHealthProfile", "3",
                   {"peer_id_or_name": str(pid)}, jwt, outcomes)
        await _probe_real_peer(bag, parse, outcomes)
        ok_p, ans_p = await effect(bag, parse, "theprotocol_pollPeerComplianceNow", {"peer_id": str(pid)}, outcomes)
        if not ok_p and "compliance record" in said(ans_p).lower():
            effect_unmeasured(outcomes, "theprotocol_pollPeerComplianceNow",
                              "an approved peer of the run's own has no compliance record to poll (one is made only "
                              "by an admission)")
        await _slash_config(rpc, parse, bag, outcomes, pid)
        tool = "theprotocol_deactivatePeerRegistry"
        await effect(bag, parse, tool, {"peer_id": str(pid)}, outcomes, check=_status_is("INACTIVE"))
        await _shows(bag, parse, outcomes, tool, pid, "INACTIVE")
        tool = "theprotocol_reactivatePeerRegistry"
        ok_r, _ = await effect(bag, parse, tool, {"peer_id": str(pid)}, outcomes, check=_status_is("ACTIVE"))
        await _shows(bag, parse, outcomes, tool, pid, "ACTIVE")
    else:
        for t2 in ("theprotocol_probeTopologyPeer", "theprotocol_pollPeerComplianceNow",
                   "theprotocol_deactivatePeerRegistry", "theprotocol_reactivatePeerRegistry"):
            effect_unmeasured(outcomes, t2, "the fixture peer of the run's own was not approved")
    # its owner retires it, for good, whatever state the steps above left
    ok, _ = await step(rpc, parse, "theprotocol_deleteFederationPeerSelf", "3", {"peer_id": str(pid)}, jwt, outcomes)
    if ok:
        st = await _admin_status(bag, parse, pid)
        if st not in ("INACTIVE", None):
            _bug(outcomes, "theprotocol_deleteFederationPeerSelf",
                 f"the admin peer list reads peer {pid} as {st!r} after its owner retired it", "3")
    else:
        # never leave a fixture ACTIVE: an administrator retires it
        await _admin_read(bag, parse, "theprotocol_deactivatePeerRegistry", {"peer_id": str(pid)})


async def _slash_config(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], pid: int) -> None:
    tool = "theprotocol_updatePeerSlashConfig"
    ok, _ = await step(rpc, parse, tool, "3", {"peer_id": str(pid),
                                               "config": {"auto_slash_enabled": True, "auto_slash_max_avt": 1}},
                       bag.developer_jwt, outcomes)
    if not ok:
        return
    ok2, body, code = await rpc("theprotocol_getPeerSlashConfig", {}, jwt=bag.developer_jwt, timeout=20)
    rows = _peer_rows(parse(body) if isinstance(body, dict) else {})
    mine = next((r for r in rows if str(r.get("peer_id") or r.get("id")) == str(pid)), None)
    if not ok2:
        _bug(outcomes, tool, f"getPeerSlashConfig could not be read afterwards (HTTP {code})", "3")
    elif mine is None or mine.get("auto_slash_enabled") is not True or _num(mine.get("auto_slash_max_avt")) != 1.0:
        _bug(outcomes, tool, f"getPeerSlashConfig reads the fixture's config as enabled="
                             f"{(mine or {}).get('auto_slash_enabled')!r} max={(mine or {}).get('auto_slash_max_avt')!r}", "3")


def _num(v: Any) -> Optional[float]:
    """A Numeric column answers as a decimal string ("1.00000000"); None when it is no number."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _probe_real_peer(bag: Any, parse: Any, outcomes: Dict[str, dict]) -> None:
    """probeTopologyPeer GETs a peer's health endpoints and writes nothing, so it probes a real active peer of the
    frame: a fixture on the reserved host answers {"ok": false} (unreachable), which measures nothing."""
    tool = "theprotocol_probeTopologyPeer"
    ok, ans, code = await _admin_read(bag, parse, "theprotocol_getAllFederationPeersAdmin", {})
    real = [r for r in _peer_rows(ans) if str(r.get("status") or "").upper() == "ACTIVE" and isinstance(r.get("id"), int)
            and not str(r.get("base_url") or "").rstrip("/").endswith(".theprotocol.test")]
    if not real:
        effect_unmeasured(outcomes, tool, f"this frame has no active peer of its own to probe (HTTP {code})")
        return
    frames = [r for r in real if r.get("peer_type") == "frame"] or real
    await effect(bag, parse, tool, {"peer_id": str(frames[0]["id"])}, outcomes,
                 check=lambda a: None if a.get("ok") is True else f"the probe reads ok={a.get('ok')!r}")


async def _peer_b(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], owner: Dict[str, Any]) -> None:
    tool = "theprotocol_rejectPeerRegistry"
    jwt = owner.get("access_token")
    if not jwt:
        effect_unmeasured(outcomes, tool, "no developer of the run's own to register a fixture peer")
        return
    tag = f"{int(time.time())}-{secrets.token_hex(2)}b"
    ok, body, code = await rpc("theprotocol_createFederationPeer", {"peer_data": _fixture(tag)}, jwt=jwt, timeout=30)
    made = parse(body) if isinstance(body, dict) else {}
    pid = made.get("id") if ok and isinstance(made, dict) else None
    if not isinstance(pid, int):
        effect_unmeasured(outcomes, tool, f"no second fixture peer could be registered (HTTP {code})")
        return
    await effect(bag, parse, tool, {"peer_id": str(pid)}, outcomes, check=_status_is("REJECTED"))
    await _shows(bag, parse, outcomes, tool, pid, "REJECTED")
    await refusal_step(bag.rpc_admin, parse, tool, ADMIN, {"peer_id": str(pid)}, bag.developer_jwt, outcomes,
                       "a peer already rejected", codes=(400,), text="Cannot reject")


def _find(obj: Any, key: str) -> Optional[Any]:
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            hit = _find(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find(v, key)
            if hit is not None:
                return hit
    return None


async def _invitation(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], owner: Dict[str, Any]) -> None:
    create, reject = "theprotocol_createFrameInvitation", "theprotocol_rejectFrameInvitation"
    ok, body, code = await rpc("theprotocol_getRegistryCard", {}, jwt=bag.developer_jwt, timeout=20)
    endpoint = _find(parse(body) if isinstance(body, dict) else {}, "spire_bundle_endpoint") if ok else None
    if not (isinstance(endpoint, str) and endpoint.startswith("https://")):
        why = "this frame's card names no https SPIRE bundle endpoint, which an invitation's intake probes"
        outcomes[create] = lc()._not_measured(create, "3", f"NOT MEASURED: {why}")
        effect_unmeasured(outcomes, reject, why)
        return
    tag = f"{int(time.time())}{secrets.token_hex(2)}"
    ok, inv = await step(rpc, parse, create, "3", {
        "trust_domain": f"mcp-earn-{tag}.invalid", "bundle_endpoint_url": endpoint,
        "federation_endpoint_url": f"https://mcp-earn-{tag}.theprotocol.test",
        "name": f"MCP Earn Frame {tag}", "contact_email": "mcp-earn-frame@throwaway-pl.example.com",
        "initiator_nonce": secrets.token_hex(16),
        "description": "The MCP tester's invitation: a trust domain that does not exist, rejected at once."},
        bag.developer_jwt, outcomes)
    iid = (inv.get("id") or inv.get("invitation_id")) if ok and isinstance(inv, dict) else None
    if not iid:
        effect_unmeasured(outcomes, reject, "no invitation of the run's own could be made")
        return
    ok, _ = await effect(bag, parse, reject, {"invitation_id": str(iid), "reason": "MCP tester: its own invitation"},
                         outcomes, check=lambda a: None if str(a.get("status") or "rejected").lower() == "rejected"
                         else f"the answer reads status={a.get('status')!r}")
    if ok:
        ok2, now, code2 = await _admin_read(bag, parse, "theprotocol_getAdminFrameInvitation",
                                            {"invitation_id": str(iid)})
        if not ok2 or str(now.get("status") or "").lower() != "rejected":
            _bug(outcomes, effect_name(reject), f"rejectFrameInvitation: the invitation reads "
                                                f"{now.get('status') if ok2 else 'unreadable (HTTP ' + code2 + ')'} "
                                                f"afterwards")
        await refusal_step(bag.rpc_admin, parse, reject, ADMIN,
                           {"invitation_id": str(iid), "reason": "MCP tester: a second reject"},
                           bag.developer_jwt, outcomes, "an invitation already rejected", codes=(409,),
                           text="Cannot reject")


async def _mode(rpc: Any, parse: Any, bag: Any, outcomes: Dict[str, dict], owner: Dict[str, Any]) -> None:
    tool = "theprotocol_setFederationComplianceEnforcementMode"
    ok, ans, code = await _admin_read(bag, parse, "theprotocol_getFederationComplianceEnforcementMode", {})
    mode = ans.get("mode") if ok and isinstance(ans, dict) else None
    if mode not in ("off", "dry_run", "enforcing"):
        effect_unmeasured(outcomes, tool, f"the frame's compliance enforcement mode could not be read (HTTP {code}), "
                                          f"so it is not written back")
        return
    await effect(bag, parse, tool, {"mode": mode, "reason": "MCP tester: the mode written back unchanged"}, outcomes)
    if _passed(outcomes, effect_name(tool)):
        ok2, now, _c = await _admin_read(bag, parse, "theprotocol_getFederationComplianceEnforcementMode", {})
        if not ok2 or now.get("mode") != mode:
            _bug(outcomes, effect_name(tool), f"setFederationComplianceEnforcementMode: the mode reads "
                                              f"{now.get('mode') if ok2 else '?'} after it was written back as {mode}")


LIFECYCLES: List[Dict[str, Any]] = [
    {"name": "earn_federation", "runner": lifecycle_earn_federation},
]
