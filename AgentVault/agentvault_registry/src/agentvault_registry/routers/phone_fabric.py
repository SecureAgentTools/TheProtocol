"""PHONE FABRIC — capability-gated agent computer-use (2026-07-07).

An agent drives a phone (mock now; redroid later) ONLY inside an IRONKEY L4 capability
token presented via `X-Capability-Token`. The token must carry `phone.use` and phone
caveats; every action is metered against the token's budget (the existing L4 debit —
Δ-irrelevant, deny-only), enforced against caveats (allowed_apps / max_actions / ttl /
no_screenshot / no_network / allowed_domains), and audited (phone_session_actions + event + owner push).

Endpoints (agent JWT + X-Capability-Token):
  POST /api/v1/phone/sessions                start (lease instance, open session)
  POST /api/v1/phone/sessions/{id}/act       one action (metered, caveat-checked, audited)
  GET  /api/v1/phone/sessions/{id}/observe   accessibility tree (+screenshot unless no_screenshot)
  POST /api/v1/phone/sessions/{id}/end       release + settle
  GET  /api/v1/phone/sessions/mine           my sessions
Admin (an admin credential, security.admin_credential):
  GET  /api/v1/admin/phone/pool · /admin/phone/sessions · POST /admin/phone/global-halt
"""
import datetime as _dt
import json
import logging
import os
import secrets
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, schemas
from agentvault_registry.database import get_db
from agentvault_registry.security import admin_credential, get_current_agent, get_current_developer
from agentvault_registry import agent_delegation as capmod
from agentvault_registry.services.phone.mock_driver import make_driver
from agentvault_registry.core.phone_fabric_gate import phone_fabric_enabled  # D6-841: one predicate, the console reads it too

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Phone Fabric"])

_ACTION_COST = Decimal(os.getenv("PHONE_ACTION_COST", "1"))     # budget units per action
_START_COST = Decimal(os.getenv("PHONE_START_COST", "1"))


def phone_use_mode() -> str:
    m = os.getenv("PHONE_USE_MODE", "off").strip().lower()
    return m if m in ("off", "shadow", "enforce") else "off"


def _backend() -> str:
    b = os.getenv("PHONE_FABRIC_BACKEND", "mock").strip().lower()
    return b if b in ("mock", "redroid") else "mock"


def _require_enabled():
    if not phone_fabric_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Phone Fabric is disabled on this registry")


