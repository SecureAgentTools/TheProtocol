<template>
  <!--
    FlareBadge — PB-1 backer cosmetic (2026-05-09).

    Single source of truth for flare visuals across the cluster. Renders the
    earned tier badge given a tier name (sentinel | architect | founder) plus
    an optional grant date for the tooltip.

    Sizes:  xs | sm | md | lg
    Themes: cyan (Sentinel) · cyan-emerald (Architect) · gold (Founder)

    Animations are scoped to the badge element + respect prefers-reduced-motion.
    Founder tier gets a subtle radial pulse + sparkle; Architect rotates on
    hover; Sentinel is clean static (the "first chapter" feel).

    Usage:
      <FlareBadge :tier="user.flare_tier" :granted-at="user.flare_granted_at" />
      <FlareBadge :tier="agent.flare_tier" size="sm" :show-label="false" />
  -->
  <!-- 2026-05-11 §12: shadow_chancellor is ENCIRCLEMENT-ONLY now — it renders
       around an avatar via FlareEncirclement.vue, never as a corner badge.
       Suppress here so call-sites that render `<FlareBadge :tier="dev.flare_tier"`
       don't double-paint when the dev's highest tier is shadow_chancellor. -->
  <span
    v-if="tier && CONFIG[tier] && tier !== 'shadow_chancellor'"
    class="flare-badge"
    :class="[
      `flare-${tier}`,
      `flare-size-${size}`,
      { 'flare-with-label': showLabel && size !== 'xs' },
      { 'flare-customized': hasCustomization },
    ]"
    role="img"
    :title="tooltip"
    :aria-label="tooltip"
    :style="customStyle"
  >
    <span class="flare-ring">
      <!-- Custom logo overlays the icon at md/lg sizes when set. -->
      <img
        v-if="effectiveLogoUrl && (size === 'md' || size === 'lg')"
        :src="effectiveLogoUrl"
        class="flare-logo"
        alt=""
        @error="onLogoError"
      />
      <!-- §20 (2026-05-13): admin corner badge variant. When `cornerVariant`
           is set (admin-only, NULL otherwise), swap the default tier icon for
           an inline SVG design. Tier color palette is preserved (rocket on
           commander = purple-rocket; rocket on operator = gold-rocket). -->
      <svg v-else-if="cornerVariant === 'rocket'" class="flare-icon flare-icon--svg" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <!-- Rocket body -->
        <path d="M12 2 C8 4 7 9 7 14 L7 18 L10 17 L12 14 L14 17 L17 18 L17 14 C17 9 16 4 12 2 Z" fill="currentColor" stroke="rgba(0,0,0,0.4)" stroke-width="0.5"/>
        <!-- Window porthole -->
        <circle cx="12" cy="9" r="1.8" fill="rgba(0,0,0,0.5)" stroke="currentColor" stroke-width="0.8"/>
        <circle cx="11.5" cy="8.5" r="0.6" fill="rgba(255,255,255,0.7)"/>
        <!-- Fins -->
        <path d="M7 14 L4 20 L7 18 Z" fill="currentColor" opacity="0.85"/>
        <path d="M17 14 L20 20 L17 18 Z" fill="currentColor" opacity="0.85"/>
        <!-- Flame trail -->
        <path d="M10 17 L12 22 L14 17 L13 19 L12 21 L11 19 Z" fill="rgba(252,165,165,0.95)"/>
        <path d="M11 17 L12 21 L13 17 Z" fill="rgba(254,243,199,0.95)"/>
      </svg>
      <svg v-else-if="cornerVariant === 'crown'" class="flare-icon flare-icon--svg" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <!-- Crown band -->
        <path d="M3 18 L5 8 L9 14 L12 6 L15 14 L19 8 L21 18 Z" fill="currentColor" stroke="rgba(0,0,0,0.45)" stroke-width="0.6"/>
        <!-- Base -->
        <rect x="3" y="18" width="18" height="2.5" rx="0.5" fill="currentColor" stroke="rgba(0,0,0,0.45)" stroke-width="0.4"/>
        <!-- Jewels -->
        <circle cx="5" cy="8" r="1.4" fill="rgba(252,211,77,1)" stroke="rgba(0,0,0,0.3)" stroke-width="0.3"/>
        <circle cx="12" cy="6" r="1.6" fill="rgba(244,114,182,1)" stroke="rgba(0,0,0,0.3)" stroke-width="0.3"/>
        <circle cx="19" cy="8" r="1.4" fill="rgba(34,211,238,1)" stroke="rgba(0,0,0,0.3)" stroke-width="0.3"/>
        <!-- Highlight on center jewel -->
        <circle cx="11.5" cy="5.5" r="0.5" fill="rgba(255,255,255,0.85)"/>
      </svg>
      <svg v-else-if="cornerVariant === 'vault'" class="flare-icon flare-icon--svg" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <!-- Vault door square -->
        <rect x="3" y="4" width="18" height="16" rx="1.5" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.6"/>
        <!-- Outer ring -->
        <circle cx="12" cy="12" r="6" fill="rgba(0,0,0,0.32)" stroke="rgba(0,0,0,0.6)" stroke-width="0.5"/>
        <!-- Wheel -->
        <circle cx="12" cy="12" r="4" fill="currentColor" stroke="rgba(0,0,0,0.55)" stroke-width="0.5"/>
        <!-- 8 spokes radiating from center -->
        <g stroke="rgba(0,0,0,0.55)" stroke-width="1" stroke-linecap="round">
          <line x1="12" y1="8" x2="12" y2="10"/>
          <line x1="12" y1="14" x2="12" y2="16"/>
          <line x1="8" y1="12" x2="10" y2="12"/>
          <line x1="14" y1="12" x2="16" y2="12"/>
          <line x1="9.2" y1="9.2" x2="10.6" y2="10.6"/>
          <line x1="13.4" y1="13.4" x2="14.8" y2="14.8"/>
          <line x1="14.8" y1="9.2" x2="13.4" y2="10.6"/>
          <line x1="10.6" y1="13.4" x2="9.2" y2="14.8"/>
        </g>
        <!-- Center bolt -->
        <circle cx="12" cy="12" r="1" fill="rgba(0,0,0,0.65)"/>
      </svg>
      <svg v-else-if="cornerVariant === 'gavel'" class="flare-icon flare-icon--svg" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <!-- Hammer head -->
        <rect x="3" y="6" width="9" height="5" rx="0.6" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.5" transform="rotate(-30 7.5 8.5)"/>
        <!-- Handle -->
        <line x1="9" y1="11" x2="18" y2="18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>
        <line x1="9" y1="11" x2="18" y2="18" stroke="rgba(0,0,0,0.55)" stroke-width="0.6" stroke-linecap="round"/>
        <!-- Striking block (judge bench) -->
        <rect x="2" y="20" width="20" height="2.5" rx="0.4" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.5"/>
        <!-- Impact sparks -->
        <line x1="7" y1="17" x2="6" y2="19" stroke="rgba(252,211,77,0.95)" stroke-width="0.8" stroke-linecap="round"/>
        <line x1="9" y1="19" x2="9" y2="21" stroke="rgba(252,211,77,0.95)" stroke-width="0.8" stroke-linecap="round"/>
      </svg>
      <svg v-else-if="cornerVariant === 'atom'" class="flare-icon flare-icon--svg" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <!-- 3 orbital ellipses rotated 60° each -->
        <ellipse cx="12" cy="12" rx="10" ry="3.5" fill="none" stroke="currentColor" stroke-width="1.4"/>
        <ellipse cx="12" cy="12" rx="10" ry="3.5" fill="none" stroke="currentColor" stroke-width="1.4" transform="rotate(60 12 12)"/>
        <ellipse cx="12" cy="12" rx="10" ry="3.5" fill="none" stroke="currentColor" stroke-width="1.4" transform="rotate(-60 12 12)"/>
        <!-- Nucleus -->
        <circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.4"/>
        <!-- Electron dots on the orbits -->
        <circle cx="22" cy="12" r="1.2" fill="rgba(254,240,138,1)" stroke="rgba(0,0,0,0.3)" stroke-width="0.3"/>
        <circle cx="7" cy="3.5" r="1.2" fill="rgba(251,207,232,1)" stroke="rgba(0,0,0,0.3)" stroke-width="0.3"/>
        <circle cx="7" cy="20.5" r="1.2" fill="rgba(125,211,252,1)" stroke="rgba(0,0,0,0.3)" stroke-width="0.3"/>
      </svg>
      <svg v-else-if="cornerVariant === 'network'" class="flare-icon flare-icon--svg" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <!-- 4 nodes connected in a diamond -->
        <line x1="12" y1="5" x2="5" y2="12" stroke="currentColor" stroke-width="1.4"/>
        <line x1="12" y1="5" x2="19" y2="12" stroke="currentColor" stroke-width="1.4"/>
        <line x1="5" y1="12" x2="12" y2="19" stroke="currentColor" stroke-width="1.4"/>
        <line x1="19" y1="12" x2="12" y2="19" stroke="currentColor" stroke-width="1.4"/>
        <!-- Center node + spokes -->
        <line x1="12" y1="5" x2="12" y2="19" stroke="currentColor" stroke-width="1" opacity="0.6"/>
        <line x1="5" y1="12" x2="19" y2="12" stroke="currentColor" stroke-width="1" opacity="0.6"/>
        <!-- Nodes -->
        <circle cx="12" cy="5" r="2.2" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.5"/>
        <circle cx="5" cy="12" r="2.2" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.5"/>
        <circle cx="19" cy="12" r="2.2" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.5"/>
        <circle cx="12" cy="19" r="2.2" fill="currentColor" stroke="rgba(0,0,0,0.5)" stroke-width="0.5"/>
        <circle cx="12" cy="12" r="1.6" fill="rgba(255,255,255,0.55)"/>
      </svg>
      <Icon v-else :name="CONFIG[tier].icon" class="flare-icon" />
    </span>
    <span v-if="showLabel && size !== 'xs'" class="flare-label">
      {{ displayName || t(`flareTiers.${tier}`) }}
    </span>
  </span>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

