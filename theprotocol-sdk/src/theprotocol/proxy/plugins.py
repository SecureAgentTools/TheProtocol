"""TheProtocol Proxy: the plugin interface (interface version 1).

A proxy gives a legacy system an agent identity on TheProtocol and translates in both directions. The core runs three
kinds of plugin, each a class found by its entry point:

    kind     entry-point group             what it does
    source   theprotocol.proxy.sources     reads a legacy system and yields Records (inbound)
    action   theprotocol.proxy.actions     does one thing on TheProtocol with a mapped record (attest, ask, pay, ...)
    sink     theprotocol.proxy.sinks       delivers TheProtocol's Events to a legacy system (outbound)

The core owns everything around a plugin: the spec file (proxy.yaml) and its validation, the identity and its tokens,
the durable outbox and its exactly-once keys, dry-run, replay, the dead letters, the breaker, the rate limits, the logs
and the metrics. A plugin owns one conversation with one system and nothing else:

* A SOURCE yields `Record`s from `records()` until it is stopped. A record's `record_id` is the legacy system's own,
  stable id for the item: read again, the same item has the same id, because the exactly-once key is a hash of the
  source's name, the record id and the mapping's version. The core calls `committed(record)` once the record is durably
  in its outbox; that is where a source advances its cursor or acknowledges its broker. A payload is JSON-compatible.
  A source never calls TheProtocol itself.
* An ACTION does one call on TheProtocol through `ctx.call(...)`, with the key it is given as the call's
  Idempotency-Key (so a repeat is a no-op on the registry's side), and returns an `Outcome`. In a dry run it sends
  nothing and returns `Outcome.dry(...)` with the request it would have made. It raises `Refused` for an answer that
  will not change on a retry (the record goes to the dead letters, and `tp-proxy replay` sends it again after a fix) and
  `Retry` for one that may (the core retries with backoff, then its breaker stops the mapping). It declares the
  IRONKEY permissions it `needs` (the proxy holds only those) and whether it `moves_value` (such an action runs only
  under a Cockpit mandate, inside the mandate's limits).
* A SINK delivers one `Event` from TheProtocol to its system and returns an `Outcome`, with the same dry-run rule and
  the same two exceptions. A delivery repeated with the same key does nothing twice (a file sink names its file by the
  key, an HTTP sink sends the key as Idempotency-Key, and so on).

Every plugin class names itself (`name`, the type a spec section asks for), says which `kind` it is, and describes its
own section of the spec as a JSON Schema (`config_schema`). A field that holds a credential carries `"x-secret": true`
in that schema: the spec then refuses a literal value there and takes only a reference (`env:NAME` or `file:/path`),
which the plugin resolves at run time with `ctx.secret(...)`.

The contract tests every plugin must pass are in theprotocol.proxy.testing.
"""
from __future__ import annotations

import inspect
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, ClassVar, Dict, FrozenSet, Mapping, Optional, Protocol, Tuple, Type, Union

INTERFACE_VERSION = 1

GROUPS: Dict[str, str] = {
    "source": "theprotocol.proxy.sources",
    "action": "theprotocol.proxy.actions",
    "sink": "theprotocol.proxy.sinks",
}

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


# ── what flows through a proxy ───────────────────────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Record:
    """One thing a legacy system said, as a source yields it.

    `source` is the name of the source's section in the spec (the core fills it when the source leaves it empty);
    `record_id` is the legacy system's own stable id for the item; `payload` is JSON-compatible."""
    record_id: str
    payload: Mapping[str, Any]
    source: str = ""
    observed_at: datetime = field(default_factory=_now)
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    """One thing TheProtocol said, as a sink receives it.

    `ledger` carries what makes it verifiable without the network: the event store's id and sequence, the hash-chain
    links, and the registry card that signed it (whatever the subscription delivered)."""
    event_id: str
    event_type: str
    aggregate_id: str
    data: Mapping[str, Any]
    occurred_at: Optional[datetime] = None
    ledger: Mapping[str, Any] = field(default_factory=dict)


