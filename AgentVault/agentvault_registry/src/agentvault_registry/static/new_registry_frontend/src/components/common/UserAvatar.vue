<!--
  UserAvatar — single-source-of-truth dual-slot avatar composition (PB-1 §12).

  Renders a user's avatar with both PB-1 flare slots resolved correctly:
    1. Encirclement slot — wraps the avatar circle (Shadow Chancellor today)
    2. Corner slot      — bottom-right badge (Sentinel/Architect/Founder/
                                              Operator/Commander)

  Source-of-truth resolution order (per slot):
    1. user.selected_<slot>_flare           (explicit user choice)
    2. user.flare_tier (legacy fallback)    if it matches the slot class
    3. null                                  → no flare in that slot

  Encirclement-class tiers (today: shadow_chancellor) NEVER render in the
  corner. Corner-class tiers NEVER render as encirclement. This component
  enforces the rules — surfaces consume `<UserAvatar :user="..." />` without
  re-implementing slot logic.

  Usage examples:

    <UserAvatar :user="authStore.user" :avatar-url="profileAvatar" size="md" clickable @click="goToSettings" />
    <UserAvatar :user="agent" :avatar-url="agent.avatar" :display-name="agent.name" size="sm" />
    <UserAvatar :user="profileForm" :avatar-url="profileForm.avatar_url" size="xl" />

  size presets pass through to FlareEncirclement (xs|sm|md|lg|xl); the corner
  badge auto-scales (xs ring for ≤md user avatar, sm ring for ≥lg).
-->
<template>
  <component
    :is="clickable ? 'button' : 'span'"
    class="ua"
    :class="[`ua-size-${size}`, { 'ua-clickable': clickable }]"
    :type="clickable ? 'button' : undefined"
    :role="clickable ? undefined : 'img'"
    :title="title || resolvedTitle"
    :aria-label="ariaLabel || resolvedTitle"
    @click="onClick"
  >
    <!-- Encirclement slot — replaces the plain ring when active.
         §14 (2026-05-12): variant forwarded so shadow_chancellor backers'
         picked aesthetic (sauron|goth|obsidian|void) lights up universally.
         An explicit `variant` prop overrides the user's stored choice (used
         by the FlareManager picker for live previews of all 4 options). -->
    <FlareEncirclement
      v-if="encirclementTier"
      :tier="encirclementTier"
      :variant="effectiveVariant"
      :overlay="effectiveOverlay"
      :avatar-url="effectiveAvatarUrl"
      :initials="resolvedInitials"
      :alt="resolvedDisplayName"
      :size="size"
      :track-record="effectiveTrackRecord"
    />

    <!-- Plain avatar ring — used when no encirclement is active -->
    <span v-else class="ua-ring" :class="{ 'ua-ring--has-image': effectiveAvatarUrl }">
      <img
        v-if="effectiveAvatarUrl"
        :src="effectiveAvatarUrl"
        :alt="resolvedDisplayName"
        class="ua-img"
        @error="onAvatarError"
      />
      <span v-else class="ua-initials">{{ resolvedInitials || '?' }}</span>
    </span>
    <!-- §POCKETDISC — the LEDGER-EARNED collar on the PLAIN path. When an
         encirclement is active the collar rides INSIDE FlareEncirclement
         (its load-bearing z-layer); gating on !encirclementTier here is what
         stops a double collar.
         §MARKSURFACES (2026-09-10): the source is now `effectiveTrackRecord`,
         which falls back to the row this component was already handed — see
         its comment below. Surfaces that pass nothing and whose row carries no
         track record stay pixel-identical. -->
    <EarnedMarkCollar
      v-if="effectiveTrackRecord && !encirclementTier"
      :tr="effectiveTrackRecord"
      :size="size"
      class="fc-earned-collar ua-collar"
    />

    <!-- Corner slot — bottom-right pip. xs ring for compact, sm for big avatars.
         §20 (2026-05-13): cornerVariant prop forwards the admin corner badge
         override (rocket / crown / vault / gavel / atom / network). NULL on
         non-admins → renders default tier icon. -->
    <FlareBadge
      v-if="cornerTier"
      :tier="cornerTier"
      :granted-at="grantedAt || null"
      :display-name="(user as any)?.flare_display_name || null"
      :tagline="(user as any)?.flare_tagline || null"
      :logo-url="(user as any)?.flare_logo_url || null"
      :cause="(user as any)?.flare_cause || null"
      :accent-color="(user as any)?.flare_accent_color || null"
      :flare-id="(user as any)?.flare_id || null"
      :corner-variant="(user as any)?.flare_corner_variant || null"
      :size="cornerBadgeSize"
      :show-label="false"
      class="ua-corner"
    />
  </component>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import FlareBadge from '@/components/common/FlareBadge.vue'
