"""§ORGPOLICY — per-ORGANIZATION configuration layered on top of the registry defaults.

An organization owns its agents via the agent's own `agents.organization_id` column (NOT via the
creating developer — `developers` has no org column; a dev↔org link is the `organization_members`
M:N table, a different axis). Its
`organizations.settings` JSON can carry policy an org admin sets to make its OWN agents behave more
STRICTLY than the registry default — never more loosely (the registry stays sovereign; a registry that
enforces can't be undercut by an org). Wired today:

  * settings.liability = {"mode": "off"|"shadow"|"enforce", "presence_threshold_avt": <number>}
      TIGHTEN-ONLY. effective mode = strictest(registry, org); effective step-up threshold = the
      strictest (lowest positive) of the two (0/unset = disabled). An org may turn liability ON for its
      own agents when the registry is off, or LOWER the presence threshold — never turn it off or raise
      it past the registry.
  * settings.contract_offer_ttl_days = <int 1..366>   (an org default for its contracts' offer expiry)

`ORG_SETTING_CATALOG` is the single source of truth for what is org-configurable — it drives both
PUT-validation (routers/organizations.py) and the FE settings form. All of this is deny-only /
bookkeeping ⇒ Δ-irrelevant.
"""
import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MODE_RANK = {"off": 0, "shadow": 1, "enforce": 2}
_RANK_MODE = {0: "off", 1: "shadow", 2: "enforce"}