type FlareTier = 'sentinel' | 'architect' | 'founder' | 'shadow_chancellor' | 'operator' | 'commander'

const props = withDefaults(defineProps<{
  tier?: FlareTier | string | null
  grantedAt?: string | null
  size?: 'xs' | 'sm' | 'md' | 'lg'
  showLabel?: boolean
  /** PB-1 hardening (2026-05-09): bespoke flare presentation. */
  displayName?: string | null
  tagline?: string | null
  logoUrl?: string | null
  cause?: string | null
  accentColor?: string | null
  flareId?: string | null
  /** §20 (2026-05-13): admin-only corner badge variant override.
   *  rocket | crown | vault | gavel | atom | network. NULL = default tier icon. */
  cornerVariant?:
    | 'rocket' | 'crown' | 'vault' | 'gavel' | 'atom' | 'network'
    | null
}>(), {
  tier: null,
  grantedAt: null,
  size: 'sm',
  showLabel: true,
  displayName: null,
  tagline: null,
  logoUrl: null,
  cause: null,
  accentColor: null,
  flareId: null,
  cornerVariant: null,
})

// Tier → display label + Icon name. Synced with backend
// (`routers/fiat_onramp.py:_TIER_TO_FLARE` + `ALL_FLARE_TIERS`) + frontend
// BuyAVT presentation. operator + commander are admin-only (no fiat path).
const CONFIG: Record<FlareTier, { label: string; icon: string }> = {
  sentinel:          { label: 'Sentinel',           icon: 'mdi:shield-half-full' },
  architect:         { label: 'Architect',          icon: 'mdi:compass-outline' },
  founder:           { label: 'Founder',            icon: 'mdi:diamond-stone' },
  // Shadow Chancellor — cumulative ≥ €500. Hidden from public tier-pitch
  // surfaces. Black-glue avatar encirclement, locked palette, no color
  // customization. Backend grants automatically; users find out by getting it.
  shadow_chancellor: { label: 'Shadow Chancellor',  icon: 'mdi:incognito' },
  operator:          { label: 'Operator',           icon: 'mdi:hexagon-multiple-outline' },
  commander:         { label: 'Commander',          icon: 'mdi:crown' },
}

