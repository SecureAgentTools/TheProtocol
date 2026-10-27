"""§FXEGRESS — the breaker that stops a dead gateway billing the sender once per retry.

The incident this encodes (2026-08-04 / 2026-08-06, traced on production ledgers):
a post-conversion egress failure is forward-only by design — the converted funds park at
the destination @fx_router and are never clawed back. The caller sees a 409 and RETRIES
the whole route, which debits the sender AGAIN. `agora-gateway-bvt` paid 1600 BVT four
times in five minutes for one trade; under load on 06 Aug the same shape produced 3,030
debits totalling 2,023,992 BVT across only 202 distinct amounts.

Nothing alerted, because every leg lands in a SYSTEM account (supply invariant correctly 0)
and the AGORA escrow invariant stops watching at the escrow boundary.

These tests exercise the pure breaker helpers against a fake Redis, so they run offline
like the rest of the suite.
"""
import pytest

from agentvault_registry.routers import teg_integration as ti


class FakeRedis:
    """Enough of the async redis surface for the breaker, plus failure injection."""

    def __init__(self, *, broken: bool = False):
        self.store: dict[str, int] = {}
        self.ttl: dict[str, int] = {}
        self.broken = broken

    async def get(self, k):
        if self.broken:
            raise RuntimeError("redis down")
        return self.store.get(k)

    async def incr(self, k):
        if self.broken:
            raise RuntimeError("redis down")
        self.store[k] = self.store.get(k, 0) + 1
        return self.store[k]

    async def expire(self, k, ttl):
        self.ttl[k] = ttl
        return True

    async def delete(self, k):
        if self.broken:
            raise RuntimeError("redis down")
        self.store.pop(k, None)
        return 1


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()

    async def _get_redis():
        return r

    import agentvault_registry.background_tasks.leader as leader
    monkeypatch.setattr(leader, "get_redis", _get_redis, raising=False)
    return r


@pytest.fixture(autouse=True)
def default_env(monkeypatch):
    monkeypatch.delenv("FX_EGRESS_BREAKER_THRESHOLD", raising=False)
    monkeypatch.delenv("FX_EGRESS_BREAKER_TTL_SEC", raising=False)


# ── configuration ───────────────────────────────────────────────────────────

def test_defaults_are_sane():
    assert ti._fx_egress_breaker_threshold() == 3
    assert ti._fx_egress_breaker_ttl() == 600


def test_threshold_zero_disables_the_breaker(monkeypatch, redis):
    monkeypatch.setenv("FX_EGRESS_BREAKER_THRESHOLD", "0")
    assert ti._fx_egress_breaker_threshold() == 0


def test_garbage_env_falls_back_instead_of_crashing_the_money_path(monkeypatch):
    monkeypatch.setenv("FX_EGRESS_BREAKER_THRESHOLD", "not-a-number")
    monkeypatch.setenv("FX_EGRESS_BREAKER_TTL_SEC", "")
    assert ti._fx_egress_breaker_threshold() == 3
    assert ti._fx_egress_breaker_ttl() == 600


def test_ttl_has_a_floor_so_the_streak_cannot_be_made_meaningless(monkeypatch):
    monkeypatch.setenv("FX_EGRESS_BREAKER_TTL_SEC", "1")
    assert ti._fx_egress_breaker_ttl() == 30


# ── the streak ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failures_accumulate_and_trip_at_the_threshold(redis):
    gw = "registry-frame-a"
    assert await ti._fx_egress_breaker_state(gw) == 0
    for expected in (1, 2, 3):
        assert await ti._fx_egress_breaker_record(gw, failed=True) == expected
    # THE REGRESSION ASSERTION: at the threshold the next origination is refused.
    assert await ti._fx_egress_breaker_state(gw) >= ti._fx_egress_breaker_threshold()


@pytest.mark.asyncio
async def test_one_failure_does_not_trip_it(redis):
    """A single post-conversion parking is normal and must NOT suspend the corridor."""
    await ti._fx_egress_breaker_record("registry-frame-a", failed=True)
    assert await ti._fx_egress_breaker_state("registry-frame-a") < ti._fx_egress_breaker_threshold()


@pytest.mark.asyncio
async def test_success_clears_the_streak_so_recovery_needs_no_operator(redis):
    gw = "registry-frame-b"
    for _ in range(5):
        await ti._fx_egress_breaker_record(gw, failed=True)
    assert await ti._fx_egress_breaker_state(gw) >= 3
    assert await ti._fx_egress_breaker_record(gw, failed=False) == 0
    assert await ti._fx_egress_breaker_state(gw) == 0


@pytest.mark.asyncio
async def test_streak_is_per_gateway(redis):
    """A broken corridor must not suspend a healthy one."""
    for _ in range(4):
        await ti._fx_egress_breaker_record("registry-frame-a", failed=True)
    assert await ti._fx_egress_breaker_state("registry-frame-a") >= 3
    assert await ti._fx_egress_breaker_state("registry-frame-b") == 0


@pytest.mark.asyncio
async def test_failures_carry_a_ttl_so_the_suspension_self_heals(redis):
    await ti._fx_egress_breaker_record("registry-frame-a", failed=True)
    assert redis.ttl[ti._fx_egress_breaker_key("registry-frame-a")] == ti._fx_egress_breaker_ttl()


@pytest.mark.asyncio
async def test_disabled_breaker_never_reports_a_trip(monkeypatch, redis):
    monkeypatch.setenv("FX_EGRESS_BREAKER_THRESHOLD", "0")
    for _ in range(10):
        await ti._fx_egress_breaker_record("registry-frame-a", failed=True)
    assert await ti._fx_egress_breaker_state("registry-frame-a") == 0


# ── fail-open, the load-bearing safety property ─────────────────────────────

@pytest.mark.asyncio
async def test_no_redis_fails_open(monkeypatch):
    """No Redis must never block a healthy swap (same convention as the spot breaker)."""
    async def _none():
        return None
    import agentvault_registry.background_tasks.leader as leader
    monkeypatch.setattr(leader, "get_redis", _none, raising=False)
    assert await ti._fx_egress_breaker_state("registry-frame-a") == 0
    assert await ti._fx_egress_breaker_record("registry-frame-a", failed=True) == 0


@pytest.mark.asyncio
async def test_broken_redis_fails_open_rather_than_raising(monkeypatch):
    broken = FakeRedis(broken=True)

    async def _broken():
        return broken
    import agentvault_registry.background_tasks.leader as leader
    monkeypatch.setattr(leader, "get_redis", _broken, raising=False)
    assert await ti._fx_egress_breaker_state("registry-frame-a") == 0
    assert await ti._fx_egress_breaker_record("registry-frame-a", failed=True) == 0


def test_key_is_namespaced_and_survives_a_blank_gateway():
    assert ti._fx_egress_breaker_key("registry-frame-a") == "fx:egress_fail:registry-frame-a"
    assert ti._fx_egress_breaker_key("") == "fx:egress_fail:unknown"
