<!--
  AdminBroadcasts.vue — §pass40 (2026-05-18)

  Full-management view for the admin broadcast/announcement system.

  Surfaces:
    - Top overview strip (total / active / 24h / 7d / emails / WS now / verified devs)
    - Scope banner — broadcast scope is local-to-this-registry (federation
      propagation is on the roadmap)
    - Filter chips (type / status / time window)
    - Compose button → modal (title / body / type / send_email / preview)
    - Broadcast list (sortable table)
    - Row click → drawer with full body + per-broadcast stats (read count,
      recent readers list, retract/reinstate/edit actions)

  All endpoints under /api/v1/admin/broadcasts/* — see admin_broadcast.py.

  Required admin flag: admin_support.
-->
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { apiClient } from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useAlive } from '@/composables/useAlive'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'

dayjs.extend(relativeTime)

const { t, tp } = useI18n()
const authStore = useAuthStore()
const uiStore = useUIStore()

// ─── Types ────────────────────────────────────────────────────────────
interface Broadcast {
  id: number
  title: string
  body: string
  broadcast_type: 'info' | 'warning' | 'maintenance' | 'critical'
  created_by: number
  created_at: string
  is_active: boolean
  send_email: boolean
  email_sent_at: string | null
  ws_recipients: number
}

interface BroadcastStats {
  broadcast_id: number
  title: string
  is_active: boolean
  ws_recipients_at_send: number
  email_sent: boolean
  read_count: number
  total_developers: number
  read_pct: number
  recent_readers: { developer_id: number; email: string; read_at: string }[]
}

interface OverviewStats {
  total: number
  active: number
  retracted: number
  last_24h: number
  last_7d: number
  by_type: Record<string, number>
  emails_sent: number
  total_recipients_lifetime: number
  ws_connections_now: number
  verified_developers: number
  scope: string
  scope_description: string
}

// ─── State ────────────────────────────────────────────────────────────
const overview = ref<OverviewStats | null>(null)
const broadcasts = ref<Broadcast[]>([])
const loadingList = ref(false)
const loadingOverview = ref(false)
const error = ref<string>('')

// Filters
const typeFilter = ref<string>('all')    // all | info | warning | maintenance | critical
const statusFilter = ref<string>('all')  // all | active | retracted
const timeFilter = ref<string>('all')    // all | 24h | 7d | 30d
const searchQuery = ref<string>('')

// Selection / drawer
const selectedBroadcast = ref<Broadcast | null>(null)
const selectedStats = ref<BroadcastStats | null>(null)
const loadingStats = ref(false)
const drawerEditMode = ref(false)
const editForm = ref({ title: '', body: '', broadcast_type: 'info' as Broadcast['broadcast_type'] })

// Compose modal
const composeOpen = ref(false)
const composeForm = ref({
  title: '',
  body: '',
  broadcast_type: 'info' as Broadcast['broadcast_type'],
  send_email: false,
  // §bc3 T3.7 — default-on so the composer doesn't get blasted by their own broadcast
  skip_self: true,
  // §bc4 T4.1 — optional org-scoped broadcast. Empty = visible to all devs.
  // Pasted org id is sent to the server as target_org_id; backend enforces
  // visibility via /notifications/unread + WS predicate.
  target_org_id: '',
})
const composeSending = ref(false)
const composeError = ref<string>('')

// Confirm modal (retract / reinstate)
const confirmOpen = ref(false)
const confirmConfig = ref<{
  title: string
  body: string
  confirmText: string
  tone: 'danger' | 'warn' | 'primary'
  action: () => Promise<void>
} | null>(null)

// Polling
let pollTimer: number | null = null

// ─── Computed ─────────────────────────────────────────────────────────
const filteredBroadcasts = computed(() => {
  let out = broadcasts.value
  if (typeFilter.value !== 'all') {
    out = out.filter(b => b.broadcast_type === typeFilter.value)
  }
  if (statusFilter.value === 'active') out = out.filter(b => b.is_active)
  if (statusFilter.value === 'retracted') out = out.filter(b => !b.is_active)
  if (timeFilter.value !== 'all') {
    const cutoff = dayjs().subtract(
      timeFilter.value === '24h' ? 24 : (timeFilter.value === '7d' ? 168 : 720),
      'hour',
    )
    out = out.filter(b => dayjs(b.created_at).isAfter(cutoff))
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    out = out.filter(b =>
      b.title.toLowerCase().includes(q) ||
      b.body.toLowerCase().includes(q),
    )
  }
  return out
})

const showingCount = computed(() => filteredBroadcasts.value.length)

// ─── API ──────────────────────────────────────────────────────────────
async function loadOverview() {
  loadingOverview.value = true
  try {
    const r = await apiClient.get<OverviewStats>('/admin/broadcasts/overview')
    overview.value = r.data
  } catch (e: any) {
    console.warn('Overview load failed', e)
  } finally {
    loadingOverview.value = false
  }
}

async function loadList() {
  loadingList.value = true
  error.value = ''
  try {
    const r = await apiClient.get<Broadcast[]>('/admin/broadcasts', {
      params: { limit: 200, include_inactive: true },
    })
    broadcasts.value = r.data
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || t('adminBroadcastsView.errors.failedToLoadBroadcasts')
  } finally {
    loadingList.value = false
  }
}

async function loadStats(id: number) {
  loadingStats.value = true
  try {
    const r = await apiClient.get<BroadcastStats>(`/admin/broadcasts/${id}/stats`)
    selectedStats.value = r.data
  } catch (e: any) {
    console.warn('Stats load failed', e)
    selectedStats.value = null
  } finally {
    loadingStats.value = false
  }
}

async function submitCompose() {
  if (!composeForm.value.title.trim() || !composeForm.value.body.trim()) {
    composeError.value = t('adminBroadcastsView.errors.titleAndBodyRequired')
    return
  }
  composeSending.value = true
  composeError.value = ''
  try {
    await apiClient.post('/admin/broadcasts', {
      title: composeForm.value.title.trim(),
      body: composeForm.value.body.trim(),
      broadcast_type: composeForm.value.broadcast_type,
      send_email: composeForm.value.send_email,
      skip_self: composeForm.value.skip_self,
      target_org_id: composeForm.value.target_org_id.trim() || null,
    })
    // §FESUITE (lifecycle 87): an org-scoped send reaches the organization's members, not every live connection on the
    // frame, so it does not claim the frame's connection count as its reach
    const toOrg = !!composeForm.value.target_org_id.trim()
    uiStore.showSuccess(t('adminBroadcastsView.toasts.broadcastSentTitle'), toOrg
      ? tp('adminBroadcastsView.toasts.broadcastSentOrgBody', '"{title}" sent to the organization\'s members', { title: composeForm.value.title })
      : t('adminBroadcastsView.toasts.broadcastSentBody', { title: composeForm.value.title, count: overview.value?.ws_connections_now ?? '?' }))
    composeOpen.value = false
    composeForm.value = { title: '', body: '', broadcast_type: 'info', send_email: false, skip_self: true, target_org_id: '' }
    await Promise.all([loadList(), loadOverview()])
  } catch (e: any) {
    composeError.value = e?.response?.data?.detail || e?.message || t('adminBroadcastsView.errors.sendFailed')
  } finally {
    composeSending.value = false
  }
}

function openCompose() {
  composeForm.value = { title: '', body: '', broadcast_type: 'info', send_email: false, skip_self: true, target_org_id: '' }
  composeError.value = ''
  composeOpen.value = true
}

// §pass40b — 3 quick-fill templates. Click a chip to populate the form.
// Just enough scaffolding to speed up the common case (typo fixes, planned
// maintenance windows, post-mortem summaries).
const composeTemplates: { id: string; label: string; data: Partial<typeof composeForm.value> }[] = [
  {
    id: 'maintenance',
    label: t('adminBroadcastsView.templates.maintenanceLabel'),
    data: {
      title: 'Maintenance window — DAY HH:MM-HH:MM UTC',
      body: 'Brief 5-15 minute touch of REGISTRY/SERVICE. Expect short interruptions to /AFFECTED_PATH/. No supply impact; no data loss; no agent suspension.',
      broadcast_type: 'maintenance',
      send_email: false,
    },
  },
  {
    id: 'feature',
    label: t('adminBroadcastsView.templates.featureLabel'),
    data: {
      title: 'New: FEATURE_NAME is live',
      body: 'TL;DR — what it does + where to find it + what it replaces (if anything). Documentation: PATH. Feedback channel: PATH.',
      broadcast_type: 'info',
      send_email: false,
    },
  },
  {
    id: 'incident',
    label: t('adminBroadcastsView.templates.incidentLabel'),
    data: {
      title: 'Resolved: SHORT_TITLE',
      body: 'Window: HH:MM-HH:MM UTC. Impact: WHO/WHAT was degraded. Root cause: ROOT. Fix: WHAT_CHANGED. Followup tasks: BULLET LIST.',
      broadcast_type: 'warning',
      send_email: true,
    },
  },
]

function applyTemplate(t: typeof composeTemplates[number]) {
  composeForm.value = { ...composeForm.value, ...t.data } as typeof composeForm.value
}

function openDrawer(b: Broadcast) {
  selectedBroadcast.value = b
  drawerEditMode.value = false
  selectedStats.value = null
  loadStats(b.id)
}

function closeDrawer() {
  selectedBroadcast.value = null
  selectedStats.value = null
  drawerEditMode.value = false
}

function startEdit() {
  if (!selectedBroadcast.value) return
  editForm.value = {
    title: selectedBroadcast.value.title,
    body: selectedBroadcast.value.body,
    broadcast_type: selectedBroadcast.value.broadcast_type,
  }
  drawerEditMode.value = true
}

// §pass40b — "Copy as new" pre-fills the compose modal with the selected
// broadcast's content. Useful for follow-up announcements that share a
// title prefix or body template. Marks the title with " (copy)" so the
// admin sees they're composing a NEW one, not editing.
function copyAsNew() {
  if (!selectedBroadcast.value) return
  composeForm.value = {
    title: `${selectedBroadcast.value.title} (copy)`,
    body: selectedBroadcast.value.body,
    broadcast_type: selectedBroadcast.value.broadcast_type,
    send_email: false,
    skip_self: true,
    target_org_id: '',
  }
  closeDrawer()
  composeOpen.value = true
}

async function saveEdit() {
  if (!selectedBroadcast.value) return
  try {
    const r = await apiClient.put<Broadcast>(
      `/admin/broadcasts/${selectedBroadcast.value.id}`,
      {
        title: editForm.value.title,
        body: editForm.value.body,
        broadcast_type: editForm.value.broadcast_type,
      },
    )
    // patch local state
    const idx = broadcasts.value.findIndex(b => b.id === selectedBroadcast.value!.id)
    if (idx !== -1) broadcasts.value[idx] = r.data
    selectedBroadcast.value = r.data
    drawerEditMode.value = false
    uiStore.showSuccess(t('adminBroadcastsView.toasts.savedTitle'), t('adminBroadcastsView.toasts.savedBody', { id: r.data.id }))
  } catch (e: any) {
    uiStore.showError(t('adminBroadcastsView.toasts.saveFailedTitle'), e?.response?.data?.detail || e?.message || t('adminBroadcastsView.errors.editFailed'))
  }
}

function confirmRetract(b: Broadcast) {
  confirmConfig.value = {
    title: t('adminBroadcastsView.confirmRetract.title'),
    body: t('adminBroadcastsView.confirmRetract.body', { title: b.title }),
    confirmText: t('adminBroadcastsView.confirmRetract.confirmText'),
    tone: 'danger',
    action: async () => {
      await apiClient.delete(`/admin/broadcasts/${b.id}`)
      b.is_active = false
      if (selectedBroadcast.value?.id === b.id) {
        selectedBroadcast.value.is_active = false
      }
      uiStore.showSuccess(t('adminBroadcastsView.toasts.retractedTitle'), t('adminBroadcastsView.toasts.retractedBody', { id: b.id }))
      await loadOverview()
    },
  }
  confirmOpen.value = true
}

function confirmReinstate(b: Broadcast) {
  confirmConfig.value = {
    title: t('adminBroadcastsView.confirmReinstate.title'),
    body: t('adminBroadcastsView.confirmReinstate.body', { title: b.title }),
    confirmText: t('adminBroadcastsView.confirmReinstate.confirmText'),
    tone: 'primary',
    action: async () => {
      const r = await apiClient.post<Broadcast>(`/admin/broadcasts/${b.id}/reinstate`)
      const idx = broadcasts.value.findIndex(x => x.id === b.id)
      if (idx !== -1) broadcasts.value[idx] = r.data
      if (selectedBroadcast.value?.id === b.id) {
        selectedBroadcast.value = r.data
      }
      uiStore.showSuccess(t('adminBroadcastsView.toasts.reinstatedTitle'), t('adminBroadcastsView.toasts.reinstatedBody', { id: b.id }))
      await loadOverview()
    },
  }
  confirmOpen.value = true
}

async function onConfirm() {
  if (!confirmConfig.value) return
  try {
    await confirmConfig.value.action()
  } catch (e: any) {
    uiStore.showError(t('adminBroadcastsView.toasts.actionFailedTitle'), e?.response?.data?.detail || e?.message || t('adminBroadcastsView.errors.actionFailed'))
  } finally {
    confirmOpen.value = false
    confirmConfig.value = null
  }
}

// ─── Lifecycle ────────────────────────────────────────────────────────
// §FESUITE (the leave sweep): a page left during its first reads starts no poll and adds no key shortcuts when they land
const alive = useAlive()
onMounted(async () => {
  await Promise.all([loadOverview(), loadList()])
  if (!alive()) return
  // Refresh overview every 30s (WS connection count drifts; we want live)
  pollTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') loadOverview()
  }, 30000)
  // §pass40 polish — keyboard shortcuts: n=new, /=search, Esc=close drawer/modal
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  document.removeEventListener('keydown', onKeydown)
})

function onKeydown(e: KeyboardEvent) {
  // §pass40b — '/' is reserved by the global Command Palette (App.vue).
  // Don't override it. We provide 'n' for compose + Esc for close.
  const tag = (e.target as HTMLElement)?.tagName
  const inField = tag === 'INPUT' || tag === 'TEXTAREA'
  if (e.key === 'Escape') {
    if (composeOpen.value && !composeSending.value) composeOpen.value = false
    else if (selectedBroadcast.value) closeDrawer()
    return
  }
  if (inField) return
  if (e.key === 'n' && !composeOpen.value && !selectedBroadcast.value) {
    e.preventDefault()
    openCompose()
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────
function typeColor(type: string) {
  switch (type) {
    case 'info': return 'cyan'
    case 'warning': return 'amber'
    case 'maintenance': return 'blue'
    case 'critical': return 'crimson'
    default: return 'cyan'
  }
}
function typeLabel(type: string) {
  return type[0].toUpperCase() + type.slice(1)
}
function formatTime(ts: string) {
  return dayjs(ts).fromNow()
}
function formatAbs(ts: string) {
  return dayjs(ts).format('MMM D YYYY · HH:mm')
}
function bodyPreview(body: string, max = 120) {
  if (body.length <= max) return body
  return body.slice(0, max).trim() + '…'
}
</script>

<template>
  <div class="adb-page">
    <!-- Header -->
    <div class="adb-header">
      <div class="adb-header-titles">
        <div class="adb-eyebrow">
          <Icon name="mdi:bullhorn" class="adb-eyebrow-icon" />
          {{ t('adminBroadcastsView.header.eyebrow') }}
        </div>
        <h1 class="adb-h1">{{ t('adminBroadcastsView.header.title') }}</h1>
        <p class="adb-sub">
          {{ t('adminBroadcastsView.header.subtitle') }}
        </p>
      </div>
      <button class="adb-compose-btn" @click="openCompose" :title="t('adminBroadcastsView.header.newBroadcastTitle')">
        <Icon name="mdi:plus" />
        {{ t('adminBroadcastsView.header.newBroadcast') }}
        <kbd class="adb-kbd">n</kbd>
      </button>
    </div>

    <!-- Scope banner -->
    <div class="adb-scope-banner" v-if="overview">
      <Icon name="mdi:alert-circle-outline" class="adb-scope-icon" />
      <div class="adb-scope-text">
        <div class="adb-scope-title">{{ t('adminBroadcastsView.scopeBanner.title') }}</div>
        <p class="adb-scope-body">{{ overview.scope_description }}</p>
      </div>
      <div class="adb-kbd-hints">
        <span class="adb-kbd-hint"><kbd class="adb-kbd adb-kbd-mono">n</kbd>{{ t('adminBroadcastsView.scopeBanner.kbdNew') }}</span>
        <span class="adb-kbd-hint"><kbd class="adb-kbd adb-kbd-mono">Esc</kbd>{{ t('adminBroadcastsView.scopeBanner.kbdClose') }}</span>
      </div>
    </div>

    <!-- Overview metrics strip -->
    <div class="adb-stats-grid">
      <div class="adb-stat" @click="statusFilter = 'all'; typeFilter = 'all'; timeFilter = 'all'">
        <div class="adb-stat-val">{{ overview?.total ?? '—' }}</div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.lifetime') }}</div>
      </div>
      <div class="adb-stat adb-stat-active" @click="statusFilter = 'active'">
        <div class="adb-stat-val">{{ overview?.active ?? '—' }}</div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.active') }}</div>
      </div>
      <div class="adb-stat adb-stat-retracted" @click="statusFilter = 'retracted'">
        <div class="adb-stat-val">{{ overview?.retracted ?? '—' }}</div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.retracted') }}</div>
      </div>
      <div class="adb-stat" @click="timeFilter = '24h'">
        <div class="adb-stat-val">{{ overview?.last_24h ?? '—' }}</div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.last24h') }}</div>
      </div>
      <div class="adb-stat" @click="timeFilter = '7d'">
        <div class="adb-stat-val">{{ overview?.last_7d ?? '—' }}</div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.last7d') }}</div>
      </div>
      <div class="adb-stat" :title="t('adminBroadcastsView.stats.wsOnlineTitle', { n: overview?.ws_connections_now ?? 0 })">
        <div class="adb-stat-val">
          <Icon name="mdi:wifi" class="adb-stat-icon" />
          {{ overview?.ws_connections_now ?? '—' }}
        </div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.wsOnline') }}</div>
      </div>
      <div class="adb-stat" :title="t('adminBroadcastsView.stats.verifiedDevsTitle', { n: overview?.verified_developers ?? 0 })">
        <div class="adb-stat-val">
          <Icon name="mdi:account-multiple-outline" class="adb-stat-icon" />
          {{ overview?.verified_developers ?? '—' }}
        </div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.verifiedDevs') }}</div>
      </div>
      <div class="adb-stat" :title="t('adminBroadcastsView.stats.emailsSentTitle', { n: overview?.emails_sent ?? 0 })">
        <div class="adb-stat-val">
          <Icon name="mdi:email-fast" class="adb-stat-icon" />
          {{ overview?.emails_sent ?? '—' }}
        </div>
        <div class="adb-stat-lbl">{{ t('adminBroadcastsView.stats.emailsSent') }}</div>
      </div>
    </div>

    <!-- By-type breakdown -->
    <div class="adb-type-grid" v-if="overview">
      <div
        v-for="t in (['info','warning','maintenance','critical'] as const)"
        :key="t"
        class="adb-type-card"
        :class="[`adb-type-${typeColor(t)}`, { 'adb-type-active': typeFilter === t }]"
        @click="typeFilter = typeFilter === t ? 'all' : t"
      >
        <span class="adb-type-pip"></span>
        <span class="adb-type-label">{{ typeLabel(t) }}</span>
        <span class="adb-type-count">{{ overview.by_type[t] ?? 0 }}</span>
      </div>
    </div>

    <!-- Filters + Search -->
    <div class="adb-filters">
      <div class="adb-filter-group">
        <span class="adb-filter-label">{{ t('adminBroadcastsView.filters.status') }}</span>
        <button
          v-for="opt in [{v:'all',l:t('adminBroadcastsView.filters.all')},{v:'active',l:t('adminBroadcastsView.filters.activeChip')},{v:'retracted',l:t('adminBroadcastsView.filters.retractedChip')}]"
          :key="opt.v"
          class="adb-chip"
          :class="{ 'adb-chip-active': statusFilter === opt.v }"
          @click="statusFilter = opt.v"
        >{{ opt.l }}</button>
      </div>
      <div class="adb-filter-group">
        <span class="adb-filter-label">{{ t('adminBroadcastsView.filters.time') }}</span>
        <button
          v-for="opt in [{v:'all',l:t('adminBroadcastsView.filters.any')},{v:'24h',l:'24h'},{v:'7d',l:'7d'},{v:'30d',l:'30d'}]"
          :key="opt.v"
          class="adb-chip"
          :class="{ 'adb-chip-active': timeFilter === opt.v }"
          @click="timeFilter = opt.v"
        >{{ opt.l }}</button>
      </div>
      <div class="adb-search">
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('adminBroadcastsView.filters.searchPlaceholder')"
          class="adb-search-input"
        />
      </div>
      <div class="adb-showing">
        {{ t('adminBroadcastsView.filters.showing', { count: showingCount, total: broadcasts.length }) }}
      </div>
    </div>

    <!-- Error state -->
    <div v-if="error" class="adb-error">
      <Icon name="mdi:alert-circle-outline" /> {{ error }}
    </div>

    <!-- Loading state -->
    <div v-else-if="loadingList && broadcasts.length === 0" class="adb-loading">
      <div class="adb-spinner"></div>
      {{ t('adminBroadcastsView.list.loading') }}
    </div>

    <!-- Empty state -->
    <div v-else-if="!loadingList && filteredBroadcasts.length === 0" class="adb-empty">
      <Icon name="mdi:bullhorn-outline" class="adb-empty-icon" />
      <h3 class="adb-empty-title">{{ broadcasts.length === 0 ? t('adminBroadcastsView.empty.noBroadcastsYet') : t('adminBroadcastsView.empty.noMatches') }}</h3>
      <p class="adb-empty-text">
        {{ broadcasts.length === 0
           ? t('adminBroadcastsView.empty.composeCta')
           : t('adminBroadcastsView.empty.clearFilters', { total: broadcasts.length }) }}
      </p>
      <button v-if="broadcasts.length === 0" class="adb-compose-btn-empty" @click="openCompose">
        <Icon name="mdi:plus" />{{ t('adminBroadcastsView.empty.composeFirstBtn') }}
      </button>
    </div>

    <!-- List -->
    <div v-else class="adb-list">
      <div
        v-for="b in filteredBroadcasts"
        :key="b.id"
        class="adb-row"
        :class="[`adb-row-${typeColor(b.broadcast_type)}`, { 'adb-row-retracted': !b.is_active }]"
        @click="openDrawer(b)"
      >
        <div class="adb-row-accent"></div>
        <div class="adb-row-main">
          <div class="adb-row-top">
            <span class="adb-type-pill" :class="`adb-pill-${typeColor(b.broadcast_type)}`">
              {{ typeLabel(b.broadcast_type) }}
            </span>
            <span v-if="!b.is_active" class="adb-status-pill adb-status-retracted">
              <Icon name="mdi:archive-outline" />{{ t('adminBroadcastsView.row.retractedPill') }}
            </span>
            <span v-if="b.send_email" class="adb-meta-pill" :title="b.email_sent_at ? t('adminBroadcastsView.row.emailedAt', { time: formatAbs(b.email_sent_at) }) : t('adminBroadcastsView.row.emailQueued')">
              <Icon name="mdi:email-fast" />{{ t('adminBroadcastsView.row.emailedPill') }}
            </span>
            <span class="adb-id-pill">#{{ b.id }}</span>
            <span class="adb-meta-pill" :title="t('adminBroadcastsView.row.wsSentTitle', { n: b.ws_recipients })">
              <Icon name="mdi:wifi" /> {{ b.ws_recipients }}
            </span>
            <span class="adb-time" :title="formatAbs(b.created_at)">{{ formatTime(b.created_at) }}</span>
          </div>
          <h3 class="adb-row-title">{{ b.title }}</h3>
          <p class="adb-row-body">{{ bodyPreview(b.body) }}</p>
        </div>
        <div class="adb-row-actions" @click.stop>
          <button
            v-if="b.is_active"
            class="adb-icon-btn adb-icon-btn-danger"
            :title="t('adminBroadcastsView.row.retractBtnTitle')"
            @click="confirmRetract(b)"
          >
            <Icon name="mdi:archive-outline" />
          </button>
          <button
            v-else
            class="adb-icon-btn adb-icon-btn-primary"
            :title="t('adminBroadcastsView.row.reinstateBtnTitle')"
            @click="confirmReinstate(b)"
          >
            <Icon name="mdi:undo-variant" />
          </button>
          <Icon name="mdi:chevron-right" class="adb-row-chev" />
        </div>
      </div>
    </div>

    <!-- ─── Compose modal ─── -->
    <div v-if="composeOpen" class="adb-modal-backdrop" @click.self="composeOpen = false">
      <div class="adb-modal">
        <div class="adb-modal-header">
          <h2 class="adb-modal-title">
            <Icon name="mdi:send" />{{ t('adminBroadcastsView.compose.title') }}
          </h2>
          <button class="adb-modal-close" @click="composeOpen = false">
            <Icon name="mdi:close-circle" />
          </button>
        </div>
        <div class="adb-modal-body">
          <!-- Quick templates -->
          <div class="adb-templates">
            <span class="adb-templates-label">{{ t('adminBroadcastsView.compose.startFrom') }}</span>
            <button
              v-for="t in composeTemplates"
              :key="t.id"
              class="adb-template-chip"
              @click="applyTemplate(t)"
              type="button"
              :disabled="composeSending"
            >{{ t.label }}</button>
            <button
              class="adb-template-chip"
              @click="composeForm = { title: '', body: '', broadcast_type: 'info', send_email: false }"
              type="button"
              :disabled="composeSending"
            >{{ t('adminBroadcastsView.compose.blank') }}</button>
          </div>
          <div class="adb-field">
            <label class="adb-field-label">{{ t('adminBroadcastsView.compose.titleLabel') }}</label>
            <input
              v-model="composeForm.title"
              type="text"
              maxlength="200"
              :placeholder="t('adminBroadcastsView.compose.titlePlaceholder')"
              class="adb-input"
              :disabled="composeSending"
            />
            <div class="adb-field-hint">{{ t('adminBroadcastsView.compose.titleHint', { len: composeForm.title.length }) }}</div>
          </div>
          <div class="adb-field">
            <label class="adb-field-label">{{ t('adminBroadcastsView.compose.bodyLabel') }}</label>
            <textarea
              v-model="composeForm.body"
              rows="6"
              :placeholder="t('adminBroadcastsView.compose.bodyPlaceholder')"
              class="adb-textarea"
              :disabled="composeSending"
            ></textarea>
            <div class="adb-field-hint">{{ t('adminBroadcastsView.compose.bodyHint', { len: composeForm.body.length }) }}</div>
          </div>
          <div class="adb-field">
            <label class="adb-field-label">{{ t('adminBroadcastsView.compose.typeLabel') }}</label>
            <div class="adb-type-picker">
              <button
                v-for="t in (['info','warning','maintenance','critical'] as const)"
                :key="t"
                class="adb-type-opt"
                :class="[`adb-type-${typeColor(t)}`, { 'adb-type-opt-active': composeForm.broadcast_type === t }]"
                @click="composeForm.broadcast_type = t"
                :disabled="composeSending"
                type="button"
              >
                <span class="adb-type-pip"></span>
                {{ typeLabel(t) }}
              </button>
            </div>
          </div>
          <div class="adb-field">
            <label class="adb-checkbox-row">
              <input
                v-model="composeForm.send_email"
                type="checkbox"
                :disabled="composeSending"
              />
              <span class="adb-checkbox-text">
                <strong>{{ t('adminBroadcastsView.compose.emailCheckboxLabel') }}</strong>
                <span class="adb-checkbox-hint">
                  {{ t('adminBroadcastsView.compose.emailCheckboxHint', { count: overview?.verified_developers ?? '?' }) }}
                </span>
              </span>
            </label>
          </div>
          <!-- §bc3 T3.7 — Self-skip toggle -->
          <div class="adb-field">
            <label class="adb-checkbox-row">
              <input
                v-model="composeForm.skip_self"
                type="checkbox"
                :disabled="composeSending"
              />
              <span class="adb-checkbox-text">
                <strong>{{ t('adminBroadcastsView.compose.skipSelfLabel') }}</strong>
                <span class="adb-checkbox-hint">
                  {{ t('adminBroadcastsView.compose.skipSelfHint') }}
                </span>
              </span>
            </label>
          </div>
          <!-- §bc4 T4.1 — Audience scope: All vs. Org-scoped -->
          <div class="adb-field">
<label class="adb-field-label">{{ t('adminBroadcastsView.compose.audienceScopeLabel') }}</label>
            <input
              v-model="composeForm.target_org_id"
              type="text"
              class="adb-input"
              :disabled="composeSending"
              :placeholder="t('adminBroadcastsView.compose.audienceScopePlaceholder')"
              maxlength="255"
            />
            <p class="adb-field-hint">
              {{ t('adminBroadcastsView.compose.audienceScopeHint') }}
            </p>
          </div>

          <!-- Live preview -->
          <div class="adb-field">
<label class="adb-field-label">{{ t('adminBroadcastsView.compose.previewLabel') }}</label>
            <div class="adb-preview" :class="`adb-preview-${typeColor(composeForm.broadcast_type)}`">
              <div class="adb-preview-accent"></div>
              <div class="adb-preview-body">
                <div class="adb-preview-top">
                  <span class="adb-type-pill" :class="`adb-pill-${typeColor(composeForm.broadcast_type)}`">
                    {{ typeLabel(composeForm.broadcast_type) }}
                  </span>
                  <span class="adb-preview-time">{{ t('adminBroadcastsView.compose.previewJustNow') }}</span>
                </div>
                <h4 class="adb-preview-title">{{ composeForm.title || t('adminBroadcastsView.compose.previewTitlePlaceholder') }}</h4>
                <p class="adb-preview-text">{{ composeForm.body || t('adminBroadcastsView.compose.previewBodyPlaceholder') }}</p>
              </div>
            </div>
          </div>

          <div v-if="composeError" class="adb-error">
            <Icon name="mdi:alert-circle-outline" /> {{ composeError }}
          </div>
        </div>
        <div class="adb-modal-footer">
          <button class="adb-btn adb-btn-ghost" @click="composeOpen = false" :disabled="composeSending">{{ t('adminBroadcastsView.compose.cancelBtn') }}</button>
          <button class="adb-btn adb-btn-primary" @click="submitCompose" :disabled="composeSending || !composeForm.title.trim() || !composeForm.body.trim()">
            <Icon name="mdi:send" />
            {{ composeSending ? t('adminBroadcastsView.compose.sending')
              : composeForm.target_org_id?.trim() ? t('adminBroadcastsView.compose.sendBtnOrg', 'Send to the organization\'s members')
              : t('adminBroadcastsView.compose.sendBtn', { live: overview?.ws_connections_now ?? 0, verified: overview?.verified_developers ?? 0 }) }}
          </button>
        </div>
      </div>
    </div>

    <!-- ─── Detail drawer ─── -->
    <div v-if="selectedBroadcast" class="adb-drawer-backdrop" @click.self="closeDrawer">
      <aside class="adb-drawer">
        <div class="adb-drawer-header" :class="`adb-drawer-header-${typeColor(selectedBroadcast.broadcast_type)}`">
          <div>
            <div class="adb-drawer-eyebrow">{{ t('adminBroadcastsView.drawer.eyebrow', { id: selectedBroadcast.id }) }}</div>
            <h2 class="adb-drawer-title">{{ selectedBroadcast.title }}</h2>
            <div class="adb-drawer-meta">
              <span class="adb-type-pill" :class="`adb-pill-${typeColor(selectedBroadcast.broadcast_type)}`">
                {{ typeLabel(selectedBroadcast.broadcast_type) }}
              </span>
              <span v-if="!selectedBroadcast.is_active" class="adb-status-pill adb-status-retracted">
                <Icon name="mdi:archive-outline" />{{ t('adminBroadcastsView.row.retractedPill') }}
              </span>
              <span v-else class="adb-status-pill adb-status-active">
                <Icon name="mdi:check-circle" />{{ t('adminBroadcastsView.drawer.activePill') }}
              </span>
              <span class="adb-drawer-time">{{ formatAbs(selectedBroadcast.created_at) }}</span>
            </div>
          </div>
          <button class="adb-drawer-close" @click="closeDrawer" :aria-label="t('adminBroadcastsView.drawer.closeAriaLabel')">
            <Icon name="mdi:close-circle" />
          </button>
        </div>

        <div class="adb-drawer-body">
          <!-- Stats section -->
          <section class="adb-drawer-section">
            <h3 class="adb-drawer-section-title">{{ t('adminBroadcastsView.drawer.statsTitle') }}</h3>
            <div v-if="loadingStats && !selectedStats" class="adb-loading-inline">
              <div class="adb-spinner adb-spinner-sm"></div>
              {{ t('adminBroadcastsView.drawer.loadingStats') }}
            </div>
            <div v-else-if="selectedStats" class="adb-stats-row">
              <div class="adb-stat-block">
                <div class="adb-stat-block-val">{{ selectedStats.ws_recipients_at_send }}</div>
                <div class="adb-stat-block-lbl">{{ t('adminBroadcastsView.drawer.wsRecipients') }}<br/><small>{{ t('adminBroadcastsView.drawer.atSendTime') }}</small></div>
              </div>
              <div class="adb-stat-block">
                <div class="adb-stat-block-val">{{ selectedStats.read_count }}<small> / {{ selectedStats.total_developers }}</small></div>
                <div class="adb-stat-block-lbl">{{ t('adminBroadcastsView.drawer.readBy') }}<br/><small>{{ t('adminBroadcastsView.drawer.verifiedDevs') }}</small></div>
              </div>
              <div class="adb-stat-block">
                <div class="adb-stat-block-val">{{ selectedStats.read_pct }}<small>%</small></div>
                <div class="adb-stat-block-lbl">{{ t('adminBroadcastsView.drawer.readRate') }}</div>
              </div>
              <div class="adb-stat-block" :class="{ 'adb-stat-block-yes': selectedStats.email_sent }">
                <div class="adb-stat-block-val">
                  <Icon :name="selectedStats.email_sent ? 'mdi:email-fast' : 'mdi:close-circle'" />
                </div>
                <div class="adb-stat-block-lbl">{{ selectedStats.email_sent ? t('adminBroadcastsView.drawer.emailed') : t('adminBroadcastsView.drawer.noEmail') }}</div>
              </div>
            </div>
          </section>

          <!-- Body / Edit form -->
          <section class="adb-drawer-section">
            <div class="adb-drawer-section-header">
              <h3 class="adb-drawer-section-title">{{ t('adminBroadcastsView.drawer.contentTitle') }}</h3>
              <button
                v-if="!drawerEditMode"
                class="adb-icon-btn adb-icon-btn-ghost"
                @click="startEdit"
                :title="t('adminBroadcastsView.drawer.editTitle')"
              >
                <Icon name="mdi:pencil-outline" />{{ t('adminBroadcastsView.drawer.editBtn') }}
              </button>
            </div>
            <div v-if="!drawerEditMode" class="adb-drawer-body-text">
              <p>{{ selectedBroadcast.body }}</p>
            </div>
            <div v-else class="adb-edit-form">
              <div class="adb-field">
                <label class="adb-field-label">{{ t('adminBroadcastsView.compose.titleLabel') }}</label>
                <input v-model="editForm.title" type="text" maxlength="200" class="adb-input" />
              </div>
              <div class="adb-field">
                <label class="adb-field-label">{{ t('adminBroadcastsView.compose.bodyLabel') }}</label>
                <textarea v-model="editForm.body" rows="6" class="adb-textarea"></textarea>
              </div>
              <div class="adb-field">
                <label class="adb-field-label">{{ t('adminBroadcastsView.compose.typeLabel') }}</label>
                <div class="adb-type-picker">
                  <button
                    v-for="t in (['info','warning','maintenance','critical'] as const)"
                    :key="t"
                    class="adb-type-opt"
                    :class="[`adb-type-${typeColor(t)}`, { 'adb-type-opt-active': editForm.broadcast_type === t }]"
                    @click="editForm.broadcast_type = t"
                    type="button"
                  >
                    <span class="adb-type-pip"></span>
                    {{ typeLabel(t) }}
                  </button>
                </div>
              </div>
              <div class="adb-edit-actions">
                <button class="adb-btn adb-btn-ghost" @click="drawerEditMode = false">{{ t('adminBroadcastsView.compose.cancelBtn') }}</button>
                <button class="adb-btn adb-btn-primary" @click="saveEdit">
                  <Icon name="mdi:content-save" /> {{ t('adminBroadcastsView.drawer.saveBtn') }}
                </button>
              </div>
            </div>
          </section>

          <!-- Recent readers -->
          <section v-if="selectedStats && selectedStats.recent_readers.length > 0" class="adb-drawer-section">
            <h3 class="adb-drawer-section-title">{{ t('adminBroadcastsView.drawer.recentReadersTitle') }} <small>{{ t('adminBroadcastsView.drawer.recentReadersLast10') }}</small></h3>
            <ul class="adb-readers-list">
              <li v-for="r in selectedStats.recent_readers" :key="r.developer_id">
                <Icon name="mdi:eye-outline" class="adb-reader-icon" />
                <span class="adb-reader-email">{{ r.email }}</span>
                <span class="adb-reader-time">{{ formatTime(r.read_at) }}</span>
              </li>
            </ul>
          </section>
          <section v-else-if="selectedStats && selectedStats.read_count === 0" class="adb-drawer-section">
            <h3 class="adb-drawer-section-title">{{ t('adminBroadcastsView.drawer.recentReadersTitle') }}</h3>
            <p class="adb-drawer-muted">{{ t('adminBroadcastsView.drawer.noReaders') }}</p>
          </section>
        </div>

        <div class="adb-drawer-footer">
          <button class="adb-btn adb-btn-ghost" @click="copyAsNew" :title="t('adminBroadcastsView.drawer.copyAsNewTitle')">
            <Icon name="mdi:plus" />{{ t('adminBroadcastsView.drawer.copyAsNewBtn') }}
          </button>
          <div class="adb-drawer-footer-spacer"></div>
          <button
            v-if="selectedBroadcast.is_active"
            class="adb-btn adb-btn-danger"
            @click="confirmRetract(selectedBroadcast)"
          >
            <Icon name="mdi:archive-outline" />{{ t('adminBroadcastsView.row.retractBtnTitle') }}
          </button>
          <button
            v-else
            class="adb-btn adb-btn-primary"
            @click="confirmReinstate(selectedBroadcast)"
          >
            <Icon name="mdi:undo-variant" />{{ t('adminBroadcastsView.row.reinstateBtnTitle') }}
          </button>
        </div>
      </aside>
    </div>

    <!-- Confirm action modal -->
    <ConfirmActionModal
      v-if="confirmConfig"
      :show="confirmOpen"
      :title="confirmConfig.title"
      :message="confirmConfig.body"
      :confirm-text="confirmConfig.confirmText"
      :tone="confirmConfig.tone"
      @confirm="onConfirm"
      @close="confirmOpen = false; confirmConfig = null"
    />
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════════════
   AdminBroadcasts — AAA+ Design Pass
   Palette: var(--nc-primary) cyan accents, amber for broadcast-active,
   crimson for critical/retract, glass-morphism cards.
   ═══════════════════════════════════════════════════════════════════ */

