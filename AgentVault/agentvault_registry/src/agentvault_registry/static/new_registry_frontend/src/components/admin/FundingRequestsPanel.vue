<template>
  <!-- Build #5 (2026-05-07): Funding Requests admin triage panel.
       Mounted as the Funding Requests tab inside AdminDevelopers.
       Strategy doc §4 Build #5. Backend: routers/funding_requests.py admin endpoints. -->
  <div class="fr-panel">

    <!-- Loading -->
    <div v-if="loading && !requests.length" class="fr-center">
      <div class="fr-spinner"></div>
      <p class="fr-loading-text">Loading funding requests…</p>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="fr-center">
      <p class="fr-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
      <button class="fr-btn fr-btn--ghost" @click="refresh">Retry</button>
    </div>

    <!-- Dashboard -->
    <div v-else>
      <!-- Stats -->
      <div class="fr-stats-row">
        <div class="fr-stat fr-stat--amber">
          <span class="fr-stat-label">Pending</span>
          <span class="fr-stat-value" :title="stats.pending === null ? NOT_COUNTED : undefined">{{ stats.pending ?? '—' }}</span>
          <span v-if="(stats.staleCount ?? 0) > 0" class="fr-stat-sub">{{ stats.staleCount }} over 24h</span>
        </div>
        <div class="fr-stat fr-stat--ok">
          <span class="fr-stat-label">Approved (24h)</span>
          <span class="fr-stat-value" :title="stats.approvedRecent === null ? NOT_COUNTED : undefined">{{ stats.approvedRecent ?? '—' }}</span>
        </div>
        <div class="fr-stat fr-stat--err">
          <span class="fr-stat-label">Rejected (24h)</span>
          <span class="fr-stat-value" :title="stats.rejectedRecent === null ? NOT_COUNTED : undefined">{{ stats.rejectedRecent ?? '—' }}</span>
        </div>
        <div class="fr-stat fr-stat--cyan">
          <span class="fr-stat-label">Total in window</span>
          <span class="fr-stat-value">{{ requests.length }}</span>
        </div>
      </div>

      <!-- Toolbar -->
      <div class="fr-toolbar">
        <div class="fr-toolbar-left">
          <span class="fr-toolbar-label">FILTER</span>
          <button
            v-for="f in FILTERS"
            :key="f.id || 'all'"
            class="fr-chip"
            :class="{ 'fr-chip--active': activeFilter === f.id }"
            @click="setFilter(f.id)"
          >{{ f.label }}<span v-if="f.id === 'pending' && (stats.pending ?? 0) > 0" class="fr-chip-count">{{ stats.pending }}</span></button>
        </div>
        <div class="fr-toolbar-right">
          <span class="fr-mono-label">{{ t('common.lastRefresh') }}</span>
          <span class="fr-mono-val">{{ lastRefreshAt || '—' }}</span>
          <button class="fr-btn fr-btn--ghost" @click="toggleAutoRefresh">
            <span class="fr-live-dot" :class="{ 'fr-live-dot--on': autoRefresh }"></span>
            {{ autoRefresh ? 'Auto 60s' : 'Auto off' }}
          </button>
          <button class="fr-btn fr-btn--primary" @click="refresh">↻ Refresh</button>
        </div>
      </div>

      <!-- Empty -->
      <div v-if="!filteredRequests.length" class="fr-empty">
        <div class="fr-empty-glyph">{{ activeFilter === 'pending' ? '✓' : '📋' }}</div>
        <p class="fr-empty-title">
          <template v-if="activeFilter === 'pending'">No pending requests</template>
          <template v-else>No requests match the filter</template>
        </p>
        <p class="fr-empty-sub">
          <template v-if="activeFilter === 'pending'">
            All caught up. New requests appear here as agents file them via the funding panel.
          </template>
          <template v-else>
            Switch filters or come back later.
          </template>
        </p>
      </div>

      <!-- Request list -->
      <div v-else class="fr-list">
        <div
          v-for="r in filteredRequests"
          :key="r.id"
          class="fr-row"
          :class="rowClass(r)"
        >
          <!-- Row body -->
          <div class="fr-row-main">
            <div class="fr-row-meta">
              <span class="fr-status-pill" :class="statusPillClass(r)">{{ r.status?.toUpperCase() }}</span>
              <span class="fr-row-time" :title="formatAbs(r.created_at)">{{ timeAgo(r.created_at) }}</span>
              <span v-if="r.status === 'pending' && hoursOld(r) > 24" class="fr-row-stale" :title="`Pending ${formatHours(r)}`"><Icon name="mdi:alert" /> {{ formatHours(r) }} old</span>
              <span class="fr-row-id">#{{ r.id }}</span>
            </div>

            <div class="fr-row-amount-line">
              <span class="fr-row-amount">◎ {{ formatAmount(r.requested_amount) }} {{ localCurrency }}</span>
              <span v-if="r.approved_amount && r.approved_amount !== r.requested_amount" class="fr-row-amount-approved">
                → approved {{ formatAmount(r.approved_amount) }}
              </span>
            </div>

            <div class="fr-row-requester">
              <span class="fr-row-requester-name">{{ r.requester_name || '(unnamed agent)' }}</span>
              <code class="fr-row-did" :title="r.requester_did">{{ shortDid(r.requester_did) }}</code>
              <button class="fr-icon-btn" @click="copyText(r.requester_did)" title="Copy DID">⎘</button>
            </div>

            <div class="fr-row-reason">
              <span class="fr-row-reason-label">REASON</span>
              <span class="fr-row-reason-text">{{ r.reason }}</span>
            </div>

            <div v-if="r.rejection_reason" class="fr-row-rejected-reason">
              <span class="fr-row-reason-label">REJECTED:</span>
              <span>{{ r.rejection_reason }}</span>
            </div>

            <div v-if="r.reviewed_at" class="fr-row-review-meta">
              Reviewed by {{ r.reviewed_by || '(unknown admin)' }} · {{ formatAbs(r.reviewed_at) }}
              <span v-if="r.funded_at" class="fr-row-funded"> · funded {{ timeAgo(r.funded_at) }}</span>
            </div>
          </div>

          <!-- Actions -->
          <div v-if="r.status === 'pending'" class="fr-row-actions">
            <button
              class="fr-btn fr-btn--ok"
              :disabled="busyId === r.id"
              @click="openApprove(r)"
            >
              <span v-if="busyId === r.id" class="fr-spinner-inline"></span>
              ✓ Approve
            </button>
            <button
              class="fr-btn fr-btn--danger"
              :disabled="busyId === r.id"
              @click="openReject(r)"
            >✗ Reject</button>
          </div>
          <div v-else-if="r.funding_transaction_id" class="fr-row-actions fr-row-actions--terminal">
            <code :title="r.funding_transaction_id">tx {{ shortId(r.funding_transaction_id) }}</code>
            <button class="fr-icon-btn" @click="copyText(r.funding_transaction_id!)" title="Copy tx ID">⎘</button>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="fr-footer">
        <span>Showing {{ filteredRequests.length }} of {{ requests.length }} requests<span v-if="activeFilter"> · filtered to <strong>{{ activeFilter }}</strong></span></span>
      </div>
    </div>

    <!-- Approve confirm — supports approved_amount override -->
    <ConfirmActionModal
      :show="showApproveModal"
      title="// APPROVE FUNDING REQUEST"
      :message="reviewing
        ? `Approve <strong>#${reviewing.id}</strong> from <strong>${reviewing.requester_name || 'unnamed agent'}</strong>? Requested <strong>${formatAmount(reviewing.requested_amount)} ${localCurrency}</strong>. The treasury will fund-agent immediately and the requester will receive an email.`
        : ''"
      tone="primary"
      reasonOptional
      reasonPlaceholder="Optional: override approved amount (leave blank for full requested amount)"
      confirmText="Approve + Fund"
      busyText="Funding…"
      :busy="approveBusy"
      @close="cancelApprove"
      @confirm="handleApprove"
    />

    <!-- Reject confirm — reason required -->
    <ConfirmActionModal
      :show="showRejectModal"
      title="// REJECT FUNDING REQUEST"
      :message="reviewing
        ? `Reject <strong>#${reviewing.id}</strong> from <strong>${reviewing.requester_name || 'unnamed agent'}</strong> requesting <strong>${formatAmount(reviewing.requested_amount)} ${localCurrency}</strong>? The requester will receive an email with your reason.`
        : ''"
      tone="warn"
      :reasonRequired="true"
      :reasonMinLength="10"
      reasonPlaceholder="Why are you rejecting this request?"
      confirmText="Reject"
      busyText="Rejecting…"
      :busy="rejectBusy"
      @close="cancelReject"
      @confirm="handleReject"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * FundingRequestsPanel — admin triage queue for AVT funding requests.
 *
 * Build #5 (2026-05-07).
 * Strategy doc §4 Build #5.
 * Mounted in AdminDevelopers.vue as the "Funding Requests" tab.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { fundingAdminService, type FundingRequest, type FundingStatusFilter } from '@/services/api/fundingAdmin'
