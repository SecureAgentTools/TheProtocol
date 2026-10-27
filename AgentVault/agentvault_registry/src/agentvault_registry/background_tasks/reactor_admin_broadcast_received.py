"""
Reactor: AdminBroadcastSent / Edited / Retracted → local materialization
=========================================================================
§bc3 T3.1 (2026-05-19).

Subscribes to the 3 broadcast lifecycle events on the local EventStore.
For each event whose `source_frame` is DIFFERENT from this registry's
REGISTRY_NAME, we materialize/update/retract a LOCAL `admin_broadcasts`
row so that developers connected to THIS registry see the broadcast as
if it were local.

Dedup is via the `(source_frame, idempotency_key)` UNIQUE partial index
added by migration 0070_bc2_schema_ext. When the sender did not set
`idempotency_key` on the original POST, line 60 synthesizes
`foreign-<broadcast_id>` so the dedup key is ALWAYS populated and
federation ALWAYS fires — confirmed live during §pass69.6 (2026-05-25)
when broadcast id=231 on Frame A (sender-side `idempotency_key=null`)
materialized on op-paris (row 482, key `foreign-231`) and op-tokyo
(row 19, key `foreign-231`) within seconds.

Per Commander lock #2 (2026-05-19):
  Default audience was LOCAL with federation-wide as the admin opt-in.
  The opt-in was meant to be sender-side `target_frame` / `target_audience`,
  but neither column has shipped yet — so in practice every broadcast
  federates today. There is currently no way to scope a broadcast to a
  single registry via the public API.

  TODO §bc3.2 / §bc4 — when `target_audience` column ships:
    - sender-side enforcement: only emit the federation event if the
      target_audience requests cross-registry reach (default LOCAL again)
    - receiver-side belt-and-braces filter:
        if target_audience == 'local-only': skip federation materialization.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from agentvault_registry import models
from agentvault_registry.database import get_db_context
from agentvault_registry.routers.websocket import broadcast_notification

from .reactor_base import EventStoreReactor

logger = logging.getLogger(__name__)


LOCAL_FRAME = os.getenv("REGISTRY_NAME", "registry-a")
# §MCPTEST30 V0639: the row a retract leaves when it comes before its copy (_apply_retract_to_local). A copy arrives
# seconds or minutes after its retract; a placeholder no copy has met in a week never will, and is pruned.
PLACEHOLDER_TITLE = "(retracted before it arrived)"
PLACEHOLDER_TTL = timedelta(days=7)
# An edit that comes before its copy holds the place too (_apply_edit_to_local): the edited words, inactive, and this
# mark in ws_recipients (a copy's count never goes below zero), so the copy that meets it goes live with them. A retract
# clears the mark. Pruned like a placeholder when no copy meets it within PLACEHOLDER_TTL.
HELD_FOR_COPY = -1


async def _local_author_id(db) -> Optional[int]:
    """This registry's first admin developer, else its first developer, else None: the author a federated row records."""
    for clause in (models.Developer.is_admin.is_(True), None):
        stmt = select(models.Developer.id)
        if clause is not None:
            stmt = stmt.where(clause)
        dev_id = (await db.execute(stmt.order_by(models.Developer.id).limit(1))).scalar_one_or_none()
        if dev_id is not None:
            return dev_id
    return None


