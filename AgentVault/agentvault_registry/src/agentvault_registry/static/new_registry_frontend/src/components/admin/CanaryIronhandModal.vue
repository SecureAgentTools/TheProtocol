<template>
  <Teleport to="body">
    <div
      class="cim-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cim-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="cim-modal" :class="{ 'cim-modal--errors': hasFailures }">
        <!-- Header -->
        <div class="cim-header">
          <div class="cim-header-left">
            <span class="cim-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="cim-modal-title" class="cim-title">Canary IRONHAND mTLS</h2>
            <span class="cim-subtitle">{{ workerId }}</span>
          </div>
          <div class="cim-header-right">
            <span v-if="status?.snapshot_iso" class="cim-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="cim-btn cim-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingEvents">
              <span class="cim-live-dot" :class="{ 'cim-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="cim-btn cim-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="cim-stats-row">
          <div class="cim-stat">
            <span class="cim-stat-label">Active paths</span>
            <span class="cim-stat-value">{{ status?.summary.active_paths ?? '—' }}</span>
            <span class="cim-stat-sub">ironhand_mtls only</span>
          </div>
          <div class="cim-stat" :class="passRateStatClass">
            <span class="cim-stat-label">Pass rate 24h</span>
            <span class="cim-stat-value">{{ passRateLabel }}</span>
            <span class="cim-stat-sub">
              {{ status?.summary.passes_24h ?? '—' }} pass · {{ status?.summary.failures_24h ?? '—' }} fail
            </span>
          </div>
          <div class="cim-stat" :class="{ 'cim-stat--bad': (status?.summary.failures_24h ?? 0) > 0 }">
            <span class="cim-stat-label">Failures 24h</span>
            <span class="cim-stat-value">{{ status?.summary.failures_24h ?? '—' }}</span>
            <span class="cim-stat-sub">paged on rate>0</span>
          </div>
          <div class="cim-stat" :class="{ 'cim-stat--warn': (status?.summary.revocation_p95_propagation_ms ?? 0) > 60000 }">
            <span class="cim-stat-label">Revoc p95</span>
            <span class="cim-stat-value">
              <template v-if="status?.summary.revocation_p95_propagation_ms != null">
                {{ status.summary.revocation_p95_propagation_ms }}ms
              </template>
              <template v-else>—</template>
            </span>
            <span class="cim-stat-sub">block latency</span>
          </div>
        </div>

        <!-- Tabs -->
        <section class="cim-section">
          <div class="cim-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              class="cim-tab"
              :class="{ 'cim-tab--active': activeTab === tab.id }"
              type="button"
              @click="activeTab = tab.id"
            >
              {{ tab.label }}
            </button>
            <div class="cim-tabs-right">
              <button class="cim-btn cim-btn--ghost" @click="exportCsv" :disabled="filteredEvents.length === 0 && activeTab === 'activity'">
                ⇩ CSV
              </button>
            </div>
          </div>

          <!-- Path scoreboard tab -->
          <div v-if="activeTab === 'paths'" class="cim-paths">
            <div v-if="loadingStatus && !status" class="cim-empty">
              <div class="cim-spinner"></div>
              <p>Querying Prometheus + canary_test_results…</p>
            </div>
            <div v-else-if="statusError" class="cim-banner cim-banner--bad">
              <Icon name="mdi:alert" /> {{ statusError }}
              <button class="cim-btn cim-btn--ghost" @click="loadStatus">Retry</button>
            </div>
            <div v-else-if="status && status.per_path.length === 0" class="cim-empty cim-empty--muted">
              <p>No ironhand_mtls paths configured.</p>
              <p class="cim-text-muted">Insert canary_paths rows with transport='ironhand_mtls' and spawn workload containers.</p>
            </div>
            <div v-else-if="status" class="cim-table-wrap">
              <table class="cim-table">
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>Sender DID</th>
                    <th>Pass rate 24h</th>
                    <th>Passes</th>
                    <th>Failures</th>
                    <th>p50 latency</th>
                    <th>p95 latency</th>
                    <th>Active</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in status.per_path" :key="p.path_id" @click="selectPath(p.path_id)" :class="{ 'cim-row--selected': selectedPath === p.path_id }">
                    <td class="cim-mono">{{ p.path_id }}</td>
                    <td class="cim-mono cim-text-muted" :title="p.sender_did">{{ shortDid(p.sender_did) }}</td>
                    <td>
                      <span class="cim-rate" :class="rateClass(p.pass_rate_24h)">
                        {{ p.pass_rate_24h !== null ? p.pass_rate_24h + '%' : '—' }}
                      </span>
                    </td>
                    <td class="cim-mono">{{ p.passes_24h }}</td>
                    <td class="cim-mono" :class="{ 'cim-text-bad': p.failures_24h > 0 }">{{ p.failures_24h }}</td>
                    <td class="cim-mono">{{ p.p50_latency_ms ?? '—' }}{{ p.p50_latency_ms !== null ? 'ms' : '' }}</td>
                    <td class="cim-mono">{{ p.p95_latency_ms ?? '—' }}{{ p.p95_latency_ms !== null ? 'ms' : '' }}</td>
                    <td>
                      <span class="cim-pill" :class="p.is_active ? 'cim-pill--ok' : 'cim-pill--muted'">
                        {{ p.is_active ? 'active' : 'inactive' }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <p v-if="selectedPath" class="cim-filter-hint">
                Filtering activity by <strong>{{ selectedPath }}</strong> — click the row again to clear.
              </p>
            </div>
          </div>

          <!-- Failure breakdown tab -->
          <div v-else-if="activeTab === 'failures'" class="cim-failures">
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="cim-empty"><div class="cim-spinner"></div><p>Querying Prometheus + canary_test_results…</p></div>
            <div v-else-if="Object.keys(status.by_failure_type).length === 0" class="cim-empty cim-empty--muted">
              <p>No failures in the last 24h. <span class="cim-text-muted">Fleet healthy.</span></p>
            </div>
            <div v-else>
              <table class="cim-table">
                <thead>
                  <tr>
                    <th>Failure type</th>
                    <th>Count 24h</th>
                    <th>Severity</th>
                    <th>Diagnostic hint</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(count, ft) in status.by_failure_type" :key="ft">
                    <td class="cim-mono">{{ ft }}</td>
                    <td class="cim-mono cim-text-bad">{{ count }}</td>
                    <td>
                      <span class="cim-pill cim-pill--bad">{{ failureSeverity(String(ft)) }}</span>
                    </td>
                    <td class="cim-text-muted">{{ failureHint(String(ft)) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Activity tab -->
          <div v-else-if="activeTab === 'activity'" class="cim-activity">
            <div class="cim-chip-row">
              <button class="cim-chip" :class="{ 'cim-chip--active': outcomeFilter === null }" @click="outcomeFilter = null">All</button>
              <button class="cim-chip" :class="{ 'cim-chip--active': outcomeFilter === 'ok' }" @click="outcomeFilter = 'ok'">OK</button>
              <button class="cim-chip" :class="{ 'cim-chip--active': outcomeFilter === 'failure' }" @click="outcomeFilter = 'failure'">Failure</button>
            </div>
            <div v-if="loadingEvents && filteredEvents.length === 0" class="cim-empty">
              <div class="cim-spinner"></div>
              <p>Loading recent fires…</p>
            </div>
            <div v-else-if="eventsError" class="cim-banner cim-banner--bad">
              <Icon name="mdi:alert" /> {{ eventsError }}
              <button class="cim-btn cim-btn--ghost" @click="loadEvents">Retry</button>
            </div>
            <div v-else-if="filteredEvents.length === 0" class="cim-empty cim-empty--muted">
              <p v-if="selectedPath || outcomeFilter">No fires match the current filter.</p>
              <p v-else>No ironhand_mtls fires yet — dispatch branch may not have run.</p>
            </div>
            <div v-else class="cim-table-wrap">
              <table class="cim-table">
                <thead>
                  <tr>
                    <th>Fired</th>
                    <th>Path</th>
                    <th>HTTP</th>
                    <th>Latency</th>
                    <th>Transfer ID</th>
                    <th>Failure type</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="e in filteredEvents" :key="e.test_id" :class="{ 'cim-row--bad': e.failure_type }">
                    <td class="cim-mono">{{ formatTime(e.fired_iso) }}</td>
                    <td class="cim-mono">{{ e.path_human }}</td>
                    <td class="cim-mono" :class="httpStatusClass(e.http_status)">{{ e.http_status ?? '—' }}</td>
                    <td class="cim-mono">{{ e.http_latency_ms !== null ? e.http_latency_ms + 'ms' : '—' }}</td>
                    <td class="cim-mono cim-text-muted" :title="e.transfer_id || ''">
                      {{ e.transfer_id ? e.transfer_id.slice(0, 12) + '…' : '—' }}
                    </td>
                    <td class="cim-mono cim-text-bad">{{ e.failure_type || '—' }}</td>
                    <td class="cim-mono cim-text-muted">
                      {{ failureSummary(e.failure_detail) || '—' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import Icon from '@/components/Icon.vue'
/**
 * CanaryIronhandModal — Tier 3 observability for canary IRONHAND mTLS (§pass30).
 *
 * Pattern A (per-agent SVID via Workload API + workload container per canary).
 * Mirrors §pass27/28/29 worker-modal shell idioms. Tabs:
 *   - Path scoreboard (per-path stats)
 *   - Failure breakdown (by failure_type)
 *   - Recent activity (canary_test_results WHERE transport='ironhand_mtls')
 *
 * Backend: /admin/canary-ironhand/{status,events} (admin_platform gated).
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import dayjs from 'dayjs'
import {
  getCanaryIronhandStatus,
  getCanaryIronhandEvents,
  type CanaryIronhandStatusResponse,
  type CanaryIronhandEvent,
} from '@/services/api/canaryIronhand'
import { downloadCsv } from '@/components/common/csvExport'

interface Props {
  workerId?: string
}
const props = withDefaults(defineProps<Props>(), { workerId: 'canary_ironhand' })
const emit = defineEmits<{ (e: 'close'): void }>()

// State
const status = ref<CanaryIronhandStatusResponse | null>(null)
const events = ref<CanaryIronhandEvent[]>([])
const loadingStatus = ref(false)
const loadingEvents = ref(false)
const statusError = ref('')
const eventsError = ref('')
const selectedPath = ref<string | null>(null)
const outcomeFilter = ref<string | null>(null)
const activeTab = ref<'paths' | 'failures' | 'activity'>('paths')
const autoRefresh = ref(true)
let refreshInterval: number | null = null

const tabs: { id: 'paths' | 'failures' | 'activity'; label: string }[] = [
  { id: 'paths',    label: 'Path Scoreboard' },
  { id: 'failures', label: 'Failure Breakdown' },
  { id: 'activity', label: 'Recent Activity' },
]

// Derived
const hasFailures = computed(() => (status.value?.summary.failures_24h ?? 0) > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'cim-status-dot--bad'
  if (!status.value) return 'cim-status-dot--muted'
  const rate = status.value.summary.pass_rate_24h
  if (rate === null) return 'cim-status-dot--muted'
  if (rate < 90) return 'cim-status-dot--bad'
  if (rate < 97) return 'cim-status-dot--warn'
  return 'cim-status-dot--ok'
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

const passRateStatClass = computed(() => {
  const r = status.value?.summary.pass_rate_24h
  if (r === null || r === undefined) return ''
  if (r < 90) return 'cim-stat--bad'
  if (r < 97) return 'cim-stat--warn'
  return ''
})

const filteredEvents = computed(() => {
  let list = events.value
  if (selectedPath.value) list = list.filter(e => e.path_human === selectedPath.value)
  if (outcomeFilter.value === 'ok') list = list.filter(e => !e.failure_type)
  if (outcomeFilter.value === 'failure') list = list.filter(e => !!e.failure_type)
  return list
})

// Helpers
function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).format('HH:mm:ss')
}

function shortDid(did: string): string {
  return did.length > 36 ? did.slice(0, 24) + '…' + did.slice(-8) : did
}

function rateClass(rate: number | null): string {
  if (rate === null) return 'cim-text-muted'
  if (rate < 90) return 'cim-text-bad'
  if (rate < 97) return 'cim-text-warn'
  return 'cim-text-ok'
}

function httpStatusClass(status: number | null): string {
  if (status === null) return 'cim-text-muted'
  if (status >= 500) return 'cim-text-bad'
  if (status >= 400) return 'cim-text-warn'
  if (status >= 200 && status < 300) return 'cim-text-ok'
  return ''
}

function failureSummary(detail: Record<string, unknown> | null): string {
  if (!detail) return ''
  const reason = (detail as any).reason
  if (reason) return String(reason).slice(0, 80)
  return JSON.stringify(detail).slice(0, 80)
}

function failureSeverity(failureType: string): string {
  if (['ironhand_svid_fetch', 'ironhand_tls_handshake'].includes(failureType)) return 'P0'
  if (['ironhand_jwt_mint', 'ironhand_no_response'].includes(failureType)) return 'P1'
  return 'P2'
}

function failureHint(failureType: string): string {
  switch (failureType) {
    case 'ironhand_svid_fetch':
      return 'SPIRE Workload API attestation broken. Check container labels + SPIRE entry selectors.'
    case 'ironhand_tls_handshake':
      return 'TLS handshake failed. Check trust bundle + federated CAs.'
    case 'ironhand_jwt_mint':
      return 'Auth endpoint unavailable or agent credentials wrong.'
    case 'ironhand_no_response':
      return 'Workload container crashed or Redis network gap.'
    case 'ironhand_http_4xx':
      return 'Server rejected the request. Validation error.'
    case 'ironhand_http_5xx':
      return 'Server-side regression.'
    case 'ironhand_timeout':
      return 'Request took longer than 15s. Backend slow.'
    default:
      return ''
  }
}

function selectPath(pathId: string) {
  if (selectedPath.value === pathId) {
    selectedPath.value = null
  } else {
    selectedPath.value = pathId
    activeTab.value = 'activity'
  }
}

// Loaders
async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getCanaryIronhandStatus()
  } catch (e: any) {
    statusError.value = e?.message || String(e)
  } finally {
    loadingStatus.value = false
  }
}

async function loadEvents() {
  if (loadingEvents.value) return
  loadingEvents.value = true
  try {
    eventsError.value = ''
    const opts: { path?: string; outcome?: string; limit: number } = { limit: 100 }
    if (selectedPath.value) opts.path = selectedPath.value
    if (outcomeFilter.value) opts.outcome = outcomeFilter.value
    const r = await getCanaryIronhandEvents(opts)
    events.value = r.events
  } catch (e: any) {
    eventsError.value = e?.message || String(e)
  } finally {
    loadingEvents.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadStatus(), loadEvents()])
}

function exportCsv() {
  if (activeTab.value === 'activity') {
    const rows = filteredEvents.value.map(e => ({
      fired_iso: e.fired_iso,
      path: e.path_human,
      http_status: e.http_status,
      http_latency_ms: e.http_latency_ms,
      transfer_id: e.transfer_id,
      failure_type: e.failure_type,
      failure_detail: failureSummary(e.failure_detail),
      sender_did: e.sender_did,
      receiver_did: e.receiver_did,
      amount: e.amount,
    }))
    downloadCsv(`canary-ironhand-activity-${dayjs().format('YYYY-MM-DD-HHmmss')}.csv`, rows)
  } else if (activeTab.value === 'paths' && status.value) {
    downloadCsv(`canary-ironhand-paths-${dayjs().format('YYYY-MM-DD-HHmmss')}.csv`, status.value.per_path)
  } else if (activeTab.value === 'failures' && status.value) {
    const rows = Object.entries(status.value.by_failure_type).map(([type, count]) => ({
      failure_type: type,
      count_24h: count,
      severity: failureSeverity(type),
      hint: failureHint(type),
    }))
    downloadCsv(`canary-ironhand-failures-${dayjs().format('YYYY-MM-DD-HHmmss')}.csv`, rows)
  }
}

// Lifecycle
onMounted(() => {
  refreshAll()
  if (autoRefresh.value) {
    refreshInterval = window.setInterval(() => {
      if (document.visibilityState === 'visible') refreshAll()
    }, 5000)
  }
})

onBeforeUnmount(() => {
  if (refreshInterval !== null) {
    window.clearInterval(refreshInterval)
    refreshInterval = null
  }
})

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.cim-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.85);
  z-index: 9999; display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.cim-modal {
  background: #0a0e14; color: #cce0ff; border: 1px solid #1a2540;
  border-radius: 6px; box-shadow: 0 0 40px rgba(0,255,255,0.15);
  width: min(1400px, 95vw); max-height: 90vh; overflow: hidden;
  display: flex; flex-direction: column;
  font-family: 'JetBrains Mono', monospace; font-size: 13px;
}
.cim-modal--errors { border-color: #ff5050; box-shadow: 0 0 40px rgba(255,80,80,0.25); }
.cim-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid #1a2540;
}
.cim-header-left, .cim-header-right { display: flex; align-items: center; gap: 10px; }
.cim-title { margin: 0; font-size: 16px; color: var(--cyan, #00ffff); }
.cim-subtitle { color: #607894; font-size: 11px; }
.cim-last-snap { color: #607894; font-size: 11px; }
.cim-status-dot {
  display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  background: #607894;
}
.cim-status-dot--ok { background: #00ff80; box-shadow: 0 0 6px #00ff80; }
.cim-status-dot--warn { background: #ffaa00; box-shadow: 0 0 6px #ffaa00; }
.cim-status-dot--bad { background: #ff5050; box-shadow: 0 0 6px #ff5050; }
.cim-live-dot {
  display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: #607894; margin-right: 5px;
}
.cim-live-dot--on { background: var(--cyan, #00ffff); box-shadow: 0 0 4px var(--cyan, #00ffff); }
.cim-btn {
  background: transparent; border: 1px solid #1a2540; color: #cce0ff;
  padding: 6px 10px; cursor: pointer; font: inherit; border-radius: 3px;
}
.cim-btn--ghost:hover { background: #1a2540; }
.cim-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.cim-stats-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
  padding: 12px 16px; border-bottom: 1px solid #1a2540;
}
.cim-stat {
  background: #0d1420; border: 1px solid #1a2540; padding: 10px;
  border-radius: 4px; display: flex; flex-direction: column; gap: 2px;
}
.cim-stat--warn { border-color: #ffaa00; background: rgba(255,170,0,0.05); }
.cim-stat--bad { border-color: #ff5050; background: rgba(255,80,80,0.05); }
.cim-stat-label { color: #607894; font-size: 11px; text-transform: uppercase; }
.cim-stat-value { font-size: 22px; color: var(--cyan, #00ffff); }
.cim-stat-sub { color: #607894; font-size: 10px; }
.cim-section { padding: 12px 16px; overflow-y: auto; flex: 1; }
.cim-tabs {
  display: flex; gap: 4px; border-bottom: 1px solid #1a2540;
  margin-bottom: 12px; align-items: center;
}
.cim-tab {
  background: transparent; border: 1px solid #1a2540; border-bottom: none;
  color: #607894; padding: 6px 12px; cursor: pointer; font: inherit;
  border-radius: 3px 3px 0 0;
}
.cim-tab--active { background: #0d1420; color: var(--cyan, #00ffff); border-color: #2a3a5a; }
.cim-tab:hover { color: #cce0ff; }
.cim-tabs-right { margin-left: auto; }
.cim-table-wrap { overflow-x: auto; }
.cim-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.cim-table th, .cim-table td {
  text-align: left; padding: 6px 10px; border-bottom: 1px solid #131a2a;
}
.cim-table th { color: #607894; background: #0d1420; font-weight: 600; }
.cim-table tbody tr:hover { background: #0d1420; cursor: pointer; }
.cim-row--selected { background: rgba(0,255,255,0.06) !important; }
.cim-row--bad { background: rgba(255,80,80,0.04); }
.cim-mono { font-family: 'JetBrains Mono', monospace; }
.cim-text-muted { color: #607894; }
.cim-text-bad { color: #ff5050; }
.cim-text-warn { color: #ffaa00; }
.cim-text-ok { color: #00ff80; }
.cim-rate { font-weight: 600; }
.cim-empty {
  text-align: center; padding: 30px; color: #607894;
}
.cim-empty--muted { color: #4a5a78; }
.cim-spinner {
  width: 20px; height: 20px; border: 2px solid #1a2540;
  border-top-color: var(--cyan, #00ffff); border-radius: 50%;
  animation: cim-spin 0.8s linear infinite; margin: 0 auto 10px;
}
@keyframes cim-spin { to { transform: rotate(360deg); } }
.cim-banner {
  padding: 12px; border-radius: 4px; display: flex; gap: 10px; align-items: center;
  margin-bottom: 12px;
}
.cim-banner--bad { background: rgba(255,80,80,0.1); border: 1px solid #ff5050; }
.cim-pill {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 600;
}
.cim-pill--ok { background: rgba(0,255,128,0.15); color: #00ff80; }
.cim-pill--bad { background: rgba(255,80,80,0.15); color: #ff5050; }
.cim-pill--muted { background: #1a2540; color: #607894; }
.cim-chip-row { display: flex; gap: 6px; margin-bottom: 10px; }
.cim-chip {
  background: transparent; border: 1px solid #1a2540; color: #607894;
  padding: 4px 10px; cursor: pointer; font: inherit; border-radius: 12px;
}
.cim-chip--active { background: var(--cyan, #00ffff); color: #0a0e14; border-color: var(--cyan, #00ffff); }
.cim-chip:hover { color: #cce0ff; }
.cim-filter-hint {
  margin-top: 8px; padding: 6px 10px;
  background: rgba(0,255,255,0.05); border: 1px solid #1a2540; border-radius: 3px;
  color: #607894; font-size: 11px;
}
</style>
