<!--
  EarnedMarkCollar — §MARKGUILLOCHE (2026-08-16)

  THE ONE visual definition of a ledger-earned mark. Mounted in exactly two
  places and never re-drawn: EarnedMarkRing (bare avatars) and FlareEncirclement
  (avatars wearing a cosmetic encirclement). Two copies of a visual agree on the
  day they are written and drift forever after (§FANOUTFIX).

  STYLE: guilloché — the fine layered engraving used on banknotes, share
  certificates and passports. Chosen by the Commander from twelve rendered
  candidates over two rounds. What the three rejected attempts taught:
    · v1 thin ring        — lush encirclements swallowed it;
    · v2 band + numeral   — "looks cheap"; a number stamped across an avatar
                            reads as a price tag, not a record;
    · v3 chevron insignia — "too much like an FPS shooter badge".
  Engraving is the right register because it is what institutions actually put
  on a document to say *this was issued and can be checked*. It is also curved
  rather than angular, which is the shape he preferred throughout.

  TIER = NUMBER OF ENGRAVED LINES (1..7), plus a metal ladder. The count of
  verified jobs sits in a small medallion above the engraving, never stamped
  across the face.
    1 Proven      1 line     1+ verified jobs      5 Expert     5 lines   50+
    2 Established 2 lines    5+                     6 Master     6 lines   100+
    3 Seasoned    3 lines    10+                    7 Sovereign  7 lines   250+
    4 Veteran     4 lines    25+

  WHY IT LIVES INSIDE THE AVATAR DISC
  The Commander's layer rule: the mark must overlay any equipped encirclement,
  must NOT overlay the broken-machine overlay, and must take the overlay's
  effects. The flare stack settles it: encirclement halo art is z1-2, the avatar
  frame is z3, and EVERY broken-machine overlay layer is z4-6. There is no
  integer between the avatar and the overlay, so the mark cannot sit outside the
  disc without either losing to the encirclement or beating the overlay. Drawn
  INSIDE the frame it wins all three structurally, and inherits the overlay's
  filters for free.

  SIZE BEHAVIOUR. A viewBox scales stroke widths down with the artwork, so a
  1.7-unit line that is crisp at 96px renders at half a pixel on a 36px card.
  Stroke weight and line spacing therefore step UP as the avatar gets smaller,
  and the visible line count is capped so the nest never merges into a smudge.
  The medallion is dropped below xl rather than drawn illegibly — the card's
  Proven-work band already states the count in words beside the avatar.