.adb-page {
  min-height: 100vh;
  padding: 32px 32px 80px;
  font-family: var(--st-sans, 'Inter', system-ui, sans-serif);

  /* pass42 type-color tokens (centralized, theme-aware) */
  --adb-cyan:        var(--nc-primary);
  --adb-cyan-rgb:    var(--nc-primary-rgb);
  --adb-amber:       var(--st-amber);
  --adb-amber-rgb:   var(--st-amber-rgb);
  --adb-blue:        var(--st-blue);
  --adb-blue-rgb:    var(--st-blue-rgb);
  --adb-crimson:     var(--st-red);
  --adb-crimson-rgb: var(--st-red-rgb);
  --adb-success:     var(--st-green);
  --adb-success-rgb: var(--st-green-rgb);
  --adb-neutral:     var(--st-text-muted);
}

/* ── Header ─── */
.adb-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 24px;
}
.adb-header-titles { flex: 1; min-width: 0; }
.adb-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--st-cyan, var(--nc-primary));
  margin-bottom: 8px;
}
.adb-eyebrow-icon { font-size: 14px; }
.adb-h1 {
  font-size: 28px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 6px;
  letter-spacing: -0.01em;
}
.adb-sub {
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
  max-width: 640px;
  line-height: 1.5;
}
.adb-compose-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(var(--adb-amber-rgb), 0.18), rgba(var(--adb-amber-rgb), 0.1));
  border: 1px solid rgba(var(--adb-amber-rgb), 0.42);
  color: var(--adb-amber);
  font-family: var(--st-mono, monospace);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}
