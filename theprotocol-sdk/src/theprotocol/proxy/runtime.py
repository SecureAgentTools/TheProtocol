"""The runtime: sources -> mappings -> the durable outbox -> actions and sinks, under one agent identity.

    a source yields a Record --> each mapping that takes it --> a row in the outbox (its exactly-once key) --> the
    source's cursor moves (committed) --> the dispatcher sends the row: an action's one call on TheProtocol, or a sink's
    one delivery --> done, retried with backoff, or dead (a refusal, with the other side's answer)

The record's key is hash(source, record id, mapping name, mapping version), so a record read twice is sent once, and a
row whose call was sent but whose answer was lost (a crash, a timeout) is sent again with the same Idempotency-Key, which
the registry answers as a repeat. A dry run maps into an outbox in memory, asks every action and sink for what it would
send and moves no cursor. The switches (a pause, per mapping or for the whole proxy, and the breakers) live in the
outbox file, so `tp-proxy pause`, `resume` and `replay` act on a proxy that is running.
"""
from __future__ import annotations

import asyncio
import collections
import dataclasses
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Tuple

import httpx

from .identity import Identity, IdentityError
from .mapping import apply, key_for, takes
from .outbox import Outbox, PluginState, Row
from .plugins import Action, Event, Outcome, PluginError, Record, Refused, Retry, Source, load
from .registry import RegistryClient
from .spec import MappingSpec, Spec

log = logging.getLogger("theprotocol.proxy")

DEFAULT_RETRY = {"first_s": 2.0, "max_s": 300.0, "attempts": 8}
DEFAULT_BREAKER = {"refusals": 5, "failures": 10, "cooldown_s": 30.0}
DEFAULT_LISTEN = "127.0.0.1:9108"


# ── what a plugin is handed ──────────────────────────────────────────────────────────────────────────────────────────

class OverlayState:
    """A dry run's state: reads the real file's values, keeps its own writes in memory (the real cursor never moves)."""

    def __init__(self, base: Optional[Outbox], scope: str):
        self._base, self._scope, self._mem = base, scope, {}

    async def get(self, key: str, default: Any = None) -> Any:
        if key in self._mem:
            return json.loads(self._mem[key])
        return self._base.state_get(self._scope, key, default) if self._base is not None else default

    async def set(self, key: str, value: Any) -> None:
        self._mem[key] = json.dumps(value, default=str)


class CoreContext:
    """The ProxyContext the core hands a plugin."""

    def __init__(self, *, proxy_name: str, agent_did: str, registry_url: str, dry_run: bool, logger: logging.Logger,
                 state: Any, secret: Callable[[str], str], client: Optional[RegistryClient], kind: str, name: str):
        self.proxy_name, self.agent_did, self.registry_url = proxy_name, agent_did, registry_url
        self.dry_run, self.logger, self.state = dry_run, logger, state
        self._secret, self._client, self._kind, self._name = secret, client, kind, name

    def secret(self, ref: str) -> str:
        return self._secret(ref)

    async def call(self, method: str, path: str, *, json: Any = None, params: Optional[Mapping[str, Any]] = None,
                   idempotency_key: Optional[str] = None, headers: Optional[Mapping[str, str]] = None) -> httpx.Response:
        if self._kind == "source":
            raise PluginError(f"the source {self._name!r} called {method} {path}: a source only reads its own system")
        if self._client is None:  # pragma: no cover - every action and sink is given one
            raise PluginError("this context has no registry")
        return await self._client.call(method, path, json=json, params=params, idempotency_key=idempotency_key,
                                       headers=headers, dry_run=self.dry_run)


# ── the breaker and the limits ───────────────────────────────────────────────────────────────────────────────────────