// Tiers that DO NOT honor the buyer-supplied accentColor. Their visual is
// fixed by design — customization would dilute the rarity. Frontend hard-locks
// these here; FlareManager also disables the picker for these tiers.
const FIXED_PALETTE_TIERS = new Set<FlareTier>(['shadow_chancellor', 'commander'])

const hasCustomization = computed(() =>
  !!(props.displayName || props.tagline || props.logoUrl || props.cause || props.accentColor),
)

// If the buyer set an accent_color, override the ring's CSS custom-property.
// Tier base palette stays as fallback — the override only changes the accent
// hue without breaking the founder-pulse animation or sentinel tint.
//
// FIXED_PALETTE_TIERS (shadow_chancellor, commander) ignore accentColor —
// the visual is by-design and customization would dilute the rarity.
const customStyle = computed(() => {
  if (!props.accentColor) return {}
  const t = props.tier as FlareTier | null
  if (t && FIXED_PALETTE_TIERS.has(t)) return {}
  return {
    '--flare-custom-accent': props.accentColor,
  } as Record<string, string>
})

// Logo can fail to load (broken URL, hotlink protection). Fall back to icon.
// Renamed `logoUrl` → `effectiveLogoUrl` so it doesn't shadow the prop of the
// same name in the template-resolution scope (was triggering a Vue compiler
// recursion + RangeError on render).
const logoBroken = ref(false)
function onLogoError() { logoBroken.value = true }
const effectiveLogoUrl = computed(() => (logoBroken.value ? null : props.logoUrl))

