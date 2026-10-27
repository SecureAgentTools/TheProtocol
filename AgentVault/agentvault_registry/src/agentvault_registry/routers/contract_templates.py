"""CONTRACT TEMPLATES — frozen, versioned agreements that mint contracts (P4, 2026-07-25).

One library serving every origination surface, free AND paid:
  free      royalty_bps=0, no purchase — always instantiable.
  purchase  up-front price in frame currency — the CICD paid-template rail re-keyed
            `ctpl:{template}:{buyer}:{in,out}` (buyer→treasury→author, exactly-once, 402 on
            decline); one purchase per buyer, then instantiate free forever.
  royalty   carved from the payout AT SETTLE (`m{seq}:settle_tpl` leg inside
            contract_settlement.compute_release_legs) — the author earns when work actually pays
            out. Snapshotted onto the contract at mint (I-C5); never blocks settlement (I-C9).

THE SAFETY PROPERTY (I-C7): a published version is IMMUTABLE and instantiation COPIES its payload
into the contract (recording template_version_id + content_hash provenance). A contract NEVER
dereferences its template at runtime — editing a template cannot reach a signed agreement.

INSTITUTIONAL SCALE (§P4.5): `terms_schema` (JSON Schema) turns a template into a FORM — the
instantiated terms are validated against it at mint. `visibility='unlisted'` = instantiable by
anyone holding the id, never listed (how a government org/NGO hands a procurement form to invited
external contractors). The version payload (terms + terms_schema + milestones + content_hash) IS
the ERP interchange format: export = GET the version verbatim, import = POST the same payload.

Gated CONTRACT_TEMPLATES_ENABLED. Reads never emit (I-C8).
"""
import datetime as _dt
import hashlib
import json
import logging
import os
import secrets
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.security import (
    get_current_agent, get_current_developer, get_current_actor_for_read,
    require_agent_permission,
)
from agentvault_registry.services import escrow
from agentvault_registry.services import contract_settlement as cs

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Contract Templates"])

_Q = Decimal("0.0000000001")
_FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
VISIBILITIES = ("private", "org", "unlisted", "public")
PRICING = ("free", "purchase", "royalty")


def templates_enabled() -> bool:
    return os.getenv("CONTRACT_TEMPLATES_ENABLED", "false").strip().lower() == "true"


def _require_enabled():
    if not templates_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Contract templates are disabled on this registry")


def content_hash(terms, terms_schema, milestones) -> str:
    """sha256 over the canonical payload — the ERP interchange integrity check and the
    cross-frame relay verification (P5)."""
    canonical = json.dumps({"terms": terms, "terms_schema": terms_schema,
                            "milestones": milestones},
                           sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_schema_def(schema: Optional[dict]) -> None:
    """A terms_schema must itself be a valid JSON Schema (D9: jsonschema lib, slim fallback)."""
    if schema is None:
        return
    if not isinstance(schema, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="terms_schema must be an object")
    try:
        import jsonschema as _js
        _js.validators.validator_for(schema).check_schema(schema)
    except ImportError:
        if schema.get("type") not in (None, "object"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="terms_schema: only object schemas supported (fallback validator)")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"terms_schema is not a valid JSON Schema: {str(e)[:200]}")


def validate_terms_against(schema: Optional[dict], terms: Optional[dict]) -> None:
    """FORM validation at instantiate: the contract's terms must satisfy the template's schema.

    The fallback path (jsonschema absent) is deliberately STRICT rather than presence-only: a
    required field that is present-but-empty is treated as missing, and minLength is honoured.
    Presence-only was the 2026-07-25 seed-probe bug — templates that pre-fill their required keys
    with "" sailed through an 'incomplete form' check that should have 422'd."""
    if not schema:
        return
    inst = terms or {}
    try:
        import jsonschema as _js
    except ImportError:
        _fallback_validate(schema, inst)
        return
    try:
        _js.validate(instance=inst, schema=schema)
    except _js.ValidationError as e:
        path = ".".join(str(p) for p in getattr(e, "absolute_path", []) or []) or "(root)"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"terms do not satisfy the template's form schema at "
                                   f"'{path}': {str(e.message)[:240]}")
    except Exception as e:  # noqa: BLE001 — schema-machinery failure, not a user error
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"terms do not satisfy the template's form schema: {str(e)[:300]}")


