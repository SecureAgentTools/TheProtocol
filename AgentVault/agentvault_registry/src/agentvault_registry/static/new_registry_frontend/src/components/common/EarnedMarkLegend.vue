<!--
  EarnedMarkLegend — §MARKCOLLAR-2 (2026-08-16)

  An "i" affordance that explains what the marks on the cards MEAN, by RENDERING
  the actual marks rather than describing them in prose. Commander's ask: put it
  on Agent Discovery (not AgentWorld), so the people browsing agents can learn
  the ladder where they meet it.

  It draws each tier through EarnedMarkCollar itself, with a synthetic track
  record at that tier's threshold. So the legend cannot go stale: change a
  threshold or a metal in one place and this panel changes with it. A legend
  maintained by hand beside the thing it documents is a legend that lies within
  a month.
-->
<template>
  <span class="eml">
    <button
      type="button"
      class="eml-btn"
      data-testid="earned-legend-btn"
      :aria-expanded="open ? 'true' : 'false'"
      :title="t('earnedMarks.legendHint', 'What do the marks on these avatars mean?')"
      @click.stop="toggle"
      @mouseenter="onEnter"
      @mouseleave="onLeave"
    >i</button>

    <teleport to="body">
      <div v-if="open" class="eml-scrim" data-testid="earned-legend" @click="dismiss">
        <div class="eml-panel" @click.stop>
          <div class="eml-head">
            <h3 class="eml-title">{{ t('earnedMarks.legendTitle', 'Earned marks') }}</h3>
            <button type="button" class="eml-x" @click="dismiss" aria-label="Close">×</button>
          </div>

          <p class="eml-lede">
            {{ t('earnedMarks.legendLede', 'These marks come from this registry\'s own guild ledger: engagements a poster escrowed, verified and paid. They cannot be bought, and they carry your disputes as well as your wins. Cosmetic flares are a separate system entirely.') }}
          </p>

          <p class="eml-grammar">
            {{ t('earnedMarks.legendGrammar', 'The mark is engraved, the way a certificate is: one line per tier, seven at the top. The medallion above the engraving is the exact number of verified jobs, and a dashed bottom line means the agent carries credentials earned on another registry.') }}
          </p>

          <!-- §MARKGUILLOCHE-2 — the whole ladder, each tier worn over a
               DIFFERENT purchased encirclement. Shared with the Flare Shop so a
               legend and a shop can never tell two different stories. -->
          <EarnedMarkTiers />

          <div class="eml-extras">
            <div class="eml-extra">
              <span class="eml-swatch eml-swatch--sm">
                <EarnedMarkCollar :tr="sampleCross" size="xl" :detail="true" />
              </span>
              <span class="eml-extra-txt">
                <b>{{ t('earnedMarks.legendCross', 'Dashed bottom line') }}</b>
                {{ t('earnedMarks.legendCrossTxt', '— holds verified work credentials earned on another registry. Trust that travelled, engraved into the same plate.') }}
              </span>
            </div>
            <div class="eml-extra">
              <span class="eml-swatch eml-swatch--sm">
                <EarnedMarkCollar :tr="sampleDispute" size="xl" :detail="true" />
              </span>
              <span class="eml-extra-txt">
                <b>{{ t('earnedMarks.legendDispute', 'Red flag') }}</b>
                {{ t('earnedMarks.legendDisputeTxt', '— a guild dispute is open right now. It is shown, not hidden, and it clears when the dispute resolves.') }}
              </span>
            </div>
          </div>

          <p class="eml-foot">
            {{ t('earnedMarks.legendFoot', 'The number on the mark is the exact count of verified jobs. Everything here is recomputed from the ledger on read.') }}
          </p>
        </div>
      </div>
    </teleport>
  </span>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import EarnedMarkCollar from '@/components/common/EarnedMarkCollar.vue'
import EarnedMarkTiers from '@/components/common/EarnedMarkTiers.vue'
import { type TrackRecordCompact } from '@/services/api/trackRecord'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const open = ref(false)

// Click OR hover, per the Commander. Hover waits so a cursor crossing the icon
// on its way somewhere else does not throw a full-screen panel up; once open by
// EITHER route it stays until dismissed, because a panel that vanishes when the
// pointer drifts is unreadable.
let hoverTimer: ReturnType<typeof setTimeout> | null = null

// ⚠ Load-bearing, and subtler than it looks. The open panel's scrim COVERS the
// "i", so opening fires mouseLEAVE on the button and dismissing fires
// mouseENTER again — on a cursor that never moved. Escape therefore closed the
// panel and it sprang straight back open, which reads as "Escape is broken".
//
// Tracking "is the pointer on the button" does NOT fix this: the scrim has
// already stolen the hover by the time the dismiss runs, so that flag is false
// exactly when it needs to be true. The honest condition is about MOTION, not
// position: after an explicit dismiss, refuse to re-open on hover until the
// pointer actually moves. Move away and come back and it works normally; sit
// still and it stays shut, which is what a dismiss means.
const dismissed = ref(false)
function releaseDismissGuard() { dismissed.value = false }
function armDismissGuard() {
  dismissed.value = true
  window.removeEventListener('pointermove', releaseDismissGuard)
  window.addEventListener('pointermove', releaseDismissGuard, { once: true })
}

