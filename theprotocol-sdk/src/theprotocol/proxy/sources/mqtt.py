"""The MQTT source: the messages a broker delivers on the topics this source subscribes to (MQTT 3.1.1 or 5, TLS with a
client certificate, QoS 0 and 1).

    sources:
      meters:
        type: mqtt
        config:
          host: broker.plant.local
          protocol: "5"                          # or "3.1.1" (the default)
          client_id: tp-proxy-meters             # the broker keeps this source's session under this name
          topics: ["meters/+/reading", {filter: "alarms/#", qos: 1}]
          tls:                                   # port 8883 unless named
            ca_file: /etc/tp-proxy/plant-ca.crt
            cert_file: /etc/tp-proxy/meters.crt
            private_key: file:/etc/tp-proxy/meters.key     # a reference, as every credential
          id_field: $.seq                        # the device's own id for a reading, when it sends one

V0659 (k). A record is one message: its payload carries the topic, the topic's levels (so a mapping can take the device
from `$.payload.levels.1`), the message read as `format` says, its QoS and its retain flag, and on MQTT 5 its user
properties (a name given more than once maps to the list of its values) and content type. A message is never dropped
for its shape: one that is not JSON is carried as text, one that is not text as base64, and `encoding` says which.

How a message becomes exactly one record, from the broker to the ledger:

* The session is persistent. MQTT 3.1.1 connects with clean session 0, MQTT 5 with clean start 0 and a session expiry
  (`session_expiry_s`, by default one that never ends). While the proxy is down the broker keeps what arrives for this
  client id, and sends it on the next connect.
* A message is acknowledged (PUBACK) in `committed()`, once its record is in the outbox, and only then: the PUBACK is
  what moves the session on. A message the proxy had received but not stored when it stopped is unacknowledged, so
  the broker sends it again, with DUP set, the same packet id and in its original order: no gap.
* The copy has the same record id, so the outbox's key drops it: no duplicate. The id is, in this order: the
  publisher's own id, scoped by the topic (`id_property`, an MQTT 5 user property, or `id_field`, a field of a JSON
  payload); a retained message taken at subscription (`retained: take`) is named by its topic and content; any other
  QoS 1 message by its place in the source's stream of QoS 1 messages, `seq-N`. A place is written to `ctx.state`
  with the message's packet id before its record leaves the source, so it is never given to another message, and a
  copy the broker sends again (DUP set, the packet id and the content of one of the last 256 places given) gets that
  place again and takes no new one: the message in hand at a stop, and one whose PUBACK was lost after its commit.
* A packet id names a message only within the broker's session that gave it, and the places remember which session
  that was. A broker that answers a connect with a new session (it lost the old one), or a spec that names another
  broker or client id, starts a session whose packet ids name other messages; and a packet id the broker gives to a
  new message (it may, once it has the PUBACK) no longer names the one remembered under it.
* When the connection drops and the broker kept the session, it sends again every QoS 1 message it has not had the
  PUBACK of: the ones the lost connection delivered that the source had not taken yet are dropped, and taken from
  the broker's copies (when the session is new, they are the only copies, and are taken). Fewer than 256 messages are
  in flight on one connection: MQTT 5 connects with a Receive Maximum of 128; on MQTT 3.1.1 the broker's own limit
  applies (mosquitto's max_inflight_messages, 20 by default), and the source says so in the log when it sends more.
* No broker sends a QoS 0 message twice (at most once, by definition), so it takes no place in that stream; it is named
  by the run that received it, `q0-R.N`, and two runs never share a name.
* QoS 2 is refused. A client hands a QoS 2 message over at its PUBREC, which a client library sends at once, before the
  proxy has the record on disk: a crash in between loses the message. QoS 1, acknowledged only after the outbox has the
  record, with the outbox's keys, is exactly once.

Retained messages: a broker sends a topic's retained message whenever a subscription to it is made, which is not a
publication made while the proxy listened. By default (`retained: skip`) those are acknowledged and passed over (MQTT 5
asks the broker for none); `retained: take` takes them, each named by its topic and content, so the same stored value
is one record however often it is sent. The source subscribes again only when the broker did not keep its session (it
says so in the log: what the broker held for it is gone), subscribes a filter the spec added and unsubscribes one it
dropped. A message on a topic no filter of the source names (a subscription the session holds from an earlier spec,
or from another client under this client id) is acknowledged and passed over, and named in the log.

What the source cannot make up for, and says where it can: a broker that lost the session (a restart with no
persistence) lost what it held for it; a broker that came back with older state than it had acknowledged (a crash
between its own saves) sends again messages committed long ago, and only the publisher's own id (`id_property`,
`id_field`) recognises those; a publisher that sends a QoS 1 message twice made two messages, unless they carry such
an id. One case stays ambiguous, for a message with the topic and content of one given a place among the last 256:
the broker sends it again (DUP set) under the packet id that message last had, and the source never took its earlier
copy (it was lost on the wire, or the proxy stopped before taking it, or before it had recorded that the broker
started a new session). It is taken for that message, and the outbox drops it. A QoS 1 topic whose content repeats
(a state, a heartbeat) should carry the publisher's own id.

A dry run connects as a session of its own (`<client_id>-dry-run`, clean) so that it neither takes the running proxy's
session over nor consumes its messages: it subscribes a shared subscription (`$share/<group>/<filter>`) as its plain
filter, since as a member of the group it would take some of the group's messages, and it acknowledges what it reads,
since it keeps nothing. With `finish_after_idle_s`, the source finishes once it has been subscribed and quiet for that
long (`tp-proxy run --once` then drains what the broker kept for this session and exits). The connection is
paho-mqtt's (`pip install 'theprotocol-sdk[proxy-mqtt]'`), on a network thread of its own, which connects again by
itself.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import hashlib
import json
import os
import ssl
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, ClassVar, Deque, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from ..mapping import _MISSING, lookup
from ..plugins import PluginError, Record, Source

PROTOCOLS = ("3.1.1", "5")
FORMATS = ("json", "text", "bytes")
RETAINED = ("skip", "take")
NEVER_EXPIRES = 0xFFFFFFFF          # MQTT 5's Session Expiry Interval for a session that does not end
RECENT = 256                        # places remembered with their packet ids, to know a copy the broker sends again
RECEIVE_MAXIMUM = 128               # MQTT 5: QoS 1 messages the broker may have in flight to this source
PASSED_OVER_NAMED = 20              # topics no filter names, each named once in the log, up to this many

_RECENT_KEY = "mqtt.recent."        # + slot (place % RECENT): [packet id or null, fingerprint, place, epoch]
_EPOCH_KEY = "mqtt.epoch"           # which of the broker's sessions the remembered packet ids belong to
_SESSION_KEY = "mqtt.session"       # host:port/client id, the session the remembered packet ids belong to
_RUN_KEY = "mqtt.run"               # how many times this source has started (names the QoS 0 messages)
_SUBSCRIBED_KEY = "mqtt.subscribed"  # {filter: qos} the broker has for the session

# a remembered place: (packet id, or None once the broker gave the id to another message; fingerprint; place; epoch)
_Entry = Tuple[Optional[int], str, int, int]

_QOS2 = ("QoS 2 is refused: a client hands a QoS 2 message over at its PUBREC, sent before the proxy has the record "
         "on disk, so a crash in between loses it. QoS 1 (acknowledged once the record is in the outbox) with the "
         "outbox's keys is exactly once")


@dataclass(frozen=True)
class Delivery:
    """One PUBLISH, as a link hands it to the source."""
    topic: str
    payload: bytes
    qos: int
    mid: int
    dup: bool = False
    retain: bool = False
    user_properties: Mapping[str, Any] = field(default_factory=dict)      # name -> value, or the list of its values
    content_type: Optional[str] = None


@dataclass(frozen=True)
class Settings:
    """What a link connects with."""
    host: str
    port: int
    protocol: str
    client_id: str
    clean: bool
    session_expiry_s: int
    keepalive_s: int
    username: Optional[str] = None
    password: Optional[str] = field(default=None, repr=False)
    tls: Optional[ssl.SSLContext] = None
    manual_ack: bool = True


@dataclass
class _Taken:
    record: Record
    delivery: Delivery
    gen: int                  # the connection it came in on
    epoch: int                # the broker's session its packet id belongs to
    kind: str                 # own, retained, q0, seq
    place: Optional[int]
    fp: str
    written: bool = False     # its place is on disk (seq), or it has none to write


def _fingerprint(topic: str, payload: bytes) -> str:
    return hashlib.sha256(topic.encode("utf-8") + b"\x00" + payload).hexdigest()[:16]


def user_properties(pairs: Optional[Iterable[Tuple[Any, Any]]]) -> Dict[str, Any]:
    """MQTT 5 user properties as a mapping: a name given once maps to its value, a name given more than once (MQTT 5
    allows it) to the list of its values, in their order."""
    out: Dict[str, Any] = {}
    for name, value in pairs or ():
        name, value = str(name), str(value)
        if name not in out:
            out[name] = value
        elif isinstance(out[name], list):
            out[name].append(value)
        else:
            out[name] = [out[name], value]
    return out


def plain_filter(flt: str) -> str:
    """A shared subscription's filter without its $share/<group>/ prefix (any other filter as it is)."""
    return flt.split("/", 2)[2] if flt.startswith("$share/") and flt.count("/") >= 2 else flt


