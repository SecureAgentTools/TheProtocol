<script setup lang="ts">
// Federation Network — peer orb SVG primitive (Pass 3 — 2026-05-21).
// Replaces the flat fed-svg-node circle with a layered orb identity that
// honors Registry Card v0.3 visual fields (orb_color, orb_glow_color,
// orb_pulse_speed_hz, halo_enabled), drift dashed-ring, and bundle-freshness
// outer ring. Tier glyph at center matches existing fed-svg-node-icon style.
//
// Mount: this component is rendered INSIDE the existing
//   <g v-for="node in graphNodes" :transform="translate(x,y)"> wrapper in
// Federation.vue, OR standalone (inline=true) for the mobile peer list (Pass 6).
//
// Layering (outer → inner):
//   1. Drift dashed ring     (radius + 8) — only when has_drift
//   2. Bundle freshness ring (radius + 5) — only when bundle_freshness exists
//   3. Halo                  (radius + 3) — orb_glow_color (with optional pulse)
//   4. Local pulse halo      (radius + 6) — overrides #3 for is_local (existing fed-pulse keyframe vibe)
//   5. Core                  (radius)     — orb_color from v0.3 card, fallback to tier color
//   6. Tier glyph            (center)     — ◆ ● ○ ☁ ★ when radius >= 14
//   7. Local marker          (above)      — bright dot indicating "you are here"
import { computed } from 'vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'

interface PeerVisualLite {
  orb_color?: string | null
  orb_glow_color?: string | null
  orb_pulse_speed_hz?: number | null
  orb_size_px?: number | null
  halo_enabled?: boolean | null
  sovereign_variant?: string | null
}
interface PeerLite {
  peer_type?: string
  has_drift?: boolean
  visual?: PeerVisualLite | null
  bundle_freshness?: {
    refresh_overdue?: boolean
    refresh_critical?: boolean
    error?: string | null
    age_seconds?: number | null
  } | null
}

const props = withDefaults(defineProps<{
  peer?: PeerLite | null
  radius: number
  isLocal?: boolean
  /** When true, wrap output in a standalone <svg> sized for inline display (mobile peer rows). */
  inline?: boolean
  /** When `inline`, override the default size. */
  inlineSize?: number
  /** Optional tier override (used for nodes without a peer object, e.g. orphan registries). */
  tier?: string | null
  /** Optional fallback name for the data-tier attribute. */
  tierFallback?: string
}>(), {
  peer: null,
  isLocal: false,
  inline: false,
  inlineSize: 44,
  tier: null,
  tierFallback: 'unknown',
})

const TIER_FALLBACK_COLOR: Record<string, string> = {
  frame: '#a855f7',           // --fed-frame
  direct_peer: '#00d2d2',     // --fed-direct
  discovered: '#f59e0b',      // --fed-discovered
  cloud_operator: '#22c55e',  // --fed-cloud
  local: '#e8eaed',           // --nc-text-primary
  unknown: '#94a3b8',         // --nc-text-muted
}

const effectiveTier = computed(() => props.tier || props.peer?.peer_type || props.tierFallback)
const tierColor = computed(() => TIER_FALLBACK_COLOR[effectiveTier.value] || TIER_FALLBACK_COLOR.unknown)
const orbColor = computed(() => props.peer?.visual?.orb_color || tierColor.value)
const orbGlow = computed(() =>
  props.peer?.visual?.orb_glow_color
  || props.peer?.visual?.orb_color
  || tierColor.value
)
const haloEnabled = computed(() => props.peer?.visual?.halo_enabled !== false)
const pulseHz = computed(() => {
  const hz = props.peer?.visual?.orb_pulse_speed_hz
  return typeof hz === 'number' && hz > 0 ? hz : null
})
// CSS `animation-duration` from Hz. Cycle period = 1/Hz seconds.
const pulseDuration = computed(() => pulseHz.value ? `${(1 / pulseHz.value).toFixed(2)}s` : null)
const hasDrift = computed(() => !!props.peer?.has_drift)
const bundleFreshnessState = computed(() => {
  const fr = props.peer?.bundle_freshness
  if (!fr) return null
  if (fr.error) return 'unknown'
  if (fr.refresh_critical) return 'critical'
  if (fr.refresh_overdue) return 'overdue'
  return 'fresh'
})