import EarnedMarkCollar from '@/components/common/EarnedMarkCollar.vue'
import type { TrackRecordCompact } from '@/services/api/trackRecord'

/** Subset of fields from Developer/User that drive the dual-slot rendering.
 *  Component accepts `user: any` for ergonomic backward-compat with stores. */
type UserLike = {
  flare_tier?: string | null
  flare_granted_at?: string | null
  selected_corner_flare?: string | null
  selected_encirclement_flare?: string | null
  display_name?: string | null
  name?: string | null
  email?: string | null
} & Record<string, any>

const props = withDefaults(defineProps<{
  /** The user object whose flare slots drive rendering. */
  user?: UserLike | null
  /** Avatar URL — falls back to initials/icon on error. */
  avatarUrl?: string | null
  /** Override display name (e.g., from /developers/me when authStore lags). */
  displayName?: string | null
  /** Pre-computed initials (1-2 chars). When omitted, derived from displayName/email. */
  initials?: string | null
  /** Size preset — passes through to FlareEncirclement. */
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  /** Optional flare grant timestamp (for FlareBadge tooltip). */
  grantedAt?: string | null
  /** When true, render as a <button>; emits 'click' on tap. */
  clickable?: boolean
  /** ARIA + title attr override. Defaults to "<name> · <Tier> backer". */
  title?: string | null
  ariaLabel?: string | null
  /** Override encirclement variant (used by FlareManager picker for live
   *  previews). Falls back to user.flare_encirclement_variant, then default. */
  variantOverride?:
    | 'sauron' | 'goth' | 'obsidian' | 'void'
    | 'aurora' | 'phoenix' | 'crystal'
    | 'blackhole' | 'halloween'
    | 'inferno' | 'glacier' | 'matrix'
    | 'galaxy' | 'ink' | 'circuit'
    | 'yule' | 'sakura' | 'solstice' | 'harvest'
    // §pass39 (2026-05-18) — sovereign signature variants (DID-locked).
    | 'aegis' | 'prism' | 'panopticon' | 'vellum' | 'dispatch' | 'bullion'
    | 'seal' | 'ozymandian' | 'clarion' | 'forge' | 'weave'
    | null
  /** §28 (2026-05-13) — Override broken-machine overlay. Falls back to
   *  user.flare_encirclement_overlay; pass null to force no overlay. */
  overlayOverride?: string | null
  /** §POCKETDISC (2026-08-23) — compact track record. Forwarded into the
   *  encirclement (collar inside the frame) or rendered as the standalone
   *  collar on the plain path. Omitted = no collar, exactly as before. */
  trackRecord?: TrackRecordCompact | null
}>(), {
  user: null,
  avatarUrl: null,
  displayName: null,
  initials: null,
  size: 'md',
  grantedAt: null,
  clickable: false,
  title: null,
  ariaLabel: null,
  variantOverride: null,
  overlayOverride: undefined,
  trackRecord: null,
})

const emit = defineEmits<{ (e: 'click'): void }>()