.adb-compose-btn:hover {
  background: linear-gradient(135deg, rgba(var(--adb-amber-rgb), 0.28), rgba(var(--adb-amber-rgb), 0.18));
  border-color: rgba(var(--adb-amber-rgb), 0.72);
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(var(--adb-amber-rgb), 0.18);
}

/* ── Scope banner ─── */
.adb-scope-banner {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px 18px;
  border-radius: 10px;
  background: rgba(var(--adb-blue-rgb), 0.06);
  border: 1px solid rgba(var(--adb-blue-rgb), 0.18);
  margin-bottom: 24px;
}
.adb-scope-text { flex: 1; min-width: 0; }
.adb-kbd-hints {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
  align-items: center;
}
.adb-kbd-hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-muted, #8696b8);
}
.adb-kbd-mono {
  width: auto;
  min-width: 18px;
  padding: 0 5px;
  height: 16px;
  font-size: 10px;
  border-color: rgba(var(--nc-primary-rgb), 0.32);
  color: var(--nc-primary);
  background: rgba(var(--nc-primary-rgb), 0.08);
  margin-left: 0;
}
.adb-scope-icon {
  color: var(--adb-blue);
  font-size: 20px;
  flex-shrink: 0;
  margin-top: 1px;
}
.adb-scope-title {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--adb-blue);
  margin-bottom: 4px;
}
.adb-scope-body {
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
  line-height: 1.5;
}

