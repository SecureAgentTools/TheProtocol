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
             "approval.request": "rail", "choice.request": "rail", "code.change.live": "rail",
             "content.change.live": "rail"}
UPDATE_RAILS = {"guild.order.live": "the Guild rail", "approval.decided": "the chat approval rail",
                "approval.request": "the chat approval rail", "choice.request": "the chat approval rail",
                "code.change.live": "the code changes rail", "content.change.live": "the code changes rail"}

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
    if ctype == "code.change.live" and data.get("state") in ("failed", "vetoed", "merged", "withdrawn"):   # V0666 D3
        return f"the change is {data.get('state')}"
    if ctype == "content.change.live" and data.get("state") in ("failed", "apply_failed", "undone", "withdrawn"):   # V0667 D5b (an applied change can still be undone)
        return f"the change is {data.get('state')}"
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

# V0659 (n): "expired" too, the reaper's end of an open order past its deadline (its card showed "open" for good)
GUILD_EVENT_TYPES = ("posted", "bid", "awarded", "submitted", "settling", "verified", "disputed", "resolving",
                     "settled", "cancelled", "expired")


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


# ---------------------------------------------------------------------------
# V0666 D3 (order gwo_542285271416c653ca39af3f): a code distribution's change, live in its organization's room
# ---------------------------------------------------------------------------

# services/code_changes.STATES, kept here so this module reads no other (a test pins the two equal)
CODE_CHANGE_STATES = ("proposed", "accepted", "balloting", "passed", "failed", "vetoed", "merged", "withdrawn")
CODE_CHANGE_TERMINAL = frozenset({"failed", "vetoed", "merged", "withdrawn"})
REASON_MAX = 200
REASONS_MAX = 6
SENTENCE_MAX = 300


