<template>
  <!-- §COCKPITDESK (2026-10-15) — HIS WORD: "webhooks needs design refresh it uses wrong design elements boxes etc are
       wrong. needs redo and polish". Rebuilt in the house language (Design_Language.md: the subtle card, stat tiles,
       eyebrow, hairline rows): one card holds the endpoints as rows, never a grey box per endpoint. The old class
       names stay on the rows and buttons as hooks only (lifecycle 04 and the tours address them). -->
  <div class="whm" data-testid="whm-root">
    <header class="whm-hero" data-tour="wh-hero">
      <span class="whm-eyebrow"><span class="whm-eyebrow-dot" aria-hidden="true" />{{ t('webhookManagerView.hero.eyebrow', 'Developer · Callbacks') }}</span>
      <h1 class="whm-h1">{{ t('webhookManagerView.hero.h1', 'Webhooks') }}</h1>
      <p class="whm-lead">{{ t('webhookManagerView.hero.subtitle', 'This registry calls your endpoints when something you subscribed to happens.') }}</p>
    </header>

    <section class="whm-stats" data-tour="wh-stats" data-testid="whm-stats">
      <div class="whm-stat">
        <span class="whm-stat-label">{{ t('webhookManagerView.stats.total', 'Endpoints') }}</span>
        <span class="whm-stat-value" data-testid="whm-stat-total">{{ webhookStore.webhookStats.total }}</span>
      </div>
      <div class="whm-stat">
        <span class="whm-stat-label">{{ t('webhookManagerView.stats.active', 'Active') }}</span>
        <span class="whm-stat-value" :class="{ 'is-ok': webhookStore.webhookStats.active > 0 }">{{ webhookStore.webhookStats.active }}</span>
      </div>
      <div class="whm-stat">
        <span class="whm-stat-label">{{ t('webhookManagerView.stats.inactive', 'Paused') }}</span>
        <span class="whm-stat-value">{{ webhookStore.webhookStats.inactive }}</span>
      </div>
      <div class="whm-stat" :class="{ 'whm-stat--warn': webhookStore.webhookStats.failedWebhooks > 0 }">
        <span class="whm-stat-label">{{ t('webhookManagerView.stats.withFailures', 'Failing') }}</span>
        <span class="whm-stat-value" :class="{ 'is-warn': webhookStore.webhookStats.failedWebhooks > 0 }">{{ webhookStore.webhookStats.failedWebhooks }}</span>
        <span class="whm-stat-sub">{{ t('webhookManagerView.stats.failuresSub', 'failures in a row; the next success resets them') }}</span>
      </div>
    </section>

    <div class="whm-toolbar">
      <button class="whm-btn whm-btn--primary" data-tour="wh-add" data-testid="whm-add" @click="showCreateModal = true">
        <Icon name="mdi:plus" class="whm-btn-icon" />{{ t('webhookManagerView.toolbar.addWebhook', 'Add endpoint') }}
      </button>
      <label class="whm-search">
        <Icon name="mdi:magnify" class="whm-search-icon" />
        <input v-model="webhookStore.filters.search" type="search" class="whm-input" data-testid="whm-search"
               :aria-label="t('webhookManagerView.toolbar.searchPlaceholder', 'Search URL or event type')"
               :placeholder="t('webhookManagerView.toolbar.searchPlaceholder', 'Search URL or event type')" />
      </label>
      <button v-if="webhookStore.filters.search" class="whm-btn whm-btn--ghost" @click="webhookStore.clearFilters()">
        {{ t('webhookManagerView.toolbar.clear', 'Clear') }}
      </button>
      <button class="whm-btn whm-btn--ghost" data-testid="whm-refresh" :disabled="webhookStore.isLoading" @click="refreshWebhooks">
        <Icon name="mdi:refresh" class="whm-btn-icon" :class="{ 'whm-spin': webhookStore.isLoading }" />{{ t('webhookManagerView.toolbar.refresh', 'Refresh') }}
      </button>
    </div>

    <!-- A FAILED READ (§FESUITE: it said "NO WEBHOOKS FOUND") -->
    <ReadFailedNotice v-if="webhookStore.listFailed && webhookStore.webhooks.length === 0 && !webhookStore.isLoading" :retry="refreshWebhooks" />

    <section v-else class="whm-card" data-tour="wh-list" data-testid="whm-card">
      <header class="whm-card-head">
        <span class="whm-card-title">{{ t('webhookManagerView.list.title', 'Endpoints') }}</span>
        <span class="whm-card-count">
          {{ webhookStore.filters.search
              ? tp('webhookManagerView.list.countOf', '{n} of {total}', { n: webhookStore.filteredWebhooks.length, total: webhookStore.webhooks.length })
              : webhookStore.webhooks.length === 1 ? t('webhookManagerView.list.countOne', '1 endpoint')
              : tp('webhookManagerView.list.count', '{n} endpoints', { n: webhookStore.webhooks.length }) }}
        </span>
      </header>

      <p v-if="webhookStore.isLoading && webhookStore.webhooks.length === 0" class="whm-quiet" data-testid="whm-loading">
        <Icon name="mdi:refresh" class="whm-btn-icon whm-spin" />{{ t('webhookManagerView.loading', 'Reading your endpoints…') }}
      </p>

      <div v-else-if="webhookStore.filteredWebhooks.length === 0" class="whm-empty" data-tour="wh-empty" data-testid="whm-empty">
        <svg class="whm-empty-glyph" viewBox="0 0 48 48" aria-hidden="true">
          <circle cx="12" cy="34" r="5" /><circle cx="36" cy="34" r="5" /><circle cx="24" cy="12" r="5" />
          <path d="M24 17 L15 30 M17 34 H31 M33 30 L26 17" />
        </svg>
        <p class="whm-empty-title">
          {{ webhookStore.filters.search ? t('webhookManagerView.empty.noMatchTitle', 'Nothing matches') : t('webhookManagerView.empty.title', 'No endpoints yet') }}
        </p>
        <p class="whm-empty-text">
          {{ webhookStore.filters.search
              ? t('webhookManagerView.empty.noMatchDesc', 'No endpoint matches your search.')
              : t('webhookManagerView.empty.noWebhooksDesc', 'Add an endpoint, choose the events it should hear, and this registry calls it each time one happens.') }}
        </p>
        <button v-if="!webhookStore.filters.search" class="whm-btn whm-btn--primary" data-testid="whm-add-first" @click="showCreateModal = true">
          <Icon name="mdi:plus" class="whm-btn-icon" />{{ t('webhookManagerView.empty.createBtn', 'Add your first endpoint') }}
        </button>
      </div>

      <template v-else>
        <div class="whm-bulk" :class="{ 'whm-bulk--active': selectedIds.size > 0 }" data-testid="whm-bulk">
          <label class="whm-check-all">
            <input type="checkbox" class="whm-check" :checked="allFilteredSelected"
                   :indeterminate.prop="someFilteredSelected && !allFilteredSelected" @change="toggleSelectAll" />
            <span>
              <template v-if="selectedIds.size > 0">{{ t('webhookManagerView.bulk.selected', { count: selectedIds.size }) }}</template>
              <template v-else>{{ t('webhookManagerView.bulk.selectAll', 'Select all') }}</template>
            </span>
          </label>
          <template v-if="selectedIds.size > 0">
            <button class="whm-act" :disabled="bulkBusy" @click="openBulkAction('test')">{{ t('webhookManagerView.bulk.testSelected', 'Test') }}</button>
            <button class="whm-act" :disabled="bulkBusy" @click="openBulkAction('enable')">{{ t('webhookManagerView.bulk.reEnable', 'Resume') }}</button>
            <button class="whm-act" :disabled="bulkBusy" @click="openBulkAction('disable')">{{ t('webhookManagerView.bulk.disable', 'Pause') }}</button>
            <span class="whm-spacer" />
            <button class="whm-act whm-act--quiet" @click="clearSelection">{{ t('webhookManagerView.bulk.clear', 'Clear') }}</button>
          </template>
        </div>

        <ul class="whm-rows">
          <li v-for="webhook in webhookStore.filteredWebhooks" :key="webhook.id"
              class="whm-row webhook-card" data-testid="whm-row" :data-state="rowState(webhook)"
              :class="{ 'is-selected': selectedIds.has(webhook.id), 'is-deleting': deletingId === webhook.id }">
            <div class="whm-row-main">
              <input type="checkbox" class="whm-check" :checked="selectedIds.has(webhook.id)"
                     :aria-label="tp('webhookManagerView.list.selectOne', 'Select {url}', { url: webhook.url })"
                     @click.stop="toggleSelected(webhook.id)" />
              <span class="whm-state" :class="`is-${rowState(webhook)}`" aria-hidden="true" />
              <div class="whm-row-text">
                <span class="whm-url" :title="webhook.url">{{ webhook.url }}</span>
                <span class="whm-meta">
                  <span class="whm-state-text" :class="`is-${rowState(webhook)}`" data-testid="whm-state">{{ stateText(webhook) }}</span>
                  <span class="whm-sep">·</span>
                  <span>{{ t('webhookManagerView.list.created', 'Created') }} {{ timeAgo(webhook.created_at) }}</span>
                  <span class="whm-sep">·</span>
                  <span v-if="webhook.last_triggered_at">{{ t('webhookManagerView.list.lastTriggered', 'Last called') }} {{ timeAgo(webhook.last_triggered_at) }}</span>
                  <span v-else>{{ t('webhookManagerView.list.neverTriggered', 'Never called') }}</span>
                </span>
                <span class="whm-events">
                  <span v-for="event in webhook.events.slice(0, 4)" :key="event" class="whm-pill" :title="event">{{ formatEventName(event) }}</span>
                  <span v-if="webhook.events.length > 4" class="whm-pill whm-pill--more">+{{ webhook.events.length - 4 }}</span>
                </span>
              </div>
              <div class="whm-actions">
                <button class="whm-act webhook-btn--test" :disabled="!webhook.is_active || testingId === webhook.id"
                        :title="webhook.is_active ? '' : t('webhookManagerView.list.testPaused', 'A paused endpoint is not called; resume it to test')"
                        @click="testWebhook(webhook)">
                  {{ testingId === webhook.id ? t('webhookManagerView.list.testing', 'Testing…') : t('webhookManagerView.list.test', 'Test') }}
                </button>
                <button class="whm-act webhook-btn--history" @click="viewDeliveries(webhook)">{{ t('webhookManagerView.list.history', 'Deliveries') }}</button>
                <button class="whm-act webhook-btn--edit" @click="editWebhook(webhook)">{{ t('webhookManagerView.list.edit', 'Edit') }}</button>
                <button class="whm-act" :class="webhook.is_active ? 'webhook-btn--disable' : 'webhook-btn--enable'" @click="toggleStatus(webhook)">
                  {{ webhook.is_active ? t('webhookManagerView.list.disable', 'Pause') : t('webhookManagerView.list.enable', 'Resume') }}
                </button>
                <button class="whm-act whm-act--danger webhook-btn--delete" @click="initiateDelete(webhook)">{{ t('webhookManagerView.list.delete', 'Delete') }}</button>
              </div>
            </div>

            <p v-if="testResults[webhook.id]" class="whm-result" data-testid="whm-test-result"
               :class="testResults[webhook.id].success ? 'is-ok' : 'is-fail'">
              {{ testResults[webhook.id].success
                  ? t('webhookManagerView.list.testOk', 'Test delivery sent: the endpoint answered 2xx.')
                  : tp('webhookManagerView.list.testFailWhy', 'The test delivery failed: {why}', { why: testResults[webhook.id].error || t('webhookManagerView.list.testFail', 'endpoint unreachable') }) }}
            </p>

            <div v-if="deletingId === webhook.id" class="whm-confirm" data-testid="whm-delete-confirm">
              <span class="whm-confirm-text">{{ t('webhookManagerView.list.deletePrompt', { url: webhook.url }) }}</span>
              <button class="whm-act whm-act--danger-solid webhook-btn--confirm-delete" :disabled="deleteBusy" @click="confirmDelete(webhook)">{{ t('webhookManagerView.list.confirm', 'Delete') }}</button>
              <button class="whm-act" @click="deletingId = null">{{ t('webhookManagerView.list.cancel', 'Cancel') }}</button>
            </div>
          </li>
        </ul>
      </template>
    </section>

    <WebhookModal v-if="showCreateModal || editingWebhook" :webhook="editingWebhook" @close="closeModal" />
    <WebhookDeliveriesModal v-if="viewingWebhook" :webhook="viewingWebhook" @close="viewingWebhook = null" />
    <ConfirmActionModal
      :show="!!bulkAction"
      :title="bulkAction === 'test' ? t('webhookManagerView.bulk.testTitle', { count: selectedIds.size })
              : bulkAction === 'enable' ? t('webhookManagerView.bulk.enableTitle', { count: selectedIds.size })
              : t('webhookManagerView.bulk.disableTitle', { count: selectedIds.size })"
      :message="bulkAction === 'test' ? t('webhookManagerView.bulk.testMessage')
        : bulkAction === 'enable' ? t('webhookManagerView.bulk.enableMessage')
        : t('webhookManagerView.bulk.disableMessage')"
      :tone="bulkAction === 'disable' ? 'warn' : 'primary'"
      :confirm-text="bulkAction === 'test' ? t('webhookManagerView.bulk.testConfirm')
                    : bulkAction === 'enable' ? t('webhookManagerView.bulk.enableConfirm')
                    : t('webhookManagerView.bulk.disableConfirm')"
      :busy-text="t('webhookManagerView.bulk.working')"
      :busy="bulkBusy"
      @close="closeBulkAction"
      @confirm="executeBulk"
    />
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import { useWebhookStore } from '@/stores/webhooks'
import { useUIStore } from '@/stores/ui'
import type { Webhook } from '@/services/api/webhookService'
import WebhookModal from '@/components/webhooks/WebhookModal.vue'
import WebhookDeliveriesModal from '@/components/webhooks/WebhookDeliveriesModal.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()
const webhookStore = useWebhookStore()
const uiStore = useUIStore()

