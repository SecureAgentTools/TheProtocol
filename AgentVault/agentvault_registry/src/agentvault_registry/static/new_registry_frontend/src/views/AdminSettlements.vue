<template>
  <!-- Build #12 (2026-05-07): Cross-Registry Settlements Watchtower.
       Surfaces dispute-driven slash + mint flows across registries.
       Each settlement: defendant slashed on home registry → complainant
       minted on home registry → both events linked via dispute_id. -->
  <div class="as">
    <div class="as-ambient">
      <div class="as-grid"></div>
      <div class="as-glow as-glow-1"></div>
      <div class="as-glow as-glow-2"></div>
    </div>

    <section class="as-hero" data-tour="settlements-hero">
      <div class="as-hero-inner">
        <div class="as-chip"><span class="as-chip-dot"></span>{{ t('adminSettlementsView.hero.chip') }}</div>
        <h1 class="as-h1">{{ t('adminSettlementsView.hero.h1a') }}<span class="as-accent">{{ t('adminSettlementsView.hero.h1Accent') }}</span></h1>
        <p class="as-lead">{{ t('adminSettlementsView.hero.lead') }}</p>

        <div class="as-toolbar">
          <div class="as-toolbar-group">
            <span class="as-toolbar-label">STATUS</span>
            <button
              v-for="s in STATUS_FILTERS" :key="s.value"
              class="as-chip-btn"
              :class="{ 'as-chip-btn--active': statusFilter === s.value }"
              :disabled="loading"
              @click="setStatusFilter(s.value)"
            >{{ s.label }}</button>
          </div>

          <span class="as-toolbar-spacer"></span>

          <div class="as-toolbar-group">
            <label class="as-toggle">
              <input type="checkbox" v-model="autoRefresh" />
              <span class="as-toggle-track"><span class="as-toggle-knob"></span></span>
              <span class="as-toggle-label">{{ t('common.autoRefresh60s') }}</span>
            </label>
          </div>
          <div class="as-toolbar-group as-toolbar-meta">
            <span class="as-toolbar-label">LAST</span>
            <span class="as-toolbar-val">{{ lastRefreshAt || '—' }}</span>
            <button class="as-btn as-btn--ghost" :disabled="loading" @click="refresh">↻</button>
            <button class="as-btn as-btn--ghost" :disabled="!data || data.settlements.length === 0" @click="exportCsv">⤓ CSV</button>
          </div>
        </div>
      </div>
    </section>

    <div class="as-body">
      <div v-if="loading && !data" class="as-center">
        <div class="as-spinner"></div>
        <p class="as-loading-text">Loading settlements…</p>
      </div>

      <div v-else-if="error && !data" class="as-center">
        <p class="as-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
        <button class="as-btn as-btn--ghost" @click="refresh">{{ t('adminSettlementsView.error.retry') }}</button>
      </div>

      <template v-else-if="data">
        <!-- §FESUITE (V0578): the list below is the last answer; when the latest read failed it says so here, not only
             in a toast that is gone in seconds -->
        <ReadFailedNotice v-if="error" dense data-testid="as-stale" :retry="refresh"
          :text="`The settlements could not be read just now. What follows is from the read at ${lastRefreshAt || 'an earlier time'}.`" />
        <!-- Hero stats — 4 cards -->
        <div class="as-stats">
          <div class="as-stat-card">
            <div class="as-stat-key">{{ t('adminSettlementsView.stats.settlements') }}</div>
            <div class="as-stat-val as-stat-val--cyan">{{ data.stats.total.toLocaleString(appLocale()) }}</div>
            <div class="as-stat-sub as-stat-sub-grid">
              <span class="as-pill as-pill--green">✓ {{ data.stats.settled }}</span>
              <span v-if="data.stats.pending > 0" class="as-pill as-pill--cyan"><Icon name="mdi:timer-sand" /> {{ data.stats.pending }}</span>
              <span v-if="data.stats.slashed > 0" class="as-pill as-pill--violet"><Icon name="mdi:scale-balance" /> {{ data.stats.slashed }}</span>
              <span v-if="data.stats.failed > 0" class="as-pill as-pill--red">✕ {{ data.stats.failed }}</span>
              <span v-if="data.stats.expired > 0" class="as-pill as-pill--warn"><Icon name="mdi:timer-sand" /> {{ data.stats.expired }}</span>
            </div>
          </div>

          <div class="as-stat-card">
            <div class="as-stat-key">{{ t('adminSettlementsView.stats.requested') }}</div>
            <div class="as-stat-val as-stat-val--violet">{{ formatAvt(data.stats.total_requested_avt) }}</div>
            <div class="as-stat-sub">{{ localCurrency }} requested by complainants</div>
          </div>

          <div class="as-stat-card">
            <div class="as-stat-key">{{ t('adminSettlementsView.stats.slashed') }}</div>
            <div class="as-stat-val as-stat-val--red">{{ formatAvt(data.stats.total_slashed_avt) }}</div>
            <div class="as-stat-sub">{{ localCurrency }} actually slashed from defendants</div>
          </div>

          <div class="as-stat-card">
            <div class="as-stat-key">{{ t('adminSettlementsView.stats.minted') }}</div>
            <div class="as-stat-val as-stat-val--green">{{ formatAvt(data.stats.total_minted_avt) }}</div>
            <div class="as-stat-sub">{{ localCurrency }} delivered to complainants</div>
          </div>
        </div>

        <!-- Settlements list -->
        <div class="as-section">
          <div class="as-section-head">
            <span class="as-section-title">RECENT SETTLEMENTS</span>
            <span class="as-section-sub">most recent {{ data.count }} (max 100)</span>
          </div>

          <!-- Bulk action toolbar (Build #17, 2026-05-08).
               Visible only when ≥1 PENDING_ADMIN_APPROVAL row is selected. -->
          <div v-if="selectedIds.size > 0" class="as-bulk-bar">
            <span class="as-bulk-count">{{ selectedIds.size }} selected</span>
            <button
              class="as-btn as-btn--primary as-btn--sm"
              :disabled="actionBusy"
              @click="openBulkAction('approve')"
            >Approve selected</button>
            <button
              class="as-btn as-btn--danger as-btn--sm"
              :disabled="actionBusy"
              @click="openBulkAction('reject')"
            >Reject selected</button>
            <span class="as-bulk-spacer"></span>
            <button class="as-btn as-btn--ghost as-btn--sm" @click="clearSelection">{{ t('adminSettlementsView.actions.clear') }}</button>
          </div>

          <div v-if="data.settlements.length === 0" class="as-empty">
            <div class="as-empty-glyph"><Icon name="mdi:scale-balance" /></div>
            <p class="as-empty-title">No settlements match this filter.</p>
          </div>
          <div v-else class="as-feed-list">
            <div
              v-for="s in data.settlements" :key="s.id"
              class="as-feed-row"
              :class="{ 'as-feed-row--expanded': expandedId === s.id }"
              @click="toggleExpand(s.id)"
            >
              <div class="as-feed-head">
                <!-- Build #17 (2026-05-08): multi-select checkbox for
                     PENDING_ADMIN_APPROVAL rows only. Click stops bubbling
                     so it doesn't toggle the row expansion. -->
                <input
                  v-if="s.status === 'PENDING_ADMIN_APPROVAL'"
                  type="checkbox"
                  class="as-row-check"
                  :checked="selectedIds.has(s.id)"
                  @click.stop="toggleSelected(s.id)"
                  :title="selectedIds.has(s.id) ? 'Deselect' : 'Select for bulk action'"
                  :aria-label="`Select settlement ${s.id}`"
                />
                <span v-else class="as-row-check-spacer"></span>
                <span class="as-feed-time">{{ formatHHMMSS(s.requested_at) }}</span>
                <span class="as-feed-date">{{ formatDate(s.requested_at) }}</span>
                <span class="as-status-pill" :class="statusPillClass(s.status)">{{ s.status }}</span>
                <span v-if="s.is_partial" class="as-pill as-pill--warn">PARTIAL</span>
                <span class="as-feed-amount">{{ formatAvt(s.slashed_amount) }}<span class="as-feed-amount-unit">/{{ formatAvt(s.requested_amount) }} {{ localCurrency }}</span></span>
                <code class="as-feed-did" :title="s.complainant_did">↗ {{ shortDid(s.complainant_did) }}</code>
                <code class="as-feed-did" :title="s.defendant_did">↘ {{ shortDid(s.defendant_did) }}</code>
                <span class="as-feed-spacer"></span>
                <!-- Per-row Approve/Reject for PENDING_ADMIN_APPROVAL only. -->
                <template v-if="s.status === 'PENDING_ADMIN_APPROVAL'">
                  <button
                    class="as-btn as-btn--primary as-btn--xs"
                    :disabled="actionBusy"
                    @click.stop="openSingleAction('approve', s.id)"
                  >Approve</button>
                  <button
                    class="as-btn as-btn--danger as-btn--xs"
                    :disabled="actionBusy"
                    @click.stop="openSingleAction('reject', s.id)"
                  >Reject</button>
                </template>
                <span class="as-feed-saga" v-if="s.saga_state && s.saga_state !== 'LEGACY'">{{ s.saga_state }}</span>
                <span class="as-feed-caret">{{ expandedId === s.id ? '▾' : '▸' }}</span>
              </div>

              <div v-if="expandedId === s.id" class="as-feed-detail" @click.stop>
                <div class="as-detail-grid">
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Settlement ID</span>
                    <span class="as-detail-val">
                      <code>{{ s.id }}</code>
                      <button class="as-icon-btn" @click.stop="copyText(s.id)" title="Copy">⎘</button>
                    </span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Dispute ID</span>
                    <span class="as-detail-val">
                      <code>{{ s.dispute_id }}</code>
                      <button class="as-icon-btn" @click.stop="copyText(s.dispute_id)" title="Copy">⎘</button>
                      <!-- B (2026-05-08): drilldown to the dispute's full
                           event chain — DisputeFiled, EvidenceSubmitted,
                           ResolutionProposed, etc. -->
                      <button
                        class="as-icon-btn"
                        @click.stop="goToEventStore(s.dispute_id)"
                        title="Open dispute thread in EventStore Explorer"
                      >⤴</button>
                    </span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Ruling</span>
                    <span class="as-detail-val">{{ s.ruling }}</span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Requested</span>
                    <span class="as-detail-val">{{ formatAvt(s.requested_amount) }} {{ localCurrency }}</span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Slashed</span>
                    <span class="as-detail-val">{{ formatAvt(s.slashed_amount) }} {{ localCurrency }}</span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Paid</span>
                    <span class="as-detail-val">{{ formatAvt(s.minted_amount) }} {{ localCurrency }}</span>
                  </div>
                  <div v-if="parseFloat(String(s.shortfall || '0')) > 0" class="as-detail-pair">
                    <span class="as-detail-key">Shortfall</span>
                    <span class="as-detail-val as-detail-val--warn">{{ formatAvt(s.shortfall) }} {{ localCurrency }}</span>
                  </div>
                  <div v-if="s.requested_at" class="as-detail-pair">
                    <span class="as-detail-key">Requested at</span>
                    <span class="as-detail-val">{{ formatAbs(s.requested_at) }}</span>
                  </div>
                  <div v-if="s.slashed_at" class="as-detail-pair">
                    <span class="as-detail-key">Slashed at</span>
                    <span class="as-detail-val">{{ formatAbs(s.slashed_at) }}</span>
                  </div>
                  <div v-if="s.settled_at" class="as-detail-pair">
                    <span class="as-detail-key">Settled at</span>
                    <span class="as-detail-val">{{ formatAbs(s.settled_at) }}</span>
                  </div>
                  <div v-if="s.saga_state" class="as-detail-pair">
                    <span class="as-detail-key">Saga state</span>
                    <span class="as-detail-val">{{ s.saga_state }}</span>
                  </div>
                  <div v-if="s.saga_timeout_at" class="as-detail-pair">
                    <span class="as-detail-key">Saga timeout</span>
                    <span class="as-detail-val">{{ formatAbs(s.saga_timeout_at) }}</span>
                  </div>
                </div>

                <div class="as-detail-grid">
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Complainant</span>
                    <span class="as-detail-val">
                      <code>{{ s.complainant_did }}</code>
                      <button class="as-icon-btn" @click.stop="goToEventStore(s.complainant_did)" title="Open in EventStore">⤴</button>
                    </span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Defendant</span>
                    <span class="as-detail-val">
                      <code>{{ s.defendant_did }}</code>
                      <button class="as-icon-btn" @click.stop="goToEventStore(s.defendant_did)" title="Open in EventStore">⤴</button>
                    </span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Origin registry</span>
                    <span class="as-detail-val"><code>{{ s.origin_registry_url }}</code></span>
                  </div>
                  <div class="as-detail-pair">
                    <span class="as-detail-key">Defendant registry</span>
                    <span class="as-detail-val"><code>{{ s.defendant_registry_url }}</code></span>
                  </div>
                </div>

                <div v-if="s.slash_tx_id || s.mint_tx_id" class="as-detail-grid">
                  <div v-if="s.slash_tx_id" class="as-detail-pair">
                    <span class="as-detail-key">Slash TX</span>
                    <span class="as-detail-val">
                      <code>{{ s.slash_tx_id }}</code>
                      <button class="as-icon-btn" @click.stop="copyText(s.slash_tx_id!)" title="Copy">⎘</button>
                    </span>
                  </div>
                  <div v-if="s.mint_tx_id" class="as-detail-pair">
                    <span class="as-detail-key">Payment TX</span>
                    <span class="as-detail-val">
                      <code>{{ s.mint_tx_id }}</code>
                      <button class="as-icon-btn" @click.stop="copyText(s.mint_tx_id!)" title="Copy">⎘</button>
                    </span>
                  </div>
                </div>

                <div v-if="s.error_message" class="as-detail-section">
                  <span class="as-detail-key">{{ t('adminSettlementsView.row.errorLabel') }}</span>
                  <pre class="as-detail-pre as-detail-pre--err">{{ localizeErrorMessage(s.error_message) }}</pre>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="as-footer">
          <code>/federation-disputes/settlements{{ statusFilter !== 'all' ? '?status_filter=' + statusFilter : '' }}</code>
          <span> · admin_enforcement gated</span>
        </div>
      </template>
    </div>

    <!-- Bulk + single approve/reject confirmation (Build #17, 2026-05-08) -->
    <ConfirmActionModal
      :show="!!actionConfirm"
      :title="actionConfirm?.kind === 'approve' ? `Approve ${actionConfirm.ids.length === 1 ? 'settlement' : `${actionConfirm.ids.length} settlements`}` : `Reject ${actionConfirm?.ids.length === 1 ? 'settlement' : `${actionConfirm?.ids.length || 0} settlements`}`"
      :message="actionConfirm?.kind === 'approve'
        ? `Approving will trigger the slash + callback flow on the defendant registry. This moves funds from the defendant to the complainant via the cross-registry settlement saga. Optional: leave a reason for the audit trail.`
        : `Rejecting closes the settlement without action. No funds move; no slash fires. Optional: leave a reason for the audit trail.`"
      :tone="actionConfirm?.kind === 'approve' ? 'primary' : 'danger'"
      :confirm-text="actionConfirm?.kind === 'approve' ? 'Approve' : 'Reject'"
      busy-text="Working…"
      :busy="actionBusy"
      reason-optional
      :reason-placeholder="t('adminSettlementsView.modal.reasonPh')"
      @close="closeActionConfirm"
      @confirm="executeAction"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * AdminSettlements — Cross-Registry Settlement Watchtower
 *
 * Build #12 (2026-05-07). Backend already shipping at
 * /federation-disputes/settlements (admin_enforcement gated).
 */
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { usePolledData } from '@/composables/usePolledData'
import { useI18n } from '@/composables/useI18n'
import {
  settlementsAdminService,
  type SettlementsListResponse,
  type SettlementRow,
} from '@/services/api/settlementsAdmin'
import { downloadCsv, csvFilenameTimestamp, type CsvColumn } from '@/components/common/csvExport'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useCurrency } from '@/composables/useCurrency'

const { t } = useI18n()
const { localCurrency } = useCurrency()

const uiStore = useUIStore()
const router = useRouter()

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'PENDING_SLASH', label: 'Pending' },
  { value: 'SLASHING', label: 'Slashing' },
  { value: 'SLASHED', label: 'Slashed' },
  { value: 'SETTLED', label: 'Settled' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'EXPIRED', label: 'Expired' },
]

