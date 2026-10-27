"""Registry Card v0.3 — sovereign-variant catalog + visual pins.

Mirrors §pass39's `SOVEREIGN_VARIANT_OWNERS` pattern (fiat_onramp.py:3761), but
at the registry-tier instead of the agent-tier. A registry can claim a
sovereign_variant in its card visual block ONLY if:

  card.identity.spiffe_id == SOVEREIGN_REGISTRY_VARIANTS[variant]
  == peer.mTLS_presented_SVID

Receivers (federation_sync._sync_registry_card → registry_card_validator)
soft-reject sovereign claims that fail this 3-way SPIFFE check, stripping
visual.sovereign_variant before caching. The rest of the card is preserved.

Pins (SOVEREIGN_VISUAL_PINS) are Commander-set values per spec §0 row 1+2.
Operator PUTs to these mainframes have their `visual.*` block silently
overridden at serve time by `apply_sovereign_visual_pin()`.
"""
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Software version — Registry Card v0.3 `identity.software_version` field
# ============================================================================
# §pass66 (2026-05-22) — single source of truth for what deploy tag a registry
# is currently running. Surfaced THREE ways from the same value:
#
#   1. Registry Card v0.3 `identity.software_version` — federation-visible at
#      `/.well-known/registry-card.json`, lets peers see "Frame A is on pass66,
#      op-london is on pass64.1" without out-of-band channels. DERIVED, NOT
#      signed (treated like `founded_at` / `display_name` — present in identity
#      block but outside the 13 canonical signed paths in registry_card_signer).
#      A federated peer could lie about its version in the card body because
#      we don't sign this field. Mitigation: peers authenticate via SPIFFE mTLS
#      before card fetch, so the fetch is bound to a known peer; compliance
#      enforcement (license `min_image_version`) ultimately gates on the peer's
#      ACTUAL runtime env at request time, not the card claim.
#
#   2. `cloud_provisioner` `.env.operator` VERSION= line — fresh provisions
#      pin to the central registry's currently-running tag so what the new
#      operator pulls is exactly what their parent is running. No more drift
#      to `:stable`.
#
#   3. Internal diagnostics — admin /admin/system-resources can surface this
#      without docker.sock introspection.
#
# Resolution order:
#   1. `IMAGE_TAG` env (canonical — Commander sets in .env.production after
#      `docker compose build && docker tag … && docker push …`)
#   2. `OPERATOR_DEFAULT_IMAGE_VERSION` env (legacy alias kept for sandbox-A,
#      where it's been in use since 2026-04-28 to pin sandbox cloud-ops to a
#      reactor-framework-aware tag)
#   3. `BUNDLED_IMAGE_TAG` constant below (last-resort default — bumped per
#      release in the codebase itself, so a forgotten env still produces a
#      meaningful, non-empty value)
#   4. "" (empty — caller sees absence, can emit warning)
#
# Mainframes are source-built (`docker compose build` against this repo's
# source), not pulled — so for a mainframe, IMAGE_TAG represents "the deploy
# tag corresponding to the source currently running" (set at rollout when
# the same source is also tagged + pushed for operators to pull). Cloud-ops
# pulled this tag literally via VERSION= in .env.operator.

# His word 2026-10-02: the tag family from V0549 on is TheProtocolReleaseVNNNN (the earlier families stay on the images
# that carry them). Both version parsers read only the trailing V(\d+) (release_channel, cloud_provisioner).
BUNDLED_IMAGE_TAG = "TheProtocolReleaseV0646"


def get_software_version() -> str:
    """Return the deploy tag this registry process is associated with.

    See module docstring for resolution order + rationale.

    Returns:
        The tag string (e.g., "pass66-software-version-2026-05-22"). Returns
        "" only if ALL three sources are unset — a configuration regression
        that callers should treat as actionable (log + don't crash).
    """
    return (
        os.environ.get("IMAGE_TAG", "")
        or os.environ.get("OPERATOR_DEFAULT_IMAGE_VERSION", "")
        or BUNDLED_IMAGE_TAG
        or ""
    )


