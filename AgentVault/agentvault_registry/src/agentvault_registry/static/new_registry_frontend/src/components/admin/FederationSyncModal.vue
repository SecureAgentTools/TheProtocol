<template>
  <Teleport to="body">
    <div
      class="fsm-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="fsm-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="fsm-modal" :class="{ 'fsm-modal--errors': hasStalePeers || hasErrors }">
        <!-- Header -->
        <div class="fsm-header">
          <div class="fsm-header-left">
            <span class="fsm-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="fsm-modal-title" class="fsm-title">Federation Sync</h2>
            <span class="fsm-subtitle">{{ workerId }}</span>
          </div>
          <div class="fsm-header-right">
            <span v-if="status?.snapshot_iso" class="fsm-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="fsm-btn fsm-btn--ghost" @click="refreshAll" :disabled="loadingStatus">
              <span class="fsm-live-dot" :class="{ 'fsm-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="fsm-btn fsm-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="fsm-stats-row">
          <div class="fsm-stat">
            <span class="fsm-stat-label">Cycles 24h</span>
            <span class="fsm-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="fsm-stat-sub">every {{ status?.summary.interval_sec ?? '—' }}s</span>
          </div>
          <div class="fsm-stat" :class="{ 'fsm-stat--warn': hasStalePeers }">
            <span class="fsm-stat-label">Active peers</span>
            <span class="fsm-stat-value">{{ status?.summary.active_peers ?? '—' }} / {{ status?.summary.total_peers ?? '—' }}</span>
            <span class="fsm-stat-sub" :class="hasStalePeers ? 'fsm-text-warn' : ''">
              {{ status?.summary.stale_active_peers ?? '—' }} stale
            </span>
          </div>
          <div class="fsm-stat">
            <span class="fsm-stat-label">Registries</span>
            <span class="fsm-stat-value">{{ status?.summary.registries_reporting ?? '—' }}</span>
            <span class="fsm-stat-sub">reporting cycles</span>
          </div>
          <div class="fsm-stat" :class="{ 'fsm-stat--bad': hasErrors }">
            <span class="fsm-stat-label">Errors 24h</span>
            <span class="fsm-stat-value">{{ status?.summary.errors_24h ?? '—' }}</span>
            <span class="fsm-stat-sub">{{ !status ? '—' : hasErrors ? 'investigate' : 'all clean' }}</span>
          </div>
        </div>

        <!-- Per-registry rail -->
        <section class="fsm-section">
          <h3 class="fsm-section-title">
            Per-registry
            <span class="fsm-section-sub">last sync success + cycle duration via Prom labels</span>
          </h3>
          <div v-if="loadingStatus && !status" class="fsm-empty">
            <div class="fsm-spinner"></div>
            <p>Loading federation sync state…</p>
          </div>
          <div v-else-if="statusError" class="fsm-banner fsm-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="fsm-btn fsm-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status && status.per_registry.length === 0" class="fsm-empty fsm-empty--muted">
            <p>No registries reporting yet — first cycle may not have run.</p>
          </div>
          <div v-else-if="status" class="fsm-fleet-grid">
            <div
              v-for="r in status.per_registry"
              :key="r.registry_id"
              class="fsm-fleet-card"
              :class="registryCardClass(r)"
            >
              <div class="fsm-fleet-card-head">
                <span class="fsm-fleet-dot" :class="registryDotClass(r)"></span>
                <span class="fsm-fleet-name">{{ r.registry_id }}</span>
              </div>
              <div class="fsm-fleet-card-body">
                <div class="fsm-fleet-row"><span class="fsm-fleet-key">cycles 24h</span><span class="fsm-fleet-val">{{ r.cycles_24h }}</span></div>
                <div class="fsm-fleet-row"><span class="fsm-fleet-key">errors 24h</span><span class="fsm-fleet-val" :class="r.errors_24h > 0 ? 'fsm-text-bad' : ''">{{ r.errors_24h }}</span></div>
                <div class="fsm-fleet-row"><span class="fsm-fleet-key">last success</span><span class="fsm-fleet-val">{{ formatRel(r.last_success_iso) }}</span></div>
                <div class="fsm-fleet-row"><span class="fsm-fleet-key">last duration</span><span class="fsm-fleet-val">{{ (r.last_duration_ms / 1000).toFixed(1) }}s</span></div>
              </div>
            </div>
          </div>
          <div v-if="status && Object.keys(status.errors_by_reason).length > 0" class="fsm-errors-summary">
            <span class="fsm-errors-summary-label">Errors by reason (24h):</span>
            <span v-for="(n, rsn) in status.errors_by_reason" :key="rsn" class="fsm-err-pill">
              {{ rsn }}: {{ n }}
            </span>
          </div>
        </section>

        <!-- Peers table -->
        <section class="fsm-section">
          <div class="fsm-tabs">
            <h3 class="fsm-section-title">
              Peers
              <span class="fsm-section-sub">{{ status ? filteredPeers.length : '—' }} of {{ status?.per_peer.length ?? '—' }} · per-peer freshness + attempts</span>
            </h3>
            <div class="fsm-tabs-right">
              <button class="fsm-btn fsm-btn--ghost" @click="exportCsv" :disabled="filteredPeers.length === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <div class="fsm-chip-row">
            <button class="fsm-chip" :class="{ 'fsm-chip--active': statusFilter === null }" @click="statusFilter = null">All</button>
            <button class="fsm-chip" :class="{ 'fsm-chip--active': statusFilter === 'ACTIVE' }" @click="statusFilter = 'ACTIVE'">ACTIVE</button>
            <button class="fsm-chip" :class="{ 'fsm-chip--active': statusFilter === 'INACTIVE' }" @click="statusFilter = 'INACTIVE'">INACTIVE</button>
            <button class="fsm-chip" :class="{ 'fsm-chip--active': statusFilter === 'PENDING_APPROVAL' }" @click="statusFilter = 'PENDING_APPROVAL'">PENDING</button>
            <span class="fsm-chip-sep">|</span>
            <button class="fsm-chip" :class="{ 'fsm-chip--active': staleOnly }" @click="staleOnly = !staleOnly">Stale only</button>
          </div>

          <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
          <div v-else-if="!status" class="fsm-empty"><div class="fsm-spinner"></div><p>Loading federation sync state…</p></div>
          <div v-else-if="filteredPeers.length === 0" class="fsm-empty fsm-empty--muted">
            <p>No peers match the current filter.</p>
          </div>
          <div v-else class="fsm-table-wrap">
            <table class="fsm-table">
              <thead>
                <tr>
                  <th @click="sortBy('name')" class="fsm-sortable">Peer</th>
                  <th>Topology</th>
                  <th @click="sortBy('status')" class="fsm-sortable">Status</th>
                  <th @click="sortBy('seconds_since_card')" class="fsm-sortable" title="agent_cards.updated_at — canonical freshness signal">Cards last received</th>
                  <th @click="sortBy('seconds_since_sync')" class="fsm-sortable" title="peer_registries.last_synced_at — direct-sync only">Direct sync</th>
                  <th @click="sortBy('freshness')" class="fsm-sortable">Freshness</th>
                  <th>Cards</th>
                  <th>Success 24h</th>
                  <th>Errors 24h</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in filteredPeers" :key="p.id" :class="{ 'fsm-row--stale': p.freshness !== 'fresh' && p.status === 'ACTIVE' }">
                  <td class="fsm-mono" :title="p.base_url">{{ p.name }}</td>
                  <td class="fsm-mono">
                    <template v-if="p.is_chain_child">
                      <span class="fsm-chain-pill" :title="`Chain-discovered via direct peer ${p.parent_name}`">
                        chain via {{ p.parent_name || '?' }}
                      </span>
                    </template>
                    <template v-else>
                      <span class="fsm-direct-pill" title="Directly synced by federation_sync worker">direct</span>
                    </template>
                  </td>
                  <td>
                    <span class="fsm-state-pill" :class="statusPillClass(p.status)">{{ p.status }}</span>
                  </td>
                  <td class="fsm-mono" :class="cardFreshClass(p)">{{ formatRel(p.last_card_received_iso) }}</td>
                  <td class="fsm-mono fsm-text-muted">
                    <template v-if="p.is_chain_child">
                      <span title="Chain children don't receive direct syncs by design — cards flow via parent peer">—</span>
                    </template>
                    <template v-else>{{ formatRel(p.last_synced_iso) }}</template>
                  </td>
                  <td>
                    <span class="fsm-freshness-pill" :class="freshnessPillClass(p.freshness)">
                      {{ p.freshness }}
                    </span>
                  </td>
                  <td class="fsm-mono">{{ p.card_count }}</td>
                  <td class="fsm-mono">{{ p.attempts_24h.success }}</td>
                  <td class="fsm-mono" :class="p.attempts_24h.error > 0 ? 'fsm-text-warn' : ''">{{ p.attempts_24h.error }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Local cycle rail -->
        <section v-if="status?.local_last_cycle.last_cycle_iso" class="fsm-section fsm-cycle-info">
          <div class="fsm-cycle-pair">
            <span class="fsm-cycle-key">Last cycle</span>
            <span class="fsm-cycle-val fsm-mono">{{ formatRel(status.local_last_cycle.last_cycle_iso) }}</span>
          </div>
          <div class="fsm-cycle-pair">
            <span class="fsm-cycle-key">Duration</span>
            <span class="fsm-cycle-val fsm-mono">{{ (status.local_last_cycle.last_duration_ms / 1000).toFixed(1) }}s</span>
          </div>
          <div class="fsm-cycle-pair">
            <span class="fsm-cycle-key">Active peers</span>
            <span class="fsm-cycle-val fsm-mono">{{ status.local_last_cycle.active_peers }}</span>
          </div>
          <div class="fsm-cycle-pair">
            <span class="fsm-cycle-key">Success</span>
            <span class="fsm-cycle-val fsm-mono fsm-text-ok">{{ status.local_last_cycle.success_count }}</span>
          </div>
          <div class="fsm-cycle-pair">
            <span class="fsm-cycle-key">Errors</span>
            <span class="fsm-cycle-val fsm-mono" :class="status.local_last_cycle.error_count > 0 ? 'fsm-text-bad' : ''">{{ status.local_last_cycle.error_count }}</span>
          </div>
          <div class="fsm-cycle-pair">
            <span class="fsm-cycle-key">License-gated skipped</span>
            <span class="fsm-cycle-val fsm-mono">{{ status.local_last_cycle.license_gated_skipped }}</span>
          </div>
          <div v-if="status.local_last_cycle.cycle_error" class="fsm-cycle-pair fsm-cycle-pair--wide">
            <span class="fsm-cycle-key">Cycle error</span>
            <span class="fsm-cycle-val fsm-mono fsm-text-bad">{{ status.local_last_cycle.cycle_error }}</span>
          </div>
        </section>

        <div class="fsm-footer">
          <span class="fsm-mono fsm-text-muted">
            GET /admin/federation-sync/*&nbsp;·&nbsp;Auto-refresh: paused on tab-hidden
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
 * FederationSyncModal — Tier 3 observability (§pass29 Phase 6).
 *
 * Surfaces per-peer freshness + cycle health for the periodic federation
 * sync worker. Per-peer attempts come from
 * `federation_sync_peer_attempts_total` Prom counter (new in §pass29);
 * per-peer freshness from `peer_registries.last_synced_at` DB.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import {
  getFederationSyncStatus,
  type FedSyncStatusResponse,
  type FedRegistryRow,
  type FedPeerRow,
  type PeerFreshness,
} from '@/services/api/federationSync'
import { downloadCsv } from '@/components/common/csvExport'

dayjs.extend(relativeTime)

interface Props { workerId?: string }
const props = withDefaults(defineProps<Props>(), { workerId: 'federation_sync' })
const emit = defineEmits<{ (e: 'close'): void }>()

const status = ref<FedSyncStatusResponse | null>(null)
const loadingStatus = ref(false)
const statusError = ref('')

const statusFilter = ref<string | null>(null)
const staleOnly = ref(false)
const sortKey = ref<keyof FedPeerRow>('freshness')
const sortDir = ref<'asc' | 'desc'>('asc')
const autoRefresh = ref(true)

let refreshInterval: number | null = null

const hasStalePeers = computed(() => (status.value?.summary.stale_active_peers ?? 0) > 0)
const hasErrors = computed(() => (status.value?.summary.errors_24h ?? 0) > 0)

const statusDotClass = computed(() => {
  if (statusError.value) return 'fsm-status-dot--bad'
  if (!status.value) return 'fsm-status-dot--muted'
  if (hasErrors.value) return 'fsm-status-dot--bad'
  if (hasStalePeers.value) return 'fsm-status-dot--warn'
  return 'fsm-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  if (hasErrors.value) return `${status.value.summary.errors_24h} errors`
  if (hasStalePeers.value) return `${status.value.summary.stale_active_peers} stale peers`
  return 'All peers fresh'
})

const filteredPeers = computed(() => {
  if (!status.value) return []
  let list = [...status.value.per_peer]
  if (statusFilter.value) list = list.filter(p => p.status === statusFilter.value)
  if (staleOnly.value) {
    list = list.filter(p =>
      ['stale', 'very_stale', 'never'].includes(p.freshness)
      && p.status === 'ACTIVE'
    )
  }
  const k = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  // Freshness sort order: never > very_stale > stale > fresh (worst-first)
  const freshOrd: Record<PeerFreshness, number> = {
    fresh: 0, stale: 1, very_stale: 2, never: 3,
  } as Record<PeerFreshness, number>
  list.sort((a, b) => {
    let av: any = a[k]
    let bv: any = b[k]
    if (k === 'freshness') {
      av = freshOrd[av as PeerFreshness] ?? 0
      bv = freshOrd[bv as PeerFreshness] ?? 0
    }
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (av === bv) return 0
    return av < bv ? -1 * dir : 1 * dir
  })
  return list
})

function sortBy(k: keyof FedPeerRow) {
  if (sortKey.value === k) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = k
    sortDir.value = k === 'freshness' || k === 'seconds_since_sync' || k === 'health_check_failure_count' ? 'desc' : 'asc'
  }
}

async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getFederationSyncStatus()
  } catch (e: any) {
    statusError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingStatus.value = false
  }
}
async function refreshAll() { await loadStatus() }

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

function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).format('HH:mm:ss')
}
function formatRel(iso?: string | null): string {
  if (!iso) return 'never'
  return dayjs(iso).fromNow()
}
function registryCardClass(r: FedRegistryRow) {
  return { 'fsm-fleet-card--bad': r.errors_24h > 0 }
}
function registryDotClass(r: FedRegistryRow) {
  if (r.errors_24h > 0) return 'fsm-fleet-dot--warn'
  return 'fsm-fleet-dot--ok'
}
function statusPillClass(s: string) {
  return {
    'fsm-state-pill--ok':     s === 'ACTIVE',
    'fsm-state-pill--warn':   s === 'INACTIVE' || s === 'PENDING_APPROVAL' || s === 'SUSPENDED',
    'fsm-state-pill--bad':    s === 'REJECTED' || s === 'REVOKED',
    'fsm-state-pill--muted':  !['ACTIVE','INACTIVE','PENDING_APPROVAL','SUSPENDED','REJECTED','REVOKED'].includes(s),
  }
}
function freshnessPillClass(f: PeerFreshness) {
  return {
    'fsm-freshness-pill--fresh':      f === 'fresh',
    'fsm-freshness-pill--stale':      f === 'stale',
    'fsm-freshness-pill--very-stale': f === 'very_stale',
    'fsm-freshness-pill--never':      f === 'never',
  }
}
function cardFreshClass(p: FedPeerRow) {
  // Per-cell color emphasis for the cards-received column. The composite
  // freshness pill on the row is the source of truth; this just nudges the
  // cell text color so very-old cards stand out at a glance.
  const secs = p.seconds_since_card
  if (secs == null) return 'fsm-text-muted'
  if (secs > 86400) return 'fsm-text-warn'
  return ''
}

function exportCsv() {
  const filename = `federation-sync-peers-${dayjs().format('YYYY-MM-DD-HHmm')}.csv`
  downloadCsv<FedPeerRow>(
    filteredPeers.value,
    [
      { label: 'name',                 value: p => p.name },
      { label: 'base_url',             value: p => p.base_url },
      { label: 'status',               value: p => p.status },
      { label: 'last_synced_iso',      value: p => p.last_synced_iso || '' },
      { label: 'seconds_since_sync',   value: p => p.seconds_since_sync?.toString() ?? '' },
      { label: 'freshness',            value: p => p.freshness },
      { label: 'success_24h',          value: p => p.attempts_24h.success.toString() },
      { label: 'error_24h',            value: p => p.attempts_24h.error.toString() },
      { label: 'health_check_failures', value: p => p.health_check_failure_count.toString() },
      { label: 'last_health_check_iso', value: p => p.last_health_check_attempt_iso || '' },
    ],
    filename,
  )
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.fsm-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.fsm-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.fsm-modal--errors {
  border-color: rgba(245, 158, 11, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(245, 158, 11, 0.2);
}

/* Header */
.fsm-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.fsm-header-left { display: flex; align-items: center; gap: 10px; }
.fsm-header-right { display: flex; align-items: center; gap: 8px; }
.fsm-title { font-size: 1.05rem; margin: 0; font-weight: 600; }
.fsm-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.fsm-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.fsm-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.fsm-status-dot--ok   { background: #10b981; color: #10b981; }
.fsm-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.fsm-status-dot--bad  { background: #ef4444; color: #ef4444; animation: fsm-pulse 1.8s infinite; }
.fsm-status-dot--muted { background: #4b5563; color: #4b5563; }
@keyframes fsm-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

.fsm-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
}
.fsm-btn:hover:not(:disabled) { background: rgba(0, 210, 210, 0.08); border-color: rgba(0, 210, 210, 0.45); }
.fsm-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.fsm-btn--ghost { background: transparent; }
.fsm-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.fsm-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

/* Stats */
.fsm-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.fsm-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.fsm-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.fsm-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.fsm-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.fsm-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.fsm-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

/* Sections */
.fsm-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.fsm-section:last-of-type { border-bottom: none; }
.fsm-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.fsm-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

/* Fleet */
.fsm-fleet-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.fsm-fleet-card {
  background: rgba(0, 210, 210, 0.02);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  border-radius: 8px;
  padding: 10px;
}
.fsm-fleet-card--bad { border-color: rgba(239, 68, 68, 0.55); }
.fsm-fleet-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.fsm-fleet-dot { width: 8px; height: 8px; border-radius: 50%; }
.fsm-fleet-dot--ok   { background: #10b981; box-shadow: 0 0 4px #10b981; }
.fsm-fleet-dot--warn { background: #f59e0b; box-shadow: 0 0 4px #f59e0b; }
.fsm-fleet-name { font-weight: 600; font-size: 0.82rem; font-family: ui-monospace, monospace; }
.fsm-fleet-card-body { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.fsm-fleet-row { display: flex; justify-content: space-between; font-size: 0.74rem; font-family: ui-monospace, monospace; }
.fsm-fleet-key { color: var(--nc-muted, #94a3b8); }
.fsm-fleet-val { font-variant-numeric: tabular-nums; }

/* Errors summary */
.fsm-errors-summary {
  margin-top: 12px;
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  font-family: ui-monospace, monospace; font-size: 0.72rem;
}
.fsm-errors-summary-label { color: var(--nc-muted, #94a3b8); }
.fsm-err-pill {
  background: rgba(245, 158, 11, 0.10);
  border: 1px solid rgba(245, 158, 11, 0.32);
  color: #fbbf24;
  padding: 2px 8px; border-radius: 4px;
}

/* Tabs / toolbar */
.fsm-tabs {
  display: flex;
  align-items: baseline;
  margin-bottom: 8px;
}
.fsm-tabs-right { margin-left: auto; }

/* Chips */
.fsm-chip-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; align-items: center; }
.fsm-chip {
  padding: 4px 10px; font-size: 0.72rem; border-radius: 12px;
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  color: var(--nc-text, #e2e8f0); cursor: pointer;
}
.fsm-chip--active {
  background: rgba(0, 210, 210, 0.18);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}
.fsm-chip:hover { background: rgba(0, 210, 210, 0.12); }
.fsm-chip-sep { color: var(--nc-muted, #94a3b8); margin: 0 4px; }

/* Table */
.fsm-table-wrap { overflow-x: auto; }
.fsm-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.fsm-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.fsm-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.fsm-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }
.fsm-table tr.fsm-row--stale { background: rgba(245, 158, 11, 0.05); }
.fsm-sortable { cursor: pointer; user-select: none; }
.fsm-sortable:hover { color: var(--nc-primary, #00d2d2); }

.fsm-state-pill, .fsm-freshness-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.fsm-state-pill--ok    { background: rgba(16, 185, 129, 0.16); color: #34d399; }
.fsm-state-pill--warn  { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }
.fsm-state-pill--bad   { background: rgba(239, 68, 68, 0.18); color: #f87171; }
.fsm-state-pill--muted { background: rgba(255, 255, 255, 0.06); color: rgba(255, 255, 255, 0.55); }

.fsm-freshness-pill--fresh      { background: rgba(16, 185, 129, 0.16); color: #34d399; }
.fsm-freshness-pill--stale      { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }
.fsm-freshness-pill--very-stale { background: rgba(239, 68, 68, 0.16); color: #f87171; }
.fsm-freshness-pill--never      { background: rgba(99, 102, 241, 0.16); color: #a5b4fc; }

/* Topology pills — §pass30 chain-vs-direct labelling */
.fsm-direct-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase;
  background: rgba(0, 210, 210, 0.14);
  color: var(--nc-primary, #00d2d2);
  border: 1px solid rgba(0, 210, 210, 0.32);
}
.fsm-chain-pill {
  display: inline-block;
  padding: 2px 8px; border-radius: 8px;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: lowercase;
  background: rgba(168, 85, 247, 0.12);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.32);
}

/* Cycle info rail */
.fsm-cycle-info {
  display: flex; flex-wrap: wrap; gap: 16px;
  font-family: ui-monospace, monospace;
}
.fsm-cycle-pair { display: inline-flex; flex-direction: column; gap: 1px; font-size: 0.78rem; min-width: 130px; }
.fsm-cycle-pair--wide { flex: 1; min-width: 280px; }
.fsm-cycle-key { color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.62rem; }
.fsm-cycle-val { color: var(--nc-text, #e2e8f0); }

/* Empty / loading */
.fsm-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.fsm-empty--muted { font-size: 0.82rem; }
.fsm-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: fsm-spin 0.8s linear infinite;
}
@keyframes fsm-spin { to { transform: rotate(360deg); } }

.fsm-banner {
  padding: 10px 14px; border-radius: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px;
}
.fsm-banner--bad {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

.fsm-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.fsm-text-muted { color: var(--nc-muted, #94a3b8); }
.fsm-text-warn  { color: #fbbf24; }
.fsm-text-bad   { color: #f87171; }
.fsm-text-ok    { color: #34d399; }

.fsm-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .fsm-stats-row { grid-template-columns: repeat(2, 1fr); }
  .fsm-modal { max-height: 92vh; }
}

@media (prefers-reduced-motion: reduce) {
  .fsm-status-dot--bad { animation: none; }
}
</style>