const data = ref<SettlementsListResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const statusFilter = ref<string>('all')
const autoRefresh = ref(true)
const expandedId = ref<string | null>(null)
// §FESUITE (V0578): the status filter the list on screen answers. A failed read after a filter change kept the previous
// filter's list under the new filter's chip ("No settlements match this filter." when that list was empty). (Two reads
// for different filters cannot overlap: the chips are disabled while a read is out.)
const dataFilter = ref<string | null>(null)

// Build #17 (2026-05-08): bulk admin actions on PENDING_ADMIN_APPROVAL rows.
// State kept inline (not a Pinia store) — local to this view.
const selectedIds = ref<Set<string>>(new Set())
const actionConfirm = ref<{ kind: 'approve' | 'reject'; ids: string[] } | null>(null)
const actionBusy = ref(false)

function toggleSelected(id: string) {
  // Reactivity quirk: must reassign Set for Vue to see the change.
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}
function clearSelection() {
  selectedIds.value = new Set()
}
function openSingleAction(kind: 'approve' | 'reject', id: string) {
  actionConfirm.value = { kind, ids: [id] }
}
function openBulkAction(kind: 'approve' | 'reject') {
  if (selectedIds.value.size === 0) return
  actionConfirm.value = { kind, ids: Array.from(selectedIds.value) }
}
function closeActionConfirm() {
  if (actionBusy.value) return
  actionConfirm.value = null
}
async function executeAction(reason: string) {
  if (!actionConfirm.value || actionBusy.value) return
  const { kind, ids } = actionConfirm.value
  actionBusy.value = true
  let okCount = 0
  let failCount = 0
  // Sequential is safer than parallel here — backend SELECT FOR UPDATE
  // serializes anyway (S4 race protection in routers/federation_disputes.py).
  for (const id of ids) {
    try {
      if (kind === 'approve') {
        await settlementsAdminService.approve(id, reason)
      } else {
        await settlementsAdminService.reject(id, reason)
      }
      okCount++
    } catch {
      failCount++
    }
  }
  actionBusy.value = false
  actionConfirm.value = null
  selectedIds.value = new Set()
  if (failCount > 0) {
    uiStore.showWarning?.(
      `${kind === 'approve' ? 'Approved' : 'Rejected'} with errors`,
      `${okCount} succeeded · ${failCount} failed`,
    )
  } else {
    uiStore.showSuccess?.(
      `${kind === 'approve' ? 'Approved' : 'Rejected'}`,
      `${okCount} settlement${okCount === 1 ? '' : 's'} ${kind === 'approve' ? 'approved' : 'rejected'}.`,
    )
  }
  void refresh()
}

