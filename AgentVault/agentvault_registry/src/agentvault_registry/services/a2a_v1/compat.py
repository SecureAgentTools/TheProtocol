"""A2A v0.3 → v1.0 card_data canonicalization (the backend Rosetta Stone).

The agent_cards table stores arbitrary JSONB card_data. During the Q-C
6-month transition (Commander Q5 signoff), both v0.3 and v1.0 shapes
coexist; this module canonicalizes ANY shape to v1.0 idempotently.

Reads: accept v0.3 OR v1.0 (or partial/mixed).
Writes: emit v1.0 fields AND keep v0.3 fields for backwards compat reads
        from older clients (federated peers).

After the 6-month window: a separate migration drops v0.3 fields from
agent_cards.card_data via UPDATE pass.

Per A2A v1.0 spec §4.4 (AgentCard structure) + §4.5 (Security objects).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── v0.3 authSchemes → v1.0 securitySchemes + security ───────────────


def derive_security_from_auth_schemes(
    auth_schemes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Map TheProtocol-custom v0.3 authSchemes[] to A2A v1.0 securitySchemes{}+security[].

    Each v0.3 entry like {"scheme": "oauth2", "tokenUrl": "..."} becomes a
    named entry in v1.0 securitySchemes{} keyed by scheme-name; AND appears
    in the security[] array (which schemes apply to this agent).

    Mapping table (Commander Q2 spec §4.5 alignment, 2026-05-12):

      v0.3 {"scheme": "oauth2", "tokenUrl": "..."}
           -> securitySchemes["oauth2_agent_jwt"] = {
                "type": "oauth2",
                "flows": {"clientCredentials": {"tokenUrl": "...", "scopes": {}}}
             }
           + security: [{"oauth2_agent_jwt": []}]

      v0.3 {"scheme": "apiKey"}
           -> securitySchemes["api_key"] = {"type": "apiKey", "in": "header", "name": "X-Api-Key"}
           + security: [{"api_key": []}]

      v0.3 {"scheme": "bearer"}
           -> securitySchemes["bearer"] = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
           + security: [{"bearer": []}]

      v0.3 {"scheme": "none"}
           -> security: []   (empty array means no auth required)

    Returns {"securitySchemes": {...}, "security": [...]}.
    """
    schemes: Dict[str, Any] = {}
    security: List[Dict[str, List[str]]] = []

    for entry in auth_schemes or []:
        if not isinstance(entry, dict):
            continue
        scheme_kind = (entry.get("scheme") or "").strip().lower()

        if scheme_kind == "none":
            continue

        if scheme_kind == "oauth2":
            name = "oauth2_agent_jwt"
            token_url = entry.get("tokenUrl") or entry.get("token_url") or ""
            schemes[name] = {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {
                        "tokenUrl": token_url,
                        "scopes": {},
                    },
                },
                "description": "Agent JWT via OAuth2 client-credentials grant",
            }
            security.append({name: []})

        elif scheme_kind == "apikey":
            name = "api_key"
            header_name = entry.get("name") or "X-Api-Key"
            schemes[name] = {
                "type": "apiKey",
                "in": "header",
                "name": header_name,
                "description": "API key in HTTP header",
            }
            security.append({name: []})

        elif scheme_kind == "bearer":
            name = "bearer"
            schemes[name] = {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Authorization: Bearer <jwt>",
            }
            security.append({name: []})

        else:
            logger.debug(
                "[a2a_v1.compat] unknown v0.3 authScheme '%s'; preserving verbatim", scheme_kind
            )
            name = scheme_kind or "custom"
            schemes[name] = {
                "type": "apiKey",
                "in": "header",
                "name": entry.get("name") or "X-Auth",
                "description": f"Legacy v0.3 scheme: {scheme_kind}",
            }
            security.append({name: []})

    return {"securitySchemes": schemes, "security": security}


# ─── v0.3 top-level url/preferredTransport → v1.0 supportedInterfaces[] ─


