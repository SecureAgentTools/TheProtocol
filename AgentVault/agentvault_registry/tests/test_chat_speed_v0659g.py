"""V0659 (g): cross-frame chat delivery, faster and as safe (the Commander's seq 1789: "lightning fast and safe").

Measured 2026-11-07 on sbx-alpha's outbox: p50 0.87 s, p95 1.41 s, max 1.8 s; most of it the leader's one-second look
for due rows and a fresh mTLS handshake per message. Now:
- the transaction that queues a delivery wakes the leader when it commits (a Redis list the leader blocks on; a
  rollback wakes nobody), and the one-second look stays as the floor;
- every peer is delivered at once, so one slow or unreachable peer delays only itself, and each thread in its order
  (a thread's rows stop at its first failure; a row waits while an earlier row of its thread to the same peer backs
  off, so the peer never receives a thread out of order);
- one keep-alive client per peer, rebuilt when the SVID rotates or the trust bundle changes;
- the first retry after 1 s.
The identity checks (the allowlisted peer, this registry's SVID), the receiver's idempotency and the rate limits are
unchanged. Red on 13d2011ac: no wake, one client per message, one peer after another, the first retry after 5 s.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import time
from types import SimpleNamespace

import pytest

from agentvault_registry.background_tasks import chat_federation_outbox as ob
from agentvault_registry.background_tasks import leader, vitals
from agentvault_registry.services import chat_federation as fed


# ── the wake on commit ───────────────────────────────────────────────────────────────────────────────────────────────

class _WakeRedis:
    def __init__(self):
        self.items = []

    async def lpush(self, key, value):
        self.items.insert(0, value)

    async def ltrim(self, key, a, b):
        self.items = self.items[a:b + 1]

    async def blpop(self, key, timeout=0):
        end = time.monotonic() + float(timeout)
        while time.monotonic() < end:
            if self.items:
                return (key, self.items.pop())
            await asyncio.sleep(0.005)
        return None


@pytest.fixture()
def loop_env(monkeypatch):
    state = {"drains": 0, "probes": 0, "led": True, "drained_at": []}
    r = _WakeRedis()
    state["redis"] = r

    async def _lead(name):
        return state["led"]

    async def _drain():
        state["drains"] += 1
        state["drained_at"].append(time.monotonic())

    async def _register(*a, **k):
        return None

    @contextlib.asynccontextmanager
    async def _cycle(name):
        yield

    async def _due():
        state["probes"] += 1
        return False

    async def _get():
        return r
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    monkeypatch.setattr(leader, "try_acquire_leadership", _lead)
    monkeypatch.setattr(leader, "get_redis", _get)
    monkeypatch.setattr(vitals, "register", _register)
    monkeypatch.setattr(vitals, "cycle", _cycle)
    monkeypatch.setattr(ob, "_drain_once", _drain)
    monkeypatch.setattr(ob, "_due_rows", _due)
    monkeypatch.setattr(ob, "CYCLE_SECONDS", 5)
    monkeypatch.setattr(ob, "DUE_POLL_SECONDS", 1.0)
    return state


def test_a_commit_wakes_the_leader_at_once_not_at_its_next_look(loop_env):
    async def go():
        task = asyncio.create_task(ob.chat_federation_outbox_loop())
        await asyncio.sleep(0.1)
        woke_at = time.monotonic()
        await fed.wake_outbox()
        await asyncio.sleep(0.2)
        ob.stop_chat_federation_outbox()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return woke_at
    woke_at = asyncio.run(go())
    assert loop_env["drains"] == 2, loop_env            # BASE: 1 (the next look was a second away)
    assert loop_env["drained_at"][1] - woke_at < 0.1


async def test_the_transaction_that_queues_a_delivery_wakes_the_leader_once_it_commits(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    woken = []

    async def _wake():
        woken.append(1)
    monkeypatch.setattr(fed, "wake_outbox", _wake)
    engine = create_engine("sqlite://")
    for commit in (True, False):
        with Session(engine) as s:
            fed.wake_after_commit(SimpleNamespace(sync_session=s))
            s.execute(text("SELECT 1"))
            s.commit() if commit else s.rollback()
        for _ in range(3):
            await asyncio.sleep(0)
        assert woken == [1], "a commit wakes once; a rollback wakes nobody"


# ── the drain: every peer at once, each thread in order ──────────────────────────────────────────────────────────────

class _Row(SimpleNamespace):
    pass


def _row(conv, seq, peer):
    return _Row(id=f"{conv}-{seq}-{peer}", conversation_id=conv, seq=seq, peer_base_url=peer, payload={"seq": seq},
                attempts=0, delivered_at=None, next_attempt_at=None, last_error=None)


class _DB:
    def __init__(self, rows):
        self.rows, self.commits = rows, 0

    async def execute(self, stmt, params=None):
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    async def commit(self):
        self.commits += 1


@pytest.fixture()
def peers(monkeypatch):
    """Two peers: `slow` answers after 0.4 s, `fast` at once; `down` refuses; a post per (target, seq) recorded."""
    posts, made = [], []

    class _Client:
        def __init__(self, **kw):
            made.append(kw)
            self.is_closed = False

        async def post(self, url, headers=None, json=None):
            t0 = time.monotonic()
            if "slow" in url:
                await asyncio.sleep(0.4)
            posts.append((url.split("/api/")[0], json["seq"], t0, time.monotonic()))
            if "down" in url or (json.get("fail")):
                return SimpleNamespace(status_code=503, text="busy")
            return SimpleNamespace(status_code=201, text="")

        async def aclose(self):
            self.is_closed = True

    async def _target(db, base):
        return base, {"cert": ("svid.pem", "key.pem")}, {"Content-Type": "application/json"}
    monkeypatch.setattr(fed.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fed, "federation_target", _target)
    monkeypatch.setattr(fed, "_POOL", {}, raising=False)        # raising=False: the base has no pool
    return posts, made


def test_every_peer_at_once_so_a_slow_peer_delays_only_itself(peers):
    posts, _made = peers
    rows = [_row("c1", 1, "https://slow.example"), _row("c1", 2, "https://slow.example"),
            _row("c2", 1, "https://fast.example"), _row("c2", 2, "https://fast.example")]
    t0 = time.monotonic()
    out = asyncio.run(fed.drain_outbox(_DB(rows)))
    took = time.monotonic() - t0
    assert out["delivered"] == 4 and out["peers"] == 2
    fast_done = max(p[3] for p in posts if "fast" in p[0])
    slow_first_done = min(p[3] for p in posts if "slow" in p[0])
    slow_done = max(p[3] for p in posts if "slow" in p[0])
    # BASE: one peer after the other, so the fast peer's rows wait behind both of the slow peer's posts
    assert fast_done < slow_first_done, "the fast peer finished while the slow one's first post was still in flight"
    assert took < 1.5 and slow_done - t0 >= 0.8, "the slow peer's two posts still go one after the other (one thread)"


def test_a_thread_stops_at_its_first_failure_and_its_later_rows_wait(peers):
    posts, _made = peers
    rows = [_row("c1", 1, "https://p.example"), _row("c1", 2, "https://p.example"),
            _row("c2", 1, "https://p.example")]
    rows[0].payload = {"seq": 1, "fail": True}
    db = _DB(rows)
    before = datetime.datetime.now(datetime.timezone.utc)
    out = asyncio.run(fed.drain_outbox(db))
    assert [(p[1]) for p in posts] == [1, 1], "c1 seq 2 was not sent after c1 seq 1 failed; c2 went on"
    assert out == {"considered": 3, "delivered": 1, "failed": 1, "batch_limit": 50, "peers": 1}
    assert rows[1].attempts == 0 and rows[1].delivered_at is None, "the held row spent no attempt"
    retry_in = (rows[0].next_attempt_at - before).total_seconds()
    assert 0.9 <= retry_in < 2.0, f"the first retry after a second, not {retry_in:.1f} s"   # BASE: 5 s
    assert db.commits == 1


def test_a_row_is_due_only_when_no_earlier_row_of_its_thread_to_that_peer_backs_off():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql
    from agentvault_registry.models import ChatFederationOutbox
    sql = str(select(ChatFederationOutbox.id).where(*fed._due_conditions()).compile(dialect=postgresql.dialect()))
    flat = " ".join(sql.split())
    assert "NOT EXISTS (SELECT 1 FROM chat_federation_outbox e" in flat
    for clause in ("e.conversation_id = chat_federation_outbox.conversation_id",
                   "e.peer_base_url = chat_federation_outbox.peer_base_url", "e.delivered_at IS NULL",
                   "e.seq < chat_federation_outbox.seq", "e.next_attempt_at > now()"):
        assert clause in flat, clause
    assert fed.BACKOFF_SECONDS[0] == 1


def test_a_backlog_larger_than_a_batch_is_taken_oldest_due_first_not_lowest_conversation_first():
    """Lead's review (room seq 1957): ORDER BY conversation_id, seq under the LIMIT let the lowest conversation ids
    win every batch while later rooms waited. The batch is chosen by each thread-and-peer's OLDEST due row (a window
    over the pair), then the pair's rows in seq order: plain next_attempt_at order would let a head row that was
    retried (and so sorts after its own later rows) fall outside the LIMIT while its successor went out alone."""
    from sqlalchemy.dialects import postgresql
    sql = " ".join(str(fed._due_batch(7).compile(dialect=postgresql.dialect())).split())
    order = sql.split("ORDER BY", 1)[1]
    assert order.lstrip().startswith(
        "min(chat_federation_outbox.next_attempt_at) OVER (PARTITION BY chat_federation_outbox.conversation_id, "
        "chat_federation_outbox.peer_base_url)"), order
    tail = order.split(")", 1)[1]
    assert tail.index("chat_federation_outbox.conversation_id") < tail.index("chat_federation_outbox.peer_base_url") \
        < tail.index("chat_federation_outbox.seq"), tail
    assert "LIMIT" in sql and "NOT EXISTS" in sql, "the batch is still bounded and still holds a thread behind its retry"


def test_a_batch_handed_back_in_any_order_still_goes_out_in_thread_order(peers):
    """The batch is sorted by thread and seq before grouping, whatever order the store returned it in."""
    posts, _made = peers
    rows = [_row("c1", 2, "https://p.example"), _row("c2", 1, "https://p.example"), _row("c1", 1, "https://p.example")]
    for r in rows:
        r.payload = {"seq": f"{r.conversation_id}-{r.seq}"}
    out = asyncio.run(fed.drain_outbox(_DB(rows)))
    assert out["delivered"] == 3
    sent = [p[1] for p in posts]
    assert [x for x in sent if x.startswith("c1-")] == ["c1-1", "c1-2"], sent     # BASE: c1-2 went out first


def test_one_keep_alive_client_per_peer_rebuilt_when_the_svid_rotates(peers):
    _posts, made = peers

    async def go():
        a1 = fed.peer_client("https://a.example", {"cert": ("svid-1.pem", "key-1.pem")})
        a2 = fed.peer_client("https://a.example", {"cert": ("svid-1.pem", "key-1.pem")})
        b = fed.peer_client("https://b.example", {"cert": ("svid-1.pem", "key-1.pem")})
        a3 = fed.peer_client("https://a.example", {"cert": ("svid-2.pem", "key-2.pem")})   # a rotation: new files
        await asyncio.sleep(0)
        return a1, a2, b, a3
    a1, a2, b, a3 = asyncio.run(go())
    assert a1 is a2 and a1 is not b and a3 is not a1
    assert a1.is_closed is True and a3.is_closed is False, "the client from before the rotation is closed"
    assert len(made) == 3 and made[0]["limits"].max_keepalive_connections == 4


def test_a_drain_dials_each_peer_through_one_pooled_client(peers):
    _posts, made = peers
    rows = [_row("c1", s, "https://p.example") for s in (1, 2, 3)]
    asyncio.run(fed.drain_outbox(_DB(rows)))
    asyncio.run(fed.drain_outbox(_DB([_row("c1", 4, "https://p.example")])))
    assert len(made) == 1, f"{len(made)} clients for one peer"                     # BASE: one per message


# ── a first message does not bounce while the host learns the thread ─────────────────────────────────────────────────

class _Scripted:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def post(self, url, headers=None, json=None):
        self.calls.append(url)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def _resp(status, text="", body=None):
    return SimpleNamespace(status_code=status, text=text, json=lambda: body if body is not None else {"detail": text})


@pytest.fixture()
def scripted(monkeypatch):
    holder = {}

    async def _target(db, base):
        return base, {}, {}

    async def _noop(*a, **k):
        return None

    @contextlib.asynccontextmanager
    async def _ctx():
        yield None
    class _Client:
        """The base dials a fresh client per call: the same script answers it (nothing reaches a network)."""

        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return holder["client"]

        async def __aexit__(self, *a):
            return False
    import agentvault_registry.database as database
    monkeypatch.setattr(fed, "federation_target", _target)
    monkeypatch.setattr(fed, "_record_relay", _noop)
    monkeypatch.setattr(fed, "peer_client", lambda target, kwargs: holder["client"], raising=False)
    monkeypatch.setattr(fed, "RELAY_RETRY_S", 0.01, raising=False)
    monkeypatch.setattr(fed.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(database, "get_db_context", _ctx)

    def use(answers):
        holder["client"] = _Scripted(answers)
        return holder["client"]
    return use


CONV = SimpleNamespace(host_registry="https://host.example", remote_ref="thread-1")
NOT_YET = "'u-7@https://res.example' is not a participant in that thread"


def _relay():
    return asyncio.run(fed.relay_to_host(None, CONV, "u-7@https://res.example", "Ada", "text", "hello", None,
                                         "ref-1"))


def test_a_relay_the_host_has_not_seated_yet_is_tried_again_a_second_later_once(scripted):
    c = scripted([_resp(403, NOT_YET), _resp(201, body={"seq": 7, "duplicate": False})])
    assert _relay() == {"seq": 7, "duplicate": False} and len(c.calls) == 2
    c = scripted([_resp(403, NOT_YET), _resp(403, NOT_YET)])
    with pytest.raises(fed.cs.ChatError) as e:
        _relay()
    assert e.value.status_code == 403 and len(c.calls) == 2, "one retry, then the host's answer stands"


def test_a_relay_lost_on_the_way_is_retried_and_any_other_refusal_is_not(scripted):
    import httpx
    c = scripted([httpx.ConnectError("reset"), _resp(201, body={"seq": 8})])
    assert _relay() == {"seq": 8} and len(c.calls) == 2
    c = scripted([_resp(403, "the calling registry is not the sender's home registry")])
    with pytest.raises(fed.cs.ChatError):
        _relay()
    assert len(c.calls) == 1, "a refusal that a second cannot change is not retried"


def test_a_join_announcement_the_host_could_not_take_is_tried_again_once(scripted):
    import httpx
    c = scripted([httpx.ConnectError("reset"), _resp(200, body={"state": "join", "changed": True})])
    assert asyncio.run(fed.announce_state_to_host("https://host.example", "thread-1", "u-7@https://res.example",
                                                  "join", household_of="a-1@https://res.example")) is True
    assert len(c.calls) == 2
    c = scripted([_resp(503, "restarting"), _resp(200)])
    assert asyncio.run(fed.announce_state_to_host("https://host.example", "thread-1", "u-7@https://res.example",
                                                  "active")) is True and len(c.calls) == 2