// F (2026-05-08): usePolledData composable replaces hand-rolled polling.
const polled = usePolledData(refresh, {
  interval: 60_000,
  immediate: true,
  pauseWhenHidden: true,
  autoStart: true,
})
watch(autoRefresh, (on) => { on ? polled.resume() : polled.pause() })

watch([statusFilter], () => { void refresh() })

async function refresh() {
  const filter = statusFilter.value
  loading.value = true
  error.value = null
  try {
    data.value = await settlementsAdminService.list(filter)
    dataFilter.value = filter
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load settlements'
    // a list that answers another filter is not this filter's answer
    if (dataFilter.value !== filter) { data.value = null; dataFilter.value = null }
    uiStore.showError?.('Settlements', error.value!)
  } finally {
    loading.value = false
  }
}

function setStatusFilter(s: string) {
  if (statusFilter.value === s) return
  statusFilter.value = s
}
function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function exportCsv() {
  if (!data.value || !data.value.settlements.length) return
  const cols: CsvColumn<SettlementRow>[] = [
    { label: 'Settlement ID', value: r => r.id },
    { label: 'Dispute ID', value: r => r.dispute_id },
    { label: 'Status', value: r => r.status },
    { label: 'Saga state', value: r => r.saga_state || '' },
    { label: 'Complainant DID', value: r => r.complainant_did },
    { label: 'Defendant DID', value: r => r.defendant_did },
    { label: 'Requested', value: r => r.requested_amount },
    { label: 'Slashed', value: r => r.slashed_amount },
    { label: 'Paid', value: r => r.minted_amount },
    { label: 'Shortfall', value: r => r.shortfall },
    { label: 'Is partial', value: r => r.is_partial },
    { label: 'Ruling', value: r => r.ruling },
    { label: 'Requested at', value: r => r.requested_at },
    { label: 'Slashed at', value: r => r.slashed_at },
    { label: 'Settled at', value: r => r.settled_at },
    { label: 'Slash TX', value: r => r.slash_tx_id },
    { label: 'Payment TX', value: r => r.mint_tx_id },
    { label: 'Error', value: r => r.error_message },
  ]
  downloadCsv(data.value.settlements, cols, `settlements-${statusFilter.value}-${csvFilenameTimestamp()}`)
  uiStore.showSuccess?.('Exported', `${data.value.settlements.length} rows`)
}

