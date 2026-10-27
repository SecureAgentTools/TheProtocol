<script setup lang="ts">
/**
 * §COCKPIT P5 — TELEMETRY. What this human's consent actually looks like.
 *
 * "41 decisions today · median read 2.9 s · 2 denials" is a sentence about a person's
 * attention, so every number in it is drawn from what the SERVER observed and the read
 * distribution is drawn WITH THE FLOOR MARKED — a read time is only meaningful next to
 * the minimum the posture allowed. A distribution piled against its own floor is the
 * finding: it says the floor, not the reading, is setting the pace.
 *
 * The denial rate is `null`, not 0, until something has been decided. "0% denials" out
 * of zero decisions is a claim about a system nobody has used.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { liabilityApi, type Receipt } from '@/services/api/liability'
import { useI18n } from '@/composables/useI18n'
import { useCockpitBus } from '@/composables/useCockpitBus'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { useConsentPosture } from '@/composables/useConsentPosture'
import { telemetry, bucketise, percentile } from './receiptStats'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.telemetry
const { readFloorMs, name: postureName, load: loadPosture } = useConsentPosture()

const receipts = ref<Receipt[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)

async function load() {
  try {
    receipts.value = (await liabilityApi.receipts({ limit: 200 })).receipts || []
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    if (e?.response?.status === 404) { receipts.value = []; err.value = ''; readAt.value = Date.now() }
    else err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}

const tel = computed(() => telemetry(receipts.value))
const empty = computed(() => !loading.value && tel.value.decisions === 0)
const medianRead = computed(() => percentile([...tel.value.readMs].sort((a, b) => a - b), 50))
const today = computed(() => {
  const d = new Date().toISOString().slice(0, 10)
  return tel.value.perDay.find(x => x.day === d)?.n ?? 0
})

const EDGES = [1000, 2000, 4000, 8000, 20000]
const readHist = computed(() => bucketise(tel.value.readMs, EDGES))
const readMax = computed(() => Math.max(1, ...readHist.value.counts, readHist.value.overflow))
/** Which bucket the posture's floor falls in, so it can be drawn ON the distribution
 *  rather than quoted beside it. */
const floorBucket = computed(() => EDGES.findIndex(e => readFloorMs.value <= e))

const ms = (v: number | null) => (v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`)

useCockpitBus({ 'liability.resolved': () => { void load() } })
// §COCKPITDESK (2026-10-14): the chip says this pane re-reads every 90 s, and it did not: it read at open and then only
// on a 'liability.resolved' cue, so a missed cue (a dropped socket) left it as old as the page. The poll makes the chip
// true; the cue stays, so a decision still shows at once.
let poll: ReturnType<typeof setInterval> | null = null
onMounted(() => { void loadPosture(); void load(); poll = setJitteredInterval(() => { void load() }, (def.pollSeconds ?? 90) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })
</script>

<template>
  <PaneShell
    :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
    :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
    :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
    :empty-text="t('cockpit.telemetry.empty', 'No decisions yet — nothing to say about them.')"
  >
    <div class="ckd-tel" data-testid="ckd-telemetry">
      <p class="ckd-tel-line" data-testid="ckd-tel-headline">
        {{ tp('cockpit.telemetry.headline',
              '{today} decisions today · median read {read} · {denials} denials',
              { today, read: ms(medianRead), denials: tel.denied }) }}
      </p>

      <div class="ckd-tel-grid">
        <div class="ckd-tel-cell"><b>{{ tel.decisions }}</b><span>{{ t('cockpit.telemetry.decided', 'decided') }}</span></div>
        <div class="ckd-tel-cell">
          <b data-testid="ckd-tel-denialrate">{{ tel.denialRate == null ? '—' : Math.round(tel.denialRate * 100) + '%' }}</b>
          <span>{{ t('cockpit.telemetry.denialRate', 'denial rate') }}</span>
        </div>
        <div class="ckd-tel-cell"><b data-testid="ckd-tel-streak">{{ tel.longestStreak }}</b>
          <span>{{ t('cockpit.telemetry.streak', 'longest identical run') }}</span></div>
        <div class="ckd-tel-cell"><b>{{ tel.refused }}</b>
          <span>{{ t('cockpit.telemetry.refused', 'posture refusals') }}</span></div>
      </div>

      <div class="ckd-tel-hist" data-testid="ckd-tel-readhist">
        <span class="ckd-tel-hist-h">
          {{ t('cockpit.telemetry.readDist', 'read time') }}
          <em v-if="postureName" class="ckd-tel-floor-tag" data-testid="ckd-tel-floor">
            {{ tp('cockpit.telemetry.floorAt', 'floor {ms}', { ms: ms(readFloorMs) }) }}
          </em>
        </span>
        <div class="ckd-tel-bars">
          <div v-for="(c, i) in readHist.counts" :key="i" class="ckd-tel-bar-wrap"
               :class="{ 'is-floor': i === floorBucket }">
            <div class="ckd-tel-bar" :style="{ height: Math.round((c / readMax) * 100) + '%' }" />
            <span class="ckd-tel-edge">{{ EDGES[i] / 1000 }}s</span>
          </div>
          <div class="ckd-tel-bar-wrap">
            <div class="ckd-tel-bar" :style="{ height: Math.round((readHist.overflow / readMax) * 100) + '%' }" />
            <span class="ckd-tel-edge">+</span>
          </div>
        </div>
      </div>

      <ul v-if="Object.keys(tel.denyReasons).length" class="ckd-tel-reasons" data-testid="ckd-tel-reasons">
        <li v-for="(n, why) in tel.denyReasons" :key="why"><b>{{ n }}</b> {{ why }}</li>
      </ul>

      <p class="ckd-tel-foot">
        <RecordLink kind="consent" :label="t('cockpit.door.consent', 'Full evidence chain')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-tel { display: flex; flex-direction: column; gap: .45rem; }
.ckd-tel-line { margin: 0; font-size: .74rem; color: var(--nc-text-primary, #e6edf3); }
.ckd-tel-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: .3rem; }
.ckd-tel-cell { display: flex; flex-direction: column; align-items: flex-start;
  border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.07)); border-radius: 6px; padding: .25rem .35rem; }
.ckd-tel-cell b { font-size: .9rem; color: var(--nc-text-primary, #e6edf3); }
.ckd-tel-cell span { font-size: .58rem; letter-spacing: .04em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.ckd-tel-hist { display: flex; flex-direction: column; gap: .2rem; }
.ckd-tel-hist-h { font-size: .62rem; letter-spacing: .05em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.ckd-tel-floor-tag { font-style: normal; color: var(--nc-warning, #d29922); margin-left: .3rem; }
.ckd-tel-bars { display: flex; align-items: flex-end; gap: .18rem; height: 44px; }
.ckd-tel-bar-wrap { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; height: 100%; }
.ckd-tel-bar-wrap.is-floor { border-left: 2px solid var(--nc-warning, #d29922); }
.ckd-tel-bar { width: 100%; min-height: 1px; background: var(--nc-primary, #00e5ff); opacity: .5; border-radius: 2px 2px 0 0; }
.ckd-tel-edge { font-size: .55rem; color: var(--nc-text-muted, #6e7681); margin-top: .1rem; }
.ckd-tel-reasons { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: .35rem; font-size: .64rem; color: var(--nc-text-dim, #8b949e); }
.ckd-tel-reasons b { color: var(--nc-text-secondary, #c9d1d9); }
.ckd-tel-foot { margin: .3rem 0 0; font-size: .62rem; }
</style>
