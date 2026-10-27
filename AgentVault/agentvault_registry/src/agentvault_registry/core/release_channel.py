"""§RELEASECHANNEL (his words 2026-09-21: "we need a channel that we provide updated images to pull ... so the
operator/admins get a notification about a hot fix or new stable version they can schedule the rollout themselfs").

The release channel is ONE signed JSON document at a public URL (`latest.json`), written by scripts/frame_kit/publish.py
on the author's host and read by three readers that all carry the same public key and the same rules: this module
(the registry's checker, background_tasks/release_channel_checker.py), the operator CLI (`tp update`) and the kit
(`frame-update.py`). Nothing in it is trusted before its signature verifies against RELEASE_PUBKEY_B64: an unsigned
or altered document is "no channel", never "a release".

    {"schema": "theprotocol-release/1", "generated_at": ..., "version": "<newest>",
     "releases": [{"version", "kind": stable|hotfix|security, "released_at", "registry_software_version",
                   "kit": {"filename", "sha256", "size_bytes", "url"},
                   "images": {"prefix", "tag", "digests": {name: "sha256:..."}},
                   "min_upgrade_from", "rollback", "notes", "notes_url"}, ...newest first],
     "signature": {"alg": "Ed25519", "kid": "...", "sig": "<base64>"}}

The signature covers the canonical JSON (sorted keys, no spaces, UTF-8) of the document WITHOUT its `signature` member.

Everything here is OFF unless switched on, and nothing here opens anything:
  RELEASE_CHANNEL_CHECK_ENABLED   the checker worker (default false; the kit's env template sets it for a new frame)
  RELEASE_CHANNEL_URL             where the document is read from (default DEFAULT_URL)
  RELEASE_CHANNEL_PUBLIC_PULL     the image registry's token server issues ANONYMOUS pull tokens for the public
                                  namespace (default false; a file at RELEASE_CHANNEL_PUBLIC_PULL_FILE turns it on
                                  without a recreate, for the day everything goes up at once)
  RELEASE_CHANNEL_PUBLIC_NAMESPACE the namespace the release images live under (default "theprotocol")
  RELEASE_CHANNEL_STATE_PATH      the checker's state (default /app/data/release_channel.json, the data volume)

Version rules, shared by every reader:
  * a KIT version reads `1.0.0-beta.10` (major.minor.patch, optional `-alpha.N|-beta.N|-rc.N`); a final release is
    newer than any pre-release of the same triple;
  * a registry built by the kit knows its kit version from /app/BUILD_INFO.json (`kit_version`); a registry built from
    the source tree does not, and compares the channel's `registry_software_version` (…V0416) with its own
    BUNDLED_IMAGE_TAG by the trailing number;
  * "newer" is decided on kit versions when both sides carry one, else on the software version number; a document
    that carries neither comparable field is "unknown", never "up to date".
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# The release signing key's PUBLIC half (Ed25519, raw, base64). The private half lives on the author's host and never
# in any repository; the CLI (tools/operator-cli/tp_operator/release_channel.py) and the kit
# (scripts/distribution/release_channel.py) carry the same value, pinned identical by tests/test_release_channel.py.
RELEASE_PUBKEY_B64 = "uo4QBdIX1BlSn3Kq08My/ba0+ZLroVWWz/vqnJliVIQ="
RELEASE_KID = "051f2f9b99798ca9"
SCHEMA = "theprotocol-release/1"
DEFAULT_URL = "https://theprotocol.cloud/downloads/frame-kit/latest.json"
KINDS = ("stable", "hotfix", "security")
KIND_RANK = {"stable": 0, "hotfix": 1, "security": 2}
MAX_BYTES = 1_000_000
DEFAULT_STATE_PATH = "/app/data/release_channel.json"
DEFAULT_PUBLIC_PULL_FILE = "/app/data/release_channel_public_pull"
DEFAULT_PUBLIC_NAMESPACE = "theprotocol"

_KIT_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?$")
_SOFTWARE_VERSION_RE = re.compile(r"V(\d{3,6})$")
_PRE_RANK = {"alpha": 0, "beta": 1, "rc": 2}


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def channel_url() -> str:
    return (os.getenv("RELEASE_CHANNEL_URL") or "").strip() or DEFAULT_URL


def check_enabled() -> bool:
    return _truthy(os.getenv("RELEASE_CHANNEL_CHECK_ENABLED"))


def public_namespace() -> str:
    ns = (os.getenv("RELEASE_CHANNEL_PUBLIC_NAMESPACE") or "").strip().strip("/")
    return ns or DEFAULT_PUBLIC_NAMESPACE


def public_pull_enabled() -> bool:
    """Anonymous pull of the public namespace: the env, or the switch file's presence (no recreate on the day)."""
    if _truthy(os.getenv("RELEASE_CHANNEL_PUBLIC_PULL")):
        return True
    path = (os.getenv("RELEASE_CHANNEL_PUBLIC_PULL_FILE") or "").strip() or DEFAULT_PUBLIC_PULL_FILE
    try:
        return os.path.isfile(path)
    except OSError:
        return False


