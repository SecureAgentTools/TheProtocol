<template>
  <!-- Build #8 (2026-05-07): Webhook Health — cluster-wide admin oversight.
       Distinct from /webhooks (per-developer self-service). This is the
       watchtower view: who's failing, what's flowing, recent failures. -->
  <div class="aw">
    <div class="aw-ambient">
      <div class="aw-grid"></div>
      <div class="aw-glow aw-glow-1"></div>
      <div class="aw-glow aw-glow-2"></div>
    </div>

    <section class="aw-hero">
      <div class="aw-hero-inner">
        <div class="aw-chip"><span class="aw-chip-dot"></span>{{ t('adminWebhooksView.hero.chip') }}</div>
        <h1 class="aw-h1">{{ t('adminWebhooksView.hero.h1a') }}<span class="aw-accent">{{ t('adminWebhooksView.hero.h1Accent') }}</span></h1>
        <p class="aw-lead">
          {{ t('adminWebhooksView.hero.lead') }}
          <RouterLink class="aw-link" to="/webhooks">/webhooks</RouterLink>.
        </p>

        <div class="aw-toolbar">
          <div class="aw-toolbar-group">
            <span class="aw-toolbar-label">{{ t('adminWebhooksView.toolbar.period') }}</span>
            <button
              v-for="p in PERIODS" :key="p.value"
              class="aw-period-btn"
              :class="{ 'aw-period-btn--active': period === p.value }"
              :disabled="loading"
              @click="setPeriod(p.value)"
            >{{ p.label }}</button>
          </div>

          <span class="aw-toolbar-spacer"></span>

          <div class="aw-toolbar-group">
            <label class="aw-toggle">
              <input type="checkbox" v-model="autoRefresh" />
              <span class="aw-toggle-track"><span class="aw-toggle-knob"></span></span>
              <span class="aw-toggle-label">{{ t('adminWebhooksView.toolbar.autoRefresh') }}</span>
            </label>
          </div>
          <div class="aw-toolbar-group aw-toolbar-meta">
            <span class="aw-toolbar-label">{{ t('adminWebhooksView.toolbar.last') }}</span>
            <span class="aw-toolbar-val">{{ lastRefreshAt || '—' }}</span>
            <button class="aw-btn aw-btn--ghost" :disabled="loading" @click="refresh">↻</button>
          </div>
        </div>
      </div>
    </section>

    <div class="aw-body">
      <div v-if="loading && !agg" class="aw-center">
        <div class="aw-spinner"></div>
        <p class="aw-loading-text">{{ t('adminWebhooksView.loading') }}</p>
      </div>

      <div v-else-if="error && !agg" class="aw-center">
        <p class="aw-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
        <button class="aw-btn aw-btn--ghost" @click="refresh">{{ t('adminWebhooksView.error.retry') }}</button>
      </div>

      <template v-else-if="agg">
        <!-- Hero stat cards -->
        <div class="aw-stats">
          <div class="aw-stat-card">
            <div class="aw-stat-key">{{ t('adminWebhooksView.stats.webhooks') }}</div>
            <div class="aw-stat-val aw-stat-val--cyan">{{ agg.webhooks.total }}</div>
            <div class="aw-stat-sub">
              <span class="aw-stat-pill aw-stat-pill--green">{{ agg.webhooks.active }} {{ t('adminWebhooksView.stats.active') }}</span>
              ·
              <span class="aw-stat-pill aw-stat-pill--muted">{{ agg.webhooks.inactive }} {{ t('adminWebhooksView.stats.inactive') }}</span>
            </div>
          </div>

          <div class="aw-stat-card">
            <div class="aw-stat-key">{{ t('adminWebhooksView.stats.deliveries') }} · {{ periodLabel }}</div>
            <div class="aw-stat-val aw-stat-val--cyan">{{ agg.deliveries_in_window.total }}</div>
            <div class="aw-stat-sub aw-stat-sub-grid">
              <span class="aw-stat-pill aw-stat-pill--green">✓ {{ agg.deliveries_in_window.success }}</span>
              <span class="aw-stat-pill aw-stat-pill--red">✕ {{ agg.deliveries_in_window.failed }}</span>
              <span class="aw-stat-pill aw-stat-pill--warn">↻ {{ agg.deliveries_in_window.retried }}</span>
              <span class="aw-stat-pill aw-stat-pill--muted"><Icon name="mdi:timer-sand" /> {{ agg.deliveries_in_window.pending }}</span>
            </div>
          </div>

          <div class="aw-stat-card">
            <div class="aw-stat-key">{{ t('adminWebhooksView.stats.successRate') }}</div>
            <div class="aw-stat-val" :class="successRateClass">
              {{ agg.deliveries_in_window.success_rate_pct !== null ? agg.deliveries_in_window.success_rate_pct.toFixed(1) + '%' : '—' }}
            </div>
            <div class="aw-stat-sub">
              {{ agg.deliveries_in_window.success }} / {{ agg.deliveries_in_window.success + agg.deliveries_in_window.failed }} resolved
            </div>
          </div>

          <div class="aw-stat-card">
            <div class="aw-stat-key">{{ t('adminWebhooksView.stats.developers') }}</div>
            <div class="aw-stat-val aw-stat-val--violet">{{ agg.webhooks.developers_with_webhooks }}</div>
            <div class="aw-stat-sub">configuring webhooks</div>
          </div>
        </div>

        <!-- Two-column: Top events + Top failing -->
        <div class="aw-twocol">
          <div class="aw-section">
            <div class="aw-section-head">
              <span class="aw-section-title">TOP EVENT TYPES · {{ periodLabel }}</span>
            </div>
            <div v-if="agg.top_event_types.length" class="aw-event-list">
              <div v-for="e in eventRows" :key="e.event_type" class="aw-event-row">
                <span class="aw-event-label" :title="e.event_type">{{ e.event_type }}</span>
                <span class="aw-event-bar">
                  <span class="aw-event-bar-fill" :style="{ width: e.pct + '%' }"></span>
                </span>
                <span class="aw-event-val">{{ e.count }}</span>
                <span class="aw-event-pct">{{ e.pct.toFixed(0) }}%</span>
              </div>
            </div>
            <div v-else class="aw-empty-mini">No deliveries in this window.</div>
          </div>

          <div class="aw-section">
            <div class="aw-section-head">
              <span class="aw-section-title">TOP FAILING WEBHOOKS</span>
              <span class="aw-section-sub">all-time failure_count</span>
            </div>

            <!-- Bulk action toolbar — #3 (2026-05-08) -->
            <div
              v-if="agg.top_failing_webhooks.length"
              class="aw-bulk-bar"
              :class="{ 'aw-bulk-bar--active': selectedIds.size > 0 }"
            >
              <label class="aw-bulk-checkbox" :title="allFailingSelected ? 'Deselect all' : 'Select all failing'">
                <input
                  type="checkbox"
                  :checked="allFailingSelected"
                  :indeterminate.prop="someFailingSelected && !allFailingSelected"
                  @change="toggleSelectAllFailing"
                />
                <span class="aw-bulk-summary">
                  <template v-if="selectedIds.size > 0">{{ selectedIds.size }} selected</template>
                  <template v-else>Select all</template>
                </span>
              </label>
              <span class="aw-bulk-spacer"></span>
              <template v-if="selectedIds.size > 0">
                <button class="aw-btn aw-btn--bulk aw-btn--test" :disabled="bulkBusy" @click="openBulkAction('test')">
                  TEST SELECTED
                </button>
                <button class="aw-btn aw-btn--bulk aw-btn--enable" :disabled="bulkBusy" @click="openBulkAction('enable')">
                  RE-ENABLE
                </button>
                <button class="aw-btn aw-btn--bulk aw-btn--disable" :disabled="bulkBusy" @click="openBulkAction('disable')">
                  DISABLE
                </button>
                <button class="aw-btn aw-btn--ghost" :disabled="bulkBusy" @click="clearSelection" title="Clear selection">×</button>
              </template>
            </div>

            <div v-if="agg.top_failing_webhooks.length" class="aw-fail-list">
              <div
                v-for="(wh, i) in agg.top_failing_webhooks"
                :key="wh.id"
                class="aw-fail-row"
                :class="{
                  'aw-fail-row--inactive': !wh.is_active,
                  'aw-fail-row--selected': selectedIds.has(wh.id),
                }"
              >
                <input
                  type="checkbox"
                  class="aw-fail-checkbox"
                  :checked="selectedIds.has(wh.id)"
                  :title="selectedIds.has(wh.id) ? 'Deselect' : 'Select for bulk action'"
                  @change="toggleSelected(wh.id)"
                />
                <span class="aw-fail-rank">#{{ i + 1 }}</span>
                <div class="aw-fail-main">
                  <code class="aw-fail-url" :title="wh.url">{{ shortUrl(wh.url) }}</code>
                  <span class="aw-fail-meta">
                    <span class="aw-stat-pill" :class="wh.is_active ? 'aw-stat-pill--green' : 'aw-stat-pill--muted'">
                      {{ wh.is_active ? 'ACTIVE' : 'DISABLED' }}
                    </span>
                    ·
                    <code>{{ wh.developer_email || `dev#${wh.developer_id}` }}</code>
                  </span>
                  <span
                    v-if="testResults[wh.id]"
                    class="aw-fail-test-result"
                    :class="testResults[wh.id].success ? 'aw-fail-test-result--ok' : 'aw-fail-test-result--err'"
                  >
                    {{ testResults[wh.id].success ? '✓' : '✕' }}
                    test {{ testResults[wh.id].success ? 'OK' : 'FAILED' }}
                    <code>{{ testResults[wh.id].status_code ?? '—' }}</code>
                  </span>
                </div>
                <span class="aw-fail-count">{{ wh.failure_count }}<span class="aw-fail-count-unit"> fails</span></span>
              </div>
            </div>
            <div v-else class="aw-empty-mini">No webhooks have failed yet.</div>
          </div>
        </div>

        <!-- Recent deliveries feed -->
        <div class="aw-section">
          <div class="aw-section-head">
            <span class="aw-section-title">RECENT DELIVERIES</span>
            <div class="aw-feed-filters">
              <button
                v-for="s in STATUS_FILTERS" :key="s.value"
                class="aw-chip-btn"
                :class="{ 'aw-chip-btn--active': statusFilter === s.value }"
                :disabled="loading"
                @click="setStatusFilter(s.value)"
              >{{ s.label }}</button>
              <select class="aw-select" v-model="eventTypeFilter" @change="onFilterChange" :aria-label="t('adminWebhooksView.eventTypeAria', 'Filter by event type')">
                <option value="">All event types</option>
                <option v-for="e in agg.top_event_types" :key="e.event_type" :value="e.event_type">{{ e.event_type }}</option>
              </select>
            </div>
          </div>

          <div v-if="deliveriesLoading && !deliveries.length" class="aw-empty-mini">Loading…</div>
          <ReadFailedNotice v-else-if="deliveriesFailed && !deliveries.length" dense :retry="loadDeliveriesOnly" data-testid="aw-deliveries-failed" />
          <div v-else-if="!deliveries.length" class="aw-empty-mini">No deliveries match this filter.</div>
          <div v-else class="aw-feed-list">
            <div
              v-for="d in deliveries"
              :key="d.id"
              class="aw-feed-row"
              :class="{ 'aw-feed-row--expanded': expandedId === d.id }"
              @click="toggleExpand(d.id)"
            >
              <div class="aw-feed-head">
                <span class="aw-feed-time" :title="d.delivered_at || ''">{{ formatHHMMSS(d.delivered_at) }}</span>
                <span class="aw-feed-date">{{ formatDate(d.delivered_at) }}</span>
                <span class="aw-status-pill" :class="statusPillClass(d.response_status)">
                  {{ statusLabel(d.response_status) }}
                </span>
                <span v-if="d.response_status !== null" class="aw-feed-code">{{ d.response_status }}</span>
                <span class="aw-feed-event-pill">{{ d.event_type }}</span>
                <span v-if="d.retry_count > 0" class="aw-stat-pill aw-stat-pill--warn">retries: {{ d.retry_count }}</span>
                <code class="aw-feed-url" :title="d.webhook_url || ''">{{ shortUrl(d.webhook_url) }}</code>
                <span class="aw-feed-spacer"></span>
                <span class="aw-feed-dev">
                  {{ d.developer_email || `dev#${d.developer_id ?? '?'}` }}
                  <!-- B (2026-05-08): drilldown to AdminDevelopers detail for
                       this developer (sees their account + other webhooks +
                       funding history). -->
                  <button
                    v-if="d.developer_id"
                    class="aw-icon-btn aw-icon-btn--small"
                    @click.stop="goToDeveloper(d.developer_id)"
                    title="Open developer detail (account, agents, webhooks, funding)"
                  >⤴</button>
                </span>
                <span class="aw-feed-caret">{{ expandedId === d.id ? '▾' : '▸' }}</span>
              </div>

              <div v-if="expandedId === d.id" class="aw-feed-detail" @click.stop>
                <div class="aw-detail-grid">
                  <div class="aw-detail-pair">
                    <span class="aw-detail-key">Delivery ID</span>
                    <span class="aw-detail-val ae-mono">
                      <code>{{ d.id }}</code>
                      <button class="aw-icon-btn" @click.stop="copyText(d.id)" title="Copy delivery ID">⎘</button>
                    </span>
                  </div>
                  <div class="aw-detail-pair">
                    <span class="aw-detail-key">Webhook ID</span>
                    <span class="aw-detail-val ae-mono">
                      <code>{{ d.webhook_id }}</code>
                      <button class="aw-icon-btn" @click.stop="copyText(d.webhook_id)" title="Copy webhook ID">⎘</button>
                    </span>
                  </div>
                  <div v-if="d.next_retry_at" class="aw-detail-pair">
                    <span class="aw-detail-key">Next retry</span>
                    <span class="aw-detail-val">{{ formatAbs(d.next_retry_at) }}</span>
                  </div>
                </div>
                <div v-if="d.error_message" class="aw-detail-section">
                  <div class="aw-detail-key">Error message</div>
                  <pre class="aw-detail-pre aw-detail-pre--err">{{ d.error_message }}</pre>
                </div>
                <div v-if="d.response_body" class="aw-detail-section">
                  <div class="aw-detail-key">Response body (truncated to 500 chars)</div>
                  <pre class="aw-detail-pre">{{ d.response_body }}</pre>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="aw-footer">
          <code>/admin/webhooks/aggregate?period={{ agg.period }}</code>
          <span> · as of {{ formatAbs(agg.as_of) }}</span>
        </div>
      </template>
    </div>

    <!-- #3 (2026-05-08): bulk-action confirmation modal -->
    <ConfirmActionModal
      :show="!!bulkAction"
      :title="bulkAction === 'test'
        ? `Test ${selectedIds.size} webhook${selectedIds.size === 1 ? '' : 's'}`
        : bulkAction === 'enable'
          ? `Re-enable ${selectedIds.size} webhook${selectedIds.size === 1 ? '' : 's'}`
          : `Disable ${selectedIds.size} webhook${selectedIds.size === 1 ? '' : 's'}`"
      :message="bulkAction === 'test'
        ? `Send a test event to ${selectedIds.size} webhook${selectedIds.size === 1 ? '' : 's'} across developer accounts. Each fires a webhook.test event and writes a delivery row. Concurrency capped at 5.`
        : bulkAction === 'enable'
          ? `Re-enable ${selectedIds.size} webhook${selectedIds.size === 1 ? '' : 's'}. failure_count will be reset to 0 so the retry worker stops backing off.`
          : `Disable ${selectedIds.size} webhook${selectedIds.size === 1 ? '' : 's'}. The retry worker will stop delivering until they're re-enabled. Owners can re-enable from /webhooks.`"
      :tone="bulkAction === 'disable' ? 'warn' : 'primary'"
      :confirm-text="bulkAction === 'test'
        ? 'Test all'
        : bulkAction === 'enable'
          ? 'Re-enable all'
          : 'Disable all'"
      cancel-text="Cancel"
      :busy="bulkBusy"
      @confirm="executeBulk"
      @close="closeBulkAction"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * AdminWebhooks — Webhook Watchtower
 *
 * Build #8 (2026-05-07). Cluster-wide oversight, distinct from per-developer
 * /webhooks self-service. Surfaces:
 *  - Total webhook counts (active/inactive)
 *  - Delivery success/failure/pending breakdown over period
 *  - Top event types flowing
 *  - Top failing webhooks
 *  - Recent deliveries feed with status/event filters
 *  - Auto-refresh 30s (visibility-guarded)
 */
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { usePolledData } from '@/composables/usePolledData'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import {
  webhooksAdminService,
  type WebhookPeriod,
  type DeliveryStatus,
  type WebhooksAggregate,
  type WebhookDeliveryRow,
} from '@/services/api/webhooksAdmin'
import { deliveryOutcome } from '@/services/webhookDeliveryOutcome'