OUTCOMES = ("done", "dry_run")


@dataclass(frozen=True)
class Outcome:
    """What one action or sink call did. `reference` is the other side's id for it (an attestation, a transaction, a
    file); `data` is anything worth keeping with the record (in a dry run: the request that would have been made)."""
    status: str
    detail: str = ""
    reference: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in OUTCOMES:
            raise ValueError(f"an outcome is one of {OUTCOMES}, not {self.status!r} (a refusal is raised: Refused, Retry)")

    @classmethod
    def done(cls, reference: str = "", detail: str = "", **data: Any) -> "Outcome":
        return cls("done", detail=detail, reference=reference, data=data)

    @classmethod
    def dry(cls, detail: str = "", **would_send: Any) -> "Outcome":
        return cls("dry_run", detail=detail, data=would_send)


class PluginError(Exception):
    """A plugin that cannot be loaded or does not keep the interface."""


class Refused(Exception):
    """An answer a retry will not change. The record goes to the dead letters with `detail` (and the other side's
    `status`, when it has one); `tp-proxy replay` sends it again after a fix."""

    def __init__(self, detail: str, *, status: Optional[int] = None, answer: Any = None):
        super().__init__(detail)
        self.detail, self.status, self.answer = detail, status, answer


class Retry(Exception):
    """An answer that may change (a timeout, a 5xx, a 429). The core retries the record with backoff, no sooner than
    `after` seconds when the other side named a time, and its breaker stops the mapping after repeated failures."""

    def __init__(self, detail: str, *, after: Optional[float] = None, status: Optional[int] = None):
        super().__init__(detail)
        self.detail, self.after, self.status = detail, after, status


# ── what the core hands a plugin ─────────────────────────────────────────────────────────────────────────────────────

class StateStore(Protocol):
    """A small store that outlives the process, one per plugin instance (a source keeps its cursor here)."""

    async def get(self, key: str, default: Any = None) -> Any: ...

    async def set(self, key: str, value: Any) -> None: ...


class ProxyContext(Protocol):
    """What the core gives every plugin it runs.

    `call` is an authenticated call to the proxy's registry as the proxy's agent (the core keeps the token fresh, and
    the mTLS identity when the spec turns it on); it answers an httpx.Response. `secret` resolves a reference from the
    spec (`env:NAME`, `file:/path`); `state` persists; `logger` writes JSON lines with no secret in them."""

    proxy_name: str
    agent_did: str
    registry_url: str
    dry_run: bool
    logger: logging.Logger
    state: StateStore

    def secret(self, ref: str) -> str: ...

    async def call(self, method: str, path: str, *, json: Any = None, params: Optional[Mapping[str, Any]] = None,
                   idempotency_key: Optional[str] = None, headers: Optional[Mapping[str, str]] = None) -> Any: ...


# ── the three kinds ──────────────────────────────────────────────────────────────────────────────────────────────────

class _Plugin(ABC):
    kind: ClassVar[str] = ""
    name: ClassVar[str] = ""
    interface: ClassVar[int] = INTERFACE_VERSION
    config_schema: ClassVar[Mapping[str, Any]] = {"type": "object"}
    description: ClassVar[str] = ""

    def __init__(self, config: Mapping[str, Any], ctx: ProxyContext):
        self.config = dict(config or {})
        self.ctx = ctx

    async def start(self) -> None:
        """Open what the plugin needs (a connection, a listener). The core calls it once before any other method."""

    async def stop(self) -> None:
        """Close what start opened. The core calls it once, also after a failure."""


class Source(_Plugin):
    kind: ClassVar[str] = "source"

    @abstractmethod
    def records(self) -> AsyncIterator[Record]:
        """Yield the legacy system's records until stopped (an async generator)."""

    async def committed(self, record: Record) -> None:
        """The record is durably in the outbox: advance the cursor, acknowledge the broker."""

    async def rewind(self, point: str) -> None:
        """Read again from `point` on the next records() (`tp-proxy run --replay SOURCE=POINT`): move the cursor back to
        what `point` names in this source's own terms (a file name, an offset, a cursor value, a time). The records read
        again that are already in the outbox are not sent twice: their keys are there. Optional: a source that cannot
        read the past again (a webhook receiver) keeps this default, which says so."""
        raise PluginError(f"the source {self.name!r} cannot read again from a point")


