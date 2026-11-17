"""§DOCSTRIAGE D1 (2026-11-13): a lock above the agent's balance answers 400 naming the balance, never 500.

POST /staking/stake raised its own HTTPException(400, "Insufficient balance...") inside a `try` whose catch-all
`except Exception` turned every error into 500 "Failed to process the lock request". The page promises 400
(`oracle/03_staking.md`: "at most your liquid balance (400 otherwise)"), and unstake already re-raises its own
HTTPException before its catch-all. Found by running the page's own example on the sandbox with a balance under 100.
"""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from agentvault_registry.routers import staking_enhanced as se
from agentvault_registry.schemas_enhanced import StakeRequest


class _Teg:
    def __init__(self, balance: str, fail_with: Exception = None):
        self._b, self._fail = Decimal(balance), fail_with
        self.staked = False

    async def get_balance(self, did):
        if self._fail:
            raise self._fail
        return self._b

    async def stake_tokens(self, agent_id, amount):   # pragma: no cover: a refused lock never reaches it
        self.staked = True
        return {"stake_id": "x"}


def _call(monkeypatch, balance="18.4", amount="100", teg=None):
    teg = teg or _Teg(balance)
    monkeypatch.setattr(se, "get_teg_client", lambda: teg)
    db = MagicMock()
    db.rollback = AsyncMock()
    agent = SimpleNamespace(id=1, did="did:theprotocol:test:agent")
    req = StakeRequest(amount=Decimal(amount), lock_period=90)
    return teg, db, asyncio.run(se.stake_tokens(req, BackgroundTasks(), db, agent, None))


def test_a_lock_above_the_balance_is_a_400_naming_the_balance(monkeypatch):
    teg = _Teg("18.4")
    with pytest.raises(HTTPException) as e:
        _call(monkeypatch, teg=teg, amount="100")
    assert e.value.status_code == 400, e.value.detail
    assert "Insufficient balance" in e.value.detail and "18.4" in e.value.detail and "100" in e.value.detail
    assert not teg.staked, "a refused lock must not reach the TEG"


def test_the_refusal_rolls_the_session_back(monkeypatch):
    db = MagicMock()
    db.rollback = AsyncMock()
    monkeypatch.setattr(se, "get_teg_client", lambda: _Teg("1"))
    agent = SimpleNamespace(id=1, did="did:theprotocol:test:agent")
    with pytest.raises(HTTPException):
        asyncio.run(se.stake_tokens(StakeRequest(amount=Decimal("100"), lock_period=90), BackgroundTasks(), db, agent, None))
    db.rollback.assert_awaited()


def test_an_unreachable_teg_is_still_a_503(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call(monkeypatch, teg=_Teg("0", fail_with=se.TEGClientError("down")))
    assert e.value.status_code == 503


def test_an_unexpected_failure_is_still_a_500(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _call(monkeypatch, teg=_Teg("0", fail_with=RuntimeError("boom")))
    assert e.value.status_code == 500