const { t } = useI18n()

const uiStore = useUIStore()
const router = useRouter()

// B (2026-05-08): drilldown helper. Opens AdminDevelopers detail drawer
// for the given developer ID, where ops can see their other webhooks +
// agents + funding history.
function goToDeveloper(developerId: number) {
  router.push({ path: '/admin/developers', query: { id: String(developerId) } }).catch(() => {})
}

const PERIODS: { value: WebhookPeriod; label: string }[] = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'all', label: 'All' },
]

const STATUS_FILTERS: { value: DeliveryStatus; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'success', label: 'Success' },
  { value: 'failed', label: 'Failed' },
  { value: 'pending', label: 'Pending' },
  { value: 'retried', label: 'Retried' },
]

const period = ref<WebhookPeriod>('24h')
const statusFilter = ref<DeliveryStatus>('all')
const eventTypeFilter = ref<string>('')

const agg = ref<WebhooksAggregate | null>(null)
const deliveries = ref<WebhookDeliveryRow[]>([])
const loading = ref(false)
const deliveriesLoading = ref(false)
// §FESUITE (2026-10-05): a filter switch whose read failed only toasted and left the previous filter's deliveries under the
// new chip. The feed answers one filter: a switch never shows the old filter's rows, a failed refresh of the same filter
// keeps them, a failed read with nothing shown says so, and a late answer is dropped.
const deliveriesFailed = ref(false)
let shownDeliveries: string | null = null
let deliveriesSeq = 0
const deliveriesKey = () => `${statusFilter.value}|${eventTypeFilter.value || ''}`
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const autoRefresh = ref(true)
const expandedId = ref<string | null>(null)