async def _resolve_phone_cap(db: AsyncSession, token: Optional[str], agent_did: str) -> dict:
    """Validate the presented capability token carries phone.use. Returns the cap dict."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="X-Capability-Token required for phone.use")
    cap, reason = await capmod.resolve_capability(db, token, agent_did)
    if cap is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"Capability rejected: {reason}")
    if "phone.use" not in cap["permissions"]:
        # shadow mode logs but still allows (posture staging); enforce blocks.
        if phone_use_mode() == "enforce":
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Token lacks phone.use")
        logger.warning("[PHONE][shadow] token %s lacks phone.use — would block in enforce", cap["id"])
    return cap


async def _debit(db: AsyncSession, token_id: int, amount: Decimal) -> None:
    """Meter one unit of phone use against the L4 token budget (the exact L4 consume debit).
    Δ-irrelevant: a counter on the capability token, pre-escrow, deny-only. No AVT moves."""
    await db.execute(text(
        "UPDATE agent_capability_tokens SET budget_spent = budget_spent + :a, uses = uses + 1, "
        "status = 'active' WHERE id = :i"
    ), {"a": amount, "i": token_id})
    await db.execute(text(
        "UPDATE agent_capability_tokens SET status = 'exhausted' WHERE id = :i "
        "AND ((budget_total IS NOT NULL AND budget_spent >= budget_total) "
        "     OR (max_uses IS NOT NULL AND uses >= max_uses))"
    ), {"i": token_id})


async def _audit(db: AsyncSession, session_id: str, action_type: str,
                 target: Optional[str], payload: Optional[dict], cost: Decimal,
                 outcome: str, detail: str = "") -> int:
    """Append one trace row and return its sequence number.

    §DOCSFIX D6-528 (2026-10-16): the number is the next one of this session's own trace (the start row is 0). It
    used to be the session's action counter plus one, which only an allowed action advances, so an observe or a
    refused action and the next allowed action wrote the same number."""
    seq = (await db.execute(text(
        "SELECT COALESCE(MAX(seq), -1) + 1 FROM phone_session_actions WHERE session_id = :s"
    ), {"s": session_id})).scalar()
    await db.execute(text("""
        INSERT INTO phone_session_actions (session_id, seq, action_type, target, payload, cost, outcome, detail)
        VALUES (:s, :q, :at, :tg, CAST(:pl AS JSONB), :c, :oc, :dt)
    """), {"s": session_id, "q": seq, "at": action_type, "tg": target,
           "pl": json.dumps(payload or {}), "c": cost, "oc": outcome, "dt": detail[:2000]})
    return seq


def _emit_ended(agent_did: str, sid: str, status_: str, end_reason: str, actions=None, budget_spent=None) -> None:
    """§DOCSFIX D6-527 (2026-10-16): PhoneSessionEnded for every end of a session (the agent's, the TTL's, a dead
    token's, an operator's kill, a global halt), with its status and reason. Only the agent's own end emitted it, so
    the other four left the ledger a PhoneSessionStarted with no end."""
    _emit_push("PhoneSessionEnded", agent_did, {
        "session_id": sid, "status": status_, "end_reason": end_reason, "actions": actions,
        "budget_spent": float(budget_spent) if budget_spent is not None else None})


def _emit_push(event_type: str, agent_did: str, data: dict) -> None:
    """Fire an audit event to the event store. Best-effort, never blocks."""
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(event_type=event_type, aggregate_id=agent_did, data=data)
    except Exception:  # noqa: BLE001
        logger.debug("[PHONE] emit %s skipped", event_type, exc_info=True)


async def _load_session(db: AsyncSession, sid: str, agent_did: str) -> dict:
    row = (await db.execute(text(
        "SELECT id, agent_did, capability_token_id, backend, instance_id, status, allowed_apps, "
        "max_actions, actions_used, no_screenshot, budget_currency, current_app, current_screen, expires_at "
        "FROM phone_sessions WHERE id = :s"
    ), {"s": sid})).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row["agent_did"] != agent_did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your session")
    if row["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Session is {row['status']}")
    # capability token still valid? (revoke_subtree flips it → kill the session live)
    tok = (await db.execute(text(
        "SELECT status, expires_at <= now() AS expired FROM agent_capability_tokens WHERE id = :i"
    ), {"i": row["capability_token_id"]})).first()
    if not tok or tok.status not in ("issued", "active") or tok.expired:
        await db.execute(text("UPDATE phone_sessions SET status='revoked', ended_at=now(), end_reason='token_revoked' WHERE id=:s"), {"s": sid})
        await db.commit()
        _emit_ended(row["agent_did"], sid, "revoked", "token_revoked", row["actions_used"])
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Capability token no longer valid — session revoked")
    exp = row["expires_at"]
    if exp and exp <= _dt.datetime.now(_dt.timezone.utc):
        await db.execute(text("UPDATE phone_sessions SET status='expired', ended_at=now(), end_reason='ttl' WHERE id=:s"), {"s": sid})
        await db.commit()
        _emit_ended(row["agent_did"], sid, "expired", "ttl", row["actions_used"])
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Session expired (ttl)")
    return dict(row)


# ── start ────────────────────────────────────────────────────────────────────
@router.post("/api/v1/phone/sessions", summary="Start a capability-gated phone session")
async def start_session(
    body: schemas.PhoneSessionStartIn,
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
    x_capability_token: Optional[str] = Header(None, alias="X-Capability-Token"),
):
    _require_enabled()
    cap = await _resolve_phone_cap(db, x_capability_token, agent.did)
    caveats = cap.get("caveats") or {}
    allowed_apps = caveats.get("phone_allowed_apps") or []
    max_actions = caveats.get("phone_max_actions")
    no_screenshot = bool(caveats.get("phone_no_screenshot"))
    # SEC-09: only an ABSENT lifetime takes the registry default. A token naming 0 was given the default too, longer than
    # any bound a parent token set on this axis (attenuation reads 0 as within it); a lifetime of 0 or less opens nothing.
    ttl_named = caveats.get("phone_ttl_seconds")
    ttl = int(ttl_named) if ttl_named is not None else int(os.getenv("PHONE_SESSION_TTL_DEFAULT", "600"))
    if ttl <= 0:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="phone_ttl_seconds caveat: this token's phone session lifetime is zero")
    # D6-523: a token that limits the network leases only a device whose network use the registry can check
    no_network, domains = _network_caveats(caveats)
    if (no_network or domains) and not hasattr(make_driver(_backend(), "probe"), "network_use"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=(
            "This registry's phone backend cannot apply phone_no_network or phone_allowed_domains, so a token that "
            "carries either opens no session here"))

    # concurrency cap
    cap_conc = int(os.getenv("PHONE_MAX_CONCURRENT_SESSIONS", "8"))
    live = (await db.execute(text("SELECT count(*) FROM phone_sessions WHERE status='active'"))).scalar() or 0
    if live >= cap_conc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Phone pool at capacity")

    backend = _backend()
    # lease an instance (mock = synthesize a handle; redroid pool would pick an idle row)
    handle = f"{backend}-{secrets.token_hex(4)}"
    inst = (await db.execute(text(
        "INSERT INTO phone_pool_instances (backend, handle, status, leased_by) VALUES (:b,:h,'leased','pending') RETURNING id"
    ), {"b": backend, "h": handle})).first()
    sid = "pfs_" + secrets.token_hex(12)
    exp = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=ttl)
    # cap the session ttl by the token's own expiry
    # (driver starts at home; optional launch below)
    driver = make_driver(backend, handle)
    await driver.reset()
    cur_app, cur_screen = driver.state if hasattr(driver, "state") else (None, None)

    await db.execute(text("""
        INSERT INTO phone_sessions (id, agent_did, capability_token_id, backend, instance_id, status,
            allowed_apps, max_actions, actions_used, no_screenshot, budget_currency, current_app, current_screen, expires_at)
        VALUES (:id,:ag,:tok,:be,:inst,'active',CAST(:aa AS JSONB),:ma,0,:ns,:cur,:capp,:cscr,:exp)
    """), {"id": sid, "ag": agent.did, "tok": cap["id"], "be": backend, "inst": inst.id,
           "aa": json.dumps(allowed_apps), "ma": max_actions, "ns": no_screenshot,
           "cur": cap.get("currency"), "capp": cur_app, "cscr": cur_screen, "exp": exp})
    await db.execute(text("UPDATE phone_pool_instances SET leased_by=:s WHERE id=:i"), {"s": sid, "i": inst.id})
    await _debit(db, cap["id"], _START_COST)
    await _audit(db, sid, "start", None, {"backend": backend, "allowed_apps": allowed_apps}, _START_COST, "ok")
    await db.commit()
    _emit_push("PhoneSessionStarted", agent.did, {"session_id": sid, "backend": backend, "allowed_apps": allowed_apps})
    logger.info("[PHONE] session %s started agent=%s token=%s backend=%s", sid, agent.did, cap["id"], backend)

    resp = {"session_id": sid, "backend": backend, "expires_at": exp.isoformat(),
            "allowed_apps": allowed_apps, "max_actions": max_actions, "budget_remaining": _rem(cap, _START_COST)}
    if body.launch:
        resp["launch"] = await _do_act(db, sid, agent.did, cap["id"], "launch", body.launch, None, allowed_apps,
                                       max_actions, backend, handle, caveats=caveats)
    return resp


def _rem(cap: dict, spent: Decimal):
    br = cap.get("budget_remaining")
    return float(Decimal(str(br)) - spent) if br is not None else None


# ── act ──────────────────────────────────────────────────────────────────────
@router.post("/api/v1/phone/sessions/{sid}/act", summary="Perform one metered, caveat-checked action")
async def act(
    sid: str,
    body: schemas.PhoneActIn,
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
    x_capability_token: Optional[str] = Header(None, alias="X-Capability-Token"),
):
    _require_enabled()
    cap = await _resolve_phone_cap(db, x_capability_token, agent.did)
    s = await _load_session(db, sid, agent.did)
    if s["capability_token_id"] != cap["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Token does not match this session")
    return await _do_act(db, sid, agent.did, cap["id"], body.type, body.target, body.text,
                         s["allowed_apps"] or [], s["max_actions"], s["backend"],
                         _handle_for(db, s), s=s, caveats=cap.get("caveats"))


def _handle_for(db, s):  # instance handle isn't stored per-request for mock; recompute deterministically
    return f"{s['backend']}-restored"


def _network_caveats(caveats: Optional[dict]) -> tuple:
    """D6-523: (phone_no_network, phone_allowed_domains as lower-case hosts) of a phone token's caveats."""
    c = caveats or {}
    domains = [str(d).strip().lower().rstrip(".") for d in (c.get("phone_allowed_domains") or []) if str(d).strip()]
    return bool(c.get("phone_no_network")), domains