const showCreateModal = ref(false)
const editingWebhook  = ref<Webhook | null>(null)
const viewingWebhook  = ref<Webhook | null>(null)
const deletingId      = ref<string | null>(null)
const testingId       = ref<string | null>(null)
const testResults     = ref<Record<string, { success: boolean; error?: string | null }>>({})

// Build #17 (2026-05-08): bulk multi-select state.
const selectedIds = ref<Set<string>>(new Set())
const bulkAction = ref<'test' | 'enable' | 'disable' | null>(null)
const bulkBusy = ref(false)

const allFilteredSelected = computed(() => {
  const filtered = webhookStore.filteredWebhooks
  return filtered.length > 0 && filtered.every(w => selectedIds.value.has(w.id))
})
const someFilteredSelected = computed(() => {
  const filtered = webhookStore.filteredWebhooks
  return filtered.some(w => selectedIds.value.has(w.id))
})

// §COCKPITDESK (2026-10-15): the selection holds only endpoints that exist. A deleted one stayed selected (unseen): the
// bar counted it and a bulk pause reported it among the endpoints that succeeded, a step that did nothing.
watch(() => webhookStore.webhooks.map(w => w.id).join(','), () => {
  const live = new Set(webhookStore.webhooks.map(w => w.id))
  const kept = [...selectedIds.value].filter(id => live.has(id))
  if (kept.length !== selectedIds.value.size) selectedIds.value = new Set(kept)
})