# The knobs an org admin may set — source of truth for validation + the FE form.
ORG_SETTING_CATALOG = [
    {"key": "liability.mode", "type": "enum", "values": ["off", "shadow", "enforce"],
     "label": "Liability mode", "tighten_only": True,
     "help": "Require a signed human mandate behind your agents' hands. Can only be made stricter than "
             "the registry — you can turn it on when the registry is off, never off when it enforces."},
    {"key": "liability.presence_threshold_avt", "type": "number", "min": 0,
     "label": "Presence step-up threshold (in the frame's currency)", "tighten_only": True,  # D6-835: it said AVT on every frame
     "help": "A hand's action at or above this value needs a live presence proof. 0 = off. Lower = stricter."},
    # §MONEY-R43 (2026-09-04): the org's own "treasury running low" floor. Read by
    # background_tasks/treasury_low_watch.py; owners + admins are notified once on the
    # crossing down and once on recovery. 0 / absent = off (the default: an org opts in).
    {"key": "treasury_low_notify_threshold", "type": "number", "min": 0,
     "label": "Treasury low-balance notice floor",
     "help": "Notify the org's owners and admins once when the org treasury falls below this amount "
             "(in the frame's currency), and once when it recovers. 0 = off."},
    # §COCKPIT P4 (§POSTURE, D3) — the consent dials, as ONE knob. Per-dial org
    # overrides are deliberately v2: three named, measured bundles are auditable and
    # a matrix of eleven independent dials is not, and the strategy's own table is
    # the contract. Empty = inherit the registry's posture (`COCKPIT_POSTURE`).
    # ⚠ This entry existing is what makes the knob REAL: creation-time and PUT
    # settings both validate against this catalog, so a posture written under a key
    # the catalog does not know is refused loudly instead of being echoed back and
    # read by nobody — the §ORGPOCKET silent-echo class, in the one place where a
    # silently-unapplied security posture would be worst.
    {"key": "cockpit_posture", "type": "enum", "values": ["", "swift", "balanced", "hardened"],
     "label": "Cockpit consent posture", "tighten_only": True,
     "help": "How hard the Cockpit asks before your agents' hands act: swift (fast, TOTP still "
             "accepted), balanced (enrolled device required once enrolled, longer read floor), "
             "hardened (WebAuthn only, every action asks). Can only be made stricter than the "
             "registry's; empty inherits it."},
    # ── §COCKPIT D4/D6 (Commander 2026-08-31) — THE TIME DIALS ────────────────
    # 🔴 These four are the ONE part of the consent posture an org may LOOSEN as well
    # as tighten. His reason, verbatim in the refinement doc: "a human reads slow and
    # he drinks coffee and looks out of the window." How long somebody is given to
    # think is ergonomics, not a security claim, and an org that knows its people is
    # better placed to set it than the registry is.
    # What keeps it safe is the CAP, not the direction — `consent_posture.HARD_BOUNDS`
    # is a law these cannot reach past, and the ranges below are the same numbers.
    {"key": "cockpit_challenge_ttl_seconds", "type": "number", "min": 30, "max": 3600,
     "label": "How long a confirmation stays answerable (seconds)", "tighten_only": False,
     "help": "A confirmation that lapses is a refusal, so this is how long your people have to "
             "answer before an agent's action is turned down. Longer OR shorter than the "
             "registry's default, up to one hour. Nobody's clock starts until a human is "
             "actually at a screen, so a long value does not mean a long exposure."},
    {"key": "cockpit_read_floor_ms", "type": "number", "min": 0, "max": 30000,
     "label": "Minimum time with the facts on screen (ms)", "tighten_only": False,
     "help": "The confirm button stays held for this long after the decision appears, so a "
             "reflex tap cannot approve something nobody read. Raise it if your people move "
             "too fast; it can never make a confirmation impossible."},
    {"key": "cockpit_ceiling_decay_hours", "type": "number", "min": 1, "max": 720,
     "label": "How long a standing consent lasts (hours)", "tighten_only": False,
     "help": "When one of your humans says \u201cstop asking me about this\u201d, this is how long "
             "that lasts before it has to be granted again. A standing consent that never "
             "decays is not a ceiling, it is a blank cheque."},
    {"key": "cockpit_preview_credit_seconds", "type": "number", "min": 0, "max": 3600,
     "label": "How long a pre-read still counts (seconds)", "tighten_only": False,
     "help": "If your human already read the exact same facts in a pre-flight preview this "
             "recently, they may confirm immediately instead of waiting out the read floor "
             "again. 0 disables the credit."},
    # ── §COCKPIT D7 — the org CAPS standing consent; the human grants inside the cap ──
    {"key": "cockpit_ceilings_enabled", "type": "bool",
     "label": "Allow standing consent", "tighten_only": True,
     "help": "Off means every action asks, every time, for every agent this org owns \u2014 no "
             "human of yours can switch that off for themselves."},
    {"key": "cockpit_ceiling_max_amount", "type": "number", "min": 0,
     "label": "Largest standing consent a human may grant", "tighten_only": True,
     "help": "The most any of your humans may pre-authorise per action when they grant a "
             "standing consent. They still have to sign for it; this is the ceiling on the "
             "ceiling. 0/unset = the registry's own limit applies."},
    {"key": "contract_offer_ttl_days", "type": "number", "min": 1, "max": 366,
     "label": "Contract offer expiry (days)", "tighten_only": False,
     "help": "Default expiry for contract offers your agents author (when not set on the request)."},
    # Track A5 (RBAC plan) — enforcement knobs, each with a live consumer gate.
    {"key": "org_spend_ceiling_avt", "type": "number", "min": 0,
     "label": "Per-transaction spend ceiling", "tighten_only": True,
     "help": "Hard per-transaction cap for every agent this org owns, enforced at the spend gate "
             "on top of each agent's own policy (the stricter wins). 0/unset = no org ceiling. "
             "Frame-local: binds spends originated on THIS registry."},
    {"key": "default_agent_authority_slice", "type": "enum",
     "values": ["", "guest", "member", "admin", "owner"],
     "label": "Default agent authority", "tighten_only": False,
     "help": "Authority slice auto-granted (as an org delegation) to agents when they are assigned "
             "to this org — including auto-assignment at onboarding. Empty = grant nothing; the "
             "grant still only bites when the agent acts for the org (org-acting token)."},
    # §OCOPTIN (2026-08-28, Commander's design): PUBLIC transparency is an ORG's
    # own choice — settable at creation and here, default OFF forever. When on,
    # the org room's WORK RECORDS (system rows + org.work.receipt cards + topic)
    # serve on a public read-only feed; free-text member messages and DMs are
    # excluded BY CONSTRUCTION (the feed query never selects them). Opting out
    # stops the feed immediately — the endpoint re-reads this setting per request.
    {"key": "public_transparency_opt_in", "type": "bool",
     "label": "Public work-record transparency", "tighten_only": False,
     "help": "Publish this organization's work records (treasury/distribution/guild receipt cards, "
             "system rows and the room topic) on a public read-only feed. Members' written "
             "messages are never included. Off by default; turning it off stops the feed at once."},
    # §ORGSPEND (2026-08-29, Commander's design) — HOW MUCH may a member move for the firm.
    # Per-TRANSACTION caps on every dev-driven treasury draw (fund, sweep, commissioning a
    # work order), enforced at the ONE choke point (org_treasury._procurement_cap_or_raise).
    # Absent/empty/0 = unlimited (today's behavior — additive). Money INTO the treasury
    # (remit) is never capped. A per-window budget would need state — deliberately not this.
    {"key": "procurement_limit_default", "type": "number", "min": 0,
     "label": "Procurement limit (default)", "tighten_only": False,
     "help": "Per-transaction cap, in this registry's currency, on org-treasury draws by ANY "
             "member (funding agents, commissioning work, sweeping). 0/unset = unlimited. "
             "Per-member overrides below beat this default."},
    {"key": "procurement_limits", "type": "object",
     "label": "Procurement limits (per member)", "tighten_only": False,
     "help": "Per-member overrides of the default: a map of developer id → per-transaction "
             "cap (decimal, this registry's currency). An override of 0 means UNLIMITED for "
             "that member (it overrides, it does not tighten-to-zero)."},
    # §FIRMHIRE (H3.2, 2026-08-29) — the firm's front door for engagement. When set,
    # Discovery's firms lane offers "Engage" against THIS agent (the ordinary
    # engage-preview/engage flow); unset = no engage door, said honestly. The PUT
    # route validates it against the DB (must be an ACTIVE agent ASSIGNED to the
    # org) — shape only here; consumers re-validate at read time (§ORGLIFE law).
    {"key": "intake_agent_did", "type": "string", "max_length": 120,
     "label": "Intake agent (engage door)", "tighten_only": False,
     "help": "The agent that receives engagements addressed to this firm. Must be an active "
             "agent assigned to this organization. Empty = the firm has no engage door."},
]