# spec §0 row 2: 9 reserved slots, 2 claimed.
# Map: variant_slug -> SPIFFE ID of the registry allowed to claim it.
# None = reserved (Commander assigns SPIFFE later via single-line code edit).
SOVEREIGN_REGISTRY_VARIANTS: Dict[str, Optional[str]] = {
    # Currently claimable (Commander-set 2026-05-21):
    "genesis-flame":         "spiffe://agentvault.com/registry/Registry-A",
    "sovereign-frame":       "spiffe://frame-b.theprotocol.cloud/registry/Frame-B",
    # §pass78c (2026-06-05) — prod Frame-C (BVT). MUST mirror the SOVEREIGN_VISUAL_PINS
    # entry added §pass78b; without it the 3-way verify rejects 'bvt-sovereign' as
    # unknown → strips visual.sovereign_variant → breaks frame-c's card SIGNATURE on
    # every peer (sig=f everywhere; the two dicts must stay in lock-step).
    "bvt-sovereign":         "spiffe://frame-c.theprotocol.cloud/registry/Frame-C",

    # Reserved for future regional mainframes:
    "eu-mainframe":          None,
    "americas-mainframe":    None,
    "asia-mainframe":        None,
    "oceania-mainframe":     None,
    "africa-mainframe":      None,

    # Reserved for special-purpose Commander-assigned later:
    "archive-mainframe":     None,
    "compliance-mainframe":  None,
    "community-mainframe":   None,
}


# §pass67 (2026-05-23) — SOVEREIGN PROMOTION DRAFTS for regional variants.
#
# The 5 regional encirclements (savanna/andes/liberty/outback/alpine) ship as
# COSMETIC tier="shadow_chancellor" variants — any registry can equip them.
#
# To promote one to a SPIFFE-locked sovereign variant for a regional mainframe,
# uncomment the matching pair of lines below + add the SPIFFE ID:
#
#   1. SOVEREIGN_REGISTRY_VARIANTS["<slot>"] = "spiffe://<td>/registry/<name>"
#      (line in dict above — uses one of the 5 reserved -mainframe slots)
#   2. SOVEREIGN_VISUAL_PINS["spiffe://<td>/registry/<name>"] = { … pin block … }
#      (line in pin dict below — locks orb_color / glow / pulse / variant)
#
# After both edits + restart, the regional encirclement becomes locked to that
# specific SPIFFE ID. Operator PUTs to that registry's card silently get the
# pin re-applied at serve time. The cosmetic variant remains available to any
# OTHER registry that wants it (since the COSMETIC variant `savanna` is in
# FLARE_ENCIRCLEMENT_VARIANTS, while the LOCKED variant would be a separate
# `africa-mainframe` slot key in SOVEREIGN_REGISTRY_VARIANTS).
#
# Drafts for the 5 regional mainframes (all commented out — Commander uncomments
# after picking the SPIFFE ID for each regional mainframe):

# SAVANNA — Africa-mainframe future-claim (warm sunset palette).
# SOVEREIGN_REGISTRY_VARIANTS["africa-mainframe"] = "spiffe://<td>/registry/<name>"
# SOVEREIGN_VISUAL_PINS["spiffe://<td>/registry/<name>"] = {
#     "orb_color":           "#c84818",   # savanna ember
#     "orb_glow_color":      "#fde088",   # sunset amber halo
#     "orb_pulse_speed_hz":  1.2,
#     "orb_size_px":         18,
#     "halo_enabled":        True,
#     "halo_thickness":      1.6,
#     "theme":               "sovereign",
#     "sovereign_variant":   "africa-mainframe",
#     # Note: the cosmetic encirclement `savanna` would still be operator-pickable
#     # on this registry's card; the sovereign variant promotes it visually.
# }

# ANDES — Americas-South mainframe future-claim (slate-condor palette).
# SOVEREIGN_REGISTRY_VARIANTS["americas-mainframe"] = "spiffe://<td>/registry/<name>"
# SOVEREIGN_VISUAL_PINS["spiffe://<td>/registry/<name>"] = {
#     "orb_color":           "#c87828",   # condor-copper
#     "orb_glow_color":      "#fde088",   # gold halo
#     "orb_pulse_speed_hz":  1.3,
#     "orb_size_px":         18,
#     "halo_enabled":        True,
#     "halo_thickness":      1.6,
#     "theme":               "sovereign",
#     "sovereign_variant":   "americas-mainframe",
# }

