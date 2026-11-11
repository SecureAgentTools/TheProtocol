"""An MQTT broker in the test's own event loop, for the MQTT source's hermetic tests (tests/test_proxy_source_mqtt.py).

It keeps what a broker keeps and does what the source depends on: sessions by client id, QoS 0 and 1, a persistent
session's unacknowledged messages sent again on its next connect (DUP set, the same packet id, in their order), the
queue a persistent session gathers while its client is away, retained messages by topic (sent on a new subscription,
with MQTT 5's retain handling), and the faults a test injects: a dropped connection (the client connects again), a lost
session (a broker that kept nothing), a lost PUBACK. The real broker (eclipse-mosquitto) is in
tests/test_proxy_source_mqtt_broker.py.

`per_state=True` keys a session by the proxy's state as well as by the client id. The contract harness
(theprotocol.proxy.testing) reads one input with several FRESH contexts, and each stands for a proxy of its own (which
in a deployment has a client id of its own); every new session is sent `seed` once it subscribes, as if the legacy
system published it then.

`reuse_ids=True` hands out the lowest packet id that is free, as MQTT allows once a PUBACK is in (at a low rate every
message then goes out under id 1); by default the ids count up, as mosquitto's do.
"""
from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple, Union

from theprotocol.proxy.sources.mqtt import Delivery


def matches(flt: str, topic: str) -> bool:
    """An MQTT topic filter against a topic name: `+` is one level, `#` the rest (a `$share/<group>/` prefix aside)."""
    if flt.startswith("$share/"):
        flt = flt.split("/", 2)[2] if flt.count("/") >= 2 else ""
    f, t = flt.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


@dataclass
class Pub:
    topic: str
    payload: bytes
    qos: int = 1
    retain: bool = False
    user_properties: Mapping[str, str] = field(default_factory=dict)
    content_type: Optional[str] = None


@dataclass
class Session:
    client_id: str
    clean: bool
    subs: Dict[str, int] = field(default_factory=dict)
    queue: Deque[Tuple[Pub, int, bool]] = field(default_factory=collections.deque)      # (message, qos, retain flag)
    inflight: "collections.OrderedDict[int, Tuple[Pub, int, bool]]" = field(default_factory=collections.OrderedDict)
    next_mid: int = 1
    seeded: bool = False
    link: Optional["FakeLink"] = None