def topic_matches(flt: str, topic: str) -> bool:
    """Whether a topic name falls under a topic filter, as MQTT matches them: + is one level, # the rest of the topic
    and its parent level (meters/# takes meters), a $share/<group>/ prefix aside, and a topic that starts with $ is
    matched by no filter that starts with a wildcard."""
    flt = plain_filter(flt)
    if topic.startswith("$") and flt[:1] in ("+", "#"):
        return False
    f, t = flt.split("/"), topic.split("/")
    for i, level in enumerate(f):
        if level == "#":
            return True
        if i >= len(t) or (level != "+" and level != t[i]):
            return False
    return len(f) == len(t)


def _entry(stored: Any) -> Optional[_Entry]:
    """A remembered place as the state keeps it, or None for a slot never written (or not readable)."""
    if not isinstance(stored, list) or len(stored) not in (3, 4):
        return None
    try:
        mid = None if stored[0] is None else int(stored[0])
        epoch = int(stored[3]) if len(stored) == 4 else -1      # no epoch: its place counts, its packet id is unknown
        return mid, str(stored[1]), int(stored[2]), epoch
    except (TypeError, ValueError):
        return None


def _decode(payload: bytes, fmt: str) -> Tuple[Any, str]:
    """The payload as `fmt` reads it, falling back (json -> text -> base64) rather than dropping a message."""
    if fmt != "bytes":
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is not None:
            if fmt == "json":
                try:
                    return json.loads(text), "json"
                except ValueError:
                    pass
            return text, "text"
    return base64.b64encode(payload).decode("ascii"), "base64"


def check_filter(flt: Any) -> str:
    """An MQTT topic filter, or PluginError naming what is wrong with it."""
    if not isinstance(flt, str) or not flt:
        raise PluginError(f"mqtt: a topic filter is a non-empty string, not {flt!r}")
    if "\x00" in flt:
        raise PluginError(f"mqtt: the topic filter {flt!r} holds a NUL character")
    rest = flt
    if flt.startswith("$share/"):
        parts = flt.split("/", 2)
        if len(parts) < 3 or not parts[1] or any(c in parts[1] for c in "+#") or not parts[2]:
            raise PluginError(f"mqtt: {flt!r} is not a shared subscription ($share/<group>/<filter>)")
        rest = parts[2]
    levels = rest.split("/")
    for i, level in enumerate(levels):
        if "#" in level and (level != "#" or i != len(levels) - 1):
            raise PluginError(f"mqtt: in {flt!r}, # stands alone as the last level (meters/#)")
        if "+" in level and level != "+":
            raise PluginError(f"mqtt: in {flt!r}, + stands alone for one whole level (meters/+/reading)")
    return flt