def _clip(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= n else s[:n - 1] + "…"


def room_state(view: Dict[str, Any]) -> str:
    """The state word a line's room last saw (code_changes.announce_state): the change's own state, except that a MERGED line change
    that went upstream says so: `upstreaming` while its proposal on the main code is open, `upstream` once it landed there. A withdrawn,
    failed or vetoed proposal leaves the change merged (V0667 D4)."""
    state = str(view.get("state") or "proposed")
    up = view.get("upstream") if isinstance(view.get("upstream"), dict) else None
    if state == "merged" and up:
        if up.get("state") == "merged":
            return "upstream"
        if up.get("state") in ("proposed", "accepted", "balloting", "passed"):
            return "upstreaming"
    return state if state in CODE_CHANGE_STATES else "proposed"


def code_change_card(view: Dict[str, Any]) -> Dict[str, Any]:
    """The `code.change.live` card of a line's change, from its public view (services/code_changes.view without a
    reader): its title and state, the line (its release and organization by name), the signed checker's verdict, the
    reviews of the commit and the line's own ballot. Never a reader's own vote or what a reader may do: the card is
    everyone's in the room, each reader reads their own from the change (GET /code-changes/{id})."""
    line = view.get("code_distribution") or {}
    acc = view.get("acceptance") if isinstance(view.get("acceptance"), dict) else None
    if acc is None or not isinstance(acc.get("ok"), bool):
        checker = {"state": "none", "reasons": []}
    else:
        checker = {"state": "ok" if acc["ok"] else "failed",
                   "reasons": [] if acc["ok"] else [_clip(r, REASON_MAX) for r in (acc.get("reasons") or [])][:REASONS_MAX]}
    rv = view.get("review_verdict") if isinstance(view.get("review_verdict"), dict) else {}
    commit = view.get("commit")
    reviews = [r for r in (view.get("reviews") or []) if isinstance(r, dict) and (not commit or r.get("commit") == commit)]
    lb = view.get("line_ballot") if isinstance(view.get("line_ballot"), dict) else {}
    res = lb.get("result") if isinstance(lb.get("result"), dict) else None
    state = str(view.get("state") or "proposed")
    data: Dict[str, Any] = {
        "change_id": str(view.get("id")),
        "title": _clip(view.get("title") or view.get("id"), TITLE_MAX),
        "state": state if state in CODE_CHANGE_STATES else "proposed",
        "sensitive": bool(view.get("sensitive")),
        "line": {"slug": line.get("slug"), "title": _clip(line.get("title"), TITLE_MAX),
                 "release_name": line.get("release_name"), "organization_name": _clip(line.get("organization_name"), 120),
                 "paused": line.get("state") == "paused"},
        "checker": checker,
        "reviews": {"count": len(reviews), "approvals": int(rv.get("approvals") or 0), "needed": int(rv.get("needed") or 1),
                    "blockers": len(rv.get("blockers") or [])},
        "ballot": {"votes": int(lb.get("votes") or 0), "deciders": int(lb.get("deciders_now") or 0), "ends": lb.get("ends"),
                   "result": res.get("status") if res else None, "sentence": _clip(res.get("sentence"), SENTENCE_MAX) if res else None,
                   "note": _clip(lb.get("deciders_note"), SENTENCE_MAX)},
    }
    up = view.get("upstream") if isinstance(view.get("upstream"), dict) else None
    if up and isinstance(up.get("change_id"), str):
        data["upstream"] = {"change_id": up["change_id"], "state": up.get("state"), "since": up.get("since")}
    return {"v": 1, "type": "code.change.live", "data": data, "refs": {"code_change_id": str(view.get("id"))}}


def validate_code_change_live(data: Dict[str, Any]) -> Optional[str]:
    """A refusal reason for a `code.change.live` card's data (the code changes rail writes it), or None."""
    cid = data.get("change_id")
    if not isinstance(cid, str) or not cid.startswith("cc_"):
        return "code.change.live: data.change_id must name a code change (cc_...)"
    if not _is_text(data.get("title"), 1, TITLE_MAX):
        return "code.change.live: data.title is required"
    if data.get("state") not in CODE_CHANGE_STATES:
        return "code.change.live: data.state must be a code change's state"
    for k in ("line", "checker", "reviews", "ballot"):
        if not isinstance(data.get(k), dict):
            return f"code.change.live: data.{k} must be an object"
    return None


def code_change_state_line(seen: Optional[str], view: Dict[str, Any]) -> Optional[str]:
    """The one line a state change posts to the change's room (the team's development log), or None: nothing when the
    room has seen no state yet (the card itself announces the change) or already saw this one."""
    state = room_state(view)
    if seen is None or seen == state:
        return None
    title = _clip(view.get("title") or view.get("id"), 120)
    line = view.get("code_distribution") or {}
    release = line.get("release_name") or "its release line"
    up = view.get("upstream") if isinstance(view.get("upstream"), dict) else {}
    said = {
        "upstreaming": f"proposed upstream to the main code as {up.get('change_id')}.",
        "upstream": f"upstream since {up.get('change_id')}: the main code has it.",
        "proposed": "proposed again: the signed checker reads its commit.",
        "accepted": "the signed checks passed; it waits for its reviews.",
        "balloting": f"the line's ballot is open; its deciders vote ({release}).",
        "passed": "passed; the veto window runs.",
        "merged": f"merged into {line.get('branch') or 'the line'}.",
        "failed": "did not pass.",
        "vetoed": "vetoed.",
        "withdrawn": "withdrawn.",
    }.get(state)
    return _clip(f"{title}: {said}", SENTENCE_MAX) if said else None


CONTENT_CHANGE_STATES = ("balloting", "failed", "apply_failed", "applied", "undone", "withdrawn")


def content_change_card(view: Dict[str, Any]) -> Dict[str, Any]:
    """V0667 D5b: the `content.change.live` card of a line's content change, from its public view (services/content_changes.view): its kind, title and state, the line (its
    release and organization by name), our checker's verdict and the line's ballot. Never a reader's own vote or what a reader may do: the card is everyone's in the room, each
    reader reads their own from the change (GET /content-changes/{id}). The content itself stays in the change: a card names what kind of change it is, never its text."""
    line = view.get("code_distribution") or {}
    k = view.get("checker") if isinstance(view.get("checker"), dict) else {}
    b = view.get("ballot") if isinstance(view.get("ballot"), dict) else {}
    res = b.get("result") if isinstance(b.get("result"), dict) else None
    state = str(view.get("state") or "balloting")
    data: Dict[str, Any] = {
        "change_id": str(view.get("id")),
        "kind": str(view.get("kind") or ""),
        "title": _clip(view.get("title") or view.get("id"), TITLE_MAX),
        "state": state if state in CONTENT_CHANGE_STATES else "balloting",
        "line": {"slug": line.get("slug"), "title": _clip(line.get("title"), TITLE_MAX), "release_name": line.get("release_name"),
                 "organization_name": _clip(view.get("organization_name"), 120), "paused": line.get("state") == "paused"},
        "checker": {"state": "ok" if k.get("ok") is True else "none", "rules": [str(r) for r in (k.get("rules") or [])][:6]},
        "ballot": {"votes": int(b.get("cast") or 0), "deciders": int(b.get("deciders") or 0), "ends": b.get("ends"),
                   "result": res.get("status") if res else None, "sentence": _clip(res.get("sentence"), SENTENCE_MAX) if res else None},
        "applied": state == "applied",
    }
    return {"v": 1, "type": "content.change.live", "data": data, "refs": {"content_change_id": str(view.get("id"))}}


def validate_content_change_live(data: Dict[str, Any]) -> Optional[str]:
    """A refusal reason for a `content.change.live` card's data (the code changes rail writes it), or None."""
    cid = data.get("change_id")
    if not isinstance(cid, str) or not cid.startswith("ct_"):
        return "content.change.live: data.change_id must name a content change (ct_...)"
    if not _is_text(data.get("title"), 1, TITLE_MAX):
        return "content.change.live: data.title is required"
    if data.get("state") not in CONTENT_CHANGE_STATES:
        return "content.change.live: data.state must be a content change's state"
    for k in ("line", "checker", "ballot"):
        if not isinstance(data.get(k), dict):
            return f"content.change.live: data.{k} must be an object"
    return None


def content_change_state_line(seen: Optional[str], view: Dict[str, Any]) -> Optional[str]:
    """The one line a state change of a content change posts to its room (the team's development log), or None: nothing when the room has seen no state yet (the card itself
    announces the change) or already saw this one."""
    state = str(view.get("state") or "")
    if seen is None or seen == state:
        return None
    title = _clip(view.get("title") or view.get("id"), 120)
    said = {
        "applied": "passed its ballot and is applied to the organization's own space; its deciders can undo it in one step.",
        "failed": "did not pass its ballot; nothing was applied.",
        "apply_failed": "passed its ballot but our checker refused it at the apply: nothing was applied.",
        "undone": "undone; the organization's space is back as it was.",
        "withdrawn": "withdrawn.",
    }.get(state)
    return _clip(f"{title}: {said}", SENTENCE_MAX) if said else None