// #3 (2026-05-08): cluster-scope bulk actions on TOP FAILING WEBHOOKS list.
// Cluster admin can multi-select failing webhooks and bulk TEST / DISABLE /
// RE-ENABLE across developer accounts. Mirrors WebhookManager bulk pattern
// (Build #17, owner-tier) but routes through admin-tier endpoints
// (/admin/webhooks/{id}/{test,disable,enable}) which bypass ownership.
type BulkAction = 'test' | 'enable' | 'disable'
const selectedIds = ref<Set<string>>(new Set())
const bulkAction = ref<BulkAction | null>(null)
const bulkBusy = ref(false)
const testResults = ref<Record<string, { success: boolean; status_code: number | null }>>({})

const failingWebhookIds = computed<string[]>(() =>
  agg.value?.top_failing_webhooks.map((w) => w.id) || []
)
const allFailingSelected = computed(() => {
  const ids = failingWebhookIds.value
  return ids.length > 0 && ids.every((id) => selectedIds.value.has(id))
})
const someFailingSelected = computed(() =>
  failingWebhookIds.value.some((id) => selectedIds.value.has(id))
)

function toggleSelected(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}
function toggleSelectAllFailing() {
  if (allFailingSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(failingWebhookIds.value)
  }
}
function clearSelection() {
  selectedIds.value = new Set()
}
function openBulkAction(action: BulkAction) {
  if (selectedIds.value.size === 0) return
  bulkAction.value = action
}
function closeBulkAction() {
  if (bulkBusy.value) return
  bulkAction.value = null
}
async function executeBulk() {
  if (!bulkAction.value || bulkBusy.value) return
  const action = bulkAction.value
  const ids = Array.from(selectedIds.value)
  bulkBusy.value = true
  let okCount = 0
  let failCount = 0

  // Concurrency cap of 5 — backend doesn't serialize webhook test fires,
  // but admin actions across N developers could spike outbound HTTP if
  // unbounded.
  const CONCURRENCY = 5
  for (let i = 0; i < ids.length; i += CONCURRENCY) {
    const batch = ids.slice(i, i + CONCURRENCY)
    const results = await Promise.all(
      batch.map(async (id) => {
        try {
          if (action === 'test') {
            const r = await webhooksAdminService.testWebhook(id)
            testResults.value[id] = { success: r.success, status_code: r.status_code }
            // Auto-clear after 8s so the inline banner doesn't linger forever
            setTimeout(() => {
              const next = { ...testResults.value }
              delete next[id]
              testResults.value = next
            }, 8000)
            return r.success
          } else if (action === 'enable') {
            await webhooksAdminService.enableWebhook(id)
            return true
          } else {
            await webhooksAdminService.disableWebhook(id)
            return true
          }
        } catch {
          return false
        }
      })
    )
    for (const ok of results) {
      if (ok) okCount++
      else failCount++
    }
  }

  bulkBusy.value = false
  bulkAction.value = null
  selectedIds.value = new Set()

  const verb = action === 'test' ? 'tested' : action === 'enable' ? 're-enabled' : 'disabled'
  if (failCount > 0) {
    uiStore.showWarning?.(
      `Bulk ${verb} with errors`,
      `${okCount} succeeded · ${failCount} failed`
    )
  } else {
    uiStore.showSuccess?.(
      `Bulk ${verb}`,
      `${okCount} webhook${okCount === 1 ? '' : 's'} ${verb}.`
    )
  }
  // Re-fetch aggregate so failure_count + is_active reflect new reality.
  await refresh()
}

