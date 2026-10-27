<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { safeExternalUrl } from '@/utils/safeUrl'
import { useRoute } from 'vue-router'
import { apiClient } from '@/services/api/client'
import { useUIStore } from '@/stores/ui'

// useRoute MUST be called at top-level script setup (not inside async
// callbacks) — Vue 3's composition API can't resolve injection past awaits.
// 2026-05-08: this import + top-level call replaces an earlier broken
// pattern where useRoute() was called inside onMounted's async body, which
// returned undefined and crashed AdminDevelopers on every visit.
const route = useRoute()
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import DevQuotaModal from '@/components/admin/DevQuotaModal.vue'
import FundingRequestsPanel from '@/components/admin/FundingRequestsPanel.vue'
import McpAuditLogPanel from '@/components/admin/McpAuditLogPanel.vue'
import { useLogger } from '@/composables/useLogger'
import { useI18n } from '@/composables/useI18n'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const { t } = useI18n()
const log = useLogger('AdminDevelopers')
const uiStore = useUIStore()

// Build #5 (2026-05-07): page-level tab between Developers list + Funding Requests triage.
type PageTab = 'developers' | 'funding'
const pageTab = ref<PageTab>('developers')

// ── Types ───────────────────────────────────────────────────
interface Developer {
  id: number
  name: string
  email: string
  is_verified: boolean
  is_admin: boolean
  two_fa_enabled: boolean
  is_suspended: boolean
  is_federation_operator: boolean
  federation_operator_status: string | null
  must_change_password: boolean
  agent_count: number
  last_login_at: string | null
  created_at: string
  deleted_at: string | null
  suspended_at: string | null
  suspended_reason: string | null
  // Fix 1 (2026-04-20): granular admin flags
  admin_treasury: boolean
  admin_support: boolean
  admin_enforcement: boolean
  admin_federation: boolean
  admin_platform: boolean
}

interface DeveloperDetail extends Developer {
  display_name: string | null
  bio: string | null
  avatar_url: string | null
  website_url: string | null
  github_url: string | null
  twitter_handle: string | null
  company: string | null
  timezone: string | null
  profile_visibility: string | null
  latitude: number | null
  longitude: number | null
  location_label: string | null
  agents: Array<{
    did: string
    name: string | null
    status: string
    enforcement_status: string | null
    created_at: string
    last_active_at: string | null
  }>
  api_keys: Array<{
    id: number
    key_prefix: string
    description: string | null
    is_active: boolean
    created_at: string
    last_used_at: string | null
  }>
  organizations: Array<{
    organization_id: string
    organization_name: string
    role: string
  }>
  operator_application_id: string | null
}

type StatusFilter = 'all' | 'verified' | 'unverified' | 'admins' | 'operators' | 'suspended' | 'deleted'

// ── State ───────────────────────────────────────────────────
const developers = ref<Developer[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const devsRead = ref(false)
const statusFilter = ref<StatusFilter>('all')
const has2FA = ref<boolean | null>(null)
const search = ref('')
const searchDebounce = ref<number | null>(null)
const limit = ref(50)
const offset = ref(0)
const showEmails = ref(false)

// Drawer state
const drawerOpen = ref(false)
const drawerTab = ref<'profile' | 'auth' | 'roles' | 'permissions' | 'agents' | 'api_keys' | 'activity' | 'mcpAudit' | 'operator'>('profile')
const selectedDetail = ref<DeveloperDetail | null>(null)
const drawerLoading = ref(false)
const activityEvents = ref<any[]>([])
const activityLoading = ref(false)

// Permissions tab (Fix 1)
interface FlagSet {
  admin_treasury: boolean
  admin_support: boolean
  admin_enforcement: boolean
  admin_federation: boolean
  admin_platform: boolean
}
const flagDraft = ref<FlagSet>({
  admin_treasury: false,
  admin_support: false,
  admin_enforcement: false,
  admin_federation: false,
  admin_platform: false,
})
const flagsSaving = ref(false)

function seedFlagsFromDetail() {
  if (!selectedDetail.value) return
  flagDraft.value = {
    admin_treasury: !!selectedDetail.value.admin_treasury,
    admin_support: !!selectedDetail.value.admin_support,
    admin_enforcement: !!selectedDetail.value.admin_enforcement,
    admin_federation: !!selectedDetail.value.admin_federation,
    admin_platform: !!selectedDetail.value.admin_platform,
  }
}

const flagsDirty = computed(() => {
  if (!selectedDetail.value) return false
  const keys: (keyof FlagSet)[] = [
    'admin_treasury', 'admin_support', 'admin_enforcement', 'admin_federation', 'admin_platform',
  ]
  return keys.some(k => !!selectedDetail.value?.[k] !== !!flagDraft.value[k])
})

async function saveFlags() {
  if (!selectedDetail.value || flagsSaving.value) return
  flagsSaving.value = true
  try {
    const res = await apiClient.put(
      `/admin/developers/${selectedDetail.value.id}/admin-flags`,
      { ...flagDraft.value }
    )
    // Merge back into selectedDetail
    selectedDetail.value = { ...selectedDetail.value, ...res.data } as DeveloperDetail
    uiStore.showSuccess?.('Permissions Saved', 'Admin flags updated.')
    await loadDevelopers()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    flagsSaving.value = false
  }
}

function resetFlags() {
  seedFlagsFromDetail()
}

// Action modals
const showSuspendModal = ref(false)
const showResetModal = ref(false)
const showDisable2FAModal = ref(false)
const showRevokeKeysModal = ref(false)
const showDeleteModal = ref(false)
const showGiftProvisioningModal = ref(false)
const giftMonths = ref(1)
// §pass66.11 — Grant Flare Tier modal
const showGrantFlareModal = ref(false)
const grantFlareTier = ref<string>('shadow_chancellor')
const actionTarget = ref<Developer | null>(null)
const actionReason = ref('')
const confirmEmail = ref('')
const actionLoading = ref(false)
// AD2/AD3/AD4 (audit 2026-05-07): inline validation feedback for the action
// modals. Was: silent return on missing reason / wrong email confirmation.
const actionValidationError = ref('')

// Phase 6: Coordinated Suspension cascade preview
const cascadeAgents = ref<Array<{ did: string; name: string | null; status: string; mtls_enabled: boolean }>>([])
const cascadeAgentCount = ref(0)
const cascadeLoading = ref(false)

// §pass66.4 (2026-05-23) — Federation shadow filter.
// `crud_peer_registry.upsert_agent_cards_from_peer` creates placeholder
// developer rows whenever the receiver doesn't have a local developer_id
// matching a federated agent card's owner. Purpose is purely structural
// (satisfy NOT NULL FK on `agent_cards.developer_id`); these rows have:
//   name  = "fed:registry-<peer>:dev-<N>"
//   email = "federated-<N>@<peer>.federation"
// They are never real users (hashed_password = "FEDERATED_ACCOUNT_NO_LOGIN",
// can never log in). Without filtering they pollute the admin UI:
// qatest16 had 22 dev rows of which 21 were shadows (95% noise).
//
// Conservative two-signal check: both name prefix AND email TLD must match.
// Real users can't trip this — `.federation` is not a real DNS TLD and
// `fed:registry-` is namespaced by the federation_sync code path.
// Backend fix (proper schema column) is deferred — Commander will revisit.
function isFederationShadow(dev: { name?: string | null; email?: string | null }): boolean {
  return (
    (dev.name || '').startsWith('fed:registry-') &&
    (dev.email || '').endsWith('.federation')
  )
}

// Filtered list used by EVERYTHING in the template (table rows, KPIs, etc.).
// Page-level `developers.value` is the raw API response; `visibleDevelopers`
// is the human-facing view with shadows hidden. Single source of truth.
const visibleDevelopers = computed(() =>
  developers.value.filter(d => !isFederationShadow(d))
)
const hiddenShadowCount = computed(() =>
  developers.value.length - visibleDevelopers.value.length
)

// KPIs
const kpis = computed(() => {
  const list = visibleDevelopers.value
  const verified = list.filter(d => d.is_verified).length
  const twofa = list.filter(d => d.two_fa_enabled).length
  const admins = list.filter(d => d.is_admin).length
  const operators = list.filter(d => d.is_federation_operator).length
  const suspended = list.filter(d => d.is_suspended).length
  // `total` reflects the visible (non-shadow) count on the current page.
  // Server-side pagination still uses the raw `total.value` for cursor math.
  return { total: list.length, verified, twofa, admins, operators, suspended }
})

// ── Data Loading ────────────────────────────────────────────
// §2026-06-18 — Forced repaint of the table subtree after every load.
// Symptom (op-london, Commander): the KPI chips + pagination footer ("Showing
// 1–2 of 2") render with the correct count, but the <tbody> rows stay BLANK in
// the user's primary browser — yet render fine in a fresh browser/session and
// in headless probes. Backend/API/build/cache/storage all verified healthy
// (both seeded admins are returned and DO render). Root cause is a browser-side
// compositing/paint glitch: the rows ARE in the DOM (that's why the footer
// counts them) but the browser fails to paint the freshly-populated subtree
// until a manual relayout (zoom/resize). This forces that relayout+repaint
// automatically on every load so the rows ALWAYS paint with zero user action.
// Idempotent, client-only, no network/Δ impact; no-op where document is absent.
function forceTableRepaint() {
  if (typeof document === 'undefined') return
  requestAnimationFrame(() => {
    const el = document.querySelector('.ad-table-wrap') as HTMLElement | null
    if (!el) return
    // display flip = guaranteed reflow + repaint of the stuck subtree
    const prevDisplay = el.style.display
    el.style.display = 'none'
    void el.offsetHeight            // force synchronous reflow
    el.style.display = prevDisplay  // restore (back to stylesheet default)
  })
}

async function loadDevelopers() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, any> = { limit: limit.value, offset: offset.value }
    if (statusFilter.value !== 'all') params.status = statusFilter.value
    if (has2FA.value !== null) params.has_2fa = has2FA.value
    if (search.value) params.search = search.value

    const res = await apiClient.get('/admin/developers', { params })
    developers.value = res.data.developers || []
    total.value = res.data.total || 0
    devsRead.value = true
  } catch (e: any) {
    error.value = e.response?.data?.detail || e.message || 'Failed to load developers'
  } finally {
    loading.value = false
    // Ensure the rows paint even on browsers that drop the freshly-rendered
    // tbody subtree until a relayout. Runs after Vue flushes the DOM.
    nextTick(() => forceTableRepaint())
  }
}

