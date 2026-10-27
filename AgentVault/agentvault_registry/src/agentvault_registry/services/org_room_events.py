"""§CHATDESK C5 — org work receipts: the room hears what the firm's money did.

ONE server emitter. Chat stays money-free (§OURSTATE-1 law): every function
here runs AFTER an existing rail has already moved and committed the money,
and posts a RAIL-ONLY ``org.work.receipt`` card into the organization's room —
a record, never a lever. The rules it encodes:

  * **A money event never creates a room.** No room ⇒ the receipt silently
    does not post. A treasury movement must never fail, or wait, on chat.
    (A room whose org later disabled chat still receives the record — the
    receipt is the org's history and is there when the room reopens;
    dropping it would silently lose records.)
  * **Exactly-once per receipt.** The client_ref is derived from the event's
    own reference, so a retried caller re-posts nothing — insert_message
    dedupes on (sender, client_ref) per thread.
  * **Failures are contained.** Every entry point is post-commit,
    best-effort, and swallows: a thrown receipt must never poison the money
    path it is reporting on.
  * **The card is rail-only.** A receipt a client could author is not
    evidence of anything (the share.certificate reasoning, verbatim).
"""
import hashlib
import logging
import os
from typing import Optional

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation
from . import chat_service as cs

logger = logging.getLogger(__name__)

# Frame-native currency (AVT=A · JDAY=B · BVT=C) — the developers.py pattern.
FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"

# The ledger rail actor — the SUPPORT_DESK shape: a rail, never a participant.
ORG_LEDGER = cs.Actor("system", display_name="Treasury", system_id="org-ledger")

RECEIPT_KINDS = frozenset({
    "treasury.fund",      # org treasury → one of the org's agents
    "treasury.remit",     # an org agent → the org treasury
    "dividend.declared",  # the org declared a dividend on its listing
    "guild.settled",      # a guild engagement settled to the FIRM (payee_org_id)
    "work.commissioned",  # §ORGCLIENT — work the FIRM posted settled to its worker (client side)
})


def _client_ref(kind: str, ref: str) -> str:
    # Deterministic and always within the 8-64 char client_ref window,
    # whatever the caller's ref looks like.
    return "orgrcpt-" + hashlib.sha1(f"{kind}|{ref}".encode()).hexdigest()[:32]


async def post_org_receipt(
    db: AsyncSession, org_id: str, *, kind: str, amount: str,
    currency: Optional[str] = None, ref: str, memo: Optional[str] = None,
    counterparty: Optional[str] = None,
) -> None:
    """Post one receipt card into the org's room, best-effort, exactly-once."""
    try:
        if kind not in RECEIPT_KINDS:
            logger.error("[CHATDESK] unknown org receipt kind %r dropped", kind)
            return
        conv = (await db.execute(select(Conversation).where(
            Conversation.kind == "org",
            Conversation.org_id == org_id))).scalars().first()
        if conv is None:
            return  # no room, no receipt — never create one from a money event

        data = {"kind": kind, "amount": str(amount),
                "currency": (currency or FRAME_CCY)}
        if memo:
            data["memo"] = str(memo)[:200]
        if counterparty:
            data["counterparty"] = str(counterparty)[:120]
        card = {"v": 1, "type": "org.work.receipt", "data": data,
                "refs": {"org_id": org_id, "ref": str(ref)[:80]}}

        msg, dup = await cs.insert_message(
            db, conv, None, ORG_LEDGER, "card", None, card,
            client_ref=_client_ref(kind, str(ref)),
            rail_author=True, mark_read=False)
        if dup:
            return

        # Post-commit fan-out (§ESDUP): live cue to open room views…
        try:
            payload = cs.serialize_message(msg)
            recipients = await cs.recipients_snapshot(db, conv, ORG_LEDGER)
            if recipients:
                cs.deliver(
                    conv.id, conv.kind, payload, recipients,
                    ORG_LEDGER.display_name)
        except Exception:  # noqa: BLE001 — a missed live update is not an outage
            logger.debug("[CHATDESK] org receipt fan-out skipped", exc_info=True)

        # …and a TYPED notification to every org member (catalog-validated;
        # prefs and quiet hours apply — this is a bell, not a delivery path).
        try:
            dev_ids = [int(r) for r in (await db.execute(sa_text(
                "SELECT developer_id FROM organization_members "
                "WHERE organization_id = :o"), {"o": org_id})).scalars().all()]
            if dev_ids:
                from ..background_tasks.push_notify import notify
                # Display-only label: `kind` is the stored receipt/card key (matched
                # verbatim elsewhere) and must not change; only what a person reads here does.
                _kind_display = "distribution declared" if kind == "dividend.declared" else kind
                cs.spawn(notify(
                    "org.work.receipt", dev_ids,
                    title="Organization money moved",
                    message=f"{_kind_display}: {data['amount']} {data['currency']}"
                            + (f" ({data['memo']})" if data.get("memo") else ""),
                    tags="moneybag", click="/ui/#/pocket/orgs"))
        except Exception:  # noqa: BLE001
            logger.debug("[CHATDESK] org receipt notify skipped", exc_info=True)
    except Exception:  # noqa: BLE001 — the money already moved; never poison it
        logger.warning("[CHATDESK] org receipt %s/%s not posted", kind, ref,
                       exc_info=True)


async def post_dividend_receipt(db: AsyncSession, dividend) -> None:
    """ONE helper both dividend doors call — resolves the org from the listing."""
    try:
        from ..models import ExchangeListing
        row = (await db.execute(select(
            ExchangeListing.organization_id, ExchangeListing.symbol).where(
            ExchangeListing.id == dividend.listing_id))).first()
        if row is None or not row[0]:
            return
        await post_org_receipt(
            db, row[0], kind="dividend.declared",
            amount=str(dividend.total_amount), ref=f"div-{dividend.id}",
            memo=f"${row[1]} epoch {dividend.epoch} · {dividend.per_share}/point")
    except Exception:  # noqa: BLE001
        logger.warning("[CHATDESK] dividend receipt not posted", exc_info=True)
