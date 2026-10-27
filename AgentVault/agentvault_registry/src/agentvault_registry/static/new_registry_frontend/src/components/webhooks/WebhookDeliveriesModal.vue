<template>
  <Teleport to="body">
    <div class="wh-modal-backdrop">
      <div class="flex min-h-screen items-center justify-center p-4">
        <!-- Overlay -->
        <div class="fixed inset-0 bg-black/70 backdrop-blur-xs" @click="$emit('close')"></div>

        <!-- Modal -->
        <div class="wh-modal relative w-full max-w-5xl" role="dialog" aria-modal="true" aria-labelledby="wh-dl-title">

          <!-- ══ HEADER ══ -->
          <div class="wh-modal-header flex items-start justify-between">
            <div class="flex-1 min-w-0">
              <div class="wh-modal-eyebrow">// WEBHOOK // DELIVERY HISTORY</div>
              <div id="wh-dl-title" class="wh-modal-title">Delivery Log</div>
              <p class="wh-dl-url-line">
                <span class="wh-dl-url-prefix">URL</span>
                <span class="wh-dl-url-text" :title="webhook.url">{{ webhook.url }}</span>
              </p>
            </div>
            <button
              @click="$emit('close')"
              class="wh-dl-close"
              aria-label="Close delivery log"
            >✕</button>
          </div>

          <!-- ══ BODY ══ -->
          <div class="wh-dl-body">

            <!-- Toolbar — auto-refresh + filter chips + actions -->
            <div class="wh-dl-toolbar">
              <div class="wh-dl-toolbar-left">
                <span class="wh-dl-toolbar-label">FILTER</span>
                <button
                  v-for="f in FILTERS"
                  :key="f.id"
                  class="wh-dl-chip"
                  :class="{ 'wh-dl-chip--active': activeFilter === f.id }"
                  :title="f.title"
                  @click="setFilter(f.id)"
                >
                  {{ f.label }}
                  <span v-if="f.id === activeFilter && stats.byFilter !== null" class="wh-dl-chip-count">{{ stats.byFilter }}</span>
                </button>
              </div>

              <div class="wh-dl-toolbar-right">
                <span class="wh-dl-meta-key">Last refresh</span>
                <span class="wh-dl-meta-val">{{ lastRefreshAt || '—' }}</span>
                <button
                  type="button"
                  class="wh-dl-btn wh-dl-btn--ghost"
                  :title="autoRefresh ? 'Pause auto-refresh' : 'Resume auto-refresh (30s)'"
                  @click="toggleAutoRefresh"
                >
                  <span class="wh-dl-live-dot" :class="{ 'wh-dl-live-dot--on': autoRefresh }"></span>
                  {{ autoRefresh ? 'Pause' : 'Resume' }}
                </button>
                <button
                  type="button"
                  class="wh-dl-btn wh-dl-btn--ghost"
                  :disabled="webhookStore.isLoadingDeliveries"
                  title="Refresh now"
                  aria-label="Refresh deliveries"
                  @click="refresh"
                >↻ Refresh</button>
                <button
                  type="button"
                  class="wh-dl-btn wh-dl-btn--primary"
                  :disabled="testingNow || !webhook.is_active"
                  :title="webhook.is_active ? 'Send a webhook.test event to this endpoint' : 'Webhook is disabled — enable it to send test events'"
                  aria-label="Send test event"
                  @click="onTest"
                >
                  <span v-if="testingNow" class="wh-dl-spinner-inline"></span>
                  <span>{{ testingNow ? 'Sending…' : 'Test Event' }}</span>
                </button>
              </div>
            </div>

            <!-- Stats bar -->
            <div class="wh-dl-stats">
              <div class="wh-dl-stat-cell">
                <div class="wh-dl-stat-value" style="color:var(--nc-text-primary)">{{ stats.total }}</div>
                <div class="wh-dl-stat-label">SHOWING</div>
              </div>
              <div class="wh-dl-stat-cell">
                <div class="wh-dl-stat-value" style="color:var(--nc-success)">{{ stats.successful }}</div>
                <div class="wh-dl-stat-label">SUCCESS</div>
              </div>
              <div class="wh-dl-stat-cell">
                <div class="wh-dl-stat-value" style="color:var(--nc-danger)">{{ stats.failed }}</div>
                <div class="wh-dl-stat-label">FAILED</div>
              </div>
              <div class="wh-dl-stat-cell">
                <div class="wh-dl-stat-value" style="color:var(--nc-warning)">{{ stats.retried }}</div>
                <div class="wh-dl-stat-label">RETRIED</div>
              </div>
              <div class="wh-dl-stat-cell">
                <div class="wh-dl-stat-value" style="color:var(--nc-text-muted)">{{ stats.pending }}</div>
                <div class="wh-dl-stat-label">PENDING</div>
              </div>
            </div>

            <!-- Inline error banner -->
            <div v-if="webhookStore.deliveriesError" class="wh-dl-error-banner" role="alert">
              <span><Icon name="mdi:alert" /> {{ webhookStore.deliveriesError }}</span>
              <button class="wh-dl-btn wh-dl-btn--ghost" @click="refresh">Retry</button>
            </div>

            <!-- Loading skeleton (only on first load) -->
            <div v-if="webhookStore.isLoadingDeliveries && !webhookStore.deliveries.length" class="wh-dl-skeleton">
              <div v-for="i in 4" :key="i" class="wh-dl-skel-row"></div>
            </div>

            <!-- Empty -->
            <div v-else-if="webhookStore.deliveries.length === 0" class="wh-dl-empty">
              <div class="wh-dl-empty-glyph"><Icon name="mdi:inbox" /></div>
              <p class="wh-dl-empty-title">No deliveries yet</p>
              <p class="wh-dl-empty-sub">
                {{ activeFilter ? `Nothing matches the "${activeFilter}" filter.` : 'Use the Test Event button above to fire a webhook.test ping.' }}
              </p>
              <div class="wh-dl-empty-actions">
                <button v-if="activeFilter" @click="setFilter(null)" class="wh-dl-btn wh-dl-btn--ghost">Clear filter</button>
                <button v-if="!activeFilter" @click="onTest" :disabled="testingNow || !webhook.is_active" class="wh-dl-btn wh-dl-btn--primary">
                  {{ testingNow ? 'Sending…' : 'Send Test Event' }}
                </button>
              </div>
            </div>

            <!-- Delivery list -->
            <div v-else class="wh-dl-list">
              <div
                v-for="d in webhookStore.deliveries"
                :key="d.id"
                class="wh-dl-row"
                :class="rowStateClass(d)"
              >
                <!-- Row header — always visible -->
                <button
                  type="button"
                  class="wh-dl-row-head"
                  :aria-expanded="expandedId === d.id"
                  :aria-controls="`wh-dl-detail-${d.id}`"
                  @click="toggleExpand(d.id)"
                >
                  <span
                    class="wh-dl-status-dot"
                    :class="dotClass(d)"
                    :title="dotLabel(d)"
                  ></span>

                  <span class="wh-dl-row-event">{{ d.event_type }}</span>

                  <span
                    v-if="d.response_status != null"
                    class="wh-dl-pill"
                    :class="statusPillClass(d.response_status)"
                  >{{ d.response_status }}</span>
                  <span v-else class="wh-dl-pill wh-dl-pill--muted">PENDING</span>

                  <span
                    v-if="(d.retry_count || 0) > 0"
                    class="wh-dl-pill wh-dl-pill--warn"
                    :title="`Retry attempt #${d.retry_count}`"
                  >RETRY ×{{ d.retry_count }}</span>

                  <span
                    v-if="d.next_retry_at && !isSuccess(d)"
                    class="wh-dl-pill wh-dl-pill--soft"
                    :title="`Next retry at ${formatAbs(d.next_retry_at)}`"
                  >NEXT {{ timeUntil(d.next_retry_at) }}</span>

                  <span class="wh-dl-row-spacer"></span>

                  <span class="wh-dl-row-time" :title="formatAbs(d.delivered_at)">{{ timeAgo(d.delivered_at) }}</span>

                  <span class="wh-dl-row-caret">{{ expandedId === d.id ? '▾' : '▸' }}</span>
                </button>

                <!-- Expanded detail panel -->
                <div
                  v-if="expandedId === d.id"
                  :id="`wh-dl-detail-${d.id}`"
                  class="wh-dl-detail"
                >
                  <!-- Error message banner inside detail -->
                  <div v-if="d.error_message || d.error" class="wh-dl-detail-error">
                    <span class="wh-dl-detail-error-glyph">✗</span>
                    <span>{{ d.error_message || d.error }}</span>
                  </div>

                  <!-- §FEPARITY-R4: redeliver. Offered on attempts that did NOT succeed;
                       a successful delivery is not re-fired from here by accident. -->
                  <div v-if="!isSuccess(d)" class="wh-dl-redeliver" data-tour="wh-redeliver-row">
                    <div class="wh-dl-redeliver-copy">
                      <strong>Re-send this attempt</strong>
                      <span>Replays the original payload through the live delivery path. This
                      records a NEW attempt; the original row is kept for audit.</span>
                    </div>
                    <button
                      class="wh-dl-redeliver-btn"
                      data-tour="wh-redeliver-btn"
                      :disabled="redeliveringId === d.id"
                      @click.stop="doRedeliver(d)"
                    >{{ redeliveringId === d.id ? 'SENDING…' : 'REDELIVER' }}</button>
                  </div>

                  <!-- Metadata grid -->
                  <div class="wh-dl-meta-grid">
                    <div class="wh-dl-meta-pair">
                      <span class="wh-dl-meta-key">Delivery ID</span>
                      <span class="wh-dl-meta-val wh-dl-meta-val--code">
                        <code>{{ d.id }}</code>
                        <button
                          class="wh-dl-icon-btn"
                          title="Copy delivery ID"
                          aria-label="Copy delivery ID"
                          @click.stop="copyText(d.id)"
                        >⎘</button>
                      </span>
                    </div>
                    <div class="wh-dl-meta-pair">
                      <span class="wh-dl-meta-key">Delivered</span>
                      <span class="wh-dl-meta-val">{{ formatAbs(d.delivered_at) }}</span>
                    </div>
                    <div v-if="d.next_retry_at" class="wh-dl-meta-pair">
                      <span class="wh-dl-meta-key">Next retry</span>
                      <span class="wh-dl-meta-val">{{ formatAbs(d.next_retry_at) }} <span style="opacity:0.6">({{ timeUntil(d.next_retry_at) }})</span></span>
                    </div>
                    <div class="wh-dl-meta-pair">
                      <span class="wh-dl-meta-key">Retry count</span>
                      <span class="wh-dl-meta-val">{{ d.retry_count || 0 }}</span>
                    </div>
                  </div>

                  <!-- Request payload -->
                  <div class="wh-dl-section">
                    <JsonViewer
                      :data="d.payload"
                      label="Request payload (sent to your endpoint)"
                      bordered
                    />
                  </div>

                  <!-- Response body -->
                  <div v-if="d.response_body" class="wh-dl-section">
                    <JsonViewer
                      :data="d.response_body"
                      label="Response body"
                      bordered
                    />
                  </div>

                  <div v-else class="wh-dl-section wh-dl-section-muted">
                    <span class="wh-dl-meta-key">Response body</span>
                    <span style="margin-left:0.6rem;opacity:0.6">— (none returned)</span>
                  </div>
                </div>
              </div>
            </div>

          </div>

          <!-- ══ FOOTER ══ -->
          <div class="wh-modal-footer flex items-center justify-between">
            <span class="wh-dl-footer-text">
              Showing {{ webhookStore.deliveries.length }} of last {{ pageLimit }} attempts<span v-if="activeFilter"> · filtered to <strong>{{ activeFilter }}</strong></span>
            </span>
            <div class="wh-dl-footer-right">
              <button
                type="button"
                class="wh-dl-btn wh-dl-btn--ghost"
                title="Export current view as JSON"
                aria-label="Export deliveries as JSON"
                :disabled="!webhookStore.deliveries.length"
                @click="exportJson"
              >⤓ Export JSON</button>
              <button @click="$emit('close')" class="wh-dl-btn wh-dl-btn--ghost">CLOSE</button>
            </div>
          </div>

        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * WebhookDeliveriesModal — drill-down delivery log per webhook.
 *
 * Build #1 (2026-05-07) AAA+ rebuild from minimal modal:
 *   - Filter chips: All / Success / Failed / Pending / Retried (server-side)
 *   - Auto-refresh (30s, visibility-guarded, default ON)
 *   - Inline Test Event button + disabled state if webhook inactive
 *   - Expandable rows with full request payload (JsonViewer) + response body
 *   - Retry count + next-retry countdown
 *   - Copy buttons + JSON export
 *   - Inline error banner with retry, skeleton loading, empty-with-action states
 *   - ARIA: role=dialog, aria-modal, aria-expanded, aria-labelledby, aria-controls
 *   - ESC closes the modal
 *
 * Strategy doc: STRATEGY_2026-05-07_FRONTEND_BUILD_ROADMAP.md §4 Build #1.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import type { Webhook, WebhookDelivery, DeliveryStatusFilter } from '@/services/api/webhookService'