def transparency_public(org_settings) -> bool:
    """§OCOPTIN — True only when the org has explicitly opted in. Fail-closed."""
    if not isinstance(org_settings, dict):
        return False
    return org_settings.get("public_transparency_opt_in") is True


def assistant_present(org_settings) -> bool:
    """§ROOMBRAIN — True only while an org admin has ADDED @assistant to the
    room (the room op is the ONE door that writes this; the settings PUT
    refuses the key). Fail-closed, read LIVE per request like transparency —
    removing the assistant silences it on the next message, not the next sync."""
    if not isinstance(org_settings, dict):
        return False
    return org_settings.get("room_assistant_present") is True


class OrgSettingsUnavailable(HTTPException):
    """The settings of the organization that owns an agent could not be read.

    Those settings only ever TIGHTEN what the registry allows (liability, the spend ceiling, the consent posture,
    standing consent), so acting on the registry defaults instead would loosen them for that organization's agents.
    A 503 with nothing done, the shape of the spend gate's authz_unavailable: a caller that does not catch it refuses
    the request, and a caller that does refuses in its own words."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=("org_settings_unavailable: the settings of the agent's organization could not be read, "
                    "so nothing was done; retry shortly"),
            headers={"Retry-After": "5"},
        )


async def get_org_settings(db: AsyncSession, agent_did: str) -> Dict[str, Any]:
    """The org settings JSON for the organization that owns `agent_did` (its own assignment), or {} when the agent
    has no organization or the organization has no settings.

    FAIL-CLOSED: a read error raises OrgSettingsUnavailable (503). §SECFIX D6-491 (2026-10-16): any error yielded {}
    here, so a database error silently lifted every organization's tighten-only settings (the registry default
    applied), and the refusal its callers had for a failed read (the spend gate's 503) could never fire."""
    try:
        # An agent's org = its DIRECT assignment (agents.organization_id, set by assign_agent_to_org).
        # Developers belong to orgs via the organization_members M:N table (no column, and possibly many
        # orgs), so the agent's OWN assignment is the unambiguous "this agent's org". The query rides a
        # SAVEPOINT so a failed read can NEVER poison the caller's (gate's) transaction: a gate in shadow
        # mode observes the failure and goes on.
        async with db.begin_nested():
            row = (await db.execute(text(
                "SELECT o.settings FROM agents a "
                "JOIN organizations o ON o.id = a.organization_id "
                "WHERE a.did = CAST(:d AS VARCHAR) AND a.organization_id IS NOT NULL LIMIT 1"), {"d": agent_did})).first()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ORGPOLICY] org settings read failed for %s: %r", agent_did, exc)
        raise OrgSettingsUnavailable() from exc
    if not row or not isinstance(row[0], dict):
        return {}
    return row[0]


