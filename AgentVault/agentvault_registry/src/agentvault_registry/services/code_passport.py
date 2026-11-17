"""V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511; sessionlogs2026/DESIGN_2026-11-16_DEVELOPER_PASSPORT.md
sections 2 to 5; his answers seq 5334 and 5336): a developer homed on another registry proposes and reviews on the governing registry
(CODE_CHANGES_GOVERNING_REGISTRY, services/code_authority) through their home, with no account there. Votes stay the governing
registry's members' (his answer (a)) until one identity holds across the federation.

THE HOME (a registry that does not govern code)
  - consent by a press: "Take part on <governing>" on the Code changes view shows the card's preview, then sets
    developers.code_passport_consent_at. Never automatic; taking it back stops every relay.
  - for each act of the developer's OWN agent (propose, review) the home signs a fresh card for code governance and relays the act over
    the federation lane (services/exchange_passport.peer_request: federation mTLS, the Passport's channel). The card discloses only what
    the governing registry records (the developer's public name, their id at home, the home's name, their standing, the agent's DID) and
    names its purpose, so an exchange card can never be replayed here. A disclosure row is written BEFORE the card leaves, and a card
    whose row cannot be written does not leave (fail closed, unlike the exchange's fail-open audit).

THE GOVERNING REGISTRY
  - the presenter is bound to the card's home: the mTLS identity's trust domain names one ACTIVE peer row whose name is the card's
    home_registry, and whose licence verdict is not refused while the federation licence is enforced (observe: logged only);
  - the card must be for code governance, at most CARD_MAX_AGE_SECONDS old (the home signs one per act, so the standing it carries is
    the home's at the act), signed with a key the home publishes (exchange_passport.verify_devcard_envelope, the home's JWKS);
  - one contributor row per (home registry, home developer id): no password, no sign-in, authority re-derived from the card at every act;
  - standing follows home: a card saying "suspended" pauses the contributor and is refused; a later "active" card restores it;
  - the act runs as the rail's own step (services/code_changes.CodeChangeFlow) with the contributor as the actor. In the rail's
    developer columns a contributor is the NEGATIVE of its row id (contributor_key): the columns are plain integers with no foreign
    key, so independence, the review count, the contributor track and the verifier read a contributor as one more distinct identity.
    A contributor proposes a branch with its commit (a bounty is posted and paid by the governing registry's own members).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

PURPOSE = "code_governance"
SCHEMA = "devcard/0.1"
CARD_MAX_AGE_SECONDS = int(os.getenv("CODE_PASSPORT_CARD_MAX_AGE_SECONDS", "300"))
CARD_SKEW_SECONDS = 60
ACTS = ("propose", "review", "repo_status", "repo_link")
STANDING_PATH = "/api/v1/federation/code-passport/standing"
STANDING_PULL_LIMIT = 200
FEDERATION_PATH = "/api/v1/federation/code-passport"
VOTE_SENTENCE = ("votes on code changes are this registry's members': a contributor from another registry proposes and reviews, and "
                 "votes once one identity holds across the federation")

Refusal = Tuple[int, str, str]


# --- pure ----------------------------------------------------------------------------------------------------------

def contributor_key(contributor_id: int) -> int:
    """A contributor in the rail's developer columns: the negative of its row id (a developer id is never negative)."""
    return -int(contributor_id)


def contributor_id_of(key: Any) -> Optional[int]:
    return -key if isinstance(key, int) and not isinstance(key, bool) and key < 0 else None


def home_standing(dev: Any, agent: Any) -> str:
    """The rail's good standing (code_changes.DbStore.developers_in_good_standing): verified, not suspended, no deletion pending,
    requested or done; and the acting agent active. Deleted at home: closed (phase 4: the code host account closes, never restored)."""
    if getattr(dev, "deleted_at", None) is not None:
        return "closed"
    good = (bool(getattr(dev, "is_verified", False)) and not getattr(dev, "is_suspended", False)
            and getattr(dev, "deletion_status", None) is None and getattr(dev, "deletion_requested_at", None) is None
            and getattr(dev, "deleted_at", None) is None and getattr(agent, "status", None) == "active")
    return "active" if good else "suspended"


def card_payload(dev: Any, agent: Any, home: str, now: dt.datetime) -> Dict[str, Any]:
    """What the governing registry receives and records, and nothing else: no e-mail, no organisations."""
    name = (getattr(dev, "display_name", None) or "").strip()
    return {"schema": SCHEMA, "purpose": PURPOSE, "developer_ref": str(dev.id),
            "display_name": name if name and "@" not in name else None,
            "home_registry": home, "standing": home_standing(dev, agent), "agent_did": agent.did, "issued_at": now.isoformat()}


