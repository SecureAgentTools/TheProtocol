"""§REPATLANE-5 (V0606): a money endpoint keeps every answer that may be the payment under its Idempotency-Key.

Before: /teg/cross-registry-transfer and /teg/transfer kept a success and nothing else (idempotency_lookup/store), so a
payment whose answer was "held" (its outcome not known) ran again when the same key came back after its 90 s claim. The
console sends exactly that: PocketSend keeps the key of a send whose outcome is unknown and asks again with it
(services/money/sendOutcome.ts), and the guild's settle retries on its stable key. A kept attempt (begin_attempt +
run_kept) keeps the answer, gives the key back only for an answer that proves nothing moved, and answers "ended without an
answer (outcome not known)" for a request that left none, instead of running the payment again.
"""
import asyncio
import json
import pathlib
import re

import pytest
from fastapi import HTTPException

from agentvault_registry.services import payout_outcome as po
from agentvault_registry.services.idempotency import cache

SCOPE = "teg.cross-registry-transfer"
BODY = {"receiver_did": "did:theprotocol:r", "amount": "0.5", "backend": None}
CALLER = cache.agent_caller("did:theprotocol:sender")   # D6-777: a kept record is its caller's
HELD = "FX route egress (outcome not known): nothing refunded, held for a ledger read (route_id=r1, transfer_id=t1)"


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


def _run(coro):
    return asyncio.run(coro)


CK = cache._cache_key(SCOPE, "k1", CALLER)


def _begin(body=BODY, key="k1"):
    return cache.begin_attempt(SCOPE, key, body, principal=CALLER)


class _Work:
    """The endpoint's work: marks dispatched (or not), then answers, raises or is cancelled."""

    def __init__(self, *, answer=None, raises=None, dispatch=True, sleep=0.0):
        self.answer, self.raises, self.dispatch, self.sleep, self.runs = answer, raises, dispatch, sleep, 0

    def __call__(self, attempt):
        async def _go():
            self.runs += 1
            if self.dispatch:
                attempt.mark_dispatched()
            if self.sleep:
                await asyncio.sleep(self.sleep)
            if self.raises is not None:
                raise self.raises
            return self.answer
        return _go


def _kept(work, body=BODY, key="k1"):
    async def _go():
        a = await _begin(body, key)
        if a.replay is not None:
            return ("replay", a.replay)
        return ("ran", await cache.run_kept(a, work(a), error_moved_nothing=po.error_moved_nothing,
                                            answer_moved_nothing=po.answer_moved_nothing))
    return _run(_go())


# ── what is kept, and answered again without running ─────────────────────────────────────────────────────────────────

def test_without_a_key_the_request_just_runs_and_nothing_is_kept(redis):
    w = _Work(answer={"status": "completed", "transfer_id": "t1"})
    assert _kept(w, key=None) == ("ran", {"status": "completed", "transfer_id": "t1"})
    assert redis.data == {} and w.runs == 1


def test_a_success_is_kept_and_answered_again_without_running(redis):
    w = _Work(answer={"status": "completed", "transfer_id": "t1"})
    assert _kept(w) == ("ran", {"status": "completed", "transfer_id": "t1"})
    assert _kept(w) == ("replay", {"status": "completed", "transfer_id": "t1"})
    assert w.runs == 1


@pytest.mark.parametrize("code,detail", [
    (409, HELD),
    (503, "Cross-registry transfer service unavailable"),          # says nothing either way: not a proof
    (502, {"smart_send_method": "fx", "inner": HELD}),             # a dict detail, kept as it is
    (402, f"402 after a reached attempt {po.OUTCOME_UNKNOWN}"),    # "not known" is read before the 402
    (400, "FX route failed post-conversion: parked for re-delivery"),
])
def test_a_held_answer_after_dispatch_is_kept_and_answered_again(redis, code, detail):
    w = _Work(raises=HTTPException(code, detail=detail))
    with pytest.raises(HTTPException) as first:
        _kept(w)
    assert first.value.status_code == code
    with pytest.raises(HTTPException) as again:
        _kept(w)
    assert (again.value.status_code, again.value.detail) == (code, detail)
    assert again.value.headers[cache.REPLAYED_HEADER] == "true"
    assert w.runs == 1, "the payment was not sent again"


