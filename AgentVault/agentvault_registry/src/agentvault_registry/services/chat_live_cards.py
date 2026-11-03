"""V0652 (aa) gwo_840aa2b590306f7eba147758 (2026-11-01, agentvault2-14): cards that live, the pure rules.

The maintainer's room (seq 248-250): a proof or a roll posted as ten messages reads as noise; a Guild order's lifecycle
was typed by hand (BID, AWARDED ...); an approval card did not show that it was used. A card can now be updated IN
PLACE: the message keeps its seq and its place in the thread, its card is the latest state, and every update is kept
(who, when, what changed). Three card types live:

- `progress` (a client posts it; only its author updates it): a proof's or a roll's progress, its steps and its verdict.
  A verdict (passed, failed, cancelled) closes it.
- `guild.order.live` (the Guild rail posts it into the room the order's poster named, and keeps it current): the
  order's lifecycle, posted, bid, awarded, delivered, settled. Settled, cancelled or expired closes it.
- `approval.decided` (the approval rail): when the approval opens its one act (V0651 (o)), the card says what it was
  used for and when. Used once, it is closed.

Every other card stays as posted. Nothing here moves money; nothing here reads a database.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

PROGRESS_STATES = ("running", "passed", "failed", "cancelled")
PROGRESS_TERMINAL = frozenset({"passed", "failed", "cancelled"})
STEP_STATES = ("pending", "running", "done", "failed", "skipped")
PROGRESS_STEPS_MAX = 30
TITLE_MAX = 200
NOTE_MAX = 500
STEP_LABEL_MAX = 120
STEP_NOTE_MAX = 200

GUILD_STATUSES = ("open", "awarded", "submitted", "settling", "disputed", "resolving", "resolved", "settled",
                  "cancelled", "expired")
GUILD_TERMINAL = frozenset({"settled", "cancelled", "expired"})
GUILD_EVENTS_MAX = 20

# Who may update each card type in place: its author ("author") or only the rail that posted it ("rail").
# V0654 (aq), item 18: a request card (approval or choice) takes one update, by its rail: it reads withdrawn when the agent
# that asked takes it back, and is closed from then on
UPDATABLE = {"progress": "author", "guild.order.live": "rail", "approval.decided": "rail",
             "approval.request": "rail", "choice.request": "rail"}
UPDATE_RAILS = {"guild.order.live": "the Guild rail", "approval.decided": "the chat approval rail",
                "approval.request": "the chat approval rail", "choice.request": "the chat approval rail"}

# A card takes at most this many updates (a progress card of a long roll stays far below it).
CARD_REV_MAX = 200
# The history keeps every update; what changed is summarized in at most this many entries per update.
CHANGES_MAX = 12


def _is_text(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, str) and lo <= len(v.strip()) and len(v) <= hi


def validate_progress(data: Dict[str, Any]) -> Optional[str]:
    """A refusal reason for a `progress` card's data, or None."""
    if not _is_text(data.get("title"), 1, TITLE_MAX):
        return f"progress: data.title is required (1-{TITLE_MAX} chars)"
    if data.get("state") not in PROGRESS_STATES:
        return f"progress: data.state must be one of {', '.join(PROGRESS_STATES)}"
    note = data.get("note")
    if note is not None and not _is_text(note, 0, NOTE_MAX):
        return f"progress: data.note must be a string of at most {NOTE_MAX} chars"
    steps = data.get("steps")
    if steps is not None:
        if not isinstance(steps, list) or len(steps) > PROGRESS_STEPS_MAX:
            return f"progress: data.steps must be a list of at most {PROGRESS_STEPS_MAX} steps"
        for s in steps:
            if not isinstance(s, dict):
                return "progress: each step is an object with a label and a state"
            if not _is_text(s.get("label"), 1, STEP_LABEL_MAX):
                return f"progress: each step needs a label (1-{STEP_LABEL_MAX} chars)"
            if s.get("state") not in STEP_STATES:
                return f"progress: a step's state must be one of {', '.join(STEP_STATES)}"
            if s.get("note") is not None and not _is_text(s.get("note"), 0, STEP_NOTE_MAX):
                return f"progress: a step's note must be a string of at most {STEP_NOTE_MAX} chars"
            extra = set(s) - {"label", "state", "note"}
            if extra:
                return f"progress: a step carries only label, state and note (not {sorted(extra)})"
    extra = set(data) - {"title", "state", "note", "steps"}
    if extra:
        return f"progress: data carries only title, state, note and steps (not {sorted(extra)})"
    return None