// ─── Slot resolution rules ──────────────────────────────────
// Single source of truth. Mirrors backend _unlocked_*_flares_for + the
// suppress logic in FlareBadge.vue. New encirclement-class tiers must
// be added here AND in FlareEncirclement's CONFIG map AND in FlareBadge's
// suppress check (early-return for that tier).
//
// §15 (2026-05-13): TWO-MODE resolution:
//   • Developer schema (has `selected_*_flare` field, possibly null): trust
//     the explicit selection. NULL = user cleared via "Hide" picker.
//   • Agent schema (no `selected_*_flare` field): fall back to flare_tier.
//     Agents share the dev's flare via _record_flare_grant but don't have
//     slot-selection columns. Both slots show for shadow_chancellor agents
//     (founder corner + shadow encirclement, mirroring the dev default).
//
// The distinction is via `typeof === 'undefined'` — field absent means
// "agent or pre-§12 user without selection schema", fall back. Field
// present (even as null) means "developer with explicit choice".
// §pass39 (2026-05-18) — sovereign tier added for per-system-agent signature
// flares. DID-locked at backend; ENCIRCLEMENT_TIERS controls whether
// UserAvatar wraps in FlareEncirclement at all (any value here just enables
// the wrap — the variant + tier combo at FlareEncirclement.vue picks the visual).
const ENCIRCLEMENT_TIERS = new Set(['shadow_chancellor', 'sovereign'])
const CORNER_TIERS = new Set(['sentinel', 'architect', 'founder', 'operator', 'commander'])

const encirclementTier = computed<string | null>(() => {
  const u = props.user
  if (!u) return null
  // §pass39b (2026-05-18) — SOVEREIGN always wins. The sovereign tier is
  // per-agent (set on agents.flare_tier directly) and NEVER user-selectable
  // — it's reserved for system agents. The slot-selection cascade below was
  // designed for backer flares where dev.selected_encirclement_flare drives
  // which agent wears the dev's flare; sovereign agents bypass that entirely
  // (dev.selected_encirclement_flare='shadow_chancellor' would otherwise
  // override the agent's sovereign tier and break CSS selectors).
  if (u.flare_tier === 'sovereign') return 'sovereign'
  const sel = (u as any).selected_encirclement_flare
  // Explicit string value — use it (typeof null === 'object', so safe).
  if (typeof sel === 'string' && ENCIRCLEMENT_TIERS.has(sel)) return sel
  // Explicit null (developer who hid it via picker) → respect null
  if (sel === null) return null
  // Field is undefined (agent schema or pre-§12 user) → flare_tier fallback
  const t = u.flare_tier
  if (t && ENCIRCLEMENT_TIERS.has(t)) return t
  return null
})

/**
 * §MARKSURFACES (2026-09-10) — THE MARK COMES OFF THE ROW, NOT OFF EVERY CALLER'S MEMORY.
 *
 * His report: *"we had a ranking display on the avatar man this got compeltly lost …
 * /leaderboard not sure if leaderboard and otherviews have it. also please in the
 * agentselector in the header of the page visible everywhere."*
 *
 * Nothing in the mark chain had broken. `EarnedMarkCollar` was correct, shipped, and in
 * every node's served dist. What was true is that the collar rendered ONLY when a caller
 * remembered to pass `trackRecord`, and exactly two surfaces did: Discovery and the agent
 * detail modal. Counted 2026-09-10, SIXTEEN others mounted `<UserAvatar :user="agent">`
 * and passed nothing — Leaderboard (the ranking page itself, 3 avatars), the header
 * AgentSwitcher (visible on every route), My Agents, Agent Details, the hover cards, the
 * flare manager. They could not show a mark however many jobs the agent had verified.
 *
 * That is §COSMETICS-ORIGIN / §FANOUTFIX exactly: widening a callee does not narrow the
 * questions its callers ask, and the fix belongs at the callee or the next surface repeats
 * it. So the component now READS the row it is already holding:
 *
 *   explicit `trackRecord` prop        (a caller that knows better still wins)
 *   -> user.track_record               (what the API ships: /agent-cards/discover,
 *                                       /developers/me/agents, /agents/by-did)
 *   -> user.trackRecord                (already-camelCased rows, e.g. the globe's)
 *   -> null                            (no verified work — renders nothing, by design)
 *
 * ⚠ `earnedMarks()` returns tier null for `jobs: 0`, and the collar renders nothing at
 * zero, so a row carrying an empty record is not a visual change. A surface whose rows
 * genuinely have no track record is byte-identical to before this existed.
 */
