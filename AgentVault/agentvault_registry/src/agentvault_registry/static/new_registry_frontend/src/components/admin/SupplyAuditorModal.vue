<template>
  <Teleport to="body">
    <div
      class="sam-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sam-modal-title"
      @click.self="emit('close')"
      tabindex="-1"
    >
      <div class="sam-modal" :class="{ 'sam-modal--errors': hasBreach }">
        <!-- Header -->
        <div class="sam-header">
          <div class="sam-header-left">
            <span class="sam-status-dot" :class="statusDotClass" :title="statusLabel"></span>
            <h2 id="sam-modal-title" class="sam-title">Supply Auditor</h2>
            <span class="sam-subtitle">{{ workerId }}</span>
          </div>
          <div class="sam-header-right">
            <span v-if="status?.snapshot_iso" class="sam-last-snap" :title="status.snapshot_iso">
              snapshot {{ formatTime(status.snapshot_iso) }}
            </span>
            <button class="sam-btn sam-btn--ghost" @click="refreshAll" :disabled="loadingStatus || loadingEvents">
              <span class="sam-live-dot" :class="{ 'sam-live-dot--on': autoRefresh }"></span>
              ↻ Refresh
            </button>
            <button class="sam-btn sam-btn--ghost" @click="emit('close')" aria-label="Close">✕</button>
          </div>
        </div>

        <!-- Top stats -->
        <div class="sam-stats-row">
          <div class="sam-stat" :class="invariantStatClass">
            <span class="sam-stat-label">Invariant</span>
            <span class="sam-stat-value sam-stat-value--small">{{ status?.summary.live_status || '—' }}</span>
            <span class="sam-stat-sub">|Δ| {{ formatAvt(status?.summary.live_delta) }}</span>
          </div>
          <div class="sam-stat">
            <span class="sam-stat-label">Cycles 24h</span>
            <span class="sam-stat-value">{{ status?.summary.cycles_24h ?? '—' }}</span>
            <span class="sam-stat-sub">across {{ status?.summary.registries_reporting ?? '—' }} registries</span>
          </div>
          <div class="sam-stat" :class="{ 'sam-stat--bad': (status?.summary.breaches_24h ?? 0) > 0 }">
            <span class="sam-stat-label">Breaches 24h</span>
            <span class="sam-stat-value">{{ status?.summary.breaches_24h ?? '—' }}</span>
            <span class="sam-stat-sub">{{ !status ? '—' : (status.summary.breaches_24h ?? 0) === 0 ? 'invariant holds' : 'INVESTIGATE' }}</span>
          </div>
          <div class="sam-stat" :class="{ 'sam-stat--warn': (status?.summary.errors_24h ?? 0) > 5 }">
            <span class="sam-stat-label">Errors 24h</span>
            <span class="sam-stat-value">{{ status?.summary.errors_24h ?? '—' }}</span>
            <span class="sam-stat-sub">audit-fetch failures</span>
          </div>
        </div>

        <!-- Live invariant readout -->
        <section v-if="status?.live_audit" class="sam-section sam-live">
          <h3 class="sam-section-title">
            Live invariant
            <span class="sam-section-sub">authoritative read from EventStore /projections/supply-audit</span>
          </h3>
          <div class="sam-live-grid">
            <div class="sam-live-cell">
              <div class="sam-live-label">net_supply</div>
              <div class="sam-live-val">{{ formatAvt(status.live_audit.net_supply) }}</div>
              <div class="sam-live-sub">issued − destroyed</div>
            </div>
            <div class="sam-live-cell">
              <div class="sam-live-label">circulating</div>
              <div class="sam-live-val">{{ formatAvt(status.live_audit.total_circulating) }}</div>
              <div class="sam-live-sub">all agent + treasury balances</div>
            </div>
            <div class="sam-live-cell" :class="{ 'sam-live-cell--bad': liveAbsDelta > 0 }">
              <div class="sam-live-label">|Δ|</div>
              <div class="sam-live-val">{{ formatAvt(liveAbsDelta) }}</div>
              <div class="sam-live-sub">tolerance: 0.0 {{ localCurrency }}</div>
            </div>
            <div class="sam-live-cell">
              <div class="sam-live-label">tokens_issued</div>
              <div class="sam-live-val">{{ formatAvt(status.live_audit.tokens_issued) }}</div>
              <div class="sam-live-sub">snapshot baseline + Issued + corrections</div>
            </div>
            <div class="sam-live-cell">
              <div class="sam-live-label">tokens_destroyed</div>
              <div class="sam-live-val">{{ formatAvt(status.live_audit.tokens_destroyed) }}</div>
              <div class="sam-live-sub">burns + negative corrections</div>
            </div>
            <div class="sam-live-cell">
              <div class="sam-live-label">fees collected</div>
              <div class="sam-live-val">{{ formatAvt(status.live_audit.tokens_fees_collected) }}</div>
              <div class="sam-live-sub">net circulation unchanged</div>
            </div>
          </div>
        </section>

        <!-- Per-registry rail -->
        <section class="sam-section">
          <h3 class="sam-section-title">
            Per-registry
            <span class="sam-section-sub">each registry runs its own auditor cycle every 60s</span>
          </h3>
          <div v-if="loadingStatus && !status" class="sam-empty">
            <div class="sam-spinner"></div>
            <p>Loading auditor state…</p>
          </div>
          <div v-else-if="statusError" class="sam-banner sam-banner--bad">
            <Icon name="mdi:alert" /> {{ statusError }}
            <button class="sam-btn sam-btn--ghost" @click="loadStatus">Retry</button>
          </div>
          <div v-else-if="status && status.per_registry.length === 0" class="sam-empty sam-empty--muted">
            <p>No registries reporting yet — wait for the first cycle (≤60s).</p>
          </div>
          <div v-else-if="status" class="sam-fleet-grid">
            <div
              v-for="r in status.per_registry"
              :key="r.registry_id"
              class="sam-fleet-card"
              :class="registryCardClass(r)"
            >
              <div class="sam-fleet-card-head">
                <span class="sam-fleet-dot" :class="registryDotClass(r)"></span>
                <span class="sam-fleet-name">{{ r.registry_id }}</span>
                <span v-if="r.breaches_24h > 0" class="sam-pill sam-pill--bad">BREACH</span>
                <span v-else-if="(r.last_delta ?? 0) > 0" class="sam-pill sam-pill--warn">Δ&gt;0</span>
                <span v-else class="sam-pill sam-pill--ok">OK</span>
              </div>
              <div class="sam-fleet-card-body">
                <div class="sam-fleet-row"><span class="sam-fleet-key">cycles 24h</span><span class="sam-fleet-val">{{ r.cycles_24h }}</span></div>
                <div class="sam-fleet-row"><span class="sam-fleet-key">breaches 24h</span><span class="sam-fleet-val" :class="r.breaches_24h > 0 ? 'sam-text-bad' : ''">{{ r.breaches_24h }}</span></div>
                <div class="sam-fleet-row"><span class="sam-fleet-key">|Δ| last</span><span class="sam-fleet-val" :class="(r.last_delta ?? 0) > 0 ? 'sam-text-warn' : ''">{{ formatAvt(r.last_delta) }}</span></div>
                <div class="sam-fleet-row"><span class="sam-fleet-key">net_supply</span><span class="sam-fleet-val">{{ formatAvt(r.net_supply) }}</span></div>
                <div class="sam-fleet-row"><span class="sam-fleet-key">circulating</span><span class="sam-fleet-val">{{ formatAvt(r.total_circulating) }}</span></div>
                <div class="sam-fleet-row"><span class="sam-fleet-key">errors 24h</span><span class="sam-fleet-val" :class="r.errors_24h > 5 ? 'sam-text-warn' : ''">{{ r.errors_24h }}</span></div>
              </div>
            </div>
          </div>
          <div v-if="status && Object.keys(status.errors_by_reason).length > 0" class="sam-errors-summary">
            <span class="sam-errors-summary-label">Errors by reason (24h):</span>
            <span v-for="(n, rsn) in status.errors_by_reason" :key="rsn" class="sam-err-pill">
              {{ rsn }}: {{ n }}
            </span>
          </div>
        </section>

        <!-- Tabs -->
        <section class="sam-section">
          <div class="sam-tabs">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              class="sam-tab"
              :class="{ 'sam-tab--active': activeTab === tab.id }"
              type="button"
              @click="activeTab = tab.id"
            >
              {{ tab.label }}
            </button>
            <div class="sam-tabs-right">
              <button class="sam-btn sam-btn--ghost" @click="exportCsv" :disabled="events.length === 0">
                ⇩ CSV
              </button>
            </div>
          </div>

          <!-- Breach history tab -->
          <div v-if="activeTab === 'breaches'" class="sam-activity">
            <div v-if="loadingEvents && events.length === 0" class="sam-empty">
              <div class="sam-spinner"></div>
              <p>Loading breach history…</p>
            </div>
            <div v-else-if="eventsError" class="sam-banner sam-banner--bad">
              <Icon name="mdi:alert" /> {{ eventsError }}
              <button class="sam-btn sam-btn--ghost" @click="loadEvents">Retry</button>
            </div>
            <div v-else-if="events.length === 0" class="sam-empty sam-empty--muted">
              <p>No SupplyInvariantBreach events on record — invariant has held since EventStore inception.</p>
            </div>
            <div v-else class="sam-table-wrap">
              <table class="sam-table">
                <thead>
                  <tr>
                    <th>Detected</th>
                    <th>|Δ|</th>
                    <th>net_supply</th>
                    <th>circulating</th>
                    <th>issued</th>
                    <th>destroyed</th>
                    <th>lockdown</th>
                    <th>type</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="e in events" :key="e.event_id || ''">
                    <td class="sam-mono">{{ formatTime(e.detected_at || e.timestamp) }}</td>
                    <td class="sam-mono sam-text-bad">{{ formatAvt(e.delta) }}</td>
                    <td class="sam-mono">{{ formatAvt(e.net_supply) }}</td>
                    <td class="sam-mono">{{ formatAvt(e.total_circulating) }}</td>
                    <td class="sam-mono">{{ formatAvt(e.tokens_issued) }}</td>
                    <td class="sam-mono">{{ formatAvt(e.tokens_destroyed) }}</td>
                    <td class="sam-mono">
                      <span :class="e.auto_lockdown ? 'sam-text-bad' : 'sam-text-muted'">
                        {{ e.auto_lockdown ? 'YES' : 'no' }}
                      </span>
                    </td>
                    <td class="sam-mono sam-text-muted">{{ e.audit_type || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Local cycle tab -->
          <div v-else-if="activeTab === 'local'" class="sam-local">
            <p class="sam-text-muted" style="margin: 0 0 12px 0; font-size: 0.78rem">
              The most-recent audit cycle recorded by the registry process
              serving this request. The fleet grid above aggregates Prometheus
              across all registries; this shows the local in-memory cache —
              freshest by definition, but represents only one registry's view.
            </p>
            <ReadFailedNotice v-if="!status && statusError" dense :retry="loadStatus" />
            <div v-else-if="!status" class="sam-empty"><div class="sam-spinner"></div><p>Loading auditor state…</p></div>
            <div v-else-if="!status.local_last_cycle.last_audit_iso" class="sam-empty sam-empty--muted">
              <p>No local cycle recorded yet (worker may have just started).</p>
            </div>
            <div v-else class="sam-live-grid">
              <div class="sam-live-cell">
                <div class="sam-live-label">last_audit</div>
                <div class="sam-live-val sam-mono">{{ formatTime(status.local_last_cycle.last_audit_iso) }}</div>
              </div>
              <div class="sam-live-cell" :class="status.local_last_cycle.status === 'BREACH' ? 'sam-live-cell--bad' : ''">
                <div class="sam-live-label">status</div>
                <div class="sam-live-val">{{ status.local_last_cycle.status || '—' }}</div>
              </div>
              <div class="sam-live-cell">
                <div class="sam-live-label">|Δ| last</div>
                <div class="sam-live-val">{{ formatAvt(status.local_last_cycle.delta) }}</div>
              </div>
              <div class="sam-live-cell">
                <div class="sam-live-label">net_supply</div>
                <div class="sam-live-val">{{ formatAvt(status.local_last_cycle.net_supply) }}</div>
              </div>
              <div class="sam-live-cell">
                <div class="sam-live-label">circulating</div>
                <div class="sam-live-val">{{ formatAvt(status.local_last_cycle.total_circulating) }}</div>
              </div>
              <div class="sam-live-cell" :class="status.local_last_cycle.consecutive_failures >= 3 ? 'sam-live-cell--warn' : ''">
                <div class="sam-live-label">consec failures</div>
                <div class="sam-live-val">{{ status.local_last_cycle.consecutive_failures }}</div>
              </div>
            </div>
          </div>

          <!-- How it works tab -->
          <div v-else-if="activeTab === 'about'" class="sam-about">
            <h4 class="sam-h4">Self-consistent supply invariant (f037 / Option 4)</h4>
            <p class="sam-prose">
              Every 60 seconds, each registry's <code>supply_auditor</code> polls
              <code>/api/v1/projections/supply-audit</code> on its frame's EventStore.
              The EventStore computes:
            </p>
            <pre class="sam-pre">tokens_issued − tokens_destroyed + transit_net == total_circulating</pre>
            <p class="sam-prose">
              <strong>tokens_issued</strong> = snapshot baseline + <code>TokensIssued</code> +
              positive <code>BalanceCorrected</code> + <code>DisputeCompensationMinted</code><br/>
              <strong>total_circulating</strong> = sum of all agent liquid + locked +
              treasury + fee_collector balances from the EventStore projection<br/>
              <strong>tokens_destroyed</strong> = burns + negative <code>BalanceCorrected</code>
            </p>
            <p class="sam-prose">
              Fees are zero-sum (deducted from sender, credited to fee_collector) so net
              circulation doesn't change. Tolerance is <strong>0.0 {{ localCurrency }}</strong> —
              any deviation is treated as a breach.
            </p>
            <h4 class="sam-h4">When breach fires</h4>
            <p class="sam-prose">
              The worker emits <code>SupplyInvariantBreach</code> to the EventStore +
              dispatches an email via the Sovereign theme. If
              <code>FEDERATION_ENFORCEMENT_ACTIVE=true</code>, it also calls
              <code>/api/v1/system/lockdown</code> to halt the EventStore — currently
              <strong>NOT active in beta</strong> (monitoring only).
            </p>
          </div>
        </section>

        <div class="sam-footer">
          <span class="sam-mono sam-text-muted">
            GET /admin/supply-auditor/*&nbsp;·&nbsp;Auto-refresh: paused on tab-hidden
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
 * SupplyAuditorModal — Tier 3 observability (§pass28 Phase 4).
 *
 * Aggregates BOTH Frame A registry-a and Frame B frame-b-registry via Prom
 * `registry_id`. The worker polls each frame's EventStore /supply-audit
 * authoritatively — this modal wraps that read with worker-cycle context.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import dayjs from 'dayjs'
import {
  getSupplyAuditorStatus,
  getSupplyAuditorEvents,
  type SupplyStatusResponse,
  type SupplyBreachEvent,
  type SupplyRegistryRow,
} from '@/services/api/supplyAuditor'
import { downloadCsv } from '@/components/common/csvExport'
import { useCurrency } from '@/composables/useCurrency'

// D6-835: the audit counts this frame's ledger, in its unit
const { localCurrency } = useCurrency()

interface Props { workerId?: string }
const props = withDefaults(defineProps<Props>(), { workerId: 'supply_auditor' })
const emit = defineEmits<{ (e: 'close'): void }>()

// State
const status = ref<SupplyStatusResponse | null>(null)
const events = ref<SupplyBreachEvent[]>([])
const loadingStatus = ref(false)
const loadingEvents = ref(false)
const statusError = ref('')
const eventsError = ref('')

const activeTab = ref<'breaches' | 'local' | 'about'>('breaches')
const autoRefresh = ref(true)

let refreshInterval: number | null = null

const tabs: { id: 'breaches' | 'local' | 'about'; label: string }[] = [
  { id: 'breaches', label: 'Breach History' },
  { id: 'local',    label: 'Local Cycle' },
  { id: 'about',    label: 'How it Works' },
]

// Derived
const hasBreach = computed(() => (status.value?.summary.breaches_24h ?? 0) > 0)

const liveAbsDelta = computed(() => {
  const v = status.value?.live_audit?.delta
  if (v === null || v === undefined) return 0
  return Math.abs(parseFloat(String(v)))
})

const statusDotClass = computed(() => {
  if (statusError.value) return 'sam-status-dot--bad'
  if (!status.value) return 'sam-status-dot--muted'
  if (status.value.summary.breaches_24h > 0) return 'sam-status-dot--bad'
  if (liveAbsDelta.value > 0) return 'sam-status-dot--warn'
  return 'sam-status-dot--ok'
})

const statusLabel = computed(() => {
  if (statusError.value) return 'Status query failed'
  if (!status.value) return 'Loading…'
  if (status.value.summary.breaches_24h > 0) return `${status.value.summary.breaches_24h} breaches in 24h`
  if (liveAbsDelta.value > 0) return `|Δ| = ${liveAbsDelta.value} (tolerance 0)`
  return 'Invariant holds'
})

const invariantStatClass = computed(() => {
  const s = status.value?.summary.live_status
  if (s === 'BREACH') return 'sam-stat--bad'
  if (liveAbsDelta.value > 0) return 'sam-stat--warn'
  return ''
})

// Loaders
async function loadStatus() {
  if (loadingStatus.value) return
  loadingStatus.value = true
  try {
    statusError.value = ''
    status.value = await getSupplyAuditorStatus()
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
    const resp = await getSupplyAuditorEvents(100)
    events.value = resp.events
  } catch (e: any) {
    eventsError.value = e?.response?.data?.detail || (e instanceof Error ? e.message : String(e))
  } finally {
    loadingEvents.value = false
  }
}
async function refreshAll() { await Promise.all([loadStatus(), loadEvents()]) }

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
function formatAvt(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (!Number.isFinite(n)) return String(v)
  const abs = Math.abs(n)
  if (abs >= 1_000_000_000) return (n / 1_000_000_000).toFixed(3) + 'B'
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (abs >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}
function registryCardClass(r: SupplyRegistryRow) {
  return {
    'sam-fleet-card--bad':  r.breaches_24h > 0,
    'sam-fleet-card--warn': r.breaches_24h === 0 && (r.last_delta ?? 0) > 0,
  }
}
function registryDotClass(r: SupplyRegistryRow) {
  if (r.breaches_24h > 0) return 'sam-fleet-dot--bad'
  if ((r.last_delta ?? 0) > 0) return 'sam-fleet-dot--warn'
  return 'sam-fleet-dot--ok'
}

function exportCsv() {
  const filename = `supply-auditor-breaches-${dayjs().format('YYYY-MM-DD-HHmm')}.csv`
  downloadCsv<SupplyBreachEvent>(
    events.value,
    [
      { label: 'detected_at',       value: e => e.detected_at || e.timestamp || '' },
      { label: 'delta',             value: e => e.delta || '' },
      { label: 'net_supply',        value: e => e.net_supply || '' },
      { label: 'total_circulating', value: e => e.total_circulating || '' },
      { label: 'tokens_issued',     value: e => e.tokens_issued || '' },
      { label: 'tokens_destroyed',  value: e => e.tokens_destroyed || '' },
      { label: 'tokens_fees',       value: e => e.tokens_fees || '' },
      { label: 'tolerance',         value: e => e.tolerance || '' },
      { label: 'auto_lockdown',     value: e => e.auto_lockdown ? 'true' : 'false' },
      { label: 'audit_type',        value: e => e.audit_type || '' },
    ],
    filename,
  )
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => true, () => emit('close'))
</script>

<style scoped>
.sam-overlay {
  position: fixed; inset: 0; z-index: 10100;
  display: flex; align-items: flex-start; justify-content: center;
  padding: 4vh 2vw;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(6px);
  overflow-y: auto;
}
.sam-modal {
  background: var(--nc-bg-deep, #0a0e14);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.25));
  border-radius: 12px;
  width: 100%;
  max-width: 1280px;
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(0, 210, 210, 0.08);
  display: flex; flex-direction: column;
  color: var(--nc-text, #e2e8f0);
}
.sam-modal--errors {
  border-color: rgba(239, 68, 68, 0.45);
  box-shadow: 0 12px 64px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(239, 68, 68, 0.2);
}

/* Header */
.sam-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
  gap: 12px;
}
.sam-header-left { display: flex; align-items: center; gap: 10px; }
.sam-header-right { display: flex; align-items: center; gap: 8px; }
.sam-title { font-size: 1.05rem; margin: 0; font-weight: 600; }
.sam-subtitle { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.sam-last-snap { font-size: 0.74rem; color: var(--nc-muted, #94a3b8); font-family: ui-monospace, monospace; }
.sam-status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  box-shadow: 0 0 8px currentColor;
}
.sam-status-dot--ok   { background: #10b981; color: #10b981; }
.sam-status-dot--warn { background: #f59e0b; color: #f59e0b; }
.sam-status-dot--bad  { background: #ef4444; color: #ef4444; animation: sam-pulse 1.8s infinite; }
.sam-status-dot--muted { background: #4b5563; color: #4b5563; }
@keyframes sam-pulse {
  0%, 100% { box-shadow: 0 0 8px currentColor; }
  50%      { box-shadow: 0 0 16px currentColor; }
}

/* Buttons */
.sam-btn {
  padding: 5px 10px; font-size: 0.78rem; border-radius: 6px; cursor: pointer;
  background: transparent; color: var(--nc-text, #e2e8f0);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.18));
}
.sam-btn:hover:not(:disabled) { background: rgba(0, 210, 210, 0.08); border-color: rgba(0, 210, 210, 0.45); }
.sam-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.sam-btn--ghost { background: transparent; }
.sam-live-dot {
  display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: #4b5563; margin-right: 4px;
}
.sam-live-dot--on { background: #10b981; box-shadow: 0 0 6px #10b981; }

/* Stats */
.sam-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
}
.sam-stat {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.sam-stat--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.32); }
.sam-stat--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.sam-stat-label { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em; }
.sam-stat-value { font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.sam-stat-value--small { font-size: 1.1rem; }
.sam-stat-sub   { font-size: 0.72rem; color: var(--nc-muted, #94a3b8); }

/* Sections */
.sam-section { padding: 14px 20px; border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.10)); }
.sam-section:last-of-type { border-bottom: none; }
.sam-section-title { font-size: 0.82rem; font-weight: 600; margin: 0 0 10px 0; display: flex; align-items: baseline; gap: 8px; }
.sam-section-sub { font-size: 0.7rem; color: var(--nc-muted, #94a3b8); font-weight: 400; }

/* Live invariant grid */
.sam-live-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}
.sam-live-cell {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.16);
  border-radius: 8px; padding: 12px;
  display: flex; flex-direction: column; gap: 3px;
}
.sam-live-cell--warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.35); }
.sam-live-cell--bad  { background: rgba(239, 68, 68, 0.10); border-color: rgba(239, 68, 68, 0.45); }
.sam-live-label { font-size: 0.64rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--nc-muted, #94a3b8); }
.sam-live-val   { font-size: 1.15rem; font-weight: 700; font-variant-numeric: tabular-nums; font-family: ui-monospace, monospace; }
.sam-live-sub   { font-size: 0.68rem; color: var(--nc-muted, #94a3b8); }

/* Fleet */
.sam-fleet-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
}
.sam-fleet-card {
  background: rgba(0, 210, 210, 0.02);
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  border-radius: 8px;
  padding: 10px;
}
.sam-fleet-card--warn { border-color: rgba(245, 158, 11, 0.45); }
.sam-fleet-card--bad  { border-color: rgba(239, 68, 68, 0.55); }
.sam-fleet-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.sam-fleet-dot { width: 8px; height: 8px; border-radius: 50%; }
.sam-fleet-dot--ok   { background: #10b981; box-shadow: 0 0 4px #10b981; }
.sam-fleet-dot--warn { background: #f59e0b; box-shadow: 0 0 4px #f59e0b; }
.sam-fleet-dot--bad  { background: #ef4444; box-shadow: 0 0 4px #ef4444; }
.sam-fleet-name { font-weight: 600; font-size: 0.82rem; font-family: ui-monospace, monospace; flex: 1; }
.sam-pill {
  font-size: 0.6rem; font-weight: 700; padding: 1px 7px; border-radius: 4px;
  letter-spacing: 0.05em;
}
.sam-pill--ok   { background: rgba(16, 185, 129, 0.16); color: #34d399; }
.sam-pill--warn { background: rgba(245, 158, 11, 0.16); color: #fbbf24; }
.sam-pill--bad  { background: rgba(239, 68, 68, 0.18); color: #f87171; }
.sam-fleet-card-body { display: flex; flex-direction: column; gap: 2px; margin-top: 4px; }
.sam-fleet-row { display: flex; justify-content: space-between; font-size: 0.74rem; font-family: ui-monospace, monospace; }
.sam-fleet-key { color: var(--nc-muted, #94a3b8); }
.sam-fleet-val { font-variant-numeric: tabular-nums; }

.sam-errors-summary {
  margin-top: 12px;
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  font-family: ui-monospace, monospace; font-size: 0.72rem;
}
.sam-errors-summary-label { color: var(--nc-muted, #94a3b8); }
.sam-err-pill {
  background: rgba(245, 158, 11, 0.10);
  border: 1px solid rgba(245, 158, 11, 0.32);
  color: #fbbf24;
  padding: 2px 8px; border-radius: 4px;
}

/* Tabs */
.sam-tabs {
  display: flex;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  margin: -6px -20px 12px -20px;
  padding: 0 20px;
  align-items: center;
}
.sam-tabs-right { margin-left: auto; padding-bottom: 6px; }
.sam-tab {
  background: transparent; border: none; color: var(--nc-muted, #94a3b8);
  padding: 8px 14px; cursor: pointer; font-size: 0.8rem;
  border-bottom: 2px solid transparent;
}
.sam-tab--active { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.sam-tab:hover { color: var(--nc-text, #e2e8f0); }

/* Table */
.sam-table-wrap { overflow-x: auto; }
.sam-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.sam-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--nc-muted, #94a3b8); text-transform: uppercase; letter-spacing: 0.04em;
  font-size: 0.66rem;
  border-bottom: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  background: rgba(0, 0, 0, 0.18);
}
.sam-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(0, 210, 210, 0.06);
  vertical-align: top;
}
.sam-table tbody tr:hover { background: rgba(0, 210, 210, 0.05); }

/* About tab */
.sam-h4 { font-size: 0.85rem; font-weight: 700; margin: 16px 0 8px 0; color: rgba(var(--nc-primary-rgb, 0, 210, 210), 1); }
.sam-prose { font-size: 0.82rem; color: rgba(255, 255, 255, 0.85); margin: 4px 0; line-height: 1.6; }
.sam-prose code { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10); color: rgba(var(--nc-primary-rgb, 0, 210, 210), 1); padding: 0 4px; border-radius: 3px; font-size: 0.78rem; }
.sam-pre { background: rgba(0, 0, 0, 0.35); padding: 8px 12px; border-radius: 6px; font-size: 0.78rem; color: #e2e8f0; margin: 6px 0; overflow-x: auto; }

/* Empty / loading */
.sam-empty { padding: 30px 20px; text-align: center; color: var(--nc-muted, #94a3b8); }
.sam-empty--muted { font-size: 0.82rem; }
.sam-spinner {
  display: inline-block; width: 22px; height: 22px;
  border: 2px solid rgba(0, 210, 210, 0.18);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%; animation: sam-spin 0.8s linear infinite;
}
@keyframes sam-spin { to { transform: rotate(360deg); } }

.sam-banner {
  padding: 10px 14px; border-radius: 8px; font-size: 0.85rem;
  display: flex; align-items: center; gap: 10px;
}
.sam-banner--bad {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.32);
  color: #fca5a5;
}

.sam-mono { font-family: ui-monospace, monospace; font-size: 0.78rem; }
.sam-text-muted { color: var(--nc-muted, #94a3b8); }
.sam-text-warn  { color: #fbbf24; }
.sam-text-bad   { color: #f87171; }
.sam-text-ok    { color: #34d399; }

.sam-footer {
  padding: 8px 20px; border-top: 1px solid var(--nc-border, rgba(0, 210, 210, 0.12));
  text-align: center;
}

@media (max-width: 768px) {
  .sam-stats-row { grid-template-columns: repeat(2, 1fr); }
  .sam-modal { max-height: 92vh; }
}

@media (prefers-reduced-motion: reduce) {
  .sam-status-dot--bad { animation: none; }
}
</style>
