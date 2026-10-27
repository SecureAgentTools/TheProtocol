"""§SOVKIT T4 (2026-09-14): who may READ the Directory.

The index aggregates every frame's cards and registries render what it returns (`DISCOVERY_VIA_DIRECTORY`), so a
read anyone can make is a place to inject a lie into Discovery. Until today the door was the mTLS sidecar alone
(`nginx-directory.conf`, `ssl_verify_client on`) with a plain `127.0.0.1:8600` publish beside it, and ANY valid SVID
from a trusted domain could read, the operators that share their parent's trust domain included.

This module is the app half of the door. A request reaches anything but `/health` only when ALL of these hold:

1. it came through our TLS terminator: `X-Directory-Proxy-Auth` equals `DIRECTORY_PROXY_TRUST_SECRET`, compared in
   constant time. The sidecar sets that header and overwrites whatever a caller sent, so the `X-SSL-*` headers below
   are believed only on a request that carries it. A secret shorter than 32 characters, or with characters outside
   `[A-Za-z0-9._~-]` (the set the sidecar's entrypoint renders safely), counts as UNSET;
2. the terminator verified the client certificate: `X-SSL-Client-Verify` is exactly `SUCCESS`;
3. the certificate's single SPIFFE URI SAN is named in `DIRECTORY_READERS` (full SPIFFE IDs, comma-separated).

An unset secret or an empty allowlist refuses every read, and `announce()` says so at import, loudly. The rule is
default-deny by PATH: only `/health` (liveness) is open, so a route added later (or FastAPI's own `/docs` and
`/openapi.json`) is gated without anyone remembering to gate it. It is an ASGI middleware rather than a route
dependency because strawberry serves GraphQL over a WEBSOCKET at the same path, and graphql-transport-ws runs
queries there too: a dependency on the HTTP routes would leave that door open.

No FastAPI and no database here, so the rule is testable on its own (`tests/test_reader_gate.py`).
"""
from __future__ import annotations

import hmac
import logging
import os
import re
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import unquote

logger = logging.getLogger("directory.reader_gate")

MIN_SECRET_LEN = 32
_SECRET_RE = re.compile(r"[A-Za-z0-9._~-]{%d,}" % MIN_SECRET_LEN)
MARKER_HEADER = "x-directory-proxy-auth"
VERIFY_HEADER = "x-ssl-client-verify"
CERT_HEADER = "x-ssl-client-cert"
GATE_HEADERS = (MARKER_HEADER, VERIFY_HEADER, CERT_HEADER)
OPEN_PATHS = frozenset({"/health"})
REFUSAL_BODY = b'{"detail":"This caller is not authorised to read the Directory"}'


def secret_usable(secret: Optional[str]) -> bool:
    """A secret the sidecar can carry and nobody can guess: 32+ characters from a set nginx renders unquoted."""
    return isinstance(secret, str) and _SECRET_RE.fullmatch(secret) is not None


def parse_readers(raw: Optional[str]) -> frozenset:
    return frozenset(part.strip() for part in (raw or "").split(",") if part.strip())


READERS_FILE = os.environ.get("DIRECTORY_READERS_FILE", "/data/readers.json")


class _ReadersCarrier:
    """The allowlist as a FILE that can change while the index runs, with the env as the fallback.

    §OPDIST (2026-09-16). `ReaderGate.__init__` bound this set ONCE at construction, so admitting a new reader —
    a cloud operator provisioned an hour after the frame — meant RECREATING the directory container. Built at
    import, no carrier, no reload: the shape FRAMES had before §FRAMEKIT P3.1 and VENUES had until this afternoon,
    in a third service. The provisioner appends the operator's SPIFFE ID to the file and the next request sees it.

    ⚠ NO RELOAD ENDPOINT, deliberately, and this is the one place the venues design must NOT be copied: an
    endpoint here means a new entry in OPEN_PATHS, which is an unauthenticated door punched into the middleware
    whose entire job is default-deny. An mtime stat costs microseconds and adds no door at all.

    TWO REFUSALS THAT KEEP A BAD WRITE FROM LOCKING EVERYONE OUT, because this file decides who may read at all:
      · a file that does not PARSE is not applied — the set in force stays in force;
      · a file that parses to an EMPTY list is not applied either. An empty allowlist refuses every request, so a
        truncated or half-written file would take the whole index down, and "a gate that removes everything is
        indistinguishable from an outage". Locking the index down deliberately means deleting the file AND
        emptying the env, which nobody does by accident.
    The complaint is logged once per mtime rather than once per request: visible without drowning the log.
    """

    def __init__(self, path: str = READERS_FILE, env_value: Optional[str] = None):
        self.path = path
        self._env = parse_readers(os.environ.get("DIRECTORY_READERS", "") if env_value is None else env_value)
        self._mtime: Optional[float] = None
        self._from_file: Optional[frozenset] = None
        self._complained_at: Optional[float] = None

    def _read_file(self) -> Optional[frozenset]:
        try:
            with open(self.path) as fh:
                import json as _json
                data = _json.load(fh)
        except FileNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001
            self._complain(f"{self.path} is unreadable ({type(exc).__name__}); the set in force is unchanged")
            return self._from_file
        entries = data.get("readers") if isinstance(data, dict) else data
        if not isinstance(entries, (list, tuple)) or not [e for e in entries if isinstance(e, str) and e.strip()]:
            self._complain(f"{self.path} names no readers; NOT applied, because an empty allowlist refuses every "
                           f"request and a truncated file must not take the index down")
            return self._from_file
        return frozenset(e.strip() for e in entries if isinstance(e, str) and e.strip())

    def _complain(self, message: str) -> None:
        stamp = self._mtime
        if self._complained_at != stamp:
            logger.error("[reader-gate] %s", message)
            self._complained_at = stamp

    def current(self) -> frozenset:
        """The set in force now: the file when it parses to a non-empty list, else the env."""
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            mtime = None
        if mtime != self._mtime:
            self._mtime = mtime
            self._from_file = self._read_file() if mtime is not None else None
        return self._from_file if self._from_file else self._env


