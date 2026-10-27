"""A webhook that is taking deliveries can still be deleted (agentvault2-66, 2026-10-25).

Measured in the V0641 operator read on sbxalphaop: deleteWebhook answered 409 and the webhook stayed (disabled later by
the dispatcher at ten failures). The hook subscribed to agent.created, agent.deleted and agent.updated, and the parallel
lifecycles wrote it a delivery every few seconds (21 rows, the last 1.1 s before the refusal). Both delete routes
remove the deliveries and then the webhook in two statements, and webhook_deliveries references the webhook with no ON
DELETE CASCADE (the ORM's own cascade loads the deliveries when the webhook is deleted and removes those it loaded), so a
delivery committed after that load and before the commit failed the webhook's own delete on the foreign key.

The fix locks the webhook row first. A delivery being recorded then waits for the delete (its foreign-key check needs a
share lock on that row) and finds its webhook gone, which its writer reports as "not recorded" in its own session
(background_tasks/reactor_helpers.dispatch_webhook_event opens one for every fan-out).

THE TEST DRIVES THE INTERLEAVING, not a race left to chance: the route's session runs normally up to its
`session.delete(webhook)` (which loads the deliveries for the cascade), then a second session records a delivery for the
same webhook and the route goes on 0.5 s later. RED before the fix: the delivery commits in that gap and the route's
commit raises IntegrityError on the webhook. THE CONTROL (a quiet webhook
is deleted with its history) passes before and after.

Skipped unless MEMBERSHIP_TEST_DB names a throwaway database it may WIPE.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import uuid

import pytest

DB = os.environ.get("MEMBERSHIP_TEST_DB")
if not DB:
    pytest.skip("needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.",
                allow_module_level=True)

from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

UTC = dt.timezone.utc


@pytest.fixture
async def engine():
    from agentvault_registry.models import Base
    eng = create_async_engine(DB)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


def _maker(eng):
    return async_sessionmaker(eng, expire_on_commit=False)


async def _seed(eng):
    from agentvault_registry.models import Developer, DeveloperWebhook, WebhookDelivery
    async with _maker(eng)() as s:
        dev = Developer(name="hooks", email=f"hooks-{uuid.uuid4().hex[:8]}@test.local", hashed_password="x",
                        is_verified=True)
        s.add(dev)
        await s.flush()
        hook = DeveloperWebhook(id=str(uuid.uuid4()), developer_id=dev.id, url="https://hook.example.test/in",
                                events=["agent.created", "agent.deleted"], secret="s", is_active=True)
        s.add(hook)
        await s.flush()
        s.add(WebhookDelivery(id=str(uuid.uuid4()), webhook_id=hook.id, event_type="agent.created", payload={},
                              delivered_at=dt.datetime.now(UTC), retry_count=0))
        await s.commit()
        return dev.id, hook.id


async def _record_delivery(eng, webhook_id: str) -> None:
    """The dispatcher's record step, in a session of its own (reactor_helpers.dispatch_webhook_event)."""
    from agentvault_registry.models import WebhookDelivery
    async with _maker(eng)() as s:
        s.add(WebhookDelivery(id=str(uuid.uuid4()), webhook_id=webhook_id, event_type="agent.deleted", payload={},
                              delivered_at=dt.datetime.now(UTC), retry_count=0))
        await s.commit()


async def _left(eng, webhook_id: str):
    from agentvault_registry.models import DeveloperWebhook, WebhookDelivery
    async with _maker(eng)() as s:
        hooks = await s.scalar(select(func.count()).select_from(DeveloperWebhook)
                               .where(DeveloperWebhook.id == webhook_id))
        rows = await s.scalar(select(func.count()).select_from(WebhookDelivery)
                              .where(WebhookDelivery.webhook_id == webhook_id))
        return hooks, rows


async def _delete_while_a_delivery_lands(eng, call):
    """Run `call(session, developer, webhook id)` with a delivery recorded right after its session.delete(webhook)."""
    from agentvault_registry.models import Developer
    dev_id, wid = await _seed(eng)
    writer = None
    async with _maker(eng)() as d:
        real_delete = d.delete

        async def delete(obj, *a, **k):
            nonlocal writer
            res = await real_delete(obj, *a, **k)   # the cascade has loaded the deliveries it will remove
            if writer is None and getattr(obj, "__tablename__", None) == "developer_webhooks":
                writer = asyncio.create_task(_record_delivery(eng, wid))
                await asyncio.sleep(0.5)   # unlocked: the delivery commits here; locked: it waits on the webhook row
            return res

        d.delete = delete
        dev = await d.get(Developer, dev_id)
        await call(d, dev, wid)
    assert writer is not None, "the route never deleted the webhook: check the test, not the code"
    return wid, writer


async def test_the_webhook_route_deletes_a_webhook_whose_delivery_lands_mid_delete(engine):
    from agentvault_registry.routers import webhooks as api
    wid, writer = await _delete_while_a_delivery_lands(
        engine, lambda d, dev, wid: api.delete_webhook(wid, developer=dev, db=d))
    with pytest.raises(IntegrityError):   # the delivery found its webhook gone: its writer reports it, the delete stood
        await writer
    assert await _left(engine, wid) == (0, 0)


async def test_the_developer_route_deletes_a_webhook_whose_delivery_lands_mid_delete(engine):
    from agentvault_registry.routers import developers as api
    wid, writer = await _delete_while_a_delivery_lands(
        engine, lambda d, dev, wid: api.delete_developer_webhook(wid, current_developer=dev, db=d))
    with pytest.raises(IntegrityError):
        await writer
    assert await _left(engine, wid) == (0, 0)


async def test_control_a_quiet_webhook_is_deleted_with_its_history(engine):
    from agentvault_registry.models import Developer
    from agentvault_registry.routers import webhooks as api
    dev_id, wid = await _seed(engine)
    async with _maker(engine)() as d:
        dev = await d.get(Developer, dev_id)
        await api.delete_webhook(wid, developer=dev, db=d)
    assert await _left(engine, wid) == (0, 0)