async def _do_act(db, sid, agent_did, token_id, action_type, target, text_arg,
                  allowed_apps, max_actions, backend, handle, s=None, caveats=None):
    # action ceiling
    if s is not None and max_actions is not None and s["actions_used"] >= max_actions:
        await _audit(db, sid, action_type, target, None, Decimal(0), "denied", "max_actions")
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="max_actions caveat reached")
    # app allowlist (launch / tapping an app icon)
    launch_pkg = target if action_type == "launch" else (
        target.split(":", 1)[1] if action_type == "tap" and (target or "").startswith("icon:") else None)
    if launch_pkg is not None and allowed_apps and launch_pkg not in allowed_apps:
        await _audit(db, sid, action_type, target, None, Decimal(0), "denied", f"app_not_allowed:{launch_pkg}")
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=f"App {launch_pkg} not in caveat allowlist")

    driver = make_driver(backend, handle)
    if s is not None and hasattr(driver, "restore"):
        driver.restore(s.get("current_app"), s.get("current_screen"))
    # D6-523: the lease's network (phone_no_network, phone_allowed_domains), asked of the device BEFORE the action runs.
    # An action whose network use the device cannot report, or whose address it cannot name, counts as reaching the
    # network at an address outside any list.
    no_network, domains = _network_caveats(caveats)
    if no_network or domains:
        use = driver.network_use(action_type, target=target, text=text_arg) if hasattr(driver, "network_use") else ""
        if use is not None:
            host = str(use).strip().lower().rstrip(".")
            if no_network:
                why, detail = "network_blocked", "phone_no_network caveat: this action would reach the network"
            elif host not in domains:
                why = f"domain_not_allowed:{host or 'unknown'}"
                detail = (f"phone_allowed_domains caveat: {host or 'the address this action would reach'} "
                          "is not on the token's list")
            else:
                why = None
            if why:
                # the trace row takes the session's next number itself (D6-528)
                await _audit(db, sid, action_type, target, None, Decimal(0), "denied", why)
                await db.commit()
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)
    result = await driver.act(action_type, target=target, text=text_arg)
    new_app, new_screen = driver.state if hasattr(driver, "state") else (result.package, result.screen)

    await _debit(db, token_id, _ACTION_COST)
    await db.execute(text(
        "UPDATE phone_sessions SET actions_used=actions_used+1, current_app=:a, current_screen=:sc, "
        "budget_spent=budget_spent+:c WHERE id=:s"
    ), {"a": new_app, "sc": new_screen, "c": _ACTION_COST, "s": sid})
    seq = await _audit(db, sid, action_type, target, {"text": bool(text_arg)}, _ACTION_COST,
                       "ok" if result.ok else "error", result.detail)
    await db.commit()
    return {"ok": result.ok, "package": new_app, "screen": new_screen, "detail": result.detail, "seq": seq}