// ── Helpers ──
function shortDid(s: string | null | undefined): string {
  if (!s) return '—'
  if (s.length <= 26) return s
  return `${s.slice(0, 14)}…${s.slice(-6)}`
}
// §pass8 — backend's settlement_reconciliation task writes a free-text
// `error_message` like:
//   "Settlement expired after 24h without slash confirmation. Age: 1 day, 0:00:25. Admin review required."
// We can't easily translate at the backend without breaking the DB-stored audit string,
// so detect the canonical shape on the FE and route through i18n. Other messages pass through verbatim.
function localizeErrorMessage(msg: string | null | undefined): string {
  if (!msg) return ''
  const m = msg.match(/^Settlement expired after (\d+)h without slash confirmation\.\s*Age:\s*(.+?)\.\s*Admin review required\.?\s*$/)
  if (m) {
    return t('adminSettlementsView.expiredNotice', { hours: m[1], age: m[2] })
  }
  return msg
}
function formatAvt(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (Number.isNaN(n)) return '—'
  if (n === 0) return '0'
  if (Math.abs(n) >= 1) return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 6 })
}
function formatHHMMSS(iso: string | Date | null | undefined): string {
  if (!iso) return '—'
  const dt = typeof iso === 'string' ? new Date(iso) : iso
  return dt.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })
}
function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function statusPillClass(status: string): string {
  const s = (status || '').toUpperCase()
  if (s === 'SETTLED') return 'as-status-pill--green'
  if (s === 'SLASHED' || s === 'SLASHING') return 'as-status-pill--violet'
  if (s === 'PENDING_SLASH') return 'as-status-pill--cyan'
  if (s === 'EXPIRED') return 'as-status-pill--warn'
  if (s === 'FAILED' || s === 'CANCELLED') return 'as-status-pill--red'
  return 'as-status-pill--muted'
}

