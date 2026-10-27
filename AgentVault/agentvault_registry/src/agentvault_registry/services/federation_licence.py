"""§FEDLICENCE (2026-09-28): federation licences as issuer-signed certificates.

His word: the software is free to run (AGPL), membership in the network is licensed. "without an active license issued
you can still do everything but not federate with other frames. but you can still provision your cloud operators. we
can make eu registry genesis registry and give it a genesis federation license issued to itself ... display the license
hash on the registry card ... it should be a derived field also so it cant be tricked."

A hash a frame derives about itself is only as honest as that frame's build, and AGPL lets anyone run a modified build.
So a licence is a small certificate SIGNED by its issuer, and anybody can check the signature against the chain:

    genesis   self-signed by the network's root (EU in production); its hash is the network's pin
    frame     signed by the genesis; carries the frame's own licence-signing public key (`key`)
    operator  signed by its frame's key (under the FRAME's own operator policy, his word: each frame decides)

The unit of network licensing is the TRUST DOMAIN (a frame and its operators share one): crossing between two trust
domains needs a genesis-issued licence on both sides, inside one trust domain nothing is checked. That is his "you can
still provision your cloud operators": a standalone frame keeps working with its own operators.

Format: a compact JWS (EdDSA / Ed25519) whose payload is canonical JSON (sorted keys, compact separators).
    licence hash = sha256(ascii compact JWS), hex. That is the value a card shows and a list names.
Revocation: every issuer serves a signed list of what it issued (`/.well-known/federation-licences.json`); a verdict
is `licensed` only when the chain verifies to the pinned root AND the issuer's list, fetched within
LIST_MAX_AGE_SECONDS, says active. Anything this module cannot decide is `unverified` with the reason, never guessed.

Pure functions (sign, parse, verify, chain, verdict) take no database and no network, so they are unit-testable and
the same code runs in the SDK-style verifier, the sync worker and the routes. The async helpers below them own the
storage.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger(__name__)

KIND = "tp.federation.licence.v1"
LIST_KIND = "tp.federation.licence-list.v1"
JWS_TYP = "tp-licence+jws"
LIST_TYP = "tp-licence-list+jws"
TYPES = ("genesis", "frame", "operator")

# His plans (2026-09-28): private, research and non-profit perpetual and free; enterprise free for one year (terms may
# change, so the plan and the expiry ride IN the certificate and a later price is a renewal, not a code change);
# founding = grandfathered, perpetual; genesis = the root's own. Values are days of validity, None = perpetual.
# One category list (his words 2026-09-28 on the frame-commander form: "free license for educational, research and non
# profits. but enterprise and goverment orgs will not have the same privilige"): educational joins the perpetual plans,
# government takes the enterprise term. The form, the site copy, the viewer and the legal text name the same list.
NETWORK_PLANS: Dict[str, Optional[int]] = {
    "genesis": None,
    "founding": None,
    "private": None,
    "educational": None,
    "research": None,
    "non-profit": None,
    "enterprise": 365,
    "government": 365,
}
_PLAN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_TD_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

VERDICT_STATES = ("genesis", "licensed", "unlicensed", "expired", "revoked", "suspended", "unverified", "invalid")
MAX_JWS_LEN = 2000  # under the card validator's 2048-character string cap, with room for nothing else to change
PASSING_STATES = ("genesis", "licensed")


# ---------------------------------------------------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------------------------------------------------

def licence_mode() -> str:
    """off | observe | enforce (FEDERATION_LICENCE_MODE, source default off = byte-inert)."""
    m = (os.getenv("FEDERATION_LICENCE_MODE", "off") or "off").strip().lower()
    return m if m in ("off", "observe", "enforce") else "off"


def normalize_trust_domain(td: Optional[str]) -> str:
    return (td or "").strip().lower().removeprefix("spiffe://").strip("/")


def genesis_trust_domain() -> str:
    """The trust domain of the network's genesis (FEDERATION_GENESIS_TRUST_DOMAIN). Empty = no network configured."""
    return normalize_trust_domain(os.getenv("FEDERATION_GENESIS_TRUST_DOMAIN", ""))


def genesis_cert_pin() -> str:
    """Optional hardening: the exact hash of the genesis certificate (FEDERATION_GENESIS_CERT_HASH, hex)."""
    return (os.getenv("FEDERATION_GENESIS_CERT_HASH", "") or "").strip().lower()


def local_trust_domain() -> str:
    return normalize_trust_domain(os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com"))


def list_max_age_seconds() -> int:
    try:
        return max(60, int(os.getenv("FEDERATION_LICENCE_LIST_MAX_AGE_SECONDS", "86400")))
    except ValueError:
        return 86400


def terms_version() -> str:
    return (os.getenv("FEDERATION_LICENCE_TERMS", "fot-2.2") or "fot-2.2").strip()[:32]


def operator_policy() -> Dict[str, Any]:
    """THIS frame's operator licence policy (his word: each frame decides its own licensing / fee model; free for now).
    FEDERATION_OPERATOR_LICENCE_PLAN (default 'operator-free') and FEDERATION_OPERATOR_LICENCE_DAYS (unset = perpetual).
    There is no payment rail: the plan names the terms, a price is the frame's own business."""
    plan = (os.getenv("FEDERATION_OPERATOR_LICENCE_PLAN", "operator-free") or "operator-free").strip().lower()
    if not _PLAN_RE.match(plan):
        plan = "operator-free"
    days_raw = (os.getenv("FEDERATION_OPERATOR_LICENCE_DAYS", "") or "").strip()
    days: Optional[int] = None
    if days_raw:
        try:
            days = max(1, int(days_raw))
        except ValueError:
            days = None
    return {"plan": plan, "days": days}


# ---------------------------------------------------------------------------------------------------------------------
# JWS primitives
# ---------------------------------------------------------------------------------------------------------------------

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_dec(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def public_jwk_of(priv: Ed25519PrivateKey) -> Dict[str, str]:
    raw = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw)}


