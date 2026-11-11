"""The evidence export: TheProtocol's events, delivered as files anyone can check offline (tp-proxy verify).

    sinks:
      evidence:
        type: evidence
        config:
          dir: /data/evidence                        # one JSONL file per UTC day, and manifest.json
          signing_key: file:/run/secrets/evidence.pem  # Ed25519 (tp-proxy keygen writes one); a reference only
          registry_card: true                        # embed the registry's signed card and its keys
          mirror: {type: sftp, host: ..., path: /in/evidence, username: ..., private_key: file:...,
                   known_hosts: /data/known_hosts}   # or {type: s3, bucket: ..., prefix: ..., access_key: env:...}

Each event becomes one line: {"v": 1, "seq", "key", "event": {...}, "received_at", "prev", "hash"}, where `hash` is
the SHA-256 of the line's canonical JSON without it and `prev` is the hash of the line before, across the files, so a
line removed, changed or put out of order breaks the chain. The event keeps what makes it verifiable: its ledger
references and, for an event the registry's webhook delivered, the signed body and its HMAC signature. manifest.json
names every file (its lines, its SHA-256, its last hash), the chain's head, the proxy's public key, and the registry's
signed card with its keys when asked for; the proxy signs it (Ed25519). `tp-proxy verify DIR` checks all of it without
a network: the signature, every file, every line, the chain, the card's signature as of the time it was fetched, and
with --webhook-secret every delivery's HMAC. A delivery repeated with the same key appends nothing.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .plugins import Event, Outcome, PluginError, Retry, Sink

FORMAT = "theprotocol-proxy-evidence/1"
MANIFEST = "manifest.json"


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def event_doc(event: Event) -> Dict[str, Any]:
    return {"event_id": event.event_id, "event_type": event.event_type, "aggregate_id": event.aggregate_id,
            "data": dict(event.data), "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "ledger": dict(event.ledger)}


def entry_for(seq: int, key: str, event: Mapping[str, Any], received_at: str, prev: str) -> Dict[str, Any]:
    body = {"v": 1, "seq": seq, "key": key, "event": dict(event), "received_at": received_at, "prev": prev}
    return {**body, "hash": sha256_hex(canonical(body))}


def file_for(received_at: str) -> str:
    return f"evidence-{received_at[:10]}.jsonl"


# ── keys ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError:  # pragma: no cover - the [proxy] extra brings it
        raise PluginError("the evidence export needs the cryptography package (theprotocol-sdk[proxy])")
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def keygen(path: str) -> str:
    """Write a new Ed25519 private key (PEM, mode 0600) to `path`; answers the public key (base64)."""
    serialization, Priv, _ = _crypto()
    p = Path(path)
    if p.exists():
        raise PluginError(f"{p} exists: a signing key is never written over")
    key = Priv.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return public_key_of(pem.decode())


def _load_private(pem: str):
    serialization, Priv, _ = _crypto()
    try:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except (ValueError, TypeError) as e:
        raise PluginError(f"the evidence signing key is not a PEM private key: {e}") from None
    if not isinstance(key, Priv):
        raise PluginError("the evidence signing key is not an Ed25519 key")
    return key


def public_key_of(pem: str) -> str:
    serialization, _, _ = _crypto()
    pub = _load_private(pem).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(pub)


def sign_manifest(doc: Dict[str, Any], pem: str) -> Dict[str, Any]:
    body = {k: v for k, v in doc.items() if k != "signature"}
    sig = _load_private(pem).sign(canonical(body).encode("utf-8"))
    return {**body, "signature": _b64(sig)}


def manifest_signature_ok(doc: Mapping[str, Any]) -> bool:
    _, _, Pub = _crypto()
    from cryptography.exceptions import InvalidSignature
    try:
        pub = Pub.from_public_bytes(base64.b64decode(doc["public_key"]))
        body = {k: v for k, v in doc.items() if k != "signature"}
        pub.verify(base64.b64decode(doc["signature"]), canonical(body).encode("utf-8"))
        return True
    except (KeyError, ValueError, TypeError, InvalidSignature):
        return False


# ── writing ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_lines(path: Path) -> List[str]:
    try:
        return [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln.strip()]
    except FileNotFoundError:
        return []


class EvidenceSink(Sink):
    name = "evidence"
    description = "Each event as one hash-chained JSON line, in files and a signed manifest anyone can check offline"
    config_schema = {
        "type": "object",
        "required": ["dir", "signing_key"],
        "additionalProperties": False,
        "properties": {
            "dir": {"type": "string", "minLength": 1},
            "signing_key": {"type": "string", "x-secret": True},
            "registry_card": {"type": "boolean"},
            "mirror": {"type": "object", "required": ["type"], "properties": {
                "type": {"enum": ["sftp", "s3"]},
                "host": {"type": "string"}, "port": {"type": "integer"}, "username": {"type": "string"},
                "password": {"type": "string", "x-secret": True},
                "private_key": {"type": "string", "x-secret": True}, "known_hosts": {"type": "string"},
                "path": {"type": "string"}, "bucket": {"type": "string"}, "prefix": {"type": "string"},
                "region": {"type": "string"}, "endpoint": {"type": "string"},
                "access_key": {"type": "string", "x-secret": True},
                "secret_key": {"type": "string", "x-secret": True}}},
        },
    }

    def __init__(self, config, ctx):
        super().__init__(config, ctx)
        self.dir = Path(self.config["dir"])
        self._pem: Optional[str] = None
        self._registry: Optional[Dict[str, Any]] = None

    async def start(self) -> None:
        self._pem = self.ctx.secret(self.config["signing_key"])
        public_key_of(self._pem)                                   # refuse a key that cannot sign, at start
        if self.ctx.dry_run:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        await self._recover()
        if self.config.get("registry_card"):
            self._registry = await self._fetch_card()

    async def _fetch_card(self) -> Optional[Dict[str, Any]]:
        try:
            card = await self.ctx.call("GET", "/.well-known/registry-card.json")
            jwks = await self.ctx.call("GET", "/.well-known/registry-jwks.json")
        except Retry as e:
            self.ctx.logger.warning("the registry card could not be read: the manifest goes without it",
                                    extra={"proxy": {"why": e.detail}})
            return None
        if card.status_code != 200 or jwks.status_code != 200:
            return None
        return {"url": self.ctx.registry_url, "fetched_at": datetime.now(timezone.utc).isoformat(),
                "card": card.json(), "jwks": jwks.json()}

    async def _recover(self) -> None:
        """A line written before a crash took its state with it: take the files' last line as the head (and drop a
        torn one, which nobody was told was kept)."""
        files = sorted(self.dir.glob("evidence-*.jsonl"))
        if not files:
            return
        last = files[-1]
        raw = last.read_text(encoding="utf-8")
        if raw and not raw.endswith("\n"):
            keep = raw[: raw.rfind("\n") + 1]
            _atomic_write(last, keep)
            raw = keep
        lines = [ln for ln in raw.split("\n") if ln.strip()]
        if not lines:
            return
        entry = json.loads(lines[-1])
        head = await self.ctx.state.get("head") or {}
        if int(entry["seq"]) > int(head.get("seq") or 0):
            await self.ctx.state.set("head", {"seq": entry["seq"], "hash": entry["hash"]})
            await self.ctx.state.set(f"key:{entry['key']}", entry["hash"])
            self._write_manifest()

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        doc = event_doc(event)
        if dry_run:
            return Outcome.dry(f"would append {event.event_type} {event.event_id} to the evidence", event=doc)
        kept = await self.ctx.state.get(f"key:{key}")
        if kept is None:
            head = await self.ctx.state.get("head") or {"seq": 0, "hash": ""}
            now = datetime.now(timezone.utc).isoformat()
            entry = entry_for(int(head["seq"]) + 1, key, doc, now, head["hash"])
            path = self.dir / file_for(now)
            with open(path, "a", encoding="utf-8") as f:
                f.write(canonical(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
            await self.ctx.state.set("head", {"seq": entry["seq"], "hash": entry["hash"]})
            await self.ctx.state.set(f"key:{key}", entry["hash"])
            self._write_manifest()
            kept = entry["hash"]
        await self._mirror()
        return Outcome.done(kept, "in the evidence")

    def manifest(self) -> Dict[str, Any]:
        files, head = [], {"seq": 0, "hash": ""}
        for path in sorted(self.dir.glob("evidence-*.jsonl")):
            lines = _read_lines(path)
            if not lines:
                continue
            first, last = json.loads(lines[0]), json.loads(lines[-1])
            files.append({"name": path.name, "lines": len(lines), "first_seq": first["seq"], "last_seq": last["seq"],
                          "last_hash": last["hash"],
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            head = {"seq": last["seq"], "hash": last["hash"]}
        pub = public_key_of(self._pem or "")
        doc: Dict[str, Any] = {"format": FORMAT, "proxy": self.ctx.proxy_name, "agent_did": self.ctx.agent_did,
                               "registry_url": self.ctx.registry_url, "files": files, "head": head,
                               "public_key": pub, "key_id": hashlib.sha256(base64.b64decode(pub)).hexdigest()[:16],
                               "written_at": datetime.now(timezone.utc).isoformat()}
        if self._registry:
            doc["registry"] = self._registry
        return sign_manifest(doc, self._pem or "")

    def _write_manifest(self) -> None:
        _atomic_write(self.dir / MANIFEST, json.dumps(self.manifest(), indent=1, sort_keys=True, ensure_ascii=False))

    async def _mirror(self) -> None:
        m = self.config.get("mirror")
        if not m:
            return
        names = [MANIFEST] + [p.name for p in sorted(self.dir.glob("evidence-*.jsonl"))[-1:]]
        try:
            if m["type"] == "sftp":
                _sftp_put(m, self.ctx, self.dir, names)
            else:
                _s3_put(m, self.ctx, self.dir, names)
        except PluginError:
            raise
        except Exception as e:  # noqa: BLE001 - the lines are kept here; the next attempt copies them again
            raise Retry(f"the {m['type']} mirror could not be written: {type(e).__name__}: {e}") from None


def _sftp_put(m: Mapping[str, Any], ctx: Any, base: Path, names: List[str]) -> None:
    try:
        import paramiko
    except ImportError:
        raise PluginError("an sftp mirror needs paramiko (pip install paramiko)") from None
    client = paramiko.SSHClient()
    # a server whose host key is not known is refused: known_hosts names the file that knows it
    if m.get("known_hosts"):
        client.load_host_keys(str(m["known_hosts"]))
    else:
        client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    kw: Dict[str, Any] = {"hostname": m["host"], "port": int(m.get("port") or 22), "username": m.get("username")}
    if m.get("private_key"):
        from io import StringIO
        text = ctx.secret(m["private_key"])
        for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
            try:
                kw["pkey"] = cls.from_private_key(StringIO(text))
                break
            except Exception:  # noqa: BLE001 - the next key type
                continue
        else:
            raise PluginError("the sftp mirror's private_key is not a key paramiko reads (Ed25519, ECDSA, RSA)")
    if m.get("password"):
        kw["password"] = ctx.secret(m["password"])
    client.connect(**kw)
    try:
        sftp = client.open_sftp()
        remote = (m.get("path") or ".").rstrip("/")
        for name in names:
            sftp.put(str(base / name), f"{remote}/{name}")
    finally:
        client.close()


def _s3_put(m: Mapping[str, Any], ctx: Any, base: Path, names: List[str]) -> None:
    try:
        import boto3
    except ImportError:
        raise PluginError("an s3 mirror needs boto3 (pip install boto3)") from None
    kw: Dict[str, Any] = {}
    if m.get("endpoint"):
        kw["endpoint_url"] = m["endpoint"]
    if m.get("region"):
        kw["region_name"] = m["region"]
    if m.get("access_key"):
        kw["aws_access_key_id"] = ctx.secret(m["access_key"])
        kw["aws_secret_access_key"] = ctx.secret(m["secret_key"])
    s3 = boto3.client("s3", **kw)
    prefix = (m.get("prefix") or "").strip("/")
    for name in names:
        s3.upload_file(str(base / name), m["bucket"], f"{prefix}/{name}" if prefix else name)


# ── checking, offline ────────────────────────────────────────────────────────────────────────────────────────────────

def verify(path: str, *, public_key: Optional[str] = None, webhook_secret: Optional[str] = None) -> Tuple[List[str], Dict[str, Any]]:
    """Check an export with no network. Answers (problems, summary); no problems means it holds."""
    base = Path(path)
    problems: List[str] = []
    try:
        man = json.loads((base / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"{MANIFEST}: cannot be read ({e})"], {}
    if man.get("format") != FORMAT:
        problems.append(f"{MANIFEST}: format {man.get('format')!r}, not {FORMAT}")
    if not manifest_signature_ok(man):
        problems.append(f"{MANIFEST}: the signature does not verify with its public key")
    if public_key and man.get("public_key") != public_key:
        problems.append(f"{MANIFEST}: signed by {man.get('key_id')}, not by the key you named")
    prev, seq, count, delivered, checked = "", 0, 0, 0, 0
    listed = [f.get("name") for f in man.get("files", [])]
    on_disk = sorted(p.name for p in base.glob("evidence-*.jsonl"))
    for extra in sorted(set(on_disk) - set(listed)):
        problems.append(f"{extra}: a file the manifest does not name")
    for f in man.get("files", []):
        name = f.get("name", "")
        p = base / name
        try:
            raw = p.read_bytes()
        except OSError:
            problems.append(f"{name}: missing")
            continue
        if hashlib.sha256(raw).hexdigest() != f.get("sha256"):
            problems.append(f"{name}: its SHA-256 is not the manifest's (the file was changed)")
        lines = [ln for ln in raw.decode("utf-8", "replace").split("\n") if ln.strip()]
        if len(lines) != f.get("lines"):
            problems.append(f"{name}: {len(lines)} lines, the manifest says {f.get('lines')}")
        for i, ln in enumerate(lines, 1):
            where = f"{name}:{i}"
            try:
                e = json.loads(ln)
            except ValueError:
                problems.append(f"{where}: not JSON")
                continue
            body = {k: v for k, v in e.items() if k != "hash"}
            if sha256_hex(canonical(body)) != e.get("hash"):
                problems.append(f"{where}: its hash does not match its content")
            if e.get("prev") != prev:
                problems.append(f"{where}: its prev is not the line before's hash (a line was removed or moved)")
            if e.get("seq") != seq + 1:
                problems.append(f"{where}: seq {e.get('seq')} after {seq}")
            prev, seq, count = e.get("hash", ""), int(e.get("seq") or 0), count + 1
            led = ((e.get("event") or {}).get("ledger") or {})
            if webhook_secret is not None and led.get("signed_body") is not None:
                delivered += 1
                want = hmac.new(webhook_secret.encode(), str(led["signed_body"]).encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(want, str(led.get("signature") or "")):
                    problems.append(f"{where}: the registry's webhook signature does not verify")
                else:
                    checked += 1
    head = man.get("head") or {}
    if (head.get("seq"), head.get("hash")) != (seq, prev):
        problems.append(f"{MANIFEST}: its head is seq {head.get('seq')}, the files end at seq {seq}")
    card_ok = None
    reg = man.get("registry")
    if reg:
        try:
            from ..registry.card_verify import verify_registry_card
            at = datetime.fromisoformat(str(reg.get("fetched_at")).replace("Z", "+00:00"))
            card_ok = verify_registry_card(reg.get("card") or {}, reg.get("jwks") or {}, now=at)
        except (ValueError, TypeError):
            card_ok = False
        if not card_ok:
            problems.append(f"{MANIFEST}: the registry card's signature does not verify (as of when it was read)")
    summary = {"lines": count, "files": len(listed), "head": head, "key_id": man.get("key_id"),
               "agent_did": man.get("agent_did"), "registry_card": card_ok,
               "webhook_signatures": {"checked": checked, "of": delivered} if webhook_secret is not None else None}
    return problems, summary