async function copyText(s: string) {
  try {
    await navigator.clipboard.writeText(s)
    uiStore.showSuccess?.('Copied', s.length > 40 ? s.slice(0, 40) + '…' : s)
  } catch { /* expected */ }
}

function goToEventStore(did: string) {
  void router.push({ path: '/admin/events', query: { aggregate_id: did } })
}
</script>

<style scoped>
.as {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}

.as-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.as-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}
.as-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
/* §pass8 (2026-05-15) — Align with Treasury/Events watchtower palette:
   cyan top-right + violet bottom-left = theme-aware Neural Command grid. */
.as-glow-1 { width: 440px; height: 440px; background: rgba(var(--cyan-rgb), 0.6); top: -110px; right: -90px; }
.as-glow-2 { width: 320px; height: 320px; background: rgba(168, 85, 247, 0.4); bottom: -60px; left: -100px; }

.as-hero { position: relative; z-index: 1; padding: 36px 32px 18px; }
.as-hero-inner { max-width: 1280px; margin: 0 auto; }
.as-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
  margin-bottom: 14px;
}
.as-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
}
.as-h1 {
  font-size: 2.1rem;
  margin: 0 0 0.4rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}
.as-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.as-lead {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 16px;
  line-height: 1.5;
  max-width: 60rem;
}

