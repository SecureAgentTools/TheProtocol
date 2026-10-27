<template>
  <div class="sd">
    <!-- ── HERO ─────────────────────────────────────────────────────── -->
    <header class="sd-hero" data-tour="agora-hero">
      <div>
        <div class="sd-eyebrow"><Icon name="mdi:chart-candlestick" /> AGORA · FEDERATION LISTINGS</div>
        <h1>AGORA Listings</h1>
        <p class="sd-sub">Every listed organization across the federation, local books and foreign markets alike. Take part where the work happens; the Passport carries your identity, the FX rail carries your money.</p>
      </div>
      <!-- §FESUITE (the loading sweep): no "0 MARKETS LIVE" while the venues are still being read; nor (2026-10-09) over
           a read that failed: the green live dot said "0 MARKETS LIVE" above "The markets could not be read just now." -->
      <div v-if="!loading && !readFailed" class="sd-live" data-testid="sd-live"><i></i>{{ venues.length }} MARKET{{ venues.length === 1 ? '' : 'S' }} LIVE</div>
    </header>

    <!-- ── §T77 AGORA-10 INDEX TICKER ───────────────────────────────── -->
    <section class="sd-index" data-tour="agora-index" v-if="agoraIndex && agoraIndex.constituents.length">
      <div class="sd-index-head">
        <span class="sd-index-name"><Icon name="mdi:chart-line" /> AGORA {{ agoraIndex.count }}</span>
        <span class="sd-index-val tick" :key="'ix' + agoraIndex.index_value">{{ fmtBig(agoraIndex.index_value) }}</span>
        <span class="sd-index-sub">value-weighted · top {{ agoraIndex.count }} by value</span>
      </div>
      <div class="sd-index-rail">
        <button v-for="c in agoraIndex.constituents" :key="c.symbol" class="sd-index-chip" :title="`${c.symbol} · value ${fmtBig(c.market_cap)} · weight ${pctFmt(c.weight_pct)}`" @click="search = c.symbol">
          <span class="sd-index-sym">${{ c.symbol }}</span>
          <span class="sd-index-px">{{ fmtPx(c.last) }}</span>
          <span class="sd-index-wt">{{ pctFmt(c.weight_pct) }}</span>
        </button>
      </div>
    </section>

    <!-- ── FEDERATION STATS ─────────────────────────────────────────── -->
    <section class="stat-grid" v-if="allListings.length">
      <div class="stat-tile">
        <span class="stat-label">LISTINGS</span>
        <span class="stat-num" data-testid="sd-listings-count">{{ liveListings.length }}</span>
        <span class="stat-sub">across {{ venues.length }} sovereign market{{ venues.length === 1 ? '' : 's' }}<template v-if="delistedCount"> · {{ delistedCount }} delisted not counted</template></span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">Σ LISTED VALUE</span>
        <span class="stat-num tick" :key="'m' + totalMcap">{{ totalMcap }}</span>
        <span class="stat-sub">{{ mcapSplit || 'per-venue currency, summed nominally' }}</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">24H VOLUME</span>
        <span class="stat-num tick" :key="'v' + totalVol">{{ totalVol }}</span>
        <span class="stat-sub">{{ volSplit || 'matched across the federation' }}</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">OPEN LAUNCHES</span>
        <span class="stat-num">{{ ipoOpenCount }}</span>
        <span class="stat-sub">fixed-price primary supply remaining</span>
      </div>
    </section>

    <!-- ── FILTER BAR ───────────────────────────────────────────────── -->
    <div class="sd-bar" v-if="allListings.length">
      <div class="sd-venues">
        <button class="sd-vchip" :class="{ on: venueFilter === '' }" @click="setVenueFilter('')">ALL</button>
        <button v-for="v in venues" :key="v.venue" class="sd-vchip" :class="{ on: venueFilter === v.venue }" @click="setVenueFilter(v.venue)">
          {{ v.venue.toUpperCase() }} <i class="sd-vccy">{{ v.currency }}</i>
        </button>
      </div>
      <input class="sd-search" type="search" spellcheck="false" v-model="search" placeholder="search ticker or organization…" aria-label="Search ticker or organization" />
      <span class="sd-count" v-if="search || venueFilter">{{ filtered.length }} / {{ shownBase.length }}</span>
      <button v-if="delistedCount" class="sd-vchip" :class="{ on: showDelisted }" data-testid="sd-show-delisted"
              :aria-pressed="showDelisted ? 'true' : 'false'" @click="showDelisted = !showDelisted">
        {{ showDelisted ? 'Hide' : 'Show' }} {{ delistedCount }} delisted
      </button>
      <div class="sd-sort">
        <span class="sd-sort-label">SORT</span>
        <button v-for="s in SORTS" :key="s.key" class="sd-vchip" :class="{ on: sortBy === s.key }" @click="sortBy = s.key">{{ s.label }}</button>
      </div>
    </div>

    <!-- §POCKETBRIDGE4 WS-P — fired price alerts (same rules the phone + the
         registry watcher share) + the account-synced watchlist strip. -->
    <div v-if="wa.firedBanner.value.length" class="sd-alert-banner" data-testid="sd-alert-banner" role="alert">
      <Icon name="mdi:bell-ring" />
      <span v-for="f in wa.firedBanner.value" :key="f.id" class="sd-alert-hit">
        ${{ f.symbol }} {{ f.fired_direction === 'up' ? '▲' : '▼' }} past ±{{ f.pct }}% (last {{ fmtPx(f.fired_price) }})
      </span>
      <button class="sd-x" @click="wa.dismissFired()" aria-label="Dismiss fired alerts"><Icon name="mdi:close" /></button>
    </div>
    <div v-if="wa.starred.value.length" class="sd-watch" data-testid="sd-watch-strip" aria-label="Watchlist">
      <span class="sd-watch-lab"><Icon name="mdi:star" /> WATCH</span>
      <button v-for="w in wa.starred.value" :key="wa.watchKey(w)" class="sd-vchip on" @click="openWatch(w)">
        ${{ w.symbol }}<i v-if="w.venue" class="sd-vccy">{{ w.venue }}</i>
      </button>
      <span v-if="wa.watchSyncNote.value" class="sd-watch-note">{{ wa.watchSyncNote.value }}</span>
    </div>

    <!-- ── LOADING SKELETON ─────────────────────────────────────────── -->
    <div class="sd-grid" v-if="loading && !allListings.length" aria-hidden="true">
      <div v-for="i in 6" :key="'sk' + i" class="sd-card sd-skel">
        <div class="skel-row"><span class="skel-line w40 tall"></span><span class="skel-line w25"></span></div>
        <span class="skel-line w55 tall"></span>
        <span class="skel-line w100 spark"></span>
        <span class="skel-line w70"></span>
        <span class="skel-line w35 btn"></span>
      </div>
    </div>

    <!-- ── LISTING CARDS ────────────────────────────────────────────── -->
    <div class="sd-grid" v-if="filtered.length">
      <div v-for="l in filtered" :key="l.venue + l.symbol" class="sd-card" data-tour="agora-stock-card" :class="{ halted: l.status === 'halted' }">
        <div class="sd-card-top">
          <div class="sd-id">
            <span class="sd-sym">${{ l.symbol }}</span>
            <span class="sd-org" :title="l.display_name">{{ l.display_name }}</span>
          </div>
          <span class="sd-venue" :class="{ home: l.isLocal }">
            <Icon :name="l.isLocal ? 'mdi:bank' : 'mdi:web'" />
            {{ l.isLocal ? 'THIS MARKET' : l.venue.toUpperCase() }} · {{ l.currency }}
          </span>
          <!-- §POCKETBRIDGE4 WS-P — the SAME synced watchlist Pocket writes
               (venue: null = this venue, byte-compatible entries). -->
          <button class="sd-star" :class="{ on: wa.isStarred(l.symbol, l.isLocal ? null : l.venue) }"
            :data-testid="'sd-star-' + l.symbol" @click.stop="starRow(l)"
            :aria-label="(wa.isStarred(l.symbol, l.isLocal ? null : l.venue) ? 'Unstar' : 'Star') + ' ' + l.symbol">
            <Icon :name="wa.isStarred(l.symbol, l.isLocal ? null : l.venue) ? 'mdi:star' : 'mdi:star-outline'" />
          </button>
        </div>

        <div class="sd-price-row">
          <template v-if="!l.federated || l.federatedLive">
            <span class="sd-px tick" :key="l.symbol + (l.last ?? '')">{{ fmtPx(l.last) }} <i>{{ l.currency }}</i></span>
            <span class="sd-chg" :class="chgClass(l.change_24h_pct)">{{ chgFmt(l.change_24h_pct) }}</span>
            <span v-if="l.federatedLive" class="sd-chg sd-fed-fresh" title="Coarse federated quote, refreshes ~every 15 min; the live price + order book are on the owning market">~15m</span>
          </template>
          <template v-else>
            <span class="sd-px sd-px-ref" title="Launch / reference price, the live price stays on the owning market (trade via Passport)">{{ fmtPx(l.ipo_price) }} <i>{{ l.currency }}</i><em class="sd-ref-tag">LAUNCH</em></span>
            <span class="sd-chg sd-fed-tag" title="Signed catalog from a federated market, live quotes stay on the market">CATALOG</span>
          </template>
        </div>

        <div class="sd-spark" :class="(l.federated && !l.federatedLive) ? 'dim' : chgClass(l.change_24h_pct)">
          <Sparkline v-if="(l.spark?.length ?? 0) >= 2" :points="l.spark!" :width="260" :height="36" />
          <span v-else class="sd-spark-empty">{{ l.federated ? `signed catalog — trade on ${l.venue} via Passport` : 'young market — chart fills with trade history' }}</span>
        </div>

        <div class="sd-meta">
          <span><i>VALUE</i><b>{{ fmtBig(l.market_cap) }}</b></span>
          <span><i>VOL 24H</i><b>{{ fmtBig(l.volume_24h_notional) }}</b></span>
          <span><i>TRADES</i><b>{{ (l.trades_24h ?? 0).toLocaleString(appLocale()) }}</b></span>
          <span v-if="(l.ipo_remaining ?? 0) > 0 && l.status !== 'delisted'" class="sd-ipo-meta"><i>LAUNCH</i><b>{{ fmtBig(String(l.ipo_remaining)) }} @ {{ fmtPx(l.ipo_price) }}</b></span>
        </div>

        <div class="sd-actions">
          <span v-if="l.status === 'delisted'" class="sd-halt sd-delisted" data-testid="sd-delisted"><Icon name="mdi:close" /> DELISTED</span>
          <button v-else-if="l.isLocal" class="sd-btn primary" data-tour="agora-trade-btn" @click="goDesk(l)">
            <Icon name="mdi:chart-candlestick" /> Trade on the Desk
          </button>
          <template v-else-if="l.status !== 'delisted'">
            <button class="sd-btn passport" :disabled="!agents.length" :title="agents.length ? 'Buy via the DevCard Passport — identity verified, FX-funded' : 'log in with an agent to passport-trade'" @click="openPassport(l)">
              <Icon name="mdi:shield-check" /> Passport Buy
            </button>
            <a v-if="safeExternalUrl(l.venue_url)" class="sd-btn" :href="`${safeExternalUrl(l.venue_url)!.replace(/\/+$/, '')}/ui#/agora/listings`" target="_blank" rel="noopener" :title="`Open ${l.venue}'s live screener — see the live price and order book, then buy there`">
              <Icon name="mdi:open-in-new" /> View on {{ l.venue }}
            </a>
          </template>
          <span v-if="l.status === 'halted'" class="sd-halt"><Icon name="mdi:pause" /> HALTED</span>
        </div>
      </div>
    </div>

    <ReadFailedNotice v-else-if="!loading && readFailed" text="The markets could not be read just now." :retry="refresh" />
    <div class="sd-empty" v-else-if="!loading">
      <Icon name="mdi:telescope" />
      <p>{{ allListings.length ? 'No listings match the filter.' : 'No markets reachable yet, listings appear here the moment any federation market goes live.' }}</p>
    </div>

    <!-- ── PASSPORT BUY MODAL ───────────────────────────────────────── -->
    <div class="sd-modal" v-if="pp.show" role="dialog" aria-modal="true" aria-label="Passport buy" @click.self="pp.show = false">
      <div class="sd-modal-card">
        <div class="sd-modal-head"><Icon name="mdi:shield-check" /> PASSPORT BUY · ${{ pp.symbol }} <span class="sd-venue">{{ pp.venue.toUpperCase() }} · {{ pp.currency }}</span></div>
        <p class="sd-modal-explain">Your home registry signs your Developer Card, relays the order, and funds the market gateway over the FX rail, escrow-settled, Δ=0 end to end. Distributions and refunds repatriate automatically.</p>
        <label class="sd-field"><span>ACTING AGENT</span>
          <select class="sd-input" v-model="pp.agent_did">
            <option v-for="a in agents" :key="a.did" :value="a.did">{{ a.name || '…' + a.did.slice(-12) }}</option>
          </select>
        </label>
        <div class="sd-modal-grid">
          <label class="sd-field"><span>QTY (points)</span>
            <input ref="qtyInput" class="sd-input" type="number" min="1" step="1" v-model.number="pp.qty" />
          </label>
          <label class="sd-field"><span>LIMIT PRICE ({{ pp.currency }})</span>
            <input class="sd-input" v-model="pp.price" inputmode="decimal" />
          </label>
        </div>
        <div class="sd-receipt">
          <div><span>LAST PRICE</span><b>{{ fmtPx(pp.last) }} {{ pp.currency }}</b></div>
          <div><span>TOTAL ≈</span><b>{{ ppNotional }} {{ pp.currency }}</b></div>
          <div><span>FX BUFFER +{{ pp.fx_buffer_pct }}%</span><b>≈ {{ ppBuffer }} {{ pp.currency }} (residue repatriates)</b></div>
        </div>
        <div class="sd-modal-row">
          <button class="sd-btn" @click="pp.show = false">Cancel</button>
          <button class="sd-btn passport" :disabled="pp.busy || !pp.agent_did || !(pp.qty > 0) || !(parseFloat(pp.price) > 0)" @click="doPassportBuy">
            {{ pp.busy ? 'relaying…' : 'Relay order home → market' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
/**
 * AGORA Stock Discovery (§V0064 P2, 2026-06-13) — the federation equity
 * screener: every live venue's listings (server-side aggregate, no CORS),
 * sparklines, mcap/vol, IPO supply; local books open the Desk, foreign books
 * buy through the DevCard Passport. Design_Language house style.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import Sparkline from '@/components/command/Sparkline.vue'
import { apiClient } from '@/services/api/client'
import { exchangeService, type AgoraIndex } from '@/services/api/exchangeService'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
// §POCKETBRIDGE4 WS-P — the shared watchlist/alert brain (same synced prefs as Pocket)
import { useWatchAlerts } from '@/composables/useWatchAlerts'
import { useAlive } from '@/composables/useAlive'
import type { WatchEntry } from '@/services/api/pocketPrefs'

interface SdListing {
  symbol: string; display_name: string; organization_id: string | null
  last: string | null; change_24h_pct: string | null
  market_cap: string | null; volume_24h_notional: string | null
  trades_24h: number | null; ipo_remaining: number | null; ipo_price: string | null
  status: string; currency: string; spark?: number[]
  venue: string; isLocal: boolean; federated?: boolean; federatedLive?: boolean; venue_url?: string | null
}

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const uiStore = useUIStore()

const SORTS = [
  { key: 'mcap', label: 'VALUE' },
  { key: 'chg', label: '24H Δ' },
  { key: 'vol', label: 'VOLUME' },
] as const

const venues = ref<{ venue: string; currency: string; listings: SdListing[] }[]>([])
const localVenue = ref<string>('')
const venueFilter = ref('')
const search = ref('')
// §POCKETBRIDGE4 WS-P
const wa = useWatchAlerts()
function starRow(l: SdListing) { void wa.toggleStar(l.symbol, l.isLocal ? null : l.venue) }
function sweepHere() {
  wa.sweep((sym, venue) => {
    for (const v of venues.value) {
      for (const l of v.listings) {
        if (l.symbol !== sym) continue
        const isLocalHit = (venue || null) === null ? l.isLocal : l.venue === venue
        if (isLocalHit && l.last != null) return Number(l.last)
      }
    }
    return null
  })
}
function openWatch(w: WatchEntry) {
  // starred chips navigate the way the ?sym= deep link does
  search.value = w.symbol
  if (w.venue) venueFilter.value = w.venue
}
const sortBy = ref<string>('mcap')
const loading = ref(true)
// §FESUITE (the failing-reads census, V0569 at sbx-beta, 2026-10-04): with every read failed the screener said "No markets reachable yet,
// listings appear here the moment any federation market goes live." while the frame listed 4 trading markets. A failed
// read keeps the markets it last read (a poll no longer blanks them) and, when it never read any, says so.
const readFailed = ref(false)
const pp = reactive({ show: false, busy: false, venue: '', symbol: '', currency: '', agent_did: '', qty: 5, price: '', last: '' as string | null, fx_buffer_pct: 4 })
const agoraIndex = ref<AgoraIndex | null>(null) // §T77 — value-weighted index header (points × last price)
const qtyInput = ref<HTMLInputElement>()
let timer: number | undefined

const agents = computed(() => authStore.availableAgents || [])
const allListings = computed<SdListing[]>(() => venues.value.flatMap(v => v.listings))
// §COCKPITDESK (2026-10-15): a delisted listing is no market. sbx-alpha lists 171 delisted test listings among 179, and the
// page drew each as a live card ("Trade on the Desk", "LAUNCH 99 @ 1.00") and counted them in the totals and the open
// launches. They are left out by default, counted aside, and shown on request with DELISTED and no trade or launch.
const showDelisted = ref(false)
const liveListings = computed(() => allListings.value.filter(l => l.status !== 'delisted'))
const delistedCount = computed(() => allListings.value.length - liveListings.value.length)
const shownBase = computed(() => (showDelisted.value ? allListings.value : liveListings.value))
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  let xs = shownBase.value.filter(l =>
    (!venueFilter.value || l.venue === venueFilter.value) &&
    (!q || l.symbol.toLowerCase().includes(q) || (l.display_name || '').toLowerCase().includes(q)))
  const f = (s?: string | null) => { const v = parseFloat(s || ''); return isFinite(v) ? v : 0 }
  if (sortBy.value === 'mcap') xs = xs.slice().sort((a, b) => f(b.market_cap) - f(a.market_cap))
  else if (sortBy.value === 'chg') xs = xs.slice().sort((a, b) => f(b.change_24h_pct) - f(a.change_24h_pct))
  else xs = xs.slice().sort((a, b) => f(b.volume_24h_notional) - f(a.volume_24h_notional))
  return xs
})
const totalMcap = computed(() => fmtBig(String(liveListings.value.reduce((a, l) => a + (parseFloat(l.market_cap || '0') || 0), 0))))
const totalVol = computed(() => fmtBig(String(liveListings.value.reduce((a, l) => a + (parseFloat(l.volume_24h_notional || '0') || 0), 0))))
const ipoOpenCount = computed(() => liveListings.value.filter(l => (l.ipo_remaining ?? 0) > 0 && l.status !== 'halted').length)
const ppNotional = computed(() => {
  const v = (pp.qty || 0) * (parseFloat(pp.price) || 0)
  return isFinite(v) ? v.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : '—'
})
const ppBuffer = computed(() => {
  const v = (pp.qty || 0) * (parseFloat(pp.price) || 0) * (pp.fx_buffer_pct / 100)
  return isFinite(v) && v > 0 ? '+' + v.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : '—'
})
function ccySplit(field: 'market_cap' | 'volume_24h_notional'): string {
  const m: Record<string, number> = {}
  for (const l of liveListings.value) {
    const v = parseFloat(l[field] || '0') || 0
    m[l.currency] = (m[l.currency] || 0) + v
  }
  const parts = Object.entries(m).map(([c, v]) => `${fmtBig(String(v))} ${c}`)
  return parts.length > 1 ? parts.join(' · ') : ''
}
const mcapSplit = computed(() => ccySplit('market_cap'))
const volSplit = computed(() => ccySplit('volume_24h_notional'))

function fmtPx(p?: string | null): string {
  const v = parseFloat(p || '')
  if (!isFinite(v)) return '—'
  if (v >= 1000) return v.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
  if (v >= 1) return v.toFixed(2)
  return v.toPrecision(3)
}
function fmtBig(s?: string | null): string {
  const v = parseFloat(s || '')
  if (!isFinite(v)) return '—'
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  return v.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}
function chgClass(c?: string | null) { const v = parseFloat(c || '0'); return v > 0 ? 'up' : v < 0 ? 'down' : 'dim' }
function chgFmt(c?: string | null) { if (c == null) return '—'; const v = parseFloat(c); return `${v > 0 ? '▲' : v < 0 ? '▼' : ''}${Math.abs(v).toFixed(2)}%` }
// §T77 — weight_pct arrives as a decimal STRING; render 1dp.
function pctFmt(p?: string | null): string { const v = parseFloat(p || ''); return isFinite(v) ? v.toFixed(1) + '%' : '—' }

// §T77 — the AGORA-N index (local-venue, public read). Isolated: a dark venue just hides the strip.
async function refreshIndex() {
  try { agoraIndex.value = await exchangeService.index(10) }
  catch { agoraIndex.value = null }
}

// local venue = the one whose listings also appear on the same-origin venue.
// Detected ONCE — re-probing /exchange/listings every poll is wasted traffic
// (and noisy 503s when this registry's own venue is dark).
let localProbed = false
async function detectLocalVenue(data: any) {
  if (localProbed) return
  localProbed = true
  try {
    const own = await apiClient.get('/agora/listings')
    const ownSyms = new Set((own.data?.listings || []).map((x: any) => x.symbol))
    if (ownSyms.size) {
      for (const v of data?.venues || []) {
        if (v.listings?.some((l: any) => ownSyms.has(l.symbol))) { localVenue.value = v.venue; break }
      }
    }
  } catch { /* dark local venue */ }
}

