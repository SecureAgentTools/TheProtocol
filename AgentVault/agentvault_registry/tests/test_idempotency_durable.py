"""§REPATLANE-8 (V0610): a kept answer outlives Redis (services/idempotency/durable.py, idempotency_kept).

Redis runs allkeys-lru, so a record the cache evicted inside its 24 h window made the same Idempotency-Key run the payment
again. The durable copy keeps the same record in the registry's database; these tests evict from Redis by hand (the
FakeRedis of test_idempotency_kept_attempt, its clock moved by hand) and hold that the copy answers instead of a second
run, puts the record back into Redis, and that a copy that cannot be used leaves Redis alone exactly as before.
"""
import asyncio
import json
import pathlib
import re

import pytest
from fastapi import HTTPException

from agentvault_registry.services.idempotency import cache, durable

SCOPE = "teg.transfer"
BODY = {"receiver_did": "did:theprotocol:r", "amount": "0.5"}
ANSWER = {"status": "completed", "transaction_id": "t-1", "amount": "0.5"}
CALLER = cache.agent_caller("did:theprotocol:sender")   # D6-777: a kept record is its caller's
CK = cache._cache_key(SCOPE, "k1", CALLER)
DK = cache._durable_key("k1", CALLER)


# the FakeRedis of test_idempotency_kept_attempt.py, copied (test modules do not import each other here)
class FakeRedis:
    """The commands the cache sends, with TTLs on a clock the test moves (`now`), and _CLAIM_LUA's two writes."""

    def __init__(self):
        self.now = 1000.0
        self.data = {}
        self.fail = set()
        self.writes = []

    def _alive(self, k):
        v = self.data.get(k)
        if v is None:
            return None
        val, exp = v
        if exp is not None and exp <= self.now:
            del self.data[k]
            return None
        return val

    def _call(self, name):
        if name in self.fail:
            raise ConnectionError(f"{name} failed")

    async def get(self, k):
        self._call("get")
        return self._alive(k)

    async def set(self, k, v, nx=False, ex=None):
        self._call("set")
        if nx and self._alive(k) is not None:
            return None
        self.data[k] = (str(v), self.now + ex if ex else None)
        self.writes.append(k)
        return True

    async def delete(self, *ks):
        self._call("delete")
        n = sum(1 for k in ks if self._alive(k) is not None)
        for k in ks:
            self.data.pop(k, None)
        return n

    async def exists(self, k):
        self._call("exists")
        return 1 if self._alive(k) is not None else 0

    async def ttl(self, k):
        self._call("ttl")
        if self._alive(k) is None:
            return -2
        exp = self.data[k][1]
        return int(exp - self.now) if exp else -1

    async def eval(self, script, numkeys, *args):
        self._call("eval")
        assert script == cache._CLAIM_LUA and numkeys == 2
        k1, k2, claim, ttl, token, beat_ttl = args
        if self._alive(k1) is not None:
            return 0
        self.data[k1] = (claim, self.now + int(ttl))
        self.data[k2] = (token, self.now + int(beat_ttl))
        self.writes += [k1, k2]
        return 1


