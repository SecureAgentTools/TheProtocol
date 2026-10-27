<script setup lang="ts">
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPITBOOK — YOUR BOOK: every AGORA position this developer's agents hold, priced,
 * allocated, and charted.
 *
 * 🔴 WHY IT EXISTS. `PaneHoldings` follows the header agent switcher, which is right —
 * shares belong to an agent, not to a person. But that means it answers for ONE agent, and
 * on this account it said **"holds no shares on this venue"** while the fleet held
 * **2.7M shares across three listings**: the acting agent simply was not one of the ~80
 * that hold any. A per-agent rail cannot answer "what do I own".
 *
 * So this pane is the deliberate OPPOSITE convention, and says so on screen: it ignores the
 * switcher and answers for the whole account. Two panes, two questions, neither pretending
 * to be the other — the §FOREIGNACT law about labels matching the thing they describe.
 *
 * ⚠ TOTALS ARE PER CURRENCY AND NEVER MERGED (§SUMSPLIT). The server groups by the
 * listing's own currency and this pane renders one line each. A single number spanning AVT
 * and BVT is not a rounded number, it is a wrong one.
 *
 * ⚠ A MISSING MARK IS NOT A ZERO (§RAT). A listing that has never traded has `last: null`,
 * so its value is unknown rather than nothing — the position still shows its size and cost,
 * the value column says so, and the currency total declares how many positions it could not
 * price. A total that silently drops the unpriceable is a total that lies downward.
 *
 * ⚠ AND THE MARK IS AS OLD AS THE LAST TRADE. Every value here is marked to the last
 * trade, which on this venue can be days old; the pane states that age rather than letting
 * a stale print pass as a live quote (the §COCKPITSHOW market-tape rule).
 *
 * 🔴 THE CHART IS HAND-DRAWN SVG, ON PURPOSE. `chart.js` is in the tree, but it has no
 * candlestick without a plugin, and this project has already killed one Chart.js pane for
 * an auto-height feedback loop (§SYBILFIX). SVG costs no dependency, resolves CSS custom
 * properties (a canvas does NOT — §TICKERLAG, where an unparseable `var()` fillStyle
 * silently painted 2,354 invisible rectangles per frame), redraws only when the data
 * changes, and can be asserted on by a battery because every candle is an element.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { PANES } from './paneRegistry'
import { exchangeService, type MyBook, type BookPosition, type Candle } from '@/services/api/exchangeService'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const def = PANES.book

const book = ref<MyBook | null>(null)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
const sel = ref<string>('')            // selected symbol
const tf = ref<'15m' | '1h' | '1d'>('1h')
const candles = ref<Candle[]>([])
/** 🔴 WHICH symbol the drawn candles actually belong to.
 *  Reading the first screenshot caught the chart showing SYBIL's tape under GRLD's
 *  heading: the header follows `sel` instantly, the candles arrive one await later, and in
 *  between the pane confidently mislabelled a price series. That is the §FOREIGNACT defect
 *  in a chart — the label and the data disagreeing while both look fine. The svg now
 *  publishes the symbol it was BUILT from, so the mislabelling is impossible to miss and a
 *  battery can assert the two agree. */
const loadedSymbol = ref('')
/** Out-of-order responses are the other half: switch A→B→A quickly and A's slow reply can
 *  land last and overwrite B's. Only the newest request may commit. */
let candleSeq = 0
const candlesErr = ref('')
const candlesLoading = ref(false)
const hover = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

const TFS: { k: '15m' | '1h' | '1d'; label: string; limit: number }[] = [
  { k: '15m', label: '15M', limit: 192 },
  { k: '1h', label: '1H', limit: 168 },
  { k: '1d', label: '1D', limit: 120 },
]

