<template>
  <Teleport to="body">
    <div
      class="acps-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="acps-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="acps-modal" :class="{ 'acps-modal--errors': hasErrors }">
        <!-- Header -->
        <div class="acps-header">
          <div class="acps-header-left">
            <span class="acps-status-dot" :class="statusDotClass"></span>
            <h2 id="acps-modal-title" class="acps-title">Agent-Card Pull-Sync</h2>
            <span class="acps-subtitle">agent_card_pullsync</span>
          </div>
          <div class="acps-header-right">
            <button class="acps-btn acps-btn--ghost" @click="refreshAll" :disabled="loadingStatus">
              ↻ Refresh
            </button>
            <button class="acps-btn acps-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Banner -->
        <div
          v-if="status?.banner"
          class="acps-banner"
          :class="status.banner.level === 'warn' ? 'acps-banner--warn' : 'acps-banner--info'"
          role="status"
        >
          <span class="acps-banner-glyph">{{ status.banner.level === 'warn' ? '⚠' : 'ℹ' }}</span>
          <span class="acps-banner-text">{{ status.banner.msg }}</span>
        </div>

        <!-- Top stats -->
        <div class="acps-stats-row">
          <div class="acps-stat">
            <span class="acps-stat-label">Cycles 24h</span>
            <span class="acps-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="acps-stat-sub">every {{ formatInterval(status?.worker_snapshot?.interval_sec) }}</span>
          </div>
          <div class="acps-stat">
            <span class="acps-stat-label">Pulls (200) 24h</span>
            <span class="acps-stat-value">{{ status?.summary.pulls_200_24h ?? '—' }}</span>
            <span class="acps-stat-sub">{{ status?.summary.pulls_304_24h ?? '—' }} × 304</span>
          </div>
          <div class="acps-stat" :class="{ 'acps-stat--warn': (status?.summary.drift_events_24h ?? 0) > 0 }">
            <span class="acps-stat-label">Drift 24h</span>
            <span class="acps-stat-value">{{ status?.summary.drift_events_24h ?? '—' }}</span>
            <span class="acps-stat-sub">{{ status ? Object.keys(status.drift_24h_by_field || {}).length : '—' }} field(s)</span>
          </div>
          <div class="acps-stat" :class="{ 'acps-stat--bad': hasErrors }">
            <span class="acps-stat-label">Errors 24h</span>
            <span class="acps-stat-value">{{ status ? totalErrors24h : '—' }}</span>
            <span class="acps-stat-sub">{{ !status ? '—' : hasErrors ? 'investigate' : 'clean' }}</span>
          </div>
        </div>

        <!-- DB buckets — native pull state -->
        <section class="acps-section">
          <h3 class="acps-section-title">
            Native cards
            <span class="acps-section-sub">
              total {{ status?.db_buckets.total_native_active ?? '—' }} ·
              stale threshold = 2× interval
            </span>
          </h3>
          <div v-if="loadingStatus && !status" class="acps-empty">
            <div class="acps-spinner"></div>
            <p>Loading pull-sync state…</p>
          </div>
          <div v-else-if="statusError" class="acps-banner acps-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="acps-btn acps-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status" class="acps-bucket-grid">
            <div class="acps-bucket-card acps-bucket-card--never">
              <div class="acps-bucket-num">{{ status.db_buckets.never_pulled }}</div>
              <div class="acps-bucket-label">never pulled</div>
            </div>
            <div class="acps-bucket-card acps-bucket-card--stale">
              <div class="acps-bucket-num">{{ status.db_buckets.stale }}</div>
              <div class="acps-bucket-label">stale (≥2× interval)</div>
            </div>
            <div class="acps-bucket-card acps-bucket-card--fresh">
              <div class="acps-bucket-num">{{ status.db_buckets.fresh }}</div>
              <div class="acps-bucket-label">fresh</div>
            </div>
          </div>
        </section>

        <!-- Tabs -->
        <nav class="acps-tabs" role="tablist">
          <button
            v-for="t in tabs"
            :key="t.id"
            class="acps-tab"
            :class="{ 'acps-tab--active': tab === t.id }"
            role="tab"
            :aria-selected="tab === t.id"
            @click="tab = t.id"
          >
            {{ t.label }}
          </button>
        </nav>

        <!-- Tab: Last cycle per-agent -->
        <section v-if="tab === 'last_cycle'" class="acps-section">
          <h3 class="acps-section-title">
            Last cycle outcomes
            <span v-if="status" class="acps-section-sub">
              candidates: {{ lastStats.candidates ?? 0 }} ·
              200: {{ lastStats.fetched_200 ?? 0 }} ·
              304: {{ lastStats.fetched_304 ?? 0 }} ·
              4xx: {{ lastStats.fetched_4xx ?? 0 }} ·
              5xx: {{ lastStats.fetched_5xx ?? 0 }} ·
              timeout: {{ lastStats.fetched_timeout ?? 0 }} ·
              skipped: {{ lastStats.skipped_internal ?? 0 }} ·
              errors: {{ lastStats.errors ?? 0 }}
            </span>
          </h3>
          <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
          <div v-else-if="!status" class="acps-empty"><div class="acps-spinner"></div><p>Loading pull-sync state…</p></div>
          <div v-else-if="!lastPullRows.length" class="acps-empty acps-empty--muted">
            <p>No agents have been pulled yet — cold start (≤30s after boot) or worker not leader on this pod.</p>
          </div>
          <div v-else class="acps-table-wrap">
            <table class="acps-table">
              <thead>
                <tr>
                  <th>DID</th>
                  <th>URL</th>
                  <th>Status</th>
                  <th>ETag</th>
                  <th>Drift fields</th>
                  <th>At</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in lastPullRows" :key="row.did">
                  <td class="acps-mono acps-cell-did">{{ shorten(row.did) }}</td>
                  <td class="acps-mono acps-cell-url" :title="row.url">{{ shorten(row.url, 50) }}</td>
                  <td>
                    <span class="acps-pill" :class="statusPillClass(row.status)">{{ row.status }}</span>
                  </td>
                  <td class="acps-mono">{{ shorten(row.etag, 14) || '—' }}</td>
                  <td>
                    <span v-if="row.drift_fields?.length" class="acps-mono acps-text-warn">
                      {{ row.drift_fields.join(', ') }}
                    </span>
                    <span v-else class="acps-text-muted">—</span>
                  </td>
                  <td class="acps-mono acps-text-muted">{{ formatRel(row.ts) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Tab: 24h field-rollup -->
        <section v-else-if="tab === 'drift_fields'" class="acps-section">
          <h3 class="acps-section-title">
            Drift fields (24h Prom rollup)
            <span class="acps-section-sub">how often each agent-owned field changed</span>
          </h3>
          <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
          <div v-else-if="!status" class="acps-empty"><div class="acps-spinner"></div><p>Loading pull-sync state…</p></div>
          <div v-else-if="driftFieldRows.length === 0" class="acps-empty acps-empty--muted">
            <p>No drift detected in the last 24h.</p>
          </div>
          <div v-else class="acps-table-wrap">
            <table class="acps-table">
              <thead>
                <tr><th>Field</th><th class="acps-right">Drift count</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in driftFieldRows" :key="row.field">
                  <td class="acps-mono">{{ row.field }}</td>
                  <td class="acps-right">{{ row.count }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Tab: How it works -->
        <section v-else-if="tab === 'about'" class="acps-section">
          <h3 class="acps-section-title">How agent_card_pullsync works</h3>
          <div class="acps-prose">
            <p>
              Per A2A v1.0 §4.1.2, each agent should publish its own AgentCard
              at <code>/.well-known/agent-card.json</code>. This worker is the
              registry-side consumer: every 6 hours, it fetches each native
              agent's well-known card and reconciles it with the stored
              <code>card_data</code>.
            </p>
            <h4>Ownership split (Option C §3.1)</h4>
            <ul>
              <li><strong>Agent owns</strong>: name, description, supportedInterfaces, securitySchemes, extensions, capabilities, skills, tags, provider, pricing, iconUrl.</li>
              <li><strong>Registry owns</strong>: federation_metadata, flare, last_pulled_at, last_pulled_etag — these are preserved across every pull.</li>
            </ul>
            <h4>Cadence + scope</h4>
            <ul>
              <li>Every <code>{{ formatInterval(status?.worker_snapshot?.interval_sec) }}</code> (env <code>AGENT_CARD_PULLSYNC_INTERVAL_SEC</code>, default 21600).</li>
              <li>Native cards only — synced-from-peer cards are owned by their origin registry.</li>
              <li>URLs pointing to localhost / single-host names / IP literals are skipped (internal-only agents).</li>
              <li>Master kill: <code>AGENT_CARD_PULLSYNC_ENABLED=false</code>.</li>
            </ul>
            <h4>Drift handling</h4>
            <p>
              When the worker finds an agent-canonical field has changed, it
              merges the new value into <code>card_data</code> (preserving
              registry-owned fields) and emits an <code>AgentCardPulled</code>
              event with <code>{drift: true, fields: [...]}</code> for audit.
              No drift = no event (avoids audit-trail spam).
            </p>
          </div>
        </section>

        <!-- Footer -->
        <div class="acps-footer">
          <span v-if="status?.worker_snapshot?.last_cycle_iso" class="acps-footer-meta">
            last cycle {{ formatRel(status.worker_snapshot.last_cycle_iso) }} · {{ status.worker_snapshot.last_duration_ms }}ms
            · leader={{ status.worker_snapshot.is_leader_now ? 'yes' : 'no' }}
            · enabled={{ status.worker_snapshot.enabled ? 'yes' : 'no' }}
          </span>
          <span class="acps-footer-spacer"></span>
          <span class="acps-footer-meta acps-text-muted">auto-refresh every 10s</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<!-- §POCKETBRIDGE P0 — this was the ONE plain-JS SFC in the tree, and the
     single error standing between `vue-tsc` and a green gate (TS6504: a
     JS virtual module under allowJs:false). Converted with minimal, honest
     annotations; behavior unchanged. -->
<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { getPullsyncStatus } from '@/services/api/agentCardPullsync'

const emit = defineEmits(['close'])

const status = ref<any>(null)
const loadingStatus = ref(false)
const statusError = ref<string | null>(null)
const autoRefreshHandle = ref<ReturnType<typeof setInterval> | null>(null)
const tab = ref('last_cycle')

const tabs = [
  { id: 'last_cycle', label: 'Last cycle' },
  { id: 'drift_fields', label: 'Drift fields (24h)' },
  { id: 'about', label: 'How it works' },
]

const lastStats = computed(() => status.value?.worker_snapshot?.last_stats || {})
const lastPullRows = computed<any[]>(() => {
  const m = lastStats.value?.last_pull_per_agent || {}
  const rows: any[] = Object.entries(m as Record<string, any>).map(([did, v]) => ({ did, ...(v as Record<string, any>) }))
  rows.sort((a, b) => String(b.ts || '').localeCompare(String(a.ts || '')))
  return rows
})
const driftFieldRows = computed(() => {
  const m = status.value?.drift_24h_by_field || {}
  return Object.entries(m as Record<string, number>)
    .map(([field, count]) => ({ field, count: Number(count) }))
    .sort((a, b) => b.count - a.count)
})

const totalErrors24h = computed(() => {
  const s = status.value?.summary
  if (!s) return 0
  return (s.pulls_5xx_24h || 0) + (s.pulls_timeout_24h || 0)
})
const hasErrors = computed(() => totalErrors24h.value > 0)

const statusDotClass = computed(() => {
  if (statusError.value && !status.value) return 'acps-dot--bad'
  if (hasErrors.value) return 'acps-dot--bad'
  if ((status.value?.summary.drift_events_24h ?? 0) > 0) return 'acps-dot--warn'
  if ((status.value?.summary.cycles_24h ?? 0) > 0) return 'acps-dot--ok'
  return 'acps-dot--neutral'
})

async function loadStatus() {
  loadingStatus.value = true
  statusError.value = null
  try {
    status.value = await getPullsyncStatus()
  } catch (e: any) {
    statusError.value = e?.response?.data?.detail || e?.message || 'unknown error'
  } finally {
    loadingStatus.value = false
  }
}

async function refreshAll() { await loadStatus() }

function formatInterval(sec?: number | null) {
  if (!sec) return '—'
  if (sec >= 3600) return `${Math.round(sec / 3600)}h`
  if (sec >= 60) return `${Math.round(sec / 60)}m`
  return `${sec}s`
}

function formatRel(iso?: string | null) {
  if (!iso) return '—'
  try {
    const t = new Date(iso).getTime()
    const delta = Date.now() - t
    if (delta < 0) return 'just now'
    const s = Math.floor(delta / 1000)
    if (s < 60) return `${s}s ago`
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    return `${Math.floor(s / 86400)}d ago`
  } catch { return iso }
}

function shorten(s?: any, max = 26) {
  if (!s) return ''
  s = String(s)
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

function statusPillClass(status?: number | string | null) {
  if (status === 200) return 'acps-pill--ok'
  if (status === 304) return 'acps-pill--info'
  if (status === 'timeout') return 'acps-pill--bad'
  if (typeof status === 'number' && status >= 500) return 'acps-pill--bad'
  if (typeof status === 'number' && status >= 400) return 'acps-pill--warn'
  return 'acps-pill--neutral'
}

onMounted(() => {
  loadStatus()
  autoRefreshHandle.value = setInterval(loadStatus, 10000)
})
onBeforeUnmount(() => {
  if (autoRefreshHandle.value) clearInterval(autoRefreshHandle.value)
})

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.acps-overlay {
  position: fixed; inset: 0; z-index: 10000;
  background: rgba(2, 6, 23, 0.85);
  display: flex; align-items: center; justify-content: center;
  padding: 1rem;
  backdrop-filter: blur(4px);
}
.acps-modal {
  background: var(--surface, #0b1220);
  border: 1px solid var(--border, rgba(56, 189, 248, 0.2));
  border-radius: 12px;
  width: min(1100px, 95vw);
  max-height: 92vh;
  display: flex; flex-direction: column;
  overflow: hidden;
  box-shadow: 0 30px 80px rgba(8, 145, 178, 0.25);
}
.acps-modal--errors { border-color: rgba(248, 113, 113, 0.45); }

.acps-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.85rem 1.1rem;
  border-bottom: 1px solid var(--border, rgba(56, 189, 248, 0.15));
}
.acps-header-left { display: flex; align-items: center; gap: 0.55rem; }
.acps-header-right { display: flex; align-items: center; gap: 0.5rem; }

.acps-title { font-size: 1.15rem; font-weight: 600; color: var(--text, #e0f2fe); margin: 0; }
.acps-subtitle { font-size: 0.75rem; color: var(--muted, #94a3b8); font-family: ui-monospace, monospace; }

.acps-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
}
.acps-dot--ok { background: #22c55e; box-shadow: 0 0 8px rgba(34, 197, 94, 0.6); }
.acps-dot--info { background: #38bdf8; }
.acps-dot--warn { background: #facc15; box-shadow: 0 0 8px rgba(250, 204, 21, 0.6); }
.acps-dot--bad { background: #ef4444; box-shadow: 0 0 8px rgba(239, 68, 68, 0.6); }
.acps-dot--neutral { background: #64748b; }

.acps-banner {
  margin: 0.6rem 1.1rem;
  padding: 0.55rem 0.85rem;
  border-radius: 6px;
  display: flex; align-items: center; gap: 0.6rem;
  font-size: 0.85rem;
}
.acps-banner--warn { background: rgba(250, 204, 21, 0.1); border: 1px solid rgba(250, 204, 21, 0.35); color: #facc15; }
.acps-banner--info { background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.3); color: #7dd3fc; }
.acps-banner--bad { background: rgba(248, 113, 113, 0.1); border: 1px solid rgba(248, 113, 113, 0.4); color: #fca5a5; }
.acps-banner-glyph { font-size: 1.1rem; }

.acps-stats-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem;
  padding: 0.85rem 1.1rem;
  border-bottom: 1px solid var(--border, rgba(56, 189, 248, 0.1));
}
.acps-stat {
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid var(--border, rgba(56, 189, 248, 0.15));
  border-radius: 8px;
  padding: 0.55rem 0.7rem;
  display: flex; flex-direction: column; gap: 0.15rem;
}
.acps-stat--warn { border-color: rgba(250, 204, 21, 0.4); }
.acps-stat--bad { border-color: rgba(248, 113, 113, 0.4); }
.acps-stat-label { font-size: 0.7rem; color: var(--muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.05em; }
.acps-stat-value { font-size: 1.4rem; font-weight: 600; color: var(--text, #e0f2fe); font-family: ui-monospace, monospace; }
.acps-stat-sub { font-size: 0.72rem; color: var(--muted, #94a3b8); }

.acps-section {
  padding: 0.75rem 1.1rem;
  overflow-y: auto;
}
.acps-section-title {
  font-size: 0.95rem; font-weight: 500; color: var(--text, #e0f2fe);
  margin: 0 0 0.55rem 0;
  display: flex; align-items: baseline; gap: 0.55rem;
}
.acps-section-sub { font-size: 0.75rem; color: var(--muted, #94a3b8); font-weight: 400; }

.acps-bucket-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem;
}
.acps-bucket-card {
  border-radius: 8px;
  padding: 0.85rem 0.85rem;
  display: flex; flex-direction: column; gap: 0.15rem;
  align-items: center;
  border: 1px solid;
  background: rgba(15, 23, 42, 0.5);
}
.acps-bucket-card--never { border-color: rgba(148, 163, 184, 0.35); }
.acps-bucket-card--stale { border-color: rgba(250, 204, 21, 0.4); }
.acps-bucket-card--fresh { border-color: rgba(34, 197, 94, 0.4); }
.acps-bucket-num { font-size: 2.1rem; font-weight: 600; font-family: ui-monospace, monospace; color: var(--text, #e0f2fe); }
.acps-bucket-label { font-size: 0.78rem; color: var(--muted, #94a3b8); }

.acps-tabs {
  display: flex; gap: 0.25rem;
  border-top: 1px solid var(--border, rgba(56, 189, 248, 0.1));
  border-bottom: 1px solid var(--border, rgba(56, 189, 248, 0.1));
  padding: 0.35rem 1.1rem;
}
.acps-tab {
  padding: 0.4rem 0.85rem;
  font-size: 0.8rem;
  background: transparent;
  border: 1px solid transparent;
  color: var(--muted, #94a3b8);
  border-radius: 6px;
  cursor: pointer;
}
.acps-tab--active { background: rgba(56, 189, 248, 0.1); border-color: rgba(56, 189, 248, 0.3); color: var(--text, #e0f2fe); }
.acps-tab:hover:not(.acps-tab--active) { background: rgba(56, 189, 248, 0.04); color: var(--text, #e0f2fe); }

.acps-table-wrap { overflow-x: auto; }
.acps-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.acps-table th { text-align: left; padding: 0.45rem 0.6rem; color: var(--muted, #94a3b8); font-weight: 500; border-bottom: 1px solid var(--border, rgba(56, 189, 248, 0.1)); }
.acps-table td { padding: 0.4rem 0.6rem; border-bottom: 1px solid rgba(56, 189, 248, 0.05); color: var(--text, #e0f2fe); }
.acps-mono { font-family: ui-monospace, monospace; }
.acps-cell-did, .acps-cell-url { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acps-right { text-align: right; }

.acps-pill {
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 10px;
  font-size: 0.72rem;
  font-family: ui-monospace, monospace;
}
.acps-pill--ok { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
.acps-pill--info { background: rgba(56, 189, 248, 0.15); color: #7dd3fc; border: 1px solid rgba(56, 189, 248, 0.3); }
.acps-pill--warn { background: rgba(250, 204, 21, 0.15); color: #facc15; border: 1px solid rgba(250, 204, 21, 0.3); }
.acps-pill--bad { background: rgba(248, 113, 113, 0.15); color: #fca5a5; border: 1px solid rgba(248, 113, 113, 0.3); }
.acps-pill--neutral { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3); }

.acps-empty { padding: 1.5rem; text-align: center; color: var(--muted, #94a3b8); }
.acps-empty--muted p { margin: 0; font-size: 0.85rem; }
.acps-spinner {
  width: 28px; height: 28px;
  border: 3px solid rgba(56, 189, 248, 0.2);
  border-top-color: #38bdf8;
  border-radius: 50%;
  animation: acps-spin 0.8s linear infinite;
  margin: 0 auto 0.6rem;
}
@keyframes acps-spin { to { transform: rotate(360deg); } }

.acps-prose { color: var(--text, #e0f2fe); font-size: 0.88rem; line-height: 1.5; }
.acps-prose h4 { font-size: 0.9rem; margin: 0.9rem 0 0.3rem 0; color: var(--text, #e0f2fe); }
.acps-prose ul { margin: 0.3rem 0; padding-left: 1.3rem; }
.acps-prose code { background: rgba(56, 189, 248, 0.1); padding: 0.05rem 0.35rem; border-radius: 4px; font-size: 0.85em; }

.acps-text-warn { color: #facc15; }
.acps-text-muted { color: var(--muted, #94a3b8); }

.acps-footer {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.55rem 1.1rem;
  border-top: 1px solid var(--border, rgba(56, 189, 248, 0.1));
  font-size: 0.75rem;
  background: rgba(15, 23, 42, 0.3);
}
.acps-footer-meta { color: var(--muted, #94a3b8); font-family: ui-monospace, monospace; }
.acps-footer-spacer { flex: 1; }

.acps-btn {
  padding: 0.3rem 0.7rem; font-size: 0.78rem;
  border-radius: 6px; border: 1px solid transparent;
  cursor: pointer;
}
.acps-btn--ghost { background: transparent; border-color: rgba(56, 189, 248, 0.3); color: var(--text, #e0f2fe); }
.acps-btn--ghost:hover:not(:disabled) { background: rgba(56, 189, 248, 0.08); }
.acps-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
