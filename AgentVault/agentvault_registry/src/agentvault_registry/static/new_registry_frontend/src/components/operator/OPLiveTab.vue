<template>
  <section class="op-tab op-live">
    <!-- System resource row -->
    <div class="op-live-resources">
      <div class="op-live-resource-card" v-if="resources">
        <div class="op-live-resource-eyebrow">CPU</div>
        <div class="op-live-resource-figure">
          {{ resources.cpu?.percent?.toFixed(0) }}<span class="op-live-resource-unit">%</span>
        </div>
        <div class="op-live-resource-bar"><div class="op-live-resource-bar-fill"
          :style="{ width: clampPct(resources.cpu?.percent) + '%' }" /></div>
        <div class="op-live-resource-sub">{{ resources.cpu?.cores }} cores</div>
      </div>
      <div class="op-live-resource-card" v-if="resources">
        <div class="op-live-resource-eyebrow">Memory</div>
        <div class="op-live-resource-figure">
          {{ resources.memory?.percent?.toFixed(0) }}<span class="op-live-resource-unit">%</span>
        </div>
        <div class="op-live-resource-bar"><div class="op-live-resource-bar-fill"
          :style="{ width: clampPct(resources.memory?.percent) + '%' }" /></div>
        <div class="op-live-resource-sub">
          {{ humanBytes(resources.memory?.used_bytes) }} / {{ humanBytes(resources.memory?.total_bytes) }}
        </div>
      </div>
      <div class="op-live-resource-card" v-if="resources?.disk">
        <div class="op-live-resource-eyebrow">Disk</div>
        <div class="op-live-resource-figure">
          {{ resources.disk?.percent?.toFixed(0) }}<span class="op-live-resource-unit">%</span>
        </div>
        <div class="op-live-resource-bar"><div class="op-live-resource-bar-fill"
          :style="{ width: clampPct(resources.disk?.percent) + '%' }" /></div>
        <div class="op-live-resource-sub">
          {{ humanBytes(resources.disk?.used_bytes) }} / {{ humanBytes(resources.disk?.total_bytes) }}
        </div>
      </div>
      <div class="op-live-resource-card op-live-actions-card">
        <div class="op-live-resource-eyebrow">Auto-refresh</div>
        <button
          type="button"
          class="op-live-toggle"
          :class="{ 'op-live-toggle--on': autoRefresh }"
          @click="autoRefresh = !autoRefresh"
        >
          <span class="op-live-toggle-dot" />
          {{ autoRefresh ? 'On (10s)' : 'Off' }}
        </button>
        <button type="button" class="op-btn-ghost" @click="refreshAll" :disabled="loading">Refresh now</button>
      </div>
    </div>

    <div v-if="resLoadError && !resources" class="op-live-error">
      Couldn't load /admin/system-resources. {{ resLoadError }}
    </div>

    <!-- Event tail -->
    <div class="op-live-section">
      <div class="op-live-section-header">
        <h3 class="op-live-section-title">Recent events <span class="op-live-count">{{ events.length }}</span></h3>
        <div class="op-live-section-meta">
          <span v-if="eventsFetchedAt" class="op-live-meta-time">last fetch {{ formatRelative(eventsFetchedAt) }}</span>
        </div>
      </div>
      <div v-if="eventsLoadError" class="op-live-error">
        Couldn't load /admin/eventstore-recent. {{ eventsLoadError }}
      </div>
      <div v-else-if="events.length === 0 && !loading" class="op-live-empty">
        No events in the recent cache.
      </div>
      <div v-else class="op-live-event-table">
        <div class="op-live-event-row op-live-event-row--head">
          <span>time</span>
          <span>event_type</span>
          <span>aggregate</span>
        </div>
        <div v-for="(evt, i) in events" :key="evt.id || i" class="op-live-event-row">
          <span class="op-live-event-time">{{ shortTime(evt.timestamp) }}</span>
          <span :class="['op-live-event-type', `op-live-event-type--${eventTone(evt.event_type)}`]">
            {{ evt.event_type }}
          </span>
          <span class="op-live-event-agg">
            <code class="op-code">{{ shortAggregate(evt.aggregate_id) }}</code>
          </span>
        </div>
      </div>
    </div>

    <!-- Grafana iframe (best-effort — operators with Grafana exposed see panels; others see fallback) -->
    <div class="op-live-section">
      <div class="op-live-section-header">
        <h3 class="op-live-section-title">Operator dashboard</h3>
        <div class="op-live-section-meta">
          <a
            class="op-link"
            :href="safeExternalUrl(grafanaUrl)"
            target="_blank"
            rel="noopener"
            v-if="grafanaUrl"
          >Open in Grafana ↗</a>
        </div>
      </div>
      <div v-if="grafanaUrl" class="op-live-grafana-wrap">
        <iframe
          :src="grafanaUrl + '?orgId=1&kiosk=tv&refresh=30s'"
          class="op-live-grafana"
          loading="lazy"
          allowtransparency="true"
        ></iframe>
        <p class="op-live-grafana-caption">
          Embedded read-only. If the panel doesn't load, your Grafana may not be reachable from the browser
          or anonymous viewing is disabled — use the "Open in Grafana ↗" link above.
        </p>
      </div>
      <div v-else class="op-live-empty">
        No Grafana URL configured for this registry. Set <code class="op-code">GRAFANA_PUBLIC_URL</code>
        on your operator if you want embedded panels here.
      </div>
    </div>

    <!-- Local CLI bridge -->
    <div class="op-cli-bridge">
      <div class="op-cli-eyebrow">Stream logs locally</div>
      <LocalCommand
        :command="`tp logs registry --tail 100`"
        caption="Tails 100 lines from the registry container. Use --follow for live stream. Same as docker compose logs --tail 100 registry."
      />
      <LocalCommand
        :command="`tp logs teg --tail 100`"
        caption="TEG layer logs (transfers, fees, cross-frame settlements)."
      />
      <LocalCommand
        :command="`tp logs event-store --tail 100`"
        caption="EventStore logs (event submission, projections, replication)."
      />
      <LocalCommand
        :command="`tp doctor`"
        caption="Diagnostic snapshot — host + compose + disk + SPIRE bundle freshness + last 5 errors. Read-only. Paste in tickets."
      />
      <LocalCommand
        :command="`tp restart registry`"
        caption="Restarts ONLY the registry container. ~30s downtime. Other services unaffected. Acknowledge before running in business hours."
        tone="warning"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