function setStatusFilter(s: StatusFilter) {
  statusFilter.value = s
  offset.value = 0
  loadDevelopers()
}

function toggle2FAFilter() {
  has2FA.value = has2FA.value === true ? null : true
  offset.value = 0
  loadDevelopers()
}

function onSearchInput() {
  if (searchDebounce.value) clearTimeout(searchDebounce.value)
  searchDebounce.value = window.setTimeout(() => {
    offset.value = 0
    loadDevelopers()
  }, 350)
}

function clearSearch() {
  search.value = ''
  offset.value = 0
  loadDevelopers()
}

function nextPage() {
  if (offset.value + limit.value < total.value) {
    offset.value += limit.value
    loadDevelopers()
  }
}

function prevPage() {
  if (offset.value > 0) {
    offset.value = Math.max(0, offset.value - limit.value)
    loadDevelopers()
  }
}

// ── Drawer ──────────────────────────────────────────────────
async function openDrawer(dev: Developer) {
  drawerOpen.value = true
  drawerTab.value = 'profile'
  drawerLoading.value = true
  selectedDetail.value = null
  activityEvents.value = []
  try {
    const res = await apiClient.get(`/admin/developers/${dev.id}`)
    selectedDetail.value = res.data
    seedFlagsFromDetail()
  } catch (e: any) {
    uiStore.showError?.('Error', e.response?.data?.detail || e.message)
    drawerOpen.value = false
  } finally {
    drawerLoading.value = false
  }
}

function closeDrawer() {
  drawerOpen.value = false
  selectedDetail.value = null
}

async function loadActivity() {
  if (!selectedDetail.value || activityLoading.value) return
  activityLoading.value = true
  try {
    const res = await apiClient.get(`/admin/developers/${selectedDetail.value.id}/activity`, { params: { limit: 20 } })
    activityEvents.value = Array.isArray(res.data) ? res.data : (res.data.events || [])
  } catch (e: any) {
    log.warn('Activity load failed:', e.message)
  } finally {
    activityLoading.value = false
  }
}

function switchTab(tab: typeof drawerTab.value) {
  drawerTab.value = tab
  if (tab === 'activity' && activityEvents.value.length === 0) loadActivity()
}

// ── Actions ─────────────────────────────────────────────────
// §pass51 P48 — Bundle quota modal
const showQuotaModal = ref(false)
const quotaTargetDev = ref<Developer | null>(null)
function openQuota(dev: Developer) {
  quotaTargetDev.value = dev
  showQuotaModal.value = true
}
function closeQuota() {
  showQuotaModal.value = false
  quotaTargetDev.value = null
}

async function openSuspend(dev: Developer) {
  actionTarget.value = dev
  actionReason.value = ''
  actionValidationError.value = ''
  cascadeAgents.value = []
  cascadeAgentCount.value = 0
  showSuspendModal.value = true
  // Phase 6: fetch cascade preview so admin sees how many agents will be affected
  cascadeLoading.value = true
  try {
    const res = await apiClient.get(`/admin/agents/by-developer/${dev.id}`, { params: { limit: 10 } })
    cascadeAgents.value = res.data.agents || []
    cascadeAgentCount.value = res.data.total || 0
  } catch (e) {
    cascadeAgentCount.value = 0
    cascadeAgents.value = []
  } finally {
    cascadeLoading.value = false
  }
}