async function refresh() {
  try {
    const { data } = await apiClient.get('/agora/federation-tickers')
    await detectLocalVenue(data)
    const liveVenues = (data?.venues || []).map((v: any) => ({
      venue: v.venue, currency: v.currency,
      listings: (v.listings || []).map((l: any) => ({ ...l, venue: v.venue, isLocal: v.venue === localVenue.value })),
    }))
    // Overlay the SIGNED federated catalog (/exchange/network-listings) so
    // listings from venues the live ticker can't reach (cloud-ops) still appear
    // — catalog-only (no live px; the card degrades to "young market"). Deduped
    // by symbol so live entries always win. Isolated try: a failure just leaves
    // the live view intact. This is the network-wide discovery read (P7).
    try {
      const seen = new Set<string>(liveVenues.flatMap((v: any) => v.listings.map((l: SdListing) => l.symbol)))
      const { data: net } = await apiClient.get('/agora/network-listings')
      const extra: Record<string, { venue: string; currency: string; listings: SdListing[] }> = {}
      for (const e of (net?.listings || [])) {
        if (!e.symbol || e.is_local || seen.has(e.symbol)) continue
        seen.add(e.symbol)
        const origin = e.origin || 'federation'
        // §2026-06-25 Federated Market Card: if the signed card carried a COARSE market
        // block (last + 24-pt sparkline, refreshed ~15 min), light the card up with it
        // (federatedLive) — else it stays catalog-only ("signed catalog" placeholder).
        const mk = (e.market && typeof e.market === 'object') ? e.market : null
        const mkSpark = Array.isArray(mk?.spark) ? (mk!.spark as number[]) : undefined
        ;(extra[origin] ||= { venue: origin, currency: e.currency || '—', listings: [] }).listings.push({
          symbol: e.symbol, display_name: e.display_name || e.symbol, organization_id: e.organization_id ?? null,
          last: mk?.last ?? null, change_24h_pct: mk?.change_24h_pct ?? null,
          market_cap: null, volume_24h_notional: null,
          trades_24h: null, ipo_remaining: null, ipo_price: e.ipo_price ?? null,
          status: e.status || 'trading', currency: e.currency || '—',
          spark: mkSpark,
          venue: origin, isLocal: false, federated: true,
          federatedLive: !!(mkSpark && mkSpark.length >= 2),
          venue_url: e.venue_url ?? null,
        })
      }
      venues.value = [...liveVenues, ...Object.values(extra)]
    } catch { venues.value = liveVenues }
    readFailed.value = false
  } catch { readFailed.value = !venues.value.length } finally { loading.value = false }
}