.as-toolbar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.8rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.as-toolbar-group { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.as-toolbar-spacer { flex: 1; }
.as-toolbar-meta { margin-left: 0.3rem; }
.as-toolbar-label {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.45);
  text-transform: uppercase;
}
.as-toolbar-val {
  font-family: var(--mono); font-size: 0.78rem;
  font-weight: 700; color: var(--cyan);
}

.as-chip-btn {
  font-family: var(--mono); font-size: 0.6rem; font-weight: 600;
  letter-spacing: 0.06em;
  background: transparent; color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px; padding: 3px 9px; cursor: pointer;
  transition: all 0.15s; text-transform: uppercase;
}
.as-chip-btn:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.9);
}
.as-chip-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}

.as-toggle {
  display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.7);
}
.as-toggle input { display: none; }
.as-toggle-track {
  width: 26px; height: 14px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 7px; position: relative;
  transition: background 0.15s;
}
.as-toggle-knob {
  position: absolute; top: 2px; left: 2px;
  width: 10px; height: 10px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  transition: transform 0.15s, background 0.15s;
}
.as-toggle input:checked ~ .as-toggle-track { background: rgba(var(--cyan-rgb), 0.3); }
.as-toggle input:checked ~ .as-toggle-track .as-toggle-knob {
  transform: translateX(12px); background: var(--cyan);
}

.as-body {
  position: relative; z-index: 1;
  padding: 0 32px;
  max-width: 1280px;
  margin: 0 auto;
  display: flex; flex-direction: column; gap: 1.25rem;
}