async function load() {
  try {
    const b = await exchangeService.myBook(5)
    book.value = b
    err.value = ''; readAt.value = Date.now()
    if (!sel.value && b.positions.length) sel.value = b.positions[0].symbol
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}

async function loadCandles() {
  const seq = ++candleSeq
  const want = sel.value
  // Drop the old series FIRST: a chart that keeps painting while the symbol has already
  // changed is the mislabelling above, and "loading" is the honest state in between.
  candles.value = []
  loadedSymbol.value = ''
  hover.value = null
  if (!want) return
  candlesLoading.value = true
  const spec = TFS.find(x => x.k === tf.value)!
  try {
    const r = await exchangeService.candles(want, tf.value, spec.limit)
    if (seq !== candleSeq) return          // a newer request has already answered
    candles.value = r.candles || []
    loadedSymbol.value = want
    candlesErr.value = ''
  } catch (e: any) {
    if (seq !== candleSeq) return
    // ⚠ The chart failing must not blank the book. Two independent reads, two states.
    candles.value = []
    candlesErr.value = e?.response?.data?.detail || e?.message || 'could not read the tape'
  } finally { if (seq === candleSeq) candlesLoading.value = false }
}

onMounted(() => {
  void load().then(loadCandles)
  poll = setJitteredInterval(() => { void load() }, (def.pollSeconds ?? 60) * 1000)
})
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })
watch([sel, tf], () => { void loadCandles() })

const positions = computed<BookPosition[]>(() => book.value?.positions ?? [])
const empty = computed(() => !loading.value && positions.value.length === 0)
const selected = computed(() => positions.value.find(p => p.symbol === sel.value) || null)

const num = (v: string | null | undefined) => (v == null ? null : Number(v))

/** Compact for the big figures, exact in the title. A truncated number is a wrong number
 *  (§COCKPITPOLISH); compact notation announces its own rounding. */
function fmt(v: string | number | null | undefined, max = 2): string {
  const n = typeof v === 'string' ? Number(v) : v
  if (n == null || !Number.isFinite(n)) return '—'
  return nAuto(n, max)
}
function exact(v: string | number | null | undefined): string {
  const n = typeof v === 'string' ? Number(v) : v
  return n == null || !Number.isFinite(n) ? '—' : nFmt(n, 6)
}

/** Share of the book by market value, within the position's OWN currency — a percentage
 *  across currencies would be the merged-total mistake wearing a percent sign. */
function share(p: BookPosition): number | null {
  const c = book.value?.currencies.find(c => c.currency === p.currency)
  const tot = c ? Number(c.market_value) : 0
  const v = num(p.market_value)
  if (!tot || v == null) return null
  return (v / tot) * 100
}

function ageOf(iso: string | null | undefined): string {
  if (!iso) return '—'
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

/** The oldest mark in the book — the honest headline for "how fresh is any of this". */
const markAge = computed(() => {
  const ts = positions.value.map(p => p.last_trade_at).filter(Boolean) as string[]
  if (!ts.length) return null
  return ts.sort()[0]
})

/* ── the chart ───────────────────────────────────────────────────────────────────
 * Geometry in one computed so the template holds no arithmetic. */
const W = 780, H = 330, VOL_H = 58, L_PAD = 52, R_PAD = 8, T_PAD = 10, GAP = 14

const chart = computed(() => {
  const cs = candles.value
  if (!cs.length) return null
  const highs = cs.map(c => Number(c.h)), lows = cs.map(c => Number(c.l))
  let hi = Math.max(...highs), lo = Math.min(...lows)
  if (!Number.isFinite(hi) || !Number.isFinite(lo)) return null
  if (hi === lo) { hi = hi * 1.01 || 1; lo = lo * 0.99 }
  /* 🔴 A LINEAR AXIS IS UNREADABLE ON THIS VENUE, and the first screenshot proved it: GRLD
   * trades near 43 and its window carried a print at 7,398, so the axis ran 5.68→7,398.05
   * and every candle collapsed onto a flat line at the bottom. Nothing was wrong with the
   * data — AGORA prices are SUPPOSED to wander (the sim anchors fair at 20x IPO inside a
   * [0.5, 80] clamp), so an outlier is the normal case here, not the exception.
   * Clipping would hide real trades. A LOG axis shows every one of them and is what price
   * charts use for exactly this reason — and it is DECLARED on screen, because a reader who
   * mistakes a log axis for a linear one misreads every move on it. */
  const useLog = lo > 0 && hi / lo > 20
  const priceH = H - VOL_H - GAP - T_PAD
  const step = (W - L_PAD - R_PAD) / cs.length
  const bodyW = Math.max(1, Math.min(9, step * 0.62))
  const maxVol = Math.max(...cs.map(c => c.v || 0), 1)
  const lg = (v: number) => Math.log(Math.max(v, Number.MIN_VALUE))
  const y = useLog
    ? (p: number) => T_PAD + (lg(hi) - lg(Math.max(p, lo))) / (lg(hi) - lg(lo)) * priceH
    : (p: number) => T_PAD + (hi - p) / (hi - lo) * priceH
  const bars = cs.map((c, i) => {
    const o = Number(c.o), h = Number(c.h), l = Number(c.l), cl = Number(c.c)
    const x = L_PAD + i * step + step / 2
    const up = cl >= o
    const yo = y(o), yc = y(cl)
    return {
      i, x, up,
      wickTop: y(h), wickBot: y(l),
      bodyY: Math.min(yo, yc),
      bodyH: Math.max(1, Math.abs(yc - yo)),
      bodyX: x - bodyW / 2, bodyW,
      volY: H - (c.v / maxVol) * VOL_H,
      volH: Math.max(0.5, (c.v / maxVol) * VOL_H),
      t: c.t, o, h, l, c: cl, v: c.v,
    }
  })
  // Four gridlines, labelled — a chart with no scale is a shape, not a measurement.
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => ({
    y: T_PAD + f * priceH,
    v: useLog ? Math.exp(lg(hi) - f * (lg(hi) - lg(lo))) : hi - f * (hi - lo),
  }))
  return { bars, hi, lo, step, ticks, priceH, useLog, first: cs[0]?.t, last: cs[cs.length - 1]?.t }
})