/* ── Stats grid ─── */
.adb-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(135px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.adb-stat {
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  border-radius: 10px;
  padding: 14px 14px;
  cursor: pointer;
  transition: border-color 0.2s, transform 0.15s, background 0.2s;
}
.adb-stat:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.32);
  transform: translateY(-2px);
}
.adb-stat-active {
  border-left: 3px solid var(--adb-success);
}
.adb-stat-retracted {
  border-left: 3px solid #6b7280;
}
.adb-stat-val {
  font-family: var(--st-mono, monospace);
  font-size: 22px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
  line-height: 1.1;
  display: flex;
  align-items: center;
  gap: 6px;
}
.adb-stat-icon {
  font-size: 14px;
  color: var(--st-cyan, var(--nc-primary));
}
.adb-stat-lbl {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
  margin-top: 6px;
}

/* ── By-type grid ─── */
.adb-type-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 10px;
  margin-bottom: 24px;
}
.adb-type-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  cursor: pointer;
  transition: all 0.2s;
}
.adb-type-card:hover { transform: translateY(-1px); }
.adb-type-active { box-shadow: 0 0 0 1px var(--type-accent, var(--nc-primary)); }
.adb-type-cyan { --type-accent: var(--adb-cyan); }
.adb-type-amber { --type-accent: var(--adb-amber); }
.adb-type-blue { --type-accent: var(--adb-blue); }
.adb-type-crimson { --type-accent: var(--adb-crimson); }
.adb-type-pip {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--type-accent);
  box-shadow: 0 0 8px var(--type-accent);
  flex-shrink: 0;
}
.adb-type-label {
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--st-text, #c8d8f0);
  flex: 1;
}
.adb-type-count {
  font-family: var(--st-mono, monospace);
  font-size: 14px;
  font-weight: 700;
  color: var(--type-accent);
}