class Breaker:
    """Stops one mapping after repeated failed calls, and says why.

    Refusals (answers a retry will not change) in a row: the mapping stops until `tp-proxy resume` (someone must fix
    what the other side refuses). Transient failures in a row: the mapping cools down and tries one call again after
    the cooldown, which doubles each time it trips again, up to the retry ceiling. Its state is the switch
    `breaker:<mapping>` in the outbox file, so a restart keeps a stopped mapping stopped and `resume` reaches a running
    proxy."""

    def __init__(self, outbox: Outbox, mapping: str, *, refusals: int, failures: int, cooldown_s: float,
                 max_s: float, clock: Callable[[], float] = time.time):
        self._o, self.mapping = outbox, mapping
        self.max_refusals, self.max_failures = int(refusals), int(failures)
        # a cooldown doubles each time it trips again, up to the retry ceiling (or the cooldown itself, if longer)
        self.cooldown_s, self.max_s, self._clock = float(cooldown_s), max(float(max_s), float(cooldown_s)), clock
        self.refusals = self.failures = 0
        self._trips = 0
        self._open = False      # this breaker wrote its switch (so a switch that is gone was resumed by hand)

    @property
    def switch(self) -> str:
        return f"breaker:{self.mapping}"

    def state(self) -> Optional[Dict[str, Any]]:
        return self._o.switch(self.switch)

    def allows(self) -> bool:
        st = self.state()
        if st is None:
            if self._open:
                # resumed by hand (the switch it wrote is gone): start counting again
                self._open = False
                self._trips = self.refusals = self.failures = 0
            return True
        self._open = True       # a switch from before a restart counts as this breaker's
        until = st.get("until")
        return until is not None and self._clock() >= float(until)    # a cooled-down mapping tries one call

    def ok(self) -> None:
        self.refusals = self.failures = 0
        self._trips = 0
        self._open = False
        if self.state() is not None:
            self._o.set_switch(self.switch, None)

    def refused(self, why: str) -> bool:
        self.refusals += 1
        self.failures = 0
        if self.refusals >= self.max_refusals:
            self._o.set_switch(self.switch, {"state": "stopped", "why": why, "refusals": self.refusals,
                                             "since": self._clock(), "until": None})
            self._open = True
            return True
        return False

    def failed(self, why: str) -> bool:
        self.failures += 1
        st = self.state()
        if st is not None and st.get("until") is not None:
            # the one call after a cooldown failed too: cool down again, twice as long
            self._trip(why)
            return True
        if self.failures >= self.max_failures:
            self._trip(why)
            return True
        return False

    def _trip(self, why: str) -> None:
        self._trips += 1
        wait = min(self.max_s, self.cooldown_s * (2 ** (self._trips - 1)))
        self._o.set_switch(self.switch, {"state": "cooling", "why": why, "failures": self.failures,
                                         "since": self._clock(), "until": self._clock() + wait})
        self._open = True


class RateLimit:
    """At most `per_minute` calls in any 60 seconds."""

    def __init__(self, per_minute: float, clock: Callable[[], float] = time.time):
        self.per_minute, self._clock = float(per_minute), clock
        self._calls: Deque[float] = collections.deque()

    def take(self) -> Optional[float]:
        """None when a call may go now (it is counted); otherwise the seconds until one may."""
        now = self._clock()
        while self._calls and now - self._calls[0] >= 60.0:
            self._calls.popleft()
        if len(self._calls) < max(1, int(self.per_minute)):
            self._calls.append(now)
            return None
        return 60.0 - (now - self._calls[0])


# ── records and events as the outbox keeps them ──────────────────────────────────────────────────────────────────────

def record_doc(rec: Record) -> Dict[str, Any]:
    return {"record_id": rec.record_id, "source": rec.source, "payload": dict(rec.payload), "meta": dict(rec.meta),
            "observed_at": rec.observed_at.isoformat() if rec.observed_at else None}


def record_from(doc: Mapping[str, Any]) -> Record:
    at = doc.get("observed_at")
    return Record(record_id=str(doc["record_id"]), payload=doc.get("payload") or {}, source=doc.get("source") or "",
                  observed_at=datetime.fromisoformat(at) if at else datetime.now(timezone.utc),
                  meta=doc.get("meta") or {})