def effective_liability(registry_mode: str, registry_threshold: float,
                        org_settings: Optional[Dict[str, Any]]) -> Tuple[str, float]:
    """TIGHTEN-ONLY composition of the registry liability posture with an org's (if any).
    Returns (effective_mode, effective_presence_threshold_avt). An org can only ESCALATE the mode
    (off→shadow→enforce) and only LOWER a positive step-up threshold — never loosen either."""
    reg_mode = (registry_mode or "off").lower()
    mode_rank = _MODE_RANK.get(reg_mode, 0)
    thr_candidates = [registry_threshold] if (registry_threshold and registry_threshold > 0) else []
    liab = (org_settings or {}).get("liability") if isinstance(org_settings, dict) else None
    if isinstance(liab, dict):
        om = str(liab.get("mode", "")).lower()
        if om in _MODE_RANK:
            mode_rank = max(mode_rank, _MODE_RANK[om])          # org may only escalate the mode
        ot = liab.get("presence_threshold_avt")
        try:
            otf = float(ot)
            if otf > 0:
                thr_candidates.append(otf)                      # a positive org threshold can only tighten
        except (TypeError, ValueError):
            pass
    eff_thr = min(thr_candidates) if thr_candidates else 0.0    # lowest positive = strictest; else disabled
    return _RANK_MODE[mode_rank], eff_thr


# Keys that belong to a DIFFERENT surface and have burned someone: the value is
# accepted here, echoed back, and read by nobody. `chat_*` lives in the
# organizations COLUMNS and is written only by PUT /chat/org-rooms/{org_id}/settings.
_ELSEWHERE = {
    "chat_enabled": "PUT /api/v1/chat/org-rooms/{org_id}/settings",
    # §ROOMBRAIN — presence is toggled by the ROOM OP so every change leaves a
    # visible system row; a silent settings write would skip the trail.
    "room_assistant_present": "POST /api/v1/chat/conversations/{id}/room (action assistant_on/assistant_off)",
    "chat_open_policy": "PUT /api/v1/chat/org-rooms/{org_id}/settings",
    "treasury_agent_did": "POST /api/v1/organizations/{org_id}/treasury",
    "name": "PUT /api/v1/organizations/{org_id}",
    "slug": "PUT /api/v1/organizations/{org_id}",
    "description": "PUT /api/v1/organizations/{org_id}",
    "website": "PUT /api/v1/organizations/{org_id}",
}


def allowed_setting_paths() -> Dict[str, set]:
    """{top-level key: set of allowed sub-keys (empty = scalar)} derived from
    ORG_SETTING_CATALOG, so the allowlist can never drift from the form or the docs."""
    out: Dict[str, set] = {}
    for entry in ORG_SETTING_CATALOG:
        head, _, tail = str(entry["key"]).partition(".")
        out.setdefault(head, set())
        if tail:
            out[head].add(tail)
    return out