const tooltip = computed(() => {
  const t = props.tier as FlareTier | null
  if (!t || !CONFIG[t]) return ''
  const tierLabel = CONFIG[t].label
  const parts: string[] = []
  // Custom display name takes precedence; tier still appears as suffix.
  if (props.displayName) {
    parts.push(`${props.displayName} (${tierLabel} backer)`)
  } else {
    parts.push(`${tierLabel} backer`)
  }
  if (props.tagline) parts.push(`— ${props.tagline}`)
  if (props.cause) parts.push(`Cause: ${props.cause}`)
  if (props.grantedAt) {
    try {
      const d = new Date(props.grantedAt)
      parts.push(`since ${d.toLocaleDateString(appLocale(), {
        year: 'numeric', month: 'short', day: 'numeric',
      })}`)
    } catch { /* ignore */ }
  }
  return parts.join(' ')
})
</script>

<style scoped>
.flare-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  vertical-align: middle;
  position: relative;
  flex-shrink: 0;
  user-select: none;
}

.flare-ring {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  position: relative;
  flex-shrink: 0;
  overflow: visible;
  transition: transform 250ms cubic-bezier(.2,.7,.2,1);
}

.flare-icon {
  display: block;
  position: relative;
  z-index: 2;
}

/* §20 (2026-05-13): admin SVG corner badge variants. Sizes scale to fill
   the ring; color follows currentColor (= tier base color) so rocket-on-
   commander = purple-rocket, rocket-on-operator = gold-rocket, etc. */
.flare-icon--svg {
  width: 78%;
  height: 78%;
  color: currentColor;
}
.flare-size-xs .flare-icon--svg { width: 72%; height: 72%; }
.flare-size-sm .flare-icon--svg { width: 78%; height: 78%; }
.flare-size-md .flare-icon--svg { width: 80%; height: 80%; }
.flare-size-lg .flare-icon--svg { width: 82%; height: 82%; }

/* Custom logo: object-fit: cover keeps shape circular like the ring. */
.flare-logo {
  display: block;
  position: relative;
  z-index: 2;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}

/* Custom-accent override: the buyer-supplied accent color recolors the ring
   without breaking the tier-base shadow/animation patterns. */
.flare-customized .flare-ring {
  border-color: var(--flare-custom-accent, currentColor);
}
.flare-customized .flare-icon { color: var(--flare-custom-accent, currentColor); }

.flare-label {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.72em;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  font-weight: 600;
  white-space: nowrap;
}

/* ── Size scales ───────────────────────────────────────────── */

.flare-size-xs .flare-ring { width: 14px; height: 14px; }
.flare-size-xs .flare-icon { font-size: 10px; }

.flare-size-sm .flare-ring { width: 22px; height: 22px; }
.flare-size-sm .flare-icon { font-size: 13px; }
.flare-size-sm .flare-label { font-size: 10px; }

.flare-size-md .flare-ring { width: 32px; height: 32px; }
.flare-size-md .flare-icon { font-size: 18px; }
.flare-size-md .flare-label { font-size: 11px; }

.flare-size-lg .flare-ring { width: 48px; height: 48px; }
.flare-size-lg .flare-icon { font-size: 26px; }
.flare-size-lg .flare-label { font-size: 13px; letter-spacing: 0.12em; }

/* ── Sentinel — themed (cyan in Neural / red in Sovereign / custom) ─ */
/* Uses --nc-primary-rgb so the badge follows the active brand theme. */