def test_a_kept_error_keeps_its_retry_after(redis):
    w = _Work(raises=HTTPException(503, detail="Cross-registry transfer service unavailable",
                                   headers={"Retry-After": "30"}))
    with pytest.raises(HTTPException):
        _kept(w)
    with pytest.raises(HTTPException) as again:
        _kept(w)
    assert again.value.headers == {cache.REPLAYED_HEADER: "true", "Retry-After": "30"}


def test_a_failed_answer_that_says_nothing_moved_frees_the_key_and_any_other_is_kept(redis):
    clean = _Work(answer={"status": "failed", "error_message": f"Transfer aborted {po.NO_FUNDS_MOVED}"})
    assert _kept(clean)[0] == "ran" and _kept(clean)[0] == "ran" and clean.runs == 2
    assert CK not in redis.data
    partial = _Work(answer={"status": "failed", "error_message": "partial commit on the target TEG"})
    assert _kept(partial, key="k2") == ("ran", partial.answer)
    assert _kept(partial, key="k2") == ("replay", partial.answer) and partial.runs == 1
    unknown = _Work(answer={"status": "failed", "error_message": f"aborted {po.NO_FUNDS_MOVED} {po.OUTCOME_UNKNOWN}"})
    _kept(unknown, key="k3")
    assert _kept(unknown, key="k3")[0] == "replay", "a proof beside 'not known' proves nothing"


# ── what gives the key back, so the same key runs again ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,detail", [
    (409, f"FX route ingress refused {po.NO_FUNDS_MOVED}"),
    (503, "ledger_unavailable: The ledger cannot record this right now. Nothing was moved. Try again shortly."),
    (503, "The receiving frame's ledger cannot record this right now. Your payment came back to you. Try again shortly."),
    (409, f"FX route egress refused (origin refunded) {po.NOT_DELIVERED}"),
    (402, "Insufficient balance"),
])
def test_an_answer_that_proves_nothing_moved_gives_the_key_back(redis, code, detail):
    w = _Work(raises=HTTPException(code, detail=detail))
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            _kept(w)
        assert e.value.status_code == code and cache.REPLAYED_HEADER not in (e.value.headers or {})
    assert w.runs == 2 and CK not in redis.data and cache._beat_key(CK) not in redis.data


def test_any_answer_before_dispatch_gives_the_key_back(redis):
    w = _Work(raises=HTTPException(409, detail=f"refused before anything was sent {po.OUTCOME_UNKNOWN}"), dispatch=False)
    for _ in range(2):
        with pytest.raises(HTTPException):
            _kept(w)
    assert w.runs == 2 and CK not in redis.data


def test_an_error_before_dispatch_propagates_and_gives_the_key_back(redis):
    w = _Work(raises=RuntimeError("db down"), dispatch=False)
    with pytest.raises(RuntimeError):
        _kept(w)
    assert CK not in redis.data


# ── no answer at all ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_error_after_dispatch_that_is_no_answer_is_kept_as_not_known(redis):
    w = _Work(raises=RuntimeError("boom after the POST"))
    with pytest.raises(HTTPException) as first:
        _kept(w)
    assert first.value.status_code == 500 and po.OUTCOME_UNKNOWN in first.value.detail
    assert isinstance(first.value.__cause__, RuntimeError)
    with pytest.raises(HTTPException) as again:
        _kept(w)
    assert (again.value.status_code, again.value.detail) == (500, first.value.detail) and w.runs == 1