def _time(v: Any) -> Optional[dt.datetime]:
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else None


def card_refusal(env: Any, now: dt.datetime) -> Optional[Refusal]:
    """The card's own checks, before any key is read: its shape, its purpose, its age."""
    p = (env or {}).get("payload") if isinstance(env, dict) else None
    sig = (env or {}).get("signature") if isinstance(env, dict) else None
    if not isinstance(p, dict) or not isinstance(sig, dict) or not sig.get("value") or p.get("schema") != SCHEMA:
        return 403, "card_malformed", "the card is not a home-signed developer card"
    if p.get("purpose") != PURPOSE:
        return 403, "wrong_purpose", "the card was not issued for code governance"
    if not all(isinstance(p.get(k), str) and p.get(k) for k in ("developer_ref", "home_registry", "agent_did", "standing")):
        return 403, "card_malformed", "the card does not name its developer, home, agent and standing"
    at = _time(p.get("issued_at"))
    if at is None:
        return 403, "card_malformed", "the card carries no time it was issued"
    age = (now - at).total_seconds()
    if age > CARD_MAX_AGE_SECONDS:
        return 403, "card_expired", f"the card is older than {CARD_MAX_AGE_SECONDS} seconds: the home signs one for each act"
    if age < -CARD_SKEW_SECONDS:
        return 403, "card_not_yet_valid", "the card was issued in the future"
    return None


def trust_domain_of(spiffe_id: Any) -> Optional[str]:
    s = str(spiffe_id or "").strip()
    if not s.lower().startswith("spiffe://"):
        return None
    td = s[len("spiffe://"):].split("/", 1)[0].strip().lower()
    return td or None


def bind_presenter(rows: Iterable[Sequence[Any]], peer_spiffe: str, home: str,
                   licence_mode: str) -> Tuple[Optional[str], Optional[Refusal]]:
    """The presenting registry must BE the card's home: its trust domain names an ACTIVE peer row, that row's name is the card's
    home_registry, and its licence verdict is not refused while the licence is enforced. rows: (name, peer_type, status, trust_domain,
    licence_state). Answers the peer row's own name (the canonical spelling) or a refusal."""
    from .federation_licence import REFUSED_STATES
    td = trust_domain_of(peer_spiffe)
    mine = [r for r in rows if td and str(r[2] or "").upper() == "ACTIVE"
            and (str(r[3] or "").strip().lower().removeprefix("spiffe://").strip("/")) == td]
    if not mine:
        return None, (403, "unknown_peer", "the presenting registry is not an active peer of this registry")
    named = [r for r in mine if str(r[0] or "").casefold() == str(home or "").casefold()]
    if not named:
        return None, (403, "home_mismatch", "a registry relays only its own developers' cards")
    row = sorted(named, key=lambda r: 0 if str(r[1] or "").lower() == "frame" else 1)[0]
    if str(row[4] or "") in REFUSED_STATES:
        if licence_mode == "enforce":
            return None, (403, "licence_refused", f"the home's federation licence is {row[4]}")
        logger.warning("[code-passport] %s presents with licence verdict %s (mode %s): allowed", row[0], row[4], licence_mode)
    return str(row[0]), None


def standing_change(current: str, card: str) -> Tuple[str, Optional[str]]:
    """ONE rule for a contributor's standing on the governing registry and their repository account's leg, whatever brought the card
    (an act or the standing pull): the new standing and the leg to queue (None: nothing changes on the code host)."""
    if current == "closed":
        return "closed", None                                     # deleted at home: never restored
    if card == "closed":
        return "closed", "close"
    if card == "active":
        return ("active", "restore") if current == "paused" else ("active", None)
    return ("paused", None) if current == "paused" else ("paused", "pause")


def host_full_name(display_name: Optional[str], home: str, home_developer_id: str) -> str:
    """What a contributor's code host account says of them: their public name, their home registry and their developer there."""
    name = (display_name or "").strip()
    if name and "@" not in name:
        return f"{name} ({home}, developer {home_developer_id})"
    return f"Developer {home_developer_id} of {home}"


def act_refusal(act: str) -> Optional[Refusal]:
    if act in ACTS:
        return None
    if act == "vote":
        return 403, "votes_members_only", VOTE_SENTENCE
    return 404, "unknown_act", "a contributor proposes and reviews"


def _out(r: Refusal) -> Tuple[int, Dict[str, Any]]:
    return r[0], {"code": r[1], "detail": r[2]}


# --- the home ------------------------------------------------------------------------------------------------------

def _home_name() -> str:
    from .contract_xframe import self_federation_name
    return self_federation_name() or "local"


