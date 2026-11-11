"""A registry and plugins to drive TheProtocol Proxy's core against, with no network.

FakeRegistry answers what a proxy's agent calls: the agent token (form-encoded client credentials), the attestation
route (an Idempotency-Key answered with its first answer, a second copy of the same data refused 409 as the TEG does),
the card and the bond status. It counts every call and every EFFECT (an attestation it kept), so a test can tell "sent
twice" from "kept twice". `mode` switches it: "ok", "down" (503), "refuse" (403), "slow" (429 with Retry-After);
`lose_answers` keeps the next N attestations and loses their answers (the proxy sees a timeout).
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from theprotocol.proxy.plugins import Action, Outcome, Record, Sink, Source

DID = "did:theprotocol:5b1e0c7a-proxy-test"
CLIENT_ID = "agent_client_proxytest"
CLIENT_SECRET = "s3cr3t-proxy-client-secret-value"


def jwt(claims: Dict[str, Any]) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.c2ln"


class FakeRegistry:
    def __init__(self, *, did: str = DID, client_id: str = CLIENT_ID, client_secret: str = CLIENT_SECRET,
                 token_ttl: float = 3600.0, clock=time.time):
        self.did, self.client_id, self.client_secret = did, client_id, client_secret
        self.token_ttl, self.clock = token_ttl, clock
        self.mode = "ok"
        self.lose_answers = 0
        self.reject_tokens: set = set()
        self.tokens: Dict[str, float] = {}
        self.calls: List[Dict[str, Any]] = []
        self.effects: List[Dict[str, Any]] = []
        self.by_key: Dict[str, Dict[str, Any]] = {}
        self.hashes: set = set()
        self.bonded = False
        self.enrollments: List[str] = []
        self.svid_ttl = 3600
        self._pems: Optional[Dict[str, str]] = None

    def svid(self) -> Dict[str, Any]:
        """An inline X509-SVID as enable-mtls returns it: a real self-signed certificate and key, made at run time
        (so no private key is written in the repository), valid for svid_ttl seconds."""
        from datetime import datetime, timedelta, timezone
        if self._pems is None:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.x509.oid import NameOID
            key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "proxy-test")])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                    .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
            cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
            key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()).decode()
            self._pems = {"svid_pem": cert_pem, "key_pem": key_pem, "bundle_pem": cert_pem}
        exp = datetime.now(timezone.utc) + timedelta(seconds=self.svid_ttl)
        return {"spiffe_id": "spiffe://test/agent/proxy", **self._pems, "ttl_seconds": self.svid_ttl,
                "expires_at": exp.isoformat()}

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self, path: str = "/api/v1/teg/attestations/submit") -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["path"] == path and c["method"] == "POST"]

    def _authorized(self, request: httpx.Request) -> bool:
        auth = request.headers.get("authorization", "")
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        return tok in self.tokens and tok not in self.reject_tokens and self.clock() < self.tokens[tok]

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append({"method": request.method, "path": path, "key": request.headers.get("idempotency-key"),
                           "auth": request.headers.get("authorization", "")})
        if path == "/api/v1/auth/agent/token":
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            if form.get("username") != self.client_id or form.get("password") != self.client_secret:
                return httpx.Response(401, json={"detail": "Incorrect client_id or client_secret"})
            exp = self.clock() + self.token_ttl
            tok = jwt({"sub": self.did, "exp": exp, "n": len(self.tokens)})
            self.tokens[tok] = exp
            return httpx.Response(200, json={"access_token": tok, "token_type": "bearer"})
        if path.startswith("/api/v1/agent-cards/"):
            return httpx.Response(200, json={"is_active": True, "card_data": {"name": "Proxy Test"}})
        if not self._authorized(request):
            return httpx.Response(401, json={"detail": "Could not validate credentials"})
        if path == "/api/v1/agent/enable-mtls":
            self.enrollments.append(request.headers.get("authorization", ""))
            return httpx.Response(200, json={"status": "enrolled", "delivery": "inline", "svid": self.svid()})
        if path == "/api/v1/agents/reputation-bond/status":
            if not self.bonded:
                return httpx.Response(404, json={"detail": {"message": "No reputation bond found for this agent",
                                                            "required_amount": "250", "currency": "ECU"}})
            return httpx.Response(200, json={"status": "matured", "amount": "250", "currency": "ECU"})
        if path == "/api/v1/teg/attestations/submit":
            key = request.headers.get("idempotency-key")
            if key and key in self.by_key:
                return httpx.Response(200, json=self.by_key[key], headers={"Idempotent-Replayed": "true"})
            if self.mode == "down":
                return httpx.Response(503, json={"detail": "TEG service unavailable"})
            if self.mode == "slow":
                return httpx.Response(429, json={"detail": "Too many requests"}, headers={"Retry-After": "1"})
            if self.mode == "refuse":
                return httpx.Response(403, json={"detail": "Agent lacks permission: reputation.signal"})
            body = json.loads(request.content)
            h = hashlib.sha256(json.dumps(body["attestation_data"], sort_keys=True).encode()).hexdigest()
            if h in self.hashes:
                return httpx.Response(409, json={"detail": "The TEG refused the request (HTTP 409): "
                                                           "Attestation already submitted"})
            self.hashes.add(h)
            att = {"attestation_id": f"att-{len(self.effects) + 1}", "status": "pending",
                   "attestation_type": body["attestation_type"], "target_agent_did": body["target_agent_did"]}
            self.effects.append(body)
            if key:
                self.by_key[key] = att
            if self.lose_answers > 0:
                self.lose_answers -= 1
                raise httpx.ReadTimeout("the answer was lost", request=request)
            return httpx.Response(200, json=att)
        return httpx.Response(404, json={"detail": f"no route {path}"})


class ListSource(Source):
    """Yields config.items as records; its cursor (state "cursor") is the last committed id. With `replay_all` it
    ignores the cursor and yields everything again on every start (a source whose cursor did not move)."""
    name = "list_source"
    config_schema = {"type": "object", "properties": {"items": {"type": "array"}, "replay_all": {"type": "boolean"},
                                                       "id_field": {"type": "string"}}}

    async def records(self):
        cursor = None if self.config.get("replay_all") else await self.ctx.state.get("cursor")
        seen = cursor is None
        for item in self.config.get("items", []):
            rid = str(item[self.config.get("id_field") or "id"])
            if not seen:
                seen = rid == cursor
                continue
            yield Record(record_id=rid, payload=item)

    async def committed(self, record):
        await self.ctx.state.set("cursor", record.record_id)

    async def rewind(self, point):
        await self.ctx.state.set("cursor", None if point in ("", "start") else point)


class KeylessAction(Action):
    """Breaks the rule the core enforces: a write without the record's key."""
    name = "keyless"

    async def perform(self, mapped, *, key, dry_run):
        if dry_run:
            return Outcome.dry()
        await self.ctx.call("POST", "/api/v1/teg/attestations/submit", json={"attestation_data": dict(mapped)})
        return Outcome.done()