// Tier glyph (matches existing fed-svg-node-icon)
const tierGlyph = computed(() => {
  switch (effectiveTier.value) {
    case 'frame': return '◆'
    case 'direct_peer': return '●'
    case 'discovered': return '○'
    case 'cloud_operator': return '☁'
    case 'local': return '★'
    default: return '?'
  }
})

const showGlyph = computed(() => props.radius >= 14)

// ── Pass 3.5: FlareEncirclement integration ────────────────────────────
// Render FlareEncirclement inside SVG via <foreignObject> when peer has a
// flare_encirclement_variant OR sovereign_variant set. Replaces the core
// circle + glyph for visual identity; halo + freshness + drift rings stay.
const hasFlare = computed(() => !!(
  props.peer?.visual?.flare_encirclement_variant
  || props.peer?.visual?.sovereign_variant
))
// §pass61.3 (2026-05-21) — when BOTH cosmetic flare AND sovereign rank pin
// are set (e.g., Frame A: sovereign_variant=genesis-flame + flare=blackhole),
// PREFER the cosmetic flare. sovereign_variant is the rank-pin (immutable
// identity); flare_encirclement_variant is what the operator equipped to
// WEAR. The wearable wins. Tier follows what we're actually rendering.
const flareVariantProp = computed(() =>
  props.peer?.visual?.flare_encirclement_variant   // cosmetic wins
  || props.peer?.visual?.sovereign_variant         // fallback to rank pin
  || null
)
const flareTierProp = computed<'sovereign' | 'shadow_chancellor'>(() => {
  // Sovereign tier only when we're rendering the sovereign_variant
  // (no cosmetic flare equipped).
  if (!props.peer?.visual?.flare_encirclement_variant && props.peer?.visual?.sovereign_variant) {
    return 'sovereign'
  }
  return 'shadow_chancellor'
})
const flareOverlayProp = computed(() =>
  (props.peer?.visual as PeerVisualLite & { flare_encirclement_overlay?: string | null })
    ?.flare_encirclement_overlay || null
)
// Pick size based on the node's render radius. FlareEncirclement sizes:
// xs=22px sm=36px md=48px lg=72px xl=96px. Cap at sm to avoid dominating the canvas.
const flareSize = computed<'xs' | 'sm' | 'md'>(() => {
  if (props.radius >= 26) return 'md'
  if (props.radius >= 18) return 'sm'
  return 'xs'
})
const flareSizePx = computed(() => ({ xs: 22, sm: 36, md: 48 }[flareSize.value] || 22))
// Render flare for any node with radius >= 9. Hop 4-5 leaves have radius=11
// — xs flare (22px) fits cleanly over an 11-radius (22px diameter) orb.
// Threshold was 12 in §pass61 which silently dropped flares on chain-leaf peers
// (op-singapore + op-sydney on prod Frame A) — §pass61.2 fix 2026-05-21.
const renderFlare = computed(() => hasFlare.value && props.radius >= 9)

// Inline-mode wrapper dims
const inlineDim = computed(() => props.inlineSize || 44)
const inlineCenter = computed(() => Math.floor(inlineDim.value / 2))
</script>