def _fallback_validate(schema: dict, inst: dict) -> None:
    """Slim validator for images without `jsonschema`: required (empty ⇒ missing), type, minLength,
    maxLength, enum on top-level scalar properties. Never MORE permissive than the real thing."""
    props = schema.get("properties") or {}
    for req in schema.get("required", []):
        v = inst.get(req)
        if v is None or (isinstance(v, (str, list, dict)) and len(v) == 0):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"terms: required field '{req}' is missing or empty (template form)")
    for key, spec in props.items():
        if key not in inst or not isinstance(spec, dict):
            continue
        v, want = inst[key], spec.get("type")
        pytype = {"string": str, "integer": int, "number": (int, float),
                  "boolean": bool, "array": list, "object": dict}.get(want)
        if pytype and not isinstance(v, pytype):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"terms.{key}: expected {want}")
        if isinstance(v, str):
            if spec.get("minLength") is not None and len(v) < int(spec["minLength"]):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail=f"terms.{key}: shorter than minLength {spec['minLength']}")
            if spec.get("maxLength") is not None and len(v) > int(spec["maxLength"]):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail=f"terms.{key}: longer than maxLength {spec['maxLength']}")
        if spec.get("enum") and v not in spec["enum"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"terms.{key}: not one of {spec['enum']}")


def _validate_milestones_def(ms: Optional[list]) -> Optional[list]:
    """Template milestones are PERCENTAGES (scaled to the instantiated total): last one absorbs
    rounding so instantiated amounts re-sum exactly (I-C6)."""
    if ms is None:
        return None
    if not isinstance(ms, list) or not ms or len(ms) > 50:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="milestones: 1..50 entries")
    out, total = [], 0.0
    for i, m in enumerate(ms, 1):
        if not isinstance(m, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"milestones[{i}]: object required")
        pct = float(m.get("amount_pct", 0))
        if pct < 0 or pct > 100:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"milestones[{i}].amount_pct: 0..100")
        total += pct
        out.append({"title": str(m.get("title") or f"Milestone {i}")[:200], "amount_pct": pct,
                    "terms": m.get("terms") if isinstance(m.get("terms"), dict) else None,
                    "due_days": int(m["due_days"]) if str(m.get("due_days") or "").isdigit() else None})
    if abs(total - 100.0) > 0.001:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"milestones amount_pct must sum to 100 (got {total})")
    return out


async def _load_tpl(db: AsyncSession, tid: str) -> dict:
    row = (await db.execute(text("SELECT * FROM contract_templates WHERE id=:t"), {"t": tid})).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Template not found")
    return dict(row)


async def _actor_may_see(db: AsyncSession, t: dict, actor: dict, *, listing: bool) -> bool:
    vis = t["visibility"]
    if vis == "public":
        return True
    if vis == "unlisted":
        return not listing            # reachable by id, never listed
    if actor.get("kind") == "developer":
        return True                   # X34 posture: dev JWT = full read
    did = actor.get("agent_did")
    if did == t["owner_agent_did"]:
        return True
    if vis == "org" and t.get("source_org_id") and did:
        org = (await db.execute(text("SELECT organization_id FROM agents WHERE did=:d"), {"d": did})).scalar()
        return str(org or "") == str(t["source_org_id"])
    return False


def _tpl_out(t: dict) -> dict:
    out = dict(t)
    if out.get("price") is not None:
        out["price"] = str(out["price"])
    return out


# ── schemas ──────────────────────────────────────────────────────────────────────────────────

class TemplateCreateIn(BaseModel):
    slug: str = Field(..., max_length=120, pattern=r"^[a-z0-9][a-z0-9\-]{1,118}$")
    title: str = Field(..., max_length=200)
    summary: Optional[str] = Field(None, max_length=500)
    contract_type: str = Field("work_order", max_length=32)
    visibility: str = Field("private")
    pricing_model: str = Field("free")
    price: Optional[Any] = None
    royalty_bps: int = Field(0, ge=0, le=500)
    # first draft version payload (v1 created inline)
    terms: Optional[Dict[str, Any]] = None
    terms_schema: Optional[Dict[str, Any]] = None
    milestones: Optional[List[Dict[str, Any]]] = None
    suggested_amount: Optional[Any] = None
    suggested_deadline_seconds: Optional[int] = Field(None, ge=60, le=366 * 86400)