// F (2026-05-08): usePolledData composable replaces hand-rolled polling.
const polled = usePolledData(refresh, {
  interval: 30_000,
  immediate: true,
  pauseWhenHidden: true,
  autoStart: true,
})
watch(autoRefresh, (on) => { on ? polled.resume() : polled.pause() })

watch([period], () => { void refresh() })

// §FESUITE V0578: a period switch whose read failed only toasted and left the previous period's figures under the new
// period's button. The figures answer the period on its button: a switch clears them (the read then says it failed), a
// failed refresh of the same period keeps them (its toast says the refresh failed).
let aggFor: WebhookPeriod | null = null
async function refresh() {
  const want = period.value
  if (aggFor !== want) agg.value = null
  loading.value = true
  error.value = null
  try {
    // Fire both calls in parallel
    const [aggRes, delivRes] = await Promise.all([
      webhooksAdminService.aggregate(period.value),
      webhooksAdminService.recentDeliveries({
        limit: 100,
        status: statusFilter.value,
        event_type: eventTypeFilter.value || undefined,
      }),
    ])
    agg.value = aggRes
    aggFor = want
    deliveries.value = delivRes.deliveries
    shownDeliveries = deliveriesKey()
    deliveriesFailed.value = false
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Failed to load webhook health'
    error.value = msg
    uiStore.showError?.('Webhooks', msg)
  } finally {
    loading.value = false
  }
}

