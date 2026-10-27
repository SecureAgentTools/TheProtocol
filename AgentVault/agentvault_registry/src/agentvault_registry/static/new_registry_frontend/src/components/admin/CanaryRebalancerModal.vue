<template>
  <Teleport to="body">
    <div
      class="crm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="crm-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="crm-modal" :class="{ 'crm-modal--errors': hasErrors }">
        <!-- Header -->
        <div class="crm-header">
          <div class="crm-header-left">
            <span class="crm-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="crm-modal-title" class="crm-title">Canary Rebalancer</h2>
            <span class="crm-subtitle">{{ workerId }}</span>
          </div>
          <div class="crm-header-right">
            <span v-if="status?.snapshot_iso" class="crm-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="crm-btn crm-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingEvents">
              <span class="crm-live-dot" :class="{ 'crm-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="crm-btn crm-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="crm-stats-row">
          <div class="crm-stat">
            <span class="crm-stat-label">Cycles 24h</span>
            <span class="crm-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="crm-stat-sub">every {{ status?.config.interval_sec ?? '—' }}s</span>
          </div>
          <div class="crm-stat" :class="{ 'crm-stat--warn': (status?.summary.funded_24h ?? 0) > 0 }">
            <span class="crm-stat-label">Funded 24h</span>
            <span class="crm-stat-value">{{ status?.summary.funded_24h ?? '—' }}</span>
            <span class="crm-stat-sub">agents refunded</span>
          </div>
          <div class="crm-stat">
            <span class="crm-stat-label">Disbursed 24h</span>
            <span class="crm-stat-value">{{ formatAvt(status?.summary.avt_disbursed_24h) }}</span>
            <span class="crm-stat-sub">{{ localCurrency }}</span>
          </div>
          <div class="crm-stat" :class="{ 'crm-stat--bad': (status?.summary.errors_24h ?? 0) > 0 }">
            <span class="crm-stat-label">Errors 24h</span>
            <span class="crm-stat-value">{{ status?.summary.errors_24h ?? '—' }}</span>
            <span class="crm-stat-sub">{{ !status ? '—' : (status.summary.errors_24h ?? 0) === 0 ? 'all healthy' : 'investigate' }}</span>
          </div>
        </div>

        <!-- Config rail -->
        <section v-if="status?.config" class="crm-section crm-config-row">
          <div class="crm-cfg-pair"><span class="crm-cfg-key">FLOOR</span><span class="crm-cfg-val">{{ formatAvt(status.config.floor_avt) }} {{ localCurrency }}</span></div>
          <div class="crm-cfg-pair"><span class="crm-cfg-key">TOPUP</span><span class="crm-cfg-val">{{ formatAvt(status.config.topup_avt) }} {{ localCurrency }}</span></div>
          <div class="crm-cfg-pair"><span class="crm-cfg-key">COOLDOWN</span><span class="crm-cfg-val">{{ status.config.min_interval_sec }}s</span></div>
          <div class="crm-cfg-pair"><span class="crm-cfg-key">OP CREDS</span><span class="crm-cfg-val">{{ status.config.op_creds_count }}</span></div>
          <div class="crm-cfg-pair"><span class="crm-cfg-key">WORKER</span>
            <span class="crm-cfg-val" :class="status.config.enabled ? 'crm-text-ok' : 'crm-text-warn'">
              {{ status.config.enabled ? 'ENABLED' : 'DISABLED' }}
            </span>
          </div>
          <div class="crm-cfg-pair"><span class="crm-cfg-key">UNDER FLOOR</span>
            <span class="crm-cfg-val" :class="status.summary.agents_under_floor > 0 ? 'crm-text-warn' : 'crm-text-ok'">
              {{ status.summary.agents_under_floor }} / {{ status.summary.agents_active }}
            </span>
          </div>
        </section>

        <!-- Per-agent table -->
        <section class="crm-section">
          <h3 class="crm-section-title">
            Canary Agents
            <span class="crm-section-sub">{{ status?.per_agent.length ?? '—' }} active · click row to filter activity</span>
          </h3>
          <div v-if="loadingStatus && !status" class="crm-empty">
            <div class="crm-spinner"></div>
            <p>Loading agent state…</p>
          </div>
          <div v-else-if="statusError" class="crm-banner crm-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="crm-btn crm-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status && status.per_agent.length === 0" class="crm-empty crm-empty--muted">
            <p>No active canary agents.</p>
          </div>
          <div v-else-if="status" class="crm-table-wrap">
            <table class="crm-table">
              <thead>
                <tr>
                  <th @click="sortAgents('name')" class="crm-sortable">Agent</th>
                  <th @click="sortAgents('home_kind')" class="crm-sortable">Home</th>
                  <th @click="sortAgents('current_balance')" class="crm-sortable">Balance</th>
                  <th @click="sortAgents('state')" class="crm-sortable">State</th>
                  <th @click="sortAgents('last_funded_iso')" class="crm-sortable">Last Funded</th>
                  <th>Next Eligible</th>
                  <th>Last Error</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in sortedAgents"
                  :key="row.agent_did"
                  :class="{ 'crm-row--active': selectedDid === row.agent_did }"
                  @click="selectedDid = selectedDid === row.agent_did ? null : row.agent_did"
                  style="cursor:pointer"
                >
                  <td>
                    <div class="crm-mono crm-text-tight" :title="row.agent_did">{{ row.name }}</div>
                    <div class="crm-mono crm-text-muted crm-text-tight">{{ truncate(row.agent_did, 28) }}</div>
                  </td>
                  <td class="crm-mono">{{ row.home_kind }}</td>
                  <td class="crm-mono" :class="balanceClass(row)">{{ formatAvt(row.current_balance) }}</td>
                  <td>
                    <span class="crm-state-pill" :class="statePillClass(row.state)">{{ row.state }}</span>
                  </td>
                  <td class="crm-mono">{{ formatRel(row.last_funded_iso) || '—' }}</td>
                  <td class="crm-mono">{{ formatRel(row.next_eligible_iso) || '—' }}</td>
                  <td class="crm-mono crm-text-muted">{{ row.last_error || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="selectedDid" class="crm-filter-hint">
            Filtering activity by <strong>{{ truncate(selectedDid, 32) }}</strong> — click row again to clear.
          </p>
        </section>

        <!-- Tabs -->
        <section class="crm-section">
          <div class="crm-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              class="crm-tab"
              :class="{ 'crm-tab--active': activeTab === tab.id }"
              type="button"
              @click="activeTab = tab.id"
            >
              {{ tab.label }}
            </button>
            <div class="crm-tabs-right">
              <button class="crm-btn crm-btn--ghost" @click="exportCsv" :disabled="filteredEvents.length === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <!-- Activity tab -->
          <div v-if="activeTab === 'activity'" class="crm-activity">
            <div class="crm-chip-row">
              <button class="crm-chip" :class="{ 'crm-chip--active': actionFilter === null }" @click="actionFilter = null">All</button>
              <button class="crm-chip" :class="{ 'crm-chip--active': actionFilter === 'funded' }" @click="actionFilter = 'funded'">Funded</button>
              <button class="crm-chip" :class="{ 'crm-chip--active': actionFilter === 'error' }" @click="actionFilter = 'error'">Errors</button>
            </div>

            <div v-if="loadingEvents && filteredEvents.length === 0" class="crm-empty">
              <div class="crm-spinner"></div>
              <p>Loading audit feed…</p>
            </div>
            <div v-else-if="eventsError" class="crm-banner crm-banner--bad">
              <Icon name="mdi:alert" /> {{ eventsError }}
              <button class="crm-btn crm-btn--ghost" @click="loadEvents">Retry</button>
            </div>
            <div v-else-if="filteredEvents.length === 0" class="crm-empty crm-empty--muted">
              <p v-if="selectedDid || actionFilter">No events match the filter.</p>
              <p v-else>No rebalancer events in last 24h — canary fleet healthy.</p>
            </div>
            <div v-else class="crm-table-wrap">
              <table class="crm-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Action</th>
                    <th>Agent</th>
                    <th>Home</th>
                    <th>Amount</th>
                    <th>Pre-balance</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="e in filteredEvents" :key="(e.event_id || '') + (e.timestamp || '')">
                    <td class="crm-mono">{{ formatTime(e.timestamp) }}</td>
                    <td>
                      <span class="crm-action-pill" :class="actionPillClass(e.action)">{{ e.action }}</span>
                    </td>
                    <td class="crm-mono" :title="e.agent_did || ''">{{ truncate(e.agent_did, 26) }}</td>
                    <td class="crm-mono">{{ e.home_kind || '—' }}</td>
                    <td class="crm-mono">{{ formatAvt(e.amount) }}</td>
                    <td class="crm-mono crm-text-muted">{{ formatAvt(e.pre_balance) }}</td>
                    <td class="crm-mono crm-text-muted">{{ e.reason || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Funding paths tab -->
          <div v-else-if="activeTab === 'paths'" class="crm-paths">
            <div class="crm-trend-cards">
              <div
                v-for="(stats, home) in homeKindAggregates"
                :key="home"
                class="crm-trend-card"
              >
                <div class="crm-trend-label">{{ home }}</div>
                <div class="crm-trend-value">{{ stats.funded }}</div>
                <div class="crm-trend-sub">
                  {{ stats.errors }} error{{ stats.errors === 1 ? '' : 's' }} · {{ stats.success_rate }}% success
                </div>
              </div>
              <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
              <div v-else-if="!status" class="crm-empty"><div class="crm-spinner"></div><p>Loading agent state…</p></div>
              <div v-else-if="Object.keys(homeKindAggregates).length === 0" class="crm-empty crm-empty--muted">
                <p>No rebalancer fundings in last 24h.</p>
              </div>
            </div>
          </div>

          <!-- Per-agent history tab -->
          <div v-else-if="activeTab === 'history'" class="crm-history">
            <div v-if="!selectedDid" class="crm-empty crm-empty--muted">
              <p>Pick an agent from the table above to view its fund/error history.</p>
            </div>
            <div v-else>
              <h4 class="crm-history-head">{{ truncate(selectedDid, 40) }}</h4>
              <ReadFailedNotice v-if="eventsError" dense :retry="loadEvents" />
              <div v-else-if="agentHistory.length === 0" class="crm-empty crm-empty--muted">
                <p>No fund/error events for this agent in last 24h.</p>
              </div>
              <table v-else class="crm-table">
                <thead>
                  <tr><th>Time</th><th>Action</th><th>Amount</th><th>Pre-balance</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  <tr v-for="e in agentHistory" :key="(e.event_id || '') + (e.timestamp || '')">
                    <td class="crm-mono">{{ formatTime(e.timestamp) }}</td>
                    <td>
                      <span class="crm-action-pill" :class="actionPillClass(e.action)">{{ e.action }}</span>
                    </td>
                    <td class="crm-mono">{{ formatAvt(e.amount) }}</td>
                    <td class="crm-mono crm-text-muted">{{ formatAvt(e.pre_balance) }}</td>
                    <td class="crm-mono crm-text-muted">{{ e.reason || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <div class="crm-footer">
          <span class="crm-mono crm-text-muted">
            GET /admin/canary-rebalancer/*&nbsp;·&nbsp;Auto-refresh: paused on tab-hidden
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
 * CanaryRebalancerModal — Tier 3 observability for canary_rebalancer (§pass27 Phase 2).
 *
 * Same shell idioms as §pass26 sweeper + Phase 1 judge: 4 stat cards →
 * per-entity table → 3 tabs → CSV → 5s polling. Activity / Funding Paths /
 * Per-Agent History tabs.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import {
  getRebalancerStatus,
  getRebalancerEvents,
  type RebalancerStatusResponse,
  type RebalancerEvent,
  type RebalancerAgentRow,
  type RebalancerAction,
} from '@/services/api/canaryRebalancer'
import { downloadCsv } from '@/components/common/csvExport'
import { useCurrency } from '@/composables/useCurrency'

dayjs.extend(relativeTime)
// D6-835: floors, top-ups and disbursements are in this frame's unit
const { localCurrency } = useCurrency()

interface Props { workerId?: string }
const props = withDefaults(defineProps<Props>(), { workerId: 'canary_rebalancer' })

const emit = defineEmits<{ (e: 'close'): void }>()

// State
const status = ref<RebalancerStatusResponse | null>(null)
const events = ref<RebalancerEvent[]>([])
const loadingStatus = ref(false)
const loadingEvents = ref(false)
const statusError = ref('')
const eventsError = ref('')

const selectedDid = ref<string | null>(null)
const actionFilter = ref<RebalancerAction | null>(null)
const activeTab = ref<'activity' | 'paths' | 'history'>('activity')
const autoRefresh = ref(true)

const agentSortKey = ref<keyof RebalancerAgentRow>('state')
const agentSortDir = ref<'asc' | 'desc'>('asc')

let refreshInterval: number | null = null

const tabs: { id: 'activity' | 'paths' | 'history'; label: string }[] = [
  { id: 'activity', label: 'Recent Activity' },
  { id: 'paths',    label: 'Funding Paths' },
  { id: 'history',  label: 'Per-Agent History' },
]

// Derived
const hasErrors = computed(() => (status.value?.summary.errors_24h ?? 0) > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'crm-status-dot--bad'
  if (!status.value) return 'crm-status-dot--muted'
  if (status.value.summary.errors_24h > 0) return 'crm-status-dot--bad'
  if (status.value.summary.agents_under_floor > 0) return 'crm-status-dot--warn'
  return 'crm-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  if (status.value.summary.errors_24h > 0) return `${status.value.summary.errors_24h} errors`
  if (status.value.summary.agents_under_floor > 0) return `${status.value.summary.agents_under_floor} agents under floor`
  return 'All healthy'
})

const sortedAgents = computed(() => {
  if (!status.value) return []
  const list = [...status.value.per_agent]
  const k = agentSortKey.value
  const dir = agentSortDir.value === 'asc' ? 1 : -1
  // Numeric sort if balance.
  list.sort((a, b) => {
    let av: any = a[k]
    let bv: any = b[k]
    if (k === 'current_balance') {
      av = parseFloat(av || '0')
      bv = parseFloat(bv || '0')
    }
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (av === bv) return 0
    return av < bv ? -1 * dir : 1 * dir
  })
  return list
})

function sortAgents(k: keyof RebalancerAgentRow) {
  if (agentSortKey.value === k) {
    agentSortDir.value = agentSortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    agentSortKey.value = k
    agentSortDir.value = 'asc'
  }
}

const filteredEvents = computed(() => {
  let list = events.value
  if (selectedDid.value) list = list.filter(e => e.agent_did === selectedDid.value)
  if (actionFilter.value) list = list.filter(e => e.action === actionFilter.value)
  return list
})

const agentHistory = computed(() => {
  if (!selectedDid.value) return []
  return events.value.filter(e => e.agent_did === selectedDid.value)
})

const homeKindAggregates = computed(() => {
  if (!status.value) return {}
  const fnd = status.value.by_home_kind.funded || {}
  const err = status.value.by_home_kind.errors || {}
  const all = new Set([...Object.keys(fnd), ...Object.keys(err)])
  const out: Record<string, { funded: number; errors: number; success_rate: number }> = {}
  for (const k of all) {
    const f = fnd[k] || 0
    const e = err[k] || 0
    const tot = f + e
    out[k] = {
      funded: f,
      errors: e,
      success_rate: tot ? Math.round((f / tot) * 100) : 0,
    }
  }
  return out
})

// Loaders
async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getRebalancerStatus()
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
    const resp = await getRebalancerEvents({
      agent_did: selectedDid.value || undefined,
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
async function refreshAll() { await Promise.all([loadStatus(), loadEvents()]) }

watch([selectedDid, actionFilter], () => { loadEvents() })

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
function formatRel(iso?: string | null): string {
  if (!iso) return ''
  return dayjs(iso).fromNow()
}
function truncate(s?: string | null, n = 12): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}
function formatAvt(v?: string | null): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = parseFloat(v)
  if (!Number.isFinite(n)) return v
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}
function balanceClass(row: RebalancerAgentRow) {
  if (!row.current_balance) return 'crm-text-muted'
  const n = parseFloat(row.current_balance)
  const floor = parseFloat(status.value?.config.floor_avt || '0')
  if (n < floor) return 'crm-text-bad'
  if (n < floor * 2) return 'crm-text-warn'
  return 'crm-text-ok'
}
function statePillClass(state: string) {
  return {
    'crm-state-pill--ok':       state === 'healthy',
    'crm-state-pill--cooldown': state === 'cooldown',
    'crm-state-pill--warn':     state === 'under_floor',
    'crm-state-pill--bad':      state === 'errored',
    'crm-state-pill--muted':    state === 'unknown',
  }
}
function actionPillClass(action: string) {
  return {
    'crm-action-pill--fund': action === 'funded',
    'crm-action-pill--err':  action === 'error',
  }
}

function exportCsv() {
  const filename = `canary-rebalancer-${dayjs().format('YYYY-MM-DD-HHmm')}.csv`
  downloadCsv<RebalancerEvent>(
    filteredEvents.value,
    [
      { label: 'timestamp',    value: e => e.timestamp || '' },
      { label: 'event_type',   value: e => e.event_type },
      { label: 'action',       value: e => e.action },
      { label: 'agent_did',    value: e => e.agent_did || '' },
      { label: 'home_kind',    value: e => e.home_kind || '' },
      { label: 'registry_url', value: e => e.registry_url || '' },
      { label: 'amount',       value: e => e.amount || '' },
      { label: 'pre_balance',  value: e => e.pre_balance || '' },
      { label: 'reason',       value: e => e.reason || '' },
      { label: 'floor',        value: e => e.floor || '' },
    ],
    filename,
  )
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.crm-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.crm-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.crm-modal--errors {
  border-color: rgba(239, 68, 68, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(239, 68, 68, 0.2);
}

/* Header */
.crm-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.crm-header-left { display: flex; align-items: center; gap: 10px; }
.crm-header-right { display: flex; align-items: center; gap: 8px; }
.crm-title { font-size: 1.05rem; margin: 0; font-weight: 600; }
.crm-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.crm-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.crm-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.crm-status-dot--ok   { background: #10b981; color: #10b981; }
.crm-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.crm-status-dot--bad  { background: #ef4444; color: #ef4444; animation: crm-pulse 1.8s infinite; }
.crm-status-dot--muted { background: #4b5563; color: #4b5563; }
@keyframes crm-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

/* Buttons */
.crm-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
}
.crm-btn:hover:not(:disabled) { background: rgba(0, 210, 210, 0.08); border-color: rgba(0, 210, 210, 0.45); }
.crm-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.crm-btn--ghost { background: transparent; }
.crm-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.crm-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

/* Stats */
.crm-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.crm-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.crm-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.crm-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.crm-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.crm-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.crm-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

/* Config rail */
.crm-config-row {
  display: flex; flex-wrap: wrap; gap: 12px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10));
  font-family: ui-monospace, monospace;
}
.crm-cfg-pair { display: inline-flex; gap: 6px; align-items: baseline; font-size: 0.72rem; }
.crm-cfg-key { color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.62rem; }
.crm-cfg-val { color: var(--nc-text, #e2e8f0); font-weight: 600; }

/* Sections */
.crm-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.crm-section:last-of-type { border-bottom: none; }
.crm-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.crm-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

/* Tabs */
.crm-tabs {
  display: flex;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  margin: -6px -20px 12px -20px;
  padding: 0 20px;
  align-items: center;
}
.crm-tabs-right { margin-left: auto; padding-bottom: 6px; }
.crm-tab {
  background: transparent; border: none; color: var(--nc-muted, #94a3b8);
  padding: 8px 14px; cursor: pointer; font-size: 0.8rem;
  border-bottom: 2px solid transparent;
}
.crm-tab--active { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.crm-tab:hover { color: var(--nc-text, #e2e8f0); }

/* Chips */
.crm-chip-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.crm-chip {
  padding: 4px 10px; font-size: 0.72rem; border-radius: 12px;
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  color: var(--nc-text, #e2e8f0); cursor: pointer;
}
.crm-chip:hover { background: rgba(0, 210, 210, 0.12); }
.crm-chip--active {
  background: rgba(0, 210, 210, 0.18);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}

/* Table */
.crm-table-wrap { overflow-x: auto; }
.crm-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.crm-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.crm-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.crm-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }
.crm-sortable { cursor: pointer; user-select: none; }
.crm-sortable:hover { color: var(--nc-primary, #00d2d2); }
.crm-row--active { background: rgba(0, 210, 210, 0.10); }

.crm-state-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.crm-state-pill--ok       { background: rgba(16, 185, 129, 0.16); color: #34d399; }
.crm-state-pill--cooldown { background: rgba(99, 102, 241, 0.16); color: #a5b4fc; }
.crm-state-pill--warn     { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }
.crm-state-pill--bad      { background: rgba(239, 68, 68, 0.16); color: #f87171; }
.crm-state-pill--muted    { background: rgba(255, 255, 255, 0.06); color: rgba(255, 255, 255, 0.55); }

.crm-action-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.crm-action-pill--fund { background: rgba(16, 185, 129, 0.18); color: #34d399; }
.crm-action-pill--err  { background: rgba(239, 68, 68, 0.18); color: #f87171; }

.crm-filter-hint { margin: 10px 0 0 0; font-size: 0.75rem; color: var(--nc-muted, #94a3b8); }

/* Paths tab */
.crm-trend-cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.crm-trend-card {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  border-radius: 8px; padding: 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.crm-trend-label { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.crm-trend-value { font-size: 1.7rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.crm-trend-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

.crm-history-head { font-size: 0.95rem; margin: 0 0 10px 0; font-family: ui-monospace, monospace; }

/* Empty / loading */
.crm-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.crm-empty--muted { font-size: 0.82rem; }
.crm-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: crm-spin 0.8s linear infinite;
}
@keyframes crm-spin { to { transform: rotate(360deg); } }

/* Banner */
.crm-banner {
  padding: 10px 14px; border-radius: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px;
}
.crm-banner--bad {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

.crm-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.crm-text-muted { color: var(--nc-muted, #94a3b8); }
.crm-text-warn  { color: #fbbf24; }
.crm-text-bad   { color: #f87171; }
.crm-text-ok    { color: #34d399; }
.crm-text-tight { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 240px; }

.crm-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .crm-stats-row { grid-template-columns: repeat(2, 1fr); }
  .crm-modal { max-height: 92vh; }
  .crm-config-row { gap: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  .crm-status-dot--bad { animation: none; }
}
</style>
