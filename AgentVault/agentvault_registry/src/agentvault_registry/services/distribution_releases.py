"""V0667 D6 part 3 (order gwo_fa3b8d7611f2573a2e63ac1c): the scoped release channel of an organization's code distribution.

DESIGN_2026-11-15_DISTRIBUTIONS.md section 8 (room seq 4473): a separate scoped release channel that unlocks for exactly the registries a line
names, never for everyone.
session-release's contract (room seq 5534 and 5540): our pipeline (stack scripts/release/dist_build.py and dist_publish.py) records each
distribution BUILD here (built, refused or failed), publishes one with the release key's signed index (schema theprotocol-distribution/1) and
withdraws it. Images live under <images host>/distributions/<tag>/registry, tag 'dist-' + the lowercase name.

Who reads a line: ONLY a registry the published index names, proven on the governing registry by BOTH its mTLS trust domain and the frame
licence it presents (X-Federation-License), each read live from this registry's database at every call, never a cached verdict:
  - the licence row is active, a frame's, and names the certificate's trust domain (spiffe://<td>);
  - the index lists a registry with that trust domain, and that registry's peer row here is ACTIVE, has the same trust domain and a passing
    network licence verdict (genesis or licensed).
Everyone else, and every line that does not exist, gets the same 404: a line's existence is not disclosed. The frame-facing routes live under
/api/v1/federation/, the one prefix every frame's nginx-federation forwards with the client certificate.
The token server (routers/docker_token_auth) grants pull on distributions/<tag>/* only to a pull grant this channel gave a listed registry:
short-lived (15 minutes), that line's images only, pull only, and the licence and the listing read again at every token.
Behind CODE_DISTRIBUTIONS_ENABLED, as the lines are; written and served on the governing registry only (services/code_authority).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import re
import secrets
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .code_changes import CodeChangeRefusal

SCHEMA = "theprotocol-distribution/1"
STATES = ("built", "refused", "failed", "published", "withdrawn")
BUILD_STATES = ("built", "refused", "failed")
NAME = re.compile(r"^V[0-9]{4}_[a-z][a-z0-9-]{1,39}$")
RELEASE = re.compile(r"^V[0-9]{4}$")
COMMIT = re.compile(r"^[0-9a-f]{7,64}$")
USER_PREFIX = "dist."                    # a pull grant's username at the token server: dist.<registry name> (Basic auth ends a username at its first colon)
GRANT_PREFIX = "dpg_"
GRANT_TTL_S = 900
PASSING = ("genesis", "licensed")        # a peer row's network licence verdict that lets it read a line (services/federation_licence)
NOT_FOUND = {"detail": "Not Found"}


# ---- pure rules -------------------------------------------------------------------------------------------------------------------

def dist_tag(name: str) -> str:
    return "dist-" + str(name or "").lower()


def repo_prefix(name: str) -> str:
    return f"distributions/{dist_tag(name)}/"


def norm_td(value: Any) -> str:
    """A trust domain however it is written: 'spiffe://Asia.Example/' and 'asia.example' are the same domain."""
    v = str(value or "").strip().lower()
    if v.startswith("spiffe://"):
        v = v[len("spiffe://"):]
    return v.split("/", 1)[0].strip(".")


def td_of_spiffe(spiffe_id: Any) -> str:
    s = str(spiffe_id or "").strip()
    return norm_td(s) if s.lower().startswith("spiffe://") else ""


def verify_index(doc: Any, pubkey_b64: Optional[str] = None) -> Tuple[bool, str]:
    """(ok, reason): the release key's Ed25519 signature over the public channel's canonical form (core.release_channel, the key it
    carries or RELEASE_CHANNEL_PUBKEY_B64), then the schema. The rule of session-release's dist_publish.verify_index. Never raises."""
    from ..core import release_channel as rc
    if not isinstance(doc, dict):
        return False, "not a JSON object"
    sig = doc.get("signature")
    if not isinstance(sig, dict) or sig.get("alg") != "Ed25519":
        return False, "unsigned or not Ed25519"
    try:
        pub = rc.pubkey_bytes(pubkey_b64)
        if sig.get("kid") and sig.get("kid") != rc.kid_of(pub):
            return False, "signed by a key this reader does not carry"
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(str(sig.get("sig") or "")), rc.canonical(doc))
    except Exception as exc:  # noqa: BLE001 — every failure is one answer: not verified
        return False, f"signature does not verify ({type(exc).__name__})"
    if doc.get("schema") != SCHEMA:
        return False, f"unknown schema {doc.get('schema')!r}"
    return True, "ok"