function toggleSelected(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}
function toggleSelectAll() {
  if (allFilteredSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(webhookStore.filteredWebhooks.map(w => w.id))
  }
}
function clearSelection() {
  selectedIds.value = new Set()
}
function openBulkAction(action: 'test' | 'enable' | 'disable') {
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

  // Parallel for test (each is independent network call); sequential not
  // necessary because the backend doesn't serialize webhook test fires.
  // Cap concurrency at 5 so we don't spam the test endpoint.
  const CONCURRENCY = 5
  for (let i = 0; i < ids.length; i += CONCURRENCY) {
    const batch = ids.slice(i, i + CONCURRENCY)
    const results = await Promise.all(batch.map(async (id) => {
      try {
        if (action === 'test') {
          const r = await webhookStore.testWebhook(id)
          // Surface the result in the per-row test banner so user sees it
          testResults.value[id] = { success: r.success, error: r.error }
          setTimeout(() => { delete testResults.value[id] }, 8000)
          return r.success
        } else if (action === 'enable') {
          const w = webhookStore.webhooks.find(x => x.id === id)
          if (w && !w.is_active) await webhookStore.toggleWebhookStatus(id)
          return true
        } else { // disable
          const w = webhookStore.webhooks.find(x => x.id === id)
          if (w && w.is_active) await webhookStore.toggleWebhookStatus(id)
          return true
        }
      } catch {
        return false
      }
    }))
    for (const ok of results) {
      if (ok) okCount++
      else failCount++
    }
  }

  bulkBusy.value = false
  bulkAction.value = null
  selectedIds.value = new Set()

  const done = action === 'test' ? t('webhookManagerView.bulk.doneTest', 'Tested')
    : action === 'enable' ? t('webhookManagerView.bulk.doneEnable', 'Resumed') : t('webhookManagerView.bulk.doneDisable', 'Paused')
  if (failCount > 0) {
    uiStore.showWarning?.(tp('webhookManagerView.bulk.doneWithErrors', '{done}, with errors', { done }),
      tp('webhookManagerView.bulk.okFail', '{ok} succeeded · {fail} failed', { ok: okCount, fail: failCount }))
  } else {
    uiStore.showSuccess?.(done, tp('webhookManagerView.bulk.okN', '{n} endpoints.', { n: okCount }))
  }
  await webhookStore.fetchWebhooks()
}