class FakeDurable:
    """durable.py's calls on rows in memory, on the FakeRedis clock; payloads go through JSON as they do in jsonb."""

    def __init__(self, clock):
        self.clock = clock
        self.rows = {}
        self.fail = set()
        self.calls = []

    def _f(self, name):
        self.calls.append(name)
        if name in self.fail:
            raise ConnectionError(f"{name} failed")

    def _live(self, k):
        r = self.rows.get(k)
        if r and r["exp"] > self.clock.now:
            return r
        self.rows.pop(k, None)
        return None

    def _rec(self, r):
        return {"body_hash": r["bh"], "state": r["state"], "owner": r["owner"], "payload": r["payload"],
                "age_s": self.clock.now - r["created"], "left_s": r["exp"] - self.clock.now}

    async def get(self, scope, key, unscoped_key=None):
        self._f("get")
        if unscoped_key and self._live((scope, unscoped_key)):
            return {"unscoped": True}
        r = self._live((scope, key))
        return self._rec(r) if r else None

    async def claim(self, scope, key, bh, owner, ttl, unscoped_key=None):
        self._f("claim")
        if unscoped_key and self._live((scope, unscoped_key)):
            return {"unscoped": True}
        r = self._live((scope, key))
        if r:
            return self._rec(r)
        self.rows[(scope, key)] = dict(bh=bh, state="claimed", owner=owner, payload=None, created=self.clock.now,
                                       exp=self.clock.now + ttl)
        return None

    async def store(self, scope, key, bh, payload, ttl):
        self._f("store")
        old = self._live((scope, key))
        self.rows[(scope, key)] = dict(bh=bh, state="answer", owner=None, payload=json.loads(json.dumps(payload, default=str)),
                                       created=old["created"] if old else self.clock.now, exp=self.clock.now + ttl)

    async def settle(self, scope, key, owner, state, payload, ttl):
        self._f("settle")
        r = self._live((scope, key))
        if not r or r["owner"] != owner:
            return False
        r.update(state=state, payload=json.loads(json.dumps(payload, default=str)), exp=self.clock.now + ttl)
        return True

    async def release(self, scope, key, owner):
        self._f("release")
        r = self._live((scope, key))
        if r and r["owner"] == owner:
            del self.rows[(scope, key)]


@pytest.fixture
def redis(monkeypatch):
    from agentvault_registry.background_tasks import leader
    r = FakeRedis()

    async def _get():
        return r
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_POLL_SECONDS", 0.005)
    return r


@pytest.fixture
def copy(monkeypatch, redis):
    d = FakeDurable(redis)
    monkeypatch.delenv("IDEMPOTENCY_DURABLE", raising=False)
    for name in ("get", "claim", "store", "settle", "release"):
        monkeypatch.setattr(durable, name, getattr(d, name))
    return d


def _run(coro):
    return asyncio.run(coro)


def _evict(redis, ck=CK):
    """What allkeys-lru does to a key: gone, with its beat."""
    redis.data.pop(ck, None)
    redis.data.pop(cache._beat_key(ck), None)


class _Work:
    def __init__(self, *, answer=None, raises=None, dispatch=True):
        self.answer, self.raises, self.dispatch, self.runs = answer, raises, dispatch, 0

    def __call__(self, attempt):
        async def go():
            self.runs += 1
            if self.dispatch:
                attempt.mark_dispatched()
            if self.raises is not None:
                raise self.raises
            return self.answer
        return go


async def _attempt(work, body=BODY, key="k1"):
    a = await cache.begin_attempt(SCOPE, key, body, principal=CALLER)
    if a.replay is not None:
        return "replay", a.replay
    out = await cache.run_kept(a, work(a), error_moved_nothing=lambda s, d: False)
    return "ran", out


def test_an_evicted_kept_answer_replays_from_the_copy_and_goes_back_into_redis(redis, copy):
    first = _Work(answer=ANSWER)
    assert _run(_attempt(first)) == ("ran", ANSWER)
    assert copy.rows[(SCOPE, DK)]["state"] == "answer"
    _evict(redis)
    again = _Work(answer={"status": "completed", "transaction_id": "t-2"})
    assert _run(_attempt(again)) == ("replay", ANSWER)
    assert again.runs == 0, "the payment ran a second time"
    assert json.loads(redis.data[CK][0]).get("response") == ANSWER, "the record went back into Redis"
    # and the next request is answered by Redis alone
    copy.fail = {"get", "claim"}
    assert _run(_attempt(_Work(answer={}))) == ("replay", ANSWER)


