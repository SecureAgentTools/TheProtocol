"""§FRAMEMAIL-5 — fleet-wide mail observability + control, on the node that holds the creds.

WHY THIS EXISTS. On 2026-08-01 an audit found **14 of 15 cloud operators** promising email
verification while pointing at the placeholder `smtp.example.com`: every self-registered account was
permanently unverifiable, and the only remedy existed in no frontend. That state had been live for
weeks and was invisible — nobody could see it without shelling into containers and reading env vars.
The Commander's words: *"without it i am blind actually."*

So this view answers, for every node in the cluster, the two questions that actually matter:

    1. Does it demand email verification?
    2. Can it actually send email?

**A node that answers yes/no to those is broken**, and that combination has a name here: the
§OPGUIDE-2 lockout. This surfaces it as a first-class verdict instead of leaving it to be discovered.

**How the data is gathered, and why it needs no fleet roll.** Node posture is read from each node's
OWN public `GET /api/v1/auth/registration-config`, which every registry already serves. That is
deliberate on two counts: it needs no new endpoint deployed fleet-wide, and it reports what the node
*actually tells a prospective user*, not what our config files believe about it. If those two ever
disagree, the node's own answer is the truth and this view shows the truth.

Send capability is resolved locally: this registry knows which nodes it handed the shared token to,
and which ones relay through it (`MAIL_RELAY_CALLERS`). Relay volume and denials come from
`security_audit_logs`, which the relay already writes on every attempt.

**Why it is gated to this node.** The shared submission token and the relay allowlist live here.
A node that holds neither has nothing to show and no business showing it, so the whole router 404s
there rather than rendering an empty console that looks broken.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Security, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models, security
from agentvault_registry.config import settings
from agentvault_registry.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mail", tags=["Admin — Mail Fleet"])

_PROBE_TIMEOUT = 8.0
_PROBE_PATH = "/api/v1/auth/registration-config"


# ---------------------------------------------------------------------------
# Gate — this console belongs on the node that holds the credentials.
# ---------------------------------------------------------------------------

def _manages_mail() -> bool:
    return bool(
        (os.getenv("OPERATOR_MAIL_PASSWORD") or "").strip()
        or (os.getenv("MAIL_RELAY_CALLERS") or "").strip()
    )


async def require_mail_authority(
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
) -> models.Developer:
    """Admin AND this-node-holds-the-creds.

    404 rather than 403 when the node manages no mail: on a node that legitimately
    has nothing to manage this is not a permission problem, and a 403 would read as
    "you are missing a flag" and send someone hunting for one that does not exist.
    """
    if not _manages_mail():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This registry does not manage fleet mail credentials.",
        )
    return admin


# ---------------------------------------------------------------------------
# Shared sender + relay configuration (never the secret itself)
# ---------------------------------------------------------------------------

def _relay_callers() -> dict:
    raw = (os.getenv("MAIL_RELAY_CALLERS") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _public_host(base_url: Optional[str]) -> Optional[str]:
    """Public origin for a peer, from its federation base_url.

    Federation URLs carry the mTLS port (`:8443`); the human-facing API is on 443.
    Stripping the port is what makes the public posture probe reachable.
    """
    if not base_url:
        return None
    try:
        p = urlparse(base_url if "//" in base_url else f"https://{base_url}")
        host = p.hostname
        if not host:
            return None
        return f"https://{host}"
    except Exception:  # noqa: BLE001
        return None


class SenderInfo(BaseModel):
    from_address: Optional[str] = None
    from_name: Optional[str] = None
    server: Optional[str] = None
    port: Optional[int] = None
    credential_present: bool = False
    relay_enabled: bool = False
    relay_callers: list[dict] = Field(default_factory=list)
    max_per_hour: Optional[int] = None
    max_recipients_per_day: Optional[int] = None


@router.get("/sender", response_model=SenderInfo, summary="Shared sender identity + relay config")
async def get_sender(_admin=Depends(require_mail_authority)):
    """Everything about how this node sends, except the token. Presence, never value."""
    callers = [
        {"key": k, "base_url": (v or {}).get("base_url"), "label": (v or {}).get("label") or k}
        for k, v in _relay_callers().items()
        if isinstance(v, dict)
    ]
    return SenderInfo(
        from_address=os.getenv("OPERATOR_MAIL_FROM") or settings.MAIL_FROM,
        from_name=os.getenv("OPERATOR_MAIL_FROM_NAME") or settings.MAIL_FROM_NAME,
        server=os.getenv("OPERATOR_MAIL_SERVER") or settings.MAIL_SERVER,
        port=int(os.getenv("OPERATOR_MAIL_PORT") or settings.MAIL_PORT or 587),
        credential_present=bool((os.getenv("OPERATOR_MAIL_PASSWORD") or settings.MAIL_PASSWORD or "").strip()),
        relay_enabled=(os.getenv("MAIL_RELAY_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on"),
        relay_callers=sorted(callers, key=lambda c: c["key"]),
        max_per_hour=int(os.getenv("MAIL_RELAY_MAX_PER_HOUR") or 60),
        max_recipients_per_day=int(os.getenv("MAIL_RELAY_MAX_RECIPIENTS_PER_DAY") or 200),
    )


# ---------------------------------------------------------------------------
# Fleet posture
# ---------------------------------------------------------------------------

class NodeMailStatus(BaseModel):
    name: str
    kind: str                      # self | frame | operator
    public_url: Optional[str] = None
    reachable: bool = False
    verification_required: Optional[bool] = None
    invite_required: Optional[bool] = None
    send_path: str = "unknown"     # direct | relay | none | unknown
    verdict: str = "UNKNOWN"       # OK | LOCKOUT | UNGATED | UNREACHABLE | UNKNOWN
    detail: Optional[str] = None
    peer_status: Optional[str] = None


def _verdict(reachable: bool, verify: Optional[bool], invite: Optional[bool], send: str) -> tuple[str, str]:
    if not reachable:
        # Deliberately NOT "OK": a node we cannot ask is a node whose posture we do
        # not know, and reporting unknown as fine is how the original defect survived.
        return "UNREACHABLE", "Could not read this node's own registration-config."
    # (INACTIVE is decided before we ever probe — see fleet_status.)
    if verify and send == "none":
        return "LOCKOUT", (
            "Demands email verification but has no way to send it — every self-registered "
            "account here is permanently unverifiable (§OPGUIDE-2)."
        )
    if not verify and not invite:
        return "UNGATED", "Neither email verification nor invite codes — registration is open to anyone."
    if verify and send in ("direct", "relay"):
        return "OK", f"Verification enforced, mail sends {send}."
    if not verify and invite:
        return "OK", "Verification off, but registration is gated by invite codes."
    return "UNKNOWN", "Could not classify."


async def _probe(client, node: dict) -> NodeMailStatus:
    st = NodeMailStatus(
        name=node["name"], kind=node["kind"], public_url=node["public_url"],
        send_path=node["send_path"], peer_status=node.get("peer_status"),
    )
    # A peer that was deliberately deactivated is not expected to answer. Probing it
    # and then reporting UNREACHABLE is a category error: it turns an intended state
    # into a warning, and puts a TLS failure for a host that stopped serving weeks ago
    # on screen as though something were broken. Decommissioned is not degraded.
    if (node.get("peer_status") or "").upper() not in ("", "ACTIVE"):
        st.verdict = "INACTIVE"
        st.detail = "Peer is deactivated; not expected to serve. Not probed."
        return st
    if not st.public_url:
        st.verdict, st.detail = "UNKNOWN", "No public URL known for this node."
        return st
    try:
        r = await client.get(st.public_url + _PROBE_PATH, timeout=_PROBE_TIMEOUT)
        if r.status_code == 200:
            d = r.json()
            st.reachable = True
            st.verification_required = bool(d.get("email_verification_required"))
            st.invite_required = bool(d.get("beta_invite_required"))
        else:
            st.detail = f"registration-config returned HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        st.detail = f"{type(exc).__name__}: {str(exc)[:120]}"
    v, why = _verdict(st.reachable, st.verification_required, st.invite_required, st.send_path)
    st.verdict = v
    st.detail = st.detail or why if v == "UNREACHABLE" else why
    return st


@router.get("/fleet", summary="Mail posture for every node in the cluster")
async def fleet_status(_admin=Depends(require_mail_authority), db: AsyncSession = Depends(get_db)):
    """Per-node: does it demand verification, and can it actually send?

    Posture comes from each node's OWN public endpoint, so this reports what the node
    tells a real user rather than what our config believes.
    """
    callers = _relay_callers()
    relay_hosts = {
        (c or {}).get("base_url", "").rstrip("/")
        for c in callers.values() if isinstance(c, dict)
    }

    nodes: list[dict] = [{
        "name": os.getenv("REGISTRY_FEDERATION_NAME") or "this registry",
        "kind": "self",
        "public_url": (str(settings.BASE_URL).rstrip("/") if settings.BASE_URL else None),
        "send_path": "direct" if (settings.MAIL_SERVER and settings.MAIL_PASSWORD) else "none",
        "peer_status": None,
    }]

    seen_hosts = {n["public_url"].rstrip("/") for n in nodes if n["public_url"]}

    rows = (await db.execute(text(
        "SELECT name, status, base_url, peer_type FROM peer_registries ORDER BY name"
    ))).fetchall()
    for name, pstatus, base_url, peer_type in rows:
        pub = _public_host(base_url)
        # A node in the relay allowlist sends through us and holds no token; anything
        # else we provisioned carries the shared credential directly.
        send = "relay" if (pub and pub.rstrip("/") in relay_hosts) else "direct"
        if pub:
            seen_hosts.add(pub.rstrip("/"))
        nodes.append({
            "name": name,
            "kind": "frame" if (peer_type or "").lower() in ("frame", "mainframe") else "operator",
            "public_url": pub,
            "send_path": send,
            "peer_status": pstatus,
        })

    # Relay callers that are NOT federation peers of this registry. The two
    # handed-over nodes live on a separate tier and appear in no peer row, so a
    # peers-only inventory silently omits exactly the nodes whose mail posture is
    # most worth watching — they are the ones that cannot send without us.
    for key, entry in callers.items():
        if not isinstance(entry, dict):
            continue
        base = str(entry.get("base_url") or "").rstrip("/")
        if not base or base in seen_hosts:
            continue
        seen_hosts.add(base)
        nodes.append({
            "name": entry.get("label") or key,
            "kind": "operator",
            "public_url": base,
            "send_path": "relay",
            "peer_status": None,
        })

    import httpx

    verify_ctx = ssl.create_default_context()
    async with httpx.AsyncClient(verify=verify_ctx, follow_redirects=True) as client:
        results = await asyncio.gather(*[_probe(client, n) for n in nodes], return_exceptions=True)

    out: list[NodeMailStatus] = []
    for n, r in zip(nodes, results):
        if isinstance(r, Exception):
            out.append(NodeMailStatus(
                name=n["name"], kind=n["kind"], public_url=n["public_url"],
                send_path=n["send_path"], verdict="UNREACHABLE",
                detail=f"probe failed: {type(r).__name__}", peer_status=n.get("peer_status"),
            ))
        else:
            out.append(r)

    counts: dict[str, int] = {}
    for s in out:
        counts[s.verdict] = counts.get(s.verdict, 0) + 1
    return {
        "summary": {
            "total": len(out),
            "ok": counts.get("OK", 0),
            "lockout": counts.get("LOCKOUT", 0),
            "ungated": counts.get("UNGATED", 0),
            "unreachable": counts.get("UNREACHABLE", 0),
            # Reported for completeness but never treated as a problem: a deactivated
            # peer is in the state an operator chose for it.
            "inactive": counts.get("INACTIVE", 0),
            "unknown": counts.get("UNKNOWN", 0),
            "healthy": counts.get("LOCKOUT", 0) == 0 and counts.get("UNGATED", 0) == 0
                       and counts.get("UNREACHABLE", 0) == 0,
        },
        "nodes": [s.model_dump() for s in out],
    }


# ---------------------------------------------------------------------------
# Relay activity — read straight off the audit trail the relay already writes
# ---------------------------------------------------------------------------

@router.get("/relay-activity", summary="Recent relay sends and refusals")
async def relay_activity(
    limit: int = 50,
    _admin=Depends(require_mail_authority),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(int(limit or 50), 200))
    rows = (await db.execute(text(
        """
        SELECT timestamp, actor_id, target_id, outcome, details
        FROM security_audit_logs
        WHERE target_type = 'mail_relay'
        ORDER BY timestamp DESC
        LIMIT :lim
        """
    ), {"lim": limit})).fetchall()

    events = []
    for ts, actor, target, outcome, details in rows:
        reason = None
        try:
            reason = (json.loads(details) or {}).get("reason") or None
        except Exception:  # noqa: BLE001
            pass
        template = (target or "").split(":")[0] or None
        events.append({
            "at": ts.isoformat() if ts else None,
            "caller": actor,
            "template": template,
            "outcome": outcome,
            "reason": reason,
            # The address itself is never stored — only this hash. Shown so an
            # operator can correlate repeat sends without the console leaking inboxes.
            "recipient_hash": (target or "").split(":")[-1] if ":" in (target or "") else None,
        })

    agg = (await db.execute(text(
        """
        SELECT actor_id, outcome, COUNT(*) FROM security_audit_logs
        WHERE target_type = 'mail_relay' AND timestamp > NOW() - INTERVAL '24 hours'
        GROUP BY actor_id, outcome
        """
    ))).fetchall()
    per_caller: dict[str, dict] = {}
    for actor, outcome, cnt in agg:
        e = per_caller.setdefault(actor or "?", {"caller": actor, "success": 0, "denied": 0, "failure": 0})
        if outcome in e:
            e[outcome] = cnt
    return {"events": events, "last_24h": sorted(per_caller.values(), key=lambda x: x["caller"] or "")}


# ---------------------------------------------------------------------------
# Control surface
# ---------------------------------------------------------------------------

class TestSendRequest(BaseModel):
    recipient: EmailStr
    note: Optional[str] = Field(default=None, max_length=200)


@router.post("/verify-credential", summary="Prove the submission credential still authenticates")
async def verify_credential(_admin=Depends(require_mail_authority)):
    """Opens a real SMTP session and authenticates. Sends nothing.

    Worth having as its own button: a token that has been revoked or rotated upstream
    looks identical to a working one in any config view. Only an AUTH proves it.
    """
    server = os.getenv("OPERATOR_MAIL_SERVER") or settings.MAIL_SERVER
    port = int(os.getenv("OPERATOR_MAIL_PORT") or settings.MAIL_PORT or 587)
    user = os.getenv("OPERATOR_MAIL_USERNAME") or settings.MAIL_USERNAME
    pw = os.getenv("OPERATOR_MAIL_PASSWORD") or settings.MAIL_PASSWORD
    if not (server and user and pw):
        raise HTTPException(status_code=400, detail="No submission credential configured on this node.")

    def _check():
        import smtplib
        s = smtplib.SMTP(server, port, timeout=20)
        try:
            s.starttls(context=ssl.create_default_context())
            s.login(user, pw)
        finally:
            try:
                s.quit()
            except Exception:  # noqa: BLE001
                pass

    try:
        await asyncio.to_thread(_check)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[mail-fleet] credential check FAILED: %s", exc)
        return {"ok": False, "server": server, "port": port, "username": user,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"ok": True, "server": server, "port": port, "username": user}


@router.post("/test-send", summary="Send a real test email from the shared sender")
async def test_send(
    payload: TestSendRequest = Body(...),
    admin: models.Developer = Depends(require_mail_authority),
):
    """A real delivery, not a render. The whole point is to exercise SMTP end to end."""
    from agentvault_registry.email_utils import send_themed_email

    ok = await send_themed_email(
        subject="TheProtocol — mail system test",
        recipients=[str(payload.recipient)],
        template="admin_notice",
        context={
            "title": "Mail system test",
            "message": (
                payload.note
                or "This is a test message from the TheProtocol mail console. "
                   "If you are reading it, the shared sender is delivering correctly."
            ),
            "actor": admin.email,
        },
        theme="neural",
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Send failed — check registry logs for the SMTP error.")
    return {"ok": True, "recipient": str(payload.recipient)}


@router.post("/relay-callers/{operator_did}/revoke", summary="Revoke a node's ability to relay mail")
async def revoke_relay_caller(
    operator_did: str,
    _admin=Depends(require_mail_authority),
    db: AsyncSession = Depends(get_db),
):
    """Instant kill switch for one node's relay, with no deploy.

    Flips the federation license to `revoked`. The relay re-checks license status on
    EVERY call, so this bites on the next request rather than at the next restart.
    """
    res = await db.execute(text(
        "UPDATE federation_licenses SET status='revoked', revoked_at=NOW(), "
        "revoked_reason='mail relay revoked from admin console' "
        "WHERE operator_did=:d AND status='active' RETURNING operator_name"
    ), {"d": operator_did})
    row = res.fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="No active license for that operator_did.")
    logger.warning("[mail-fleet] relay REVOKED for %s", operator_did)
    return {"ok": True, "operator_did": operator_did, "status": "revoked"}


@router.post("/relay-callers/{operator_did}/reinstate", summary="Restore a node's relay access")
async def reinstate_relay_caller(
    operator_did: str,
    _admin=Depends(require_mail_authority),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(text(
        "UPDATE federation_licenses SET status='active', revoked_at=NULL, revoked_reason=NULL "
        "WHERE operator_did=:d AND status<>'active' RETURNING operator_name"
    ), {"d": operator_did})
    row = res.fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="No inactive license for that operator_did.")
    logger.warning("[mail-fleet] relay REINSTATED for %s", operator_did)
    return {"ok": True, "operator_did": operator_did, "status": "active"}


@router.get("/relay-licenses", summary="Relay licenses and their live status")
async def relay_licenses(_admin=Depends(require_mail_authority), db: AsyncSession = Depends(get_db)):
    callers = _relay_callers()
    rows = (await db.execute(text(
        "SELECT operator_did, operator_name, status, issued_at, last_seen_at "
        "FROM federation_licenses ORDER BY operator_name"
    ))).fetchall()
    out = []
    for did, name, lic_status, issued, last_seen in rows:
        entry = callers.get(did) or callers.get(name)
        if not entry:
            continue  # only licenses that are actually allow-listed for mail relay
        out.append({
            "operator_did": did,
            "operator_name": name,
            "status": lic_status,
            "issued_at": issued.isoformat() if issued else None,
            "last_seen_at": last_seen.isoformat() if last_seen else None,
            "base_url": (entry or {}).get("base_url"),
            "label": (entry or {}).get("label") or name,
        })
    return {"licenses": out}