class FakeBroker:
    def __init__(self, *, seed: Tuple[Union[Pub, tuple], ...] = (), per_state: bool = False, inflight_max: int = 20,
                 reuse_ids: bool = False):
        self.seed = [p if isinstance(p, Pub) else Pub(p[0], p[1] if isinstance(p[1], bytes) else str(p[1]).encode(),
                                                      *p[2:]) for p in seed]
        self.per_state = per_state
        self.inflight_max = inflight_max
        self.reuse_ids = reuse_ids
        self.sessions: Dict[Any, Session] = {}
        self.retained: Dict[str, Pub] = {}
        self.links: List["FakeLink"] = []
        self.acks: List[Tuple[str, int]] = []           # every PUBACK the broker took: (client id, packet id)
        self.lost_acks: List[Tuple[str, int]] = []      # PUBACKs lost on the way (lose_acks)
        self.stale_acks: List[Tuple[str, int]] = []     # PUBACKs sent on a connection that had already dropped
        self.lose_acks = 0                              # the next N PUBACKs are lost on the way
        self.connects: List[Tuple[str, bool]] = []      # (client id, session present) per CONNACK
        self.subscribes: List[Tuple[str, List[Tuple[str, int]], int]] = []   # (client id, filters, retain handling)
        self.unsubscribes: List[Tuple[str, List[str]]] = []

    # ── what a client and a publisher do ────────────────────────────────────────────────────────────────────────

    def link(self, source: Any, settings: Any) -> "FakeLink":
        link = FakeLink(self, source, settings)
        self.links.append(link)
        return link

    def publish(self, topic: str, payload: Union[bytes, str] = b"", *, qos: int = 1, retain: bool = False,
                user_properties: Optional[Mapping[str, str]] = None, content_type: Optional[str] = None) -> None:
        body = payload.encode() if isinstance(payload, str) else bytes(payload)
        pub = Pub(topic, body, qos, retain, dict(user_properties or {}), content_type)
        if retain:
            if body:
                self.retained[topic] = pub
            else:
                self.retained.pop(topic, None)
        for s in list(self.sessions.values()):
            q = self._granted(s, topic)
            if q is not None:
                s.queue.append((pub, min(qos, q), False))   # a live delivery carries retain 0 (MQTT 3.3.1.3)
                self._pump(s)

    # ── the faults ──────────────────────────────────────────────────────────────────────────────────────────────

    def drop(self, *, reconnect: bool = True) -> None:
        """Every connection drops; each client connects again on the next turn of the loop (its session kept), or,
        with reconnect=False, only once reconnect() is called (the broker is away meanwhile)."""
        for link in list(self.links):
            if link.connected:
                self._lost(link, "the connection dropped")
                if reconnect:
                    link.reconnect_soon()

    def reconnect(self) -> None:
        """The broker is back: every client whose connection dropped connects again."""
        for link in list(self.links):
            if not link.connected:
                link.reconnect_soon()

    def forget(self) -> None:
        """The broker restarts having kept nothing: every connection drops and every session is gone."""
        live = [link for link in self.links if link.connected]
        for link in live:
            self._lost(link, "the broker went away")
        self.sessions.clear()
        for link in live:
            link.reconnect_soon()

    # ── the session machinery ───────────────────────────────────────────────────────────────────────────────────

    def _key(self, link: "FakeLink") -> Any:
        if self.per_state:
            return (link.settings.client_id, id(link.source.ctx.state))
        return link.settings.client_id

    def _granted(self, s: Session, topic: str) -> Optional[int]:
        best = None
        for flt, q in s.subs.items():
            if matches(flt, topic):
                best = q if best is None else max(best, q)
        return best

    def _connect(self, link: "FakeLink") -> None:
        if link.closed:
            return
        key = self._key(link)
        s = self.sessions.get(key)
        if s is not None and link.settings.clean:
            del self.sessions[key]
            s = None
        present = s is not None
        if s is None:
            s = Session(link.settings.client_id, link.settings.clean)
            self.sessions[key] = s
        if s.link is not None and s.link is not link and s.link.connected:
            self._lost(s.link, "another connection took the session over")
        s.link = link
        link.session = s
        link.connected = True
        link.epoch += 1
        self.connects.append((link.settings.client_id, present))
        link.call(link.source._link_connected, present)
        for mid, (pub, qos, retain) in s.inflight.items():      # what was in flight goes again: DUP, same id, in order
            link.deliver(pub, qos, mid, dup=True, retain=retain)
        self._pump(s)

    def _lost(self, link: "FakeLink", why: str) -> None:
        link.connected = False
        link.epoch += 1                                         # what was on its way to that connection never arrives
        link.call(link.source._link_lost, why)

    def _close(self, link: "FakeLink") -> None:
        s = link.session
        link.connected = False
        link.closed = True
        link.epoch += 1
        if s is not None and s.link is link:
            s.link = None
            if s.clean:
                self.sessions = {k: v for k, v in self.sessions.items() if v is not s}

    def _pump(self, s: Session) -> None:
        link = s.link
        if link is None or not link.connected:
            return
        while s.queue:
            pub, qos, retain = s.queue[0]
            if qos == 1 and len(s.inflight) >= self.inflight_max:
                break
            s.queue.popleft()
            if qos == 1:
                if self.reuse_ids:
                    mid = 1
                    while mid in s.inflight:
                        mid += 1
                else:
                    mid = s.next_mid
                    s.next_mid = s.next_mid % 65535 + 1
                s.inflight[mid] = (pub, qos, retain)
            else:
                mid = 0
            link.deliver(pub, qos, mid, dup=False, retain=retain)

    def _subscribe(self, link: "FakeLink", items: List[Tuple[str, int]], retain_handling: int) -> None:
        s = link.session
        self.subscribes.append((link.settings.client_id, list(items), retain_handling))
        if s is None:
            return
        v5 = str(link.settings.protocol) == "5"
        results = []
        for flt, q in items:
            new = flt not in s.subs
            s.subs[flt] = q
            results.append((flt, q))
            if not v5 or retain_handling == 0 or (retain_handling == 1 and new):
                for topic, pub in sorted(self.retained.items()):
                    if matches(flt, topic):
                        s.queue.append((pub, min(pub.qos, q), True))
        if not s.seeded:
            s.seeded = True
            for pub in self.seed:
                q = self._granted(s, pub.topic)
                if q is not None:
                    s.queue.append((pub, min(pub.qos, q), False))
        link.call(link.source._link_subscribed, results)
        self._pump(s)

    def _unsubscribe(self, link: "FakeLink", filters: List[str]) -> None:
        self.unsubscribes.append((link.settings.client_id, list(filters)))
        if link.session is not None:
            for flt in filters:
                link.session.subs.pop(flt, None)

    def _ack(self, link: "FakeLink", mid: int) -> None:
        cid = link.settings.client_id
        if not link.connected:
            self.stale_acks.append((cid, mid))
            return
        if self.lose_acks > 0:
            self.lose_acks -= 1
            self.lost_acks.append((cid, mid))
            return
        self.acks.append((cid, mid))
        s = link.session
        if s is not None:
            s.inflight.pop(mid, None)
            self._pump(s)


class FakeLink:
    """The client side of one source's connection to the FakeBroker (the source's link_factory returns it)."""

    blocking_close = False        # close() is quick and belongs on the event loop (the paho link's blocks)

    def __init__(self, broker: FakeBroker, source: Any, settings: Any):
        self.broker, self.source, self.settings = broker, source, settings
        self.session: Optional[Session] = None
        self.connected = False
        self.closed = False
        self.epoch = 0
        self.opened = 0

    # what the source calls
    def open(self) -> None:
        self.opened += 1
        asyncio.get_running_loop().call_soon(self.broker._connect, self)

    def close(self) -> None:
        self.broker._close(self)

    def subscribe(self, items: List[Tuple[str, int]], retain_handling: int = 0) -> None:
        self.broker._subscribe(self, items, retain_handling)

    def unsubscribe(self, filters: List[str]) -> None:
        self.broker._unsubscribe(self, filters)

    def ack(self, mid: int) -> None:
        self.broker._ack(self, mid)

    # what the broker does to it
    def call(self, fn: Any, *args: Any) -> None:
        epoch = self.epoch

        def run() -> None:
            if not self.closed and self.epoch == epoch:
                fn(*args)
        asyncio.get_running_loop().call_soon(run)

    def deliver(self, pub: Pub, qos: int, mid: int, *, dup: bool, retain: bool) -> None:
        self.call(self.source._link_message, Delivery(topic=pub.topic, payload=pub.payload, qos=qos, mid=mid, dup=dup,
                                                      retain=retain, user_properties=dict(pub.user_properties),
                                                      content_type=pub.content_type))

    def reconnect_soon(self) -> None:
        if not self.closed:
            asyncio.get_running_loop().call_soon(self.broker._connect, self)