async function confirmSuspend() {
  if (!actionTarget.value) return
  if (actionReason.value.length < 10) {
    actionValidationError.value = `Reason must be at least 10 characters (got ${actionReason.value.length}). Audit trail requires context.`
    return
  }
  actionValidationError.value = ''
  actionLoading.value = true
  try {
    const res = await apiClient.post(`/admin/developers/${actionTarget.value.id}/suspend`, { reason: actionReason.value })
    const cascadeCount = res.data.message?.match(/Cascaded (\d+)/)?.[1] || cascadeAgentCount.value
    const cascadeMsg = cascadeCount && Number(cascadeCount) > 0
      ? ` · ${cascadeCount} owned agents cascade-suspended (mTLS revoked + TEG suspended)`
      : ''
    uiStore.showSuccess?.('Suspended', `${redactEmail(actionTarget.value.email)} suspended.${cascadeMsg}`)
    showSuspendModal.value = false
    await loadDevelopers()
    if (selectedDetail.value?.id === actionTarget.value.id) {
      const res2 = await apiClient.get(`/admin/developers/${actionTarget.value.id}`)
      selectedDetail.value = res2.data
    }
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

// AD1 (audit 2026-05-07): replaced native confirm() with themed ConfirmActionModal.
const showReinstateModal = ref(false)
const reinstateTarget = ref<Developer | null>(null)
const reinstateBusy = ref(false)

function openReinstate(dev: Developer) {
  reinstateTarget.value = dev
  showReinstateModal.value = true
}

async function reinstate(_reasonFromModal: string) {
  const dev = reinstateTarget.value
  if (!dev) return
  reinstateBusy.value = true
  try {
    const res = await apiClient.post(`/admin/developers/${dev.id}/reinstate`)
    const cascadeCount = res.data.message?.match(/Cascaded (\d+)/)?.[1] || 0
    const cascadeMsg = Number(cascadeCount) > 0
      ? ` · ${cascadeCount} agents cascade-reinstated.`
      : ''
    uiStore.showSuccess?.('Reinstated', `${redactEmail(dev.email)} can log in again.${cascadeMsg}`)
    showReinstateModal.value = false
    reinstateTarget.value = null
    await loadDevelopers()
    if (selectedDetail.value?.id === dev.id) {
      const res2 = await apiClient.get(`/admin/developers/${dev.id}`)
      selectedDetail.value = res2.data
    }
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    reinstateBusy.value = false
  }
}

function openResetPassword(dev: Developer) {
  actionTarget.value = dev
  showResetModal.value = true
}

async function confirmReset() {
  if (!actionTarget.value) return
  actionLoading.value = true
  try {
    const res = await apiClient.post(`/admin/developers/${actionTarget.value.id}/force-password-reset`)
    uiStore.showSuccess?.('Reset Email Sent', res.data.message || 'Password reset email sent.')
    showResetModal.value = false
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

function openDisable2FA(dev: Developer) {
  actionTarget.value = dev
  actionReason.value = ''
  actionValidationError.value = ''
  showDisable2FAModal.value = true
}

async function confirmDisable2FA() {
  if (!actionTarget.value) return
  if (!actionReason.value.trim()) {
    actionValidationError.value = 'Reason required — disabling 2FA is a security event; the audit log needs a justification.'
    return
  }
  actionValidationError.value = ''
  actionLoading.value = true
  try {
    await apiClient.post(`/admin/developers/${actionTarget.value.id}/disable-2fa`, { reason: actionReason.value })
    uiStore.showSuccess?.('2FA Disabled', `${redactEmail(actionTarget.value.email)} will re-enrol on next login.`)
    showDisable2FAModal.value = false
    await loadDevelopers()
    if (selectedDetail.value?.id === actionTarget.value.id) {
      const res = await apiClient.get(`/admin/developers/${actionTarget.value.id}`)
      selectedDetail.value = res.data
    }
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

// AD1 (audit 2026-05-07): replaced native confirm() with themed ConfirmActionModal.
const showVerifyEmailModal = ref(false)
const verifyEmailTarget = ref<Developer | null>(null)
const verifyEmailBusy = ref(false)

function openForceEmailVerify(dev: Developer) {
  verifyEmailTarget.value = dev
  showVerifyEmailModal.value = true
}

async function forceEmailVerify(_reasonFromModal: string) {
  const dev = verifyEmailTarget.value
  if (!dev) return
  verifyEmailBusy.value = true
  try {
    await apiClient.post(`/admin/developers/${dev.id}/force-email-verify`)
    uiStore.showSuccess?.('Verified', `${redactEmail(dev.email)} is now verified.`)
    showVerifyEmailModal.value = false
    verifyEmailTarget.value = null
    await loadDevelopers()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    verifyEmailBusy.value = false
  }
}

function openRevokeKeys(dev: Developer) {
  actionTarget.value = dev
  showRevokeKeysModal.value = true
}

// §pass66.9 — P10 Gift Provisioning Time
function openGiftProvisioning(dev: Developer) {
  actionTarget.value = dev
  giftMonths.value = 1
  actionReason.value = ''
  actionValidationError.value = ''
  showGiftProvisioningModal.value = true
}

// §pass66.11 — Grant Flare Tier handler
function openGrantFlare(dev: Developer) {
  actionTarget.value = dev
  grantFlareTier.value = 'shadow_chancellor'
  actionReason.value = ''
  actionValidationError.value = ''
  showGrantFlareModal.value = true
}

async function confirmGrantFlare() {
  if (!actionTarget.value) return
  if (actionReason.value.trim().length < 10) {
    actionValidationError.value = `Reason must be at least 10 characters (got ${actionReason.value.length}). Audit trail requires context.`
    return
  }
  actionLoading.value = true
  try {
    const res = await apiClient.post('/admin/fiat/flare/grant', {
      developer_id: actionTarget.value.id,
      tier: grantFlareTier.value,
      force: true,
    })
    uiStore.showSuccess?.(
      'Flare Granted',
      `${redactEmail(actionTarget.value.email)} → ${res.data.flare_tier} (id ${res.data.flare_id})`,
    )
    showGrantFlareModal.value = false
    if (selectedDetail.value?.id === actionTarget.value.id) {
      const d = await apiClient.get(`/admin/developers/${actionTarget.value.id}`)
      selectedDetail.value = d.data
    }
  } catch (e: any) {
    uiStore.showError?.('Grant Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

async function confirmGiftProvisioning() {
  if (!actionTarget.value) return
  if (giftMonths.value < 1 || giftMonths.value > 120) {
    actionValidationError.value = 'Months must be between 1 and 120.'
    return
  }
  if (actionReason.value.trim().length < 10) {
    actionValidationError.value = `Reason must be at least 10 characters (got ${actionReason.value.length}). Audit trail requires context.`
    return
  }
  actionLoading.value = true
  try {
    const res = await apiClient.post(
      `/admin/developers/${actionTarget.value.id}/gift-provisioning`,
      { months: giftMonths.value, reason: actionReason.value },
    )
    uiStore.showSuccess?.('Provisioning Gifted', res.data.message || `${giftMonths.value} month(s) gifted.`)
    showGiftProvisioningModal.value = false
    if (selectedDetail.value?.id === actionTarget.value.id) {
      const d = await apiClient.get(`/admin/developers/${actionTarget.value.id}`)
      selectedDetail.value = d.data
    }
  } catch (e: any) {
    uiStore.showError?.('Gift Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

async function confirmRevokeKeys() {
  if (!actionTarget.value) return
  actionLoading.value = true
  try {
    const res = await apiClient.post(`/admin/developers/${actionTarget.value.id}/revoke-api-keys`)
    uiStore.showSuccess?.('Keys Revoked', res.data.message || 'All API keys invalidated.')
    showRevokeKeysModal.value = false
    if (selectedDetail.value?.id === actionTarget.value.id) {
      const d = await apiClient.get(`/admin/developers/${actionTarget.value.id}`)
      selectedDetail.value = d.data
    }
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

function openDelete(dev: Developer) {
  actionTarget.value = dev
  actionReason.value = ''
  confirmEmail.value = ''
  actionValidationError.value = ''
  showDeleteModal.value = true
}

async function confirmDelete() {
  if (!actionTarget.value) return
  if (actionReason.value.length < 20) {
    actionValidationError.value = `Reason must be at least 20 characters for hard-delete (got ${actionReason.value.length}).`
    return
  }
  if (confirmEmail.value !== actionTarget.value.email) {
    actionValidationError.value = `Email confirmation must match exactly: ${actionTarget.value.email}`
    return
  }
  actionValidationError.value = ''
  actionLoading.value = true
  try {
    await apiClient.delete(`/admin/developers/${actionTarget.value.id}`, {
      data: { reason: actionReason.value, confirm_email: confirmEmail.value },
    })
    uiStore.showSuccess?.('Deleted', `${redactEmail(actionTarget.value.email)} soft-deleted. Their agents are now orphaned.`)
    showDeleteModal.value = false
    closeDrawer()
    await loadDevelopers()
  } catch (e: any) {
    uiStore.showError?.('Failed', e.response?.data?.detail || e.message)
  } finally {
    actionLoading.value = false
  }
}

// ── Helpers ─────────────────────────────────────────────────
// §FESUITE 132 (2026-10-15): every door, confirm and toast on this page goes through here: with emails hidden (the
// default, for a shared screen) none of them may spell a developer's email out.
function redactEmail(email: string): string {
  if (showEmails.value) return email
  if (!email) return '—'
  const [local, domain] = email.split('@')
  if (!domain) return '••••@••••'
  return local.substring(0, 2) + '••••@' + domain
}

function timeAgo(ts: string | null): string {
  if (!ts) return '—'
  return dayjs(ts).fromNow()
}

function shortDate(ts: string | null): string {
  if (!ts) return '—'
  return dayjs(ts).format('YYYY-MM-DD')
}

function initials(name: string): string {
  if (!name) return '?'
  return name.split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase()
}

function statusBadge(d: Developer): { label: string; cls: string } {
  if (d.deleted_at) return { label: 'deleted', cls: 'ad-sb-deleted' }
  if (d.is_suspended) return { label: 'suspended', cls: 'ad-sb-suspended' }
  if (d.is_admin) return { label: 'admin', cls: 'ad-sb-admin' }
  if (d.is_federation_operator) return { label: `operator: ${d.federation_operator_status || ''}`, cls: 'ad-sb-operator' }
  if (!d.is_verified) return { label: 'unverified', cls: 'ad-sb-unverified' }
  return { label: 'active', cls: 'ad-sb-active' }
}

// B (2026-05-08): cross-view drilldown — when navigated from AdminWebhooks
// or other watchtowers with `?id=N`, auto-open that developer's drawer.
async function openDrawerById(developerId: number | string) {
  const id = typeof developerId === 'string' ? Number(developerId) : developerId
  if (!Number.isFinite(id) || id <= 0) return
  // Find in already-loaded list first; fall back to fetch-by-id which
  // openDrawer does internally.
  const found = developers.value.find(d => d.id === id)
  if (found) {
    await openDrawer(found)
  } else {
    // Synthesize a stub Developer with id; openDrawer fetches the full detail
    await openDrawer({ id } as Developer)
  }
}

onMounted(async () => {
  await loadDevelopers()
  // route was bound at top-level script setup (above) — safe to read here.
  const queryId = route.query.id
  if (typeof queryId === 'string' && queryId) {
    void openDrawerById(queryId)
  }
})

/* §FESUITE — a deep link (?id=) followed while this page is already open is a query-only change: vue-router reuses
   the component and onMounted does not run again, so the drawer never opened (measured by the admin lifecycle). */
watch(() => route.query.id, (id) => {
  if (typeof id === 'string' && id) void openDrawerById(id)
})
</script>

<template>
<div class="ad hm-module">
  <!-- Ambient -->
  <div class="ad-ambient">
    <div class="ad-grid"></div>
    <div class="ad-glow ad-glow-1"></div>
    <div class="ad-glow ad-glow-2"></div>
  </div>

  <!-- Hero -->
  <section class="ad-hero" data-tour="admin-devs-hero">
    <div class="ad-hero-inner">
      <div class="ad-chip"><span class="ad-chip-dot"></span>{{ t('adminDevelopersView.chip') }}</div>
      <h1 class="ad-h1">{{ t('adminDevelopersView.hero.h1a') }}<span class="ad-accent">{{ t('adminDevelopersView.hero.h1Accent') }}</span></h1>
      <p class="ad-lead">{{ t('adminDevelopersView.lead') }}</p>
    </div>
  </section>

  <!-- Page tabs (Build #5, 2026-05-07) -->
  <div class="ad-tabbar-wrap">
    <div class="ad-tabbar">
      <button
        class="ad-tabbar-btn"
        :class="{ 'ad-tabbar-btn--active': pageTab === 'developers' }"
        @click="pageTab = 'developers'"
        aria-label="Show developers list"
      >
        <span class="ad-tabbar-icon">◉</span>
        <span class="ad-tabbar-label">{{ t('adminDevelopersView.pageTabs.developers') }}</span>
      </button>
      <button
        class="ad-tabbar-btn"
        :class="{ 'ad-tabbar-btn--active': pageTab === 'funding' }"
        @click="pageTab = 'funding'"
        aria-label="Show funding requests triage"
      >
        <span class="ad-tabbar-icon">◎</span>
        <span class="ad-tabbar-label">{{ t('adminDevelopersView.pageTabs.funding') }}</span>
      </button>
    </div>
  </div>

  <!-- Funding triage tab (Build #5) -->
  <FundingRequestsPanel v-if="pageTab === 'funding'" />

  <!-- Developers list tab — original content gated by tab -->
  <template v-else>

  <!-- KPIs -->
  <div class="ad-stats-row">
    <div class="ad-stat">
      <span class="ad-stat-label">{{ t('adminDevelopersView.kpi.total') }}</span>
      <span class="ad-stat-value">{{ devsRead ? kpis.total : '—' }}</span>
    </div>
    <div class="ad-stat ad-stat-ok">
      <span class="ad-stat-label">{{ t('adminDevelopersView.kpi.verified') }}</span>
      <span class="ad-stat-value">{{ devsRead ? kpis.verified : '—' }}</span>
    </div>
    <div class="ad-stat ad-stat-cyan">
      <span class="ad-stat-label">{{ t('adminDevelopersView.kpi.twoFaOn') }}</span>
      <span class="ad-stat-value">{{ devsRead ? kpis.twofa : '—' }}</span>
    </div>
    <div class="ad-stat ad-stat-purple">
      <span class="ad-stat-label">{{ t('adminDevelopersView.kpi.admins') }}</span>
      <span class="ad-stat-value">{{ devsRead ? kpis.admins : '—' }}</span>
    </div>
    <div class="ad-stat ad-stat-amber">
      <span class="ad-stat-label">{{ t('adminDevelopersView.kpi.operators') }}</span>
      <span class="ad-stat-value">{{ devsRead ? kpis.operators : '—' }}</span>
    </div>
    <div class="ad-stat" :class="kpis.suspended > 0 ? 'ad-stat-bad' : 'ad-stat-muted'">
      <span class="ad-stat-label">{{ t('adminDevelopersView.kpi.suspended') }}</span>
      <span class="ad-stat-value">{{ devsRead ? kpis.suspended : '—' }}</span>
    </div>
  </div>

  <!-- Filter + Search -->
  <div class="ad-toolbar">
    <div class="ad-filter-bar">
      <button class="ad-fb-btn" :class="{ 'ad-fb-active': statusFilter === 'all' }" @click="setStatusFilter('all')">{{ t('adminDevelopersView.filters.all') }}</button>
      <button class="ad-fb-btn" :class="{ 'ad-fb-active': statusFilter === 'verified' }" @click="setStatusFilter('verified')">{{ t('adminDevelopersView.filters.verified') }}</button>
      <button class="ad-fb-btn" :class="{ 'ad-fb-active': statusFilter === 'unverified' }" @click="setStatusFilter('unverified')">{{ t('adminDevelopersView.filters.unverified') }}</button>
      <button class="ad-fb-btn" :class="{ 'ad-fb-active': statusFilter === 'admins' }" @click="setStatusFilter('admins')">{{ t('adminDevelopersView.filters.admins') }}</button>
      <button class="ad-fb-btn" :class="{ 'ad-fb-active': statusFilter === 'operators' }" @click="setStatusFilter('operators')">{{ t('adminDevelopersView.filters.operators') }}</button>
      <button class="ad-fb-btn" :class="{ 'ad-fb-active': statusFilter === 'suspended' }" @click="setStatusFilter('suspended')">{{ t('adminDevelopersView.filters.suspended') }}</button>
      <button class="ad-fb-btn" :class="{ 'ad-fb-active': statusFilter === 'deleted' }" @click="setStatusFilter('deleted')">{{ t('adminDevelopersView.filters.deleted') }}</button>
      <button class="ad-fb-btn ad-fb-right" :class="{ 'ad-fb-active': has2FA === true }" @click="toggle2FAFilter">{{ t('adminDevelopersView.twoFAEnabled') }}</button>
    </div>
    <div class="ad-search-wrap">
      <input v-model="search" @input="onSearchInput" class="ad-search" :placeholder="t('adminDevelopersView.search')" />
      <button v-if="search" @click="clearSearch" class="ad-search-clear">×</button>
    </div>
    <button @click="showEmails = !showEmails" class="ad-toggle-btn">
      {{ showEmails ? t('adminDevelopersView.hideEmails') : t('adminDevelopersView.showEmails') }}
    </button>
    <button @click="loadDevelopers()" class="ad-toggle-btn" :disabled="loading" :title="t('common.forceRefresh')">
      {{ loading ? t('common.loading') : '↻ ' + t('common.refresh') }}
    </button>
  </div>

  <!-- Loading status banner — always visible during fetch so user gets feedback
       even if the table somehow collapses (defensive against stale-cache states) -->
  <div v-if="loading" class="ad-loading-banner">
    <div class="ad-spinner-inline"></div>
    <span>Loading developers from /admin/developers… (offset {{ offset }}, limit {{ limit }})</span>
  </div>

  <!-- Table -->
  <div v-if="error" class="ad-error">{{ error }}</div>

  <!-- Phase 6.5: keep the table-wrap always rendered so headers + pagination
       footer are visible during loading (was: spinner replaced the whole table,
       leading to a "blank page" perception during slow fetches with 1000+ devs).
       §pass66.4.2 (2026-05-23): removed `min-height: 360px` — on a cloud-op
       with only 1 real dev visible (21 federation shadows hidden), the 360px
       floor created a 177px empty area BELOW the pagination that read as
       "missing content" in screenshots, even though everything rendered.
       Natural height (~190px when 1 row) is fine; the loading skeleton itself
       provides height during fetch, no min-height needed. -->
  <div class="ad-table-wrap">
    <table class="ad-table">
      <thead>
        <tr>
          <th></th>
          <th>{{ t('adminDevelopersView.table.name') }}</th>
          <th>{{ t('adminDevelopersView.table.email') }}</th>
          <th>{{ t('adminDevelopersView.table.status') }}</th>
          <th>{{ t('adminDevelopersView.table.twoFa') }}</th>
          <th>{{ t('adminDevelopersView.table.agents') }}</th>
          <th>{{ t('adminDevelopersView.table.lastLogin') }}</th>
          <th>{{ t('adminDevelopersView.table.created') }}</th>
          <th style="text-align: right;">{{ t('adminDevelopersView.table.actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <!-- Loading skeleton rows so the table doesn't disappear during fetch -->
        <template v-if="loading && visibleDevelopers.length === 0">
          <tr v-for="n in 8" :key="`skel-${n}`" class="ad-row ad-row-skeleton">
            <td colspan="9"><div class="ad-skeleton-row"></div></td>
          </tr>
        </template>
        <tr v-for="d in visibleDevelopers" :key="d.id" class="ad-row" @click="openDrawer(d)">
          <td><div class="ad-avatar">{{ initials(d.name) }}</div></td>
          <td><span class="ad-name">{{ d.name }}</span></td>
          <td><span class="ad-email">{{ redactEmail(d.email) }}</span></td>
          <td>
            <span class="ad-sb" :class="statusBadge(d).cls">{{ statusBadge(d).label }}</span>
          </td>
          <td>
            <span v-if="d.two_fa_enabled" title="2FA enabled" class="ad-icon-on"><Icon name="mdi:lock" /></span>
            <span v-else class="ad-icon-off">—</span>
          </td>
          <td class="ad-num">{{ d.agent_count }}</td>
          <td class="ad-dim">{{ timeAgo(d.last_login_at) }}</td>
          <td class="ad-dim">{{ shortDate(d.created_at) }}</td>
          <td style="text-align: right;" @click.stop>
            <div class="ad-row-actions">
              <button v-if="!d.is_suspended && !d.deleted_at" @click="openSuspend(d)" class="ad-btn ad-btn-sm ad-btn-warn">{{ t('adminDevelopersView.actions.suspend') }}</button>
              <button v-if="d.is_suspended" @click="openReinstate(d)" class="ad-btn ad-btn-sm ad-btn-good">{{ t('adminDevelopersView.actions.reinstate') }}</button>
              <button v-if="!d.deleted_at" @click="openResetPassword(d)" class="ad-btn ad-btn-sm">{{ t('adminDevelopersView.actions.resetPw') }}</button>
              <button v-if="d.two_fa_enabled && !d.deleted_at" @click="openDisable2FA(d)" class="ad-btn ad-btn-sm">2FA off</button>
              <button v-if="!d.is_verified && !d.deleted_at" @click="openForceEmailVerify(d)" class="ad-btn ad-btn-sm">{{ t('adminDevelopersView.actions.verify') }}</button>
              <button v-if="!d.deleted_at" @click="openQuota(d)" class="ad-btn ad-btn-sm" title="Bundle quota">Quota</button>
            </div>
          </td>
        </tr>
        <!-- §FESUITE (2026-10-04): "none" only after a read that answered; the error banner says a failed one -->
        <tr v-if="visibleDevelopers.length === 0 && devsRead">
          <td colspan="9" class="ad-empty">No developers match the current filter.</td>
        </tr>
        <tr v-if="hiddenShadowCount > 0">
          <td colspan="9" class="ad-shadow-note">
            <span style="opacity:0.55; font-size:0.7rem; font-family:'IBM Plex Mono',monospace;">
              {{ hiddenShadowCount }} federation-shadow placeholder row{{ hiddenShadowCount === 1 ? '' : 's' }} hidden (peer FK stubs, never real users)
            </span>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="ad-pagination">
      <button class="ad-btn ad-btn-ghost" :disabled="offset === 0" @click="prevPage">{{ t('adminDevelopersView.pagination.prev') }}</button>
      <!-- §pass66.4.1 (2026-05-23) — pagination shows VISIBLE rows (post shadow
           filter), not the raw server total. Was confusing on cloud-ops where
           the raw server count is dominated by federation shadows (qatest16:
           "1–22 of 22" but only 1 actual row rendered). -->
      <span class="ad-dim">
        Showing {{ visibleDevelopers.length === 0 ? 0 : offset + 1 }}–{{ offset + visibleDevelopers.length }} of {{ Math.max(total - hiddenShadowCount, visibleDevelopers.length) }}
        <span v-if="hiddenShadowCount > 0" style="opacity:0.55;">· {{ hiddenShadowCount }} federation shadow{{ hiddenShadowCount === 1 ? '' : 's' }} hidden</span>
      </span>
      <button class="ad-btn ad-btn-ghost" :disabled="offset + limit >= total" @click="nextPage">{{ t('adminDevelopersView.pagination.next') }}</button>
    </div>
  </div>

  </template><!-- /pageTab === 'developers' -->

  <!-- ════ Detail Drawer ════════════════════════════════════════════ -->
  <Teleport to="body">
    <div v-if="drawerOpen" class="ad-drawer-overlay" @click.self="closeDrawer">
      <aside class="ad-drawer">
        <header class="ad-drawer-header">
          <div>
            <div class="ad-drawer-label">DEVELOPER · ID {{ selectedDetail?.id || '…' }}</div>
            <h2 class="ad-drawer-title">{{ selectedDetail?.name || '…' }}</h2>
            <div class="ad-drawer-sub">{{ redactEmail(selectedDetail?.email || '') }}</div>
          </div>
          <button class="ad-drawer-close" @click="closeDrawer">×</button>
        </header>

        <div v-if="drawerLoading" class="ad-center"><div class="ad-spinner"></div></div>

        <template v-else-if="selectedDetail">
          <!-- Tabs -->
          <nav class="ad-drawer-tabs">
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'profile' }" @click="switchTab('profile')">{{ t('adminDevelopersView.drawerTabs.profile') }}</button>
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'auth' }" @click="switchTab('auth')">{{ t('adminDevelopersView.drawerTabs.auth') }}</button>
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'roles' }" @click="switchTab('roles')">{{ t('adminDevelopersView.drawerTabs.roles') }}</button>
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'permissions' }" @click="switchTab('permissions')">{{ t('adminDevelopersView.drawerTabs.permissions') }}</button>
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'agents' }" @click="switchTab('agents')">{{ t('adminDevelopersView.drawerTabs.agents') }} <span class="ad-count">{{ selectedDetail.agents.length }}</span></button>
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'api_keys' }" @click="switchTab('api_keys')">{{ t('adminDevelopersView.drawerTabs.apiKeys') }} <span class="ad-count">{{ selectedDetail.api_keys.length }}</span></button>
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'activity' }" @click="switchTab('activity')">{{ t('adminDevelopersView.drawerTabs.activity') }}</button>
            <button class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'mcpAudit' }" @click="switchTab('mcpAudit')" title="Recent MCP tool calls made under this developer's account">MCP Audit</button>
            <button v-if="selectedDetail.operator_application_id" class="ad-drawer-tab" :class="{ 'ad-drawer-tab-active': drawerTab === 'operator' }" @click="switchTab('operator')">{{ t('adminDevelopersView.drawerTabs.operator') }}</button>
          </nav>

          <div class="ad-drawer-body">
            <!-- Profile -->
            <section v-if="drawerTab === 'profile'" class="ad-tab-pane">
              <dl class="ad-kv">
                <dt>{{ t('adminDevelopersView.details.displayName') }}</dt><dd>{{ selectedDetail.display_name || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.bio') }}</dt><dd class="ad-bio">{{ selectedDetail.bio || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.company') }}</dt><dd>{{ selectedDetail.company || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.location') }}</dt><dd>{{ selectedDetail.location_label || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.timezone') }}</dt><dd>{{ selectedDetail.timezone || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.website') }}</dt><dd><a v-if="selectedDetail.website_url" :href="safeExternalUrl(selectedDetail.website_url)" target="_blank" rel="noopener noreferrer">{{ selectedDetail.website_url }}</a><span v-else>—</span></dd>
                <dt>{{ t('adminDevelopersView.details.github') }}</dt><dd>{{ selectedDetail.github_url || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.twitter') }}</dt><dd>{{ selectedDetail.twitter_handle || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.profileVisibility') }}</dt><dd>{{ selectedDetail.profile_visibility || '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.created') }}</dt><dd>{{ shortDate(selectedDetail.created_at) }} ({{ timeAgo(selectedDetail.created_at) }})</dd>
              </dl>
            </section>

            <!-- Auth -->
            <section v-else-if="drawerTab === 'auth'" class="ad-tab-pane">
              <dl class="ad-kv">
                <dt>{{ t('adminDevelopersView.details.emailVerified') }}</dt><dd>{{ selectedDetail.is_verified ? '✓ verified' : '✗ unverified' }}</dd>
                <dt>{{ t('adminDevelopersView.details.twoFaEnabled') }}</dt><dd>{{ selectedDetail.two_fa_enabled ? '✓ enabled' : '✗ disabled' }}</dd>
                <dt>{{ t('adminDevelopersView.details.mustChangePassword') }}</dt><dd>{{ selectedDetail.must_change_password ? 'yes (operator bootstrap)' : 'no' }}</dd>
                <dt>{{ t('adminDevelopersView.details.lastLogin') }}</dt><dd>{{ selectedDetail.last_login_at ? `${shortDate(selectedDetail.last_login_at)} (${timeAgo(selectedDetail.last_login_at)})` : 'never' }}</dd>
                <dt>{{ t('adminDevelopersView.details.suspended') }}</dt><dd>
                  <span v-if="selectedDetail.is_suspended" class="ad-sb ad-sb-suspended">
                    suspended {{ selectedDetail.suspended_at ? timeAgo(selectedDetail.suspended_at) : '' }}
                  </span>
                  <span v-else>no</span>
                </dd>
                <dt v-if="selectedDetail.suspended_reason">{{ t('adminDevelopersView.details.suspensionReason') }}</dt>
                <dd v-if="selectedDetail.suspended_reason">{{ selectedDetail.suspended_reason }}</dd>
                <dt>{{ t('adminDevelopersView.details.deleted') }}</dt><dd>{{ selectedDetail.deleted_at ? `${shortDate(selectedDetail.deleted_at)} (${timeAgo(selectedDetail.deleted_at)})` : 'no' }}</dd>
              </dl>
            </section>

            <!-- Roles -->
            <section v-else-if="drawerTab === 'roles'" class="ad-tab-pane">
              <dl class="ad-kv">
                <dt>{{ t('adminDevelopersView.details.platformAdmin') }}</dt><dd>{{ selectedDetail.is_admin ? '✓ is_admin' : '—' }}</dd>
                <dt>{{ t('adminDevelopersView.details.federationOperator') }}</dt>
                <dd>
                  <template v-if="selectedDetail.is_federation_operator">
                    ✓ {{ selectedDetail.federation_operator_status || 'unknown' }}
                  </template>
                  <template v-else>—</template>
                </dd>
                <dt>Flare tier</dt>
                <dd>
                  <code class="ad-mono">{{ selectedDetail.flare_tier || '(none)' }}</code>
                </dd>
                <dt>{{ t('adminDevelopersView.details.organisationMemberships') }}</dt>
                <dd>
                  <div v-if="selectedDetail.organizations.length === 0">—</div>
                  <ul v-else class="ad-list">
                    <li v-for="o in selectedDetail.organizations" :key="o.organization_id">
                      <strong>{{ o.organization_name }}</strong> · <em>{{ o.role }}</em>
                    </li>
                  </ul>
                </dd>
              </dl>

              <!-- §pass66.11 — Grant Flare Tier (incl. Shadow Chancellor) -->
              <div class="ad-section" style="margin-top: 20px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.08);">
                <h4 style="font-size: 0.85rem; margin: 0 0 8px; color: var(--cyan);">
                  Grant Flare Tier
                </h4>
                <p style="font-size: 0.75rem; color: var(--text-secondary); margin: 0 0 12px;">
                  Grant any flare tier (including <strong>shadow_chancellor</strong>) directly,
                  bypassing fiat-purchase thresholds. Higher-rank-wins applies unless force
                  is set (default true for admin grants).
                </p>
                <button class="ad-btn ad-btn-sm ad-btn-good" @click="openGrantFlare(selectedDetail)">
                  Grant Flare Tier
                </button>
              </div>
            </section>

            <!-- Permissions (Fix 1) -->
            <section v-else-if="drawerTab === 'permissions'" class="ad-tab-pane">
              <p class="ad-perm-intro">
                Grant granular platform-admin authority. Each flag unlocks a specific set of <code>/api/v1/admin/*</code>
                endpoints. Legacy <code>is_admin</code> is a super-flag that passes every check — set it via the database if
                you need full authority for a developer.
              </p>
              <div v-if="selectedDetail.is_admin" class="ad-warn-box" style="background: rgba(168, 85, 247, 0.1); border-color: rgba(168, 85, 247, 0.3); color: #c084fc;">
                <p><strong>Legacy super-admin.</strong> This developer has <code>is_admin=True</code>, which grants every flag regardless of what's checked below. Flag edits are still persisted.</p>
              </div>
              <div class="ad-perm-grid">
                <label class="ad-perm-row">
                  <input type="checkbox" v-model="flagDraft.admin_treasury" :disabled="selectedDetail.id === selectedDetail.id && false" />
                  <div>
                    <strong>admin_treasury</strong>
                    <p>fund-agent · issue · event emission policies · projection snapshots · funding requests</p>
                  </div>
                </label>
                <label class="ad-perm-row">
                  <input type="checkbox" v-model="flagDraft.admin_support" />
                  <div>
                    <strong>admin_support</strong>
                    <p>support tickets · broadcast · invite codes</p>
                  </div>
                </label>
                <label class="ad-perm-row">
                  <input type="checkbox" v-model="flagDraft.admin_enforcement" />
                  <div>
                    <strong>admin_enforcement</strong>
                    <p>disputes ruling · agent suspend/revoke/slash · enforcement policy</p>
                  </div>
                </label>
                <label class="ad-perm-row">
                  <input type="checkbox" v-model="flagDraft.admin_federation" />
                  <div>
                    <strong>admin_federation</strong>
                    <p>operator approve/reject/revoke · federation licenses · cloud provisioning · docker pull tokens</p>
                  </div>
                </label>
                <label class="ad-perm-row">
                  <input type="checkbox" v-model="flagDraft.admin_platform" />
                  <div>
                    <strong>admin_platform</strong>
                    <p>diagnostics · api tester · simulation · tutorials · system-health · developer admin</p>
                  </div>
                </label>
              </div>
              <div class="ad-perm-actions">
                <button class="ad-btn ad-btn-ghost" :disabled="!flagsDirty || flagsSaving" @click="resetFlags">Reset</button>
                <button class="ad-btn ad-btn-cyan" :disabled="!flagsDirty || flagsSaving" @click="saveFlags">
                  {{ flagsSaving ? 'Saving…' : 'Save permissions' }}
                </button>
              </div>
            </section>

            <!-- Agents -->
            <section v-else-if="drawerTab === 'agents'" class="ad-tab-pane">
              <div v-if="selectedDetail.agents.length === 0" class="ad-dim">No agents owned by this developer.</div>
              <table v-else class="ad-sub-table">
                <thead><tr><th>Name</th><th>DID</th><th>Status</th><th>Last active</th></tr></thead>
                <tbody>
                  <tr v-for="a in selectedDetail.agents" :key="a.did">
                    <td>{{ a.name || '—' }}</td>
                    <!-- §FESUITE — every DID on a frame shares its first 32 characters; the unique part is the tail -->
                    <td><code class="ad-mono" :title="a.did">{{ a.did.length > 36 ? `${a.did.slice(0, 22)}…${a.did.slice(-10)}` : a.did }}</code></td>
                    <td>{{ a.status }}<span v-if="a.enforcement_status && a.enforcement_status !== 'active'"> / <em>{{ a.enforcement_status }}</em></span></td>
                    <td class="ad-dim">{{ timeAgo(a.last_active_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <!-- API Keys -->
            <section v-else-if="drawerTab === 'api_keys'" class="ad-tab-pane">
              <div v-if="selectedDetail.api_keys.length === 0" class="ad-dim">No API keys issued.</div>
              <table v-else class="ad-sub-table">
                <thead><tr><th>Prefix</th><th>Description</th><th>Active</th><th>Last used</th></tr></thead>
                <tbody>
                  <tr v-for="k in selectedDetail.api_keys" :key="k.id">
                    <td><code class="ad-mono">{{ k.key_prefix }}</code></td>
                    <td>{{ k.description || '—' }}</td>
                    <td><span :class="k.is_active ? 'ad-icon-on' : 'ad-icon-off'">{{ k.is_active ? '●' : '○' }}</span></td>
                    <td class="ad-dim">{{ timeAgo(k.last_used_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </section>

            <!-- Activity -->
            <section v-else-if="drawerTab === 'activity'" class="ad-tab-pane">
              <div v-if="activityLoading" class="ad-center"><div class="ad-spinner"></div></div>
              <div v-else-if="activityEvents.length === 0" class="ad-dim">No EventStore activity recorded for this developer.</div>
              <ul v-else class="ad-activity-feed">
                <li v-for="(ev, i) in activityEvents" :key="i" class="ad-activity-item">
                  <span class="ad-activity-type">{{ ev.event_type || '?' }}</span>
                  <span class="ad-activity-time">{{ timeAgo(ev.timestamp || ev.created_at) }}</span>
                  <pre class="ad-activity-data">{{ JSON.stringify(ev.data || ev, null, 2).slice(0, 300) }}</pre>
                </li>
              </ul>
            </section>

            <!-- MCP Audit (2026-05-24, §pass68 admin variant) — per-developer scoped audit log
                 with self-watching warning when admin ≠ subject. Each cross-developer read
                 emits an admin_read_mcp_audit row into the target's own audit history. -->
            <section v-else-if="drawerTab === 'mcpAudit'" class="ad-tab-pane">
              <McpAuditLogPanel
                scope="admin"
                :actor-id="String(selectedDetail.id)"
                :subject-label="selectedDetail.name || selectedDetail.email"
                :storage-key="'admin-dev-mcp'"
                :poll-interval-ms="30000"
              />
            </section>

            <!-- Operator -->
            <section v-else-if="drawerTab === 'operator'" class="ad-tab-pane">
              <p>
                Operator application ID:
                <code class="ad-mono">{{ selectedDetail.operator_application_id }}</code>
              </p>
              <router-link to="/operator-management" class="ad-btn ad-btn-sm">→ Open Operator Management</router-link>

              <!-- §pass66.9 — P10 Gift Provisioning Time -->
              <div class="ad-section" style="margin-top: 20px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.08);">
                <h4 style="font-size: 0.85rem; margin: 0 0 8px; color: var(--cyan);">
                  Gift Cloud-Op Provisioning Time
                </h4>
                <p style="font-size: 0.75rem; color: var(--text-secondary); margin: 0 0 12px;">
                  Add months to this developer's cloud-op provisioning unlock window
                  without requiring a fiat purchase. Mainframe-only. Audited.
                </p>
                <button class="ad-btn ad-btn-sm ad-btn-good" @click="openGiftProvisioning(selectedDetail)">
                  Gift Provisioning Time
                </button>
              </div>

            </section>
          </div>

          <!-- Drawer action footer (danger zone) -->
          <footer class="ad-drawer-footer">
            <button v-if="!selectedDetail.deleted_at" class="ad-btn ad-btn-sm" @click="openRevokeKeys(selectedDetail)">Revoke API keys</button>
            <button
              v-if="!selectedDetail.deleted_at && !selectedDetail.is_admin"
              class="ad-btn ad-btn-sm ad-btn-danger"
              @click="openDelete(selectedDetail)"
            >Soft delete</button>
          </footer>
        </template>
      </aside>
    </div>
  </Teleport>

  <!-- ════ Action Modals ═══════════════════════════════════════════ -->
  <Teleport to="body">
    <div v-if="showSuspendModal && actionTarget" class="ad-overlay" @click.self="showSuspendModal = false">
      <div class="ad-modal" style="width: 540px;">
        <p class="ad-modal-title">// COORDINATED SUSPEND — DEVELOPER</p>
        <p class="ad-modal-sub">
          Suspending <strong>{{ redactEmail(actionTarget.email) }}</strong>. They will be unable to log in.
          <span v-if="cascadeAgentCount > 0" style="color: #f87171; display: block; margin-top: 4px;">
            <Icon name="mdi:alert" /> This will cascade-suspend {{ cascadeAgentCount }} owned agent{{ cascadeAgentCount !== 1 ? 's' : '' }} — all will lose mTLS identity + TEG access.
          </span>
        </p>
        <div v-if="cascadeLoading" class="ad-dim" style="font-size: 11px; margin-bottom: 8px;">Loading cascade preview…</div>
        <div v-else-if="cascadeAgentCount > 0" style="background: rgba(239,68,68,0.06); border: 1px solid rgba(239,68,68,0.25); border-radius: 4px; padding: 8px 10px; margin-bottom: 12px;">
          <p style="font-size: 11px; color: #fca5a5; margin: 0 0 6px 0;"><strong>Affected agents (showing {{ cascadeAgents.length }} of {{ cascadeAgentCount }}):</strong></p>
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <div v-for="agent in cascadeAgents" :key="agent.did" style="font-size: 11px; font-family: monospace; color: #cbd5e1; padding: 3px 6px; background: rgba(0,0,0,0.3); border-radius: 3px; display: flex; justify-content: space-between;">
              <span>{{ agent.name || (agent.did.length > 30 ? agent.did.slice(0, 30) + '…' : agent.did) }}</span>
              <span :style="{ color: agent.mtls_enabled ? '#4ade80' : '#8291a8' }">
                {{ agent.mtls_enabled ? 'mTLS active' : 'no mTLS' }}
              </span>
            </div>
          </div>
        </div>
        <label class="ad-label">Reason * (min 10 chars)</label>
        <textarea v-model="actionReason" class="ad-input" rows="3" placeholder="Reason for suspension (cascaded to all agents)…"></textarea>
        <p v-if="actionValidationError" class="ad-modal-error" role="alert"><Icon name="mdi:alert" /> {{ actionValidationError }}</p>
        <div class="ad-modal-actions">
          <button class="ad-btn ad-btn-ghost" @click="showSuspendModal = false">Cancel</button>
          <button class="ad-btn ad-btn-warn" :disabled="actionReason.length < 10 || actionLoading" @click="confirmSuspend">
            {{ actionLoading ? 'Suspending…' : (cascadeAgentCount > 0 ? `Suspend (cascade ${cascadeAgentCount})` : 'Suspend') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showResetModal && actionTarget" class="ad-overlay" @click.self="showResetModal = false">
      <div class="ad-modal">
        <p class="ad-modal-title">// FORCE PASSWORD RESET</p>
        <p class="ad-modal-sub">A password reset email will be sent to <strong>{{ redactEmail(actionTarget.email) }}</strong>. The token expires in 24 hours.</p>
        <div class="ad-modal-actions">
          <button class="ad-btn ad-btn-ghost" @click="showResetModal = false">Cancel</button>
          <button class="ad-btn ad-btn-cyan" :disabled="actionLoading" @click="confirmReset">
            {{ actionLoading ? 'Sending…' : 'Send Reset Email' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showDisable2FAModal && actionTarget" class="ad-overlay" @click.self="showDisable2FAModal = false">
      <div class="ad-modal">
        <p class="ad-modal-title">// DISABLE 2FA</p>
        <p class="ad-modal-sub">Disabling 2FA for <strong>{{ redactEmail(actionTarget.email) }}</strong>. They will be prompted to re-enrol on next login.</p>
        <label class="ad-label">Reason *</label>
        <textarea v-model="actionReason" class="ad-input" rows="2" placeholder="Reason (e.g. lost authenticator)…"></textarea>
        <p v-if="actionValidationError" class="ad-modal-error" role="alert"><Icon name="mdi:alert" /> {{ actionValidationError }}</p>
        <div class="ad-modal-actions">
          <button class="ad-btn ad-btn-ghost" @click="showDisable2FAModal = false">Cancel</button>
          <button class="ad-btn ad-btn-warn" :disabled="!actionReason || actionLoading" @click="confirmDisable2FA">
            {{ actionLoading ? 'Disabling…' : 'Disable 2FA' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showRevokeKeysModal && actionTarget" class="ad-overlay" @click.self="showRevokeKeysModal = false">
      <div class="ad-modal">
        <p class="ad-modal-title">// REVOKE ALL API KEYS</p>
        <p class="ad-modal-sub">Invalidate all programmatic API keys for <strong>{{ redactEmail(actionTarget.email) }}</strong>. Existing integrations will need new keys.</p>
        <div class="ad-modal-actions">
          <button class="ad-btn ad-btn-ghost" @click="showRevokeKeysModal = false">Cancel</button>
          <button class="ad-btn ad-btn-danger" :disabled="actionLoading" @click="confirmRevokeKeys">
            {{ actionLoading ? 'Revoking…' : 'Revoke All Keys' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §pass66.11 — Grant Flare Tier modal -->
  <Teleport to="body">
    <div v-if="showGrantFlareModal && actionTarget" class="ad-overlay" @click.self="showGrantFlareModal = false">
      <div class="ad-modal" style="width: 520px;">
        <p class="ad-modal-title">// GRANT FLARE TIER</p>
        <p class="ad-modal-sub">
          Grant a flare tier to <strong>{{ redactEmail(actionTarget.email) }}</strong>.
          Bypasses the fiat-purchase threshold (Shadow Chancellor normally requires
          €500 cumulative spend; admin grants override). Audited.
        </p>
        <div class="ad-field" style="margin-bottom: 14px;">
          <label for="admindevelopers-sel-1296" style="display:block; font-size:0.8rem; color: var(--text-secondary); margin-bottom:6px;">
            Tier
          </label>
          <select id="admindevelopers-sel-1296" v-model="grantFlareTier" class="nc-input" style="width: 100%;">
            <option value="sentinel">sentinel (rank 1 — €1+ purchase)</option>
            <option value="architect">architect (rank 2 — €20+ purchase)</option>
            <option value="founder">founder (rank 3 — €100+ purchase)</option>
            <option value="shadow_chancellor">shadow_chancellor (rank 4 — €500 cumulative)</option>
            <option value="operator">operator (rank 50 — federation operator badge)</option>
            <option value="commander">commander (rank 99 — top tier)</option>
          </select>
        </div>
        <div class="ad-field" style="margin-bottom: 12px;">
          <label style="display:block; font-size:0.8rem; color: var(--text-secondary); margin-bottom:6px;">
            Audit reason (min 10 chars) <span style="color:#ef4444;">*</span>
          </label>
          <textarea
            v-model="actionReason"
            rows="3"
            placeholder="e.g., Early backer of TheProtocol, sovereign agent contribution, community contributor recognition"
            class="nc-input"
            style="width: 100%;"
          ></textarea>
        </div>
        <p v-if="actionValidationError" style="color:#ef4444; font-size:0.75rem; margin: 0 0 12px;">
          {{ actionValidationError }}
        </p>
        <div class="ad-modal-actions">
          <button class="ad-btn ad-btn-ghost" @click="showGrantFlareModal = false">Cancel</button>
          <button class="ad-btn ad-btn-good" :disabled="actionLoading" @click="confirmGrantFlare">
            {{ actionLoading ? 'Granting…' : `Grant ${grantFlareTier}` }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §pass66.9 — P10 Gift Provisioning modal -->
  <Teleport to="body">
    <div v-if="showGiftProvisioningModal && actionTarget" class="ad-overlay" @click.self="showGiftProvisioningModal = false">
      <div class="ad-modal" style="width: 540px;">
        <p class="ad-modal-title">// GIFT CLOUD-OP PROVISIONING TIME</p>
        <p class="ad-modal-sub">
          Extend cloud-op provisioning unlock for <strong>{{ redactEmail(actionTarget.email) }}</strong>.
          This adds months to their <code>provisioning_unlocked_until</code> window
          without requiring a fiat purchase. Audited under <code>ProvisioningGifted</code>
          event type.
        </p>
        <div class="ad-field" style="margin-bottom: 16px;">
          <label style="display:block; font-size:0.8rem; color: var(--text-secondary); margin-bottom:6px;">
            Months to gift (1-120)
          </label>
          <input
            v-model.number="giftMonths"
            type="number"
            min="1"
            max="120"
            class="nc-input"
            style="width: 120px;"
          />
        </div>
        <div class="ad-field" style="margin-bottom: 12px;">
          <label style="display:block; font-size:0.8rem; color: var(--text-secondary); margin-bottom:6px;">
            Audit reason (min 10 chars) <span style="color:#ef4444;">*</span>
          </label>
          <textarea
            v-model="actionReason"
            rows="3"
            placeholder="e.g., Grant for beta testing feedback, sovereign agent contribution, etc."
            class="nc-input"
            style="width: 100%;"
          ></textarea>
        </div>
        <p v-if="actionValidationError" style="color:#ef4444; font-size:0.75rem; margin: 0 0 12px;">
          {{ actionValidationError }}
        </p>
        <div class="ad-modal-actions">
          <button class="ad-btn ad-btn-ghost" @click="showGiftProvisioningModal = false">Cancel</button>
          <button class="ad-btn ad-btn-good" :disabled="actionLoading" @click="confirmGiftProvisioning">
            {{ actionLoading ? 'Gifting…' : `Gift ${giftMonths} Month${giftMonths === 1 ? '' : 's'}` }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="showDeleteModal && actionTarget" class="ad-overlay" @click.self="showDeleteModal = false">
      <div class="ad-modal">
        <p class="ad-modal-title">// SOFT DELETE DEVELOPER</p>
        <div class="ad-warn-box">
          <p><strong>Irreversible action</strong> — soft-deletes account, nulls PII, forces suspension. Agents become orphaned.</p>
        </div>
        <label class="ad-label">Reason * (min 20 chars)</label>
        <textarea v-model="actionReason" class="ad-input" rows="3" placeholder="Describe why this account is being deleted…"></textarea>
        <label class="ad-label">Type the developer's email to confirm *</label>
        <input v-model="confirmEmail" class="ad-input" :placeholder="redactEmail(actionTarget.email)" />
        <p v-if="actionValidationError" class="ad-modal-error" role="alert"><Icon name="mdi:alert" /> {{ actionValidationError }}</p>
        <div class="ad-modal-actions">
          <button class="ad-btn ad-btn-ghost" @click="showDeleteModal = false">Cancel</button>
          <button
            class="ad-btn ad-btn-danger"
            :disabled="actionReason.length < 20 || confirmEmail !== actionTarget.email || actionLoading"
            @click="confirmDelete"
          >
            {{ actionLoading ? 'Deleting…' : 'Soft Delete' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- §pass51 P48 — Bundle quota editor -->
  <DevQuotaModal
    :show="showQuotaModal"
    :developer-id="quotaTargetDev?.id ?? null"
    :developer-email="quotaTargetDev?.email"
    @close="closeQuota"
  />

  <!-- AD1 (audit 2026-05-07): themed reinstate + verify-email confirms -->
  <ConfirmActionModal
    :show="showReinstateModal"
    title="// REINSTATE DEVELOPER"
    :message="reinstateTarget
      ? `Reinstate <strong>${redactEmail(reinstateTarget.email)}</strong>? Their previously-cascaded agents will be re-enrolled (mTLS + TEG reactivated).`
      : ''"
    tone="primary"
    confirm-text="Reinstate"
    busy-text="Reinstating…"
    :busy="reinstateBusy"
    @close="showReinstateModal = false"
    @confirm="reinstate"
  />

  <ConfirmActionModal
    :show="showVerifyEmailModal"
    title="// FORCE EMAIL VERIFY"
    :message="verifyEmailTarget
      ? `Manually mark <strong>${redactEmail(verifyEmailTarget.email)}</strong> as verified? Bypasses the email-confirmation flow — only use when you've validated identity out-of-band.`
      : ''"
    tone="warn"
    confirm-text="Verify"
    busy-text="Verifying…"
    :busy="verifyEmailBusy"
    @close="showVerifyEmailModal = false"
    @confirm="forceEmailVerify"
  />
</div>
</template>

<style scoped>
/* ── Layout ─────────────────────────────────────────────── */
.ad {
  padding: 24px 32px 48px;
  color: var(--nc-text, #e2e8f0);
  position: relative;
  min-height: calc(100vh - 48px);
  /* Section 30 polish (2026-05-07): theme-aware accent tokens. Replaces
     hardcoded 0,210,210 / #00d2d2 literals so body.theme-sovereign cycles
     them to red without per-rule overrides. */
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
}
.ad-ambient {
  position: absolute; inset: 0; pointer-events: none; overflow: hidden; z-index: 0;
}
.ad-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}
.ad-glow { position: absolute; width: 600px; height: 600px; border-radius: 50%; filter: blur(120px); opacity: 0.15; }
.ad-glow-1 { top: -100px; right: -200px; background: radial-gradient(circle, var(--cyan) 0%, transparent 70%); }
.ad-glow-2 { bottom: -200px; left: -200px; background: radial-gradient(circle, #7c3aed 0%, transparent 70%); }

/* ── Hero ───────────────────────────────────────────────── */
.ad-hero { position: relative; z-index: 1; margin-bottom: 20px; }
.ad-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--nc-primary, #00d2d2);
  padding: 4px 10px; border: 1px solid rgba(var(--cyan-rgb), 0.3);
  border-radius: 4px; margin-bottom: 10px;
}
.ad-chip-dot { width: 6px; height: 6px; background: var(--cyan); border-radius: 50%; box-shadow: 0 0 8px var(--cyan); }
.ad-h1 { font-size: 28px; font-weight: 700; margin: 0 0 4px 0; letter-spacing: -0.02em; }
.ad-accent { color: var(--nc-primary, #00d2d2); }
.ad-lead { color: #94a3b8; font-size: 13px; margin: 0; }

/* ── Tab bar (Build #5) ─────────────────────────────────── */
.ad-tabbar-wrap {
  position: relative;
  z-index: 1;
  padding: 0 32px 18px;
  max-width: 1280px;
  margin: 0 auto;
}
.ad-tabbar {
  display: inline-flex;
  gap: 4px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 8px;
  padding: 4px;
}
.ad-tabbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: transparent;
  border: none;
  border-radius: 5px;
  padding: 8px 16px;
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.15s;
}
.ad-tabbar-btn:hover {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(var(--nc-primary-rgb), 0.06);
}
.ad-tabbar-btn--active {
  background: rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(var(--nc-primary-rgb), 1);
  box-shadow: inset 0 0 0 1px rgba(var(--nc-primary-rgb), 0.35);
}
.ad-tabbar-icon {
  font-size: 0.95rem;
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.ad-tabbar-btn--active .ad-tabbar-icon { color: rgba(var(--nc-primary-rgb), 1); }
.ad-tabbar-label { font-size: inherit; }

/* ── KPI stats ──────────────────────────────────────────── */
.ad-stats-row {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px; margin-bottom: 20px; position: relative; z-index: 1;
}
.ad-stat {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-top: 2px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.ad-stat-ok { border-top-color: #22c55e; }
.ad-stat-cyan { border-top-color: var(--nc-primary, #00d2d2); }
.ad-stat-purple { border-top-color: #a855f7; }
.ad-stat-amber { border-top-color: #f59e0b; }
.ad-stat-bad { border-top-color: #ef4444; }
.ad-stat-muted { border-top-color: rgba(148, 163, 184, 0.3); }
.ad-stat-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  letter-spacing: 0.1em; text-transform: uppercase; color: #8291a8; }
.ad-stat-value { font-family: 'IBM Plex Mono', monospace; font-size: 22px; font-weight: 700; color: #e2e8f0; }

/* ── Toolbar (filter + search) ────────────────────────── */
.ad-toolbar {
  display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  margin-bottom: 16px; position: relative; z-index: 1;
}
.ad-filter-bar { display: flex; gap: 4px; flex-wrap: wrap; flex: 1; min-width: 0; }
.ad-fb-btn {
  background: rgba(15, 23, 42, 0.6); color: #94a3b8;
  border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  padding: 6px 10px; cursor: pointer; transition: all 120ms;
}
.ad-fb-btn:hover { border-color: rgba(var(--cyan-rgb), 0.4); color: #e2e8f0; }
.ad-fb-active {
  background: rgba(var(--cyan-rgb), 0.15); border-color: var(--nc-primary, #00d2d2); color: var(--nc-primary, #00d2d2);
}
.ad-fb-right { margin-left: auto; }

.ad-search-wrap { position: relative; min-width: 240px; }
.ad-search {
  width: 100%; padding: 6px 26px 6px 10px;
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px; color: #e2e8f0; font-size: 12px;
}
.ad-search:focus { outline: none; border-color: var(--nc-primary, #00d2d2); }
.ad-search-clear {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 16px;
}
.ad-toggle-btn {
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.08);
  color: #94a3b8; padding: 6px 10px; border-radius: 4px;
  font-size: 11px; font-family: 'IBM Plex Mono', monospace; cursor: pointer;
}

/* ── Errors / spinners ─────────────────────────────────── */
.ad-error {
  padding: 10px 14px; background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px;
  color: #fca5a5; margin-bottom: 16px; font-size: 13px;
}
.ad-center { display: flex; justify-content: center; align-items: center; padding: 40px; }
.ad-spinner { width: 28px; height: 28px; border: 3px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: var(--nc-primary, #00d2d2); border-radius: 50%; animation: ad-spin 1s linear infinite; }
@keyframes ad-spin { to { transform: rotate(360deg); } }

/* ── Table ──────────────────────────────────────────────── */
.ad-table-wrap {
  background: rgba(15, 23, 42, 0.5); border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px; overflow: hidden; position: relative; z-index: 1;
}
.ad-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ad-table thead th {
  background: rgba(15, 23, 42, 0.8); padding: 10px 12px; text-align: left;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase; color: #8291a8;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.ad-table tbody td { padding: 10px 12px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); vertical-align: middle; }
.ad-row { cursor: pointer; transition: background 100ms; }

/* Phase 6.5: skeleton placeholder rows during loading so the table never
   appears blank — gives immediate feedback that 1000+ developers are loading */
.ad-row-skeleton { cursor: default; }
.ad-row-skeleton td { padding: 12px 8px; }
.ad-skeleton-row {
  height: 16px;
  border-radius: 3px;
  background: linear-gradient(90deg,
    rgba(255,255,255,0.04) 0%,
    rgba(255,255,255,0.08) 50%,
    rgba(255,255,255,0.04) 100%);
  background-size: 200% 100%;
  animation: ad-shimmer 1.4s ease-in-out infinite;
}
@keyframes ad-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Phase 6.5b: explicit loading banner (defensive — visible even if table collapses) */
.ad-loading-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  margin-bottom: 8px;
  background: rgba(var(--cyan-rgb), 0.06);
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 6px;
  color: var(--nc-primary, #00d2d2);
  font-size: 12px;
  font-family: 'IBM Plex Mono', monospace;
}
.ad-spinner-inline {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%;
  animation: ad-spin 0.8s linear infinite;
}
@keyframes ad-spin {
  to { transform: rotate(360deg); }
}
.ad-row:hover { background: rgba(var(--cyan-rgb), 0.04); }

.ad-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  background: linear-gradient(135deg, #0ea5e9 0%, #7c3aed 100%);
  color: white; display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700;
}
.ad-name { color: #e2e8f0; font-weight: 500; }
.ad-email { color: #94a3b8; font-family: 'IBM Plex Mono', monospace; font-size: 11px; }
.ad-num { text-align: right; font-variant-numeric: tabular-nums; color: #cbd5e1; }
.ad-dim { color: #8291a8; font-size: 11px; }

/* Status badges */
.ad-sb {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.ad-sb-active { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
.ad-sb-admin { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); }
.ad-sb-operator { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
.ad-sb-unverified { background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); }
.ad-sb-suspended { background: rgba(251, 146, 60, 0.15); color: #fb923c; border: 1px solid rgba(251, 146, 60, 0.3); }
.ad-sb-deleted { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }

.ad-icon-on { color: #22c55e; }
.ad-icon-off { color: #475569; }

/* Row actions */
.ad-row-actions { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
.ad-btn {
  background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1; padding: 6px 12px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; cursor: pointer;
  transition: all 120ms;
}
.ad-btn:hover:not(:disabled) { border-color: var(--nc-primary, #00d2d2); color: var(--nc-primary, #00d2d2); }
.ad-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ad-btn-sm { padding: 4px 8px; font-size: 10px; }
.ad-btn-ghost { background: transparent; }
.ad-btn-good { background: rgba(34, 197, 94, 0.1); border-color: rgba(34, 197, 94, 0.3); color: #4ade80; }
.ad-btn-warn { background: rgba(251, 146, 60, 0.1); border-color: rgba(251, 146, 60, 0.3); color: #fb923c; }
.ad-btn-danger { background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: #f87171; }
.ad-btn-cyan { background: rgba(var(--cyan-rgb), 0.1); border-color: rgba(var(--cyan-rgb), 0.3); color: var(--nc-primary, #00d2d2); }

.ad-empty { text-align: center; padding: 40px; color: #8291a8; }
.ad-pagination {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-top: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(15, 23, 42, 0.4);
}

/* ── Drawer ─────────────────────────────────────────────── */
.ad-drawer-overlay {
  position: fixed; top: 48px; right: 0; bottom: 0; left: 0;
  background: rgba(0, 0, 0, 0.5); backdrop-filter: blur(2px);
  z-index: 999; display: flex; justify-content: flex-end;
}
.ad-drawer {
  width: 680px; max-width: 100vw; height: 100%;
  background: #0f172a; border-left: 1px solid rgba(var(--cyan-rgb), 0.2);
  box-shadow: -20px 0 40px rgba(0, 0, 0, 0.5);
  display: flex; flex-direction: column; overflow: hidden;
}
.ad-drawer-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 18px 20px; border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.ad-drawer-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  color: var(--nc-primary, #00d2d2); letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 4px; }
.ad-drawer-title { font-size: 20px; font-weight: 700; margin: 0 0 2px 0; color: #e2e8f0; }
.ad-drawer-sub { color: #94a3b8; font-size: 12px; font-family: 'IBM Plex Mono', monospace; }
.ad-drawer-close {
  background: transparent; border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8; width: 32px; height: 32px; border-radius: 4px; font-size: 18px; cursor: pointer;
}
.ad-drawer-tabs {
  display: flex; gap: 2px; padding: 0 20px;
  background: rgba(15, 23, 42, 0.6); border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  overflow-x: auto;
}
.ad-drawer-tab {
  background: transparent; border: none; color: #94a3b8;
  padding: 10px 12px; font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap;
}
.ad-drawer-tab:hover { color: #e2e8f0; }
.ad-drawer-tab-active { color: var(--nc-primary, #00d2d2); border-bottom-color: var(--nc-primary, #00d2d2); }
.ad-count { background: rgba(255,255,255,0.08); padding: 1px 6px; border-radius: 8px; font-size: 9px; margin-left: 4px; }
.ad-drawer-body { flex: 1; overflow-y: auto; padding: 18px 20px; }
.ad-tab-pane { font-size: 13px; }
.ad-kv { display: grid; grid-template-columns: 140px 1fr; gap: 8px 16px; }
.ad-kv dt { color: #8291a8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; }
.ad-kv dd { color: #e2e8f0; margin: 0; }
.ad-bio { white-space: pre-wrap; }
.ad-list { margin: 0; padding-left: 18px; }
.ad-sub-table { width: 100%; font-size: 11px; border-collapse: collapse; }
.ad-sub-table th { text-align: left; padding: 6px 8px; color: #8291a8; font-size: 10px; text-transform: uppercase; }
.ad-sub-table td { padding: 6px 8px; border-top: 1px solid rgba(255, 255, 255, 0.04); }
.ad-mono { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #7dd3fc; }
.ad-activity-feed { list-style: none; padding: 0; margin: 0; }
.ad-activity-item { padding: 8px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
.ad-activity-type { color: var(--nc-primary, #00d2d2); font-family: 'IBM Plex Mono', monospace; font-size: 11px; margin-right: 8px; }
.ad-activity-time { color: #8291a8; font-size: 10px; }
.ad-activity-data { background: rgba(0, 0, 0, 0.3); padding: 6px; margin: 4px 0 0; border-radius: 4px; font-size: 10px; color: #94a3b8; overflow-x: auto; }
.ad-drawer-footer {
  display: flex; gap: 8px; padding: 12px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 23, 42, 0.6);
}

/* ── Modals ─────────────────────────────────────────────── */
.ad-overlay {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6);
  display: flex; justify-content: center; align-items: center; z-index: 1000;
}
.ad-modal {
  width: 420px; max-width: 92vw; background: #0f172a;
  border: 1px solid rgba(var(--cyan-rgb), 0.3); border-radius: 8px; padding: 20px;
}
.ad-modal-title { font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  color: var(--nc-primary, #00d2d2); letter-spacing: 0.1em; margin: 0 0 10px 0; }
.ad-modal-sub { color: #94a3b8; font-size: 13px; margin: 0 0 14px 0; }
.ad-label { display: block; color: #cbd5e1; font-size: 11px; font-family: 'IBM Plex Mono', monospace;
  text-transform: uppercase; letter-spacing: 0.08em; margin: 10px 0 4px 0; }
.ad-input {
  width: 100%; background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 4px;
  color: #e2e8f0; padding: 8px 10px; font-size: 12px; font-family: inherit;
  resize: vertical; box-sizing: border-box;
}
.ad-input:focus { outline: none; border-color: var(--nc-primary, #00d2d2); }
.ad-warn-box {
  background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 4px; padding: 10px 12px; margin-bottom: 12px;
  color: #fca5a5; font-size: 12px;
}
.ad-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
/* AD2/AD3/AD4 (audit 2026-05-07): inline modal validation banner. */
.ad-modal-error {
  margin-top: 10px;
  padding: 8px 12px;
  font-size: 12px;
  border-radius: 6px;
  background: rgba(239,68,68,0.1);
  border: 1px solid rgba(239,68,68,0.3);
  color: #fca5a5;
}

/* Permissions tab (Fix 1) */
.ad-perm-intro { color: #94a3b8; font-size: 12px; margin-bottom: 12px; line-height: 1.5; }
.ad-perm-intro code { background: rgba(var(--cyan-rgb), 0.08); padding: 1px 5px; border-radius: 3px; color: #7dd3fc; font-size: 11px; }
.ad-perm-grid { display: flex; flex-direction: column; gap: 8px; margin: 12px 0; }
.ad-perm-row {
  display: grid; grid-template-columns: 28px 1fr; gap: 10px;
  padding: 10px 12px; background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 6px;
  cursor: pointer; transition: border-color 120ms;
}
.ad-perm-row:hover { border-color: rgba(var(--cyan-rgb), 0.3); }
.ad-perm-row input[type="checkbox"] { width: 16px; height: 16px; margin-top: 3px; accent-color: var(--nc-primary, #00d2d2); cursor: pointer; }
.ad-perm-row strong { display: block; color: #e2e8f0; font-family: 'IBM Plex Mono', monospace; font-size: 12px; margin-bottom: 2px; }
.ad-perm-row p { color: #8291a8; font-size: 11px; margin: 0; line-height: 1.4; }
.ad-perm-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255, 255, 255, 0.06); }
</style>