const effectiveTrackRecord = computed<TrackRecordCompact | null>(() => {
  if (props.trackRecord) return props.trackRecord
  const u = props.user as any
  const fromRow = u?.track_record ?? u?.trackRecord
  return fromRow && typeof fromRow === 'object' ? (fromRow as TrackRecordCompact) : null
})

// §14 (2026-05-12): which encirclement variant to render. Caller can override
// (used by the FlareManager picker for live previews of all 4 styles); else
// honor the user's stored flare_encirclement_variant; else default 'sauron'.
// §21 fix (2026-05-12): removed the KNOWN_VARIANTS whitelist gate. The
// backend (fiat_onramp.py) is the source of truth and validates every
// write against ENCIRCLEMENT_VARIANTS, so a stored variant string is
// always legitimate. A client-side whitelist here was a stale gate that
// silently filtered out new variants (glitch fell through and rendered
// as sauron). Pass through any truthy string; FlareEncirclement and
// CSS gracefully degrade for unknown values (just no special styling).
const effectiveVariant = computed<string>(() => {
  if (props.variantOverride) return props.variantOverride
  const u: any = props.user
  const stored = u?.flare_encirclement_variant
  if (stored) return stored
  return 'sauron'
})

// §28 (2026-05-13) — Broken-machine overlay (independent axis). Explicit
// override wins; else trust user.flare_encirclement_overlay; null = none.
const effectiveOverlay = computed<string | null>(() => {
  if (props.overlayOverride !== undefined) return props.overlayOverride
  const u: any = props.user
  const stored = u?.flare_encirclement_overlay
  return stored ?? null
})

const cornerTier = computed<string | null>(() => {
  const u = props.user
  if (!u) return null
  const sel = (u as any).selected_corner_flare
  // Explicit string value (developer's pick) — use it.
  if (typeof sel === 'string' && CORNER_TIERS.has(sel)) return sel
  // Explicit null (developer hid corner via picker) → respect null
  if (sel === null) return null
  // Field is undefined (agent schema) → flare_tier fallback
  const t = u.flare_tier
  if (t && CORNER_TIERS.has(t)) return t
  // Shadow chancellor agent: default to founder corner (canonical companion)
  if (t === 'shadow_chancellor') return 'founder'
  return null
})

// Corner badge ring size auto-scales with avatar size for visual balance.
const cornerBadgeSize = computed<'xs' | 'sm'>(() => {
  return props.size === 'xl' || props.size === 'lg' ? 'sm' : 'xs'
})

// ─── Display fallbacks ───────────────────────────────────────

const resolvedDisplayName = computed<string>(() => {
  const u = props.user
  return (
    props.displayName ||
    u?.display_name ||
    u?.name ||
    u?.email ||
    'User'
  )
})

const resolvedInitials = computed<string>(() => {
  if (props.initials) return props.initials.slice(0, 2).toUpperCase()
  const src = resolvedDisplayName.value
  if (!src || src === 'User') return '?'
  // Split on whitespace OR @ (so emails like "alice@x.com" become "AL" or "AS"
  // depending on the username's first letter; we drop the domain).
  const parts = src.split(/[\s@.]+/).filter(Boolean)
  return parts.map(w => w[0]?.toUpperCase()).filter(Boolean).slice(0, 2).join('') || '?'
})

const resolvedTitle = computed<string>(() => {
  const name = resolvedDisplayName.value
  const t = props.user?.flare_tier
  if (!t) return name
  const label = t[0]?.toUpperCase() + t.slice(1).replace(/_/g, ' ')
  return `${name} · ${label} backer`
})

// ─── Avatar URL fallback chain ───────────────────────────────
// Image load failure → fall back to initials. Image URL change resets the
// broken flag (e.g., user uploads a new avatar — the old broken state
// shouldn't sticky-suppress the new image).
const imgBroken = ref(false)
const effectiveAvatarUrl = computed(() =>
  imgBroken.value ? null : (props.avatarUrl || null)
)
function onAvatarError() { imgBroken.value = true }
watch(() => props.avatarUrl, () => { imgBroken.value = false })

