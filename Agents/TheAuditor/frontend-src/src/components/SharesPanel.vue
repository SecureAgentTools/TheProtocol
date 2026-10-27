<!--
  Holder register (V5, 2026-06-17; AGORA's words since 2026-10-25: points, launch, holder register) — the
  points analog of CIRCULATING SUPPLY. One card per AGORA listing (per frame): current price in the
  listing's local currency + 24h trend, total points issued, WHERE IT SITS (treasury vs
  public holders vs the launch allocation not yet sold — sums to total_shares), points locked backing open
  SELL orders, and the TOP HOLDERS. Read by the auditor directly from each frame's
  registry DB (org_share_positions + exchange_listings + exchange_trades) — the same
  independent-direct-read principle used for currency holders.

  I-SHARES (independent invariant): treasury + public + unsold == total_shares. The header
  chip + per-card state flag any violation (over-issuance, negative holdings, locked>owned,
  launch oversold) — the points analog of the I1 supply Δ / I3 per-user floor. Like I3, it is
  its own conservation witness and does NOT feed the I1 supply uptime.
-->
<template>
  <section v-if="cards.length" class="au-sh">
    <div class="au-sh-head">
      <span class="au-sh-glyph" aria-hidden="true">&#x25E9;</span>
      <span class="au-label">DO THE HOLDER REGISTERS BALANCE?</span>
      <span class="au-sh-tag">AGORA &middot; WHO HOLDS THE POINTS &middot; PRICE &amp; TREND</span>
      <span class="au-sh-count" :title="registries.length + ' registers read: ' + registries.map(r => r.f.name).join(', ')">
        {{ cards.length }} listings &middot; {{ registries.length }} venues
      </span>
      <span v-if="unreachableVenues.length" class="au-sh-unreach"
            :title="unreachableVenues.map(v => v.name + ': ' + (v.note || v.status)).join(' | ')">
        &#9888; {{ unreachableVenues.length }} venue{{ unreachableVenues.length > 1 ? 's' : '' }} unreadable
      </span>
      <span class="au-sh-spacer"></span>
      <span :class="['au-sh-agg', aggOk ? 'st-ok' : 'st-breach']" title="Points conserved: treasury + public + unsold = total points, for every listing">
        <span class="au-sh-agg-dot"></span>{{ aggOk ? 'POINTS CONSERVED' : breachedCount + ' POINTS BREACH' }}
      </span>
    </div>

    <div class="au-sh-grid">
      <article v-for="card in cards" :key="card.frameId + ':' + card.l.symbol"
               :class="['au-sh-card', card.l.ok ? '' : 'st-breach']">
        <header class="au-sh-card-head">
          <span class="au-sh-ccy" :style="{ color: ccyColor(card.l.currency) }">{{ ccyGlyph(card.l.currency) }}</span>
          <span class="au-sh-sym">${{ card.l.symbol }}</span>
          <span class="au-sh-status" :class="'st-' + card.l.status">{{ card.l.status }}</span>
          <span class="au-sh-holders">{{ card.l.holders.toLocaleString() }} holders</span>
        </header>
        <div class="au-sh-subhead">
          <span class="au-sh-name">{{ card.l.display_name }}</span>
          <span class="au-sh-frame">{{ card.frameName }} &middot; {{ card.l.currency }}</span>
        </div>

        <!-- Price ticker: current price (local currency) + 24h trend sparkline -->
        <div v-if="card.l.price != null" class="au-sh-ticker">
          <span class="au-sh-price au-mono">{{ fmtPrice(card.l.price) }}</span>
          <span class="au-sh-price-ccy">{{ card.l.currency }}</span>
          <span v-if="card.l.price_change_pct != null" class="au-sh-chg" :class="chgClass(card.l.price_change_pct)">
            {{ chgArrow(card.l.price_change_pct) }} {{ Math.abs(card.l.price_change_pct).toFixed(2) }}%
            <span class="au-sh-chg-win">{{ card.l.spark_window }}</span>
          </span>
          <span class="au-sh-spark" v-html="sparkSvg(card.l.price_spark, card.l.price_change_pct)"></span>
          <!-- §AGORAFLAT (2026-08-22): activity beside price. A price pinned by a
               buy-only regime looked identical to a dead market; the trade count is
               the difference between "flat" and "silent". -->
          <span class="au-sh-activity au-mono" :title="fmtQty(card.l.vol_24h_qty ?? 0) + ' points · ' + fmtPrice(card.l.vol_24h_notional ?? 0) + ' ' + card.l.currency + ' notional, 24h'">
            {{ (card.l.trades_24h ?? 0).toLocaleString() }} trades <span class="au-sh-chg-win">24h</span>
          </span>
        </div>

        <!-- points breach banner (per listing) -->
        <div v-if="!card.l.ok" class="au-sh-breach">
          <span class="au-sh-breach-dot"></span>
          <span class="au-sh-breach-txt">{{ card.l.violations.join(' · ') }}</span>
        </div>

        <!-- Headline: total points issued -->
        <div class="au-sh-headline">
          <span class="au-sh-headline-v au-mono">{{ fmt(card.l.total_shares) }}</span>
          <span class="au-sh-headline-u">points issued</span>
          <span v-if="card.l.ok" class="au-sh-ok">&check; conserved</span>
          <span v-else class="au-sh-warn">&#9888; breach</span>
        </div>

        <!-- Where it sits: stacked bar (treasury / public / unsold float) -->
        <div class="au-sh-where">
          <div class="au-sh-where-label">WHERE IT SITS</div>
          <div class="au-sh-bar" role="img" :aria-label="'points distribution for ' + card.l.symbol">
            <span v-for="seg in segments(card.l)" :key="seg.key"
                  class="au-sh-seg" :class="'seg-' + seg.key"
                  :style="{ width: seg.pct + '%' }"
                  :title="seg.label + ' ' + fmt(seg.val) + ' (' + seg.pct.toFixed(1) + '%)'"></span>
          </div>
          <div class="au-sh-legend">
            <span v-for="seg in segments(card.l)" :key="seg.key" class="au-sh-leg">
              <i class="au-sh-dot" :class="'seg-' + seg.key"></i>{{ seg.label }}
              <b class="au-mono">{{ fmtShort(seg.val) }}</b>
            </span>
          </div>
          <div v-if="card.l.locked > 0" class="au-sh-locked">
            <i class="au-sh-dot seg-locked"></i>{{ fmtShort(card.l.locked) }} locked
            <span class="au-sh-dim">backing open sell orders</span>
          </div>
        </div>

        <!-- Top holders (the holder register) -->
        <div class="au-sh-holders-list">
          <div class="au-sh-where-label">TOP HOLDERS</div>
          <div v-for="(h, i) in card.l.top_holders.slice(0, 6)" :key="h.did" class="au-sh-holder">
            <span class="au-sh-rank">{{ i + 1 }}</span>
            <span class="au-sh-htag" :class="'seg-' + (h.label === 'treasury' ? 'treasury' : 'public')">{{ h.label }}</span>
            <code class="au-sh-hdid">{{ shortDid(h.did) }}</code>
            <span class="au-sh-hpct au-mono">{{ h.pct.toFixed(1) }}%</span>
            <span class="au-sh-hval au-mono">{{ fmtShort(h.qty) }}</span>
          </div>
        </div>

        <!-- Reconciliation detail (collapsible — auditors only) -->
        <details class="au-sh-recon">
          <summary class="au-sh-recon-sum">Reconciliation detail &middot; points conservation</summary>
          <div class="au-sh-recon-note">
            <code>treasury + public + unsold&nbsp;launch = total&nbsp;points</code> — the points
            conservation identity. <b>unsold launch</b> is the launch allocation not yet bought
            ({{ fmt(card.l.ipo_sold) }} / {{ fmt(card.l.ipo_float) }} sold at launch). Read directly
            from the registry's points ledger.
          </div>
          <div class="au-sh-water">
            <div class="au-sh-row"><span class="au-sh-k">treasury</span><span class="au-sh-v au-mono">{{ fmt(card.l.treasury_qty) }}</span></div>
            <div class="au-sh-row au-sh-sub-row"><span class="au-sh-k">+ public holders</span><span class="au-sh-v au-mono">{{ fmt(card.l.public_held) }}</span></div>
            <div class="au-sh-row au-sh-sub-row"><span class="au-sh-k">+ unsold at launch</span><span class="au-sh-v au-mono">{{ fmt(card.l.float_unissued) }}</span></div>
            <div class="au-sh-row au-sh-total"><span class="au-sh-k">= total points</span><span class="au-sh-v au-mono">{{ fmt(card.l.total_shares) }}</span></div>
          </div>
        </details>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuditorStore } from '@/stores/auditorStore'