def derive_supported_interfaces(
    card_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build A2A v1.0 supportedInterfaces[] from v0.3 top-level fields."""
    interfaces: List[Dict[str, Any]] = []

    primary_url = card_data.get("url", "")
    if primary_url:
        primary_iface = {
            "url": primary_url,
            "protocolBinding": (card_data.get("preferredTransport") or "JSONRPC"),
            "protocolVersion": card_data.get("protocolVersion") or "1.0",
        }
        interfaces.append(primary_iface)

    extras = card_data.get("additionalInterfaces") or []
    if isinstance(extras, list):
        for extra in extras:
            if isinstance(extra, dict) and extra.get("url"):
                iface = {
                    "url": extra["url"],
                    "protocolBinding": extra.get("transport") or extra.get("protocolBinding") or "JSONRPC",
                    "protocolVersion": extra.get("protocolVersion") or "1.0",
                }
                interfaces.append(iface)

    return interfaces


# ─── Top-level canonicalization ───────────────────────────────────────


def is_v1_card(card_data: Dict[str, Any]) -> bool:
    """Heuristic: does this card_data already have v1.0 fields?

    Returns True if BOTH supportedInterfaces[] AND securitySchemes{} are
    populated.
    """
    has_interfaces = bool(card_data.get("supportedInterfaces"))
    has_schemes = bool(card_data.get("securitySchemes"))
    return has_interfaces and has_schemes


def canonicalize_card_data(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """Canonicalize ANY card_data shape (v0.3 / v1.0 / mixed) to v1.0.

    IDEMPOTENT. Safe to call multiple times.

    Strategy:
      1. If already v1.0 (supportedInterfaces + securitySchemes present), no-op
         except backfill missing capabilities sub-fields.
      2. If v0.3, derive v1.0 fields and ADD them (don't strip v0.3 fields —
         keep both shapes during 6-month transition per Q5).

    Returns a new dict (does NOT mutate input).
    """
    if not isinstance(card_data, dict):
        return card_data

    result = dict(card_data)

    # §AGENTDISC #189 (2026-08-16) — every derivation guard below treats a
    # null-VALUED key as absent. Stored cards from pydantic writers carry
    # `"supportedInterfaces": null` / `"securitySchemes": null`, which the old
    # `"key" not in result` guards read as PRESENT, silently skipping derivation
    # (caught live by the A2A schema gate on frame-c).

    # 1. Derive securitySchemes + security from authSchemes
    if result.get("securitySchemes") is None and isinstance(result.get("authSchemes"), list):
        derived = derive_security_from_auth_schemes(result.get("authSchemes") or [])
        result["securitySchemes"] = derived["securitySchemes"]
        result["security"] = derived["security"]

    # 2. Derive supportedInterfaces from url + preferredTransport
    if not result.get("supportedInterfaces") and result.get("url"):
        result["supportedInterfaces"] = derive_supported_interfaces(result)

    # 3. capabilities.extendedAgentCard from supportsAuthenticatedExtendedCard
    capabilities = result.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    if capabilities.get("extendedAgentCard") is None and result.get("supportsAuthenticatedExtendedCard") is not None:
        capabilities["extendedAgentCard"] = bool(result.get("supportsAuthenticatedExtendedCard"))
    result["capabilities"] = capabilities

    # 4. v0.3 schemaVersion → protocolVersion (defensive; library already handles)
    if result.get("schemaVersion") is not None and result.get("protocolVersion") is None:
        result["protocolVersion"] = result["schemaVersion"]

    # 5. If we derived v1.0 fields from a v0.3 card, mark it as v1.0-capable
    has_derived_v1 = bool(result.get("supportedInterfaces")) and result.get("securitySchemes") is not None
    if has_derived_v1 and (result.get("protocolVersion") or "").startswith("0."):
        original = result["protocolVersion"]
        result["protocolVersion"] = "1.0"
        if "schemaVersion" not in result:
            result["schemaVersion"] = original

    # 6. §AGENTDISC #189 — guarantee the remaining v1.0 REQUIRED fields
    #    (a2a.proto v1.0.1 field_behavior=REQUIRED). Idempotent + additive.
    derive_v1_required_fields(result)

    # 7. §EXTPUB (2026-08-28) — a card that DECLARES payment in the legacy
    #    pricing block publishes the A2A payment extension too. Our own SDK
    #    says a paid agent MUST publish it, yet 0 of the 12 real paid agents'
    #    cards carried it (§HIRECOHERE measurement) — every writer relied on
    #    hand-authored extensions. Derivation rules match the ONE price rule
    #    (§DISCREFINE: agent_cards._PAY_EXT_SQL + cardPricing.ts, top-level
    #    extensions[], params.base_rate): fill-when-missing, NEVER overwrite
    #    an extension the author wrote (either legal placement counts), and a
    #    paid block whose base_rate cannot price the extension logs the lint
    #    WARNING instead of inventing a number. Runs everywhere HOME cards
    #    are written or served (create / update / native pullsync / export);
    #    federated MIRRORS never pass through here — a mirror stays verbatim.
    derive_payment_extension(result)

    return result


_EXT_A2A_PAYMENT_URI = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"


def derive_payment_extension(result: Dict[str, Any]) -> Dict[str, Any]:
    """§EXTPUB — see step 7 above. MUTATES `result` in place, returns it. IDEMPOTENT."""
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        pricing = result.get("pricing")
        if not isinstance(pricing, dict):
            return result
        paid_flag = pricing.get("payment_required") is True
        rate_raw = pricing.get("base_rate")
        try:
            rate = float(rate_raw)
            has_rate = rate > 0
        except (TypeError, ValueError):
            has_rate = False
        if not (paid_flag or has_rate):
            return result

        def _has_ext(seq: Any) -> bool:
            return any(isinstance(e, dict) and e.get("uri") == _EXT_A2A_PAYMENT_URI
                       for e in (seq or []) if seq is not None) if isinstance(seq, list) else False

        caps = result.get("capabilities")
        if _has_ext(result.get("extensions")) or _has_ext(
                caps.get("extensions") if isinstance(caps, dict) else None):
            return result   # the author already published one — theirs wins

        if not has_rate:
            # paid without a priceable rate: the LINT half — warn, never block,
            # never invent a number (a fabricated price is worse than none).
            _log.warning("[EXTPUB] card %r declares payment_required without a "
                         "numeric base_rate — a2a-payment extension NOT derived",
                         result.get("name") or result.get("humanReadableId"))
            return result

        # §DOCSFIX D6-457: a block that names no currency is priced in this registry's own unit (the home frame's:
        # only home cards pass through here), as /a2a-payment/quote and the console read it; it was "AVT", a unit no
        # production frame uses
        from ...core.frame_currency import frame_currency
        params = {
            "base_rate": str(rate_raw),
            "currency": str(pricing.get("currency") or frame_currency()).upper(),
            "pricing_model": str(pricing.get("pricing_model") or pricing.get("model")
                                 or "per_request"),
        }
        ext = {"uri": _EXT_A2A_PAYMENT_URI,
               "description": "A2A payment token; single-use; settlement-after-success",
               "params": params}
        if paid_flag:
            ext["required"] = True
        exts = result.get("extensions")
        result["extensions"] = (list(exts) if isinstance(exts, list) else []) + [ext]
    except Exception:   # derivation must never break a card write/serve
        _log.warning("[EXTPUB] payment-extension derivation failed", exc_info=True)
    return result


def derive_v1_required_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    """§AGENTDISC #189 (2026-08-16) — fill the v1.0 REQUIRED fields the v0.3→v1.0
    derivation above does not cover, per the vendored a2a_v1.0.1.proto
    (schema/agent_card_v1.schema.json is the encoded contract; the CI gate
    .forgejo/checks/a2a_schema_gate.py enforces it).

    MUTATES `result` in place (callers already own a copy) and returns it.
    IDEMPOTENT: every derivation is a fill-when-missing, never an overwrite.
    Honest limits: `supportedInterfaces` is NOT invented here — an agent with no
    declared endpoint cannot truthfully claim one (the gate reports those as
    no-endpoint cards instead of fabricating a URL)."""
    # description — REQUIRED string (empty string is valid proto3)
    if not isinstance(result.get("description"), str):
        result["description"] = str(result.get("description") or "")

    # version — REQUIRED string (v0.3 cards carry it as agentVersion)
    ver = result.get("version")
    if not isinstance(ver, str) or not ver:
        alt = result.get("agentVersion")
        result["version"] = (alt if isinstance(alt, str) and alt else (str(ver) if ver else "1.0.0"))

    # capabilities — REQUIRED object (step 3 above already coerced non-dicts)
    if not isinstance(result.get("capabilities"), dict):
        result["capabilities"] = {}

    # defaultInputModes / defaultOutputModes — REQUIRED non-empty string arrays.
    # Our agents speak JSON request/response over their declared interfaces.
    for key in ("defaultInputModes", "defaultOutputModes"):
        v = result.get(key)
        if not (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
            result[key] = ["application/json"]

    # skills — REQUIRED non-empty. Existing entries are normalized to carry the
    # proto-required members; a card with none gets ONE descriptive skill built
    # from its own name/description/tags (a2a: "largely a descriptive concept").
    tags_src = result.get("tags")
    card_tags = [str(t) for t in tags_src if isinstance(t, (str, int))] if isinstance(tags_src, list) else []
    skills = result.get("skills")
    normalized: List[Dict[str, Any]] = []
    if isinstance(skills, list):
        for s in skills:
            if not isinstance(s, dict):
                continue
            s = dict(s)
            name = s.get("name") or s.get("id") or "skill"
            s.setdefault("id", str(name).strip().lower().replace(" ", "-")[:64] or "skill")
            s.setdefault("name", str(name))
            if not isinstance(s.get("description"), str):
                s["description"] = str(s.get("description") or "")
            t = s.get("tags")
            s["tags"] = ([str(x) for x in t] if isinstance(t, list) and t else (card_tags or ["general"]))
            normalized.append(s)
    if not normalized:
        normalized = [{
            "id": "general",
            "name": result.get("name") or "General service",
            "description": result.get("description") or "General agent service",
            "tags": card_tags[:8] or ["general"],
        }]
    result["skills"] = normalized

    # provider — optional, but url+organization are REQUIRED when present.
    # v0.3 providers carry {name, url}; organization := name is the faithful map.
    prov = result.get("provider")
    if isinstance(prov, dict) and prov:
        prov = dict(prov)
        if not isinstance(prov.get("organization"), str) or not prov.get("organization"):
            prov["organization"] = str(prov.get("name") or prov.get("organization") or "")
        # D6-814 (2026-10-23): an EMPTY url counts as none, and a v1.0 card's endpoint (supportedInterfaces[0].url) is
        # the fallback after the v0.3 top-level url. Before, a provider without a url on a v1.0 card (no top-level url)
        # was written with url "", which every peer's fail-closed ingest refuses (HttpUrl): ASIA refused EU's SYBIL and
        # ten showcase cards from such saves. "" stays only when the card names no URL anywhere.
        if not (isinstance(prov.get("url"), str) and prov["url"].strip()):
            _ifaces = result.get("supportedInterfaces")
            _iface_url = next((i.get("url") for i in _ifaces if isinstance(i, dict) and isinstance(i.get("url"), str)
                               and i["url"].strip()), "") if isinstance(_ifaces, list) else ""
            _top = result.get("url") if isinstance(result.get("url"), str) and result["url"].strip() else ""
            _own = prov.get("url") if prov.get("url") and not isinstance(prov.get("url"), str) else ""
            prov["url"] = str(_own or _top or _iface_url or "")
        result["provider"] = prov

    return result


def render_for_v03_peer(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """Lossy outbound rendering for v0.3-only federation peers (Q10 signoff).

    Strips v1.0-only fields (supportedInterfaces, securitySchemes, security,
    extensions[]) but keeps v0.3 fields (authSchemes, url, preferredTransport,
    additionalInterfaces) so a strict-v0.3 peer can read the card.

    Returns a new dict (does NOT mutate input).
    """
    if not isinstance(card_data, dict):
        return card_data

    result = dict(card_data)
    for v1_only in ("supportedInterfaces", "securitySchemes", "security", "extensions"):
        result.pop(v1_only, None)
    if isinstance(result.get("capabilities"), dict):
        caps = dict(result["capabilities"])
        caps.pop("extendedAgentCard", None)
        result["capabilities"] = caps
    if "schemaVersion" not in result and "protocolVersion" in result:
        result["schemaVersion"] = result["protocolVersion"]
    result["protocolVersion"] = "0.3.0"
    return result


__all__ = [
    "derive_security_from_auth_schemes",
    "derive_supported_interfaces",
    "derive_v1_required_fields",
    "is_v1_card",
    "canonicalize_card_data",
    "render_for_v03_peer",
]
