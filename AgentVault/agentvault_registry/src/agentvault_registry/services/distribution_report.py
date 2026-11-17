"""V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7; DESIGN_2026-11-15_DISTRIBUTIONS.md section 7): the signed per-release report of an organization's release line, and the signed record of one change.

  the report   `distribution.release.report`: for ONE release of the line (`<base_release>_<slug>`) every change it carries, code and content, in every state: who proposed (developer and agent), who
               reviewed, the ballot (the rule it opened with, its end, its result, EACH vote), our checker's record, what was applied or merged, and the protected-set verdict, which reads `not_measured`
               and says why until the line's builds (D6) exist: a verdict nobody measured is never a pass. A content change's text is not in it: its sha256 is, so the organization's own copy can be held
               against it. Everything is a developer id, never a name.
  the record   `distribution.change.record`: one change of the line, the same entry, the same envelope.
  the envelope {envelope_version, registry_spiffe_id, kind, subject, digest, report, signature}; digest = sha256 of the report's canonical JSON (sort_keys, tight separators: the registry card's own
               convention); signature = EdDSA with the registry's card key over the canonical JSON of {registry_spiffe_id, kind, subject, digest}, kid `<spiffe_id>#<rotation_seq>`, the key published at
               /.well-known/registry-jwks.json. Checked OFFLINE with the registry's published keys and nothing else (theprotocol.distributions.verify_envelope in the SDK): one changed byte anywhere in the
               report fails the digest, and nothing else in the envelope can be re-pointed without failing the signature.
Read-only: it writes nothing (Δ-irrelevant); the line's records are the rail's own, this only states them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict, List, Optional

ENVELOPE_VERSION = 1
REPORT_KIND = "distribution.release.report"
RECORD_KIND = "distribution.change.record"
SIGNED_PATHS = ["registry_spiffe_id", "kind", "subject", "digest"]
PROTECTED_SET_REASON = ("the line's builds do not exist yet (D6): the protected set is checked on every build against its base release, so there is no verdict to state; "
                        "this report never reads as a pass for what nobody measured")


def canonical(doc: Any) -> bytes:
    """The registry card's own convention (registry_card_signer_impl._canonical_bytes): sort_keys, tight separators, default=str."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def digest_of(doc: Any) -> str:
    return hashlib.sha256(canonical(doc)).hexdigest()


def protected_set_section(verdict: Any = None) -> Dict[str, Any]:
    """The report's protected-set section (D6: the check of a build against its base release). With no build's verdict it reads `not_measured` and says why; with one (services/distribution_protected.verdict's
    dict: 'intact' or 'refused', its refusals, its areas, what it removed, what it cannot see) it carries that dict WHOLE and unchanged: each refusal as its own fields (area, path, kind, a line number when
    there is one, whatever the check adds later), never reduced to a fixed list of kinds, because the check gains kinds and a report that renders only the kinds it knew would hide the new ones."""
    if isinstance(verdict, dict) and verdict.get("verdict") in ("intact", "refused"):
        return {"status": verdict["verdict"], "details": json.loads(json.dumps(verdict, default=str))}
    return {"status": "not_measured", "reason": PROTECTED_SET_REASON}


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, dt.datetime) else v


def _votes(rows: List[Any]) -> List[Dict[str, Any]]:
    return [{"developer_id": r.developer_id, "vote": bool(r.vote), "agent_did": r.agent_did, "cast_at": _iso(r.cast_at)}
            for r in sorted(rows, key=lambda r: (r.cast_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc), r.developer_id))]


def _content_entry(c: Any, votes: List[Any]) -> Dict[str, Any]:
    return {"id": c.id, "kind": "content", "change_kind": c.kind, "target": c.target, "title": c.title, "state": c.state, "created_at": _iso(c.created_at),
            "proposer": {"developer_id": c.proposer_developer_id, "agent_did": c.proposer_did},
            "ballot": {"rule": c.ballot_rule, "ends": _iso(c.ballot_ends), "result": c.ballot_result, "votes": _votes(votes)},
            "checker": {k: v for k, v in (c.checker or {}).items() if k != "after"},          # the verdict's own `after` is the content's text: the report keeps its hash only
            "reviews": [], "content_hash": digest_of(c.content),
            "outcome": {"applied_at": _iso(c.applied_at), "before_hash": digest_of(c.before) if c.before is not None else None,
                        "after_hash": digest_of(c.after) if c.after is not None else None, "apply_error": c.apply_error, "undone": c.undone}}


