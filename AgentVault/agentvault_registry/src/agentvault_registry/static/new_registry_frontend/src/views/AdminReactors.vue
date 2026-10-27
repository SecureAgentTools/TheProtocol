<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { ref, computed } from 'vue'
import { apiClient } from '@/services/api/client'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import WorkerTasksPanel from '@/components/admin/WorkerTasksPanel.vue'
import { usePolledData } from '@/composables/usePolledData'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

dayjs.extend(relativeTime)

interface ReactorStatus {
  name: string
  event_type: string
  leader_key: string
  running: boolean
  is_leader: boolean
  leader_worker?: string | null
  ws_connected: boolean
  started_at: string | null
  dispatch_count: number
  error_count: number
  dedup_count: number
  last_event_at: string | null
  last_event_id: string | null
  last_dispatch_ms: number | null
  last_error: string | null
}

interface ReactorStatusResponse {
  summary: {
    total_reactors: number
    leaders: number
    ws_connected: number
    lifetime_dispatches: number
    lifetime_errors: number
  }
  reactors: ReactorStatus[]
  snapshot_at: string
}

const error = ref('')
const autoRefresh = ref(true)

// Build #4 (2026-05-07): tabs for Reactors (existing) + Worker Tasks (new).
type TabId = 'reactors' | 'workers'
const activeTab = ref<TabId>('reactors')

// Visibility-guarded polling via shared composable (#6, 2026-05-08).
// Replaces the prior hand-rolled setInterval (which had no
// document.visibilityState check, so it kept polling in background tabs).
const polled = usePolledData<ReactorStatusResponse>(async () => {
  try {
    const resp = await apiClient.get<ReactorStatusResponse>('/admin/reactor/status')
    error.value = ''
    return resp.data
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    error.value = `Failed to load reactor status: ${msg}`
    throw e
  }
}, { interval: 10_000, autoStart: autoRefresh.value })

const data = polled.data
const loading = polled.loading
const lastRefreshAt = computed(() =>
  polled.lastFetchAt.value ? dayjs(polled.lastFetchAt.value).format('HH:mm:ss') : ''
)

const fetchStatus = () => polled.refetch()

const toggleAutoRefresh = () => {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    polled.resume()
    polled.refetch()
  } else {
    polled.pause()
  }
}

const sortedReactors = computed(() => {
  if (!data.value) return []
  return [...data.value.reactors].sort((a, b) => {
    if (a.is_leader !== b.is_leader) return b.is_leader ? 1 : -1
    return a.name.localeCompare(b.name)
  })
})

// P5.2 (2026-05-08): Recent Dispatches feed.
// Each reactor reports its most-recent event via the backend snapshot
// (`last_event_at`, `last_event_id`, `last_dispatch_ms`, `last_error`).
// We aggregate across all reactors, sort by `last_event_at` DESC, and
// display as a time-ordered feed below the cards. Filter chips: all /
// errored. No backend changes — pure-frontend over the existing data.
type LogFilter = 'all' | 'errored'
const logFilter = ref<LogFilter>('all')

interface DispatchLogEntry {
  reactor: string
  event_type: string
  event_id: string | null
  fired_at: string
  fired_at_relative: string
  latency_ms: number | null
  error: string | null
  is_leader: boolean
  ws_connected: boolean
}

// All reactor dispatches in time-DESC order, regardless of filter
const allDispatches = computed<DispatchLogEntry[]>(() => {
  if (!data.value) return []
  return data.value.reactors
    .filter((r) => !!r.last_event_at)
    .map((r) => ({
      reactor: r.name,
      event_type: r.event_type,
      event_id: r.last_event_id,
      fired_at: r.last_event_at as string,
      fired_at_relative: lastEventRelative(r.last_event_at),
      latency_ms: r.last_dispatch_ms,
      error: r.last_error,
      is_leader: r.is_leader,
      ws_connected: r.ws_connected,
    }))
    .sort((a, b) => (b.fired_at || '').localeCompare(a.fired_at || ''))
})

const recentDispatches = computed<DispatchLogEntry[]>(() => {
  if (logFilter.value === 'errored') return allDispatches.value.filter((e) => !!e.error)
  return allDispatches.value
})

const erroredDispatchCount = computed(
  () => allDispatches.value.filter((e) => !!e.error).length,
)

const lastEventRelative = (iso: string | null): string => {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}

const formatMs = (ms: number | null): string => {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1) return '<1ms'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