# ── observe ──────────────────────────────────────────────────────────────────
@router.get("/api/v1/phone/sessions/{sid}/observe", summary="Read the accessibility tree")
async def observe(
    sid: str,
    screenshot: bool = False,
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
    x_capability_token: Optional[str] = Header(None, alias="X-Capability-Token"),
):
    _require_enabled()
    cap = await _resolve_phone_cap(db, x_capability_token, agent.did)
    s = await _load_session(db, sid, agent.did)
    if s["capability_token_id"] != cap["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Token does not match this session")
    want_shot = bool(screenshot) and not s["no_screenshot"]
    driver = make_driver(s["backend"], f"{s['backend']}-restored")
    if hasattr(driver, "restore"):
        driver.restore(s.get("current_app"), s.get("current_screen"))
    obs = await driver.observe(want_screenshot=want_shot)
    await _debit(db, cap["id"], _ACTION_COST)
    await db.execute(text("UPDATE phone_sessions SET budget_spent=budget_spent+:c WHERE id=:s"), {"c": _ACTION_COST, "s": sid})
    await _audit(db, sid, "observe", None, {"screenshot": want_shot}, _ACTION_COST, "ok")
    await db.commit()

    def node(n):
        return {"id": n.id, "role": n.role, "text": n.text, "package": n.package,
                "tappable": n.tappable, "editable": n.editable,
                "children": [node(c) for c in n.children]}
    return {"package": obs.package, "screen": obs.screen, "tree": node(obs.tree),
            "screenshot": obs.screenshot_b64 if want_shot else None,
            "screenshot_blocked": bool(s["no_screenshot"])}


