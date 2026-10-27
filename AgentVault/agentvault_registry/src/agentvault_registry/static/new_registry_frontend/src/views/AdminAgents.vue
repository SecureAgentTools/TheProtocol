<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { apiClient } from '@/services/api/client'
import { useUIStore } from '@/stores/ui'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { bulkOutcome } from './adminBulkOutcome'
import JsonViewer from '@/components/common/JsonViewer.vue'
import Icon from '@/components/Icon.vue'
import McpAuditLogPanel from '@/components/admin/McpAuditLogPanel.vue'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const { t } = useI18n()
const { localCurrency } = useCurrency()
const uiStore = useUIStore()

// ── Types ───────────────────────────────────────────────────
interface Agent {
  did: string
  name: string | null
  client_id: string
  status: string
  enforcement_status: string
  enforcement_level: number
  offense_count: number
  creator_developer_id: number
  creator_developer_email: string | null
  creator_developer_deleted: boolean
  organization_id: string | null
  team_id: string | null
  reputation_score: number
  liquid_balance: number
  staked_balance: number
  staking_tier: string | null
  auto_compound_enabled: boolean
  mtls_enabled: boolean
  spiffe_id: string | null
  created_at: string
  last_active_at: string | null
  // §pass37 (2026-05-18) — Option C signal cell fields
  last_pulled_at: string | null
  last_pulled_etag: string | null
  current_signing_kid: string | null
  drift_count_24h: number
}

interface SigningKey {
  rotation_seq: number
  kid: string
  algorithm: string
  public_jwk: Record<string, any> | null
  created_at: string
  expires_at: string | null
  is_current: boolean
}

interface LastDriftEvent {
  timestamp: string | null
  drifted_fields: string[]
  new_etag: string | null
}

interface AgentDetail extends Agent {
  public_key_jwk: Record<string, unknown> | null
  reputation_bond_amount: number
  reputation_bond_status: string
  rewards_paused_until: string | null
  total_rewards_earned: number | null
  last_reward_distribution: string | null
  last_offense_at: string | null
  mtls_enrolled_at: string | null
  latitude: number | null
  longitude: number | null
  location_label: string | null
  stakes: Array<{
    id: string
    amount: number
    staked_at: string
    unstaked_at: string | null
    is_active: boolean
  }>
  open_disputes_as_complainant: number
  open_disputes_as_defendant: number
  // §pass34 (2026-05-17) — full agent_cards.card_data + metadata
  card_data: Record<string, any> | null
  card_id: string | null
  card_created_at: string | null
  card_updated_at: string | null
  card_is_active: boolean | null
  // §pass37 (2026-05-18) — Option C drawer payloads
  signing_keys: SigningKey[]
  last_drift_event: LastDriftEvent | null
}

type StatusFilter = 'all' | 'active' | 'suspended' | 'revoked' | 'pending'
// §pass37 — Option C extra filter chips
type SignalFilter = null | 'mtls' | 'has_drift' | 'never_pulled'