# ── TLS ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _load_cert_chain(ctx: ssl.SSLContext, cert_file: str, key_pem: str, password: Any) -> None:
    """Load the client certificate with its private key. Python's ssl module reads a key only from a file, so the key
    goes through an anonymous in-memory file where the system has one (memfd, Linux) and otherwise through a file only
    this process can read, in a directory of its own, removed as soon as it is loaded."""
    data = key_pem.encode("utf-8")
    if not data.endswith(b"\n"):
        data += b"\n"
    memfd = getattr(os, "memfd_create", None)
    if memfd is not None:
        try:
            fd = memfd("tp-proxy-mqtt-key", getattr(os, "MFD_CLOEXEC", 0))
        except OSError:
            fd = None
        if fd is not None:
            try:
                os.write(fd, data)
                path = f"/proc/self/fd/{fd}"
                if os.path.exists(path):
                    ctx.load_cert_chain(cert_file, path, password)
                    return
            finally:
                os.close(fd)
    with tempfile.TemporaryDirectory(prefix="tp-proxy-mqtt-") as d:
        path = os.path.join(d, "client.key")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        ctx.load_cert_chain(cert_file, path, password)


def _no_prompt() -> bytes:
    # without a key_password OpenSSL would prompt on the terminal for an encrypted key, and a daemon would hang there
    return b""


def _watched(on_error: Callable[[BaseException], None]) -> type:
    """An SSLSocket that reports a failed handshake (paho retries a connect without saying why it failed)."""

    class _WatchedSocket(ssl.SSLSocket):
        def do_handshake(self, *args: Any, **kwargs: Any) -> None:
            try:
                return super().do_handshake(*args, **kwargs)
            except OSError as exc:              # ssl.SSLError is an OSError
                try:
                    on_error(exc)
                except Exception:  # noqa: BLE001 - a report must never change the handshake's outcome
                    pass
                raise

    return _WatchedSocket


def tls_context(*, ca_file: Optional[str] = None, cert_file: Optional[str] = None, private_key: Optional[str] = None,
                key_password: Optional[str] = None,
                on_error: Optional[Callable[[BaseException], None]] = None) -> ssl.SSLContext:
    """The TLS a source connects with: the broker verified against `ca_file` (the system's CAs without one), strictly
    (RFC 5280) and with its host name checked, TLS 1.2 at least, and the client certificate `cert_file` with
    `private_key` (the PEM text, as ctx.secret resolves its reference) when the broker asks for one."""
    try:
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file or None)
    except (OSError, ssl.SSLError) as exc:
        raise PluginError(f"mqtt: tls.ca_file {ca_file!r} cannot be read as CA certificates: {exc}") from None
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    # RFC 5280 strictly, as Python verifies by default from 3.13 on: set here on every Python, so a broker certificate
    # that passes on one passes on all (on 3.10 to 3.12 a leaf without its authority key id would pass, then fail)
    ctx.verify_flags |= ssl.VERIFY_X509_STRICT | ssl.VERIFY_X509_PARTIAL_CHAIN
    if cert_file or private_key:
        if not (cert_file and private_key):
            raise PluginError("mqtt: a client certificate is tls.cert_file with its tls.private_key")
        try:
            _load_cert_chain(ctx, cert_file, private_key, key_password if key_password is not None else _no_prompt)
        except (OSError, ssl.SSLError, ValueError) as exc:
            raise PluginError(f"mqtt: the client certificate {cert_file!r} and its private key do not load together "
                              f"(a wrong key, a wrong tls.key_password, or a file that cannot be read): "
                              f"{type(exc).__name__}: {exc}") from None
    if on_error is not None:
        ctx.sslsocket_class = _watched(on_error)
    return ctx


# ── the connection: paho-mqtt ───────────────────────────────────────────────────────────────────────────────────────

