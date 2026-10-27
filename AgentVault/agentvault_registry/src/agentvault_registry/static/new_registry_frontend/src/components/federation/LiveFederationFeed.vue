<script setup lang="ts">
// Federation Network — live event feed sidebar (Pass 5 — 2026-05-21).
// Collapsible right-side panel inside the Network tab. Shows the last N
// federation events with type pills + relative timestamps. Click an event
// to scroll/highlight the relevant peer.
//
// Pill color convention mirrors AdminEvents.vue's ae-pill--* — green for
// transfers/rewards, cyan for federation/topology, violet for governance,
// amber for warnings, red for errors, muted for misc.
//
// Collapse state persists in localStorage('theprotocol:federation:liveFeed:collapsed').
// Hidden on viewport width < 1024 (CSS @media; no JS gate needed).

import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { ledgerEventLabel } from '@/services/ledgerEventLabel'

export interface FeedEvent {
  id: string
  type: string
  ts: number          // Date.now() at receipt
  payload?: any       // optional; varies per event_type
  // §pass62.1 (2026-05-21) — true when this event was loaded from the backlog
  // on mount (via GET /admin/events) rather than received live via WebSocket.
  // Displayed with reduced opacity + a "HIST" tag so user can distinguish
  // "this happened before I opened the page" from "this just happened".
  historical?: boolean
}

const props = withDefaults(defineProps<{
  events: FeedEvent[]
  collapsed: boolean
  /** Optional title; defaults to LIVE FEED. */
  title?: string
  /** Optional ISO timestamp of the most-recent backlog event, used to render
   *  a helpful "last federation event was X hours ago" hint in the empty
   *  state when the feed has no live events yet (§pass62.1). */
  lastEventIso?: string | null
  /** §pass62.1 — true once the WebSocket has been observed as open at least
   *  once. Controls the "Listening" vs "Connecting…" copy. */
  wsConnected?: boolean
}>(), {
  collapsed: false,
  title: 'LIVE FEED',
  lastEventIso: null,
  wsConnected: true,
})

const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'highlight', evt: FeedEvent): void
}>()

// Map event type → pill color variant (mirrors AdminEvents.vue:typePillClass).
function eventPillVariant(eventType: string): 'cyan' | 'green' | 'violet' | 'indigo' | 'orange' | 'red' | 'muted' {
  const lower = (eventType || '').toLowerCase()
  if (lower.includes('token') || lower.includes('reward') || lower.includes('fee')) return 'green'
  if (lower.includes('cross') || lower.includes('bridge') || lower.includes('topology') || lower.includes('federation')) return 'cyan'
  if (lower.includes('governance') || lower.includes('proposal') || lower.includes('vote')) return 'violet'
  if (lower.includes('attestation')) return 'indigo'
  if (lower.includes('webhook') || lower.includes('compliance') || lower.includes('drift')) return 'orange'
  if (lower.includes('error') || lower.includes('breach') || lower.includes('revoked') || lower.includes('blocked')) return 'red'
  return 'muted'
}

function humanizeAgo(ts: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (s < 10) return 'now'
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h`
}

// §pass61.1 (2026-05-21) — reduced visible from 30 to 10 to prevent the wall
// of identical-type entries Commander caught after first §pass61 rollout (the
// dedup-by-event-id in Federation.vue suppresses replay storms; this caps
// what reaches the user even when they have legitimately different events).
const VISIBLE_CAP = 10
const visibleEvents = computed(() => props.events.slice(0, VISIBLE_CAP))
const eventCount = computed(() => props.events.length)
const overflowCount = computed(() => Math.max(0, eventCount.value - VISIBLE_CAP))

// §pass62.1 — pretty label for the "last federation event was X ago" hint.
const lastEventHint = computed(() => {
  if (!props.lastEventIso) return ''
  try {
    const diff = Date.now() - new Date(props.lastEventIso).getTime()
    if (diff < 60_000) return 'less than a minute ago'
    const m = Math.floor(diff / 60_000)
    if (m < 60) return `${m} minute${m === 1 ? '' : 's'} ago`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h} hour${h === 1 ? '' : 's'} ago`
    const d = Math.floor(h / 24)
    return `${d} day${d === 1 ? '' : 's'} ago`
  } catch {
    return ''
  }
})
</script>

