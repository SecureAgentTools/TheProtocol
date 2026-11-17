"""V0667: OPA queries in flight across an SVID refresh must not fail (order gwo_25771cc56f472ec72ed05673; session-release's finding, room
seq 5385: sbx-beta under enforce logged 3 OPA errors, opa=null, within 3 ms at 11:59:51.6Z, the sidecar answering 200 throughout).

The cause, proven here against a REAL local HTTP server (a mock transport can finish a request on a closed client, a socket cannot):
opa_client.get_client rebuilds its client on the first query after an SVID refresh (every 5 minutes, §SVIDRACE V0639) and closed the old
one at once with aclose(), so a query still in flight on it failed and query_opa turned the exception into None. Under enforce Python then
decides alone; nothing is refused wrongly, but those requests had no OPA answer.

Pinned:
  - a query in flight across a rotation answers (the old client stays open until its last request leaves)
  - the new client serves new queries at once, and the old one is closed once drained (no leak)
  - a retired client still busy past the grace is closed anyway, and the error that causes is counted apart (cause client_rotated),
    never mixed with any other error
RED on 1b4352194: the in-flight query answers None, and there is no count by cause.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry import opa_client as opa

STAMP_A, STAMP_B = ((10, 5), (10, 5), (10, 5)), ((11, 6), (11, 6), (11, 6))


class _Opa:
    """An OPA sidecar on a loopback socket that answers {"result": true} only when released."""

    def __init__(self):
        self.arrived, self.release, self.served = asyncio.Queue(), asyncio.Event(), 0

    async def handle(self, reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            length = next((int(line.split(b":", 1)[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:")), 0)
            await reader.readexactly(length)
            await self.arrived.put(1)
            await self.release.wait()
            body = b'{"result": true}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
            await writer.drain()
            self.served += 1
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


@pytest.fixture
def wired(monkeypatch):
    stamp = {"v": STAMP_A}
    monkeypatch.setenv("OPA_ENABLED", "true")
    monkeypatch.setattr(opa, "svid_stamp", lambda: stamp["v"])
    monkeypatch.setattr(opa, "get_httpx_verify", lambda: False)
    monkeypatch.setattr(opa, "spire_trust_loaded", lambda verify, st: True)
    monkeypatch.setattr(opa, "_client", None)
    monkeypatch.setattr(opa, "_client_stamp", ())
    return stamp


async def _serve(sidecar, monkeypatch):
    server = await asyncio.start_server(sidecar.handle, "127.0.0.1", 0)
    monkeypatch.setenv("OPA_URL", f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}")
    return server


def test_a_query_in_flight_across_a_rotation_answers_and_the_old_client_closes_once_drained(wired, monkeypatch):
    async def run():
        sidecar = _Opa()
        server = await _serve(sidecar, monkeypatch)
        first = asyncio.create_task(opa.query_opa("agentvault/admin/allow", {"n": 1}))
        await asyncio.wait_for(sidecar.arrived.get(), 5)             # the first query is on the wire, on the first client
        old = opa._client
        wired["v"] = STAMP_B                                           # the SVID file was refreshed
        second = asyncio.create_task(opa.query_opa("agentvault/admin/allow", {"n": 2}))
        await asyncio.wait_for(sidecar.arrived.get(), 5)             # the second query went out at once, on a new client
        new = opa._client
        closed_under_it = old.is_closed                                # was the first query's client closed while it ran?
        sidecar.release.set()
        r1, r2 = await first, await second
        await asyncio.sleep(0)
        server.close()
        await server.wait_closed()
        return r1, r2, old, new, closed_under_it

    r1, r2, old, new, closed_under_it = asyncio.run(run())
    assert r1 is not None and r1["result"] is True, "the query in flight across the rotation must answer, not None"
    assert not closed_under_it, "the old client must stay open while it carries a query"
    assert new is not old and not new.is_closed
    assert r2 is not None and r2["result"] is True
    assert old.is_closed, "the old client is closed once its last request left (no leak)"
    assert opa.retired_count() == 0


def test_a_retired_client_still_busy_past_the_grace_is_closed_and_its_error_is_counted_apart(wired, monkeypatch):
    monkeypatch.setattr(opa, "RETIRE_GRACE_SECONDS", 0.05)

    async def run():
        sidecar = _Opa()
        server = await _serve(sidecar, monkeypatch)
        before = opa.errors_by_cause()
        stuck = asyncio.create_task(opa.query_opa("agentvault/admin/allow", {"n": 1}))
        await asyncio.wait_for(sidecar.arrived.get(), 5)
        old = opa._client
        wired["v"] = STAMP_B
        await opa.get_client()                                         # the rotation retires the busy client
        await asyncio.sleep(0.1)
        await opa.get_client()                                         # past the grace: closed under its request
        result = await stuck
        sidecar.release.set()
        server.close()
        await server.wait_closed()
        return result, old, before, opa.errors_by_cause()

    result, old, before, after = asyncio.run(run())
    assert result is None and old.is_closed and opa.retired_count() == 0
    assert after.get("client_rotated", 0) - before.get("client_rotated", 0) == 1
    assert {k: v for k, v in after.items() if k != "client_rotated"} == {k: v for k, v in before.items() if k != "client_rotated"}


def test_an_error_that_is_not_a_rotation_is_counted_under_its_own_cause(wired, monkeypatch):
    monkeypatch.setenv("OPA_URL", "http://127.0.0.1:9")                # nothing listens: a connection error, no rotation

    async def run():
        before = opa.errors_by_cause()
        out = await opa.query_opa("agentvault/admin/allow", {})
        return out, before, opa.errors_by_cause()

    out, before, after = asyncio.run(run())
    assert out is None
    assert after.get("client_rotated", 0) == before.get("client_rotated", 0)
    assert sum(after.values()) - sum(before.values()) == 1


def test_every_request_a_grace_close_cuts_off_is_counted_as_client_rotated(wired, monkeypatch):
    monkeypatch.setattr(opa, "RETIRE_GRACE_SECONDS", 0.05)

    async def run():
        sidecar = _Opa()
        server = await _serve(sidecar, monkeypatch)
        before = opa.errors_by_cause()
        stuck = [asyncio.create_task(opa.query_opa("agentvault/admin/allow", {"n": n})) for n in (1, 2)]
        for _ in stuck:
            await asyncio.wait_for(sidecar.arrived.get(), 5)
        wired["v"] = STAMP_B
        await opa.get_client()
        await asyncio.sleep(0.1)
        await opa.get_client()
        results = [await t for t in stuck]
        sidecar.release.set()
        server.close()
        await server.wait_closed()
        return results, before, opa.errors_by_cause()

    results, before, after = asyncio.run(run())
    assert results == [None, None]
    assert after.get("client_rotated", 0) - before.get("client_rotated", 0) == 2
    assert sum(after.values()) - sum(before.values()) == 2