def state_path() -> str:
    return (os.getenv("RELEASE_CHANNEL_STATE_PATH") or "").strip() or DEFAULT_STATE_PATH


# ---------------------------------------------------------------------------------------------------------------------
# The document: canonical form, signature, shape
# ---------------------------------------------------------------------------------------------------------------------
def canonical(doc: Dict[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pubkey_bytes(pubkey_b64: Optional[str] = None) -> bytes:
    """The baked key, unless RELEASE_CHANNEL_PUBKEY_B64 names another (an operator running a private channel for
    frames of their own, and the tests, which sign with a key of their own)."""
    raw = base64.b64decode(pubkey_b64 or (os.getenv("RELEASE_CHANNEL_PUBKEY_B64") or "").strip() or RELEASE_PUBKEY_B64)
    if len(raw) != 32:
        raise ValueError("the release public key is not a 32-byte Ed25519 key")
    return raw


def kid_of(pub: bytes) -> str:
    return hashlib.sha256(pub).hexdigest()[:16]


def verify(doc: Any, pubkey_b64: Optional[str] = None) -> Tuple[bool, str]:
    """(ok, reason). Never raises: a document that cannot be verified is reported, not trusted."""
    if not isinstance(doc, dict):
        return False, "not a JSON object"
    sig = doc.get("signature")
    if not isinstance(sig, dict):
        return False, "unsigned"
    if sig.get("alg") != "Ed25519":
        return False, f"unsupported signature algorithm {sig.get('alg')!r}"
    try:
        pub = pubkey_bytes(pubkey_b64)
        if sig.get("kid") and sig.get("kid") != kid_of(pub):
            return False, "signed by a key this reader does not carry"
        raw_sig = base64.b64decode(str(sig.get("sig") or ""))
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(pub).verify(raw_sig, canonical(doc))
    except Exception as exc:  # noqa: BLE001 — every failure is one answer: not verified
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


def sign(doc: Dict[str, Any], private_key_pem: bytes) -> Dict[str, Any]:
    """The writer's half (publish.py). Returns a copy carrying `signature`."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("the release signing key is not an Ed25519 key")
    body = {k: v for k, v in doc.items() if k != "signature"}
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    sig = key.sign(canonical(body))
    body["signature"] = {"alg": "Ed25519", "kid": kid_of(pub), "sig": base64.b64encode(sig).decode("ascii")}
    return body


# ---------------------------------------------------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------------------------------------------------
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
    """Is the release `candidate` newer than what `running` describes? None when the two cannot be compared."""
    rk, ck = parse_kit_version(running.get("kit_version")), parse_kit_version(candidate.get("version"))
    if rk is not None and ck is not None:
        return ck > rk
    rs = parse_software_version(running.get("software_version"))
    cs = parse_software_version(candidate.get("registry_software_version"))
    if rs is not None and cs is not None:
        return cs > rs
    return None


def running_versions() -> Dict[str, Any]:
    """What THIS registry runs: its kit version when the image was built by the kit, and its software version."""
    out: Dict[str, Any] = {"kit_version": None, "software_version": None}
    try:
        from agentvault_registry.core.registry_identity import BUNDLED_IMAGE_TAG
        out["software_version"] = BUNDLED_IMAGE_TAG
    except Exception:  # noqa: BLE001
        pass
    try:
        with open(os.getenv("KIT_BUILD_INFO_PATH", "/app/BUILD_INFO.json"), encoding="utf-8") as f:
            info = json.load(f)
        if isinstance(info, dict) and info.get("kit_version"):
            out["kit_version"] = str(info["kit_version"])
            out["modified_build"] = bool(info.get("modified"))
    except (OSError, ValueError):
        pass
    return out


def assess(doc: Dict[str, Any], running: Dict[str, Any]) -> Dict[str, Any]:
    """The verdict every reader shares. `latest` is the newest release; `newer` those newer than `running`, newest
    first; `kind` the strongest kind among them (security > hotfix > stable); `comparable` says whether the running
    version could be compared at all (a reader must show "unknown", never "up to date", when it is False)."""
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
    return {"latest": _summary(latest) if latest else None, "newer": [_summary(r) for r in newer],
            "update_available": bool(newer), "kind": kind if newer else None, "comparable": comparable}


def _summary(r: Dict[str, Any]) -> Dict[str, Any]:
    kit, images = r.get("kit") or {}, r.get("images") or {}
    return {
        "version": r.get("version"), "kind": r.get("kind"), "released_at": r.get("released_at"),
        "registry_software_version": r.get("registry_software_version"),
        "kit_url": kit.get("url"), "kit_sha256": kit.get("sha256"),
        "images_prefix": images.get("prefix"), "images_tag": images.get("tag"), "image_digests": images.get("digests") or {},
        "min_upgrade_from": r.get("min_upgrade_from"), "rollback": r.get("rollback"),
        "notes": (r.get("notes") or "")[:2000], "notes_url": r.get("notes_url"),
    }


# ---------------------------------------------------------------------------------------------------------------------
# The checker's state (a JSON file on the data volume; memory when the volume is not writable)
# ---------------------------------------------------------------------------------------------------------------------
_MEMORY_STATE: Dict[str, Any] = {}
_EMPTY: Dict[str, Any] = {"last_check_at": None, "last_outcome": None, "last_error": None, "running": None,
                          "latest": None, "newer": [], "update_available": False, "kind": None, "comparable": None,
                          "notified": {}, "schedule": None, "channel_url": None}


def load_state() -> Dict[str, Any]:
    path = state_path()
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict):
            return {**_EMPTY, **doc}
    except (OSError, ValueError):
        pass
    # the process memory stands in for the file only for the path it was saved for (a changed path is a new state)
    if _MEMORY_STATE and _MEMORY_STATE.get("_path") == path:
        return {**_EMPTY, **{k: v for k, v in _MEMORY_STATE.items() if not k.startswith("_")}}
    return dict(_EMPTY)


def save_state(state: Dict[str, Any]) -> bool:
    """True when the file was written; False when only the process memory holds it (logged once)."""
    path = state_path()
    warned = _MEMORY_STATE.get("_warned_unwritable")
    _MEMORY_STATE.clear()
    _MEMORY_STATE.update(state)
    _MEMORY_STATE["_path"] = path
    if warned:
        _MEMORY_STATE["_warned_unwritable"] = True
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        if not _MEMORY_STATE.get("_warned_unwritable"):
            logger.warning("[release-channel] state not persisted (%s): %s; a restart forgets what was notified", path, exc)
            _MEMORY_STATE["_warned_unwritable"] = True
        return False


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def images_host() -> str:
    return (os.getenv("RELEASE_CHANNEL_IMAGES_HOST") or "").strip() or "images.theprotocol.cloud"


def mail_context() -> Dict[str, Any]:
    """What an approval mail may say about images and updates: nothing unless the public pull is on, and then the
    public prefix and the newest tag the channel lists (or the kit version this registry runs)."""
    on = public_pull_enabled()
    tag = None
    if on:
        st = load_state()
        tag = ((st.get("latest") or {}).get("images_tag") or (st.get("latest") or {}).get("version")
               or running_versions().get("kit_version"))
    return {"release_channel_public_pull": bool(on and tag), "images_prefix": f"{images_host()}/{public_namespace()}",
            "images_tag": tag}


def public_view(state: Dict[str, Any]) -> Dict[str, Any]:
    """The state as the admin rail and the dashboard show it (no internals)."""
    return {k: v for k, v in state.items() if not k.startswith("_")}


def same_build(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
    a, b = a or {}, b or {}
    return a.get("kit_version") == b.get("kit_version") and a.get("software_version") == b.get("software_version")


def schedule_spent(schedule: Optional[Dict[str, Any]], running: Dict[str, Any]) -> bool:
    """A scheduled rollout whose version this registry already runs, or has passed: nothing is left to remind of."""
    if not isinstance(schedule, dict) or not schedule.get("version"):
        return False
    return is_newer({"version": schedule["version"]}, running) is False


def current_view(state: Dict[str, Any]) -> Dict[str, Any]:
    """The state as a reader shows it, held against the build this registry runs NOW.

    The stored verdict was computed against the build that ran at the last check. A registry updated (or rolled back)
    since then said "runs <the old version>, update available" until its next check (agentvault2-56, 2026-10-23: a kit
    frame updated from beta.22 to beta.23 through the channel still showed beta.22, "update available" and the command
    to apply beta.23). The releases the check stored, the newest and those that were newer, are read again against the
    live build: forward that is exact (whatever is newer than the new build was newer than the old one), backward it
    still says an update is available. `checked_against` names the build the stored check saw, when it was another; a
    scheduled rollout this registry already runs is left out."""
    st = public_view(state)
    live = running_versions()
    checked = st.get("running")
    st["running"] = live
    if checked and not same_build(checked, live):
        st["checked_against"] = checked
        seen, candidates = set(), []
        for r in [st.get("latest")] + list(st.get("newer") or []):
            if isinstance(r, dict) and r.get("version") and r["version"] not in seen:
                seen.add(r["version"])
                candidates.append(r)
        newer, comparable = [], True
        for r in candidates:
            verdict = is_newer(r, live)
            if verdict is None:
                comparable = False
            elif verdict:
                newer.append(r)
        kind = "stable"
        for r in newer:
            if KIND_RANK.get(r.get("kind"), 0) > KIND_RANK[kind]:
                kind = r["kind"]
        st.update({"newer": newer, "update_available": bool(newer), "kind": kind if newer else None,
                   "comparable": comparable if candidates else st.get("comparable")})
    if schedule_spent(st.get("schedule"), live):
        st["schedule"] = None
    return st


def dashboard_summary() -> Dict[str, Any]:
    """The one block the admin dashboard carries: behind or not, and what it is behind on."""
    st = current_view(load_state())
    return {
        "enabled": check_enabled(), "channel_url": channel_url(), "last_check_at": st.get("last_check_at"),
        "last_outcome": st.get("last_outcome"), "running": st.get("running"),
        "update_available": bool(st.get("update_available")), "kind": st.get("kind"),
        "latest": st.get("latest"), "schedule": st.get("schedule"), "public_pull": public_pull_enabled(),
        "public_namespace": public_namespace(),
    }