/* ── Filters ─── */
.adb-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px 24px;
  padding: 14px 18px;
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.5));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.08));
  border-radius: 10px;
  margin-bottom: 20px;
}
.adb-filter-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.adb-filter-label {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
  margin-right: 4px;
}
.adb-chip {
  padding: 4px 10px;
  border-radius: 14px;
  background: transparent;
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.18));
  color: var(--st-text-muted, #8696b8);
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.adb-chip:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  color: var(--st-text, #c8d8f0);
}
.adb-chip-active {
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: var(--st-cyan, var(--nc-primary));
}
.adb-search { flex: 1; min-width: 220px; }
.adb-search-input {
  width: 100%;
  padding: 7px 12px;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.18));
  border-radius: 6px;
  color: var(--st-text, #c8d8f0);
  font-size: 13px;
  font-family: var(--st-sans, sans-serif);
}
.adb-search-input:focus {
  outline: none;
  border-color: rgba(var(--nc-primary-rgb), 0.55);
}
.adb-showing {
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  color: var(--st-text-muted, #8696b8);
}
.adb-showing strong {
  color: var(--st-text, #c8d8f0);
  font-weight: 700;
}

/* ── List ─── */
.adb-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.adb-row {
  display: flex;
  align-items: stretch;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  border-radius: 10px;
  cursor: pointer;
  overflow: hidden;
  transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s;
}
.adb-row:hover {
  border-color: color-mix(in srgb, var(--row-accent, var(--nc-primary)) 50%, transparent);
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18), 0 0 0 1px color-mix(in srgb, var(--row-accent, var(--nc-primary)) 20%, transparent);
}
/* §FESUITE: a retracted row stays readable; its "retracted" pill names the state. The row-wide opacity (0.55) put
   its id, type and body text at 2.3-3.7:1, and no opacity below 1 keeps the id at 4.5:1, so the cue is non-text. */
.adb-row-retracted { border-style: dashed; }
.adb-row-retracted .adb-row-accent { opacity: 0.35; }
.adb-row-cyan { --row-accent: var(--adb-cyan); }
.adb-row-amber { --row-accent: var(--adb-amber); }
.adb-row-blue { --row-accent: var(--adb-blue); }
.adb-row-crimson { --row-accent: var(--adb-crimson); }
.adb-row-accent {
  width: 3px;
  background: var(--row-accent);
  flex-shrink: 0;
}
.adb-row-main {
  flex: 1;
  min-width: 0;
  padding: 14px 18px;
}
.adb-row-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.adb-row-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 5px;
  line-height: 1.35;
}
.adb-row-body {
  font-size: 12.5px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
  line-height: 1.55;
  white-space: pre-wrap;
}
.adb-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  flex-shrink: 0;
}
.adb-row-chev {
  color: var(--st-text-dim, #6882ad);
  font-size: 18px;
}

/* ── Pills + meta ─── */
.adb-type-pill {
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 2px 7px;
  border-radius: 4px;
  text-transform: uppercase;
  border: 1px solid;
}
.adb-pill-cyan { background: rgba(var(--nc-primary-rgb), 0.1); color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.32); }
.adb-pill-amber { background: rgba(var(--adb-amber-rgb), 0.12); color: var(--adb-amber); border-color: rgba(var(--adb-amber-rgb), 0.32); }
.adb-pill-blue { background: rgba(var(--adb-blue-rgb), 0.12); color: var(--adb-blue); border-color: rgba(var(--adb-blue-rgb), 0.32); }
.adb-pill-crimson { background: rgba(var(--adb-crimson-rgb), 0.12); color: var(--adb-crimson); border-color: rgba(var(--adb-crimson-rgb), 0.32); }
.adb-status-pill {
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 2px 7px;
  border-radius: 4px;
  text-transform: uppercase;
  border: 1px solid;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.adb-status-active { background: rgba(var(--adb-success-rgb), 0.12); color: var(--adb-success); border-color: rgba(var(--adb-success-rgb), 0.32); }
.adb-status-retracted { background: rgba(var(--adb-blue-rgb), 0.08); color: var(--adb-neutral); border-color: rgba(var(--adb-blue-rgb), 0.18); }
.adb-meta-pill {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-muted, #8696b8);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.adb-id-pill {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
}
.adb-time {
  margin-left: auto;
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
}

/* ── Buttons ─── */
.adb-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 6px;
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid;
  background: transparent;
}
.adb-btn-ghost {
  border-color: var(--st-border, rgba(var(--nc-primary-rgb), 0.25));
  color: var(--st-text-muted, #8696b8);
}
.adb-btn-ghost:hover {
  border-color: var(--st-border-hover, rgba(var(--nc-primary-rgb), 0.5));
  color: var(--st-text, #c8d8f0);
}
.adb-btn-primary {
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: var(--nc-primary);
}
.adb-btn-primary:hover {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.75);
}
.adb-btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.adb-btn-danger {
  background: rgba(var(--adb-crimson-rgb), 0.1);
  border-color: rgba(var(--adb-crimson-rgb), 0.45);
  color: var(--adb-crimson);
}
.adb-btn-danger:hover {
  background: rgba(var(--adb-crimson-rgb), 0.18);
  border-color: rgba(var(--adb-crimson-rgb), 0.7);
}
.adb-icon-btn {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--st-text-muted, #8696b8);
  cursor: pointer;
  transition: all 0.15s;
}
.adb-icon-btn:hover {
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border-color: var(--st-border, rgba(var(--nc-primary-rgb), 0.18));
  color: var(--st-text, #c8d8f0);
}
.adb-icon-btn-danger:hover { color: var(--adb-crimson); border-color: rgba(var(--adb-crimson-rgb), 0.42); }
.adb-icon-btn-primary:hover { color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.42); }
.adb-icon-btn-ghost {
  width: auto;
  padding: 6px 10px;
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

/* ── Empty / error / loading ─── */
.adb-loading, .adb-empty {
  text-align: center;
  padding: 64px 24px;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.08));
  border-radius: 10px;
}
.adb-empty-icon {
  font-size: 48px;
  color: var(--st-text-dim, #6882ad);
  margin-bottom: 16px;
}
.adb-empty-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 8px;
}
.adb-empty-text {
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  max-width: 480px;
  margin: 0 auto 20px;
  line-height: 1.55;
}
.adb-compose-btn-empty {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: rgba(var(--adb-amber-rgb), 0.12);
  border: 1px solid rgba(var(--adb-amber-rgb), 0.4);
  color: var(--adb-amber);
  border-radius: 8px;
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
}
.adb-compose-btn-empty:hover {
  background: rgba(var(--adb-amber-rgb), 0.22);
}
.adb-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(var(--adb-crimson-rgb), 0.1);
  border: 1px solid rgba(var(--adb-crimson-rgb), 0.32);
  border-radius: 8px;
  color: var(--adb-crimson);
  font-size: 13px;
  margin-bottom: 16px;
}
.adb-spinner, .adb-spinner-sm {
  width: 24px;
  height: 24px;
  border: 2px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.18));
  border-top-color: var(--nc-primary, #06b6d4);
  border-radius: 50%;
  animation: adb-spin 0.8s linear infinite;
  display: inline-block;
  margin: 0 auto;
}
.adb-spinner-sm { width: 16px; height: 16px; border-width: 2px; }
@keyframes adb-spin { to { transform: rotate(360deg); } }

