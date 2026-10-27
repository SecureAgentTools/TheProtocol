<!--
  EarnedMarkTiers — §MARKGUILLOCHE-2 (2026-08-16)

  THE ladder, shown rather than described: all seven earned tiers, each one worn
  over a DIFFERENT cosmetic encirclement. That pairing is the whole argument in
  one glance — every mark stays legible no matter what the agent bought, so a
  cosmetic can never hide (or fake) a record.

  Commander's ask, after seeing the two-example version: "just with all tiers.
  you can also use a mix of encirclements to not make it boring."

  ONE component, two mounts: the Flare Shop (where someone is about to spend
  money on cosmetics and should see exactly what is NOT for sale) and the Agent
  Discovery legend (where someone is reading the marks on cards). A shop and a
  legend that each drew their own ladder would disagree within a month.

  Every swatch renders the real EarnedMarkCollar inside the real
  FlareEncirclement, so this cannot drift from the cards: change a threshold, a
  metal, or the engraving and this panel changes with it.
-->
<template>
  <div class="emt" data-testid="earned-mark-tiers">
    <div v-if="heading" class="emt-head">{{ heading }}</div>

    <ul class="emt-grid" :class="compact ? 'emt-grid--compact' : null">
      <li v-for="s in tiers" :key="s.tier" class="emt-item"
          :data-testid="`earned-tier-${s.tier}`" :title="`${s.label} · ${s.min}+ verified jobs`">
        <!-- ⚠ the reserved box MUST be a wrapper, never a class on the
             encirclement: that class lands on .fc-encircle itself, so sizing it
             resizes the DISC instead of reserving room around the halo. -->
        <span class="emt-art">
          <FlareEncirclement
            :tier="COSMETIC[s.rank % COSMETIC.length].tier"
            :variant="COSMETIC[s.rank % COSMETIC.length].variant"
            :overlay="COSMETIC[s.rank % COSMETIC.length].overlay"
            :track-record="sample(s.min)"
            initials="TP"
            size="xl"
            :detail="true"
          />
        </span>
        <span class="emt-name">{{ s.label }}</span>
        <span class="emt-min">{{ s.min }}+</span>
        <span class="emt-lines">{{ s.rank }} {{ s.rank === 1 ? t('earnedMarks.line', 'line') : t('earnedMarks.lines', 'lines') }}</span>
      </li>
    </ul>

    <p v-if="!compact" class="emt-foot">
      {{ t('earnedMarks.tiersFoot', 'Each agent above wears a different purchased encirclement. The engraved mark reads through every one of them, because it is not part of the cosmetic: it is struck from this registry\'s guild ledger and recomputed on read.') }}
    </p>
  </div>
</template>

<script setup lang="ts">
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import { EARNED_TIERS_ASC, type TrackRecordCompact } from '@/services/api/trackRecord'
import { useI18n } from '@/composables/useI18n'

withDefaults(defineProps<{
  heading?: string | null
  /** denser grid, no closing paragraph — for use inside an already-wordy panel */
  compact?: boolean
}>(), { heading: null, compact: false })

const { t } = useI18n()
const tiers = EARNED_TIERS_ASC

// A deliberately mixed cast of cosmetics, including a full-cover variant
// (blackhole) and a broken-machine overlay, so the row is not seven copies of
// the same ring and so the two hardest cases are always on screen.
const COSMETIC: { tier: string; variant: string; overlay: string | null }[] = [
  { tier: 'shadow_chancellor', variant: 'sauron',    overlay: null },
  { tier: 'shadow_chancellor', variant: 'obsidian',  overlay: null },
  { tier: 'shadow_chancellor', variant: 'blackhole', overlay: null },
  { tier: 'shadow_chancellor', variant: 'goth',      overlay: 'glitch' },
  { tier: 'shadow_chancellor', variant: 'void',      overlay: null },
  { tier: 'shadow_chancellor', variant: 'matrix',    overlay: null },
  { tier: 'shadow_chancellor', variant: 'obsidian',  overlay: 'cascade' },
]

// Synthetic record at each threshold. The REAL component draws it, so the panel
// cannot go stale.
function sample(jobs: number): TrackRecordCompact {
  return {
    jobs, stars: 5, five_star: jobs, on_time_met: jobs, on_time_of: jobs,
    traveled: 0, cross_registry: jobs >= 25 ? 3 : 0,
    disputes: 0, open_disputes: 0, lost_disputes: 0, last_verified_at: null,
  }
}
</script>

<style scoped>
.emt { width: 100%; }
.emt-head {
  font-size: 0.82rem; font-weight: 600; color: #cbd5e1;
  margin-bottom: 0.9rem; letter-spacing: 0.01em;
}
/* ⚠ THE §FLARESHOP GALLERY LESSON, RE-EARNED HERE. An xl encirclement is a 96px
   disc that throws its halo 30-40px past the rim in every direction, and several
   of these variants animate outward. Sized to the DISC, the top row's glow
   washed over the paragraph above it and neighbours bled into each other, which
   a testid-counting battery reports as a clean pass. Size the cell to the HALO,
   not to the disc, and reserve the artwork box explicitly so the caption never
   sits inside someone else's glow. */
/* Flex, not grid: the ladder is seven items and auto-fit leaves the last row
   left-packed under a full row, which reads as a layout accident rather than a
   deliberate wrap. Centred rows look like a plate of specimens, which is what
   this is. */
/* Capped to four across on purpose. Left uncapped, the wide Flare Shop laid the
   ladder out 6 + 1 and orphaned Sovereign on its own line, which reads as an
   accident rather than a top rung. 4 + 3 is a plate of specimens on BOTH
   surfaces, which also makes the "same ladder, two mounts" claim visible. */
.emt-grid {
  list-style: none; padding: 0.4rem 0 0;
  margin: 0 auto; max-width: 664px;
  display: flex; flex-wrap: wrap; justify-content: center;
  gap: 1.9rem 1.1rem;
}
.emt-item {
  flex: 0 0 152px;
  display: flex; flex-direction: column; align-items: center; gap: 0.28rem;
  text-align: center;
}
.emt-grid--compact { gap: 1.5rem 0.8rem; }
.emt-grid--compact .emt-item { flex: 0 0 132px; }
/* Reserved artwork box: the halo lives inside this, so labels below and prose
   above are never overlapped no matter which cosmetic a rung wears. */
.emt-art {
  height: 144px; width: 144px; flex: none;
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 0.15rem;
}
.emt-grid--compact .emt-art { height: 122px; width: 122px; }
.emt-item :deep(.fc-encircle) { flex: none; }
.emt-name { font-size: 0.78rem; font-weight: 600; color: #e2e8f0; line-height: 1.2; }
.emt-min {
  font-size: 0.7rem; color: #8a96a8; /* §FESUITE: was #64748b, 4.0:1 */
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
}
.emt-lines { font-size: 0.66rem; color: #8a96a8; } /* §FESUITE: was #475569, 2.5:1 */
.emt-foot {
  margin: 1.35rem 0 0; font-size: 0.76rem; line-height: 1.55; color: #94a3b8;
}
</style>