import { ref, onMounted, onUnmounted, watch } from 'vue'
import LocalCommand from './LocalCommand.vue'
import { getRecentEvents, getSystemResources, type RecentEvent, type SystemResources } from '@/services/api/operator'

const resources = ref<SystemResources | null>(null)
const events = ref<RecentEvent[]>([])
const loading = ref(false)
const resLoadError = ref<string | null>(null)
const eventsLoadError = ref<string | null>(null)
const eventsFetchedAt = ref<string | null>(null)
const autoRefresh = ref(false)
let refreshTimer: number | null = null

// Grafana URL — built from env-injected runtime config (window-attached or computed
// from current host). If neither is available, hide the panel.
const grafanaUrl = ref<string | null>(null)
function resolveGrafanaUrl(): string | null {
  // Window-attached config (set by index.html template if operator wires it)
  const w = window as any
  if (w.__OPERATOR_GRAFANA_URL__) return w.__OPERATOR_GRAFANA_URL__
  // Heuristic: if current host has a grafana.* subdomain conventional sibling
  try {
    const host = window.location.host
    // Don't auto-attempt for prod mainframe (Commander uses dedicated Grafana)
    if (host.startsWith('grafana.') || host.startsWith('api.')) return null
    return null
  } catch { return null }
}

function clampPct(v: number | undefined | null): number {
  if (v === null || v === undefined) return 0
  return Math.max(0, Math.min(100, v))
}