import { useUIStore } from '@/stores/ui'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'

const { t } = useI18n()
const { localCurrency } = useCurrency()

const uiStore = useUIStore()

// State
const requests = ref<FundingRequest[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const autoRefresh = ref(true)
const activeFilter = ref<FundingStatusFilter | 'all'>('pending')
// the filter the shown list was read with (a filter switched while a read is in flight answers for the newest only)
const loadedFilter = ref<FundingStatusFilter | 'all' | null>(null)
let readSeq = 0
const busyId = ref<number | null>(null)

let pollHandle: ReturnType<typeof setInterval> | null = null

const FILTERS: { id: FundingStatusFilter | 'all'; label: string }[] = [
  { id: 'pending',   label: 'Pending' },
  { id: 'approved',  label: 'Approved' },
  { id: 'rejected',  label: 'Rejected' },
  { id: 'funded',    label: 'Funded' },
  { id: 'all',       label: 'All' },
]

// Approval modal
const showApproveModal = ref(false)
const approveBusy = ref(false)

// Reject modal
const showRejectModal = ref(false)
const rejectBusy = ref(false)

const reviewing = ref<FundingRequest | null>(null)

// ── Lifecycle ─────────────────────────────────────────────
onMounted(() => {
  refresh()
  startPolling()
})
onBeforeUnmount(() => stopPolling())

function startPolling() {
  if (pollHandle) return
  // 60s — funding triage isn't ultra-time-sensitive; 60s = 1 RPM is plenty.
  pollHandle = setInterval(() => {
    if (!autoRefresh.value) return
    if (document.visibilityState === 'hidden') return
    refresh().catch(() => {})
  }, 60_000)
}
function stopPolling() {
  if (pollHandle) {
    clearInterval(pollHandle)
    pollHandle = null
  }
}
function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) refresh()
}

