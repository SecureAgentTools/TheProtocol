"""Offline verifier of an organization's signed release report and of a signed change record (V0667 D7, order gwo_0f317438b7dfc6dfacd3e9b7).

The registry serves, for a release line of an organization (a code distribution), a signed ENVELOPE:

    {"envelope_version": 1, "registry_spiffe_id": ..., "kind": "distribution.release.report" | "distribution.change.record", "subject": <the release or the change id>,
     "digest": <sha256 hex of the canonical JSON of "report">, "report": {...},
     "signature": {"alg": "EdDSA", "kid": "<spiffe_id>#<rotation_seq>", "signed_canonical": [...], "value": <base64url>}}

The signature is the registry's card key's (the key published at /.well-known/registry-jwks.json) over the canonical JSON of {registry_spiffe_id, kind, subject, digest}. Canonical JSON is the registry card's
own: ``json.dumps(doc, sort_keys=True, separators=(",", ":"))`` (non-ASCII escaped), UTF-8.

``verify_distribution_envelope(envelope, jwks)`` needs the document and the registry's published keys, and nothing else: no network. It answers (ok, reason):

  digest    the report's digest is not the envelope's: one byte of the report changed (or it was added to or cut)
  signature the signature does not verify with the key the kid names (a re-made digest over an altered report lands here)
  no_key    the JWKS holds no key of that kid
  kind      the kind is not one of the two, or the report does not say the same kind as the envelope
  counts    the report's own counts disagree with the changes it lists (signed, but the registry's own statement contradicts itself)
  signed_fields the document names another list of signed fields than the four this verifier checks
  malformed anything else wrong with the shape; never an exception

The list of signed fields is THIS module's, never the document's: a document that names any other list (only the digest, say) is refused (signed_fields).

Command line:  python -m theprotocol.registry.distribution_report <document.json> <jwks.json>   exits 0 and prints VALID, or 1 and prints NOT VALID and why.
Requires ``cryptography`` (pip install 'theprotocol-sdk[anp]').
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

REPORT_KIND = "distribution.release.report"
RECORD_KIND = "distribution.change.record"
SIGNED_PATHS = ["registry_spiffe_id", "kind", "subject", "digest"]


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: Optional[str] = None
    kind: Optional[str] = None
    subject: Optional[str] = None
    changes: Optional[int] = None

    def __bool__(self) -> bool:
        return self.ok


def _canonical(doc: Any) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _b64url_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _no(reason: str) -> VerifyResult:
    return VerifyResult(False, reason)


def verify_distribution_envelope(envelope: Any, jwks: Any) -> VerifyResult:
    """Verify a signed release report or change record against the registry's published keys. Never raises on malformed input; ImportError only when ``cryptography`` is missing."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:  # pragma: no cover - env-dependent
        raise ImportError("verify_distribution_envelope requires the 'cryptography' package (pip install 'theprotocol-sdk[anp]')") from e
    if not isinstance(envelope, dict) or not isinstance(jwks, dict):
        return _no("malformed")
    report, digest, sig = envelope.get("report"), envelope.get("digest"), envelope.get("signature")
    kind, subject = envelope.get("kind"), envelope.get("subject")
    if not isinstance(report, dict) or not isinstance(digest, str) or not isinstance(sig, dict) or not isinstance(sig.get("kid"), str) or not isinstance(sig.get("value"), str):
        return _no("malformed")
    if kind not in (REPORT_KIND, RECORD_KIND) or report.get("kind") != kind or not isinstance(subject, str):
        return _no("kind")
    if sig.get("signed_canonical") != SIGNED_PATHS:
        return _no("signed_fields")
    if hashlib.sha256(_canonical(report)).hexdigest() != digest:
        return _no("digest")
    keys = jwks.get("keys")
    jwk = next((k for k in keys if isinstance(k, dict) and k.get("kid") == sig["kid"]), None) if isinstance(keys, list) else None
    if jwk is None:
        return _no("no_key")
    try:
        public = Ed25519PublicKey.from_public_bytes(_b64url_dec(str(jwk["x"])))
        public.verify(_b64url_dec(sig["value"]), _canonical({p: envelope.get(p) for p in SIGNED_PATHS}))
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return _no("signature")
    changes: Optional[int] = None
    if kind == REPORT_KIND:
        listed = report.get("changes")
        counts = report.get("counts")
        if not isinstance(listed, list) or not isinstance(counts, dict) or counts.get("changes") != len(listed):
            return _no("counts")
        changes = len(listed)
    else:
        changes = 1 if isinstance(report.get("change"), dict) else 0
    return VerifyResult(True, None, kind, subject, changes)


def verify_files(document_path: str, jwks_path: str) -> VerifyResult:
    with open(document_path, "r", encoding="utf-8") as f:
        envelope = json.load(f)
    with open(jwks_path, "r", encoding="utf-8") as f:
        jwks = json.load(f)
    return verify_distribution_envelope(envelope, jwks)


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m theprotocol.registry.distribution_report <document.json> <jwks.json>")
        return 2
    try:
        r = verify_files(args[0], args[1])
    except (OSError, ValueError) as e:
        print(f"NOT VALID: {e}")
        return 1
    if r.ok:
        print(f"VALID: {r.kind} {r.subject} ({r.changes} change(s)), signed by the registry's published key")
        return 0
    print(f"NOT VALID: {r.reason}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