function goDesk(l: SdListing) { void router.push({ path: '/agora', query: { sym: l.symbol } }) }

// venue filter ⇄ URL: chips write ?venue= (shareable), navigation drives the
// filter — covers same-component hash navs where onMounted never re-runs.
function setVenueFilter(v: string) {
  venueFilter.value = v
  void router.replace({ query: { ...route.query, venue: v || undefined } })
}
watch(() => route.query.venue, v => {
  if (route.name !== 'stocks') return
  venueFilter.value = typeof v === 'string' ? v : ''
})

function openPassport(l: SdListing) {
  pp.venue = l.venue
  pp.symbol = l.symbol
  pp.currency = l.currency
  pp.last = l.last
  pp.agent_did = authStore.activeAgent?.did || agents.value[0]?.did || ''
  pp.price = l.last ? (Math.round(parseFloat(l.last) * 1.03 * 100) / 100).toFixed(2) : ''
  pp.qty = 5
  pp.show = true
  void nextTick(() => qtyInput.value?.focus())
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && pp.show && !pp.busy) pp.show = false
}

async function doPassportBuy() {
  if (pp.busy) return
  pp.busy = true
  try {
    if (pp.agent_did && pp.agent_did !== authStore.activeAgent?.did) {
      await authStore.switchAgent(pp.agent_did)
    }
    const { data } = await apiClient.post('/agora/passport/orders', {
      venue_registry: pp.venue, listing: pp.symbol, qty: pp.qty,
      price: pp.price, fx_buffer_pct: pp.fx_buffer_pct,
    })
    uiStore.showSuccess(`Passport order relayed — ${data?.status || 'accepted'}; funding crosses the FX rail, then it matches`)
    pp.show = false
  } catch (e: any) {
    uiStore.showError('Passport relay failed', e?.response?.data?.detail || e?.message)
  } finally { pp.busy = false }
}

