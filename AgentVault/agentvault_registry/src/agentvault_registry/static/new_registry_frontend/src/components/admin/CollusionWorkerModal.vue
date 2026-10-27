<template>
  <Teleport to="body">
    <div
      class="cwm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cwm-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="cwm-modal" :class="{ 'cwm-modal--errors': hasRings24h }">
        <!-- Header -->
        <div class="cwm-header">
          <div class="cwm-header-left">
            <span class="cwm-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="cwm-modal-title" class="cwm-title">Collusion Detection</h2>
            <span class="cwm-subtitle">{{ workerId }}</span>
          </div>
          <div class="cwm-header-right">
            <span v-if="status?.snapshot_iso" class="cwm-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="cwm-btn cwm-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingRings">
              <span class="cwm-live-dot" :class="{ 'cwm-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="cwm-btn cwm-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="cwm-stats-row">
          <div class="cwm-stat">
            <span class="cwm-stat-label">Lifetime rings</span>
            <span class="cwm-stat-value">{{ status?.summary.lifetime_rings ?? '—' }}</span>
            <span class="cwm-stat-sub">all CollusionRingDetected rows</span>
          </div>
          <div class="cwm-stat" :class="{ 'cwm-stat--warn': (status?.summary.rings_24h ?? 0) > 0 }">
            <span class="cwm-stat-label">Rings 24h</span>
            <span class="cwm-stat-value">{{ status?.summary.rings_24h ?? '—' }}</span>
            <span class="cwm-stat-sub">recent flags</span>
          </div>
          <div class="cwm-stat">
            <span class="cwm-stat-label">Cycles 24h</span>
            <span class="cwm-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="cwm-stat-sub">daily cadence ({{ Math.round((status?.summary.interval_sec ?? 86400) / 3600) }}h interval)</span>
          </div>
          <div class="cwm-stat" :class="{ 'cwm-stat--bad': (status?.summary.errors_24h ?? 0) > 0 }">
            <span class="cwm-stat-label">Errors 24h</span>
            <span class="cwm-stat-value">{{ status?.summary.errors_24h ?? '—' }}</span>
            <span class="cwm-stat-sub">{{ !status ? '—' : (status.summary.errors_24h ?? 0) === 0 ? 'all clean' : 'investigate' }}</span>
          </div>
        </div>

        <!-- Next cycle banner -->
        <section v-if="status?.summary.next_cycle_iso" class="cwm-section cwm-cycle-info">
          <div class="cwm-cycle-pair">
            <span class="cwm-cycle-key">Last cycle</span>
            <span class="cwm-cycle-val cwm-mono">{{ formatRel(status.local_last_cycle.last_cycle_iso) }}
              <span class="cwm-text-muted">({{ formatDate(status.local_last_cycle.last_cycle_iso) }})</span>
            </span>
          </div>
          <div class="cwm-cycle-pair">
            <span class="cwm-cycle-key">Next cycle</span>
            <span class="cwm-cycle-val cwm-mono">{{ formatRel(status.summary.next_cycle_iso) }}
              <span class="cwm-text-muted">({{ formatDate(status.summary.next_cycle_iso) }})</span>
            </span>
          </div>
          <div class="cwm-cycle-pair">
            <span class="cwm-cycle-key">Decay pass</span>
            <span class="cwm-cycle-val">
              <span class="cwm-state-pill" :class="stageClass(status.local_last_cycle.decay_pass_status)">
                {{ status.local_last_cycle.decay_pass_status }}
              </span>
            </span>
          </div>
          <div class="cwm-cycle-pair">
            <span class="cwm-cycle-key">Ring scan</span>
            <span class="cwm-cycle-val">
              <span class="cwm-state-pill" :class="stageClass(status.local_last_cycle.collusion_scan_status)">
                {{ status.local_last_cycle.collusion_scan_status }}
              </span>
              <span v-if="status.local_last_cycle.rings_detected_last_cycle > 0" class="cwm-text-warn cwm-mono">
                · {{ status.local_last_cycle.rings_detected_last_cycle }} flagged
              </span>
            </span>
          </div>
          <div class="cwm-cycle-pair">
            <span class="cwm-cycle-key">Last duration</span>
            <span class="cwm-cycle-val cwm-mono">{{ (status.local_last_cycle.last_duration_ms / 1000).toFixed(1) }}s</span>
          </div>
        </section>

        <!-- Per-registry rail -->
        <section class="cwm-section">
          <h3 class="cwm-section-title">
            Per-registry
            <span class="cwm-section-sub">cycles + ring counts via Prom labels</span>
          </h3>
          <div v-if="loadingStatus && !status" class="cwm-empty">
            <div class="cwm-spinner"></div>
            <p>Loading collusion worker state…</p>
          </div>
          <div v-else-if="statusError" class="cwm-banner cwm-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="cwm-btn cwm-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status && status.per_registry.length === 0" class="cwm-empty cwm-empty--muted">
            <p>No registries reporting yet — daily cadence; check after first 24h post-deploy.</p>
          </div>
          <div v-else-if="status" class="cwm-fleet-grid">
            <div
              v-for="r in status.per_registry"
              :key="r.registry_id"
              class="cwm-fleet-card"
              :class="{ 'cwm-fleet-card--warn': r.rings_detected_24h > 0, 'cwm-fleet-card--bad': r.errors_24h > 0 }"
            >
              <div class="cwm-fleet-card-head">
                <span class="cwm-fleet-dot" :class="r.errors_24h > 0 ? 'cwm-fleet-dot--bad' : (r.rings_detected_24h > 0 ? 'cwm-fleet-dot--warn' : 'cwm-fleet-dot--ok')"></span>
                <span class="cwm-fleet-name">{{ r.registry_id }}</span>
              </div>
              <div class="cwm-fleet-card-body">
                <div class="cwm-fleet-row"><span class="cwm-fleet-key">cycles 24h</span><span class="cwm-fleet-val">{{ r.cycles_24h }}</span></div>
                <div class="cwm-fleet-row"><span class="cwm-fleet-key">decay 24h</span><span class="cwm-fleet-val">{{ r.decay_passes_24h }}</span></div>
                <div class="cwm-fleet-row"><span class="cwm-fleet-key">rings 24h</span><span class="cwm-fleet-val" :class="r.rings_detected_24h > 0 ? 'cwm-text-warn' : ''">{{ r.rings_detected_24h }}</span></div>
                <div class="cwm-fleet-row"><span class="cwm-fleet-key">errors 24h</span><span class="cwm-fleet-val" :class="r.errors_24h > 0 ? 'cwm-text-bad' : ''">{{ r.errors_24h }}</span></div>
              </div>
            </div>
          </div>
        </section>

        <!-- Severity rollup + top DIDs -->
        <section v-if="status" class="cwm-section">
          <div class="cwm-rollup-cards">
            <div class="cwm-rollup-card">
              <h4 class="cwm-rollup-h4">Lifetime severity rollup</h4>
              <div class="cwm-sev-pills">
                <span v-for="(n, sev) in status.by_severity" :key="sev" class="cwm-sev-pill" :class="sevPillClass(sev)">
                  {{ sev }}: {{ n }}
                </span>
                <span v-if="Object.keys(status.by_severity).length === 0" class="cwm-text-muted">none yet</span>
              </div>
            </div>
            <div class="cwm-rollup-card">
              <h4 class="cwm-rollup-h4">Most recently flagged DIDs</h4>
              <div v-if="status.top_flagged_dids.length === 0" class="cwm-text-muted">none</div>
              <ul v-else class="cwm-dids-list">
                <li v-for="d in status.top_flagged_dids" :key="d.agent_did" class="cwm-mono">
                  <button class="cwm-link-btn" @click="filterByDid(d.agent_did)" :title="d.agent_did">
                    {{ truncate(d.agent_did, 38) }}
                  </button>
                  <span class="cwm-text-muted"> · {{ formatRel(d.last_flagged_iso) }}</span>
                </li>
              </ul>
            </div>
          </div>
        </section>

        <!-- Rings table -->
        <section class="cwm-section">
          <div class="cwm-tabs">
            <h3 class="cwm-section-title">
              Ring history
              <span class="cwm-section-sub">{{ rings.length }} rings shown · filters chip below</span>
            </h3>
            <div class="cwm-tabs-right">
              <button class="cwm-btn cwm-btn--ghost" @click="exportCsv" :disabled="rings.length === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <div class="cwm-chip-row">
            <button class="cwm-chip" :class="{ 'cwm-chip--active': sinceFilter === '24h' }" @click="sinceFilter = '24h'">24h</button>
            <button class="cwm-chip" :class="{ 'cwm-chip--active': sinceFilter === '7d' }" @click="sinceFilter = '7d'">7d</button>
            <button class="cwm-chip" :class="{ 'cwm-chip--active': sinceFilter === '30d' }" @click="sinceFilter = '30d'">30d</button>
            <button class="cwm-chip" :class="{ 'cwm-chip--active': sinceFilter === 'all' }" @click="sinceFilter = 'all'">all-time</button>
            <span class="cwm-chip-sep">|</span>
            <button class="cwm-chip" :class="{ 'cwm-chip--active': severityFilter === null }" @click="severityFilter = null">All</button>
            <button class="cwm-chip" :class="{ 'cwm-chip--active': severityFilter === 'HIGH' }" @click="severityFilter = 'HIGH'">HIGH</button>
            <button class="cwm-chip" :class="{ 'cwm-chip--active': severityFilter === 'MEDIUM' }" @click="severityFilter = 'MEDIUM'">MEDIUM</button>
            <button class="cwm-chip" :class="{ 'cwm-chip--active': severityFilter === 'LOW' }" @click="severityFilter = 'LOW'">LOW</button>
            <button v-if="didFilter" class="cwm-chip cwm-chip--active" @click="didFilter = null">
              did: {{ truncate(didFilter, 18) }} ✕
            </button>
          </div>

          <div v-if="loadingRings && rings.length === 0" class="cwm-empty">
            <div class="cwm-spinner"></div>
            <p>Loading ring history…</p>
          </div>
          <div v-else-if="ringsError" class="cwm-banner cwm-banner--bad">
            <Icon name="mdi:alert" /> {{ ringsError }}
            <button class="cwm-btn cwm-btn--ghost" @click="loadRings">Retry</button>
          </div>
          <div v-else-if="rings.length === 0" class="cwm-empty cwm-empty--muted">
            <p>No rings match the current filters.</p>
          </div>
          <div v-else class="cwm-table-wrap">
            <table class="cwm-table">
              <thead>
                <tr>
                  <th>Detected</th>
                  <th>Severity</th>
                  <th>Flagged agent</th>
                  <th>SCC size</th>
                  <th>Score</th>
                  <th>Ring members</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="r in rings" :key="r.id">
                  <tr>
                    <td class="cwm-mono">{{ formatTime(r.created_at) }} <span class="cwm-text-muted">· {{ formatDate(r.created_at) }}</span></td>
                    <td>
                      <span class="cwm-state-pill" :class="sevPillClass(r.severity)">{{ r.severity }}</span>
                    </td>
                    <td class="cwm-mono" :title="r.flagged_agent_did">
                      <button class="cwm-link-btn" @click="filterByDid(r.flagged_agent_did)">
                        {{ truncate(r.flagged_agent_did, 26) }}
                      </button>
                    </td>
                    <td class="cwm-mono">{{ r.scc_size ?? '—' }}</td>
                    <td class="cwm-mono">{{ r.score ?? '—' }}</td>
                    <td>
                      <button v-if="r.members && r.members.length > 0" class="cwm-btn cwm-btn--ghost cwm-btn--inline" @click="toggleExpand(r.id)">
                        {{ expanded.has(r.id) ? '▼' : '▶' }} {{ r.members.length }} members
                      </button>
                      <span v-else class="cwm-text-muted cwm-mono">—</span>
                    </td>
                  </tr>
                  <tr v-if="expanded.has(r.id)" class="cwm-expanded-row">
                    <td colspan="6">
                      <div class="cwm-members-list">
                        <span v-for="m in r.members" :key="m" class="cwm-member-pill cwm-mono">
                          <button class="cwm-link-btn" @click="filterByDid(m)" :title="m">
                            {{ truncate(m, 38) }}
                          </button>
                        </span>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
        </section>

        <div class="cwm-footer">
          <span class="cwm-mono cwm-text-muted">
            GET /admin/collusion/*&nbsp;·&nbsp;Auto-refresh: 60s (24h-cadence worker)
          </span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import Icon from '@/components/Icon.vue'
/**
 * CollusionWorkerModal — Tier 3 observability (§pass28 Phase 5).
 *
 * 24h-cadence worker. Modal polls every 60s (longer than the standard 5s
 * for canary-tempo workers — data only changes once a day).
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import {
  getCollusionStatus,
  getCollusionRings,
  type CollusionStatusResponse,
  type CollusionRing,
} from '@/services/api/collusionWorker'
import { downloadCsv } from '@/components/common/csvExport'

dayjs.extend(relativeTime)

interface Props { workerId?: string }
const props = withDefaults(defineProps<Props>(), { workerId: 'collusion_worker' })
const emit = defineEmits<{ (e: 'close'): void }>()

const status = ref<CollusionStatusResponse | null>(null)
const rings = ref<CollusionRing[]>([])
const loadingStatus = ref(false)
const loadingRings = ref(false)
const statusError = ref('')
const ringsError = ref('')

const severityFilter = ref<'LOW' | 'MEDIUM' | 'HIGH' | null>(null)
const didFilter = ref<string | null>(null)
const sinceFilter = ref<'24h' | '7d' | '30d' | 'all'>('30d')
const expanded = ref<Set<number>>(new Set())
const autoRefresh = ref(true)

let refreshInterval: number | null = null

const hasRings24h = computed(() => (status.value?.summary.rings_24h ?? 0) > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'cwm-status-dot--bad'
  if (!status.value) return 'cwm-status-dot--muted'
  if (status.value.summary.errors_24h > 0) return 'cwm-status-dot--bad'
  if (status.value.summary.rings_24h > 0) return 'cwm-status-dot--warn'
  return 'cwm-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  if (status.value.summary.errors_24h > 0) return `${status.value.summary.errors_24h} errors`
  if (status.value.summary.rings_24h > 0) return `${status.value.summary.rings_24h} rings in 24h`
  return 'No new rings in 24h'
})

async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getCollusionStatus()
  } catch (e: any) {
    statusError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingStatus.value = false
  }
}
async function loadRings() {
  if (loadingRings.value) return
  loadingRings.value = true
  try {
    ringsError.value = ''
    const resp = await getCollusionRings({
      severity: severityFilter.value || undefined,
      agent_did: didFilter.value || undefined,
      since: sinceFilter.value,
      limit: 100,
    })
    rings.value = resp.rings
  } catch (e: any) {
    ringsError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingRings.value = false
  }
}
async function refreshAll() { await Promise.all([loadStatus(), loadRings()]) }

watch([severityFilter, didFilter, sinceFilter], () => { loadRings() })

function tick() {
  if (document.visibilityState === 'hidden') return
  refreshAll()
}
function startPolling() {
  if (refreshInterval !== null) return
  // 60s — 24h-cadence worker, no need for 5s polling.
  refreshInterval = window.setInterval(tick, 60_000)
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
function formatDate(iso?: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).format('YYYY-MM-DD')
}
function formatRel(iso?: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}
function truncate(s?: string | null, n = 12): string {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}
function sevPillClass(sev: string) {
  return {
    'cwm-state-pill--low':    sev === 'LOW',
    'cwm-state-pill--medium': sev === 'MEDIUM',
    'cwm-state-pill--high':   sev === 'HIGH',
    'cwm-state-pill--muted':  !['LOW', 'MEDIUM', 'HIGH'].includes(sev),
  }
}
function stageClass(s: string) {
  return {
    'cwm-state-pill--ok':    s === 'ok',
    'cwm-state-pill--high':  s === 'error',
    'cwm-state-pill--muted': s === 'never_run',
  }
}
function toggleExpand(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}
function filterByDid(did: string) {
  didFilter.value = didFilter.value === did ? null : did
}

function exportCsv() {
  const filename = `collusion-rings-${dayjs().format('YYYY-MM-DD-HHmm')}.csv`
  downloadCsv<CollusionRing>(
    rings.value,
    [
      { label: 'detected_at',       value: r => r.created_at || '' },
      { label: 'severity',          value: r => r.severity },
      { label: 'flagged_agent_did', value: r => r.flagged_agent_did },
      { label: 'scc_size',          value: r => r.scc_size?.toString() ?? '' },
      { label: 'score',             value: r => r.score?.toString() ?? '' },
      { label: 'members',           value: r => (r.members || []).join('|') },
      { label: 'flag_id',           value: r => r.id.toString() },
    ],
    filename,
  )
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.cwm-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.cwm-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.cwm-modal--errors {
  border-color: rgba(245, 158, 11, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(245, 158, 11, 0.2);
}

/* Header */
.cwm-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.cwm-header-left { display: flex; align-items: center; gap: 10px; }
.cwm-header-right { display: flex; align-items: center; gap: 8px; }
.cwm-title { font-size: 1.05rem; margin: 0; font-weight: 600; }
.cwm-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.cwm-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.cwm-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.cwm-status-dot--ok   { background: #10b981; color: #10b981; }
.cwm-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.cwm-status-dot--bad  { background: #ef4444; color: #ef4444; animation: cwm-pulse 1.8s infinite; }
.cwm-status-dot--muted { background: #4b5563; color: #4b5563; }
@keyframes cwm-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

/* Buttons */
.cwm-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
}
.cwm-btn:hover:not(:disabled) { background: rgba(0, 210, 210, 0.08); border-color: rgba(0, 210, 210, 0.45); }
.cwm-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.cwm-btn--ghost { background: transparent; }
.cwm-btn--inline { padding: 2px 8px; font-size: 0.72rem; }
.cwm-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.cwm-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

.cwm-link-btn {
  background: none; border: none; color: var(--nc-primary, #00d2d2); cursor: pointer;
  font: inherit; padding: 0; text-decoration: underline; font-family: ui-monospace, monospace;
}
.cwm-link-btn:hover { color: #5eead4; }

/* Stats */
.cwm-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.cwm-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.cwm-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.cwm-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.cwm-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.cwm-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.cwm-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

/* Cycle info rail */
.cwm-cycle-info {
  display: flex; flex-wrap: wrap; gap: 16px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10));
  font-family: ui-monospace, monospace;
}
.cwm-cycle-pair { display: inline-flex; flex-direction: column; gap: 1px; font-size: 0.78rem; min-width: 160px; }
.cwm-cycle-key { color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.62rem; }
.cwm-cycle-val { color: var(--nc-text, #e2e8f0); }

/* Sections */
.cwm-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.cwm-section:last-of-type { border-bottom: none; }
.cwm-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.cwm-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

/* Fleet */
.cwm-fleet-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.cwm-fleet-card {
  background: rgba(0, 210, 210, 0.02);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  border-radius: 8px;
  padding: 10px;
}
.cwm-fleet-card--warn { border-color: rgba(245, 158, 11, 0.45); }
.cwm-fleet-card--bad  { border-color: rgba(239, 68, 68, 0.55); }
.cwm-fleet-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.cwm-fleet-dot { width: 8px; height: 8px; border-radius: 50%; }
.cwm-fleet-dot--ok   { background: #10b981; box-shadow: 0 0 4px #10b981; }
.cwm-fleet-dot--warn { background: #f59e0b; box-shadow: 0 0 4px #f59e0b; }
.cwm-fleet-dot--bad  { background: #ef4444; box-shadow: 0 0 4px #ef4444; }
.cwm-fleet-name { font-weight: 600; font-size: 0.82rem; font-family: ui-monospace, monospace; }
.cwm-fleet-card-body { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.cwm-fleet-row { display: flex; justify-content: space-between; font-size: 0.74rem; font-family: ui-monospace, monospace; }
.cwm-fleet-key { color: var(--nc-muted, #94a3b8); }
.cwm-fleet-val { font-variant-numeric: tabular-nums; }

/* Rollup cards */
.cwm-rollup-cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.cwm-rollup-card {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 12px;
}
.cwm-rollup-h4 { font-size: 0.78rem; margin: 0 0 8px 0; font-weight: 600; }
.cwm-sev-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.cwm-sev-pill {
  font-family: ui-monospace, monospace; font-size: 0.74rem; font-weight: 700;
  padding: 3px 8px; border-radius: 5px;
}
.cwm-dids-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 3px; font-size: 0.74rem; }

/* Tabs / toolbar */
.cwm-tabs {
  display: flex;
  align-items: baseline;
  margin-bottom: 8px;
}
.cwm-tabs-right { margin-left: auto; }

/* Chips */
.cwm-chip-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }
.cwm-chip {
  padding: 4px 10px; font-size: 0.72rem; border-radius: 12px;
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  color: var(--nc-text, #e2e8f0); cursor: pointer;
}
.cwm-chip--active {
  background: rgba(0, 210, 210, 0.18);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}
.cwm-chip:hover { background: rgba(0, 210, 210, 0.12); }
.cwm-chip-sep { color: var(--nc-muted, #94a3b8); margin: 0 4px; }

/* Table */
.cwm-table-wrap { overflow-x: auto; }
.cwm-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.cwm-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.cwm-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.cwm-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }

.cwm-state-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.cwm-state-pill--ok      { background: rgba(16, 185, 129, 0.16); color: #34d399; }
.cwm-state-pill--low     { background: rgba(99, 102, 241, 0.16); color: #a5b4fc; }
.cwm-state-pill--medium  { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }
.cwm-state-pill--high    { background: rgba(239, 68, 68, 0.18); color: #f87171; }
.cwm-state-pill--muted   { background: rgba(255, 255, 255, 0.06); color: rgba(255, 255, 255, 0.55); }

.cwm-expanded-row { background: rgba(0, 210, 210, 0.03) !important; }
.cwm-members-list { display: flex; flex-wrap: wrap; gap: 6px; padding: 6px 0; }
.cwm-member-pill {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.32);
  padding: 3px 8px; border-radius: 5px;
}

/* Empty / loading */
.cwm-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.cwm-empty--muted { font-size: 0.82rem; }
.cwm-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: cwm-spin 0.8s linear infinite;
}
@keyframes cwm-spin { to { transform: rotate(360deg); } }

.cwm-banner {
  padding: 10px 14px; border-radius: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px;
}
.cwm-banner--bad {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

.cwm-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.cwm-text-muted { color: var(--nc-muted, #94a3b8); }
.cwm-text-warn  { color: #fbbf24; }
.cwm-text-bad   { color: #f87171; }
.cwm-text-ok    { color: #34d399; }

.cwm-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .cwm-stats-row { grid-template-columns: repeat(2, 1fr); }
  .cwm-modal { max-height: 92vh; }
  .cwm-cycle-info { gap: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  .cwm-status-dot--bad { animation: none; }
}
</style>
