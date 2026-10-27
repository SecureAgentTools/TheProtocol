<template>
  <!-- Self-hiding: renders NOTHING until /exchange/federation-tickers returns a
       live venue — fleet-safe everywhere (the registry aggregates server-side,
       so every registry's landing shows its parent frame's venue + its own,
       and the strip lights up by itself the moment any venue enables). -->
  <div v-if="show" class="xt" :class="{ compact, 'xt-rows-tape': rows === 'tape', 'xt-rows-main': rows === 'main' }" :data-rows="rows">
    <div v-if="rows !== 'tape'" class="xt-main">
      <div class="xt-label">
        <span class="xt-dot"></span>
        <Icon name="mdi:chart-candlestick" />
        <span class="xt-label-txt">{{ t('exchangeTicker.label') }}</span>
      </div>
      <button v-if="canScroll" class="xt-nav xt-nav-l" :disabled="atStart"
              :aria-label="t('exchangeTicker.scrollLeft', 'Scroll left')" @click="scrollBy(-1)">
        <Icon name="mdi:chevron-left" />
      </button>
      <div ref="trackEl" class="xt-track" @scroll.passive="onScroll">
        <template v-for="v in venues" :key="v.venue">
          <span class="xt-venue" :title="v.currency">{{ v.venue.toUpperCase() }}</span>
          <button
            v-for="l in v.listings" :key="v.venue + l.symbol"
            class="xt-chip" :class="{ halted: l.status === 'halted' }"
            :title="(l.display_name || l.symbol) + ' · ' + l.currency + ' · ' + v.venue"
            @click="goDesk"
          >
            <span class="xt-sym">${{ l.symbol }}</span>
            <span class="xt-px tick" :key="l.symbol + (l.last ?? '')">{{ fmtPx(l.last) }}</span>
            <span class="xt-chg" :class="chgClass(l.change_24h_pct)">{{ chgFmt(l.change_24h_pct) }}</span>
          </button>
        </template>
      </div>
      <button v-if="canScroll" class="xt-nav xt-nav-r" :disabled="atEnd"
              :aria-label="t('exchangeTicker.scrollRight', 'Scroll right')" @click="scrollBy(1)">
        <Icon name="mdi:chevron-right" />
      </button>
      <button v-if="cta" class="xt-cta" @click="goDesk">
        {{ t('exchangeTicker.cta') }} <Icon name="mdi:chevron-right" />
      </button>
    </div>
    <div class="xt-tape" v-if="rows !== 'main' && !compact && tapeItems.length" @mouseenter="paused = true" @mouseleave="paused = false">
      <div class="xt-tape-track" :class="{ paused }">
        <span v-for="(m, i) in tapeItems" :key="i" class="xt-print" :class="m.dir">
          <b>${{ m.symbol }}</b>
          <span class="xt-print-venue">{{ m.venue }}</span>
          <span class="xt-print-px">{{ m.dir === 'down' ? '▼' : m.dir === 'up' ? '▲' : '·' }} {{ fmtPx(m.price) }}</span>
          <span class="xt-print-qty">× {{ m.qty }}</span>
        </span>
      </div>
    </div>
  </div>
  <!-- §FRESHFRAME (2026-09-14, row 61): on a fresh frame the strip used to render NOTHING while the
       ledger beside it streamed, which reads as an outage. The main row now names the state the feed
       is in: an empty network (`venues: []`, the sandbox shape) or a feed that did not answer. The tape
       row stays silent: a tape with no prints is not an outage. Decision in services/frameHost.ts. -->
  <div v-else-if="rows === 'main' && (feedState === 'empty' || feedState === 'unreachable')" class="xt xt-empty" :data-state="feedState" data-testid="xt-empty">
    <span class="xt-dot xt-dot-dim"></span>
    <span class="xt-empty-txt">{{ feedState === 'empty' ? t('exchangeTicker.empty', 'No market lists points on this network yet.') : t('exchangeTicker.unreachable', 'The price feed is not answering.') }}</span>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * AGORA ExchangeTicker v2 (§V0064, 2026-06-13) — federation venue strip for
 * MissionControl + the public landing. Data: /exchange/federation-tickers
 * (server-side aggregate of every live venue — the §V-1r same-origin doctrine;
 * browsers never cross-origin the mainframes). Poll 20s; live-trades marquee
 * row (Desk-style, tick-rule colored) on the full variant.
 * App i18n is LEGACY mode — raw vue-i18n useI18n() throws (burned 2026-06-13);
 * always the app composable.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useFederationTickers, type TickVenue } from '@/services/exchange/federationTickers'
