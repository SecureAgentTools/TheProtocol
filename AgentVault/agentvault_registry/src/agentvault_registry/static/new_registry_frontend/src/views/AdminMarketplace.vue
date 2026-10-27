<!--
  §pass51 P42 — Admin moderation queue for bundle marketplace.
  Gated server-side by admin_enforcement (P21 RBAC matrix).
-->
<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted } from 'vue'
import { apiClient } from '@/services/api/client'
import Icon from '@/components/Icon.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'

const ui = useUIStore()
const { t } = useI18n()

const loading = ref(false)
const summary = ref<{ open: number; resolved: number; total: number } | null>(null)
const reports = ref<any[]>([])
const statusFilter = ref<'open' | 'resolved' | 'all'>('open')
// §FESUITE (2026-10-05): a failed read toasted and drew the shield and "no reports" under it (an all-clear on the
// moderation queue the page never read), with 0 / 0 / 0 above. The rows answer one filter: a switch never shows the old
// filter's rows under the new chip; a failed refresh of the same filter keeps them; a late answer is dropped.
const reportsRead = ref<'loading' | 'ok' | 'failed'>('loading')
let shownFilter: string | null = null
let seq = 0
const hideTarget = ref<{ id: string; name: string; report_id: number } | null>(null)
const hideBusy = ref(false)
const dismissTarget = ref<{ id: number; bundle_name: string } | null>(null)
const dismissBusy = ref(false)

const visibleReports = computed(() => reports.value)

async function load() {
  const want = statusFilter.value
  const my = ++seq
  if (shownFilter !== want) { reports.value = []; reportsRead.value = 'loading' }
  loading.value = true
  try {
    const { data } = await apiClient.get('/admin/bundles/reports', {
      params: { status_filter: want, limit: 50 }
    })
    if (my !== seq) return
    reports.value = data.reports || []
    summary.value = data.summary || { open: 0, resolved: 0, total: 0 }
    shownFilter = want
    reportsRead.value = 'ok'
  } catch (e: any) {
    if (my !== seq) return
    if (shownFilter !== want) reportsRead.value = 'failed'
    ui.showError?.(e?.response?.data?.detail || t('adminMarketplaceView.errors.loadFailed'))
  } finally {
    if (my === seq) loading.value = false
  }
}

onMounted(load)

function openHide(report: any) {
  hideTarget.value = { id: report.bundle_id, name: report.bundle.name, report_id: report.id }
}

async function confirmHide(reason: string) {
  if (!hideTarget.value) return
  if (!reason || reason.trim().length < 3) {
    ui.showError?.(t('adminMarketplaceView.errors.reasonRequired'))
    return
  }
  hideBusy.value = true
  try {
    await apiClient.post(`/admin/bundles/${hideTarget.value.id}/hide`, { reason: reason.trim() })
    ui.showSuccess?.(t('adminMarketplaceView.messages.bundleHidden', { name: hideTarget.value.name }))
    hideTarget.value = null
    await load()
  } catch (e: any) {
    ui.showError?.(e?.response?.data?.detail || t('adminMarketplaceView.errors.hideFailed'))
  } finally {
    hideBusy.value = false
  }
}

function openDismiss(report: any) {
  dismissTarget.value = { id: report.id, bundle_name: report.bundle.name }
}

async function confirmDismiss(resolutionNote: string) {
  if (!dismissTarget.value) return
  dismissBusy.value = true
  try {
    await apiClient.post(`/admin/bundles/reports/${dismissTarget.value.id}/dismiss`, {
      resolution: resolutionNote.trim() || 'no action',
      note: resolutionNote.trim(),
    })
    ui.showSuccess?.(t('adminMarketplaceView.messages.reportDismissed'))
    dismissTarget.value = null
    await load()
  } catch (e: any) {
    ui.showError?.(e?.response?.data?.detail || t('adminMarketplaceView.errors.dismissFailed'))
  } finally {
    dismissBusy.value = false
  }
}