const cardClass = (r: ReactorStatus): string[] => {
  const classes = ['ar-card']
  if (!r.running) classes.push('ar-card-stopped')
  if (r.error_count > 0) classes.push('ar-card-warn')
  if (r.is_leader && r.ws_connected) classes.push('ar-card-active')
  if (r.is_leader && !r.ws_connected) classes.push('ar-card-degraded')
  return classes
}

const statusLabel = (r: ReactorStatus): string => {
  if (!r.running) return 'STOPPED'
  if (r.is_leader && r.ws_connected) return 'LEADER · LIVE'
  if (r.is_leader && !r.ws_connected) return 'LEADER · WS DISCONNECTED'
  return 'STANDBY'
}

const statusColorClass = (r: ReactorStatus): string => {
  if (!r.running) return 'ar-dot-bad'
  if (r.is_leader && r.ws_connected) return 'ar-dot-ok'
  if (r.is_leader && !r.ws_connected) return 'ar-dot-warn'
  return 'ar-dot-muted'
}
</script>

<template>
<div class="ar">
  <!-- Ambient -->
  <div class="ar-ambient">
    <div class="ar-grid"></div>
    <div class="ar-scan"></div>
    <div class="ar-glow ar-glow-1"></div>
    <div class="ar-glow ar-glow-2"></div>
  </div>

  <!-- Hero -->
  <section class="ar-hero" data-tour="reactors-hero">
    <div class="ar-hero-inner">
      <div class="ar-chip"><span class="ar-chip-dot"></span>{{ t('adminReactorsView.hero.chip') }}</div>
      <h1 class="ar-h1">{{ t('adminReactorsView.hero.h1a') }}<span class="ar-accent">{{ t('adminReactorsView.hero.h1Accent') }}</span>{{ t('adminReactorsView.hero.h1b') }}</h1>
      <p class="ar-lead">{{ t('adminReactorsView.hero.lead') }}</p>
    </div>
  </section>

  <!-- Tab bar (Build #4) -->
  <div class="ar-tabbar-wrap">
    <div class="ar-tabbar">
      <button
        class="ar-tabbar-btn"
        :class="{ 'ar-tabbar-btn--active': activeTab === 'reactors' }"
        @click="activeTab = 'reactors'"
        aria-label="Show event-store reactors"
      >
        <span class="ar-tabbar-icon">⏣</span>
        <span class="ar-tabbar-label">{{ t('adminReactorsView.tabs.reactors') }}</span>
        <span v-if="data?.reactors?.length" class="ar-tabbar-count">{{ data.reactors.length }}</span>
      </button>
      <button
        class="ar-tabbar-btn"
        :class="{ 'ar-tabbar-btn--active': activeTab === 'workers' }"
        @click="activeTab = 'workers'"
        aria-label="Show background worker tasks"
      >
        <span class="ar-tabbar-icon"><Icon name="mdi:cog" /></span>
        <span class="ar-tabbar-label">{{ t('adminReactorsView.tabs.workers') }}</span>
      </button>
    </div>
  </div>

  <!-- Worker Tasks panel — new -->
  <div v-if="activeTab === 'workers'">
    <WorkerTasksPanel />
  </div>

  <!-- Reactors content — preserved exactly, now gated by tab -->
  <div v-else>

  <!-- Loading -->
  <div v-if="loading" class="ar-center">
    <div class="ar-spinner"></div>
    <p class="ar-loading-text">Querying reactor framework…</p>
  </div>

  <!-- Error -->
  <div v-else-if="error" class="ar-center">
    <p class="ar-error-text">{{ error }}</p>
    <button @click="fetchStatus" class="ar-btn ar-btn-ghost" style="margin-top:12px;">Retry</button>
  </div>

  <!-- Dashboard -->
  <div v-else-if="data" class="ar-section">
    <!-- Summary stats -->
    <div class="ar-stats-row">
      <div class="ar-stat ar-stat-cyan">
        <span class="ar-stat-label">Reactors</span>
        <span class="ar-stat-value">{{ data.summary.total_reactors }}</span>
      </div>
      <div class="ar-stat" :class="data.summary.leaders > 0 ? 'ar-stat-ok' : 'ar-stat-warn'">
        <span class="ar-stat-label">Leaders</span>
        <span class="ar-stat-value">{{ data.summary.leaders }}</span>
        <span class="ar-stat-sub">on this worker</span>
      </div>
      <div class="ar-stat" :class="data.summary.ws_connected > 0 ? 'ar-stat-ok' : 'ar-stat-muted'">
        <span class="ar-stat-label">WS Live</span>
        <span class="ar-stat-value">{{ data.summary.ws_connected }}</span>
      </div>
      <div class="ar-stat ar-stat-cyan">
        <span class="ar-stat-label">Dispatches</span>
        <span class="ar-stat-value">{{ data.summary.lifetime_dispatches }}</span>
        <span class="ar-stat-sub">since start</span>
      </div>
      <div class="ar-stat" :class="data.summary.lifetime_errors > 0 ? 'ar-stat-bad' : 'ar-stat-muted'">
        <span class="ar-stat-label">Errors</span>
        <span class="ar-stat-value">{{ data.summary.lifetime_errors }}</span>
      </div>
    </div>

    <!-- Refresh + per-worker note -->
    <div class="ar-toolbar">
      <div class="ar-toolbar-info">
        <span class="ar-mono-label">{{ t('common.lastRefresh') }}</span>
        <span class="ar-mono-value">{{ lastRefreshAt || '—' }}</span>
        <span class="ar-mono-label" style="margin-left: 14px;">Auto:</span>
        <span class="ar-mono-value">{{ autoRefresh ? '10s' : 'off' }}</span>
      </div>
      <div class="ar-toolbar-actions">
        <button class="ar-btn ar-btn-ghost" @click="toggleAutoRefresh">
          {{ autoRefresh ? 'Pause' : 'Resume' }}
        </button>
        <button class="ar-btn ar-btn-primary" @click="fetchStatus">
          ↻ Refresh
        </button>
      </div>
    </div>

    <div class="ar-note ar-note-info">
      <span class="ar-note-icon">ⓘ</span>
      <div class="ar-note-body">
        <strong class="ar-note-title">Reading the data</strong>
        <span class="ar-note-text">
          All fields shown — <code>dispatch_count</code>, <code>error_count</code>,
          <code>dedup_count</code>, <code>last_event_at</code>, <code>LEADER</code>,
          <code>WS</code>, and the summary tiles — are
          <strong>aggregated cross-worker</strong>.
          Counters live in a Redis HASH (Phase&nbsp;C3); leadership and WS state
          are derived from the <code>leader:</code> lease keys + the leader's
          HASH writes (Phase&nbsp;C4). Each card shows the cluster's view of the
          reactor, not the snapshot worker's. <code>leader_worker</code>
          identifies which uvicorn worker currently holds the lease.
        </span>
      </div>
    </div>

    <!-- Reactor cards -->
    <div class="ar-cards">
      <div v-for="r in sortedReactors" :key="r.leader_key" :class="cardClass(r)">
        <div class="ar-card-head">
          <div class="ar-card-title-row">
            <span class="ar-dot" :class="statusColorClass(r)"></span>
            <h3 class="ar-card-title">{{ r.name }}</h3>
          </div>
          <span class="ar-card-status">{{ statusLabel(r) }}</span>
        </div>

        <div class="ar-card-body">
          <div class="ar-card-row">
            <span class="ar-mono-label">Event</span>
            <code class="ar-code">{{ r.event_type }}</code>
          </div>
          <div class="ar-card-row">
            <span class="ar-mono-label">Lock</span>
            <code class="ar-code-muted">{{ r.leader_key }}</code>
          </div>
          <div v-if="r.leader_worker" class="ar-card-row">
            <span class="ar-mono-label">Leader</span>
            <code class="ar-code-muted ar-code-trunc" :title="r.leader_worker">{{ r.leader_worker }}</code>
          </div>
          <div class="ar-card-row">
            <span class="ar-mono-label">Started</span>
            <span class="ar-card-val">{{ r.started_at ? dayjs(r.started_at).format('HH:mm:ss') : '—' }}</span>
          </div>

          <div class="ar-card-divider"></div>

          <div class="ar-stat-grid">
            <div class="ar-mini-stat">
              <span class="ar-mini-stat-label">Dispatches</span>
              <span class="ar-mini-stat-value ar-mini-stat-ok">{{ r.dispatch_count }}</span>
            </div>
            <div class="ar-mini-stat">
              <span class="ar-mini-stat-label">Errors</span>
              <span
                class="ar-mini-stat-value"
                :class="r.error_count > 0 ? 'ar-mini-stat-bad' : 'ar-mini-stat-muted'"
              >{{ r.error_count }}</span>
            </div>
            <div class="ar-mini-stat">
              <span class="ar-mini-stat-label" title="Backlog replay duplicates skipped">Dedup</span>
              <span
                class="ar-mini-stat-value"
                :class="(r.dedup_count ?? 0) > 0 ? 'ar-mini-stat-cyan' : 'ar-mini-stat-muted'"
              >{{ r.dedup_count ?? 0 }}</span>
            </div>
            <div class="ar-mini-stat">
              <span class="ar-mini-stat-label">Last</span>
              <span class="ar-mini-stat-value ar-mini-stat-cyan">{{ formatMs(r.last_dispatch_ms) }}</span>
            </div>
          </div>

          <div class="ar-card-divider"></div>

          <div class="ar-card-row">
            <span class="ar-mono-label">Last event</span>
            <span class="ar-card-val">{{ lastEventRelative(r.last_event_at) }}</span>
          </div>
          <div v-if="r.last_event_id" class="ar-card-row">
            <span class="ar-mono-label">Event ID</span>
            <code class="ar-code-muted ar-code-trunc" :title="r.last_event_id">{{ r.last_event_id.slice(0, 8) }}…</code>
          </div>
          <!-- Hide last_error when the reactor is healthy (ws_connected) and
               there hasn't been a real error count increment — these are
               stale transient reconnect blips that the backend now self-
               clears on successful reconnect. -->
          <div v-if="r.last_error && (!r.ws_connected || r.error_count > 0)" class="ar-card-row ar-card-row-error">
            <span class="ar-mono-label">Last error</span>
            <span class="ar-card-val ar-card-val-error" :title="r.last_error">{{ r.last_error.slice(0, 60) }}{{ r.last_error.length > 60 ? '…' : '' }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Recent Dispatches feed (P5.2, 2026-05-08).
         Aggregates each reactor's most-recent event into a single time-ordered
         feed. Auto-refreshes via the existing /admin/reactor/status poll —
         shows up-to 30s lag. Pattern mirrors AdminCanaries log. -->
    <div v-if="allDispatches.length > 0" class="ar-log-section">
      <div class="ar-log-head">
        <div class="ar-log-head-left">
          <h3 id="ar-log-title" class="ar-log-title">Recent Dispatches</h3>
          <span class="ar-log-sub">{{ allDispatches.length }} reactor{{ allDispatches.length === 1 ? '' : 's' }} reporting</span>
        </div>
        <div class="ar-log-filter">
          <button
            class="ar-log-chip"
            :class="{ 'ar-log-chip--active': logFilter === 'all' }"
            @click="logFilter = 'all'"
          >All ({{ allDispatches.length }})</button>
          <button
            class="ar-log-chip"
            :class="{ 'ar-log-chip--active': logFilter === 'errored' }"
            :disabled="erroredDispatchCount === 0"
            @click="logFilter = 'errored'"
          >Errored ({{ erroredDispatchCount }})</button>
        </div>
      </div>
      <div class="ar-log-list" role="region" aria-labelledby="ar-log-title" tabindex="0">
        <div
          v-for="entry in recentDispatches"
          :key="`${entry.reactor}_${entry.event_id || entry.fired_at}`"
          class="ar-log-row"
          :class="{ 'ar-log-row--errored': !!entry.error }"
        >
          <span class="ar-log-time" :title="entry.fired_at">{{ entry.fired_at_relative }}</span>
          <span class="ar-log-reactor" :title="`Leader: ${entry.is_leader ? 'yes' : 'no'} · WS: ${entry.ws_connected ? 'connected' : 'down'}`">
            <span class="ar-log-dot" :class="entry.is_leader && entry.ws_connected ? 'ar-log-dot--ok' : 'ar-log-dot--idle'"></span>
            {{ entry.reactor }}
          </span>
          <code class="ar-log-event">{{ entry.event_type }}</code>
          <span class="ar-log-latency">{{ formatMs(entry.latency_ms) }}</span>
          <span v-if="entry.error" class="ar-log-error" :title="entry.error"><Icon name="mdi:alert" /> {{ entry.error.slice(0, 80) }}{{ entry.error.length > 80 ? '…' : '' }}</span>
          <code v-else-if="entry.event_id" class="ar-log-eid" :title="entry.event_id">{{ entry.event_id.slice(0, 8) }}…</code>
        </div>
      </div>
    </div>
    <div v-else class="ar-log-empty">
      <span class="ar-log-empty-icon">⏣</span>
      <span class="ar-log-empty-text">No dispatches yet — waiting for the first event to land.</span>
    </div>

    <!-- Footer -->
    <div class="ar-footer">
      Reactor framework · {{ data.reactors.length }} reactors live ·
      <code>/admin/reactor/status</code> · Snapshot {{ data.snapshot_at ? dayjs(data.snapshot_at).format('HH:mm:ss') : '' }}
    </div>
  </div>

  </div><!-- / activeTab === 'reactors' -->
</div>
</template>

<style scoped>
.ar {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  /* 2026-05-17: removed opaque `background: var(--bg-primary)` so the global
     DashboardLayout <ViewAmbient> (cyber grid + scan-beam + glows) shows
     through, matching AdminTreasury and the other admin views. The local
     `.ar-ambient` markup is auto-suppressed by neural-command.css §25 to
     avoid double-stacking. See memory: feedback_view_ambient_lives_in_layout. */
  color: var(--text-primary, #e8eaed);
  /* Theme-aware accent (audit 2026-05-07): --cyan/--cyan-rgb now alias the
   * global brand-theme tokens. Neural mode resolves to cyan #00d2d2;
   * sovereign mode resolves to red #DC2626 (see neural-command.css).
   * All references in this view continue to use var(--cyan) / rgba(var(--cyan-rgb),X)
   * so a single switch theme-cycles the whole page. Pattern matches
   * AdminCanaries Phase 11 polish (memory: feedback_admincanaries_theme_polish.md). */
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366;
  --green: #00ff88;
  --amber: #ff9500;
  --muted: #788593;  /* §FESUITE: 5.15:1 (#6b7785 was 4.25:1) */
  --border: rgba(var(--cyan-rgb), 0.18);
  --surface: #0a0d16;
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed;
}

/* ── Ambient ─────────────────────────── */
.ar-ambient {
  position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;
}
.ar-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}
.ar-scan {
  position: absolute; inset: 0;
  background: repeating-linear-gradient(
    180deg,
    transparent 0, transparent 3px,
    rgba(var(--cyan-rgb), 0.025) 3px, rgba(var(--cyan-rgb), 0.025) 4px
  );
}
.ar-glow {
  position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18;
}
.ar-glow-1 { width: 480px; height: 480px; background: rgba(var(--cyan-rgb), 0.6); top: -100px; right: -100px; }
.ar-glow-2 { width: 360px; height: 360px; background: rgba(255,51,102,0.4); bottom: -80px; left: -80px; }

/* ── Tab bar (Build #4) ─────────────── */
.ar-tabbar-wrap {
  position: relative;
  z-index: 1;
  padding: 0 32px 18px;
  max-width: 1280px;
  margin: 0 auto;
}
.ar-tabbar {
  display: inline-flex;
  gap: 4px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 4px;
}
.ar-tabbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: transparent;
  border: none;
  border-radius: 5px;
  padding: 8px 16px;
  cursor: pointer;
  font-family: var(--mono);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.15s;
}
.ar-tabbar-btn:hover {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(var(--cyan-rgb), 0.06);
}
.ar-tabbar-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: var(--cyan);
  box-shadow: inset 0 0 0 1px rgba(var(--cyan-rgb), 0.35);
}
.ar-tabbar-icon {
  font-size: 0.95rem;
  color: rgba(var(--cyan-rgb), 0.85);
}
.ar-tabbar-btn--active .ar-tabbar-icon { color: var(--cyan); }
.ar-tabbar-label { font-size: inherit; }
.ar-tabbar-count {
  background: rgba(var(--cyan-rgb), 0.2);
  color: rgba(var(--cyan-rgb), 1);
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 0.6rem;
  font-weight: 700;
}

