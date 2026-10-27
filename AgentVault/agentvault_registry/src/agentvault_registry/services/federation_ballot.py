"""§MEMBERSHIP phase D2 (2026-10-02, agentvault2-33): federal ballots — one signed ballot per registry, weight 1.

Plan sessionlogs2026/PLAN_2026-10-02_MEMBERSHIP_COMMONS.md section 2.7 is the contract; design section 12, S2.

A federation proposal opened where FEDERATION_BALLOT_MODE=on is decided by registries, not agents: each eligible
registry casts ONE ballot, its members' result (a linked local member vote) or, without members, its operator's choice.
The ballot is a small document signed with the casting registry's CARD key and delivered over the federation mTLS lane
to the registry hosting the proposal, which alone writes it into its store (the store's ballot route is origin-only).

What the host checks before it writes (every check refuses, never guesses):
  * the mTLS caller binds to ONE ACTIVE peer row: a frame by its trust domain, an operator by its trust domain and the
    operator name in its SVID path (a licence-only or internal identity cannot deliver a ballot);
  * the ballot names that registry and this host, and its `kid` is `spiffe://<caller td>/registry/<name>#<n>`;
  * the key is fetched from that ROW's own base URL and must carry exactly that `kid` (never a fallback to any key:
    a registry's JWKS also serves other keys, e.g. developer cards, so "some key verifies" proves nothing);
  * the proposal is a ballot proposal still VOTING; the registry is eligible (licence, and the track record where
    FEDERATION_BALLOT_TRACK_RECORD=required).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import network_profile as _np

logger = logging.getLogger(__name__)

KIND = "tp.federation.ballot.v1"
CHOICES = ("for", "against", "abstain")
PASSING_LICENCE = ("genesis", "licensed", "same-domain")
ELIGIBLE_PEER_TYPES = ("frame", "cloud_operator")
MAX_CLOCK_SKEW_SECONDS = 300
TRACK_CACHE_SECONDS = 300
OPEN_CACHE_SECONDS = 60


class BallotRefusal(Exception):
    def __init__(self, status_code: int, error: str, message: str, **extra: Any):
        super().__init__(message)
        self.status_code, self.error, self.message, self.extra = status_code, error, message, extra

    def body(self) -> Dict[str, Any]:
        return {"error": self.error, "message": self.message, **self.extra}


# ── switches and identity ───────────────────────────────────────────────────

def ballot_mode() -> bool:
    return (_np.knob("FEDERATION_BALLOT_MODE", "off") or "off").strip().lower() == "on"


def track_record_rule() -> str:
    v = (_np.knob("FEDERATION_BALLOT_TRACK_RECORD", "required") or "required").strip().lower()
    return v if v in ("required", "observe") else "required"


def auditor_url() -> str:
    return (os.getenv("AUDITOR_PUBLIC_URL", "https://auditor.theprotocol.cloud") or "").rstrip("/")


_ID_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def registry_name_slug(name: str) -> str:
    """The name part of a registry id: lowercase, every run of other characters one '-', never empty.

    Measured 2026-10-03 (agentvault2-09's first FINISH run): the raw display name went into the id, so 'Sandbox Alpha'
    made 'registry:sandbox-a.theprotocol.cloud/Sandbox Alpha', and the store's RegistryBallotCreate.registry_id
    (^registry:[^/\\s]+/[^\\s]+$, agentvault-event-store/src/routers/federation_governance.py) refused every ballot
    of a registry whose name has a space (422). The case matters as much: a host derives a voter's id from ITS peer row
    ('eu') while the voter derives its own from REGISTRY_NAME ('EU'), so 'did I cast here?' could never match."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()   # 'Ü' -> 'U'
    # 64 at most: the store keeps registry_id in String(255) (min 12), and a trust domain shares those characters
    return _ID_UNSAFE.sub("-", ascii_name.strip().lower()).strip("-")[:64].strip("-") or "unnamed"


def registry_id(trust_domain: str, name: str) -> str:
    return f"registry:{(trust_domain or '').strip().lower()}/{registry_name_slug(name)}"


def own_identity() -> Dict[str, str]:
    from .registry_card_builder import _build_spiffe_id, federation_name
    td = (os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com") or "").strip().lower()
    # §MCPTEST30 (V0559): the name the card publishes, never the container label. Measured 2026-10-03 on the sandbox:
    # sbxbetaop's REGISTRY_NAME is "cloud-op-sbxbetaop", its card, SPIFFE path and its parent's peer row say "sbxbetaop";
    # its ballot named the label and Sandbox Beta refused it (403 registry_mismatch), so no cloud operator could cast.
    name = federation_name()
    return {"trust_domain": td, "name": name, "id": registry_id(td, name), "card_spiffe": _build_spiffe_id()}


def split_spiffe(spiffe_id: str) -> Tuple[str, List[str]]:
    if not spiffe_id or not spiffe_id.startswith("spiffe://"):
        return "", []
    domain, _, path = spiffe_id[len("spiffe://"):].partition("/")
    return domain.strip().lower(), [s for s in path.split("/") if s]


# ── the document, signed with the card key ──────────────────────────────────

def now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def build_ballot(*, proposal_id: str, host: Dict[str, str], voter: Dict[str, str], choice: str,
                 basis: Dict[str, Any], cast_at: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    if choice not in CHOICES:
        raise BallotRefusal(422, "bad_choice", "choice is for, against or abstain.")
    return {"kind": KIND, "proposal_id": str(proposal_id),
            "host": {"trust_domain": host["trust_domain"], "name": host.get("name") or ""},
            "registry": {"trust_domain": voter["trust_domain"], "name": voter["name"]},
            "choice": choice, "basis": basis, "cast_at": (cast_at or now_utc()).isoformat()}


async def sign_ballot(db: AsyncSession, ballot: Dict[str, Any]) -> Dict[str, Any]:
    """The envelope {ballot, alg, kid, signature}: EdDSA over the canonical ballot, with this registry's CARD key."""
    from .registry_card_keystore import get_or_mint_signing_key
    from .registry_card_signer_impl import sign_with_keypair
    me = own_identity()
    key_row = await get_or_mint_signing_key(db, me["card_spiffe"])
    return {"ballot": ballot, "alg": "EdDSA", "kid": f"{me['card_spiffe']}#{key_row.rotation_seq}",
            "signature": sign_with_keypair(ballot, key_row)}


def verify_envelope(envelope: Dict[str, Any], jwks: Dict[str, Any], *, caller_td: str) -> Tuple[bool, str]:
    """Exact kid, under this caller's trust domain and the /registry/ path, and a signature that verifies."""
    from .registry_card_signer_impl import verify_with_jwk
    kid = str(envelope.get("kid") or "")
    if envelope.get("alg") != "EdDSA" or not isinstance(envelope.get("ballot"), dict) or not envelope.get("signature"):
        return False, "not a signed ballot envelope"
    if not kid.startswith(f"spiffe://{caller_td}/registry/") or "#" not in kid:
        return False, "the kid is not a registry card key of the caller's trust domain"
    key = next((k for k in (jwks or {}).get("keys") or [] if k.get("kid") == kid), None)
    if key is None:
        return False, "the caller's key set does not carry this kid"
    if not verify_with_jwk(envelope["ballot"], str(envelope["signature"]), key):
        return False, "the signature does not verify"
    return True, "verified"


# ── who the caller is ───────────────────────────────────────────────────────

async def caller_row(db: AsyncSession, caller_spiffe: str):
    """The ONE ACTIVE peer row this mTLS identity is: an operator by its SVID's operator name (and trust domain),
    a frame by its trust domain. None when nothing or more than one row matches."""
    from .. import models as m
    td, segs = split_spiffe(caller_spiffe)
    if not td:
        return None
    q = select(m.PeerRegistry).where(func.upper(m.PeerRegistry.status) == "ACTIVE")
    if len(segs) >= 2 and segs[0] == "operator":
        rows = (await db.execute(q.where(func.lower(m.PeerRegistry.name) == segs[1].lower(),
                                         m.PeerRegistry.peer_type == "cloud_operator"))).scalars().all()
        rows = [r for r in rows if not r.trust_domain or r.trust_domain.strip().lower() == td]
    else:
        rows = (await db.execute(q.where(func.lower(m.PeerRegistry.trust_domain) == td,
                                         m.PeerRegistry.peer_type == "frame"))).scalars().all()
    return rows[0] if len(rows) == 1 else None


def _row_identity(row) -> Dict[str, str]:
    card = row.cached_registry_card if isinstance(row.cached_registry_card, dict) else {}
    ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    td = (row.trust_domain or ident.get("trust_domain") or "").strip().lower()
    return {"name": row.name, "trust_domain": td, "id": registry_id(td, row.name), "kind": row.peer_type,
            "public_host": (urlparse(str(ident.get("public_url") or "")).hostname or "").lower()}


def _mtls_kwargs(url: str) -> Dict[str, Any]:
    from .exchange_passport import _client_config_for
    cfg, err = _client_config_for(url)
    if err:
        raise BallotRefusal(502, "no_federation_client", err)
    return cfg


async def fetch_peer_jwks(row) -> Dict[str, Any]:
    from ..routers.teg_integration import _to_internal_mtls_url
    url = _to_internal_mtls_url(row.base_url.rstrip("/")) + "/.well-known/registry-jwks.json"
    try:
        async with httpx.AsyncClient(**_mtls_kwargs(url)) as c:
            r = await c.get(url)
        if r.status_code == 200 and isinstance(r.json(), dict):
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise BallotRefusal(502, "peer_keys_unreadable", f"the caller's key set could not be read: {e}")
    raise BallotRefusal(502, "peer_keys_unreadable", f"the caller's key set answered {r.status_code}")


# ── eligibility ─────────────────────────────────────────────────────────────

_TRACK_CACHE: Dict[str, Any] = {"at": 0.0, "by_host": None}


async def track_records_by_host(force: bool = False) -> Optional[Dict[str, Dict[str, Any]]]:
    """The auditor's latest track record per registry, keyed by the public host it probes; None when unreadable."""
    if not force and _TRACK_CACHE["by_host"] is not None and time.monotonic() - _TRACK_CACHE["at"] < TRACK_CACHE_SECONDS:
        return _TRACK_CACHE["by_host"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{auditor_url()}/api/auditor/track-record")
        doc = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("[BALLOT] track records unreadable: %s", e)
        doc = None
    if not isinstance(doc, dict):
        return None
    out = {}
    for rec in doc.get("records") or []:
        host = (urlparse(str(rec.get("base") or "")).hostname or "").lower()
        if host:
            out[host] = {"score": rec.get("score"), "provisional": bool(rec.get("provisional")),
                         "observed_days": rec.get("observed_days"), "computed_at": rec.get("computed_at")}
    _TRACK_CACHE.update(at=time.monotonic(), by_host=out)
    return out


def _judge(entry: Dict[str, Any], tracks: Optional[Dict[str, Dict[str, Any]]], rule: str) -> Dict[str, Any]:
    rec = (tracks or {}).get(entry.get("public_host") or "")
    entry["track_record"] = rec
    reasons = []
    if not entry["licence_ok"]:
        reasons.append(f"licence {entry.get('licence_state') or 'unknown'}")
    track_ok = rec is not None and not rec["provisional"]
    if not track_ok:
        why = "no track record" if rec is None else "a provisional track record"
        if tracks is None:
            why = "the track records could not be read"
        reasons.append(why if rule == "required" else f"{why} (observed, not enforced)")
    entry["track_ok"] = track_ok
    entry["eligible"] = entry["licence_ok"] and (track_ok or rule == "observe")
    entry["reasons"] = reasons
    return entry


async def eligibility(db: AsyncSession, *, tracks: Optional[Dict[str, Dict[str, Any]]] = None,
                      fetch_tracks: bool = True) -> List[Dict[str, Any]]:
    """This host and every ACTIVE peer row of type frame or cloud_operator, each judged on its licence and, where
    the rule asks, a track record that is not provisional. A snapshot: who may count NOW."""
    from .. import models as m
    if tracks is None and fetch_tracks:
        tracks = await track_records_by_host()
    rule = track_record_rule()
    me = own_identity()
    own_host = (urlparse(os.getenv("PUBLIC_URL", "") or os.getenv("PUBLIC_UI_URL", "") or "").hostname or "").lower()
    out = [_judge({"id": me["id"], "name": me["name"], "trust_domain": me["trust_domain"], "kind": "self",
                   "public_host": own_host, "licence_state": "self", "licence_ok": True}, tracks, rule)]
    rows = (await db.execute(select(m.PeerRegistry).where(func.upper(m.PeerRegistry.status) == "ACTIVE",
                                                          m.PeerRegistry.peer_type.in_(ELIGIBLE_PEER_TYPES)))).scalars().all()
    for row in sorted(rows, key=lambda r: r.name.lower()):
        e = _row_identity(row)
        e.update(licence_state=row.licence_state, licence_ok=(row.licence_state or "") in PASSING_LICENCE)
        out.append(_judge(e, tracks, rule))
    return out


# ── the host's store (its own ES, over the registry's usual lane) ───────────

async def _es(method: str, path: str, json_body: Optional[dict] = None) -> Tuple[int, Any]:
    from ..routers.governance import _get_es_url, _get_es_headers, _get_es_client_kwargs
    async with httpx.AsyncClient(**_get_es_client_kwargs()) as c:
        r = await c.request(method, f"{_get_es_url()}/api/v1/federation-governance{path}", json=json_body,
                            headers=_get_es_headers())
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text[:300]}


async def host_proposal(proposal_id: str) -> Dict[str, Any]:
    st, doc = await _es("GET", f"/proposals/{proposal_id}")
    if st == 404:
        raise BallotRefusal(404, "proposal_not_found", f"no federation proposal {proposal_id} at this registry.")
    if st != 200 or not isinstance(doc, dict):
        raise BallotRefusal(502, "store_unreadable", f"the store answered {st}.")
    return doc


def _assert_open(p: Dict[str, Any]) -> None:
    if not p.get("ballot_mode"):
        raise BallotRefusal(409, "not_a_ballot_proposal", "this federation proposal is decided by agents' votes.")
    if p.get("status") != "VOTING":
        raise BallotRefusal(409, "proposal_closed", f"this federation proposal is {p.get('status')}.")
    end = _dt.datetime.fromisoformat(str(p.get("end_timestamp")).replace("Z", "+00:00"))
    if end <= now_utc():
        raise BallotRefusal(409, "proposal_closed", "the federation proposal's voting window has ended.")


async def record_ballot(proposal_id: str, envelope: Dict[str, Any], voter: Dict[str, Any]) -> Dict[str, Any]:
    st, doc = await _es("POST", f"/proposals/{proposal_id}/ballots", {
        "registry_id": voter["id"], "choice": envelope["ballot"]["choice"],
        "ballot_jws": json.dumps(envelope, sort_keys=True, separators=(",", ":")),
        "basis": envelope["ballot"].get("basis"),
        "eligibility": {k: voter.get(k) for k in ("licence_state", "licence_ok", "track_record", "track_ok", "reasons")},
    })
    if st == 409:
        raise BallotRefusal(409, "already_cast", "this registry has already cast its ballot on this proposal.")
    if st != 201:
        raise BallotRefusal(502 if st >= 500 else st, "store_refused", f"the store answered {st}: {doc}")
    return doc


async def tally_body(db: AsyncSession, proposal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The store's tally body for a ballot proposal: the registries eligible NOW (None for an agents' proposal)."""
    if not proposal.get("ballot_mode"):
        return None
    return {"eligible_registries": [e["id"] for e in await eligibility(db) if e["eligible"]]}


# ── the host: receive a peer's ballot ───────────────────────────────────────

async def receive_ballot(db: AsyncSession, caller_spiffe: str, envelope: Dict[str, Any]) -> Dict[str, Any]:
    row = await caller_row(db, caller_spiffe)
    if row is None:
        raise BallotRefusal(403, "unknown_caller", "no single ACTIVE frame or operator row matches this identity.")
    voter = _row_identity(row)
    td, segs = split_spiffe(caller_spiffe)
    ballot = envelope.get("ballot") if isinstance(envelope, dict) else None
    if not isinstance(ballot, dict) or ballot.get("kind") != KIND:
        raise BallotRefusal(422, "not_a_ballot", f"the document is not a {KIND}.")
    me = own_identity()
    if (ballot.get("host") or {}).get("trust_domain") != me["trust_domain"]:
        raise BallotRefusal(422, "wrong_host", "the ballot names another host.")
    reg = ballot.get("registry") or {}
    if (reg.get("trust_domain") or "").lower() != td:
        raise BallotRefusal(403, "registry_mismatch", "the ballot names another trust domain than its caller's.")
    if len(segs) >= 2 and segs[0] == "operator" and registry_name_slug(reg.get("name")) != registry_name_slug(segs[1]):
        raise BallotRefusal(403, "registry_mismatch", "the ballot names another operator than its caller.")
    try:
        cast = _dt.datetime.fromisoformat(str(ballot.get("cast_at")).replace("Z", "+00:00"))
        if cast.tzinfo is None:
            raise ValueError("naive")
    except ValueError:
        raise BallotRefusal(422, "not_a_ballot", "the ballot carries no valid cast_at (ISO 8601 with a zone).")
    if ballot.get("choice") not in CHOICES or not isinstance(ballot.get("proposal_id"), str) \
            or not 8 <= len(ballot["proposal_id"]) <= 64:
        raise BallotRefusal(422, "not_a_ballot", "the ballot needs a proposal_id and a choice of for, against or abstain.")
    if cast > now_utc() + _dt.timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        raise BallotRefusal(422, "cast_in_future", "the ballot is dated in the future.")
    ok, why = verify_envelope(envelope, await fetch_peer_jwks(row), caller_td=td)
    if not ok:
        raise BallotRefusal(403, "bad_signature", why)
    _assert_open(await host_proposal(str(ballot.get("proposal_id"))))
    judged = next((e for e in await eligibility(db) if e["id"] == voter["id"]), None)
    if judged is None or not judged["eligible"]:
        raise BallotRefusal(403, "not_eligible", "this registry may not cast a ballot here now.",
                            reasons=(judged or {}).get("reasons", ["not a frame or operator peer of this host"]))
    stored = await record_ballot(str(ballot["proposal_id"]), envelope, judged)
    return {"recorded": True, "proposal_id": ballot["proposal_id"], "registry_id": judged["id"],
            "choice": ballot["choice"], "store": stored}


# ── the caster: what the ballot says ───────────────────────────────────────

def federation_ref(host_td: str, proposal_id: str) -> str:
    return f"{host_td.strip().lower()}/{proposal_id}"


async def member_basis(db: AsyncSession, ref: str) -> Optional[Dict[str, Any]]:
    """The linked local member vote's result, or None when there is none. Refuses while it is still open."""
    row = (await db.execute(text(
        "SELECT id, end_timestamp FROM governance_proposals WHERE federation_ref = :r"), {"r": ref})).mappings().first()
    if row is None:
        return None
    end = row["end_timestamp"]
    if end.tzinfo is None:
        end = end.replace(tzinfo=_dt.timezone.utc)
    if end > now_utc():
        raise BallotRefusal(409, "local_vote_open", "the members' vote on this ballot is still open.",
                            local_proposal_id=row["id"], ends_at=end.isoformat())
    sums = (await db.execute(text(
        "SELECT COALESCE(SUM(CASE WHEN vote THEN voting_power ELSE 0 END), 0) AS f, "
        "COALESCE(SUM(CASE WHEN vote THEN 0 ELSE voting_power END), 0) AS a, COUNT(*) AS n "
        "FROM votes WHERE proposal_id = :p"), {"p": row["id"]})).mappings().first()
    f, a = float(sums["f"] or 0), float(sums["a"] or 0)
    choice = "for" if f > a else ("against" if a > f else "abstain")
    return {"mode": "members", "local_proposal_id": row["id"], "points_for": f, "points_against": a,
            "voters": int(sums["n"] or 0), "choice": choice}


__all__ = ["BallotRefusal", "registry_name_slug", "ballot_mode", "build_ballot", "sign_ballot", "verify_envelope", "caller_row",
           "eligibility", "receive_ballot", "member_basis", "federation_ref", "own_identity", "registry_id",
           "record_ballot", "host_proposal", "track_record_rule", "tally_body"]