def catalog_enums() -> Dict[str, set]:
    """{catalog key: allowed values} for every `type: "enum"` entry.

    🔴 THE CATALOG DECLARED ENUMS AND NOTHING READ THE DECLARATION. Every enum was
    validated, or not, by a hand-written `if` further down this function: `liability.mode`
    had one and `default_agent_authority_slice` had one, so both looked safe — and the
    next enum added (`cockpit_posture`) inherited nothing, accepted `"bogus-tier"`,
    stored it, echoed it back with a 200, and was then IGNORED at read time because the
    resolver refuses to obey a value it does not know.
    That is the §ORGPOCKET silent-echo class one level down: the KEY was known, so the
    allowlist waved it through, and only the VALUE was nonsense. An org admin who sets a
    security posture and is told 200 has every reason to believe it is in force.
    Deriving the check from the same table the FE form is built from is what makes the
    catalog the source of truth its docstring already claims it is — and means the hole
    cannot come back with the entry after next.

    ⚠ Enums only, deliberately. Numbers keep their bespoke range checks below, because
    those carry semantics (1..366 days, >= 0) that no generic type check can express.
    """
    out: Dict[str, set] = {}
    for entry in ORG_SETTING_CATALOG:
        if entry.get("type") == "enum":
            out[str(entry["key"])] = set(entry.get("values") or [])
    return out


