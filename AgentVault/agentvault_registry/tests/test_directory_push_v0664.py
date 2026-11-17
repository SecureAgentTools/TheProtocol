"""V0664 (order gwo_5374cd3a0eed96d787c4f813; the push half of Directory freshness, stack 98488854): this registry tells
its Directory when its own card epoch moves, so the index reads the card again at once instead of at its next cycle.

  the epoch     the card's own serve etag (registry_card_builder.compute_serve_etag): it moves on an operator edit and on
                every coarse epoch the card carries (policy, catalog, solvency, market, jurisdiction, licence), so a
                leader-elected check reads it every DIRECTORY_PUSH_INTERVAL (60 s); an admin's card edit nudges at once
  the push      POST <DIRECTORY_MTLS_URL>/push/card-changed {"registry": <its federation name>, "card_etag": <epoch>},
                nothing else, over the read path's own client (routers/public_directory: the SVID, a fixed target the
                operator sets; never an address from input)
  once          an epoch the Directory took is not pushed again; one it refused (5xx) or never answered is tried on the
                next tick; one the Directory does not know the registry for (404) is not repeated every minute
  best effort   no Directory named: nothing; a Directory that fails or hangs: counted, logged, never raised; the
                admin's card write never waits for it (the nudge is a task started after the commit)
Red on ededff4bf: the module does not exist.
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import httpx
import pytest

try:     # red as one failure per test, not a collection error
    from agentvault_registry.background_tasks import directory_push as dp
except ImportError:
    dp = None

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
DIR = "https://directory-sandbox-nginx:8443"


class Memo:
    def __init__(self):
        self.value = None

    async def get(self):
        return self.value

    async def set(self, v):
        self.value = v


def epoch(value, name="Sandbox Alpha"):
    async def read():
        return name, value
    return read


def directory(answer):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url), json.loads(request.content or b"{}")))
        return answer(request)
    return seen, (lambda url: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def ok(_r):
    return httpx.Response(200, json={"read": True, "reachable": True, "verified": True})


def run(c):
    return asyncio.run(c)


def test_a_moved_epoch_is_pushed_once_with_the_name_and_the_epoch_only(monkeypatch):
    monkeypatch.setenv("DIRECTORY_MTLS_URL", DIR)
    seen, client = directory(ok)
    memo = Memo()
    assert run(dp.push_once(read_epoch=epoch("sha256:e2"), memo=memo, client_factory=client)) == "pushed"
    assert seen == [("POST", DIR + "/push/card-changed", {"registry": "Sandbox Alpha", "card_etag": "sha256:e2"})]
    assert memo.value == "sha256:e2"
    assert run(dp.push_once(read_epoch=epoch("sha256:e2"), memo=memo, client_factory=client)) == "unchanged"
    assert len(seen) == 1, "an epoch the Directory took is not pushed again"
    assert run(dp.push_once(read_epoch=epoch("sha256:e3"), memo=memo, client_factory=client)) == "pushed"
    assert len(seen) == 2


def test_no_directory_named_pushes_nothing(monkeypatch):
    monkeypatch.delenv("DIRECTORY_MTLS_URL", raising=False)
    seen, client = directory(ok)
    assert run(dp.push_once(read_epoch=epoch("sha256:e2"), memo=Memo(), client_factory=client)) == "no_directory"
    assert seen == []


def test_a_refusal_is_tried_again_and_an_unknown_registry_is_not_repeated(monkeypatch):
    monkeypatch.setenv("DIRECTORY_MTLS_URL", DIR)
    memo = Memo()
    seen, client = directory(lambda r: httpx.Response(503, json={"detail": "busy"}))
    assert run(dp.push_once(read_epoch=epoch("sha256:e2"), memo=memo, client_factory=client)) == "refused:503"
    assert memo.value is None, "kept unpushed: the next tick tries again"
    seen2, client2 = directory(lambda r: httpx.Response(404, json={"read": False, "why": "unknown registry"}))
    assert run(dp.push_once(read_epoch=epoch("sha256:e2"), memo=memo, client_factory=client2)) == "unknown_to_directory"
    assert memo.value == "sha256:e2", "the index does not know this registry yet: its crawl will; no push every minute"


def test_a_directory_that_fails_or_hangs_is_counted_never_raised(monkeypatch):
    monkeypatch.setenv("DIRECTORY_MTLS_URL", DIR)

    def hang(r):
        raise httpx.ReadTimeout("timed out", request=r)
    for answer in (hang, lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused", request=r))):
        memo = Memo()
        _seen, client = directory(answer)
        out = run(dp.push_once(read_epoch=epoch("sha256:e2"), memo=memo, client_factory=client))
        assert out == "failed" and memo.value is None


def test_an_epoch_that_cannot_be_read_pushes_nothing(monkeypatch):
    monkeypatch.setenv("DIRECTORY_MTLS_URL", DIR)
    seen, client = directory(ok)

    async def broken():
        raise RuntimeError("database gone")
    assert run(dp.push_once(read_epoch=broken, memo=Memo(), client_factory=client)) == "no_epoch"
    assert seen == []


def test_the_nudge_returns_at_once_and_never_raises(monkeypatch):
    monkeypatch.setenv("DIRECTORY_MTLS_URL", DIR)
    started = []

    async def slow_push(**kw):
        started.append(True)
        await asyncio.sleep(30)

    async def caller():
        monkeypatch.setattr(dp, "push_once", slow_push)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        dp.nudge()                               # a plain call: it starts a task and returns
        took = loop.time() - t0
        await asyncio.sleep(0)                   # let the task start
        for t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
            t.cancel()
        return took
    assert run(caller()) < 0.05 and started == [True]


# --- the wiring --------------------------------------------------------------------------------------------------------

def test_the_push_goes_to_the_read_paths_fixed_target_with_its_client():
    src = (SRC / "background_tasks" / "directory_push.py").read_text()
    assert "public_directory" in src and "_upstream()" in src and "_client_kwargs(" in src
    # an address the operator sets keeps its own client (core/outbound_guard.py): the guard is neither imported nor
    # used (its name may appear in the module's prose, which says why)
    for use in ("import outbound_guard", "outbound_guard import", "guarded_client(", "GuardedClient(", "guarded_request("):
        assert use not in src, use


def test_the_admin_card_write_nudges_after_its_commit():
    src = (SRC / "routers" / "admin_registry_card.py").read_text()
    commit = src.index("row.card_etag = full_etag\n    await db.commit()")
    nudge = src.index("directory_push.nudge()")
    assert nudge > commit, "the nudge comes after the card is committed"


def test_the_check_runs_leader_elected_and_has_an_off_switch():
    src = (SRC / "background_tasks" / "directory_push.py").read_text()
    assert 'run_with_leadership("directory_push"' in src and "DIRECTORY_PUSH_ENABLED" in src
    main = (SRC / "main.py").read_text()
    assert "start_directory_push" in main