// §FESUITE (the leave sweep): a page left during its first reads starts nothing when they land (useAlive)
const alive = useAlive()
onMounted(async () => {
  if (typeof route.query.venue === 'string' && route.query.venue) venueFilter.value = route.query.venue
  // ?sym= deep link (Discovery / MyAgents equity chip): focus that one ticker
  if (typeof route.query.sym === 'string' && route.query.sym) search.value = route.query.sym
  window.addEventListener('keydown', onKeydown)
  if (!agents.value.length) { try { await authStore.fetchAvailableAgents() } catch { /* guest */ } }
  if (!alive()) return
  await Promise.all([refresh(), refreshIndex()])
  if (!alive()) return
  void wa.loadWatch(); void wa.loadAlerts()
  sweepHere()
  timer = window.setInterval(() => { void refresh().then(sweepHere); void refreshIndex() }, 25000)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.sd {
  --cyan: var(--nc-primary);
  --cyan-rgb: var(--nc-primary-rgb);
  position: relative; z-index: 1; min-height: 100%;
  padding: 18px 22px 40px; color: rgba(255, 255, 255, 0.88);
}
.up { color: #10b981; } .down { color: #ef4444; } .dim { opacity: 0.55; }
.tick { display: inline-block; animation: sd-tick 0.45s ease-out; }
@keyframes sd-tick { 0% { transform: scale(1.05); } 100% { transform: scale(1); } }

.sd-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }
.sd-eyebrow { display: inline-flex; align-items: center; gap: 7px; font-size: 10px; letter-spacing: 0.18em; color: rgba(var(--cyan-rgb), 0.8); font-family: ui-monospace, monospace; }
.sd-eyebrow :deep(svg) { width: 13px; height: 13px; }
.sd-hero h1 { font-size: 28px; font-weight: 800; margin: 3px 0 4px; }
.sd-sub { font-size: 12px; opacity: 0.6; max-width: 640px; }
.sd-live { display: inline-flex; align-items: center; gap: 7px; font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.14em; color: #10b981; border: 1px solid rgba(16, 185, 129, 0.45); border-radius: 99px; padding: 6px 14px; }
.sd-live i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; animation: sd-pulse 1.9s infinite; }
@keyframes sd-pulse { 50% { opacity: 0.45; } }

.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin-bottom: 14px; }
.stat-tile {
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.035);
  border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 10px; backdrop-filter: blur(9px);
  padding: 11px 14px; display: flex; flex-direction: column; gap: 2px;
}
.stat-label { font-size: 9px; letter-spacing: 0.16em; opacity: 0.55; font-family: ui-monospace, monospace; }
.stat-num { font-size: 23px; font-weight: 800; font-variant-numeric: tabular-nums; text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.32); }
.stat-sub { font-size: 10px; opacity: 0.45; font-family: ui-monospace, monospace; }