# LIBERTY — Americas-North mainframe future-claim (verdigris-torch palette).
# Alternative slot for the Americas continent; pick one (andes OR liberty).
# SOVEREIGN_REGISTRY_VARIANTS["americas-mainframe"] = "spiffe://<td>/registry/<name>"
# SOVEREIGN_VISUAL_PINS["spiffe://<td>/registry/<name>"] = {
#     "orb_color":           "#7eb8a8",   # verdigris copper
#     "orb_glow_color":      "#fde04a",   # torch-flame gold
#     "orb_pulse_speed_hz":  1.5,
#     "orb_size_px":         18,
#     "halo_enabled":        True,
#     "halo_thickness":      1.6,
#     "theme":               "sovereign",
#     "sovereign_variant":   "americas-mainframe",
# }

# OUTBACK — Oceania-mainframe future-claim (terracotta dot-painting palette).
# Abstract geometric only — respects Indigenous art traditions.
# SOVEREIGN_REGISTRY_VARIANTS["oceania-mainframe"] = "spiffe://<td>/registry/<name>"
# SOVEREIGN_VISUAL_PINS["spiffe://<td>/registry/<name>"] = {
#     "orb_color":           "#a8421a",   # outback terracotta
#     "orb_glow_color":      "#fde088",   # ochre highlight
#     "orb_pulse_speed_hz":  1.1,
#     "orb_size_px":         18,
#     "halo_enabled":        True,
#     "halo_thickness":      1.6,
#     "theme":               "sovereign",
#     "sovereign_variant":   "oceania-mainframe",
# }

# ALPINE — EU-mainframe future-claim (glacier-edelweiss palette).
# SOVEREIGN_REGISTRY_VARIANTS["eu-mainframe"] = "spiffe://<td>/registry/<name>"
# SOVEREIGN_VISUAL_PINS["spiffe://<td>/registry/<name>"] = {
#     "orb_color":           "#a8c8e0",   # alpine sky
#     "orb_glow_color":      "#ffffff",   # glacial white halo
#     "orb_pulse_speed_hz":  1.0,
#     "orb_size_px":         18,
#     "halo_enabled":        True,
#     "halo_thickness":      1.6,
#     "theme":               "sovereign",
#     "sovereign_variant":   "eu-mainframe",
# }


# spec §0 row 1+2 (Commander LOCKED 2026-05-21): visual identity for the
# two sovereign mainframes. Operator-uneditable; server silently re-applies
# at serve time so any PUT that tries to change these is a no-op.
SOVEREIGN_VISUAL_PINS: Dict[str, Dict[str, Any]] = {
    "spiffe://agentvault.com/registry/Registry-A": {
        "orb_color":           "#ff6b35",   # genesis-flame orange
        "orb_glow_color":      "#ffaa00",   # amber halo
        "orb_pulse_speed_hz":  1.6,         # slightly faster than peers
        "orb_size_px":         18,
        "halo_enabled":        True,
        "halo_thickness":      1.6,
        "theme":               "sovereign",
        "sovereign_variant":   "genesis-flame",
    },
    "spiffe://frame-b.theprotocol.cloud/registry/Frame-B": {
        "orb_color":           "#dc2626",   # sovereign red
        "orb_glow_color":      "#f97316",   # amber complement
        "orb_pulse_speed_hz":  1.4,
        "orb_size_px":         18,
        "halo_enabled":        True,
        "halo_thickness":      1.6,
        "theme":               "sovereign",
        "sovereign_variant":   "sovereign-frame",
    },
    # §pass78b (2026-06-04) — prod Frame C, sovereign BVT second-currency frame.
    # Gold/amber BVT identity (matches the auditor's BVT hue), distinct from
    # Frame-A genesis-flame orange and Frame-B sovereign red.
    "spiffe://frame-c.theprotocol.cloud/registry/Frame-C": {
        "orb_color":           "#ffb300",   # BVT gold
        "orb_glow_color":      "#ffd700",   # gold halo
        "orb_pulse_speed_hz":  1.5,
        "orb_size_px":         18,
        "halo_enabled":        True,
        "halo_thickness":      1.6,
        "theme":               "sovereign",
        "sovereign_variant":   "bvt-sovereign",
    },
}