import { webhookService } from '@/services/api/webhookService'
import { deliveryOutcome } from '@/services/webhookDeliveryOutcome'
import { useWebhookStore } from '@/stores/webhooks'
import { useUIStore } from '@/stores/ui'
import JsonViewer from '@/components/common/JsonViewer.vue'

const props = defineProps<{ webhook: Webhook }>()
const emit = defineEmits<{ close: [] }>()

const webhookStore = useWebhookStore()
const uiStore = useUIStore()

const FILTERS: { id: DeliveryStatusFilter; label: string; title: string }[] = [
  { id: null,       label: 'All',      title: 'All recent deliveries' },
  { id: 'success',  label: 'Success',  title: 'HTTP 2xx responses' },
  { id: 'failed',   label: 'Failed',   title: 'Any answer other than 2xx, a redirect included' },
  { id: 'pending',  label: 'Pending',  title: 'No answer: in flight, or none came' },
  { id: 'retried',  label: 'Retried',  title: 'retry_count > 0' },
]

const activeFilter = ref<DeliveryStatusFilter>(null)
const expandedId = ref<string | null>(null)
const redeliveringId = ref<string | null>(null)
const lastRefreshAt = ref<string>('')
const autoRefresh = ref(true)
const testingNow = ref(false)
const pageLimit = 50
let pollHandle: ReturnType<typeof setInterval> | null = null

