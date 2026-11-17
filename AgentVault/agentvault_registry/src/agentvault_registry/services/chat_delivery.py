"""V0663 (order gwo_01681f32a8cfe7390b773532, his suggestion 6): what waits in the chat federation outbox, per peer, for
the admins' delivery panel (routers/chat_delivery_admin): one grouped SELECT of chat_federation_outbox.

V0664 (order gwo_efdd53bd198423a5ec2b742d): the panel acts on one stuck row. A peer's rows (never their payload) with
each one's state; RETRY NOW (its next attempt now; a given-up row gets one more try) and DROP WITH A REASON (who, when
and why on the row itself, migration 0226, and an audit row; a dropped row is never due and never holds its thread).
Both are one guarded UPDATE that only moves a row the drain cannot be sending (given up, or backing off: its stored next
attempt still ahead), so neither races the drain's own write; the drain is woken after the commit. Nothing is deleted:
not the message, not the outbox row.

Per peer: the rows waiting (not delivered), the age of the oldest, the most attempts among them, how many reached
MAX_ATTEMPTS (the worker stopped: they wait for a human), the next attempt, the latest error, the last delivery. Every
ACTIVE peer has a line (nothing waiting reads clear); a queue for an address that is no longer an active peer still
shows. The verdict makes a stuck delivery visible at a glance:
  given_up  a row reached MAX_ATTEMPTS        late     the oldest waiting row is older than CHAT_DELIVERY_LATE_SECONDS
  waiting   rows waiting, none late           clear    nothing waiting
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_LATE_SECONDS = 120
_RANK = {"given_up": 0, "late": 1, "waiting": 2, "clear": 3}
_WAITS = "delivered_at IS NULL AND dropped_at IS NULL"     # V0664: a dropped row no longer waits
MAX_REASON = 500


def late_seconds() -> int:
    try:
        v = int(os.getenv("CHAT_DELIVERY_LATE_SECONDS", "") or DEFAULT_LATE_SECONDS)
    except ValueError:
        return DEFAULT_LATE_SECONDS
    return v if v > 0 else DEFAULT_LATE_SECONDS


def max_attempts() -> int:
    from .chat_federation import MAX_ATTEMPTS
    return MAX_ATTEMPTS


def delivery_stmt():
    """One grouped read; the waiting figures filter on delivered_at IS NULL (the outbox's due index leads with it) and,
    since V0664, on a row not dropped; the dropped ones are counted apart."""
    from sqlalchemy import text
    return text(
        "SELECT peer_base_url, "
        f"count(*) FILTER (WHERE {_WAITS}) AS waiting, "
        f"min(created_at) FILTER (WHERE {_WAITS}) AS oldest_waiting_at, "
        f"coalesce(max(attempts) FILTER (WHERE {_WAITS}), 0) AS max_attempts, "
        f"count(*) FILTER (WHERE {_WAITS} AND attempts >= :m) AS given_up, "
        f"min(next_attempt_at) FILTER (WHERE {_WAITS}) AS next_attempt_at, "
        "(array_agg(last_error ORDER BY next_attempt_at DESC) "
        f" FILTER (WHERE {_WAITS} AND last_error IS NOT NULL))[1] AS last_error, "
        "count(*) FILTER (WHERE delivered_at IS NULL AND dropped_at IS NOT NULL) AS dropped, "
        "max(delivered_at) AS last_delivered_at "
        "FROM chat_federation_outbox GROUP BY peer_base_url").bindparams(m=max_attempts())


async def read_rows(db: Any) -> List[Dict[str, Any]]:
    return [dict(r) for r in (await db.execute(delivery_stmt())).mappings().all()]


async def active_peers(db: Any) -> Dict[str, str]:
    from .chat_federation import peer_base_urls
    return await peer_base_urls(db)


async def worker_stats() -> Dict[str, Any]:
    from ..background_tasks.chat_federation_outbox import outbox_stats
    return await outbox_stats()


def federation_enabled() -> bool:
    from .chat_federation import federation_enabled as _on
    return _on()


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)).isoformat()
    return v


def _verdict(waiting: int, given_up: int, age: Optional[int]) -> str:
    if given_up:
        return "given_up"
    if waiting and age is not None and age > late_seconds():
        return "late"
    return "waiting" if waiting else "clear"


def delivery_view(rows: List[Dict[str, Any]], peers: Dict[str, str], *, now: dt.datetime) -> List[Dict[str, Any]]:
    """A line per active peer and per address with rows, with its verdict; the worst first, then by name."""
    by = {r["peer_base_url"]: r for r in rows}
    out = []
    for url in sorted(set(by) | set(peers)):
        r = by.get(url, {})
        waiting, given_up = int(r.get("waiting") or 0), int(r.get("given_up") or 0)
        oldest = r.get("oldest_waiting_at")
        if isinstance(oldest, dt.datetime) and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=dt.timezone.utc)
        age = int((now - oldest).total_seconds()) if isinstance(oldest, dt.datetime) and waiting else None
        out.append({
            "peer_base_url": url, "name": peers.get(url), "active_peer": url in peers,
            "waiting": waiting, "oldest_waiting_at": _iso(oldest) if waiting else None, "oldest_age_seconds": age,
            "attempts_max": int(r.get("max_attempts") or 0), "given_up": given_up,
            "next_attempt_at": _iso(r.get("next_attempt_at")) if waiting else None,
            "last_error": (str(r["last_error"])[:500] if r.get("last_error") else None),
            "last_delivered_at": _iso(r.get("last_delivered_at")), "dropped": int(r.get("dropped") or 0),
            "verdict": _verdict(waiting, given_up, age)})
    out.sort(key=lambda p: (_RANK[p["verdict"]], -(p["oldest_age_seconds"] or 0), p["name"] or p["peer_base_url"]))
    return out


async def delivery_by_peer(db: Any, *, now: dt.datetime) -> List[Dict[str, Any]]:
    """The panel's lines: the grouped read and the active peers, as delivery_view words them."""
    return delivery_view(await read_rows(db), await active_peers(db), now=now)


# --- V0664: one row at a time (order gwo_efdd53bd198423a5ec2b742d) ----------------------------------------------------

class DeliveryRefusal(Exception):
    """A refusal the route answers with its status, a short code and a sentence."""

    def __init__(self, status: int, code: str, sentence: str) -> None:
        super().__init__(sentence)
        self.status, self.code, self.sentence = status, code, sentence


def _outbox():
    from ..models import ChatFederationOutbox
    return ChatFederationOutbox


def _row_columns():
    """Every column an admin sees of a row, and never the payload (the message's text stays out of the panel)."""
    O = _outbox()
    return (O.id, O.conversation_id, O.seq, O.event_id, O.peer_base_url, O.attempts, O.next_attempt_at, O.last_error,
            O.created_at, O.delivered_at, O.dropped_at, O.dropped_by, O.drop_reason)


def rows_stmt(peer: str, limit: int):
    """A peer's rows still to deliver (not delivered, not dropped), oldest first."""
    from sqlalchemy import select
    O = _outbox()
    return (select(*_row_columns()).where(O.peer_base_url == peer, O.delivered_at.is_(None), O.dropped_at.is_(None))
            .order_by(O.created_at, O.seq).limit(max(1, min(int(limit), 200))))


def _stuck():
    """A row the drain cannot be sending: given up (never loaded), or backing off (a batch that loaded it would still
    hold the stored next attempt it was loaded on, which is in the past; a row whose stored next attempt is ahead was
    written by a batch that has finished)."""
    from sqlalchemy import func, or_
    O = _outbox()
    return [O.delivered_at.is_(None), O.dropped_at.is_(None),
            or_(O.attempts >= max_attempts(), O.next_attempt_at > func.now())]


def retry_stmt(row_id: str):
    """Its next attempt now; a given-up row gets ONE more try (a further failure gives up again)."""
    from sqlalchemy import func, update
    O = _outbox()
    return (update(O).where(O.id == row_id, *_stuck())
            .values(next_attempt_at=func.now(), attempts=func.least(O.attempts, max_attempts() - 1)))


def drop_stmt(row_id: str, *, actor_id: Any, reason: str):
    """Who, when and why, on the row itself; the row stays, and so does the message."""
    from sqlalchemy import func, update
    O = _outbox()
    return (update(O).where(O.id == row_id, *_stuck())
            .values(dropped_at=func.now(), dropped_by=actor_id, drop_reason=reason))


async def read_row(db: Any, row_id: str) -> Optional[Dict[str, Any]]:
    from sqlalchemy import select
    O = _outbox()
    r = (await db.execute(select(*_row_columns()).where(O.id == row_id))).mappings().first()
    return dict(r) if r else None


async def thread_rows(db: Any, row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The undelivered, undropped rows of the row's thread to the same peer (what could hold it)."""
    from sqlalchemy import select
    O = _outbox()
    rs = (await db.execute(select(*_row_columns()).where(
        O.conversation_id == row["conversation_id"], O.peer_base_url == row["peer_base_url"],
        O.delivered_at.is_(None), O.dropped_at.is_(None)))).mappings().all()
    return [dict(r) for r in rs]


async def peer_rows(db: Any, peer: str, limit: int) -> List[Dict[str, Any]]:
    return [dict(r) for r in (await db.execute(rows_stmt(peer, limit))).mappings().all()]


async def audit(db: Any, **kw: Any) -> None:
    from .admin_audit import log_admin_action
    await log_admin_action(db, **kw)


async def wake() -> None:
    from .chat_federation import wake_outbox
    await wake_outbox()


def db_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(v: Any) -> Optional[dt.datetime]:
    if not isinstance(v, dt.datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)


def _order(r: Dict[str, Any]) -> Tuple[int, dt.datetime]:
    return int(r.get("seq") or 0), _aware(r.get("created_at")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def _backing_off(r: Dict[str, Any], now: dt.datetime) -> bool:
    nxt = _aware(r.get("next_attempt_at"))
    return (r.get("delivered_at") is None and r.get("dropped_at") is None and int(r.get("attempts") or 0) < max_attempts()
            and nxt is not None and nxt > now)


def row_states(rows: List[Dict[str, Any]], *, now: dt.datetime) -> List[Dict[str, Any]]:
    """Each row with its state and what an admin may do with it. The states, first match wins: delivered, dropped,
    given_up (MAX_ATTEMPTS reached), held (an earlier row of its thread to the same peer is backing off: the drain sends
    the thread in order, so nothing moves until that one does; held_by names it), due (the drain may be sending it now),
    backing_off. Retry needs a row given up or backing off and held by nothing; drop needs a row the drain cannot be
    sending (given up, or its own next attempt still ahead)."""
    out = []
    for r in rows:
        earlier = [e for e in rows if e is not r and e.get("conversation_id") == r.get("conversation_id")
                   and e.get("peer_base_url") == r.get("peer_base_url") and _order(e) < _order(r) and _backing_off(e, now)]
        held_by = min(earlier, key=_order)["id"] if earlier else None
        nxt = _aware(r.get("next_attempt_at"))
        ahead = nxt is not None and nxt > now
        if r.get("delivered_at") is not None:
            state = "delivered"
        elif r.get("dropped_at") is not None:
            state = "dropped"
        elif int(r.get("attempts") or 0) >= max_attempts():
            state = "given_up"
        elif held_by:
            state = "held"
        elif not ahead:
            state = "due"
        else:
            state = "backing_off"
        open_ = state in ("given_up", "backing_off", "held")
        out.append({**r, "state": state, "held_by": held_by,
                    "can_retry": state in ("given_up", "backing_off") and held_by is None,
                    "can_drop": open_ and (state == "given_up" or ahead)})
    return out


def row_view(r: Dict[str, Any]) -> Dict[str, Any]:
    """What the panel shows of a row (no payload)."""
    return {"id": r.get("id"), "kind": "event" if r.get("event_id") else "message", "conversation_id": r.get("conversation_id"),
            "seq": r.get("seq"), "event_id": r.get("event_id"), "attempts": int(r.get("attempts") or 0),
            "next_attempt_at": _iso(_aware(r.get("next_attempt_at"))), "created_at": _iso(_aware(r.get("created_at"))),
            "last_error": (str(r["last_error"])[:500] if r.get("last_error") else None),
            "state": r.get("state"), "held_by": r.get("held_by"), "can_retry": bool(r.get("can_retry")),
            "can_drop": bool(r.get("can_drop"))}


async def _state_of(db: Any, row_id: str) -> Dict[str, Any]:
    row = await read_row(db, row_id)
    if row is None:
        raise DeliveryRefusal(404, "not_found", "no outbox row with that id")
    if row.get("delivered_at") is not None:
        raise DeliveryRefusal(409, "delivered", "this row was delivered: nothing to retry or drop")
    if row.get("dropped_at") is not None:
        raise DeliveryRefusal(409, "dropped", "this row was already dropped")
    thread = await thread_rows(db, row)
    if not any(t.get("id") == row_id for t in thread):
        thread = thread + [row]
    return next(t for t in row_states(thread, now=db_now()) if t.get("id") == row_id)


def _facts(st: Dict[str, Any]) -> Dict[str, Any]:
    return {"peer_base_url": st.get("peer_base_url"), "conversation_id": st.get("conversation_id"), "seq": st.get("seq"),
            "event_id": st.get("event_id"), "attempts_before": int(st.get("attempts") or 0), "state_before": st.get("state"),
            "last_error": (str(st["last_error"])[:300] if st.get("last_error") else None),
            "created_at": _iso(_aware(st.get("created_at")))}


async def retry_row(db: Any, row_id: str, *, actor_id: Any) -> Dict[str, Any]:
    """Retry one row now (an admin's act, audited); the drain is woken after the commit."""
    st = await _state_of(db, row_id)
    if st["held_by"]:
        raise DeliveryRefusal(409, "held", f"held behind {st['held_by']}, an earlier row of its thread to this peer that "
                                           f"is backing off: retry that one first")
    if not st["can_retry"]:
        raise DeliveryRefusal(409, "due_now", "this row is due now: the delivery worker may be sending it")
    res = await db.execute(retry_stmt(row_id))
    if not getattr(res, "rowcount", 0):
        raise DeliveryRefusal(409, "changed", "the row moved meanwhile (the worker tried or sent it): read it again")
    await audit(db, action="chat_federation.outbox_retry", actor_id=str(actor_id), target_type="chat_federation_outbox",
                target_id=row_id, severity="info", details=_facts(st))
    await db.commit()
    await wake()
    return {"ok": True, "row_id": row_id, "state_before": st["state"], "attempts_before": int(st.get("attempts") or 0)}


async def drop_row(db: Any, row_id: str, *, actor_id: Any, reason: Any) -> Dict[str, Any]:
    """Drop one row with a reason (an admin's act, kept on the row and audited); it may release its thread, so the
    drain is woken after the commit. The message stays in its thread; the row stays in the outbox."""
    why = " ".join(str(reason or "").split())
    if not why or len(why) > MAX_REASON:
        raise DeliveryRefusal(422, "reason", f"say why the row is dropped, in 1 to {MAX_REASON} characters")
    st = await _state_of(db, row_id)
    if not st["can_drop"]:
        raise DeliveryRefusal(409, "due_now", "this row is due now: the delivery worker may be sending it (drop the "
                                              "earlier row of its thread first, or wait for it to back off)")
    res = await db.execute(drop_stmt(row_id, actor_id=actor_id, reason=why))
    if not getattr(res, "rowcount", 0):
        raise DeliveryRefusal(409, "changed", "the row moved meanwhile (the worker tried or sent it): read it again")
    await audit(db, action="chat_federation.outbox_drop", actor_id=str(actor_id), target_type="chat_federation_outbox",
                target_id=row_id, severity="warning", details={**_facts(st), "reason": why})
    await db.commit()
    await wake()
    return {"ok": True, "row_id": row_id, "dropped": True, "reason": why, "state_before": st["state"]}