def _deferred_until(event_data: dict) -> Optional[datetime]:
    """D6-211 (2026-10-17): a broadcast its sender scheduled for later ('deferred', scheduled_for still ahead) is copied
    as scheduled, so this registry's broadcast_scheduler sends it then and every developer read hides it until then;
    the copy went out at once. A time already past, or one that does not parse, is sent now, as the sender's would be."""
    if not event_data.get("deferred") or not event_data.get("scheduled_for"):
        return None
    try:
        when = datetime.fromisoformat(str(event_data["scheduled_for"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when if when > datetime.now(timezone.utc) else None


def _constraint_of(exc: Exception) -> str:
    """The constraint an IntegrityError names, so a foreign-key failure is never read as a duplicate."""
    orig = getattr(exc, "orig", None)
    name = getattr(getattr(orig, "diag", None), "constraint_name", None) or getattr(orig, "constraint_name", None)
    return f"constraint {name}" if name else str(orig or exc).splitlines()[0][:200]


async def _materialize_received_broadcast(event_data: dict, content: Optional[dict] = None) -> Optional[int]:
    """INSERT (or UPDATE if same idempotency_key already exists) a local
    admin_broadcasts row representing the foreign broadcast. Returns the
    LOCAL broadcast id (new or existing), or None if the event was
    skipped (no idempotency_key, or originated locally). `content`, when given, receives the title, body and type the
    copy carries: the Sent's, or an edit's that came first."""
    source_frame = event_data.get("source_frame")
    if not source_frame:
        logger.debug("[Reactor:AdminBroadcastReceived] no source_frame; skip")
        return None
    if source_frame == LOCAL_FRAME:
        # Loop-back: this event was emitted by us; we already wrote the row.
        return None
    if event_data.get("target_org_id") or event_data.get("target_developer_id") is not None:
        # §SECFIX D6-305 (2026-10-16): an organization's broadcast is for that organization's members, and they are
        # developers of the SENDING registry (organizations are per registry). The copy carried no audience, so every
        # developer here saw its title and got its live push. Not copied, like a direct notice (its own event type).
        logger.debug("[Reactor:AdminBroadcastReceived] targeted broadcast from %s: not copied", source_frame)
        return None
    foreign_idem = event_data.get("idempotency_key") or f"foreign-{event_data.get('broadcast_id')}"
    if foreign_idem is None:
        logger.debug("[Reactor:AdminBroadcastReceived] no idempotency_key; skip federation")
        return None

    title = event_data.get("title") or "(no title)"
    body = event_data.get("body") or f"[Federated from {source_frame}]"
    broadcast_type = event_data.get("broadcast_type") or "info"
    requires_ack = bool(event_data.get("requires_ack", False))

    async with get_db_context() as db:
        # A federated broadcast has no LOCAL author. `created_by` is NOT NULL and a foreign key to developers HERE, so
        # the sender's developer id (their numbering, not ours) failed the insert wherever that id did not exist, and
        # the unique-conflict branch below read the failure as "no row found" (§TESTBED 2026-09-19, measured on a kit
        # sandbox's operator: created_by 5 against developers 1-3, every broadcast lost). It passed on the network's
        # tier only where the numbers happened to line up. The author is this registry's own first admin.
        author = await _local_author_id(db)
        if author is None:
            logger.warning(f"[Reactor:AdminBroadcastReceived] no local developer to author the federated broadcast "
                           f"from {source_frame} (foreign_id={event_data.get('broadcast_id')}); not materialized")
            return None
        # Try insert; on conflict (source_frame, idempotency_key), look up the
        # existing row and return its id (idempotent receive).
        new_row = models.AdminBroadcast(
            title=title,
            body=body,
            broadcast_type=broadcast_type,
            created_by=author,
            send_email=False,             # never re-email; that already happened upstream
            ws_recipients=0,
            cta_url=event_data.get("cta_url"),
            cta_label=event_data.get("cta_label"),
            requires_ack=requires_ack,
            scheduled_for=_deferred_until(event_data),
            source_frame=source_frame,
            idempotency_key=foreign_idem,
        )
        try:
            db.add(new_row)
            await db.commit()
            await db.refresh(new_row)
            logger.info(
                f"[Reactor:AdminBroadcastReceived] materialized federated broadcast "
                f"from {source_frame} (foreign_id={event_data.get('broadcast_id')}) "
                f"→ local_id={new_row.id}"
            )
            if content is not None:
                content.update(title=title, body=body, broadcast_type=broadcast_type)
            return new_row.id
        except IntegrityError as exc:
            await db.rollback()
            # UNIQUE on (source_frame, idempotency_key) hit → row already
            # exists. Look it up and return its id.
            r = await db.execute(
                select(models.AdminBroadcast).where(
                    models.AdminBroadcast.source_frame == source_frame,
                    models.AdminBroadcast.idempotency_key == foreign_idem,
                )
            )
            existing = r.scalar_one_or_none()
            if existing is not None and existing.is_active is False and existing.ws_recipients == HELD_FOR_COPY:
                # §MCPTEST30 V0639: its edit came first and holds the place with the edited words: the copy goes live
                # with them, and with the rest of the Sent (its button, its acknowledgement, its schedule).
                existing.is_active, existing.ws_recipients = True, 0
                existing.cta_url, existing.cta_label = event_data.get("cta_url"), event_data.get("cta_label")
                existing.requires_ack, existing.scheduled_for = requires_ack, _deferred_until(event_data)
                await db.commit()
                logger.info(
                    f"[Reactor:AdminBroadcastReceived] federated broadcast from {source_frame} idem={foreign_idem} "
                    f"arrived after its edit: local_id={existing.id} goes live with the edited words"
                )
                if content is not None:
                    content.update(title=existing.title, body=existing.body, broadcast_type=existing.broadcast_type)
                return existing.id
            if existing is not None and existing.is_active is False:
                # §MCPTEST30 V0639: retracted already (its retract came first, or this is a redelivery after one): it
                # stays retracted and no live toast goes out. The admin list reads the real words: the Sent's in place
                # of a placeholder's, an edit's where one reached the place first (newer than this Sent).
                if existing.title == PLACEHOLDER_TITLE:
                    existing.title, existing.body, existing.broadcast_type = title, body, broadcast_type
                    await db.commit()
                logger.info(
                    f"[Reactor:AdminBroadcastReceived] federated broadcast from {source_frame} idem={foreign_idem} "
                    f"arrived after its retract: local_id={existing.id} stays retracted"
                )
                return None
            if existing is not None:
                logger.debug(
                    f"[Reactor:AdminBroadcastReceived] dup foreign broadcast "
                    f"from {source_frame} idem={foreign_idem} — existing local_id={existing.id}"
                )
                if content is not None:
                    content.update(title=existing.title, body=existing.body, broadcast_type=existing.broadcast_type)
                return existing.id
            logger.warning(
                f"[Reactor:AdminBroadcastReceived] integrity error but no row found "
                f"for source_frame={source_frame} idem={foreign_idem}: {_constraint_of(exc)}"
            )
            return None


async def _apply_edit_to_local(event_data: dict) -> None:
    """For AdminBroadcastEdited from a foreign frame, locate the local row
    by (source_frame, idempotency_key) and patch the editable fields.

    D6-211 (2026-10-17): the edit of a broadcast to everyone carries its title, type and body (the sender's
    copy_content rule); an event with flags only (a targeted broadcast, or one from an older registry) changes
    nothing here."""
    source_frame = event_data.get("source_frame")
    if not source_frame or source_frame == LOCAL_FRAME:
        return
    foreign_bid = event_data.get("broadcast_id")
    values = {k: event_data[k] for k in ("title", "broadcast_type", "body") if event_data.get(k)}
    if foreign_bid is None or not values:
        logger.debug(
            f"[Reactor:AdminBroadcastReceived] AdminBroadcastEdited from {source_frame} "
            f"(no-op locally: the event carries no title, type or body)"
        )
        return
    foreign_idem = event_data.get("idempotency_key") or f"foreign-{foreign_bid}"
    async with get_db_context() as db:
        edited_ids = await _edit_rows(db, source_frame, foreign_idem, values)
        if edited_ids:
            logger.info(
                f"[Reactor:AdminBroadcastReceived] applied the edit of federated broadcast from {source_frame} "
                f"idem={foreign_idem} ({', '.join(sorted(values))}) → local_ids={edited_ids}"
            )
            return
        # §MCPTEST30 V0639 (agentvault2-aa, 2026-10-24; agentvault2-66's finding): an edit loses the same race as a
        # retract. Its reactor can reach this registry before the copy does; the UPDATE found nothing, and the copy
        # materialized afterwards with the words from before the edit, for good (29 "fedsuite event probe" copies on the
        # sandbox's beta operator kept their pre-edit titles). An edit that carries the whole content (D6-211's rule
        # for a broadcast to everyone) now holds the copy's place with it, inactive, so the copy that arrives goes live
        # with the edited words. One that carries part of it can only patch a copy that exists.
        if set(values) != {"title", "broadcast_type", "body"}:
            return
        author = await _local_author_id(db)
        if author is None:
            logger.warning(f"[Reactor:AdminBroadcastReceived] edit of a broadcast from {source_frame} "
                           f"idem={foreign_idem} found no copy, and no local developer can hold its place")
            return
        db.add(models.AdminBroadcast(
            title=values["title"], body=values["body"], broadcast_type=values["broadcast_type"], created_by=author,
            send_email=False, ws_recipients=HELD_FOR_COPY, is_active=False,
            source_frame=source_frame, idempotency_key=foreign_idem,
        ))
        try:
            await db.commit()
        except IntegrityError:
            # the copy (or a retract's place) arrived between the update and the insert: edit it now
            await db.rollback()
            edited_ids = await _edit_rows(db, source_frame, foreign_idem, values)
            logger.info(
                f"[Reactor:AdminBroadcastReceived] applied the edit of federated broadcast from {source_frame} "
                f"idem={foreign_idem}, which arrived during the edit → local_ids={edited_ids}"
            )
            return
        logger.info(
            f"[Reactor:AdminBroadcastReceived] edit of a broadcast from {source_frame} idem={foreign_idem} came before "
            f"its copy: its place holds the edited words, so the copy goes live with them when it arrives"
        )
        await _prune_places(db)


async def _edit_rows(db, source_frame: str, foreign_idem: str, values: dict) -> list:
    r = await db.execute(
        update(models.AdminBroadcast)
        .where(
            models.AdminBroadcast.source_frame == source_frame,
            models.AdminBroadcast.idempotency_key == foreign_idem,
        )
        .values(**values)
        .returning(models.AdminBroadcast.id)
    )
    ids = [row[0] for row in r.fetchall()]
    await db.commit()
    return ids


async def _apply_retract_to_local(event_data: dict) -> None:
    source_frame = event_data.get("source_frame")
    if not source_frame or source_frame == LOCAL_FRAME:
        return
    # Retract is straightforward: find by foreign idempotency_key, flip is_active.
    foreign_bid = event_data.get("broadcast_id")
    if foreign_bid is None:
        return
    # If there's an idempotency key, use that to disambiguate
    foreign_idem = event_data.get("idempotency_key") or f"foreign-{foreign_bid}"
    async with get_db_context() as db:
        retracted_ids = await _retract_rows(db, source_frame, foreign_idem)
        if retracted_ids:
            logger.info(
                f"[Reactor:AdminBroadcastReceived] retracted federated broadcast(s) "
                f"from {source_frame} idem={foreign_idem} → local_ids={retracted_ids}"
            )
            return
        # §MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): the retract can come first. Sent and Retracted are separate
        # reactors, each with its own lag, so a broadcast retracted seconds after it was sent can be retracted here
        # before its copy exists: the UPDATE found nothing, said nothing, and the copy materialized afterwards ACTIVE
        # for good (broadcast 1095 on the alpha operator: sent 17:10:25.6Z, retracted 17:10:39.9Z; the beta operator
        # materialized it at 17:10:53.2Z; 24 such copies lived on the two sandbox operators). Its key now holds a
        # retracted row, so the copy that arrives later meets it and stays retracted.
        if event_data.get("targeted"):
            return            # an organization's broadcast or a direct notice: never copied here, no place to hold
        author = await _local_author_id(db)
        if author is None:
            logger.warning(f"[Reactor:AdminBroadcastReceived] retract of a broadcast from {source_frame} "
                           f"idem={foreign_idem} found no copy, and no local developer can hold its place")
            return
        db.add(models.AdminBroadcast(
            title=PLACEHOLDER_TITLE,
            body=f"[Federated from {source_frame}: retracted there before its copy arrived here]",
            broadcast_type="info", created_by=author, send_email=False, ws_recipients=0, is_active=False,
            source_frame=source_frame, idempotency_key=foreign_idem,
        ))
        try:
            await db.commit()
        except IntegrityError:
            # the copy arrived between the update and the insert: retract it now
            await db.rollback()
            retracted_ids = await _retract_rows(db, source_frame, foreign_idem)
            logger.info(
                f"[Reactor:AdminBroadcastReceived] retracted federated broadcast(s) from {source_frame} "
                f"idem={foreign_idem}, which arrived during the retract → local_ids={retracted_ids}"
            )
            return
        logger.info(
            f"[Reactor:AdminBroadcastReceived] retract of a broadcast from {source_frame} idem={foreign_idem} came "
            f"before its copy: its place is held retracted, so the copy stays retracted when it arrives"
        )
        await _prune_places(db)


async def _prune_places(db) -> None:
    """Places a retract or an edit held that no copy met within PLACEHOLDER_TTL: deleted, so the rows stay bounded."""
    pruned = await db.execute(
        delete(models.AdminBroadcast)
        .where(
            or_(models.AdminBroadcast.title == PLACEHOLDER_TITLE,
                models.AdminBroadcast.ws_recipients == HELD_FOR_COPY),
            models.AdminBroadcast.is_active.is_(False),
            models.AdminBroadcast.created_at < datetime.now(timezone.utc) - PLACEHOLDER_TTL,
        )
        .returning(models.AdminBroadcast.id)
    )
    gone = [row[0] for row in pruned.fetchall()]
    await db.commit()
    if gone:
        logger.info(f"[Reactor:AdminBroadcastReceived] pruned {len(gone)} place(s) no copy met within "
                    f"{PLACEHOLDER_TTL.days} days: local_ids={gone}")


async def _retract_rows(db, source_frame: str, foreign_idem: str) -> list:
    # ws_recipients=0: a place an edit held is retracted too, and stops waiting for its copy (HELD_FOR_COPY)
    r = await db.execute(
        update(models.AdminBroadcast)
        .where(
            models.AdminBroadcast.source_frame == source_frame,
            models.AdminBroadcast.idempotency_key == foreign_idem,
        )
        .values(is_active=False, ws_recipients=0)
        .returning(models.AdminBroadcast.id)
    )
    ids = [row[0] for row in r.fetchall()]
    await db.commit()
    return ids


# ────────────────────────────────────────────────────────────────────────────
# Reactor classes — one per event type
# ────────────────────────────────────────────────────────────────────────────

class AdminBroadcastSentReceived(EventStoreReactor):
    event_type = "AdminBroadcastSent"
    leader_key = "reactor_admin_broadcast_sent"
    name = "AdminBroadcastSentReceived"

    async def handle_event(self, event_data: dict) -> None:
        content: dict = {}           # the words the copy carries: an edit's that came first, else the Sent's
        local_id = await _materialize_received_broadcast(event_data, content)
        if local_id is None:
            return
        if _deferred_until(event_data) is not None:
            # D6-211: scheduled; broadcast_scheduler pushes it at its time
            return
        # Re-fire the live notification locally so connected devs see the toast.
        try:
            await broadcast_notification(
                title=content.get("title") or event_data.get("title") or "(federated broadcast)",
                message=content.get("body") or event_data.get("body") or "[federated]",
                notification_type=content.get("broadcast_type") or event_data.get("broadcast_type") or "info",
            )
        except Exception as e:
            logger.warning(
                f"[Reactor:{self.name}] local WS re-broadcast failed for id={local_id}: {e}"
            )


class AdminBroadcastEditedReceived(EventStoreReactor):
    event_type = "AdminBroadcastEdited"
    leader_key = "reactor_admin_broadcast_edited"
    name = "AdminBroadcastEditedReceived"

    async def handle_event(self, event_data: dict) -> None:
        await _apply_edit_to_local(event_data)


class AdminBroadcastRetractedReceived(EventStoreReactor):
    event_type = "AdminBroadcastRetracted"
    leader_key = "reactor_admin_broadcast_retracted"
    name = "AdminBroadcastRetractedReceived"

    async def handle_event(self, event_data: dict) -> None:
        await _apply_retract_to_local(event_data)


# ─── module-level start/stop bridges (called from main.py lifespan) ────────

_sent: Optional[AdminBroadcastSentReceived] = None
_edited: Optional[AdminBroadcastEditedReceived] = None
_retracted: Optional[AdminBroadcastRetractedReceived] = None


def _gated() -> bool:
    return os.getenv("REACTOR_ADMIN_BROADCAST_RECEIVED_ENABLED", "true").lower() == "true"


async def start() -> None:
    global _sent, _edited, _retracted
    if not _gated():
        logger.info("[Reactor:AdminBroadcastReceived] disabled by env gate")
        return
    if _sent is None:
        _sent = AdminBroadcastSentReceived()
    if _edited is None:
        _edited = AdminBroadcastEditedReceived()
    if _retracted is None:
        _retracted = AdminBroadcastRetractedReceived()
    await _sent.start()
    await _edited.start()
    await _retracted.start()


async def stop() -> None:
    global _sent, _edited, _retracted
    for r in (_sent, _edited, _retracted):
        if r is not None:
            try:
                await r.stop()
            except Exception as e:
                logger.warning(f"reactor stop error: {e}")
    _sent = _edited = _retracted = None