class Action(_Plugin):
    kind: ClassVar[str] = "action"
    needs: ClassVar[FrozenSet[str]] = frozenset()
    moves_value: ClassVar[bool] = False

    @abstractmethod
    async def perform(self, mapped: Mapping[str, Any], *, key: str, dry_run: bool) -> Outcome:
        """Do the one call, with `key` as its Idempotency-Key; in a dry run send nothing and return Outcome.dry."""


class Sink(_Plugin):
    kind: ClassVar[str] = "sink"

    @abstractmethod
    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        """Deliver the event once per key; in a dry run deliver nothing and return Outcome.dry."""


BASES: Dict[str, Type[_Plugin]] = {"source": Source, "action": Action, "sink": Sink}
Plugin = Union[Source, Action, Sink]


# ── finding them ─────────────────────────────────────────────────────────────────────────────────────────────────────

# The core's own plugins: found without an installed distribution (a source checkout), and an installed plugin may not
# take one's name.
BUILTINS: Dict[str, Dict[str, str]] = {
    "source": {"webhook": "theprotocol.proxy.sources_builtin:WebhookSource",
               # V0659 (b): the two sources that need no server to test honestly. They live in the sources/ package
               # rather than beside the webhook in sources_builtin, because five of them are coming ((k), (l), (m)).
               "filedrop": "theprotocol.proxy.sources.filedrop:FileDropSource",
               "logtail": "theprotocol.proxy.sources.logtail:LogTailSource",
               # V0659 (k): a broker's messages; paho-mqtt comes with the proxy-mqtt extra, imported at start()
               "mqtt": "theprotocol.proxy.sources.mqtt:MqttSource",
               # V0659 (l): the SFTP poll (paramiko and defusedxml, the proxy-sftp extra, imported only when it runs)
               "sftp": "theprotocol.proxy.sources.sftp:SftpSource",
               # V0659 (m): a table or view, polled by a cursor column. Its drivers are optional extras, imported
               # only when the source starts, so the class loads (and is checked) without any of them.
               "sqlpoll": "theprotocol.proxy.sources.sqlpoll:SqlPollSource",
               # V0659 (c)
               "theprotocol_events": "theprotocol.proxy.sources_builtin:TheProtocolEventsSource",
               # V0660 (c): the QPU recipe's results
               "quantum_results": "theprotocol.proxy.quantum.plugins:QuantumResultSource",
               # V0664 (M3): used by tp-proxy migrate --sample only: a kit's sample read as the source it stands in for
               "migrate_sample": "theprotocol.proxy.migrate.sample:MigrateSampleSource"},
    "action": {"attestation": "theprotocol.proxy.actions_builtin:AttestationAction",
               "a2a_task": "theprotocol.proxy.actions_builtin:A2ATaskAction",
               "payment": "theprotocol.proxy.actions_builtin:PaymentAction",
               "milestone_evidence": "theprotocol.proxy.actions_builtin:MilestoneEvidenceAction",
               "chat_message": "theprotocol.proxy.actions_builtin:ChatMessageAction",
               "quantum_report": "theprotocol.proxy.quantum.plugins:QuantumReportAction"},
    "sink": {"webhook": "theprotocol.proxy.sinks_builtin:WebhookSink",
             "journal": "theprotocol.proxy.sinks_builtin:JournalSink",
             "calendar": "theprotocol.proxy.sinks_builtin:CalendarSink",
             "email_digest": "theprotocol.proxy.sinks_builtin:EmailDigestSink",
             "evidence": "theprotocol.proxy.evidence:EvidenceSink",
             # V0664 (Migrate a system, M1): the writers, the new system's side of a migration
             "sql_upsert": "theprotocol.proxy.sinks.sql_upsert:SqlUpsertSink",
             "rest": "theprotocol.proxy.sinks.rest:RestSink",
             "file_out": "theprotocol.proxy.sinks.file_out:FileOutSink",
             "quantum_submit": "theprotocol.proxy.quantum.plugins:QuantumSubmitSink"},
}