// ── State ───────────────────────────────────────────────────
const agents = ref<Agent[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const agentsRead = ref(false)
const statusFilter = ref<StatusFilter>('all')
const orphansOnly = ref(false)
const mtlsOnly = ref<boolean | null>(null)
// §pass37 — Option C filter chips
const hasDriftOnly = ref(false)
const neverPulledOnly = ref(false)
const search = ref('')
const searchDebounce = ref<number | null>(null)
const limit = ref(50)
const offset = ref(0)
const sortBy = ref<'created_at' | 'last_active_at' | 'reputation_score' | 'liquid_balance'>('created_at')

// Drawer — §pass37: added cardSync + signingKeys tabs
const drawerOpen = ref(false)
type DrawerTab = 'identity' | 'ownership' | 'state' | 'balances' | 'stakes' | 'card' | 'cardSync' | 'signingKeys' | 'mcpAudit' | 'federation'
const drawerTab = ref<DrawerTab>('identity')
const selectedDetail = ref<AgentDetail | null>(null)
const drawerLoading = ref(false)

// §pass37 — Option C drawer-action state
const cardSyncDiff = ref<any | null>(null)
const cardSyncDiffLoading = ref(false)
const cardSyncDiffError = ref<string | null>(null)
const refreshingCard = ref(false)
const flaggingDrift = ref(false)
const rotatingSigKey = ref(false)
const rotatedSigKey = ref<{ kid: string; private_pem: string; old_kid_expires_at: string | null } | null>(null)
const showRotateSigKeyModal = ref(false)
const showSigKeyResultModal = ref(false)

// Action modals
const showTransferModal = ref(false)
const showRotateModal = ref(false)
const showDeleteModal = ref(false)
const showBulkSuspendModal = ref(false)
const showBulkReinstateModal = ref(false)
const showCredDisplay = ref(false)
const actionTarget = ref<Agent | null>(null)
const actionReason = ref('')

// §pass37 — bulk Option C action modals
const showBulkRefreshModal = ref(false)
const showBulkRotateSigModal = ref(false)
const showBulkFlagDriftModal = ref(false)
const showBulkDeleteWarnModal = ref(false)
const bulkRefreshBusy = ref(false)
const bulkRefreshProgress = ref<{ done: number; total: number; succeeded: number; skipped: number; failed: number } | null>(null)
const bulkRotateSigBusy = ref(false)
const bulkFlagDriftBusy = ref(false)
const bulkActionNote = ref('')
const moreMenuOpen = ref(false)
const rowFlashDids = ref<Set<string>>(new Set())  // visual cue post-refresh

// §pass34 (2026-05-17) — Card Data tab "copy JSON" UX state
const copyState = ref<'' | 'card_data' | 'jwk'>('')
function copyJson(obj: any, which: 'card_data' | 'jwk'): void {
  try {
    navigator.clipboard.writeText(JSON.stringify(obj, null, 2))
    copyState.value = which
    setTimeout(() => { if (copyState.value === which) copyState.value = '' }, 1500)
  } catch {}
}

// §pass34 (2026-05-17) — Federation tab structured info, derived from card_data.
function _shortSpiffe(s?: string | null): string | null {
  if (!s) return null
  const pats = [
    /\/operator\/([^/]+)\/registry/,
    /\/service\/registry-([^/]+)/,
    /\/ns\/agentvault\/sa\/registry-([^/]+)/,
    /\/registry-([^/]+)$/,
  ]
  for (const re of pats) { const m = s.match(re); if (m) return m[1] }
  const i = s.lastIndexOf('/'); return i > 0 && i < s.length - 1 ? s.slice(i + 1) : s
}

const federationInfo = computed(() => {
  const cd = selectedDetail.value?.card_data
  const fm = (cd?.federation_metadata as Record<string, any>) || {}
  const last = (fm.last_synced_from as string) || null
  const first = (fm.first_synced_from as string) || null
  const src = (fm.source_registry as string) || null
  const loc = fm.origin_registry_location
  let originLocation: string | null = null
  if (loc && typeof loc === 'object') {
    const lbl = (loc.label as string) || ''
    if (lbl) originLocation = lbl
    else if (loc.latitude !== undefined && loc.longitude !== undefined) originLocation = `${loc.latitude}, ${loc.longitude}`
  }
  return {
    isLocal: !last && !first && !src,
    originName: (fm.origin_registry_name as string) || null,
    sourceRegistry: src,
    lastSyncedFrom: last,
    lastSyncedFromShort: _shortSpiffe(last),
    firstSyncedFrom: first,
    firstSyncedFromShort: _shortSpiffe(first),
    lastSyncTimestamp: (fm.last_sync_timestamp as string) || null,
    firstSyncTimestamp: (fm.first_sync_timestamp as string) || null,
    protocolVersion: (fm.protocol_version as string) || (cd?.protocolVersion as string) || null,
    mtlsEnabled: fm.mtls_enabled !== undefined ? !!fm.mtls_enabled : undefined,
    spiffeId: (fm.spiffe_id as string) || null,
    originLocation,
    fedMetaRaw: Object.keys(fm).length > 0 ? fm : null,
  }
})

// Phase 6: Coordinated Suspension state
const softSuspendOnly = ref(false)
const softReinstateOnly = ref(false)
const lastSuspendBreakdown = ref<{ mtls_revoked: number; teg_suspended: number; succeeded: number } | null>(null)
// AA3 (audit 2026-05-07): inline validation feedback for the bulk modals.
const bulkValidationError = ref('')

// Phase 6.5: Multi-select state for bulk operations
const selectedDids = ref<string[]>([])
const allVisibleSelected = computed(() => {
  if (agents.value.length === 0) return false
  return agents.value.every(a => selectedDids.value.includes(a.did))
})
const someVisibleSelected = computed(() => {
  return agents.value.some(a => selectedDids.value.includes(a.did)) && !allVisibleSelected.value
})
function toggleSelectAll() {
  if (allVisibleSelected.value) {
    // Deselect all visible
    selectedDids.value = selectedDids.value.filter(d => !agents.value.find(a => a.did === d))
  } else {
    // Select all visible (preserving any already-selected from other pages)
    const visibleDids = agents.value.map(a => a.did)
    const merged = new Set([...selectedDids.value, ...visibleDids])
    selectedDids.value = Array.from(merged)
  }
}
function clearSelection() {
  selectedDids.value = []
}
function toggleSelectOne(did: string) {
  const idx = selectedDids.value.indexOf(did)
  if (idx >= 0) selectedDids.value.splice(idx, 1)
  else selectedDids.value.push(did)
}

async function bulkSuspendSelected() {
  if (selectedDids.value.length === 0) return
  // Pre-fill bulkDids and open the existing modal
  bulkDids.value = selectedDids.value.join('\n')
  actionReason.value = ''
  softSuspendOnly.value = false
  showBulkSuspendModal.value = true
}

async function bulkReinstateSelected() {
  if (selectedDids.value.length === 0) return
  bulkDids.value = selectedDids.value.join('\n')
  actionReason.value = ''
  softReinstateOnly.value = false
  showBulkReinstateModal.value = true
}

// AA-mTLS (audit 2026-05-07): replaced 2 native confirms (bulk + single
// force-mTLS-enrol) with themed ConfirmActionModal — closes the AA1 lacuna
// from batch 1 (fixed suspend/reinstate but missed force-mTLS).
const showBulkMtlsModal = ref(false)
const bulkMtlsTargets = ref<Agent[]>([])
const bulkMtlsBusy = ref(false)

const showForceMtlsModal = ref(false)
const forceMtlsTarget = ref<Agent | null>(null)
const forceMtlsBusy = ref(false)

function bulkForceMtlsSelected() {
  if (selectedDids.value.length === 0) return
  const targets = agents.value.filter(a =>
    selectedDids.value.includes(a.did) &&
    !a.mtls_enabled &&
    a.status === 'active'
  )
  if (targets.length === 0) {
    uiStore.showWarning?.(
      'No targets',
      'Selected agents either already have mTLS enrolled or are not active. Filter your selection.'
    )
    return
  }
  bulkMtlsTargets.value = targets
  showBulkMtlsModal.value = true
}

async function executeBulkForceMtls() {
  bulkMtlsBusy.value = true
  let ok = 0, fail = 0
  const errors: string[] = []
  for (const a of bulkMtlsTargets.value) {
    try {
      await apiClient.post(`/admin/agents/${encodeURIComponent(a.did)}/force-mtls-enrol`)
      ok++
    } catch (e: any) {
      fail++
      errors.push(`${a.name || a.did.slice(0, 16)}: ${e.response?.data?.detail || e.message}`)
    }
  }
  if (fail === 0) {
    uiStore.showSuccess?.('Bulk mTLS Enroll Done', `${ok}/${bulkMtlsTargets.value.length} agents enrolled.`)
  } else {
    uiStore.showError?.(
      'Bulk mTLS Enroll Partial',
      `${ok} succeeded, ${fail} failed. First failure: ${errors[0]?.slice(0, 200)}`
    )
  }
  showBulkMtlsModal.value = false
  bulkMtlsTargets.value = []
  bulkMtlsBusy.value = false
  await loadAgents()
}

// AA1+AA2 (audit 2026-05-07): route single-agent suspend/reinstate through
// the existing bulk modal (pre-fills the DID). Removes the native confirm()
// inconsistency + forces real reason capture (was hardcoded "Single-agent
// inline suspend from admin agents view"). Audit-trail integrity preserved.
import AgentAccessPanel from '@/components/agent/AgentAccessPanel.vue'  // IRONKEY
const accessDid = ref<string | null>(null)  // IRONKEY access modal

async function suspendSingleAgent(agent: Agent) {
  bulkDids.value = agent.did
  actionReason.value = ''
  softSuspendOnly.value = false
  bulkValidationError.value = ''
  showBulkSuspendModal.value = true
}

async function reinstateSingleAgent(agent: Agent) {
  bulkDids.value = agent.did
  actionReason.value = ''
  softReinstateOnly.value = false
  bulkValidationError.value = ''
  showBulkReinstateModal.value = true
}
const confirmDid = ref('')
const newOwnerId = ref<number | null>(null)
const rotatedCred = ref<{ did: string; client_id: string; secret: string } | null>(null)
const actionLoading = ref(false)
const bulkDids = ref('')

const kpis = computed(() => {
  const active = agents.value.filter(a => a.status === 'active').length
  const suspended = agents.value.filter(a => a.status === 'suspended' || a.enforcement_status === 'suspended').length
  const revoked = agents.value.filter(a => a.status === 'revoked').length
  const mtls = agents.value.filter(a => a.mtls_enabled).length
  const orphans = agents.value.filter(a => a.creator_developer_deleted).length
  return { total: total.value, active, suspended, revoked, mtls, orphans }
})

// ── Data loading ────────────────────────────────────────────
async function loadAgents() {
  loading.value = true
  error.value = ''
  try {
    if (orphansOnly.value) {
      const res = await apiClient.get('/admin/agents/orphans', { params: { limit: limit.value, offset: offset.value } })
      agents.value = res.data.agents || []
      total.value = res.data.total || 0
    } else {
      const params: Record<string, any> = { limit: limit.value, offset: offset.value, sort_by: sortBy.value }
      if (statusFilter.value !== 'all') params.status = statusFilter.value
      if (mtlsOnly.value !== null) params.has_mtls = mtlsOnly.value
      // §pass37 — Option C signal filters
      if (hasDriftOnly.value) params.has_drift = true
      if (neverPulledOnly.value) params.never_pulled = true
      if (search.value) params.search = search.value
      const res = await apiClient.get('/admin/agents', { params })
      agents.value = res.data.agents || []
      total.value = res.data.total || 0
    }
    agentsRead.value = true
  } catch (e: any) {
    error.value = e.response?.data?.detail || e.message || 'Failed to load agents'
  } finally {
    loading.value = false
  }
}

function setStatusFilter(s: StatusFilter) {
  statusFilter.value = s
  orphansOnly.value = false
  offset.value = 0
  loadAgents()
}

function toggleOrphans() {
  orphansOnly.value = !orphansOnly.value
  statusFilter.value = 'all'
  offset.value = 0
  loadAgents()
}

function toggleMtls() {
  mtlsOnly.value = mtlsOnly.value === true ? null : true
  offset.value = 0
  loadAgents()
}

// §pass37 — Option C signal filter chips
function toggleHasDrift() {
  hasDriftOnly.value = !hasDriftOnly.value
  offset.value = 0
  loadAgents()
}
function toggleNeverPulled() {
  neverPulledOnly.value = !neverPulledOnly.value
  offset.value = 0
  loadAgents()
}

// §pass37 — visual flash on the row after a pull (cyan flash → fade)
function flashRow(did: string) {
  rowFlashDids.value.add(did)
  rowFlashDids.value = new Set(rowFlashDids.value)
  setTimeout(() => {
    rowFlashDids.value.delete(did)
    rowFlashDids.value = new Set(rowFlashDids.value)
  }, 1400)
}

// ── Top-strip + KPIs derived signal totals ─────────────────────
const driftTotal24h = computed(() => agents.value.reduce((s, a) => s + (a.drift_count_24h || 0), 0))
const driftedAgentsCount = computed(() => agents.value.filter(a => a.drift_count_24h > 0).length)
const neverPulledCount = computed(() => agents.value.filter(a => a.last_pulled_at === null).length)

function applyDriftFilter() {
  if (!hasDriftOnly.value) toggleHasDrift()
}
function applyNeverPulledFilter() {
  if (!neverPulledOnly.value) toggleNeverPulled()
}

function onSearchInput() {
  if (searchDebounce.value) clearTimeout(searchDebounce.value)
  searchDebounce.value = window.setTimeout(() => {
    offset.value = 0
    loadAgents()
  }, 350)
}

function clearSearch() { search.value = ''; offset.value = 0; loadAgents() }
function nextPage() { if (offset.value + limit.value < total.value) { offset.value += limit.value; loadAgents() } }
function prevPage() { if (offset.value > 0) { offset.value = Math.max(0, offset.value - limit.value); loadAgents() } }

// ── Drawer ──────────────────────────────────────────────────
async function openDrawer(a: Agent) {
  drawerOpen.value = true
  drawerTab.value = 'identity'
  drawerLoading.value = true
  selectedDetail.value = null
  try {
    const res = await apiClient.get(`/admin/agents/${encodeURIComponent(a.did)}`)
    selectedDetail.value = res.data
  } catch (e: any) {
    uiStore.showError?.('Error', e.response?.data?.detail || e.message)
    drawerOpen.value = false
  } finally {
    drawerLoading.value = false
  }
}

function closeDrawer() { drawerOpen.value = false; selectedDetail.value = null }

async function refreshDrawer() {
  if (!selectedDetail.value) return
  const did = selectedDetail.value.did
  const res = await apiClient.get(`/admin/agents/${encodeURIComponent(did)}`)
  selectedDetail.value = res.data
}

// ── Actions ─────────────────────────────────────────────────
function openTransfer(a: Agent) {
  actionTarget.value = a
  actionReason.value = ''
  newOwnerId.value = null
  showTransferModal.value = true
}

async function confirmTransfer() {
  if (!actionTarget.value || !newOwnerId.value || actionReason.value.length < 10) return
  actionLoading.value = true
  try {
    await apiClient.post(`/admin/agents/${encodeURIComponent(actionTarget.value.did)}/transfer-ownership`, {
      new_creator_developer_id: newOwnerId.value,
      reason: actionReason.value,
    })
    uiStore.showSuccess?.('Transferred', `Agent reassigned to developer #${newOwnerId.value}.`)
    showTransferModal.value = false
    await loadAgents()
    if (selectedDetail.value?.did === actionTarget.value.did) await refreshDrawer()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

function openRotate(a: Agent) {
  actionTarget.value = a
  showRotateModal.value = true
}

async function confirmRotate() {
  if (!actionTarget.value) return
  actionLoading.value = true
  try {
    const res = await apiClient.post(`/admin/agents/${encodeURIComponent(actionTarget.value.did)}/rotate-credentials`)
    rotatedCred.value = {
      did: res.data.did,
      client_id: res.data.client_id,
      secret: res.data.new_client_secret,
    }
    showRotateModal.value = false
    showCredDisplay.value = true
    if (selectedDetail.value?.did === actionTarget.value.did) await refreshDrawer()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

// AA-mTLS (audit 2026-05-07): themed single-agent force-mTLS confirm.
function forceMtls(a: Agent) {
  forceMtlsTarget.value = a
  showForceMtlsModal.value = true
}

async function executeForceMtls() {
  const a = forceMtlsTarget.value
  if (!a) return
  forceMtlsBusy.value = true
  try {
    const res = await apiClient.post(`/admin/agents/${encodeURIComponent(a.did)}/force-mtls-enrol`)
    uiStore.showSuccess?.('Enrolled', res.data.message || 'Agent enrolled for mTLS.')
    showForceMtlsModal.value = false
    forceMtlsTarget.value = null
    await loadAgents()
    if (selectedDetail.value?.did === a.did) await refreshDrawer()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    forceMtlsBusy.value = false
  }
}

function openDelete(a: Agent) {
  actionTarget.value = a
  actionReason.value = ''
  confirmDid.value = ''
  showDeleteModal.value = true
}

async function confirmHardDelete() {
  if (!actionTarget.value || actionReason.value.length < 20 || confirmDid.value !== actionTarget.value.did) return
  actionLoading.value = true
  try {
    await apiClient.delete(`/admin/agents/${encodeURIComponent(actionTarget.value.did)}`, {
      data: { reason: actionReason.value, confirm_did: confirmDid.value },
    })
    uiStore.showSuccess?.('Deleted', 'Agent hard-deleted. Final audit event emitted.')
    showDeleteModal.value = false
    closeDrawer()
    await loadAgents()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

function openBulkSuspend() {
  bulkDids.value = ''
  actionReason.value = ''
  softSuspendOnly.value = false
  showBulkSuspendModal.value = true
}

async function confirmBulkSuspend() {
  const dids = bulkDids.value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean)
  // AA3 (audit 2026-05-07): surface validation inline instead of silent return.
  if (dids.length === 0) {
    bulkValidationError.value = 'Paste at least one DID.'
    return
  }
  if (dids.length > 50) {
    bulkValidationError.value = `Cap is 50 DIDs per bulk operation (got ${dids.length}).`
    return
  }
  if (actionReason.value.length < 10) {
    bulkValidationError.value = `Reason must be at least 10 characters (got ${actionReason.value.length}). Audit trail requires context.`
    return
  }
  bulkValidationError.value = ''
  actionLoading.value = true
  try {
    const res = await apiClient.post('/admin/agents/bulk/suspend', {
      agent_dids: dids,
      reason: actionReason.value,
      soft_suspend: softSuspendOnly.value,
    })
    // Phase 6: surface lever-by-lever breakdown
    const results = res.data.results || []
    const mtlsRevoked = results.filter((r: any) => (r.reason || '').includes('mtls=revoked')).length
    const tegSuspended = results.filter((r: any) => (r.reason || '').includes('teg=suspended')).length
    const summary = softSuspendOnly.value
      ? `${res.data.succeeded} suspended (registry only — mTLS + TEG untouched)`
      : `${res.data.succeeded} suspended · ${mtlsRevoked} mTLS revoked · ${tegSuspended} TEG accounts suspended`
    reportBulk('Suspend', res.data, summary)
    showBulkSuspendModal.value = false
    await loadAgents()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

// §FESUITE (2026-10-10): a bulk action's toast follows its outcome. Every outcome was a SUCCESS toast, so
// "0 suspended (skipped 0, failed 1 of 1)" read as done on an enforcement action.
function reportBulk(verb: 'Suspend' | 'Reinstate', data: any, summary: string) {
  const line = `${summary} (skipped ${data?.skipped ?? 0}, failed ${data?.failed ?? 0} of ${data?.requested ?? '?'})`
  const outcome = bulkOutcome(data)
  if (outcome === 'error') uiStore.showError?.(`Coordinated ${verb} failed`, line)
  else if (outcome === 'warning') uiStore.showWarning?.(`Coordinated ${verb} partly done`, line)
  else uiStore.showSuccess?.(`Coordinated ${verb} Done`, line)
}

function openBulkReinstate(a?: Agent) {
  if (a) {
    bulkDids.value = a.did
  } else {
    bulkDids.value = ''
  }
  actionReason.value = ''
  softReinstateOnly.value = false
  showBulkReinstateModal.value = true
}

async function confirmBulkReinstate() {
  const dids = bulkDids.value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean)
  if (dids.length === 0 || dids.length > 50) return
  actionLoading.value = true
  try {
    const res = await apiClient.post('/admin/agents/bulk/reinstate', {
      agent_dids: dids,
      reason: actionReason.value || '',
      soft_reinstate: softReinstateOnly.value,
    })
    const results = res.data.results || []
    const mtlsEnrolled = results.filter((r: any) => (r.reason || '').includes('mtls=enrolled')).length
    const tegReinstated = results.filter((r: any) => (r.reason || '').includes('teg=reinstated')).length
    const summary = softReinstateOnly.value
      ? `${res.data.succeeded} reinstated (registry only)`
      : `${res.data.succeeded} reinstated · ${mtlsEnrolled} mTLS re-enrolled · ${tegReinstated} TEG accounts reactivated`
    reportBulk('Reinstate', res.data, summary)
    showBulkReinstateModal.value = false
    await loadAgents()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

async function copyText(t: string) {
  try {
    await navigator.clipboard.writeText(t)
    uiStore.showInfo?.('Copied', 'Copied to clipboard.')
  } catch { /* noop */ }
}

// ───────────────────────────────────────────────────────────────
// §pass37 — Option C drawer-side actions (per-agent)
// ───────────────────────────────────────────────────────────────

async function refreshAgentCard(did: string) {
  refreshingCard.value = true
  try {
    const res = await apiClient.post(`/admin/agent-card-drift/${encodeURIComponent(did)}/refresh`)
    const outcome = res.data.outcome || {}
    if (outcome.status === 'ok') {
      const fields = (outcome.drifted_fields || []).join(', ')
      uiStore.showSuccess?.(
        'Card refreshed',
        `HTTP ${outcome.http}${fields ? ` · drift: ${fields}` : ' · no drift'}`,
      )
    } else {
      uiStore.showWarning?.(
        `Refresh ${outcome.status}`,
        outcome.reason || `HTTP ${outcome.http || '?'} from ${outcome.url || 'agent'}`,
      )
    }
    flashRow(did)
    await refreshDrawer()
    // Also refresh the row in the table so last_pulled_at + drift_count update.
    await loadAgents()
  } catch (e: any) {
    uiStore.showError?.('Refresh failed', e?.response?.data?.detail || e?.message)
  } finally {
    refreshingCard.value = false
  }
}

async function loadCardSyncDiff(did: string) {
  cardSyncDiffLoading.value = true
  cardSyncDiffError.value = null
  cardSyncDiff.value = null
  try {
    const res = await apiClient.get(`/admin/agent-card-drift/${encodeURIComponent(did)}`)
    cardSyncDiff.value = res.data
  } catch (e: any) {
    cardSyncDiffError.value = e?.response?.data?.detail || e?.message || 'failed'
  } finally {
    cardSyncDiffLoading.value = false
  }
}

async function flagDriftForReview(did: string) {
  flaggingDrift.value = true
  try {
    const note = window.prompt('Note for the audit log (optional):') || ''
    await apiClient.post(
      `/admin/agent-card-drift/${encodeURIComponent(did)}/force-register`,
      { note: note || null },
    )
    uiStore.showSuccess?.('Drift flagged', 'CommanderFlaggedDrift event emitted for follow-up.')
  } catch (e: any) {
    uiStore.showError?.('Flag failed', e?.response?.data?.detail || e?.message)
  } finally {
    flaggingDrift.value = false
  }
}

function openRotateSigKey() {
  if (!selectedDetail.value) return
  showRotateSigKeyModal.value = true
}

async function confirmRotateSigKey() {
  if (!selectedDetail.value) return
  rotatingSigKey.value = true
  try {
    const did = selectedDetail.value.did
    const res = await apiClient.post(`/admin/agents/${encodeURIComponent(did)}/rotate-signing-key`)
    rotatedSigKey.value = {
      kid: res.data.new_kid,
      private_pem: res.data.private_pem,
      old_kid_expires_at: res.data.old_kid_expires_at,
    }
    showRotateSigKeyModal.value = false
    showSigKeyResultModal.value = true
    await refreshDrawer()
    await loadAgents()
  } catch (e: any) {
    uiStore.showError?.('Rotation failed', e?.response?.data?.detail || e?.message)
  } finally {
    rotatingSigKey.value = false
  }
}

// ───────────────────────────────────────────────────────────────
// §pass37 — Option C bulk actions (toolbar "More ▾" dropdown)
// ───────────────────────────────────────────────────────────────

function bulkRefreshSelected() {
  if (selectedDids.value.length === 0) return
  bulkRefreshProgress.value = null
  bulkActionNote.value = ''
  moreMenuOpen.value = false
  showBulkRefreshModal.value = true
}

async function confirmBulkRefresh() {
  if (selectedDids.value.length === 0) return
  bulkRefreshBusy.value = true
  bulkRefreshProgress.value = {
    done: 0,
    total: selectedDids.value.length,
    succeeded: 0,
    skipped: 0,
    failed: 0,
  }
  try {
    const res = await apiClient.post('/admin/agents/bulk/refresh-cards', {
      agent_dids: selectedDids.value,
      reason: bulkActionNote.value || null,
    })
    bulkRefreshProgress.value = {
      done: res.data.requested,
      total: res.data.requested,
      succeeded: res.data.succeeded,
      skipped: res.data.skipped,
      failed: res.data.failed,
    }
    uiStore.showSuccess?.(
      'Bulk refresh done',
      `${res.data.succeeded}/${res.data.requested} pulled · ${res.data.skipped} skipped · ${res.data.failed} failed`,
    )
    selectedDids.value.forEach(flashRow)
    setTimeout(() => { showBulkRefreshModal.value = false; bulkRefreshProgress.value = null }, 800)
    await loadAgents()
  } catch (e: any) {
    uiStore.showError?.('Bulk refresh failed', e?.response?.data?.detail || e?.message)
  } finally {
    bulkRefreshBusy.value = false
  }
}

function bulkRotateSigSelected() {
  if (selectedDids.value.length === 0) return
  bulkActionNote.value = ''
  moreMenuOpen.value = false
  showBulkRotateSigModal.value = true
}

async function confirmBulkRotateSig() {
  if (selectedDids.value.length === 0) return
  bulkRotateSigBusy.value = true
  let ok = 0
  let fail = 0
  const errs: string[] = []
  for (const did of selectedDids.value) {
    try {
      await apiClient.post(`/admin/agents/${encodeURIComponent(did)}/rotate-signing-key`)
      ok++
    } catch (e: any) {
      fail++
      errs.push(`${did.slice(0, 24)}…: ${e?.response?.data?.detail || e?.message}`)
    }
  }
  if (fail === 0) {
    uiStore.showSuccess?.(
      'Bulk rotate done',
      `${ok}/${selectedDids.value.length} agents rotated. Each holder must reload their .env.secret to the new PEM (operator delivers out-of-band).`,
    )
  } else {
    uiStore.showWarning?.(
      'Bulk rotate partial',
      `${ok} ok, ${fail} failed. First failure: ${errs[0]?.slice(0, 200) || ''}`,
    )
  }
  showBulkRotateSigModal.value = false
  bulkRotateSigBusy.value = false
  await loadAgents()
}

function bulkFlagDriftSelected() {
  if (selectedDids.value.length === 0) return
  bulkActionNote.value = ''
  moreMenuOpen.value = false
  showBulkFlagDriftModal.value = true
}

async function confirmBulkFlagDrift() {
  if (selectedDids.value.length === 0) return
  bulkFlagDriftBusy.value = true
  let ok = 0
  let fail = 0
  for (const did of selectedDids.value) {
    try {
      await apiClient.post(
        `/admin/agent-card-drift/${encodeURIComponent(did)}/force-register`,
        { note: bulkActionNote.value || null },
      )
      ok++
    } catch {
      fail++
    }
  }
  uiStore.showSuccess?.(
    'Bulk flag done',
    `${ok}/${selectedDids.value.length} agents flagged. Failed: ${fail}.`,
  )
  showBulkFlagDriftModal.value = false
  bulkFlagDriftBusy.value = false
}

function bulkExportCsv() {
  if (selectedDids.value.length === 0) return
  moreMenuOpen.value = false
  const rows = agents.value.filter(a => selectedDids.value.includes(a.did))
  const header = [
    'did', 'name', 'status', 'creator_email', 'mtls_enabled',
    'liquid_balance', 'staked_balance', 'reputation_score',
    'last_pulled_at', 'current_signing_kid', 'drift_count_24h',
  ].join(',')
  const csv = [header].concat(
    rows.map(a => [
      a.did,
      JSON.stringify(a.name || ''),
      a.status,
      JSON.stringify(a.creator_developer_email || ''),
      a.mtls_enabled,
      a.liquid_balance,
      a.staked_balance,
      a.reputation_score,
      a.last_pulled_at || '',
      JSON.stringify(a.current_signing_kid || ''),
      a.drift_count_24h,
    ].join(','))
  ).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `agents-selection-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  uiStore.showInfo?.('Exported', `${rows.length} agents → CSV.`)
}

// ───────────────────────────────────────────────────────────────
// §pass37 — signal-pill click handlers — open drawer at the right tab
// ───────────────────────────────────────────────────────────────

async function openDrawerAtTab(a: Agent, tab: DrawerTab) {
  await openDrawer(a)
  drawerTab.value = tab
}

// Signals derived state for a row (memoised at template time per row)
function pullState(a: Agent): 'fresh' | 'stale' | 'never' {
  if (!a.last_pulled_at) return 'never'
  const dt = new Date(a.last_pulled_at).getTime()
  const ageH = (Date.now() - dt) / 36e5
  // 12h stale threshold (worker cadence is 6h — 2x interval is the standard
  // stale window per the existing pull-sync admin endpoint heuristic).
  return ageH > 12 ? 'stale' : 'fresh'
}

// ── Helpers ─────────────────────────────────────────────────
function timeAgo(ts: string | null): string { if (!ts) return '—'; return dayjs(ts).fromNow() }
function shortDate(ts: string | null): string { if (!ts) return '—'; return dayjs(ts).format('YYYY-MM-DD') }
// §FESUITE — every DID on a frame shares its head; the part that tells two agents apart is the tail
function truncDid(did: string): string { if (did.length <= 38) return did; return did.slice(0, 24) + '…' + did.slice(-12) }
function fmtNum(n: number): string { return (n || 0).toLocaleString(appLocale(), { maximumFractionDigits: 2 }) }
function fmtAvt(n: number): string {
  if (!n) return '0'
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K'
  return n.toFixed(2)
}
function repClass(score: number): string {
  if (score >= 800) return 'aa-rep-high'
  if (score >= 400) return 'aa-rep-med'
  if (score > 0) return 'aa-rep-low'
  return 'aa-rep-none'
}
function statusBadge(a: Agent): { label: string; cls: string } {
  if (a.status === 'revoked') return { label: 'revoked', cls: 'aa-sb-revoked' }
  if (a.status === 'suspended' || a.enforcement_status === 'suspended') return { label: 'suspended', cls: 'aa-sb-suspended' }
  if (a.creator_developer_deleted) return { label: 'orphan', cls: 'aa-sb-orphan' }
  if (a.status === 'active') return { label: 'active', cls: 'aa-sb-active' }
  return { label: a.status, cls: 'aa-sb-default' }
}

// §pass37 — global click-away to close the "More ▾" bulk dropdown
function _onGlobalClick(e: MouseEvent) {
  if (!moreMenuOpen.value) return
  const target = e.target as HTMLElement | null
  if (target && target.closest && target.closest('.aa-more-wrap')) return
  moreMenuOpen.value = false
}
// global ESC closes the more-menu + collapses diff view if open
function _onGlobalKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && moreMenuOpen.value) moreMenuOpen.value = false
}

onMounted(() => {
  loadAgents()
  document.addEventListener('click', _onGlobalClick)
  document.addEventListener('keydown', _onGlobalKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', _onGlobalClick)
  document.removeEventListener('keydown', _onGlobalKey)
})
</script>

<template>
<div class="aa hm-module">
  <div class="aa-ambient">
    <div class="aa-grid"></div>
    <div class="aa-glow aa-glow-1"></div>
    <div class="aa-glow aa-glow-2"></div>
  </div>

  <!-- Hero -->
  <section class="aa-hero" data-tour="admin-agents-hero">
    <div class="aa-hero-inner">
      <div class="aa-chip"><span class="aa-chip-dot"></span>{{ t('adminAgentsView.chip') }}</div>
      <h1 class="aa-h1">{{ t('adminAgentsView.hero.h1a') }}<span class="aa-accent">{{ t('adminAgentsView.hero.h1Accent') }}</span></h1>
      <p class="aa-lead">{{ t('adminAgentsView.lead') }}</p>
    </div>
  </section>

  <!-- KPIs -->
  <div class="aa-stats-row">
    <div class="aa-stat"><span class="aa-stat-label">{{ t('adminAgentsView.kpi.total') }}</span><span class="aa-stat-value">{{ agentsRead ? kpis.total : '—' }}</span></div>
    <div class="aa-stat aa-stat-ok"><span class="aa-stat-label">{{ t('adminAgentsView.kpi.active') }}</span><span class="aa-stat-value">{{ agentsRead ? kpis.active : '—' }}</span></div>
    <div class="aa-stat" :class="kpis.suspended > 0 ? 'aa-stat-warn' : 'aa-stat-muted'"><span class="aa-stat-label">{{ t('adminAgentsView.kpi.suspended') }}</span><span class="aa-stat-value">{{ agentsRead ? kpis.suspended : '—' }}</span></div>
    <div class="aa-stat" :class="kpis.revoked > 0 ? 'aa-stat-bad' : 'aa-stat-muted'"><span class="aa-stat-label">{{ t('adminAgentsView.kpi.revoked') }}</span><span class="aa-stat-value">{{ agentsRead ? kpis.revoked : '—' }}</span></div>
    <div class="aa-stat aa-stat-cyan"><span class="aa-stat-label">{{ t('adminAgentsView.kpi.mtls') }}</span><span class="aa-stat-value">{{ agentsRead ? kpis.mtls : '—' }}</span></div>
    <div class="aa-stat" :class="kpis.orphans > 0 ? 'aa-stat-warn' : 'aa-stat-muted'"><span class="aa-stat-label">{{ t('adminAgentsView.kpi.orphans') }}</span><span class="aa-stat-value">{{ agentsRead ? kpis.orphans : '—' }}</span></div>
  </div>

  <!-- §pass37 — slim Option C status strip (only when relevant) -->
  <div v-if="driftedAgentsCount > 0 || neverPulledCount > 0" class="aa-strip">
    <Icon icon="mdi:information" class="aa-strip-ico" />
    <span v-if="driftTotal24h > 0">
      <strong>{{ driftTotal24h }}</strong> drift event{{ driftTotal24h === 1 ? '' : 's' }}
      across <strong>{{ driftedAgentsCount }}</strong> agent{{ driftedAgentsCount === 1 ? '' : 's' }} (24h)
      <button class="aa-strip-link" @click="applyDriftFilter">filter ▸</button>
    </span>
    <span v-if="driftedAgentsCount > 0 && neverPulledCount > 0" class="aa-strip-sep">·</span>
    <span v-if="neverPulledCount > 0">
      <strong>{{ neverPulledCount }}</strong> never pulled
      <button class="aa-strip-link" @click="applyNeverPulledFilter">filter ▸</button>
    </span>
  </div>

  <!-- Filter + Search -->
  <div class="aa-toolbar">
    <div class="aa-filter-bar">
      <button class="aa-fb-btn" :class="{ 'aa-fb-active': statusFilter === 'all' && !orphansOnly }" @click="setStatusFilter('all')">{{ t('adminAgentsView.filters.all') }}</button>
      <button class="aa-fb-btn" :class="{ 'aa-fb-active': statusFilter === 'active' }" @click="setStatusFilter('active')">{{ t('adminAgentsView.filters.active') }}</button>
      <button class="aa-fb-btn" :class="{ 'aa-fb-active': statusFilter === 'suspended' }" @click="setStatusFilter('suspended')">{{ t('adminAgentsView.filters.suspended') }}</button>
      <button class="aa-fb-btn" :class="{ 'aa-fb-active': statusFilter === 'revoked' }" @click="setStatusFilter('revoked')">{{ t('adminAgentsView.filters.revoked') }}</button>
      <button class="aa-fb-btn" :class="{ 'aa-fb-active': orphansOnly }" @click="toggleOrphans">{{ t('adminAgentsView.filters.orphans') }}</button>
      <button class="aa-fb-btn" :class="{ 'aa-fb-active': mtlsOnly === true }" @click="toggleMtls">{{ t('adminAgentsView.mtlsEnabled') }}</button>
      <!-- §pass37 — Option C signal filter chips -->
      <button class="aa-fb-btn aa-fb-icon" :class="{ 'aa-fb-active': hasDriftOnly }" @click="toggleHasDrift" title="Agents with AgentCardPulled events in last 24h">
        <Icon icon="mdi:alert-circle" class="aa-fb-ic" />
        <span>Drift</span>
      </button>
      <button class="aa-fb-btn aa-fb-icon" :class="{ 'aa-fb-active': neverPulledOnly }" @click="toggleNeverPulled" title="Native cards never pulled by agent_card_pullsync">
        <Icon icon="mdi:cloud-off-outline" class="aa-fb-ic" />
        <span>Never Pulled</span>
      </button>
      <select v-model="sortBy" @change="loadAgents" class="aa-select aa-fb-right" :aria-label="t('adminAgentsView.sortAria', 'Sort agents by')">
        <option value="created_at">{{ t('adminAgentsView.sortCreated') }}</option>
        <option value="last_active_at">{{ t('adminAgentsView.sortLastActive') }}</option>
        <option value="reputation_score">{{ t('adminAgentsView.sortReputation') }}</option>
        <option value="liquid_balance">{{ t('adminAgentsView.sortBalance') }}</option>
      </select>
    </div>
    <div class="aa-search-wrap">
      <input v-model="search" @input="onSearchInput" class="aa-search" :placeholder="t('adminAgentsView.search')" />
      <button v-if="search" @click="clearSearch" class="aa-search-clear">×</button>
    </div>
    <button @click="openBulkSuspend" class="aa-btn aa-btn-warn">{{ t('adminAgentsView.bulk.suspend') }}</button>
    <button @click="openBulkReinstate()" class="aa-btn aa-btn-cyan">{{ t('adminAgentsView.bulk.reinstate') }}</button>
  </div>

  <!-- §pass37 — Bulk-actions toolbar, sticky, only when ≥1 selected. Tier-1
       direct buttons (high-frequency) + Tier-2 "More ▾" dropdown (rare/destructive) -->
  <div v-if="selectedDids.length > 0" class="aa-bulk-toolbar">
    <span class="aa-bulk-count">
      <strong>{{ selectedDids.length }}</strong> agent{{ selectedDids.length === 1 ? '' : 's' }} selected
    </span>
    <div class="aa-bulk-actions">
      <button class="aa-btn aa-btn-warn aa-btn-sm" @click="bulkSuspendSelected">
        Suspend
      </button>
      <button class="aa-btn aa-btn-cyan aa-btn-sm" @click="bulkReinstateSelected">
        Reinstate
      </button>
      <button class="aa-btn aa-btn-sm aa-btn-pull aa-btn-ic" @click="bulkRefreshSelected"
              title="Force-pull /.well-known/agent-card.json for each selected agent (bypass 6h scheduler)">
        <Icon icon="mdi:refresh" class="aa-btn-ic-svg" />
        <span>Refresh Cards</span>
      </button>

      <div class="aa-more-wrap" @click.stop>
        <button class="aa-btn aa-btn-sm aa-more-btn aa-btn-ic" @click="moreMenuOpen = !moreMenuOpen"
                :class="{ 'aa-more-open': moreMenuOpen }">
          <span>More</span>
          <Icon icon="mdi:menu-down" class="aa-btn-ic-svg aa-more-chev" />
        </button>
        <div v-if="moreMenuOpen" class="aa-more-menu" role="menu">
          <button class="aa-more-item" @click="bulkForceMtlsSelected"
                  title="Force mTLS enrollment on active, not-yet-enrolled agents">
            <Icon icon="mdi:lock" class="aa-more-ico" />
            <span>Force mTLS Enroll</span>
          </button>
          <button class="aa-more-item" @click="bulkRotateSigSelected"
                  title="Rotate EdDSA signing key for each selected agent; private PEMs returned in audit log (NOT shown)">
            <Icon icon="mdi:key" class="aa-more-ico" />
            <span>Rotate Signing Keys</span>
          </button>
          <button class="aa-more-item" @click="bulkFlagDriftSelected"
                  title="Emit CommanderFlaggedDrift audit event for each selected agent">
            <Icon icon="mdi:flag-outline" class="aa-more-ico" />
            <span>Flag Drift for Review</span>
          </button>
          <div class="aa-more-sep"></div>
          <button class="aa-more-item" @click="bulkExportCsv"
                  title="Download selected agents as CSV (RFC 4180)">
            <Icon icon="mdi:file-download-outline" class="aa-more-ico" />
            <span>Export Selection (CSV)</span>
          </button>
        </div>
      </div>

      <button class="aa-btn aa-btn-ghost aa-btn-sm" @click="clearSelection">
        Clear
      </button>
    </div>
  </div>

  <div v-if="error" class="aa-error">{{ error }}</div>

  <!-- Phase 6.5: keep table rendered always; show skeleton rows during loading
       so the page doesn't go blank with 2000+ agents on slow networks. -->
  <div class="aa-table-wrap">
    <table class="aa-table">
      <thead>
        <tr>
          <th class="aa-col-checkbox" @click.stop>
            <input
              type="checkbox"
              :checked="allVisibleSelected"
              :indeterminate.prop="someVisibleSelected"
              @change="toggleSelectAll"
              :title="allVisibleSelected ? 'Deselect all visible' : 'Select all visible'"
            />
          </th>
          <th>{{ t('adminAgentsView.table.name') }}</th>
          <th class="aa-col-did">{{ t('adminAgentsView.colDid') }}</th>
          <th>{{ t('adminAgentsView.table.status') }}</th>
          <th>{{ t('adminAgentsView.table.owner') }}</th>
          <th>{{ t('adminAgentsView.table.org') }}</th>
          <th style="text-align: right;">{{ t('adminAgentsView.table.liquid') }}</th>
          <th style="text-align: right;">{{ t('adminAgentsView.table.staked') }}</th>
          <th>{{ t('adminAgentsView.table.rep') }}</th>
          <!-- §pass37 — compound Signals column replaces standalone mTLS.
               4 indicators: mTLS / JWS signing key / pull state / drift count -->
          <th class="aa-col-signals" title="mTLS · JWS signing key · pull-sync state · 24h drift count">Signals</th>
          <th>{{ t('adminAgentsView.table.lastActive') }}</th>
          <th style="text-align: right;">{{ t('adminAgentsView.table.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <template v-if="loading && agents.length === 0">
          <tr v-for="n in 8" :key="`skel-${n}`" class="aa-row aa-row-skeleton">
            <td colspan="12"><div class="aa-skeleton-row"></div></td>
          </tr>
        </template>
        <tr v-for="a in agents" :key="a.did" class="aa-row"
            :class="{ 'aa-row-selected': selectedDids.includes(a.did), 'aa-row-flash': rowFlashDids.has(a.did) }"
            @click="openDrawer(a)">
          <td class="aa-col-checkbox" @click.stop>
            <input
              type="checkbox"
              :checked="selectedDids.includes(a.did)"
              @change="toggleSelectOne(a.did)"
              :title="`Select ${a.name || a.did}`"
            />
          </td>
          <td><span class="aa-name">{{ a.name || '—' }}</span></td>
          <td class="aa-col-did">
            <code class="aa-did" @click.stop="copyText(a.did)" :title="`${a.did} (click to copy)`">{{ truncDid(a.did) }}</code>
          </td>
          <td><span class="aa-sb" :class="statusBadge(a).cls">{{ statusBadge(a).label }}</span></td>
          <td>
            <span class="aa-owner" :class="{ 'aa-owner-deleted': a.creator_developer_deleted }">
              {{ a.creator_developer_email || `#${a.creator_developer_id}` }}
            </span>
          </td>
          <td class="aa-dim">{{ a.organization_id ? a.organization_id.slice(0, 8) : '—' }}</td>
          <td class="aa-num" :title="fmtNum(a.liquid_balance)">{{ fmtAvt(a.liquid_balance) }}</td>
          <td class="aa-num" :title="fmtNum(a.staked_balance)">{{ fmtAvt(a.staked_balance) }}</td>
          <td><span class="aa-rep" :class="repClass(a.reputation_score)">{{ a.reputation_score }}</span></td>
          <!-- §pass37 — compound Signals: clickable pills opening drawer at relevant tab -->
          <td class="aa-col-signals" @click.stop>
            <div class="aa-signals">
              <button
                class="aa-sig"
                :class="a.mtls_enabled ? 'aa-sig-on aa-sig-mtls' : 'aa-sig-off'"
                :title="a.mtls_enabled
                  ? `mTLS enrolled · click for SPIFFE-ID + SVID details`
                  : `mTLS not enrolled — click to view identity`"
                @click="openDrawerAtTab(a, 'identity')"
              ><Icon icon="mdi:lock" class="aa-sig-ic" /></button>

              <button
                class="aa-sig"
                :class="a.current_signing_kid ? 'aa-sig-on aa-sig-jws' : 'aa-sig-off'"
                :title="a.current_signing_kid
                  ? `JWS signing key registered (${a.current_signing_kid.split('#')[1] ? '#' + a.current_signing_kid.split('#')[1] : ''}) · click for rotation history`
                  : `No signing key — click to generate one`"
                @click="openDrawerAtTab(a, 'signingKeys')"
              ><Icon icon="mdi:key" class="aa-sig-ic" /></button>

              <button
                class="aa-sig"
                :class="`aa-sig-pull aa-sig-pull-${pullState(a)}`"
                :title="a.last_pulled_at
                  ? `Pull-sync state: ${pullState(a)} · last pulled ${timeAgo(a.last_pulled_at)}`
                  : `Never pulled — agent's well-known not yet reached`"
                @click="openDrawerAtTab(a, 'cardSync')"
              ><Icon :icon="a.last_pulled_at ? 'mdi:cloud-download-outline' : 'mdi:cloud-off-outline'" class="aa-sig-ic" /></button>

              <button
                v-if="a.drift_count_24h > 0"
                class="aa-sig aa-sig-drift"
                :title="`${a.drift_count_24h} drift event(s) in last 24h — click for details`"
                @click="openDrawerAtTab(a, 'cardSync')"
              ><Icon icon="mdi:alert-circle" class="aa-sig-ic" /><span class="aa-sig-num">{{ a.drift_count_24h }}</span></button>
            </div>
          </td>
          <td class="aa-dim">{{ timeAgo(a.last_active_at) }}</td>
          <td style="text-align: right;" @click.stop>
            <div class="aa-row-actions">
              <button class="aa-btn aa-btn-sm aa-btn-cyan" @click="accessDid = a.did" title="Manage roles & spend limits (IRONKEY)">Access</button>
              <!-- Phase 6: Coordinated suspend / reinstate per-row -->
              <button
                v-if="a.status !== 'suspended' && a.status !== 'revoked'"
                class="aa-btn aa-btn-sm aa-btn-warn"
                @click="suspendSingleAgent(a)"
                title="Coordinated suspend (registry + mTLS + TEG)"
              >{{ t('adminAgentsView.filters.suspended') }}</button>
              <button
                v-if="a.status === 'suspended'"
                class="aa-btn aa-btn-sm aa-btn-cyan"
                @click="reinstateSingleAgent(a)"
                title="Coordinated reinstate"
              >Reinstate</button>
              <button class="aa-btn aa-btn-sm" @click="openTransfer(a)" title="Transfer ownership to another developer">{{ t('adminAgentsView.rowActions.transfer') }}</button>
              <button v-if="a.status !== 'revoked'" class="aa-btn aa-btn-sm" @click="openRotate(a)" title="Rotate client_secret">{{ t('adminAgentsView.rowActions.rotate') }}</button>
              <button v-if="!a.mtls_enabled && a.status === 'active'" class="aa-btn aa-btn-sm" @click="forceMtls(a)" title="Force mTLS enrollment">mTLS</button>
            </div>
          </td>
        </tr>
        <!-- §FESUITE (2026-10-04): "none" only after a read that answered; the error banner says a failed one -->
        <tr v-if="agents.length === 0 && agentsRead"><td colspan="12" class="aa-empty">No agents match the current filter.</td></tr>
      </tbody>
    </table>

    <div class="aa-pagination">
      <button class="aa-btn aa-btn-ghost" :disabled="offset === 0" @click="prevPage">{{ t('adminAgentsView.pagination.prev') }}</button>
      <span class="aa-dim">Showing {{ offset + 1 }}–{{ Math.min(offset + limit, total) }} of {{ total }}</span>
      <button class="aa-btn aa-btn-ghost" :disabled="offset + limit >= total" @click="nextPage">{{ t('adminAgentsView.pagination.next') }}</button>
    </div>
  </div>

  <!-- ════ Detail Drawer ════════════════════════════════════════════ -->
  <Teleport to="body">
    <div v-if="drawerOpen" class="aa-drawer-overlay" @click.self="closeDrawer">
      <aside class="aa-drawer">
        <header class="aa-drawer-header">
          <div>
            <div class="aa-drawer-label">AGENT · {{ selectedDetail?.enforcement_status || '…' }}</div>
            <h2 class="aa-drawer-title">{{ selectedDetail?.name || t('adminAgentsView.unnamed') }}</h2>
            <div class="aa-drawer-sub">
              <code class="aa-mono" @click="copyText(selectedDetail?.did || '')">{{ selectedDetail?.did || '…' }}</code>
            </div>
          </div>
          <button class="aa-drawer-close" @click="closeDrawer">×</button>
        </header>

        <div v-if="drawerLoading" class="aa-center"><div class="aa-spinner"></div></div>

        <template v-else-if="selectedDetail">
          <nav class="aa-drawer-tabs">
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'identity' }" @click="drawerTab = 'identity'">{{ t('adminAgentsView.drawerTabs.identity') }}</button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'ownership' }" @click="drawerTab = 'ownership'">{{ t('adminAgentsView.drawerTabs.ownership') }}</button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'state' }" @click="drawerTab = 'state'">{{ t('adminAgentsView.drawerTabs.state') }}</button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'balances' }" @click="drawerTab = 'balances'">{{ t('adminAgentsView.drawerTabs.balances') }}</button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'stakes' }" @click="drawerTab = 'stakes'">{{ t('adminAgentsView.drawerTabs.stakes') }} <span class="aa-count">{{ selectedDetail.stakes.length }}</span></button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'card' }" @click="drawerTab = 'card'">{{ t('adminAgentsView.drawerTabs.card') }}</button>
            <!-- §pass37 — Option C drawer tabs -->
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'cardSync' }" @click="drawerTab = 'cardSync'">
              Card Sync
              <span v-if="(selectedDetail.drift_count_24h || 0) > 0" class="aa-count aa-count-warn">{{ selectedDetail.drift_count_24h }}</span>
            </button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'mcpAudit' }" @click="drawerTab = 'mcpAudit'" title="Recent MCP tool calls made under this agent's DID">
              MCP Audit
            </button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'signingKeys' }" @click="drawerTab = 'signingKeys'">
              Signing Keys
              <span class="aa-count">{{ selectedDetail.signing_keys?.length || 0 }}</span>
            </button>
            <button class="aa-drawer-tab" :class="{ 'aa-drawer-tab-active': drawerTab === 'federation' }" @click="drawerTab = 'federation'">Federation</button>
          </nav>

          <div class="aa-drawer-body">
            <section v-if="drawerTab === 'identity'" class="aa-tab-pane">
              <dl class="aa-kv">
                <dt>{{ t('adminAgentsView.details.did') }}</dt><dd><code class="aa-mono">{{ selectedDetail.did }}</code></dd>
                <dt>{{ t('adminAgentsView.details.clientId') }}</dt><dd><code class="aa-mono">{{ selectedDetail.client_id }}</code></dd>
                <dt>{{ t('adminAgentsView.details.spiffeId') }}</dt><dd><code class="aa-mono">{{ selectedDetail.spiffe_id || '—' }}</code></dd>
                <dt>{{ t('adminAgentsView.details.mtlsEnabled') }}</dt><dd>{{ selectedDetail.mtls_enabled ? '✓ enabled' : '—' }}</dd>
                <dt>{{ t('adminAgentsView.details.mtlsEnrolledAt') }}</dt><dd>{{ selectedDetail.mtls_enrolled_at ? shortDate(selectedDetail.mtls_enrolled_at) : '—' }}</dd>
                <dt>{{ t('adminAgentsView.details.created') }}</dt><dd>{{ shortDate(selectedDetail.created_at) }} ({{ timeAgo(selectedDetail.created_at) }})</dd>
                <dt>{{ t('adminAgentsView.details.lastActive') }}</dt><dd>{{ timeAgo(selectedDetail.last_active_at) }}</dd>
                <dt>{{ t('adminAgentsView.details.location') }}</dt><dd>{{ selectedDetail.location_label || '—' }}</dd>
              </dl>
            </section>

            <section v-else-if="drawerTab === 'ownership'" class="aa-tab-pane">
              <dl class="aa-kv">
                <dt>{{ t('adminAgentsView.details.creatorDeveloper') }}</dt>
                <dd>
                  <span :class="{ 'aa-owner-deleted': selectedDetail.creator_developer_deleted }">
                    #{{ selectedDetail.creator_developer_id }} · {{ selectedDetail.creator_developer_email || 'unknown email' }}
                  </span>
                  <span v-if="selectedDetail.creator_developer_deleted" class="aa-sb aa-sb-orphan" style="margin-left: 8px;">creator deleted</span>
                </dd>
                <dt>{{ t('adminAgentsView.details.organisation') }}</dt><dd>{{ selectedDetail.organization_id || '—' }}</dd>
                <dt>{{ t('adminAgentsView.details.team') }}</dt><dd>{{ selectedDetail.team_id || '—' }}</dd>
              </dl>
            </section>

            <section v-else-if="drawerTab === 'state'" class="aa-tab-pane">
              <dl class="aa-kv">
                <dt>{{ t('adminAgentsView.details.registryStatus') }}</dt><dd><span class="aa-sb" :class="statusBadge(selectedDetail).cls">{{ selectedDetail.status }}</span></dd>
                <dt>{{ t('adminAgentsView.details.enforcementStatus') }}</dt><dd>{{ selectedDetail.enforcement_status }}</dd>
                <dt>{{ t('adminAgentsView.details.enforcementLevel') }}</dt><dd>{{ selectedDetail.enforcement_level }}</dd>
                <dt>{{ t('adminAgentsView.details.offenseCount') }}</dt><dd>{{ selectedDetail.offense_count }}</dd>
                <dt>{{ t('adminAgentsView.details.lastOffense') }}</dt><dd>{{ timeAgo(selectedDetail.last_offense_at) }}</dd>
                <dt>{{ t('adminAgentsView.details.rewardsPausedUntil') }}</dt><dd>{{ selectedDetail.rewards_paused_until ? shortDate(selectedDetail.rewards_paused_until) : '—' }}</dd>
                <dt>{{ t('adminAgentsView.details.reputationBond') }}</dt>
                <dd>{{ fmtNum(selectedDetail.reputation_bond_amount) }} · <em>{{ selectedDetail.reputation_bond_status }}</em></dd>
                <dt>{{ t('adminAgentsView.details.openDisputes') }}</dt>
                <dd>
                  complainant: {{ selectedDetail.open_disputes_as_complainant }} ·
                  defendant: {{ selectedDetail.open_disputes_as_defendant }}
                </dd>
              </dl>
            </section>

            <section v-else-if="drawerTab === 'balances'" class="aa-tab-pane">
              <dl class="aa-kv">
                <dt>{{ t('adminAgentsView.details.liquidBalance') }}</dt><dd class="aa-mono">{{ fmtNum(selectedDetail.liquid_balance) }} {{ localCurrency }}</dd>
                <dt>{{ t('adminAgentsView.details.stakedBalance') }}</dt><dd class="aa-mono">{{ fmtNum(selectedDetail.staked_balance) }} {{ localCurrency }}</dd>
                <dt>{{ t('adminAgentsView.details.stakingTier') }}</dt><dd>{{ selectedDetail.staking_tier || '—' }}</dd>
                <dt>{{ t('adminAgentsView.details.autoCompound') }}</dt><dd>{{ selectedDetail.auto_compound_enabled ? '✓ enabled' : '—' }}</dd>
                <dt>{{ t('adminAgentsView.details.totalRewardsEarned') }}</dt><dd class="aa-mono">{{ fmtNum(selectedDetail.total_rewards_earned || 0) }} {{ localCurrency }}</dd>
                <dt>{{ t('adminAgentsView.details.lastRewardDistribution') }}</dt><dd>{{ timeAgo(selectedDetail.last_reward_distribution) }}</dd>
                <dt>{{ t('adminAgentsView.details.reputationScore') }}</dt><dd><span class="aa-rep" :class="repClass(selectedDetail.reputation_score)">{{ selectedDetail.reputation_score }}</span></dd>
              </dl>
            </section>

            <section v-else-if="drawerTab === 'stakes'" class="aa-tab-pane">
              <div v-if="selectedDetail.stakes.length === 0" class="aa-dim">No locks.</div>
              <table v-else class="aa-sub-table">
                <thead><tr><th>Amount</th><th>Locked</th><th>Unlocked</th><th>Active</th></tr></thead>
                <tbody>
                  <tr v-for="s in selectedDetail.stakes" :key="s.id">
                    <td class="aa-mono">{{ fmtNum(s.amount) }}</td>
                    <td class="aa-dim">{{ shortDate(s.staked_at) }}</td>
                    <td class="aa-dim">{{ s.unstaked_at ? shortDate(s.unstaked_at) : '—' }}</td>
                    <td>{{ s.is_active ? '✓' : '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <section v-else-if="drawerTab === 'card'" class="aa-tab-pane">
              <!-- §pass34 (2026-05-17) — Full card_data + public_key_jwk via JsonViewer.
                   Replaces the prior tab that only showed public_key_jwk; admins now get
                   the entire agent_cards.card_data tree (federation_metadata, supported
                   interfaces, security schemes, flare, extensions, etc.) without writing
                   SQL queries. -->
              <div v-if="selectedDetail.card_data" class="aa-card-section">
                <div class="aa-card-section-head">
                  <span class="aa-card-section-label">agent_cards.card_data</span>
                  <span class="aa-dim">card_id={{ selectedDetail.card_id || '—' }}</span>
                  <span class="aa-dim">updated {{ selectedDetail.card_updated_at ? timeAgo(selectedDetail.card_updated_at) : '—' }}</span>
                  <button class="aa-btn aa-btn-sm" @click="copyJson(selectedDetail.card_data, 'card_data')">
                    {{ copyState === 'card_data' ? 'copied ✓' : 'copy JSON' }}
                  </button>
                </div>
                <JsonViewer :data="selectedDetail.card_data" :default-collapsed="false" :hide-toolbar="true" max-height="420px" />
              </div>
              <div v-else class="aa-dim">No agent_cards row exists for this DID.</div>

              <div v-if="selectedDetail.public_key_jwk" class="aa-card-section" style="margin-top: 18px;">
                <div class="aa-card-section-head">
                  <span class="aa-card-section-label">public_key_jwk</span>
                  <button class="aa-btn aa-btn-sm" @click="copyJson(selectedDetail.public_key_jwk, 'jwk')">
                    {{ copyState === 'jwk' ? 'copied ✓' : 'copy JSON' }}
                  </button>
                </div>
                <pre class="aa-activity-data">{{ JSON.stringify(selectedDetail.public_key_jwk, null, 2) }}</pre>
              </div>
            </section>

            <!-- §pass37 (2026-05-18) — Card Sync tab: Option C pull-sync state,
                 drift events, refresh + flag actions, live side-by-side diff. -->
            <section v-else-if="drawerTab === 'cardSync'" class="aa-tab-pane">
              <div class="aa-cs-grid">
                <div class="aa-cs-card">
                  <div class="aa-cs-card-head">Pull-sync state</div>
                  <dl class="aa-kv">
                    <dt>Last pulled</dt>
                    <dd>
                      <span v-if="selectedDetail.last_pulled_at" :class="`aa-sb aa-sb-pull-${pullState(selectedDetail)}`">
                        {{ pullState(selectedDetail) }}
                      </span>
                      <span v-else class="aa-sb aa-sb-default">never</span>
                      <span v-if="selectedDetail.last_pulled_at" class="aa-dim" style="margin-left:8px;">
                        {{ timeAgo(selectedDetail.last_pulled_at) }} · {{ shortDate(selectedDetail.last_pulled_at) }}
                      </span>
                    </dd>
                    <dt>ETag</dt>
                    <dd><code class="aa-mono">{{ selectedDetail.last_pulled_etag || '—' }}</code></dd>
                    <dt>Source URL</dt>
                    <dd>
                      <code class="aa-mono aa-cs-url"
                            :title="selectedDetail.card_data?.supportedInterfaces?.[0]?.url || ''">
                        {{ selectedDetail.card_data?.supportedInterfaces?.[0]?.url || '—' }}
                      </code>
                    </dd>
                    <dt>24h drift events</dt>
                    <dd>
                      <span :class="(selectedDetail.drift_count_24h || 0) > 0 ? 'aa-text-warn' : 'aa-dim'">
                        {{ selectedDetail.drift_count_24h || 0 }}
                      </span>
                    </dd>
                  </dl>
                </div>

                <div class="aa-cs-card">
                  <div class="aa-cs-card-head">Actions</div>
                  <div class="aa-cs-actions">
                    <button class="aa-btn aa-btn-cyan aa-btn-ic" @click="refreshAgentCard(selectedDetail.did)" :disabled="refreshingCard">
                      <Icon icon="mdi:refresh" class="aa-btn-ic-svg" :class="{ 'aa-spin': refreshingCard }" />
                      <span>{{ refreshingCard ? 'Refreshing…' : 'Refresh now' }}</span>
                    </button>
                    <button class="aa-btn aa-btn-ghost aa-btn-ic" @click="flagDriftForReview(selectedDetail.did)" :disabled="flaggingDrift">
                      <Icon icon="mdi:flag-outline" class="aa-btn-ic-svg" />
                      <span>{{ flaggingDrift ? 'Flagging…' : 'Flag for review' }}</span>
                    </button>
                  </div>
                  <p class="aa-dim aa-cs-note">
                    Refresh bypasses the 6h scheduler. Flag emits a
                    <code>CommanderFlaggedDrift</code> audit event — no state change.
                  </p>
                </div>
              </div>

              <!-- Last drift event (rendered when available) -->
              <div v-if="selectedDetail.last_drift_event" class="aa-card-section" style="margin-top:14px;">
                <div class="aa-card-section-head">
                  <span class="aa-card-section-label">Last drift event</span>
                  <span class="aa-dim">{{ timeAgo(selectedDetail.last_drift_event.timestamp) }}</span>
                </div>
                <div class="aa-cs-drift-fields">
                  <span v-for="f in selectedDetail.last_drift_event.drifted_fields" :key="f"
                        class="aa-pill aa-pill-warn aa-mono">{{ f }}</span>
                  <span v-if="!selectedDetail.last_drift_event.drifted_fields.length" class="aa-dim">no fields</span>
                </div>
              </div>

              <!-- Side-by-side live diff (collapsed by default; loads on click) -->
              <div class="aa-card-section" style="margin-top:14px;">
                <div class="aa-card-section-head">
                  <span class="aa-card-section-label">Live diff (stored vs agent's well-known)</span>
                  <button v-if="!cardSyncDiff && !cardSyncDiffLoading" class="aa-btn aa-btn-sm"
                          @click="loadCardSyncDiff(selectedDetail.did)">load diff</button>
                  <button v-if="cardSyncDiff" class="aa-btn aa-btn-sm aa-btn-ghost"
                          @click="cardSyncDiff = null">collapse</button>
                </div>
                <div v-if="cardSyncDiffLoading" class="aa-dim">Loading diff…</div>
                <div v-else-if="cardSyncDiffError" class="aa-text-warn aa-inline-ic">
                  <Icon icon="mdi:alert-circle" class="aa-inline-ic-svg" />
                  <span>{{ cardSyncDiffError }}</span>
                </div>
                <template v-else-if="cardSyncDiff">
                  <div v-if="cardSyncDiff.unreachable_reason" class="aa-text-warn aa-dim" style="margin-bottom:8px;">
                    Agent unreachable: {{ cardSyncDiff.unreachable_reason }}
                    <span v-if="cardSyncDiff.http_code"> (HTTP {{ cardSyncDiff.http_code }})</span>
                  </div>
                  <div class="aa-diff-grid">
                    <div>
                      <div class="aa-diff-col-title">stored (registry)</div>
                      <pre class="aa-diff-pre">{{ JSON.stringify(cardSyncDiff.stored, null, 2) }}</pre>
                    </div>
                    <div>
                      <div class="aa-diff-col-title">fresh (agent's well-known)</div>
                      <pre class="aa-diff-pre">{{ cardSyncDiff.fresh ? JSON.stringify(cardSyncDiff.fresh, null, 2) : '— (unreachable)' }}</pre>
                    </div>
                  </div>

                  <div v-if="cardSyncDiff.diff" class="aa-diff-summary">
                    <div v-if="Object.keys(cardSyncDiff.diff.changed || {}).length === 0
                              && (cardSyncDiff.diff.added || []).length === 0
                              && (cardSyncDiff.diff.removed || []).length === 0" class="aa-dim">
                      No drift detected — registry and agent agree.
                    </div>
                    <div v-if="Object.keys(cardSyncDiff.diff.changed || {}).length" class="aa-diff-block">
                      <strong>Changed</strong>
                      <ul>
                        <li v-for="(_v, k) in cardSyncDiff.diff.changed" :key="k"><code class="aa-mono">{{ k }}</code></li>
                      </ul>
                    </div>
                    <div v-if="(cardSyncDiff.diff.added || []).length" class="aa-diff-block">
                      <strong>Added by agent</strong>
                      <ul><li v-for="k in cardSyncDiff.diff.added" :key="k"><code class="aa-mono">{{ k }}</code></li></ul>
                    </div>
                    <div v-if="(cardSyncDiff.diff.removed || []).length" class="aa-diff-block">
                      <strong>Removed (will be dropped on next refresh)</strong>
                      <ul><li v-for="k in cardSyncDiff.diff.removed" :key="k"><code class="aa-mono">{{ k }}</code></li></ul>
                    </div>
                  </div>
                </template>
              </div>
            </section>

            <!-- §pass37 (2026-05-18) — Signing Keys tab: Option C Phase 9.a -->
            <section v-else-if="drawerTab === 'signingKeys'" class="aa-tab-pane">
              <div class="aa-cs-card">
                <div class="aa-cs-card-head">
                  Current signing key
                  <button class="aa-btn aa-btn-warn aa-btn-sm aa-cs-rotate aa-btn-ic" @click="openRotateSigKey"
                          :disabled="rotatingSigKey"
                          title="Generate fresh Ed25519 keypair. Private PEM shown ONCE.">
                    <Icon icon="mdi:key" class="aa-btn-ic-svg" />
                    <span>{{ rotatingSigKey ? 'Rotating…' : 'Rotate signing key' }}</span>
                  </button>
                </div>
                <dl v-if="(selectedDetail.signing_keys?.length || 0) > 0" class="aa-kv">
                  <template v-for="k in selectedDetail.signing_keys.filter(k => k.is_current)" :key="k.rotation_seq">
                    <dt>kid</dt><dd><code class="aa-mono">{{ k.kid }}</code></dd>
                    <dt>alg</dt><dd>{{ k.algorithm }}</dd>
                    <dt>created</dt><dd>{{ shortDate(k.created_at) }} ({{ timeAgo(k.created_at) }})</dd>
                    <dt>public_jwk</dt>
                    <dd>
                      <pre class="aa-diff-pre" style="max-height:120px; margin:0;">{{ JSON.stringify(k.public_jwk, null, 2) }}</pre>
                    </dd>
                  </template>
                </dl>
                <p v-else class="aa-dim aa-cs-note">
                  This agent has no signing keys registered. Server-generated keypairs
                  happen at agent create via <code>A2A_DID_JWT_AUTOGEN=true</code>.
                  Click <em>Rotate signing key</em> to generate one now.
                </p>
              </div>

              <div v-if="(selectedDetail.signing_keys?.length || 0) > 0" class="aa-card-section" style="margin-top:14px;">
                <div class="aa-card-section-head">
                  <span class="aa-card-section-label">Rotation history</span>
                </div>
                <table class="aa-sub-table">
                  <thead>
                    <tr>
                      <th>seq</th><th>kid</th><th>alg</th><th>created</th><th>expires</th><th>state</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="k in [...selectedDetail.signing_keys].sort((a,b) => b.rotation_seq - a.rotation_seq)" :key="k.rotation_seq">
                      <td>#{{ k.rotation_seq }}</td>
                      <td class="aa-mono">{{ k.kid.split('#')[0].slice(0, 32) }}…#{{ k.rotation_seq }}</td>
                      <td>{{ k.algorithm }}</td>
                      <td class="aa-dim">{{ shortDate(k.created_at) }}</td>
                      <td class="aa-dim">{{ k.expires_at ? shortDate(k.expires_at) : '—' }}</td>
                      <td>
                        <span v-if="k.is_current" class="aa-sb aa-sb-active">current</span>
                        <span v-else-if="k.expires_at && new Date(k.expires_at).getTime() > Date.now()" class="aa-sb aa-sb-orphan">grace</span>
                        <span v-else class="aa-sb aa-sb-default">expired</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <p class="aa-dim aa-cs-note" style="margin-top:8px;">
                  Old keys remain valid during the 7-day grace window after rotation.
                  Verifiers accept any signature whose kid points to a non-expired row.
                </p>
              </div>
            </section>

            <section v-else-if="drawerTab === 'mcpAudit'" class="aa-tab-pane">
              <!-- 2026-05-24 — §pass68 MCP audit log scoped to this agent's DID.
                   Reads /admin/mcp-audit-log?actor_id={agent_did}. Cross-agent reads
                   never apply here (the panel's subject IS the drawer agent), but the
                   self-watching meta-event still fires because admin ≠ agent. -->
              <McpAuditLogPanel
                scope="admin"
                :actor-id="selectedDetail.did"
                :subject-label="selectedDetail.name || selectedDetail.did"
                :storage-key="'admin-agent-mcp'"
                :poll-interval-ms="30000"
              />
            </section>

            <section v-else-if="drawerTab === 'federation'" class="aa-tab-pane">
              <!-- §pass34 (2026-05-17) — Federation lifecycle view: origin, relay chain,
                   sync timestamps, location, protocol version, mTLS state. -->
              <div v-if="!selectedDetail.card_data" class="aa-dim">No card_data — cannot show federation info.</div>
              <template v-else>
                <dl class="aa-kv">
                  <dt>Origin Registry</dt>
                  <dd>{{ federationInfo.originName || '—' }}
                    <span v-if="federationInfo.isLocal" class="aa-sb aa-sb-native" style="margin-left: 8px;">native here</span>
                    <span v-else class="aa-sb aa-sb-relayed" style="margin-left: 8px;">synced</span>
                  </dd>
                  <dt>Source Registry (SPIFFE)</dt>
                  <dd><code class="aa-mono">{{ federationInfo.sourceRegistry || '—' }}</code></dd>
                  <dt>Most Recent Hop</dt>
                  <dd>
                    <span>{{ federationInfo.lastSyncedFromShort || '—' }}</span>
                    <code v-if="federationInfo.lastSyncedFrom" class="aa-mono" style="display:block; opacity:0.65; margin-top: 2px;">{{ federationInfo.lastSyncedFrom }}</code>
                  </dd>
                  <dt>First Hop</dt>
                  <dd>
                    <span>{{ federationInfo.firstSyncedFromShort || '—' }}</span>
                    <code v-if="federationInfo.firstSyncedFrom" class="aa-mono" style="display:block; opacity:0.65; margin-top: 2px;">{{ federationInfo.firstSyncedFrom }}</code>
                  </dd>
                  <dt>Last Sync</dt>
                  <dd>{{ federationInfo.lastSyncTimestamp ? shortDate(federationInfo.lastSyncTimestamp) : '—' }} <span class="aa-dim" v-if="federationInfo.lastSyncTimestamp">({{ timeAgo(federationInfo.lastSyncTimestamp) }})</span></dd>
                  <dt>First Sync</dt>
                  <dd>{{ federationInfo.firstSyncTimestamp ? shortDate(federationInfo.firstSyncTimestamp) : '—' }}</dd>
                  <dt>A2A Protocol Version</dt>
                  <dd>{{ federationInfo.protocolVersion || '—' }}</dd>
                  <dt>mTLS Enabled (card)</dt>
                  <dd>{{ federationInfo.mtlsEnabled === undefined ? '—' : (federationInfo.mtlsEnabled ? '✓ yes' : 'no') }}</dd>
                  <dt>SPIFFE-ID (card)</dt>
                  <dd><code class="aa-mono">{{ federationInfo.spiffeId || '—' }}</code></dd>
                  <dt>Origin Location</dt>
                  <dd>{{ federationInfo.originLocation || '—' }}</dd>
                </dl>
                <div v-if="federationInfo.fedMetaRaw" class="aa-card-section" style="margin-top: 16px;">
                  <div class="aa-card-section-head">
                    <span class="aa-card-section-label">federation_metadata (raw)</span>
                  </div>
                  <JsonViewer :data="federationInfo.fedMetaRaw" :default-collapsed="true" :hide-toolbar="true" max-height="280px" />
                </div>
              </template>
            </section>
          </div>

          <footer class="aa-drawer-footer">
            <button class="aa-btn aa-btn-sm" @click="openTransfer(selectedDetail)">{{ t('adminAgentsView.drawerActions.transfer') }}</button>
            <button v-if="selectedDetail.status !== 'revoked'" class="aa-btn aa-btn-sm" @click="openRotate(selectedDetail)">{{ t('adminAgentsView.drawerActions.rotate') }}</button>
            <button v-if="!selectedDetail.mtls_enabled && selectedDetail.status === 'active'" class="aa-btn aa-btn-sm" @click="forceMtls(selectedDetail)">{{ t('adminAgentsView.drawerActions.forceMtls') }}</button>
            <!-- §pass37 — Option C drawer actions -->
            <button class="aa-btn aa-btn-sm aa-btn-cyan aa-btn-ic" @click="refreshAgentCard(selectedDetail.did)" :disabled="refreshingCard"
                    title="Force pull-sync now (bypass 6h scheduler)">
              <Icon icon="mdi:refresh" class="aa-btn-ic-svg" :class="{ 'aa-spin': refreshingCard }" />
              <span>{{ refreshingCard ? 'Refreshing…' : 'Refresh Card' }}</span>
            </button>
            <button class="aa-btn aa-btn-sm aa-btn-warn aa-btn-ic" @click="openRotateSigKey" :disabled="rotatingSigKey"
                    title="Rotate EdDSA signing key (Option C Phase 9.a) — private PEM shown ONCE">
              <Icon icon="mdi:key" class="aa-btn-ic-svg" />
              <span>{{ rotatingSigKey ? 'Rotating…' : 'Rotate Sig Key' }}</span>
            </button>
            <a class="aa-btn aa-btn-sm aa-btn-warn aa-btn-ic" :href="`#/admin/enforcement?did=${encodeURIComponent(selectedDetail.did)}`"
               title="Open the enforcement console for this agent (slash / offenses / payouts / suspension)">
              <Icon icon="mdi:gavel" class="aa-btn-ic-svg" />
              <span>Enforcement</span>
            </a>
            <button class="aa-btn aa-btn-sm aa-btn-danger" @click="openDelete(selectedDetail)">{{ t('adminAgentsView.drawerActions.hardDelete') }}</button>
          </footer>
        </template>
      </aside>
    </div>
  </Teleport>

  <!-- ════ Modals ══════════════════════════════════════════════════ -->
  <Teleport to="body">
    <div v-if="showTransferModal && actionTarget" class="aa-overlay" @click.self="showTransferModal = false">
      <div class="aa-modal">
        <p class="aa-modal-title">// TRANSFER AGENT OWNERSHIP</p>
        <p class="aa-modal-sub">Reassigning <strong>{{ actionTarget.name || truncDid(actionTarget.did) }}</strong> from developer #{{ actionTarget.creator_developer_id }}.</p>
        <label class="aa-label">New owner developer ID *</label>
        <input v-model.number="newOwnerId" type="number" class="aa-input" placeholder="e.g. 42" />
        <label class="aa-label">Reason * (min 10 chars)</label>
        <textarea v-model="actionReason" class="aa-input" rows="3" placeholder="Reason for transfer…"></textarea>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showTransferModal = false">Cancel</button>
          <button class="aa-btn aa-btn-cyan" :disabled="!newOwnerId || actionReason.length < 10 || actionLoading" @click="confirmTransfer">
            {{ actionLoading ? 'Transferring…' : 'Transfer' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showRotateModal && actionTarget" class="aa-overlay" @click.self="showRotateModal = false">
      <div class="aa-modal">
        <p class="aa-modal-title">// ROTATE AGENT CREDENTIALS</p>
        <div class="aa-warn-box">
          <p><strong>Current client_secret will stop working immediately.</strong> New secret will be shown ONCE.</p>
        </div>
        <p class="aa-modal-sub">Rotating credentials for <strong>{{ actionTarget.name || truncDid(actionTarget.did) }}</strong>.</p>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showRotateModal = false">Cancel</button>
          <button class="aa-btn aa-btn-warn" :disabled="actionLoading" @click="confirmRotate">
            {{ actionLoading ? 'Rotating…' : 'Rotate Now' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showCredDisplay && rotatedCred" class="aa-overlay">
      <div class="aa-modal">
        <p class="aa-modal-title">// NEW CREDENTIALS ISSUED</p>
        <div class="aa-warn-box" style="border-color: rgba(239,68,68,0.4);">
          <p><strong>THIS SECRET WILL NOT BE SHOWN AGAIN.</strong> Copy it and deliver to the agent owner securely.</p>
        </div>
        <label class="aa-label">client_id</label>
        <div class="aa-cred-display">{{ rotatedCred.client_id }}</div>
        <label class="aa-label">new client_secret</label>
        <div class="aa-cred-display aa-cred-secret">{{ rotatedCred.secret }}</div>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-cyan" @click="copyText(rotatedCred.secret)">Copy secret</button>
          <button class="aa-btn aa-btn-ghost" @click="showCredDisplay = false; rotatedCred = null">I've saved it — Close</button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showDeleteModal && actionTarget" class="aa-overlay" @click.self="showDeleteModal = false">
      <div class="aa-modal">
        <p class="aa-modal-title">// HARD DELETE AGENT</p>
        <div class="aa-warn-box">
          <p><strong>Row will be permanently removed.</strong> Rejected if agent has balance, active locks, or open disputes.</p>
        </div>
        <label class="aa-label">Reason * (min 20 chars)</label>
        <textarea v-model="actionReason" class="aa-input" rows="3" placeholder="Why is this agent being hard-deleted?"></textarea>
        <label class="aa-label">Type the DID to confirm *</label>
        <input v-model="confirmDid" class="aa-input aa-mono" :placeholder="actionTarget.did" />
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showDeleteModal = false">Cancel</button>
          <button class="aa-btn aa-btn-danger"
            :disabled="actionReason.length < 20 || confirmDid !== actionTarget.did || actionLoading"
            @click="confirmHardDelete">
            {{ actionLoading ? 'Deleting…' : 'Hard Delete' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showBulkSuspendModal" class="aa-overlay" @click.self="showBulkSuspendModal = false">
      <div class="aa-modal" style="width: 580px;">
        <p class="aa-modal-title">// COORDINATED SUSPEND</p>
        <p class="aa-modal-sub">
          <span v-if="!softSuspendOnly">
            Suspends across <b>three security levers</b>: registry status flip, IRONHAND mTLS revoke (SPIFFE SVID invalidated), and TEG account suspension. Cryptographic block fully active.
          </span>
          <span v-else style="color: #fbbf24;">
            <b>Soft mode:</b> registry status only. mTLS identity + TEG account stay active.
          </span>
        </p>
        <label class="aa-label">Agent DIDs * (max 50)</label>
        <textarea v-model="bulkDids" class="aa-input aa-mono" rows="6" placeholder="did:theprotocol:… &#10;did:theprotocol:… "></textarea>
        <label class="aa-label">Reason * (min 10 chars)</label>
        <textarea v-model="actionReason" class="aa-input" rows="2" placeholder="Reason for bulk suspension…"></textarea>
        <label class="aa-checkbox" style="display: flex; gap: 8px; align-items: center; margin-top: 8px; font-size: 12px; color: #94a3b8;">
          <input v-model="softSuspendOnly" type="checkbox" />
          <span>Soft suspend (registry only, leave mTLS + TEG active)</span>
        </label>
        <!-- AA3 (audit 2026-05-07): inline validation feedback -->
        <p v-if="bulkValidationError" class="aa-modal-error" role="alert"><Icon name="mdi:alert" /> {{ bulkValidationError }}</p>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showBulkSuspendModal = false">Cancel</button>
          <button class="aa-btn aa-btn-warn"
            :disabled="!bulkDids.trim() || actionReason.length < 10 || actionLoading"
            @click="confirmBulkSuspend">
            {{ actionLoading ? 'Suspending…' : (softSuspendOnly ? 'Soft Suspend' : 'Coordinated Suspend') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showBulkReinstateModal" class="aa-overlay" @click.self="showBulkReinstateModal = false">
      <div class="aa-modal" style="width: 560px;">
        <p class="aa-modal-title">// COORDINATED REINSTATE</p>
        <p class="aa-modal-sub">
          <span v-if="!softReinstateOnly">
            Reinstates across all three levers: registry status active, IRONHAND mTLS <b>re-enrolled</b> (fresh SPIFFE SVID issued), and TEG account reactivated.
          </span>
          <span v-else style="color: #fbbf24;">
            <b>Soft mode:</b> registry status only. mTLS + TEG state unchanged.
          </span>
        </p>
        <label class="aa-label">Agent DIDs * (max 50)</label>
        <textarea v-model="bulkDids" class="aa-input aa-mono" rows="4" placeholder="did:theprotocol:… "></textarea>
        <label class="aa-label">Reason (optional)</label>
        <textarea v-model="actionReason" class="aa-input" rows="2" placeholder="Optional context for the audit log…"></textarea>
        <label class="aa-checkbox" style="display: flex; gap: 8px; align-items: center; margin-top: 8px; font-size: 12px; color: #94a3b8;">
          <input v-model="softReinstateOnly" type="checkbox" />
          <span>Soft reinstate (registry only)</span>
        </label>
        <!-- AA3: inline validation feedback (shared with reinstate modal) -->
        <p v-if="bulkValidationError" class="aa-modal-error" role="alert"><Icon name="mdi:alert" /> {{ bulkValidationError }}</p>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showBulkReinstateModal = false">Cancel</button>
          <button class="aa-btn aa-btn-cyan"
            :disabled="!bulkDids.trim() || actionLoading"
            @click="confirmBulkReinstate">
            {{ actionLoading ? 'Reinstating…' : (softReinstateOnly ? 'Soft Reinstate' : 'Coordinated Reinstate') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- AA-mTLS (audit 2026-05-07): themed force-mTLS confirms -->
  <ConfirmActionModal
    :show="showBulkMtlsModal"
    title="// BULK FORCE mTLS ENROL"
    :message="`Force-enroll mTLS for <strong>${bulkMtlsTargets.length} agent${bulkMtlsTargets.length === 1 ? '' : 's'}</strong>? Each gets a fresh SPIFFE SVID issued from the SPIRE server.`"
    tone="primary"
    confirm-text="Enroll All"
    busy-text="Enrolling…"
    :busy="bulkMtlsBusy"
    @close="showBulkMtlsModal = false; bulkMtlsTargets = []"
    @confirm="executeBulkForceMtls"
  />

  <ConfirmActionModal
    :show="showForceMtlsModal"
    title="// FORCE mTLS ENROL"
    :message="forceMtlsTarget
      ? `Force-enroll mTLS for <strong>${forceMtlsTarget.name || forceMtlsTarget.did.slice(0, 28) + '…'}</strong>? A fresh SPIRE entry will be created and a new SVID issued.`
      : ''"
    tone="primary"
    confirm-text="Enroll"
    busy-text="Enrolling…"
    :busy="forceMtlsBusy"
    @close="showForceMtlsModal = false; forceMtlsTarget = null"
    @confirm="executeForceMtls"
  />

  <!-- §pass37 — Option C: ROTATE SIGNING KEY confirm -->
  <ConfirmActionModal
    :show="showRotateSigKeyModal"
    title="// ROTATE SIGNING KEY"
    :message="selectedDetail
      ? `Generate a fresh Ed25519 keypair for <strong>${selectedDetail.name || selectedDetail.did.slice(0, 28) + '…'}</strong>?<br><br>The current key remains valid for a <strong>7-day grace window</strong>. The new private PEM will be shown ONCE — you must deliver it to the agent operator out-of-band.`
      : ''"
    tone="warn"
    confirm-text="Rotate Now"
    busy-text="Rotating…"
    :busy="rotatingSigKey"
    @close="showRotateSigKeyModal = false"
    @confirm="confirmRotateSigKey"
  />

  <!-- §pass37 — Option C: new private PEM display (shown ONCE) -->
  <Teleport to="body">
    <div v-if="showSigKeyResultModal && rotatedSigKey" class="aa-overlay">
      <div class="aa-modal" style="width: 560px;">
        <p class="aa-modal-title">// NEW SIGNING KEY ISSUED</p>
        <div class="aa-warn-box" style="border-color: rgba(239,68,68,0.4);">
          <p><strong>THIS PRIVATE PEM WILL NOT BE SHOWN AGAIN.</strong>
          Deliver it to the agent operator securely. Old key remains valid until
          <code>{{ rotatedSigKey.old_kid_expires_at ? shortDate(rotatedSigKey.old_kid_expires_at) : 'no prior key' }}</code>.</p>
        </div>
        <label class="aa-label">new kid</label>
        <div class="aa-cred-display">{{ rotatedSigKey.kid }}</div>
        <label class="aa-label">private_pem (PKCS#8)</label>
        <pre class="aa-cred-display aa-cred-secret" style="white-space: pre-wrap; word-break: break-all;">{{ rotatedSigKey.private_pem }}</pre>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-cyan" @click="copyText(rotatedSigKey.private_pem)">Copy PEM</button>
          <button class="aa-btn aa-btn-ghost" @click="showSigKeyResultModal = false; rotatedSigKey = null">I've saved it — Close</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §pass37 — Option C: BULK REFRESH CARDS modal w/ progressive feedback -->
  <Teleport to="body">
    <div v-if="showBulkRefreshModal" class="aa-overlay" @click.self="!bulkRefreshBusy && (showBulkRefreshModal = false)">
      <div class="aa-modal" style="width: 520px;">
        <p class="aa-modal-title">// BULK REFRESH CARDS</p>
        <p class="aa-modal-sub">
          Force-pull <strong>{{ selectedDids.length }} agent{{ selectedDids.length === 1 ? '' : 's' }}</strong>' /.well-known/agent-card.json now.
          Bypasses the 6h scheduler. Unreachable agents return per-row status without breaking the request.
        </p>
        <label class="aa-label">Reason (optional, audit log)</label>
        <textarea v-model="bulkActionNote" class="aa-input" rows="2" placeholder="Context for the audit trail…"></textarea>
        <div v-if="bulkRefreshProgress" class="aa-bulk-progress">
          <div class="aa-bulk-progress-bar">
            <div class="aa-bulk-progress-fill"
                 :style="{ width: bulkRefreshProgress.total > 0 ? ((bulkRefreshProgress.done / bulkRefreshProgress.total * 100) + '%') : '0%' }"></div>
          </div>
          <div class="aa-bulk-progress-text">
            {{ bulkRefreshProgress.done }} / {{ bulkRefreshProgress.total }}
            <span class="aa-text-ok">· {{ bulkRefreshProgress.succeeded }} ok</span>
            <span class="aa-dim">· {{ bulkRefreshProgress.skipped }} skipped</span>
            <span v-if="bulkRefreshProgress.failed > 0" class="aa-text-warn">· {{ bulkRefreshProgress.failed }} failed</span>
          </div>
        </div>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showBulkRefreshModal = false" :disabled="bulkRefreshBusy">Cancel</button>
          <button class="aa-btn aa-btn-cyan aa-btn-ic" :disabled="bulkRefreshBusy" @click="confirmBulkRefresh">
            <Icon icon="mdi:refresh" class="aa-btn-ic-svg" :class="{ 'aa-spin': bulkRefreshBusy }" />
            <span>{{ bulkRefreshBusy ? 'Refreshing…' : `Refresh ${selectedDids.length}` }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §pass37 — Option C: BULK ROTATE SIGNING KEYS modal -->
  <Teleport to="body">
    <div v-if="showBulkRotateSigModal" class="aa-overlay" @click.self="!bulkRotateSigBusy && (showBulkRotateSigModal = false)">
      <div class="aa-modal" style="width: 520px;">
        <p class="aa-modal-title">// BULK ROTATE SIGNING KEYS</p>
        <div class="aa-warn-box">
          <p>
            Generates fresh Ed25519 keypairs for <strong>{{ selectedDids.length }}</strong>
            agent{{ selectedDids.length === 1 ? '' : 's' }}.
            Old keys remain valid for the 7-day grace window.
            <strong>Private PEMs are NOT shown for bulk rotations</strong> —
            audit log records the rotation; deliver new PEMs via the per-agent
            drawer where they're shown once.
          </p>
        </div>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showBulkRotateSigModal = false" :disabled="bulkRotateSigBusy">Cancel</button>
          <button class="aa-btn aa-btn-warn aa-btn-ic" :disabled="bulkRotateSigBusy" @click="confirmBulkRotateSig">
            <Icon icon="mdi:key" class="aa-btn-ic-svg" />
            <span>{{ bulkRotateSigBusy ? 'Rotating…' : `Rotate ${selectedDids.length}` }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §pass37 — Option C: BULK FLAG DRIFT modal -->
  <Teleport to="body">
    <div v-if="showBulkFlagDriftModal" class="aa-overlay" @click.self="!bulkFlagDriftBusy && (showBulkFlagDriftModal = false)">
      <div class="aa-modal" style="width: 520px;">
        <p class="aa-modal-title">// BULK FLAG DRIFT</p>
        <p class="aa-modal-sub">
          Emit a <code>CommanderFlaggedDrift</code> audit event for each of the
          <strong>{{ selectedDids.length }}</strong> selected agent{{ selectedDids.length === 1 ? '' : 's' }}.
          No state change on the card; this records operator concern for follow-up.
        </p>
        <label class="aa-label">Note (optional)</label>
        <textarea v-model="bulkActionNote" class="aa-input" rows="2" placeholder="Why are these agents being flagged?"></textarea>
        <div class="aa-modal-actions">
          <button class="aa-btn aa-btn-ghost" @click="showBulkFlagDriftModal = false" :disabled="bulkFlagDriftBusy">Cancel</button>
          <button class="aa-btn aa-btn-warn aa-btn-ic" :disabled="bulkFlagDriftBusy" @click="confirmBulkFlagDrift">
            <Icon icon="mdi:flag-outline" class="aa-btn-ic-svg" />
            <span>{{ bulkFlagDriftBusy ? 'Flagging…' : `Flag ${selectedDids.length}` }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</div>
    <!-- IRONKEY access modal (admin) -->
    <div v-if="accessDid" style="position:fixed;inset:0;background:rgba(2,6,23,.78);z-index:1000;display:flex;align-items:flex-start;justify-content:center;padding:5vh 1rem;overflow:auto" @click.self="accessDid = null">
      <div style="background:#0b1220;border:1px solid #1e293b;border-radius:14px;max-width:660px;width:100%;padding:1.2rem">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;color:#e2e8f0;font-weight:600">
          <span style="display:flex;flex-direction:column;gap:2px;min-width:0">
            <span>Agent Access (admin)</span>
            <span style="font-size:10px;font-weight:400;color:#64748b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ accessDid }}</span>
          </span>
          <button style="background:none;border:none;color:#94a3b8;font-size:1.5rem;line-height:1;cursor:pointer" @click="accessDid = null">×</button>
        </div>
        <AgentAccessPanel :agent-did="accessDid" mode="admin" />
      </div>
    </div>
</template>

<style scoped>
/* Scaffold matches ad-* from AdminDevelopers.vue but with aa-* prefix.
   CSS below parallels the developer view — see that file for structural notes. */
.aa { padding: 24px 32px 48px; color: var(--nc-text, #e2e8f0); position: relative; min-height: calc(100vh - 48px); }
.aa-ambient { position: absolute; inset: 0; pointer-events: none; overflow: hidden; z-index: 0; }
.aa-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(124, 58, 237, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(124, 58, 237, 0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}
.aa-glow { position: absolute; width: 600px; height: 600px; border-radius: 50%; filter: blur(120px); opacity: 0.15; }
.aa-glow-1 { top: -100px; right: -200px; background: radial-gradient(circle, #7c3aed 0%, transparent 70%); }
.aa-glow-2 { bottom: -200px; left: -200px; background: radial-gradient(circle, #00d2d2 0%, transparent 70%); }
/* AA3 (audit 2026-05-07): inline modal validation banner. */
.aa-modal-error {
  margin-top: 10px;
  padding: 8px 12px;
  font-size: 12px;
  border-radius: 6px;
  background: rgba(239,68,68,0.1);
  border: 1px solid rgba(239,68,68,0.3);
  color: #fca5a5;
}

.aa-hero { position: relative; z-index: 1; margin-bottom: 20px; }
.aa-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em;
  text-transform: uppercase; color: #a855f7;
  padding: 4px 10px; border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 4px; margin-bottom: 10px;
}
.aa-chip-dot { width: 6px; height: 6px; background: #a855f7; border-radius: 50%; box-shadow: 0 0 8px #a855f7; }
.aa-h1 { font-size: 28px; font-weight: 700; margin: 0 0 4px 0; letter-spacing: -0.02em; }
.aa-accent { color: #a855f7; }
.aa-lead { color: #94a3b8; font-size: 13px; margin: 0; }

.aa-stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-bottom: 20px; position: relative; z-index: 1; }
.aa-stat {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-top: 2px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.aa-stat-ok { border-top-color: #22c55e; }
.aa-stat-cyan { border-top-color: var(--nc-primary, #00d2d2); }
.aa-stat-warn { border-top-color: #f59e0b; }
.aa-stat-bad { border-top-color: #ef4444; }
.aa-stat-muted { border-top-color: rgba(148, 163, 184, 0.3); }
.aa-stat-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #64748b; }
.aa-stat-value { font-family: 'IBM Plex Mono', monospace; font-size: 22px; font-weight: 700; color: #e2e8f0; }

.aa-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-bottom: 16px; position: relative; z-index: 1; }
/* a 320 px basis: on a phone the search takes the next line, where with a zero basis its 240 px floor left the chips
   one per line in a ~120 px column (the camera, 2026-10-13) */
.aa-filter-bar { display: flex; gap: 4px; flex-wrap: wrap; flex: 1 1 320px; min-width: 0; align-items: center; }
.aa-fb-btn {
  background: rgba(15, 23, 42, 0.6); color: #94a3b8;
  border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  padding: 6px 10px; cursor: pointer; transition: all 120ms;
}
.aa-fb-btn:hover { border-color: rgba(168, 85, 247, 0.4); color: #e2e8f0; }
.aa-fb-active { background: rgba(168, 85, 247, 0.15); border-color: #a855f7; color: #c084fc; }
.aa-fb-right { margin-left: auto; }
.aa-select {
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px; color: #cbd5e1; padding: 6px 10px; font-size: 11px;
  font-family: 'IBM Plex Mono', monospace;
}
.aa-search-wrap { position: relative; min-width: 240px; flex: 1 1 240px; max-width: 420px; }
.aa-search {
  width: 100%; padding: 6px 26px 6px 10px;
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px; color: #e2e8f0; font-size: 12px;
}
.aa-search:focus { outline: none; border-color: #a855f7; }
.aa-search-clear { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 16px; }

.aa-error { padding: 10px 14px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; color: #fca5a5; margin-bottom: 16px; font-size: 13px; }
.aa-center { display: flex; justify-content: center; align-items: center; padding: 40px; }
.aa-spinner { width: 28px; height: 28px; border: 3px solid rgba(168, 85, 247, 0.2); border-top-color: #a855f7; border-radius: 50%; animation: aa-spin 1s linear infinite; }
@keyframes aa-spin { to { transform: rotate(360deg); } }

/* the table scrolls sideways inside its card when it is wider (it was clipped: beside the sidebar at 1440 px the actions
   column, Access to mTLS, could not be reached, nor most columns on a phone; the camera, 2026-10-13) */
.aa-table-wrap { background: rgba(15, 23, 42, 0.5); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 8px; overflow-x: auto; position: relative; z-index: 1; }
.aa-table { width: 100%; border-collapse: collapse; font-size: 12px; }
/* 8 px a side (was 12): twelve columns beside the sidebar at 1440 px need the room; with the DID chip at 200 px the
   table fits its card and the Actions column shows (the camera, 2026-10-13) */
.aa-table thead th {
  background: rgba(15, 23, 42, 0.8); padding: 10px 8px; text-align: left;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase; color: #64748b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.aa-table tbody td { padding: 10px 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); vertical-align: middle; }
.aa-row { cursor: pointer; transition: background 100ms; }
.aa-row:hover { background: rgba(168, 85, 247, 0.05); }
.aa-name { color: #e2e8f0; font-weight: 500; }
.aa-did {
  cursor: pointer;
  color: #7dd3fc;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.aa-did:hover { color: #bae6fd; }
.aa-col-did { max-width: 220px; }
.aa-col-checkbox { width: 32px; padding: 0 4px !important; text-align: center; }
.aa-col-checkbox input[type="checkbox"] { cursor: pointer; width: 14px; height: 14px; accent-color: #00d2d2; }

/* Phase 6.5: bulk-actions toolbar */
.aa-bulk-toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 10px 14px;
  margin-bottom: 8px;
  background: linear-gradient(90deg, rgba(0, 210, 210, 0.12), rgba(0, 210, 210, 0.04));
  border: 1px solid rgba(0, 210, 210, 0.35);
  border-radius: 6px;
  font-size: 12px;
  color: #cbd5e1;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}
.aa-bulk-count strong { color: #00d2d2; font-weight: 600; }
.aa-bulk-actions { display: flex; gap: 8px; align-items: center; }

/* Selected row highlight */
.aa-row.aa-row-selected {
  background: rgba(0, 210, 210, 0.06);
  outline: 1px solid rgba(0, 210, 210, 0.18);
}

/* Skeleton rows during loading */
.aa-row-skeleton { cursor: default; }
.aa-row-skeleton td { padding: 12px 8px; }
.aa-skeleton-row {
  height: 16px;
  border-radius: 3px;
  background: linear-gradient(90deg,
    rgba(255,255,255,0.04) 0%,
    rgba(255,255,255,0.08) 50%,
    rgba(255,255,255,0.04) 100%);
  background-size: 200% 100%;
  animation: aa-shimmer 1.4s ease-in-out infinite;
}
@keyframes aa-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.aa-num { text-align: right; font-variant-numeric: tabular-nums; color: #cbd5e1; font-family: 'IBM Plex Mono', monospace; }
.aa-dim { color: #7d8aa0; font-size: 11px; }  /* §FESUITE: 5.3:1 on the table (#64748b was 3.9:1, 40 cells) */
.aa-owner { color: #94a3b8; font-size: 11px; }
.aa-owner-deleted { color: #f87171; text-decoration: line-through; }
.aa-mono { font-family: 'IBM Plex Mono', monospace; font-size: 11px; cursor: pointer; }

.aa-sb { display: inline-block; padding: 2px 8px; border-radius: 4px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
.aa-sb-active { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
.aa-sb-suspended { background: rgba(251, 146, 60, 0.15); color: #fb923c; border: 1px solid rgba(251, 146, 60, 0.3); }
.aa-sb-revoked { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.aa-sb-orphan { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.aa-sb-default { background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); }

.aa-rep { padding: 1px 6px; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600; }
.aa-rep-high { background: rgba(34, 197, 94, 0.15); color: #4ade80; }
.aa-rep-med { background: rgba(0, 210, 210, 0.15); color: #00d2d2; }
.aa-rep-low { background: rgba(245, 158, 11, 0.15); color: #fbbf24; }
.aa-rep-none { background: rgba(148, 163, 184, 0.1); color: #64748b; }

.aa-icon-on { color: #22c55e; }
.aa-icon-off { color: #475569; }

.aa-row-actions { display: flex; gap: 4px; justify-content: flex-end; flex-wrap: wrap; }
.aa-btn {
  background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1; padding: 6px 12px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; cursor: pointer;
  transition: all 120ms;
}
.aa-btn:hover:not(:disabled) { border-color: #a855f7; color: #c084fc; }
.aa-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.aa-btn-sm { padding: 4px 8px; font-size: 10px; }
.aa-btn-ghost { background: transparent; }
.aa-btn-warn { background: rgba(251, 146, 60, 0.1); border-color: rgba(251, 146, 60, 0.3); color: #fb923c; }
.aa-btn-danger { background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: #f87171; }
.aa-btn-cyan { background: rgba(0, 210, 210, 0.1); border-color: rgba(0, 210, 210, 0.3); color: var(--nc-primary, #00d2d2); }

.aa-empty { text-align: center; padding: 40px; color: #64748b; }
.aa-pagination { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-top: 1px solid rgba(255, 255, 255, 0.05); background: rgba(15, 23, 42, 0.4); }

/* Drawer */
.aa-drawer-overlay { position: fixed; top: 48px; right: 0; bottom: 0; left: 0; background: rgba(0, 0, 0, 0.5); backdrop-filter: blur(2px); z-index: 999; display: flex; justify-content: flex-end; }
.aa-drawer { width: 720px; max-width: 100vw; height: 100%; background: #0f172a; border-left: 1px solid rgba(168, 85, 247, 0.2); box-shadow: -20px 0 40px rgba(0, 0, 0, 0.5); display: flex; flex-direction: column; overflow: hidden; }
.aa-drawer-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 18px 20px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
.aa-drawer-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #a855f7; letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 4px; }
.aa-drawer-title { font-size: 20px; font-weight: 700; margin: 0 0 4px 0; color: #e2e8f0; }
.aa-drawer-sub { font-size: 11px; }
.aa-drawer-close { background: transparent; border: 1px solid rgba(255, 255, 255, 0.1); color: #94a3b8; width: 32px; height: 32px; border-radius: 4px; font-size: 18px; cursor: pointer; }
.aa-drawer-tabs { display: flex; gap: 2px; padding: 0 20px; background: rgba(15, 23, 42, 0.6); border-bottom: 1px solid rgba(255, 255, 255, 0.08); overflow-x: auto; }
.aa-drawer-tab { background: transparent; border: none; color: #94a3b8; padding: 10px 12px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.aa-drawer-tab:hover { color: #e2e8f0; }
.aa-drawer-tab-active { color: #c084fc; border-bottom-color: #a855f7; }
.aa-count { background: rgba(255,255,255,0.08); padding: 1px 6px; border-radius: 8px; font-size: 9px; margin-left: 4px; }
.aa-drawer-body { flex: 1; overflow-y: auto; padding: 18px 20px; }
.aa-tab-pane { font-size: 13px; }
.aa-kv { display: grid; grid-template-columns: 170px 1fr; gap: 8px 16px; }
.aa-kv dt { color: #64748b; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; }
.aa-kv dd { color: #e2e8f0; margin: 0; }
.aa-sub-table { width: 100%; font-size: 11px; border-collapse: collapse; }
.aa-sub-table th { text-align: left; padding: 6px 8px; color: #64748b; font-size: 10px; text-transform: uppercase; }
.aa-sub-table td { padding: 6px 8px; border-top: 1px solid rgba(255, 255, 255, 0.04); }
.aa-activity-data { background: rgba(0, 0, 0, 0.3); padding: 10px; border-radius: 4px; font-size: 10px; color: #94a3b8; overflow-x: auto; }
.aa-drawer-footer { display: flex; gap: 8px; padding: 12px 20px; border-top: 1px solid rgba(255, 255, 255, 0.08); background: rgba(15, 23, 42, 0.6); flex-wrap: wrap; }

/* Modals */
.aa-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); display: flex; justify-content: center; align-items: center; z-index: 1000; }
.aa-modal { width: 460px; max-width: 92vw; background: #0f172a; border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 8px; padding: 20px; }
.aa-modal-title { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #c084fc; letter-spacing: 0.1em; margin: 0 0 10px 0; }
.aa-modal-sub { color: #94a3b8; font-size: 13px; margin: 0 0 14px 0; }
.aa-label { display: block; color: #cbd5e1; font-size: 11px; font-family: 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: 0.08em; margin: 10px 0 4px 0; }
.aa-input {
  width: 100%; background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 4px;
  color: #e2e8f0; padding: 8px 10px; font-size: 12px; font-family: inherit; resize: vertical; box-sizing: border-box;
}
.aa-input:focus { outline: none; border-color: #a855f7; }
.aa-warn-box { background: rgba(251, 146, 60, 0.1); border: 1px solid rgba(251, 146, 60, 0.3); border-radius: 4px; padding: 10px 12px; margin-bottom: 12px; color: #fdba74; font-size: 12px; }
.aa-cred-display { background: rgba(0, 0, 0, 0.5); border: 1px solid rgba(168, 85, 247, 0.3); border-radius: 4px; padding: 10px 12px; color: #4ade80; font-family: 'IBM Plex Mono', monospace; font-size: 12px; word-break: break-all; margin-bottom: 8px; }
.aa-cred-secret { color: #22c55e; }
.aa-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }

/* §pass34 (2026-05-17) — Card Data + Federation tabs */
.aa-card-section {
  background: rgba(15, 12, 28, 0.45);
  border: 1px solid rgba(168, 85, 247, 0.22);
  border-radius: 6px;
  padding: 10px 12px;
}
.aa-card-section-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.aa-card-section-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(168, 85, 247, 0.95);
  flex: 1;
}
.aa-sb-native {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.3);
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.aa-sb-relayed {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.3);
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.06em;
}

/* ─────────────────────────────────────────────────────────────────────
   §pass37 (2026-05-18) — Option C integration into AdminAgents:
     - status strip
     - compound Signals column
     - "More ▾" bulk dropdown
     - Card Sync + Signing Keys drawer tabs
     - row flash after refresh
     - bulk-refresh progress bar
   ───────────────────────────────────────────────────────────────────── */

/* Status strip above filter toolbar — only shows when drift / never-pulled > 0 */
.aa-strip {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 14px;
  margin-bottom: 8px;
  background: linear-gradient(90deg, rgba(0, 210, 210, 0.08), rgba(168, 85, 247, 0.04));
  border: 1px solid rgba(0, 210, 210, 0.18);
  border-radius: 6px;
  font-size: 11px;
  color: #cbd5e1;
}
/* .aa-strip-ico definition lives in the §pass37b Icon block below — kept here
   for visual sequencing of the toolbar. */
.aa-strip-sep { color: #475569; }
.aa-strip-link {
  background: transparent;
  border: none;
  color: var(--nc-primary, #00d2d2);
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  padding: 0 2px;
  margin-left: 4px;
}
.aa-strip-link:hover { text-decoration: underline; }

/* Compound Signals column */
.aa-col-signals { min-width: 130px; max-width: 180px; }
.aa-signals {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  flex-wrap: nowrap;
}
.aa-sig {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #475569;
  padding: 3px 5px;
  border-radius: 4px;
  cursor: pointer;
  transition: transform 80ms ease, background 120ms;
  line-height: 1;
  min-width: 22px;
  text-align: center;
  /* font-size drives the inner SVG size via Icon.vue's `1em` rule.
     Was set to 0 in §pass37b — that collapsed every icon to 0×0
     (cause of the "empty boxes" bug — Commander 2026-05-18). */
  font-size: 13px;
}
.aa-sig:hover { transform: translateY(-1px); background: rgba(168, 85, 247, 0.08); }
.aa-sig-off { opacity: 0.35; }
.aa-sig-on { color: #4ade80; border-color: rgba(74, 222, 128, 0.35); }
.aa-sig-mtls.aa-sig-on { color: #22c55e; background: rgba(34, 197, 94, 0.08); }
.aa-sig-jws.aa-sig-on { color: #38bdf8; border-color: rgba(56, 189, 248, 0.35); background: rgba(56, 189, 248, 0.06); }
.aa-sig-pull-fresh { color: #4ade80; border-color: rgba(74, 222, 128, 0.35); background: rgba(74, 222, 128, 0.06); }
.aa-sig-pull-stale { color: #facc15; border-color: rgba(250, 204, 21, 0.35); background: rgba(250, 204, 21, 0.06); }
.aa-sig-pull-never { color: #64748b; border-color: rgba(100, 116, 139, 0.3); }
.aa-sig-drift {
  color: #fbbf24;
  border-color: rgba(251, 191, 36, 0.45);
  background: rgba(251, 191, 36, 0.08);
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px 2px 4px;
}
.aa-sig-num {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0;
}

/* Row flash on post-refresh */
.aa-row-flash {
  animation: aa-flash 1.4s ease-out;
}
@keyframes aa-flash {
  0%   { background: rgba(0, 210, 210, 0.32); }
  40%  { background: rgba(0, 210, 210, 0.18); }
  100% { background: transparent; }
}

/* Pull/Refresh-specific button accent */
.aa-btn-pull {
  background: rgba(56, 189, 248, 0.1);
  border-color: rgba(56, 189, 248, 0.3);
  color: #7dd3fc;
}
.aa-btn-pull:hover:not(:disabled) {
  background: rgba(56, 189, 248, 0.18);
  border-color: rgba(56, 189, 248, 0.5);
  color: #bae6fd;
}

/* More ▾ dropdown */
.aa-more-wrap { position: relative; }
.aa-more-btn {
  background: rgba(15, 23, 42, 0.8);
  border-color: rgba(168, 85, 247, 0.3);
  color: #c084fc;
}
.aa-more-btn:hover:not(:disabled) {
  background: rgba(168, 85, 247, 0.12);
}
.aa-more-open {
  background: rgba(168, 85, 247, 0.18);
}
.aa-more-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 240px;
  background: #0f172a;
  border: 1px solid rgba(168, 85, 247, 0.35);
  border-radius: 6px;
  padding: 4px;
  z-index: 50;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.aa-more-item {
  background: transparent;
  border: 1px solid transparent;
  color: #cbd5e1;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  padding: 7px 10px;
  text-align: left;
  cursor: pointer;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.aa-more-item:hover {
  background: rgba(168, 85, 247, 0.1);
  color: #e2e8f0;
}
.aa-more-ico { font-size: 12px; opacity: 0.85; width: 16px; text-align: center; }
.aa-more-sep {
  height: 1px;
  background: rgba(168, 85, 247, 0.2);
  margin: 4px 2px;
}

/* Card Sync drawer tab */
.aa-cs-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 12px;
}
.aa-cs-card {
  background: rgba(15, 12, 28, 0.5);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 6px;
  padding: 12px;
}
.aa-cs-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: #7dd3fc;
  margin-bottom: 10px;
}
.aa-cs-rotate {
  margin-left: auto;
}
.aa-cs-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.aa-cs-note {
  font-size: 11px;
  margin: 10px 0 0;
  color: #64748b;
}
.aa-cs-note code {
  background: rgba(56, 189, 248, 0.1);
  padding: 0.05rem 0.35rem;
  border-radius: 3px;
}
.aa-cs-url {
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.aa-cs-drift-fields {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.aa-pill {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
  border: 1px solid;
}
.aa-pill-warn {
  background: rgba(251, 191, 36, 0.1);
  color: #fbbf24;
  border-color: rgba(251, 191, 36, 0.3);
}

/* Live diff (side-by-side) */
.aa-diff-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.aa-diff-col-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
}
.aa-diff-pre {
  background: rgba(0, 0, 0, 0.4);
  padding: 8px 10px;
  border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10.5px;
  color: #cbd5e1;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  border: 1px solid rgba(255, 255, 255, 0.05);
}
.aa-diff-summary {
  margin-top: 10px;
  padding: 8px 10px;
  background: rgba(15, 23, 42, 0.4);
  border-radius: 4px;
  font-size: 11px;
}
.aa-diff-block { margin-bottom: 6px; }
.aa-diff-block strong { color: #cbd5e1; }
.aa-diff-block ul { margin: 4px 0; padding-left: 18px; }
.aa-diff-block li { margin: 2px 0; }

/* Signing Keys tab pulls from existing .aa-sub-table style */
.aa-text-ok { color: #4ade80; }
.aa-text-warn { color: #facc15; }

/* Pull-state badge inside Card Sync (header) */
.aa-sb-pull-fresh { background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.3); }
.aa-sb-pull-stale { background: rgba(250, 204, 21, 0.15); color: #facc15; border: 1px solid rgba(250, 204, 21, 0.3); }
.aa-sb-pull-never { background: rgba(100, 116, 139, 0.15); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.3); }

/* Drawer tab count — warn flavour for non-zero drift */
.aa-count-warn {
  background: rgba(251, 191, 36, 0.18) !important;
  color: #fbbf24 !important;
}

/* Bulk-refresh progress bar */
.aa-bulk-progress {
  margin-top: 10px;
  padding: 10px;
  background: rgba(15, 23, 42, 0.6);
  border-radius: 4px;
  border: 1px solid rgba(56, 189, 248, 0.2);
}
.aa-bulk-progress-bar {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 6px;
}
.aa-bulk-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #38bdf8, #00d2d2);
  transition: width 200ms ease;
}
.aa-bulk-progress-text {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: #cbd5e1;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

/* Modal error reuse */
.aa-modal-error {
  margin: 8px 0 0;
  padding: 6px 10px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 4px;
  color: #fca5a5;
  font-size: 12px;
}

/* §pass37b (2026-05-18) — Icon-component conversions (removed cringe emojis).
   Icon.vue sizes BOTH the wrapper <span> AND the inner <svg> via `1em`,
   driven by font-size. Setting width/height on the wrapper alone leaves the
   inner SVG at whatever the inherited font-size is — and `font-size: 0`
   collapses everything to a zero-size box. Always size icons via FONT-SIZE
   on the wrapper class. (Bug caught 2026-05-18 — "empty boxes" report.) */

/* Generic button-with-icon (icon + label side-by-side). */
.aa-btn-ic {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  line-height: 1;
}
.aa-btn-ic-svg {
  font-size: 14px;
  flex: 0 0 1em;
}
.aa-more-chev {
  font-size: 13px;
  opacity: 0.8;
  transition: transform 120ms;
}
.aa-more-open .aa-more-chev { transform: rotate(180deg); }

/* Spin animation for the refresh icon during in-flight requests */
@keyframes aa-spin-anim {
  to { transform: rotate(360deg); }
}
.aa-spin { animation: aa-spin-anim 0.8s linear infinite; }

/* Filter chip with icon */
.aa-fb-icon {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.aa-fb-ic {
  font-size: 13px;
  flex: 0 0 1em;
  opacity: 0.85;
}

/* Status strip icon — replaces literal "ℹ" glyph */
.aa-strip-ico {
  font-size: 14px;
  flex: 0 0 1em;
  color: var(--nc-primary, #00d2d2);
  opacity: 0.85;
}

/* Inline icons (e.g. error messages with leading alert glyph) */
.aa-inline-ic {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.aa-inline-ic-svg {
  font-size: 14px;
  flex: 0 0 1em;
}

/* Signal-pill icons — sized via the parent .aa-sig font-size: 13px. */
.aa-sig-ic {
  font-size: inherit;
  flex: 0 0 1em;
  display: inline-flex;
  vertical-align: middle;
}
.aa-sig {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 6px;
}
.aa-sig-drift {
  gap: 3px;
  padding-right: 7px;
}
.aa-sig-num {
  font-size: 10px;
  line-height: 1;
}

/* More menu icon — slightly larger for legibility in the dropdown */
.aa-more-ico {
  font-size: 14px;
  flex: 0 0 1em;
  opacity: 0.85;
}

/* Click-outside helper — close menu when clicking elsewhere */
</style>
