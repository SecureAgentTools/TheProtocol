"""§MCPTEST30 (2026-10-06): a webhook that has ever delivered can be deleted, and so can the account that owns it.

Measured on sbx-alpha by the federation suite (run a1ffe1c5198e4e9e, chat_g1's cleanup, 18:22Z):
DELETE /api/v1/webhooks/<id> answered 409 "Referenced record does not exist". Postgres had refused:
`update or delete on table "developer_webhooks" violates foreign key constraint "webhook_deliveries_webhook_id_fkey"`.
webhook_deliveries.webhook_id references developer_webhooks.id with no ON DELETE CASCADE, and both delete paths removed
the webhook alone:
- the developer's own route, so a webhook with any delivery could never be deleted;
- account deletion's bulk delete, so ONE such webhook failed the whole deletion, which runs in a single transaction.

The deliveries now go first, in the same transaction. Pinned through the real route with a session that records what it
is asked to do, and through the account-deletion function's own statements, compiled. RED on the pre-change tree.

V0643 (agentvault2-66, 2026-10-25): both delete routes lock the webhook row first, so a delivery recorded between the two
deletes cannot fail the webhook's own (tests/test_webhook_delete_race_db.py drives that race on a real Postgres). Here:
the route asks the owned read for the lock, the alias route's own select carries it, and a plain read does not take it.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import re
import types

from sqlalchemy.dialects import postgresql

webhooks = importlib.import_module("agentvault_registry.routers.webhooks")
account_deletion = importlib.import_module("agentvault_registry.routers.account_deletion")
developers = importlib.import_module("agentvault_registry.routers.developers")


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _Session:
    """Records the order of what the route asks: statements (compiled), deletes, commits."""

    def __init__(self):
        self.calls = []

    async def execute(self, stmt):
        self.calls.append(("execute", _sql(stmt)))
        return types.SimpleNamespace(rowcount=3)

    async def delete(self, obj):
        self.calls.append(("delete", obj))

    async def commit(self):
        self.calls.append(("commit", None))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_the_route_removes_the_deliveries_before_the_webhook_in_one_transaction(monkeypatch):
    hook = types.SimpleNamespace(id="b9ff1a2c-5a40-43e6-a9a5-968fe779436a", developer_id=1)

    asked = {}

    async def _owned(webhook_id, developer_id, db, *, for_update=False):
        assert (webhook_id, developer_id) == (hook.id, 1), "the ownership check still runs first"
        asked["for_update"] = for_update
        return hook

    monkeypatch.setattr(webhooks, "_get_owned_webhook", _owned)
    db = _Session()
    _run(webhooks.delete_webhook(hook.id, developer=types.SimpleNamespace(id=1), db=db))
    kinds = [k for k, _ in db.calls]
    assert kinds == ["execute", "delete", "commit"], db.calls
    stmt = db.calls[0][1]
    assert stmt.startswith("DELETE FROM webhook_deliveries"), stmt
    assert f"webhook_deliveries.webhook_id = '{hook.id}'" in stmt, "only THIS webhook's history"
    assert db.calls[1][1] is hook
    assert asked == {"for_update": True}, "the webhook row is locked before anything goes"


def test_account_deletion_removes_the_deliveries_of_its_own_webhooks_first():
    """Compiled from the function's own statements, in the order it issues them: the deliveries of the developer's
    webhooks, then the webhooks. A delete scoped to anything wider would take another developer's history."""
    src = inspect.getsource(account_deletion.anonymize_developer)
    i_deliv = src.find("delete(models.WebhookDelivery)")
    i_hooks = src.find("delete(models.DeveloperWebhook)")
    assert i_deliv != -1 and i_hooks != -1, "both deletes are issued by anonymize_developer"
    assert i_deliv < i_hooks, "the deliveries must go before the webhooks they reference"
    models = importlib.import_module("agentvault_registry.models")
    from sqlalchemy import delete, select
    stmt = delete(models.WebhookDelivery).where(models.WebhookDelivery.webhook_id.in_(
        select(models.DeveloperWebhook.id).where(models.DeveloperWebhook.developer_id == 42)))
    sql = _sql(stmt)
    assert re.search(r"DELETE FROM webhook_deliveries WHERE webhook_deliveries\.webhook_id IN "
                     r"\(SELECT developer_webhooks\.id\s+FROM developer_webhooks\s+WHERE developer_webhooks\.developer_id = 42\)",
                     sql), sql
    # the function builds exactly that statement: the same three names, in that nesting
    seg = src[i_deliv:i_hooks]
    assert "models.WebhookDelivery.webhook_id.in_(" in seg and "select(models.DeveloperWebhook.id)" in seg
    assert "models.DeveloperWebhook.developer_id == developer_id" in seg
    assert 'report["webhook_deliveries_deleted"]' in seg, "the report says how much history went"


class _OwnedSession(_Session):
    """The alias route reads the webhook itself: its first statement (the owned select) answers with the hook."""

    def __init__(self, hook):
        super().__init__()
        self._hook = hook

    async def execute(self, stmt):
        sql = _sql(stmt)
        self.calls.append(("execute", sql))
        if sql.startswith("SELECT"):
            return types.SimpleNamespace(scalar_one_or_none=lambda: self._hook)
        return types.SimpleNamespace(rowcount=3)


def test_the_developers_alias_route_removes_the_deliveries_first_too():
    """§DOCSFIX D6-761 (2026-10-16): DELETE /api/v1/developers/webhooks/{id}, the same act under the developer prefix,
    still deleted the webhook alone, so there a webhook that had ever delivered could not be deleted either."""
    hook = types.SimpleNamespace(id="5d0c7e9a-2f1b-4c3d-8e6f-7a8b9c0d1e2f", developer_id=7)
    db = _OwnedSession(hook)
    _run(developers.delete_developer_webhook(hook.id, current_developer=types.SimpleNamespace(id=7), db=db))
    kinds = [k for k, _ in db.calls]
    assert kinds == ["execute", "execute", "delete", "commit"], db.calls
    assert db.calls[0][1].startswith("SELECT"), "the ownership check still runs first"
    assert "developer_webhooks.developer_id = 7" in db.calls[0][1]
    assert db.calls[0][1].rstrip().endswith("FOR UPDATE"), "the webhook row is locked before anything goes"
    stmt = db.calls[1][1]
    assert stmt.startswith("DELETE FROM webhook_deliveries"), stmt
    assert f"webhook_deliveries.webhook_id = '{hook.id}'" in stmt, "only THIS webhook's history"
    assert db.calls[2][1] is hook


def test_the_owned_read_locks_the_row_only_when_asked():
    """The helper the delete route asks: FOR UPDATE with for_update=True, none by default, so the read, update and test
    routes that share it take no lock."""
    hook = types.SimpleNamespace(id="0a9e8d7c-6b5a-4f3e-9d2c-1b0a9f8e7d6c", developer_id=3)
    locked, plain = _OwnedSession(hook), _OwnedSession(hook)
    assert _run(webhooks._get_owned_webhook(hook.id, 3, locked, for_update=True)) is hook
    assert _run(webhooks._get_owned_webhook(hook.id, 3, plain)) is hook
    assert locked.calls[0][1].rstrip().endswith("FOR UPDATE"), locked.calls
    assert "FOR UPDATE" not in plain.calls[0][1], plain.calls