import type { ShareListing, ShareRegistry } from '@/types/auditor'

const store = useAuditorStore()
const { frames, latestByFrame, venueShares } = storeToRefs(store)

interface ShareCard { frameId: string; frameName: string; l: ShareListing }

// §VENUESHARES — a FRAME is the unit of money; a VENUE is the unit of a share
// register, and 13 of 16 venues are cloud-ops rather than frames. This panel read
// only `latest.extra_data.shares`, which exists per FRAME, so it showed 15 of the
// federation's 30 listings and said nothing about the other 15.
const frameRegistries = computed(() =>
  (frames.value || [])
    .map((f) => ({ f, sh: latestByFrame.value[f.id]?.extra_data?.shares as ShareRegistry | null | undefined }))
    .filter((x): x is { f: typeof x.f; sh: ShareRegistry } => !!x.sh && (x.sh.listings?.length || 0) > 0),
)
const venueRegistries = computed(() =>
  Object.entries(venueShares.value || {})
    .filter(([, sh]: [string, any]) => (sh?.listings?.length || 0) > 0)
    .map(([name, sh]: [string, any]) => ({
      f: { id: `venue:${name}`, name },
      sh: sh as ShareRegistry,
    })),
)
const registries = computed(() => [...frameRegistries.value, ...venueRegistries.value])

