"""WEBAUTHN (2026-07-25) — biometric-ENFORCED confirmations for the Cockpit Card.

Why this replaces the WebCrypto signing path: a non-extractable WebCrypto key proves the private
key cannot be stolen, but nothing in WebCrypto requires a human to be present when it is USED. It
signs silently. For a liability confirmation that is the wrong primitive — the whole claim we want
to make is "a specific human authorised this specific action".

WebAuthn makes that claim checkable. A platform credential created with
`userVerification: "required"` lives in the phone's hardware keystore (Secure Enclave / StrongBox)
and the OS refuses to produce an assertion without a fingerprint or device PIN. The proof is not a
promise from our JavaScript: bit 2 of `authenticatorData.flags` is the **UV bit**, set by the
authenticator itself and covered by the signature. We verify it server-side and reject the
assertion when it is clear — so an attacker who controls the page still cannot fabricate presence.

Signature is over `authenticatorData ‖ SHA256(clientDataJSON)` (WebAuthn §6.3.3). The challenge we
issued is echoed inside clientDataJSON, so a signature cannot be replayed onto a different action.

Standards only: W3C WebAuthn. No vendor, no account, no cost.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# authenticatorData flag bits (WebAuthn §6.1)
FLAG_UP = 0x01   # user present
FLAG_UV = 0x04   # user VERIFIED — biometric or device PIN actually happened
FLAG_AT = 0x40   # attested credential data included (a registration carries the new key)

_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


class RegistrationRefused(ValueError):
    """A registration response this server does not bind; the message is a short reason a caller may show."""


def b64u_decode(data: str) -> bytes:
    if isinstance(data, bytes):
        data = data.decode("ascii")
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _cose_to_public_key(cose: bytes):
    """Extract an EC P-256 public key from a COSE_Key (alg -7 / ES256).

    Minimal CBOR walk rather than a cbor2 dependency: a COSE EC2 key is a small fixed map and we
    only need the two 32-byte coordinates. Anything that is not ES256/P-256 is refused outright —
    silently accepting an unknown algorithm is how verification becomes theatre.
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    x = y = None
    # labels: -2 = x, -3 = y (negative ints encode as 0x21, 0x22 in CBOR major type 1)
    i = 0
    n = len(cose)
    while i < n - 2:
        if cose[i] in (0x21, 0x22) and cose[i + 1] == 0x58 and cose[i + 2] == 0x20:
            coord = cose[i + 3: i + 35]
            if cose[i] == 0x21:
                x = coord
            else:
                y = coord
            i += 35
            continue
        i += 1
    if not x or not y or len(x) != 32 or len(y) != 32:
        raise ValueError("unsupported COSE key (expected ES256 / P-256)")
    return ec.EllipticCurvePublicNumbers(
        int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
    ).public_key()


def rp_id_hash(rp_id: str) -> bytes:
    """The 32 bytes an authenticator puts at the head of authenticatorData for this origin."""
    return hashlib.sha256(rp_id.encode()).digest()


def match_rp_id(candidate_hash: bytes, expected_rp_ids) -> Optional[str]:
    """Which of OUR origins this signature was made for, or None.

    A deployment is reachable at several hostnames (here: registry./api./theprotocol.cloud), and
    the browser bakes whichever one the user happened to be on into every signature. Pinning a
    single configured host silently breaks every credential enrolled on any of the others. The
    security property is unchanged: the hash must match a host WE serve, and the list is built
    from configuration, never from the request alone.
    """
    if isinstance(expected_rp_ids, str):
        expected_rp_ids = [expected_rp_ids]
    for rid in expected_rp_ids:
        if rid and candidate_hash == rp_id_hash(rid):
            return rid
    return None


def parse_attestation_public_key(attestation_object_b64u: str) -> Tuple[str, str, bytes]:
    """From a registration response, pull out (credential_id_b64u, cose_public_key_b64u, rp_id_hash).

    We do NOT verify the attestation statement: we are not attesting device provenance, only
    binding a key the user just created on a device they control. Claiming otherwise would be
    the sort of overstatement this whole feature exists to avoid.
    """
    cred_id, cose_key, rp_hash, _flags = parse_attestation(attestation_object_b64u)
    return cred_id, cose_key, rp_hash


def parse_attestation(attestation_object_b64u: str) -> Tuple[str, str, bytes, int]:
    """parse_attestation_public_key plus the authenticatorData flags byte (what verify_registration checks)."""
    raw = b64u_decode(attestation_object_b64u)
    # authData sits inside the CBOR map under key "authData"; locate it by its label bytes.
    marker = b"authData"
    idx = raw.find(marker)
    if idx < 0:
        raise ValueError("attestationObject missing authData")
    p = idx + len(marker)
    # byte-string header: 0x58 <len8> | 0x59 <len16>
    if raw[p] == 0x58:
        length = raw[p + 1]; p += 2
    elif raw[p] == 0x59:
        length = int.from_bytes(raw[p + 1:p + 3], "big"); p += 3
    else:
        raise ValueError("unexpected authData encoding")
    auth_data = raw[p:p + length]
    # rpIdHash(32) flags(1) signCount(4) aaguid(16) credIdLen(2) credId credPubKey
    if len(auth_data) < 55:
        raise ValueError("authData too short (no attested credential)")
    cred_len = int.from_bytes(auth_data[53:55], "big")
    cred_id = auth_data[55:55 + cred_len]
    cose_key = auth_data[55 + cred_len:]
    _cose_to_public_key(cose_key)  # fail fast on anything we cannot verify later
    # The rp hash comes back too so the caller can refuse to store a credential minted for an
    # origin we do not serve — otherwise it would enrol cleanly and fail every signature later.
    return b64u_encode(cred_id), b64u_encode(cose_key), auth_data[:32], auth_data[32]


