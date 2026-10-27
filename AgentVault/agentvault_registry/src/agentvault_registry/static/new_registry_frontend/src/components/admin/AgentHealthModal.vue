<template>
  <Teleport to="body">
    <div
      class="ahm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ahm-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="ahm-modal" :class="{ 'ahm-modal--errors': hasDown }">
        <!-- Header -->
        <div class="ahm-header">
          <div class="ahm-header-left">
            <span class="ahm-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="ahm-modal-title" class="ahm-title">Agent Health Checker</h2>
            <span class="ahm-subtitle">{{ workerId }}</span>
          </div>
          <div class="ahm-header-right">
            <span v-if="status?.snapshot_iso" class="ahm-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="ahm-btn ahm-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingTransitions">
              <span class="ahm-live-dot" :class="{ 'ahm-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="ahm-btn ahm-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="ahm-stats-row">
          <div class="ahm-stat">
            <span class="ahm-stat-label">Agents checked</span>
            <span class="ahm-stat-value">{{ status?.summary.agents_active ?? '—' }}</span>
            <span class="ahm-stat-sub">active w/ probe URL</span>
          </div>
          <div class="ahm-stat" :class="{ 'ahm-stat--warn': downCount > 0 }">
            <span class="ahm-stat-label">Currently down</span>
            <span class="ahm-stat-value">{{ status ? downCount : '—' }}</span>
            <span class="ahm-stat-sub">unhealthy + unreachable</span>
          </div>
          <div class="ahm-stat">
            <span class="ahm-stat-label">Cycles 24h</span>
            <span class="ahm-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="ahm-stat-sub">every {{ status?.summary.interval_sec ?? '—' }}s</span>
          </div>
          <div class="ahm-stat">
            <span class="ahm-stat-label">State changes 24h</span>
            <span class="ahm-stat-value">{{ status?.summary.state_changes_24h ?? '—' }}</span>
            <span class="ahm-stat-sub">flap detections / recoveries</span>
          </div>
        </div>

        <!-- DB summary bar (current state) -->
        <section v-if="status?.db_summary" class="ahm-section ahm-summary-bar">
          <h3 class="ahm-section-title">
            Current state
            <span class="ahm-section-sub">DB rollup of agents.last_health</span>
          </h3>
          <div class="ahm-bar-grid">
            <div class="ahm-bar-cell ahm-bar-cell--ok">
              <div class="ahm-bar-label">healthy</div>
              <div class="ahm-bar-val">{{ status.db_summary.healthy ?? 0 }}</div>
            </div>
            <div class="ahm-bar-cell ahm-bar-cell--warn">
              <div class="ahm-bar-label">unhealthy</div>
              <div class="ahm-bar-val">{{ status.db_summary.unhealthy ?? 0 }}</div>
            </div>
            <div class="ahm-bar-cell ahm-bar-cell--bad">
              <div class="ahm-bar-label">unreachable</div>
              <div class="ahm-bar-val">{{ status.db_summary.unreachable ?? 0 }}</div>
            </div>
            <div class="ahm-bar-cell ahm-bar-cell--muted">
              <div class="ahm-bar-label">never observed</div>
              <div class="ahm-bar-val">{{ status.db_summary.never_observed ?? 0 }}</div>
            </div>
          </div>
        </section>

        <!-- Tabs -->
        <section class="ahm-section">
          <div class="ahm-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              class="ahm-tab"
              :class="{ 'ahm-tab--active': activeTab === tab.id }"
              type="button"
              @click="activeTab = tab.id"
            >
              {{ tab.label }}
            </button>
            <div class="ahm-tabs-right">
              <button class="ahm-btn ahm-btn--ghost" @click="exportCsv" :disabled="exportCount === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <!-- Recent Transitions tab -->
          <div v-if="activeTab === 'transitions'" class="ahm-activity">
            <p class="ahm-text-muted" style="margin: 0 0 10px 0; font-size: 0.76rem">
              In-memory ring buffer of recent agent-health state changes (newest first).
              Each transition fired an <code>agent.health_changed</code> webhook.
              Buffer max 200 entries.
            </p>
            <div v-if="loadingTransitions && transitions.length === 0" class="ahm-empty">
              <div class="ahm-spinner"></div>
              <p>Loading transitions…</p>
            </div>
            <ReadFailedNotice v-else-if="transitionsError" dense :retry="loadTransitions" />
            <div v-else-if="transitions.length === 0" class="ahm-empty ahm-empty--muted">
              <p>No state transitions on record — fleet healthy + stable.</p>
            </div>
            <div v-else class="ahm-table-wrap">
              <table class="ahm-table">
                <thead>
                  <tr>
                    <th>Observed</th>
                    <th>Agent DID</th>
                    <th>From → To</th>
                    <th>URL</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="t in transitions" :key="t.agent_did + t.observed_iso">
                    <td class="ahm-mono">{{ formatTime(t.observed_iso) }}</td>
                    <td class="ahm-mono" :title="t.agent_did">{{ truncate(t.agent_did, 34) }}</td>
                    <td>
                      <span class="ahm-state-pill" :class="statePillClass(t.from_state)">{{ t.from_state }}</span>
                      <span class="ahm-text-muted" style="margin: 0 6px">→</span>
                      <span class="ahm-state-pill" :class="statePillClass(t.to_state)">{{ t.to_state }}</span>
                    </td>
                    <td class="ahm-mono ahm-text-muted" :title="t.url">{{ truncate(t.url, 40) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Transition Matrix tab -->
          <div v-else-if="activeTab === 'matrix'" class="ahm-matrix">
            <p class="ahm-text-muted" style="margin: 0 0 10px 0; font-size: 0.76rem">
              24h transition counts grouped by from-state → to-state. The
              diagonal (no-change) is not counted — every cell represents a
              real flap or recovery.
            </p>
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="ahm-empty"><div class="ahm-spinner"></div><p>Loading checker state…</p></div>
            <div v-else-if="matrixStates.length === 0" class="ahm-empty ahm-empty--muted">
              <p>No transitions in last 24h.</p>
            </div>
            <div v-else class="ahm-table-wrap">
              <table class="ahm-table">
                <thead>
                  <tr>
                    <th>from \ to</th>
                    <th v-for="s in matrixStates" :key="'col-'+s">
                      <span class="ahm-state-pill" :class="statePillClass(s)">{{ s }}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="from in matrixStates" :key="'row-'+from">
                    <td>
                      <span class="ahm-state-pill" :class="statePillClass(from)">{{ from }}</span>
                    </td>
                    <td v-for="to in matrixStates" :key="from+'-'+to" class="ahm-mono"
                        :class="matrixCellClass(from, to)">
                      {{ matrixValue(from, to) || (from === to ? '—' : 0) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Flapping / Down tab -->
          <div v-else-if="activeTab === 'down'" class="ahm-down">
            <p class="ahm-text-muted" style="margin: 0 0 10px 0; font-size: 0.76rem">
              Agents whose most recent probe was <code>unhealthy</code> or
              <code>unreachable</code> (most-recently-active first). Up to 25.
            </p>
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="ahm-empty"><div class="ahm-spinner"></div><p>Loading checker state…</p></div>
            <div v-else-if="status.flapping_or_down.length === 0" class="ahm-empty ahm-empty--muted">
              <p>No agents currently in non-healthy state.</p>
            </div>
            <div v-else class="ahm-table-wrap">
              <table class="ahm-table">
                <thead>
                  <tr>
                    <th>Agent DID</th>
                    <th>State</th>
                    <th>Last active</th>
                    <th>URL</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="d in status.flapping_or_down" :key="d.agent_did">
                    <td class="ahm-mono" :title="d.agent_did">{{ truncate(d.agent_did, 34) }}</td>
                    <td>
                      <span class="ahm-state-pill" :class="statePillClass(d.last_health)">{{ d.last_health }}</span>
                    </td>
                    <td class="ahm-mono">{{ formatRel(d.last_active_iso) }}</td>
                    <td class="ahm-mono ahm-text-muted" :title="d.url">{{ truncate(d.url, 40) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <!-- Local cycle rail -->
        <section v-if="status?.local_last_cycle.last_cycle_iso" class="ahm-section ahm-cycle-info">
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">Last cycle</span>
            <span class="ahm-cycle-val ahm-mono">{{ formatRel(status.local_last_cycle.last_cycle_iso) }}</span>
          </div>
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">Duration</span>
            <span class="ahm-cycle-val ahm-mono">{{ (status.local_last_cycle.last_duration_ms / 1000).toFixed(1) }}s</span>
          </div>
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">Checked</span>
            <span class="ahm-cycle-val ahm-mono">{{ status.local_last_cycle.checked }}</span>
          </div>
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">Healthy</span>
            <span class="ahm-cycle-val ahm-mono ahm-text-ok">{{ status.local_last_cycle.healthy }}</span>
          </div>
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">Unhealthy</span>
            <span class="ahm-cycle-val ahm-mono" :class="status.local_last_cycle.unhealthy > 0 ? 'ahm-text-warn' : ''">
              {{ status.local_last_cycle.unhealthy }}
            </span>
          </div>
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">Unreachable</span>
            <span class="ahm-cycle-val ahm-mono" :class="status.local_last_cycle.unreachable > 0 ? 'ahm-text-bad' : ''">
              {{ status.local_last_cycle.unreachable }}
            </span>
          </div>
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">First obs</span>
            <span class="ahm-cycle-val ahm-mono">{{ status.local_last_cycle.first_observations }}</span>
          </div>
          <div class="ahm-cycle-pair">
            <span class="ahm-cycle-key">Changes</span>
            <span class="ahm-cycle-val ahm-mono">{{ status.local_last_cycle.state_changes }}</span>
          </div>
        </section>

        <div class="ahm-footer">
          <span class="ahm-mono ahm-text-muted">
            GET /admin/agent-health/*&nbsp;·&nbsp;Auto-refresh: paused on tab-hidden
          </span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import {
  getAgentHealthStatus,
  getAgentHealthTransitions,
  type AgentHealthStatusResponse,
  type AHTransition,
} from '@/services/api/agentHealth'
import { downloadCsv } from '@/components/common/csvExport'

dayjs.extend(relativeTime)

interface Props { workerId?: string }
const props = withDefaults(defineProps<Props>(), { workerId: 'agent_health_checker' })
const emit = defineEmits<{ (e: 'close'): void }>()

const status = ref<AgentHealthStatusResponse | null>(null)
const transitions = ref<AHTransition[]>([])
const loadingStatus = ref(false)
const loadingTransitions = ref(false)
const statusError = ref('')
// a transitions read that got no answer says so (it was swallowed: the tab then said "No state transitions on record
// — fleet healthy + stable." over a failed read; §FESUITE V0577)
const transitionsError = ref('')

const activeTab = ref<'transitions' | 'matrix' | 'down'>('transitions')
const autoRefresh = ref(true)

let refreshInterval: number | null = null

const tabs: { id: 'transitions' | 'matrix' | 'down'; label: string }[] = [
  { id: 'transitions', label: 'Recent Transitions' },
  { id: 'matrix',      label: 'Transition Matrix' },
  { id: 'down',        label: 'Currently Down' },
]

const downCount = computed(() =>
  (status.value?.summary.agents_unhealthy ?? 0) +
  (status.value?.summary.agents_unreachable ?? 0)
)

const hasDown = computed(() => downCount.value > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'ahm-status-dot--bad'
  if (!status.value) return 'ahm-status-dot--muted'
  if (status.value.summary.agents_unreachable > 0) return 'ahm-status-dot--bad'
  if (status.value.summary.agents_unhealthy > 0) return 'ahm-status-dot--warn'
  return 'ahm-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  if (downCount.value > 0) return `${downCount.value} agents down`
  return 'All agents healthy'
})

const matrixStates = computed(() => {
  const grid = status.value?.transitions_grid || {}
  const set = new Set<string>()
  for (const from of Object.keys(grid)) {
    set.add(from)
    for (const to of Object.keys(grid[from] || {})) {
      set.add(to)
    }
  }
  // Stable order: healthy → unhealthy → unreachable → others
  const known = ['healthy', 'unhealthy', 'unreachable']
  const result = known.filter(s => set.has(s))
  for (const s of set) {
    if (!known.includes(s)) result.push(s)
  }
  return result
})

function matrixValue(from: string, to: string): number {
  return status.value?.transitions_grid?.[from]?.[to] ?? 0
}

function matrixCellClass(from: string, to: string) {
  if (from === to) return 'ahm-cell-diag'
  const v = matrixValue(from, to)
  if (v === 0) return 'ahm-cell-zero'
  // Recovery (toward healthy) is green; degradation is amber/red
  if (to === 'healthy') return 'ahm-cell-recover'
  if (to === 'unreachable') return 'ahm-cell-bad'
  return 'ahm-cell-warn'
}

const exportCount = computed(() => {
  if (activeTab.value === 'transitions') return transitions.value.length
  if (activeTab.value === 'down') return status.value?.flapping_or_down.length ?? 0
  return 0
})

async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getAgentHealthStatus()
  } catch (e: any) {
    statusError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingStatus.value = false
  }
}
async function loadTransitions() {
  if (loadingTransitions.value) return
  loadingTransitions.value = true
  try {
    const resp = await getAgentHealthTransitions(150)
    transitions.value = resp.transitions
    transitionsError.value = ''
  } catch (e: any) {
    transitionsError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingTransitions.value = false
  }
}
async function refreshAll() { await Promise.all([loadStatus(), loadTransitions()]) }

function tick() {
  if (document.visibilityState === 'hidden') return
  refreshAll()
}
function startPolling() {
  if (refreshInterval !== null) return
  refreshInterval = window.setInterval(tick, 10_000)  // 10s — 5min-cadence worker
}
function stopPolling() {
  if (refreshInterval !== null) { clearInterval(refreshInterval); refreshInterval = null }
}

onMounted(() => {
  refreshAll()
  if (autoRefresh.value) startPolling()
})
onBeforeUnmount(() => { stopPolling() })

function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).format('HH:mm:ss')
}
function formatRel(iso?: string | null): string {
  if (!iso) return 'never'
  return dayjs(iso).fromNow()
}
function truncate(s?: string | null, n = 12): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}
function statePillClass(s: string) {
  return {
    'ahm-state-pill--ok':    s === 'healthy',
    'ahm-state-pill--warn':  s === 'unhealthy',
    'ahm-state-pill--bad':   s === 'unreachable',
    'ahm-state-pill--muted': !['healthy', 'unhealthy', 'unreachable'].includes(s),
  }
}

function exportCsv() {
  const stamp = dayjs().format('YYYY-MM-DD-HHmm')
  if (activeTab.value === 'transitions') {
    downloadCsv<AHTransition>(
      transitions.value,
      [
        { label: 'observed_iso', value: t => t.observed_iso },
        { label: 'agent_did',    value: t => t.agent_did },
        { label: 'from_state',   value: t => t.from_state },
        { label: 'to_state',     value: t => t.to_state },
        { label: 'url',          value: t => t.url },
      ],
      `agent-health-transitions-${stamp}.csv`,
    )
  } else if (activeTab.value === 'down' && status.value) {
    downloadCsv(
      status.value.flapping_or_down,
      [
        { label: 'agent_did',       value: d => d.agent_did },
        { label: 'last_health',     value: d => d.last_health },
        { label: 'last_active_iso', value: d => d.last_active_iso || '' },
        { label: 'url',             value: d => d.url },
      ],
      `agent-health-down-${stamp}.csv`,
    )
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.ahm-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.ahm-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.ahm-modal--errors {
  border-color: rgba(245, 158, 11, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(245, 158, 11, 0.2);
}

.ahm-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.ahm-header-left { display: flex; align-items: center; gap: 10px; }
.ahm-header-right { display: flex; align-items: center; gap: 8px; }
.ahm-title { font-size: 1.05rem; margin: 0; font-weight: 600; }
.ahm-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.ahm-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.ahm-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.ahm-status-dot--ok   { background: #10b981; color: #10b981; }
.ahm-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.ahm-status-dot--bad  { background: #ef4444; color: #ef4444; animation: ahm-pulse 1.8s infinite; }
.ahm-status-dot--muted { background: #4b5563; color: #4b5563; }
@keyframes ahm-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

.ahm-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
}
.ahm-btn:hover:not(:disabled) { background: rgba(0, 210, 210, 0.08); border-color: rgba(0, 210, 210, 0.45); }
.ahm-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ahm-btn--ghost { background: transparent; }
.ahm-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.ahm-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

.ahm-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.ahm-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.ahm-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.ahm-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.ahm-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.ahm-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.ahm-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

.ahm-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.ahm-section:last-of-type { border-bottom: none; }
.ahm-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.ahm-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

.ahm-bar-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}
.ahm-bar-cell {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px;
  display: flex; flex-direction: column; gap: 2px;
}
.ahm-bar-cell--ok    { background: rgba(16, 185, 129, 0.08); border-color: rgba(16, 185, 129, 0.32); }
.ahm-bar-cell--warn  { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.ahm-bar-cell--bad   { background: rgba(239, 68, 68, 0.08);  border-color: rgba(239, 68, 68, 0.45); }
.ahm-bar-cell--muted { background: rgba(255, 255, 255, 0.04); border-color: rgba(255, 255, 255, 0.10); }
.ahm-bar-label { font-size: 0.64rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.ahm-bar-val   { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; font-family: ui-monospace, monospace; }

.ahm-tabs {
  display: flex;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  margin: -6px -20px 12px -20px;
  padding: 0 20px;
  align-items: center;
}
.ahm-tabs-right { margin-left: auto; padding-bottom: 6px; }
.ahm-tab {
  background: transparent; border: none; color: var(--nc-muted, #94a3b8);
  padding: 8px 14px; cursor: pointer; font-size: 0.8rem;
  border-bottom: 2px solid transparent;
}
.ahm-tab--active { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.ahm-tab:hover { color: var(--nc-text, #e2e8f0); }

.ahm-table-wrap { overflow-x: auto; }
.ahm-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.ahm-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.ahm-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.ahm-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }

.ahm-state-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.ahm-state-pill--ok    { background: rgba(16, 185, 129, 0.16); color: #34d399; }
.ahm-state-pill--warn  { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }
.ahm-state-pill--bad   { background: rgba(239, 68, 68, 0.18); color: #f87171; }
.ahm-state-pill--muted { background: rgba(255, 255, 255, 0.06); color: rgba(255, 255, 255, 0.55); }

.ahm-cell-diag    { background: rgba(255, 255, 255, 0.04); color: rgba(255, 255, 255, 0.4); text-align: center; }
.ahm-cell-zero    { color: rgba(255, 255, 255, 0.35); text-align: center; }
.ahm-cell-recover { background: rgba(16, 185, 129, 0.10); color: #34d399; font-weight: 600; text-align: center; }
.ahm-cell-warn    { background: rgba(245, 158, 11, 0.10); color: #fbbf24; font-weight: 600; text-align: center; }
.ahm-cell-bad     { background: rgba(239, 68, 68, 0.12);  color: #f87171; font-weight: 600; text-align: center; }

.ahm-cycle-info {
  display: flex; flex-wrap: wrap; gap: 16px;
  font-family: ui-monospace, monospace;
}
.ahm-cycle-pair { display: inline-flex; flex-direction: column; gap: 1px; font-size: 0.78rem; min-width: 110px; }
.ahm-cycle-key { color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.62rem; }
.ahm-cycle-val { color: var(--nc-text, #e2e8f0); }

.ahm-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.ahm-empty--muted { font-size: 0.82rem; }
.ahm-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: ahm-spin 0.8s linear infinite;
}
@keyframes ahm-spin { to { transform: rotate(360deg); } }

.ahm-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.ahm-text-muted { color: var(--nc-muted, #94a3b8); }
.ahm-text-warn  { color: #fbbf24; }
.ahm-text-bad   { color: #f87171; }
.ahm-text-ok    { color: #34d399; }

.ahm-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .ahm-stats-row { grid-template-columns: repeat(2, 1fr); }
  .ahm-modal { max-height: 92vh; }
}

@media (prefers-reduced-motion: reduce) {
  .ahm-status-dot--bad { animation: none; }
}
</style>