async function loadDeliveriesOnly() {
  const want = deliveriesKey()
  const my = ++deliveriesSeq
  if (shownDeliveries !== want) { deliveries.value = []; deliveriesFailed.value = false }
  deliveriesLoading.value = true
  try {
    const r = await webhooksAdminService.recentDeliveries({
      limit: 100,
      status: statusFilter.value,
      event_type: eventTypeFilter.value || undefined,
    })
    if (my !== deliveriesSeq) return
    deliveries.value = r.deliveries
    shownDeliveries = want
    deliveriesFailed.value = false
  } catch (e: any) {
    if (my !== deliveriesSeq) return
    if (shownDeliveries !== want) deliveriesFailed.value = true
    uiStore.showError?.('Webhooks', e?.response?.data?.detail || e?.message || 'Failed to load deliveries')
  } finally {
    if (my === deliveriesSeq) deliveriesLoading.value = false
  }
}

function setPeriod(p: WebhookPeriod) {
  if (period.value === p) return
  period.value = p
}
function setStatusFilter(s: DeliveryStatus) {
  if (statusFilter.value === s) return
  statusFilter.value = s
  void loadDeliveriesOnly()
}
function onFilterChange() {
  void loadDeliveriesOnly()
}
function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

const periodLabel = computed(() => PERIODS.find(p => p.value === period.value)?.label || period.value)

const successRateClass = computed(() => {
  const r = agg.value?.deliveries_in_window?.success_rate_pct
  if (r === null || r === undefined) return 'aw-stat-val--muted'
  if (r >= 99) return 'aw-stat-val--green'
  if (r >= 90) return 'aw-stat-val--cyan'
  if (r >= 50) return 'aw-stat-val--warn'
  return 'aw-stat-val--red'
})

const eventRows = computed(() => {
  if (!agg.value) return []
  const total = agg.value.deliveries_in_window.total || 1
  return agg.value.top_event_types.map(e => ({
    ...e,
    pct: (e.count / total) * 100,
  }))
})

// ── Helpers ────────────────────────────────────
function shortUrl(u: string | null | undefined): string {
  if (!u) return '—'
  if (u.length <= 50) return u
  return u.slice(0, 30) + '…' + u.slice(-12)
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

// §DOCSFIX D6-786: the registry's rule (services/webhookDeliveryOutcome), the one the feed's filter and the window counts
// read: a 3xx is a failed attempt (not followed, and retried), never "OTHER" beside a count that left it out
function statusLabel(code: number | null | undefined): string {
  return { success: 'SUCCESS', failed: 'FAILED', pending: 'PENDING' }[deliveryOutcome(code)]
}
function statusPillClass(code: number | null | undefined): string {
  return { success: 'aw-status-pill--green', failed: 'aw-status-pill--red', pending: 'aw-status-pill--muted' }[deliveryOutcome(code)]
}

async function copyText(s: string) {
  try {
    await navigator.clipboard.writeText(s)
    uiStore.showSuccess?.('Copied', s.length > 40 ? s.slice(0, 40) + '…' : s)
  } catch { /* expected */ }
}
</script>

<style scoped>
.aw {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}

/* ── Ambient ──────────── */
.aw-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.aw-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}
.aw-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.aw-glow-1 { width: 420px; height: 420px; background: rgba(255, 149, 0, 0.5); top: -100px; right: -80px; }
.aw-glow-2 { width: 320px; height: 320px; background: rgba(var(--cyan-rgb), 0.4); bottom: -60px; left: -100px; }

