"""§FESUITE: an unstake that names a position touches only that position.

The console lists staking positions and offers Unstake on each one, while /staking/unstake took only an amount and
released it from the unlocked positions oldest first: pressing Unstake on a locked position answered "Unstaked." and
released a different one. `_positions_for_unstake` is the rule: no position_id keeps the original walk for every
existing caller; a named position is the only one touched, and a refusal (locked, too much, not an active position of
this agent) touches nothing.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers.staking_enhanced import _positions_for_unstake

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _pos(pid: str, amount: str, lock_days: int, age_days: int) -> SimpleNamespace:
    return SimpleNamespace(id=pid, amount=Decimal(amount), lock_period_days=lock_days,
                           staked_at=NOW - timedelta(days=age_days))


def test_without_a_position_the_oldest_first_walk_is_unchanged():
    stakes = [_pos("a", "10", 0, 5), _pos("b", "10", 30, 1)]
    assert _positions_for_unstake(stakes, None, Decimal("10"), NOW) == stakes
    assert _positions_for_unstake(stakes, "", Decimal("10"), NOW) == stakes


def test_a_named_unlocked_position_is_the_only_one_touched():
    a, b = _pos("a", "10", 0, 5), _pos("b", "10", 0, 1)
    assert _positions_for_unstake([a, b], "b", Decimal("10"), NOW) == [b]
    assert _positions_for_unstake([a, b], "b", Decimal("4"), NOW) == [b]


def test_a_named_locked_position_is_refused_with_its_unlock_date():
    a, b = _pos("a", "10", 0, 5), _pos("b", "10", 30, 1)
    with pytest.raises(HTTPException) as e:
        _positions_for_unstake([a, b], "b", Decimal("10"), NOW)
    assert e.value.status_code == 403
    assert "2026-10-30" in e.value.detail and "Nothing was unlocked" in e.value.detail


def test_a_lock_that_has_run_out_is_unlocked():
    b = _pos("b", "10", 30, 31)
    assert _positions_for_unstake([b], "b", Decimal("10"), NOW) == [b]


def test_more_than_the_position_holds_is_refused():
    with pytest.raises(HTTPException) as e:
        _positions_for_unstake([_pos("a", "10", 0, 5)], "a", Decimal("11"), NOW)
    assert e.value.status_code == 400


def test_an_id_that_is_not_an_active_position_of_this_agent_is_a_404():
    with pytest.raises(HTTPException) as e:
        _positions_for_unstake([_pos("a", "10", 0, 5)], "zzz", Decimal("1"), NOW)
    assert e.value.status_code == 404