def _governing() -> str:
    from . import code_authority
    return code_authority.governing_name() or code_authority.DEFAULT_NAME


def available() -> bool:
    """The passport exists only where a governing registry is NAMED (CODE_CHANGES_GOVERNING_REGISTRY) and this registry is not it. With
    none named nobody governs code: the governing sentence's default name is a place to go, never a registry to send cards to."""
    from . import code_authority
    return code_authority.governing_name() is not None and not code_authority.is_governing()


NO_GOVERNING: Refusal = (409, "no_governing_registry", "no registry governs code on this network yet: there is nowhere to take part")


async def _first_agent(db: Any, dev: Any, agent_did: Optional[str]) -> Any:
    from sqlalchemy import select
    from .. import models
    q = select(models.Agent).where(models.Agent.creator_developer_id == dev.id)
    q = q.where(models.Agent.did == agent_did) if agent_did else q.where(models.Agent.status == "active").order_by(models.Agent.id)
    return (await db.execute(q.limit(1))).scalars().first()


async def consent_state(db: Any, dev: Any, agent_did: Optional[str] = None) -> Dict[str, Any]:
    """What the press shows: who governs, whether this registry does, the consent, and the exact card one of the developer's agents
    would carry (a preview: unsigned, nothing disclosed)."""
    from . import code_authority
    on = available()
    agent = await _first_agent(db, dev, agent_did) if on else None
    at = getattr(dev, "code_passport_consent_at", None)
    return {"governing": _governing(), "self_governing": code_authority.is_governing(), "available": on, "home": _home_name(),
            "consented": at is not None, "consented_at": at.isoformat() if at else None,
            "preview": card_payload(dev, agent, _home_name(), dt.datetime.now(dt.timezone.utc)) if agent is not None else None,
            "votes": "members_only"}


async def set_consent(db: Any, dev: Any, on: bool) -> Dict[str, Any]:
    dev.code_passport_consent_at = dt.datetime.now(dt.timezone.utc) if on else None
    await db.commit()
    return await consent_state(db, dev)