/* ── Modal (compose) ─── */
.adb-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}
.adb-modal {
  width: 100%;
  max-width: 680px;
  max-height: 90vh;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.25));
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55);
}
.adb-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
}
.adb-modal-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}
.adb-modal-close {
  background: transparent;
  border: none;
  color: var(--st-text-muted, #8696b8);
  font-size: 24px;
  cursor: pointer;
  transition: color 0.15s;
}
.adb-modal-close:hover { color: var(--st-text, #c8d8f0); }
.adb-modal-body {
  padding: 22px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.adb-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 22px;
  border-top: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
}

/* ── Form fields ─── */
.adb-field { display: flex; flex-direction: column; gap: 6px; }
.adb-field-label {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
}
.adb-input, .adb-textarea {
  padding: 9px 12px;
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.2));
  border-radius: 6px;
  color: var(--st-text, #c8d8f0);
  font-size: 13px;
  font-family: var(--st-sans, sans-serif);
  resize: vertical;
}
.adb-input:focus, .adb-textarea:focus {
  outline: none;
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.08);
}
.adb-field-hint {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
  align-self: flex-end;
}
.adb-type-picker {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.adb-type-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.18));
  border-radius: 6px;
  color: var(--st-text-muted, #8696b8);
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.adb-type-opt:hover { border-color: var(--type-accent); }
.adb-type-opt-active {
  background: color-mix(in srgb, var(--type-accent) 12%, transparent);
  border-color: var(--type-accent);
  color: var(--type-accent);
}
.adb-checkbox-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
  padding: 10px 14px;
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.18));
  border-radius: 6px;
}
.adb-checkbox-row input[type="checkbox"] {
  margin-top: 3px;
  accent-color: var(--nc-primary);
}
.adb-checkbox-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.adb-checkbox-text strong {
  font-size: 13px;
  color: var(--st-text, #c8d8f0);
  font-weight: 600;
}
.adb-checkbox-hint {
  font-size: 11px;
  color: var(--st-text-muted, #8696b8);
  line-height: 1.5;
}

/* ── Preview ─── */
.adb-preview {
  display: flex;
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.18));
  border-radius: 8px;
  overflow: hidden;
}
.adb-preview-cyan { --type-accent: var(--adb-cyan); }
.adb-preview-amber { --type-accent: var(--adb-amber); }
.adb-preview-blue { --type-accent: var(--adb-blue); }
.adb-preview-crimson { --type-accent: var(--adb-crimson); }
.adb-preview-accent {
  width: 3px;
  background: var(--type-accent);
  flex-shrink: 0;
}
.adb-preview-body { padding: 12px 16px; flex: 1; min-width: 0; }
.adb-preview-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.adb-preview-time {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
}
.adb-preview-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 4px;
}
.adb-preview-text {
  font-size: 12px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
  line-height: 1.55;
  white-space: pre-wrap;
}

