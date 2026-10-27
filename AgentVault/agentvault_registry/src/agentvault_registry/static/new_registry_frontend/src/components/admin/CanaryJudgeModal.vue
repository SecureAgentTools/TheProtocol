<template>
  <Teleport to="body">
    <div
      class="cjm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cjm-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="cjm-modal" :class="{ 'cjm-modal--errors': hasFailures }">
        <!-- Header -->
        <div class="cjm-header">
          <div class="cjm-header-left">
            <span class="cjm-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="cjm-modal-title" class="cjm-title">Canary Judge</h2>
            <span class="cjm-subtitle">{{ workerId }}</span>
          </div>
          <div class="cjm-header-right">
            <span v-if="status?.snapshot_iso" class="cjm-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="cjm-btn cjm-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingEvents">
              <span class="cjm-live-dot" :class="{ 'cjm-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="cjm-btn cjm-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="cjm-stats-row">
          <div class="cjm-stat">
            <span class="cjm-stat-label">Cycles 24h</span>
            <span class="cjm-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="cjm-stat-sub">{{ status?.summary.active_paths ?? '—' }} active paths</span>
          </div>
          <div class="cjm-stat">
            <span class="cjm-stat-label">Passes 24h</span>
            <span class="cjm-stat-value">{{ status?.summary.passes_24h ?? '—' }}</span>
            <span class="cjm-stat-sub">{{ passRateLabel }}</span>
          </div>
          <div class="cjm-stat" :class="{ 'cjm-stat--warn': (status?.summary.failures_24h ?? 0) > 0 }">
            <span class="cjm-stat-label">Failures 24h</span>
            <span class="cjm-stat-value">{{ status?.summary.failures_24h ?? '—' }}</span>
            <span class="cjm-stat-sub">timeouts + refunds</span>
          </div>
          <div class="cjm-stat" :class="{ 'cjm-stat--warn': (status?.summary.in_flight_count ?? 0) > 0 }">
            <span class="cjm-stat-label">In flight</span>
            <span class="cjm-stat-value">{{ status?.summary.in_flight_count ?? '—' }}</span>
            <span class="cjm-stat-sub">awaiting judge</span>
          </div>
        </div>

        <!-- Path × Backend matrix -->
        <section class="cjm-section">
          <h3 class="cjm-section-title">
            Path × Backend Matrix
            <span class="cjm-section-sub">
              {{ status?.per_path.length ?? '—' }} paths · click a cell to filter the activity feed
            </span>
          </h3>
          <div v-if="loadingStatus && !status" class="cjm-empty">
            <div class="cjm-spinner"></div>
            <p>Querying Prometheus + canary_test_results…</p>
          </div>
          <div v-else-if="statusError" class="cjm-banner cjm-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="cjm-btn cjm-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status && status.per_path.length === 0" class="cjm-empty cjm-empty--muted">
            <p>No canary paths configured.</p>
          </div>
          <div v-else-if="status" class="cjm-matrix">
            <div class="cjm-matrix-grid">
              <button
                v-for="p in status.per_path"
                :key="p.path_id + ':' + p.backend"
                class="cjm-matrix-cell"
                :class="cellClass(p)"
                type="button"
                @click="selectedPath = (selectedPath === p.path_human && selectedBackend === p.backend) ? null : p.path_human; selectedBackend = (selectedPath ? p.backend : null)"
                :aria-pressed="selectedPath === p.path_human && selectedBackend === p.backend"
                :title="`${p.path_human}\nbackend=${p.backend}\npasses=${p.passes_24h} failures=${p.failures_24h}`"
              >
                <div class="cjm-cell-head">
                  <span class="cjm-cell-dot" :class="cellDotClass(p)"></span>
                  <span class="cjm-cell-name">{{ shortPath(p.path_human) }}</span>
                </div>
                <div class="cjm-cell-body">
                  <span class="cjm-cell-rate" :class="rateClass(p)">
                    {{ p.pass_rate_24h !== null ? p.pass_rate_24h + '%' : '—' }}
                  </span>
                  <span class="cjm-cell-sub">{{ p.backend }}</span>
                </div>
                <div class="cjm-cell-foot">
                  <span class="cjm-mono cjm-text-muted">
                    {{ p.passes_24h }}/{{ p.passes_24h + p.failures_24h }}
                  </span>
                </div>
              </button>
            </div>
            <p v-if="selectedPath" class="cjm-filter-hint">
              Filtering by <strong>{{ selectedPath }}</strong>
              <span v-if="selectedBackend">· backend={{ selectedBackend }}</span>
              — click the cell again to clear.
            </p>
          </div>
        </section>

        <!-- Tabs -->
        <section class="cjm-section">
          <div class="cjm-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              class="cjm-tab"
              :class="{ 'cjm-tab--active': activeTab === tab.id }"
              type="button"
              @click="activeTab = tab.id"
            >
              {{ tab.label }}
            </button>
            <div class="cjm-tabs-right">
              <button class="cjm-btn cjm-btn--ghost" @click="exportCsv" :disabled="filteredEvents.length === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <!-- Activity tab -->
          <div v-if="activeTab === 'activity'" class="cjm-activity">
            <div class="cjm-chip-row">
              <button class="cjm-chip" :class="{ 'cjm-chip--active': outcomeFilter === null }" @click="outcomeFilter = null">All</button>
              <button class="cjm-chip" :class="{ 'cjm-chip--active': outcomeFilter === 'passed' }" @click="outcomeFilter = 'passed'">Passed</button>
              <button class="cjm-chip" :class="{ 'cjm-chip--active': outcomeFilter === 'failed' }" @click="outcomeFilter = 'failed'">Failed</button>
              <button class="cjm-chip" :class="{ 'cjm-chip--active': outcomeFilter === 'fired' }" @click="outcomeFilter = 'fired'">Pending</button>
            </div>

            <div v-if="loadingEvents && filteredEvents.length === 0" class="cjm-empty">
              <div class="cjm-spinner"></div>
              <p>Loading recent results…</p>
            </div>
            <div v-else-if="eventsError" class="cjm-banner cjm-banner--bad">
              <Icon name="mdi:alert" /> {{ eventsError }}
              <button class="cjm-btn cjm-btn--ghost" @click="loadEvents">Retry</button>
            </div>
            <div v-else-if="filteredEvents.length === 0" class="cjm-empty cjm-empty--muted">
              <p v-if="selectedPath || outcomeFilter">No results match the current filter.</p>
              <p v-else>No canary results yet — judge cycle may not have run.</p>
            </div>
            <div v-else class="cjm-table-wrap">
              <table class="cjm-table">
                <thead>
                  <tr>
                    <th>Fired</th>
                    <th>Path</th>
                    <th>Backend</th>
                    <th>Outcome</th>
                    <th>Latency</th>
                    <th>Failure type</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="e in filteredEvents" :key="e.test_id">
                    <td class="cjm-mono">{{ formatTime(e.fired_iso) }}</td>
                    <td>{{ shortPath(e.path_human) }}</td>
                    <td class="cjm-mono">{{ e.backend }}</td>
                    <td>
                      <span class="cjm-outcome-pill" :class="outcomePillClass(e.outcome)">
                        {{ e.outcome }}
                      </span>
                    </td>
                    <td class="cjm-mono">
                      <template v-if="e.total_latency_ms !== null">{{ e.total_latency_ms }}ms</template>
                      <template v-else>—</template>
                    </td>
                    <td class="cjm-mono cjm-text-muted">{{ e.failure_type || '—' }}</td>
                    <td class="cjm-mono cjm-text-muted">
                      {{ failureSummary(e.failure_detail) || '—' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Outcome breakdown tab -->
          <div v-else-if="activeTab === 'outcome'" class="cjm-outcome">
            <div class="cjm-trend-cards">
              <div class="cjm-trend-card">
                <div class="cjm-trend-label">Pass rate 24h</div>
                <div class="cjm-trend-value">{{ passRateLabel }}</div>
                <div class="cjm-trend-sub">{{ status?.summary.passes_24h ?? '—' }} pass · {{ status?.summary.failures_24h ?? '—' }} fail</div>
              </div>
              <div class="cjm-trend-card">
                <div class="cjm-trend-label">Failures by type</div>
                <div class="cjm-trend-failures">
                  <div v-for="(n, ft) in failureBreakdown" :key="ft" class="cjm-trend-failrow">
                    <span class="cjm-trend-failkey">{{ ft }}</span>
                    <span class="cjm-trend-failval">{{ n }}</span>
                  </div>
                  <div v-if="!status" class="cjm-text-muted">—</div>
                  <div v-else-if="Object.keys(failureBreakdown).length === 0" class="cjm-text-muted">no failures in 24h</div>
                </div>
              </div>
            </div>

            <h4 class="cjm-sub-h4">Worst-performing paths (24h)</h4>
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="cjm-empty"><div class="cjm-spinner"></div><p>Loading judge state…</p></div>
            <div v-else-if="worstPaths.length === 0" class="cjm-empty cjm-empty--muted">
              <p>No path has < 100% pass rate.</p>
            </div>
            <table v-else class="cjm-table">
              <thead>
                <tr><th>Path</th><th>Backend</th><th>Pass rate</th><th>Failures</th></tr>
              </thead>
              <tbody>
                <tr v-for="p in worstPaths" :key="p.path_human + ':' + p.backend">
                  <td>{{ p.path_human }}</td>
                  <td class="cjm-mono">{{ p.backend }}</td>
                  <td>
                    <span :class="rateClass(p)">{{ p.pass_rate_24h !== null ? p.pass_rate_24h + '%' : '—' }}</span>
                  </td>
                  <td class="cjm-mono">{{ p.failures_24h }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Latency tab -->
          <div v-else-if="activeTab === 'latency'" class="cjm-latency">
            <p class="cjm-text-muted" style="margin: 0 0 10px 0; font-size: 0.78rem">
              Percentiles computed across <code>passed</code> rows in the last 24h.
              Sort by clicking a column header.
            </p>
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="cjm-empty"><div class="cjm-spinner"></div><p>Loading judge state…</p></div>
            <div v-else class="cjm-table-wrap">
              <table class="cjm-table">
                <thead>
                  <tr>
                    <th @click="sortLatencyBy('path_human')" class="cjm-sortable">Path</th>
                    <th @click="sortLatencyBy('backend')" class="cjm-sortable">Backend</th>
                    <th @click="sortLatencyBy('p50_latency_ms')" class="cjm-sortable">p50</th>
                    <th @click="sortLatencyBy('avg_latency_ms')" class="cjm-sortable">avg</th>
                    <th @click="sortLatencyBy('p95_latency_ms')" class="cjm-sortable">p95</th>
                    <th @click="sortLatencyBy('max_latency_ms')" class="cjm-sortable">max</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in latencyRows" :key="p.path_id + ':' + p.backend">
                    <td>{{ p.path_human }}</td>
                    <td class="cjm-mono">{{ p.backend }}</td>
                    <td class="cjm-mono">{{ p.p50_latency_ms ?? '—' }}ms</td>
                    <td class="cjm-mono">{{ p.avg_latency_ms ?? '—' }}ms</td>
                    <td class="cjm-mono">{{ p.p95_latency_ms ?? '—' }}ms</td>
                    <td class="cjm-mono">{{ p.max_latency_ms ?? '—' }}ms</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- Footer -->
        <div class="cjm-footer">
          <span class="cjm-mono cjm-text-muted">
            GET /admin/canary-judge/*&nbsp;·&nbsp;Auto-refresh: paused on tab-hidden
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
 * CanaryJudgeModal — Tier 3 observability for the canary_judge worker.
 *
 * §pass27 Phase 1 (2026-05-17). Mirrors the §pass26 CrossTegSweeperModal
 * shell idioms (4 stat cards → entity grid → 3 tabs → CSV export → 5s polling).
 * Path × Backend matrix surfaces 30 prod paths (sandbox: 13) with pass-rate
 * color coding. Click a cell to filter the activity feed by path+backend.
 *
 * Backend: /admin/canary-judge/{status,events} (admin_platform gated).
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import dayjs from 'dayjs'
import {
  getCanaryJudgeStatus,
  getCanaryJudgeEvents,
  type CanaryJudgeStatusResponse,
  type CanaryJudgeEvent,
  type CanaryJudgePathStat,
  type CanaryOutcome,
} from '@/services/api/canaryJudge'
import { downloadCsv } from '@/components/common/csvExport'

interface Props {
  workerId?: string
}
const props = withDefaults(defineProps<Props>(), { workerId: 'canary_judge' })

const emit = defineEmits<{ (e: 'close'): void }>()

// ── State ────────────────────────────────────────────────────────────────
const status = ref<CanaryJudgeStatusResponse | null>(null)
const events = ref<CanaryJudgeEvent[]>([])
const loadingStatus = ref(false)
const loadingEvents = ref(false)
const statusError = ref('')
const eventsError = ref('')

const selectedPath = ref<string | null>(null)
const selectedBackend = ref<string | null>(null)
const outcomeFilter = ref<CanaryOutcome | null>(null)
const activeTab = ref<'activity' | 'outcome' | 'latency'>('activity')
const autoRefresh = ref(true)

const latencySortKey = ref<keyof CanaryJudgePathStat>('p95_latency_ms')
const latencySortDir = ref<'asc' | 'desc'>('desc')

let refreshInterval: number | null = null

const tabs: { id: 'activity' | 'outcome' | 'latency'; label: string }[] = [
  { id: 'activity', label: 'Recent Activity' },
  { id: 'outcome',  label: 'Outcome Breakdown' },
  { id: 'latency',  label: 'Latency' },
]

// ── Derived ──────────────────────────────────────────────────────────────
const hasFailures = computed(() => (status.value?.summary.failures_24h ?? 0) > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'cjm-status-dot--bad'
  if (!status.value) return 'cjm-status-dot--muted'
  const rate = status.value.summary.pass_rate_24h
  if (rate === null) return 'cjm-status-dot--muted'
  if (rate < 90) return 'cjm-status-dot--bad'
  if (rate < 97) return 'cjm-status-dot--warn'
  return 'cjm-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  const rate = status.value.summary.pass_rate_24h
  if (rate === null) return 'No data yet'
  return `${rate}% pass rate (24h)`
})

const passRateLabel = computed(() => {
  const r = status.value?.summary.pass_rate_24h
  return r === null || r === undefined ? '—' : r.toFixed(1) + '%'
})

const failureBreakdown = computed(() => status.value?.by_failure_type || {})

const worstPaths = computed(() => {
  if (!status.value) return []
  return status.value.per_path
    .filter(p => p.pass_rate_24h !== null && p.pass_rate_24h < 100 && (p.passes_24h + p.failures_24h) > 0)
    .sort((a, b) => (a.pass_rate_24h ?? 100) - (b.pass_rate_24h ?? 100))
    .slice(0, 8)
})

const latencyRows = computed(() => {
  if (!status.value) return []
  const list = [...status.value.per_path]
  const k = latencySortKey.value
  const dir = latencySortDir.value === 'asc' ? 1 : -1
  list.sort((a, b) => {
    const av = (a[k] ?? -Infinity) as number | string
    const bv = (b[k] ?? -Infinity) as number | string
    if (av === bv) return 0
    return av < bv ? -1 * dir : 1 * dir
  })
  return list
})

const filteredEvents = computed(() => {
  let list = events.value
  if (selectedPath.value) list = list.filter(e => e.path_human === selectedPath.value)
  if (selectedBackend.value) list = list.filter(e => e.backend === selectedBackend.value)
  if (outcomeFilter.value) list = list.filter(e => e.outcome === outcomeFilter.value)
  return list
})

function sortLatencyBy(k: keyof CanaryJudgePathStat) {
  if (latencySortKey.value === k) {
    latencySortDir.value = latencySortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    latencySortKey.value = k
    latencySortDir.value = 'desc'
  }
}

// ── Loaders ──────────────────────────────────────────────────────────────
async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getCanaryJudgeStatus()
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
    const resp = await getCanaryJudgeEvents({
      path: selectedPath.value || undefined,
      backend: selectedBackend.value || undefined,
      outcome: outcomeFilter.value || undefined,
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

watch([selectedPath, selectedBackend, outcomeFilter], () => { loadEvents() })

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
  if (refreshInterval !== null) { clearInterval(refreshInterval); refreshInterval = null }
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
function shortPath(s: string): string {
  // path_human is like "registry-a→tokyo:async". Keep as is — fits.
  return s
}
function cellClass(p: CanaryJudgePathStat) {
  const active = selectedPath.value === p.path_human && selectedBackend.value === p.backend
  return {
    'cjm-matrix-cell--active': active,
    'cjm-matrix-cell--bad':    p.pass_rate_24h !== null && p.pass_rate_24h < 90,
    'cjm-matrix-cell--warn':   p.pass_rate_24h !== null && p.pass_rate_24h >= 90 && p.pass_rate_24h < 97,
    'cjm-matrix-cell--ok':     p.pass_rate_24h !== null && p.pass_rate_24h >= 97,
    'cjm-matrix-cell--idle':   p.pass_rate_24h === null,
  }
}
function cellDotClass(p: CanaryJudgePathStat) {
  if (p.pass_rate_24h === null) return 'cjm-cell-dot--muted'
  if (p.pass_rate_24h < 90) return 'cjm-cell-dot--bad'
  if (p.pass_rate_24h < 97) return 'cjm-cell-dot--warn'
  return 'cjm-cell-dot--ok'
}
function rateClass(p: CanaryJudgePathStat) {
  if (p.pass_rate_24h === null) return 'cjm-text-muted'
  if (p.pass_rate_24h < 90) return 'cjm-text-bad'
  if (p.pass_rate_24h < 97) return 'cjm-text-warn'
  return 'cjm-text-ok'
}
function outcomePillClass(outcome: string) {
  return {
    'cjm-outcome-pill--pass': outcome === 'passed',
    'cjm-outcome-pill--fail': outcome === 'failed',
    'cjm-outcome-pill--fire': outcome === 'fired',
  }
}
function failureSummary(d: Record<string, unknown> | null | undefined): string {
  if (!d) return ''
  const elapsed = d.elapsed_sec
  const missing = d.missing_events
  if (Array.isArray(missing)) return `missing: ${missing.join(', ')}`
  if (typeof elapsed === 'number') return `elapsed: ${Math.round(elapsed)}s`
  const reason = d.reason
  if (typeof reason === 'string') return reason
  return JSON.stringify(d).slice(0, 60)
}

function exportCsv() {
  const filename = `canary-judge-${dayjs().format('YYYY-MM-DD-HHmm')}.csv`
  downloadCsv<CanaryJudgeEvent>(
    filteredEvents.value,
    [
      { label: 'fired_iso',        value: e => e.fired_iso || '' },
      { label: 'completed_iso',    value: e => e.completed_iso || '' },
      { label: 'path_human',       value: e => e.path_human },
      { label: 'backend',          value: e => e.backend },
      { label: 'outcome',          value: e => String(e.outcome) },
      { label: 'http_status',      value: e => e.http_status?.toString() ?? '' },
      { label: 'http_latency_ms',  value: e => e.http_latency_ms?.toString() ?? '' },
      { label: 'total_latency_ms', value: e => e.total_latency_ms?.toString() ?? '' },
      { label: 'failure_type',     value: e => e.failure_type || '' },
      { label: 'transfer_id',      value: e => e.transfer_id || '' },
      { label: 'sender_did',       value: e => e.sender_did },
      { label: 'receiver_did',     value: e => e.receiver_did },
      { label: 'amount',           value: e => e.amount || '' },
      { label: 'test_id',          value: e => e.test_id },
    ],
    filename,
  )
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.cjm-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.cjm-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.cjm-modal--errors {
  border-color: rgba(239, 68, 68, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(239, 68, 68, 0.2);
}

/* Header */
.cjm-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.cjm-header-left { display: flex; align-items: center; gap: 10px; }
.cjm-header-right { display: flex; align-items: center; gap: 8px; }
.cjm-title { font-size: 1.05rem; margin: 0; font-weight: 600; letter-spacing: 0.01em; }
.cjm-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.cjm-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }

.cjm-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.cjm-status-dot--ok   { background: #10b981; color: #10b981; }
.cjm-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.cjm-status-dot--bad  { background: #ef4444; color: #ef4444; animation: cjm-pulse 1.8s infinite; }
.cjm-status-dot--muted { background: #4b5563; color: #4b5563; }

@keyframes cjm-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

/* Buttons */
.cjm-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  transition: background 0.15s, border-color 0.15s;
}
.cjm-btn:hover:not(:disabled) {
  background: rgba(0, 210, 210, 0.08);
  border-color: rgba(0, 210, 210, 0.45);
}
.cjm-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.cjm-btn--ghost { background: transparent; }
.cjm-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.cjm-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

/* Stats row */
.cjm-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.cjm-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.cjm-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.cjm-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.cjm-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.cjm-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.cjm-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

/* Sections */
.cjm-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.cjm-section:last-of-type { border-bottom: none; }
.cjm-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.cjm-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

/* Matrix */
.cjm-matrix-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}
.cjm-matrix-cell {
  background: rgba(0, 210, 210, 0.02);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  border-radius: 8px;
  padding: 10px;
  text-align: left;
  cursor: pointer;
  color: inherit;
  transition: background 0.15s, border-color 0.15s, transform 0.15s;
}
.cjm-matrix-cell:hover { background: rgba(0, 210, 210, 0.06); transform: translateY(-1px); }
.cjm-matrix-cell--active { border-color: var(--nc-primary, #00d2d2); background: rgba(0, 210, 210, 0.10); }
.cjm-matrix-cell--bad  { border-color: rgba(239, 68, 68, 0.55); }
.cjm-matrix-cell--warn { border-color: rgba(245, 158, 11, 0.45); }
.cjm-matrix-cell--ok   { border-color: rgba(16, 185, 129, 0.30); }
.cjm-matrix-cell--idle { opacity: 0.7; }
.cjm-cell-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.cjm-cell-dot { width: 8px; height: 8px; border-radius: 50%; }
.cjm-cell-dot--ok   { background: #10b981; box-shadow: 0 0 4px #10b981; }
.cjm-cell-dot--warn { background: #f59e0b; box-shadow: 0 0 4px #f59e0b; }
.cjm-cell-dot--bad  { background: #ef4444; box-shadow: 0 0 4px #ef4444; }
.cjm-cell-dot--muted { background: #4b5563; }
.cjm-cell-name { font-weight: 600; font-size: 0.78rem; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cjm-cell-body { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 4px 0; }
.cjm-cell-rate { font-size: 1.05rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.cjm-cell-sub  { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.cjm-cell-foot { padding-top: 6px; border-top: 1px solid rgba(0, 210, 210, 0.08); }
.cjm-filter-hint {
  margin: 10px 0 0 0;
  font-size: 0.75rem;
  color: var(--nc-muted, #94a3b8);
}

/* Tabs */
.cjm-tabs {
  display: flex;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  margin: -6px -20px 12px -20px;
  padding: 0 20px;
  align-items: center;
}
.cjm-tabs-right { margin-left: auto; padding-bottom: 6px; }
.cjm-tab {
  background: transparent; border: none; color: var(--nc-muted, #94a3b8);
  padding: 8px 14px; cursor: pointer; font-size: 0.8rem;
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
}
.cjm-tab:hover { color: var(--nc-text, #e2e8f0); }
.cjm-tab--active { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }

/* Chip row */
.cjm-chip-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.cjm-chip {
  padding: 4px 10px; font-size: 0.72rem; border-radius: 12px;
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  color: var(--nc-text, #e2e8f0); cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.cjm-chip:hover { background: rgba(0, 210, 210, 0.12); }
.cjm-chip--active {
  background: rgba(0, 210, 210, 0.18);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}

/* Table */
.cjm-table-wrap { overflow-x: auto; }
.cjm-table {
  width: 100%; border-collapse: collapse; font-size: 0.78rem;
}
.cjm-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.cjm-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.cjm-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }
.cjm-sortable { cursor: pointer; user-select: none; }
.cjm-sortable:hover { color: var(--nc-primary, #00d2d2); }

.cjm-outcome-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.cjm-outcome-pill--pass { background: rgba(16, 185, 129, 0.16); color: #34d399; }
.cjm-outcome-pill--fail { background: rgba(239, 68, 68, 0.18); color: #f87171; }
.cjm-outcome-pill--fire { background: rgba(99, 102, 241, 0.18); color: #a5b4fc; }

/* Outcome tab */
.cjm-trend-cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  margin-bottom: 18px;
}
.cjm-trend-card {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  border-radius: 8px; padding: 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.cjm-trend-label { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.cjm-trend-value { font-size: 1.7rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.cjm-trend-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }
.cjm-trend-failures { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.cjm-trend-failrow { display: flex; justify-content: space-between; font-size: 0.82rem; }
.cjm-trend-failkey { color: var(--nc-text, #e2e8f0); }
.cjm-trend-failval { font-variant-numeric: tabular-nums; font-weight: 600; }
.cjm-sub-h4 { font-size: 0.82rem; margin: 10px 0 8px 0; font-weight: 600; }

/* Empty/loading */
.cjm-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.cjm-empty--muted { color: var(--nc-muted, #94a3b8); font-size: 0.82rem; }
.cjm-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: cjm-spin 0.8s linear infinite;
}
@keyframes cjm-spin { to { transform: rotate(360deg); } }

/* Banner */
.cjm-banner {
  padding: 10px 14px; border-radius: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px;
}
.cjm-banner--bad {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

/* Text utilities */
.cjm-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.cjm-text-muted { color: var(--nc-muted, #94a3b8); }
.cjm-text-warn  { color: #fbbf24; }
.cjm-text-bad   { color: #f87171; }
.cjm-text-ok    { color: #34d399; }

/* Footer */
.cjm-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .cjm-stats-row { grid-template-columns: repeat(2, 1fr); }
  .cjm-modal { max-height: 92vh; }
}

@media (prefers-reduced-motion: reduce) {
  .cjm-status-dot--bad { animation: none; }
  .cjm-matrix-cell { transition: none; }
}
</style>
