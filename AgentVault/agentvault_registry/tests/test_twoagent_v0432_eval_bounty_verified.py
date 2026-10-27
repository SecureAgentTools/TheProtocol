"""§TWOAGENT G3 follow-up (V0432) — an OBJECTIVE (eval-bounty) settle tells the worker's owner, like a poster's verify.

V0431 wired `guild.verified` into `verify` and named the gap it left: the FORGE eval-bounty auto-settle paths (local and
cross-registry) settle a submitted order without any notice to the worker. Now the local path sends the owner-scoped
webhook and the cross-registry path sends the advisory notice to the worker's home.

RED on V0431: neither path notifies.
"""
from __future__ import annotations

import types

import pytest


class _R:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount

    def scalar(self):
        return 1


class _Db:
    async def execute(self, stmt, params=None):
        return _R()

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def g(monkeypatch):
    from agentvault_registry.routers import guild

    async def _nothing(*a, **k):
        return None

    async def _order(db, oid):
        return {"id": oid, "worker_did": "did:w", "poster_did": "did:p", "title": "t", "currency": "SBXA",
                "worker_home_registry": "https://home.test", "bounty": "1.0"}

    async def _cred(o2, stars=5):
        return {"kind": "guild.work_credential.v1"}

    async def _ship(db, o2, credential, stars):
        return True
    for name in ("_payout_with_royalty", "_resolve_worker_stake", "_audit", "_tr_touch"):
        monkeypatch.setattr(guild, name, _nothing)
    monkeypatch.setattr(guild, "_load", _order)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(guild, "_ship_work_credential", _ship)
    monkeypatch.setattr(guild.guild_reputation, "fold_work_reputation", _nothing)
    monkeypatch.setattr(guild.guild_reputation, "issue_work_credential", _cred)
    monkeypatch.setattr(guild.guild_contract_mirror, "sync_from_order", _nothing)
    monkeypatch.setattr(guild.guild_escrow, "escrow_payout", _nothing)
    seen: list = []
    monkeypatch.setattr(guild, "_guild_webhook", lambda event, dids, data: seen.append(("hook", event, tuple(dids))),
                        raising=False)
    monkeypatch.setattr(guild, "_ship_guild_notice", lambda o, kind, extra: seen.append(("notice", kind, o["worker_did"])),
                        raising=False)
    guild._seen = seen
    return guild


async def test_a_local_objective_settle_tells_the_worker(g):
    o = {"id": "gwo_1", "worker_did": "did:w", "poster_did": "did:p", "title": "t", "currency": "SBXA", "bounty": "1.0",
         "fee_bps": 250, "payee_did": None}
    out = await g._auto_settle_eval_bounty(_Db(), o, "gwo_1", actor_did="did:w", score=0.9)
    assert out["status"] == "settled"
    assert g._seen == [("hook", "guild.verified", ("did:w", "did:w"))], g._seen


async def test_a_cross_registry_objective_settle_tells_the_workers_home(g, monkeypatch):
    from agentvault_registry.services import exchange_service

    async def _credit(*a, **k):
        return None
    monkeypatch.setattr(exchange_service, "_add_gateway_credit", _credit)
    o = {"id": "gwo_2", "worker_did": "did:w", "poster_did": "did:p", "title": "t", "currency": "SBXA", "bounty": "1.0",
         "fee_bps": 250, "payee_did": None, "worker_home_registry": "https://home.test"}
    out = await g._auto_settle_eval_bounty_xreg(_Db(), o, "gwo_2", actor_did="did:w", score=0.9)
    assert out["status"] == "settled"
    assert g._seen == [("notice", "verified", "did:w")], g._seen
