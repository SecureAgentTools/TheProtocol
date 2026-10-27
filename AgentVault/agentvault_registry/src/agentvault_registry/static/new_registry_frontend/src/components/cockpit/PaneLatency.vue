<script setup lang="ts">
/**
 * §COCKPIT P5 — LATENCY. The instrument shows its own numbers (§12).
 *
 * Three legs, all from SERVER timestamps (R5):
 *   RAISE→ARRIVE  challenge created → a surface acked PRESENTING it. An ARRIVAL, not a
 *                 send: the WS cue and the push are both best-effort, and R6's rule is
 *                 that measuring the send would quietly report the wrong leg — an
 *                 accelerator that stopped accelerating looks exactly like one that works.
 *   READ          ack → resolved. How long the human had it in front of them.
 *   CONSENT       created → resolved. The whole ask, end to end.
 *
 * `n` and `missing` are rendered beside every percentile on purpose. A p95 over four
 * samples is a number, not a measurement, and a pane that hides its sample size invites
 * exactly the confidence it has not earned.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { liabilityApi, type Receipt } from '@/services/api/liability'
import { useI18n } from '@/composables/useI18n'
import { useCockpitBus } from '@/composables/useCockpitBus'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { legStat, bucketise, type LegStat } from './receiptStats'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.latency

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

const legs = computed<LegStat[]>(() =>
  (['arrive', 'read', 'consent'] as const).map(k => legStat(receipts.value, k)))
const empty = computed(() => !loading.value && legs.value.every(l => l.n === 0))

const EDGES = [250, 500, 1000, 2000, 5000, 15000]
const hist = computed(() => {
  const vals = receipts.value
    .map(r => r.legs_ms?.consent)
    .filter((v): v is number => typeof v === 'number' && v >= 0)
  return bucketise(vals, EDGES)
})
const histMax = computed(() => Math.max(1, ...hist.value.counts, hist.value.overflow))

const ms = (v: number | null) => (v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}s` : `${v}ms`)
const legLabel = (k: string) => ({
  arrive: t('cockpit.latency.arrive', 'raise → arrive'),
  read: t('cockpit.latency.read', 'read'),
  consent: t('cockpit.latency.consent', 'raise → consent'),
}[k] || k)

useCockpitBus({ 'liability.resolved': () => { void load() } })
// §COCKPITDESK (2026-10-14): the chip says this pane re-reads every 60 s, and it did not: it read at open and then only
// on a 'liability.resolved' cue, so a missed cue (a dropped socket) left it as old as the page. The poll makes the chip
// true; the cue stays, so a decision still shows at once.
let poll: ReturnType<typeof setInterval> | null = null
onMounted(() => { void load(); poll = setJitteredInterval(() => { void load() }, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })
</script>

<template>
  <PaneShell
    :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
    :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
    :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
    :empty-text="t('cockpit.latency.empty', 'No decisions measured yet.')"
  >
    <div class="ckd-latency" data-testid="ckd-latency">
      <table class="ckd-lat-tbl">
        <thead>
          <tr>
            <th>{{ t('cockpit.latency.leg', 'leg') }}</th>
            <th>p50</th><th>p95</th><th>n</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in legs" :key="l.key" :data-testid="`ckd-lat-${l.key}`">
            <td class="ckd-lat-name">{{ legLabel(l.key) }}</td>
            <td class="ckd-lat-num">{{ ms(l.p50) }}</td>
            <td class="ckd-lat-num">{{ ms(l.p95) }}</td>
            <td class="ckd-lat-n">
              {{ l.n }}<span v-if="l.missing" class="ckd-lat-miss"
                :title="t('cockpit.latency.missingHint', 'Receipts where this leg was never observed. Excluded, not counted as zero.')"
              > +{{ l.missing }}?</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="ckd-lat-hist" data-testid="ckd-lat-hist">
        <span class="ckd-lat-hist-h">{{ t('cockpit.latency.histogram', 'raise → consent') }}</span>
        <div class="ckd-lat-bars">
          <div v-for="(c, i) in hist.counts" :key="i" class="ckd-lat-bar-wrap">
            <div class="ckd-lat-bar" :style="{ height: Math.round((c / histMax) * 100) + '%' }" />
            <span class="ckd-lat-edge">{{ EDGES[i] >= 1000 ? (EDGES[i] / 1000) + 's' : EDGES[i] + 'ms' }}</span>
          </div>
          <div class="ckd-lat-bar-wrap">
            <div class="ckd-lat-bar ckd-lat-bar--over"
                 :style="{ height: Math.round((hist.overflow / histMax) * 100) + '%' }" />
            <span class="ckd-lat-edge">+</span>
          </div>
        </div>
      </div>

      <p class="ckd-lat-note" data-testid="ckd-lat-note">
        {{ tp('cockpit.latency.note',
              'From {n} receipts, server clocks only. A missing leg is excluded, never counted as zero.',
              { n: receipts.length }) }}
        <RecordLink kind="consent" class="ckd-doorsep"
                    :label="t('cockpit.door.consent', 'Full evidence chain')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-latency { display: flex; flex-direction: column; gap: .45rem; }
.ckd-lat-tbl { width: 100%; border-collapse: collapse; font-size: .7rem; }
.ckd-lat-tbl th { text-align: left; font-weight: 500; font-size: .62rem; letter-spacing: .05em;
  text-transform: uppercase; color: var(--nc-text-muted, #6e7681); padding-bottom: .15rem; }
.ckd-lat-tbl td { padding: .1rem 0; }
.ckd-lat-name { color: var(--nc-text-secondary, #c9d1d9); }
.ckd-lat-num { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-primary, #e6edf3); }
.ckd-lat-n { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-dim, #8b949e); }
.ckd-lat-miss { color: var(--nc-warning, #d29922); }
.ckd-lat-hist { display: flex; flex-direction: column; gap: .2rem; }
.ckd-lat-hist-h { font-size: .62rem; letter-spacing: .05em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.ckd-lat-bars { display: flex; align-items: flex-end; gap: .18rem; height: 46px; }
.ckd-lat-bar-wrap { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; height: 100%; }
.ckd-lat-bar { width: 100%; min-height: 1px; background: var(--nc-primary, #00e5ff); opacity: .55; border-radius: 2px 2px 0 0; }
.ckd-lat-bar--over { background: var(--nc-warning, #d29922); }
.ckd-lat-edge { font-size: .55rem; color: var(--nc-text-muted, #6e7681); margin-top: .1rem; }
.ckd-lat-note { margin: 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.ckd-doorsep { margin-left: .4rem; }
</style>