/* ── Hero ───────────────────────────── */
.ar-hero {
  position: relative; z-index: 1; padding: 48px 32px 24px;
}
.ar-hero-inner { max-width: 1280px; margin: 0 auto; }
.ar-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px; border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 99px; margin-bottom: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
}
.ar-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
  animation: arPulse 1.6s ease-in-out infinite;
}
@keyframes arPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.ar-h1 {
  font-family: 'Orbitron', 'IBM Plex Sans', sans-serif;
  font-weight: 800; font-size: 36px; letter-spacing: 0.02em;
  margin: 0 0 10px; color: var(--text-bright); line-height: 1.15;
}
.ar-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.ar-lead { color: var(--muted); font-size: 14px; max-width: 720px; line-height: 1.7; margin: 0; }

/* ── Section ─────────────────────────── */
.ar-section {
  position: relative; z-index: 1;
  max-width: 1280px;
  margin: 24px auto 0;
  padding: 0 32px;
}
.ar-center {
  position: relative; z-index: 1;
  text-align: center; padding: 80px 32px;
}
.ar-error-text { color: #f87171; font-family: var(--mono); font-size: 12px; }

/* ── Stats row ───────────────────────── */
.ar-stats-row {
  display: flex; gap: 12px; margin-bottom: 18px; flex-wrap: wrap;
}
.ar-stat {
  flex: 1; min-width: 140px;
  display: flex; flex-direction: column; gap: 4px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(10,13,22,0.85), rgba(6,8,16,0.85));
  border: 1px solid var(--border); border-top-color: rgba(var(--cyan-rgb), 0.32);
  border-radius: 5px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3), inset 0 1px 0 rgba(var(--cyan-rgb), 0.05);
}
.ar-stat-label {
  font-family: var(--mono); font-size: 9px; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted);
}
.ar-stat-value {
  font-family: 'Orbitron', monospace; font-weight: 700; font-size: 26px;
  letter-spacing: 0.02em; color: var(--text-bright);
}
.ar-stat-sub { font-family: var(--mono); font-size: 10px; color: var(--muted); }
.ar-stat-cyan .ar-stat-value { color: var(--cyan); }
.ar-stat-ok .ar-stat-value { color: var(--green); }
.ar-stat-bad .ar-stat-value { color: var(--red); }
.ar-stat-warn .ar-stat-value { color: var(--amber); }
.ar-stat-muted .ar-stat-value { color: var(--muted); }