# ── end ──────────────────────────────────────────────────────────────────────
@router.post("/api/v1/phone/sessions/{sid}/end", summary="End + release a session")
async def end_session(
    sid: str,
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    row = (await db.execute(text("SELECT agent_did, status, instance_id, actions_used, budget_spent FROM phone_sessions WHERE id=:s"), {"s": sid})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row.agent_did != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your session")
    if row.status == "active":
        await db.execute(text("UPDATE phone_sessions SET status='ended', ended_at=now(), end_reason='agent' WHERE id=:s"), {"s": sid})
        await db.execute(text("UPDATE phone_pool_instances SET status='idle', leased_by=NULL WHERE id=:i"), {"i": row.instance_id})
        await _audit(db, sid, "end", None, None, Decimal(0), "ok", "agent-ended")
        await db.commit()
        _emit_ended(agent.did, sid, "ended", "agent", row.actions_used, row.budget_spent)
    return {"ok": True, "session_id": sid, "actions": row.actions_used, "budget_spent": float(row.budget_spent), "status": "ended"}


@router.get("/api/v1/phone/sessions/mine", summary="My phone sessions")
async def my_sessions(
    agent: models.Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    rows = (await db.execute(text(
        "SELECT id, backend, status, current_app, current_screen, actions_used, budget_spent, "
        "started_at, expires_at, ended_at, end_reason FROM phone_sessions "
        "WHERE agent_did=:a ORDER BY started_at DESC LIMIT 50"
    ), {"a": agent.did})).mappings().all()
    return {"sessions": [dict(r) for r in rows], "total": len(rows)}


# ── admin ────────────────────────────────────────────────────────────────────
def _require_admin(dev: models.Developer):
    # D6-529: the presented credential's authority, not the account's flag alone (security.admin_credential, which the
    # other inline admin checks ask since §POCKETPAIR): a scoped API key without 'mcp:admin' (a paired phone's, an MCP
    # OAuth client's) is no admin credential, and REQUIRE_ADMIN_2FA binds every credential.
    if not admin_credential(dev):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.get("/api/v1/admin/phone/sessions", summary="All phone sessions (admin)")
async def admin_sessions(dev: models.Developer = Depends(get_current_developer), db: AsyncSession = Depends(get_db)):
    _require_admin(dev)
    rows = (await db.execute(text(
        "SELECT id, agent_did, backend, status, actions_used, budget_spent, current_app, started_at, ended_at, end_reason "
        "FROM phone_sessions ORDER BY started_at DESC LIMIT 200"
    ))).mappings().all()
    return {"sessions": [dict(r) for r in rows], "total": len(rows),
            "enabled": phone_fabric_enabled(), "backend": _backend(), "mode": phone_use_mode()}


@router.get("/api/v1/admin/phone/pool", summary="Phone pool status (admin)")
async def admin_pool(dev: models.Developer = Depends(get_current_developer), db: AsyncSession = Depends(get_db)):
    _require_admin(dev)
    rows = (await db.execute(text("SELECT id, backend, handle, status, leased_by, last_seen_at FROM phone_pool_instances ORDER BY id DESC LIMIT 100"))).mappings().all()
    active = (await db.execute(text("SELECT count(*) FROM phone_sessions WHERE status='active'"))).scalar() or 0
    return {"instances": [dict(r) for r in rows], "active_sessions": active,
            "max_concurrent": int(os.getenv("PHONE_MAX_CONCURRENT_SESSIONS", "8"))}


@router.post("/api/v1/admin/phone/global-halt", summary="Kill every active phone session (admin)")
async def admin_global_halt(dev: models.Developer = Depends(get_current_developer), db: AsyncSession = Depends(get_db)):
    _require_admin(dev)
    halted = (await db.execute(text(
        "UPDATE phone_sessions SET status='ended', ended_at=now(), end_reason='global_halt' WHERE status='active' "
        "RETURNING id, agent_did, actions_used, budget_spent"
    ))).fetchall()
    n = len(halted)
    await db.execute(text("UPDATE phone_pool_instances SET status='idle', leased_by=NULL WHERE status='leased'"))
    await db.commit()
    for h in halted:
        _emit_ended(h.agent_did, h.id, "ended", "global_halt", h.actions_used, h.budget_spent)
    logger.warning("[PHONE] GLOBAL HALT by dev=%s — %s sessions killed", dev.id, n)
    return {"ok": True, "halted": n}


@router.post("/api/v1/admin/phone/sessions/{sid}/kill", summary="End ONE active phone session (admin)")
async def admin_kill_session(sid: str, dev: models.Developer = Depends(get_current_developer), db: AsyncSession = Depends(get_db)):
    """Status-only kill of a single session + release its instance. Δ-neutral. The oversight
    KILL button — surgical alternative to global-halt when only one agent needs stopping."""
    _require_admin(dev)
    row = (await db.execute(text(
        "SELECT status, instance_id, actions_used, agent_did, budget_spent FROM phone_sessions WHERE id=:s"
    ), {"s": sid})).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row.status != "active":
        return {"ok": True, "session_id": sid, "status": row.status, "already_terminal": True}
    await db.execute(text(
        "UPDATE phone_sessions SET status='revoked', ended_at=now(), end_reason='admin_kill' WHERE id=:s"
    ), {"s": sid})
    await db.execute(text("UPDATE phone_pool_instances SET status='idle', leased_by=NULL WHERE id=:i"), {"i": row.instance_id})
    await _audit(db, sid, "end", None, None, Decimal(0), "ok", f"admin-kill by dev={dev.id}")
    await db.commit()
    _emit_ended(row.agent_did, sid, "revoked", "admin_kill", row.actions_used, row.budget_spent)
    logger.warning("[PHONE] session %s killed by dev=%s", sid, dev.id)
    return {"ok": True, "session_id": sid, "status": "revoked"}


@router.get("/api/v1/admin/phone/sessions/{sid}/actions", summary="Action trace for a session (admin)")
async def admin_session_actions(sid: str, dev: models.Developer = Depends(get_current_developer), db: AsyncSession = Depends(get_db)):
    """Append-only per-action audit trace — powers the console's live action viewer."""
    _require_admin(dev)
    head = (await db.execute(text(
        "SELECT id, agent_did, backend, status, actions_used, budget_spent, budget_currency, "
        "current_app, current_screen, allowed_apps, max_actions, no_screenshot, started_at, expires_at, ended_at, end_reason "
        "FROM phone_sessions WHERE id=:s"
    ), {"s": sid})).mappings().first()
    if not head:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    rows = (await db.execute(text(
        "SELECT seq, action_type, target, cost, outcome, detail, created_at "
        "FROM phone_session_actions WHERE session_id=:s ORDER BY seq ASC LIMIT 500"
    ), {"s": sid})).mappings().all()
    return {"session": dict(head), "actions": [dict(r) for r in rows], "total": len(rows)}
