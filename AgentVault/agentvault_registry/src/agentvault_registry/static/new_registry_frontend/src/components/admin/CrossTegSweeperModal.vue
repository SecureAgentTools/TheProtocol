<template>
  <Teleport to="body">
    <div
      class="cts-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cts-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="cts-modal" :class="{ 'cts-modal--errors': hasErrors }">
        <!-- Header -->
        <div class="cts-header">
          <div class="cts-header-left">
            <span class="cts-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="cts-modal-title" class="cts-title">2PC Coordination Sweeper</h2>
            <span class="cts-subtitle">{{ workerId }}</span>
          </div>
          <div class="cts-header-right">
            <span v-if="status?.snapshot_iso" class="cts-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="cts-btn cts-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingEvents">
              <span class="cts-live-dot" :class="{ 'cts-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="cts-btn cts-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="cts-stats-row">
          <div class="cts-stat">
            <span class="cts-stat-label">Cycles 24h</span>
            <span class="cts-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="cts-stat-sub">{{ status?.summary.teg_count ?? '—' }} TEGs reporting</span>
          </div>
          <div class="cts-stat" :class="{ 'cts-stat--warn': (status?.summary.aborted_24h ?? 0) > 0 }">
            <span class="cts-stat-label">Aborted 24h</span>
            <span class="cts-stat-value">{{ status?.summary.aborted_24h ?? '—' }}</span>
            <span class="cts-stat-sub">expired INITIATED rows</span>
          </div>
          <div class="cts-stat" :class="{ 'cts-stat--warn': (status?.summary.resumed_24h ?? 0) > 0 }">
            <span class="cts-stat-label">Resumed 24h</span>
            <span class="cts-stat-value">{{ status?.summary.resumed_24h ?? '—' }}</span>
            <span class="cts-stat-sub">commit-phase review</span>
          </div>
          <div class="cts-stat" :class="{ 'cts-stat--bad': (status?.summary.errors_24h ?? 0) > 0 }">
            <span class="cts-stat-label">Errors 24h</span>
            <span class="cts-stat-value">{{ status?.summary.errors_24h ?? '—' }}</span>
            <span class="cts-stat-sub">{{ !status ? '—' : status.summary.errors_24h ? 'investigate' : 'all healthy' }}</span>
          </div>
        </div>

        <!-- Fleet grid -->
        <section class="cts-section">
          <h3 class="cts-section-title">
            Fleet
            <span class="cts-section-sub">{{ status?.per_op.length ?? '—' }} TEGs · pending {{ status?.summary.pending_total ?? '—' }}</span>
          </h3>
          <div v-if="loadingStatus && !status" class="cts-empty">
            <div class="cts-spinner"></div>
            <p>Querying Prometheus…</p>
          </div>
          <div v-else-if="statusError" class="cts-banner cts-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="cts-btn cts-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status && status.per_op.length === 0" class="cts-empty cts-empty--muted">
            <p>No sweeper metrics observed yet — TEG containers may not have started reporting.</p>
          </div>
          <div v-else-if="status" class="cts-fleet-grid">
            <button
              v-for="op in status.per_op"
              :key="op.teg_id"
              class="cts-fleet-card"
              :class="opCardClass(op)"
              type="button"
              @click="selectedOp = selectedOp === op.op_slug ? null : op.op_slug"
              :aria-pressed="selectedOp === op.op_slug"
            >
              <div class="cts-fleet-card-head">
                <span class="cts-fleet-dot" :class="opDotClass(op)"></span>
                <span class="cts-fleet-name">{{ op.op_slug || op.teg_id }}</span>
                <span v-if="op.pending > 0" class="cts-fleet-pending" :class="op.pending > 5 ? 'cts-pill--bad' : 'cts-pill--warn'">
                  {{ op.pending }} pending
                </span>
              </div>
              <div class="cts-fleet-card-body">
                <div class="cts-fleet-row">
                  <span class="cts-fleet-key">cycles</span>
                  <span class="cts-fleet-val">{{ op.cycles_24h }}</span>
                </div>
                <div class="cts-fleet-row">
                  <span class="cts-fleet-key">aborted</span>
                  <span class="cts-fleet-val" :class="op.aborted_24h > 0 ? 'cts-text-warn' : ''">{{ op.aborted_24h }}</span>
                </div>
                <div class="cts-fleet-row">
                  <span class="cts-fleet-key">resumed</span>
                  <span class="cts-fleet-val" :class="op.resumed_24h > 0 ? 'cts-text-warn' : ''">{{ op.resumed_24h }}</span>
                </div>
                <div class="cts-fleet-row">
                  <span class="cts-fleet-key">errors</span>
                  <span class="cts-fleet-val" :class="op.errors_24h > 0 ? 'cts-text-bad' : ''">{{ op.errors_24h }}</span>
                </div>
              </div>
              <div class="cts-fleet-card-foot">
                <span class="cts-mono cts-text-muted">{{ op.teg_id }}</span>
              </div>
            </button>
          </div>
          <p v-if="selectedOp" class="cts-filter-hint">
            Filtering activity by <strong>{{ selectedOp }}</strong> — click the card again to clear.
          </p>
        </section>

        <!-- Inner tabs -->
        <section class="cts-section">
          <div class="cts-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              class="cts-tab"
              :class="{ 'cts-tab--active': activeTab === tab.id }"
              type="button"
              @click="activeTab = tab.id"
            >
              {{ tab.label }}
            </button>
            <div class="cts-tabs-right">
              <button class="cts-btn cts-btn--ghost" @click="exportCsv" :disabled="filteredEvents.length === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <!-- Activity tab -->
          <div v-if="activeTab === 'activity'" class="cts-activity">
            <!-- Action filter chips -->
            <div class="cts-chip-row">
              <button
                class="cts-chip"
                :class="{ 'cts-chip--active': actionFilter === null }"
                @click="actionFilter = null"
              >All</button>
              <button
                class="cts-chip"
                :class="{ 'cts-chip--active': actionFilter === 'aborted' }"
                @click="actionFilter = 'aborted'"
              >Aborted</button>
              <button
                class="cts-chip"
                :class="{ 'cts-chip--active': actionFilter === 'resumed' }"
                @click="actionFilter = 'resumed'"
              >Resumed</button>
              <button
                class="cts-chip"
                :class="{ 'cts-chip--active': actionFilter === 'error' }"
                @click="actionFilter = 'error'"
              >Errors</button>
            </div>

            <div v-if="loadingEvents && filteredEvents.length === 0" class="cts-empty">
              <div class="cts-spinner"></div>
              <p>Loading audit feed…</p>
            </div>
            <div v-else-if="eventsError" class="cts-banner cts-banner--bad">
              <Icon name="mdi:alert" /> {{ eventsError }}
              <button class="cts-btn cts-btn--ghost" @click="loadEvents">Retry</button>
            </div>
            <div v-else-if="filteredEvents.length === 0" class="cts-empty cts-empty--muted">
              <p v-if="selectedOp || actionFilter">No events match the current filter.</p>
              <p v-else>No sweeper events in the last 24h — fleet healthy.</p>
            </div>
            <div v-else class="cts-table-wrap">
              <table class="cts-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Op</th>
                    <th>Action</th>
                    <th>Transfer ID</th>
                    <th>Agent</th>
                    <th>Amount</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="e in filteredEvents" :key="e.event_id || e.timestamp || ''">
                    <td class="cts-mono">{{ formatTime(e.timestamp) }}</td>
                    <td>{{ e.op_slug || '—' }}</td>
                    <td>
                      <span class="cts-action-pill" :class="actionPillClass(e.action)">
                        {{ e.action }}
                      </span>
                    </td>
                    <td>
                      <a
                        v-if="e.transfer_id"
                        :href="eventsLinkFor(e.transfer_id)"
                        class="cts-link"
                        target="_blank"
                        rel="noopener"
                        :title="e.transfer_id"
                      >{{ truncate(e.transfer_id, 14) }}</a>
                      <span v-else class="cts-text-muted">—</span>
                    </td>
                    <td class="cts-mono" :title="e.source_agent_id || ''">
                      {{ truncate(e.source_agent_id, 24) }}
                    </td>
                    <td class="cts-mono">{{ e.amount || '—' }}</td>
                    <td class="cts-mono cts-text-muted">
                      <template v-if="e.action === 'error'">{{ truncate(e.error_message, 60) }}</template>
                      <template v-else-if="e.resolution">{{ e.resolution }}</template>
                      <template v-else-if="e.prior_status">prior: {{ e.prior_status }}</template>
                      <template v-else>—</template>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Trends tab -->
          <div v-else-if="activeTab === 'trends'" class="cts-trends">
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div class="cts-trend-cards">
              <div class="cts-trend-card">
                <div class="cts-trend-label">Cycles 24h</div>
                <div class="cts-trend-value">{{ status?.summary.cycles_24h ?? '—' }}</div>
                <div class="cts-trend-sub">across {{ status?.summary.teg_count ?? '—' }} TEGs</div>
              </div>
              <div class="cts-trend-card">
                <div class="cts-trend-label">Aborted 24h</div>
                <div class="cts-trend-value">{{ status?.summary.aborted_24h ?? '—' }}</div>
                <div class="cts-trend-sub">expired locks released</div>
              </div>
              <div class="cts-trend-card">
                <div class="cts-trend-label">Pending now</div>
                <div class="cts-trend-value">{{ status?.summary.pending_total ?? '—' }}</div>
                <div class="cts-trend-sub">past expires_at, awaiting sweep</div>
              </div>
            </div>
            <p class="cts-trends-note">
              ⓘ Long-window trends + sparklines live in Grafana —
              <a href="https://grafana.theprotocol.cloud" target="_blank" rel="noopener" class="cts-link">
                cross-TEG / 2PC dashboard
              </a>. The modal surfaces 24h sums for incident-response triage.
            </p>
          </div>

          <!-- Per-op details tab -->
          <div v-else-if="activeTab === 'per-op'" class="cts-per-op">
            <div v-if="!selectedOp" class="cts-empty cts-empty--muted">
              <p>Pick a TEG from the fleet grid above to inspect its sweeper history in isolation.</p>
            </div>
            <div v-else>
              <h4 class="cts-per-op-head">{{ selectedOp }}</h4>
              <div v-if="perOpEntry" class="cts-per-op-stats">
                <div class="cts-per-op-stat">
                  <span class="cts-per-op-stat-key">teg_id</span>
                  <span class="cts-per-op-stat-val cts-mono">{{ perOpEntry.teg_id }}</span>
                </div>
                <div class="cts-per-op-stat">
                  <span class="cts-per-op-stat-key">cycles 24h</span>
                  <span class="cts-per-op-stat-val">{{ perOpEntry.cycles_24h }}</span>
                </div>
                <div class="cts-per-op-stat">
                  <span class="cts-per-op-stat-key">aborted 24h</span>
                  <span class="cts-per-op-stat-val">{{ perOpEntry.aborted_24h }}</span>
                </div>
                <div class="cts-per-op-stat">
                  <span class="cts-per-op-stat-key">resumed 24h</span>
                  <span class="cts-per-op-stat-val">{{ perOpEntry.resumed_24h }}</span>
                </div>
                <div class="cts-per-op-stat">
                  <span class="cts-per-op-stat-key">errors 24h</span>
                  <span class="cts-per-op-stat-val" :class="perOpEntry.errors_24h > 0 ? 'cts-text-bad' : ''">
                    {{ perOpEntry.errors_24h }}
                  </span>
                </div>
                <div class="cts-per-op-stat">
                  <span class="cts-per-op-stat-key">pending</span>
                  <span class="cts-per-op-stat-val" :class="perOpEntry.pending > 0 ? 'cts-text-warn' : ''">
                    {{ perOpEntry.pending }}
                  </span>
                </div>
              </div>
              <p class="cts-per-op-note">
                Switch to the <button class="cts-link-btn" @click="activeTab = 'activity'">Recent Activity</button>
                tab to see the per-op event stream (filtered automatically by your selection).
              </p>
            </div>
          </div>
        </section>

        <!-- Footer -->
        <div class="cts-footer">
          <span class="cts-mono cts-text-muted">
            GET /admin/cross-teg-sweeper/*&nbsp;·&nbsp;Auto-refresh: paused on tab-hidden
          </span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import Icon from '@/components/Icon.vue'
/**
 * CrossTegSweeperModal — Tier 3 observability for the 2PC coordination sweeper.
 *
 * §pass26 (2026-05-17). Generic worker-modal foundation: accepts `worker_id`
 * prop; today only `cross_teg_sweeper` is mapped on the backend. Future
 * workers (canary_judge / canary_rebalancer / saga_timeout_checker) can
 * reuse the same shell by adding their endpoint mappings server-side.
 *
 * Polls /admin/cross-teg-sweeper/{status,events} every 5s while open.
 * Pauses on tab-hidden (visibilitychange). All CSV export goes via the
 * shared csvExport.ts helper for RFC 4180 compliance.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import dayjs from 'dayjs'
import {
  getSweeperStatus,
  getSweeperEvents,
  type SweeperStatusResponse,
  type SweeperEvent,
  type SweeperPerOp,
  type SweeperAction,
} from '@/services/api/crossTegSweeper'
import { downloadCsv } from '@/components/common/csvExport'

interface Props {
  workerId?: string
}
const props = withDefaults(defineProps<Props>(), {
  workerId: 'cross_teg_sweeper',
})

const emit = defineEmits<{ (e: 'close'): void }>()

// ── State ────────────────────────────────────────────────────────────────
const status = ref<SweeperStatusResponse | null>(null)
const events = ref<SweeperEvent[]>([])
const loadingStatus = ref(false)
const loadingEvents = ref(false)
const statusError = ref('')
const eventsError = ref('')

const selectedOp = ref<string | null>(null)
const actionFilter = ref<SweeperAction | null>(null)
const activeTab = ref<'activity' | 'trends' | 'per-op'>('activity')
const autoRefresh = ref(true)

let refreshInterval: number | null = null

const tabs: { id: 'activity' | 'trends' | 'per-op'; label: string }[] = [
  { id: 'activity', label: 'Recent Activity' },
  { id: 'trends',   label: 'Trends' },
  { id: 'per-op',   label: 'Per-Op Details' },
]

// ── Derived ──────────────────────────────────────────────────────────────
const hasErrors = computed(() => (status.value?.summary.errors_24h ?? 0) > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'cts-status-dot--bad'
  if (!status.value) return 'cts-status-dot--muted'
  if (status.value.summary.errors_24h > 0) return 'cts-status-dot--bad'
  if (status.value.summary.pending_total > 0) return 'cts-status-dot--warn'
  return 'cts-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  if (status.value.summary.errors_24h > 0) return `Errors detected (${status.value.summary.errors_24h})`
  if (status.value.summary.pending_total > 0) return `${status.value.summary.pending_total} pending`
  return 'All healthy'
})

const filteredEvents = computed(() => {
  let list = events.value
  if (selectedOp.value) list = list.filter(e => e.op_slug === selectedOp.value)
  if (actionFilter.value) list = list.filter(e => e.action === actionFilter.value)
  return list
})

const perOpEntry = computed<SweeperPerOp | null>(() => {
  if (!selectedOp.value || !status.value) return null
  return status.value.per_op.find(p => p.op_slug === selectedOp.value) || null
})

// ── Loaders ──────────────────────────────────────────────────────────────
async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getSweeperStatus()
  } catch (e: any) {
    statusError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingStatus.value = false
  }
}

async function loadEvents() {
  if (loadingEvents.value) return
  loadingEvents.value = true
  try {
    eventsError.value = ''
    const resp = await getSweeperEvents({
      op: selectedOp.value || undefined,
      action: actionFilter.value || undefined,
      limit: 100,
    })
    events.value = resp.events
  } catch (e: any) {
    eventsError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingEvents.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadEvents()])
}

// Re-fetch events when filters change (server-side filter is cheaper than client-side
// when traffic grows).
watch([selectedOp, actionFilter], () => { loadEvents() })

// ── Polling ──────────────────────────────────────────────────────────────
function tick() {
  if (document.visibilityState === 'hidden') return
  refreshAll()
}
function startPolling() {
  if (refreshInterval !== null) return
  refreshInterval = window.setInterval(tick, 5_000)
}
function stopPolling() {
  if (refreshInterval !== null) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}

onMounted(() => {
  refreshAll()
  if (autoRefresh.value) startPolling()
})
onBeforeUnmount(() => { stopPolling() })

// ── Helpers ──────────────────────────────────────────────────────────────
function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).format('HH:mm:ss')
}
function truncate(s?: string | null, n = 12): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}
function opCardClass(op: SweeperPerOp) {
  return {
    'cts-fleet-card--active': selectedOp.value === op.op_slug,
    'cts-fleet-card--bad':    op.errors_24h > 0,
    'cts-fleet-card--warn':   op.errors_24h === 0 && op.pending > 5,
    'cts-fleet-card--idle':   op.errors_24h === 0 && op.pending === 0,
  }
}
function opDotClass(op: SweeperPerOp) {
  if (op.errors_24h > 0) return 'cts-fleet-dot--bad'
  if (op.pending > 5) return 'cts-fleet-dot--warn'
  if (op.pending > 0) return 'cts-fleet-dot--warn-mild'
  return 'cts-fleet-dot--ok'
}
function actionPillClass(action: string) {
  return {
    'cts-action-pill--abort':  action === 'aborted',
    'cts-action-pill--resume': action === 'resumed',
    'cts-action-pill--err':    action === 'error',
  }
}
function eventsLinkFor(transferId: string): string {
  // Frame A admin events page deep-link. Open in new tab.
  return `/ui#/admin/events?search=${encodeURIComponent(transferId)}`
}

function exportCsv() {
  const filename = `cross-teg-sweeper-${dayjs().format('YYYY-MM-DD-HHmm')}.csv`
  downloadCsv<SweeperEvent>(
    filteredEvents.value,
    [
      { label: 'timestamp',       value: e => e.timestamp || '' },
      { label: 'op_slug',         value: e => e.op_slug || '' },
      { label: 'action',          value: e => e.action },
      { label: 'transfer_id',     value: e => e.transfer_id || '' },
      { label: 'source_agent_id', value: e => e.source_agent_id || '' },
      { label: 'target_agent_id', value: e => e.target_agent_id || '' },
      { label: 'amount',          value: e => e.amount || '' },
      { label: 'currency',        value: e => e.currency || '' },
      { label: 'prior_status',    value: e => e.prior_status || '' },
      { label: 'resolution',      value: e => e.resolution || '' },
      { label: 'error_message',   value: e => e.error_message || '' },
      { label: 'teg_id',          value: e => e.teg_id || '' },
    ],
    filename,
  )
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.cts-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.cts-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.cts-modal--errors {
  border-color: rgba(239, 68, 68, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(239, 68, 68, 0.2);
}

/* Header */
.cts-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.cts-header-left { display: flex; align-items: center; gap: 10px; }
.cts-header-right { display: flex; align-items: center; gap: 8px; }
.cts-title { font-size: 1.05rem; margin: 0; font-weight: 600; letter-spacing: 0.01em; }
.cts-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.cts-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }

