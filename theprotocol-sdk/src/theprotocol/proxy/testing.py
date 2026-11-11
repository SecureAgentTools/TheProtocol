"""The contract tests every TheProtocol Proxy plugin passes, for the plugin's own test suite.

    from theprotocol.proxy.testing import FakeContext, check_class, check_source, check_resume, check_action, check_sink

    def test_my_source_keeps_the_contract():
        check_class(MySource)

    async def test_my_source_yields_records():
        records = await check_source(MySource, {"path": "fixtures/"}, limit=3)

    async def test_my_source_resumes_from_its_cursor():
        await check_resume(MySource, {"path": "fixtures/"}, first=2, limit=5)

`FakeContext` stands in for the core: it answers `call` from a script (default 200 {}), records every call with its
headers, resolves secrets from a dict, and keeps state in memory. Nothing here reaches a network.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Type

from .plugins import Action, Event, Outcome, Record, Refused, Retry, Sink, Source, problems


class FakeResponse:
    """The shape of an httpx.Response a plugin reads: status_code, json(), text, headers."""

    def __init__(self, status_code: int = 200, body: Any = None, headers: Optional[Mapping[str, str]] = None):
        self.status_code = status_code
        self._body = {} if body is None else body
        self.headers = dict(headers or {})
        self.text = body if isinstance(body, str) else json.dumps(self._body)

    def json(self) -> Any:
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body


class _MemoryState:
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        self.data[key] = json.loads(json.dumps(value))   # what the core keeps is JSON


class FakeContext:
    """A ProxyContext with no network. `answers` is a list of FakeResponse (or exceptions to raise), used in order, or
    a function (method, path, kwargs) -> FakeResponse; the default answers 200 {} to everything."""

    def __init__(self, *, answers: Any = None, secrets: Optional[Mapping[str, str]] = None, dry_run: bool = False,
                 agent_did: str = "did:theprotocol:test:proxy", registry_url: str = "https://registry.test",
                 proxy_name: str = "test-proxy"):
        self.proxy_name, self.agent_did, self.registry_url, self.dry_run = proxy_name, agent_did, registry_url, dry_run
        self.logger = logging.getLogger(f"theprotocol.proxy.test.{proxy_name}")
        self.state = _MemoryState()
        self.calls: List[Dict[str, Any]] = []
        self._answers = answers
        self._secrets = dict(secrets or {})

    def secret(self, ref: str) -> str:
        if ref not in self._secrets:
            raise KeyError(f"no secret {ref!r} in this FakeContext")
        return self._secrets[ref]

    async def call(self, method: str, path: str, *, json: Any = None, params: Optional[Mapping[str, Any]] = None,
                   idempotency_key: Optional[str] = None, headers: Optional[Mapping[str, str]] = None) -> Any:
        rec = {"method": method.upper(), "path": path, "json": json, "params": dict(params or {}),
               "idempotency_key": idempotency_key, "headers": dict(headers or {})}
        self.calls.append(rec)
        a = self._answers
        if callable(a):
            out = a(method.upper(), path, rec)
        elif isinstance(a, list):
            if not a:
                raise AssertionError(f"FakeContext ran out of answers at {method} {path}")
            out = a.pop(0)
        else:
            out = FakeResponse()
        if isinstance(out, BaseException):
            raise out
        return out


def check_class(cls: Type[Any], kind: Optional[str] = None) -> None:
    """The class keeps the interface: its kind, its name, its interface version, its config schema, its methods."""
    bad = problems(cls, kind)
    assert not bad, "; ".join(bad)


def _json_ok(value: Any, what: str) -> None:
    try:
        json.dumps(value)
    except (TypeError, ValueError) as e:
        raise AssertionError(f"{what} is not JSON-compatible: {e}") from None


async def check_source(cls: Type[Source], config: Mapping[str, Any], *, limit: int = 10,
                       ctx: Optional[FakeContext] = None, twice: bool = True) -> List[Record]:
    """Collect up to `limit` records from the source and check them: Record instances, a non-empty string id, a
    JSON-compatible payload, no call to TheProtocol. With `twice`, a second source over the same input yields the same
    ids (record ids are stable, the exactly-once key depends on it)."""
    check_class(cls, "source")

    async def collect(c: FakeContext) -> List[Record]:
        src = cls(config, c)
        await src.start()
        got: List[Record] = []
        try:
            async for rec in src.records():
                assert isinstance(rec, Record), f"{cls.__name__} yielded {type(rec).__name__}, not a Record"
                assert isinstance(rec.record_id, str) and rec.record_id, f"{cls.__name__}: a record without an id"
                _json_ok(rec.payload, f"{cls.__name__}'s payload of {rec.record_id}")
                got.append(rec)
                await src.committed(rec)
                if len(got) >= limit:
                    break
        finally:
            await src.stop()
        assert not c.calls, f"{cls.__name__} called TheProtocol ({c.calls[0]['method']} {c.calls[0]['path']}): a source only reads"
        return got

    first = await collect(ctx or FakeContext())
    if twice:
        again = await collect(FakeContext())
        assert [r.record_id for r in again] == [r.record_id for r in first], \
            f"{cls.__name__}: the same input read twice gave other record ids"
    return first


async def check_resume(cls: Type[Source], config: Mapping[str, Any], *, first: int = 2, limit: int = 10,
                       ctx_factory: Optional[Callable[[], FakeContext]] = None) -> List[str]:
    """A restart resumes from the cursor: a source that read and committed `first` records, then a NEW source over the
    same state (what a restart is), yields the records after them: no record twice, none skipped, in order, against a
    full read with fresh state. (check_source's second pass uses fresh state, so it proves stable ids, not this: a
    source with no cursor at all passes it.) The input must hold more than `first` records. Returns the ids read."""
    check_class(cls, "source")
    make = ctx_factory or FakeContext

    async def read(c: FakeContext, n: int) -> List[str]:
        src = cls(config, c)
        await src.start()
        ids: List[str] = []
        try:
            if n > 0:
                async for rec in src.records():
                    ids.append(rec.record_id)
                    await src.committed(rec)
                    if len(ids) >= n:
                        break
        finally:
            await src.stop()
        return ids

    full = await read(make(), limit)
    assert len(full) > first, f"{cls.__name__}: the input has {len(full)} records; check_resume needs more than {first}"
    shared = make()
    before = await read(shared, first)
    after = await read(shared, len(full) - len(before))
    dup = sorted(set(before) & set(after))
    assert not dup, f"{cls.__name__} yielded {dup} again after a restart: its cursor did not hold"
    assert before + after == full[:len(before) + len(after)], \
        f"{cls.__name__} resumed at the wrong record: read {before} then {after}, the input is {full}"
    # V0659 (m): and the rest of the input, all of it. A restart that goes past every record it had not read yet
    # gives a short read that is still a prefix of the input, which the comparison above passes.
    skipped = full[len(before) + len(after):]
    assert not skipped, f"{cls.__name__} skipped {skipped} after a restart: its cursor went past them"
    return before + after


async def check_action(cls: Type[Action], config: Mapping[str, Any], mapped: Mapping[str, Any], *,
                       answers: Any = None, key: str = "proxy-contract-key-1") -> Outcome:
    """A dry run sends nothing and answers Outcome.dry; a real run sends `key` as the Idempotency-Key of every call it
    makes that writes, and answers Outcome.done. Returns the real run's outcome."""
    check_class(cls, "action")
    dry_ctx = FakeContext(dry_run=True)
    dry = await cls(config, dry_ctx).perform(mapped, key=key, dry_run=True)
    assert isinstance(dry, Outcome) and dry.status == "dry_run", f"{cls.__name__}'s dry run answered {dry!r}"
    assert not dry_ctx.calls, f"{cls.__name__}'s dry run called {dry_ctx.calls[0]['method']} {dry_ctx.calls[0]['path']}"
    ctx = FakeContext(answers=answers)
    out = await cls(config, ctx).perform(mapped, key=key, dry_run=False)
    assert isinstance(out, Outcome) and out.status == "done", f"{cls.__name__} answered {out!r}"
    writes = [c for c in ctx.calls if c["method"] not in ("GET", "HEAD")]
    assert writes, f"{cls.__name__} wrote nothing on TheProtocol"
    for c in writes:
        assert c["idempotency_key"] == key, f"{cls.__name__}: {c['method']} {c['path']} without the record's key"
    return out


