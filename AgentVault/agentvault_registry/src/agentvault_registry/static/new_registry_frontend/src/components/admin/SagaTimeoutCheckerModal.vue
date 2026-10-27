<template>
  <Teleport to="body">
    <div
      class="stm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="stm-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="stm-modal" :class="{ 'stm-modal--errors': hasErrors }">
        <!-- Header -->
        <div class="stm-header">
          <div class="stm-header-left">
            <span class="stm-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="stm-modal-title" class="stm-title">Saga Timeout Checker</h2>
            <span class="stm-subtitle">{{ workerId }}</span>
          </div>
          <div class="stm-header-right">
            <span v-if="status?.snapshot_iso" class="stm-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="stm-btn stm-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingEvents">
              <span class="stm-live-dot" :class="{ 'stm-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="stm-btn stm-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="stm-stats-row">
          <div class="stm-stat" :class="{ 'stm-stat--warn': (status?.summary.settlements_timed_out_24h ?? 0) > 0 }">
            <span class="stm-stat-label">Settlements 24h</span>
            <span class="stm-stat-value">{{ status?.summary.settlements_timed_out_24h ?? '—' }}</span>
            <span class="stm-stat-sub">timed out past 72h</span>
          </div>
          <div class="stm-stat" :class="{ 'stm-stat--warn': (status?.summary.cross_frame_refunded_24h ?? 0) > 0 }">
            <span class="stm-stat-label">Cross-frame 24h</span>
            <span class="stm-stat-value">{{ status?.summary.cross_frame_refunded_24h ?? '—' }}</span>
            <span class="stm-stat-sub">refunded via sweep</span>
          </div>
          <div class="stm-stat" :class="{ 'stm-stat--warn': (status?.summary.pending_now ?? 0) > 0 }">
            <span class="stm-stat-label">Pending now</span>
            <span class="stm-stat-value">{{ status?.summary.pending_now ?? '—' }}</span>
            <span class="stm-stat-sub">awaiting sweep</span>
          </div>
          <div class="stm-stat" :class="{ 'stm-stat--bad': (status?.summary.errors_24h ?? 0) > 0 }">
            <span class="stm-stat-label">Errors 24h</span>
            <span class="stm-stat-value">{{ status?.summary.errors_24h ?? '—' }}</span>
            <span class="stm-stat-sub">{{ !status ? '—' : (status.summary.errors_24h ?? 0) === 0 ? 'all healthy' : 'investigate' }}</span>
          </div>
        </div>

        <!-- Per-registry rail -->
        <section class="stm-section">
          <h3 class="stm-section-title">
            Fleet
            <span class="stm-section-sub">
              {{ status?.per_registry.length ?? '—' }} registries reporting · {{ status?.summary.cross_frame_cycles_24h ?? '—' }} cf cycles · {{ status?.summary.settlement_cycles_24h ?? '—' }} settlement cycles (24h)
            </span>
          </h3>
          <div v-if="loadingStatus && !status" class="stm-empty">
            <div class="stm-spinner"></div>
            <p>Loading registry state…</p>
          </div>
          <div v-else-if="statusError" class="stm-banner stm-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="stm-btn stm-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status && status.per_registry.length === 0" class="stm-empty stm-empty--muted">
            <p>No metrics observed yet — registries may not have reported a cycle.</p>
          </div>
          <div v-else-if="status" class="stm-fleet-grid">
            <div
              v-for="r in status.per_registry"
              :key="r.registry_id"
              class="stm-fleet-card"
              :class="registryCardClass(r)"
            >
              <div class="stm-fleet-card-head">
                <span class="stm-fleet-dot" :class="registryDotClass(r)"></span>
                <span class="stm-fleet-name">{{ r.registry_id }}</span>
              </div>
              <div class="stm-fleet-card-body">
                <div class="stm-fleet-row"><span class="stm-fleet-key">cf refunded</span><span class="stm-fleet-val">{{ r.cross_frame_refunded_24h }}</span></div>
                <div class="stm-fleet-row"><span class="stm-fleet-key">settle timeouts</span><span class="stm-fleet-val">{{ r.settlements_timed_out_24h }}</span></div>
                <div class="stm-fleet-row"><span class="stm-fleet-key">cf cycles</span><span class="stm-fleet-val">{{ r.cross_frame_cycles_24h }}</span></div>
                <div class="stm-fleet-row"><span class="stm-fleet-key">settle cycles</span><span class="stm-fleet-val">{{ r.settlement_cycles_24h }}</span></div>
                <div class="stm-fleet-row">
                  <span class="stm-fleet-key">pending</span>
                  <span class="stm-fleet-val" :class="r.pending_now > 0 ? 'stm-text-warn' : ''">{{ r.pending_now }}</span>
                </div>
                <div class="stm-fleet-row">
                  <span class="stm-fleet-key">errors</span>
                  <span class="stm-fleet-val" :class="r.errors_24h > 0 ? 'stm-text-bad' : ''">{{ r.errors_24h }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Tabs -->
        <section class="stm-section">
          <div class="stm-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              class="stm-tab"
              :class="{ 'stm-tab--active': activeTab === tab.id }"
              type="button"
              @click="activeTab = tab.id"
            >
              {{ tab.label }}
            </button>
            <div class="stm-tabs-right">
              <button class="stm-btn stm-btn--ghost" @click="exportCsv" :disabled="filteredEvents.length === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <!-- Activity tab -->
          <div v-if="activeTab === 'activity'" class="stm-activity">
            <div class="stm-chip-row">
              <button class="stm-chip" :class="{ 'stm-chip--active': actionFilter === null }" @click="actionFilter = null">All</button>
              <button class="stm-chip" :class="{ 'stm-chip--active': actionFilter === 'settlement' }" @click="actionFilter = 'settlement'">Settlement timeouts</button>
              <button class="stm-chip" :class="{ 'stm-chip--active': actionFilter === 'cross_frame' }" @click="actionFilter = 'cross_frame'">Cross-frame refunds</button>
            </div>

            <div v-if="loadingEvents && filteredEvents.length === 0" class="stm-empty">
              <div class="stm-spinner"></div>
              <p>Loading audit feed…</p>
            </div>
            <div v-else-if="eventsError" class="stm-banner stm-banner--bad">
              <Icon name="mdi:alert" /> {{ eventsError }}
              <button class="stm-btn stm-btn--ghost" @click="loadEvents">Retry</button>
            </div>
            <div v-else-if="filteredEvents.length === 0" class="stm-empty stm-empty--muted">
              <p v-if="actionFilter">No events match this filter.</p>
              <p v-else>No saga timeouts in last 24h — fleet healthy.</p>
            </div>
            <div v-else class="stm-table-wrap">
              <table class="stm-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Type</th>
                    <th>Registry</th>
                    <th>Source → Target</th>
                    <th>ID</th>
                    <th>Amount</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="e in filteredEvents" :key="(e.event_id || '') + (e.timestamp || '')">
                    <td class="stm-mono">{{ formatTime(e.timestamp) }}</td>
                    <td>
                      <span class="stm-action-pill" :class="actionPillClass(e.action)">{{ e.action }}</span>
                    </td>
                    <td class="stm-mono">{{ e.registry_id || '—' }}</td>
                    <td class="stm-mono">
                      <template v-if="e.source_frame || e.target_frame">
                        {{ e.source_frame || '?' }} → {{ e.target_frame || '?' }}
                      </template>
                      <template v-else>—</template>
                    </td>
                    <td class="stm-mono" :title="e.settlement_id || e.transfer_id || ''">
                      {{ truncate(e.settlement_id || e.transfer_id, 18) }}
                    </td>
                    <td class="stm-mono">{{ e.amount ? formatAvt(e.amount) : '—' }}</td>
                    <td class="stm-mono stm-text-muted">{{ e.reason || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Pending sagas tab -->
          <div v-else-if="activeTab === 'pending'" class="stm-pending">
            <p class="stm-text-muted" style="margin: 0 0 10px 0; font-size: 0.78rem">
              Settlements past their 72h saga deadline (caught at next 5-min tick).
            </p>
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="stm-empty"><div class="stm-spinner"></div><p>Loading registry state…</p></div>
            <div v-else-if="status.pending_settlements.length === 0" class="stm-empty stm-empty--muted">
              <p>No pending settlements past deadline — the happy path.</p>
            </div>
            <div v-else class="stm-table-wrap">
              <table class="stm-table">
                <thead>
                  <tr>
                    <th>Settlement</th>
                    <th>Saga state</th>
                    <th>Status</th>
                    <th>Age</th>
                    <th>Amount</th>
                    <th>Defendant</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in status.pending_settlements" :key="p.settlement_id">
                    <td class="stm-mono" :title="p.settlement_id">{{ truncate(p.settlement_id, 14) }}</td>
                    <td class="stm-mono">{{ p.saga_state }}</td>
                    <td class="stm-mono">{{ p.status }}</td>
                    <td class="stm-mono stm-text-warn">{{ p.age_hours ? p.age_hours.toFixed(1) + 'h' : '—' }}</td>
                    <td class="stm-mono">{{ formatAvt(p.requested_amount) }}</td>
                    <td class="stm-mono" :title="p.defendant_did">{{ truncate(p.defendant_did, 24) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Frame flow tab -->
          <div v-else-if="activeTab === 'flow'" class="stm-flow">
            <p class="stm-text-muted" style="margin: 0 0 10px 0; font-size: 0.78rem">
              Cross-frame refund counts grouped by source → target frame, last 24h.
            </p>
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="stm-empty"><div class="stm-spinner"></div><p>Loading registry state…</p></div>
            <div v-else-if="frameMatrixRows.length === 0" class="stm-empty stm-empty--muted">
              <p>No cross-frame refunds in last 24h.</p>
            </div>
            <div v-else class="stm-flow-matrix">
              <div class="stm-flow-grid">
                <div class="stm-flow-cell stm-flow-corner"></div>
                <div v-for="tf in frameAxis" :key="'col-' + tf" class="stm-flow-axis-cell">
                  {{ truncateFrame(tf) }}
                </div>
                <template v-for="sf in frameAxis" :key="'row-' + sf">
                  <div class="stm-flow-axis-cell">{{ truncateFrame(sf) }}</div>
                  <div
                    v-for="tf in frameAxis"
                    :key="sf + '→' + tf"
                    class="stm-flow-cell"
                    :class="flowCellClass(sf, tf)"
                    @click="selectFrame(sf, tf)"
                    :title="`source=${sf} → target=${tf}\nrefunded 24h=${getMatrixValue(sf, tf)}`"
                  >
                    {{ getMatrixValue(sf, tf) }}
                  </div>
                </template>
              </div>
            </div>
            <p v-if="selectedSourceFrame || selectedTargetFrame" class="stm-filter-hint">
              Filtering activity by
              <span v-if="selectedSourceFrame"><strong>src={{ selectedSourceFrame }}</strong></span>
              <span v-if="selectedTargetFrame"> · <strong>tgt={{ selectedTargetFrame }}</strong></span>
              — click cell again to clear.
            </p>
          </div>
        </section>

        <div class="stm-footer">
          <span class="stm-mono stm-text-muted">
            GET /admin/saga-timeout/*&nbsp;·&nbsp;Auto-refresh: paused on tab-hidden
          </span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * SagaTimeoutCheckerModal — Tier 3 observability (§pass27 Phase 3).
 *
 * Aggregates BOTH registry-a and frame-b-registry via Prom `registry_id`.
 * 4 stat cards → per-registry grid → 3 tabs (Activity / Pending / Flow).
 * Frame flow matrix is a clickable N×N grid showing 24h refund counts per
 * source→target frame pair.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import dayjs from 'dayjs'
import {
  getSagaStatus,
  getSagaEvents,
  type SagaStatusResponse,
  type SagaEvent,
  type SagaRegistryRow,
  type SagaAction,
} from '@/services/api/sagaTimeout'
import { downloadCsv } from '@/components/common/csvExport'

interface Props { workerId?: string }
const props = withDefaults(defineProps<Props>(), { workerId: 'saga_timeout_checker' })

const emit = defineEmits<{ (e: 'close'): void }>()

// State
const status = ref<SagaStatusResponse | null>(null)
const events = ref<SagaEvent[]>([])
const loadingStatus = ref(false)
const loadingEvents = ref(false)
const statusError = ref('')
const eventsError = ref('')

const selectedSourceFrame = ref<string | null>(null)
const selectedTargetFrame = ref<string | null>(null)
const actionFilter = ref<SagaAction | null>(null)
const activeTab = ref<'activity' | 'pending' | 'flow'>('activity')
const autoRefresh = ref(true)

let refreshInterval: number | null = null

const tabs: { id: 'activity' | 'pending' | 'flow'; label: string }[] = [
  { id: 'activity', label: 'Recent Activity' },
  { id: 'pending',  label: 'Pending Sagas' },
  { id: 'flow',     label: 'Frame Flow' },
]

// Derived
const hasErrors = computed(() => (status.value?.summary.errors_24h ?? 0) > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'stm-status-dot--bad'
  if (!status.value) return 'stm-status-dot--muted'
  if (status.value.summary.errors_24h > 0) return 'stm-status-dot--bad'
  if (status.value.summary.pending_now > 0) return 'stm-status-dot--warn'
  return 'stm-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  if (status.value.summary.errors_24h > 0) return `${status.value.summary.errors_24h} errors`
  if (status.value.summary.pending_now > 0) return `${status.value.summary.pending_now} pending`
  return 'All healthy'
})

const frameMatrixRows = computed(() => status.value?.frame_pair_matrix ?? [])

const frameAxis = computed(() => {
  const set = new Set<string>()
  for (const c of frameMatrixRows.value) {
    if (c.source_frame) set.add(c.source_frame)
    if (c.target_frame) set.add(c.target_frame)
  }
  return [...set].sort()
})

function getMatrixValue(sf: string, tf: string): number {
  return frameMatrixRows.value.find(c => c.source_frame === sf && c.target_frame === tf)?.refunded_24h ?? 0
}

const filteredEvents = computed(() => {
  let list = events.value
  if (actionFilter.value) list = list.filter(e => e.action === actionFilter.value)
  if (selectedSourceFrame.value) list = list.filter(e => e.source_frame === selectedSourceFrame.value)
  if (selectedTargetFrame.value) list = list.filter(e => e.target_frame === selectedTargetFrame.value)
  return list
})

function registryCardClass(r: SagaRegistryRow) {
  return {
    'stm-fleet-card--bad':  r.errors_24h > 0,
    'stm-fleet-card--warn': r.errors_24h === 0 && r.pending_now > 0,
  }
}
function registryDotClass(r: SagaRegistryRow) {
  if (r.errors_24h > 0) return 'stm-fleet-dot--bad'
  if (r.pending_now > 0) return 'stm-fleet-dot--warn'
  return 'stm-fleet-dot--ok'
}
function flowCellClass(sf: string, tf: string) {
  const v = getMatrixValue(sf, tf)
  return {
    'stm-flow-cell--active': selectedSourceFrame.value === sf && selectedTargetFrame.value === tf,
    'stm-flow-cell--hot':    v >= 10,
    'stm-flow-cell--warm':   v > 0 && v < 10,
    'stm-flow-cell--cold':   v === 0,
  }
}
function selectFrame(sf: string, tf: string) {
  if (selectedSourceFrame.value === sf && selectedTargetFrame.value === tf) {
    selectedSourceFrame.value = null
    selectedTargetFrame.value = null
  } else {
    selectedSourceFrame.value = sf
    selectedTargetFrame.value = tf
  }
}
function actionPillClass(action: string) {
  return {
    'stm-action-pill--settlement': action === 'settlement',
    'stm-action-pill--crossframe': action === 'cross_frame',
  }
}

// Loaders
async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getSagaStatus()
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
    const resp = await getSagaEvents({
      action: actionFilter.value || undefined,
      source_frame: selectedSourceFrame.value || undefined,
      target_frame: selectedTargetFrame.value || undefined,
      limit: 100,
    })
    events.value = resp.events
  } catch (e: any) {
    eventsError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingEvents.value = false
  }
}
async function refreshAll() { await Promise.all([loadStatus(), loadEvents()]) }

watch([actionFilter, selectedSourceFrame, selectedTargetFrame], () => { loadEvents() })

function tick() {
  if (document.visibilityState === 'hidden') return
  refreshAll()
}
function startPolling() {
  if (refreshInterval !== null) return
  refreshInterval = window.setInterval(tick, 5_000)
}
function stopPolling() {
  if (refreshInterval !== null) { clearInterval(refreshInterval); refreshInterval = null }
}

onMounted(() => {
  refreshAll()
  if (autoRefresh.value) startPolling()
})
onBeforeUnmount(() => { stopPolling() })

// Helpers
function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).format('HH:mm:ss')
}
function truncate(s?: string | null, n = 12): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}
function truncateFrame(s: string): string {
  // Trust-domain strings can be long; keep them readable.
  if (s.length <= 16) return s
  return s.slice(0, 14) + '…'
}
function formatAvt(v?: string | null): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = parseFloat(v)
  if (!Number.isFinite(n)) return v
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}

function exportCsv() {
  const filename = `saga-timeout-${dayjs().format('YYYY-MM-DD-HHmm')}.csv`
  downloadCsv<SagaEvent>(
    filteredEvents.value,
    [
      { label: 'timestamp',     value: e => e.timestamp || '' },
      { label: 'event_type',    value: e => e.event_type },
      { label: 'action',        value: e => e.action },
      { label: 'registry_id',   value: e => e.registry_id || '' },
      { label: 'source_frame',  value: e => e.source_frame || '' },
      { label: 'target_frame',  value: e => e.target_frame || '' },
      { label: 'settlement_id', value: e => e.settlement_id || '' },
      { label: 'transfer_id',   value: e => e.transfer_id || '' },
      { label: 'sender_did',    value: e => e.sender_did || '' },
      { label: 'receiver_did',  value: e => e.receiver_did || '' },
      { label: 'amount',        value: e => e.amount || '' },
      { label: 'reason',        value: e => e.reason || '' },
    ],
    filename,
  )
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.stm-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.stm-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.stm-modal--errors {
  border-color: rgba(239, 68, 68, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(239, 68, 68, 0.2);
}

/* Header */
.stm-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.stm-header-left { display: flex; align-items: center; gap: 10px; }
.stm-header-right { display: flex; align-items: center; gap: 8px; }
.stm-title { font-size: 1.05rem; margin: 0; font-weight: 600; }
.stm-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.stm-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.stm-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.stm-status-dot--ok   { background: #10b981; color: #10b981; }
.stm-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.stm-status-dot--bad  { background: #ef4444; color: #ef4444; animation: stm-pulse 1.8s infinite; }
.stm-status-dot--muted { background: #4b5563; color: #4b5563; }
@keyframes stm-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

/* Buttons */
.stm-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
}
.stm-btn:hover:not(:disabled) { background: rgba(0, 210, 210, 0.08); border-color: rgba(0, 210, 210, 0.45); }
.stm-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.stm-btn--ghost { background: transparent; }
.stm-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.stm-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

/* Stats */
.stm-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.stm-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.stm-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.stm-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.stm-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.stm-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.stm-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

/* Sections */
.stm-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.stm-section:last-of-type { border-bottom: none; }
.stm-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.stm-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

/* Fleet */
.stm-fleet-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.stm-fleet-card {
  background: rgba(0, 210, 210, 0.02);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  border-radius: 8px;
  padding: 10px;
}
.stm-fleet-card--warn { border-color: rgba(245, 158, 11, 0.45); }
.stm-fleet-card--bad  { border-color: rgba(239, 68, 68, 0.55); }
.stm-fleet-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.stm-fleet-dot { width: 8px; height: 8px; border-radius: 50%; }
.stm-fleet-dot--ok   { background: #10b981; box-shadow: 0 0 4px #10b981; }
.stm-fleet-dot--warn { background: #f59e0b; box-shadow: 0 0 4px #f59e0b; }
.stm-fleet-dot--bad  { background: #ef4444; box-shadow: 0 0 4px #ef4444; }
.stm-fleet-name { font-weight: 600; font-size: 0.82rem; font-family: ui-monospace, monospace; }
.stm-fleet-card-body { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.stm-fleet-row { display: flex; justify-content: space-between; font-size: 0.74rem; }
.stm-fleet-key { color: var(--nc-muted, #94a3b8); }
.stm-fleet-val { font-variant-numeric: tabular-nums; }

/* Tabs */
.stm-tabs {
  display: flex;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  margin: -6px -20px 12px -20px;
  padding: 0 20px;
  align-items: center;
}
.stm-tabs-right { margin-left: auto; padding-bottom: 6px; }
.stm-tab {
  background: transparent; border: none; color: var(--nc-muted, #94a3b8);
  padding: 8px 14px; cursor: pointer; font-size: 0.8rem;
  border-bottom: 2px solid transparent;
}
.stm-tab--active { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.stm-tab:hover { color: var(--nc-text, #e2e8f0); }

/* Chips */
.stm-chip-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.stm-chip {
  padding: 4px 10px; font-size: 0.72rem; border-radius: 12px;
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  color: var(--nc-text, #e2e8f0); cursor: pointer;
}
.stm-chip--active {
  background: rgba(0, 210, 210, 0.18);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}
.stm-chip:hover { background: rgba(0, 210, 210, 0.12); }

/* Table */
.stm-table-wrap { overflow-x: auto; }
.stm-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.stm-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.stm-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.stm-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }

.stm-action-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.stm-action-pill--settlement { background: rgba(245, 158, 11, 0.18); color: #fbbf24; }
.stm-action-pill--crossframe { background: rgba(99, 102, 241, 0.18); color: #a5b4fc; }

/* Flow matrix */
.stm-flow-matrix { padding: 4px 0; }
.stm-flow-grid {
  display: grid;
  grid-template-columns: auto repeat(var(--stm-cols, 4), minmax(80px, 1fr));
  gap: 4px;
}
.stm-flow-corner { background: transparent; }
.stm-flow-axis-cell {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.12);
  border-radius: 4px;
  padding: 6px 8px;
  font-family: ui-monospace, monospace;
  font-size: 0.72rem;
  color: var(--nc-muted, #94a3b8);
  text-align: center;
}
.stm-flow-cell {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(0, 210, 210, 0.12);
  border-radius: 4px;
  padding: 14px 8px;
  text-align: center;
  cursor: pointer;
  font-family: ui-monospace, monospace;
  font-size: 0.92rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  transition: background 0.15s, border-color 0.15s;
}
.stm-flow-cell:hover { background: rgba(0, 210, 210, 0.1); }
.stm-flow-cell--cold { color: rgba(255, 255, 255, 0.35); }
.stm-flow-cell--warm { background: rgba(245, 158, 11, 0.10); border-color: rgba(245, 158, 11, 0.35); color: #fbbf24; }
.stm-flow-cell--hot  { background: rgba(239, 68, 68, 0.12);  border-color: rgba(239, 68, 68, 0.45);  color: #f87171; }
.stm-flow-cell--active { box-shadow: 0 0 0 2px var(--nc-primary, #00d2d2) inset; }

.stm-filter-hint { margin: 10px 0 0 0; font-size: 0.75rem; color: var(--nc-muted, #94a3b8); }

/* Empty / loading */
.stm-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.stm-empty--muted { font-size: 0.82rem; }
.stm-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: stm-spin 0.8s linear infinite;
}
@keyframes stm-spin { to { transform: rotate(360deg); } }

.stm-banner {
  padding: 10px 14px; border-radius: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px;
}
.stm-banner--bad {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

.stm-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.stm-text-muted { color: var(--nc-muted, #94a3b8); }
.stm-text-warn  { color: #fbbf24; }
.stm-text-bad   { color: #f87171; }
.stm-text-ok    { color: #34d399; }

.stm-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .stm-stats-row { grid-template-columns: repeat(2, 1fr); }
  .stm-modal { max-height: 92vh; }
}

@media (prefers-reduced-motion: reduce) {
  .stm-status-dot--bad { animation: none; }
}
</style>