.flare-sentinel .flare-ring {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  border: 1.5px solid var(--nc-primary, #00d2d2);
  box-shadow:
    0 0 0 1px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.30),
    inset 0 0 8px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20);
}
.flare-sentinel .flare-icon { color: var(--nc-primary, #00d2d2); }
.flare-sentinel .flare-label {
  color: var(--nc-primary, #00d2d2);
}

/* ── Architect — themed primary + emerald accent ─────────────── */

.flare-architect .flare-ring {
  background: linear-gradient(135deg,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.14),
    rgba(16, 185, 129, 0.18));
  border: 1.5px solid rgba(16, 185, 129, 0.55);
  box-shadow:
    0 0 0 1px rgba(16, 185, 129, 0.30),
    inset 0 0 10px rgba(16, 185, 129, 0.18);
}
.flare-architect .flare-icon { color: rgb(52, 211, 153); }
.flare-architect .flare-label { color: rgb(52, 211, 153); }
.flare-architect:hover .flare-ring { transform: rotate(15deg) scale(1.04); }

/* ── Founder (gold/amber, premium with animation) ───────────── */

.flare-founder .flare-ring {
  background:
    radial-gradient(circle at 35% 30%, rgba(253, 224, 71, 0.40), rgba(245, 158, 11, 0.18) 60%);
  border: 1.5px solid rgb(245, 158, 11);
  box-shadow:
    0 0 0 1px rgba(245, 158, 11, 0.45),
    0 0 16px -2px rgba(245, 158, 11, 0.55),
    inset 0 0 10px rgba(253, 224, 71, 0.30);
  animation: flare-founder-pulse 3.4s ease-in-out infinite;
}
.flare-founder .flare-icon {
  color: rgb(253, 224, 71);
  filter: drop-shadow(0 0 3px rgba(245, 158, 11, 0.7));
  animation: flare-founder-rotate 14s linear infinite;
}
.flare-founder .flare-label {
  color: rgb(252, 211, 77);
  text-shadow: 0 0 8px rgba(245, 158, 11, 0.4);
}

/* Sparkle dot — purely decorative, sits at top-right of the ring */
.flare-founder .flare-ring::after {
  content: '';
  position: absolute;
  top: -1px;
  right: -1px;
  width: 4px;
  height: 4px;
  background: rgb(254, 240, 138);
  border-radius: 50%;
  box-shadow: 0 0 6px 1px rgba(253, 224, 71, 0.9);
  animation: flare-founder-sparkle 2.8s ease-in-out infinite;
}

@keyframes flare-founder-pulse {
  0%, 100% {
    box-shadow:
      0 0 0 1px rgba(245, 158, 11, 0.45),
      0 0 16px -2px rgba(245, 158, 11, 0.55),
      inset 0 0 10px rgba(253, 224, 71, 0.30);
  }
  50% {
    box-shadow:
      0 0 0 2px rgba(245, 158, 11, 0.55),
      0 0 26px -4px rgba(245, 158, 11, 0.85),
      inset 0 0 14px rgba(253, 224, 71, 0.45);
  }
}
@keyframes flare-founder-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes flare-founder-sparkle {
  0%, 100% { opacity: 0.20; transform: scale(0.85); }
  50%      { opacity: 1.0;  transform: scale(1.4); }
}

/* ── Shadow Chancellor — cumulative ≥ €500, hidden tier ─────── */
/* Black-glue avatar encirclement. Multiple gooey blobs orbit the ring
   in slow motion. Deep violet under-glow leaks through. Animation is
   ominous-but-elegant: not a celebration like Founder, more a presence.
   Color is NOT customizable — fixed palette is the entire point. */

.flare-shadow_chancellor .flare-ring {
  background:
    radial-gradient(circle at 50% 50%, rgba(15, 5, 25, 0.95) 0%, rgba(8, 2, 14, 1) 70%),
    radial-gradient(circle at 30% 30%, rgba(88, 28, 135, 0.50), transparent 60%),
    radial-gradient(circle at 70% 70%, rgba(67, 20, 110, 0.55), transparent 65%);
  border: 1.5px solid rgba(15, 5, 25, 0.95);
  box-shadow:
    0 0 0 1px rgba(88, 28, 135, 0.45),
    0 0 18px -1px rgba(67, 20, 110, 0.65),
    inset 0 0 14px rgba(8, 2, 14, 0.7);
}
.flare-shadow_chancellor .flare-icon {
  color: rgb(196, 181, 253);
  filter: drop-shadow(0 0 4px rgba(88, 28, 135, 0.85));
  position: relative; z-index: 3;
}
.flare-shadow_chancellor .flare-label {
  color: rgb(196, 181, 253);
  text-shadow: 0 0 8px rgba(88, 28, 135, 0.55);
}

/* The black-glue encirclement — three gooey blobs orbiting the ring.
   Implemented as a ::before pseudo-element rotating slowly with multiple
   radial gradients positioned around the ring perimeter. The blobs feel
   viscous because of the soft alpha falloff + slight blur via box-shadow.
   Suppressed at xs/sm sizes to keep the badge legible at agent-card scale. */
.flare-size-md.flare-shadow_chancellor .flare-ring::before,
.flare-size-lg.flare-shadow_chancellor .flare-ring::before {
  content: '';
  position: absolute;
  inset: -8px;
  border-radius: 50%;
  background:
    radial-gradient(ellipse 14px 10px at 50% 0%, rgba(8, 2, 14, 0.95) 0%, rgba(8, 2, 14, 0.6) 40%, transparent 75%),
    radial-gradient(ellipse 12px 9px at 96% 38%, rgba(8, 2, 14, 0.92) 0%, rgba(8, 2, 14, 0.55) 45%, transparent 78%),
    radial-gradient(ellipse 16px 11px at 70% 96%, rgba(8, 2, 14, 0.95) 0%, rgba(8, 2, 14, 0.6) 40%, transparent 75%),
    radial-gradient(ellipse 13px 9px at 18% 78%, rgba(8, 2, 14, 0.93) 0%, rgba(8, 2, 14, 0.55) 45%, transparent 78%);
  filter: blur(0.4px);
  animation: flare-shadow-rotate 22s linear infinite;
  pointer-events: none;
  z-index: 1;
}

/* A second slower-rotating layer of blobs, opposite direction, slightly
   inset — gives the encirclement depth without DOM additions. */
.flare-size-md.flare-shadow_chancellor .flare-ring::after,
.flare-size-lg.flare-shadow_chancellor .flare-ring::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  background:
    radial-gradient(ellipse 9px 7px at 28% 6%, rgba(8, 2, 14, 0.7) 0%, transparent 70%),
    radial-gradient(ellipse 10px 7px at 80% 18%, rgba(8, 2, 14, 0.65) 0%, transparent 72%),
    radial-gradient(ellipse 9px 7px at 92% 70%, rgba(8, 2, 14, 0.7) 0%, transparent 70%),
    radial-gradient(ellipse 9px 7px at 14% 50%, rgba(8, 2, 14, 0.65) 0%, transparent 72%);
  animation: flare-shadow-counter-rotate 35s linear infinite;
  pointer-events: none;
  z-index: 0;
}

.flare-shadow_chancellor:hover .flare-ring { transform: scale(1.04); }

@keyframes flare-shadow-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes flare-shadow-counter-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(-360deg); }
}

