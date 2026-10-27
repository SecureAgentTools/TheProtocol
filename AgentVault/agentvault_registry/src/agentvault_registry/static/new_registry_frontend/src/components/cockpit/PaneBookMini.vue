<script setup lang="ts">
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPITBOOK — the one-column form of YOUR BOOK.
 *
 * Same rail, same rules, a fifth of the space: per-currency totals (never merged), the
 * three largest positions, and a sparkline of the leader's close. For a board where the
 * full analytics pane would crowd out the operational panes beside it.
 *
 * ⚠ It reads the SAME endpoint as `PaneBook` and derives everything from it — a second
 * "what do I own" query would be a second answer to the question, and the two would drift.
 * The sparkline is the only extra read, and it is the same candles rail the big pane uses.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { PANES } from './paneRegistry'
import { exchangeService, type MyBook, type Candle } from '@/services/api/exchangeService'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const def = PANES.bookmini

const book = ref<MyBook | null>(null)
const spark = ref<Candle[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const b = await exchangeService.myBook(0)   // no holder names needed at this size
    book.value = b
    err.value = ''; readAt.value = Date.now()
    const lead = b.positions[0]
    if (lead) {
      try { spark.value = (await exchangeService.candles(lead.symbol, '1d', 60)).candles || [] }
      catch { spark.value = [] }   // the sparkline is decoration; the totals are not
    }
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const top = computed(() => (book.value?.positions ?? []).slice(0, 3))
const empty = computed(() => !loading.value && !(book.value?.positions.length))

function fmt(v: string | number | null | undefined, max = 2): string {
  const n = typeof v === 'string' ? Number(v) : v
  if (n == null || !Number.isFinite(n)) return '—'
  return nAuto(n, max)
}

/** A polyline over the closes. No axis on purpose — a sparkline is a SHAPE, and labelling
 *  it would imply a precision this size cannot carry. The big pane is where you read
 *  values off a scale. */
const sparkPath = computed(() => {
  const cs = spark.value
  if (cs.length < 2) return ''
  const ys = cs.map(c => Number(c.c))
  const hi = Math.max(...ys), lo = Math.min(...ys)
  const span = hi - lo || 1
  const W = 200, H = 34
  return cs.map((c, i) => {
    const x = (i / (cs.length - 1)) * W
    const y = H - ((Number(c.c) - lo) / span) * (H - 4) - 2
    return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})
const sparkUp = computed(() => {
  const cs = spark.value
  return cs.length >= 2 && Number(cs[cs.length - 1].c) >= Number(cs[0].c)
})
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.book.empty', 'No agent on this account holds points on this market.')">
    <div class="bm" data-testid="bm-root">
      <div v-for="c in book?.currencies || []" :key="c.currency" class="bm-tot" data-testid="bm-total">
        <span class="bm-val">{{ money(fmt(c.market_value)) }}</span>
        <span class="bm-ccy">{{ c.currency }}</span>
        <span v-if="nIsCompact(c.market_value)" class="bm-exact" data-testid="bm-exact">
          {{ money(nFmt(c.market_value, 2)) }}
        </span>
        <span class="bm-pnl" :class="Number(c.unrealized_pnl) >= 0 ? 'is-up' : 'is-down'">
          {{ Number(c.unrealized_pnl) >= 0 ? '+' : '' }}{{ money(fmt(c.unrealized_pnl)) }}
          <em class="bm-since">{{ t('cockpit.book.vsCost', 'vs cost') }}</em>
        </span>
      </div>

      <svg v-if="sparkPath" class="bm-spark" viewBox="0 0 200 34" preserveAspectRatio="none"
           data-testid="bm-spark" :class="sparkUp ? 'is-up' : 'is-down'">
        <path :d="sparkPath" fill="none" stroke-width="1.5" vector-effect="non-scaling-stroke" />
      </svg>
      <!-- §COCKPITTILES T3 — the sparkline is 60 daily closes of the LARGEST position, not
           the book. Unlabelled it reads as the whole account's history, which is a stronger
           claim than the data supports. Same rule the candle chart's log axis follows: a
           chart states what it is of. -->
      <p v-if="sparkPath" class="bm-sparklab" data-testid="bm-sparklab">
        {{ tp('cockpit.book.sparkOf', '60d · {sym} close', { sym: top[0]?.symbol || '—' }) }}
      </p>

      <ul class="bm-list">
        <li v-for="p in top" :key="p.symbol" class="bm-row" data-testid="bm-row">
          <span class="bm-sym">{{ p.symbol }}</span>
          <span class="bm-qty">{{ fmt(p.qty, 0) }}</span>
          <span class="bm-mv" :class="{ 'is-none': p.market_value == null }">
            {{ p.market_value == null ? t('cockpit.book.noMark', 'no mark') : money(fmt(p.market_value)) }}
          </span>
        </li>
      </ul>

      <p class="bm-foot">
        {{ tp('cockpit.book.miniFoot', '{n} of your agents hold points · whole account, not the acting agent',
              { n: book?.agents_holding ?? 0 }) }}
        <RecordLink kind="exchange" class="ckd-doorsep"
                    :label="t('cockpit.door.exchange', 'Open the market')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.bm { display: flex; flex-direction: column; gap: .35rem; }
.bm-tot { display: flex; align-items: baseline; gap: .35rem; }
.bm-val { font-size: 1.1rem; font-weight: 600; font-variant-numeric: tabular-nums;
  color: var(--nc-text-primary, #e6edf3); }
.bm-ccy { font-size: .6rem; letter-spacing: .06em; color: var(--nc-primary, #00e5ff); }
.bm-pnl { margin-left: auto; font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-size: .68rem; font-variant-numeric: tabular-nums; }
.bm-spark { width: 100%; height: 34px; display: block; }
.bm-spark.is-up path { stroke: var(--nc-success, #3fb950); }
.bm-spark.is-down path { stroke: var(--nc-danger, #f85149); }
.bm-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .12rem; }
.bm-row { display: flex; align-items: baseline; gap: .4rem; font-size: .68rem; }
.bm-sym { font-weight: 600; flex: 1; }
.bm-qty { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .62rem;
  font-variant-numeric: tabular-nums; color: var(--nc-text-muted, #6e7681); }
.bm-mv { font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  color: var(--nc-text-dim, #8b949e); width: 5.2rem; text-align: right; }
.is-up { color: var(--nc-success, #3fb950); }
.is-down { color: var(--nc-danger, #f85149); }
.is-none { color: var(--nc-text-muted, #6e7681); }
.bm-exact { font-size: .6rem; color: var(--nc-text-dim, #8b949e);
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums; }
.bm-since { font-style: normal; font-size: .55rem; opacity: .75; margin-left: .2rem; }
.bm-sparklab { margin: 0; font-size: .55rem; color: var(--nc-text-muted, #6e7681); letter-spacing: .04em; }
.bm-foot { margin: .1rem 0 0; font-size: .58rem; color: var(--nc-text-muted, #6e7681); line-height: 1.4; }
.ckd-doorsep { margin-left: .4rem; }
</style>
