"""§HELLOFRAME: the frame kit, the applicant's own page for a frame they run themselves (his word 2026-09-19: "build it
behind the flag, off by default").

    GET  /api/v1/frame-kit/me                      the caller's frame requests, each with its kit window and progress,
                                                    the kit release this frame publishes, and the network to join
    POST /api/v1/frame-kit/me/{request_id}/link    a single-use download link, valid five minutes
    GET  /api/v1/frame-kit/download?token=...      the kit itself, for that link

Off unless FRAME_KIT_ENABLED is true: every route answers 404 with one sentence, and the console hides the page (the
public registry-config field `frame_kit_enabled`, the router guard and the sidebar read the same flag).

What the kit is: one release of the open-source export, published by an operator of THIS frame into FRAME_KIT_DIR
(default /app/frame-kit, a read-only mount) as `manifest.json` beside one `*.tar.gz` (scripts/frame_kit/publish.py
writes both, the manifest last). The registry never builds or signs the kit; it serves the file the manifest names after
checking that the file is there and its size matches the manifest. The applicant checks the sha256 the page shows.

Who may download: the developer who asked for the frame. That is the request's `developer_id`, or a VERIFIED developer
whose email is the request's contact email, because the intake writes the row before it creates the account. Only a
SELF-HOSTED request the admin APPROVED, within FRAME_KIT_WINDOW_DAYS of the approval and FRAME_KIT_MAX_DOWNLOADS
downloads; approving again in Frame Management opens a new window.

Why a link and not the bearer: a 300 MB file belongs in the browser's own download manager, which cannot carry an
Authorization header. The page asks for a link with the bearer; the link carries a random token that works ONCE, for
five minutes, and names the request and the developer it was made for. Redis holds only the token's digest.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.middleware.rate_limiter import shared_limiter as limiter
from agentvault_registry.security import get_current_developer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Frame Kit"], dependencies=[Depends(require_mainframe_only)])

OFF_SENTENCE = "The frame kit is not offered on this frame."
LINK_TTL_S = 300
_TOKEN_PREFIX = "framekit:dl:"
_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.tar\.gz")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

# One sentence per closed window, in the product's voice: what is true, and what to do about it.
WINDOW_SENTENCES = {
    "not_self_hosted": "This request is for a frame we host, so there is no kit to download.",
    "rejected": "This request was not approved, so the kit stays closed.",
    "locked": "The kit opens when your request is approved.",
    "expired": "The download window for this request has closed. Reply to your approval mail for a new one.",
    "exhausted": "This request has used all of its downloads. Reply to your approval mail for a new window.",
    "unpublished": "No kit is published on this frame yet. It appears here as soon as it is.",
}


# ── configuration ──────────────────────────────────────────────────────────────────────────────────────────────────

def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def frame_kit_enabled() -> bool:
    return _truthy(os.getenv("FRAME_KIT_ENABLED"))


def kit_dir() -> Path:
    return Path(os.getenv("FRAME_KIT_DIR", "/app/frame-kit"))


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int((os.getenv(name) or str(default)).strip())
    except ValueError:
        value = default
    return max(lo, min(hi, value))


def max_downloads() -> int:
    return _int_env("FRAME_KIT_MAX_DOWNLOADS", 5, 1, 100)


def window_days() -> int:
    return _int_env("FRAME_KIT_WINDOW_DAYS", 30, 1, 365)


def _require_enabled() -> None:
    if not frame_kit_enabled():
        raise HTTPException(status_code=404, detail=OFF_SENTENCE)


# ── the published kit ──────────────────────────────────────────────────────────────────────────────────────────────

def load_release(directory: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    """The kit this frame publishes, or None and the reason. `manifest.json` names ONE plain `*.tar.gz` in the same
    directory; the file must be there and its size must match the manifest (a copy cut short is not a kit)."""
    try:
        doc = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "no kit is published on this frame yet"
    except (OSError, ValueError) as exc:
        return None, f"the kit manifest is unreadable ({type(exc).__name__})"
    if not isinstance(doc, dict):
        return None, "the kit manifest is not an object"
    filename = str(doc.get("filename") or "")
    if not _FILENAME_RE.fullmatch(filename):
        return None, "the kit manifest names no plain .tar.gz file"
    sha256 = str(doc.get("sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(sha256):
        return None, "the kit manifest carries no sha256"
    try:
        size = int(doc.get("size_bytes"))
    except (TypeError, ValueError):
        return None, "the kit manifest carries no size"
    path = directory / filename
    try:
        actual = path.stat().st_size
    except OSError:
        return None, "the kit file the manifest names is not on this frame"
    if actual != size:
        return None, "the kit file's size does not match its manifest"
    return {
        "name": str(doc.get("name") or "theprotocol-frame-kit"),
        "version": str(doc.get("version") or ""),
        "filename": filename,
        "size_bytes": size,
        "sha256": sha256,
        "published_at": str(doc.get("published_at") or ""),
        "top_dir": str(doc.get("top_dir") or filename[: -len(".tar.gz")]),
        "path": str(path),
    }, ""


def public_release(release: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {k: v for k, v in release.items() if k != "path"} if release else None


# ── one request, as its applicant sees it ──────────────────────────────────────────────────────────────────────────

def _answers(row: Any) -> Dict[str, Any]:
    return row.answers if isinstance(getattr(row, "answers", None), dict) else {}


def _group(row: Any, name: str) -> Dict[str, Any]:
    value = _answers(row).get(name)
    return value if isinstance(value, dict) else {}


def hosting_of(row: Any) -> Optional[str]:
    """Where the frame runs, as the applicant answered: `self` (their infrastructure) or `theprotocol` (we host it).
    None on a row stored before the form asked."""
    hosting = _group(row, "provisioning").get("hosting")
    return hosting if hosting in ("self", "theprotocol") else None


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def is_owner(row: Any, developer: Any) -> bool:
    """The Python twin of `owner_clause`, for a row loaded by id."""
    if row.developer_id is not None and row.developer_id == getattr(developer, "id", None):
        return True
    email = (getattr(developer, "email", "") or "").strip().lower()
    return bool(email) and bool(getattr(developer, "is_verified", False)) and (row.contact_email or "").strip().lower() == email


def owner_clause(developer: Any):
    """Rows this developer asked for: by id, or by contact email when the developer's email is verified."""
    conditions = [models.FrameRequest.developer_id == developer.id]
    email = (getattr(developer, "email", "") or "").strip().lower()
    if email and getattr(developer, "is_verified", False):
        conditions.append(func.lower(models.FrameRequest.contact_email) == email)
    return or_(*conditions)


