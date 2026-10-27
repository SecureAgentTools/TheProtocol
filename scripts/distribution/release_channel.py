"""§RELEASECHANNEL: the kit's reader of the signed release channel (frame-update.py imports it beside itself).

The same document, the same public key and the same version rules as the registry's
`agentvault_registry/core/release_channel.py` (tests pin the key identical; the vectors in the CLI's tests pin the
rules). Nothing in a document is trusted before its signature verifies: unsigned or altered means "no channel".
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

RELEASE_PUBKEY_B64 = "uo4QBdIX1BlSn3Kq08My/ba0+ZLroVWWz/vqnJliVIQ="
SCHEMA = "theprotocol-release/1"
DEFAULT_URL = "https://theprotocol.cloud/downloads/frame-kit/latest.json"
KINDS = ("stable", "hotfix", "security")
KIND_RANK = {"stable": 0, "hotfix": 1, "security": 2}
MAX_BYTES = 1_000_000

_KIT_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?$")
_SOFTWARE_VERSION_RE = re.compile(r"V(\d{3,6})$")
_PRE_RANK = {"alpha": 0, "beta": 1, "rc": 2}


def canonical(doc: Dict[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def kid_of(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:16]


def verify(doc: Any, pubkey_b64: Optional[str] = None) -> Tuple[bool, str]:
    """(ok, reason). Never raises."""
    if not isinstance(doc, dict):
        return False, "not a JSON object"
    sig = doc.get("signature")
    if not isinstance(sig, dict):
        return False, "unsigned"
    if sig.get("alg") != "Ed25519":
        return False, f"unsupported signature algorithm {sig.get('alg')!r}"
    try:
        pub = base64.b64decode(pubkey_b64 or RELEASE_PUBKEY_B64)
        if len(pub) != 32:
            return False, "the release public key is not a 32-byte Ed25519 key"
        if sig.get("kid") and sig.get("kid") != kid_of(pub):
            return False, "signed by a key this reader does not carry"
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(str(sig.get("sig") or "")), canonical(doc))
    except Exception as exc:  # noqa: BLE001
        return False, f"signature does not verify ({type(exc).__name__})"
    if doc.get("schema") != SCHEMA:
        return False, f"unknown schema {doc.get('schema')!r}"
    rels = doc.get("releases")
    if not isinstance(rels, list) or not rels or not all(isinstance(r, dict) and r.get("version") for r in rels):
        return False, "no releases"
    for r in rels:
        if r.get("kind") not in KINDS:
            return False, f"release {r.get('version')} has an unknown kind {r.get('kind')!r}"
    return True, "ok"


def parse_kit_version(s: Optional[str]) -> Optional[Tuple[int, int, int, int, int]]:
    m = _KIT_VERSION_RE.match((s or "").strip())
    if not m:
        return None
    major, minor, patch, pre, n = m.groups()
    return (int(major), int(minor), int(patch), _PRE_RANK[pre] if pre else 3, int(n) if n else 0)


def parse_software_version(s: Optional[str]) -> Optional[int]:
    m = _SOFTWARE_VERSION_RE.search((s or "").strip())
    return int(m.group(1)) if m else None


def is_newer(candidate: Dict[str, Any], running: Dict[str, Any]) -> Optional[bool]:
    rk, ck = parse_kit_version(running.get("kit_version")), parse_kit_version(candidate.get("version"))
    if rk is not None and ck is not None:
        return ck > rk
    rs = parse_software_version(running.get("software_version"))
    cs = parse_software_version(candidate.get("registry_software_version"))
    if rs is not None and cs is not None:
        return cs > rs
    return None


def running_from_version_string(local: Optional[str]) -> Dict[str, Any]:
    """An operator's VERSION line is either a kit version (the public lineage) or a software version string (the
    author's own lineage); `is_newer` compares like with like."""
    if parse_kit_version(local):
        return {"kit_version": local, "software_version": None}
    return {"kit_version": None, "software_version": local}


def assess(doc: Dict[str, Any], running: Dict[str, Any]) -> Dict[str, Any]:
    releases = [r for r in (doc.get("releases") or []) if isinstance(r, dict) and r.get("version")]
    latest = releases[0] if releases else None
    newer: List[Dict[str, Any]] = []
    comparable = True
    for r in releases:
        verdict = is_newer(r, running)
        if verdict is None:
            comparable = False
            continue
        if verdict:
            newer.append(r)
    kind = "stable"
    for r in newer:
        if KIND_RANK.get(r.get("kind"), 0) > KIND_RANK[kind]:
            kind = r["kind"]
    return {"latest": latest, "newer": newer, "update_available": bool(newer), "kind": kind if newer else None,
            "comparable": comparable}


def find_release(doc: Dict[str, Any], version: str) -> Optional[Dict[str, Any]]:
    for r in doc.get("releases") or []:
        if isinstance(r, dict) and r.get("version") == version:
            return r
    return None