// A venue the auditor could NOT reach is shown, not omitted: "no shares" and
// "could not look" must never render the same.
const unreachableVenues = computed(() =>
  Object.entries(venueShares.value || {})
    .filter(([, sh]: [string, any]) => sh?.reachable === false)
    .map(([name, sh]: [string, any]) => ({ name, status: sh.reach_status || 'unreachable', note: sh.note || '' })),
)

const cards = computed<ShareCard[]>(() =>
  registries.value.flatMap(({ f, sh }) => sh.listings.map((l) => ({ frameId: f.id, frameName: f.name, l }))),
)
const aggOk = computed(() => registries.value.every((r) => r.sh.status === 'OK'))
const breachedCount = computed(() => registries.value.reduce((n, r) => n + (r.sh.breached_count || 0), 0))

const fmt = (n: number) => Math.round(n).toLocaleString()
const fmtQty = (n: number) => Math.round(n || 0).toLocaleString()
const fmtShort = (n: number) => {
  const a = Math.abs(n)
  if (a >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (a >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (a >= 1e3) return (n / 1e3).toFixed(1) + 'k'
  return Math.round(n).toString()
}
const fmtPrice = (n: number) => {
  if (n >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
  if (n >= 1) return n.toFixed(2)
  return n.toFixed(4)
}

const ccyGlyph = (c: string): string =>
  ({ AVT: '◆', JDAY: '◇', BVT: '◈' } as Record<string, string>)[c] || '◆'
const ccyColor = (c: string): string =>
  ({ AVT: '#7fe9c8', JDAY: '#00b0ff', BVT: '#ffb300' } as Record<string, string>)[c] || '#7fe9c8'

const chgClass = (c: number) => (Math.abs(c) < 0.005 ? 'flat' : c > 0 ? 'up' : 'down')
const chgArrow = (c: number) => (Math.abs(c) < 0.005 ? '→' : c > 0 ? '▲' : '▼')

// Inline SVG sparkline from the 24h hourly price series (up=green, down=amber).
function sparkSvg(prices: number[], chg: number | null): string {
  if (!prices || prices.length < 2) return ''
  const w = 100, h = 22, p = 2
  const min = Math.min(...prices), max = Math.max(...prices)
  const span = max - min || 1
  const n = prices.length
  const pts = prices
    .map((v, i) => {
      const x = p + (i / (n - 1)) * (w - 2 * p)
      const y = p + (1 - (v - min) / span) * (h - 2 * p)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  const col = chg == null ? '#9fb8b2' : chg >= 0 ? '#7fe9c8' : '#ff9b8a'
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" width="100%" height="22" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`
}

const SEG_DEFS = [
  { key: 'treasury', label: 'treasury', get: (l: ShareListing) => l.treasury_qty },
  { key: 'public', label: 'public holders', get: (l: ShareListing) => l.public_held },
  { key: 'unsold', label: 'unsold at launch', get: (l: ShareListing) => l.float_unissued },
]
const segments = (l: ShareListing) => {
  const total = Math.max(1, l.total_shares)
  return SEG_DEFS.map((s) => {
    const val = s.get(l)
    return { key: s.key, label: s.label, val, pct: (val / total) * 100 }
  }).filter((s) => s.val > 0)
}

const shortDid = (did: string) => {
  const tail = did.split(':').pop() || did
  if (tail.includes('-treasury') || tail.length <= 14) return tail
  return tail.slice(0, 8) + '…'
}
</script>

<style scoped>
.au-sh { margin: 22px 0; }
.au-sh-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.au-sh-glyph { color: #7fe9c8; font-size: 16px; }
.au-label { font-family: var(--au-mono, ui-monospace, monospace); font-size: 12px; font-weight: 800; letter-spacing: 0.18em; color: #cfe9e2; }
.au-sh-tag { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.1em; color: #6f8a83; border: 1px solid rgba(127,233,200,0.25); border-radius: 99px; padding: 2px 8px; }
.au-sh-spacer { flex: 1; }
.au-sh-agg { display: inline-flex; align-items: center; gap: 7px; font-family: var(--au-mono, monospace); font-size: 10.5px; font-weight: 800; letter-spacing: 0.1em; padding: 3px 10px; border-radius: 99px; }
.au-sh-agg.st-ok { color: #7fe9c8; background: rgba(127,233,200,0.10); border: 1px solid rgba(127,233,200,0.3); }
.au-sh-agg.st-breach { color: #ff9b8a; background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.35); }
.au-sh-agg-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.au-sh-agg.st-breach .au-sh-agg-dot { animation: shPulse 1.5s ease-in-out infinite; }
.au-mono { font-family: var(--au-mono, ui-monospace, monospace); }

.au-sh-count { font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: .06em;
  opacity: .62; margin-left: 10px; }
.au-sh-unreach { font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: .05em;
  margin-left: 8px; color: #f6ad55; }
.au-sh-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.au-sh-card {
  border: 1px solid rgba(127,233,200,0.14); border-radius: 14px; padding: 16px 18px;
  background: linear-gradient(180deg, rgba(20,40,36,0.40), rgba(12,22,20,0.20));
}
.au-sh-card.st-breach { border: 1px solid rgba(248,113,113,0.45); background: linear-gradient(180deg, rgba(60,22,20,0.45), rgba(22,12,12,0.25)); }
.au-sh-card-head { display: flex; align-items: baseline; gap: 9px; margin-bottom: 3px; }
.au-sh-ccy { font-size: 14px; }
.au-sh-sym { font-weight: 800; color: #e6f5f0; font-size: 16px; letter-spacing: 0.02em; }
.au-sh-status { font-family: var(--au-mono, monospace); font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; padding: 1px 6px; border-radius: 5px; color: #0c1614; background: #7fe9c8; }
.au-sh-status.st-halted { background: #ffcf6b; } .au-sh-status.st-ipo { background: #b88bff; }
.au-sh-holders { margin-left: auto; font-size: 10.5px; color: #6f8a83; }
.au-sh-subhead { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.au-sh-name { font-size: 12px; color: #9fb8b2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.au-sh-frame { margin-left: auto; font-size: 9.5px; color: #6f8a83; }

/* Price ticker */
.au-sh-ticker { display: flex; align-items: center; gap: 7px; margin: 2px 0 10px; }
.au-sh-price { font-size: 20px; font-weight: 800; color: #e6f5f0; line-height: 1; }
.au-sh-price-ccy { font-size: 10px; color: #8aa39d; }
.au-sh-chg { font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; }
.au-sh-chg.up { color: #7fe9c8; } .au-sh-chg.down { color: #ff9b8a; } .au-sh-chg.flat { color: #9fb8b2; }
.au-sh-chg-win { font-size: 8.5px; color: #6f8a83; font-weight: 400; letter-spacing: 0.06em; }
.au-sh-activity { margin-left: auto; font-size: 10px; color: #9fb8b2; }
.au-sh-spark { margin-left: auto; width: 96px; height: 22px; display: inline-block; opacity: 0.95; }

/* Per-listing breach banner */
.au-sh-breach { display: flex; align-items: center; gap: 7px; margin: 0 0 10px; padding: 5px 9px; border-radius: 7px; background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.35); }
.au-sh-breach-dot { width: 7px; height: 7px; border-radius: 50%; background: #ff9b8a; animation: shPulse 1.5s ease-in-out infinite; flex: none; }
.au-sh-breach-txt { font-size: 10.5px; color: #ffb4a6; line-height: 1.35; }

.au-sh-headline { display: flex; align-items: baseline; gap: 9px; margin: 2px 0 10px; }
.au-sh-headline-v { font-size: 24px; font-weight: 800; color: #7fe9c8; line-height: 1; }
.au-sh-headline-u { font-size: 11px; color: #8aa39d; }
.au-sh-ok { margin-left: auto; color: #7fe9c8; font-size: 9.5px; }
.au-sh-warn { margin-left: auto; color: #ff9b8a; font-size: 9.5px; font-weight: 700; }

.au-sh-where-label { font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.12em; color: #6f8a83; margin: 10px 0 6px; }
.au-sh-bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; background: rgba(255,255,255,0.04); }
.au-sh-seg { height: 100%; }
.seg-treasury { background: #b88bff; }
.seg-public { background: #5bb3ff; }
.seg-unsold { background: #3d6e64; }
.seg-locked { background: #ffcf6b; }
.au-sh-legend { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 7px; }
.au-sh-leg { font-size: 10.5px; color: #9fb8b2; display: inline-flex; align-items: center; gap: 4px; }
.au-sh-leg b { color: #d6ece6; }
.au-sh-dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.au-sh-locked { margin-top: 6px; font-size: 10.5px; color: #d8b271; display: inline-flex; align-items: center; gap: 5px; }
.au-sh-dim { color: #6f8a83; }

.au-sh-holders-list { margin-top: 4px; }
.au-sh-holder { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 11.5px; }
.au-sh-rank { color: #51655f; width: 12px; font-family: var(--au-mono, monospace); }
.au-sh-htag { font-size: 9px; padding: 1px 6px; border-radius: 99px; color: #0c1614; font-weight: 700; }
.au-sh-htag.seg-treasury { background: #b88bff; } .au-sh-htag.seg-public { background: #5bb3ff; }
.au-sh-hdid { color: #8aa39d; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.au-sh-hpct { color: #9fb8b2; font-size: 10.5px; }
.au-sh-hval { color: #e6f5f0; min-width: 48px; text-align: right; }

.au-sh-recon { margin-top: 12px; border-top: 1px dashed rgba(127,233,200,0.16); padding-top: 8px; }
.au-sh-recon-sum { cursor: pointer; font-family: var(--au-mono, monospace); font-size: 9.5px; letter-spacing: 0.1em; color: #6f8a83; user-select: none; }
.au-sh-recon-sum:hover { color: #aee7d6; }
.au-sh-recon-note { font-size: 11px; color: #8aa39d; line-height: 1.5; margin: 8px 0 10px; max-width: 64ch; }
.au-sh-recon-note code { color: #aee7d6; background: rgba(127,233,200,0.07); padding: 1px 5px; border-radius: 4px; font-family: var(--au-mono, monospace); }
.au-sh-water { border-top: 1px dashed rgba(127,233,200,0.12); padding-top: 8px; }
.au-sh-row { display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0; font-size: 13px; }
.au-sh-k { color: #b6cfc9; }
.au-sh-v { color: #e6f5f0; font-size: 13px; }
.au-sh-sub-row .au-sh-k, .au-sh-sub-row .au-sh-v { color: #93ada7; font-size: 12px; }
.au-sh-total { margin-top: 4px; padding-top: 6px; border-top: 1px solid rgba(127,233,200,0.18); }
.au-sh-total .au-sh-k { font-weight: 800; color: #e6f5f0; }
.au-sh-total .au-sh-v { font-weight: 800; color: #7fe9c8; font-size: 14px; }

@keyframes shPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>
