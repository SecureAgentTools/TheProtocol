<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * BridgePulse.vue — §BRIDGE #B17
 *
 * The last sixty minutes of the network's heartbeat, one bar per minute.
 *
 * HONESTY FIRST: this counts what THIS SESSION has actually seen. It does not
 * backfill from an API and then present the result as if the page had been
 * watching all along — a sparkline that invents its own past would be the exact
 * opposite of what this product is about. Minutes before you arrived are drawn
 * as empty and the strip says how much of the hour it can actually vouch for.
 *
 * Cost: 60 divs and one tick a second. No canvas, no second socket - it reads
 * the shared `useLedgerStream` counter that is already running.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useLedgerStream } from '@/composables/useLedgerStream'

const { t } = useI18n()
const stream = useLedgerStream()

const BUCKETS = 60
/** counts[0] is the CURRENT minute; higher indexes are further in the past. */
const counts = ref<number[]>(new Array(BUCKETS).fill(0))
/** How many minutes this page has actually been watching (capped at BUCKETS). */
const covered = ref(0)

let lastTotal = 0
let tick: ReturnType<typeof setInterval> | null = null
let rollover: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  lastTotal = stream.totalEvents.value
  // Accumulate into the current minute every second...
  tick = setInterval(() => {
    const now = stream.totalEvents.value
    const delta = Math.max(0, now - lastTotal)
    lastTotal = now
    if (delta > 0) counts.value[0] += delta
  }, 1000)
  // ...and roll the window once a minute.
  rollover = setInterval(() => {
    counts.value.unshift(0)
    counts.value.length = BUCKETS
    covered.value = Math.min(BUCKETS, covered.value + 1)
  }, 60_000)
})

onBeforeUnmount(() => {
  if (tick) clearInterval(tick)
  if (rollover) clearInterval(rollover)
})

const peak = computed(() => Math.max(1, ...counts.value))
const total = computed(() => counts.value.reduce((a, b) => a + b, 0))
const showHelp = ref(false)

/**
 * The rate the viewer can actually check against the ledger ticking beside it.
 * Averaged over the minutes we have WATCHED — never over the whole hour, which
 * would divide a real count by minutes we were not here for and quietly halve
 * the number the moment you arrive.
 */
const perMin = computed(() => {
  const known = Math.max(1, Math.min(BUCKETS, covered.value + 1))
  return Math.round(total.value / known)
})

/** Oldest first, so the strip reads left-to-right like time. */
const bars = computed(() =>
  counts.value.map((n, i) => ({
    i,
    n,
    /** Minutes ago. */
    ago: i,
    known: i <= covered.value,
    h: Math.max(n > 0 ? 8 : 0, Math.round((n / peak.value) * 100)),
  })).reverse(),
)

const coverageLabel = computed(() =>
  covered.value >= BUCKETS
    ? t('bridge.pulse.full', 'last 60 min')
    : `${t('bridge.pulse.watching', 'watching')} ${covered.value + 1}m`,
)
</script>

<template>
  <section class="bpl" data-tour="bridge-pulse" :aria-label="t('bridge.pulse.title', 'Event density, last 60 minutes')">
    <div class="bpl-strip">
      <div
        v-for="b in bars" :key="b.i"
        class="bpl-bar" :class="{ 'is-unknown': !b.known, 'is-now': b.i === 0 }"
        :style="{ height: b.h + '%' }"
        :title="b.known
          ? `${b.n.toLocaleString(appLocale())} ${t('bridge.pulse.events', 'events')} · ${b.ago}${t('bridge.pulse.minAgo', 'm ago')}`
          : t('bridge.pulse.beforeYou', 'before this page was open - not counted, not invented')"
      ></div>
    </div>
    <div class="bpl-meta">
      <span class="bpl-k">{{ t('bridge.pulse.label', 'NETWORK PULSE') }}</span>
      <span class="bpl-v">{{ total.toLocaleString(appLocale()) }}</span>
      <span class="bpl-u">{{ t('bridge.pulse.seen', 'events seen') }}</span>
      <span class="bpl-dot">·</span>
      <span class="bpl-v">{{ perMin.toLocaleString(appLocale()) }}</span>
      <span class="bpl-u">{{ t('bridge.pulse.perMin', '/min') }}</span>
      <span class="bpl-sub">{{ coverageLabel }}</span>
      <!-- §BRIDGE R10 — "the bottom pulse could use refinement and explanation
           too." A strip of bars that never says what it counts is decoration.
           This states the unit, the window, and what the pale bars mean. -->
      <button type="button" class="bpl-help" data-testid="pulse-help"
              :aria-expanded="showHelp"
              :title="t('bridge.pulse.helpTitle', 'What is this?')"
              @click="showHelp = !showHelp">?</button>
    </div>

    <p v-if="showHelp" class="bpl-explain" data-testid="pulse-explain">
      {{ t('bridge.pulse.explain',
           'One bar per minute, newest on the right: how many ledger events this page saw across all three frames. Pale bars are minutes before you opened it — not counted, not invented.') }}
    </p>
  </section>