<template>
  <aside class="lff" :class="{ 'lff--collapsed': collapsed }" :aria-expanded="!collapsed">
    <header class="lff-header">
      <button class="lff-toggle"
        :aria-label="collapsed ? 'Expand live feed' : 'Collapse live feed'"
        @click="emit('toggle')">
        <Icon :name="collapsed ? 'mdi:chevron-left' : 'mdi:chevron-right'" :size="14" />
      </button>
      <h3 v-if="!collapsed" class="lff-title">
        <span class="lff-dot"></span>
        {{ title }}
        <span v-if="eventCount > 0" class="lff-count">{{ eventCount }}</span>
      </h3>
      <h3 v-else class="lff-title-collapsed">
        <span class="lff-dot"></span>
      </h3>
    </header>

    <div v-if="!collapsed" class="lff-body">
      <ul v-if="visibleEvents.length > 0" class="lff-list">
        <li v-for="event in visibleEvents" :key="event.id"
          class="lff-item"
          :class="[`lff-item--${eventPillVariant(event.type)}`, { 'lff-item--historical': event.historical }]"
          tabindex="0"
          @click="emit('highlight', event)"
          @keyup.enter="emit('highlight', event)">
          <span class="lff-pill" :class="[`lff-pill--${eventPillVariant(event.type)}`]" :title="event.type">{{ ledgerEventLabel(event.type) }}</span>
          <span v-if="event.historical" class="lff-hist-tag" title="Loaded from event store on page open (not a live event)">HIST</span>
          <span class="lff-ago">{{ humanizeAgo(event.ts) }}</span>
        </li>
      </ul>
      <div v-else class="lff-empty">
        <Icon name="mdi:rss" :size="18" />
        <p class="lff-empty-line">{{ wsConnected ? 'Federation in steady state' : 'Connecting…' }}</p>
        <p v-if="lastEventHint" class="lff-empty-sub">Last federation event: {{ lastEventHint }}</p>
        <p v-else-if="wsConnected" class="lff-empty-sub">Listening on /ws/events for drift / sync / quarantine</p>
        <p v-else class="lff-empty-sub">Reconnecting to event stream…</p>
      </div>
      <div v-if="overflowCount > 0" class="lff-overflow">
        + {{ overflowCount }} older event{{ overflowCount === 1 ? '' : 's' }}
      </div>
    </div>
  </aside>
</template>

<style scoped>
.lff {
  position: absolute;
  top: 76px;     /* below the Network panel header */
  right: 14px;
  width: 240px;
  max-height: calc(100% - 100px);
  display: flex;
  flex-direction: column;
  background: var(--nc-overlay, #1d2438);
  border: 1px solid var(--nc-border-strong, #343a4d);
  border-radius: 6px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 6;
  overflow: hidden;
  transition: width 220ms cubic-bezier(0.4, 0, 0.2, 1);
}
.lff--collapsed {
  width: 36px;
}

.lff-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px 7px 6px;
  border-bottom: 1px solid var(--nc-border-subtle, rgba(255, 255, 255, 0.06));
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.02) 0%, transparent 100%);
}
.lff-toggle {
  flex-shrink: 0;
  width: 22px; height: 22px;
  background: transparent;
  color: var(--nc-text-muted, #94a3b8);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 3px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 200ms;
}
.lff-toggle:hover {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  color: var(--nc-primary-bright, #00e5e5);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3);
}
.lff-title,
.lff-title-collapsed {
  margin: 0;
  font-size: 0.66rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--nc-text-muted, #94a3b8);
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}
.lff-title-collapsed { justify-content: center; }
.lff-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--nc-success-bright, #4ade80);
  box-shadow: 0 0 6px rgba(0, 255, 136, 0.55);
  animation: lff-dot-pulse 2s ease-in-out infinite;
}
@keyframes lff-dot-pulse {
  0%, 100% { opacity: 0.5; transform: scale(1); }
  50%      { opacity: 1; transform: scale(1.2); }
}
.lff-count {
  margin-left: auto;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.6rem;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.1);
  color: var(--nc-primary-bright, #00e5e5);
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.2);
}