/* ── Drawer ─── */
.adb-drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 9999;
  display: flex;
  justify-content: flex-end;
}
.adb-drawer {
  width: min(540px, 100vw);
  background: var(--st-surface, #0d1626);
  border-left: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.25));
  display: flex;
  flex-direction: column;
  height: 100vh;
  animation: adb-slide 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes adb-slide {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.adb-drawer-header {
  padding: 22px 24px;
  border-bottom: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.adb-drawer-header-cyan { box-shadow: inset 4px 0 0 var(--adb-cyan); }
.adb-drawer-header-amber { box-shadow: inset 4px 0 0 var(--adb-amber); }
.adb-drawer-header-blue { box-shadow: inset 4px 0 0 var(--adb-blue); }
.adb-drawer-header-crimson { box-shadow: inset 4px 0 0 var(--adb-crimson); }
.adb-drawer-eyebrow {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--st-text-muted, #8696b8);
  margin-bottom: 8px;
}
.adb-drawer-title {
  font-size: 19px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 10px;
  line-height: 1.3;
}
.adb-drawer-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.adb-drawer-time {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
}
.adb-drawer-close {
  background: transparent;
  border: none;
  color: var(--st-text-muted, #8696b8);
  font-size: 24px;
  cursor: pointer;
  flex-shrink: 0;
}
.adb-drawer-close:hover { color: var(--st-text, #c8d8f0); }
.adb-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.adb-drawer-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.adb-drawer-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.adb-drawer-section-title {
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--st-cyan, var(--nc-primary));
  margin: 0;
}
.adb-drawer-section-title small {
  font-family: var(--st-sans, sans-serif);
  font-size: 10px;
  font-weight: 400;
  color: var(--st-text-dim, #6882ad);
  margin-left: 6px;
  text-transform: none;
  letter-spacing: 0;
}
.adb-drawer-body-text {
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.1));
  border-radius: 8px;
  padding: 14px 16px;
}
.adb-drawer-body-text p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--st-text, #c8d8f0);
  white-space: pre-wrap;
}
.adb-drawer-muted {
  font-size: 12px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
}
.adb-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.adb-stat-block {
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.1));
  border-radius: 6px;
  padding: 12px 10px;
  text-align: center;
}
.adb-stat-block-val {
  font-family: var(--st-mono, monospace);
  font-size: 18px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
  line-height: 1.1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
}
.adb-stat-block-val small {
  font-size: 12px;
  color: var(--st-text-muted, #8696b8);
  font-weight: 500;
}
.adb-stat-block-yes { border-color: rgba(var(--adb-success-rgb), 0.32); }
.adb-stat-block-yes .adb-stat-block-val { color: var(--adb-success); }
.adb-stat-block-lbl {
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
  margin-top: 6px;
  line-height: 1.3;
}
.adb-stat-block-lbl small {
  display: block;
  font-size: 8px;
  color: var(--st-text-dim, #6882ad);
  margin-top: 2px;
}
.adb-loading-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--st-text-muted, #8696b8);
  padding: 14px;
}
.adb-readers-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.adb-readers-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--st-surface-deep, rgba(13, 22, 38, 0.7));
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.08));
  border-radius: 6px;
  font-size: 12px;
}
.adb-reader-icon { color: var(--st-text-dim, #6882ad); font-size: 14px; }
.adb-reader-email {
  flex: 1;
  color: var(--st-text, #c8d8f0);
  font-family: var(--st-mono, monospace);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.adb-reader-time {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
}
.adb-edit-form { display: flex; flex-direction: column; gap: 12px; }
.adb-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.adb-drawer-footer {
  padding: 14px 24px;
  border-top: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  display: flex;
  gap: 10px;
  align-items: center;
}
.adb-drawer-footer-spacer { flex: 1; }

/* ── §pass40b polish — compose-modal quick templates ─── */
.adb-templates {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding-bottom: 10px;
  margin-bottom: 4px;
  border-bottom: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.08));
}
.adb-templates-label {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
  margin-right: 2px;
}
.adb-template-chip {
  padding: 4px 10px;
  border-radius: 14px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: var(--st-text, #c8d8f0);
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.adb-template-chip:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.14);
  border-color: rgba(var(--nc-primary-rgb), 0.42);
}
.adb-template-chip:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── §pass40b polish — keyboard hint kbd ─── */
.adb-kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-left: 6px;
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 700;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(245, 158, 11, 0.35);
  color: rgba(245, 158, 11, 0.85);
}

/* ── §pass40b polish — type pip inside compose-preview pill ─── */
.adb-preview .adb-type-pill {
  position: relative;
  padding-left: 14px;
}
.adb-preview .adb-type-pill::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 50%;
  width: 5px;
  height: 5px;
  margin-top: -2.5px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}

