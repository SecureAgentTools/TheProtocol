"""V0657 recut: an admin ruling of a dispute that is not about a Guild order answers its ruling, not a 500.

V0657 (a) item 22 writes the ruling's money into the dispute's record and commits. An AsyncSession expires every
attribute of the row on that commit, and the route went on to read the row (the webhook, the notices, its answer):
outside the session's greenlet that read raises sqlalchemy.exc.MissingGreenlet, answered as 500 ("A database error
occurred") after the ruling, the compensation and the notices had all happened; a retry answered "already
resolved". V0657's pair proof found it (session-tester, room seq 1879): PUT /admin/disputes/{1,2,3}/ruling all 500.
The route's earlier tests used a session that never expires anything, so they could not see it. Here the dispute row
behaves as an AsyncSession's does: a commit expires it, a read before a refresh raises MissingGreenlet, a refresh
loads it again. Red on 13d2011ac.
"""
import asyncio
import types

import pytest

POSTER = "did:theprotocol:poster-0001"
WORKER = "did:theprotocol:worker-0001"


class _Expiring:
    """A row as an AsyncSession holds it."""

    def __init__(self, **kw):
        object.__setattr__(self, "_d", dict(kw))
        object.__setattr__(self, "_expired", False)

    def __getattr__(self, name):
        if object.__getattribute__(self, "_expired"):
            from sqlalchemy.exc import MissingGreenlet
            raise MissingGreenlet(f"greenlet_spawn has not been called; can't call await_only() here ({name})")
        d = object.__getattribute__(self, "_d")
        if name in d:
            return d[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        object.__getattribute__(self, "_d")[name] = value


class _Result:
    def scalar_one_or_none(self):
        return None


class _Session:
    """Expires what it holds on commit, as expire_on_commit does; refresh() loads one row again."""

    def __init__(self, rows):
        self.rows, self.commits, self.refreshed = list(rows), 0, 0

    async def execute(self, stmt, params=None):
        return _Result()

    async def commit(self):
        self.commits += 1
        for r in self.rows:
            object.__setattr__(r, "_expired", True)

    async def refresh(self, obj):
        self.refreshed += 1
        if isinstance(obj, _Expiring):
            object.__setattr__(obj, "_expired", False)

    async def rollback(self):
        return None

    async def flush(self):
        return None


@pytest.fixture
def ruled(monkeypatch):
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.background_tasks import reactor_helpers as rh
    from agentvault_registry.crud import crud_disputes as cd
    from agentvault_registry.routers import admin
    from agentvault_registry.services import contract_settlement as cs
    from agentvault_registry.services import dispute_settlement as ds

    class _T:
        def isoformat(self):
            return "2026-11-07T12:03:56+00:00"
    dispute = _Expiring(id=1, status="OPEN", ruling=None, complainant_did=POSTER, defendant_did=WORKER, evidence=[],
                        contract_id=None, contract_ref=None, guild_order_id=None, reason="quality", filed_by=None,
                        amount_claimed=None, outcome=None, ruled_by=None, ruled_at=None, ruling_note=None,
                        created_at=None, updated_at=_T())
    session = _Session([dispute])

    async def get_dispute(db, dispute_id):
        return dispute

    async def update_ruling(db, dispute_id, ruling, **kw):
        dispute.status, dispute.ruling, dispute.ruled_by = "CLOSED", ruling, kw.get("ruled_by")
        dispute.ruling_note, dispute.ruled_at, dispute.outcome = kw.get("note"), _T(), {"ruling": ruling}
        return dispute

    async def compensation(db, d, ruling):
        return {"applied": True, "amount": 5, "currency": "ECU"}

    async def no_contract(db, d, ruling):
        return None

    async def no_order(db, d):
        return None

    async def nothing(*a, **k):
        return 0
    monkeypatch.setattr(cd, "get_dispute_by_id", get_dispute)
    monkeypatch.setattr(cd, "update_dispute_ruling", update_ruling)
    monkeypatch.setattr(cd, "process_compensation", compensation)
    monkeypatch.setattr(cs, "settle_linked_contract_for_ruling", no_contract)
    monkeypatch.setattr(ds, "linked_guild_order", no_order)
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", nothing)
    monkeypatch.setattr(push_notify, "notify_agent_owners", nothing)
    admin_dev = types.SimpleNamespace(id=6, email="ruler@example.invalid")

    def rule(ruling="IN_FAVOR_OF_COMPLAINANT"):
        async def go():
            return await admin.update_dispute_ruling_endpoint(1, ruling=ruling, db=session, current_admin=admin_dev)
        return asyncio.run(go())
    return types.SimpleNamespace(rule=rule, session=session, dispute=dispute)


def test_a_ruling_that_moved_a_wallet_claim_answers_its_ruling_after_the_commit(ruled):
    out = ruled.rule()                                        # BASE: sqlalchemy.exc.MissingGreenlet (answered 500)
    assert out["status"] == "CLOSED" and out["ruling"] == "IN_FAVOR_OF_COMPLAINANT"
    assert out["updated_at"] == "2026-11-07T12:03:56+00:00" and out["dispute_id"] == 1
    assert out["outcome"]["money"]["applied"] is True and out["outcome"]["money"]["amount"] == 5
    assert ruled.session.commits >= 1 and ruled.session.refreshed >= 1


def test_a_dismissal_answers_too(ruled):
    out = ruled.rule("DISMISSED")
    assert out["ruling"] == "DISMISSED" and out["status"] == "CLOSED"