def spiffe_ids_from_escaped_pem(escaped: str) -> List[str]:
    """The spiffe:// URI SANs of the certificate nginx forwarded as `$ssl_client_escaped_cert` (URL-escaped PEM)."""
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID

    cert = x509.load_pem_x509_certificate(unquote(escaped).encode("ascii"))
    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    except x509.ExtensionNotFound:
        return []
    return [uri for uri in san.get_values_for_type(x509.UniformResourceIdentifier) if uri.startswith("spiffe://")]


def decide(headers: Mapping[str, str], *, secret: Optional[str], readers: frozenset) -> Tuple[bool, str, Optional[str]]:
    """(allowed, reason, spiffe_id) for one request. `headers` maps lower-case names to single values.
    The reason never echoes a header value; the SPIFFE ID is returned so a refusal can name WHO was refused."""
    if not secret_usable(secret):
        return False, "DIRECTORY_PROXY_TRUST_SECRET is unset or malformed", None
    if not readers:
        return False, "DIRECTORY_READERS is empty", None
    marker = headers.get(MARKER_HEADER) or ""
    if not marker:
        return False, "no proxy trust marker (the request did not come through the mTLS sidecar)", None
    if not hmac.compare_digest(marker.encode("latin-1", "replace"), secret.encode("ascii")):
        return False, "the proxy trust marker does not match", None
    if headers.get(VERIFY_HEADER) != "SUCCESS":
        return False, "the sidecar did not report a verified client certificate", None
    escaped = headers.get(CERT_HEADER) or ""
    if not escaped:
        return False, "no client certificate was forwarded", None
    try:
        ids = spiffe_ids_from_escaped_pem(escaped)
    except Exception as exc:  # a malformed certificate is a refusal, never a crash
        return False, f"the forwarded certificate could not be parsed ({type(exc).__name__})", None
    if len(ids) != 1:
        return False, f"the certificate carries {len(ids)} SPIFFE URI SANs, not exactly one", None
    if ids[0] not in readers:
        return False, "the SPIFFE ID is not in DIRECTORY_READERS", ids[0]
    return True, "reader allowed", ids[0]


def gate_headers(scope: Mapping) -> Tuple[Dict[str, str], List[str]]:
    """The three gate headers of an ASGI scope, and the names that arrived more than once."""
    seen: Dict[str, str] = {}
    repeated: List[str] = []
    for raw_name, raw_value in scope.get("headers") or []:
        name = raw_name.decode("latin-1").lower()
        if name in GATE_HEADERS:
            if name in seen:
                repeated.append(name)
            seen[name] = raw_value.decode("latin-1")
    return seen, repeated


def announce(secret: Optional[str] = None, readers: Optional[Iterable[str]] = None) -> Tuple[bool, frozenset]:
    """Say at boot what the gate will do. Returns (secret usable, readers). Never prints the secret."""
    secret = os.environ.get("DIRECTORY_PROXY_TRUST_SECRET", "") if secret is None else secret
    readers = parse_readers(os.environ.get("DIRECTORY_READERS", "")) if readers is None else frozenset(readers)
    usable = secret_usable(secret)
    if not usable:
        logger.error("[reader-gate] DIRECTORY_PROXY_TRUST_SECRET is unset or malformed (32+ characters from "
                     "[A-Za-z0-9._~-]): EVERY request except %s will be refused", sorted(OPEN_PATHS))
    if not readers:
        logger.error("[reader-gate] DIRECTORY_READERS is empty: EVERY request except %s will be refused",
                     sorted(OPEN_PATHS))
    if usable and readers:
        logger.info("[reader-gate] reads need the sidecar's marker, a verified client certificate and one of "
                    "%d allowlisted SPIFFE IDs: %s", len(readers), sorted(readers))
    return usable, readers


class ReaderGate:
    """ASGI middleware: default-deny for everything but OPEN_PATHS, for HTTP and WebSocket alike."""

    def __init__(self, app, secret: Optional[str] = None, readers: Optional[Iterable[str]] = None,
                 open_paths: Iterable[str] = OPEN_PATHS):
        self.app = app
        self.secret = os.environ.get("DIRECTORY_PROXY_TRUST_SECRET", "") if secret is None else secret
        # An explicit `readers=` still pins the set (every test does that); otherwise the carrier decides per
        # request, so an operator provisioned while this process runs is admitted without a recreate.
        self._carrier = None if readers is not None else _ReadersCarrier()
        self.readers = frozenset(readers) if readers is not None else self._carrier.current()
        self.open_paths = frozenset(open_paths)

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket") or scope.get("path") in self.open_paths:
            await self.app(scope, receive, send)
            return
        headers, repeated = gate_headers(scope)
        if repeated:
            allowed, reason, sid = False, "a gate header arrived more than once", None
        else:
            readers = self._carrier.current() if self._carrier is not None else self.readers
            allowed, reason, sid = decide(headers, secret=self.secret, readers=readers)
        if allowed:
            await self.app(scope, receive, send)
            return
        logger.warning("[reader-gate] REFUSED %s %s: %s%s", kind, scope.get("path"), reason,
                       f" ({sid})" if sid else "")
        if kind == "websocket":
            # a close before accept is a 403 at the handshake
            await send({"type": "websocket.close", "code": 1008})
            return
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(REFUSAL_BODY)).encode())]})
        await send({"type": "http.response.body", "body": REFUSAL_BODY})