def validate_guild_live(data: Dict[str, Any]) -> Optional[str]:
    """A refusal reason for a `guild.order.live` card's data (the Guild rail writes it), or None."""
    oid = data.get("order_id")
    if not isinstance(oid, str) or not oid.startswith("gwo_"):
        return "guild.order.live: data.order_id must name an order (gwo_...)"
    if not _is_text(data.get("title"), 1, TITLE_MAX):
        return "guild.order.live: data.title is required"
    if data.get("status") not in GUILD_STATUSES:
        return "guild.order.live: data.status must be an order status"
    ev = data.get("events")
    if not isinstance(ev, list) or len(ev) > GUILD_EVENTS_MAX:
        return f"guild.order.live: data.events must be a list of at most {GUILD_EVENTS_MAX}"
    return None


def closed_reason(card: Any) -> Optional[str]:
    """Why a card takes no more updates (its verdict, its end, its one use), or None while it is open."""
    if not isinstance(card, dict):
        return None
    ctype, data = card.get("type"), card.get("data") or {}
    if ctype == "progress" and data.get("state") in PROGRESS_TERMINAL:
        return f"its verdict is {data.get('state')}"
    if ctype == "guild.order.live" and data.get("status") in GUILD_TERMINAL:
        return f"the order is {data.get('status')}"
    if ctype == "approval.decided" and data.get("used"):
        return "the approval was used"
    if ctype in ("approval.request", "choice.request") and data.get("withdrawn"):   # V0654 (aq), item 18
        return "the request was withdrawn"
    return None


def _short(v: Any) -> Any:
    if isinstance(v, str):
        return v if len(v) <= 80 else v[:79] + "…"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return "…"


def card_changes(old: Any, new: Any) -> List[Dict[str, Any]]:
    """What an update changed, as [{path, from, to}] (at most CHANGES_MAX; the last entry says how many more).

    A progress card's steps compare by their label, so a step that changed its state reads as that step, and a step
    added or dropped says so. Every other card compares its data's top-level fields."""
    od = (old or {}).get("data") or {} if isinstance(old, dict) else {}
    nd = (new or {}).get("data") or {} if isinstance(new, dict) else {}
    out: List[Dict[str, Any]] = []
    for k in sorted(set(od) | set(nd)):
        if k == "steps" and (new or {}).get("type") == "progress":
            continue
        if od.get(k) != nd.get(k):
            out.append({"path": k, "from": _short(od.get(k)), "to": _short(nd.get(k))})
    if (new or {}).get("type") == "progress":
        before = {s.get("label"): s for s in od.get("steps") or [] if isinstance(s, dict)}
        after = {s.get("label"): s for s in nd.get("steps") or [] if isinstance(s, dict)}
        for label, s in after.items():
            b = before.get(label)
            if b is None:
                out.append({"path": f"step {label}", "from": None, "to": s.get("state")})
            elif b.get("state") != s.get("state") or b.get("note") != s.get("note"):
                out.append({"path": f"step {label}", "from": b.get("state"), "to": s.get("state")})
        for label, b in before.items():
            if label not in after:
                out.append({"path": f"step {label}", "from": b.get("state"), "to": None})
    if len(out) > CHANGES_MAX:
        more = len(out) - (CHANGES_MAX - 1)
        out = out[:CHANGES_MAX - 1] + [{"path": f"and {more} more", "from": None, "to": None}]
    return out


# ---------------------------------------------------------------------------
# The Guild's order card: built from the order and its events (the rail's one renderer)
# ---------------------------------------------------------------------------

GUILD_EVENT_TYPES = ("posted", "bid", "awarded", "submitted", "settling", "verified", "disputed", "resolving",
                     "settled", "cancelled")


def guild_order_card(order: Dict[str, Any], events: List[Dict[str, Any]], *, bid_count: int,
                     worker_name: Optional[str] = None) -> Dict[str, Any]:
    """The `guild.order.live` card of an order: its title, bounty, status, worker and its lifecycle (the last
    GUILD_EVENTS_MAX of the events the card shows, oldest first)."""
    shown = [e for e in events if e.get("event_type") in GUILD_EVENT_TYPES]
    ev = [{"type": e.get("event_type"), "at": e.get("at"), "seq": int(e.get("seq") or 0)}
          for e in shown][-GUILD_EVENTS_MAX:]
    status = str(order.get("status") or "open")
    data: Dict[str, Any] = {
        "order_id": str(order.get("id")),
        "title": str(order.get("title") or order.get("id"))[:TITLE_MAX],
        "status": status if status in GUILD_STATUSES else "open",
        "bounty": str(order.get("bounty")) if order.get("bounty") is not None else None,
        "currency": order.get("currency"),
        "bids": int(bid_count),
        "events": ev,
    }
    if order.get("worker_did"):
        data["worker_did"] = order.get("worker_did")
        if worker_name:
            data["worker_name"] = str(worker_name)[:120]
    return {"v": 1, "type": "guild.order.live", "data": data, "refs": {"order_id": str(order.get("id"))}}