function onClick() {
  if (!props.clickable) return
  emit('click')
}
</script>

<style scoped>
/* ── Outer container — sized to its inner ring; corner pip is absolutely
   positioned so it doesn't push siblings around. */
.ua {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  flex-shrink: 0;
  background: transparent;
  border: 0;
  padding: 0;
  vertical-align: middle;
  cursor: default;
  font: inherit;
  color: inherit;
}
.ua-clickable {
  cursor: pointer;
  border-radius: 50%;
  transition: transform 0.15s ease;
}
.ua-clickable:hover { transform: scale(1.06); }
.ua-clickable:focus-visible {
  outline: 2px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55);
  outline-offset: 2px;
}

.ua-size-xs { width: 22px; height: 22px; }
.ua-size-sm { width: 26px; height: 26px; }
.ua-size-md { width: 36px; height: 36px; }
.ua-size-lg { width: 48px; height: 48px; }
.ua-size-xl { width: 96px; height: 96px; }

/* Mobile responsive — xl is too big for narrow phones (96px on a 360px
   screen pushes profile-card layouts into overflow). Drop to lg on
   <640px so the encirclement halo still has room to bloom outside the
   bbox. md/lg/sm/xs stay as-is — they're already mobile-safe. */
@media (max-width: 639.98px) {
  .ua-size-xl { width: 72px; height: 72px; }
}
/* Tap-target safety — the entire .ua-clickable surface should be at least
   44×44 on touch devices. We don't grow the visible bbox; we extend the
   click area via a transparent ::before layer that satisfies tap-target
   metrics without affecting layout. iOS + Android both honor this. */
@media (hover: none) {
  .ua-clickable { position: relative; }
  .ua-clickable::before {
    content: '';
    position: absolute;
    inset: -6px;
    min-width: 44px;
    min-height: 44px;
    /* Keep the ::before centered when avatar is smaller than 44px */
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    border-radius: 50%;
  }
}

/* ── Plain ring (no encirclement) — themed by --nc-primary so it
   follows the active brand theme. */
.ua-ring {
  width: 100%; height: 100%;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06);
  border: 1.5px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.28);
  box-shadow:
    inset 0 0 0 1px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.04),
    0 0 8px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.ua-clickable:hover .ua-ring {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55);
  box-shadow:
    inset 0 0 0 1px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08),
    0 0 14px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.32);
}
.ua-ring--has-image {
  background: rgba(0, 0, 0, 0.35);
}

.ua-img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}

.ua-initials {
  font-family: 'IBM Plex Mono', 'Fira Code', ui-monospace, monospace;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.95);
  text-shadow: 0 0 6px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.4);
  line-height: 1;
}
.ua-size-xs .ua-initials { font-size: 9px; }
.ua-size-sm .ua-initials { font-size: 10px; }
.ua-size-md .ua-initials { font-size: 13px; }
.ua-size-lg .ua-initials { font-size: 17px; }
.ua-size-xl .ua-initials { font-size: 32px; }

/* ── Corner badge — bottom-right pip. Position offsets hand-tuned per
   size so the pip kisses the avatar edge without overlapping. */
/* §POCKETDISC — standalone collar on the plain path: the .ua root is the
   sized square, and the collar is inset:0 absolute, so it hugs the ring. */
.ua-collar { pointer-events: none; }
.ua-corner {
  position: absolute;
  bottom: -3px;
  right: -3px;
  pointer-events: none;
  z-index: 4;
}
.ua-size-xs .ua-corner { bottom: -2px; right: -2px; }
.ua-size-sm .ua-corner { bottom: -2px; right: -2px; }
.ua-size-md .ua-corner { bottom: -3px; right: -3px; }
.ua-size-lg .ua-corner { bottom: -3px; right: -3px; }
.ua-size-xl .ua-corner { bottom: -2px; right: -2px; }
</style>