/* ── Hero ──────────────── */
.aw-hero { position: relative; z-index: 1; padding: 36px 32px 18px; }
.aw-hero-inner { max-width: 1280px; margin: 0 auto; }
.aw-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
  margin-bottom: 14px;
}
.aw-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
}
.aw-h1 {
  font-size: 2.1rem;
  margin: 0 0 0.4rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}
.aw-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.aw-lead {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 16px;
  line-height: 1.5;
  max-width: 60rem;
}
.aw-link { color: var(--cyan); text-decoration: none; border-bottom: 1px dotted rgba(var(--cyan-rgb), 0.5); }
.aw-link:hover { color: rgba(var(--cyan-rgb), 1); }

/* ── Toolbar ──────────── */
.aw-toolbar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.8rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.aw-toolbar-group { display: flex; align-items: center; gap: 0.4rem; }
.aw-toolbar-spacer { flex: 1; }
.aw-toolbar-meta { margin-left: 0.3rem; }
.aw-toolbar-label {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.45);
  text-transform: uppercase;
}
.aw-toolbar-val {
  font-family: var(--mono); font-size: 0.78rem; font-weight: 700; color: var(--cyan);
}

.aw-period-btn {
  font-family: var(--mono); font-size: 0.65rem; font-weight: 600; letter-spacing: 0.06em;
  background: transparent; color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px; padding: 4px 10px; cursor: pointer;
  transition: all 0.15s; text-transform: uppercase;
}
.aw-period-btn:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.9);
}
.aw-period-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
  box-shadow: 0 0 8px rgba(var(--cyan-rgb), 0.18);
}
.aw-period-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.aw-toggle {
  display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.7);
}
.aw-toggle input { display: none; }
.aw-toggle-track {
  width: 26px; height: 14px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 7px; position: relative;
  transition: background 0.15s;
}
.aw-toggle-knob {
  position: absolute; top: 2px; left: 2px;
  width: 10px; height: 10px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  transition: transform 0.15s, background 0.15s;
}
.aw-toggle input:checked ~ .aw-toggle-track { background: rgba(var(--cyan-rgb), 0.3); }
.aw-toggle input:checked ~ .aw-toggle-track .aw-toggle-knob {
  transform: translateX(12px); background: var(--cyan);
}
.aw-toggle-label { font-weight: 600; }

/* ── Body ──────────── */
.aw-body {
  position: relative; z-index: 1;
  padding: 0 32px;
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.aw-btn {
  display: inline-flex; align-items: center; gap: 0.35rem;
  font-family: var(--mono); font-size: 0.65rem;
  letter-spacing: 0.08em; font-weight: 600;
  padding: 4px 10px; border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s;
}
.aw-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.aw-btn--ghost {
  background: transparent;
  border-color: rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.85);
}
.aw-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  border-color: rgba(var(--cyan-rgb), 0.5);
  color: rgba(var(--cyan-rgb), 1);
}

/* ── Center ──────────── */
.aw-center {
  text-align: center;
  padding: 5rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 6px;
}
.aw-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: rgba(var(--cyan-rgb), 0.95);
  border-radius: 50%;
  animation: aw-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes aw-spin { to { transform: rotate(360deg); } }