/* ── Toolbar ─────────────────────────── */
.ar-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 10px 14px; margin-bottom: 12px;
  background: rgba(10,13,22,0.6);
  border: 1px solid var(--border); border-radius: 4px;
}
.ar-toolbar-info { display: flex; align-items: center; gap: 6px; }
.ar-toolbar-actions { display: flex; gap: 8px; }
.ar-mono-label { font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
.ar-mono-value { font-family: var(--mono); font-size: 11px; color: var(--text-bright); }

.ar-note {
  display: flex; align-items: flex-start; gap: 10px;
  margin: 0 0 14px; padding: 12px 16px;
  font-family: var(--mono); font-size: 11px; color: var(--muted); line-height: 1.65;
  background: rgba(var(--cyan-rgb), 0.03);
  border-left: 2px solid rgba(var(--cyan-rgb), 0.3);
  border-radius: 4px;
}
.ar-note code { color: var(--cyan); font-size: 10px; background: rgba(var(--cyan-rgb), 0.08); padding: 1px 5px; border-radius: 3px; }
.ar-note-icon { color: var(--cyan); font-size: 14px; flex-shrink: 0; margin-top: 1px; }
.ar-note-body { display: flex; flex-direction: column; gap: 4px; }
.ar-note-title {
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--cyan);
}
.ar-note-text { color: var(--text-secondary, #94a3b8); font-size: 11px; }
.ar-note-text strong { color: var(--text-bright); }
.ar-note-text em { font-style: normal; color: var(--cyan); }

/* ── Cards ───────────────────────────── */
.ar-cards {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
}
.ar-card {
  position: relative;
  display: flex; flex-direction: column;
  padding: 16px 18px;
  background: linear-gradient(180deg, rgba(10,13,22,0.92), rgba(6,8,16,0.88));
  border: 1px solid var(--border); border-top-color: rgba(var(--cyan-rgb), 0.18);
  border-radius: 5px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.32), 0 0 32px rgba(var(--cyan-rgb), 0.04);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.ar-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--cyan-rgb), 0.5), transparent);
  opacity: 0.6;
}
.ar-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(0,0,0,0.4), 0 0 48px rgba(var(--cyan-rgb), 0.08);
  border-top-color: rgba(var(--cyan-rgb), 0.45);
}
.ar-card-active { border-top-color: rgba(0,255,136,0.4); }
.ar-card-active::before { background: linear-gradient(90deg, transparent, rgba(0,255,136,0.6), transparent); }
.ar-card-degraded { border-top-color: rgba(255,149,0,0.4); }
.ar-card-degraded::before { background: linear-gradient(90deg, transparent, rgba(255,149,0,0.6), transparent); }
.ar-card-stopped { opacity: 0.55; border-top-color: rgba(255,51,102,0.35); }
.ar-card-warn { border-top-color: rgba(255,51,102,0.35); }