def test_a_request_that_ended_without_an_answer_is_never_run_again(redis):
    async def _dead_worker():
        a = await _begin()
        assert a.claimed
        a.mark_dispatched()          # it sent the payment, then its worker died: nothing settles the key
    _run(_dead_worker())
    redis.now += cache.IDEMPOTENCY_BEAT_TTL_SECONDS + 1   # its beat stopped
    w = _Work(answer={"status": "completed"})
    with pytest.raises(HTTPException) as e:
        _kept(w)
    assert e.value.status_code == 409 and po.OUTCOME_UNKNOWN in e.value.detail and w.runs == 0
    lane = po.classify(type("R", (), {"status_code": 409, "text": json.dumps({"detail": e.value.detail}),
                                      "json": lambda self: {"detail": e.value.detail}})(), None)
    assert lane.kind == po.HOLD


def test_a_request_cancelled_after_dispatch_leaves_its_claim_and_one_before_gives_it_back(redis):
    w = _Work(raises=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        _kept(w)
    assert CK in redis.data, "cancelled after it sent: the claim stays"
    redis.now += cache.IDEMPOTENCY_BEAT_TTL_SECONDS + 1
    with pytest.raises(HTTPException) as e:
        _kept(w)
    assert e.value.status_code == 409 and w.runs == 1
    early = _Work(raises=asyncio.CancelledError(), dispatch=False)
    with pytest.raises(asyncio.CancelledError):
        _kept(early, key="k2")
    assert cache._cache_key(SCOPE, "k2", CALLER) not in redis.data


# ── an earlier request still running ─────────────────────────────────────────────────────────────────────────────────

def test_a_request_under_a_running_one_waits_then_hears_it_is_in_progress(redis):
    async def _go():
        first = await _begin()
        assert first.claimed
        with pytest.raises(HTTPException) as e:
            await _begin()
        return e.value
    e = _run(_go())
    assert e.status_code == 422 and e.detail == cache.kept_claim_message("k1")
    lane = po.classify(type("R", (), {"status_code": 422, "text": e.detail, "json": lambda self: {}})(), None)
    assert lane.kind == po.WAIT


def test_a_request_under_a_running_one_answers_with_its_answer_when_it_lands(redis, monkeypatch):
    monkeypatch.setattr(cache, "IDEMPOTENCY_INFLIGHT_WAIT_SECONDS", 2.0)
    w = _Work(answer={"status": "completed", "transfer_id": "t9"}, sleep=0.05)

    async def _go():
        a = await _begin()
        first = asyncio.ensure_future(cache.run_kept(a, w(a), error_moved_nothing=po.error_moved_nothing))
        second = await _begin()
        await first
        return second.replay
    assert _run(_go()) == {"status": "completed", "transfer_id": "t9"} and w.runs == 1


def test_the_beat_is_refreshed_while_the_request_runs(redis, monkeypatch):
    monkeypatch.setattr(cache, "IDEMPOTENCY_BEAT_SECONDS", 0.01)
    w = _Work(answer={"status": "completed"}, sleep=0.08)
    _kept(w)
    beats = [k for k in redis.writes if k == cache._beat_key(CK)]
    assert len(beats) >= 3, f"one beat with the claim and more while it ran, saw {len(beats)}"


def test_a_claim_that_became_its_answer_between_two_reads_is_answered(redis):
    class _Racing(FakeRedis):
        async def exists(self, k):
            # the owner stores its answer right after the claim was read (a stored answer keeps no beat)
            self.data[CK] = (json.dumps({"body_hash": cache._record_hash(CALLER, BODY),
                                         "response": {"status": "completed"}}), None)
            self.data.pop(k, None)
            return 0
    r = _Racing()
    r.data[CK] = (json.dumps({"body_hash": cache._record_hash(CALLER, BODY), "pending": True, "kept": True,
                              "owner": "o"}), None)

    async def _go():
        from agentvault_registry.background_tasks import leader

        async def _get():
            return r
        leader.get_redis, old = _get, leader.get_redis
        try:
            return (await _begin()).replay
        finally:
            leader.get_redis = old
    assert _run(_go()) == {"status": "completed"}


# ── refusals of the attempt itself ───────────────────────────────────────────────────────────────────────────────────

def test_another_body_under_the_key_is_refused(redis):
    _kept(_Work(answer={"status": "completed"}))
    with pytest.raises(HTTPException) as e:
        _kept(_Work(answer={"status": "completed"}), body={**BODY, "amount": "0.6"})
    assert e.value.status_code == 422 and "different request payload" in e.value.detail


def test_a_held_key_whose_store_cannot_be_read_sends_nothing(redis):
    async def _go():
        await _begin()
        redis.fail.add("get")
        with pytest.raises(HTTPException) as e:
            await _begin()
        return e.value
    e = _run(_go())
    assert e.status_code == 503 and po.NO_FUNDS_MOVED in e.detail


def test_a_store_that_cannot_be_used_runs_the_request_unkeyed(redis):
    redis.fail.add("eval")
    w = _Work(answer={"status": "completed"})
    assert _kept(w)[0] == "ran" and _kept(w)[0] == "ran" and w.runs == 2


def test_a_claim_that_is_not_kept_is_read_as_idempotency_lookup_reads_it(redis):
    """A claim without "kept" (idempotency_lookup's, 90 s) of the same caller is waited for and then named as
    idempotency_lookup names it."""
    redis.data[CK] = (json.dumps({"body_hash": cache._record_hash(CALLER, BODY), "pending": True}), redis.now + 37)
    with pytest.raises(HTTPException) as e:
        _kept(_Work(answer={"status": "completed"}))
    assert e.value.status_code == 422 and "in 37 s" in e.value.detail


def test_an_older_images_record_of_the_key_is_not_matching_and_nothing_runs(redis):
    """D6-777: a record an older image kept under the scope and key alone names no caller: it is neither replayed nor
    run past, for its caller or anyone else, and the claim this request took goes back."""
    legacy = cache._unscoped_cache_key(SCOPE, "k1")
    redis.data[legacy] = (json.dumps({"body_hash": cache._body_hash(BODY), "response": {"status": "completed",
                                                                                       "transfer_id": "theirs"}}),
                          redis.now + 600)
    w = _Work(answer={"status": "completed", "transfer_id": "mine"})
    with pytest.raises(HTTPException) as e:
        _kept(w)
    assert e.value.status_code == 422 and e.value.detail == cache.unscoped_record_message("k1")
    assert po.OUTCOME_UNKNOWN in e.value.detail and w.runs == 0
    assert CK not in redis.data and cache._beat_key(CK) not in redis.data
    lane = po.classify(type("R", (), {"status_code": 422, "text": json.dumps({"detail": e.value.detail}),
                                      "json": lambda self: {"detail": e.value.detail}})(), None)
    assert lane.kind == po.HOLD


def test_a_release_deletes_only_its_own_claim(redis):
    async def _go():
        a = await _begin()
        redis.data[CK] = ("someone else's", None)
        await a.release()
    _run(_go())
    assert redis.data[CK][0] == "someone else's"


# ── the lane and the console read the same answers ───────────────────────────────────────────────────────────────────

def test_the_lane_reads_a_kept_error_as_held(redis):
    w = _Work(raises=HTTPException(409, detail=HELD))
    with pytest.raises(HTTPException):
        _kept(w)
    assert _run(po.stored_answer("k1", callers=(CALLER,))) == ("held", {"status_code": 409, "detail": HELD})


def test_the_texts_are_the_lanes():
    assert cache._OUTCOME_UNKNOWN == po.OUTCOME_UNKNOWN and cache._NO_FUNDS_MOVED == po.NO_FUNDS_MOVED
    assert any(s in cache.kept_claim_message("k") for s in po._CLAIMED)
    assert po.OUTCOME_UNKNOWN in cache.ended_without_answer_message("k")


def test_the_console_reads_the_lanes_sentences():
    ts = (pathlib.Path(po.__file__).resolve().parents[1] / "static" / "new_registry_frontend" / "src" / "services"
          / "money" / "sendOutcome.ts").read_text()

    def _list(name):
        m = re.search(rf"export const {name} = \[(.*?)\] as const", ts, re.S)
        assert m, name
        return tuple(re.findall(r"'([^']*)'", m.group(1)))
    assert _list("MAY_HAVE_MOVED") == po._MOVED
    assert _list("STILL_CLAIMED") == po._CLAIMED


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