// ── Fetch ─────────────────────────────────────────────────
async function refresh() {
  const mine = ++readSeq
  const filter = activeFilter.value
  loading.value = true
  error.value = null
  try {
    let list: FundingRequest[]
    if (filter === 'pending') {
      list = await fundingAdminService.listPending()
    } else if (filter === 'all') {
      list = await fundingAdminService.listAll({ limit: 200 })
    } else {
      list = await fundingAdminService.listAll({ status: filter as FundingStatusFilter, limit: 200 })
    }
    // a late answer for a filter already left would list its rows under the newer chip
    if (mine !== readSeq) return
    requests.value = list
    loadedFilter.value = filter
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    if (mine !== readSeq) return
    const msg = e?.response?.data?.detail || e?.message || 'Failed to load requests'
    error.value = msg
    uiStore.showError?.('Funding', msg)
  } finally {
    if (mine === readSeq) loading.value = false
  }
}

function setFilter(id: FundingStatusFilter | 'all') {
  activeFilter.value = id
  refresh()
}

// ── Approve flow ──────────────────────────────────────────
function openApprove(r: FundingRequest) {
  reviewing.value = r
  showApproveModal.value = true
}
function cancelApprove() {
  showApproveModal.value = false
  reviewing.value = null
}
async function handleApprove(reasonOrAmount: string) {
  const r = reviewing.value
  if (!r) return
  approveBusy.value = true
  busyId.value = r.id
  try {
    const approvedAmount = (reasonOrAmount || '').trim() || undefined
    const updated = await fundingAdminService.approve(r.id, approvedAmount)
    uiStore.showSuccess?.('Approved', `Request #${r.id} approved & funded for ${formatAmount(updated.approved_amount || updated.requested_amount)} ${localCurrency}.`)
    showApproveModal.value = false
    reviewing.value = null
    await refresh()
  } catch (e: any) {
    uiStore.showError?.('Approve failed', e?.response?.data?.detail || e?.message || 'Unknown error')
  } finally {
    approveBusy.value = false
    busyId.value = null
  }
}