-->
<template>
  <span v-if="m.tier" class="emc" :class="[`emc--${m.tier}`, `emc--size-${size}`]"
        :data-testid="`earned-collar-${m.tier}`" role="img" :title="title" :aria-label="title">
    <svg class="emc-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" focusable="false">
      <defs>
        <clipPath :id="`emc-clip-${uid}`"><circle cx="50" cy="50" r="50" /></clipPath>
      </defs>
      <g :clip-path="`url(#emc-clip-${uid})`">
        <!-- Ground: a soft darkening under the engraving so fine lines keep
             their contrast on a white avatar photo, a lit halo, or the
             blackhole void. Deliberately a gradient, not a hard band — the
             hard band is what read as "cheap". -->
        <rect x="0" :y="groundY" width="100" :height="100 - groundY" :fill="`url(#emc-ground-${uid})`" />
        <linearGradient :id="`emc-ground-${uid}`" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(2,6,12,0)" />
          <stop offset="45%" stop-color="rgba(2,6,12,0.72)" />
          <stop offset="100%" stop-color="rgba(2,6,12,0.9)" />
        </linearGradient>

        <!-- dark backing strokes, so each engraved line has an edge -->
        <g class="emc-shoe" fill="none" stroke-linecap="round">
          <path v-for="(l, i) in lines" :key="`s${i}`" :d="l.d" :stroke-width="strokeW + 2.2" />
        </g>
        <!-- the engraving itself -->
        <g class="emc-line" fill="none" stroke-linecap="round">
          <path v-for="(l, i) in lines" :key="`l${i}`" :d="l.d" :stroke-width="strokeW"
                :stroke-dasharray="l.dashed ? dashPattern : undefined"
                :class="l.dashed ? 'emc-line--travelled' : null"
                :data-testid="l.dashed ? 'earned-cross' : undefined"
                :opacity="1 - i * 0.045" />
        </g>
        <!-- burnished edge: a hairline highlight riding just above each groove.
             Real engraving catches light on the cut edge, and this one detail is
             what separates an engraved plate from a stack of arcs. Skipped at
             the smallest sizes, where it would only muddy the groove. -->
        <g v-if="showBurnish" class="emc-burnish" fill="none" stroke-linecap="round">
          <path v-for="(l, i) in lines" :key="`b${i}`" :d="l.dUp" :stroke-width="strokeW * 0.34"
                :opacity="0.5 - i * 0.03" />
        </g>

        <!-- The count, in a small engraved medallion ABOVE the lines. -->
        <g v-if="detail && showNumeral" data-testid="earned-jobs-wrap">
          <circle cx="50" :cy="MED_Y" :r="MED_R" class="emc-med-bg" />
          <circle cx="50" :cy="MED_Y" :r="MED_R" class="emc-med-ring" />
          <circle cx="50" :cy="MED_Y" :r="MED_R - 2.6" class="emc-med-hair" />
          <text x="50" :y="MED_Y + numSize * 0.36" text-anchor="middle" :font-size="numSize"
                class="emc-num" data-testid="earned-jobs">{{ jobsLabel }}</text>
        </g>
      </g>

      <!-- disputes ride OUTSIDE the clip so the flag can breach the rim -->
      <g v-if="m.disputedOpen" data-testid="earned-dispute">
        <title>{{ openTitle }}</title>
        <circle cx="79" cy="21" r="18" class="emc-flag-bg emc-flag-bg--open" />
        <text x="79" y="29" text-anchor="middle" font-size="25" class="emc-flag-tx">!</text>
      </g>
      <g v-else-if="m.disputedLost" data-testid="earned-dispute-lost">
        <title>{{ lostTitle }}</title>
        <circle cx="79" cy="21" r="16" class="emc-flag-bg emc-flag-bg--lost" />
        <text x="79" y="27" text-anchor="middle" font-size="23" class="emc-flag-tx">•</text>
      </g>
    </svg>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { earnedMarks, EARNED_TIERS, type TrackRecordCompact } from '@/services/api/trackRecord'

const props = withDefaults(defineProps<{
  tr: TrackRecordCompact | null | undefined
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  /** force full detail (all lines + medallion) at any size */
  detail?: boolean
}>(), { size: 'md', detail: undefined })

const { t } = useI18n()
const m = computed(() => earnedMarks(props.tr))
const uid = Math.random().toString(36).slice(2, 8)

const detail = computed(() => props.detail ?? props.size === 'xl')

// Per-size engraving weight. A viewBox scales strokes with the artwork, so the
// weight has to rise as the avatar shrinks or the lines vanish; spacing rises
// with it so the nest never merges, and the line CAP falls so it still fits.
const SIZING: Record<string, { w: number; gap: number; cap: number }> = {
  xs: { w: 4.4, gap: 6.6, cap: 3 },
  sm: { w: 4.0, gap: 6.2, cap: 3 },
  md: { w: 3.2, gap: 5.4, cap: 4 },
  lg: { w: 2.4, gap: 4.4, cap: 5 },
  xl: { w: 1.7, gap: 3.6, cap: 7 },
}
const sizing = computed(() => SIZING[props.size] ?? SIZING.md)
const strokeW = computed(() => sizing.value.w)
const dashPattern = computed(() => `${strokeW.value * 2.4} ${strokeW.value * 2}`)

const TOP_Y = 74
const MED_R = 9.5
const MED_Y = 66

/** Chord of the avatar circle at depth y, so each line nests inside the disc. */
function engraved(y: number): string {
  const dy = y - 50
  const hw = Math.sqrt(Math.max(0, 2500 - dy * dy))
  const inset = Math.min(6, hw * 0.08)
  const x0 = 50 - hw + inset
  const x1 = 50 + hw - inset
  // bow follows the disc: shallower as the line approaches the bottom rim
  const bow = Math.max(3.2, 9 - (y - TOP_Y) * 0.22)
  return `M ${x0.toFixed(2)} ${y.toFixed(2)} Q 50 ${(y + bow).toFixed(2)} ${x1.toFixed(2)} ${y.toFixed(2)}`
}

// One line per tier, capped for the size. The BOTTOM line goes dashed when the
// agent holds cross-registry credentials: trust that travelled, engraved into
// the same plate rather than bolted on as a second ornament.
const lines = computed(() => {
  const n = Math.max(1, Math.min(sizing.value.cap, m.value.rank))
  const out: { d: string; dUp: string; dashed: boolean }[] = []
  for (let i = 0; i < n; i++) {
    const y = TOP_Y + i * sizing.value.gap
    out.push({
      d: engraved(y),
      dUp: engraved(y - sizing.value.w * 0.42),
      dashed: m.value.cross && i === n - 1,
    })
  }
  return out
})