# §pass78c (2026-06-05) — DRIFT GUARD / single source of truth.
# SOVEREIGN_VISUAL_PINS (who renders which sovereign orb) and SOVEREIGN_REGISTRY_VARIANTS
# (who is ALLOWED to claim which sovereign_variant in the 3-way verify) must never drift:
# §pass78b added Frame-C to the PINS but not the VARIANTS catalog, so the validator saw
# 'bvt-sovereign' as unknown → stripped it → broke Frame-C's card signature on EVERY peer
# (sig=f fleet-wide; the sovereign orb never propagated). Deriving the claimable entries
# from the pins makes adding a new sovereign frame a one-place edit that can't silently
# collide or break — operators get the full vanity surface without this footgun.
for _spiffe_id, _pin in SOVEREIGN_VISUAL_PINS.items():
    _variant = _pin.get("sovereign_variant")
    if _variant:
        SOVEREIGN_REGISTRY_VARIANTS[_variant] = _spiffe_id


# §pass78c (2026-06-05) — VANITY IS SHAREABLE (Commander directive).
# A registry's visual representation (orb style, encirclement, overlay, sovereign
# variant) is self-determined vanity that ANY op/frame-commander may equip — it does
# NOT have to be unique and may be used by others. The sovereign_variant was the one
# visual that used to be SPIFFE-locked to a single owner (write-time reject + receiver
# strip); that gating is dropped. We keep a KNOWN-variant allowlist only so the renderer
# always has defined styling to draw (an unknown string still soft-strips to the
# operator default). SOVEREIGN_VISUAL_PINS now means "canonical DEFAULT look for this
# variant", not "exclusive owner". Identity/trust is established by SPIFFE + the card
# signature, never by the orb — so shared vanity carries no spoofing risk.
KNOWN_SOVEREIGN_VARIANTS = frozenset(
    p["sovereign_variant"] for p in SOVEREIGN_VISUAL_PINS.values() if p.get("sovereign_variant")
)


def is_known_sovereign_variant(variant: Optional[str]) -> bool:
    """True if `variant` is a renderable sovereign vanity style any registry may equip."""
    return bool(variant) and variant in KNOWN_SOVEREIGN_VARIANTS


def apply_sovereign_visual_pin(
    spiffe_id: str,
    operator_visual: Dict[str, Any],
) -> Dict[str, Any]:
    """If this SPIFFE is sovereign-pinned, overlay the pin onto the operator visual block.

    Args:
        spiffe_id: card.identity.spiffe_id
        operator_visual: card_json.visual subset (operator-edited)

    Returns:
        New dict — pinned values WIN over operator values; non-pinned fields
        (e.g., icon_url, icon_etag) pass through unchanged.
    """
    pin = SOVEREIGN_VISUAL_PINS.get(spiffe_id)
    if pin is None:
        return dict(operator_visual)
    merged = dict(operator_visual)
    merged.update(pin)  # pin keys override
    # Preserve non-pinned operator additions (icon_url, etc.)
    for key in ("icon_url", "icon_etag", "icon_size_bytes",
                "flare_corner_variant", "flare_encirclement_variant",
                "schema_compat"):
        if key in operator_visual:
            merged[key] = operator_visual[key]
    merged.setdefault("schema_compat", "v0.3")
    return merged


def is_sovereign_pinned(spiffe_id: str) -> bool:
    return spiffe_id in SOVEREIGN_VISUAL_PINS


def get_owner_spiffe_for_variant(variant: str) -> Optional[str]:
    """Return the SPIFFE ID that owns `variant`, or None if reserved/unknown."""
    return SOVEREIGN_REGISTRY_VARIANTS.get(variant)