// ── Reject flow ───────────────────────────────────────────
function openReject(r: FundingRequest) {
  reviewing.value = r
  showRejectModal.value = true
}
function cancelReject() {
  showRejectModal.value = false
  reviewing.value = null
}
async function handleReject(reason: string) {
  const r = reviewing.value
  if (!r) return
  rejectBusy.value = true
  busyId.value = r.id
  try {
    await fundingAdminService.reject(r.id, reason)
    uiStore.showSuccess?.('Rejected', `Request #${r.id} rejected. Requester notified.`)
    showRejectModal.value = false
    reviewing.value = null
    await refresh()
  } catch (e: any) {
    uiStore.showError?.('Reject failed', e?.response?.data?.detail || e?.message || 'Unknown error')
  } finally {
    rejectBusy.value = false
    busyId.value = null
  }
}

// ── Computed / helpers ────────────────────────────────────
const filteredRequests = computed(() => requests.value)

// A count is drawn only from a list that holds its whole population (§FESUITE V0577). The panel reads one filter at a
// time, so under Pending (where it opens) the approved and rejected rows were never asked for and both 24h counts read 0
// whatever the registry did. A count the shown list cannot make reads '—', and says why on hover.
const NOT_COUNTED = 'Not counted under this filter: choose All to count it'
const stats = computed(() => {
  const list = requests.value
  const read = loadedFilter.value
  const holds = (f: FundingStatusFilter) => read === 'all' || read === f
  const oneDay = Date.now() - 86_400_000
  const pending = list.filter(r => r.status === 'pending').length
  const approvedRecent = list.filter(r => (r.status === 'approved' || r.status === 'funded') && r.reviewed_at && new Date(r.reviewed_at).getTime() > oneDay).length
  const rejectedRecent = list.filter(r => r.status === 'rejected' && r.reviewed_at && new Date(r.reviewed_at).getTime() > oneDay).length
  const staleCount = list.filter(r => r.status === 'pending' && hoursOld(r) > 24).length
  return {
    pending: holds('pending') ? pending : null,
    // approved counts approved AND funded rows: only All holds both
    approvedRecent: read === 'all' ? approvedRecent : null,
    rejectedRecent: holds('rejected') ? rejectedRecent : null,
    staleCount: holds('pending') ? staleCount : null,
  }
})

function hoursOld(r: FundingRequest): number {
  if (!r.created_at) return 0
  return (Date.now() - new Date(r.created_at).getTime()) / 3_600_000
}
function formatHours(r: FundingRequest): string {
  const h = hoursOld(r)
  if (h < 1) return `${Math.floor(h * 60)}m`
  if (h < 24) return `${Math.floor(h)}h`
  return `${Math.floor(h / 24)}d`
}

function statusPillClass(r: FundingRequest): string {
  switch (r.status) {
    case 'pending':  return 'fr-status-pill--amber'
    case 'approved': return 'fr-status-pill--ok'
    case 'funded':   return 'fr-status-pill--ok'
    case 'rejected': return 'fr-status-pill--err'
    default:         return 'fr-status-pill--muted'
  }
}
function rowClass(r: FundingRequest): string[] {
  const out: string[] = ['fr-row']
  if (r.status === 'pending' && hoursOld(r) > 72) out.push('fr-row--stale-72')
  else if (r.status === 'pending' && hoursOld(r) > 24) out.push('fr-row--stale-24')
  else if (r.status === 'pending') out.push('fr-row--pending')
  else if (r.status === 'approved' || r.status === 'funded') out.push('fr-row--ok')
  else if (r.status === 'rejected') out.push('fr-row--err')
  return out
}