class VersionIn(BaseModel):
    terms: Optional[Dict[str, Any]] = None
    terms_schema: Optional[Dict[str, Any]] = None
    milestones: Optional[List[Dict[str, Any]]] = None
    suggested_amount: Optional[Any] = None
    suggested_deadline_seconds: Optional[int] = Field(None, ge=60, le=366 * 86400)
    changelog: Optional[str] = Field(None, max_length=500)


class TemplatePatchIn(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    summary: Optional[str] = Field(None, max_length=500)
    visibility: Optional[str] = None
    pricing_model: Optional[str] = None
    price: Optional[Any] = None
    royalty_bps: Optional[int] = Field(None, ge=0, le=500)
    maintained_by_org_id: Optional[str] = Field(None, max_length=64)


class InstantiateIn(BaseModel):
    version: Optional[int] = None                 # default: current published
    total_amount: Optional[Any] = None            # default: suggested_amount
    provider_did: Optional[str] = Field(None, max_length=120)
    terms_overrides: Optional[Dict[str, Any]] = None
    deadline_seconds: Optional[int] = Field(None, ge=60, le=366 * 86400)


class ForkIn(BaseModel):
    slug: str = Field(..., max_length=120, pattern=r"^[a-z0-9][a-z0-9\-]{1,118}$")
    title: Optional[str] = Field(None, max_length=200)


# ── library CRUD ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/v1/contracts/templates", summary="Browse the template library")
async def list_templates(q: Optional[str] = None, contract_type: Optional[str] = None,
                         pricing_model: Optional[str] = None, mine: bool = False,
                         limit: int = 20, cursor: Optional[str] = None,
                         actor: dict = Depends(get_current_actor_for_read),
                         db: AsyncSession = Depends(get_db)):
    _require_enabled()
    limit = max(1, min(100, limit))
    params: Dict[str, Any] = {"lim": limit}
    if mine and actor.get("kind") == "agent":
        where = "owner_agent_did = :me"
        params["me"] = actor["agent_did"]
    elif actor.get("kind") == "developer":
        where = "visibility IN ('public','org','unlisted','private')" if mine else "visibility = 'public'"
    else:
        did = actor.get("agent_did")
        org = None
        if did:
            org = (await db.execute(text(
                "SELECT organization_id FROM agents WHERE did=:d"), {"d": did})).scalar()
        where = "(visibility='public' OR owner_agent_did=:me OR (visibility='org' AND source_org_id=:org))"
        params["me"] = did or ""
        params["org"] = str(org) if org else "__none__"
    if q:
        where += " AND (title ILIKE :q OR summary ILIKE :q OR slug ILIKE :q)"
        params["q"] = f"%{q[:80]}%"
    if contract_type:
        where += " AND contract_type = :ct"; params["ct"] = contract_type
    if pricing_model:
        where += " AND pricing_model = :pm"; params["pm"] = pricing_model
    if cursor:
        where += " AND id < :cur"; params["cur"] = cursor
    rows = (await db.execute(text(
        f"SELECT * FROM contract_templates WHERE {where} ORDER BY id DESC LIMIT :lim"),
        params)).mappings().all()
    items = [_tpl_out(dict(r)) for r in rows]
    return {"items": items, "next_cursor": rows[-1]["id"] if len(rows) == limit else None}


@router.get("/api/v1/contracts/templates/{tid}", summary="Template detail + version index")
async def get_template(tid: str, actor: dict = Depends(get_current_actor_for_read),
                       db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    if not await _actor_may_see(db, t, actor, listing=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not visible to you")
    vers = (await db.execute(text(
        "SELECT id, version, changelog, content_hash, published_at, created_at "
        "FROM contract_template_versions WHERE template_id=:t ORDER BY version DESC"),
        {"t": tid})).mappings().all()
    # settle-rate: outcomes, not adjectives — completed / (completed + disputed + cancelled)
    stats = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE c.status='completed')           AS done,
               count(*) FILTER (WHERE c.status IN ('disputed','cancelled')) AS bad
        FROM contracts c JOIN contract_template_versions v ON v.id = c.template_version_id
        WHERE v.template_id = :t
    """), {"t": tid})).first()
    done, bad = (stats[0] or 0), (stats[1] or 0)
    out = _tpl_out(t)
    out["versions"] = [dict(v) for v in vers]
    out["settle_rate"] = round(done / (done + bad), 4) if (done + bad) else None
    return out


@router.get("/api/v1/contracts/templates/{tid}/versions/{n}",
            summary="A frozen version, verbatim (the ERP export format)")
async def get_template_version(tid: str, n: int,
                               actor: dict = Depends(get_current_actor_for_read),
                               db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    if not await _actor_may_see(db, t, actor, listing=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not visible to you")
    v = (await db.execute(text(
        "SELECT * FROM contract_template_versions WHERE template_id=:t AND version=:v"),
        {"t": tid, "v": n})).mappings().first()
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Version not found")
    v = dict(v)
    if v.get("suggested_amount") is not None:
        v["suggested_amount"] = str(v["suggested_amount"])
    return v


@router.post("/api/v1/contracts/templates", status_code=status.HTTP_201_CREATED,
             summary="Create a template (draft v1 inline)")
async def create_template(body: TemplateCreateIn,
                          agent: models.Agent = Security(require_agent_permission("contract.template.publish")),
                          db: AsyncSession = Depends(get_db)):
    _require_enabled()
    from agentvault_registry.input_validators import validate_safe_text
    if body.visibility not in VISIBILITIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"visibility ∈ {VISIBILITIES}")
    if body.pricing_model not in PRICING:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"pricing_model ∈ {PRICING}")
    price, ccy = None, None
    if body.pricing_model == "purchase":
        price = Decimal(str(body.price or 0)).quantize(_Q)
        if price <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="purchase pricing needs price > 0")
        ccy = _FRAME_CCY
    royalty = body.royalty_bps if body.pricing_model == "royalty" else 0
    if body.pricing_model == "royalty" and royalty <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="royalty pricing needs royalty_bps > 0")
    _validate_schema_def(body.terms_schema)
    ms = _validate_milestones_def(body.milestones)
    org = (await db.execute(text("SELECT organization_id FROM agents WHERE did=:d"),
                            {"d": agent.did})).scalar()
    tid = "ctpl_" + secrets.token_hex(10)
    vid = "ctpv_" + secrets.token_hex(10)
    try:
        await db.execute(text("""
            INSERT INTO contract_templates (id, slug, title, summary, owner_agent_did, source_org_id,
                contract_type, visibility, pricing_model, price, price_currency, royalty_bps, updated_at)
            VALUES (:id,:sl,:t,:su,:o,:org,:ct,:v,:pm,:p,:pc,:rb, now())
        """), {"id": tid, "sl": body.slug, "t": validate_safe_text(body.title, "title")[:200],
               "su": (validate_safe_text(body.summary, "summary")[:500] if body.summary else None),
               "o": agent.did, "org": str(org) if org else None, "ct": body.contract_type,
               "v": body.visibility, "pm": body.pricing_model, "p": price, "pc": ccy, "rb": royalty})
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="slug already exists for this owner")
    await db.execute(text("""
        INSERT INTO contract_template_versions (id, template_id, version, terms, terms_schema,
            milestones, suggested_amount, suggested_currency, suggested_deadline_seconds,
            changelog, content_hash)
        VALUES (:id,:t,1,CAST(:tm AS JSONB),CAST(:ts AS JSONB),CAST(:ms AS JSONB),:sa,:sc,:sd,
                'initial draft',:h)
    """), {"id": vid, "t": tid,
           "tm": json.dumps(body.terms) if body.terms is not None else None,
           "ts": json.dumps(body.terms_schema) if body.terms_schema is not None else None,
           "ms": json.dumps(ms) if ms is not None else None,
           "sa": Decimal(str(body.suggested_amount)).quantize(_Q) if body.suggested_amount is not None else None,
           "sc": _FRAME_CCY, "sd": body.suggested_deadline_seconds,
           "h": content_hash(body.terms, body.terms_schema, ms)})
    await db.commit()
    logger.info("[CTPL] %s created by %s (%s/%s)", tid, agent.did, body.pricing_model, body.visibility)
    return {"template_id": tid, "version_id": vid, "version": 1, "published": False}


@router.post("/api/v1/contracts/templates/{tid}/versions", status_code=status.HTTP_201_CREATED,
             summary="New draft version (owner)")
async def create_version(tid: str, body: VersionIn,
                         agent: models.Agent = Security(require_agent_permission("contract.template.publish")),
                         db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    if t["owner_agent_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the owner can version")
    _validate_schema_def(body.terms_schema)
    ms = _validate_milestones_def(body.milestones)
    n = (await db.execute(text(
        "SELECT COALESCE(MAX(version),0)+1 FROM contract_template_versions WHERE template_id=:t"),
        {"t": tid})).scalar()
    vid = "ctpv_" + secrets.token_hex(10)
    await db.execute(text("""
        INSERT INTO contract_template_versions (id, template_id, version, terms, terms_schema,
            milestones, suggested_amount, suggested_currency, suggested_deadline_seconds,
            changelog, content_hash)
        VALUES (:id,:t,:v,CAST(:tm AS JSONB),CAST(:ts AS JSONB),CAST(:ms AS JSONB),:sa,:sc,:sd,:cl,:h)
    """), {"id": vid, "t": tid, "v": int(n),
           "tm": json.dumps(body.terms) if body.terms is not None else None,
           "ts": json.dumps(body.terms_schema) if body.terms_schema is not None else None,
           "ms": json.dumps(ms) if ms is not None else None,
           "sa": Decimal(str(body.suggested_amount)).quantize(_Q) if body.suggested_amount is not None else None,
           "sc": _FRAME_CCY, "sd": body.suggested_deadline_seconds,
           "cl": (body.changelog or "")[:500],
           "h": content_hash(body.terms, body.terms_schema, ms)})
    await db.commit()
    return {"template_id": tid, "version_id": vid, "version": int(n), "published": False}


@router.post("/api/v1/contracts/templates/{tid}/versions/{n}/publish",
             summary="FREEZE a version: irreversible (owner)")
async def publish_version(tid: str, n: int,
                          agent: models.Agent = Security(require_agent_permission("contract.template.publish")),
                          db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    if t["owner_agent_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the owner can publish")
    res = await db.execute(text(
        "UPDATE contract_template_versions SET published_at=now() "
        "WHERE template_id=:t AND version=:v AND published_at IS NULL RETURNING id"),
        {"t": tid, "v": n})
    row = res.first()
    if not row:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Version missing or already published (frozen)")
    await db.execute(text(
        "UPDATE contract_templates SET current_version_id=:v, updated_at=now() WHERE id=:t"),
        {"v": row[0], "t": tid})
    await db.commit()
    cs.emit("ContractTemplatePublished", tid, {"version": n, "by": agent.did})
    return {"template_id": tid, "version": n, "published": True, "version_id": row[0]}


@router.patch("/api/v1/contracts/templates/{tid}",
              summary="Edit metadata, visibility or pricing, NEVER version content (owner)")
async def patch_template(tid: str, body: TemplatePatchIn,
                         agent: models.Agent = Security(require_agent_permission("contract.template.publish")),
                         db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    if t["owner_agent_did"] != agent.did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the owner can edit")
    sets, params = [], {"t": tid}
    if body.title is not None:
        from agentvault_registry.input_validators import validate_safe_text
        sets.append("title=:ti"); params["ti"] = validate_safe_text(body.title, "title")[:200]
    if body.summary is not None:
        from agentvault_registry.input_validators import validate_safe_text
        sets.append("summary=:su"); params["su"] = validate_safe_text(body.summary, "summary")[:500]
    if body.visibility is not None:
        if body.visibility not in VISIBILITIES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"visibility ∈ {VISIBILITIES}")
        sets.append("visibility=:vi"); params["vi"] = body.visibility
    if body.pricing_model is not None:
        if body.pricing_model not in PRICING:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"pricing_model ∈ {PRICING}")
        sets.append("pricing_model=:pm"); params["pm"] = body.pricing_model
    if body.price is not None:
        sets.append("price=:pr, price_currency=:pc")
        params["pr"] = Decimal(str(body.price)).quantize(_Q); params["pc"] = _FRAME_CCY
    if body.royalty_bps is not None:
        sets.append("royalty_bps=:rb"); params["rb"] = body.royalty_bps
    if body.maintained_by_org_id is not None:
        sets.append("maintained_by_org_id=:mo"); params["mo"] = body.maintained_by_org_id or None
    if not sets:
        return _tpl_out(t)
    await db.execute(text(f"UPDATE contract_templates SET {', '.join(sets)}, updated_at=now() WHERE id=:t"),
                     params)
    await db.commit()
    return _tpl_out(await _load_tpl(db, tid))


@router.post("/api/v1/contracts/templates/{tid}/fork", status_code=status.HTTP_201_CREATED,
             summary="Fork a visible template (lineage recorded; royalty NOT inherited)")
async def fork_template(tid: str, body: ForkIn,
                        agent: models.Agent = Security(require_agent_permission("contract.template.publish")),
                        db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    actor = {"kind": "agent", "agent_did": agent.did}
    if not await _actor_may_see(db, t, actor, listing=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not visible to you")
    src = None
    if t.get("current_version_id"):
        src = (await db.execute(text(
            "SELECT * FROM contract_template_versions WHERE id=:v"),
            {"v": t["current_version_id"]})).mappings().first()
    org = (await db.execute(text("SELECT organization_id FROM agents WHERE did=:d"),
                            {"d": agent.did})).scalar()
    nid = "ctpl_" + secrets.token_hex(10)
    vid = "ctpv_" + secrets.token_hex(10)
    try:
        await db.execute(text("""
            INSERT INTO contract_templates (id, slug, title, summary, owner_agent_did, source_org_id,
                contract_type, visibility, pricing_model, royalty_bps, forked_from_template_id, updated_at)
            VALUES (:id,:sl,:ti,:su,:o,:org,:ct,'private','free',0,:ff, now())
        """), {"id": nid, "sl": body.slug, "ti": (body.title or f"Fork of {t['title']}")[:200],
               "su": t.get("summary"), "o": agent.did, "org": str(org) if org else None,
               "ct": t["contract_type"], "ff": tid})
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="slug already exists for this owner")
    s = dict(src) if src else {}
    await db.execute(text("""
        INSERT INTO contract_template_versions (id, template_id, version, terms, terms_schema,
            milestones, suggested_amount, suggested_currency, suggested_deadline_seconds,
            changelog, content_hash)
        VALUES (:id,:t,1,CAST(:tm AS JSONB),CAST(:ts AS JSONB),CAST(:ms AS JSONB),:sa,:sc,:sd,:cl,:h)
    """), {"id": vid, "t": nid,
           "tm": json.dumps(s.get("terms")) if s.get("terms") is not None else None,
           "ts": json.dumps(s.get("terms_schema")) if s.get("terms_schema") is not None else None,
           "ms": json.dumps(s.get("milestones")) if s.get("milestones") is not None else None,
           "sa": s.get("suggested_amount"), "sc": s.get("suggested_currency") or _FRAME_CCY,
           "sd": s.get("suggested_deadline_seconds"),
           "cl": f"forked from {tid} v{s.get('version', '?')}",
           "h": content_hash(s.get("terms"), s.get("terms_schema"), s.get("milestones"))})
    await db.commit()
    return {"template_id": nid, "version_id": vid, "forked_from": tid, "published": False}


# ── money: purchase (up-front) + instantiate ────────────────────────────────────────────────

@router.post("/api/v1/contracts/templates/{tid}/purchase",
             summary="Buy a purchase-priced template (one-time; then instantiate free)")
async def purchase_template(tid: str, agent: models.Agent = Depends(get_current_agent),
                            db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    actor = {"kind": "agent", "agent_did": agent.did}
    if not await _actor_may_see(db, t, actor, listing=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not visible to you")
    if t["pricing_model"] != "purchase":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Template is not purchase-priced")
    if t["owner_agent_did"] == agent.did:
        return {"ok": True, "already": "owner"}
    existing = (await db.execute(text(
        "SELECT id FROM contract_template_purchases WHERE template_id=:t AND buyer_did=:b"),
        {"t": tid, "b": agent.did})).first()
    if existing:
        return {"ok": True, "already": "purchased"}
    price = Decimal(str(t["price"] or 0)).quantize(_Q)
    if price <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Template has no price set")
    # buyer → treasury → author: two exactly-once legs on the SHARED rail (the CICD paid-template
    # pattern, re-keyed). A crash between legs re-drives on retry — both keys dedup server-side.
    try:
        await escrow.escrow_deposit(agent.did, price, f"ctpl:{tid}:{agent.did}:in",
                                    reason="contract_escrow")
    except escrow.EscrowError as e:
        from agentvault_registry.services.ledger_unavailable import refusal_from_error  # §LEDGERGATE (V0598)
        raise refusal_from_error(e) or HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                                                     detail=f"Purchase failed (insufficient balance?): {e.message}")
    await escrow.escrow_payout(db, t["owner_agent_did"], price, f"ctpl:{tid}:{agent.did}:out",
                               reason="contract_settle")
    await db.execute(text("""
        INSERT INTO contract_template_purchases (template_id, buyer_did, price, currency)
        VALUES (:t,:b,:p,:c) ON CONFLICT (template_id, buyer_did) DO NOTHING
    """), {"t": tid, "b": agent.did, "p": price, "c": t.get("price_currency") or _FRAME_CCY})
    await db.commit()
    cs.emit("ContractTemplatePurchased", tid, {"buyer": agent.did, "price": str(price)})
    logger.info("[CTPL] %s purchased by %s for %s", tid, agent.did, price)
    return {"ok": True, "template_id": tid, "price": str(price),
            "currency": t.get("price_currency") or _FRAME_CCY}


@router.post("/api/v1/contracts/templates/{tid}/instantiate", status_code=status.HTTP_201_CREATED,
             summary="Create a contract OFFER from a published version (terms COPIED)")
async def instantiate_template(tid: str, body: InstantiateIn, request: Request,
                               agent: models.Agent = Security(require_agent_permission("contracts.engage")),
                               db: AsyncSession = Depends(get_db)):
    _require_enabled()
    t = await _load_tpl(db, tid)
    actor = {"kind": "agent", "agent_did": agent.did}
    if not await _actor_may_see(db, t, actor, listing=False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not visible to you")
    if body.version is not None:
        v = (await db.execute(text(
            "SELECT * FROM contract_template_versions WHERE template_id=:t AND version=:v "
            "AND published_at IS NOT NULL"), {"t": tid, "v": body.version})).mappings().first()
    else:
        v = None
        if t.get("current_version_id"):
            v = (await db.execute(text(
                "SELECT * FROM contract_template_versions WHERE id=:v AND published_at IS NOT NULL"),
                {"v": t["current_version_id"]})).mappings().first()
    if not v:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No published version to instantiate")
    v = dict(v)
    price_paid = None
    if t["pricing_model"] == "purchase" and t["owner_agent_did"] != agent.did:
        bought = (await db.execute(text(
            "SELECT price FROM contract_template_purchases WHERE template_id=:t AND buyer_did=:b"),
            {"t": tid, "b": agent.did})).first()
        if not bought:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                                detail="This template is purchase-priced — buy it first "
                                       "(POST …/purchase), then instantiate freely")
        price_paid = Decimal(str(bought[0]))
    total = Decimal(str(body.total_amount if body.total_amount is not None
                        else (v.get("suggested_amount") or 0))).quantize(_Q)
    terms = dict(v.get("terms") or {})
    if body.terms_overrides:
        terms.update(body.terms_overrides)
    terms["template_provenance"] = {"template_id": tid, "version": v["version"],
                                    "content_hash": v["content_hash"]}
    validate_terms_against(v.get("terms_schema"), terms)
    ms = None
    if v.get("milestones"):
        ms, acc = [], Decimal("0")
        pcts = v["milestones"]
        for i, m in enumerate(pcts):
            if i < len(pcts) - 1:
                amt = (total * Decimal(str(m.get("amount_pct", 0))) / Decimal(100)).quantize(_Q)
                acc += amt
            else:
                amt = total - acc              # exact tail (I-C6)
            ms.append({"title": m.get("title") or f"Milestone {i+1}", "amount": str(amt),
                       "terms": m.get("terms"),
                       "due_seconds": (int(m["due_days"]) * 86400) if m.get("due_days") else None})
    royalty_bps = t["royalty_bps"] if t["pricing_model"] == "royalty" else None
    from agentvault_registry.routers.contracts_v2 import mint_contract
    c = await mint_contract(
        db, client_did=agent.did, title=str(v.get("title_tpl") or t["title"])[:200],
        total_amount=total, contract_type=t["contract_type"], terms=terms,
        milestones=ms, provider_did=body.provider_did,
        deadline_seconds=body.deadline_seconds or v.get("suggested_deadline_seconds"),
        origin_surface="template", origin_ref=v["id"],
        template_version_id=v["id"], template_royalty_bps=royalty_bps,
        template_price_paid=price_paid,
        fee_bps=int(os.getenv("TEMPLATE_CONTRACT_FEE_BPS", "0")),
        actor_did=agent.did, request=request)
    out = dict(c)
    for k in ("total_amount", "fee_charged", "template_price_paid"):
        if out.get(k) is not None:
            out[k] = str(out[k])
    return out