# ----------------------------------------------------------------------------
# Flare encirclement + broken-machine overlay catalogs (Registry Card v0.3.1).
# Mirror the agent flare system (FlareEncirclement.vue + FlareManager.vue) —
# cosmetic only, NOT SPIFFE-locked. Any registry can equip any variant.
# ----------------------------------------------------------------------------

# 19 + 18 = 37 encirclement variants — full catalog.
# §pass67 (2026-05-23) — 18 NEW registry-themed full-cover variants added.
# Diversity targets: government / NGO / meme / regional / treasury.
# All new ones use tier="shadow_chancellor" (cosmetic, NOT SPIFFE-locked).
# Order matches the picker UI grid (frontend reads this from the registry-card
# editor's import of FLARE_ENCIRCLEMENT_VARIANTS via its own constant).
FLARE_ENCIRCLEMENT_VARIANTS = frozenset({
    # Original 19 (§14-§20)
    "sauron", "goth", "obsidian", "void", "aurora", "phoenix", "crystal",
    "blackhole", "halloween", "inferno", "glacier", "matrix", "galaxy", "ink",
    "circuit", "yule", "sakura", "solstice", "harvest",
    # §pass67 wave A — Government / Civic / Official-State (4)
    "chancellery", "statehouse", "bastille", "ministry",
    # §pass67 wave B — NGO / Humanitarian / Multilateral (4)
    "olive-branch", "cross-shield", "lighthouse", "commons",
    # §pass67 wave C — Meme-native / Underground (4); the console shows Moonshot, Diamond, Frog, Pixel Shrine
    "moonshot", "diamond-hands", "chad-frog", "pixel-shrine",
    # §pass67 wave D — Regional / Future-mainframe pins (5)
    "savanna", "andes", "liberty", "outback", "alpine",
    # §pass67 wave E — Hard-money / Treasury (1)
    "bullion-vault",
})

# 13 + 8 = 21 broken-machine overlays.
# §pass67 (2026-05-23) — 8 NEW overlays added: redaction / manifold / rugpull /
# shilling / brownout / stampede / karma-debt / freeze.
# Receivers render these as a second SVG layer on top of the encirclement.
FLARE_ENCIRCLEMENT_OVERLAYS = frozenset({
    # Original 13 (§21-§pass43)
    "glitch", "cascade", "panic-a", "panic-b", "panic-c",
    "breach", "refract", "stutter", "bleed", "crackle",
    "feedback", "spatter", "unravel",
    # §pass67 wave F — Registry-themed broken-machine overlays (8)
    "redaction", "manifold", "rugpull", "shilling",
    "brownout", "stampede", "karma-debt", "freeze",
})

# Corner-badge variants (smaller catalog; mirrors agent flare_corner_variant).
# §pass67 — extended with 4 new corner-readable variants from the registry set.
FLARE_CORNER_VARIANTS = frozenset({
    "sauron", "phoenix", "crystal", "matrix", "circuit",
    # §pass67 — new readable-at-16-22px badges
    "chancellery", "diamond-hands", "liberty", "bullion-vault",
})


def is_valid_encirclement_variant(v: Optional[str]) -> bool:
    return v is None or v in FLARE_ENCIRCLEMENT_VARIANTS


def is_valid_encirclement_overlay(v: Optional[str]) -> bool:
    return v is None or v in FLARE_ENCIRCLEMENT_OVERLAYS


def is_valid_corner_variant(v: Optional[str]) -> bool:
    return v is None or v in FLARE_CORNER_VARIANTS


__all__ = [
    "SOVEREIGN_REGISTRY_VARIANTS",
    "SOVEREIGN_VISUAL_PINS",
    "apply_sovereign_visual_pin",
    "is_sovereign_pinned",
    "get_owner_spiffe_for_variant",
    "FLARE_ENCIRCLEMENT_VARIANTS",
    "FLARE_ENCIRCLEMENT_OVERLAYS",
    "FLARE_CORNER_VARIANTS",
    "is_valid_encirclement_variant",
    "is_valid_encirclement_overlay",
    "is_valid_corner_variant",
    "BUNDLED_IMAGE_TAG",
    "get_software_version",
]
