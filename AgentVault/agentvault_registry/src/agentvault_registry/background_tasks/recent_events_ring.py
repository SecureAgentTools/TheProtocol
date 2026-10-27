"""
recent_events_ring — keep the registry's public event SEED complete.

§BRIDGE R7-B (2026-08-19)

WHAT THIS FIXES
    `/api/v1/public/eventstore-recent` serves a Redis ring that used to be
    written only by the registry's OWN emitter. On frame-c that is a minority of
    what happens on the frame: measured over 20 minutes, `teg-balance-outbox`
    emitted 813 events and `registry` 350. So the seed showed roughly 30% of the
    frame's activity and silently omitted the rest.

    This task makes the ring complete by ringing what the EventStore BROADCASTS
    — which is everything it stores, whoever emitted it.

WHY IT NEEDS NO NEW INFRASTRUCTURE, NO NEW SUBSCRIPTION, AND NO ES CHANGE
    The EventStore already publishes every broadcast to Redis Pub/Sub
    (`es:ws:broadcast:<namespace>`) so that its own workers can fan out to
    websocket clients. Redis Pub/Sub is NOT database-scoped: a client on db 0
    (the registry) receives what a client on db 1 (the EventStore) publishes on
    the same server. Verified live before this file was written.

    So this is the registry listening to its OWN EventStore, on infrastructure
    that already exists, which is exactly the boundary the system keeps:
    "registries only subscribe to their own eventstore by design". No foreign
    frame is touched here.

THREE THINGS THE REAL SYSTEM FORCED
    1. EVERY EVENT IS PUBLISHED THREE TIMES — once on `agent:<aggregate_id>`,
       once on `events:all`, once on `events:<EventType>`. A subscriber that
       rings every message would triple every event. We take `events:all` only.
    2. This task is the SINGLE WRITER of the ring. The emitter no longer writes
       it, because an event emitted here comes back through this channel once
       the EventStore has stored it — writing in both places would double-count
       our own events while leaving everyone else's single. One writer, no
       dedup state, no drift.
    3. THE WIRE IS AT-LEAST-ONCE. Measured 2026-08-19 on frame-c: 47 messages on
       `events:all` carrying 28 unique event ids, and the same doubling observed
       on the PUBLIC websocket (64 messages / 42 ids). The cause is upstream and
       known — the EventStore broadcasts once at accept time (`routers/events.py`,
       202 branch) and again once its Kafka consumer has stored the event
       (`services/kafka_consumer.py`) — so anything ingested over its HTTP route
       while KAFKA_ENABLED=true arrives twice. We remember the last SEEN_CAP ids
       and ring each event once. This is not a patch over the upstream double
       publish (that changes what every websocket client on the fleet receives
       and is a separate decision); it is the correct reading of an at-least-once
       stream, and it keeps the ring's advertised window honest: 400 entries of
       which half are repeats is a 200-event window pretending to be 400.
    4. LEADERSHIP MUST BE ACQUIRED AND HELD, NOT CHECKED. `leader.is_leader()`
       says so in its own docstring: "Does NOT acquire". Nothing else acquires
       this task's lock, so a version of this loop that gated on `is_leader()`
       returned False forever and never subscribed at all — deployed, healthy,
       and completely inert. We `try_acquire_leadership()`, and because the lock
       expires after LOCK_TTL (30s) we cannot sit inside a blocking
       `pubsub.listen()`: we poll with a timeout so the renewal can run on
       schedule. A lock that lapses while we hold the subscription open is a
       SECOND writer, which is the one thing this design does not tolerate.

FAILURE BEHAVIOUR
    Fail-quiet and bounded, like every other cache in this system: if Redis is
    unreachable the loop backs off with jitter and the ring simply goes stale.
    The endpoint publishes `count`, so a stale ring is visible rather than
    presented as truth. A seed is never worth failing anything for.
"""
import asyncio
import json
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)

_task = None
_running = False

#: Matches whatever namespace this frame's EventStore uses. A registry's Redis
#: only ever carries its own EventStore's channel, so the wildcard cannot pick
#: up a foreign frame — and it means this needs no configuration that could be
#: set wrong on a new node.
CHANNEL_PATTERN = "es:ws:broadcast:*"

#: The one channel that carries each event exactly once (see note 1 above).
ALL_EVENTS_CHANNEL = "events:all"

#: Leader-election lock name. One writer per registry, across all gunicorn
#: workers (38 on registry-a).
LEADER_TASK = "recent_events_ring"

#: How many recent event ids to remember for the repeat check (note 4). Ids only,
#: FIFO, so the memory is bounded by construction.
SEEN_CAP = 2000

