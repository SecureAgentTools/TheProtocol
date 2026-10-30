"""A cross-frame dispute settlement the defendant's home rejects (V0639, agentvault2-aa, 2026-10-24).

The OWL25 settlement path, run for the first time on these frames: cross_registry_settlements held no row on
sbx-alpha, sbx-beta, EU or ASIA (read 2026-10-24). A complainant on sandbox-A (the origin) files a dispute against a
defendant homed on sandbox-B, with evidence naming an amount over every auto-slash threshold sandbox-B holds. A's
administrator rules for the complainant, which sends the slash request to the defendant's home
(crud_disputes._process_cross_registry_compensation); B parks it as PENDING_ADMIN_APPROVAL
(routers/federation_disputes.receive_slash_request). B's administrator reads it (getFederationDisputeSettlement) and
rejects it (rejectDisputeSettlement), never approves; nothing moves, and A hears "failed". Sandbox-B is the home because
the console's settlements door is measured there (agentvault2-5b's lifecycle 134).

The conditions agentvault2-5b set for 134 hold here too: the amount is over the threshold read at run time, and
auto_slash_enabled is never written; only the settlement this run's own throwaway caused is touched, found by its
defendant's DID and the dispute's id; the read-back is REJECTED with nothing slashed, the defendant's balance unchanged
and the origin's settlement failed; both throwaways are deleted, and the cleanup is judged.

⚠ Writes: two throwaway agents named `fedsuite-settle-*` (soft-deleted at the end), one dispute on sandbox-A and one
settlement row on each frame, kept as history (no route removes a dispute or a settlement). No money moves: the home
holds the request for an administrator, and the rejection moves nothing.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.federation_suite import throwaways
from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import FederationTestRig, AssertionResult, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests.test_twoagent_contract_xframe import (
    _call, _until, _run, _balance,
)
from agentvault_registry.services.registry_card_builder import _dialable_from_outside

_TAG = "fedsuite-settle"
_A, _B = "sandbox-A", "sandbox-B"
_ADMIN = {_A: "sandbox-A-admin", _B: "sandbox-B-admin"}
_REQUIRES = [_A, _B, _ADMIN[_A], _ADMIN[_B]]
_MIRROR_SEC = 240.0     # a fresh card reached the peer in 21.6-92.2 s on the sandbox (TESTPLAN F5)
_SETTLE_SEC = 90.0
_PENDING = "PENDING_ADMIN_APPROVAL"


async def _agent(rig, label: str, tag: str, made: List[Tuple[str, str]]) -> Dict[str, str]:
    """A throwaway agent of the frame's administrator, with its token; recorded for the cleanup at once."""
    name = f"{_TAG}-{tag}-{uuid.uuid4().hex[:8]}"
    r, refused = await _call(rig, label, "createAgent",
                             {"name": name, "description": "federation suite cross-frame settlement probe"})
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
    return {"did": did, "jwt": jwt, "name": name}


def amount_over_every_threshold(peers: Any) -> int:
    """One unit over the highest auto-slash threshold the home holds for any active peer (1 when none is on), so the
    request parks for an administrator whichever peer row the origin's request is matched to."""
    tops = [int(float(str(p.get("auto_slash_max_avt") or 0))) for p in (peers or [])
            if isinstance(p, dict) and p.get("auto_slash_enabled")]
    return (max(tops) if tops else 0) + 1


def ours(rows: Any, defendant_did: str, dispute_id: str) -> List[Dict[str, Any]]:
    """The settlements this run caused: its own defendant's DID AND its own dispute's id, nothing else."""
    return [s for s in (rows or []) if isinstance(s, dict) and s.get("defendant_did") == defendant_did
            and str(s.get("dispute_id")) == dispute_id]