class ListSink(Sink):
    """Delivers into a class-level list, once per key (as a file sink names its file by the key)."""
    name = "list_sink"
    delivered: List[Any] = []

    async def deliver(self, event, *, key, dry_run):
        if dry_run:
            return Outcome.dry("would deliver", event_id=event.event_id)
        if key not in [k for k, _ in type(self).delivered]:
            type(self).delivered.append((key, event))
        return Outcome.done(reference=key)


def spec_doc(tmp, *, items: Optional[list] = None, mappings: Optional[list] = None, actions: Optional[dict] = None,
             sources: Optional[dict] = None, sinks: Optional[dict] = None, **extra) -> Dict[str, Any]:
    """A spec for the fakes: one list source, the attestation action, the credentials in a dotenv file."""
    secret_file = tmp / ".env.secret"
    if not secret_file.exists():
        secret_file.write_text(f"CLIENT_ID={CLIENT_ID}\nCLIENT_SECRET={CLIENT_SECRET}\n")
    doc = {
        "version": 1, "name": "proxy-test", "registry": "https://registry.test",
        "identity": {"agent_did": DID, "client_id": "file:.env.secret#CLIENT_ID",
                     "client_secret": "file:.env.secret#CLIENT_SECRET"},
        "state": str(tmp / "state.db"),
        "sources": sources if sources is not None else {"feed": {"type": "list_source",
                                                                 "config": {"items": items or []}}},
        "actions": actions if actions is not None else {"attest": {"type": "attestation",
                                                                   "config": {"attestation_type": "test.reading"}}},
        "sinks": sinks if sinks is not None else {},
        "mappings": mappings or [{"name": "reading", "version": 1, "from": "feed", "to": "attest",
                                  "fields": {"value": "$.payload.v", "id": "$.record_id"}}],
        "retry": {"first_s": 0.01, "max_s": 0.05, "attempts": 4},
        "breaker": {"refusals": 3, "failures": 3, "cooldown_s": 0.05},
        "service": {"enabled": False},
    }
    doc.update(extra)
    return doc