async def check_action_refusals(cls: Type[Action], config: Mapping[str, Any], mapped: Mapping[str, Any]) -> None:
    """A 4xx answer is raised as Refused, a 5xx or 429 as Retry, never returned as an outcome."""
    for status, want in ((422, Refused), (409, Refused), (503, Retry), (429, Retry)):
        ctx = FakeContext(answers=lambda m, p, r, s=status: FakeResponse(s, {"detail": f"contract answer {s}"}))
        try:
            out = await cls(config, ctx).perform(mapped, key="proxy-contract-key-2", dry_run=False)
        except want:
            continue
        except (Refused, Retry) as e:
            raise AssertionError(f"{cls.__name__}: HTTP {status} raised {type(e).__name__}, not {want.__name__}") from None
        raise AssertionError(f"{cls.__name__}: HTTP {status} answered {out!r} instead of raising {want.__name__}")


async def check_sink(cls: Type[Sink], config: Mapping[str, Any], event: Event, *,
                     ctx_factory: Optional[Callable[[], FakeContext]] = None, key: str = "proxy-contract-key-3",
                     delivered: Optional[Callable[[], Sequence[Any]]] = None) -> Outcome:
    """A dry run answers Outcome.dry and calls nothing; a real run answers Outcome.done. With `delivered` (a function
    reading what the sink's system received), a dry run delivered nothing and two deliveries of one key delivered once."""
    check_class(cls, "sink")
    make = ctx_factory or FakeContext
    before = len(delivered()) if delivered else 0
    dctx = make()
    dry = await cls(config, dctx).deliver(event, key=key, dry_run=True)
    assert isinstance(dry, Outcome) and dry.status == "dry_run", f"{cls.__name__}'s dry run answered {dry!r}"
    assert not dctx.calls, f"{cls.__name__}'s dry run called {dctx.calls[0]['method']} {dctx.calls[0]['path']}"
    if delivered:
        assert len(delivered()) == before, f"{cls.__name__}'s dry run delivered"
    sink = cls(config, make())
    out = await sink.deliver(event, key=key, dry_run=False)
    assert isinstance(out, Outcome) and out.status == "done", f"{cls.__name__} answered {out!r}"
    if delivered:
        await sink.deliver(event, key=key, dry_run=False)
        assert len(delivered()) == before + 1, f"{cls.__name__} delivered one key twice"
    return out
