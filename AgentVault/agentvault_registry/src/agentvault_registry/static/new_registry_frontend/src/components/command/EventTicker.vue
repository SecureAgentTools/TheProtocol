<template>
  <!-- GCC P8 — live event ticker: the local frame's EventStore stream, same-origin
       WS (nginx /ws/events{,-b,-c} — V-1r). Degrades silently when WS is
       unavailable (headless/test contexts can't open these — known gotcha). -->
  <div class="gcc-ticker" :class="{ 'gcc-ticker--open': open }" @contextmenu.stop>
    <div class="gcc-ticker-bar">
      <component
        :is="connected ? 'span' : 'button'"
        class="gcc-ticker-live" :class="{ 'gcc-ticker-live--on': connected, 'gcc-ticker-live--btn': !connected }"
        :type="connected ? undefined : 'button'"
        :title="connected ? 'stream connected' : 'click to reconnect'"
        @click="!connected && manualReconnect()"
      >
        <span class="gcc-ticker-dot"></span>{{ connected ? 'LIVE' : 'OFFLINE' }}
      </component>
      <span v-if="!availableFrames?.length" class="gcc-ticker-frame">{{ frameLabel }}</span>
      <span v-else class="gcc-ticker-tabs" role="tablist" aria-label="Frame stream">
        <button
          v-for="f in availableFrames" :key="f"
          class="gcc-ticker-tab" :class="{ 'gcc-ticker-tab--on': f === activeFrame }"
          type="button" role="tab" :aria-selected="f === activeFrame"
          :title="`Watch ${frameLabels?.[f] || f}'s event stream`"
          @click="$emit('switch-frame', f)"
        >{{ frameLabels?.[f] || f }}</button>
      </span>
      <!-- P10: supply-invariant tile for the watched frame (the system's trust signal) -->
      <span
        v-if="supply !== undefined"
        class="gcc-ticker-delta"
        :class="supply && supply.status === 'OK' ? 'gcc-ticker-delta--ok' : supply ? 'gcc-ticker-delta--bad' : 'gcc-ticker-delta--na'"
        :title="supply ? `Supply invariant on ${watchedLabel}: issued − destroyed + transit = circulating (Δ=${supply.delta})` : `No direct ES source for ${watchedLabel} from this registry`"
      >Δ {{ supply ? (supply.status === 'OK' ? `${supply.delta} OK` : `${supply.delta} ${supply.status}`) : '—' }}</span>
      <span v-if="latest && !open" class="gcc-ticker-latest" :class="{ 'gcc-ticker-hl': isHl(latest) }">
        <Icon :name="iconFor(latest.event_type)" :size="11" />
        <span class="gcc-ticker-type">{{ shortType(latest.event_type) }}</span>
        <span v-if="amountOf(latest)" class="gcc-ticker-amt">{{ amountOf(latest) }}</span>
        <span class="gcc-ticker-agg">{{ shortAgg(latest.aggregate_id) }}</span>
      </span>
      <span v-else-if="!open" class="gcc-ticker-latest gcc-ticker-idle">{{ connected ? 'awaiting events…' : 'stream unavailable' }}</span>
      <span class="gcc-ticker-count">{{ count }}</span>
      <button v-if="open" class="gcc-ticker-btn" type="button" :class="{ 'gcc-ticker-btn--on': manualPaused }" :title="manualPaused ? 'Resume stream' : 'Pause stream'" @click="togglePause">
        <Icon :name="manualPaused ? 'mdi:play' : 'mdi:pause'" :size="13" />
      </button>
      <button class="gcc-ticker-btn" type="button" :title="open ? 'Collapse stream' : 'Expand stream'" @click="toggle">
        <Icon :name="open ? 'mdi:chevron-up' : 'mdi:chevron-down'" :size="13" />
      </button>
    </div>

    <!-- GC2-4: type-filter chips — tame the firehose. Buffer stays unfiltered;
         only the DISPLAYED rows filter, so switching back loses nothing. -->
    <div v-if="open" class="gcc-ticker-filters">
      <button
        v-for="c in FILTER_CATS" :key="`fc-${c.id}`"
        class="gcc-ticker-fchip"
        :class="{ 'gcc-ticker-fchip--on': filterCat === c.id }"
        type="button"
        @click="filterCat = c.id"
      >{{ c.label }}</button>
    </div>
    <ul v-if="open" class="gcc-ticker-list" @mouseenter="hoverPaused = true" @mouseleave="hoverPaused = false">
      <li v-if="!rows.length" class="gcc-ticker-empty">{{ connected ? (filterCat === 'all' ? 'awaiting events…' : `no ${filterCat} events yet`) : 'stream unavailable in this context' }}</li>
      <li v-for="e in rows" :key="e.id" class="gcc-ticker-item">
        <div class="gcc-ticker-row" :class="{ 'gcc-ticker-hl': isHl(e), 'gcc-ticker-row--open': openId === e.id }" role="button" tabindex="0" @click="toggleRow(e.id)" @keydown.enter="toggleRow(e.id)">
          <span class="gcc-ticker-ts">{{ fmtTs(e) }}</span>
          <Icon :name="iconFor(e.event_type)" :size="11" class="gcc-ticker-ic" />
          <span class="gcc-ticker-type">{{ shortType(e.event_type) }}</span>
          <span v-if="amountOf(e)" class="gcc-ticker-amt">{{ amountOf(e) }}</span>
          <span class="gcc-ticker-agg" :title="e.aggregate_id">{{ shortAgg(e.aggregate_id) }}</span>
          <Icon :name="openId === e.id ? 'mdi:chevron-up' : 'mdi:chevron-down'" :size="10" class="gcc-ticker-rowchev" />
        </div>
        <pre v-if="openId === e.id" class="gcc-ticker-payload">{{ payloadOf(e) }}</pre>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { liveOld } from '@/services/ledgerNames'

interface TickerEvent {
  id: string
  event_type: string
  aggregate_id: string
  data: Record<string, any>
  timestamp: string
  raw: string
}

const props = defineProps<{
  /** The watched frame's ledger socket: an absolute wss:// URL (the frame manifest's `ledger_ws`, §FEFRAME W2) or
   *  a same-origin path. */
  wsPath: string
  /** §FEFRAME W2: tab labels by frame key (the manifest's display names); absent = the key itself. */
  frameLabels?: Record<string, string>
  frameLabel: string
  /** Soft-highlight events mentioning the selected registry (raw contains-match). */
  highlightKey: string | null
  /** P9 — frame letters offered as stream tabs (all paths exist on every vhost, V-1r). */
  availableFrames?: string[]
  activeFrame?: string
  /** P10 — watched frame's supply audit; null = no trustworthy source, undefined = hide tile. */
  supply?: { delta: number | null; status: string } | null
}>()
defineEmits<{ (e: 'switch-frame', f: string): void }>()

// §FEDEVENTS-5: tab mode watches "Frame X"; tab-less (single-frame deployment)
// watches whatever frameLabel says — never "Frame undefined".
const watchedLabel = computed(() => (props.activeFrame ? (props.frameLabels?.[props.activeFrame] || props.activeFrame) : props.frameLabel))

const MAX = 50
const open = ref(localStorage.getItem('gcc_ticker_open') === '1')
function toggle() {
  open.value = !open.value
  try { localStorage.setItem('gcc_ticker_open', open.value ? '1' : '0') } catch { /* private mode */ }
}

const connected = ref(false)
const count = ref(0)
const hoverPaused = ref(false)   // transient: freeze while the cursor is over the list
const manualPaused = ref(false)  // sticky: explicit pause button (survives mouseleave)
const openId = ref<string | null>(null)  // expanded payload row
// The list freezes whenever you're hovering, have hit pause, OR have a payload open.
// Pinning on an open payload is the key fix: inspecting an event holds the stream
// still until you close it, so the row you're reading can never reshuffle, scroll
// off, or blank out from under you (resumes the moment you collapse it).
const paused = computed(() => hoverPaused.value || manualPaused.value || openId.value !== null)
function togglePause() { manualPaused.value = !manualPaused.value }
function toggleRow(id: string) { openId.value = openId.value === id ? null : id }
const events = ref<TickerEvent[]>([])
const frozen = ref<TickerEvent[]>([])
const latest = computed(() => events.value[0] || null)

// GC2-4: client-side category filter over the already-parsed event types.
// The buffer itself is never filtered — only what's rendered.
const FILTER_CATS = [
  { id: 'all', label: 'All' },
  { id: 'market', label: 'Market' },
  { id: 'transfer', label: 'Transfers' },
  { id: 'fee', label: 'Fees' },
  { id: 'mint', label: 'Issued' },
  { id: 'enforce', label: 'Enforce' },
] as const
type FilterCat = typeof FILTER_CATS[number]['id']
const filterCat = ref<FilterCat>(((): FilterCat => {
  const s = sessionStorage.getItem('gccTickerCat')
  return (FILTER_CATS.some(c => c.id === s) ? s : 'all') as FilterCat
})())
watch(filterCat, v => { try { sessionStorage.setItem('gccTickerCat', v) } catch { /* private mode */ } })
function catOf(t: string): FilterCat | 'other' {
  // AGORA first — first-match-wins keeps exchange events out of 'transfer'
  if (/Exchange(Order|Trade|Listing|Dividend)/i.test(t)) return 'market'
  if (/Transfer|CrossRegistry|CrossFrame|FxRoute|Bridge/i.test(t)) return 'transfer'
  if (/Fee/i.test(t)) return 'fee'
  if (/Issued|Mint/i.test(t)) return 'mint'
  if (/Suspend|Enforc|Slash|Revok|Blocklist|Quarantin|Reinstat/i.test(t)) return 'enforce'
  return 'other'
}
const rows = computed(() => {
  const src = paused.value ? frozen.value : events.value
  const filtered = filterCat.value === 'all' ? src : src.filter(e => catOf(e.event_type) === filterCat.value)
  return filtered.slice(0, 12)
})
// Snapshot the on-screen list the INSTANT we pause, release it when we resume. The
// old design filled `frozen` lazily on the next incoming event, which blanked the
// list on hover (until an event arrived) and let the clicked row drop out — the bug.
watch(paused, (p) => { frozen.value = p ? events.value.slice() : [] })
function payloadOf(e: TickerEvent): string {
  try {
    return JSON.stringify({ event_type: e.event_type, aggregate_id: e.aggregate_id, timestamp: e.timestamp, data: e.data }, null, 2).slice(0, 4000)
  } catch { return String(e.raw || '').slice(0, 4000) }
}

// ── WS client (protocol per eventStoreWebSocket.ts: subscribe events:all, 30s ping,
//    bounded backoff reconnect). Self-contained — no global singletons.
let ws: WebSocket | null = null
let pingTimer: ReturnType<typeof setInterval> | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let attempts = 0
let closedForGood = false

function wsUrl() {
  if (/^wss?:\/\//.test(props.wsPath)) return props.wsPath
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${props.wsPath}`
}
function connect() {
  if (closedForGood) return
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
  try {
    ws = new WebSocket(wsUrl())
  } catch { scheduleReconnect(); return }
  ws.onopen = () => {
    connected.value = true
    attempts = 0
    try { ws?.send(JSON.stringify({ action: 'subscribe', channel: 'events:all' })) } catch { /* race */ }
    if (pingTimer) clearInterval(pingTimer)
    pingTimer = setInterval(() => { try { ws?.send(JSON.stringify({ action: 'ping' })) } catch { /* closed */ } }, 30000)
  }
  ws.onmessage = (m) => {
    try {
      const d = JSON.parse(m.data)
      if (d.type === 'event' && d.event) {
        const ev: TickerEvent = {
          id: d.event.id || `${Date.now()}-${count.value}`,
          event_type: d.event.event_type || 'unknown',
          aggregate_id: d.event.aggregate_id || '',
          data: d.event.data || {},
          timestamp: d.event.timestamp || '',
          raw: typeof m.data === 'string' ? m.data : '',
        }
        // While paused the display reads the frozen snapshot, so just keep the live
        // buffer flowing underneath — resuming catches straight up to it. (Freezing is
        // handled by the watch(paused) above; no per-message frozen bookkeeping here.)
        events.value.unshift(ev)
        if (events.value.length > MAX) events.value.length = MAX
        count.value++
      }
    } catch { /* non-JSON keepalives */ }
  }
  ws.onclose = () => { connected.value = false; if (pingTimer) { clearInterval(pingTimer); pingTimer = null }; scheduleReconnect() }
  ws.onerror = () => { connected.value = false }
}
function scheduleReconnect() {
  if (closedForGood || attempts >= 5) return
  attempts++
  reconnectTimer = setTimeout(connect, 2000 * attempts)
}
/** P11 — manual rejoin after the backoff cap gave up (click the OFFLINE badge). */
function manualReconnect() {
  attempts = 0
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  connect()
}

onMounted(() => {
  connect()
  // Debug/preview hook (mirrors window.__gmReg): seed N synthetic events so the ticker
  // is exercisable where the WS can't open (headless/CI) and to preview the inspect UX.
  ;(window as unknown as { __gccTickerSeed?: (n?: number) => void }).__gccTickerSeed = (n = 8) => {
    for (let i = 0; i < n; i++) {
      events.value.unshift({
        id: `seed-${count.value}`, event_type: i % 2 ? 'TokensTransferred' : 'FxRouteSettled',
        aggregate_id: `did:demo:agent-${count.value}`, data: { amount: 100 + i, note: 'synthetic' },
        timestamp: new Date().toISOString(), raw: `seed-${count.value}`,
      })
      count.value++
    }
    if (events.value.length > MAX) events.value.length = MAX
  }
})
onBeforeUnmount(() => {
  closedForGood = true
  try { delete (window as unknown as { __gccTickerSeed?: unknown }).__gccTickerSeed } catch { /* ignore */ }
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (pingTimer) clearInterval(pingTimer)
  try { ws?.close() } catch { /* already closed */ }
})

// P9 — frame tab switch: tear down the old socket cleanly and rejoin the new stream.
watch(() => props.wsPath, () => {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (pingTimer) { clearInterval(pingTimer); pingTimer = null }
  const old = ws
  ws = null
  if (old) { old.onclose = null; old.onmessage = null; old.onerror = null; try { old.close() } catch { /* already closed */ } }
  connected.value = false
  events.value = []; frozen.value = []; count.value = 0
  openId.value = null   // drop any open payload — it belonged to the previous frame's stream
  attempts = 0
  connect()
})

// ── presentation helpers ─────────────────────────────────────────────────────
const ICONS: Record<string, string> = {
  TokensTransferred: 'mdi:bank-transfer',
  TokensIssued: 'mdi:plus-circle',
  TokensStaked: 'mdi:wallet',
  TransactionFeeCollected: 'mdi:cash-multiple',
  LedgerBalanceChanged: 'mdi:sync',
}
const iconFor = (t: string) => ICONS[liveOld(t)] || (t.startsWith('Fx') ? 'mdi:swap-horizontal' : 'mdi:radio-tower')
const shortType = (t: string) => t.replace(/^(Tokens|Transaction|Ledger)/, '').replace(/([a-z])([A-Z])/g, '$1 $2')
const shortAgg = (a: string) => {
  if (!a) return ''
  return a.length > 22 ? `${a.slice(0, 14)}…${a.slice(-5)}` : a
}
const amountOf = (e: TickerEvent) => {
  const v = e.data?.amount ?? e.data?.value ?? null
  if (v == null) return ''
  const n = Number(v)
  return Number.isFinite(n) ? Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n) : String(v)
}
const fmtTs = (e: TickerEvent) => {
  const d = e.timestamp ? new Date(e.timestamp) : null
  return d && !Number.isNaN(+d) ? d.toLocaleTimeString(appLocale(), { hour12: false }) : ''
}
const isHl = (e: TickerEvent) => {
  const k = (props.highlightKey || '').toLowerCase()
  return !!k && e.raw.toLowerCase().includes(k)
}
</script>

<style scoped>
.gcc-ticker {
  position: absolute; top: 10px; right: 10px; z-index: 35;
  width: 360px; max-width: calc(100% - 20px);
  background: rgba(8, 12, 20, 0.88);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .22);
  border-radius: 10px;
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 8px 28px rgba(0,0,0,.45);
}
/* P11 mobile: full-width compact bar at the top of the stage (deck stays desktop-only) */
@media (max-width: 1024px) {
  .gcc-ticker { left: 10px; right: 10px; width: auto; }
  .gcc-ticker-list { max-height: 130px; }
}
.gcc-ticker-bar { display: flex; align-items: center; gap: 8px; padding: 6px 9px; min-width: 0; }
.gcc-ticker-live {
  display: inline-flex; align-items: center; gap: 5px; flex: 0 0 auto;
  font-size: .56rem; font-weight: 800; letter-spacing: .14em;
  color: var(--nc-text-muted, #94a3b8);
}
.gcc-ticker-live--on { color: #10b981; }
.gcc-ticker-live--btn { background: transparent; border: 1px dashed rgba(255,255,255,.2); border-radius: 4px; padding: 1px 5px; cursor: pointer; }
.gcc-ticker-live--btn:hover { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); }
.gcc-ticker-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.gcc-ticker-live--on .gcc-ticker-dot { animation: gcc-tick-pulse 1.6s ease-in-out infinite; }
@keyframes gcc-tick-pulse { 50% { opacity: .35; } }
.gcc-ticker-frame {
  flex: 0 0 auto; font-size: .56rem; font-weight: 800; padding: 0 5px; border-radius: 3px;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .12); border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .3);
  color: var(--nc-primary, #00d2d2);
}
.gcc-ticker-tabs { display: inline-flex; gap: 3px; flex: 0 0 auto; }
.gcc-ticker-tab {
  min-width: 20px; height: 18px; padding: 0 4px; border-radius: 4px; cursor: pointer;
  font-size: .56rem; font-weight: 800;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1);
  color: var(--nc-text-muted, #94a3b8);
}
.gcc-ticker-tab--on {
  background: rgba(var(--nc-primary-rgb, 0,210,210), .14);
  border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45);
  color: var(--nc-primary, #00d2d2);
}
.gcc-ticker-delta {
  flex: 0 0 auto; font-size: .56rem; font-weight: 800; padding: 1px 5px; border-radius: 4px;
  font-variant-numeric: tabular-nums; letter-spacing: .04em;
}
.gcc-ticker-delta--ok { background: rgba(16,185,129,.1); border: 1px solid rgba(16,185,129,.4); color: #10b981; }
.gcc-ticker-delta--bad { background: rgba(239,68,68,.12); border: 1px solid rgba(239,68,68,.5); color: #ef4444; }
.gcc-ticker-delta--na { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); color: var(--nc-text-muted, #94a3b8); }
.gcc-ticker-latest {
  flex: 1 1 auto; min-width: 0; display: inline-flex; align-items: center; gap: 6px;
  font-size: .64rem; color: var(--nc-text-primary, #e8eaed);
  overflow: hidden; white-space: nowrap;
}
.gcc-ticker-idle { color: var(--nc-text-muted, #94a3b8); font-style: italic; }
.gcc-ticker-count { flex: 0 0 auto; font-size: .6rem; color: var(--nc-text-muted, #94a3b8); font-variant-numeric: tabular-nums; }
.gcc-ticker-btn {
  flex: 0 0 auto; width: 22px; height: 22px; display: grid; place-items: center;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); border-radius: 6px;
  color: var(--nc-text-muted, #94a3b8); cursor: pointer;
}
.gcc-ticker-btn:hover { color: var(--nc-primary, #00d2d2); }
.gcc-ticker-btn--on { color: #fbbf24; border-color: rgba(245,158,11,.5); background: rgba(245,158,11,.12); }
.gcc-ticker-filters {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  padding: 4px 9px 2px;
}
.gcc-ticker-fchip {
  flex: 0 0 auto; padding: 1px 8px; border-radius: 999px;
  font-size: .56rem; font-weight: 700; letter-spacing: .04em;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1);
  color: var(--nc-text-muted, #94a3b8); cursor: pointer;
}
.gcc-ticker-fchip:hover { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .4); }
.gcc-ticker-fchip--on {
  background: rgba(var(--nc-primary-rgb, 0,210,210), .14);
  border-color: rgba(var(--nc-primary-rgb, 0,210,210), .55);
  color: var(--nc-primary, #00d2d2);
}
.gcc-ticker-list {
  list-style: none; margin: 0; padding: 2px 9px 8px;
  display: grid; gap: 3px; max-height: 200px; overflow-y: auto;
  scrollbar-width: thin;
}
.gcc-ticker-empty { font-size: .64rem; color: var(--nc-text-muted, #94a3b8); font-style: italic; padding: 4px 0; }
.gcc-ticker-item { display: grid; gap: 0; }
.gcc-ticker-row {
  display: flex; align-items: center; gap: 6px; min-width: 0;
  font-size: .62rem; font-family: ui-monospace, monospace;
  padding: 3px 6px; border-radius: 5px;
  background: rgba(255,255,255,.02); cursor: pointer;
}
.gcc-ticker-row:hover { background: rgba(var(--nc-primary-rgb, 0,210,210), .08); }
.gcc-ticker-row--open { background: rgba(var(--nc-primary-rgb, 0,210,210), .12); }
.gcc-ticker-rowchev { flex: 0 0 auto; color: var(--nc-text-muted, #94a3b8); }
.gcc-ticker-payload {
  margin: 2px 0 0; padding: 6px 8px; border-radius: 5px; max-height: 150px; overflow: auto;
  background: rgba(4,8,14,.6); border: 1px solid rgba(255,255,255,.08);
  font-size: .58rem; line-height: 1.45; color: var(--nc-text-muted, #cbd5e1);
  font-family: ui-monospace, monospace; white-space: pre-wrap; word-break: break-word;
}
.gcc-ticker-hl { background: rgba(var(--nc-primary-rgb, 0,210,210), .1); box-shadow: inset 2px 0 0 var(--nc-primary, #00d2d2); }
.gcc-ticker-ts { flex: 0 0 auto; color: var(--nc-text-muted, #94a3b8); }
.gcc-ticker-ic { flex: 0 0 auto; color: var(--nc-primary, #00d2d2); }
.gcc-ticker-type { flex: 0 0 auto; font-weight: 700; }
.gcc-ticker-amt { flex: 0 0 auto; font-weight: 800; color: #10b981; font-variant-numeric: tabular-nums; }
.gcc-ticker-agg { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--nc-text-muted, #94a3b8); }
</style>