def registries_of(index: Any) -> List[Dict[str, str]]:
    regs = index.get("registries") if isinstance(index, dict) else None
    out = []
    for r in regs if isinstance(regs, list) else []:
        if isinstance(r, dict) and str(r.get("name") or "").strip() and norm_td(r.get("trust_domain")):
            out.append({"name": str(r["name"]).strip(), "trust_domain": norm_td(r["trust_domain"])})
    return out


def listed(index: Any, trust_domain: Any) -> Optional[Dict[str, str]]:
    """The registry the index names with this trust domain, or None."""
    td = norm_td(trust_domain)
    if not td:
        return None
    return next((r for r in registries_of(index) if r["trust_domain"] == td), None)


def grant_scopes(name: str, requested: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What a pull grant for line `name` holds of a token request: repositories under distributions/<its tag>/, pull only."""
    prefix, out = repo_prefix(name), []
    for s in requested or []:
        repo = str(s.get("name") or "")
        if s.get("type") != "repository" or not repo.startswith(prefix) or len(repo) == len(prefix):
            continue
        if "pull" in (s.get("actions") or []):
            out.append({"type": "repository", "name": repo, "actions": ["pull"]})
    return out


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(v: Optional[dt.datetime]) -> Optional[str]:
    return v.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if v else None


def _parse_time(v: Any) -> Optional[dt.datetime]:
    if not v:
        return None
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def public(row: Any) -> Dict[str, Any]:
    return {"id": row.id, "name": row.name, "release": row.release, "tag": row.tag, "state": row.state,
            "base_commit": row.base_commit, "base_tree": row.base_tree, "head": row.head, "head_tree": row.head_tree,
            "changes": row.changes, "protected": row.protected, "carry": row.carry, "image_id": row.image_id,
            "build_rc": row.build_rc, "built_at": _iso(row.built_at), "index": row.index, "image_digests": row.image_digests,
            "registries": row.registries, "publish_word": row.publish_word, "published_at": _iso(row.published_at),
            "withdrawn_at": _iso(row.withdrawn_at), "withdrawn_reason": row.withdrawn_reason, "created_at": _iso(row.created_at)}


# ---- the switch and the governing registry ----------------------------------------------------------------------------------------

def serving() -> bool:
    """A line is recorded and served only where the lines are switched on AND this registry governs code."""
    from . import code_authority, code_distributions
    return code_distributions.enabled() and code_authority.is_governing()


def _require_writable() -> None:
    from . import code_authority, code_distributions
    if not code_distributions.enabled():
        raise CodeChangeRefusal(404, "not_found", "Not Found")
    code_authority.require_governing()


# ---- the admin side: the pipeline records, publishes and withdraws ------------------------------------------------------------------

async def _rows(db: Any, name: str) -> List[Any]:
    from sqlalchemy import select
    from .. import models
    R = models.DistributionRelease
    return list((await db.execute(select(R).where(R.name == name).order_by(R.created_at.desc(), R.id.desc()))).scalars())


async def record_build(db: Any, actor_id: Optional[int], name: str, record: Any) -> Dict[str, Any]:
    from sqlalchemy import select
    from .. import models
    _require_writable()
    if not NAME.match(str(name or "")):
        raise CodeChangeRefusal(422, "bad_name", "a distribution release is named <release>_<line>, e.g. V0667_lyceum")
    rec = record if isinstance(record, dict) else {}
    if rec.get("name") != name or rec.get("release") != name.split("_", 1)[0]:
        raise CodeChangeRefusal(422, "name_mismatch", f"the build record names {rec.get('name')!r}, release {rec.get('release')!r}, not {name}")
    if rec.get("state") not in BUILD_STATES:
        raise CodeChangeRefusal(422, "bad_state", "a build is recorded as built, refused or failed")
    tag = rec.get("tag") or dist_tag(name)
    if tag != dist_tag(name):
        raise CodeChangeRefusal(422, "tag_mismatch", f"a distribution's images are tagged {dist_tag(name)}, not {tag}")
    if not (COMMIT.match(str(rec.get("base_commit") or "")) and COMMIT.match(str(rec.get("head") or ""))):
        raise CodeChangeRefusal(422, "bad_commit", "the build record needs its base_commit and head as commit ids")
    if not isinstance(rec.get("protected"), dict):
        raise CodeChangeRefusal(422, "no_protected_verdict", "the build record needs the protected-set verdict")
    slug = name.split("_", 1)[1]
    line = (await db.execute(select(models.CodeDistribution).where(models.CodeDistribution.slug == slug))).scalar_one_or_none()
    if line is None:
        raise CodeChangeRefusal(404, "no_line", f"no code distribution named {slug}")
    row = models.DistributionRelease(
        code_distribution_id=line.id, name=name, release=rec["release"], tag=tag, base_commit=rec["base_commit"],
        base_tree=rec.get("base_tree"), head=rec["head"], head_tree=rec.get("head_tree"),
        changes=rec.get("changes") if isinstance(rec.get("changes"), list) else [], protected=rec["protected"],
        carry=rec.get("carry") if isinstance(rec.get("carry"), dict) else {}, image_id=(str(rec["image_id"])[:80] if rec.get("image_id") else None),
        build_rc=rec.get("build_rc") if isinstance(rec.get("build_rc"), int) else None, built_at=_parse_time(rec.get("built_at")),
        state=rec["state"], recorded_by_developer_id=actor_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return public(row)


async def publish(db: Any, actor_id: Optional[int], name: str, index: Any, card_word: Any) -> Dict[str, Any]:
    from sqlalchemy.exc import IntegrityError
    _require_writable()
    word = str(card_word or "").strip()
    if not word:
        raise CodeChangeRefusal(422, "no_card_word", "a distribution is published on his card: send its words as card_word")
    rows = await _rows(db, str(name or ""))
    if not rows:
        raise CodeChangeRefusal(404, "not_found", "no build of that distribution release is recorded")
    if any(r.state == "published" for r in rows):
        raise CodeChangeRefusal(409, "already_published", f"{name} is published already: withdraw it first")
    row = rows[0]
    if row.state != "built":
        raise CodeChangeRefusal(409, "not_built", f"the newest build of {name} is {row.state}: only a built one is published")
    ok, why = verify_index(index)
    if not ok:
        raise CodeChangeRefusal(422, "index_unverified", f"the index does not verify: {why}")
    if index.get("name") != name:
        raise CodeChangeRefusal(422, "name_mismatch", f"the index names {index.get('name')!r}, not {name}")
    regs = registries_of(index)
    if not regs:
        raise CodeChangeRefusal(422, "no_registries", "the index names no registry: a scoped channel is for named registries only")
    images = index.get("images") if isinstance(index.get("images"), dict) else {}
    row.state, row.index, row.registries = "published", index, regs
    row.image_digests = images.get("digests") if isinstance(images.get("digests"), dict) else None
    row.publish_word, row.published_at, row.published_by_developer_id = word[:500], _now(), actor_id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise CodeChangeRefusal(409, "already_published", f"{name} is published already: withdraw it first")
    await db.refresh(row)
    return public(row)


async def withdraw(db: Any, actor_id: Optional[int], name: str, reason: Any) -> Dict[str, Any]:
    _require_writable()
    row = next((r for r in await _rows(db, str(name or "")) if r.state == "published"), None)
    if row is None:
        raise CodeChangeRefusal(404, "not_published", f"{name} is not published")
    row.state, row.withdrawn_at, row.withdrawn_reason = "withdrawn", _now(), (str(reason or "").strip()[:500] or None)
    await db.commit()
    await db.refresh(row)
    return public(row)


async def read(db: Any, name: str) -> Dict[str, Any]:
    _require_writable()
    rows = await _rows(db, str(name or ""))
    if not rows:
        raise CodeChangeRefusal(404, "not_found", "no build of that distribution release is recorded")
    pub = next((r for r in rows if r.state == "published"), None)
    return {"name": name, "state": rows[0].state, "published": public(pub) if pub else None, "builds": [public(r) for r in rows]}


async def inbox(db: Any, state: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    from sqlalchemy import select
    from .. import models
    _require_writable()
    R = models.DistributionRelease
    q = select(R).order_by(R.created_at.desc(), R.id.desc()).limit(max(1, min(int(limit or 100), 500)))
    if state:
        if state not in STATES:
            raise CodeChangeRefusal(422, "bad_state", "state is one of " + ", ".join(STATES))
        q = q.where(R.state == state)
    return {"releases": [public(r) for r in (await db.execute(q)).scalars()]}


# ---- the frame side: a listed registry reads its line and pulls its images ----------------------------------------------------------

async def _licence(db: Any, td: str, licence_key: Any) -> Optional[Any]:
    """The presented frame licence, live: active, a frame's, naming the certificate's trust domain."""
    from sqlalchemy import select
    from .. import models
    key = str(licence_key or "").strip()
    if not td or not key:
        return None
    L = models.FederationLicense
    lic = (await db.execute(select(L).where(L.license_key_hash == hashlib.sha256(key.encode()).hexdigest()))).scalar_one_or_none()
    if lic is None or lic.status != "active" or (lic.licensee_type or "") != "frame" or norm_td(lic.operator_did) != td:
        return None
    return lic


async def _peer_passes(db: Any, entry: Dict[str, str]) -> bool:
    """The listed registry's peer row here, live: ACTIVE, the same trust domain, a passing network licence verdict."""
    from sqlalchemy import func, select
    from .. import models
    P = models.PeerRegistry
    rows = (await db.execute(select(P.status, P.trust_domain, P.licence_state)
                             .where(func.lower(P.name) == entry["name"].lower()))).all()
    return any(str(st or "").upper() == "ACTIVE" and norm_td(td) == entry["trust_domain"] and str(ls or "") in PASSING
               for st, td, ls in rows)


async def _published(db: Any, name: str) -> Optional[Any]:
    return next((r for r in await _rows(db, str(name or "")) if r.state == "published"), None)


async def _reader(db: Any, name: str, spiffe_id: Any, licence_key: Any) -> Optional[Tuple[Any, Dict[str, str], Any]]:
    """(the published row, the caller's entry in its index, the licence) or None: the one answer for everyone else."""
    if not serving() or not NAME.match(str(name or "")):
        return None
    td = td_of_spiffe(spiffe_id)
    lic = await _licence(db, td, licence_key)
    if lic is None:
        return None
    row = await _published(db, name)
    entry = listed(row.index, td) if row is not None else None
    if entry is None or not await _peer_passes(db, entry):
        return None
    return row, entry, lic


async def index_for(db: Any, name: str, spiffe_id: Any, licence_key: Any) -> Optional[Dict[str, Any]]:
    found = await _reader(db, name, spiffe_id, licence_key)
    return found[0].index if found else None


async def pull_grant(db: Any, name: str, spiffe_id: Any, licence_key: Any) -> Optional[Dict[str, Any]]:
    from .. import models
    from ..core import release_channel as rc
    found = await _reader(db, name, spiffe_id, licence_key)
    if not found:
        return None
    row, entry, lic = found
    secret = GRANT_PREFIX + secrets.token_hex(24)
    expires = _now() + dt.timedelta(seconds=GRANT_TTL_S)
    db.add(models.DistributionPullGrant(release_id=row.id, registry_name=entry["name"], trust_domain=entry["trust_domain"], licence_id=lic.id,
                                        secret_hash=hashlib.sha256(secret.encode()).hexdigest(), expires_at=expires))
    await db.commit()
    return {"registry": rc.images_host(), "username": USER_PREFIX + entry["name"], "password": secret, "expires_at": _iso(expires),
            "scope": repo_prefix(row.name) + "*", "repository": repo_prefix(row.name) + "registry"}


async def lines_for(db: Any, spiffe_id: Any, licence_key: Any) -> Optional[Dict[str, Any]]:
    """The published lines whose index names the caller; None when the caller is not a frame this registry can identify."""
    from sqlalchemy import select
    from .. import models
    if not serving():
        return None
    td = td_of_spiffe(spiffe_id)
    if await _licence(db, td, licence_key) is None:
        return None
    R = models.DistributionRelease
    out = []
    for row in (await db.execute(select(R).where(R.state == "published").order_by(R.name))).scalars():
        entry = listed(row.index, td)
        if entry and await _peer_passes(db, entry):
            out.append({"name": row.name, "release": row.release, "generated_at": (row.index or {}).get("generated_at"),
                        "images": (row.index or {}).get("images"), "published_at": _iso(row.published_at)})
    return {"lines": out}


async def token_access(db: Any, username: str, password: str, requested: Sequence[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The token server's distribution lane: the access a pull grant holds, or None (the caller answers 401). Everything read live: the grant
    unexpired, its line still published and still naming the registry, the licence still active, the peer row still passing."""
    from sqlalchemy import select
    from .. import models
    if not serving() or not str(username or "").startswith(USER_PREFIX):
        return None
    G = models.DistributionPullGrant
    grant = (await db.execute(select(G).where(G.secret_hash == hashlib.sha256(str(password or "").encode()).hexdigest()))).scalar_one_or_none()
    if grant is None or grant.registry_name != username[len(USER_PREFIX):] or grant.expires_at <= _now():
        return None
    row = await db.get(models.DistributionRelease, grant.release_id)
    lic = await db.get(models.FederationLicense, grant.licence_id)
    if row is None or row.state != "published" or lic is None or lic.status != "active" or norm_td(lic.operator_did) != grant.trust_domain:
        return None
    entry = listed(row.index, grant.trust_domain)
    if entry is None or entry["name"] != grant.registry_name or not await _peer_passes(db, entry):
        return None
    return grant_scopes(row.name, requested)