def _settlements(r: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(r, list):
        return r
    if isinstance(r, dict) and isinstance(r.get("settlements"), list):
        return r["settlements"]
    return None


def settlement_of(r: Any) -> Dict[str, Any]:
    """The settlement in getFederationDisputeSettlement's answer. The route answers {"settlement": {...}}
    (routers/federation_disputes.get_settlement); reading id or status at the top level reads None, which is how this
    flow went red every night on the standing sandbox while both frames did the right thing (V0649, agentvault2-13).
    An answer that is already the bare row is taken as it is; anything else is an empty dict."""
    if not isinstance(r, dict):
        return {}
    inner = r.get("settlement")
    return inner if isinstance(inner, dict) else r


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(str(v))
    except (TypeError, ValueError):
        return None


@federation_test(
    name="xframe_settlement_the_home_rejects_and_nothing_moves",
    category="disputes_xframe",
    budget_sec=600.0,
    severity="critical",
    requires=_REQUIRES,
    tags=["disputes", "xframe", "owl25", "cross_frame", "settlements", "money", "v0639"],
)
async def test_xframe_settlement_reject(rig: FederationTestRig) -> AssertionResult:
    planned = ["the_amount_is_over_every_threshold_the_home_holds", "the_origin_takes_the_dispute",
               "the_evidence_names_the_amount", "the_origin_rules_for_the_complainant",
               "the_home_holds_it_for_an_administrator", "getFederationDisputeSettlement_reads_it",
               "rejectDisputeSettlement_rejects_it", "nothing_moved_on_the_home", "the_origin_hears_failed"]

    async def body(legs, made, hooks):
        cfg, refused = await _call(rig, _B, "getPeerSlashConfig", {})
        peers = cfg.get("peers") if isinstance(cfg, dict) else None
        if refused or not isinstance(peers, list):
            raise PreconditionUnmet(f"getPeerSlashConfig on {_B}: {refused or str(cfg)[:160]}")
        amount = amount_over_every_threshold(peers)
        legs.check("the_amount_is_over_every_threshold_the_home_holds", amount >= 1,
                   {"amount": amount, "thresholds": [(p.get("name"), p.get("auto_slash_enabled"),
                                                      p.get("auto_slash_max_avt")) for p in peers]})

        defendant = await _agent(rig, _B, "defendant", made)
        complainant = await _agent(rig, _A, "complainant", made)
        before = await _balance(rig, _B, defendant["jwt"])

        async def _file():
            # the origin takes the dispute once it knows the defendant: a mirrored card (routers/disputes.py)
            r, why = await _call(rig, _A, "submitDispute", {
                "agent_jwt": complainant["jwt"], "defendant_did": defendant["did"],
                "description": "federation suite: a cross-frame settlement the home rejects"})
            if why and "not known to this registry" in why:
                return None
            return {"r": r, "refused": why}
        filed = await _until(_file, _MIRROR_SEC)
        r = (filed or {}).get("r")
        dispute_id = str((r or {}).get("id") or (r or {}).get("dispute_id") or "") if isinstance(r, dict) else ""
        if not legs.check("the_origin_takes_the_dispute", bool(dispute_id) and not (filed or {}).get("refused"),
                          {"refused": (filed or {}).get("refused"), "within_sec": _MIRROR_SEC}):
            return

        _, why = await _call(rig, _A, "submitDisputeEvidence", {
            "agent_jwt": complainant["jwt"], "dispute_id": dispute_id,
            "evidence_data": {"amount_disputed": amount, "note": "federation suite settlement probe"}})
        if not legs.check("the_evidence_names_the_amount", not why, {"refused": why}):
            return

        ruled, why = await _call(rig, _ADMIN[_A], "updateDisputeRuling",
                                 {"dispute_id": dispute_id, "ruling": "IN_FAVOR_OF_COMPLAINANT"})
        comp = (ruled or {}).get("compensation") if isinstance(ruled, dict) else None
        sent = isinstance(comp, dict) and comp.get("settlement_status") == "pending_remote_slash"
        if not legs.check("the_origin_rules_for_the_complainant", not why and sent,
                          {"refused": why, "compensation": comp}):
            return
        sid = str(comp.get("settlement_id") or "")
        # The origin's address decides whether any peer takes the request: the home accepts a callback only under an
        # ACTIVE peer's base_url, the address the origin's card publishes. An origin that names its internal proxy
        # (CROSS_REGISTRY_SETTLEMENT_DELIVERY off, the default, core/settlement_origin) is refused by every peer: the
        # home's half cannot run, which is the environment, not the path (V0639).
        own, _w = await _call(rig, _A, "getFederationDisputeSettlement", {"settlement_id": sid})
        own = settlement_of(own)
        named = str(own.get("origin_registry_url") or "")
        if named and not _dialable_from_outside(named):
            raise PreconditionUnmet(
                f"{_A} named itself {named} as the settlement's origin, an address no peer holds, so every peer refuses "
                f"its slash request (CROSS_REGISTRY_SETTLEMENT_DELIVERY is off there, or it has no dialable federation "
                f"address): the home's half of the path cannot run here")

        async def _pending():
            got, w = await _call(rig, _B, "getFederationDisputeSettlements", {"status_filter": _PENDING, "limit": 100})
            mine = ours(_settlements(got), defendant["did"], dispute_id)
            return mine or None
        mine = await _until(_pending, _SETTLE_SEC) or []
        row = mine[0] if len(mine) == 1 else {}
        held = (len(mine) == 1 and row.get("status") == _PENDING and str(row.get("id")) == sid
                and _num(row.get("requested_amount")) == float(amount))
        if not legs.check("the_home_holds_it_for_an_administrator", held, {"rows": mine, "settlement_id": sid}):
            return

        got, why = await _call(rig, _B, "getFederationDisputeSettlement", {"settlement_id": sid})
        one = settlement_of(got)
        legs.check("getFederationDisputeSettlement_reads_it",
                   not why and str(one.get("id")) == sid and one.get("status") == _PENDING,
                   {"refused": why, "status": one.get("status")})

        rej, why = await _call(rig, _B, "rejectDisputeSettlement", {"settlement_id": sid})
        legs.check("rejectDisputeSettlement_rejects_it",
                   not why and isinstance(rej, dict) and rej.get("status") == "REJECTED",
                   {"refused": why, "answer": rej})

        got, why = await _call(rig, _B, "getFederationDisputeSettlement", {"settlement_id": sid})
        after_row = settlement_of(got)
        after = await _balance(rig, _B, defendant["jwt"])
        legs.check("nothing_moved_on_the_home",
                   not why and after_row.get("status") == "REJECTED"
                   and not _num(after_row.get("slashed_amount")) and before is not None and after == before,
                   {"status": after_row.get("status"), "slashed": after_row.get("slashed_amount"),
                    "balance_before": before, "balance_after": after})

        async def _told():
            got, w = await _call(rig, _A, "getFederationDisputeSettlement", {"settlement_id": sid})
            st = settlement_of(got).get("status")
            return st if st and st not in ("PENDING_SLASH", "PENDING") else None
        told = await _until(_told, _SETTLE_SEC)
        legs.check("the_origin_hears_failed", told == "FAILED", {"origin_status": told})

    return await _run(rig, planned, "a cross-frame settlement: the home holds it, rejects it, and nothing moves", body)