// Initial fetch — full page (50) with current filter
onMounted(() => {
  void refresh()
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})

watch(activeFilter, () => {
  // Filter changed — kick off a new fetch
  void refresh()
})

// Escape closes the log, the topmost dialog only (composables/useEscapeClose; its own document listener closed it under
// any dialog opened above it)
useEscapeClose(() => true, () => emit('close'))

async function refresh() {
  await webhookStore.fetchDeliveries(props.webhook.id, pageLimit, 0, activeFilter.value)
  lastRefreshAt.value = formatHHMMSS(new Date())
}

function setFilter(id: DeliveryStatusFilter) {
  activeFilter.value = id
  expandedId.value = null
}

/**
 * §FEPARITY-R4 — re-send one past attempt. The outcome is reported from the RESPONSE
 * (2xx vs the actual status code), never assumed from the 200 on the redeliver call
 * itself: the request to us succeeding says nothing about the customer endpoint
 * accepting the replay.
 */
async function doRedeliver(d: WebhookDelivery) {
  if (redeliveringId.value) return
  redeliveringId.value = d.id
  try {
    const res = await webhookService.redeliver(props.webhook.id, d.id)
    if (res.success) {
      uiStore.showSuccess('Redelivered', `${d.event_type} accepted (HTTP ${res.status_code}).`)
    } else {
      uiStore.showError(
        'Redelivery failed',
        `${d.event_type} — endpoint answered ${res.status_code ?? 'no response'}.`,
      )
    }
    await refresh()
    expandedId.value = null
  } catch (e: any) {
    uiStore.showError('Redelivery failed', e?.response?.data?.detail || e?.message || 'Request rejected')
  } finally {
    redeliveringId.value = null
  }
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function startPolling() {
  if (pollHandle) return
  pollHandle = setInterval(() => {
    if (!autoRefresh.value) return
    if (document.visibilityState === 'hidden') return
    refresh().catch(() => { /* error already in deliveriesError */ })
  }, 30_000)
}

function stopPolling() {
  if (pollHandle) {
    clearInterval(pollHandle)
    pollHandle = null
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    void refresh()
  }
}

async function onTest() {
  if (testingNow.value) return
  testingNow.value = true
  try {
    await webhookStore.testWebhook(props.webhook.id)
    // After test, refresh to pick up the new delivery row
    await refresh()
  } finally {
    testingNow.value = false
  }
}

const stats = computed(() => {
  const list = webhookStore.deliveries
  const successful = list.filter(d => isSuccess(d)).length
  const failed = list.filter(d => isFailure(d)).length
  const pending = list.filter(d => deliveryOutcome(d.response_status) === 'pending').length
  const retried = list.filter(d => (d.retry_count || 0) > 0).length
  return {
    total: list.length,
    successful,
    failed,
    pending,
    retried,
    byFilter: activeFilter.value ? list.length : null,
  }
})

// §DOCSFIX D6-786: the registry's rule (services/webhookDeliveryOutcome): a 2xx is a delivery, any other answer a failed
// attempt, a redirect included (not followed, and retried); "failed" read 4xx/5xx, so a redirect was counted nowhere
function isSuccess(d: WebhookDelivery): boolean {
  return d.success === true || deliveryOutcome(d.response_status) === 'success'
}
function isFailure(d: WebhookDelivery): boolean {
  return d.success === false || deliveryOutcome(d.response_status) === 'failed'
}

function dotClass(d: WebhookDelivery): string {
  if (isSuccess(d)) return 'wh-dl-status-dot--ok'
  if (d.response_status != null && d.response_status >= 300 && d.response_status < 400) return 'wh-dl-status-dot--warn'
  if (isFailure(d)) return 'wh-dl-status-dot--err'
  return 'wh-dl-status-dot--null'
}
function dotLabel(d: WebhookDelivery): string {
  if (isSuccess(d)) return 'Success'
  if (d.response_status != null && d.response_status >= 300 && d.response_status < 400) return `Failed: redirect (${d.response_status}), not followed`
  if (isFailure(d)) return 'Failed'
  return 'Pending or never delivered'
}

function rowStateClass(d: WebhookDelivery): string[] {
  const out: string[] = ['wh-dl-row']
  if (isSuccess(d)) out.push('wh-dl-row--ok')
  else if (isFailure(d)) out.push('wh-dl-row--err')
  else if (d.response_status == null) out.push('wh-dl-row--pending')
  if (expandedId.value === d.id) out.push('wh-dl-row--expanded')
  return out
}

function statusPillClass(status: number): string {
  if (status >= 200 && status < 300) return 'wh-dl-pill--ok'
  if (status >= 300 && status < 400) return 'wh-dl-pill--warn'
  if (status >= 400 && status < 500) return 'wh-dl-pill--err'
  if (status >= 500) return 'wh-dl-pill--err'
  return 'wh-dl-pill--muted'
}

function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
function formatHHMMSS(d: Date): string {
  return d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}
function timeUntil(iso: string | null | undefined): string {
  if (!iso) return ''
  const ms = new Date(iso).getTime() - Date.now()
  if (ms <= 0) return 'now'
  if (ms < 60_000) return `in ${Math.floor(ms / 1_000)}s`
  if (ms < 3_600_000) return `in ${Math.floor(ms / 60_000)}m`
  return `in ${Math.floor(ms / 3_600_000)}h`
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    uiStore.showSuccess?.('Copied', text.length > 40 ? text.slice(0, 40) + '…' : text)
  } catch {
    /* expected */
  }
}