/* ── §pass40b polish — row hover lifts the title slightly ─── */
.adb-row-title {
  transition: color 0.15s;
}
.adb-row:hover .adb-row-title {
  color: var(--row-accent, var(--nc-primary));
}

/* ── §pass40b polish — drawer header accent stripe via gradient backdrop
       (replaces the inset box-shadow which looked janky at corners) ─── */
.adb-drawer-header { position: relative; }
.adb-drawer-header::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--accent, var(--nc-primary));
}
.adb-drawer-header-cyan { --accent: var(--adb-cyan); box-shadow: none; }
.adb-drawer-header-amber { --accent: var(--adb-amber); box-shadow: none; }
.adb-drawer-header-blue { --accent: var(--adb-blue); box-shadow: none; }
.adb-drawer-header-crimson { --accent: var(--adb-crimson); box-shadow: none; }

/* ── §pass40b polish — make stats clickable feel obvious ─── */
.adb-stat::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 10px;
  pointer-events: none;
  opacity: 0;
  background: linear-gradient(135deg, transparent 30%, rgba(var(--nc-primary-rgb), 0.06));
  transition: opacity 0.15s;
}
.adb-stat { position: relative; }
.adb-stat:hover::after { opacity: 1; }

/* ── Responsive ─── */
@media (max-width: 768px) {
  .adb-page { padding: 20px 14px 60px; }
  .adb-header { flex-direction: column; gap: 14px; }
  .adb-type-picker { grid-template-columns: repeat(2, 1fr); }
  .adb-stats-row { grid-template-columns: repeat(2, 1fr); }
  .adb-kbd { display: none; }
}
</style>