function shortDid(d: string): string {
  if (!d) return '—'
  if (d.length <= 32) return d
  return `${d.slice(0, 18)}…${d.slice(-6)}`
}
function shortId(s: string): string {
  if (!s) return ''
  if (s.length <= 14) return s
  return `${s.slice(0, 8)}…${s.slice(-4)}`
}
function formatAmount(v: string | number | null | undefined): string {
  const n = typeof v === 'number' ? v : Number(v || 0)
  if (Number.isNaN(n)) return '0'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 4 })
}
function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
function formatHHMMSS(d: Date): string {
  return d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 60_000) return `${Math.floor(ms / 1_000)}s ago`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`
  return `${Math.floor(ms / 86_400_000)}d ago`
}
async function copyText(s: string) {
  try {
    await navigator.clipboard.writeText(s)
    uiStore.showSuccess?.('Copied', s.length > 40 ? s.slice(0, 40) + '…' : s)
  } catch { /* expected */ }
}
</script>

<style scoped>
.fr-panel {
  position: relative;
  z-index: 1;
  padding: 0 32px 18px;
  max-width: 1280px;
  margin: 0 auto;
}

.fr-center { text-align: center; padding: 4rem 1rem; }
.fr-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--nc-primary-rgb), 0.2);
  border-top-color: rgba(var(--nc-primary-rgb), 0.95);
  border-radius: 50%;
  animation: fr-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes fr-spin { to { transform: rotate(360deg); } }
.fr-loading-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: var(--nc-text-muted);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.fr-error-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  color: var(--nc-danger);
  margin-bottom: 0.8rem;
}

/* ── Stats ─────────────────────── */
.fr-stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.fr-stat {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-top: 2px solid rgba(var(--nc-primary-rgb), 0.32);
  border-radius: 8px;
  padding: 0.85rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}
.fr-stat--cyan  { border-top-color: rgba(var(--nc-primary-rgb), 0.4); }
.fr-stat--ok    { border-top-color: rgba(0, 255, 136, 0.4); }
.fr-stat--err   { border-top-color: rgba(255, 51, 102, 0.4); }
.fr-stat--amber { border-top-color: rgba(255, 149, 0, 0.4); }
.fr-stat-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted);
  text-transform: uppercase;
  font-weight: 600;
}
.fr-stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1.1;
  color: rgba(var(--nc-primary-rgb), 1);
}
.fr-stat--ok .fr-stat-value    { color: var(--nc-success); }
.fr-stat--err .fr-stat-value   { color: var(--nc-danger); }
.fr-stat--amber .fr-stat-value { color: var(--nc-warning); }
.fr-stat-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  color: var(--nc-text-muted);
}

/* ── Toolbar ──────────────────── */
.fr-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.85rem;
  padding: 0.6rem 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  margin-bottom: 0.85rem;
}
.fr-toolbar-left, .fr-toolbar-right { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.fr-toolbar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  color: rgba(var(--nc-primary-rgb), 0.55);
  font-weight: 600;
  margin-right: 0.25rem;
}
.fr-mono-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.1em;
  color: var(--nc-text-muted);
  text-transform: uppercase;
}
.fr-mono-val {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(var(--nc-primary-rgb), 1);
}

.fr-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.06em;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 14px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.6);
  background: rgba(var(--nc-primary-rgb), 0.04);
  cursor: pointer;
  transition: all 0.15s;
  text-transform: uppercase;
}
.fr-chip:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  color: rgba(255, 255, 255, 0.95);
}
.fr-chip--active {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  color: rgba(var(--nc-primary-rgb), 1);
}
.fr-chip-count {
  background: rgba(0, 0, 0, 0.35);
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 0.55rem;
}

.fr-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.08em;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.fr-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.fr-btn--ghost {
  background: transparent;
  border-color: rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.fr-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  color: rgba(var(--nc-primary-rgb), 1);
}
.fr-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
}
.fr-btn--primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.3); }
.fr-btn--ok {
  background: rgba(0, 255, 136, 0.12);
  border-color: rgba(0, 255, 136, 0.4);
  color: var(--nc-success);
}
.fr-btn--ok:hover:not(:disabled) { background: rgba(0, 255, 136, 0.22); }
.fr-btn--danger {
  background: rgba(255, 51, 102, 0.12);
  border-color: rgba(255, 51, 102, 0.4);
  color: var(--nc-danger);
}
.fr-btn--danger:hover:not(:disabled) { background: rgba(255, 51, 102, 0.22); }

.fr-live-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--nc-text-muted);
}
.fr-live-dot--on {
  background: var(--nc-success);
  box-shadow: 0 0 8px rgba(0, 255, 136, 0.6);
  animation: fr-pulse 2s ease-in-out infinite;
}
@keyframes fr-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(0, 255, 136, 0.6); }
  50% { box-shadow: 0 0 14px rgba(0, 255, 136, 0.9); }
}
.fr-spinner-inline {
  width: 10px; height: 10px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: fr-spin 0.8s linear infinite;
}

/* ── Empty ────────────────────── */
.fr-empty {
  text-align: center;
  padding: 3rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.fr-empty-glyph { font-size: 2rem; opacity: 0.5; margin-bottom: 0.5rem; }
.fr-empty-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.95rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.3rem;
}
.fr-empty-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: var(--nc-text-muted);
  max-width: 32rem;
  line-height: 1.5;
}

/* ── Request list ─────────────── */
.fr-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.fr-row {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.75), rgba(6, 8, 16, 0.75));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-left-width: 4px;
  border-radius: 6px;
  padding: 0.85rem 1rem;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 1rem;
  align-items: flex-start;
  transition: border-color 0.15s;
}
.fr-row:hover { border-color: rgba(var(--nc-primary-rgb), 0.3); }
.fr-row--pending  { border-left-color: var(--nc-warning); }
.fr-row--stale-24 { border-left-color: var(--nc-warning); box-shadow: 0 0 12px rgba(255, 149, 0, 0.15); }
.fr-row--stale-72 { border-left-color: var(--nc-danger); box-shadow: 0 0 14px rgba(255, 51, 102, 0.2); }
.fr-row--ok       { border-left-color: var(--nc-success); }
.fr-row--err      { border-left-color: var(--nc-danger); opacity: 0.78; }

.fr-row-main { display: flex; flex-direction: column; gap: 0.4rem; min-width: 0; }
.fr-row-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.fr-status-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 1px 7px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.fr-status-pill--ok    { background: rgba(0, 255, 136, 0.1); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.fr-status-pill--err   { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger); border-color: rgba(255, 51, 102, 0.3); }
.fr-status-pill--amber { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning); border-color: rgba(255, 149, 0, 0.3); }
.fr-status-pill--muted { background: rgba(var(--nc-primary-rgb), 0.06); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--nc-primary-rgb), 0.18); }

.fr-row-time {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
}
.fr-row-stale {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  color: var(--nc-warning);
  font-weight: 600;
}
.fr-row--stale-72 .fr-row-stale { color: var(--nc-danger); }
.fr-row-id {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin-left: auto;
}

.fr-row-amount-line {
  display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap;
}
.fr-row-amount {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.05rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
}
.fr-row-amount-approved {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  color: var(--nc-success);
}

.fr-row-requester {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.fr-row-requester-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}
.fr-row-did {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
  background: rgba(var(--nc-primary-rgb), 0.05);
  padding: 1px 6px;
  border-radius: 3px;
}

.fr-row-reason {
  display: flex; gap: 0.5rem; align-items: flex-start;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.7);
  line-height: 1.5;
}
.fr-row-reason-label {
  font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted);
  font-weight: 600;
  text-transform: uppercase;
  flex-shrink: 0;
  padding-top: 1px;
}
.fr-row-reason-text {
  flex: 1;
}

.fr-row-rejected-reason {
  display: flex; gap: 0.5rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: var(--nc-danger);
  font-style: italic;
}
.fr-row-rejected-reason .fr-row-reason-label { color: rgba(255, 51, 102, 0.7); }

.fr-row-review-meta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
}
.fr-row-funded {
  color: var(--nc-success);
  font-weight: 600;
}

.fr-row-actions {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  flex-shrink: 0;
  align-items: stretch;
}
.fr-row-actions--terminal {
  flex-direction: row;
  align-items: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
}
.fr-row-actions--terminal code {
  background: rgba(var(--nc-primary-rgb), 0.05);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.6rem;
}

.fr-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--nc-primary-rgb), 0.7);
  font-family: monospace;
  font-size: 0.7rem;
  padding: 0 4px;
  cursor: pointer;
}
.fr-icon-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.1);
  color: rgba(var(--nc-primary-rgb), 1);
}

/* ── Footer ────────────────────── */
.fr-footer {
  margin-top: 1rem;
  padding-top: 0.7rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
  text-align: center;
}

/* ── Responsive ─────────────── */
@media (max-width: 768px) {
  .fr-panel { padding: 0 16px 18px; }
  .fr-row { grid-template-columns: 1fr; }
  .fr-row-actions { flex-direction: row; }
  .fr-toolbar { flex-direction: column; align-items: flex-start; }
}
</style>