def kit_window(row: Any, release: Optional[Dict[str, Any]], now: datetime, *, days: int, limit: int) -> Dict[str, Any]:
    """Whether this request may download the kit now, and why not. Order matters: the reason a person can act on first."""
    used = int(row.kit_download_count or 0)
    approved_at = row.kit_approved_at
    until = approved_at + timedelta(days=days) if approved_at else None
    if hosting_of(row) != "self":
        state = "not_self_hosted"
    elif row.status == "rejected":
        state = "rejected"
    elif row.status not in ("approved", "provisioned") or approved_at is None:
        state = "locked"
    elif until is not None and now > until:
        state = "expired"
    elif used >= limit:
        state = "exhausted"
    elif release is None:
        state = "unpublished"
    else:
        state = "ready"
    return {
        "state": state,
        "sentence": WINDOW_SENTENCES.get(state),
        "downloads_used": used,
        "downloads_max": limit,
        "available_until": until,
        "last_download_at": row.kit_last_download_at,
    }


def progress(row: Any, invitation: Any = None) -> List[Dict[str, Any]]:
    """The request's path to a federated frame: each step done, current (the first not done) or ahead, with its time.
    A self-hosted frame: requested, approved, downloaded, invited (the frame sent its invitation to this frame), federated.
    A hosted frame: requested, reviewed, provisioned. A declined request ends at `declined`."""
    if row.status == "rejected":
        return [{"key": "requested", "state": "done", "at": row.created_at},
                {"key": "declined", "state": "declined", "at": row.reviewed_at}]
    if hosting_of(row) == "self":
        invited_at = getattr(invitation, "created_at", None) if invitation is not None else None
        federated_at = (getattr(invitation, "completed_at", None)
                        if invitation is not None and getattr(invitation, "status", "") == "completed" else None)
        steps = [
            ("requested", True, row.created_at),
            ("approved", row.status in ("approved", "provisioned") and row.kit_approved_at is not None, row.kit_approved_at),
            ("downloaded", row.kit_last_download_at is not None, row.kit_last_download_at),
            ("invited", invitation is not None, invited_at),
            ("federated", federated_at is not None or row.status == "provisioned", federated_at),
        ]
    else:
        steps = [
            ("requested", True, row.created_at),
            ("reviewed", row.status in ("reviewed", "approved", "provisioned"), row.reviewed_at),
            ("provisioned", row.status == "provisioned", row.reviewed_at if row.status == "provisioned" else None),
        ]
    out, current_given = [], False
    for key, done, at in steps:
        if done:
            state = "done"
        elif not current_given:
            state, current_given = "current", True
        else:
            state = "ahead"
        out.append({"key": key, "state": state, "at": at if done else None})
    return out