<template>
  <!-- Pass 3: renders inside parent <g transform="translate(x,y)"> in Federation.vue
       at (0,0). Pass 6 will add an `inline` mode that wraps in a standalone <svg>. -->
  <g class="peer-orb-group" :data-tier="effectiveTier" :data-orb-color="orbColor">
    <!-- §pass61.4 (2026-05-21) — invisible hit target. Without this, peers
         with a flare have NO solid shape inside the <g> at the hover area:
         halo is hidden (§pass61.3), core+glyph are hidden when flare renders,
         and foreignObject has pointer-events: none. The parent <g>'s
         @mouseenter would never fire because no inner element captures the
         mouse event. A transparent fill with pointer-events="all" catches
         events without obscuring the visual. Always present, sized to cover
         the entire orb area including halo zone. -->
    <circle
      :r="radius + 8"
      fill="transparent"
      pointer-events="all"
      class="peer-orb-hittarget"
    />
    <!-- Drift ring (outermost visible) -->
    <circle
      v-if="hasDrift"
      :r="radius + 8"
      class="peer-orb-drift"
    />
    <!-- Bundle freshness ring -->
    <circle
      v-if="bundleFreshnessState"
      :r="radius + 5"
      :class="['peer-orb-freshness', `peer-orb-freshness--${bundleFreshnessState}`]"
    />
    <!-- §pass61.3 (2026-05-21): Halo only renders when NO flare is equipped.
         The flare provides its own visual identity + glow; the orb_glow_color
         halo on TOP of a flare creates a giant bouncing colored circle that
         overwhelms the flare (Commander caught this 2026-05-21). When flare
         is equipped, the FlareEncirclement is the single source of visual
         identity. Halo stays for plain-orb peers (no flare set). -->
    <circle
      v-if="haloEnabled && !renderFlare"
      :r="radius + 3"
      :fill="orbGlow"
      :class="['peer-orb-halo', {
        'peer-orb-halo--pulse': pulseDuration,
        'peer-orb-halo--local': isLocal,
      }]"
      :style="pulseDuration ? { animationDuration: pulseDuration } : {}"
    />
    <!-- §pass-N Pass 3.5: Card v0.3 flare encirclement via foreignObject.
         Hides core+glyph when present. Halo + freshness + drift still render
         around the flare. pointer-events: none so parent click handler wins. -->
    <foreignObject
      v-if="renderFlare"
      :x="-flareSizePx / 2"
      :y="-flareSizePx / 2"
      :width="flareSizePx"
      :height="flareSizePx"
      class="peer-orb-flare-host"
      overflow="visible"
    >
      <div class="peer-orb-flare-frame" :data-variant="flareVariantProp" :data-overlay="flareOverlayProp" :data-tier="flareTierProp">
        <FlareEncirclement
          v-if="flareVariantProp"
          :tier="flareTierProp"
          :variant="flareVariantProp"
          :overlay="flareOverlayProp"
          :size="flareSize"
        />
      </div>
    </foreignObject>
    <!-- Core orb — only when no flare is replacing it -->
    <circle
      v-if="!renderFlare"
      :r="radius"
      :fill="orbColor"
      :class="['peer-orb-core', `peer-orb-core--${effectiveTier}`]"
    />
    <!-- Tier glyph — hidden when flare replaces the core -->
    <text
      v-if="showGlyph && !renderFlare"
      y="4"
      text-anchor="middle"
      class="peer-orb-glyph"
    >{{ tierGlyph }}</text>
    <!-- Local "you are here" marker dot above the orb -->
    <circle
      v-if="isLocal"
      :cy="-(radius + 12)"
      r="2"
      class="peer-orb-local-marker"
    />
  </g>
</template>

<style scoped>
/* Halo + pulse */
.peer-orb-halo {
  opacity: 0.42;
  filter: blur(2.5px);
  transform-origin: center;
}
.peer-orb-halo--pulse {
  animation-name: peer-orb-pulse;
  animation-iteration-count: infinite;
  animation-timing-function: ease-in-out;
  /* duration via inline style */
}
.peer-orb-halo--local {
  opacity: 0.55;
}
@keyframes peer-orb-pulse {
  /* §pass61.3 (2026-05-21): reduced scale from 1.12 → 1.05 and opacity max from
     0.78 → 0.55 — the larger jitter looked like "bouncing circles" behind the
     orbs at hop-2+ resolutions. Subtler is better for graph context. */
  0%, 100% { opacity: 0.34; transform: scale(1); }
  50%      { opacity: 0.55; transform: scale(1.05); }
}