function humanBytes(b: number | undefined | null): string {
  if (!b) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0; let n = b
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(n < 10 ? 1 : 0)} ${u[i]}`
}

function shortTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return iso }
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return 'never'
  try {
    const ms = Date.now() - new Date(iso).getTime()
    if (ms < 0) return 'just now'
    const s = Math.floor(ms / 1000); if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
    return `${Math.floor(m / 60)}h ago`
  } catch { return iso }
}

function shortAggregate(s: string | null | undefined): string {
  if (!s) return '—'
  if (s.length <= 28) return s
  // DID-style: did:theprotocol:<hex>
  if (s.startsWith('did:')) {
    const parts = s.split(':')
    if (parts.length >= 3 && parts[2].length > 12) {
      return `${parts[0]}:${parts[1]}:${parts[2].slice(0, 8)}…`
    }
  }
  return s.slice(0, 24) + '…'
}

function eventTone(t: string): string {
  const lower = (t || '').toLowerCase()
  if (lower.includes('issued') || lower.includes('mint') || lower.includes('created')) return 'mint'
  if (lower.includes('transferred')) return 'transfer'
  if (lower.includes('fee')) return 'fee'
  if (lower.includes('stake')) return 'stake'
  if (lower.includes('breach') || lower.includes('slash') || lower.includes('revoked')) return 'critical'
  if (lower.includes('dispute') || lower.includes('suspended')) return 'warn'
  return 'neutral'
}

async function refreshResources() {
  resLoadError.value = null
  try {
    resources.value = await getSystemResources()
  } catch (e: any) {
    resLoadError.value = e?.response?.data?.detail || e?.message || 'Network error'
  }
}

async function refreshEvents() {
  eventsLoadError.value = null
  try {
    const data = await getRecentEvents()
    // Newest first
    events.value = data.slice(0, 30)
    eventsFetchedAt.value = new Date().toISOString()
  } catch (e: any) {
    eventsLoadError.value = e?.response?.data?.detail || e?.message || 'Network error'
  }
}

async function refreshAll() {
  loading.value = true
  try { await Promise.all([refreshResources(), refreshEvents()]) }
  finally { loading.value = false }
}

function startAuto() {
  if (refreshTimer) return
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return
    refreshAll()
  }, 10_000)
}
function stopAuto() {
  if (refreshTimer) { window.clearInterval(refreshTimer); refreshTimer = null }
}

watch(autoRefresh, (on) => { on ? startAuto() : stopAuto() })

onMounted(() => {
  grafanaUrl.value = resolveGrafanaUrl()
  refreshAll()
})
onUnmounted(stopAuto)
defineExpose({ refresh: refreshAll })
</script>

<style scoped>
.op-tab { padding: 1.2rem 1.6rem 2rem; }

.op-live-resources {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.7rem;
}
.op-live-resource-card {
  padding: 0.9rem 1rem;
  background: rgba(0, 8, 14, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 3px;
  transition: border-color 0.25s;
}
.op-live-resource-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.32); }
.op-live-resource-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
  margin-bottom: 0.45rem;
}
.op-live-resource-figure {
  font-size: 1.55rem; font-weight: 600; color: #f4f9ff;
  font-family: 'IBM Plex Mono', monospace;
  line-height: 1;
}
.op-live-resource-unit {
  font-size: 0.85rem; color: rgba(255, 255, 255, 0.45); font-weight: 400; margin-left: 0.15rem;
}
.op-live-resource-bar {
  margin-top: 0.5rem;
  height: 4px;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 2px;
  overflow: hidden;
}
.op-live-resource-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.8), rgba(var(--nc-primary-rgb), 1));
  transition: width 0.4s ease;
}
.op-live-resource-sub {
  margin-top: 0.4rem;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.45);
  font-family: 'IBM Plex Mono', monospace;
}

.op-live-actions-card { display: flex; flex-direction: column; gap: 0.5rem; }
.op-live-toggle {
  display: inline-flex; align-items: center; gap: 0.5rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  color: rgba(255, 255, 255, 0.7);
  padding: 0.4rem 0.7rem;
  font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
  font-weight: 600; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, border-color 0.18s, color 0.18s;
}
.op-live-toggle:hover { border-color: rgba(var(--nc-primary-rgb), 0.4); color: rgba(255, 255, 255, 0.9); }
.op-live-toggle-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: rgba(255, 255, 255, 0.3);
}
.op-live-toggle--on {
  background: rgba(0, 230, 118, 0.1);
  border-color: rgba(0, 230, 118, 0.45);
  color: rgba(180, 255, 220, 1);
}
.op-live-toggle--on .op-live-toggle-dot {
  background: #00e676;
  box-shadow: 0 0 6px rgba(0, 230, 118, 0.7);
  animation: opLivePulse 1.6s ease-in-out infinite;
}
@keyframes opLivePulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.op-btn-ghost {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.65);
  padding: 0.4rem 0.7rem;
  font-size: 0.68rem; letter-spacing: 0.09em; text-transform: uppercase;
  font-weight: 600; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, color 0.18s, border-color 0.18s;
}
.op-btn-ghost:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.35);
  color: rgba(255, 255, 255, 0.85);
}
.op-btn-ghost:disabled { opacity: 0.4; }

.op-live-section { margin-top: 1.4rem; }
.op-live-section-header {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 0.6rem;
}
.op-live-section-title {
  margin: 0; font-size: 0.95rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: baseline; gap: 0.5rem;
}
.op-live-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  padding: 0.1rem 0.4rem;
  background: rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 2px;
  color: rgba(var(--nc-primary-rgb), 0.95);
  font-weight: 600;
}
.op-live-meta-time, .op-live-section-meta .op-link {
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.45);
  font-family: 'IBM Plex Mono', monospace;
}

.op-live-error {
  padding: 0.8rem 1rem;
  margin-top: 0.5rem;
  background: rgba(40, 16, 0, 0.5);
  border: 1px solid rgba(255, 176, 0, 0.32);
  border-radius: 2px;
  color: rgba(255, 200, 80, 0.95);
  font-size: 0.78rem;
}

.op-live-empty {
  padding: 1.8rem;
  text-align: center;
  background: rgba(0, 8, 14, 0.3);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 2px;
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.4);
}

.op-live-event-table {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 2px;
  overflow: hidden;
}
.op-live-event-row {
  display: grid; grid-template-columns: 95px 1fr 1.5fr;
  gap: 0.7rem;
  padding: 0.45rem 0.85rem;
  font-size: 0.78rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.04);
  transition: background 0.15s;
}
.op-live-event-row:hover { background: rgba(var(--nc-primary-rgb), 0.04); }
.op-live-event-row--head {
  background: rgba(0, 0, 0, 0.4);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; letter-spacing: 0.12em; text-transform: uppercase;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.4);
}
.op-live-event-row--head:hover { background: rgba(0, 0, 0, 0.4); }
.op-live-event-time {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.55);
}
.op-live-event-type {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem; font-weight: 600;
  letter-spacing: 0.01em;
}
.op-live-event-type--mint     { color: #b9ffe0; }
.op-live-event-type--transfer { color: #c0e4ff; }
.op-live-event-type--fee      { color: #d3c0ff; }
.op-live-event-type--stake    { color: #ffd8b0; }
.op-live-event-type--critical { color: #ffc4c4; }
.op-live-event-type--warn     { color: #ffe1a0; }
.op-live-event-type--neutral  { color: rgba(255, 255, 255, 0.7); }
.op-live-event-agg { display: flex; align-items: center; min-width: 0; }
.op-live-event-agg .op-code { font-size: 0.7rem; }

.op-live-grafana-wrap {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 2px;
  overflow: hidden;
}
.op-live-grafana {
  display: block;
  width: 100%;
  height: 540px;
  border: none;
  background: rgba(0, 0, 0, 0.45);
}
.op-live-grafana-caption {
  margin: 0; padding: 0.55rem 0.85rem;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.5;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.06);
  background: rgba(0, 0, 0, 0.2);
}

.op-link {
  color: rgba(var(--nc-primary-rgb), 0.9);
  text-decoration: none;
  border-bottom: 1px dotted rgba(var(--nc-primary-rgb), 0.35);
}
.op-link:hover { border-bottom-style: solid; }

.op-code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  background: rgba(0, 0, 0, 0.32);
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
  color: #c0e4ff;
}

.op-cli-bridge {
  margin-top: 1.8rem; padding-top: 1.3rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.op-cli-eyebrow {
  font-size: 0.65rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45); font-weight: 600;
  margin-bottom: 0.6rem;
}

@media (max-width: 768px) {
  .op-tab { padding: 1rem; }
  .op-live-event-row { grid-template-columns: 80px 1fr; }
  .op-live-event-row > :nth-child(3) { display: none; }
  .op-live-grafana { height: 380px; }
}
</style>
