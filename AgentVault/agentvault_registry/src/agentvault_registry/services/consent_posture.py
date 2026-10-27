"""§COCKPIT P4 (§POSTURE) — the dials, as data.

Strategy §7/§8 split the design in two: **invariants** are laws (never configurable)
and **posture** is the dials. A deployment chooses its dials; it does not get to
choose its laws. This module is the dials — and, deliberately, the hard bounds sit
in the same file so the two can be read against each other in one screen.

D3 (Commander, 2026-08-30) ratified the names — swift · balanced · hardened — and
this deployment's registry default: **swift**.

Composition is TIGHTEN-ONLY and rides the SAME path `org_policy.effective_liability`
already walks (agent → creator developer → organization). An org may escalate its own
agents' posture; it can never relax below the registry's. `swift < balanced < hardened`.

⚠ ONE CORRECTION TO THE PLAN, MADE BY MEASUREMENT (R9 vs R5/§8):
R9 says a matching pre-flight preview's `first_presented_at` starts the read-floor
clock. `first_presented_at` is CLIENT-ASSERTED (§8: "the read floor ... is enforced
against the server's own delivery-ack timestamp, never the client's clock"), so
honouring it would let any client claim it painted the preview an hour ago and skip
the floor entirely — the floor would be advisory, which is the same as absent.
The rule shipped here keeps R9's INTENT (a human who genuinely pre-read consents
immediately) on a SERVER-ATTESTED clock: the matching preview's own `created_at`,
stamped when the server minted it. The client's `first_presented_at` is still stored
and still surfaced, labelled `client_asserted`, because it is the only signal of how
long the facts were actually on screen — it just never decides a refusal.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── ordering ────────────────────────────────────────────────────────────────
ORDER = ("swift", "balanced", "hardened")
_RANK = {name: i for i, name in enumerate(ORDER)}
DEFAULT_POSTURE = "swift"

# ── methods, ranked by the PRESENCE they prove (not by how modern they are) ──
# `enclave` is the raw ES256 rail: it proves possession of a key and NOTHING about a
# human — the approve path says so in its own comment. `totp` costs a human a glance
# at a second device. `webauthn_uv` is the only one where the authenticator refuses to
# sign without a fingerprint or PIN and REPORTS that fact in a flag the server checks.
# That is the ranking; "newer" would have put enclave above totp and been wrong.
METHOD_RANK: Dict[str, int] = {"enclave": 1, "totp": 2, "webauthn_uv": 3}
_RANK_METHOD = {v: k for k, v in METHOD_RANK.items()}

# ── the bundles (strategy §8's table, one row per dial) ──────────────────────
# Numbers are defaults to measure against. The ROWS are the contract: which dials
# exist, and which law bounds each.
POSTURES: Dict[str, Dict[str, Any]] = {
    "swift": {
        "name": "swift",
        # method floor — §8 reads "webauthn_uv, TOTP fallback". That cell names the
        # PREFERRED method and an explicit fallback, i.e. it refuses nothing; the
        # plan's default-posture invariant is that swift preserves today's behaviour
        # exactly. So the FLOOR (what gets refused) and the PREFERENCE (what the UI
        # offers first) are separate fields here rather than one conflated string.
        "method_floor": "enclave",
        "method_preferred": "webauthn_uv",
        "totp_only_while_unenrolled": False,
        "read_floor_ms": 800,
        "challenge_ttl_seconds": 900,
        "preflight": True,
        # R9's clock credit is not eternal. "The human already read this" is a claim
        # about a working session, not about all history: without a bound, one preview
        # would make every future identical ask instantly confirmable forever, which
        # is the fatigue vector the read floor exists to resist.
        "preview_credit_max_age_s": 900,
        # D5 — ON IN EVERY POSTURE. Never mint a challenge nobody can see.
        "presence_gated_raise": True,
        "device_render": "core_line_desk_authenticator_ok",
        "ceilings": True,
        "ceiling_decay_hours": 24,
        "four_eyes": "off",
        "overflow": "propose_ceiling",
        "streak_badge_at": 3,
        # R7 gave anti-fatigue teeth: at this streak the method floor escalates for
        # that action type. `None` = presentational only, which is what D3's default
        # posture asks for.
        "streak_method_escalate_at": None,
        "streak_propose_ceiling_at": 8,
        "quiet_hours": "queue_notify_on_return",
    },
    "balanced": {
        "name": "balanced",
        "method_floor": "totp",
        "method_preferred": "webauthn_uv",
        # "TOTP only while unenrolled": once this human HAS a live WebAuthn
        # credential, TOTP stops being a fallback and becomes a downgrade.
        "totp_only_while_unenrolled": True,
        "read_floor_ms": 1500,
        "challenge_ttl_seconds": 600,
        "preflight": True,
        "preview_credit_max_age_s": 900,
        "presence_gated_raise": True,
        "device_render": "core_line_separate_device",
        "ceilings": True,
        "ceiling_decay_hours": 8,
        "four_eyes": "above_amount",
        "overflow": "route_then_escalate",
        "streak_badge_at": 3,
        "streak_method_escalate_at": 5,
        "streak_propose_ceiling_at": None,
        "quiet_hours": "escalate",
    },
    "hardened": {
        "name": "hardened",
        "method_floor": "webauthn_uv",
        "method_preferred": "webauthn_uv",
        "totp_only_while_unenrolled": False,   # moot: totp is below the floor
        "read_floor_ms": 3000,
        "challenge_ttl_seconds": 300,
        "preflight": False,
        # Moot while `preflight` is off — a preview grants no credit at all under
        # hardened, which is what "every action asks" has to mean.
        "preview_credit_max_age_s": 0,
        "presence_gated_raise": True,
        "device_render": "full_facts_device_paced",
        "ceilings": False,
        "ceiling_decay_hours": None,
        "four_eyes": "all_money",
        "overflow": "queue_and_wait",
        "streak_badge_at": 2,
        "streak_method_escalate_at": 5,
        "streak_propose_ceiling_at": None,
        "quiet_hours": "escalate",
    },
}

# ── hard bounds (the I-laws), kept beside the dials on purpose ───────────────
# A dial that could be turned past one of these is a law that was really a default.
# Anything a future bundle sets outside these is CLAMPED here, loudly.
HARD_BOUNDS = {
    # I3 — expiry stays a denial. What changed at D4 is the CEILING, not the law: a
    # lapsed confirm is still a refusal, it just no longer happens because somebody
    # made coffee. 120 s was a number chosen when nobody had watched a human use this;
    # the Commander watched, and "a human reads slow and looks out of the window" is
    # the requirement. The registry MAX is a law; the value inside it is ergonomics.
    "challenge_ttl_seconds": (30, 3600),
    # A read floor is a pause, not a lock-out: a floor longer than the shortest TTL
    # would make some challenges unconfirmable by construction (the unsatisfiable
    # gate class — a rail that fails 100% of the time and looks like policy).
    "read_floor_ms": (0, 30_000),
    # I4 — the method is recorded and never downgraded; the floor may never be set
    # below the weakest method that exists.
    "method_floor": tuple(METHOD_RANK),
    # A standing consent that never decays is not a ceiling, it is a blank cheque.
    "ceiling_decay_hours": (1, 720),
    "preview_credit_max_age_s": (0, 3600),
}

# ── D4/D6 — THE TIME DIALS ──────────────────────────────────────────────────
# 🔴 THESE FOUR ARE NOT TIGHTEN-ONLY, AND THAT IS THE POINT.
# Every other dial an org can touch may only be made STRICTER than the registry's,
# because a posture is a security claim and an org must not be able to weaken one it
# was given. These four are not security claims — they are how long a human is given
# to think, and an org that knows its people read slowly must be able to give them
# LONGER, not merely shorter.
#
# What keeps that safe is the bound, not the direction: the registry's HARD_BOUNDS are
# a law the org cannot reach past, so "free inside the cap" is bounded by construction.
# The relaxation is named here so nobody later reads the tighten-only rule elsewhere in
# this file and assumes it covers everything.
#
# The mapping is catalog-key → bundle-key because the two vocabularies are allowed to
# differ: the org-facing name should read like a question a human asks ("how long do I
# get?"), the bundle key is the dial's internal name.
TIME_DIALS = {
    "cockpit_read_floor_ms": "read_floor_ms",
    "cockpit_challenge_ttl_seconds": "challenge_ttl_seconds",
    "cockpit_ceiling_decay_hours": "ceiling_decay_hours",
    "cockpit_preview_credit_seconds": "preview_credit_max_age_s",
}


def apply_time_dials(b: Dict[str, Any], org_settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Overlay an org's TIME dials onto a bundle, clamped to the registry's hard bounds.

    Longer OR shorter (D4). A value outside the bound is clamped and logged rather than
    refused here — the org-settings PUT validates ranges at write time, and a stored
    value that somehow sits outside them must still resolve to something usable rather
    than take a live gate down.
    """
    if not isinstance(org_settings, dict):
        return b
    out = dict(b)
    for cat_key, dial in TIME_DIALS.items():
        if cat_key not in org_settings:
            continue
        raw = org_settings.get(cat_key)
        if raw is None or raw == "":
            continue
        try:
            val = int(raw)
        except (TypeError, ValueError):
            logger.warning("[POSTURE] org %s=%r is not a number — ignored", cat_key, raw)
            continue
        lo, hi = HARD_BOUNDS.get(dial, (None, None))
        if lo is not None and (val < lo or val > hi):
            logger.warning("[POSTURE] org %s=%s outside the registry bound [%s,%s] — clamped",
                           cat_key, val, lo, hi)
            val = max(lo, min(hi, val))
        out[dial] = val
    return out


