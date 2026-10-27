<script setup lang="ts">
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPITSHOW C2a — THE MARKET, on the desk. HIS ASK: *"i want a trading modul. showing
 * your holdings and a ticker of what is selling etc. the whole thing can be multiple
 * moduls."* — this is the "what is selling" half; holdings are `PaneHoldings`, because
 * they answer different questions and need different authority (public venue data here,
 * the acting agent's own JWT there).
 *
 * Pure mount: `exchangeService.listings()` and `.trades()` already existed. No new route.
 *
 * 🔴 THE HONESTY THIS PANE IS BUILT AROUND: a 24-hour window over a venue that has not
 * traded today reports `volume_24h 0 · trades_24h 0 · change null`, which renders exactly
 * like a market that is broken. Measured on registry-a while writing this: the last GRLD
 * trade was **2026-08-27**, four days back, because the AGORA sim is off. So the pane
 * shows the last price WITH ITS AGE. "43.28, four days ago" is a market that is quiet;
 * "43.28" alone is a lie about liquidity, and "—" would be a lie about the price.
 *
 * ⚠ `change_24h_pct: null` is NOT 0%. Null means no comparison was possible; zero means
 * the price did not move. They render differently here for the same reason `no traffic
 * recorded` is not `0% success` on the agents pane (§RAT).
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { PANES } from './paneRegistry'
import { exchangeService, type Listing, type Tape } from '@/services/api/exchangeService'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const def = PANES.market

const listings = ref<Listing[]>([])
const tape = ref<Array<Tape & { symbol: string }>>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

const num = (v: unknown): number | null => {
  const n = Number(v)
  return v === null || v === undefined || v === '' || !Number.isFinite(n) ? null : n
}

/** Ranked by value at last price (points × price): the biggest thing on the market is what a glance should land on. */
const ranked = computed(() =>
  [...listings.value]
    .filter(l => l.status !== 'delisted')
    .sort((a, b) => (num(b.stats?.market_cap) ?? 0) - (num(a.stats?.market_cap) ?? 0)))

const tradedToday = computed(() => ranked.value.filter(l => (l.stats?.trades_24h ?? 0) > 0).length)
const halted = computed(() => ranked.value.filter(l => l.status === 'halted').length)

async function load() {
  try {
    const r = await exchangeService.listings()
    listings.value = r.listings || []
    err.value = ''; readAt.value = Date.now()
    // The tape is assembled from the top few symbols rather than a venue-wide feed,
    // because there is no venue-wide trade endpoint and inventing one for a pane would be
    // machinery where a door will do. Bounded to 4 calls, whatever the venue holds.
    const top = ranked.value.slice(0, 4)
    const got = await Promise.all(top.map(async l => {
      try {
        const tr = await exchangeService.trades(l.symbol, 8)
        return (tr.trades || []).map(x => ({ ...x, symbol: l.symbol }))
      } catch { return [] }
    }))
    tape.value = got.flat()
      .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
      .slice(0, 12)
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const empty = computed(() => !loading.value && ranked.value.length === 0)

function price(l: Listing): string {
  const p = num(l.stats?.last)
  if (p === null) return '—'
  return money(nFmt(p, 2))
}

/** null → "—" and a title saying why; 0 → "0.0%". Two different silences. */
function change(l: Listing): { text: string; tone: string; title: string } {
  const c = num(l.stats?.change_24h_pct)
  if (c === null) {
    return { text: '—', tone: 'is-flat',
             title: t('cockpit.mkt.noChange', 'No 24h comparison — this listing has not traded in the window. Not the same as unchanged.') }
  }
  return {
    text: `${c > 0 ? '+' : ''}${c.toFixed(1)}%`,
    tone: c > 0 ? 'is-up' : c < 0 ? 'is-down' : 'is-flat',
    title: t('cockpit.mkt.changeHint', 'Change over the last 24 hours'),
  }
}

function ago(iso?: string | null): string {
  if (!iso) return ''
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}
const lastTradeAt = computed(() => tape.value.length ? tape.value[0].at : null)
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.mkt.empty', 'This registry serves no AGORA listings.')">
    <div class="mkt" data-testid="ckd-market" data-tour="cockpit-market">
      <table class="mkt-t">
        <thead>
          <tr>
            <th class="mkt-sym">{{ t('cockpit.mkt.sym', 'symbol') }}</th>
            <th class="mkt-n">{{ t('cockpit.mkt.last', 'last') }}</th>
            <th class="mkt-n">{{ t('cockpit.mkt.chg', '24h') }}</th>
            <th class="mkt-n">{{ t('cockpit.mkt.bidask', 'bid / ask') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in ranked" :key="l.id" data-testid="mkt-row" :class="{ 'is-halted': l.status === 'halted' }">
            <td class="mkt-sym" :title="l.display_name">
              {{ l.symbol }}
              <span v-if="l.status === 'halted'" class="mkt-halt" data-testid="mkt-halted">{{ t('cockpit.mkt.halted', 'halted') }}</span>
              <span v-else-if="l.status === 'ipo'" class="mkt-ipo">{{ t('cockpit.mkt.ipo', 'Launch') }}</span>
            </td>
            <td class="mkt-n" data-testid="mkt-price">{{ price(l) }}<span class="mkt-ccy">{{ l.currency }}</span></td>
            <td class="mkt-n" :class="change(l).tone" :title="change(l).title" data-testid="mkt-change">{{ change(l).text }}</td>
            <td class="mkt-n mkt-dim">
              {{ money(l.stats?.best_bid ? Number(l.stats.best_bid).toFixed(2) : '—') }}
              /
              {{ money(l.stats?.best_ask ? Number(l.stats.best_ask).toFixed(2) : '—') }}
            </td>
          </tr>
        </tbody>
      </table>

      <!-- THE TAPE — what actually changed hands, newest first, each carrying its age. -->
      <div v-if="tape.length" class="mkt-tape" data-testid="mkt-tape">
        <p class="mkt-tape-h">{{ t('cockpit.mkt.tape', 'Last trades') }}</p>
        <p v-for="x in tape" :key="`${x.symbol}-${x.seq}`" class="mkt-tick" data-testid="mkt-tick">
          <span class="mkt-tick-sym">{{ x.symbol }}</span>
          <span class="mkt-tick-qty">{{ x.qty }}</span>
          <span class="mkt-tick-at">@</span>
          <span class="mkt-tick-px">{{ money(Number(x.price).toFixed(2)) }}</span>
          <span class="mkt-tick-age">{{ ago(x.at) }}</span>
        </p>
      </div>

      <p class="mkt-foot" data-testid="mkt-foot">
        {{ tp('cockpit.mkt.foot', '{n} listings · {t} traded in the last 24h · {h} halted',
              { n: ranked.length, t: tradedToday, h: halted }) }}
        <template v-if="lastTradeAt">
          · {{ tp('cockpit.mkt.lastTrade', 'last trade {age} ago', { age: ago(lastTradeAt) }) }}
        </template>
        <RecordLink kind="exchange" class="ckd-doorsep"
                    :label="t('cockpit.door.exchange', 'Open the market')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.mkt { display: flex; flex-direction: column; gap: .4rem; }
.mkt-t { width: 100%; border-collapse: collapse; font-size: .72rem; }
.mkt-t th { font-size: .58rem; letter-spacing: .06em; text-transform: uppercase;
  color: var(--nc-text-muted, #6e7681); font-weight: 500; text-align: right; padding-bottom: .2rem; }
.mkt-t th.mkt-sym { text-align: left; }
.mkt-t td { padding: .1rem 0; color: var(--nc-text-secondary, #c9d1d9); }
.mkt-sym { text-align: left; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 11rem; }
.mkt-n { text-align: right; font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; white-space: nowrap; padding-left: .5rem; }
.mkt-ccy { font-size: .55rem; color: var(--nc-text-muted, #6e7681); margin-left: .2rem; }
.mkt-dim { color: var(--nc-text-muted, #6e7681); font-size: .66rem; }
.is-up { color: var(--nc-success, #3fb950); }
.is-down { color: var(--nc-danger, #f85149); }
.is-flat { color: var(--nc-text-muted, #6e7681); }
.is-halted .mkt-sym { color: var(--nc-warning, #d29922); }
.mkt-halt, .mkt-ipo { font-size: .52rem; letter-spacing: .06em; text-transform: uppercase;
  margin-left: .3rem; padding: 0 .22rem; border-radius: 3px; border: 1px solid currentColor; }
.mkt-halt { color: var(--nc-warning, #d29922); }
.mkt-ipo { color: var(--nc-primary, #00e5ff); }
.mkt-tape { border-top: 1px solid var(--nc-border-subtle, rgba(255,255,255,.08)); padding-top: .3rem; }
.mkt-tape-h { margin: 0 0 .15rem; font-size: .58rem; letter-spacing: .06em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.mkt-tick { margin: 0; display: flex; gap: .35rem; align-items: baseline; font-size: .68rem;
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums; }
.mkt-tick-sym { color: var(--nc-text-secondary, #c9d1d9); flex: 0 0 3.6rem; }
.mkt-tick-qty { color: var(--nc-text-dim, #8b949e); flex: 0 0 2rem; text-align: right; }
.mkt-tick-at { color: var(--nc-text-muted, #6e7681); }
.mkt-tick-px { color: var(--nc-primary, #00e5ff); flex: 1; }
.mkt-tick-age { color: var(--nc-text-muted, #6e7681); font-size: .62rem; }
.mkt-foot { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.ckd-doorsep { margin-left: .4rem; }
</style>