.lff-body {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.12) transparent;
}
.lff-body::-webkit-scrollbar { width: 4px; }
.lff-body::-webkit-scrollbar-track { background: transparent; }
.lff-body::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.12); border-radius: 2px; }

.lff-list {
  list-style: none;
  padding: 4px 0;
  margin: 0;
}
.lff-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  cursor: pointer;
  transition: background 160ms;
  border-left: 2px solid transparent;
}
.lff-item:hover,
.lff-item:focus {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06);
  outline: none;
  border-left-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.4);
}
.lff-item--cyan   { border-left-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25); }
.lff-item--green  { border-left-color: rgba(0, 255, 136, 0.25); }
.lff-item--violet { border-left-color: rgba(168, 85, 247, 0.25); }
.lff-item--indigo { border-left-color: rgba(99, 102, 241, 0.25); }
.lff-item--orange { border-left-color: rgba(255, 149, 0, 0.25); }
.lff-item--red    { border-left-color: rgba(255, 51, 102, 0.3); }
.lff-item--muted  { border-left-color: rgba(255, 255, 255, 0.05); }
/* §pass62.1 — Backfilled (historical) events: reduced opacity + dashed border so
   the user can distinguish them from genuinely live arrivals. */
.lff-item--historical { opacity: 0.62; border-left-style: dashed; }
.lff-item--historical:hover { opacity: 0.85; }

.lff-hist-tag {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.52rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  padding: 1px 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.12);
  flex-shrink: 0;
}

.lff-pill {
  flex: 1;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  letter-spacing: 0.02em;
  min-width: 0;
}
.lff-pill--cyan   { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.1); color: var(--nc-primary-bright, #00e5e5); }
.lff-pill--green  { background: rgba(0, 255, 136, 0.1); color: var(--nc-success-bright, #4ade80); }
.lff-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; }
.lff-pill--indigo { background: rgba(99, 102, 241, 0.1); color: #818cf8; }
.lff-pill--orange { background: rgba(255, 149, 0, 0.12); color: var(--nc-warning, #ff9500); }
.lff-pill--red    { background: rgba(255, 51, 102, 0.12); color: var(--nc-danger, #ff3366); }
.lff-pill--muted  { background: rgba(255, 255, 255, 0.05); color: var(--nc-text-muted, #94a3b8); }

.lff-ago {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.6rem;
  color: var(--nc-text-muted, #94a3b8);
  flex-shrink: 0;
  min-width: 28px;
  text-align: right;
}

.lff-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px 12px;
  text-align: center;
  color: var(--nc-text-muted, #94a3b8);
}
.lff-empty-line {
  margin: 6px 0 0;
  font-size: 0.7rem;
  font-weight: 500;
}
.lff-empty-sub {
  margin: 2px 0 0;
  font-size: 0.6rem;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  /* §FESUITE: no opacity: at 0.7 over the muted text it read 3.19:1, without it 4.99:1 (size and face set it apart) */
}

/* §pass61.1 — "+ N older events" overflow indicator */
.lff-overflow {
  padding: 6px 10px;
  font-size: 0.6rem;
  color: var(--nc-text-muted, #94a3b8);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  text-align: center;
  border-top: 1px dashed rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.01);
}

/* Mobile/tablet — hide live feed below desktop breakpoint */
@media (max-width: 1024px) {
  .lff { display: none }
}

@media (prefers-reduced-motion: reduce) {
  .lff-dot { animation: none }
  .lff { transition: none }
}
</style>