/* Core + per-tier subtle stroke (matches existing fed-svg-node-- pattern) */
.peer-orb-core { stroke: rgba(255, 255, 255, 0.12); stroke-width: 1; }
.peer-orb-core--local { stroke: #fff; stroke-width: 1.5; }
.peer-orb-core--frame { stroke: rgba(168, 85, 247, 0.35); }
.peer-orb-core--direct_peer { stroke: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35); }
.peer-orb-core--discovered { stroke: rgba(245, 158, 11, 0.35); }
.peer-orb-core--cloud_operator { stroke: rgba(34, 197, 94, 0.35); }

/* Tier glyph (white, monospace) */
.peer-orb-glyph {
  font-size: 11px;
  fill: rgba(255, 255, 255, 0.92);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-weight: 700;
  pointer-events: none;
  user-select: none;
}

/* Bundle freshness ring */
.peer-orb-freshness { fill: none; stroke-width: 2; }
.peer-orb-freshness--fresh    { stroke: var(--nc-success, #00ff88); opacity: 0.85; }
.peer-orb-freshness--overdue  {
  stroke: var(--nc-warning, #ff9500);
  animation: peer-orb-freshness-overdue 2.4s ease-in-out infinite;
}
.peer-orb-freshness--critical {
  stroke: var(--nc-danger, #ff3366);
  stroke-width: 2.5;
  animation: peer-orb-freshness-critical 1.4s ease-in-out infinite;
}
.peer-orb-freshness--unknown {
  stroke: var(--nc-text-muted, #94a3b8);
  stroke-width: 1.2;
  stroke-dasharray: 2 3;
  opacity: 0.6;
}
@keyframes peer-orb-freshness-overdue {
  0%, 100% { opacity: 0.45; }
  50%      { opacity: 0.9; }
}
@keyframes peer-orb-freshness-critical {
  0%, 100% { opacity: 0.55; }
  50%      { opacity: 1.0; }
}

/* Drift dashed ring (red) */
.peer-orb-drift {
  fill: none;
  stroke: var(--nc-danger, #ff3366);
  stroke-width: 1.5;
  stroke-dasharray: 3 3;
  opacity: 0.55;
  animation: peer-orb-drift-spin 18s linear infinite;
}
@keyframes peer-orb-drift-spin {
  from { stroke-dashoffset: 0; }
  to   { stroke-dashoffset: 60; }
}

/* Local "you are here" marker */
.peer-orb-local-marker {
  fill: var(--nc-primary-bright, #00e5e5);
  filter: drop-shadow(0 0 4px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.8));
}

@media (prefers-reduced-motion: reduce) {
  .peer-orb-halo--pulse,
  .peer-orb-freshness--overdue,
  .peer-orb-freshness--critical,
  .peer-orb-drift { animation: none }
}

/* Inline-mode SVG container (for mobile list) */
.peer-orb-svg-inline { display: inline-block; vertical-align: middle; }

/* §pass-N Pass 3.5: foreignObject host for FlareEncirclement.
   Scoped styles apply data-v-* attrs only to elements rendered by THIS component.
   FlareEncirclement's deeply nested spans carry a different data-v attribute, so
   plain `.peer-orb-flare-host *` will not match them. `:deep(*)` punches through
   the scope boundary so pointer-events: none cascades to FlareEncirclement's
   internals — parent <g> in Federation.vue then receives mouseenter/click. */
.peer-orb-flare-host {
  pointer-events: none;
  overflow: visible;
}
.peer-orb-flare-host :deep(*) {
  pointer-events: none !important;
}
.peer-orb-flare-frame {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
</style>