def problems(cls: Any, kind: Optional[str] = None) -> Tuple[str, ...]:
    """What keeps `cls` from being a plugin of `kind` (empty when it is one)."""
    out = []
    if not inspect.isclass(cls):
        return (f"{cls!r} is not a class",)
    want = kind or getattr(cls, "kind", "")
    base = BASES.get(want)
    if base is None:
        return (f"{cls.__name__}: kind {want!r} is none of {tuple(BASES)}",)
    if not issubclass(cls, base):
        out.append(f"{cls.__name__} is not a {base.__name__} (theprotocol.proxy.{base.__name__})")
    if getattr(cls, "kind", None) != want:
        out.append(f"{cls.__name__}: kind is {getattr(cls, 'kind', None)!r}, not {want!r}")
    name = getattr(cls, "name", "")
    if not isinstance(name, str) or not _NAME.match(name):
        out.append(f"{cls.__name__}: name {name!r} is not a lower-case identifier (it is the spec's type for it)")
    if getattr(cls, "interface", None) != INTERFACE_VERSION:
        out.append(f"{cls.__name__}: built for interface {getattr(cls, 'interface', None)!r}, this core runs {INTERFACE_VERSION}")
    schema = getattr(cls, "config_schema", None)
    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        out.append(f"{cls.__name__}: config_schema is not a JSON Schema of an object")
    if inspect.isabstract(cls):
        missing = sorted(getattr(cls, "__abstractmethods__", ()))
        out.append(f"{cls.__name__} does not implement {', '.join(missing)}")
    if want == "action":
        if not isinstance(getattr(cls, "needs", None), frozenset):
            out.append(f"{cls.__name__}: needs is not a frozenset of permissions")
        if not isinstance(getattr(cls, "moves_value", None), bool):
            out.append(f"{cls.__name__}: moves_value is not a bool")
    return tuple(out)


def _entry_points(group: str):
    from importlib.metadata import entry_points
    eps = entry_points()
    if hasattr(eps, "select"):            # Python 3.10+
        return list(eps.select(group=group))
    return list(eps.get(group, []))     # pragma: no cover


def available(kind: str) -> Dict[str, str]:
    """name -> where it comes from ("module:Class"), the built-ins and every installed plugin of `kind`. An installed
    plugin may not take a built-in's name."""
    if kind not in GROUPS:
        raise PluginError(f"no plugin kind {kind!r}: one of {tuple(GROUPS)}")
    out = dict(BUILTINS[kind])
    for ep in _entry_points(GROUPS[kind]):
        if ep.name in BUILTINS[kind] and ep.value != BUILTINS[kind][ep.name]:
            continue
        out.setdefault(ep.name, ep.value)
    return out


def load(kind: str, name: str) -> Type[_Plugin]:
    """The plugin class of `kind` called `name`, checked against the interface (PluginError when it is not one)."""
    where = available(kind).get(name)
    if where is None:
        raise PluginError(f"no {kind} plugin called {name!r} (installed: {', '.join(sorted(available(kind))) or 'none'})")
    module, _, attr = where.partition(":")
    try:
        import importlib
        cls = getattr(importlib.import_module(module), attr)
    except Exception as e:  # noqa: BLE001
        raise PluginError(f"the {kind} plugin {name!r} ({where}) does not load: {type(e).__name__}: {e}") from e
    bad = problems(cls, kind)
    if bad:
        raise PluginError(f"the {kind} plugin {name!r} ({where}) does not keep the interface: " + "; ".join(bad))
    if cls.name != name:
        raise PluginError(f"the {kind} plugin registered as {name!r} calls itself {cls.name!r}")
    return cls