def test_an_evicted_kept_error_is_raised_again_with_its_mark(redis, copy):
    held = HTTPException(status_code=502, detail="the leg's answer was lost (outcome not known)",
                         headers={"Retry-After": "30"})
    with pytest.raises(HTTPException):
        _run(_attempt(_Work(raises=held)))
    assert copy.rows[(SCOPE, DK)]["state"] == "error"
    _evict(redis)
    again = _Work(answer=ANSWER)
    with pytest.raises(HTTPException) as e:
        _run(_attempt(again))
    assert again.runs == 0
    assert e.value.status_code == 502 and "(outcome not known)" in str(e.value.detail)
    assert e.value.headers.get(cache.REPLAYED_HEADER) == "true" and e.value.headers.get("Retry-After") == "30"
    assert "error" in json.loads(redis.data[CK][0])


def test_an_evicted_claim_reads_as_running_then_as_ended_without_an_answer(redis, copy):
    a = _run(cache.begin_attempt(SCOPE, "k1", BODY, principal=CALLER))
    assert a.claimed and copy.rows[(SCOPE, DK)]["state"] == "claimed"
    _evict(redis)   # the request is still running somewhere; Redis lost its claim and its beat
    w = _Work(answer=ANSWER)
    with pytest.raises(HTTPException) as e:
        _run(_attempt(w))
    assert e.value.status_code == 422 and "still in progress" in str(e.value.detail)
    redis.now += cache.DURABLE_CLAIM_RUNNING_S + 1
    with pytest.raises(HTTPException) as e:
        _run(_attempt(w))
    assert e.value.status_code == 409 and "(outcome not known)" in str(e.value.detail)
    assert w.runs == 0, "a claim Redis lost ran the payment again"
    assert CK not in redis.data, "the refused request left its own Redis claim behind"


def test_a_key_given_back_runs_again_and_leaves_no_row(redis, copy):
    refused = HTTPException(status_code=400, detail="refused before anything was sent")
    with pytest.raises(HTTPException):
        _run(_attempt(_Work(raises=refused, dispatch=False)))
    assert (SCOPE, DK) not in copy.rows
    w = _Work(answer=ANSWER)
    assert _run(_attempt(w)) == ("ran", ANSWER) and w.runs == 1


def test_another_body_under_an_evicted_key_is_refused(redis, copy):
    _run(_attempt(_Work(answer=ANSWER)))
    _evict(redis)
    w = _Work(answer=ANSWER)
    with pytest.raises(HTTPException) as e:
        _run(_attempt(w, body={**BODY, "amount": "5"}))
    assert e.value.status_code == 422 and "different request payload" in str(e.value.detail)
    assert w.runs == 0


def test_a_copy_that_cannot_be_used_leaves_redis_alone(redis, copy):
    copy.fail = {"get", "claim", "store", "settle", "release"}
    w = _Work(answer=ANSWER)
    assert _run(_attempt(w)) == ("ran", ANSWER)
    assert json.loads(redis.data[CK][0]).get("response") == ANSWER
    assert _run(_attempt(_Work(answer={}))) == ("replay", ANSWER)
    assert not copy.rows


def test_the_older_keyed_path_replays_an_evicted_answer(redis, copy):
    scope, key = "teg.treasury.fund-agent", "f1"
    ck = cache._cache_key(scope, key, CALLER)
    assert _run(cache.idempotency_lookup(scope, key, BODY, principal=CALLER)) == (None, None)
    _run(cache.idempotency_store(scope, key, BODY, ANSWER, principal=CALLER))
    assert copy.rows[(scope, cache._durable_key(key, CALLER))]["state"] == "answer"
    _evict(redis, ck)
    assert _run(cache.idempotency_lookup(scope, key, BODY, principal=CALLER)) == (ANSWER, None)
    assert json.loads(redis.data[ck][0]).get("response") == ANSWER
    resp, err = _run(cache.idempotency_lookup(scope, key, {**BODY, "amount": "9"}, principal=CALLER))
    assert resp is None and "different request payload" in err