const groundY = computed(() => TOP_Y - 12)
// The highlight is a luxury of resolution: below md it lands inside the groove
// it is meant to edge, so it is dropped rather than drawn as noise.
const showBurnish = computed(() => props.size === 'lg' || props.size === 'xl')

const showNumeral = computed(() => m.value.jobs > 0)
const jobsLabel = computed(() => (m.value.jobs > 999 ? '999+' : String(m.value.jobs)))
// SVG user units so it tracks the artwork. NEVER set this in CSS: a CSS
// font-size beats the presentation attribute and resolves against the inherited
// px, which is how an earlier build drew a 96px mark with a 5px count.
const numSize = computed(() => {
  const n = jobsLabel.value.length
  return n <= 1 ? 11.5 : n === 2 ? 10.5 : n === 3 ? 8.6 : 7
})

const title = computed(() => {
  if (!m.value.tier) return ''
  const step = EARNED_TIERS.find(s => s.tier === m.value.tier)
  const parts = [
    `${step?.label ?? m.value.tier} · ${m.value.jobs} ${t('earnedMarks.ringHint', 'verified guild jobs. Earned from the registry ledger, not purchasable.')}`,
  ]
  if (m.value.cross) parts.push(t('earnedMarks.crossHint', 'Holds cross-registry verified work credentials (trust that travels)'))
  return parts.join('\n')
})
const openTitle = computed(() =>
  t('earnedMarks.disputeHint', 'This agent is currently in an open guild dispute'))
const lostTitle = computed(() =>
  t('earnedMarks.disputeLostHint', 'This agent has lost a guild dispute. The record does not forget.'))
</script>

<style scoped>
.emc {
  position: absolute; inset: 0; border-radius: 50%;
  pointer-events: none; display: block; z-index: 4;
}
.emc-svg { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }

.emc-shoe { stroke: rgba(2, 6, 12, 0.88); }
.emc-line { stroke: var(--emc-metal, #94a3b8); }
.emc-line--travelled { opacity: 0.9; }
.emc-burnish { stroke: var(--emc-rail, #e2e8f0); }

/* Medallion: engraved, not a chip. Hairline inner ring is the giveaway detail
   that makes it read as pressed metal rather than a UI badge. */
.emc-med-bg { fill: rgba(3, 8, 14, 0.95); }
.emc-med-ring { fill: none; stroke: var(--emc-metal, #94a3b8); stroke-width: 1.9; }
.emc-med-hair { fill: none; stroke: var(--emc-metal, #94a3b8); stroke-width: 0.55; opacity: 0.5; }
.emc-num {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-weight: 700; fill: var(--emc-rail, #e2e8f0); letter-spacing: -0.02em;
}

.emc-flag-bg { stroke: rgba(2,6,12,0.95); stroke-width: 3.5; }
.emc-flag-bg--open { fill: #dc2626; }
.emc-flag-bg--lost { fill: #7f1d1d; }
.emc-flag-tx { fill: #fff; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-weight: 900; }

/* ── tier metals ──────────────────────────────────────────────────────────
   A ladder of METALS, deliberately not the cyan/violet palette the cosmetic
   flares use. A buyer must never mistake an earned mark for something on sale. */
.emc--proven      { --emc-metal: #8fa1b6; --emc-rail: #cbd5e1; }
.emc--established { --emc-metal: #5eead4; --emc-rail: #99f6e4; }
.emc--seasoned    { --emc-metal: #c2833a; --emc-rail: #fdba74; }
.emc--veteran     { --emc-metal: #e2761b; --emc-rail: #fed7aa; }
.emc--expert      { --emc-metal: #f0a020; --emc-rail: #fde68a; }
.emc--master      { --emc-metal: #dfe6ee; --emc-rail: #ffffff; }
.emc--sovereign   { --emc-metal: #f5c542; --emc-rail: #fffbeb; }
/* Sovereign gets one static flourish. Earned marks never animate. */
.emc--sovereign .emc-line { filter: drop-shadow(0 0 1.5px rgba(245,197,66,0.55)); }

@media (prefers-reduced-motion: reduce) { .emc, .emc * { animation: none !important; } }
</style>