.as-btn {
  display: inline-flex; align-items: center; gap: 0.35rem;
  font-family: var(--mono); font-size: 0.65rem;
  letter-spacing: 0.08em; font-weight: 600;
  padding: 4px 10px; border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s;
}
.as-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.as-btn--ghost {
  background: transparent;
  border-color: rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.85);
}
.as-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  border-color: rgba(var(--cyan-rgb), 0.5);
  color: rgba(var(--cyan-rgb), 1);
}

/* Build #17 (2026-05-08): bulk-action button variants */
.as-btn--primary {
  background: rgba(var(--cyan-rgb), 0.95);
  border-color: rgba(var(--cyan-rgb), 1);
  color: #06141a;
}
.as-btn--primary:hover:not(:disabled) {
  background: var(--nc-primary-bright, rgba(var(--cyan-rgb), 1));
  box-shadow: 0 0 8px rgba(var(--cyan-rgb), 0.4);
}
.as-btn--danger {
  background: rgba(255, 51, 102, 0.18);
  border-color: rgba(255, 51, 102, 0.55);
  color: #ff8fa3;
}
.as-btn--danger:hover:not(:disabled) {
  background: rgba(255, 51, 102, 0.32);
  border-color: rgba(255, 51, 102, 0.85);
  color: #fff;
}
.as-btn--xs { padding: 3px 8px; font-size: 0.6rem; }
.as-btn--sm { padding: 5px 12px; font-size: 0.65rem; }

/* Per-row checkbox */
.as-row-check {
  width: 14px; height: 14px;
  margin-right: 0.4rem;
  accent-color: rgba(var(--cyan-rgb), 0.95);
  cursor: pointer;
}
.as-row-check-spacer {
  display: inline-block;
  width: 14px; margin-right: 0.4rem;
}

/* Bulk-action toolbar */
.as-bulk-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.9rem;
  margin-bottom: 0.6rem;
  background: linear-gradient(180deg, rgba(var(--cyan-rgb), 0.12), rgba(var(--cyan-rgb), 0.04));
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  border-radius: 6px;
}
.as-bulk-count {
  font-family: var(--mono);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--cyan);
}
.as-bulk-spacer { flex: 1; }

.as-center {
  text-align: center;
  padding: 5rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 6px;
}
.as-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: rgba(var(--cyan-rgb), 0.95);
  border-radius: 50%;
  animation: as-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes as-spin { to { transform: rotate(360deg); } }
.as-loading-text {
  font-family: var(--mono); font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em; text-transform: uppercase;
}
.as-error-text { font-family: var(--mono); font-size: 0.85rem; color: var(--nc-danger); }