/* §T77 — AGORA-N index header ticker */
.sd-index {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 14px;
  padding: 10px 14px; border-radius: 11px;
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.05);
  border: 1px solid rgba(var(--cyan-rgb), 0.22); backdrop-filter: blur(9px);
}
/* the head may shrink to the card, so its own wrap puts the sub on a line of its own on a phone (with flex: none it kept
   its one-line width and the sub ran past the card; the camera, 2026-10-13) */
.sd-index-head { display: flex; align-items: baseline; gap: 4px 10px; flex-wrap: wrap; flex: 0 1 auto; min-width: 0; }
.sd-index-name { display: inline-flex; align-items: center; gap: 6px; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 800; letter-spacing: 0.12em; color: rgba(var(--cyan-rgb), 0.95); }
.sd-index-name :deep(svg) { width: 14px; height: 14px; }
.sd-index-val { font-size: 20px; font-weight: 800; font-variant-numeric: tabular-nums; text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.3); }
.sd-index-sub { font-size: 9px; letter-spacing: 0.08em; opacity: 0.45; font-family: ui-monospace, monospace; }
.sd-index-rail { display: flex; gap: 7px; overflow-x: auto; flex: 1; min-width: 0; padding-bottom: 2px; }
.sd-index-chip {
  display: inline-flex; align-items: center; gap: 7px; flex: none; cursor: pointer;
  background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 99px;
  padding: 5px 11px; font-family: ui-monospace, monospace; transition: all 0.15s;
}
.sd-index-chip:hover { border-color: rgba(var(--cyan-rgb), 0.5); background: rgba(var(--cyan-rgb), 0.1); }
.sd-index-sym { font-size: 11px; font-weight: 800; color: rgba(var(--cyan-rgb), 0.95); }
.sd-index-px { font-size: 11px; font-variant-numeric: tabular-nums; opacity: 0.85; }
.sd-index-wt { font-size: 9px; opacity: 0.5; }