import { tickerState } from '@/services/frameHost'
import { useI18n } from '@/composables/useI18n'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'

/** §MCFOLD — `rows`: the whole two-row strip (default, the landing page and the Bridge), or
 *  ONE of its rows so Mission Control can fold the tape and the listings independently.
 *  Both rows read the ONE shared feed (`services/exchange/federationTickers.ts`). */
const props = withDefaults(defineProps<{ compact?: boolean; cta?: boolean; rows?: 'both' | 'main' | 'tape' }>(), { compact: false, cta: true, rows: 'both' })
const rows = computed(() => props.rows)
/**
 * `loaded` fires once the FIRST fetch settles, with how many venues came back.
 *
 * This component's root is `v-if="venues.length"`, so it renders NOTHING until
 * data arrives — fine when it is mounted at page load and nobody is watching,
 * but §BRIDGE mounts it on a click, and `/agora/federation-tickers` takes
 * 7-11s on this network. A host that cannot tell "still loading" from "nothing
 * here" shows an empty box and looks broken. Purely additive: every other mount
 * ignores it.
 */
const emit = defineEmits<{ (e: 'loaded', venueCount: number): void }>()

const { t } = useI18n()
const router = useRouter()
const feed = useFederationTickers()
const venues = feed.venues
const paused = ref(false)

// ── the AGORA strip scrolls. It listed every venue's every symbol in a flex row
//    that simply overflowed, so the only way to see the far end was to select the
//    text and drag. Two quiet buttons + a real overflow container fix that, and
//    they HIDE themselves when everything already fits (no furniture on a narrow
//    federation). Native scrolling still works — this only adds a handle.
const trackEl = ref<HTMLElement | null>(null)
const canScroll = ref(false)
const atStart = ref(true)
const atEnd = ref(false)

function onScroll() {
  const el = trackEl.value
  if (!el) return
  atStart.value = el.scrollLeft <= 1
  atEnd.value = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1
}
function measure() {
  const el = trackEl.value
  if (!el) { canScroll.value = false; return }
  canScroll.value = el.scrollWidth > el.clientWidth + 4
  onScroll()
}
function scrollBy(dir: number) {
  const el = trackEl.value
  if (!el) return
  el.scrollBy({ left: dir * Math.max(200, el.clientWidth * 0.8), behavior: 'smooth' })
}

const tapeItems = computed(() => {
  // 🔴 2026-08-27 — this was `venues.flatMap(v => v.trades).slice(0, 16)`, and the
  // flatMap is in VENUE ORDER. Every venue returns 8 prints, so the first 16 were
  // always registry-a's 8 + frame-b's 8: the tape showed SYBIL and BSEA and nothing
  // else, on a federation of 16 venues and 30 listings. A tape is CHRONOLOGICAL, so
  // sort by print time and the venues mix themselves — no round-robin needed, and a
  // genuinely busier venue is allowed to dominate honestly.
  const all = venues.value
    .flatMap(v => (v.trades || []).map(tr => ({ ...tr, venue: v.venue })))
    .sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')))
  if (all.length < 2) return []
  // newest-first; tick-rule = vs the NEXT (older) same-symbol print
  return all.slice(0, 28).map((tr, i) => {
    const older = all.slice(i + 1).find(x => x.symbol === tr.symbol)
    const cur = parseFloat(tr.price), prev = older ? parseFloat(older.price) : cur
    return { ...tr, dir: cur > prev ? 'up' : cur < prev ? 'down' : 'flat' }
  })
})

