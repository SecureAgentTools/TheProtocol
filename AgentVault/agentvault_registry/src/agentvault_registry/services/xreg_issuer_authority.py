"""§TWOAGENT G4 (2026-09-23) — a cross-registry delegation conveys no more than its ISSUER holds NOW, at the issuer's home.

A capability token (L4) already obeys the confused-deputy rule: `resolve_capability` intersects its caveats with the
issuer's CURRENT authority, so clamping the issuer empties every token it issued. A cross-registry delegation did not.
Its grant lives on the DELEGATE's home, is minted once from the signed claim, and was honoured for its whole TTL (up to
30 days) whatever became of the issuer at home: Session A measured it on the EU/ASIA pair, where a delegate on one
frame kept acting "on behalf of" an issuer the other frame had already cut back. The only other path by which the
delegate's home learns anything is the issuer's revoke message, which is sent again until it lands (D6-272,
services/xreg_revoke_delivery); this answer does not wait for it.

Both halves live here, and neither needs a migration:

  * ISSUER home, `issuer_answer()`: the scoped read a delegate's home asks. It answers ONLY the registry the credential
    was shipped to (the caller is resolved from its SVID, never from the request), about a credential THIS registry
    issued (its `ironkey.xreg_delegation_issue` audit row is the issuer side's only durable record). Anything else is
    None and the route answers 404, which confirms nothing. The answer is no wider than what the revoke ship already
    tells that registry: whether the credential still stands, and what the issuer holds today.
  * DELEGATE home, `conveyed_for()`: what an `agent:<issuer>` grant conveys on THIS request: the granted set intersected
    with the issuer's current permissions when the issuer and the credential are live, otherwise nothing. The issuer's
    home is asked over federation mTLS and the answer is cached briefly; a home that cannot answer conveys NOTHING (fail
    closed) and is counted, so an outage of the issuer's home is visible. A LOCAL agent principal (an admin-made L3
    grant) is clamped the same way from this registry's own rows.

`XREG_ISSUER_AUTHORITY_MODE` = enforce (default) | shadow (check, log and count, but convey the grant) | off.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ROUTE = "/api/v1/federation/ironkey/issuer-authority"

# The issuer home's 404 carries THIS detail, so the delegate's home can tell "this home does not vouch for that" from
# "this home runs an image without the route" (whose 404 is FastAPI's generic one). Both convey nothing; only the
# sentence differs.
NOT_VOUCHED_DETAIL = "no delegation issued by this registry matches that request from the calling registry"

# The CLOSED set of outcomes (a metric label and the key of the sentence a refusal carries).
OUTCOMES = ("ok", "clamped", "issuer_inactive", "credential_revoked", "credential_expired", "not_vouched",
            "issuer_home_not_peer", "issuer_home_predates", "issuer_home_unreachable", "check_error")

SENTENCES: Dict[str, str] = {
    "clamped": "the issuer no longer holds any of the delegated permissions at its home registry",
    "issuer_inactive": "the issuer is not active on its home registry (suspended, revoked or deleted), so its "
                       "delegation conveys nothing",
    "credential_revoked": "the issuer's home says this delegation was revoked",
    "credential_expired": "this delegation has expired at the issuer's home",
    "not_vouched": "the issuer's home does not vouch for this delegation",
    "issuer_home_not_peer": "the issuer's home is no longer an active peer of this registry, so its delegation "
                            "conveys nothing",
    "issuer_home_predates": "the issuer's home runs a version that cannot confirm a delegation's authority, so this "
                            "delegation conveys nothing until it can",
    "issuer_home_unreachable": "the issuer's home could not confirm its authority right now, so this delegation "
                               "conveys nothing until it can; try again shortly",
    "check_error": "this registry could not check the issuer's authority, so the delegation conveys nothing",
}

_CACHE_TTL_S = int(os.getenv("XREG_ISSUER_AUTHORITY_CACHE_S", "60"))
_UNREACHABLE_TTL_S = int(os.getenv("XREG_ISSUER_AUTHORITY_UNREACHABLE_CACHE_S", "10"))
_TIMEOUT_S = float(os.getenv("XREG_ISSUER_AUTHORITY_TIMEOUT_S", "4"))
_SCAN_ISSUED = 500   # how many of one issuer's issue rows the home reads to find a credential id

try:
    from prometheus_client import Counter as _Counter

    XREG_ISSUER_CHECKS = _Counter(
        "ironkey_xreg_issuer_check_total",
        "Cross-registry delegation uses checked against the issuer's CURRENT authority at its home, by outcome "
        "(issuer_home_unreachable rising = the issuer's home is down and its delegations convey nothing)",
        ["outcome", "mode"],
    )
except Exception:  # pragma: no cover - metrics are optional, never load-bearing
    XREG_ISSUER_CHECKS = None


def issuer_check_mode() -> str:
    m = os.getenv("XREG_ISSUER_AUTHORITY_MODE", "enforce").strip().lower()
    return m if m in ("off", "shadow", "enforce") else "enforce"


def _count(outcome: str, mode: str) -> None:
    if XREG_ISSUER_CHECKS is None:
        return
    try:
        XREG_ISSUER_CHECKS.labels(outcome=outcome if outcome in OUTCOMES else "check_error", mode=mode).inc()
    except Exception:  # noqa: BLE001 — a metric never decides anything
        pass


def _json_or_empty(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        out = json.loads(value or "{}")
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def _is_past(iso: Optional[str], now: Optional[_dt.datetime] = None) -> bool:
    if not iso:
        return False
    try:
        t = _dt.datetime.fromisoformat(str(iso))
    except ValueError:
        return True   # an expiry we cannot read is not a promise we keep
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t <= (now or _dt.datetime.now(_dt.timezone.utc))


def _agent_live(status: Optional[str], enforcement_status: Optional[str]) -> bool:
    return str(status or "").lower() == "active" and str(enforcement_status or "active").lower() == "active"


# ─────────────────────────────── issuer home ───────────────────────────────

async def issued_record(db: AsyncSession, issuer_did: str, credential_id: str, *,
                        delivered_only: bool = True) -> Optional[Dict[str, Any]]:
    """The issue record of a credential `issuer_did` issued (the details of its `ironkey.xreg_delegation_issue` audit
    row, the issuer side's only record of a delegation it shipped), or None.

    delivered_only=True (the issuer-authority answer): only an issue whose credential reached the delegate's registry.
    False (the issuer's revoke, D6-272): any issue by this agent, one whose answer was lost included, since the
    delegate's registry may hold it all the same."""
    if not issuer_did or not credential_id:
        return None
    rows = (await db.execute(text(
        "SELECT details FROM security_audit_logs WHERE action = 'ironkey.xreg_delegation_issue' AND actor_id = :iss "
        + ("AND outcome = 'success' " if delivered_only else "") + "ORDER BY timestamp DESC LIMIT :n"),
        {"iss": issuer_did, "n": _SCAN_ISSUED})).all()
    return next((d for d in (_json_or_empty(r[0]) for r in rows) if d.get("credential_id") == credential_id), None)


async def issuer_answer(db: AsyncSession, issuer_did: str, credential_id: str,
                        caller_peer: Optional[str]) -> Optional[Dict[str, Any]]:
    """The answer to a delegate home's question, or None (the route's 404). See the module docstring for the scope."""
    if not caller_peer or not issuer_did or not credential_id:
        return None
    issued = await issued_record(db, issuer_did, credential_id)
    if issued is None:
        return None
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    if (await resolve_peer_name(db, issued.get("delegate_registry"))) != caller_peer:
        return None
    # The issuer's revoke counts whether or not its ship reached the delegate's home: that is the point.
    revoked = (await db.execute(text(
        "SELECT 1 FROM security_audit_logs WHERE action = 'ironkey.xreg_delegation_revoke' AND actor_id = :iss "
        "AND target_id = :cid LIMIT 1"), {"iss": issuer_did, "cid": credential_id})).first() is not None
    agent = (await db.execute(text("SELECT status, enforcement_status FROM agents WHERE did = :d"),
                              {"d": issuer_did})).first()
    live = agent is not None and _agent_live(agent[0], agent[1])
    held: Iterable[str] = ()
    if live:
        from agentvault_registry.agent_authz import resolve_agent_permissions
        # Minimal disclosure (Session A's review): the delegate's home needs only what this credential granted that
        # the issuer still holds, never the issuer's whole permission set.
        granted = {str(p) for p in (issued.get("permissions") or [])}
        held = set(await resolve_agent_permissions(db, issuer_did)) & granted
    return {"issuer_did": issuer_did, "credential_id": credential_id,
            "credential": "revoked" if revoked else ("expired" if _is_past(issued.get("expires_at")) else "active"),
            "issuer_status": "active" if live else ("gone" if agent is None else "inactive"),
            "issuer_permissions": sorted(held),
            "checked_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}


# ─────────────────────────────── delegate home ───────────────────────────────

def decide(granted: Set[str], answer: Dict[str, Any]) -> Tuple[Set[str], str]:
    """Pure: what a grant conveys given the issuer home's answer."""
    cred = str(answer.get("credential") or "")
    if cred == "revoked":
        return set(), "credential_revoked"
    if cred == "expired":
        return set(), "credential_expired"
    if cred != "active":
        return set(), "not_vouched"
    if str(answer.get("issuer_status") or "") != "active":
        return set(), "issuer_inactive"
    conveyed = set(granted) & {str(p) for p in (answer.get("issuer_permissions") or [])}
    return conveyed, ("ok" if conveyed == set(granted) else "clamped")


def _cache_key(host: str, issuer_did: str, credential_id: str) -> str:
    h = hashlib.sha256(f"{host}|{issuer_did}|{credential_id}".encode()).hexdigest()[:32]
    return f"ironkey:xreg:issuer-authority:{h}"


async def fetch_issuer_answer(db: AsyncSession, host_registry: str, issuer_did: str,
                              credential_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """(answer, "answered") or (None, the outcome that explains why there is none). Cached per credential."""
    from agentvault_registry.background_tasks.leader import get_redis
    key = _cache_key(host_registry, issuer_did, credential_id)
    r = None
    try:
        r = await get_redis()
        hit = await r.get(key) if r is not None else None
        if hit:
            c = json.loads(hit)
            return c.get("answer"), str(c.get("outcome") or "check_error")
    except Exception as e:  # noqa: BLE001 — a cache miss, not a verdict
        logger.debug("[IRONKEY-XREG] issuer-authority cache read skipped: %s", e)
    answer, outcome = await _ask_issuer_home(db, host_registry, issuer_did, credential_id)
    if r is not None:
        try:
            ttl = _UNREACHABLE_TTL_S if outcome in ("issuer_home_unreachable", "check_error") else _CACHE_TTL_S
            await r.set(key, json.dumps({"answer": answer, "outcome": outcome}), ex=max(1, ttl))
        except Exception as e:  # noqa: BLE001
            logger.debug("[IRONKEY-XREG] issuer-authority cache write skipped: %s", e)
    return answer, outcome


async def _ask_issuer_home(db: AsyncSession, host_registry: str, issuer_did: str,
                           credential_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    import httpx
    from fastapi import HTTPException
    from agentvault_registry.routers.guild import _fed_client_config, _resolve_peer_url
    try:
        target = await _resolve_peer_url(db, host_registry)
    except HTTPException:
        return None, "issuer_home_not_peer"
    cfg, headers = _fed_client_config(target)
    cfg["timeout"] = _TIMEOUT_S
    # mTLS is the credential here. This registry's internal secret means nothing to a peer frame, so it is not sent.
    headers = {k: v for k, v in headers.items() if k.lower() != "x-federation-secret"}
    try:
        async with httpx.AsyncClient(**cfg) as client:
            resp = await client.get(f"{target}{ROUTE}", headers=headers,
                                    params={"issuer_did": issuer_did, "credential_id": credential_id})
    except Exception as e:  # noqa: BLE001 — every transport failure is the same answer: not confirmed
        logger.warning("[IRONKEY-XREG] issuer home %s did not answer for cred=%s: %s", host_registry, credential_id,
                       type(e).__name__)
        return None, "issuer_home_unreachable"
    if resp.status_code == 200:
        try:
            body = resp.json()
        except ValueError:
            return None, "issuer_home_unreachable"
        return (body, "answered") if isinstance(body, dict) else (None, "issuer_home_unreachable")
    if resp.status_code == 404:
        try:
            detail = (resp.json() or {}).get("detail")
        except ValueError:
            detail = None
        return None, ("not_vouched" if detail == NOT_VOUCHED_DETAIL else "issuer_home_predates")
    logger.warning("[IRONKEY-XREG] issuer home %s answered %s for cred=%s", host_registry, resp.status_code,
                   credential_id)
    return None, "issuer_home_unreachable"


async def clamp_agent_principal(db: AsyncSession, delegate_did: str, issuer_did: str,
                                granted: Set[str]) -> Tuple[Set[str], str]:
    """What an `agent:<issuer>` grant to `delegate_did` conveys right now, and the outcome that explains it."""
    granted = set(granted or ())
    if not granted:
        return set(), "ok"
    cred = (await db.execute(text(
        "SELECT credential_id, host_registry FROM agent_delegation_credentials "
        "WHERE issuer_did = :iss AND delegate_did = :del AND revoked_at IS NULL "
        "ORDER BY received_at DESC LIMIT 1"), {"iss": issuer_did, "del": delegate_did})).first()
    if cred is None:
        # A LOCAL agent principal (an admin-made L3 grant): the issuer's authority is readable here.
        agent = (await db.execute(text("SELECT status, enforcement_status FROM agents WHERE did = :d"),
                                  {"d": issuer_did})).first()
        if agent is None or not _agent_live(agent[0], agent[1]):
            return set(), "issuer_inactive"
        from agentvault_registry.agent_authz import resolve_agent_permissions
        conveyed = granted & set(await resolve_agent_permissions(db, issuer_did))
        return conveyed, ("ok" if conveyed == granted else "clamped")
    answer, outcome = await fetch_issuer_answer(db, str(cred[1] or ""), issuer_did, str(cred[0] or ""))
    if answer is None:
        return set(), outcome
    return decide(granted, answer)


async def conveyed_for(db: AsyncSession, delegate_did: str, principal_ref: str, granted: Set[str]) -> Set[str]:
    """The resolver's entry point: the mode decides whether the clamp binds (enforce), is only reported (shadow) or is
    not run at all (off). Never raises; an error conveys nothing under enforce."""
    mode = issuer_check_mode()
    if mode == "off" or not granted:
        return set(granted or ())
    issuer_did = principal_ref[len("agent:"):] if principal_ref.startswith("agent:") else principal_ref
    try:
        conveyed, outcome = await clamp_agent_principal(db, delegate_did, issuer_did, set(granted))
    except Exception as e:  # noqa: BLE001
        logger.warning("[IRONKEY-XREG] issuer-authority check failed for %s acting as %s: %s", delegate_did,
                       principal_ref, e)
        conveyed, outcome = set(), "check_error"
    _count(outcome, mode)
    if outcome != "ok":
        logger.warning("[IRONKEY-XREG] mode=%s delegate=%s act=%s outcome=%s conveyed=%s of %s", mode, delegate_did,
                       principal_ref, outcome, sorted(conveyed), sorted(granted))
    return set(granted) if mode == "shadow" else conveyed


def refusal_sentence(outcome: str) -> str:
    return SENTENCES.get(outcome) or SENTENCES["check_error"]
