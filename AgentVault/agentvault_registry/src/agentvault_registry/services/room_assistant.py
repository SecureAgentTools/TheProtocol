"""§ROOMBRAIN (H3.3, 2026-08-29) — @assistant: a DETERMINISTIC records-reader.

NO MODEL. The assistant answers ONLY from the org's own records — the room's
receipt cards, the roster, the treasury read — through a closed command
vocabulary. An LLM brain would need a key/consent design nobody approved, and
a records-reader is honest about what it can know. The rules:

  * present only while an org admin ADDED it (org_policy.assistant_present,
    read LIVE per message — removal silences it on the NEXT message);
  * answers ONLY when addressed (`@assistant …` prefix) — it never volunteers;
  * every read is scoped to THIS org's records (the invocation window);
  * a question outside the vocabulary gets the honest "I only read records"
    line, never a guess;
  * answers post as SYSTEM-authored text (a rail speaking, labelled as one),
  * best-effort and post-commit — a broken assistant must never break chat.
"""
import datetime
import logging
import re
from typing import Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from . import chat_service as cs

logger = logging.getLogger(__name__)

ASSISTANT = cs.Actor("system", display_name="Assistant", system_id="room-assistant")

_ADDRESS = re.compile(r"^\s*@assistant\b[\s,:]*", re.IGNORECASE)

HELP_TEXT = (
    "I read this organization's records — nothing else. Commands:\n"
    "@assistant settled — work receipts from the last 7 days\n"
    "@assistant treasury — the org treasury balance (TEG truth)\n"
    "@assistant who is here — the room roster\n"
    "@assistant help — this list"
)

REFUSAL = ("I only read records (receipts, the roster, the treasury). "
           "Try: @assistant help")


def addressed(body: Optional[str]) -> Optional[str]:
    """The question text when the message addresses the assistant, else None."""
    if not body or not isinstance(body, str):
        return None
    m = _ADDRESS.match(body)
    if not m:
        return None
    return body[m.end():].strip()


async def _answer(db: AsyncSession, org_id: str, conv_id: str, q: str) -> str:
    ql = q.lower()
    if not ql or "help" in ql:
        return HELP_TEXT

    if "who" in ql or "roster" in ql or "here" in ql:
        rows = (await db.execute(sa_text(
            "SELECT ptype, developer_id, agent_did FROM conversation_participants "
            "WHERE conversation_id = :c AND state = 'active' LIMIT 50"
        ), {"c": conv_id})).fetchall()
        keys = []
        for p in rows:
            if p[0] == "developer" and p[1] is not None:
                keys.append(cs.principal_key("developer", p[1]))
            elif p[0] == "agent" and p[2]:
                keys.append(cs.principal_key("agent", p[2]))
        names = await cs.display_names(db, keys)
        listed = [names.get(k) or k.split(":", 1)[1][:24] for k in keys]
        return (f"{len(listed)} in this room: " + ", ".join(sorted(listed)[:25])) if listed \
            else "Nobody has opened this room yet."

    if "settle" in ql or "receipt" in ql or "week" in ql or "work" in ql:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        rows = (await db.execute(sa_text(
            "SELECT m.card->'data'->>'kind' AS kind, m.card->'data'->>'amount' AS amount, "
            "m.card->'data'->>'currency' AS ccy "
            "FROM chat_messages m WHERE m.conversation_id = :c AND m.deleted_at IS NULL "
            "AND m.kind = 'card' AND m.card->>'type' = 'org.work.receipt' "
            "AND m.created_at >= :since ORDER BY m.seq DESC LIMIT 50"
        ), {"c": conv_id, "since": since})).fetchall()
        if not rows:
            return "No work receipts in the last 7 days."
        by_kind: dict = {}
        for k, amt, ccy in rows:
            by_kind.setdefault(k or "?", []).append(f"{amt} {ccy}")
        parts = [f"{k} ×{len(v)} ({', '.join(v[:3])}{'…' if len(v) > 3 else ''})"
                 for k, v in by_kind.items()]
        return f"Last 7 days, {len(rows)} receipt(s): " + " · ".join(parts)

    if "treasur" in ql or "balance" in ql:
        from agentvault_registry.services.org_treasury import resolve_org_treasury_did
        did = await resolve_org_treasury_did(db, org_id)
        if not did:
            return "This organization has no treasury account."
        try:
            from agentvault_registry.services.exchange_service import mover
            bal = await mover.agent_balance(did)
            import os as _os
            ccy = (_os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").upper()
            return f"Treasury balance: {bal} {ccy} (TEG truth, read just now)."
        except Exception:  # noqa: BLE001
            return "The treasury could not be read right now — an honest gap, not a zero."

    return REFUSAL


async def maybe_answer(db: AsyncSession, conv, body: Optional[str]) -> None:
    """Post the assistant's answer into the room, best-effort. Caller has
    already committed the human's message; this runs after, and swallows."""
    try:
        if conv.kind != "org" or not conv.org_id:
            return
        q = addressed(body)
        if q is None:
            return
        from agentvault_registry.services.org_policy import assistant_present
        row = (await db.execute(sa_text(
            "SELECT settings FROM organizations WHERE id = :o"), {"o": conv.org_id})).first()
        if not row or not assistant_present(row[0] if isinstance(row[0], dict) else None):
            return   # not present ⇒ silence (never an error, never a volunteer)

        answer = await _answer(db, conv.org_id, conv.id, q)
        msg, dup = await cs.insert_message(
            db, conv, None, ASSISTANT, "text", answer, None,
            client_ref=f"asst-{conv.id[:8]}-{int(datetime.datetime.now().timestamp() * 1000)}",
            rail_author=True, mark_read=False)
        if dup:
            return
        try:
            payload = cs.serialize_message(msg)
            recipients = await cs.recipients_snapshot(db, conv, ASSISTANT)
            if recipients:
                cs.deliver(
                    conv.id, conv.kind, payload, recipients, ASSISTANT.display_name)
        except Exception:  # noqa: BLE001
            logger.debug("[ROOMBRAIN] fan-out skipped", exc_info=True)
    except Exception:  # noqa: BLE001 — chat must never break on the assistant
        logger.warning("[ROOMBRAIN] answer failed for %s", getattr(conv, "id", "?"),
                       exc_info=True)