async def signed_card(db: Any, dev: Any, agent: Any, *, requested_by: str, issued_at: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """The card for one act: the disclosure row first (purpose code_governance), then the signature. Fail closed: no row, no card."""
    from .. import models
    from ..routers.dev_card import sign_devcard_payload
    payload = card_payload(dev, agent, _home_name(), issued_at or dt.datetime.now(dt.timezone.utc))
    db.add(models.DevCardDisclosure(developer_id=dev.id, agent_did=agent.did, requested_by=requested_by[:255], purpose=PURPOSE))
    await db.flush()
    env = await sign_devcard_payload(db, payload)
    await db.commit()
    return env


async def send_to_governing(db: Any, path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """The wire: the governing registry over the federation lane (the Passport's mTLS channel)."""
    from .exchange_passport import PassportError, peer_request
    try:
        return await peer_request(db, _governing(), "POST", path, body)
    except PassportError as e:
        return 502, {"code": "governing_unreachable", "detail": str(getattr(e, "detail", e))}


async def relay(db: Any, agent: Any, act: str, args: Dict[str, Any], code_change_id: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    """An act of the developer's own agent, carried to the governing registry with a fresh card."""
    from sqlalchemy import select
    from .. import models
    from . import code_authority
    if code_authority.is_governing():
        return _out((409, "governing_here", "this registry governs code: propose and review on its Code changes view"))
    if not available():
        return _out(NO_GOVERNING)
    refused = act_refusal(act)
    if refused:
        return _out(refused)
    dev = (await db.execute(select(models.Developer).where(models.Developer.id == agent.creator_developer_id))).scalar_one_or_none()
    if dev is None:
        return _out((404, "no_developer", "the agent's developer is not on this registry"))
    if getattr(dev, "code_passport_consent_at", None) is None:
        return _out((403, "no_consent", f"press \"Take part on {_governing()}\" on the Code changes view first: nothing about you leaves "
                                        "this registry without it"))
    env = await signed_card(db, dev, agent, requested_by=_governing())
    body: Dict[str, Any] = {"dev_card": env, "args": dict(args or {})}
    if code_change_id:
        body["code_change_id"] = code_change_id
    return await send_to_governing(db, f"{FEDERATION_PATH}/{act}", body)


async def relay_for_developer(db: Any, dev: Any, act: str, args: Dict[str, Any], agent_did: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    """The console's press works in the developer's session: the card is carried by one of their own agents (the one named, else
    their first active one)."""
    agent = await _first_agent(db, dev, agent_did)
    if agent is None:
        return _out((409, "no_agent", "taking part goes through one of your own agents: create one first"))
    return await relay(db, agent, act, args)


async def standing_card(db: Any, peer_spiffe: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """The home's answer to the governing registry's standing pull: a fresh card for the developer behind one agent, only to the
    governing registry (its trust domain's ACTIVE peer row is the one CODE_CHANGES_GOVERNING_REGISTRY names) and only with consent."""
    from sqlalchemy import select
    from .. import models
    if not available():
        return _out(NO_GOVERNING)
    mode = (os.getenv("FEDERATION_LICENCE_MODE", "off") or "off").strip().lower()
    _name, refused = bind_presenter(await _peer_rows(db), peer_spiffe, _governing(), mode)
    if refused:
        return _out((403, "not_the_governing_registry", "only the registry that governs code asks for a developer's standing"))
    did = str((body or {}).get("agent_did") or "")
    agent = (await db.execute(select(models.Agent).where(models.Agent.did == did))).scalars().first() if did else None
    dev = await db.get(models.Developer, agent.creator_developer_id) if agent is not None else None
    if dev is None:
        return _out((404, "unknown_agent", "no developer of this registry stands behind that agent"))
    if getattr(dev, "code_passport_consent_at", None) is None:
        return _out((403, "no_consent", "this developer does not take part in code governance from here"))
    return 200, await signed_card(db, dev, agent, requested_by=_governing())


# --- the governing registry ----------------------------------------------------------------------------------------

async def _peer_rows(db: Any):
    from sqlalchemy import select
    from .. import models
    P = models.PeerRegistry
    return (await db.execute(select(P.name, P.peer_type, P.status, P.trust_domain, P.licence_state)
                             .where(P.trust_domain.is_not(None)))).all()


async def _contributor(db: Any, home: str, p: Dict[str, Any]) -> Any:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from .. import models
    C = models.CodeContributor
    await db.execute(pg_insert(C).values(home_registry=home, home_developer_id=p["developer_ref"], standing="active")
                     .on_conflict_do_nothing(index_elements=["home_registry", "home_developer_id"]))
    row = (await db.execute(select(C).where(C.home_registry == home, C.home_developer_id == p["developer_ref"])
                            .with_for_update())).scalar_one()
    row.display_name = p.get("display_name")
    row.agent_did = p.get("agent_did")
    row.last_act_at = dt.datetime.now(dt.timezone.utc)
    return row


async def accept(db: Any, peer_spiffe: str, act: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """A relayed act on the governing registry: the presenter, the card, the contributor, its standing, then the rail's own step."""
    from . import code_authority, code_changes
    from .exchange_passport import PassportError, verify_devcard_envelope
    if not code_authority.is_governing():
        await code_authority.warm_peer_link(db, _governing())
        return _out((403, "code_change_not_governed_here", code_authority.sentence()))
    refused = act_refusal(act)
    if refused:
        return _out(refused)
    env = (body or {}).get("dev_card")
    refused = card_refusal(env, dt.datetime.now(dt.timezone.utc))
    if refused:
        return _out(refused)
    p = env["payload"]
    mode = (os.getenv("FEDERATION_LICENCE_MODE", "off") or "off").strip().lower()
    home, refused = bind_presenter(await _peer_rows(db), peer_spiffe, p["home_registry"], mode)
    if refused:
        return _out(refused)
    try:
        await verify_devcard_envelope(db, p["agent_did"], env, home_hint=home)
    except PassportError as e:
        return _out((403, "card_signature", f"the card does not verify against {home}'s published keys: {getattr(e, 'detail', e)}"))
    c = await _contributor(db, home, p)
    await apply_standing(db, c, p["standing"], cause=f"card_{p['standing']}")
    await db.commit()
    if c.standing == "closed":
        return _out((403, "contributor_closed", f"{home} closed this developer's account: their part here ended"))
    if c.standing != "active":
        return _out((403, "home_suspended", f"{home} says this developer is not in good standing: their acts here are paused until "
                                            "it says otherwise"))
    key = contributor_key(c.id)
    args = dict((body or {}).get("args") or {})
    if act in ("repo_status", "repo_link"):
        return await _repo_act(db, key, act, args)
    actor = {"did": p["agent_did"], "developer_id": key,
             "contributor": {"id": c.id, "home_registry": home, "home_developer_id": c.home_developer_id}}
    flow = code_changes.CodeChangeFlow(code_changes.store_for(db))
    try:
        if act == "propose":
            from . import repo_accounts
            try:                                # with the code host open, a contributor proposes with a linked account, as a member does
                await repo_accounts.RepoAccounts(repo_accounts.DbStore(db)).require_linked(key)
            except repo_accounts.RepoAccountRefusal as r:
                return r.status, {"code": r.code, "detail": r.sentence}
            return 201, await flow.propose(actor, args)
        return 200, await flow.review(actor, str((body or {}).get("code_change_id") or ""), args)
    except code_changes.CodeChangeRefusal as r:
        return r.status, {"code": r.code, "detail": r.sentence}


async def apply_standing(db: Any, c: Any, card_standing: str, *, cause: str) -> None:
    """The card's standing onto the contributor row (standing_change), and the repository account's leg in the same transaction."""
    new, leg = standing_change(c.standing, card_standing)
    if new != c.standing:
        c.standing = new
        c.paused_at = None if new == "active" else dt.datetime.now(dt.timezone.utc)
    if leg:
        from . import repo_accounts
        await repo_accounts.RepoAccounts(repo_accounts.DbStore(db)).enqueue(contributor_key(c.id), leg, cause)


async def _repo_act(db: Any, key: int, act: str, args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """The contributor's repository account on the code host (phase 4): its status, or the link, with a member's rules."""
    from . import repo_accounts as ra
    flow = ra.RepoAccounts(ra.DbStore(db), ra.ForgejoClient())
    if act == "repo_status":
        out = await flow.status(key)
        return 200, out
    try:
        out = await flow.link(key, args)
    except ra.RepoAccountRefusal as r:
        return r.status, {"code": r.code, "detail": r.sentence}
    served = out.pop("terms_version")
    await ra.DbStore(db).update_account(key, terms_version=served, terms_accepted_at=dt.datetime.now(dt.timezone.utc))
    try:
        await db.commit()
    except Exception:  # noqa: BLE001 - the host user was made before this commit: it must not outlive a link not recorded
        await db.rollback()
        await flow.undo_link(out["username"])
        return 503, {"code": "not_recorded", "detail": "the link could not be recorded: nothing was kept, try again"}
    return 201, out


async def ask_home(db: Any, home: str, agent_did: str) -> Tuple[int, Dict[str, Any]]:
    """The wire of the standing pull: the contributor's home over the federation lane."""
    from .exchange_passport import PassportError, peer_request
    try:
        return await peer_request(db, home, "POST", STANDING_PATH, {"agent_did": agent_did})
    except PassportError as e:
        return 502, {"code": "home_unreachable", "detail": str(getattr(e, "detail", e))}


async def pull_standing_once(db: Any, limit: int = STANDING_PULL_LIMIT) -> int:
    """On the governing registry: for each contributor whose code host account is not closed, a fresh card from their home, verified
    as an act's card is, its standing applied by the one rule. A git push needs no act, so this is how a suspension at home reaches
    the code host. A home that answers no consent pauses them (they stopped taking part); an unreachable home changes nothing and is
    counted (the worker reports it). Answers how many contributors were read."""
    from sqlalchemy import select
    from .. import models
    from . import code_authority
    from .exchange_passport import PassportError, verify_devcard_envelope
    if not code_authority.is_governing():
        return 0
    C, A = models.CodeContributor, models.ContributorRepoAccount
    rows = (await db.execute(select(C).join(A, A.contributor_id == C.id).where(A.state != "closed", C.standing != "closed",
                                                                              C.agent_did.is_not(None))
                             .order_by(C.id).limit(limit))).scalars().all()
    read = 0
    for c in rows:
        status, env = await ask_home(db, c.home_registry, c.agent_did)
        if status == 403 and (env or {}).get("code") == "no_consent":
            await apply_standing(db, c, "suspended", cause="consent_withdrawn")
            await db.commit()
            read += 1
            continue
        if status != 200 or card_refusal(env, dt.datetime.now(dt.timezone.utc)):
            logger.warning("[code-passport] standing of contributor %s not read from %s (HTTP %s)", c.id, c.home_registry, status)
            continue
        p = env["payload"]
        if str(p.get("home_registry", "")).casefold() != c.home_registry.casefold() or p.get("developer_ref") != c.home_developer_id \
                or p.get("agent_did") != c.agent_did:
            logger.warning("[code-passport] %s answered a card for someone else (contributor %s): ignored", c.home_registry, c.id)
            continue
        try:
            await verify_devcard_envelope(db, c.agent_did, env, home_hint=c.home_registry)
        except PassportError as e:
            logger.warning("[code-passport] contributor %s: %s's card does not verify: %s", c.id, c.home_registry, getattr(e, "detail", e))
            continue
        await apply_standing(db, c, p["standing"], cause=f"home_{p['standing']}")
        await db.commit()
        read += 1
    return read