/** What this mount shows: a tape-only strip renders nothing until there are prints. */
const show = computed(() => rows.value === 'tape' ? tapeItems.value.length > 0 : (venues.value as TickVenue[]).length > 0)
const feedState = computed(() => tickerState(feed.loadedOnce.value, (venues.value as TickVenue[]).length, feed.lastError.value))
let announced = false
watch(feed.loadedOnce, (v) => { if (v && !announced) { announced = true; emit('loaded', (venues.value as TickVenue[]).length) } }, { immediate: true })

// 2026-06-17 — the strip + CTA now lead to the PUBLIC network-wide Stock
// Discovery view (/stocks), not the agent-gated Desk; traders drill into the
// Desk from a listing's "Trade on the Desk" button.
function goDesk() { void router.push('/agora/listings') }

function fmtPx(p?: string | null): string {
  const v = parseFloat(p || '')
  if (!isFinite(v)) return '—'
  if (v >= 1000) return v.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
  if (v >= 1) return v.toFixed(2)
  return v.toPrecision(3)
}
function chgClass(c?: string | null) { const v = parseFloat(c || '0'); return v > 0 ? 'up' : v < 0 ? 'down' : 'dim' }
function chgFmt(c?: string | null) { if (c == null) return '—'; const v = parseFloat(c); return `${v > 0 ? '▲' : v < 0 ? '▼' : ''}${Math.abs(v).toFixed(2)}%` }

let ro: ResizeObserver | undefined
onMounted(() => {
  feed.join()
  // the row's width changes with the window AND with the chip count
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => measure())
    if (trackEl.value) ro.observe(trackEl.value)
  }
  window.addEventListener('resize', measure)
})
watch(venues, () => { void nextTick(measure) })
onBeforeUnmount(() => {
  feed.leave()
  ro?.disconnect()
  window.removeEventListener('resize', measure)
})
</script>

<style scoped>
.xt {
  display: flex; flex-direction: column; gap: 0;
  border-radius: 11px; overflow: hidden;
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--nc-primary-rgb), 0.035);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  backdrop-filter: blur(9px);
}
.xt-main { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 9px 14px; }
/* the strip is now a real scroll container; the row must NOT wrap or it cannot scroll */
.xt-track { display: flex; align-items: center; gap: 8px; flex: 1 1 0; min-width: 0;
  overflow-x: auto; scroll-behavior: smooth; scrollbar-width: thin; padding-bottom: 2px; }
.xt-track::-webkit-scrollbar { height: 4px; }
.xt-track::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb), .30); border-radius: 999px; }
.xt-track > * { flex: none; }
.xt-nav { flex: none; width: 22px; height: 22px; display: inline-flex; align-items: center;
  justify-content: center; cursor: pointer; border-radius: 999px; background: none;
  color: rgba(var(--nc-primary-rgb), .85);
  border: 1px solid rgba(var(--nc-primary-rgb), .28); padding: 0; }
.xt-nav:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), .12); }
.xt-nav:disabled { opacity: .28; cursor: default; }
.xt-nav :deep(svg) { width: 14px; height: 14px; }
.xt-print-venue { font-family: ui-monospace, monospace; font-size: 8.5px; letter-spacing: .08em;
  text-transform: uppercase; opacity: .52; margin-left: 2px; }