def _clamp_ttl(v: Any) -> int:
    lo, hi = HARD_BOUNDS["challenge_ttl_seconds"]
    try:
        n = int(v)
    except (TypeError, ValueError):
        return lo
    if n < lo or n > hi:
        logger.warning("[POSTURE] challenge_ttl_seconds %s outside hard bound [%s,%s] — clamped", n, lo, hi)
    return max(lo, min(hi, n))


def _clamp_floor_ms(v: Any) -> int:
    lo, hi = HARD_BOUNDS["read_floor_ms"]
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    if n < lo or n > hi:
        logger.warning("[POSTURE] read_floor_ms %s outside hard bound [%s,%s] — clamped", n, lo, hi)
    return max(lo, min(hi, n))


def bundle(name: str) -> Dict[str, Any]:
    """The named bundle, hard-bounds applied. Unknown name ⇒ the default, loudly."""
    key = (name or "").strip().lower()
    if key not in POSTURES:
        if key:
            logger.warning("[POSTURE] unknown posture %r — falling back to %s", key, DEFAULT_POSTURE)
        key = DEFAULT_POSTURE
    b = dict(POSTURES[key])
    b["challenge_ttl_seconds"] = _clamp_ttl(b["challenge_ttl_seconds"])
    b["read_floor_ms"] = _clamp_floor_ms(b["read_floor_ms"])
    if b["method_floor"] not in METHOD_RANK:
        logger.warning("[POSTURE] %s has an unknown method_floor %r — clamped to the weakest known",
                       key, b["method_floor"])
        b["method_floor"] = _RANK_METHOD[min(METHOD_RANK.values())]
    return b