function exportJson() {
  const list = webhookStore.deliveries
  if (!list.length) return
  const payload = {
    webhook_id: props.webhook.id,
    webhook_url: props.webhook.url,
    exported_at: new Date().toISOString(),
    filter: activeFilter.value,
    deliveries: list,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `webhook-${props.webhook.id.slice(0, 8)}-deliveries-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 4000)
  uiStore.showSuccess?.('Exported', `${list.length} deliveries downloaded.`)
}
</script>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
@import '@/assets/styles/tp-webhooks.css';

/* ─── Backdrop ─── */
.wh-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  overflow-y: auto;
}

/* ─── Header URL line ─── */
.wh-dl-url-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  margin-top: 0.25rem;
  min-width: 0;
}
.wh-dl-url-prefix {
  color: rgba(var(--nc-primary-rgb), 0.9);
  font-size: 0.55rem;
  letter-spacing: 0.16em;
  font-weight: 600;
}
.wh-dl-url-text {
  color: rgba(var(--nc-primary-rgb), 0.95);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wh-dl-close {
  background: none;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--nc-text-muted);
  cursor: pointer;
  font-size: 1rem;
  padding: 0.3rem 0.5rem;
  flex-shrink: 0;
  transition: all 0.15s;
}
.wh-dl-close:hover {
  color: rgba(var(--nc-primary-rgb), 0.9);
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.3);
}

/* ─── Body ─── */
.wh-dl-body { padding: 1rem 1.25rem 0.75rem; }

/* ─── Toolbar ─── */
.wh-dl-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  margin-bottom: 0.85rem;
  padding-bottom: 0.85rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.wh-dl-toolbar-left, .wh-dl-toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.wh-dl-toolbar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  color: rgba(var(--nc-primary-rgb), 0.9);
  font-weight: 600;
  margin-right: 0.25rem;
}
.wh-dl-meta-key {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem;
  letter-spacing: 0.12em;
  color: rgba(var(--nc-primary-rgb), 0.9);
  font-weight: 600;
}
.wh-dl-meta-val {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.85);
}
.wh-dl-meta-val--code {
  display: inline-flex; align-items: center; gap: 0.4rem;
}
.wh-dl-meta-val code {
  background: rgba(var(--nc-primary-rgb), 0.08);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.7rem;
}

/* ─── Chip filter ─── */
.wh-dl-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.06em;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 14px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.65);
  background: rgba(var(--nc-primary-rgb), 0.04);
  cursor: pointer;
  transition: all 0.15s;
}
.wh-dl-chip:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  color: rgba(255, 255, 255, 0.95);
}
.wh-dl-chip--active {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  color: rgba(var(--nc-primary-rgb), 1);
}
.wh-dl-chip-count {
  background: rgba(0, 0, 0, 0.35);
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 0.55rem;
}

/* ─── Buttons ─── */
.wh-dl-btn {
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
.wh-dl-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.wh-dl-btn--ghost {
  background: transparent;
  border-color: rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.wh-dl-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  color: rgba(var(--nc-primary-rgb), 1);
}
.wh-dl-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
}
.wh-dl-btn--primary:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.3);
}

.wh-dl-live-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--nc-text-muted);
  transition: background 0.15s, box-shadow 0.15s;
}
.wh-dl-live-dot--on {
  background: var(--nc-success);
  box-shadow: 0 0 8px rgba(0, 255, 136, 0.6);
  animation: wh-dl-pulse 2s ease-in-out infinite;
}
@keyframes wh-dl-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(0, 255, 136, 0.6); }
  50% { box-shadow: 0 0 14px rgba(0, 255, 136, 0.9); }
}

.wh-dl-spinner-inline {
  width: 10px; height: 10px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: wh-dl-spin 0.8s linear infinite;
}
@keyframes wh-dl-spin { to { transform: rotate(360deg); } }

/* ─── Stats ─── */
.wh-dl-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0.6rem;
  margin-bottom: 0.85rem;
}
.wh-dl-stat-cell {
  background: var(--nc-deep, #0a0d16);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 5px;
  padding: 0.6rem 0.5rem;
  text-align: center;
}
.wh-dl-stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.15;
}
.wh-dl-stat-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted);
  margin-top: 0.18rem;
}

/* ─── Error banner ─── */
.wh-dl-error-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.3);
  color: var(--nc-danger);
  padding: 0.5rem 0.85rem;
  border-radius: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  margin-bottom: 0.75rem;
}
.wh-dl-error-banner span { flex: 1; min-width: 0; }

/* ─── Skeleton ─── */
.wh-dl-skeleton {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.wh-dl-skel-row {
  height: 36px;
  border-radius: 5px;
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb), 0.05) 0%,
    rgba(var(--nc-primary-rgb), 0.12) 50%,
    rgba(var(--nc-primary-rgb), 0.05) 100%);
  background-size: 200% 100%;
  animation: wh-dl-shimmer 1.4s linear infinite;
}
@keyframes wh-dl-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* ─── Empty ─── */
.wh-dl-empty {
  text-align: center;
  padding: 2.4rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.wh-dl-empty-glyph {
  font-size: 1.8rem;
  margin-bottom: 0.5rem;
  opacity: 0.5;
}
.wh-dl-empty-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.25rem;
}
.wh-dl-empty-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: var(--nc-text-muted);
  margin-bottom: 0.85rem;
  max-width: 28rem;
}
.wh-dl-empty-actions { display: flex; gap: 0.5rem; }

/* ─── List ─── */
.wh-dl-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  max-height: 26rem;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--nc-primary-rgb), 0.2) transparent;
  padding-right: 0.25rem;
}
.wh-dl-list::-webkit-scrollbar { width: 5px; }
.wh-dl-list::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb), 0.25); border-radius: 3px; }

.wh-dl-row {
  background: rgba(var(--nc-primary-rgb), 0.03);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-left-width: 3px;
  border-radius: 5px;
  overflow: hidden;
  transition: background 0.15s, border-color 0.15s;
}
.wh-dl-row--ok      { border-left-color: var(--nc-success); }
.wh-dl-row--err     { border-left-color: var(--nc-danger); background: rgba(255, 51, 102, 0.04); }
.wh-dl-row--pending { border-left-color: var(--nc-warning); }
.wh-dl-row--expanded { background: rgba(var(--nc-primary-rgb), 0.08); }

.wh-dl-row-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  color: inherit;
}
.wh-dl-row-head:hover { background: rgba(var(--nc-primary-rgb), 0.05); }
.wh-dl-row-head:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.5); outline-offset: -2px; }

.wh-dl-status-dot {
  width: 7px; height: 7px; border-radius: 50%;
  flex-shrink: 0;
}
.wh-dl-status-dot--ok   { background: var(--nc-success); box-shadow: 0 0 6px rgba(0, 255, 136, 0.5); }
.wh-dl-status-dot--warn { background: var(--nc-warning); }
.wh-dl-status-dot--err  { background: var(--nc-danger);  box-shadow: 0 0 6px rgba(255, 51, 102, 0.5); }
.wh-dl-status-dot--null { background: var(--nc-text-muted); opacity: 0.5; }

.wh-dl-row-event {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}
.wh-dl-row-spacer { flex: 1; }
.wh-dl-row-time {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
}
.wh-dl-row-caret {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(var(--nc-primary-rgb), 0.6);
  margin-left: 0.4rem;
}

/* ─── Pills ─── */
.wh-dl-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
  white-space: nowrap;
}
.wh-dl-pill--ok    { background: rgba(0, 255, 136, 0.1);  color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.wh-dl-pill--err   { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger);  border-color: rgba(255, 51, 102, 0.3); }
.wh-dl-pill--warn  { background: rgba(255, 149, 0, 0.1);  color: var(--nc-warning); border-color: rgba(255, 149, 0, 0.3); }
.wh-dl-pill--muted { background: rgba(var(--nc-primary-rgb), 0.06); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--nc-primary-rgb), 0.18); }
.wh-dl-pill--soft  { background: rgba(var(--nc-primary-rgb), 0.08); color: rgba(var(--nc-primary-rgb), 0.85); border-color: rgba(var(--nc-primary-rgb), 0.22); }

/* ─── Detail panel ─── */
.wh-dl-detail {
  padding: 0.5rem 0.75rem 0.85rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.wh-dl-detail-error {
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.3);
  border-radius: 5px;
  padding: 0.5rem 0.7rem;
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: var(--nc-danger);
}
.wh-dl-detail-error-glyph { font-weight: 700; }

/* §FEPARITY-R4 — redeliver affordance */
.wh-dl-redeliver {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  padding: 0.65rem 0.8rem;
  margin-bottom: 0.75rem;
  border: 1px solid rgba(255, 176, 32, 0.28);
  border-radius: 6px;
  background: rgba(255, 176, 32, 0.06);
}
.wh-dl-redeliver-copy { display: flex; flex-direction: column; gap: 0.15rem; min-width: 12rem; flex: 1; }
.wh-dl-redeliver-copy strong {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  color: var(--nc-text-primary);
}
.wh-dl-redeliver-copy span { font-size: 0.7rem; line-height: 1.45; color: var(--nc-text-muted); }
.wh-dl-redeliver-btn {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.66rem;
  letter-spacing: 0.08em;
  padding: 0.38rem 0.9rem;
  border-radius: 4px;
  border: 1px solid rgba(255, 176, 32, 0.5);
  background: rgba(255, 176, 32, 0.12);
  color: #ffb020;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
  white-space: nowrap;
}
.wh-dl-redeliver-btn:hover:not(:disabled) { background: rgba(255, 176, 32, 0.22); border-color: rgba(255, 176, 32, 0.75); }
.wh-dl-redeliver-btn:disabled { opacity: 0.55; cursor: not-allowed; }

.wh-dl-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.5rem 0.85rem;
}
.wh-dl-meta-pair {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.wh-dl-section { margin-top: 0.25rem; }
.wh-dl-section-muted {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
}

.wh-dl-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--nc-primary-rgb), 0.7);
  font-family: monospace;
  font-size: 0.7rem;
  padding: 0 5px;
  cursor: pointer;
  transition: all 0.12s;
}
.wh-dl-icon-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.1);
  color: rgba(var(--nc-primary-rgb), 1);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
}

/* ─── Footer ─── */
.wh-dl-footer-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
}
.wh-dl-footer-right {
  display: flex;
  gap: 0.5rem;
}

/* ─── Responsive ─── */
@media (max-width: 768px) {
  .wh-dl-stats { grid-template-columns: repeat(3, 1fr); }
  .wh-dl-toolbar-right { width: 100%; justify-content: flex-end; }
  .wh-dl-row-head { flex-wrap: wrap; }
}
</style>