.xt.compact .xt-main { padding: 6px 11px; gap: 10px; }
.xt-label { display: inline-flex; align-items: center; gap: 7px; font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.16em; color: rgba(var(--nc-primary-rgb), 0.9); flex: none; }
.xt-label :deep(svg) { width: 13px; height: 13px; }
.xt-dot { width: 6px; height: 6px; border-radius: 50%; background: #10b981; box-shadow: 0 0 7px rgba(16, 185, 129, 0.8); animation: xt-pulse 1.9s infinite; }
@keyframes xt-pulse { 50% { opacity: 0.45; } }
.xt-track { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.xt-track::-webkit-scrollbar { display: none; }
.xt-venue { flex: none; font-family: ui-monospace, monospace; font-size: 8px; letter-spacing: 0.16em; font-weight: 800; color: rgba(var(--nc-primary-rgb), 0.75); border: 1px solid rgba(var(--nc-primary-rgb), 0.3); border-radius: 5px; padding: 3px 7px; }
.xt-chip {
  display: inline-flex; align-items: baseline; gap: 7px; flex: none;
  padding: 4px 11px; border-radius: 8px; cursor: pointer;
  background: rgba(0, 0, 0, 0.22); border: 1px solid rgba(var(--nc-primary-rgb), 0.16);
  color: rgba(255, 255, 255, 0.88); font-family: ui-monospace, monospace; transition: border-color 0.15s;
}
.xt-chip:hover { border-color: rgba(var(--nc-primary-rgb), 0.5); }
.xt-chip.halted { opacity: 0.5; }
.xt-sym { font-weight: 800; font-size: 12px; color: rgba(var(--nc-primary-rgb), 0.95); }
.xt-px { font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
.xt-chg { font-size: 10px; font-variant-numeric: tabular-nums; }
.up { color: #10b981; } .down { color: #ef4444; } .flat { opacity: 0.8; } .dim { opacity: 0.55; }
.tick { display: inline-block; animation: xt-tick 0.45s ease-out; }
@keyframes xt-tick { 0% { transform: scale(1.08); } 100% { transform: scale(1); } }
.xt-cta {
  display: inline-flex; align-items: center; gap: 3px; flex: none; cursor: pointer;
  font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 0.1em; font-weight: 700;
  color: rgba(var(--nc-primary-rgb), 1); background: rgba(var(--nc-primary-rgb), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35); border-radius: 99px; padding: 5px 12px;
  min-height: 28px; transition: background 0.15s;
}
.xt-cta:hover { background: rgba(var(--nc-primary-rgb), 0.22); }
.xt-cta :deep(svg) { width: 12px; height: 12px; }

/* live-trades marquee (the full strip, or a tape-only mount — §MCFOLD) */
.xt.xt-rows-tape .xt-tape { border-top: 0; }
.xt-tape {
  overflow: hidden; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  background: rgba(0, 0, 0, 0.18);
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);
  mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);
}
.xt-tape-track { display: inline-flex; gap: 34px; padding: 5px 0; white-space: nowrap; animation: xt-scroll 34s linear infinite; }
.xt-tape-track.paused { animation-play-state: paused; }
@keyframes xt-scroll { from { transform: translateX(12%); } to { transform: translateX(-100%); } }
.xt-print { display: inline-flex; gap: 6px; align-items: baseline; font-family: ui-monospace, monospace; font-size: 10px; color: rgba(255, 255, 255, 0.7); }
.xt-print b { color: rgba(var(--nc-primary-rgb), 0.95); font-size: 10px; }
.xt-print-px { font-variant-numeric: tabular-nums; font-weight: 700; }
.xt-print.up .xt-print-px { color: #10b981; }
.xt-print.down .xt-print-px { color: #ef4444; }
.xt-print-qty { opacity: 0.55; font-size: 9px; }

@media (max-width: 639.98px) {
  .xt-main { gap: 9px; }
  .xt-label-txt { display: none; }
}
.xt-empty { display: flex; align-items: center; gap: 0.5rem; padding: 0.55rem 0.9rem; font-size: 0.78rem; letter-spacing: 0.02em; opacity: 0.72; }
.xt-dot-dim { opacity: 0.35; }
</style>