onMounted(() => webhookStore.fetchWebhooks())

function refreshWebhooks() { webhookStore.fetchWebhooks() }

/** "agent.created" reads "Agent created": the subject stays (the last part alone made agent.created and
 *  contract.created both "Created"); the raw name is the pill's title. */
function formatEventName(event: string): string {
  const words = event.split('.').join(' ').replace(/_/g, ' ').replace(/\s+/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : event
}

/** active, failing (active with failures in a row) or paused: said in words AND by the mark's shape, never by colour alone. */
function rowState(w: Webhook): 'ok' | 'failing' | 'paused' {
  if (!w.is_active) return 'paused'
  return (w.failure_count || 0) > 0 ? 'failing' : 'ok'
}
function stateText(w: Webhook): string {
  const n = w.failure_count || 0
  if (!w.is_active) {
    return n > 0 ? tp('webhookManagerView.list.pausedAfter', 'Paused after {n} failures', { n })
                 : t('webhookManagerView.list.disabled', 'Paused')
  }
  return n > 0 ? tp('webhookManagerView.list.failingN', '{n} failed in a row', { n })
               : t('webhookManagerView.list.active', 'Active')
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  return dayjs(dateStr).fromNow()
}

async function toggleStatus(webhook: Webhook) {
  await webhookStore.toggleWebhookStatus(webhook.id)
}

async function testWebhook(webhook: Webhook) {
  if (testingId.value) return
  testingId.value = webhook.id
  // Clear previous result
  delete testResults.value[webhook.id]
  try {
    const result = await webhookStore.testWebhook(webhook.id)
    testResults.value[webhook.id] = { success: result.success, error: result.error }
    // Auto-clear after 6s
    setTimeout(() => { delete testResults.value[webhook.id] }, 6000)
  } catch {
    testResults.value[webhook.id] = { success: false, error: 'Request failed' }
    setTimeout(() => { delete testResults.value[webhook.id] }, 6000)
  } finally {
    testingId.value = null
  }
}

function viewDeliveries(webhook: Webhook) {
  viewingWebhook.value = webhook
  webhookStore.fetchDeliveries(webhook.id)
}

function editWebhook(webhook: Webhook) {
  editingWebhook.value = webhook
}

function initiateDelete(webhook: Webhook) {
  deletingId.value = webhook.id
}

// One delete at a time; a refused delete keeps its confirmation (the store says why) instead of throwing out of the click.
// A second press sent a second DELETE, whose 404 said "Failed to delete webhook" beside the success.
const deleteBusy = ref(false)
async function confirmDelete(webhook: Webhook) {
  if (deleteBusy.value) return
  deleteBusy.value = true
  try {
    await webhookStore.deleteWebhook(webhook.id)
    deletingId.value = null
  } catch { /* the store showed the refusal; the confirmation stays to retry or cancel */ }
  finally { deleteBusy.value = false }
}

function closeModal() {
  showCreateModal.value = false
  editingWebhook.value  = null
}
</script>

<style scoped>
/* §COCKPITDESK (2026-10-15) — the house language (PRODUCTION_DOCS/03_SERVICES/Frontend/Design_Language.md), theme-reactive. */
.whm {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --muted: var(--nc-text-muted, #8f9399);
  --text-bright: #e8eaed;
  --border: rgba(var(--cyan-rgb), 0.18);
  --hair: rgba(var(--cyan-rgb), 0.10);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --ok: #10b981; --warn: #f59e0b; --danger: #ef4444;
  min-height: 100vh; padding: 24px; max-width: 1440px; margin: 0 auto; position: relative; z-index: 1;
  display: flex; flex-direction: column; gap: 18px;
}

/* hero */
.whm-hero { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.whm-eyebrow { display: inline-flex; align-items: center; gap: 7px; font: 700 10px/1 var(--mono); letter-spacing: .12em; text-transform: uppercase;
  color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 5px 10px; }
.whm-eyebrow-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 8px rgba(var(--cyan-rgb), .7); }
.whm-h1 { margin: 0; font-size: 28px; font-weight: 800; line-height: 1.15; color: var(--text-bright); letter-spacing: -.01em; }
.whm-lead { margin: 0; font-size: 13px; line-height: 1.5; color: var(--muted); max-width: 70ch; }

/* stat tiles: one even row */
.whm-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.whm-stat { display: flex; flex-direction: column; gap: 6px; background: rgba(var(--cyan-rgb), .03); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px; min-width: 0; }
.whm-stat-label { font: 700 10px/1 var(--mono); text-transform: uppercase; letter-spacing: .1em; color: var(--muted); }
.whm-stat-value { font-size: 26px; font-weight: 800; color: var(--text-bright); font-variant-numeric: tabular-nums; line-height: 1.1; }
.whm-stat-value.is-ok { color: var(--ok); }
.whm-stat-value.is-warn { color: var(--warn); }
.whm-stat-sub { font-size: 11px; color: var(--muted); }
.whm-stat--warn { border-color: rgba(245, 158, 11, .45); background: rgba(245, 158, 11, .04); }

/* toolbar: one height for every control */
.whm-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.whm-btn { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 14px; border-radius: 7px; cursor: pointer;
  font: 600 12px/1 var(--mono); letter-spacing: .04em; white-space: nowrap; transition: border-color .15s, background .15s, color .15s; }
.whm-btn:active { transform: translateY(1px); }
.whm-btn:disabled { opacity: .5; cursor: not-allowed; }
.whm-btn--primary { background: var(--cyan); color: #04121a; border: 1px solid var(--cyan); }
.whm-btn--primary:hover { filter: brightness(1.08); }
.whm-btn--ghost { background: transparent; color: var(--muted); border: 1px solid var(--border); }
.whm-btn--ghost:hover:not(:disabled) { color: var(--cyan); border-color: rgba(var(--cyan-rgb), .45); }
.whm-btn-icon { width: 14px; height: 14px; flex: 0 0 auto; }
.whm-search { position: relative; flex: 1 1 260px; display: flex; align-items: center; min-width: 0; }
.whm-search-icon { position: absolute; left: 11px; width: 15px; height: 15px; color: var(--muted); pointer-events: none; }
.whm-input { width: 100%; height: 34px; padding: 0 12px 0 34px; border-radius: 7px; background: rgba(0, 0, 0, .35); border: 1px solid var(--border);
  color: var(--text-bright); font: 13px var(--mono); outline: none; }
.whm-input::placeholder { color: var(--muted); }
.whm-input:focus { border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }

/* the one card */
.whm-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035);
  border: 1px solid var(--border); border-radius: 12px; backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.03), 0 12px 32px -22px rgba(0,0,0,.8); overflow: hidden; }
