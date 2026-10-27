"""Tests for services/reward_funding.py (§REWARDEVENTS 2026-08-11).

The shared registry-side waterfall rail: pays via TEG, emits ONE
TokensTransferred per returned leg, syncs the cached balance from TEG truth
on completed AND exhausted, never commits the caller's session. Hermetic —
TEG client, event emitter, and DB session are all mocked.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentvault_registry.services import reward_funding
from agentvault_registry.teg_client import TEGClientError


def _completed_body():
    return {
        "status": "completed",
        "funded_amount": "1000.0",
        "shortfall": "0",
        "new_target_balance": "1000.000000000000000000",
        "legs": [
            {"source": "fee_collector", "source_did": "teg:system:fee_collector",
             "amount": "40.0", "transaction_id": "tx-leg-1"},
            {"source": "treasury", "source_did": "did:theprotocol:teg_system_treasury",
             "amount": "960.0", "transaction_id": "tx-leg-2"},
        ],
    }


def _exhausted_error():
    err = TEGClientError("exhausted")
    err.teg_status_code = 400
    err.teg_response = {
        "status": "exhausted",
        "total_amount": "1000.0",
        "funded_amount": "14.88",
        "shortfall": "985.12",
        "new_target_balance": "14.880000000000000000",
        "legs": [
            {"source": "fee_collector", "source_did": "teg:system:fee_collector",
             "amount": "14.88", "transaction_id": "tx-partial-1"},
        ],
    }
    return err


def _fakes(fund_side_effect=None, fund_return=None, emit_return=True,
           emit_side_effect=None, agent_row=True):
    client = MagicMock()
    client.fund_reward = AsyncMock(side_effect=fund_side_effect,
                                   return_value=fund_return)
    emitter = MagicMock()
    emitter.emit_tokens_transferred = AsyncMock(return_value=emit_return,
                                                side_effect=emit_side_effect)
    agent = SimpleNamespace(liquid_balance=Decimal("0")) if agent_row else None
    row = MagicMock()
    row.scalar_one_or_none.return_value = agent
    db = MagicMock()
    db.execute = AsyncMock(return_value=row)
    db.commit = AsyncMock()
    return client, emitter, db, agent


async def _run(client, emitter, db, **kw):
    with patch.object(reward_funding, "get_teg_client", return_value=client), \
         patch.object(reward_funding, "get_event_emitter", return_value=emitter):
        return await reward_funding.fund_reward_via_waterfall(
            db,
            target_agent_did=kw.pop("target", "did:theprotocol:test-agent"),
            amount=kw.pop("amount", "1000.0"),
            reason=kw.pop("reason", "genesis_grant"),
            **kw,
        )


async def test_completed_emits_per_leg_and_syncs():
    client, emitter, db, agent = _fakes(fund_return=_completed_body())
    res = await _run(client, emitter, db, idempotency_key="genesis-x")
    assert res["status"] == "completed"
    assert res["first_transaction_id"] == "tx-leg-1"
    assert res["events_emitted"] == 2
    # one TokensTransferred per leg, with the leg's own source/amount/tx
    assert emitter.emit_tokens_transferred.await_count == 2
    first = emitter.emit_tokens_transferred.await_args_list[0].kwargs
    assert first["from_agent"] == "teg:system:fee_collector"
    assert first["to_agent"] == "did:theprotocol:test-agent"
    assert first["amount"] == "40.0"
    assert first["transaction_id"] == "tx-leg-1"
    assert "genesis_grant" in first["memo"] and "fee_collector" in first["memo"]
    # cache synced to TEG truth, session NOT committed (caller's discipline)
    assert agent.liquid_balance == Decimal("1000.000000000000000000")
    assert res["balance_synced"] is True
    db.commit.assert_not_awaited()


async def test_exhausted_reports_partial_and_still_emits_and_syncs():
    client, emitter, db, agent = _fakes(fund_side_effect=_exhausted_error())
    res = await _run(client, emitter, db)
    assert res["status"] == "exhausted"
    assert res["funded_amount"] == "14.88"
    assert res["shortfall"] == "985.12"
    # the committed partial leg IS emitted and the cache IS synced
    assert emitter.emit_tokens_transferred.await_count == 1
    assert agent.liquid_balance == Decimal("14.880000000000000000")
    assert res["first_transaction_id"] == "tx-partial-1"
    db.commit.assert_not_awaited()


async def test_hard_failure_raises_and_emits_nothing():
    err = TEGClientError("connection refused")  # no teg_response body
    client, emitter, db, agent = _fakes(fund_side_effect=err)
    with pytest.raises(TEGClientError):
        await _run(client, emitter, db)
    emitter.emit_tokens_transferred.assert_not_awaited()
    assert agent.liquid_balance == Decimal("0")


async def test_non_exhausted_400_body_still_raises():
    err = TEGClientError("bad request")
    err.teg_response = {"status": "rejected", "detail": "nope"}
    client, emitter, db, _ = _fakes(fund_side_effect=err)
    with pytest.raises(TEGClientError):
        await _run(client, emitter, db)
    emitter.emit_tokens_transferred.assert_not_awaited()


async def test_idempotency_key_passed_through_to_teg():
    client, emitter, db, _ = _fakes(fund_return=_completed_body())
    await _run(client, emitter, db, idempotency_key="genesis-did:x")
    assert client.fund_reward.await_args.kwargs["idempotency_key"] == "genesis-did:x"


async def test_source_agnostic_treasury_only_legs():
    """Waterfall order is policy-configurable (Commander 2026-08-11) — a
    treasury-only routing must emit exactly what TEG returned, no
    fee_collector assumptions."""
    body = _completed_body()
    body["legs"] = [{"source": "treasury",
                     "source_did": "did:theprotocol:teg_system_treasury",
                     "amount": "1000.0", "transaction_id": "tx-t-only"}]
    client, emitter, db, _ = _fakes(fund_return=body)
    res = await _run(client, emitter, db)
    assert res["events_emitted"] == 1
    kw = emitter.emit_tokens_transferred.await_args.kwargs
    assert kw["from_agent"] == "did:theprotocol:teg_system_treasury"
    assert kw["transaction_id"] == "tx-t-only"


async def test_leg_without_transaction_id_is_skipped_not_fatal():
    body = _completed_body()
    body["legs"][1] = {"source": "treasury", "source_did": "x", "amount": "1"}
    client, emitter, db, _ = _fakes(fund_return=body)
    res = await _run(client, emitter, db)
    assert res["events_emitted"] == 1
    assert emitter.emit_tokens_transferred.await_count == 1


async def test_emit_failure_never_fails_the_payment():
    client, emitter, db, agent = _fakes(fund_return=_completed_body(),
                                        emit_side_effect=RuntimeError("ES down"))
    res = await _run(client, emitter, db)
    assert res["status"] == "completed"
    assert res["events_emitted"] == 0
    # balance sync still happened — the money moved regardless of emission
    assert agent.liquid_balance == Decimal("1000.000000000000000000")


async def test_no_agent_row_is_fine_for_system_targets():
    client, emitter, db, _ = _fakes(fund_return=_completed_body(),
                                    agent_row=False)
    res = await _run(client, emitter, db)
    assert res["status"] == "completed"
    assert res["balance_synced"] is False


async def test_db_none_skips_sync_but_still_emits():
    client, emitter, _db, _ = _fakes(fund_return=_completed_body())
    with patch.object(reward_funding, "get_teg_client", return_value=client), \
         patch.object(reward_funding, "get_event_emitter", return_value=emitter):
        res = await reward_funding.fund_reward_via_waterfall(
            None, target_agent_did="did:x", amount="5", reason="achievement")
    assert res["balance_synced"] is False
    assert res["events_emitted"] == 2