/* ── Operator — admin-granted: silver/steel + cyan accent ───── */
/* Federation operators / sub-admins. Distinguished from payment tiers
   by a metallic silver finish + subtle hex-grid border feel. */

.flare-operator .flare-ring {
  background:
    linear-gradient(135deg, rgba(203, 213, 225, 0.20), rgba(71, 85, 105, 0.30) 70%);
  border: 1.5px solid rgba(203, 213, 225, 0.65);
  box-shadow:
    0 0 0 1px rgba(148, 163, 184, 0.45),
    0 0 12px -2px rgba(103, 232, 249, 0.30),
    inset 0 0 10px rgba(148, 163, 184, 0.22);
}
.flare-operator .flare-icon {
  color: rgb(226, 232, 240);
  filter: drop-shadow(0 0 2px rgba(103, 232, 249, 0.55));
}
.flare-operator .flare-label {
  color: rgb(186, 230, 253);
  text-shadow: 0 0 6px rgba(103, 232, 249, 0.30);
}
.flare-operator:hover .flare-ring { transform: scale(1.05); }
/* Subtle rotating outer hex tick — drawn via dual conic gradient
   so we don't need extra DOM. Suppressed at xs/sm to stay readable. */
.flare-size-md.flare-operator .flare-ring::after,
.flare-size-lg.flare-operator .flare-ring::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  background:
    conic-gradient(from 0deg,
      transparent 0%,
      rgba(103, 232, 249, 0.55) 8%,
      transparent 16%,
      rgba(103, 232, 249, 0.55) 33%,
      transparent 41%,
      rgba(103, 232, 249, 0.55) 58%,
      transparent 66%,
      rgba(103, 232, 249, 0.55) 83%,
      transparent 91%);
  -webkit-mask: radial-gradient(circle, transparent 60%, black 62%);
          mask: radial-gradient(circle, transparent 60%, black 62%);
  animation: flare-operator-rotate 18s linear infinite;
  pointer-events: none;
  z-index: 1;
}
@keyframes flare-operator-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* ── Commander — admin-granted top tier: crimson + gold royal ─── */
/* The Commander's flare. Always-on. Outranks every other tier. */