def jwk_thumbprint(jwk: Dict[str, Any]) -> str:
    """RFC 7638 thumbprint of an Ed25519 JWK (the required members only, lexical order)."""
    core = {"crv": jwk.get("crv"), "kty": jwk.get("kty"), "x": jwk.get("x")}
    return _b64u(hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")).digest())


def public_key_from_jwk(jwk: Dict[str, Any]) -> Ed25519PublicKey:
    if not isinstance(jwk, dict) or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not jwk.get("x"):
        raise ValueError("not an Ed25519 JWK")
    return Ed25519PublicKey.from_public_bytes(_b64u_dec(str(jwk["x"])))


def sign_jws(payload: Dict[str, Any], priv: Ed25519PrivateKey, *, kid: str, typ: str = JWS_TYP) -> str:
    header = {"alg": "EdDSA", "kid": kid, "typ": typ}
    signing_input = _b64u(canonical(header)) + "." + _b64u(canonical(payload))
    return signing_input + "." + _b64u(priv.sign(signing_input.encode("ascii")))


# a certificate is kept under MAX_JWS_LEN at issue; a LIST grows with every licence an issuer ever signed (perpetual
# plans never drop out, renewals add rows), so it has its own, much larger cap (agentvault2-41, measured: under the
# certificate cap a list stopped verifying at 39 licences and revocation failed open across the network)
CERT_PARSE_MAX = 16384
LIST_PARSE_MAX = 8 * 1024 * 1024


def parse_jws(jws: str, *, max_len: int = CERT_PARSE_MAX) -> Tuple[Dict[str, Any], Dict[str, Any], bytes, bytes]:
    """(header, payload, signing_input, signature). Raises ValueError naming WHY: too long, or malformed."""
    if not isinstance(jws, str):
        raise ValueError("not a compact JWS (not a string)")
    if len(jws) > max_len:
        raise ValueError(f"too long: {len(jws)} characters, the limit for this kind is {max_len}")
    if jws.count(".") != 2:
        raise ValueError("not a compact JWS")
    h_b64, p_b64, s_b64 = jws.split(".")
    try:
        header = json.loads(_b64u_dec(h_b64))
        payload = json.loads(_b64u_dec(p_b64))
        sig = _b64u_dec(s_b64)
    except Exception as exc:  # noqa: BLE001 — every decode failure is the same verdict: malformed
        raise ValueError(f"malformed JWS: {type(exc).__name__}") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ValueError("JWS header or payload is not an object")
    if header.get("alg") != "EdDSA":
        raise ValueError(f"unsupported alg {header.get('alg')!r}")
    return header, payload, (h_b64 + "." + p_b64).encode("ascii"), sig


def verify_jws(jws: str, jwk: Dict[str, Any], *, max_len: int = CERT_PARSE_MAX) -> bool:
    try:
        header, _payload, signing_input, sig = parse_jws(jws, max_len=max_len)
        if header.get("kid") and header.get("kid") != jwk_thumbprint(jwk):
            return False
        public_key_from_jwk(jwk).verify(sig, signing_input)
        return True
    except (ValueError, InvalidSignature):
        return False
    except Exception:  # noqa: BLE001 — a verifier never raises; an unverifiable signature is a False
        return False


def licence_hash(jws: str) -> str:
    return hashlib.sha256((jws or "").strip().encode("ascii", "replace")).hexdigest()


def short_hash(h: Optional[str]) -> Optional[str]:
    return (h[:16] if h else None)


# ---------------------------------------------------------------------------------------------------------------------
# certificates
# ---------------------------------------------------------------------------------------------------------------------

def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _ts(d: Optional[_dt.datetime]) -> Optional[int]:
    return int(d.timestamp()) if d else None


def build_payload(*, type_: str, sub: Dict[str, Any], iss: Dict[str, Any], plan: str, network: Optional[str],
                  key: Optional[Dict[str, Any]] = None, days: Optional[int] = None,
                  now: Optional[_dt.datetime] = None, lid: Optional[str] = None) -> Dict[str, Any]:
    """The certificate payload. `sub` = {trust_domain, name, url?, spiffe?}; `iss` = {trust_domain, name, kid,
    licence (the issuer's own network certificate hash, or None for a genesis / a standalone frame)}."""
    if type_ not in TYPES:
        raise ValueError(f"unknown licence type {type_!r}")
    if not _PLAN_RE.match(plan or ""):
        raise ValueError(f"bad plan {plan!r}")
    td = normalize_trust_domain(sub.get("trust_domain"))
    if not _TD_RE.match(td):
        raise ValueError(f"bad subject trust domain {sub.get('trust_domain')!r}")
    now = now or _now()
    payload: Dict[str, Any] = {
        "kind": KIND,
        "lid": lid or str(uuid.uuid4()),
        "type": type_,
        "sub": {k: v for k, v in {
            "trust_domain": td,
            "name": str(sub.get("name") or "")[:255],
            "url": (str(sub.get("url"))[:500] if sub.get("url") else None),
            "spiffe": (str(sub.get("spiffe"))[:255] if sub.get("spiffe") else None),
        }.items() if v is not None},
        "iss": {
            "trust_domain": normalize_trust_domain(iss.get("trust_domain")),
            "name": str(iss.get("name") or "")[:255],
            "kid": str(iss.get("kid") or ""),
            "licence": iss.get("licence") or None,
        },
        "network": normalize_trust_domain(network) or None,
        "plan": plan,
        "terms": terms_version(),
        "iat": _ts(now),
        "exp": (_ts(now + _dt.timedelta(days=int(days))) if days else None),
    }
    if key is not None:
        payload["key"] = {"kty": key.get("kty"), "crv": key.get("crv"), "x": key.get("x")}
    return payload


@dataclass
class Cert:
    jws: str
    header: Dict[str, Any]
    payload: Dict[str, Any]
    hash: str

    @property
    def type(self) -> str:
        return str(self.payload.get("type") or "")

    @property
    def sub_td(self) -> str:
        return normalize_trust_domain((self.payload.get("sub") or {}).get("trust_domain"))

    @property
    def sub_name(self) -> str:
        return str((self.payload.get("sub") or {}).get("name") or "")

    @property
    def iss_td(self) -> str:
        return normalize_trust_domain((self.payload.get("iss") or {}).get("trust_domain"))

    @property
    def iss_licence(self) -> Optional[str]:
        v = (self.payload.get("iss") or {}).get("licence")
        return str(v).lower() if v else None

    @property
    def key(self) -> Optional[Dict[str, Any]]:
        k = self.payload.get("key")
        return k if isinstance(k, dict) else None

    @property
    def plan(self) -> str:
        return str(self.payload.get("plan") or "")

    @property
    def exp(self) -> Optional[int]:
        v = self.payload.get("exp")
        return int(v) if isinstance(v, (int, float)) else None

    @property
    def iat(self) -> Optional[int]:
        v = self.payload.get("iat")
        return int(v) if isinstance(v, (int, float)) else None


def load_cert(jws: str) -> Cert:
    """Parse (never verify) a certificate. Raises ValueError when it is not one of ours."""
    header, payload, _si, _sig = parse_jws(jws)
    if payload.get("kind") != KIND:
        raise ValueError(f"not a licence certificate (kind {payload.get('kind')!r})")
    if payload.get("type") not in TYPES:
        raise ValueError(f"unknown licence type {payload.get('type')!r}")
    return Cert(jws=jws.strip(), header=header, payload=payload, hash=licence_hash(jws))


# ---------------------------------------------------------------------------------------------------------------------
# verdicts (pure: no database, no network)
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class Verdict:
    state: str
    reason: str = ""
    hash: Optional[str] = None
    type: Optional[str] = None
    plan: Optional[str] = None
    issuer: Optional[str] = None
    network: Optional[str] = None
    expires_at: Optional[int] = None
    list_state: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def passes(self) -> bool:
        return self.state in PASSING_STATES

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["passes"] = self.passes
        return d


def verify_root(root_jws: Optional[str], *, genesis_td: str, pin: str = "") -> Tuple[Optional[Cert], str]:
    """(root cert, "") when `root_jws` is a self-signed genesis certificate for `genesis_td` (and matches the pin when
    one is set), else (None, why)."""
    if not root_jws:
        return None, "no genesis certificate known"
    try:
        root = load_cert(root_jws)
    except ValueError as exc:
        return None, f"genesis certificate unreadable: {exc}"
    if root.type != "genesis":
        return None, f"the root is a {root.type!r} certificate, not a genesis"
    if not genesis_td or root.sub_td != genesis_td or root.iss_td != genesis_td:
        return None, f"the root names {root.sub_td!r}, the network's genesis is {genesis_td or '(unset)'!r}"
    if pin and root.hash != pin:
        return None, "the genesis certificate does not match FEDERATION_GENESIS_CERT_HASH"
    if not root.key or not verify_jws(root.jws, root.key):
        return None, "the genesis certificate's self-signature does not verify"
    return root, ""


def _temporal(cert: Cert, now_ts: int) -> Optional[str]:
    if cert.iat and cert.iat > now_ts + 300:
        return "issued in the future"
    if cert.exp is not None and cert.exp <= now_ts:
        return "expired"
    return None


# the issuer's list states, mapped EXPLICITLY (agentvault2-41's review): anything not named here is `unverified`, which
# enforce allows, so every state an issuer can publish must be listed. `superseded` = the subject was issued a newer
# licence, so the older one no longer licenses anybody.
LIST_VERDICT = {"active": "licensed", "revoked": "revoked", "superseded": "revoked", "suspended": "suspended",
                "expired": "expired"}


def _subject_key(row: Any) -> Tuple[str, str, str]:
    """One licensee: a frame is its trust domain; an operator is its frame's trust domain plus its name."""
    t = str(getattr(row, "type", "") or "")
    return (t, str(getattr(row, "sub_trust_domain", "") or ""),
            str(getattr(row, "sub_name", "") or "") if t == "operator" else "")


def _list_state(lists: Dict[str, Dict[str, Any]], issuer_td: str, cert_hash: str, now_ts: int,
                max_age: int) -> Tuple[Optional[str], str]:
    """(state from the issuer's verified list, why). None when the list is missing or stale."""
    entry = (lists or {}).get(issuer_td) or {}
    fetched = entry.get("fetched_at")
    if not entry or not isinstance(fetched, (int, float)):
        return None, f"no verified licence list from {issuer_td}"
    if now_ts - int(fetched) > max_age:
        return None, f"the licence list from {issuer_td} is {now_ts - int(fetched)} s old (max {max_age})"
    states = entry.get("states") or {}
    st = states.get(cert_hash)
    if st is None:
        return None, f"{issuer_td}'s list does not name this certificate"
    return str(st), ""


def evaluate(cert_jws: Optional[str], chain: Optional[List[str]], *, expect_trust_domain: str, root_jws: Optional[str],
             genesis_td: str, pin: str = "", lists: Optional[Dict[str, Dict[str, Any]]] = None,
             now_ts: Optional[int] = None, max_age: Optional[int] = None) -> Verdict:
    """The verdict about a NETWORK licence presented for `expect_trust_domain` (a frame's own certificate, or the frame
    certificate an operator rides). `lists` maps an issuer trust domain to {"fetched_at": ts, "states": {hash: state}}
    for lists whose signature was already verified. Never raises."""
    now_ts = int(now_ts if now_ts is not None else _now().timestamp())
    max_age = int(max_age if max_age is not None else list_max_age_seconds())
    expect = normalize_trust_domain(expect_trust_domain)
    if not cert_jws:
        return Verdict("unlicensed", "no network licence presented")
    try:
        cert = load_cert(cert_jws)
    except ValueError as exc:
        return Verdict("invalid", str(exc))
    v = Verdict("unverified", hash=cert.hash, type=cert.type, plan=cert.plan, issuer=cert.iss_td,
                network=normalize_trust_domain(cert.payload.get("network")) or None, expires_at=cert.exp)
    if cert.type not in ("genesis", "frame"):
        v.state, v.reason = "invalid", f"a {cert.type} certificate is not a network licence"
        return v
    if cert.sub_td != expect:
        v.state, v.reason = "invalid", f"the certificate names {cert.sub_td!r}, the peer is {expect!r}"
        return v
    root, why = verify_root(root_jws, genesis_td=genesis_td, pin=pin)
    if root is None:
        v.reason = why
        return v
    if cert.type == "genesis":
        if cert.hash != root.hash:
            v.state, v.reason = "invalid", "a second genesis certificate: only the network's pinned root is a genesis"
            return v
        v.state, v.reason = "genesis", "the network's root"
        return v
    # a frame certificate: issued by the genesis, signed by the root's key
    if cert.iss_td != root.sub_td or (cert.iss_licence and cert.iss_licence != root.hash):
        v.state, v.reason = "invalid", f"issued by {cert.iss_td!r}, not by the network's genesis"
        return v
    if not verify_jws(cert.jws, root.key or {}):
        v.state, v.reason = "invalid", "the genesis signature does not verify"
        return v
    t = _temporal(cert, now_ts)
    if t:
        v.state, v.reason = ("expired" if t == "expired" else "invalid"), t
        return v
    st, why = _list_state(lists or {}, root.sub_td, cert.hash, now_ts, max_age)
    v.list_state = st
    if st is None:
        v.reason = why
        return v
    v.state = LIST_VERDICT.get(st, "unverified")
    v.reason = (f"signed by {root.sub_td}, active on its list" if st == "active"
                else f"{root.sub_td}'s list says {st}" + (" (a newer licence replaced it)" if st == "superseded" else ""))
    return v


def evaluate_operator(op_jws: Optional[str], *, frame_cert_jws: Optional[str], frame_td: str,
                      lists: Optional[Dict[str, Dict[str, Any]]] = None, now_ts: Optional[int] = None,
                      max_age: Optional[int] = None) -> Verdict:
    """The verdict about an OPERATOR licence: it must be signed by the key its frame's network certificate carries, and
    the frame's own list decides its state. A standalone frame holds no network certificate, so nobody outside it can
    check its operators' signatures: that verdict is `unverified`, never a guess."""
    now_ts = int(now_ts if now_ts is not None else _now().timestamp())
    max_age = int(max_age if max_age is not None else list_max_age_seconds())
    if not op_jws:
        return Verdict("unlicensed", "no operator licence presented")
    try:
        op = load_cert(op_jws)
    except ValueError as exc:
        return Verdict("invalid", str(exc))
    v = Verdict("unverified", hash=op.hash, type=op.type, plan=op.plan, issuer=op.iss_td, expires_at=op.exp,
                network=normalize_trust_domain(op.payload.get("network")) or None)
    if op.type != "operator":
        v.state, v.reason = "invalid", f"a {op.type} certificate is not an operator licence"
        return v
    ftd = normalize_trust_domain(frame_td)
    if op.sub_td != ftd or op.iss_td != ftd:
        v.state, v.reason = "invalid", f"the operator licence names {op.sub_td!r} / issuer {op.iss_td!r}, the frame is {ftd!r}"
        return v
    if not frame_cert_jws:
        v.reason = "the issuing frame holds no network certificate carrying its key"
        return v
    try:
        frame = load_cert(frame_cert_jws)
    except ValueError as exc:
        v.reason = f"the frame's certificate is unreadable: {exc}"
        return v
    if not frame.key or not verify_jws(op.jws, frame.key):
        v.state, v.reason = "invalid", "the frame's signature does not verify"
        return v
    t = _temporal(op, now_ts)
    if t:
        v.state, v.reason = ("expired" if t == "expired" else "invalid"), t
        return v
    st, why = _list_state(lists or {}, ftd, op.hash, now_ts, max_age)
    v.list_state = st
    if st is None:
        v.reason = why
        return v
    v.state = LIST_VERDICT.get(st, "unverified")
    v.reason = f"signed by {ftd}, {st} on its list"
    return v


def verify_list(list_jws: str, issuer_jwk: Dict[str, Any], *, issuer_td: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """(payload, "") when `list_jws` is a licence list signed by `issuer_jwk` naming `issuer_td`, else (None, why)."""
    try:
        header, payload, _si, _sig = parse_jws(list_jws, max_len=LIST_PARSE_MAX)
    except ValueError as exc:
        return None, str(exc)
    if payload.get("kind") != LIST_KIND:
        return None, f"not a licence list (kind {payload.get('kind')!r})"
    if normalize_trust_domain((payload.get("issuer") or {}).get("trust_domain")) != normalize_trust_domain(issuer_td):
        return None, "the list names another issuer"
    if not verify_jws(list_jws, issuer_jwk, max_len=LIST_PARSE_MAX):
        return None, "the list's signature does not verify"
    return payload, ""


def list_states(list_payload: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in list_payload.get("licences") or []:
        if isinstance(item, dict) and item.get("hash"):
            out[str(item["hash"]).lower()] = str(item.get("state") or "")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# storage (async; the routes and the sync worker call these)
# ---------------------------------------------------------------------------------------------------------------------

async def get_or_create_key(db) -> Tuple[Any, Ed25519PrivateKey]:
    """(row, private key) of this registry's active licence-signing key, minted on first use. The private half is
    encrypted with the registry-card keystore's scheme (and refused in plaintext where that keystore refuses)."""
    from sqlalchemy import select
    from .. import models
    from .registry_card_keystore import _decrypt_pem, _encrypt_pem

    row = (await db.execute(
        select(models.FederationLicenceKey)
        .where(models.FederationLicenceKey.retired_at.is_(None))
        .order_by(models.FederationLicenceKey.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is not None:
        pem = _decrypt_pem(row.private_pem_encrypted)
        return row, serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    jwk = public_jwk_of(priv)
    row = models.FederationLicenceKey(kid=jwk_thumbprint(jwk), public_jwk=jwk, private_pem_encrypted=_encrypt_pem(pem))
    db.add(row)
    await db.flush()
    logger.info("[fedlicence] minted this registry's licence-signing key kid=%s", row.kid)
    return row, priv


async def get_certs(db, role: str) -> List[Any]:
    from sqlalchemy import select
    from .. import models
    return list((await db.execute(
        select(models.FederationLicenceCert)
        .where(models.FederationLicenceCert.role == role)
        .order_by(models.FederationLicenceCert.id.desc())
    )).scalars().all())


async def get_cert(db, role: str) -> Optional[Any]:
    """The newest certificate in `role` that is not revoked (held / held_operator / root are one-per-registry)."""
    for row in await get_certs(db, role):
        if row.state not in ("revoked", "replaced"):
            return row
    return None


async def store_cert(db, cert: Cert, *, role: str, chain: Optional[List[str]] = None, state: str = "active",
                     created_by: Optional[int] = None) -> Any:
    """Insert (or refresh) the row for (cert.hash, role). A held/held_operator/root cert REPLACES the previous one in
    that role (the old row is marked `replaced`, never deleted)."""
    from sqlalchemy import select
    from .. import models
    existing = (await db.execute(
        select(models.FederationLicenceCert).where(
            models.FederationLicenceCert.hash == cert.hash, models.FederationLicenceCert.role == role,
        )
    )).scalar_one_or_none()
    if role in ("held", "held_operator", "root"):
        for other in await get_certs(db, role):
            if other.hash != cert.hash and other.state not in ("revoked", "replaced"):
                other.state, other.state_reason = "replaced", f"replaced by {cert.hash[:16]}"
    if existing is not None:
        existing.chain = list(chain or existing.chain or [])
        if existing.state == "replaced":
            existing.state, existing.state_reason = state, None
        await db.flush()
        return existing
    p = cert.payload
    sub = p.get("sub") or {}
    row = models.FederationLicenceCert(
        hash=cert.hash, role=role, lid=str(p.get("lid") or "")[:36], type=cert.type,
        sub_trust_domain=cert.sub_td, sub_name=cert.sub_name[:255] or cert.sub_td,
        sub_url=(str(sub.get("url"))[:500] if sub.get("url") else None),
        iss_trust_domain=cert.iss_td, network=(normalize_trust_domain(p.get("network")) or None),
        plan=cert.plan, issued_at=_dt.datetime.fromtimestamp(cert.iat or 0, _dt.timezone.utc),
        expires_at=(_dt.datetime.fromtimestamp(cert.exp, _dt.timezone.utc) if cert.exp else None),
        state=state, jws=cert.jws, chain=list(chain or []), created_by=created_by,
    )
    db.add(row)
    await db.flush()
    return row


def cert_row_brief(row: Any) -> Dict[str, Any]:
    return {
        "hash": row.hash, "role": row.role, "lid": row.lid, "type": row.type,
        "sub_trust_domain": row.sub_trust_domain, "sub_name": row.sub_name, "sub_url": row.sub_url,
        "issuer": row.iss_trust_domain, "network": row.network, "plan": row.plan,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "state": row.state, "state_reason": row.state_reason,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
    }


async def issued_list_jws(db, *, public_name: str) -> Tuple[str, Dict[str, Any]]:
    """The signed list of every certificate this registry issued (its revocation source). (jws, payload)."""
    key_row, priv = await get_or_create_key(db)
    rows = await get_certs(db, "issued")
    payload = {
        "kind": LIST_KIND,
        "issuer": {"trust_domain": local_trust_domain(), "name": public_name, "kid": key_row.kid},
        "generated_at": int(_now().timestamp()),
        "licences": [{
            "hash": r.hash, "lid": r.lid, "type": r.type, "sub_trust_domain": r.sub_trust_domain,
            "sub_name": r.sub_name, "plan": r.plan,
            "iat": _ts(r.issued_at), "exp": _ts(r.expires_at),
            "state": ("expired" if (r.expires_at and r.expires_at <= _now() and r.state == "active") else r.state),
            "updated_at": _ts(r.updated_at),
        } for r in rows],
    }
    return sign_jws(payload, priv, kid=key_row.kid, typ=LIST_TYP), payload


async def issue(db, *, type_: str, sub: Dict[str, Any], plan: str, days: Optional[int], public_name: str,
                created_by: Optional[int] = None) -> Tuple[Any, Cert]:
    """Issue a certificate signed by THIS registry's licence key. Rules:
       genesis   only where this registry's trust domain IS the configured genesis, self-issued, once
       frame     only by the genesis (it holds the network's root)
       operator  by any frame, for a subject in its OWN trust domain, under its own operator policy
    Returns (row, cert). Raises ValueError with the refusal sentence."""
    local_td = local_trust_domain()
    gtd = genesis_trust_domain()
    key_row, priv = await get_or_create_key(db)
    held = await get_cert(db, "held")
    held_hash = held.hash if held is not None else None
    if type_ == "genesis":
        if not gtd or gtd != local_td:
            raise ValueError(f"this registry ({local_td}) is not the configured genesis "
                             f"(FEDERATION_GENESIS_TRUST_DOMAIN={gtd or 'unset'})")
        existing_root = await get_cert(db, "root")
        if existing_root is not None and existing_root.type == "genesis" and existing_root.sub_trust_domain == local_td:
            raise ValueError(f"this registry already holds its genesis certificate {existing_root.hash[:16]}; "
                             "a second genesis would split the network")
        sub = {"trust_domain": local_td, "name": public_name, "url": sub.get("url")}
        payload = build_payload(type_="genesis", sub=sub, iss={"trust_domain": local_td, "name": public_name,
                                                              "kid": key_row.kid, "licence": None},
                                plan="genesis", network=local_td, key=key_row.public_jwk, days=None)
    elif type_ == "frame":
        root = await get_cert(db, "root")
        if not gtd or gtd != local_td or root is None or root.sub_trust_domain != local_td:
            raise ValueError("only the network's genesis issues frame licences, and this registry is not it "
                             "(or has not self-issued its genesis certificate yet)")
        sub_td = normalize_trust_domain(sub.get("trust_domain"))
        if sub_td == local_td:
            raise ValueError("a frame licence names another trust domain; the genesis holds its own genesis certificate")
        if plan not in NETWORK_PLANS or plan == "genesis":
            raise ValueError(f"plan must be one of {sorted(p for p in NETWORK_PLANS if p != 'genesis')}")
        subject_key = sub.get("key")
        if not isinstance(subject_key, dict):
            raise ValueError("a frame licence carries the frame's licence-signing public key (sub.key, an Ed25519 JWK); "
                             "read it from the frame's GET /api/v1/admin/federation/licence/status or its public "
                             "/.well-known/federation-licence.json")
        public_key_from_jwk(subject_key)  # raises ValueError on a bad key
        payload = build_payload(type_="frame", sub=sub, iss={"trust_domain": local_td, "name": public_name,
                                                            "kid": key_row.kid, "licence": root.hash},
                                plan=plan, network=local_td, key=subject_key,
                                days=(days if days is not None else NETWORK_PLANS.get(plan)))
    elif type_ == "operator":
        sub_td = normalize_trust_domain(sub.get("trust_domain") or local_td)
        if sub_td != local_td:
            raise ValueError(f"an operator licence names this frame's own trust domain ({local_td}); "
                             f"{sub_td!r} is another network")
        pol = operator_policy()
        payload = build_payload(type_="operator", sub={**sub, "trust_domain": local_td},
                                iss={"trust_domain": local_td, "name": public_name, "kid": key_row.kid,
                                     "licence": held_hash},
                                plan=(plan or pol["plan"]),
                                network=(held.network if held is not None else None),
                                days=(days if days is not None else pol["days"]))
    else:
        raise ValueError(f"unknown licence type {type_!r}")
    jws = sign_jws(payload, priv, kid=key_row.kid)
    if len(jws) >= MAX_JWS_LEN:
        # every peer's card validator refuses a WHOLE card holding a string over 2048 characters, and the certificate
        # rides on the licensee's card: a longer one would take the licensee off every peer's map
        raise ValueError(f"the certificate would be {len(jws)} characters, over the {MAX_JWS_LEN} a card may carry; "
                         "shorten the name or url")
    cert = load_cert(jws)
    if type_ in ("frame", "operator"):
        # agentvault2-41's review: one subject holds ONE live licence. A renewal or a plan change retires the older
        # ones, or revoking the current licence would leave an older, still-active one licensing the subject.
        _new_key = (type_, cert.sub_td, cert.sub_name if type_ == "operator" else "")
        for older in await get_certs(db, "issued"):
            if _subject_key(older) == _new_key and older.state in ("active", "suspended"):
                older.state, older.state_reason = "superseded", f"superseded by {cert.hash[:16]}"
    row = await store_cert(db, cert, role="issued", created_by=created_by)
    if type_ == "genesis":
        await store_cert(db, cert, role="root", created_by=created_by)
        await store_cert(db, cert, role="held", created_by=created_by)
    logger.info("[fedlicence] issued %s licence %s to %s (%s) plan=%s", type_, cert.hash[:16],
                cert.sub_td, cert.sub_name, cert.plan)
    return row, cert


async def set_issued_state(db, cert_hash: str, state: str, reason: str) -> Any:
    """Revoke, suspend or reinstate. A revoke or a suspend acts on the SUBJECT (agentvault2-41's review, measured): every
    licence this registry issued to that frame (an operator: that frame's operator of that name) that could still
    license it, so an older certificate cannot stand in for the one revoked. A reinstate lifts only the named licence's
    suspension (a superseded or revoked licence stays so)."""
    if state not in ("active", "suspended", "revoked"):
        raise ValueError("state must be active, suspended or revoked")
    h = (cert_hash or "").strip().lower()
    issued = await get_certs(db, "issued")
    row = next((r for r in issued if r.hash == h), None)
    if row is None:
        raise LookupError("no certificate with that hash was issued here")
    if row.type == "genesis":
        raise ValueError("the genesis certificate is the network's root; it is not suspended or revoked from a list")
    if row.state == "revoked" and state != "revoked":
        raise ValueError("a revoked licence stays revoked; issue a new one")
    if state == "active" and row.state == "superseded":
        raise ValueError("a superseded licence stays superseded; the subject's newer licence is the live one")
    why = (reason or "")[:240] or None
    if state == "active":
        row.state, row.state_reason = "active", why
    else:
        key = _subject_key(row)
        for r in issued:
            if _subject_key(r) != key:
                continue
            if state == "revoked" and r.state != "revoked":
                r.state, r.state_reason = "revoked", why
            elif state == "suspended" and r.state == "active":
                r.state, r.state_reason = "suspended", why
    await db.flush()
    return row


# ---------------------------------------------------------------------------------------------------------------------
# the card block, the ETag token
# ---------------------------------------------------------------------------------------------------------------------

def _iso(ts: Optional[int]) -> Optional[str]:
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat() if ts else None


async def active_key_jwk(db) -> Optional[Dict[str, Any]]:
    """This registry's licence-signing public key, when one exists (read only: the card build never mints)."""
    from sqlalchemy import select
    from .. import models
    row = (await db.execute(
        select(models.FederationLicenceKey)
        .where(models.FederationLicenceKey.retired_at.is_(None))
        .order_by(models.FederationLicenceKey.id.desc()).limit(1)
    )).scalar_one_or_none()
    return dict(row.public_jwk) if row is not None else None


def configured() -> bool:
    """A network is configured here (a genesis trust domain named, or licensing switched on). Without it and without a
    held licence, the CARD carries no licence block at all: a frame on an image that knows licences, in a network that
    has not held its genesis ceremony yet, must not read "standalone" on its card."""
    return bool(genesis_trust_domain()) or licence_mode() != "off"


async def card_block(db, *, is_operator: bool, for_card: bool = False) -> Optional[Dict[str, Any]]:
    """`federation.licence`, DERIVED at card-build time from the certificates this registry holds and the verdict its
    own sync worker last reached about them. Never read from the operator-editable card JSON (the admin PUT model has
    no key for it). A frame shows its own network licence; an operator shows the network licence of the frame it rides
    AND its own operator licence. `for_card`: None when no network is configured and nothing is held (the card then
    carries no block); the public route always answers, with the frame's key, so a genesis can issue it a licence."""
    held = await get_cert(db, "held")
    root = await get_cert(db, "root")
    if for_card and held is None and not configured() and (not is_operator or await get_cert(db, "held_operator") is None):
        return None
    block: Dict[str, Any] = {
        "state": "unlicensed",
        "hash": None,
        "network": genesis_trust_domain() or None,
        "issuer": None,
        "plan": None,
        "expires_at": None,
        "certificate": None,
        "chain": [],
        "checked_at": None,
        "reason": "holds no network licence",
    }
    if held is not None:
        block.update({
            "state": held.state if held.state in VERDICT_STATES else "unverified",
            "hash": held.hash,
            "network": held.network or block["network"],
            "issuer": held.iss_trust_domain,
            "plan": held.plan,
            "expires_at": held.expires_at.isoformat() if held.expires_at else None,
            "certificate": held.jws,
            "chain": [c for c in (held.chain or []) if isinstance(c, str)][:2],
            "checked_at": held.checked_at.isoformat() if held.checked_at else None,
            "reason": (held.state_reason or "")[:240],
        })
        if held.type == "genesis" and root is not None and root.hash == held.hash:
            block["state"], block["chain"] = "genesis", []
    if is_operator:
        op = await get_cert(db, "held_operator")
        block["operator"] = None if op is None else {
            "state": op.state if op.state in VERDICT_STATES else "unverified",
            "hash": op.hash, "issuer": op.iss_trust_domain, "plan": op.plan,
            "expires_at": op.expires_at.isoformat() if op.expires_at else None,
            "certificate": op.jws,
            "checked_at": op.checked_at.isoformat() if op.checked_at else None,
        }
    else:
        block["key"] = await active_key_jwk(db)
        block["operator_policy"] = operator_policy()
    return block


def etag_token(block: Optional[Dict[str, Any]]) -> str:
    """The licence's share of the card ETag basis: a rotation, a revocation or a verdict change is never hidden behind
    a 304."""
    b = block or {}
    op = b.get("operator") or {}
    return "|".join(str(x or "") for x in (b.get("state"), b.get("hash"), op.get("state"), op.get("hash")))


# ---------------------------------------------------------------------------------------------------------------------
# the per-cycle refresh (the leader-elected federation sync worker calls this once a cycle)
# ---------------------------------------------------------------------------------------------------------------------

# the paths a peer's sync worker reads over the federation lane: a frame's nginx-federation serves /api/v1/federation/
# and three named well-known files only, so the /.well-known/federation-licence(s).json names would 404 there
FED_OWN_PATH = "/api/v1/federation/licence/own"
FED_LIST_PATH = "/api/v1/federation/licence/list"

# the last VERIFIED list per issuer trust domain: {"fetched_at": ts, "states": {hash: state}}; in-process on purpose
# (the leader computes every verdict and writes it to the database; a restart re-fetches within one cycle)
_LISTS: Dict[str, Dict[str, Any]] = {}
_LAST_SUMMARY: Dict[str, Any] = {}


def last_summary() -> Dict[str, Any]:
    return dict(_LAST_SUMMARY)


_SUMMARY_KEY = "fedlicence:last_cycle"
_SUMMARY_TTL_S = 7200


async def save_summary(summary: Dict[str, Any]) -> None:
    """The last cycle's summary, shared by every worker (agentvault2-41: an in-process summary answered {} from 7 of 8
    workers, so "all quiet" and "this worker never ran a cycle" read the same). Best effort, TTL two hours."""
    try:
        from ..background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            await r.set(_SUMMARY_KEY, json.dumps(summary, default=str), ex=_SUMMARY_TTL_S)
    except Exception as exc:  # noqa: BLE001 — a summary never costs a cycle
        logger.debug("[fedlicence] summary not shared: %s", exc)


async def read_summary() -> Dict[str, Any]:
    """The last cycle's summary from Redis (any worker), else this worker's own, else a sentence saying there is none."""
    try:
        from ..background_tasks.leader import get_redis
        r = await get_redis()
        raw = await r.get(_SUMMARY_KEY) if r is not None else None
        if raw:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception:  # noqa: BLE001
        pass
    if _LAST_SUMMARY:
        return dict(_LAST_SUMMARY)
    return {"available": False, "why": "no licence cycle has run in the last two hours (the leader runs one per "
                                       "federation-sync cycle while FEDERATION_LICENCE_MODE is not off)"}


async def own_issued_states(db) -> Dict[str, str]:
    now = _now()
    out: Dict[str, str] = {}
    for r in await get_certs(db, "issued"):
        st = r.state
        if st == "active" and r.expires_at and r.expires_at <= now:
            st = "expired"
        out[r.hash] = st
    return out


def _operator_slug_from_spiffe(spiffe_id: str, local_td: str) -> Optional[str]:
    m = re.match(r"^spiffe://([^/]+)/operator/([A-Za-z0-9._-]{1,120})(/|$)", spiffe_id or "")
    if not m or normalize_trust_domain(m.group(1)) != local_td:
        return None
    return m.group(2)


async def parent_answer_for_operator(db, *, spiffe_id: str, public_name: str,
                                     operator_url: Optional[str] = None) -> Dict[str, Any]:
    """What a frame hands ITS OWN operator that asks over mTLS: the operator's licence (issued on first ask while the
    frame's operator policy auto-issues, his word: free for now), the frame's own network certificate and chain, and
    the frame's verdict about both. Raises PermissionError for an identity that is not one of this frame's operators."""
    local_td = local_trust_domain()
    slug = _operator_slug_from_spiffe(spiffe_id, local_td)
    if not slug:
        raise PermissionError("only this frame's own operators ask for their licence here")
    issued = [r for r in await get_certs(db, "issued") if r.type == "operator" and r.sub_name == slug]
    live = next((r for r in issued if r.state in ("active", "suspended")), None)
    created = False
    if live is None and (os.getenv("FEDERATION_OPERATOR_LICENCE_AUTO_ISSUE", "true") or "").strip().lower() in (
            "1", "true", "yes", "on"):
        live, _cert = await issue(db, type_="operator", sub={"trust_domain": local_td, "name": slug,
                                                             "spiffe": spiffe_id, "url": operator_url},
                                  plan="", days=None, public_name=public_name)
        created = True
    held = await get_cert(db, "held")
    root = await get_cert(db, "root")
    states = await own_issued_states(db)
    return {
        "operator": None if live is None else {
            "certificate": live.jws, "hash": live.hash, "state": states.get(live.hash, live.state), "issued_now": created,
        },
        "network": None if held is None else {
            "certificate": held.jws, "chain": list(held.chain or []), "hash": held.hash,
            "state": ("genesis" if (held.type == "genesis" and root is not None and root.hash == held.hash) else held.state),
            "reason": held.state_reason, "checked_at": held.checked_at.isoformat() if held.checked_at else None,
        },
        "root": None if root is None else {"certificate": root.jws, "hash": root.hash},
        "policy": operator_policy(),
        "frame_trust_domain": local_td,
    }


async def install_from_parent(db, answer: Dict[str, Any]) -> Dict[str, Any]:
    """The operator side of `parent_answer_for_operator`: store the frame's network certificate as `held` (its state is
    the FRAME's verdict: an operator rides its frame), its own operator certificate as `held_operator`, and the root.
    Signatures are checked where this operator can check them; nothing is taken because the parent said so except the
    parent's own verdict about its network licence, which the operator has no other way to reach."""
    now = _now()
    out: Dict[str, Any] = {"network": None, "operator": None, "root": None}
    local_td = local_trust_domain()
    root_jws = ((answer.get("root") or {}).get("certificate")) or None
    # an operator follows its frame: with no network configured on the operator itself, the network is the one whose
    # root the parent (same trust domain, mTLS-authenticated) hands over. Its own env, when set, still wins.
    gtd = genesis_trust_domain()
    if not gtd and root_jws:
        try:
            gtd = load_cert(root_jws).sub_td
        except ValueError:
            gtd = ""
    if root_jws:
        root_cert, why = verify_root(root_jws, genesis_td=gtd, pin=genesis_cert_pin())
        if root_cert is not None:
            await store_cert(db, root_cert, role="root")
            out["root"] = root_cert.hash
        else:
            out["root"] = f"refused: {why}"
    net = answer.get("network") or {}
    if net.get("certificate"):
        try:
            cert = load_cert(net["certificate"])
            if cert.sub_td != local_td:
                raise ValueError(f"the frame's certificate names {cert.sub_td!r}, this operator is in {local_td!r}")
            row = await store_cert(db, cert, role="held", chain=[c for c in (net.get("chain") or []) if isinstance(c, str)])
            st = str(net.get("state") or "unverified")
            row.state = st if st in VERDICT_STATES else "unverified"
            row.state_reason = (f"the frame's verdict: {net.get('reason') or ''}")[:240]
            row.checked_at = now
            out["network"] = cert.hash
        except ValueError as exc:
            out["network"] = f"refused: {exc}"
    op = answer.get("operator") or {}
    if op.get("certificate"):
        frame_jws = net.get("certificate")
        v = evaluate_operator(op["certificate"], frame_cert_jws=frame_jws, frame_td=local_td,
                              lists={local_td: {"fetched_at": int(now.timestamp()),
                                                "states": {str(op.get("hash") or ""): str(op.get("state") or "")}}})
        try:
            cert = load_cert(op["certificate"])
            row = await store_cert(db, cert, role="held_operator")
            row.state, row.state_reason, row.checked_at = v.state, v.reason[:240], now
            out["operator"] = {"hash": cert.hash, "state": v.state, "reason": v.reason}
        except ValueError as exc:
            out["operator"] = f"refused: {exc}"
    await db.flush()
    return out


async def refresh_frame_cycle(db, *, peers: List[Any], fetch_json) -> Dict[str, Any]:
    """One cycle on a FRAME (the genesis included): the root, the genesis's list, this frame's own verdict, and a
    verdict about every ACTIVE peer's network licence. `fetch_json(peer, path)` returns (status, json) over the
    worker's own mTLS client for that peer. Writes rows through `db` (the caller commits). Never raises."""
    now = _now()
    now_ts = int(now.timestamp())
    local_td = local_trust_domain()
    gtd = genesis_trust_domain()
    pin = genesis_cert_pin()
    summary: Dict[str, Any] = {"at": now.isoformat(), "mode": licence_mode(), "genesis": gtd or None,
                               "local": local_td, "self": None, "peers": {}, "counts": {}, "notes": []}
    if not gtd:
        summary["notes"].append("FEDERATION_GENESIS_TRUST_DOMAIN is unset: no network is configured, nothing checked")
        _LAST_SUMMARY.clear(); _LAST_SUMMARY.update(summary)
        return summary
    root_row = await get_cert(db, "root")
    genesis_peer = next((p for p in peers if normalize_trust_domain(getattr(p, "trust_domain", "")) == gtd
                         and (getattr(p, "peer_type", "") or "").lower() == "frame"), None)
    # 1. the root
    if local_td != gtd and genesis_peer is not None:
        try:
            st, body = await fetch_json(genesis_peer, FED_OWN_PATH)
            cand = None
            if st == 200 and isinstance(body, dict):
                cand = body.get("certificate") if body.get("state") == "genesis" else None
            if cand:
                root_cert, why = verify_root(cand, genesis_td=gtd, pin=pin)
                if root_cert is None:
                    summary["notes"].append(f"the genesis offered a root that does not verify: {why}")
                elif root_row is None or root_row.hash == root_cert.hash:
                    root_row = await store_cert(db, root_cert, role="root")
                elif pin and root_cert.hash == pin:
                    root_row = await store_cert(db, root_cert, role="root")
                    summary["notes"].append("the root was replaced by the pinned FEDERATION_GENESIS_CERT_HASH")
                else:
                    summary["notes"].append(f"the genesis now offers another root {root_cert.hash[:16]} than the one "
                                            f"trusted here ({root_row.hash[:16]}); kept the old one (set "
                                            "FEDERATION_GENESIS_CERT_HASH to accept a new root)")
            elif st != 200:
                summary["notes"].append(f"the genesis's own licence answered HTTP {st}")
        except Exception as exc:  # noqa: BLE001 — one failed fetch never costs the cycle
            summary["notes"].append(f"root fetch failed: {type(exc).__name__}")
    root_jws = root_row.jws if root_row is not None else None
    # 2. the genesis's list
    if local_td == gtd:
        _LISTS[gtd] = {"fetched_at": now_ts, "states": await own_issued_states(db)}
    elif genesis_peer is not None and root_row is not None:
        try:
            st, body = await fetch_json(genesis_peer, FED_LIST_PATH)
            if st == 200 and isinstance(body, dict) and body.get("jws"):
                root_cert = load_cert(root_jws)
                payload, why = verify_list(str(body["jws"]), root_cert.key or {}, issuer_td=gtd)
                if payload is not None:
                    _LISTS[gtd] = {"fetched_at": now_ts, "states": list_states(payload)}
                else:
                    summary["notes"].append(f"the genesis's list was refused: {why}")
                    # loud: a refused list means revocations stop arriving and, after the max age, every licence
                    # reads `unverified` (which enforce allows); a note in a summary is not enough
                    logger.warning("[fedlicence] the genesis %s's licence list was REFUSED: %s (revocations do not "
                                   "arrive while this lasts)", gtd, why)
            else:
                summary["notes"].append(f"the genesis's list answered HTTP {st}")
        except Exception as exc:  # noqa: BLE001
            summary["notes"].append(f"list fetch failed: {type(exc).__name__}")
    elif genesis_peer is None and local_td != gtd:
        summary["notes"].append(f"no ACTIVE frame peer row for the genesis {gtd}: its root and list are not reachable")
    # 3. this frame's own verdict
    held = await get_cert(db, "held")
    if held is not None:
        v = evaluate(held.jws, list(held.chain or []), expect_trust_domain=local_td, root_jws=root_jws,
                     genesis_td=gtd, pin=pin, lists=_LISTS, now_ts=now_ts)
        held.state, held.state_reason, held.checked_at = v.state, v.reason[:240], now
        summary["self"] = {"state": v.state, "reason": v.reason, "hash": short_hash(held.hash)}
    else:
        summary["self"] = {"state": "unlicensed", "reason": "holds no network licence"}
    # 4. every peer
    no_licence_of_its_own: List[Any] = []
    for p in peers:
        td = normalize_trust_domain(getattr(p, "trust_domain", ""))
        if not td:
            continue
        if td == local_td:
            st_, why_, h_ = "same-domain", "this frame's own trust domain: not a crossing", None
        else:
            # agentvault2-41's review: the CERTIFICATE decides, whatever the card's own signature says: it is issuer-
            # signed and names the peer's trust domain, so an unverifiable card cannot hide a revoked licence behind
            # `unverified`. Only a card that is unverified AND presents no certificate stays `unverified`.
            card = getattr(p, "cached_registry_card", None) or {}
            lic = ((card.get("federation") or {}).get("licence") or {}) if isinstance(card, dict) else {}
            if not isinstance(lic, dict):
                lic = {}
            card_ok = bool(getattr(p, "card_signature_verified", False))
            cert_jws = lic.get("certificate")
            if not cert_jws:
                no_licence_of_its_own.append(p)
            if cert_jws and lic.get("hash") and licence_hash(str(cert_jws)) != str(lic.get("hash")).strip().lower():
                st_, why_, h_ = "invalid", "the card's signed hash does not match the certificate it carries", lic.get("hash")
            elif not cert_jws and not card_ok:
                st_, why_, h_ = "unverified", "the peer's card signature is not verified here and it presents no licence", None
            else:
                v = evaluate(cert_jws, lic.get("chain") or [], expect_trust_domain=td, root_jws=root_jws,
                             genesis_td=gtd, pin=pin, lists=_LISTS, now_ts=now_ts)
                st_, why_, h_ = v.state, v.reason, v.hash
                if not card_ok:
                    why_ = f"{why_} (the peer's card signature is not verified here; the certificate decided)"
        p.licence_state, p.licence_reason, p.licence_hash, p.licence_checked_at = st_, why_[:240], h_, now
    # 5. agentvault2-a4 (the V0478 sandbox proof): the crossing check resolves each trust domain from its ACTIVE frame
    # rows (core.mtls_auth.licence_states_from_peer_rows; other rows only where a domain has no frame row), but this
    # summary named every ROW in a refused state. Another frame's operator that had not installed its licence yet read
    # `unlicensed` and was listed in would_refuse (and `refused` under enforce) while every crossing from its trust
    # domain was allowed. The report now resolves with the crossing check's own function, and an operator row that
    # presents no licence of its own shows the verdict of the frame it rides, and says so.
    from ..core.mtls_auth import licence_states_from_peer_rows
    rows = [((getattr(p, "peer_type", "") or ""), (getattr(p, "status", None) or "ACTIVE"),
             normalize_trust_domain(getattr(p, "trust_domain", "")), getattr(p, "licence_state", None)) for p in peers]
    domains = {td: st_ for td, st_ in licence_states_from_peer_rows(rows).items() if td != local_td}
    frame_rows: Dict[str, List[Any]] = {}
    for p in peers:
        td = normalize_trust_domain(getattr(p, "trust_domain", ""))
        if td and td != local_td and (getattr(p, "peer_type", "") or "").lower() == "frame" and p.licence_state:
            frame_rows.setdefault(td, []).append(p)
    for p in no_licence_of_its_own:
        td = normalize_trust_domain(getattr(p, "trust_domain", ""))
        if (getattr(p, "peer_type", "") or "").lower() == "frame" or td not in frame_rows:
            continue
        rides = next((f for f in frame_rows[td] if f.licence_state == domains.get(td)), frame_rows[td][0])
        p.licence_state, p.licence_hash = rides.licence_state, rides.licence_hash
        p.licence_reason = (f"presents no licence of its own; rides its frame {getattr(rides, 'name', td)}'s network "
                            f"licence ({rides.licence_state})")[:240]
    counts: Dict[str, int] = {}
    refused: List[str] = []
    for p in peers:
        td = normalize_trust_domain(getattr(p, "trust_domain", ""))
        if not td or getattr(p, "licence_state", None) is None:
            continue
        name = getattr(p, "name", td)
        summary["peers"][name] = p.licence_state
        counts[p.licence_state] = counts.get(p.licence_state, 0) + 1
        if td != local_td and domains.get(td) in REFUSED_STATES:
            refused.append(name)
    summary["counts"] = counts
    summary["domains"] = domains
    summary["would_refuse" if summary["mode"] != "enforce" else "refused"] = sorted(refused)
    await db.flush()
    _LAST_SUMMARY.clear(); _LAST_SUMMARY.update(summary)
    return summary


# the verdicts `enforce` refuses. `unverified` is NOT refused on purpose: a genesis outage (its list unreachable)
# must never partition the network; it is counted, reported and alerted instead.
REFUSED_STATES = ("unlicensed", "expired", "revoked", "suspended", "invalid")


async def install_network_licence(db, certificate: str, chain: List[str]) -> Tuple[Any, Verdict]:
    """Install the network licence a genesis issued to THIS frame (from the finalize callback or the admin route). It
    must name this frame's trust domain and carry this frame's own licence-signing key; the chain's root must be a
    self-signed genesis for the configured network (and match the pin, and the root already trusted here). Returns
    (row, verdict); raises ValueError with the refusal sentence."""
    local_td = local_trust_domain()
    gtd = genesis_trust_domain()
    cert = load_cert(certificate)
    if cert.type != "frame" or cert.sub_td != local_td:
        raise ValueError(f"a {cert.type} licence for {cert.sub_td!r} is not this frame's network licence ({local_td})")
    own_key = await active_key_jwk(db)
    if not own_key or not cert.key or jwk_thumbprint(cert.key) != jwk_thumbprint(own_key):
        raise ValueError("the licence does not carry this frame's licence-signing key (it was issued for another key, "
                         "or this frame has no key yet)")
    root_jws = next((c for c in (chain or []) if isinstance(c, str)), None)
    root, why = verify_root(root_jws, genesis_td=gtd, pin=genesis_cert_pin())
    if root is None:
        raise ValueError(f"the chain's root does not verify: {why}")
    if not verify_jws(cert.jws, root.key or {}):
        raise ValueError("the genesis signature on the licence does not verify")
    # agentvault2-41's review: a delivered chain must never INTRODUCE a root. The finalize callback is authenticated by
    # the invitation nonce, not by SPIFFE, so the frame that approved could be any frame, not the genesis. A new root is
    # trusted only through the pin, or when the sync cycle fetches it from the genesis over mTLS (SPIFFE proves who
    # answered). Until then the licence is held `unverified` and says why.
    pin = genesis_cert_pin()
    existing_root = await get_cert(db, "root")
    trusted_root: Optional[Cert] = None
    if existing_root is not None:
        if existing_root.hash != root.hash and pin != root.hash:
            raise ValueError("the chain's root differs from the root this frame already trusts")
        trusted_root = root
    elif pin and root.hash == pin:
        trusted_root = root
    if trusted_root is not None:
        await store_cert(db, trusted_root, role="root")
    row = await store_cert(db, cert, role="held", chain=[root.jws])
    if trusted_root is not None:
        v = evaluate(cert.jws, [root.jws], expect_trust_domain=local_td, root_jws=trusted_root.jws, genesis_td=gtd,
                     pin=pin, lists=_LISTS)
    else:
        v = Verdict("unverified", "the network's root is not trusted here yet: the next sync cycle fetches it from the "
                                  "genesis over mTLS (or set FEDERATION_GENESIS_CERT_HASH)",
                    hash=cert.hash, type=cert.type, plan=cert.plan, issuer=cert.iss_td,
                    network=normalize_trust_domain(cert.payload.get("network")) or None, expires_at=cert.exp)
    row.state, row.state_reason, row.checked_at = v.state, v.reason[:240], _now()
    await db.flush()
    logger.info("[fedlicence] installed this frame's network licence %s (verdict %s: %s)", cert.hash[:16], v.state,
                v.reason)
    return row, v


def presented_verdict(certificate: Optional[str], chain: Optional[List[str]], *, expect_trust_domain: str,
                      root_jws: Optional[str]) -> Verdict:
    """The verdict about a certificate an INITIATOR presents with its invitation (the approve's enforce check)."""
    return evaluate(certificate, chain or [], expect_trust_domain=expect_trust_domain, root_jws=root_jws,
                    genesis_td=genesis_trust_domain(), pin=genesis_cert_pin(), lists=_LISTS)