def request_view(row: Any, release: Optional[Dict[str, Any]], invitation: Any, now: datetime, *,
                 days: int, limit: int) -> Dict[str, Any]:
    card, provisioning = _group(row, "card"), _group(row, "provisioning")
    return {
        "id": row.id,
        "status": row.status,
        "hosting": hosting_of(row),
        "organization": row.organization,
        "contact_name": row.contact_name,
        "contact_email": row.contact_email,
        "frame_name": row.frame_name,
        "display_name": row.display_name,
        "hostname": row.hostname,
        "trust_domain": row.trust_domain,
        "ticker": row.ticker,
        "currency_name": row.currency_name,
        "location": card.get("location") if isinstance(card.get("location"), str) else None,
        "lat": _number(card.get("lat")),
        "lng": _number(card.get("lng")),
        "theme": card.get("theme") if card.get("theme") in ("neural", "sovereign") else None,
        "posture": provisioning.get("posture") if isinstance(provisioning.get("posture"), str) else None,
        "created_at": row.created_at,
        "approved_at": row.kit_approved_at,
        "kit": kit_window(row, release, now, days=days, limit=limit),
        "progress": progress(row, invitation),
    }


def pick_invitations(invitations: Iterable[Any]) -> Dict[str, Any]:
    """The invitation that speaks for each trust domain: its latest completed one, else its latest."""
    best: Dict[str, Any] = {}
    for inv in invitations:
        domain = (getattr(inv, "initiator_trust_domain", "") or "").strip().lower()
        if not domain:
            continue
        held = best.get(domain)
        rank = (getattr(inv, "status", "") == "completed", getattr(inv, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc))
        if held is None or rank > (getattr(held, "status", "") == "completed",
                                   getattr(held, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc)):
            best[domain] = inv
    return best


def network_view() -> Dict[str, Any]:
    """The network a self-hosted frame joins: this frame's console (the address `frame-federate --with` takes)."""
    from agentvault_registry.core.public_url import public_base_url_static, public_ui_origin
    console = (public_ui_origin() or public_base_url_static() or "").rstrip("/")
    name = (os.getenv("REGISTRY_FEDERATION_NAME") or os.getenv("REGISTRY_NAME") or "").strip()
    return {"name": name, "console": console}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _redis():
    from agentvault_registry.background_tasks.leader import get_redis
    return await get_redis()


# ── routes ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/frame-kit/me", summary="Your frame requests and the frame kit")
async def my_frame_kit(
    db: AsyncSession = Depends(get_db),
    developer: models.Developer = Security(get_current_developer),
) -> Dict[str, Any]:
    _require_enabled()
    rows = list((await db.execute(
        select(models.FrameRequest).where(owner_clause(developer))
        .order_by(models.FrameRequest.created_at.desc()).limit(20)
    )).scalars().all())
    domains = sorted({(r.trust_domain or "").strip().lower() for r in rows if r.trust_domain})
    invitations: Dict[str, Any] = {}
    if domains:
        invitations = pick_invitations((await db.execute(
            select(models.FrameInvitation).where(func.lower(models.FrameInvitation.initiator_trust_domain).in_(domains))
        )).scalars().all())
    release, why = load_release(kit_dir())
    now, days, limit = datetime.now(timezone.utc), window_days(), max_downloads()
    return {
        "requests": [request_view(r, release, invitations.get((r.trust_domain or "").strip().lower()), now,
                                  days=days, limit=limit) for r in rows],
        "release": public_release(release),
        "release_note": None if release else why,
        "network": network_view(),
        "window_days": days,
        "max_downloads": limit,
    }