.aw-loading-text {
  font-family: var(--mono); font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.aw-error-text {
  font-family: var(--mono); font-size: 0.85rem;
  color: var(--nc-danger);
}

/* ── Hero stats ──────────── */
.aw-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}
.aw-stat-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 1.05rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.aw-stat-key {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.14em; font-weight: 700;
  color: var(--cyan);
  text-transform: uppercase;
}
.aw-stat-val {
  font-family: var(--mono);
  font-size: 1.7rem; font-weight: 700;
  letter-spacing: -0.02em; line-height: 1.05;
}
.aw-stat-val--cyan { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.4); }
.aw-stat-val--green { color: var(--nc-success, #00ff88); text-shadow: 0 0 14px rgba(0, 255, 136, 0.35); }
.aw-stat-val--violet { color: #c084fc; text-shadow: 0 0 14px rgba(168, 85, 247, 0.35); }
.aw-stat-val--red { color: var(--nc-danger, #ff3366); text-shadow: 0 0 14px rgba(255, 51, 102, 0.45); }
.aw-stat-val--warn { color: var(--nc-warning, #ff9500); text-shadow: 0 0 14px rgba(255, 149, 0, 0.4); }
.aw-stat-val--muted { color: rgba(255, 255, 255, 0.45); }
.aw-stat-sub {
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.04em;
  display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap;
}
.aw-stat-sub-grid { display: flex; gap: 0.4rem; flex-wrap: wrap; }

.aw-stat-pill {
  display: inline-block;
  font-family: var(--mono); font-size: 0.55rem; font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px; border-radius: 3px;
  border: 1px solid transparent;
}
.aw-stat-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.aw-stat-pill--red   { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.aw-stat-pill--warn  { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.aw-stat-pill--muted { background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.6); border-color: rgba(var(--cyan-rgb), 0.18); }

/* ── Section ──────────── */
.aw-section {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 8px;
  padding: 1rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.7rem;
}
.aw-section-head {
  display: flex; justify-content: space-between; align-items: center;
  gap: 1rem; flex-wrap: wrap;
}
.aw-section-title {
  font-family: var(--mono); font-size: 0.65rem;
  letter-spacing: 0.14em; font-weight: 700;
  color: var(--cyan);
  text-transform: uppercase;
}
.aw-section-sub {
  font-family: var(--mono); font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.45);
  letter-spacing: 0.06em;
}

/* ── Twocol ──────────── */
.aw-twocol {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
}

/* ── Event list ──────────── */
.aw-event-list { display: flex; flex-direction: column; gap: 0.4rem; }
.aw-event-row {
  display: grid;
  grid-template-columns: minmax(0, 200px) 1fr auto auto;
  align-items: center; gap: 0.6rem;
  font-family: var(--mono); font-size: 0.7rem;
}
.aw-event-label {
  color: rgba(255, 255, 255, 0.85);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  font-size: 0.65rem;
}
.aw-event-bar {
  position: relative; height: 6px;
  background: rgba(var(--cyan-rgb), 0.1);
  border-radius: 3px; overflow: hidden;
}
.aw-event-bar-fill {
  position: absolute; inset: 0;
  background: linear-gradient(90deg, rgba(var(--cyan-rgb), 0.5), var(--cyan));
  border-radius: 3px; transition: width 0.3s;
}
.aw-event-val { color: var(--cyan); font-weight: 600; font-size: 0.7rem; }
.aw-event-pct { font-size: 0.6rem; color: rgba(255, 255, 255, 0.55); min-width: 3rem; text-align: right; }

/* ── Failing list ──────────── */
.aw-fail-list { display: flex; flex-direction: column; gap: 0.4rem; }
.aw-fail-row {
  display: grid;
  grid-template-columns: 22px 30px 1fr auto;
  align-items: center; gap: 0.5rem;
  padding: 6px 9px;
  background: rgba(255, 51, 102, 0.04);
  border: 1px solid rgba(255, 51, 102, 0.18);
  border-radius: 4px;
  transition: background 0.15s, border-color 0.15s;
}
.aw-fail-row--inactive {
  background: rgba(var(--cyan-rgb), 0.02);
  border-color: rgba(var(--cyan-rgb), 0.12);
}
.aw-fail-row--selected {
  background: rgba(var(--cyan-rgb), 0.10);
  border-color: rgba(var(--cyan-rgb), 0.45);
}
.aw-fail-checkbox {
  width: 14px; height: 14px;
  accent-color: var(--cyan);
  cursor: pointer;
}
.aw-fail-test-result {
  font-family: var(--mono); font-size: 0.58rem; font-weight: 600;
  letter-spacing: 0.04em; padding: 1px 6px; border-radius: 3px;
  display: inline-flex; gap: 0.3rem; align-items: center;
  margin-top: 2px;
}
.aw-fail-test-result code {
  background: rgba(0, 0, 0, 0.25); padding: 0 4px; border-radius: 2px;
}
.aw-fail-test-result--ok {
  background: rgba(0, 220, 130, 0.12);
  color: rgba(0, 220, 130, 0.95);
  border: 1px solid rgba(0, 220, 130, 0.35);
}
.aw-fail-test-result--err {
  background: rgba(255, 51, 102, 0.12);
  color: rgba(255, 90, 130, 0.95);
  border: 1px solid rgba(255, 51, 102, 0.35);
}

/* ── Bulk action bar (#3, 2026-05-08) ──────── */
.aw-bulk-bar {
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
  padding: 6px 9px;
  margin-bottom: 0.5rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.14);
  border-radius: 4px;
  transition: border-color 0.15s, background 0.15s;
}
.aw-bulk-bar--active {
  background: rgba(var(--cyan-rgb), 0.08);
  border-color: rgba(var(--cyan-rgb), 0.45);
}
.aw-bulk-checkbox {
  display: flex; align-items: center; gap: 0.4rem;
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
}
.aw-bulk-checkbox input { width: 14px; height: 14px; accent-color: var(--cyan); cursor: pointer; }
.aw-bulk-summary { font-weight: 600; letter-spacing: 0.04em; }
.aw-bulk-spacer { flex: 1; }
.aw-btn--bulk {
  font-family: var(--mono); font-size: 0.6rem; font-weight: 700;
  letter-spacing: 0.08em;
  border-radius: 4px;
  padding: 4px 12px; cursor: pointer; text-transform: uppercase;
  transition: all 0.15s;
}
.aw-btn--bulk:disabled { opacity: 0.45; cursor: not-allowed; }
.aw-btn--test {
  background: rgba(var(--cyan-rgb), 0.12);
  color: var(--cyan);
  border: 1px solid rgba(var(--cyan-rgb), 0.45);
}
.aw-btn--test:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.22);
}
.aw-btn--enable {
  background: rgba(0, 220, 130, 0.10);
  color: rgba(0, 220, 130, 0.9);
  border: 1px solid rgba(0, 220, 130, 0.35);
}
.aw-btn--enable:hover:not(:disabled) {
  background: rgba(0, 220, 130, 0.20);
}
.aw-btn--disable {
  background: rgba(255, 165, 0, 0.10);
  color: rgba(255, 180, 60, 0.95);
  border: 1px solid rgba(255, 165, 0, 0.40);
}
.aw-btn--disable:hover:not(:disabled) {
  background: rgba(255, 165, 0, 0.20);
}
.aw-fail-rank {
  font-family: var(--mono); color: var(--nc-danger, #ff3366);
  font-weight: 700; font-size: 0.65rem;
}
.aw-fail-row--inactive .aw-fail-rank { color: rgba(255, 255, 255, 0.4); }
.aw-fail-main {
  display: flex; flex-direction: column; gap: 2px;
  min-width: 0;
}
.aw-fail-url {
  font-family: var(--mono); font-size: 0.66rem;
  color: rgba(255, 255, 255, 0.85);
  background: transparent;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.aw-fail-meta {
  font-family: var(--mono); font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.5);
  display: flex; align-items: center; gap: 0.35rem;
}
.aw-fail-meta code {
  background: rgba(var(--cyan-rgb), 0.06);
  color: rgba(255, 255, 255, 0.75);
  padding: 1px 5px; border-radius: 3px;
}
.aw-fail-count {
  font-family: var(--mono); font-size: 1rem; font-weight: 700;
  color: var(--nc-danger, #ff3366);
}
.aw-fail-row--inactive .aw-fail-count { color: rgba(255, 255, 255, 0.5); }
.aw-fail-count-unit {
  font-size: 0.55rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.5);
  margin-left: 0.2rem;
}

/* ── Feed filters ──────────── */
.aw-feed-filters { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
.aw-chip-btn {
  font-family: var(--mono); font-size: 0.6rem; font-weight: 600;
  letter-spacing: 0.06em;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px;
  padding: 3px 9px; cursor: pointer;
  transition: all 0.15s; text-transform: uppercase;
}
.aw-chip-btn:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.06);
  color: rgba(255, 255, 255, 0.9);
}
.aw-chip-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.aw-chip-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.aw-select {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  color: rgba(255, 255, 255, 0.9);
  border-radius: 4px;
  font-family: var(--mono); font-size: 0.65rem;
  padding: 3px 7px;
  outline: none;
}

/* ── Feed list ──────────── */
.aw-feed-list { display: flex; flex-direction: column; gap: 0.35rem; }
.aw-feed-row {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  overflow: hidden;
}
.aw-feed-row:hover {
  background: rgba(var(--cyan-rgb), 0.04);
  border-color: rgba(var(--cyan-rgb), 0.25);
}
.aw-feed-row--expanded {
  background: rgba(var(--cyan-rgb), 0.06);
  border-color: rgba(var(--cyan-rgb), 0.4);
}
.aw-feed-head {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.45rem 0.75rem;
  flex-wrap: wrap;
  font-family: var(--mono);
}
.aw-feed-time {
  font-size: 0.7rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}
.aw-feed-date {
  font-size: 0.6rem; color: rgba(255, 255, 255, 0.5);
}
.aw-feed-code {
  font-size: 0.62rem;
  background: rgba(var(--cyan-rgb), 0.05);
  padding: 1px 5px;
  border-radius: 3px;
  color: rgba(255, 255, 255, 0.75);
}
.aw-feed-event-pill {
  font-size: 0.6rem; font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(168, 85, 247, 0.1);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.3);
}
.aw-feed-url {
  font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.65);
  background: rgba(var(--cyan-rgb), 0.04);
  padding: 1px 5px; border-radius: 3px;
}
.aw-feed-spacer { flex: 1; }
.aw-feed-dev {
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.5);
}
.aw-feed-caret {
  font-size: 0.7rem;
  color: rgba(var(--cyan-rgb), 0.6);
}

.aw-status-pill {
  font-family: var(--mono); font-size: 0.58rem; font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px; border-radius: 3px;
  border: 1px solid transparent;
}
.aw-status-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.aw-status-pill--red   { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.aw-status-pill--cyan  { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.aw-status-pill--muted { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(255, 255, 255, 0.15); }

/* ── Feed detail ──────────── */
.aw-feed-detail {
  padding: 0.7rem 0.85rem 0.85rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
  display: flex; flex-direction: column; gap: 0.6rem;
  cursor: default;
}
.aw-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.4rem 0.85rem;
}
.aw-detail-pair {
  display: flex; flex-direction: column; gap: 0.15rem;
}
.aw-detail-key {
  font-family: var(--mono); font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase; font-weight: 600;
}
.aw-detail-val {
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: center; gap: 0.35rem;
}
.aw-detail-val code {
  background: rgba(var(--cyan-rgb), 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  word-break: break-all;
  font-size: 0.65rem;
}
.aw-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-family: monospace; font-size: 0.7rem;
  padding: 0 5px; cursor: pointer;
  transition: all 0.12s;
}
.aw-icon-btn:hover {
  background: rgba(var(--cyan-rgb), 0.1);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.aw-detail-section { margin-top: 0.2rem; }
.aw-detail-pre {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 4px;
  padding: 6px 9px;
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.75);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 14rem;
  overflow-y: auto;
}
.aw-detail-pre--err {
  background: rgba(255, 51, 102, 0.06);
  border-color: rgba(255, 51, 102, 0.3);
  color: rgba(255, 200, 200, 0.85);
}

/* ── Empty mini ──────────── */
.aw-empty-mini {
  text-align: center;
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.4);
  padding: 1.4rem;
  letter-spacing: 0.06em;
}

/* ── Footer ──────────── */
.aw-footer {
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5);
  padding-top: 0.5rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.aw-footer code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px; border-radius: 3px;
}

.ae-mono { font-family: var(--mono); }

/* ── Responsive ──────────── */
@media (max-width: 1100px) {
  .aw-stats { grid-template-columns: 1fr 1fr; }
  .aw-twocol { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .aw-hero { padding: 24px 16px 12px; }
  .aw-h1 { font-size: 1.5rem; }
  .aw-body { padding: 0 16px; }
  .aw-stats { grid-template-columns: 1fr; }
  .aw-feed-head { gap: 0.35rem; }
}
</style>