.whm-card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 18px; border-bottom: 1px solid var(--border); }
.whm-card-title { font: 700 11px/1 var(--mono); letter-spacing: .12em; text-transform: uppercase; color: var(--cyan); }
.whm-card-count { font: 10px/1 var(--mono); color: var(--muted); }
.whm-quiet { display: flex; align-items: center; gap: 8px; margin: 0; padding: 28px 18px; font: 12px var(--mono); color: var(--muted); }

.whm-empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 8px; padding: 44px 24px 40px; }
.whm-empty-glyph { width: 44px; height: 44px; fill: none; stroke: rgba(var(--cyan-rgb), .7); stroke-width: 1.4; stroke-linecap: round; margin-bottom: 4px; }
.whm-empty-title { margin: 0; font-size: 15px; font-weight: 700; color: var(--text-bright); }
.whm-empty-text { margin: 0 0 8px; font-size: 13px; color: var(--muted); max-width: 52ch; line-height: 1.5; }

.whm-bulk { display: flex; align-items: center; gap: 8px; padding: 9px 18px; border-bottom: 1px solid var(--hair); min-height: 42px; flex-wrap: wrap; }
.whm-bulk--active { background: rgba(var(--cyan-rgb), .06); }
.whm-check-all { display: inline-flex; align-items: center; gap: 9px; cursor: pointer; user-select: none;
  font: 600 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.whm-check { width: 14px; height: 14px; accent-color: var(--cyan); cursor: pointer; flex: 0 0 auto; margin: 0; }
.whm-spacer { flex: 1; }

.whm-rows { list-style: none; margin: 0; padding: 0; }
.whm-row { padding: 13px 18px; border-bottom: 1px solid var(--hair); transition: background .15s; }
.whm-row:last-child { border-bottom: 0; }
.whm-row:hover { background: rgba(var(--cyan-rgb), .03); }
.whm-row.is-selected { background: rgba(var(--cyan-rgb), .06); }
.whm-row-main { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.whm-row-main > .whm-check { margin-top: 3px; }
.whm-state { flex: 0 0 auto; width: 9px; height: 9px; margin-top: 5px; border-radius: 50%; }
.whm-state.is-ok { background: var(--ok); }
.whm-state.is-failing { background: var(--danger); box-shadow: 0 0 0 3px rgba(239, 68, 68, .2); }
.whm-state.is-paused { background: transparent; border: 1.5px solid var(--muted); }
.whm-row-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.whm-url { font: 13px var(--mono); color: var(--text-bright); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.whm-meta { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; font: 11px var(--mono); color: var(--muted); }
.whm-state-text.is-ok { color: var(--ok); }
.whm-state-text.is-failing { color: var(--danger); }
.whm-state-text.is-paused { color: var(--warn); }
.whm-sep { opacity: .5; }
.whm-events { display: flex; flex-wrap: wrap; gap: 5px; }
/* the row whose delete waits for its confirm (the confirm line is under it) */
.whm-row.is-deleting { border-color: rgba(var(--nc-error-rgb, 248, 81, 73), .45); }
.whm-pill { font: 10px/1 var(--mono); letter-spacing: .03em; color: rgba(var(--cyan-rgb), .9); border: 1px solid rgba(var(--cyan-rgb), .22);
  border-radius: 999px; padding: 4px 8px; background: rgba(var(--cyan-rgb), .04); }
.whm-pill--more { color: var(--muted); border-color: var(--hair); }

.whm-actions { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; flex-wrap: wrap; justify-content: flex-end; }
.whm-act { height: 28px; padding: 0 10px; border-radius: 6px; cursor: pointer; font: 600 11px/1 var(--mono); letter-spacing: .03em;
  color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .28); white-space: nowrap; }
.whm-act:hover:not(:disabled) { background: rgba(var(--cyan-rgb), .14); border-color: rgba(var(--cyan-rgb), .45); }
.whm-act:disabled { opacity: .45; cursor: not-allowed; }
.whm-act--quiet { color: var(--muted); background: transparent; border-color: var(--hair); }
.whm-act--danger { color: #f87171; background: transparent; border-color: rgba(239, 68, 68, .35); }
.whm-act--danger:hover:not(:disabled) { background: rgba(239, 68, 68, .1); border-color: rgba(239, 68, 68, .55); }
.whm-act--danger-solid { color: #fff; background: rgba(239, 68, 68, .85); border-color: rgba(239, 68, 68, .9); }

.whm-result { margin: 10px 0 0 35px; font: 11px var(--mono); padding: 7px 10px; border-radius: 6px; }
.whm-result.is-ok { color: var(--ok); background: rgba(16, 185, 129, .06); border: 1px solid rgba(16, 185, 129, .25); }
.whm-result.is-fail { color: #f87171; background: rgba(239, 68, 68, .06); border: 1px solid rgba(239, 68, 68, .25); }
.whm-confirm { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 10px 0 0 35px; padding: 8px 10px; border-radius: 6px;
  background: rgba(239, 68, 68, .06); border: 1px solid rgba(239, 68, 68, .3); }
.whm-confirm-text { flex: 1; min-width: 0; font: 12px var(--mono); color: var(--text-bright); overflow-wrap: anywhere; }

.whm-spin { animation: whm-spin 1s linear infinite; }
@keyframes whm-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .whm-spin { animation: none; } }

@media (max-width: 900px) {
  .whm-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .whm { padding: 16px 12px; gap: 14px; }
  .whm-h1 { font-size: 22px; }
  .whm-row-main { flex-wrap: wrap; }
  .whm-actions { width: 100%; justify-content: flex-start; padding-left: 35px; }
  .whm-result, .whm-confirm { margin-left: 0; }
}
</style>