async function unhide(bundleId: string, name: string) {
  try {
    await apiClient.post(`/admin/bundles/${bundleId}/unhide`)
    ui.showSuccess?.(t('adminMarketplaceView.messages.bundleUnhidden', { name }))
    await load()
  } catch (e: any) {
    ui.showError?.(e?.response?.data?.detail || t('adminMarketplaceView.errors.unhideFailed'))
  }
}

const reasonColors: Record<string, string> = {
  spam: 'rgba(245,158,11,0.85)',
  impersonation: 'rgba(248,113,113,0.95)',
  malicious: 'rgba(248,113,113,1)',
  copyright: 'rgba(168,85,247,0.85)',
  offensive: 'rgba(248,113,113,0.85)',
  broken: 'rgba(96,165,250,0.85)',
  other: 'rgba(148,163,184,0.8)',
}
</script>

<template>
  <div class="am-shell">
    <header class="am-head">
      <div>
        <div class="am-eyebrow">{{ t('adminMarketplaceView.eyebrow') }}</div>
        <h1 class="am-title">{{ t('adminMarketplaceView.title') }}</h1>
        <p class="am-sub">{{ t('adminMarketplaceView.subtitle') }}</p>
      </div>
      <div class="am-summary">
        <div class="am-stat"><span class="am-stat-n">{{ summary ? summary.open : '—' }}</span><span class="am-stat-l">{{ t('adminMarketplaceView.stats.open') }}</span></div>
        <div class="am-stat"><span class="am-stat-n">{{ summary ? summary.resolved : '—' }}</span><span class="am-stat-l">{{ t('adminMarketplaceView.stats.resolved') }}</span></div>
        <div class="am-stat"><span class="am-stat-n">{{ summary ? summary.total : '—' }}</span><span class="am-stat-l">{{ t('adminMarketplaceView.stats.total') }}</span></div>
      </div>
    </header>

    <div class="am-toolbar">
      <div class="am-filters">
        <button class="am-chip" :class="{'is-active': statusFilter === 'open'}" @click="statusFilter = 'open'; load()">{{ t('adminMarketplaceView.filters.open') }}</button>
        <button class="am-chip" :class="{'is-active': statusFilter === 'resolved'}" @click="statusFilter = 'resolved'; load()">{{ t('adminMarketplaceView.filters.resolved') }}</button>
        <button class="am-chip" :class="{'is-active': statusFilter === 'all'}" @click="statusFilter = 'all'; load()">{{ t('adminMarketplaceView.filters.all') }}</button>
      </div>
      <button class="am-refresh" @click="load"><Icon name="mdi:refresh" /> {{ t('adminMarketplaceView.refresh') }}</button>
    </div>

    <div v-if="loading && !visibleReports.length" class="am-loading">{{ t('adminMarketplaceView.loading') }}</div>
    <ReadFailedNotice v-else-if="reportsRead === 'failed' && !visibleReports.length" :retry="load" data-testid="am-reports-failed" />
    <div v-else-if="reportsRead === 'ok' && visibleReports.length === 0" class="am-empty">
      <Icon name="mdi:shield-check" class="am-empty-icon" />
      <p>{{ t('adminMarketplaceView.empty', { statusFilter }) }}</p>
    </div>
    <table v-else class="am-table">
      <thead>
        <tr>
          <th>{{ t('adminMarketplaceView.table.when') }}</th>
          <th>{{ t('adminMarketplaceView.table.bundle') }}</th>
          <th>{{ t('adminMarketplaceView.table.reason') }}</th>
          <th>{{ t('adminMarketplaceView.table.reporter') }}</th>
          <th>{{ t('adminMarketplaceView.table.comment') }}</th>
          <th>{{ t('adminMarketplaceView.table.status') }}</th>
          <th>{{ t('adminMarketplaceView.table.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in visibleReports" :key="r.id" :class="{'is-resolved': r.resolved_at}">
          <td class="am-when">{{ new Date(r.created_at).toLocaleString(appLocale()) }}</td>
          <td class="am-bundle">
            <strong>{{ r.bundle.name }}</strong>
            <span v-if="r.bundle.is_official" class="am-pill am-pill--official">{{ t('adminMarketplaceView.pills.official') }}</span>
            <span v-if="r.bundle.is_hidden" class="am-pill am-pill--hidden">{{ t('adminMarketplaceView.pills.hidden') }}</span>
            <span class="am-vis">{{ r.bundle.visibility }}</span>
          </td>
          <td>
            <span class="am-reason" :style="{ background: reasonColors[r.reason_code] + '22', color: reasonColors[r.reason_code] }">{{ r.reason_code }}</span>
          </td>
          <td class="am-reporter">{{ r.reporter_email || `dev #${r.reporter_dev_id}` }}</td>
          <td class="am-comment">{{ r.comment || '—' }}</td>
          <td>
            <span v-if="r.resolved_at" class="am-status am-status--done">✓ {{ r.resolution }}</span>
            <span v-else class="am-status am-status--open">{{ t('adminMarketplaceView.statusBadge.open') }}</span>
          </td>
          <td class="am-actions">
            <template v-if="!r.resolved_at">
              <button v-if="!r.bundle.is_hidden" class="am-btn am-btn--danger" @click="openHide(r)">
                <Icon name="mdi:eye-off" /> {{ t('adminMarketplaceView.actions.hide') }}
              </button>
              <button v-else class="am-btn am-btn--ghost" @click="unhide(r.bundle_id, r.bundle.name)">
                <Icon name="mdi:eye-outline" /> {{ t('adminMarketplaceView.actions.unhide') }}
              </button>
              <button class="am-btn am-btn--ghost" @click="openDismiss(r)">
                {{ t('adminMarketplaceView.actions.dismiss') }}
              </button>
            </template>
            <span v-else class="am-actions-empty">—</span>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Hide confirm -->
    <ConfirmActionModal
      :show="!!hideTarget"
      tone="danger"
      :title="t('adminMarketplaceView.hideModal.title')"
      :message="t('adminMarketplaceView.hideModal.message', { name: hideTarget?.name || '' })"
      :confirm-text="t('adminMarketplaceView.hideModal.confirmText')"
      :cancel-text="t('adminMarketplaceView.hideModal.cancelText')"
      :busy-text="t('adminMarketplaceView.hideModal.busyText')"
      :busy="hideBusy"
      reason-required
      :reason-min-length="3"
      :reason-placeholder="t('adminMarketplaceView.hideModal.reasonPlaceholder')"
      @close="hideTarget = null"
      @confirm="confirmHide"
    />

    <!-- Dismiss confirm -->
    <ConfirmActionModal
      :show="!!dismissTarget"
      tone="primary"
      :title="t('adminMarketplaceView.dismissModal.title')"
      :message="t('adminMarketplaceView.dismissModal.message', { name: dismissTarget?.bundle_name || '' })"
      :confirm-text="t('adminMarketplaceView.dismissModal.confirmText')"
      :cancel-text="t('adminMarketplaceView.dismissModal.cancelText')"
      :busy-text="t('adminMarketplaceView.dismissModal.busyText')"
      :busy="dismissBusy"
      reason-optional
      :reason-placeholder="t('adminMarketplaceView.dismissModal.reasonPlaceholder')"
      @close="dismissTarget = null"
      @confirm="confirmDismiss"
    />
  </div>
</template>

<style scoped>
.am-shell { min-height: 100%; position: relative; z-index: 1; padding: 1.4rem 1.6rem 2rem; color: #e8eaed; font-family: 'IBM Plex Mono', monospace; }
.am-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1.5rem; padding-bottom: 1rem; margin-bottom: 1rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12); }
.am-eyebrow { font-size: 0.62rem; letter-spacing: 0.24em; color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 700; margin-bottom: 0.5rem; }
.am-title { font-size: 1.7rem; font-weight: 700; margin: 0; color: #fff; letter-spacing: -0.005em; }
.am-sub { font-size: 0.82rem; color: #99a5b3; margin: 0.5rem 0 0; line-height: 1.5; max-width: 700px; }
.am-summary { display: flex; gap: 1.2rem; flex-shrink: 0; }
.am-stat { text-align: right; }
.am-stat-n { display: block; font-size: 1.4rem; font-weight: 700; color: #fff; }
.am-stat-l { display: block; font-size: 0.65rem; letter-spacing: 0.18em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.65); }

.am-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 0.6rem; padding: 0.4rem 0 1rem; }
.am-filters { display: flex; gap: 0.4rem; }
.am-chip { background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.22); color: rgba(var(--nc-primary-rgb), 0.75); font-family: inherit; font-size: 0.72rem; font-weight: 600; padding: 6px 12px; border-radius: 4px; cursor: pointer; transition: background 0.15s, border-color 0.15s; }
.am-chip:hover { background: rgba(var(--nc-primary-rgb), 0.06); }
.am-chip.is-active { background: rgba(var(--nc-primary-rgb), 0.18); border-color: rgba(var(--nc-primary-rgb), 0.55); color: var(--nc-primary); }
.am-refresh { background: rgba(var(--nc-primary-rgb), 0.05); border: 1px solid rgba(var(--nc-primary-rgb), 0.25); color: rgba(var(--nc-primary-rgb), 0.85); font-family: inherit; font-size: 0.72rem; padding: 6px 12px; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem; }
.am-refresh svg { width: 12px; height: 12px; }
.am-refresh:hover { background: rgba(var(--nc-primary-rgb), 0.12); color: var(--nc-primary); }

.am-loading { padding: 3rem; text-align: center; color: #99a5b3; font-style: italic; }
.am-empty { padding: 3rem; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 0.6rem; color: #99a5b3; }
.am-empty-icon { width: 48px; height: 48px; color: rgba(0, 255, 136, 0.6); }

.am-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; background: rgba(13, 22, 38, 0.45); border: 1px solid rgba(var(--nc-primary-rgb), 0.12); border-radius: 8px; overflow: hidden; }
.am-table th { text-align: left; padding: 10px 12px; background: rgba(var(--nc-primary-rgb), 0.08); border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.16); font-size: 0.64rem; letter-spacing: 0.14em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.85); font-weight: 700; }
.am-table td { padding: 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.03); vertical-align: top; }
.am-table tr:last-child td { border-bottom: none; }
.am-table tr.is-resolved { opacity: 0.55; }
.am-table tr:hover { background: rgba(var(--nc-primary-rgb), 0.03); }