function toggle() {
  hoverCancel()
  open.value = !open.value
  if (!open.value) armDismissGuard()
}
/** Explicit dismissal: Escape, the ×, or a click on the scrim. */
function dismiss() {
  hoverCancel()
  open.value = false
  armDismissGuard()
}
function onEnter() {
  if (open.value || dismissed.value) return
  hoverCancel()
  hoverTimer = setTimeout(() => { open.value = true }, 380)
}
function onLeave() { hoverCancel() }
function hoverCancel() { if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null } }

// Synthetic records at each threshold: the legend renders the REAL component,
// so it can never drift from what the cards show.
function sample(jobs: number): TrackRecordCompact {
  return {
    jobs, stars: 5, five_star: jobs, on_time_met: jobs, on_time_of: jobs,
    traveled: 0, cross_registry: 0, disputes: 0, open_disputes: 0, lost_disputes: 0,
    last_verified_at: null,
  }
}
const sampleCross: TrackRecordCompact = { ...sample(10), cross_registry: 3 }
const sampleDispute: TrackRecordCompact = { ...sample(10), disputes: 1, open_disputes: 1 }

// Escape closes it. Anything that covers the screen and cannot be dismissed
// from the keyboard is a trap; this one is teleported to <body>, so without
// this it also survives navigating away underneath it.
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') dismiss() }
watch(open, (v) => {
  if (v) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('pointermove', releaseDismissGuard)
  hoverCancel()
})
</script>

<style scoped>
.eml { display: inline-flex; }
.eml-btn {
  width: 16px; height: 16px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 10px; font-weight: 800; line-height: 1;
  color: rgba(148,163,184,0.95);
  background: rgba(148,163,184,0.12);
  border: 1px solid rgba(148,163,184,0.35);
  cursor: pointer; transition: all 140ms ease;
}
.eml-btn:hover { color: #fff; background: rgba(148,163,184,0.3); border-color: rgba(148,163,184,0.6); }

.eml-scrim {
  position: fixed; inset: 0; z-index: 9000;
  background: rgba(2,6,12,0.72); backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center; padding: 1.5rem;
}
.eml-panel {
  /* 720 not 560: the ladder is capped at four across, and this is the width
     that lets all four fit so the legend shows the same 4 + 3 plate the shop
     does instead of breaking to three. */
  width: min(720px, 100%); max-height: 86vh; overflow-y: auto;
  background: #0b1220; border: 1px solid rgba(148,163,184,0.22);
  border-radius: 0.8rem; padding: 1.35rem 1.5rem;
  box-shadow: 0 24px 70px rgba(0,0,0,0.6);
}
.eml-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.6rem; }
.eml-title { font-size: 1rem; font-weight: 700; color: #e2e8f0; margin: 0; letter-spacing: 0.01em; }
.eml-x {
  background: none; border: none; color: rgba(148,163,184,0.8);
  font-size: 1.4rem; line-height: 1; cursor: pointer; padding: 0 0.25rem;
}
.eml-x:hover { color: #fff; }
.eml-lede { font-size: 0.82rem; line-height: 1.55; color: #94a3b8; margin: 0 0 1.1rem; }

/* NOTE: the hand-rolled tier list, its .eml-meta/.eml-name/.eml-min/.eml-shape
   rows and the two-example .eml-over block were all replaced by the shared
   EarnedMarkTiers showcase; their rules are deleted with them. Scoped CSS for
   markup that no longer exists is the quietest kind of rot. */
.eml-swatch {
  position: relative; width: 58px; height: 58px; flex: none;
  border-radius: 50%; background: #16202e; border: 1px solid rgba(148,163,184,0.18);
  overflow: hidden;
}
.eml-swatch--sm { width: 50px; height: 50px; }
.eml-grammar { font-size: 0.78rem; line-height: 1.5; color: #94a3b8; margin: 0 0 0.9rem;
  padding-left: 0.7rem; border-left: 2px solid rgba(148,163,184,0.25); }

.eml-extras { display: grid; gap: 0.7rem; padding-top: 1rem; border-top: 1px solid rgba(148,163,184,0.14); }
.eml-extra { display: flex; align-items: center; gap: 0.85rem; }
.eml-extra-txt { font-size: 0.78rem; line-height: 1.5; color: #94a3b8; }
.eml-extra-txt b { color: #cbd5e1; font-weight: 600; }
.eml-foot {
  margin: 1rem 0 0; padding-top: 0.85rem;
  border-top: 1px solid rgba(148,163,184,0.14);
  font-size: 0.75rem; line-height: 1.5; color: #64748b;
}
</style>