def event_from(row: Row, data: Mapping[str, Any]) -> Event:
    """The Event a sink receives for an outbound row: its identity from the record (the event source puts event_type,
    aggregate_id, occurred_at and ledger in the record's meta, or in its payload), its data from the mapping."""
    rec = row.record or {}
    meta, payload = rec.get("meta") or {}, rec.get("payload") or {}

    def pick(name: str, default: Any = None) -> Any:
        if meta.get(name) not in (None, ""):
            return meta[name]
        return payload.get(name, default) if isinstance(payload, Mapping) else default

    at = pick("occurred_at")
    try:
        occurred = datetime.fromisoformat(str(at).replace("Z", "+00:00")) if at else None
    except ValueError:
        occurred = None
    return Event(event_id=str(rec.get("record_id") or row.record_id), event_type=str(pick("event_type", row.mapping)),
                 aggregate_id=str(pick("aggregate_id", "")), data=dict(data), occurred_at=occurred,
                 ledger=dict(pick("ledger", {}) or {}))


def _outcome_doc(out: Outcome) -> Dict[str, Any]:
    return {"status": out.status, "detail": out.detail, "reference": out.reference, "data": dict(out.data)}


# ── the proxy ────────────────────────────────────────────────────────────────────────────────────────────────────────

class Proxy:
    """One spec, running."""

    def __init__(self, spec: Spec, *, dry_run: bool = False, transport: Optional[httpx.AsyncBaseTransport] = None,
                 clock: Callable[[], float] = time.time, report: Optional[Callable[[Dict[str, Any]], None]] = None,
                 identity: Optional[Identity] = None, logger: Optional[logging.Logger] = None,
                 service: Optional[bool] = None, poll_s: float = 1.0):
        self.spec, self.dry_run, self._clock, self._report = spec, dry_run, clock, report
        self.log = logger or log
        self.poll_s = poll_s
        self.retry = {**DEFAULT_RETRY, **(spec.retry or {})}
        self.breaker_cfg = {**DEFAULT_BREAKER, **(spec.breaker or {})}
        svc = spec.service or {}
        self.service_enabled = (svc.get("enabled", True) if service is None else service)
        self.listen = svc.get("listen") or DEFAULT_LISTEN
        state_path = spec.state_path
        if dry_run:
            self.outbox = Outbox(":memory:")
            self._base = Outbox(state_path, readonly=True) if Path(state_path).exists() else None
        else:
            self.outbox = Outbox(state_path)
            self._base = None
        ident = spec.identity
        mtls = ident.get("mtls") or {}
        mtls_dir = None
        if mtls.get("enabled"):
            mtls_dir = str(Path(spec.base or ".") / (mtls.get("dir") or "certs"))
        self.identity = identity or Identity(
            spec.registry, spec.value(ident["agent_did"]), spec.value(ident["client_id"]),
            spec.value(ident["client_secret"]), mtls_dir=mtls_dir, transport=transport, clock=clock)
        self.client = RegistryClient(self.identity, transport=transport)
        self.mappings: Dict[str, MappingSpec] = {m.name: m for m in spec.mappings}
        self._by_source: Dict[str, List[MappingSpec]] = collections.defaultdict(list)
        for m in spec.mappings:
            self._by_source[m.source].append(m)
        self.sources: Dict[str, Source] = {}
        self.targets: Dict[str, Any] = {}
        for kind, group in (("source", spec.sources), ("action", spec.actions), ("sink", spec.sinks)):
            for name, ps in group.items():
                cls = load(kind, ps.type)
                inst = cls(ps.config, self._context(kind, name))
                if kind == "source":
                    self.sources[name] = inst
                else:
                    self.targets[name] = inst
        self.limits: Dict[str, RateLimit] = {
            name: RateLimit(ps.per_minute, clock) for group in (spec.actions, spec.sinks)
            for name, ps in group.items() if ps.per_minute}
        self.breakers: Dict[str, Breaker] = {
            m.name: Breaker(self.outbox, m.name, refusals=self.breaker_cfg["refusals"],
                            failures=self.breaker_cfg["failures"], cooldown_s=self.breaker_cfg["cooldown_s"],
                            max_s=self.retry["max_s"], clock=clock) for m in spec.mappings}
        self.counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = collections.defaultdict(float)
        self._wake = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        self._stopping = False
        self._started = False
        self._stopped = False
        self._service = None
        self._svid_task: Optional[asyncio.Task] = None
        self.finished_sources: set = set()

    # ── helpers ───────────────────────────────────────────────────────────────────────────────────────────────────

    def _context(self, kind: str, name: str) -> CoreContext:
        scope = f"{kind}:{name}"
        state = OverlayState(self._base, scope) if self.dry_run else PluginState(self.outbox, scope)
        return CoreContext(proxy_name=self.spec.name, agent_did=str(self.spec.value(self.spec.identity["agent_did"])),
                           registry_url=self.spec.registry, dry_run=self.dry_run,
                           logger=self.log.getChild(f"{kind}.{name}"), state=state, secret=self.spec.secret,
                           client=None if kind == "source" else self.client, kind=kind, name=name)

    def count(self, metric: str, n: float = 1.0, **labels: str) -> None:
        self.counters[(metric, tuple(sorted((k, str(v)) for k, v in labels.items())))] += n

    def _note(self, level: int, msg: str, **fields: Any) -> None:
        self.log.log(level, msg, extra={"proxy": fields})

    def backoff(self, attempts: int, after: Optional[float]) -> float:
        base = min(float(self.retry["max_s"]), float(self.retry["first_s"]) * (2 ** max(0, attempts - 1)))
        wait = base * (0.5 + random.random() / 2)          # jittered, so a crowd of rows does not retry in step
        return max(wait, float(after)) if after is not None else wait

    def paused(self, mapping: Optional[str] = None) -> bool:
        sw = self.outbox.switches() if not self.dry_run else {}
        if sw.get("pause"):
            return True
        return bool(mapping and sw.get(f"pause:{mapping}"))

    # ── inbound: a record into the outbox ────────────────────────────────────────────────────────────────────────

    async def ingest(self, source: str, rec: Record) -> List[str]:
        """Each mapping that takes the record writes its row (durably) and answers its key; a record already there is
        not written twice. A record a mapping cannot map is a dead row from the start, with the path it lacks."""
        if not isinstance(rec, Record):
            raise PluginError(f"the source {source!r} yielded a {type(rec).__name__}, not a Record")
        if not rec.source:
            rec = dataclasses.replace(rec, source=source)
        doc = record_doc(rec)
        keys = []
        for m in self._by_source.get(source, ()):
            try:
                if not takes(m.when, rec):
                    continue
            except (ValueError, TypeError) as e:
                self._note(logging.WARNING, "the mapping's condition cannot be read", mapping=m.name, error=str(e))
                continue
            key = key_for(source, rec.record_id, m.name, m.version)
            mapped, error = None, None
            try:
                mapped = apply(m.fields, rec)
            except Refused as e:
                error = e.detail
            if self.outbox.enqueue(key=key, mapping=m.name, version=m.version, source=source, record_id=rec.record_id,
                                   action=m.action, record=doc, mapped=mapped, error=error, now=self._clock()):
                keys.append(key)
                self.count("tp_proxy_records_total", source=source, mapping=m.name)
                if error is not None:
                    self.count("tp_proxy_dead_letters_total", mapping=m.name)
                    self._note(logging.WARNING, "a record the mapping cannot map: to the dead letters", mapping=m.name,
                               key=key, record_id=rec.record_id, why=error)
            else:
                self.count("tp_proxy_records_repeated_total", source=source, mapping=m.name)
        if keys:
            self._wake.set()
        return keys

    # ── the dispatcher ─────────────────────────────────────────────────────────────────────────────────────────────

    async def dispatch_once(self, *, limit: int = 50) -> int:
        """Send what is due (not paused, not stopped by a breaker, within the rate limits); answers how many were sent."""
        if self.paused():
            return 0
        held = self._held()
        sent = 0
        for row in self.outbox.due(limit=limit, now=self._clock(), skip_mappings=held):
            m = self.mappings.get(row.mapping)
            if m is None:
                self.outbox.dead(row.key, f"the spec has no mapping {row.mapping!r} now")
                continue
            target = self.targets.get(row.action)
            if target is None:
                self.outbox.dead(row.key, f"the spec has no action or sink {row.action!r} now")
                continue
            if not self.breakers[m.name].allows():
                continue      # it tripped on an earlier row of this round
            lim = self.limits.get(row.action)
            if lim is not None and lim.take() is not None:
                continue      # the row stays due; the next round takes it
            sent += 1
            await self._send(row, m, target)
        return sent

    async def _send(self, row: Row, m: MappingSpec, target: Any) -> None:
        b = self.breakers[m.name]
        labels = {"mapping": m.name, "target": row.action}
        try:
            mapped = row.mapped
            if mapped is None:
                # a replayed row the mapping could not map before: map it with the spec as it is now
                mapped = apply(m.fields, record_from(row.record))
                if not self.dry_run:
                    self.outbox.set_mapped(row.key, mapped)
            if isinstance(target, Action):
                out = await target.perform(mapped, key=row.key, dry_run=self.dry_run)
            else:
                out = await target.deliver(event_from(row, mapped), key=row.key, dry_run=self.dry_run)
            if not isinstance(out, Outcome):
                raise PluginError(f"{row.action!r} returned {type(out).__name__}, not an Outcome")
            if (out.status == "dry_run") != self.dry_run:
                raise PluginError(f"{row.action!r} answered {out.status!r} in a {'dry' if self.dry_run else 'real'} run")
        except Refused as e:
            self.outbox.dead(row.key, e.detail, answer=e.answer)
            self.count("tp_proxy_refused_total", **labels)
            self.count("tp_proxy_dead_letters_total", mapping=m.name)
            stopped = b.refused(e.detail)
            self._note(logging.WARNING, "refused: to the dead letters", key=row.key, why=e.detail, status=e.status,
                       stopped=stopped, **labels)
            return
        except PluginError as e:
            # a plugin that breaks the interface is not retried blindly: its row waits for a fix and a replay
            self.outbox.dead(row.key, f"plugin error: {e}")
            self.count("tp_proxy_dead_letters_total", mapping=m.name)
            b.refused(str(e))
            self._note(logging.ERROR, "plugin error: to the dead letters", key=row.key, why=str(e), **labels)
            return
        except Retry as e:
            self._failed(row, m, b, e.detail, e.after, labels)
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - an unexpected error may pass: retried like a Retry, and counted
            self._failed(row, m, b, f"{type(e).__name__}: {e}", None, labels)
            return
        self.outbox.done(row.key, _outcome_doc(out))
        b.ok()
        self.count("tp_proxy_sent_total", outcome=out.status, **labels)
        if self._report is not None:
            self._report({"mapping": m.name, "target": row.action, "key": row.key, "record_id": row.record_id,
                          **_outcome_doc(out)})
        self._note(logging.INFO, "dry run: would send" if self.dry_run else "done", key=row.key,
                   reference=out.reference, **labels)

    def _failed(self, row: Row, m: MappingSpec, b: Breaker, why: str, after: Optional[float],
                labels: Dict[str, str]) -> None:
        attempts = self.outbox.retry(row.key, why, after=self.backoff(row.attempts + 1, after), now=self._clock())
        self.count("tp_proxy_retries_total", **labels)
        tripped = b.failed(why)
        if attempts >= int(self.retry["attempts"]):
            self.outbox.dead(row.key, f"gave up after {attempts} attempts: {why}")
            self.count("tp_proxy_dead_letters_total", mapping=m.name)
            self._note(logging.WARNING, "gave up: to the dead letters", key=row.key, attempts=attempts, why=why,
                       **labels)
        else:
            self._note(logging.INFO, "will retry", key=row.key, attempts=attempts, why=why, cooling=tripped, **labels)

    # ── running ──────────────────────────────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for name, p in list(self.sources.items()) + list(self.targets.items()):
            await p.start()
        if not self.dry_run:
            try:
                await self.identity.token()
            except IdentityError as e:
                if e.status is not None and 400 <= e.status < 500 and e.status != 429:
                    raise
                self._note(logging.WARNING, "no token yet: the calls will retry", why=e.detail)
            if self.identity.mtls_dir:
                await self.identity.ensure_svid()
                self._svid_task = self.identity.start_svid_renewal()
        if self.service_enabled:
            from .service import start_service
            self._service = await start_service(self, self.listen)

    async def _run_source(self, name: str, src: Source) -> None:
        delay = 1.0
        while not self._stopping:
            try:
                async for rec in src.records():
                    if self._stopping:
                        return
                    await self.ingest(name, rec)
                    if not self.dry_run:
                        await src.committed(rec)       # only once the row is on disk
                    delay = 1.0
                self.finished_sources.add(name)
                self._note(logging.INFO, "the source has no more records", source=name)
                self._wake.set()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - a source that fails is started again, later each time
                self.count("tp_proxy_source_errors_total", source=name)
                self._note(logging.ERROR, "the source failed: starting it again", source=name,
                           why=f"{type(e).__name__}: {e}", after_s=delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, float(self.retry["max_s"]))

    async def _dispatch_loop(self) -> None:
        while not self._stopping:
            n = await self.dispatch_once()
            if n == 0:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self.poll_s)
                except asyncio.TimeoutError:
                    pass

    def _held(self) -> List[str]:
        """The mappings that send nothing now: paused by hand, or stopped by their breaker."""
        return [name for name in self.mappings if self.paused(name) or not self.breakers[name].allows()]

    def idle(self) -> bool:
        """Every source finished and nothing can be sent now (rows of a paused or stopped mapping wait for a resume,
        rows in their backoff for their time)."""
        if not set(self.sources) <= self.finished_sources:
            return False
        if self.paused():
            return True
        return not self.outbox.due(limit=1, now=self._clock(), skip_mappings=self._held())

    async def run(self, *, until_idle: bool = False, stop: Optional[asyncio.Event] = None) -> None:
        """Run until `stop` is set (or, with until_idle, until every source finished and nothing is due)."""
        await self.start()
        self._tasks = [asyncio.ensure_future(self._run_source(n, s)) for n, s in self.sources.items()]
        self._tasks.append(asyncio.ensure_future(self._dispatch_loop()))
        try:
            while True:
                if stop is not None and stop.is_set():
                    break
                if until_idle and self.idle():
                    break
                await asyncio.sleep(0.05)
        finally:
            await self.stop()

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []
        if self._svid_task is not None:
            self._svid_task.cancel()
            self._svid_task = None
        for name, p in list(self.sources.items()) + list(self.targets.items()):
            try:
                await p.stop()
            except Exception as e:  # noqa: BLE001
                self._note(logging.WARNING, "a plugin did not stop cleanly", plugin=name, why=str(e))
        if self._service is not None:
            await self._service.cleanup()
            self._service = None
        await self.client.aclose()
        self._started = False

    def close(self) -> None:
        self.outbox.close()
        if self._base is not None:
            self._base.close()

    # ── what status, health and metrics read ─────────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        sw = self.outbox.switches()
        by = self.outbox.counts_by_mapping()
        return {
            "name": self.spec.name, "agent_did": self.identity.agent_did, "registry": self.spec.registry,
            "dry_run": self.dry_run, "paused": bool(sw.get("pause")),
            "outbox": self.outbox.counts(), "mappings": {
                m: {**by.get(m, {"pending": 0, "done": 0, "dead": 0}),
                    "paused": bool(sw.get(f"pause:{m}")), "breaker": sw.get(f"breaker:{m}")}
                for m in self.mappings},
            "identity": {"tokens_issued": self.identity.issued, "last_error": self.identity.last_error,
                         "mtls": bool(self.identity.mtls_dir), "svid": bool(self.identity.client_cert())},
        }