</template>

<style scoped>
.bpl {
  position: relative;
  /* Sized from the SAME token the stage offsets by, so the LIVE badge can never
     be swallowed by this strip again. */
  box-sizing: border-box;
  height: var(--brg-pulse-h, 42px);
  display: flex; align-items: flex-end; gap: 0.5rem;
  padding: 0.25rem 0.6rem 0.3rem;
  background: rgba(8, 12, 22, 0.82);
  border-top: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14));
  font-family: var(--nc-font-mono, ui-monospace, monospace);
}
.bpl-strip {
  flex: 1 1 auto; min-width: 0;
  display: flex; align-items: flex-end; gap: 1px;
  height: 26px;
  /* A baseline, so the bars sit ON something and read as a chart rather than as
     stray marks along the bottom edge of the window. */
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  padding-bottom: 1px;
}
.bpl-bar {
  flex: 1 1 0; min-width: 1px;
  background: linear-gradient(to top,
    var(--nc-primary, #22d3ee),
    color-mix(in srgb, var(--nc-primary, #22d3ee) 55%, transparent));
  opacity: 0.62; border-radius: 1px 1px 0 0;
  transition: height 400ms ease;
}
.bpl-bar:hover { opacity: 1; }
/* The live minute is the one you can watch move. */
.bpl-bar.is-now {
  opacity: 1;
  box-shadow: 0 0 5px color-mix(in srgb, var(--nc-primary, #22d3ee) 60%, transparent);
}
/* A minute we were not here for is drawn as ABSENCE, never as zero activity —
   but absence still has to be legible, or the strip reads as an empty band and
   nobody can tell it is a 60-slot hour (seen, screenshot 2026-08-19: one live
   bar and 59 invisible ones). Grey, flat and short keeps it unmistakably
   different from a real reading; it just no longer disappears. */
.bpl-bar.is-unknown { background: var(--nc-text-dim, #6b7f9e); opacity: 0.22; height: 4px !important; }
.bpl-meta { display: flex; align-items: baseline; gap: 0.35rem; flex: 0 0 auto; }
.bpl-k { font-size: 0.5rem; letter-spacing: 0.14em; color: var(--nc-text-dim, #6b7f9e); }
.bpl-v { font-size: 0.62rem; color: var(--nc-text, #d6e2f2); }
.bpl-sub { font-size: 0.5rem; color: var(--nc-text-dim, #6b7f9e); }
.bpl-u { font-size: 0.5rem; color: var(--nc-text-dim, #6b7f9e); }
.bpl-dot { font-size: 0.5rem; color: var(--nc-text-dim, #6b7f9e); opacity: .5; }
.bpl-help {
  background: none; border: 1px solid var(--nc-border, rgba(120,160,210,.25));
  color: var(--nc-text-dim, #6b7f9e); border-radius: 50%;
  width: 12px; height: 12px; line-height: 10px; padding: 0;
  font-size: 8px; cursor: pointer; margin-left: .2rem;
}
.bpl-help:hover { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
.bpl-explain {
  position: absolute; left: 0.6rem; right: 0.6rem; bottom: var(--brg-pulse-h, 42px);
  margin: 0 0 .3rem; padding: .4rem .55rem;
  background: rgba(8, 12, 22, 0.94);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 3px;
  font-size: 0.58rem; line-height: 1.5; color: var(--nc-text-dim, #9db0c8);
  max-width: 46rem;
}
@media (prefers-reduced-motion: reduce) { .bpl-bar { transition: none; } }
</style>