.sd-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.sd-venues, .sd-sort { display: flex; gap: 6px; flex-wrap: wrap; }
.sd-vchip {
  display: inline-flex; align-items: baseline; gap: 6px; cursor: pointer;
  font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.1em; font-weight: 700;
  color: rgba(255, 255, 255, 0.7); background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.25); border-radius: 99px; padding: 6px 13px; min-height: 30px;
  transition: all 0.15s;
}
.sd-vchip:hover { border-color: rgba(var(--cyan-rgb), 0.5); }
.sd-vchip.on { background: rgba(var(--cyan-rgb), 0.16); color: #fff; border-color: rgba(var(--cyan-rgb), 0.6); }
.sd-vccy { font-style: normal; font-size: 8px; opacity: 0.6; }
.sd-search {
  flex: 1; min-width: 220px; background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.22); border-radius: 99px; color: #fff;
  padding: 8px 16px; font-size: 13px;
}
.sd-search:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.7); box-shadow: 0 0 0 2px rgba(var(--cyan-rgb), 0.18); }
.sd-count { font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.1em; color: rgba(var(--cyan-rgb), 0.85); white-space: nowrap; font-variant-numeric: tabular-nums; }
.sd-sort-label { align-self: center; font-family: ui-monospace, monospace; font-size: 8px; letter-spacing: 0.18em; opacity: 0.4; margin-right: 2px; }