def client_data_challenge(client_data_json_b64u: str) -> Optional[str]:
    """The challenge the browser echoed in clientDataJSON (base64url, unpadded), or None when unreadable."""
    try:
        cd = json.loads(b64u_decode(client_data_json_b64u))
    except Exception:
        return None
    ch = cd.get("challenge") if isinstance(cd, dict) else None
    return ch.rstrip("=") if isinstance(ch, str) and ch else None


def origin_on_rp(origin: Any, rp_id: str) -> bool:
    """Is `origin` (clientDataJSON's) a page of the RP ID the credential was made for: https on that host or one of
    its subdomains, or plain http on loopback (a local browser, the E2E harness)."""
    from urllib.parse import urlparse
    try:
        u = urlparse(str(origin or ""))
    except Exception:
        return False
    host = (u.hostname or "").lower()
    rp = (rp_id or "").lower()
    if not host or not rp or not (host == rp or host.endswith("." + rp)):
        return False
    return u.scheme == "https" or (u.scheme == "http" and host in _LOOPBACK_HOSTS)


def verify_registration(*, attestation_object_b64u: str, client_data_json_b64u: str,
                        expected_challenge_b64u: str, expected_rp_ids) -> Tuple[str, str, str]:
    """Verify one registration response (attestation "none") and return (credential_id_b64u, cose_public_key_b64u,
    rp_id). Raises RegistrationRefused naming what failed.

    WebAuthn §7.1, the parts that matter without attestation: the ceremony is a create, the challenge is the one this
    server issued, the page was ours and not framed cross-origin, the key was made for an RP ID we serve, and the
    authenticator says a person was present AND verified (the same UV bit every later assertion must carry).
    """
    try:
        cd = json.loads(b64u_decode(client_data_json_b64u))
    except Exception:
        raise RegistrationRefused("client_data_unparseable")
    if not isinstance(cd, dict) or cd.get("type") != "webauthn.create":
        raise RegistrationRefused("wrong_ceremony_type")
    got = cd.get("challenge")
    if not isinstance(got, str) or not got or got.rstrip("=") != (expected_challenge_b64u or "").rstrip("="):
        raise RegistrationRefused("challenge_mismatch")
    if cd.get("crossOrigin") is True:
        raise RegistrationRefused("cross_origin")
    try:
        cred_id, cose_key, rp_hash, flags = parse_attestation(attestation_object_b64u)
    except Exception as exc:
        raise RegistrationRefused(f"unsupported_credential: {exc}")
    rp_id = match_rp_id(rp_hash, expected_rp_ids)
    if rp_id is None:
        raise RegistrationRefused("rp_id_mismatch")
    if not origin_on_rp(cd.get("origin"), rp_id):
        raise RegistrationRefused("origin_mismatch")
    if not (flags & FLAG_UP):
        raise RegistrationRefused("user_not_present")
    if not (flags & FLAG_UV):
        raise RegistrationRefused("user_verification_missing")
    if not (flags & FLAG_AT):
        raise RegistrationRefused("no_attested_credential")
    return cred_id, cose_key, rp_id


def verify_assertion(*, cose_public_key_b64u: str, client_data_json_b64u: str,
                     authenticator_data_b64u: str, signature_b64u: str,
                     expected_challenge_b64u: str, expected_rp_ids,
                     require_uv: bool = True) -> Tuple[bool, Optional[str], Optional[int]]:
    """Verify one WebAuthn assertion. Returns (ok, reason_if_not, new_sign_count).

    `expected_rp_ids` is every hostname this deployment serves the app from (a single string is
    also accepted). See `match_rp_id`.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        client_data_raw = b64u_decode(client_data_json_b64u)
        client_data = json.loads(client_data_raw)
    except Exception:
        return False, "client_data_unparseable", None

    if client_data.get("type") != "webauthn.get":
        return False, "wrong_ceremony_type", None

    # The challenge is echoed by the AUTHENTICATOR-signed client data, so this binds the
    # signature to the exact action we asked about — it cannot be replayed onto another.
    got = (client_data.get("challenge") or "").rstrip("=")
    if got != expected_challenge_b64u.rstrip("="):
        return False, "challenge_mismatch", None

    try:
        auth_data = b64u_decode(authenticator_data_b64u)
    except Exception:
        return False, "auth_data_unparseable", None
    if len(auth_data) < 37:
        return False, "auth_data_too_short", None

    got_rp_hash = auth_data[:32]
    flags = auth_data[32]
    sign_count = int.from_bytes(auth_data[33:37], "big")

    if match_rp_id(got_rp_hash, expected_rp_ids) is None:
        return False, "rp_id_mismatch", None
    if not (flags & FLAG_UP):
        return False, "user_not_present", None
    # THE point of the exercise: the authenticator asserts a biometric/PIN actually happened.
    if require_uv and not (flags & FLAG_UV):
        return False, "user_verification_missing", None

    try:
        pub = _cose_to_public_key(b64u_decode(cose_public_key_b64u))
        signed = auth_data + hashlib.sha256(client_data_raw).digest()
        pub.verify(b64u_decode(signature_b64u), signed, ec.ECDSA(hashes.SHA256()))
    except Exception:
        return False, "bad_signature", None

    return True, None, sign_count