def validate_org_settings_patch(patch: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate an org-settings PATCH against the catalog. Returns (ok, error_message).

    §ORGPOCKET (2026-08-28) — this now actually does what its name and this module's
    docstring have always claimed. It used to range-check the four keys it recognised
    and return ok for everything else, and the caller merged whatever it was given into
    organizations.settings. `PUT .../settings {"chat_enabled": true}` therefore answered
    200 with the value echoed while the real switch — the organizations.chat_enabled
    COLUMN — stayed false. Unknown keys are refused, and the ones that belong to a known
    neighbouring route say so instead of just saying no.
    """
    if not isinstance(patch, dict):
        return False, "settings must be an object"
    allowed = allowed_setting_paths()
    for k, v in patch.items():
        if k not in allowed:
            where = _ELSEWHERE.get(k)
            return False, (
                f"'{k}' is not an org setting; set it with {where}" if where else
                f"'{k}' is not an org setting (allowed: {', '.join(sorted(allowed))})"
            )
        if allowed[k] and isinstance(v, dict):
            unknown = [s for s in v if s not in allowed[k]]
            if unknown:
                return False, (f"'{k}.{unknown[0]}' is not an org setting "
                               f"(allowed under {k}: {', '.join(sorted(allowed[k]))})")
    # Catalog-DERIVED enum validation, before any hand-written check, so a new enum
    # entry is protected by existing in the catalog rather than by someone remembering.
    enums = catalog_enums()
    for k, v in patch.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                allowed_vals = enums.get(f"{k}.{sk}")
                if allowed_vals is not None and str(sv) not in allowed_vals:
                    return False, (f"'{k}.{sk}' must be one of "
                                   f"{'|'.join(sorted(x for x in allowed_vals if x)) or '(none)'}")
        else:
            allowed_vals = enums.get(k)
            if allowed_vals is not None and str(v) not in allowed_vals:
                return False, (f"'{k}' must be one of "
                               f"{'|'.join(sorted(x for x in allowed_vals if x)) or '(none)'}"
                               + ("" if "" not in allowed_vals else " (empty inherits the registry default)"))

    liab = patch.get("liability")
    if liab is not None:
        if not isinstance(liab, dict):
            return False, "liability must be an object"
        m = liab.get("mode")
        if m is not None and str(m).lower() not in _MODE_RANK:
            return False, "liability.mode must be one of off|shadow|enforce"
        t = liab.get("presence_threshold_avt")
        if t is not None:
            try:
                if float(t) < 0:
                    return False, "liability.presence_threshold_avt must be >= 0"
            except (TypeError, ValueError):
                return False, "liability.presence_threshold_avt must be a number"
    ttl = patch.get("contract_offer_ttl_days")
    if ttl is not None:
        try:
            iv = int(ttl)
            if iv < 1 or iv > 366:
                return False, "contract_offer_ttl_days must be an integer 1..366"
        except (TypeError, ValueError):
            return False, "contract_offer_ttl_days must be an integer"
    ceil = patch.get("org_spend_ceiling_avt")
    if ceil is not None:
        try:
            if float(ceil) < 0:
                return False, "org_spend_ceiling_avt must be >= 0"
        except (TypeError, ValueError):
            return False, "org_spend_ceiling_avt must be a number"
    # Catalog-DERIVED range checks, run AFTER the bespoke ones above so their specific
    # messages keep winning where they exist. Same lesson as `catalog_enums()`, one type
    # further along: the catalog already declares min/max, and a new number entry should
    # be protected by EXISTING in the table rather than by someone remembering to add a
    # fourth hand-written `if` down here.
    for entry in ORG_SETTING_CATALOG:
        if entry.get("type") != "number":
            continue
        key = str(entry["key"])
        if "." in key or key not in patch:
            continue
        v = patch.get(key)
        if v is None or v == "":
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return False, f"'{key}' must be a number"
        lo, hi = entry.get("min"), entry.get("max")
        if lo is not None and fv < lo:
            return False, f"'{key}' must be at least {lo}"
        if hi is not None and fv > hi:
            return False, f"'{key}' must be at most {hi}"

    slice_ = patch.get("default_agent_authority_slice")
    if slice_ is not None and str(slice_) not in ("", "guest", "member", "admin", "owner"):
        return False, "default_agent_authority_slice must be one of ''|guest|member|admin|owner"
    pub = patch.get("public_transparency_opt_in")
    if pub is not None and not isinstance(pub, bool):
        return False, "public_transparency_opt_in must be true or false"
    pld = patch.get("procurement_limit_default")
    if pld is not None and pld != "":
        if isinstance(pld, bool) or _decimal_or_none(pld) is None or _decimal_or_none(pld) < 0:
            return False, "procurement_limit_default must be a decimal >= 0 (0/empty = unlimited)"
    plm = patch.get("procurement_limits")
    if plm is not None:
        if not isinstance(plm, dict):
            return False, "procurement_limits must be an object map of developer id → amount"
        for k, v in plm.items():
            if not str(k).isdigit():
                return False, f"procurement_limits key '{k}' must be a developer id (integer)"
            if isinstance(v, bool) or _decimal_or_none(v) is None or _decimal_or_none(v) < 0:
                return False, (f"procurement_limits['{k}'] must be a decimal >= 0 "
                               "(0 = unlimited for that member)")
    intake = patch.get("intake_agent_did")
    if intake is not None:
        if not isinstance(intake, str) or len(intake) > 120:
            return False, "intake_agent_did must be a DID string (max 120 chars) or empty"
        if intake and not intake.startswith("did:"):
            return False, "intake_agent_did must be an agent DID (did:…) or empty to clear"
    return True, ""


def _decimal_or_none(v):
    """Decimal from a number or decimal string, None when it isn't one (bools excluded by callers)."""
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def procurement_cap(org_settings: Optional[Dict[str, Any]], developer_id: int):
    """§ORGSPEND — the per-TRANSACTION treasury-draw cap binding `developer_id`, or None.

    Resolution: a per-member override in ``procurement_limits`` beats
    ``procurement_limit_default``; 0 (or unset/invalid) means UNLIMITED at BOTH levels —
    an override of 0 explicitly exempts that member from the default (consistent
    semantics; "block a member" is a role change, not a zero cap — only org admins can
    draw at all). Returns a positive Decimal or None. Pure — unit-testable."""
    if not isinstance(org_settings, dict):
        return None
    overrides = org_settings.get("procurement_limits")
    if isinstance(overrides, dict) and str(developer_id) in overrides:
        v = _decimal_or_none(overrides[str(developer_id)])
        return v if v is not None and v > 0 else None
    v = _decimal_or_none(org_settings.get("procurement_limit_default"))
    return v if v is not None and v > 0 else None


def org_spend_ceiling(org_settings: Optional[Dict[str, Any]]) -> Optional[float]:
    """The org's per-tx spend ceiling, or None when unset/0/invalid (no org cap)."""
    if not isinstance(org_settings, dict):
        return None
    try:
        v = float(org_settings.get("org_spend_ceiling_avt"))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def default_authority_slice(org_settings: Optional[Dict[str, Any]]) -> str:
    """The org's configured default authority slice for newly-assigned agents ('' = none)."""
    if not isinstance(org_settings, dict):
        return ""
    v = str(org_settings.get("default_agent_authority_slice") or "")
    return v if v in ("guest", "member", "admin", "owner") else ""