.ar-card-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 12px; margin-bottom: 12px;
}
.ar-card-title-row { display: flex; align-items: center; gap: 9px; min-width: 0; }
.ar-card-title {
  font-family: 'Orbitron', sans-serif; font-weight: 700; font-size: 14px;
  letter-spacing: 0.04em; margin: 0; color: var(--text-bright);
  /* a reactor's name is one long word ("AdminBroadcastEditedReceived"): it breaks inside its row rather than run under
     the status on a phone (the camera, 2026-10-13) */
  min-width: 0; overflow-wrap: anywhere;
}
.ar-card-status {
  font-family: var(--mono); font-size: 9px; font-weight: 600;
  letter-spacing: 0.12em; color: var(--muted);
}
.ar-card-active .ar-card-status { color: var(--green); }
.ar-card-degraded .ar-card-status { color: var(--amber); }
.ar-card-stopped .ar-card-status { color: var(--red); }

.ar-card-body { display: flex; flex-direction: column; gap: 6px; }
.ar-card-row {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; font-size: 12px;
}
.ar-card-row-error { color: #f87171; }
.ar-card-val { color: var(--text-bright); font-family: var(--mono); font-size: 11px; }
.ar-card-val-error { color: #f87171; }
.ar-card-divider {
  height: 1px; margin: 8px 0;
  background: linear-gradient(90deg, transparent, rgba(var(--cyan-rgb), 0.18), transparent);
}

.ar-stat-grid {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px;
}
.ar-mini-stat {
  display: flex; flex-direction: column; gap: 2px;
  padding: 6px 8px;
  background: rgba(var(--cyan-rgb), 0.04); border: 1px solid rgba(var(--cyan-rgb), 0.08);
  border-radius: 3px;
}
.ar-mini-stat-label { font-family: var(--mono); font-size: 8px; font-weight: 600; letter-spacing: 0.1em; color: var(--muted); text-transform: uppercase; }
.ar-mini-stat-value { font-family: 'Orbitron', monospace; font-weight: 700; font-size: 16px; color: var(--text-bright); }
.ar-mini-stat-ok { color: var(--green); }
.ar-mini-stat-bad { color: var(--red); }
.ar-mini-stat-cyan { color: var(--cyan); }
.ar-mini-stat-muted { color: var(--muted); }

/* ── Code ─────────────────────────────── */
.ar-code {
  font-family: var(--mono); font-size: 11px; color: var(--cyan);
  background: rgba(var(--cyan-rgb), 0.08);
  padding: 1px 6px; border-radius: 3px;
  overflow-wrap: anywhere;   /* a long event or worker name breaks inside a phone-wide card (the camera, 2026-10-13) */
}
.ar-code-muted {
  font-family: var(--mono); font-size: 10px; color: var(--muted);
  background: rgba(255,255,255,0.04);
  padding: 1px 6px; border-radius: 3px;
  overflow-wrap: anywhere;
}
.ar-code-trunc { max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }

/* ── Dots ──────────────────────────────── */
.ar-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ar-dot-ok { background: var(--green); box-shadow: 0 0 8px rgba(0,255,136,0.6); }
.ar-dot-bad { background: var(--red); box-shadow: 0 0 8px rgba(255,51,102,0.6); }
.ar-dot-warn { background: var(--amber); box-shadow: 0 0 8px rgba(255,149,0,0.6); }
.ar-dot-muted { background: #6b7785; }

/* ── Buttons ───────────────────────────── */
.ar-btn {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  padding: 6px 14px; border-radius: 4px; border: 1px solid transparent; cursor: pointer;
  transition: all 0.15s;
}
.ar-btn-ghost {
  background: transparent; color: var(--cyan);
  border-color: rgba(var(--cyan-rgb), 0.2);
}
.ar-btn-ghost:hover { background: rgba(var(--cyan-rgb), 0.08); border-color: rgba(var(--cyan-rgb), 0.4); }
.ar-btn-primary {
  background: rgba(var(--cyan-rgb), 0.15); color: var(--cyan);
  border-color: rgba(var(--cyan-rgb), 0.3);
}
.ar-btn-primary:hover { background: rgba(var(--cyan-rgb), 0.25); }

/* ── Spinner ───────────────────────────── */
.ar-spinner {
  width: 32px; height: 32px;
  border: 2px solid rgba(var(--cyan-rgb), 0.15);
  border-top-color: var(--cyan);
  border-radius: 50%;
  margin: 0 auto;
  animation: arSpin 0.8s linear infinite;
}
@keyframes arSpin { to { transform: rotate(360deg); } }
.ar-loading-text { color: var(--muted); margin-top: 12px; font-size: 12px; font-family: var(--mono); }

/* ── Recent Dispatches feed (P5.2, 2026-05-08) ─── */
.ar-log-section {
  margin-top: 32px;
  padding: 20px;
  background: linear-gradient(180deg, rgba(var(--cyan-rgb), 0.04), rgba(0, 0, 0, 0.35));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 12px;
}
.ar-log-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.ar-log-head-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex: 1;
}
.ar-log-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--cyan);
  margin: 0;
}
.ar-log-sub {
  font-size: 10px;
  color: var(--muted);
  font-family: var(--mono);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.ar-log-filter {
  display: flex;
  gap: 6px;
}
.ar-log-chip {
  padding: 5px 12px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 100px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.65);
  cursor: pointer;
  transition: all 150ms ease;
  font-family: inherit;
}
.ar-log-chip:hover:not(:disabled) {
  border-color: rgba(var(--cyan-rgb), 0.4);
  color: rgba(255, 255, 255, 0.95);
}
.ar-log-chip--active {
  background: rgba(var(--cyan-rgb), 0.18);
  border-color: var(--cyan);
  color: var(--cyan);
}
.ar-log-chip:disabled { opacity: 0.4; cursor: not-allowed; }