_ringed = 0
_skipped_dupes = 0
_skipped_repeats = 0
_leader = False


def ring_stats() -> dict:
    """Observability: what this task has actually done, for /admin/workers."""
    return {
        "ringed": _ringed,
        "skipped_duplicate_channels": _skipped_dupes,
        "skipped_repeat_events": _skipped_repeats,
        "running": _running,
        "leader": _leader,
    }


async def _loop() -> None:
    global _running, _ringed, _skipped_dupes, _skipped_repeats, _leader
    from agentvault_registry.background_tasks.leader import (
        LEADER_CHECK_INTERVAL,
        LOCK_TTL,
        get_redis,
        release_leadership,
        renew_leadership,
        try_acquire_leadership,
    )
    from agentvault_registry.event_emitter import RECENT_EVENTS_RING

    from . import vitals as _vitals

    _running = True
    backoff = 0.5
    renew_every = max(5.0, LOCK_TTL / 3.0)
    # §VITALS: this worker SUBSCRIBES, it does not cycle — wrapping a subscription
    # that lives for hours in vitals.cycle() would stamp on entry and on exit and
    # say nothing in between. The leadership renewal below is the honest heartbeat:
    # it happens only while the poll loop is still turning, so a hang inside the
    # subscription stops the stamp exactly as a dead worker would.
    await _vitals.register(LEADER_TASK, module=__name__, pattern="subscriber",
                           interval_sec=renew_every, enabled=True)

    while _running:
        pubsub = None
        held = False
        try:
            # Note 3: ACQUIRE. Checking is not becoming.
            held = await try_acquire_leadership(LEADER_TASK)
            _leader = held
            if not held:
                await asyncio.sleep(LEADER_CHECK_INTERVAL)
                continue

            r = await get_redis()
            if r is None:
                await asyncio.sleep(min(backoff, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue

            pubsub = r.pubsub()
            await pubsub.psubscribe(CHANNEL_PATTERN)
            logger.info(
                "[recent_events_ring] leader; subscribed pattern=%s ring=%d",
                CHANNEL_PATTERN, RECENT_EVENTS_RING,
            )
            backoff = 0.5
            last_renew = time.monotonic()
            seen: set = set()
            seen_order: deque = deque()

            while _running:
                # Poll, never block: a blocking listen() cannot renew the 30s
                # leadership lock, and a lapsed lock is a second writer.
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

                now = time.monotonic()
                if now - last_renew >= renew_every:
                    if not await renew_leadership(LEADER_TASK):
                        # Losing leadership is an orderly handover, not a failure —
                        # the new leader stamps from here on.
                        logger.info("[recent_events_ring] lost leadership; unsubscribing")
                        held = False
                        _leader = False
                        break
                    last_renew = now
                    await _vitals.stamp(LEADER_TASK, _vitals.OUTCOME_OK,
                                        stats={"state": "subscribed"})

                if msg is None or msg.get("type") != "pmessage":
                    continue

                try:
                    raw = msg.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "replace")
                    payload = json.loads(raw)
                except Exception:
                    continue

                # Note 1: take the one channel that carries each event once.
                if payload.get("channel") != ALL_EVENTS_CHANNEL:
                    _skipped_dupes += 1
                    continue

                message = payload.get("message")
                if not isinstance(message, dict):
                    continue

                # Note 3: identity, not arrival, decides.
                ev = message.get("event") if isinstance(message.get("event"), dict) else message
                eid = ev.get("id") or ev.get("event_id")
                if eid:
                    if eid in seen:
                        _skipped_repeats += 1
                        continue
                    seen.add(eid)
                    seen_order.append(eid)
                    if len(seen_order) > SEEN_CAP:
                        seen.discard(seen_order.popleft())

                try:
                    await r.lpush("recent_events", json.dumps(message))
                    await r.ltrim("recent_events", 0, RECENT_EVENTS_RING - 1)
                    _ringed += 1
                except Exception as e:
                    logger.debug("[recent_events_ring] ring write failed: %s", e)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[recent_events_ring] loop error: %s", e)
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)
        finally:
            _leader = False
            if pubsub is not None:
                try:
                    await pubsub.close()
                except Exception:
                    pass
            if held:
                # Compare-and-delete on this worker's id, so releasing after a
                # lost lock cannot delete the new leader's.
                try:
                    await release_leadership(LEADER_TASK)
                except Exception:
                    pass


async def start_recent_events_ring() -> None:
    global _task
    if _task is not None:
        return
    _task = asyncio.create_task(_loop())


async def stop_recent_events_ring() -> None:
    global _task, _running
    _running = False
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