def _code_entry(c: Any, votes: List[Any], reviews: List[Any]) -> Dict[str, Any]:
    return {"id": c.id, "kind": "code", "change_kind": None, "target": c.repository, "title": c.title, "state": c.state, "created_at": _iso(c.created_at),
            "proposer": {"developer_id": c.proposer_developer_id, "agent_did": c.proposer_did},
            "ballot": {"rule": c.ballot_rule, "ends": _iso(c.ballot_ends), "result": c.ballot_result, "votes": _votes(votes)},
            "checker": {"acceptance": c.acceptance},
            "reviews": [{"reviewer_developer_id": r.reviewer_developer_id, "verdict": r.verdict, "commit": r.commit, "at": _iso(r.created_at)}
                        for r in sorted(reviews, key=lambda r: (r.created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc), r.id))],
            "content_hash": None,
            "outcome": {"commit": c.commit, "branch": c.branch, "paths": c.paths, "sensitive": bool(c.sensitive), "passed_at": _iso(c.passed_at),
                        "merged": c.merged, "veto": c.veto, "go": c.go, "org_go": c.org_go}}


async def _entries(db: Any, dist_id: str, only: Optional[str] = None) -> List[Dict[str, Any]]:
    from sqlalchemy import select
    from .. import models
    out: List[Dict[str, Any]] = []
    C, V = models.ContentChange, models.ContentChangeVote
    q = select(C).where(C.code_distribution_id == dist_id)
    if only:
        q = q.where(C.id == only)
    for c in (await db.execute(q)).scalars().all():
        votes = (await db.execute(select(V).where(V.content_change_id == c.id))).scalars().all()
        out.append(_content_entry(c, votes))
    K, KV, KR = models.CodeChange, models.CodeDistributionVote, models.CodeChangeReview
    q = select(K).where(K.code_distribution_id == dist_id)
    if only:
        q = q.where(K.id == only)
    for c in (await db.execute(q)).scalars().all():
        votes = (await db.execute(select(KV).where(KV.code_change_id == c.id))).scalars().all()
        reviews = (await db.execute(select(KR).where(KR.code_change_id == c.id))).scalars().all()
        out.append(_code_entry(c, votes, reviews))
    return sorted(out, key=lambda e: (str(e["created_at"]), e["id"]))


def release_name(dist: Dict[str, Any]) -> str:
    return f"{dist['base_release']}_{dist['slug']}"


async def _head(db: Any, dist: Dict[str, Any], kind: str) -> Dict[str, Any]:
    from .registry_card_builder import _build_spiffe_id, federation_name
    from . import code_distributions as cd
    from . import content_changes as cc
    store = cc.store_for(db)
    who, _why = await cd.deciders(store, dist, None)
    names = await store.organization_names([dist["organization_id"]])
    return {"kind": kind, "release": release_name(dist), "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "registry": {"name": federation_name(), "spiffe_id": _build_spiffe_id()},
            "line": {"slug": dist["slug"], "title": dist["title"], "base_release": dist["base_release"], "organization_id": dist["organization_id"],
                     "organization_name": names.get(dist["organization_id"]), "state": dist["state"], "open_paths": dist["open_paths"],
                     "quorum_percent": dist["quorum_percent"], "pass_rule": dist["pass_rule"], "decider_team_id": dist.get("decider_team_id")},
            "deciders_now": len(who)}


async def build_report(db: Any, dist: Dict[str, Any], verdict: Any = None) -> Dict[str, Any]:
    body = await _head(db, dist, REPORT_KIND)
    changes = await _entries(db, dist["id"])
    by_state: Dict[str, int] = {}
    for c in changes:
        by_state[c["state"]] = by_state.get(c["state"], 0) + 1
    body["report_version"] = ENVELOPE_VERSION
    body["changes"] = changes
    body["counts"] = {"changes": len(changes), "code": sum(1 for c in changes if c["kind"] == "code"), "content": sum(1 for c in changes if c["kind"] == "content"),
                      "by_state": dict(sorted(by_state.items()))}
    body["protected_set"] = protected_set_section(verdict)          # the line's latest build's verdict, when a build exists (D6 part 3 passes it); else not measured
    return body


async def build_record(db: Any, dist: Dict[str, Any], cid: str) -> Optional[Dict[str, Any]]:
    entries = await _entries(db, dist["id"], only=cid)
    if not entries:
        return None
    body = await _head(db, dist, RECORD_KIND)
    body["record_version"] = ENVELOPE_VERSION
    body["change"] = entries[0]
    return body


async def sign(db: Any, kind: str, subject: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """The envelope: the body, its digest, and the registry's card-key signature over {registry_spiffe_id, kind, subject, digest}."""
    from .registry_card_builder import _build_spiffe_id
    from .registry_card_keystore import get_or_mint_signing_key
    from .registry_card_signer_impl import sign_with_keypair
    spiffe_id = _build_spiffe_id()
    envelope: Dict[str, Any] = {"envelope_version": ENVELOPE_VERSION, "registry_spiffe_id": spiffe_id, "kind": kind, "subject": subject, "digest": digest_of(body), "report": body}
    key_row = await get_or_mint_signing_key(db, spiffe_id)
    envelope["signature"] = {"alg": "EdDSA", "kid": f"{spiffe_id}#{key_row.rotation_seq}", "jwks_url": "/.well-known/registry-jwks.json",
                             "signed_canonical": list(SIGNED_PATHS), "value": sign_with_keypair({p: envelope[p] for p in SIGNED_PATHS}, key_row)}
    return envelope