.am-when { color: #99a5b3; font-size: 0.7rem; white-space: nowrap; }
.am-bundle { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
.am-bundle strong { color: #e8eaed; font-weight: 600; }
.am-pill { font-size: 0.55rem; letter-spacing: 0.16em; font-weight: 700; padding: 1px 6px; border-radius: 3px; }
.am-pill--official { background: rgba(255, 215, 0, 0.22); color: rgba(255, 215, 0, 0.95); }
.am-pill--hidden { background: rgba(248, 113, 113, 0.25); color: rgba(248, 113, 113, 0.95); }
.am-vis { font-size: 0.65rem; color: rgba(148, 163, 184, 0.7); letter-spacing: 0.08em; }
.am-reason { font-size: 0.7rem; padding: 3px 9px; border-radius: 999px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; }
.am-reporter { color: #99a5b3; font-size: 0.7rem; word-break: break-all; max-width: 180px; }
.am-comment { color: #d0d8e0; max-width: 280px; word-break: break-word; font-size: 0.72rem; }
.am-status { font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; }
.am-status--open { color: rgba(245, 158, 11, 0.9); }
.am-status--done { color: rgba(0, 255, 136, 0.85); }
.am-actions { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.am-actions-empty { color: rgba(148, 163, 184, 0.4); }
.am-btn { display: inline-flex; align-items: center; gap: 0.3rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; padding: 5px 9px; border-radius: 4px; cursor: pointer; }
.am-btn--ghost { background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); color: rgba(var(--nc-primary-rgb), 0.8); }
.am-btn--ghost:hover { background: rgba(var(--nc-primary-rgb), 0.06); color: var(--nc-primary); }
.am-btn--danger { background: rgba(248, 113, 113, 0.12); border: 1px solid rgba(248, 113, 113, 0.4); color: rgba(248, 113, 113, 0.95); }
.am-btn--danger:hover { background: rgba(248, 113, 113, 0.22); border-color: rgba(248, 113, 113, 0.7); }
.am-btn svg { width: 11px; height: 11px; }
</style>