const hovered = computed(() => {
  const ch = chart.value
  if (!ch || hover.value == null) return null
  return ch.bars[hover.value] ?? null
})

function onMove(e: MouseEvent) {
  const ch = chart.value
  if (!ch) return
  const svg = e.currentTarget as SVGSVGElement
  const r = svg.getBoundingClientRect()
  const xv = ((e.clientX - r.left) / r.width) * W
  const i = Math.floor((xv - L_PAD) / ch.step)
  hover.value = i >= 0 && i < ch.bars.length ? i : null
}

/** Window change over the drawn candles — the number a chart is usually read FOR. */
const windowChange = computed(() => {
  const ch = chart.value
  if (!ch || ch.bars.length < 2) return null
  const a = ch.bars[0].o, b = ch.bars[ch.bars.length - 1].c
  if (!a) return null
  return { abs: b - a, pct: ((b - a) / a) * 100, from: a, to: b }
})
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty" tall
             :empty-text="t('cockpit.book.empty', 'No agent on this account holds points on this market.')">
    <div class="bk" data-testid="bk-root">

      <!-- WHOSE book this is. The one thing a reader must not have to guess, because the
           pane next door follows the switcher and this one deliberately does not. -->
      <p class="bk-lede" data-testid="bk-lede">
        {{ tp('cockpit.book.lede',
              'Every position held by any agent on this account: {agents} of your agents hold points. This pane does not follow the agent switcher.',
              { agents: book?.agents_holding ?? 0 }) }}
      </p>

      <!-- Per-currency totals. One line each, never a single merged figure. -->
      <ul class="bk-tot" data-testid="bk-totals">
        <li v-for="c in book?.currencies || []" :key="c.currency" class="bk-tot-row" data-testid="bk-total">
          <span class="bk-tot-ccy">{{ c.currency }}</span>
          <span class="bk-tot-main" :title="exact(c.market_value)">{{ money(fmt(c.market_value)) }}</span>
          <span class="bk-tot-lab">{{ t('cockpit.book.value', 'market value') }}</span>
          <!-- §COCKPITTILES T3 — a compact headline ROUNDS, and the exact figure lived only
               in a `title`: invisible in a screenshot, on a touch screen, and to anyone
               reading the number out loud. It goes on screen, small and tabular, and only
               where compaction actually happened. Masked like every other amount. -->
          <span v-if="nIsCompact(c.market_value)" class="bk-tot-exact" data-testid="bk-exact">
            {{ money(exact(c.market_value)) }}
          </span>
          <span class="bk-tot-cost" :title="exact(c.cost_basis)">
            {{ tp('cockpit.book.cost', 'cost {v}', { v: money(fmt(c.cost_basis)) }) }}
          </span>
          <span class="bk-tot-pnl" :class="Number(c.unrealized_pnl) >= 0 ? 'is-up' : 'is-down'"
                :title="exact(c.unrealized_pnl)">
            {{ Number(c.unrealized_pnl) >= 0 ? '+' : '' }}{{ money(fmt(c.unrealized_pnl)) }}
            <!-- A gain with no stated baseline is not a figure, it is a mood. -->
            <em class="bk-tot-since">{{ t('cockpit.book.vsCost', 'vs cost') }}</em>
          </span>
          <span v-if="c.unpriced_positions" class="bk-tot-warn"
                :title="t('cockpit.book.unpricedHint', 'These positions have never traded, so they carry no mark. The total above is therefore a floor, not the whole book.')">
            {{ tp('cockpit.book.unpriced', '{n} unpriced', { n: c.unpriced_positions }) }}
          </span>
        </li>
      </ul>

      <!-- Allocation, by market value, within each currency. -->
      <div v-if="positions.length" class="bk-alloc" data-testid="bk-alloc">
        <div class="bk-alloc-bar">
          <button v-for="p in positions" :key="p.symbol" class="bk-alloc-seg"
                  :class="{ 'is-sel': p.symbol === sel, 'is-unpriced': p.market_value == null }"
                  :style="{ flexGrow: String(Math.max(0.01, share(p) ?? 0.5)) }"
                  :data-symbol="p.symbol" data-testid="bk-alloc-seg"
                  :title="`${p.symbol} · ${share(p) == null ? t('cockpit.book.noMark', 'no mark') : fmt(share(p), 1) + '%'}`"
                  @click="sel = p.symbol">
            <span class="bk-alloc-lab">{{ p.symbol }}</span>
          </button>
        </div>
      </div>

      <!-- The book itself. -->
      <div class="bk-tablewrap">
        <table class="bk-table" data-testid="bk-table">
          <thead>
            <tr>
              <th>{{ t('cockpit.book.colSymbol', 'Symbol') }}</th>
              <th class="n">{{ t('cockpit.book.colQty', 'Points') }}</th>
              <th class="n">{{ t('cockpit.book.colAvg', 'Avg cost') }}</th>
              <th class="n">{{ t('cockpit.book.colLast', 'Last') }}</th>
              <th class="n">{{ t('cockpit.book.colValue', 'Value') }}</th>
              <th class="n">{{ t('cockpit.book.colPnl', 'Unrealized') }}</th>
              <th class="n">{{ t('cockpit.book.colShare', 'Weight') }}</th>
              <th class="n">{{ t('cockpit.book.colHolders', 'Agents') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in positions" :key="p.symbol" class="bk-row" data-testid="bk-row"
                :class="{ 'is-sel': p.symbol === sel }" @click="sel = p.symbol">
              <td>
                <span class="bk-sym">{{ p.symbol }}</span>
                <span class="bk-ccy">{{ p.currency }}</span>
                <span v-if="p.locked_qty" class="bk-lock"
                      :title="tp('cockpit.book.lockedHint', '{n} points are locked behind open sell orders', { n: p.locked_qty })">
                  {{ tp('cockpit.book.locked', '{n} locked', { n: p.locked_qty }) }}
                </span>
              </td>
              <td class="n" :title="exact(p.qty)">{{ fmt(p.qty, 0) }}</td>
              <td class="n" :title="exact(p.avg_cost)">{{ money(fmt(p.avg_cost, 4)) }}</td>
              <!-- null last ⇒ never traded. Said, not rendered as 0. -->
              <td class="n" :class="{ 'is-none': p.last == null }" :title="exact(p.last)">
                {{ p.last == null ? t('cockpit.book.noMark', 'no mark') : money(fmt(p.last, 4)) }}
              </td>
              <td class="n" :class="{ 'is-none': p.market_value == null }" :title="exact(p.market_value)">
                {{ p.market_value == null ? '—' : money(fmt(p.market_value)) }}
              </td>
              <td class="n" :class="p.unrealized_pnl == null ? 'is-none' : (Number(p.unrealized_pnl) >= 0 ? 'is-up' : 'is-down')"
                  :title="exact(p.unrealized_pnl)">
                {{ p.unrealized_pnl == null ? '—' : (Number(p.unrealized_pnl) >= 0 ? '+' : '') + money(fmt(p.unrealized_pnl)) }}
              </td>
              <td class="n">{{ share(p) == null ? '—' : fmt(share(p), 1) + '%' }}</td>
              <td class="n" :title="t('cockpit.book.holdersHint', 'How many of your agents hold this symbol')">{{ p.holders }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- The chart for whichever row is selected. -->
      <section v-if="selected" class="bk-chart" data-testid="bk-chart">
        <header class="bk-chart-head">
          <span class="bk-chart-sym">{{ selected.symbol }}</span>
          <span v-if="selected.display_name" class="bk-chart-name">{{ selected.display_name }}</span>
          <span v-if="windowChange" class="bk-chart-chg" :class="windowChange.abs >= 0 ? 'is-up' : 'is-down'"
                data-testid="bk-window-change">
            {{ windowChange.abs >= 0 ? '+' : '' }}{{ fmt(windowChange.pct, 2) }}%
            <span class="bk-chart-chg-abs">{{ windowChange.abs >= 0 ? '+' : '' }}{{ money(fmt(windowChange.abs, 4)) }}</span>
          </span>
          <span class="bk-spacer" />
          <!-- A log axis that does not say so makes every move on it read wrong. -->
          <span v-if="chart?.useLog" class="bk-scale" data-testid="bk-scale"
                :title="t('cockpit.book.logHint', 'This price axis is logarithmic. The window spans more than a 20x range, and a linear axis would flatten every candle against the extreme.')">
            {{ t('cockpit.book.log', 'log') }}
          </span>
          <button v-for="x in TFS" :key="x.k" class="bk-tf" :class="{ 'is-on': tf === x.k }"
                  :data-testid="`bk-tf-${x.k}`" @click="tf = x.k">{{ x.label }}</button>
        </header>

        <p v-if="candlesErr" class="bk-chart-err" data-testid="bk-chart-err">{{ candlesErr }}</p>
        <p v-else-if="!candlesLoading && !chart" class="bk-chart-none" data-testid="bk-chart-none">
          {{ t('cockpit.book.noTape', 'No trades in this window — the chart is empty because the tape is, not because it failed.') }}
        </p>

        <svg v-else-if="chart" class="bk-svg" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none"
             data-testid="bk-svg" :data-symbol="loadedSymbol" :data-scale="chart.useLog ? 'log' : 'linear'"
             @mousemove="onMove" @mouseleave="hover = null">
          <!-- scale first, so the candles are read against it -->
          <g class="bk-grid">
            <template v-for="(tk, i) in chart.ticks" :key="i">
              <line :x1="L_PAD" :x2="W - R_PAD" :y1="tk.y" :y2="tk.y" />
              <text :x="L_PAD - 5" :y="tk.y + 3" text-anchor="end">{{ fmt(tk.v, 2) }}</text>
            </template>
          </g>
          <g class="bk-vol">
            <rect v-for="b in chart.bars" :key="`v${b.i}`" :x="b.bodyX" :y="b.volY"
                  :width="b.bodyW" :height="b.volH" :class="b.up ? 'is-up' : 'is-down'" />
          </g>
          <g class="bk-candles">
            <template v-for="b in chart.bars" :key="b.i">
              <line class="bk-wick" :class="b.up ? 'is-up' : 'is-down'"
                    :x1="b.x" :x2="b.x" :y1="b.wickTop" :y2="b.wickBot" />
              <rect class="bk-body" :class="b.up ? 'is-up' : 'is-down'" data-testid="bk-candle"
                    :x="b.bodyX" :y="b.bodyY" :width="b.bodyW" :height="b.bodyH" />
            </template>
          </g>
          <line v-if="hovered" class="bk-cross" :x1="hovered.x" :x2="hovered.x" :y1="T_PAD" :y2="H" />
        </svg>

        <!-- The readout: a chart you cannot read a value off is decoration. -->
        <p class="bk-read" data-testid="bk-readout">
          <template v-if="hovered">
            <span class="bk-read-t">{{ nWhen(hovered.t) }}</span>
            <span>O {{ fmt(hovered.o, 4) }}</span><span>H {{ fmt(hovered.h, 4) }}</span>
            <span>L {{ fmt(hovered.l, 4) }}</span><span>C {{ fmt(hovered.c, 4) }}</span>
            <span>V {{ fmt(hovered.v, 0) }}</span>
          </template>
          <template v-else>
            {{ tp('cockpit.book.readoutIdle', '{n} candles · {tf} · hover for one', { n: chart?.bars.length ?? 0, tf }) }}
          </template>
        </p>

        <!-- Who on this account holds it. Named, because a DID is not an identity. -->
        <p v-if="selected.top_holders.length" class="bk-holders" data-testid="bk-holders">
          <span class="bk-holders-h">{{ t('cockpit.book.heldBy', 'Held by') }}</span>
          <span v-for="h in selected.top_holders" :key="h.agent_did" class="bk-holder" :title="h.agent_did">
            {{ h.name || h.agent_did.slice(0, 22) }}
            <b>{{ fmt(h.qty, 0) }}</b>
          </span>
        </p>
      </section>

      <p class="bk-foot" data-testid="bk-foot">
        {{ tp('cockpit.book.foot',
              'Marked to the last trade, not a live quote: the freshest mark here is {age} old. Distributions received: {legs} legs, {amt}.',
              { age: ageOf(markAge), legs: book?.dividends.legs ?? 0, amt: money(fmt(book?.dividends.amount)) }) }}
        <RecordLink kind="exchange" class="ckd-doorsep"
                    :label="t('cockpit.door.exchange', 'Open the market')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.bk { display: flex; flex-direction: column; gap: .5rem; font-size: .72rem; }
.bk-lede { margin: 0; font-size: .66rem; color: var(--nc-text-muted, #6e7681); line-height: 1.45; }

.bk-tot { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .25rem; }
.bk-tot-row {
  display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap;
  padding: .35rem .5rem; border: 1px solid var(--nc-border, rgba(255,255,255,.08));
  border-radius: 8px; background: rgba(var(--nc-primary-rgb, 0,229,255), .03);
}
.bk-tot-ccy { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .62rem;
  letter-spacing: .08em; color: var(--nc-primary, #00e5ff); }
.bk-tot-main { font-size: 1.15rem; font-weight: 600; font-variant-numeric: tabular-nums;
  color: var(--nc-text-primary, #e6edf3); }
.bk-tot-exact { grid-column: 2 / -1; font-size: .62rem; color: var(--nc-text-dim, #8b949e);
  font-variant-numeric: tabular-nums; font-family: var(--nc-font-mono, ui-monospace, monospace); }
.bk-tot-since { font-style: normal; font-size: .56rem; opacity: .75; margin-left: .25rem; }
.bk-tot-lab { font-size: .6rem; text-transform: uppercase; letter-spacing: .06em;
  color: var(--nc-text-muted, #6e7681); }
.bk-tot-cost, .bk-tot-pnl { font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-size: .68rem; font-variant-numeric: tabular-nums; }
.bk-tot-cost { color: var(--nc-text-dim, #8b949e); }
.bk-tot-warn { font-size: .6rem; color: var(--nc-warning, #d29922); }

.bk-alloc-bar { display: flex; gap: 2px; height: 22px; }
.bk-alloc-seg {
  flex: 1 1 auto; min-width: 12px; border: 0; border-radius: 3px; cursor: pointer;
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb,0,229,255),.55), rgba(var(--nc-primary-rgb,0,229,255),.28));
  color: var(--nc-bg, #05050a); font-size: .58rem; font-weight: 700; letter-spacing: .04em;
  overflow: hidden; white-space: nowrap; padding: 0 .2rem;
}
.bk-alloc-seg.is-sel { outline: 1px solid var(--nc-primary, #00e5ff); outline-offset: 1px; }
.bk-alloc-seg.is-unpriced { background: repeating-linear-gradient(45deg,
  rgba(255,255,255,.10) 0 4px, rgba(255,255,255,.03) 4px 8px); color: var(--nc-text-dim, #8b949e); }

.bk-tablewrap { overflow-x: auto; }
.bk-table { width: 100%; border-collapse: collapse; font-size: .68rem; }
.bk-table th {
  text-align: left; font-size: .58rem; text-transform: uppercase; letter-spacing: .06em;
  color: var(--nc-text-muted, #6e7681); font-weight: 600; padding: .2rem .35rem;
  border-bottom: 1px solid var(--nc-border, rgba(255,255,255,.08)); white-space: nowrap;
}
.bk-table th.n, .bk-table td.n { text-align: right; font-variant-numeric: tabular-nums;
  font-family: var(--nc-font-mono, ui-monospace, monospace); }
.bk-table td { padding: .25rem .35rem; border-bottom: 1px solid var(--nc-border-subtle, rgba(255,255,255,.04)); }
.bk-row { cursor: pointer; }
.bk-row:hover { background: rgba(255,255,255,.03); }
.bk-row.is-sel { background: rgba(var(--nc-primary-rgb, 0,229,255), .07); }
.bk-sym { font-weight: 700; color: var(--nc-text-primary, #e6edf3); }
.bk-ccy { margin-left: .3rem; font-size: .56rem; color: var(--nc-text-muted, #6e7681); }
.bk-lock { margin-left: .3rem; font-size: .56rem; color: var(--nc-warning, #d29922); }
.is-up { color: var(--nc-success, #3fb950); }
.is-down { color: var(--nc-danger, #f85149); }
.is-none { color: var(--nc-text-muted, #6e7681); }

.bk-chart { display: flex; flex-direction: column; gap: .3rem; }
.bk-chart-head { display: flex; align-items: baseline; gap: .45rem; flex-wrap: wrap; }
.bk-chart-sym { font-weight: 700; letter-spacing: .04em; }
.bk-chart-name { font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.bk-chart-chg { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .72rem; font-weight: 600; }
.bk-chart-chg-abs { font-size: .6rem; opacity: .75; margin-left: .2rem; }
.bk-spacer { flex: 1; }
.bk-scale { font-size: .56rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--nc-warning, #d29922); border: 1px solid rgba(210,153,34,.35);
  border-radius: 4px; padding: .02rem .28rem; }
.bk-tf {
  border: 1px solid var(--nc-border, rgba(255,255,255,.12)); background: transparent;
  color: var(--nc-text-dim, #8b949e); border-radius: 5px; padding: .05rem .35rem;
  font-size: .58rem; letter-spacing: .06em; cursor: pointer;
}
.bk-tf.is-on { color: var(--nc-primary, #00e5ff); border-color: var(--nc-primary, #00e5ff); }
.bk-svg { width: 100%; height: 330px; display: block; }
.bk-grid line { stroke: var(--nc-border-subtle, rgba(255,255,255,.06)); stroke-width: 1; }
.bk-grid text { fill: var(--nc-text-muted, #6e7681); font-size: 9px;
  font-family: var(--nc-font-mono, ui-monospace, monospace); }
.bk-wick { stroke-width: 1; }
.bk-wick.is-up, .bk-body.is-up { stroke: var(--nc-success, #3fb950); fill: var(--nc-success, #3fb950); }
.bk-wick.is-down, .bk-body.is-down { stroke: var(--nc-danger, #f85149); fill: var(--nc-danger, #f85149); }
.bk-vol rect { opacity: .28; }
.bk-cross { stroke: var(--nc-primary, #00e5ff); stroke-width: 1; stroke-dasharray: 2 2; opacity: .7; }
.bk-read { margin: 0; display: flex; gap: .6rem; flex-wrap: wrap; font-size: .62rem;
  font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-dim, #8b949e); }
.bk-read-t { color: var(--nc-text-secondary, #c9d1d9); }
.bk-chart-err { margin: 0; font-size: .64rem; color: var(--nc-danger, #f85149); }
.bk-chart-none { margin: 0; font-size: .64rem; color: var(--nc-text-muted, #6e7681); }

.bk-holders { margin: 0; display: flex; gap: .4rem; flex-wrap: wrap; font-size: .62rem; align-items: baseline; }
.bk-holders-h { font-size: .58rem; text-transform: uppercase; letter-spacing: .06em;
  color: var(--nc-text-muted, #6e7681); }
.bk-holder { color: var(--nc-text-dim, #8b949e); }
.bk-holder b { color: var(--nc-text-secondary, #c9d1d9); font-variant-numeric: tabular-nums; margin-left: .15rem; }

.bk-foot { margin: .1rem 0 0; font-size: .6rem; color: var(--nc-text-muted, #6e7681); line-height: 1.45; }
.ckd-doorsep { margin-left: .4rem; }
</style>