def test_the_older_path_reads_a_kept_claim_redis_lost_as_unresolved(redis, copy):
    _run(cache.begin_attempt(SCOPE, "k1", BODY, principal=CALLER))
    _evict(redis)
    resp, err = _run(cache.idempotency_lookup(SCOPE, "k1", BODY, principal=CALLER))
    assert resp is None and "has not stored a result" in err
    assert CK not in redis.data, "the older path left its placeholder over the durable record"


def test_an_evicted_answer_is_another_callers_never_this_ones(redis, copy):
    """D6-777: the copy keeps a key as its caller's: another caller's request under the same key value runs as its own,
    and the first caller's evicted answer still replays for the first caller."""
    first = _Work(answer=ANSWER)
    assert _run(_attempt(first)) == ("ran", ANSWER)
    _evict(redis)
    other = cache.agent_caller("did:theprotocol:someone-else")
    w = _Work(answer={"status": "completed", "transaction_id": "t-other"})

    async def _theirs():
        a = await cache.begin_attempt(SCOPE, "k1", BODY, principal=other)
        assert a.replay is None and a.claimed, "another caller was answered from the first caller's record"
        return await cache.run_kept(a, w(a), error_moved_nothing=lambda s, d: False)
    assert _run(_theirs())["transaction_id"] == "t-other" and w.runs == 1
    assert _run(_attempt(_Work(answer={}))) == ("replay", ANSWER)


@pytest.mark.parametrize("path", ["kept", "older"])
def test_a_row_the_copy_kept_before_rows_were_the_callers_is_not_matching(redis, copy, path):
    """D6-777: a live row under the scope and key alone (written before) answers as not matching on both paths, for
    every caller, and the request runs nothing."""
    copy.rows[(SCOPE, "k1")] = dict(bh=cache._body_hash(BODY), state="answer", owner=None, payload=ANSWER,
                                    created=redis.now, exp=redis.now + 600)
    if path == "kept":
        w = _Work(answer={"status": "completed", "transaction_id": "t-9"})
        with pytest.raises(HTTPException) as e:
            _run(_attempt(w))
        assert e.value.status_code == 422 and e.value.detail == cache.unscoped_record_message("k1") and w.runs == 0
        assert CK not in redis.data and (SCOPE, DK) not in copy.rows
    else:
        resp, err = _run(cache.idempotency_lookup(SCOPE, "k1", BODY, principal=CALLER))
        assert resp is None and err == cache.unscoped_record_message("k1")
        assert CK not in redis.data, "the refused request left its placeholder behind"


def test_the_copy_switched_off_is_never_asked(redis, copy, monkeypatch):
    monkeypatch.setenv("IDEMPOTENCY_DURABLE", "off")
    _run(_attempt(_Work(answer=ANSWER)))
    _evict(redis)
    w = _Work(answer=ANSWER)
    assert _run(_attempt(w)) == ("ran", ANSWER) and w.runs == 1
    assert copy.calls == []


def test_the_sql_names_the_table_the_migration_makes():
    """durable.py writes raw SQL: every column it names exists in migration 0191 and in the model, and nothing else."""
    mig = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0191_idempotency_kept.py"
    made = set(re.findall(r'sa\.Column\("([a-z_]+)"', mig.read_text()))
    assert made == {"scope", "idem_key", "body_hash", "state", "owner", "payload", "created_at", "expires_at"}
    from agentvault_registry import models
    assert set(models.IdempotencyKept.__table__.columns.keys()) == made
    inserts = 0
    for stmt in (durable._LIVE_ROW, durable._CLAIM, durable._STORE, durable._SETTLE, durable._RELEASE, durable._SWEEP):
        sql = stmt.text
        assert "idempotency_kept" in sql
        ins = re.search(r"INSERT INTO idempotency_kept \(([^)]*)\)", sql)
        if ins:
            inserts += 1
            assert {c.strip() for c in ins.group(1).split(",")} == made, sql
        st = re.search(r"\bSET (.*?)(?: WHERE |$)", sql, flags=re.S)
        if st:
            assert {c.split("=")[0].strip() for c in st.group(1).split(",")} <= made, sql
    assert inserts == 2