class PahoLink:
    """The source's connection to its broker, through paho-mqtt: its network loop runs on a thread of its own and
    connects again by itself (1 s, doubling to 30 s). It calls the source's _link_* methods from that thread."""

    blocking_close = True         # close() joins the network thread: the source runs it off the event loop

    def __init__(self, source: "MqttSource", s: Settings):
        try:
            import paho.mqtt.client as mqtt
            from paho.mqtt.enums import CallbackAPIVersion
            from paho.mqtt.packettypes import PacketTypes
            from paho.mqtt.properties import Properties
            from paho.mqtt.subscribeoptions import SubscribeOptions
        except ImportError as exc:
            raise PluginError("mqtt: the mqtt source needs paho-mqtt: "
                              "pip install 'theprotocol-sdk[proxy-mqtt]'") from exc
        self._src, self._s = source, s
        self._v5 = s.protocol == "5"
        self._SubscribeOptions = SubscribeOptions
        self._log_error: Optional[str] = None
        self._tls_error: Optional[str] = None
        self._refusal: Optional[str] = None       # this attempt's refusal, which its disconnect must not hide
        self._subs: Dict[int, List[Tuple[str, int]]] = {}
        self._subs_lock = threading.Lock()
        self._client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=s.client_id,
                                   clean_session=None if self._v5 else s.clean,
                                   protocol=mqtt.MQTTv5 if self._v5 else mqtt.MQTTv311,
                                   manual_ack=s.manual_ack, reconnect_on_failure=True)
        if s.username:
            self._client.username_pw_set(s.username, s.password)
        if s.tls is not None:
            self._client.tls_set_context(s.tls)
        self._client.reconnect_delay_set(1, 30)
        self._client.on_pre_connect = self._on_pre_connect
        self._client.on_connect = self._on_connect
        self._client.on_connect_fail = self._on_connect_fail
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe
        self._client.on_log = self._on_log
        self._MQTT_LOG_ERR = mqtt.MQTT_LOG_ERR
        self._connect_props = None
        if self._v5:
            self._connect_props = Properties(PacketTypes.CONNECT)
            self._connect_props.SessionExpiryInterval = 0 if s.clean else int(s.session_expiry_s)
            # at most this many QoS 1 messages in flight: fewer than the committed ones the source remembers, so a
            # copy of any message whose PUBACK was lost is still known when it comes again
            self._connect_props.ReceiveMaximum = RECEIVE_MAXIMUM

    def tls_failed(self, exc: BaseException) -> None:
        self._tls_error = f"TLS: {exc}"

    # what the source calls
    def open(self) -> None:
        if self._v5:
            self._client.connect_async(self._s.host, self._s.port, self._s.keepalive_s, clean_start=self._s.clean,
                                       properties=self._connect_props)
        else:
            self._client.connect_async(self._s.host, self._s.port, self._s.keepalive_s)
        self._client.loop_start()

    def close(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def subscribe(self, items: List[Tuple[str, int]], retain_handling: int = 0) -> None:
        if self._v5:
            topics: Any = [(f, self._SubscribeOptions(qos=q, retainHandling=retain_handling)) for f, q in items]
        else:
            topics = [(f, q) for f, q in items]
        with self._subs_lock:
            rc, mid = self._client.subscribe(topics)
            if rc == 0 and mid is not None:
                self._subs[mid] = list(items)
        if rc != 0:
            self._src._link_subscribed([(f, None) for f, _ in items])

    def unsubscribe(self, filters: List[str]) -> None:
        self._client.unsubscribe(list(filters))

    def ack(self, mid: int) -> None:
        self._client.ack(mid, 1)

    # paho's callbacks, on its network thread
    def _on_log(self, client: Any, userdata: Any, level: int, buf: str) -> None:
        if level == self._MQTT_LOG_ERR:
            self._log_error = buf

    def _on_pre_connect(self, client: Any, userdata: Any) -> None:
        self._refusal = None

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if getattr(reason_code, "is_failure", False):
            self._refusal = f"the broker refused the connection: {reason_code}"
            self._src._link_refused(self._refusal)
            return
        self._tls_error = self._log_error = None
        self._src._link_connected(bool(getattr(flags, "session_present", False)))

    def _on_connect_fail(self, client: Any, userdata: Any) -> None:
        why = self._tls_error or self._log_error or "no answer"
        self._tls_error = self._log_error = None
        self._src._link_refused(f"cannot connect to {self._s.host}:{self._s.port}: {why}")

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if self._refusal is not None:           # the broker closes the connection it refused: the refusal is why
            why, self._refusal, self._log_error = self._refusal, None, None
            self._src._link_lost(why)
            return
        why = str(reason_code)
        if self._log_error:
            why = f"{why} ({self._log_error})"
            self._log_error = None
        self._src._link_lost(why)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            topic = msg.topic
        except UnicodeDecodeError:
            topic = bytes(getattr(msg, "_topic", b"")).decode("utf-8", "replace")
        props, user, ctype = getattr(msg, "properties", None), {}, None
        if props is not None:
            user = user_properties(getattr(props, "UserProperty", None))
            ctype = getattr(props, "ContentType", None)
        self._src._link_message(Delivery(topic=topic, payload=bytes(msg.payload or b""), qos=int(msg.qos),
                                         mid=int(msg.mid), dup=bool(msg.dup), retain=bool(msg.retain),
                                         user_properties=user, content_type=ctype))

    def _on_subscribe(self, client: Any, userdata: Any, mid: int, reason_codes: Any, properties: Any) -> None:
        with self._subs_lock:
            items = self._subs.pop(mid, [])
        out: List[Tuple[str, Optional[int]]] = []
        for i, (flt, _q) in enumerate(items):
            rc = reason_codes[i] if i < len(reason_codes or []) else None
            value = getattr(rc, "value", rc)
            failed = rc is None or bool(getattr(rc, "is_failure", False)) or (isinstance(value, int) and value >= 0x80)
            out.append((flt, None if failed else int(value)))
        self._src._link_subscribed(out)


# ── the source ───────────────────────────────────────────────────────────────────────────────────────────────────────

class MqttSource(Source):
    """The messages an MQTT broker delivers on the topics this source subscribes to."""

    name = "mqtt"
    description = ("Messages an MQTT broker delivers (MQTT 3.1.1 or 5, TLS with client certificates, QoS 0 and 1), "
                   "acknowledged once in the outbox and resumed by the broker's persistent session")
    config_schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["host", "client_id", "topics"],
        "additionalProperties": False,
        "properties": {
            "host": {"type": "string", "minLength": 1, "description": "The broker's host name or address."},
            "port": {"type": "integer", "minimum": 1, "maximum": 65535,
                     "description": "Default 8883 with tls, 1883 without."},
            "protocol": {"enum": [*PROTOCOLS, 5], "default": "3.1.1",
                         "description": "3.1.1 or 5 (YAML's protocol: 5, a number, is taken as \"5\")."},
            "client_id": {"type": "string", "minLength": 1,
                          "description": "The name the broker keeps this source's session under: stable, and used "
                                         "by no other client."},
            "topics": {"type": "array", "minItems": 1, "items": {"anyOf": [
                {"type": "string", "minLength": 1},
                {"type": "object", "required": ["filter"], "additionalProperties": False,
                 "properties": {"filter": {"type": "string", "minLength": 1}, "qos": {"enum": [0, 1]}}}]},
                "description": "Topic filters (+ is one level, # the rest), each a string or {filter, qos}."},
            "qos": {"enum": [0, 1], "default": 1,
                    "description": "The QoS a filter given as a string is subscribed with. 2 is refused: see the "
                                   "source's documentation (a QoS 2 message is handed over before it is on disk)."},
            "username": {"type": "string", "minLength": 1},
            "password": {"type": "string", "x-secret": True},
            "tls": {"type": "object", "additionalProperties": False, "properties": {
                "ca_file": {"type": "string", "minLength": 1,
                            "description": "The CA certificates the broker's certificate is checked against "
                                           "(default: the system's)."},
                "cert_file": {"type": "string", "minLength": 1, "description": "The client certificate (PEM)."},
                "private_key": {"type": "string", "x-secret": True,
                                "description": "The client certificate's private key: a reference (file:/path or "
                                               "env:NAME holding the PEM)."},
                "key_password": {"type": "string", "x-secret": True,
                                 "description": "The private key's password, when it is encrypted."}}},
            "keepalive_s": {"type": "integer", "minimum": 5, "maximum": 65535, "default": 60},
            "session_expiry_s": {"type": "integer", "minimum": 1, "maximum": NEVER_EXPIRES, "default": NEVER_EXPIRES,
                                 "description": "MQTT 5: how long the broker keeps the session while the proxy is "
                                                "away (default: it does not end)."},
            "format": {"enum": list(FORMATS), "default": "json",
                       "description": "json (text when it is not JSON), text (base64 when it is not UTF-8) or bytes "
                                      "(base64)."},
            "id_field": {"type": "string", "minLength": 1,
                         "description": "A field of a JSON payload ($.a.b, or a top-level key) holding the "
                                        "publisher's own id for the message; the record id is topic#id."},
            "id_property": {"type": "string", "minLength": 1,
                            "description": "MQTT 5 only: a user property holding the publisher's own id (its first "
                                           "value, when the name is given more than once)."},
            "retained": {"enum": list(RETAINED), "default": "skip",
                         "description": "What to do with the retained messages a broker sends at subscription."},
            "finish_after_idle_s": {"type": "number", "minimum": 0, "default": 0,
                                    "description": "With a value, finish once subscribed and quiet this long "
                                                   "(tp-proxy run --once); 0 listens until stopped."},
        },
    }

    # The connection: (source, Settings) -> a link with open(), close(), subscribe(items, retain_handling),
    # unsubscribe(filters) and ack(mid), which calls the source's _link_* methods. Tests give a broker of their own.
    link_factory: ClassVar[Callable[..., Any]] = staticmethod(PahoLink)

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        c = self.config
        self._host = str(c.get("host") or "").strip()
        if not self._host:
            raise PluginError("mqtt: host names the broker")
        self._client_id = str(c.get("client_id") or "")
        if not self._client_id:
            raise PluginError("mqtt: client_id is required: the broker keeps this source's session under it, so it "
                              "must be stable and used by no other client")
        protocol = c.get("protocol") or "3.1.1"
        if protocol == 5 and not isinstance(protocol, bool):     # YAML reads `protocol: 5` as a number
            protocol = "5"
        self._protocol = str(protocol)
        if self._protocol not in PROTOCOLS:
            raise PluginError(f"mqtt: protocol is one of {', '.join(PROTOCOLS)}, not {self._protocol!r}")
        self._v5 = self._protocol == "5"
        default_qos = c.get("qos", 1)
        if default_qos == 2:
            raise PluginError(f"mqtt: {_QOS2}")
        if default_qos not in (0, 1):
            raise PluginError(f"mqtt: qos is 0 or 1, not {default_qos!r}")
        topics = c.get("topics")
        if not isinstance(topics, list) or not topics:
            raise PluginError("mqtt: topics lists at least one topic filter")
        self._filters: Dict[str, int] = {}
        for item in topics:
            if isinstance(item, Mapping):
                flt, q = item.get("filter"), item.get("qos", default_qos)
            else:
                flt, q = item, default_qos
            check_filter(flt)
            if q == 2:
                raise PluginError(f"mqtt: {flt}: {_QOS2}")
            if q not in (0, 1):
                raise PluginError(f"mqtt: {flt}: qos is 0 or 1, not {q!r}")
            if flt in self._filters:
                raise PluginError(f"mqtt: the topic filter {flt!r} is named twice")
            self._filters[flt] = int(q)
        tls = c.get("tls")
        if tls is not None and not isinstance(tls, Mapping):
            raise PluginError("mqtt: tls is a mapping (ca_file, cert_file, private_key, key_password)")
        self._tls: Optional[Dict[str, Any]] = dict(tls) if tls is not None else None
        if self._tls is not None:
            if self._tls.get("cert_file") and not self._tls.get("private_key"):
                raise PluginError("mqtt: tls.cert_file needs its tls.private_key (a reference)")
            if self._tls.get("private_key") and not self._tls.get("cert_file"):
                raise PluginError("mqtt: tls.private_key needs its tls.cert_file")
        self._port = int(c.get("port") or (8883 if self._tls is not None else 1883))
        if c.get("password") and not c.get("username"):
            raise PluginError("mqtt: a password needs its username (MQTT sends no password alone)")
        self._format = str(c.get("format") or "json")
        if self._format not in FORMATS:
            raise PluginError(f"mqtt: format is one of {', '.join(FORMATS)}, not {self._format!r}")
        self._retained = str(c.get("retained") or "skip")
        if self._retained not in RETAINED:
            raise PluginError(f"mqtt: retained is one of {', '.join(RETAINED)}, not {self._retained!r}")
        self._id_field = str(c.get("id_field") or "")
        self._id_property = str(c.get("id_property") or "")
        if self._id_property and not self._v5:
            raise PluginError("mqtt: id_property reads an MQTT 5 user property, and MQTT 3.1.1 has none: set protocol "
                              "\"5\", or name the publisher's id inside the payload with id_field")
        self._finish_after = float(c.get("finish_after_idle_s") or 0)
        self._keepalive = int(c.get("keepalive_s") or 60)
        self._expiry = int(c.get("session_expiry_s") or NEVER_EXPIRES)
        self._dry = bool(getattr(ctx, "dry_run", False))
        if self._dry:
            # a shared subscription's plain filter: as a member of the group a dry run would take some of the running
            # proxy's messages, while the plain filter gets a copy of each and takes none
            plain: Dict[str, int] = {}
            for flt, q in self._filters.items():
                p = plain_filter(flt)
                plain[p] = max(q, plain.get(p, 0))
            self._filters = plain
        # run time
        self._lock = threading.Lock()
        self._gen = 0                     # connections made (the link's thread counts them)
        self._epoch = 0                   # the broker's session the packet ids belong to (from the state, at start)
        self._epoch_written = 0
        self._epoch_lock: Optional[asyncio.Lock] = None
        self._connected = False
        self._live_gen = 0                # the connection the event loop has seen made, and whether it is up
        self._live = False
        self._inflight = 0                # QoS 1 messages of this connection not acknowledged yet
        self._inflight_warned = False
        self._session_present: Optional[bool] = None
        self._last_error: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._inbox: Optional[Deque[Tuple[Delivery, int, int]]] = None    # (delivery, connection, epoch)
        self._changed: Optional[asyncio.Event] = None
        self._ready: Optional[asyncio.Event] = None
        self._quiet_since = 0.0
        self._link: Any = None
        self._held: Optional[_Taken] = None
        self._next_place = 0
        self._by_mid: Dict[Tuple[int, int], Tuple[str, int]] = {}  # (epoch, packet id) -> (fingerprint, place)
        self._slots: Dict[int, _Entry] = {}                         # slot -> the entry, as stored
        self._subscribed: Dict[str, int] = {}
        self._passed_over = 0
        self._passed_over_topics: Set[str] = set()
        self._run = 0
        self._q0 = 0
        self._writes: List["asyncio.Future[Any]"] = []
        self._closing = False

    # ── what the core calls ────────────────────────────────────────────────────────────────────────────────────

    @property
    def status(self) -> Dict[str, Any]:
        """Where the connection is: connected, subscribed, whether the broker kept the session, how many times it has
        connected, the last refusal or loss with its reason (cleared by a connect that succeeds), the messages
        received and not taken yet, and the messages passed over (on a topic no filter names)."""
        return {"connected": self._connected, "subscribed": bool(self._ready and self._ready.is_set()),
                "session_present": self._session_present, "connects": self._gen, "last_error": self._last_error,
                "client_id": self._settings_client_id(), "queued": len(self._inbox) if self._inbox is not None else 0,
                "passed_over": self._passed_over}

    def _settings_client_id(self) -> str:
        return f"{self._client_id}-dry-run" if self._dry else self._client_id

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._inbox = collections.deque()
        self._changed = asyncio.Event()
        self._ready = asyncio.Event()
        self._epoch_lock = asyncio.Lock()
        client_id = self._settings_client_id()
        session = f"{self._host}:{self._port}/{client_id}"
        state = self.ctx.state
        try:
            epoch = int(await state.get(_EPOCH_KEY, 0) or 0)
        except (TypeError, ValueError):
            epoch = 0
        same = (await state.get(_SESSION_KEY)) == session
        if not same:
            # another broker or client id: another session, in which the remembered packet ids name nothing
            epoch += 1
            await state.set(_EPOCH_KEY, epoch)
            await state.set(_SESSION_KEY, session)
            await state.set(_SUBSCRIBED_KEY, {})
        entries = []
        for slot in range(RECENT):
            e = _entry(await state.get(f"{_RECENT_KEY}{slot}"))
            if e is not None:
                entries.append(e)
        entries.sort(key=lambda e: e[2])
        # every place counts, whichever session it was given in: a place is never given twice
        self._next_place = entries[-1][2] + 1 if entries else 0
        self._slots = {e[2] % RECENT: e for e in entries}
        # the packet ids of the session the broker had at the last connect; of two places under one id the later one
        # wins (the broker gave the id again, so it had the PUBACK of the earlier message)
        self._by_mid = {(ep, mid): (fp, place) for mid, fp, place, ep in entries if mid is not None and ep == epoch}
        with self._lock:
            self._epoch = epoch
        self._epoch_written = epoch
        self._subscribed = dict(await state.get(_SUBSCRIBED_KEY, {}) or {}) if same else {}
        self._run = int(await state.get(_RUN_KEY, 0) or 0) + 1
        await state.set(_RUN_KEY, self._run)
        password = self.ctx.secret(self.config["password"]) if self.config.get("password") else None
        tls_ctx = None
        if self._tls is not None:
            t = self._tls
            tls_ctx = tls_context(ca_file=t.get("ca_file"), cert_file=t.get("cert_file"),
                                  private_key=self.ctx.secret(t["private_key"]) if t.get("private_key") else None,
                                  key_password=self.ctx.secret(t["key_password"]) if t.get("key_password") else None,
                                  on_error=self._tls_failed)
        settings = Settings(host=self._host, port=self._port, protocol=self._protocol, client_id=client_id,
                            clean=self._dry, session_expiry_s=self._expiry, keepalive_s=self._keepalive,
                            username=self.config.get("username") or None, password=password, tls=tls_ctx,
                            manual_ack=not self._dry)
        self._link = self.link_factory(self, settings)
        self._link.open()

    async def stop(self) -> None:
        self._closing = True
        link, self._link = self._link, None
        with self._lock:
            self._connected = False
        if link is not None:
            if getattr(link, "blocking_close", True):
                await asyncio.get_running_loop().run_in_executor(None, link.close)
            else:
                link.close()
        if self._writes:
            await asyncio.gather(*self._writes, return_exceptions=True)
            self._writes = []

    async def records(self) -> AsyncIterator[Record]:
        held = self._held
        if held is not None:                        # handed over before and not committed: the core takes it again
            await self._reserve(held)
            yield held.record
        while True:
            item = await self._next()
            if item is None:
                return
            try:
                taken = await self._take(*item)
            except BaseException:
                assert self._inbox is not None
                self._inbox.appendleft(item)        # not taken: the next records() starts with it
                raise
            if taken is None:
                continue
            self._held = taken
            await self._reserve(taken)              # its place is on disk before the record leaves the source
            yield taken.record

    async def committed(self, record: Record) -> None:
        """The record is in the outbox: its PUBACK goes, which moves the broker's session on. The record handed back
        may be an equal one (the core copies a record to fill its source); one that is not the record in hand sends
        no PUBACK, and is named in the log."""
        t = self._held
        if t is None or not (record is t.record or (record.record_id == t.record.record_id
                                                    and (record.meta or {}).get("mid") == t.delivery.mid)):
            in_hand = t.record.record_id if t is not None else None
            self.ctx.logger.warning(f"mqtt: committed() for {record.record_id!r}, which is not the record in hand "
                                    f"({in_hand!r}): no PUBACK sent for it")
            return
        await self._reserve(t)                      # written before it was handed over: this only makes sure
        self._held = None
        self._ack(t.delivery, t.gen)

    async def rewind(self, point: str) -> None:
        raise PluginError("mqtt: a broker keeps no history beyond a topic's retained message, so the mqtt source "
                          "cannot read again from a point")

    # ── records ────────────────────────────────────────────────────────────────────────────────────────────────

    async def _next(self) -> Optional[Tuple[Delivery, int, int]]:
        assert self._inbox is not None and self._changed is not None and self._ready is not None
        loop = asyncio.get_running_loop()
        wait = min(0.25, self._finish_after) if self._finish_after > 0 else None
        # the event loop runs once before a message is taken, so what the link reported (a lost connection, a new
        # one) is seen first: a core that never waits otherwise (its writes are synchronous, and from Python 3.12
        # asyncio.wait_for runs the step in the same task) would take every message of a lost connection first
        await asyncio.sleep(0)
        while True:
            if self._inbox and self._takeable(self._inbox[0]):
                self._quiet_since = loop.time()
                return self._inbox.popleft()
            # the quiet counts only while subscribed: a broker that cannot be reached is not one with nothing to send
            if self._finish_after > 0 and self._ready.is_set() and loop.time() - self._quiet_since >= self._finish_after:
                return None
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), wait)
            except asyncio.TimeoutError:
                pass

    def _takeable(self, item: Tuple[Delivery, int, int]) -> bool:
        d, gen, _ = item
        # a QoS 1 message whose connection is lost waits for the next connection's answer: when the broker kept the
        # session it sends the message again (and this copy is dropped), when it did not, this is the only copy
        return d.qos != 1 or gen != self._live_gen or self._live

    def _own_id(self, d: Delivery, data: Any) -> Optional[str]:
        if self._id_property:
            v = (d.user_properties or {}).get(self._id_property)
            if isinstance(v, list):                 # a name given more than once: its first value
                v = v[0] if v else None
            if v not in (None, ""):
                return str(v)
        if self._id_field and isinstance(data, (Mapping, list)):
            v = lookup(data, self._id_field) if self._id_field.startswith("$") else (
                data.get(self._id_field, _MISSING) if isinstance(data, Mapping) else _MISSING)
            if v is not _MISSING and v is not None and not (isinstance(v, str) and not v.strip()) \
                    and not isinstance(v, (Mapping, list)):
                return str(v)
        return None

    async def _take(self, d: Delivery, gen: int, epoch: int) -> Optional[_Taken]:
        if epoch > self._epoch_written:
            await self._write_epoch()             # the broker's new session is on disk before any of its messages
        fp = _fingerprint(d.topic, d.payload)
        known: Optional[Tuple[str, int]] = None
        if d.qos == 1:
            known = self._by_mid.get((epoch, d.mid))
            if known is not None and not (d.dup and known[0] == fp):
                # the broker gave this packet id to another message, so it had the PUBACK of the one remembered under
                # it: that one cannot come again, and the id names it no longer
                await self._forget(epoch, d.mid, known)
                known = None
        if not any(topic_matches(f, d.topic) for f in self._filters):
            self._note_passed_over(d.topic)
            self._ack(d, gen)                     # every record before it is committed: the PUBACKs stay in order
            return None
        if d.retain and self._retained == "skip":
            self._ack(d, gen)
            return None
        data, encoding = _decode(d.payload, self._format)
        place: Optional[int] = None
        own = self._own_id(d, data)
        if own is not None:
            rid, kind = f"{d.topic}#{own}", "own"
        elif d.retain:
            rid, kind = f"{d.topic}#retained-{fp}", "retained"
        elif d.qos == 0:
            rid, kind = f"q0-{self._run}.{self._q0}", "q0"
            self._q0 += 1
        else:
            if known is not None:
                place = known[1]                  # sent again: the message in hand at a stop, or a lost PUBACK's
            else:
                place = self._next_place
                self._next_place += 1
            rid, kind = f"seq-{place}", "seq"
        payload: Dict[str, Any] = {"topic": d.topic, "levels": d.topic.split("/"), "data": data, "encoding": encoding,
                                   "qos": d.qos, "retain": d.retain}
        if self._v5 and (d.user_properties or d.content_type):
            props: Dict[str, Any] = {}
            if d.user_properties:
                props["user"] = dict(d.user_properties)
            if d.content_type:
                props["content_type"] = d.content_type
            payload["properties"] = props
        rec = Record(record_id=rid, payload=payload, meta={"via": "mqtt", "mid": d.mid, "dup": d.dup})
        return _Taken(rec, d, gen, epoch, kind, place, fp, written=kind != "seq")

    async def _reserve(self, t: _Taken) -> None:
        """Write the place a QoS 1 message was given, with its packet id and the broker's session, before its record
        leaves the source: a copy the broker sends again is known by it after a restart too, and the place is never
        given to another message (the record handed over may be in the outbox already)."""
        if t.written or t.place is None:
            return
        if t.epoch > self._epoch_written:
            await self._write_epoch()
        entry: _Entry = (t.delivery.mid, t.fp, t.place, t.epoch)
        slot = t.place % RECENT
        old = self._slots.get(slot)
        if old != entry:
            await self.ctx.state.set(f"{_RECENT_KEY}{slot}", list(entry))
            if old is not None and old[2] != t.place and old[0] is not None \
                    and self._by_mid.get((old[3], old[0])) == (old[1], old[2]):
                del self._by_mid[(old[3], old[0])]      # out of the window, as it is out of the state
            self._slots[slot] = entry
        self._by_mid[(t.epoch, t.delivery.mid)] = (t.fp, t.place)
        self._next_place = max(self._next_place, t.place + 1)
        t.written = True

    async def _forget(self, epoch: int, mid: int, known: Tuple[str, int]) -> None:
        """Packet id `mid` no longer names the message remembered under it: cleared on disk (its place kept) before
        the message the broker gave it to is handed over, so a restart does not take that one for the other."""
        _fp, place = known
        slot = place % RECENT
        entry = self._slots.get(slot)
        if entry is not None and entry[0] == mid and entry[2] == place and entry[3] == epoch:
            cleared: _Entry = (None, entry[1], place, epoch)
            await self.ctx.state.set(f"{_RECENT_KEY}{slot}", list(cleared))
            self._slots[slot] = cleared
        self._by_mid.pop((epoch, mid), None)

    async def _write_epoch(self) -> None:
        """Write which session of the broker the packet ids belong to (the newest the link has connected to)."""
        assert self._epoch_lock is not None
        async with self._epoch_lock:
            with self._lock:
                epoch = self._epoch
            if epoch > self._epoch_written:
                await self.ctx.state.set(_EPOCH_KEY, epoch)
                self._epoch_written = epoch

    def _note_passed_over(self, topic: str) -> None:
        self._passed_over += 1
        if topic in self._passed_over_topics or len(self._passed_over_topics) >= PASSED_OVER_NAMED:
            return
        self._passed_over_topics.add(topic)
        self.ctx.logger.warning(f"mqtt: a message on {topic!r}, which no topic filter of this source names (a "
                                f"subscription the broker keeps for this client id, from an earlier spec or another "
                                f"client): acknowledged and passed over")

    def _ack(self, d: Delivery, gen: int) -> None:
        if d.qos != 1 or self._dry:
            return
        with self._lock:
            # a PUBACK goes only on the connection its message came in on: after a reconnect the broker sends the
            # message again, and that copy is acknowledged instead
            if self._connected and gen == self._gen and self._link is not None:
                self._link.ack(d.mid)
                self._inflight = max(0, self._inflight - 1)

    # ── what the link calls (from its own thread) ──────────────────────────────────────────────────────────────

    def _soon(self, fn: Callable[..., Any], *args: Any) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(fn, *args)
            except RuntimeError:                    # the loop closed in between
                pass

    def _tls_failed(self, exc: BaseException) -> None:
        link = self._link
        if link is not None and hasattr(link, "tls_failed"):
            link.tls_failed(exc)
        self._last_error = f"TLS: {exc}"

    def _link_connected(self, session_present: bool) -> None:
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._connected = True
            first = gen == 1
            if not session_present:
                self._epoch += 1          # the broker started the session anew: its packet ids name other messages
            self._inflight, self._inflight_warned = 0, False
        self._soon(self._on_connected, gen, session_present)    # before any message of this connection
        self._session_present = session_present
        self._last_error = None
        if session_present:
            want = {f: q for f, q in self._filters.items() if self._subscribed.get(f) != q}
            drop = [f for f in self._subscribed if f not in self._filters]
        else:
            if (self._subscribed or not first) and not self._dry:      # a dry run's session is clean by design
                self.ctx.logger.warning(f"mqtt: the broker did not keep the session {self._settings_client_id()!r}: "
                                        f"what it held for this source is gone; subscribing again")
            want, drop = dict(self._filters), []
            self._subscribed = {}
        self.ctx.logger.info(f"mqtt: connected to {self._host}:{self._port} as {self._settings_client_id()!r} "
                             f"(session {'kept' if session_present else 'new'})")
        link = self._link
        if drop and link is not None:
            for f in drop:
                self._subscribed.pop(f, None)
            link.unsubscribe(sorted(drop))
            self._persist_subscribed()
        if want and link is not None:
            # MQTT 5: no retained message at all when they are skipped; once, for a subscription that is new, when
            # they are taken
            link.subscribe(sorted(want.items()), 2 if self._retained == "skip" else 1)
        else:
            self._soon(self._set_ready)

    def _link_subscribed(self, results: List[Tuple[str, Optional[int]]]) -> None:
        for flt, granted in results:
            if granted is None:
                self.ctx.logger.error(f"mqtt: the broker refused the subscription to {flt!r}")
                continue
            want = self._filters.get(flt, granted)
            if granted < want:
                self.ctx.logger.warning(f"mqtt: the broker granted QoS {granted} for {flt!r}: its messages arrive at "
                                        f"most once")
            self._subscribed[flt] = want
        self._persist_subscribed()
        self._soon(self._set_ready)

    def _link_lost(self, why: str) -> None:
        if self._closing:
            return
        with self._lock:
            was = self._connected
            self._connected = False
            gen = self._gen
        if was:
            self._last_error = f"the connection was lost: {why}"
            self.ctx.logger.warning(f"mqtt: {self._last_error}; connecting again")
        elif why:
            self._last_error = why
        self._soon(self._on_lost, gen)

    def _link_refused(self, why: str) -> None:
        self._last_error = why
        self.ctx.logger.warning(f"mqtt: {why}")

    def _link_message(self, d: Delivery) -> None:
        warn = False
        with self._lock:
            gen, epoch = self._gen, self._epoch
            if d.qos == 1 and not self._dry:          # a dry run's messages are acknowledged by paho on receipt
                self._inflight += 1
                if self._inflight > RECENT and not self._inflight_warned:
                    self._inflight_warned = warn = True
        if warn:
            self.ctx.logger.warning(
                f"mqtt: the broker has more than {RECENT} QoS 1 messages in flight to this source on one connection, "
                f"and a copy it sends again is known among the last {RECENT} places given: set its limit for "
                f"messages in flight to a client (mosquitto: max_inflight_messages) to {RECENT} or less, or connect "
                f"with protocol \"5\" (Receive Maximum {RECEIVE_MAXIMUM})")
        self._soon(self._enqueue, (d, gen, epoch))

    # ── on the event loop ──────────────────────────────────────────────────────────────────────────────────────

    def _enqueue(self, item: Tuple[Delivery, int, int]) -> None:
        if self._inbox is not None:
            self._inbox.append(item)
        if self._changed is not None:
            self._changed.set()

    def _on_connected(self, gen: int, session_present: bool) -> None:
        self._live_gen, self._live = gen, True
        if session_present and self._inbox:
            # the broker kept the session: it sends again every QoS 1 message it has not had the PUBACK of, under its
            # packet id and in order, so what the lost connection delivered and the source had not taken is dropped
            # (taken as well, each would be committed with no PUBACK, and its copy known again only among the last
            # RECENT places)
            kept = collections.deque(it for it in self._inbox if not (it[0].qos == 1 and it[1] < gen))
            if len(kept) != len(self._inbox):
                self.ctx.logger.info(f"mqtt: {len(self._inbox) - len(kept)} QoS 1 message(s) the lost connection "
                                     f"delivered are taken from the broker's copies (it kept the session)")
                self._inbox = kept
        with self._lock:
            newer = self._epoch > self._epoch_written
        if newer:
            self._track(self._write_epoch())
        if self._changed is not None:
            self._changed.set()

    def _on_lost(self, gen: int) -> None:
        if gen == self._live_gen:
            self._live = False
        if self._ready is not None:
            self._ready.clear()
        if self._changed is not None:
            self._changed.set()

    def _track(self, coro: Any) -> None:
        """Run a state write beside the records, gathered at stop; a failure is named in the log."""
        self._writes = [w for w in self._writes if not w.done()]
        fut = asyncio.ensure_future(coro)
        fut.add_done_callback(self._write_done)
        self._writes.append(fut)

    def _write_done(self, fut: "asyncio.Future[Any]") -> None:
        if not fut.cancelled() and fut.exception() is not None:
            self.ctx.logger.warning(f"mqtt: a state write failed: {type(fut.exception()).__name__}: {fut.exception()}")

    def _set_ready(self) -> None:
        if self._ready is not None and not self._ready.is_set():
            self._ready.set()
            if self._loop is not None:
                self._quiet_since = self._loop.time()

    def _persist_subscribed(self) -> None:
        snapshot = dict(self._subscribed)
        self._soon(self._write_subscribed, snapshot)

    def _write_subscribed(self, snapshot: Dict[str, int]) -> None:
        if self._closing:
            return
        self._track(self.ctx.state.set(_SUBSCRIBED_KEY, snapshot))