.as-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
.as-stat-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 1.05rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.as-stat-key {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.14em; font-weight: 700;
  color: var(--cyan); text-transform: uppercase;
}
.as-stat-val {
  font-family: var(--mono);
  font-size: 1.7rem; font-weight: 700;
  letter-spacing: -0.02em; line-height: 1.05;
}
.as-stat-val--cyan { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.4); }
.as-stat-val--green { color: var(--nc-success, #00ff88); text-shadow: 0 0 14px rgba(0, 255, 136, 0.35); }
.as-stat-val--violet { color: #c084fc; text-shadow: 0 0 14px rgba(168, 85, 247, 0.35); }
.as-stat-val--red { color: var(--nc-danger, #ff3366); text-shadow: 0 0 14px rgba(255, 51, 102, 0.45); }
.as-stat-val--muted { color: rgba(255, 255, 255, 0.45); }
.as-stat-sub {
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.04em;
  display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap;
}
.as-stat-sub-grid { display: flex; gap: 0.3rem; flex-wrap: wrap; }

.as-pill {
  display: inline-block;
  font-family: var(--mono); font-size: 0.55rem; font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px; border-radius: 3px;
  border: 1px solid transparent;
}
.as-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.as-pill--cyan { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.as-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.as-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.as-pill--red { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }

.as-section {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 8px;
  padding: 1rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.7rem;
}
.as-section-head {
  display: flex; justify-content: space-between; align-items: center;
  gap: 1rem;
}
.as-section-title {
  font-family: var(--mono); font-size: 0.65rem;
  letter-spacing: 0.14em; font-weight: 700;
  color: var(--cyan); text-transform: uppercase;
}
.as-section-sub {
  font-family: var(--mono); font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.45);
  letter-spacing: 0.06em;
}

.as-empty {
  text-align: center;
  padding: 3rem 1rem;
  display: flex; flex-direction: column;
  align-items: center; gap: 0.4rem;
}
.as-empty-glyph { font-size: 2rem; color: rgba(var(--cyan-rgb), 0.4); font-family: var(--mono); }
.as-empty-title {
  font-family: var(--mono); font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.7); margin: 0;
}

.as-feed-list { display: flex; flex-direction: column; gap: 0.35rem; }
.as-feed-row {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  overflow: hidden;
}
.as-feed-row:hover {
  background: rgba(var(--cyan-rgb), 0.04);
  border-color: rgba(var(--cyan-rgb), 0.25);
}
.as-feed-row--expanded {
  background: rgba(var(--cyan-rgb), 0.06);
  border-color: rgba(var(--cyan-rgb), 0.4);
}
.as-feed-head {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.45rem 0.75rem;
  flex-wrap: wrap;
  font-family: var(--mono);
}
.as-feed-time { font-size: 0.7rem; font-weight: 600; color: rgba(255, 255, 255, 0.85); }
.as-feed-date { font-size: 0.6rem; color: rgba(255, 255, 255, 0.5); }
.as-feed-amount { font-size: 0.72rem; font-weight: 700; color: var(--cyan); }
.as-feed-amount-unit { font-size: 0.55rem; color: rgba(255, 255, 255, 0.45); font-weight: 600; letter-spacing: 0.02em; margin-left: 0.05rem; }
.as-feed-did {
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.65);
  background: rgba(var(--cyan-rgb), 0.04);
  padding: 1px 5px; border-radius: 3px;
}
.as-feed-saga {
  font-size: 0.55rem;
  color: rgba(168, 85, 247, 0.85);
  background: rgba(168, 85, 247, 0.06);
  padding: 1px 6px; border-radius: 3px;
  border: 1px solid rgba(168, 85, 247, 0.2);
  font-weight: 700;
  letter-spacing: 0.06em;
}
.as-feed-spacer { flex: 1; }
.as-feed-caret { font-size: 0.7rem; color: rgba(var(--cyan-rgb), 0.6); }

.as-status-pill {
  font-family: var(--mono); font-size: 0.55rem; font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px; border-radius: 3px;
  border: 1px solid transparent;
}
.as-status-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.as-status-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.as-status-pill--cyan { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.as-status-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.as-status-pill--red { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.as-status-pill--muted { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(255, 255, 255, 0.15); }

.as-feed-detail {
  padding: 0.7rem 0.85rem 0.85rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
  display: flex; flex-direction: column; gap: 0.85rem;
  cursor: default;
}
.as-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.4rem 0.85rem;
}
.as-detail-pair { display: flex; flex-direction: column; gap: 0.15rem; }
.as-detail-key {
  font-family: var(--mono); font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase; font-weight: 600;
}
.as-detail-val {
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: center; gap: 0.35rem;
}
.as-detail-val--warn { color: var(--nc-warning, #ff9500); }
.as-detail-val code {
  background: rgba(var(--cyan-rgb), 0.06);
  padding: 1px 5px; border-radius: 3px;
  word-break: break-all; font-size: 0.65rem;
}
.as-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-family: monospace; font-size: 0.7rem;
  padding: 0 5px; cursor: pointer;
  transition: all 0.12s;
}
.as-icon-btn:hover {
  background: rgba(var(--cyan-rgb), 0.1);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.as-detail-section { margin-top: 0.2rem; }
.as-detail-pre {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 4px;
  padding: 6px 9px;
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.75);
  white-space: pre-wrap; word-break: break-all;
  max-height: 14rem; overflow-y: auto;
}
.as-detail-pre--err {
  background: rgba(255, 51, 102, 0.06);
  border-color: rgba(255, 51, 102, 0.3);
  color: rgba(255, 200, 200, 0.85);
}

.as-footer {
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5);
  padding-top: 0.5rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.as-footer code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px; border-radius: 3px;
}

@media (max-width: 1100px) { .as-stats { grid-template-columns: 1fr 1fr; } }
@media (max-width: 768px) {
  .as-hero { padding: 24px 16px 12px; }
  .as-h1 { font-size: 1.5rem; }
  .as-body { padding: 0 16px; }
  .as-stats { grid-template-columns: 1fr; }
}
</style>