@router.post("/frame-kit/me/{request_id}/link", summary="A single-use download link for the frame kit")
@limiter.limit("20/minute")
async def create_download_link(
    request: Request,
    request_id: str = PathParam(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
    developer: models.Developer = Security(get_current_developer),
) -> Dict[str, Any]:
    _require_enabled()
    row = (await db.execute(
        select(models.FrameRequest).where(models.FrameRequest.id == request_id, owner_clause(developer))
    )).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Frame request not found.")
    release, _why = load_release(kit_dir())
    window = kit_window(row, release, datetime.now(timezone.utc), days=window_days(), limit=max_downloads())
    if window["state"] != "ready":
        raise HTTPException(status_code=409, detail=window["sentence"])
    r = await _redis()
    if r is None:
        raise HTTPException(status_code=503, detail="Downloads need this frame's Redis, and none is configured.")
    token = secrets.token_urlsafe(32)
    await r.set(_TOKEN_PREFIX + _digest(token), json.dumps({"request_id": row.id, "developer_id": developer.id}), ex=LINK_TTL_S)
    logger.info("[frame-kit] link for request %s by developer %s (%s)", row.id, developer.id, release["filename"])
    return {
        "url": f"/api/v1/frame-kit/download?token={token}",
        "expires_in": LINK_TTL_S,
        "filename": release["filename"],
        "size_bytes": release["size_bytes"],
        "sha256": release["sha256"],
    }


@router.get("/frame-kit/download", summary="The frame kit, for a single-use link")
@limiter.limit("30/minute")
async def download_kit(
    request: Request,
    token: str = Query(..., min_length=20, max_length=128),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    r = await _redis()
    if r is None:
        raise HTTPException(status_code=503, detail="Downloads need this frame's Redis, and none is configured.")
    raw = await r.getdel(_TOKEN_PREFIX + _digest(token))
    if not raw:
        raise HTTPException(status_code=410, detail="This download link has expired or was already used. Open your frame page and download again.")
    try:
        claim = json.loads(raw)
        request_id, developer_id = str(claim["request_id"]), int(claim["developer_id"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=410, detail="This download link is not valid. Open your frame page and download again.")
    developer = await db.get(models.Developer, developer_id)
    row = (await db.execute(
        select(models.FrameRequest).where(models.FrameRequest.id == request_id).with_for_update()
    )).scalars().first()
    if developer is None or row is None or not is_owner(row, developer):
        raise HTTPException(status_code=404, detail="Frame request not found.")
    release, _why = load_release(kit_dir())
    now, limit = datetime.now(timezone.utc), max_downloads()
    window = kit_window(row, release, now, days=window_days(), limit=limit)
    if window["state"] != "ready":
        raise HTTPException(status_code=409, detail=window["sentence"])
    row.kit_download_count = int(row.kit_download_count or 0) + 1
    row.kit_last_download_at = now
    await db.commit()
    logger.info("[frame-kit] download of %s for request %s by developer %s (%d of %d)",
                release["filename"], request_id, developer_id, row.kit_download_count, limit)
    return FileResponse(
        release["path"], media_type="application/gzip", filename=release["filename"],
        headers={"Cache-Control": "no-store", "X-Content-SHA256": release["sha256"]},
    )


# ── the approval mail (sent by routers/frame_requests.py when the admin approves) ──────────────────────────────────

def approval_mail(row: Any, console: str, *, days: int, limit: int) -> Optional[Dict[str, Any]]:
    """The mail an approved self-hosted request sends, or None when there is nothing to send (flag off, not
    self-hosted, no address, no console to link to). Pure, so its words are testable."""
    if not frame_kit_enabled() or hosting_of(row) != "self" or not (row.contact_email or "").strip() or not console:
        return None
    name = row.display_name or row.hostname or row.frame_name or "your frame"
    link = f"{console.rstrip('/')}/#/frame-kit"
    greeting = f"Hello {row.contact_name}," if row.contact_name else "Hello,"
    body = (
        f"{greeting}\n\n"
        f"Your request for {name} is approved. The frame kit is ready on your frame page:\n\n{link}\n\n"
        f"Sign in as {row.contact_email}. The page has the kit, its sha256 fingerprint, and the commands for your host "
        f"with your frame's values filled in. The download stays open for {days} days and {limit} downloads.\n\n"
        "When your frame is up, it sends its invitation to this network, and we approve it here."
    )
    return {
        "subject": f"Your frame is approved: {name}",
        "recipients": [row.contact_email.strip()],
        "template": "admin_notice",
        "context": {"kicker_label": "FRAME APPROVED", "headline_text": f"{name} is approved", "body_text": body},
    }


def send_approval_mail(row: Any) -> bool:
    """Fire-and-forget; a mail that fails is logged and never undoes the approval."""
    mail = approval_mail(row, network_view()["console"], days=window_days(), limit=max_downloads())
    if mail is None:
        return False
    from agentvault_registry.email_utils import send_themed_email

    async def _dispatch() -> None:
        try:
            await send_themed_email(subject=mail["subject"], recipients=mail["recipients"], template=mail["template"],
                                    context=mail["context"], theme="neural")
        except Exception as exc:  # noqa: BLE001 (logged; the approval stands)
            logger.warning("[frame-kit] approval mail to %s not sent: %s", mail["recipients"][0], exc)

    try:
        asyncio.get_running_loop().create_task(_dispatch())
        return True
    except RuntimeError:
        return False