.flare-commander .flare-ring {
  background:
    radial-gradient(circle at 30% 25%, rgba(252, 211, 77, 0.55), transparent 50%),
    radial-gradient(circle at 70% 75%, rgba(220, 38, 38, 0.65), transparent 60%),
    linear-gradient(135deg, rgba(127, 29, 29, 0.40), rgba(245, 158, 11, 0.25) 100%);
  border: 1.5px solid rgb(252, 211, 77);
  box-shadow:
    0 0 0 1px rgba(220, 38, 38, 0.55),
    0 0 18px -2px rgba(252, 211, 77, 0.70),
    inset 0 0 14px rgba(252, 211, 77, 0.32);
  animation: flare-commander-pulse 3.0s ease-in-out infinite;
}
.flare-commander .flare-icon {
  color: rgb(254, 240, 138);
  filter: drop-shadow(0 0 4px rgba(252, 211, 77, 0.85));
}
.flare-commander .flare-label {
  color: rgb(254, 240, 138);
  text-shadow: 0 0 10px rgba(252, 211, 77, 0.55);
  font-weight: 700;
}
/* Outer crown spikes (pure CSS — eight radial nicks rotated). */
.flare-size-md.flare-commander .flare-ring::before,
.flare-size-lg.flare-commander .flare-ring::before {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background:
    conic-gradient(from 0deg,
      rgb(252, 211, 77) 0deg 6deg,
      transparent 6deg 45deg,
      rgb(220, 38, 38) 45deg 51deg,
      transparent 51deg 90deg,
      rgb(252, 211, 77) 90deg 96deg,
      transparent 96deg 135deg,
      rgb(220, 38, 38) 135deg 141deg,
      transparent 141deg 180deg,
      rgb(252, 211, 77) 180deg 186deg,
      transparent 186deg 225deg,
      rgb(220, 38, 38) 225deg 231deg,
      transparent 231deg 270deg,
      rgb(252, 211, 77) 270deg 276deg,
      transparent 276deg 315deg,
      rgb(220, 38, 38) 315deg 321deg,
      transparent 321deg 360deg);
  -webkit-mask: radial-gradient(circle, transparent 65%, black 70%);
          mask: radial-gradient(circle, transparent 65%, black 70%);
  animation: flare-commander-spin 22s linear infinite;
  pointer-events: none;
  opacity: 0.65;
}
.flare-commander .flare-ring::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(252, 211, 77, 0.45) 0%, transparent 60%);
  pointer-events: none;
  animation: flare-commander-glow 2.4s ease-in-out infinite alternate;
  z-index: 1;
}
@keyframes flare-commander-pulse {
  0%, 100% {
    box-shadow:
      0 0 0 1px rgba(220, 38, 38, 0.55),
      0 0 18px -2px rgba(252, 211, 77, 0.70),
      inset 0 0 14px rgba(252, 211, 77, 0.32);
  }
  50% {
    box-shadow:
      0 0 0 2px rgba(252, 211, 77, 0.65),
      0 0 30px -4px rgba(252, 211, 77, 1),
      inset 0 0 18px rgba(252, 211, 77, 0.50);
  }
}
@keyframes flare-commander-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes flare-commander-glow {
  from { opacity: 0.35; }
  to   { opacity: 0.75; }
}

/* ── Reduced motion: kill all animations ────────────────────── */

@media (prefers-reduced-motion: reduce) {
  .flare-founder .flare-ring,
  .flare-founder .flare-icon,
  .flare-founder .flare-ring::after,
  .flare-architect:hover .flare-ring,
  .flare-operator:hover .flare-ring,
  .flare-operator .flare-ring::after,
  .flare-commander .flare-ring,
  .flare-commander .flare-ring::before,
  .flare-commander .flare-ring::after {
    animation: none !important;
    transform: none !important;
  }
}
</style>