.ar-log-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 480px;
  overflow-y: auto;
}
.ar-log-list:focus-visible { outline: 1px solid rgba(var(--nc-primary-rgb), 0.55); outline-offset: 2px; }
.ar-log-list::-webkit-scrollbar { width: 6px; }
.ar-log-list::-webkit-scrollbar-thumb {
  background: rgba(var(--cyan-rgb), 0.3);
  border-radius: 3px;
}

.ar-log-row {
  display: grid;
  grid-template-columns: 100px 220px 220px 80px 1fr;
  gap: 12px;
  align-items: center;
  padding: 6px 10px;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  font-size: 11px;
  font-family: var(--mono);
  transition: background 150ms ease;
}
.ar-log-row:hover {
  background: rgba(var(--cyan-rgb), 0.06);
  border-color: rgba(var(--cyan-rgb), 0.2);
}
.ar-log-row--errored {
  background: rgba(255, 51, 102, 0.06);
  border-color: rgba(255, 51, 102, 0.25);
}
.ar-log-time {
  color: var(--muted);
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ar-log-reactor {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: rgba(255, 255, 255, 0.95);
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ar-log-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ar-log-dot--ok    { background: var(--nc-success, #00ff88); box-shadow: 0 0 6px rgba(0, 255, 136, 0.5); }
.ar-log-dot--idle  { background: rgba(255, 255, 255, 0.3); }
.ar-log-event {
  color: var(--cyan);
  background: rgba(var(--cyan-rgb), 0.08);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 10px;
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ar-log-latency {
  color: rgba(255, 255, 255, 0.65);
  text-align: right;
  font-size: 10px;
  letter-spacing: 0.04em;
}
.ar-log-error {
  color: #ff6b81;
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ar-log-eid {
  color: rgba(255, 255, 255, 0.4);
  font-size: 10px;
  letter-spacing: 0.04em;
}

.ar-log-empty {
  margin-top: 24px;
  padding: 32px;
  text-align: center;
  background: rgba(0, 0, 0, 0.25);
  border: 1px dashed rgba(var(--cyan-rgb), 0.2);
  border-radius: 12px;
}
.ar-log-empty-icon {
  display: block;
  font-size: 32px;
  color: rgba(var(--cyan-rgb), 0.4);
  margin-bottom: 8px;
}
.ar-log-empty-text {
  font-size: 12px;
  color: var(--muted);
  letter-spacing: 0.04em;
}

/* ── Footer ────────────────────────────── */
.ar-footer {
  text-align: center; padding: 28px 0 0;
  font-family: var(--mono); font-size: 10px; color: var(--muted);
  letter-spacing: 0.06em;
}
.ar-footer code { color: var(--cyan); background: rgba(var(--cyan-rgb), 0.08); padding: 1px 4px; border-radius: 2px; }

@media (max-width: 720px) {
  .ar-h1 { font-size: 26px; }
  .ar-stats-row { flex-direction: column; }
  .ar-toolbar { flex-direction: column; align-items: flex-start; gap: 8px; }
  /* minmax(0, 1fr): a 1fr column grew to the widest card's content (a long event or worker name) and the cards ran
     ~22 px past a phone's edge (the camera, 2026-10-13) */
  .ar-cards { grid-template-columns: minmax(0, 1fr); }
  .ar-log-row { grid-template-columns: 80px 1fr; gap: 6px; font-size: 10px; }
  .ar-log-row > .ar-log-event,
  .ar-log-row > .ar-log-latency,
  .ar-log-row > .ar-log-eid { display: none; }
}
</style>