/* loading skeleton — opacity pulse only (cheap, no filter/layout work) */
.sd-skel { pointer-events: none; }
.skel-row { display: flex; justify-content: space-between; gap: 10px; }
.skel-line { display: block; height: 11px; border-radius: 6px; background: rgba(255, 255, 255, 0.06); animation: sd-skel 1.1s ease-in-out infinite alternate; }
.skel-line.tall { height: 20px; }
.skel-line.spark { height: 36px; border-radius: 8px; }
.skel-line.btn { height: 34px; border-radius: 9px; }
.w25 { width: 25%; } .w35 { width: 35%; } .w40 { width: 40%; } .w55 { width: 55%; } .w70 { width: 70%; } .w100 { width: 100%; }
@keyframes sd-skel { from { opacity: 0.45; } to { opacity: 1; } }

/* auto-fit (not auto-fill): with few listings the cards STRETCH to fill the row
   instead of leaving empty tracks — the cards stay readable + scale up on wide
   viewports, collapse to 1-up on mobile (the @media below). */
.sd-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 13px; }
.sd-card {
  position: relative; overflow: hidden;
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.035);
  border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 13px; backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8);
  padding: 14px 16px; display: flex; flex-direction: column; gap: 9px; transition: border-color 0.2s, transform 0.2s;
}
.sd-card::before {
  content: ''; position: absolute; top: 0; left: 10%; right: 10%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--cyan-rgb), 0.7), transparent);
  opacity: 0; transition: opacity 0.25s;
}
.sd-card:hover { border-color: rgba(var(--cyan-rgb), 0.42); transform: translateY(-2px); }
.sd-card:hover::before { opacity: 1; }
.sd-card.halted { opacity: 0.6; filter: grayscale(0.45); }
.sd-card-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.sd-id { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.sd-sym { font-size: 19px; font-weight: 800; color: rgba(var(--cyan-rgb), 0.95); font-family: ui-monospace, monospace; text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.3); }
.sd-org { font-size: 11px; opacity: 0.6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }
.sd-venue { display: inline-flex; align-items: center; gap: 5px; flex: none; font-family: ui-monospace, monospace; font-size: 8px; letter-spacing: 0.12em; font-weight: 800; padding: 4px 9px; border-radius: 99px; border: 1px solid rgba(255, 255, 255, 0.2); opacity: 0.8; }
.sd-venue.home { color: rgba(var(--cyan-rgb), 1); border-color: rgba(var(--cyan-rgb), 0.5); opacity: 1; }
.sd-venue :deep(svg) { width: 10px; height: 10px; }
.sd-price-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.sd-px { font-size: 24px; font-weight: 800; font-variant-numeric: tabular-nums; }
.sd-px i { font-style: normal; font-size: 11px; font-weight: 600; opacity: 0.5; }
.sd-chg { font-size: 13px; font-weight: 700; font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.sd-px-ref { opacity: 0.9; }
.sd-ref-tag { font-style: normal; font-size: 8px; letter-spacing: 0.12em; opacity: 0.5; margin-left: 5px; vertical-align: super; font-family: ui-monospace, monospace; }
.sd-fed-tag { font-size: 9px; letter-spacing: 0.14em; opacity: 0.5; font-family: ui-monospace, monospace; }
.sd-fed-fresh { font-size: 8px; letter-spacing: 0.06em; opacity: 0.55; padding: 1px 4px; align-self: center;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28); border-radius: 4px; color: rgba(var(--nc-primary-rgb), 0.85); }
.sd-spark { height: 38px; display: flex; align-items: center; }
.sd-spark :deep(svg) { width: 100%; }
.sd-spark-empty { font-size: 9px; letter-spacing: 0.08em; opacity: 0.35; font-family: ui-monospace, monospace; }
.sd-meta { display: flex; gap: 14px; flex-wrap: wrap; padding-top: 8px; border-top: 1px dashed rgba(var(--cyan-rgb), 0.14); }
.sd-meta span { display: flex; flex-direction: column; gap: 1px; }
.sd-meta i { font-style: normal; font-size: 8px; letter-spacing: 0.16em; opacity: 0.45; font-family: ui-monospace, monospace; }
.sd-meta b { font-size: 12px; font-variant-numeric: tabular-nums; }
.sd-ipo-meta { background: rgba(var(--cyan-rgb), 0.07); border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 7px; padding: 3px 8px; margin: -4px 0; }
.sd-ipo-meta b { color: rgba(var(--cyan-rgb), 0.95); }
.sd-actions { display: flex; align-items: center; gap: 8px; margin-top: 2px; }
.sd-btn {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.1em; font-weight: 800;
  color: rgba(255, 255, 255, 0.85); background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 9px; padding: 9px 14px; min-height: 38px;
  transition: all 0.15s; text-decoration: none;
}
.sd-btn:hover { background: rgba(255, 255, 255, 0.09); border-color: rgba(255, 255, 255, 0.32); }
.sd-btn :deep(svg) { width: 13px; height: 13px; }
.sd-btn.primary { color: rgba(var(--cyan-rgb), 1); background: rgba(var(--cyan-rgb), 0.1); border-color: rgba(var(--cyan-rgb), 0.45); }
.sd-btn.primary:hover { background: rgba(var(--cyan-rgb), 0.22); box-shadow: 0 0 16px rgba(var(--cyan-rgb), 0.25); }
.sd-btn.passport { color: #10b981; background: rgba(16, 185, 129, 0.08); border-color: rgba(16, 185, 129, 0.45); }
.sd-btn.passport:hover:not(:disabled) { background: rgba(16, 185, 129, 0.18); box-shadow: 0 0 16px rgba(16, 185, 129, 0.25); }
.sd-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.sd-halt { display: inline-flex; align-items: center; gap: 4px; font-size: 9px; letter-spacing: 0.12em; color: #f59e0b; font-family: ui-monospace, monospace; }
.sd-delisted { color: #f87171; }
.sd-halt :deep(svg) { width: 11px; height: 11px; }
.sd-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 70px 16px; opacity: 0.5; text-align: center; font-family: ui-monospace, monospace; font-size: 12px; }
.sd-empty :deep(svg) { width: 38px; height: 38px; }

/* passport modal */
.sd-modal { position: fixed; inset: 0; z-index: 9000; display: grid; place-items: center; background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(3px); padding: 16px; }
.sd-modal-card {
  width: min(480px, 96vw); max-height: 90vh; overflow-y: auto;
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 60%), rgba(10, 16, 24, 0.97);
  border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 14px; padding: 18px 20px;
  box-shadow: 0 24px 70px -20px rgba(0, 0, 0, 0.9), 0 0 40px -18px rgba(16, 185, 129, 0.45);
}
.sd-modal-head { display: flex; align-items: center; gap: 8px; font-size: 12px; letter-spacing: 0.12em; font-weight: 800; color: #10b981; font-family: ui-monospace, monospace; margin-bottom: 9px; }
.sd-modal-head :deep(svg) { width: 15px; height: 15px; }
.sd-modal-head .sd-venue { margin-left: auto; }
.sd-modal-explain { font-size: 11px; opacity: 0.6; line-height: 1.55; margin: 0 0 12px; }
.sd-field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 9px; }
.sd-field span { font-size: 9px; letter-spacing: 0.14em; opacity: 0.55; font-family: ui-monospace, monospace; }
.sd-input { background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(var(--cyan-rgb), 0.22); border-radius: 8px; color: #fff; padding: 9px 11px; font-size: 13px; width: 100%; font-variant-numeric: tabular-nums; }
.sd-input:focus { outline: none; border-color: rgba(16, 185, 129, 0.6); }
.sd-modal-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.sd-receipt { border: 1px dashed rgba(16, 185, 129, 0.3); border-radius: 9px; padding: 9px 11px; margin: 4px 0 10px; font-family: ui-monospace, monospace; }
.sd-receipt div { display: flex; justify-content: space-between; font-size: 10px; padding: 2px 0; }
.sd-receipt span { opacity: 0.55; letter-spacing: 0.08em; }
.sd-receipt b { font-variant-numeric: tabular-nums; }
.sd-modal-row { display: flex; justify-content: flex-end; gap: 8px; }

@media (max-width: 639.98px) {
  .sd { padding: 12px 10px 32px; }
  .sd-hero h1 { font-size: 22px; }
  .sd-grid { grid-template-columns: 1fr; }
  .sd-modal-grid { grid-template-columns: 1fr; }
}
/* §POCKETBRIDGE4 WS-P — watchlist + alerts */
.sd-star { background: none; border: none; color: rgba(230,237,243,0.35); width: 34px; height: 34px; display: grid; place-items: center; cursor: pointer; position: relative; flex: 0 0 auto; }
.sd-star::before { content: ''; position: absolute; inset: -5px; }
.sd-star :deep(svg) { width: 1rem; height: 1rem; }
.sd-star.on { color: #fbbf24; }
.sd-watch { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; margin: 0.45rem 0 0.6rem; }
.sd-watch-lab { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.62rem; letter-spacing: 0.08em; font-weight: 800; color: #fbbf24; }
.sd-watch-lab :deep(svg) { width: 0.85rem; height: 0.85rem; }
.sd-watch-note { font-size: 0.64rem; color: #fbbf24; }
.sd-alert-banner { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; background: rgba(251,191,36,0.09); border: 1px solid rgba(251,191,36,0.4); border-radius: 10px; padding: 0.45rem 0.7rem; margin: 0.45rem 0; font-size: 0.78rem; }
.sd-alert-banner :deep(svg) { width: 1rem; height: 1rem; color: #fbbf24; }
.sd-alert-hit { font-variant-numeric: tabular-nums; font-weight: 700; }
.sd-x { margin-left: auto; background: rgba(255,255,255,0.07); border: none; color: inherit; width: 1.6rem; height: 1.6rem; border-radius: 50%; display: grid; place-items: center; cursor: pointer; }
.sd-x :deep(svg) { width: 0.75rem; height: 0.75rem; }
/* §COCKPITDESK (2026-10-15), the phone camera: the index's subtitle ran past a 412 px screen ([201..440]). On a phone it
   takes a line of its own and wraps. */
@media (max-width: 640px) {
  .sd-index-sub { flex-basis: 100%; white-space: normal; overflow-wrap: anywhere; }
}
</style>