.cts-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.cts-status-dot--ok   { background: #10b981; color: #10b981; }
.cts-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.cts-status-dot--bad  { background: #ef4444; color: #ef4444; animation: cts-pulse 1.8s infinite; }
.cts-status-dot--muted { background: #4b5563; color: #4b5563; }

@keyframes cts-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

/* Buttons */
.cts-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  transition: background 0.15s, border-color 0.15s;
}
.cts-btn:hover:not(:disabled) {
  background: rgba(0, 210, 210, 0.08);
  border-color: rgba(0, 210, 210, 0.45);
}
.cts-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.cts-btn--ghost { background: transparent; }
.cts-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.cts-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

/* Stats row */
.cts-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.cts-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.cts-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.cts-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.cts-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.cts-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.cts-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

/* Sections */
.cts-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.cts-section:last-of-type { border-bottom: none; }
.cts-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.cts-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

/* Fleet grid */
.cts-fleet-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}
.cts-fleet-card {
  background: rgba(0, 210, 210, 0.02);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  border-radius: 8px;
  padding: 10px;
  text-align: left;
  cursor: pointer;
  color: inherit;
  transition: background 0.15s, border-color 0.15s, transform 0.15s;
}
.cts-fleet-card:hover { background: rgba(0, 210, 210, 0.06); transform: translateY(-1px); }
.cts-fleet-card--active { border-color: var(--nc-primary, #00d2d2); background: rgba(0, 210, 210, 0.08); }
.cts-fleet-card--bad  { border-color: rgba(239, 68, 68, 0.55); }
.cts-fleet-card--warn { border-color: rgba(245, 158, 11, 0.45); }
.cts-fleet-card--idle { /* default */ }
.cts-fleet-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.cts-fleet-dot { width: 8px; height: 8px; border-radius: 50%; }
.cts-fleet-dot--ok        { background: #10b981; box-shadow: 0 0 4px #10b981; }
.cts-fleet-dot--warn-mild { background: #facc15; }
.cts-fleet-dot--warn      { background: #f59e0b; box-shadow: 0 0 4px #f59e0b; }
.cts-fleet-dot--bad       { background: #ef4444; box-shadow: 0 0 4px #ef4444; }
.cts-fleet-name { font-weight: 600; font-size: 0.82rem; flex: 1; }
.cts-fleet-pending {
  font-size: 0.66rem; padding: 2px 6px; border-radius: 4px; font-weight: 600;
  letter-spacing: 0.02em;
}
.cts-pill--warn { background: rgba(245, 158, 11, 0.18); color: #fbbf24; }
.cts-pill--bad  { background: rgba(239, 68, 68, 0.18); color: #f87171; }
.cts-fleet-card-body { display: flex; flex-direction: column; gap: 2px; margin: 4px 0; }
.cts-fleet-row { display: flex; justify-content: space-between; font-size: 0.74rem; }
.cts-fleet-key { color: var(--nc-muted, #94a3b8); }
.cts-fleet-val { font-variant-numeric: tabular-nums; }
.cts-fleet-card-foot { margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(0, 210, 210, 0.08); }

.cts-filter-hint {
  margin: 10px 0 0 0;
  font-size: 0.75rem;
  color: var(--nc-muted, #94a3b8);
}

/* Tabs */
.cts-tabs {
  display: flex;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  margin: -6px -20px 12px -20px;
  padding: 0 20px;
  align-items: center;
}
.cts-tabs-right { margin-left: auto; padding-bottom: 6px; }
.cts-tab {
  background: transparent; border: none; color: var(--nc-muted, #94a3b8);
  padding: 8px 14px; cursor: pointer; font-size: 0.8rem;
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
}
.cts-tab:hover { color: var(--nc-text, #e2e8f0); }
.cts-tab--active { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }

/* Chip row */
.cts-chip-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.cts-chip {
  padding: 4px 10px; font-size: 0.72rem; border-radius: 12px;
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  color: var(--nc-text, #e2e8f0); cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.cts-chip:hover { background: rgba(0, 210, 210, 0.12); }
.cts-chip--active {
  background: rgba(0, 210, 210, 0.18);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}

/* Table */
.cts-table-wrap { overflow-x: auto; }
.cts-table {
  width: 100%; border-collapse: collapse; font-size: 0.78rem;
}
.cts-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.cts-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.cts-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }

.cts-action-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.cts-action-pill--abort  { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }
.cts-action-pill--resume { background: rgba(99, 102, 241, 0.16); color: #a5b4fc; }
.cts-action-pill--err    { background: rgba(239, 68, 68, 0.16); color: #f87171; }

.cts-link {
  color: var(--nc-primary, #00d2d2); text-decoration: none; border-bottom: 1px dashed currentColor;
}
.cts-link:hover { color: #5eead4; }
.cts-link-btn {
  background: none; border: none; color: var(--nc-primary, #00d2d2); cursor: pointer;
  font: inherit; padding: 0; text-decoration: underline;
}

/* Trends */
.cts-trends { padding-top: 8px; }
.cts-trend-cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.cts-trend-card {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  border-radius: 8px; padding: 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.cts-trend-label { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.cts-trend-value { font-size: 1.7rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.cts-trend-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }
.cts-trends-note { margin-top: 14px; font-size: 0.78rem; color: var(--nc-muted, #94a3b8); }

/* Per-op */
.cts-per-op { padding-top: 4px; }
.cts-per-op-head { font-size: 0.95rem; margin: 0 0 12px 0; }
.cts-per-op-stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px; margin-bottom: 16px;
}
.cts-per-op-stat {
  background: rgba(0, 210, 210, 0.03);
  border: 1px solid rgba(0, 210, 210, 0.12);
  border-radius: 6px; padding: 8px 10px;
  display: flex; flex-direction: column; gap: 2px;
}
.cts-per-op-stat-key { font-size: 0.66rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; }
.cts-per-op-stat-val { font-size: 1rem; font-weight: 600; }
.cts-per-op-note { font-size: 0.78rem; color: var(--nc-muted, #94a3b8); }

/* Empty/loading */
.cts-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.cts-empty--muted { color: var(--nc-muted, #94a3b8); font-size: 0.82rem; }
.cts-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: cts-spin 0.8s linear infinite;
}
@keyframes cts-spin { to { transform: rotate(360deg); } }

/* Banner */
.cts-banner {
  padding: 10px 14px; border-radius: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px;
}
.cts-banner--bad {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

/* Text utilities */
.cts-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.cts-text-muted { color: var(--nc-muted, #94a3b8); }
.cts-text-warn  { color: #fbbf24; }
.cts-text-bad   { color: #f87171; }

/* Footer */
.cts-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .cts-stats-row { grid-template-columns: repeat(2, 1fr); }
  .cts-modal { max-height: 92vh; }
}

@media (prefers-reduced-motion: reduce) {
  .cts-status-dot--bad { animation: none; }
  .cts-fleet-card { transition: none; }
}
</style>