def registry_posture() -> str:
    """This registry's floor. Env `COCKPIT_POSTURE`; D3's default is `swift`."""
    raw = (os.environ.get("COCKPIT_POSTURE", "") or "").strip().lower()
    if raw and raw not in POSTURES:
        logger.warning("[POSTURE] COCKPIT_POSTURE=%r is not one of %s — using %s",
                       raw, ORDER, DEFAULT_POSTURE)
        return DEFAULT_POSTURE
    return raw or DEFAULT_POSTURE


def org_posture(org_settings: Optional[Dict[str, Any]]) -> Optional[str]:
    """The org's chosen posture, or None. Unknown values are ignored, not obeyed —
    an org cannot escape its registry floor by writing nonsense."""
    if not isinstance(org_settings, dict):
        return None
    raw = str(org_settings.get("cockpit_posture") or "").strip().lower()
    if raw and raw not in POSTURES:
        logger.warning("[POSTURE] org cockpit_posture=%r unknown — ignored", raw)
        return None
    return raw or None


def resolve(registry_name: str, org_settings: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Strictest wins. Returns (name, bundle)."""
    reg = registry_name if registry_name in POSTURES else DEFAULT_POSTURE
    org = org_posture(org_settings)
    name = reg
    if org and _RANK[org] > _RANK[reg]:
        name = org
    # The bundle first (strictest posture wins), THEN the org's time dials on top —
    # order matters: a posture change must not silently discard the org's ergonomics,
    # and a time dial must never be able to change which posture is in force.
    return name, apply_time_dials(bundle(name), org_settings)


async def for_agent(db, agent_did: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    """Resolve the posture that binds actions of `agent_did`.

    An organization's posture can only be stricter than the registry's, so an org lookup that fails refuses
    (org_policy.OrgSettingsUnavailable, a 503) rather than resolving to the registry floor. §SECFIX D6-491
    (2026-10-16): it fell back to the registry posture, which RELAXED an organization's stricter posture whenever
    its settings could not be read."""
    reg = registry_posture()
    if not agent_did:
        return reg, bundle(reg)
    from agentvault_registry.services import org_policy as _op
    settings = await _op.get_org_settings(db, agent_did)
    return resolve(reg, settings)


# ── the method floor ────────────────────────────────────────────────────────
def method_allowed(b: Dict[str, Any], method: str, *,
                   has_webauthn_credential: bool = False,
                   escalated_floor: Optional[str] = None) -> Tuple[bool, Optional[str], str]:
    """May this posture hear `method` as an answer? Returns (ok, refusal_code, floor).

    `escalated_floor` is R7's teeth: a streak can raise the floor for one action type
    without changing the org's posture.
    """
    floor = b.get("method_floor", "enclave")
    if escalated_floor and METHOD_RANK.get(escalated_floor, 0) > METHOD_RANK.get(floor, 0):
        floor = escalated_floor
    have = METHOD_RANK.get(method, 0)
    if have == 0:
        return False, "method_unknown", floor
    if have < METHOD_RANK[floor]:
        return False, "method_below_floor", floor
    if method == "totp" and b.get("totp_only_while_unenrolled") and has_webauthn_credential:
        # Not "below the floor" — a DIFFERENT refusal, and the message must say so,
        # or the human re-reads a floor they already meet and learns nothing.
        return False, "totp_superseded_by_enrolled_key", floor
    return True, None, floor


def method_refusal_detail(b: Dict[str, Any], method: str, code: str, floor: str) -> Dict[str, Any]:
    """The body of a floor refusal. §8's legacy-honesty rule: an `enclave`-only device
    under a `webauthn_uv` floor must be told to RE-ENROL. Never fail dark; never
    accept silently either."""
    remedy = {
        "method_below_floor": (
            "re-enrol this device with WebAuthn (GET /api/v1/liability/webauthn/options "
            "then POST /api/v1/liability/webauthn/register) and approve again"
            if floor == "webauthn_uv" and method == "enclave"
            else f"approve with a method at or above `{floor}`"),
        "totp_superseded_by_enrolled_key": (
            "this account has a WebAuthn credential enrolled, so TOTP is no longer "
            "accepted here — approve with the enrolled device"),
        "method_unknown": "no recognised presence method was offered",
    }.get(code, f"approve with a method at or above `{floor}`")
    return {
        "error": code,
        "posture": b.get("name"),
        "method_floor": floor,
        "method_offered": method,
        "accepted_methods": [m for m, r in METHOD_RANK.items() if r >= METHOD_RANK[floor]],
        "remedy": remedy,
        # The challenge is NOT consumed by a floor refusal: single-use is a property of
        # ANSWERS, not of refusals-to-hear. Said out loud so a client does not re-mint.
        "challenge_still_pending": True,
    }
