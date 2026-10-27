<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'

// ── PUSH LOGIN (phone as second factor) ──────────────────────────────────────────────────────
import { pushLoginApi } from '@/services/api/pushLogin'
const pushLoginEnabled = ref(false)
const pushLoginDeviceReady = ref(false)
const pushLoginBusy = ref(false)
const pushLoginMsg = ref('')
// §FESUITE (2026-10-05): the setting's read has a state. Before it answered, or after it failed, the card drew "Disabled"
// and an off switch over a setting it never read; now it says Loading… or that the read failed, and a registry without the
// route (404) shows no card at all. A failed refresh (the read after a change) keeps what was shown.
const pushLoginRead = ref<'loading' | 'ok' | 'failed' | 'absent'>('loading')

async function loadPushLogin() {
  if (pushLoginRead.value !== 'ok') pushLoginRead.value = 'loading'
  try {
    const s = await pushLoginApi.getSettings()
    pushLoginEnabled.value = s.push_login_enabled
    pushLoginDeviceReady.value = s.device_ready
    pushLoginRead.value = 'ok'
  } catch (e: any) {
    if (pushLoginRead.value !== 'ok') pushLoginRead.value = e?.response?.status === 404 ? 'absent' : 'failed'
  }
}

async function togglePushLogin(next: boolean) {
  pushLoginBusy.value = true; pushLoginMsg.value = ''
  try {
    await pushLoginApi.setSettings(next)
    pushLoginEnabled.value = next
    pushLoginMsg.value = next
      ? 'Sign-ins can now be approved from your phone.'
      : 'Phone approval disabled.'
  } catch (e: any) {
    pushLoginMsg.value = e?.response?.data?.detail || 'Could not change this setting.'
  } finally { pushLoginBusy.value = false; loadPushLogin() }
}
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { searchPlaces, PLACE_QUERY_MIN } from '@/services/api/geocode'
import MultiFrameConsole from '@/components/settings/MultiFrameConsole.vue'
import TwoFactorSettings from '@/components/auth/TwoFactorSettings.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ThemeStudio from '@/components/common/ThemeStudio.vue'
import NotificationsPanel from '@/components/settings/NotificationsPanel.vue'
// §DESKCHROME (2026-08-28): the notification LOG mounts here too — the SAME
// component Pocket renders at /pocket/notifications ("same source everything",
// Commander). Desktop's notification home is Settings; the phone keeps Pocket.
import PocketNotificationLog from '@/views/pocket/PocketNotificationLog.vue'
import InvitationsPanel from '@/components/settings/InvitationsPanel.vue'
import SpendApprovalsPanel from '@/components/settings/SpendApprovalsPanel.vue'
import { getRegistrationConfig } from '@/services/api/inviteCodes'
import UserAvatar from '@/components/common/UserAvatar.vue'
import McpAuditLogPanel from '@/components/admin/McpAuditLogPanel.vue'
import { useLogger } from '@/composables/useLogger'
import { useI18n } from '@/composables/useI18n'
import {
  accountService,
  ACCOUNT_DELETE_CONFIRMATION_PHRASE,
  type DeletionStatusResponse,
} from '@/services/api/account'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import '@/components/settings/tp-settings.css'
import { queryForTab, tabQueryAction } from '@/services/settingsTabQuery'

dayjs.extend(relativeTime)

const log = useLogger('Settings')
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const uiStore = useUIStore()
const { t, tp, locale: i18nLocale, availableLocales } = useI18n()

// ─── Tabs ───
type Tab = 'profile' | 'security' | 'preferences' | 'notifications' | 'api' | 'activity' | 'location' | 'devcard' | 'multiframe' | 'invitations' | 'approvals'
const activeTab = ref<Tab>('profile')

// §OPGUIDE-6 — Invitations tab: the viewer can administer codes (admin_support, or legacy is_admin); a tab for anyone
// else would 403 on every call. §FESUITE V0595: no longer only where registration needs a code; where it is open the
// panel says a code grants nothing until invite-only is on. beta_invite_required is PUBLIC config, one unauthenticated GET.
const betaInviteRequired = ref(false)
// §FESUITE V0595 (a console gap): every registry's admins get the tab; where registration is open the panel says that a
// code is asked for nowhere and grants nothing until invite-only is on (an open registry's admin could mint none before)
const canManageInvites = computed(
  () => authStore.isAdmin || !!authStore.user?.admin_support,
)
const tabs = computed(() => [
  // §FESUITE (2026-10-04, his word "settings ... needs some polish and maybe reordering"): the everyday tabs first
  // (who you are, how you sign in, what reaches you, how the console looks), then the developer and agent tools, then
  // where you appear (the Developer Card before the globe position it feeds), the multi-frame sessions and, for an
  // invite-gated registry, the invitations.
  { key: 'profile',     label: t('settingsView.tabs.profile'),     icon: 'mdi:account' },
  { key: 'security',    label: t('settingsView.tabs.security'),    icon: 'mdi:shield-lock' },
  // §SETPOLISH (2026-07-27): notifications get a first-class tab — the 42-row
  // matrix was drowning the Preferences tab (Commander: "preferences is cluttered").
  { key: 'notifications', label: t('settingsView.tabs.notifications'), icon: 'mdi:bell' },
  { key: 'preferences', label: t('settingsView.tabs.preferences'), icon: 'mdi:tune-variant' },
  { key: 'api',         label: t('settingsView.tabs.api'),         icon: 'mdi:key-variant' },
  // B3 (RBAC plan) — the spend step-up queue: agents' over-threshold spends park here
  // for this human's approve/deny. Every developer can own thresholded agents, so the
  // tab is unconditional; the panel itself explains + empty-states cleanly.
  // (its icon was 'mdi:gesture-tap-button', a name Icon.vue does not carry: the tab drew a blank)
  { key: 'approvals',   label: t('settingsView.tabs.approvals', 'Approvals'), icon: 'mdi:check-decagram' },
  { key: 'activity',    label: t('settingsView.tabs.activity'),    icon: 'mdi:radar' },
  // §V0064 DevCard v0.1 — passport identity transparency + consent.
  { key: 'devcard',     label: t('settingsView.tabs.devcard'),     icon: 'mdi:fingerprint' },
  { key: 'location',    label: t('settingsView.tabs.location'),    icon: 'mdi:earth' },
  /*
   * §FOREIGNDEV — this tab was admin-only, which made a panel whose whole
   * purpose is "hold a session on every registry you have an account on"
   * invisible to the developers it is for. Commander, 2026-08-21: "admin
   * gated? no dev usage? that makes the whole purpose of this pannel for devs
   * obsolet. thats wrong!" He is right: the gate was inherited from the relay
   * being admin-only, and the relay is no longer the only road (see
   * services/api/peerDirect.ts). Any developer gets the tab now.
   */
  { key: 'multiframe', label: t('settingsView.tabs.multiframe', 'Multi-Frame'), icon: 'mdi:layers' },
  // §OPGUIDE-6 — only when invite codes actually gate registration AND you can manage them.
  ...(canManageInvites.value
    ? [{ key: 'invitations', label: t('settingsView.tabs.invitations'), icon: 'mdi:ticket-confirmation-outline' }]
    : []),
])

function switchTab(key: string) {
  activeTab.value = key as Tab
  syncTabQuery(key)
  // §FESUITE (2026-10-04): on a phone the strip scrolls, and a tab opened by link (?tab=) could sit off screen with
  // nothing showing which one is open; bring it into the strip's view (nearest: no page scroll when already visible)
  void nextTick(() => document.querySelector('.st-tab-bar .st-tab.active')?.scrollIntoView?.({ inline: 'nearest', block: 'nearest' }))
  if (key === 'activity' && activityEvents.value.length === 0) loadActivity()
  if (key === 'location' && !locationForm.value.latitude) loadLocation()
}

// §FESUITE (2026-10-04): the address names the open tab (services/settingsTabQuery.ts). A click replaces ?tab=; a ?tab=
// this viewer cannot see gives way to the open tab; ?tab=invitations waits for the registration config, which decides
// whether that tab exists (loadInviteVisibility), instead of being judged against a list that cannot hold it yet.
const inviteReadDone = ref(false)
// The route this view was opened on: leaving Settings for a page with a ?tab= of its own (/organization?tab=members) fires
// the watcher below with THAT page's query before this view unmounts, and a replace then would rewrite the next page's
// address. Nothing here acts once the address is no longer this view's.
const ownPath = route.path
function syncTabQuery(key: string) {
  if (route.path !== ownPath || route.query.tab === key) return
  void router.replace({ query: queryForTab(route.query, key) })
}
function applyTabQuery(requested: unknown) {
  if (route.path !== ownPath) return
  const act = tabQueryAction(requested, tabs.value.map((tb) => tb.key), inviteReadDone.value ? [] : ['invitations'])
  if (act === 'open' && requested !== activeTab.value) switchTab(requested as string)
  else if (act === 'drop') syncTabQuery(activeTab.value)
}

// ─── Profile (editable — f035) ───
const profileLoading = ref(false)
const profileSaving = ref(false)
const profileSaveMsg = ref('')
const profileSaveOk = ref(false)
// §FESUITE (2026-10-05): the profile's read has a state. A failed read left this form empty, and Save then wrote the empty
// form over the profile (PUT /developers/me with every field blank); the form, the account details and the save bar wait
// for the read now, and a failed one says so with Try again.
const profileRead = ref<'loading' | 'ok' | 'failed'>('loading')

const profileForm = ref({
  display_name: '',
  bio: '',
  avatar_url: '',
  website_url: '',
  github_url: '',
  twitter_handle: '',
  company: '',
  timezone: '',
  profile_visibility: 'public',
})
const profileReadOnly = ref({
  name: '',
  email: '',
  is_verified: false,
  is_admin: false,
  created_at: '',
  last_login_at: '',
})
/** §FESUITE (the loading sweep): the fleet tiles wait for the summary's own read; until then, or after a failed one,
 *  a dash (the zero-filled summary said 0 agents and 0 balance). */
const tegRead = ref(false)
const tegSummary = ref({ total_liquid_balance: 0, total_staked_balance: 0, total_balance: 0, aggregate_reputation_score: 0, agent_count: 0, active_agent_count: 0 })

// Suffix formatter — keeps stat tiles readable at any scale.
// 1,279,213,352.75 → "1.28B"; 128,398.7 → "128.4K"; 42 → "42".
function formatAvt(n: number | string): string {
  const num = typeof n === 'string' ? parseFloat(n) : n
  if (!isFinite(num)) return '—'
  const abs = Math.abs(num)
  if (abs >= 1e12) return (num / 1e12).toFixed(2) + 'T'
  if (abs >= 1e9)  return (num / 1e9).toFixed(2) + 'B'
  if (abs >= 1e6)  return (num / 1e6).toFixed(2) + 'M'
  if (abs >= 1e3)  return (num / 1e3).toFixed(1) + 'K'
  return num.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}

const avatarInitials = computed(() => {
  const src = profileForm.value.display_name || profileReadOnly.value.name || profileReadOnly.value.email || '?'
  return src.split(/[\s@.]+/).map(w => w[0]).filter(Boolean).join('').slice(0, 2).toUpperCase()
})

// Tier label for the role-badge row. Mirrors UserAvatar's resolution.
const flareTierLabel = computed(() => {
  const t = authStore.user?.flare_tier
  if (!t) return ''
  return t[0]?.toUpperCase() + t.slice(1).replace(/_/g, ' ')
})

// §pass42 (2026-05-18) — Grouped by continent for readability in the <optgroup>
// select. UTC stays at top as a baseline.
const TIMEZONE_GROUPS: Array<{ label: string; zones: string[] }> = [
  { label: 'UTC', zones: ['UTC'] },
  { label: 'Americas', zones: [
    'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
    'America/Anchorage', 'America/Honolulu', 'America/Phoenix',
    'America/Toronto', 'America/Vancouver', 'America/Sao_Paulo', 'America/Argentina/Buenos_Aires',
    'America/Bogota', 'America/Lima', 'America/Mexico_City',
  ]},
  { label: 'Europe', zones: [
    'Europe/London', 'Europe/Dublin', 'Europe/Lisbon',
    'Europe/Paris', 'Europe/Berlin', 'Europe/Amsterdam', 'Europe/Brussels', 'Europe/Zurich',
    'Europe/Madrid', 'Europe/Rome', 'Europe/Prague', 'Europe/Warsaw', 'Europe/Stockholm',
    'Europe/Oslo', 'Europe/Copenhagen', 'Europe/Helsinki', 'Europe/Athens',
    'Europe/Istanbul', 'Europe/Moscow', 'Europe/Kiev',
  ]},
  { label: 'Africa', zones: [
    'Africa/Cairo', 'Africa/Lagos', 'Africa/Johannesburg', 'Africa/Nairobi',
  ]},
  { label: 'Asia', zones: [
    'Asia/Dubai', 'Asia/Karachi', 'Asia/Kolkata', 'Asia/Dhaka',
    'Asia/Bangkok', 'Asia/Singapore', 'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Seoul',
  ]},
  { label: 'Oceania', zones: [
    'Australia/Sydney', 'Australia/Melbourne', 'Australia/Perth', 'Australia/Brisbane',
    'Pacific/Auckland', 'Pacific/Fiji',
  ]},
]

// §pass42 (2026-05-18) — "Last saved" timestamp for sticky save bar
const profileLastSavedAt = ref<string | null>(null)
const profileLastSavedDisplay = ref('')
function refreshLastSavedDisplay() {
  if (profileLastSavedAt.value) {
    profileLastSavedDisplay.value = dayjs(profileLastSavedAt.value).fromNow()
  } else {
    profileLastSavedDisplay.value = ''
  }
}
// §FESUITE (the leave sweep): started in setup and never cleared, so every visit to Settings added one more for the tab's life
const lastSavedTimer = setInterval(refreshLastSavedDisplay, 60_000)
onUnmounted(() => clearInterval(lastSavedTimer))

// §pass42 (2026-05-18) — Live avatar preview (debounced)
const avatarPreviewUrl = ref('')
const avatarPreviewOk = ref<boolean | null>(null)
let avatarPreviewTimer: number | null = null
function scheduleAvatarPreview(url: string) {
  if (avatarPreviewTimer !== null) {
    window.clearTimeout(avatarPreviewTimer)
  }
  avatarPreviewOk.value = null
  avatarPreviewTimer = window.setTimeout(() => {
    avatarPreviewUrl.value = url
  }, 500)
}

async function loadProfile() {
  profileLoading.value = true
  if (profileRead.value !== 'ok') profileRead.value = 'loading'
  try {
    const [meRes, tegRes] = await Promise.allSettled([
      apiClient.get('/developers/me'),
      apiClient.get('/developers/me/teg-summary'),
    ])
    if (meRes.status === 'rejected') {
      log.warn('Profile read failed:', meRes.reason)
      if (profileRead.value !== 'ok') profileRead.value = 'failed'
    }
    if (meRes.status === 'fulfilled') {
      const d = meRes.value.data
      profileReadOnly.value = {
        name: d.name || '',
        email: d.email || '',
        is_verified: d.is_verified ?? false,
        is_admin: d.is_admin ?? false,
        created_at: d.created_at || '',
        last_login_at: d.last_login_at || '',
      }
      profileForm.value = {
        display_name: d.display_name || '',
        bio: d.bio || '',
        avatar_url: d.avatar_url || '',
        website_url: d.website_url || '',
        github_url: d.github_url || '',
        twitter_handle: d.twitter_handle || '',
        company: d.company || '',
        timezone: d.timezone || '',
        profile_visibility: d.profile_visibility || 'public',
      }
      profileRead.value = 'ok'
    }
    if (tegRes.status === 'fulfilled') {
      tegSummary.value = tegRes.value.data
      tegRead.value = true
    }
  } catch (e) {
    // an answer this page could not read is a failed read too, never an empty form
    log.warn('Profile load failed:', e)
    if (profileRead.value !== 'ok') profileRead.value = 'failed'
  } finally {
    profileLoading.value = false
  }
}

async function saveProfile() {
  if (profileRead.value !== 'ok') return   // never write a form this page did not read
  profileSaving.value = true
  profileSaveMsg.value = ''
  try {
    await apiClient.put('/developers/me', profileForm.value)
    profileSaveOk.value = true
    profileSaveMsg.value = t('settingsView.profile.saved', 'Profile saved')  // the bundles had it; the code said English
    profileLastSavedAt.value = new Date().toISOString()
    refreshLastSavedDisplay()
    setTimeout(() => { profileSaveMsg.value = '' }, 3000)
  } catch (e: any) {
    profileSaveOk.value = false
    profileSaveMsg.value = e?.response?.data?.detail || t('settingsView.profile.saveFailed', 'Save failed')
  } finally {
    profileSaving.value = false
  }
}

// §pass42 (2026-05-18) — clipboard helper for the account-info tiles
async function copyText(text: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    uiStore.showNotification?.({ type: 'success', title: 'Copied', message: text.slice(0, 80) })
  } catch (_err) {
    // best-effort; silent on permission denial
  }
}

// ─── Preferences (§SETPOLISH 2026-07-27) ───
// The old tab carried three dead controls: a "color mode" trio writing a
// tp_preferences localStorage blob NOTHING read (plus a 'midnight' root class
// with no CSS behind it), an animations toggle with no reader, and a 9-key
// notification blob PUT over the same developers.notification_prefs column
// the broadcast store owns — a second writer with a different shape. All
// gone. What remains is real: the brand Theme Studio, the ambient-background
// level below (read by ViewAmbient on every view), and the language picker.
// Everything applies instantly — no save bar.
const ambientOptions = computed(() => [
  { v: 'full' as const,   label: t('settingsView.preferences.bgFull'),   sub: t('settingsView.preferences.bgFullSub') },
  { v: 'subtle' as const, label: t('settingsView.preferences.bgSubtle'), sub: t('settingsView.preferences.bgSubtleSub') },
  { v: 'off' as const,    label: t('settingsView.preferences.bgOff'),    sub: t('settingsView.preferences.bgOffSub') },
])
// §ALERTS header strip (2026-10-06; his words "can we make the new announcement bar optional in the settings? i really
// like the led"): the strip at the top of every page. Per browser, like the background level; applies at once.
const headerStripOptions = computed(() => [
  { v: 'led' as const, label: t('settingsView.preferences.headerStripLed', 'LED ticker'),
    sub: t('settingsView.preferences.headerStripLedSub', 'The scrolling dot-matrix board (the default)') },
  { v: 'bar' as const, label: t('settingsView.preferences.headerStripBar', 'Announcement bar'),
    sub: t('settingsView.preferences.headerStripBarSub', 'One broadcast at a time, still, with open and mark read') },
])

// ─── API Keys ───
const apiKeys = ref<any[]>([])

// 2026-05-24 — paginate the API keys list at 50 per page so heavily-seeded
// sandbox / legacy developer accounts stay readable without losing keys 51+.
// Sort order: active before revoked; newest-first within each group.
const API_KEYS_PAGE_SIZE = 50
const apiKeysPage = ref(0)
const apiKeysSorted = computed(() => {
  const all = [...apiKeys.value]
  all.sort((a, b) => {
    const aActive = a.is_active !== false ? 0 : 1
    const bActive = b.is_active !== false ? 0 : 1
    if (aActive !== bActive) return aActive - bActive
    const aTs = a.created_at ? new Date(a.created_at).getTime() : 0
    const bTs = b.created_at ? new Date(b.created_at).getTime() : 0
    return bTs - aTs
  })
  return all
})
const apiKeysTotalPages = computed(() =>
  Math.max(1, Math.ceil(apiKeysSorted.value.length / API_KEYS_PAGE_SIZE)),
)
const apiKeysDisplay = computed(() => {
  const start = apiKeysPage.value * API_KEYS_PAGE_SIZE
  return apiKeysSorted.value.slice(start, start + API_KEYS_PAGE_SIZE)
})
const apiKeysPageRange = computed(() => {
  if (!apiKeysSorted.value.length) return { from: 0, to: 0 }
  const start = apiKeysPage.value * API_KEYS_PAGE_SIZE
  return {
    from: start + 1,
    to: Math.min(apiKeysSorted.value.length, start + API_KEYS_PAGE_SIZE),
  }
})
function apiKeysNextPage() {
  if (apiKeysPage.value + 1 < apiKeysTotalPages.value) apiKeysPage.value++
}
function apiKeysPrevPage() {
  if (apiKeysPage.value > 0) apiKeysPage.value--
}
// Keep the page index in range after a key gets revoked / created mid-flight.
watch(apiKeysTotalPages, (n) => {
  if (apiKeysPage.value >= n) apiKeysPage.value = Math.max(0, n - 1)
})
const showCreateKeyModal = ref(false)
const newKeyDesc = ref('')
// §FEPARITY-1 — AL-4 narrowing state
const newKeyScopeMode = ref<'full' | 'scoped'>('full')
const newKeyScopes = ref('')
const newKeyExpiresDays = ref<number | null>(null)
const createdKeyPlain = ref('')
const showCreatedKeyModal = ref(false)
const apiKeySaving = ref(false)

// §FESUITE (2026-10-05): the list's read has a state; a failed read said "No API keys yet", now it says the read failed.
// A failed refresh keeps the list that was shown.
const apiKeysRead = ref<'loading' | 'ok' | 'failed'>('loading')

async function loadApiKeys() {
  if (apiKeysRead.value !== 'ok') apiKeysRead.value = 'loading'
  try {
    // RFB1 (2026-07-24): the real routes live under /auth/api-keys — the old
    // /developers/me/apikeys path never existed and 404'd the whole panel.
    const res = await apiClient.get('/auth/api-keys')
    apiKeys.value = res.data.items || res.data || []
    apiKeysRead.value = 'ok'
  } catch (e) {
    log.warn('API key list read failed:', e)
    if (apiKeysRead.value !== 'ok') apiKeysRead.value = 'failed'
  }
}

async function createApiKey() {
  if (!newKeyDesc.value.trim()) return
  apiKeySaving.value = true
  try {
    // §FEPARITY-1: canonical OBJECT form (FLOW 9 union) — carries the AL-4
    // narrowing the bare-string shape structurally could not express.
    const body: Record<string, unknown> = { key_name: newKeyDesc.value.trim() }
    if (newKeyScopeMode.value === 'scoped') {
      const scopes = newKeyScopes.value.split(',').map(s => s.trim()).filter(Boolean)
      if (scopes.length) body.scopes = scopes
    }
    // v-model.number yields '' when the field is cleared — only a real number ships.
    if (typeof newKeyExpiresDays.value === 'number' && Number.isFinite(newKeyExpiresDays.value)) {
      body.expires_in_days = newKeyExpiresDays.value   // 0 passes through = non-expiring
    }
    const res = await apiClient.post('/auth/api-keys', body)
    const data = res.data
    apiKeys.value.push(data.api_key_info || data)
    createdKeyPlain.value = data.plain_api_key || ''
    showCreateKeyModal.value = false
    showCreatedKeyModal.value = true
    if (apiKeysRead.value !== 'ok') void loadApiKeys()   // the list was never read: read it now, never show the new key alone
    newKeyDesc.value = ''
    newKeyScopeMode.value = 'full'
    newKeyScopes.value = ''
    newKeyExpiresDays.value = null
  } catch (e: any) {
    uiStore.showError('Create Failed', e?.response?.data?.detail || 'Failed to create key')
  } finally {
    apiKeySaving.value = false
  }
}

// ST1 (audit 2026-05-07): replaced native confirm() with themed ConfirmActionModal.
// Revoking an API key is destructive (any external system using the key loses
// registry access immediately) — deserves a real modal that names the key being
// revoked and uses danger tone.
const showRevokeKeyModal = ref(false)
const keyToRevoke = ref<any>(null)
const revokeKeyBusy = ref(false)

function revokeKey(key: any) {
  keyToRevoke.value = key
  showRevokeKeyModal.value = true
}

async function executeRevokeKey() {
  const key = keyToRevoke.value
  if (!key) return
  revokeKeyBusy.value = true
  try {
    await apiClient.delete(`/auth/api-keys/${key.id}`)
    apiKeys.value = apiKeys.value.filter(k => k.id !== key.id)
    showRevokeKeyModal.value = false
    keyToRevoke.value = null
    uiStore.showSuccess?.('Key Revoked', `${key.description || 'API key'} can no longer access the registry.`)
  } catch (e) {
    uiStore.showError('Revoke Failed', 'Failed to revoke key')
  } finally {
    revokeKeyBusy.value = false
  }
}

function copyKey() {
  if (!createdKeyPlain.value) return
  navigator.clipboard.writeText(createdKeyPlain.value)
    .then(() => uiStore.showSuccess('Copied', 'API key copied to clipboard'))
    .catch(() => {})
}

// ─── Activity (real — /developers/me/activity + /notifications/unread) ───
const activityEvents = ref<any[]>([])
const activityLoading = ref(false)
const activityFilter = ref('all')
const unreadBroadcasts = ref<any[]>([])
// §FESUITE (2026-10-05): both reads have a state. A failed event read said "No activity yet" and a failed broadcast read
// hid the admin broadcasts without a word; each says its read failed now, with Try again. A failed refresh keeps what was
// shown.
type ActRead = 'idle' | 'loading' | 'ok' | 'failed'
const activityRead = ref<ActRead>('idle')
const broadcastsRead = ref<ActRead>('idle')

const FILTER_PILLS = ['all', 'agent', 'token', 'governance', 'system']

const filteredEvents = computed(() => {
  if (activityFilter.value === 'all') return activityEvents.value
  const map: Record<string, string[]> = {
    agent:      ['AGENT_ONBOARDED', 'AGENT_UPDATED', 'AGENT_REVOKED'],
    token:      ['TOKEN_TRANSFER', 'STAKING_EVENT', 'REWARD_CYCLE'],
    governance: ['GOVERNANCE_PROPOSAL', 'GOVERNANCE_VOTE', 'DISPUTE_FILED', 'DISPUTE_RESOLVED'],
    system:     ['FEDERATION_REQUEST', 'FEDERATION_APPROVED', 'FEDERATION_SYNC', 'ATTESTATION_CREATED', 'CONTRACT_CREATED', 'CONTRACT_SIGNED', 'SYSTEM_EVENT'],
  }
  const types = map[activityFilter.value] || []
  return activityEvents.value.filter(e => types.includes(e.event_type || e.type || ''))
})

const EVENT_ICON_CLASS: Record<string, string> = {
  TOKEN_TRANSFER:      'st-event-type-transfer',
  STAKING_EVENT:       'st-event-type-stake',
  REWARD_CYCLE:        'st-event-type-stake',
  GOVERNANCE_PROPOSAL: 'st-event-type-governance',
  GOVERNANCE_VOTE:     'st-event-type-governance',
  DISPUTE_FILED:       'st-event-type-dispute',
  DISPUTE_RESOLVED:    'st-event-type-dispute',
  ATTESTATION_CREATED: 'st-event-type-attest',
}

// 2026-05-24 — emoji sweep: replaced emoji dict with mdi icon names. The render
// site in the Activity tab uses <Icon :name="EVENT_ICON[...] || 'mdi:flash'"/>
const EVENT_ICON: Record<string, string> = {
  AGENT_ONBOARDED:     'mdi:robot-happy',
  TOKEN_TRANSFER:      'mdi:cash-fast',
  STAKING_EVENT:       'mdi:lock',
  REWARD_CYCLE:        'mdi:gift-outline',
  GOVERNANCE_PROPOSAL: 'mdi:scroll-text',
  GOVERNANCE_VOTE:     'mdi:vote-outline',
  DISPUTE_FILED:       'mdi:alert',
  DISPUTE_RESOLVED:    'mdi:check-decagram',
  FEDERATION_REQUEST:  'mdi:earth',
  FEDERATION_SYNC:     'mdi:sync',
  ATTESTATION_CREATED: 'mdi:shield-star',
  CONTRACT_CREATED:    'mdi:file-document',
  CONTRACT_SIGNED:     'mdi:draw-pen',
  AGENT_REVOKED:       'mdi:cancel',
  SYSTEM_EVENT:        'mdi:flash',
}

async function loadActivity() {
  activityLoading.value = true
  if (activityRead.value !== 'ok') activityRead.value = 'loading'
  if (broadcastsRead.value !== 'ok') broadcastsRead.value = 'loading'
  try {
    const [evRes, notifRes] = await Promise.allSettled([
      apiClient.get('/developers/me/activity', { params: { limit: 50 } }),
      apiClient.get('/notifications/unread'),
    ])
    if (evRes.status === 'fulfilled') {
      activityEvents.value = evRes.value.data.events || evRes.value.data.items || []
      activityRead.value = 'ok'
    } else {
      log.warn('Activity read failed:', evRes.reason)
      if (activityRead.value !== 'ok') activityRead.value = 'failed'
    }
    if (notifRes.status === 'fulfilled') {
      unreadBroadcasts.value = notifRes.value.data.notifications || notifRes.value.data || []
      broadcastsRead.value = 'ok'
    } else {
      log.warn('Unread broadcasts read failed:', notifRes.reason)
      if (broadcastsRead.value !== 'ok') broadcastsRead.value = 'failed'
    }
  } catch (e) {
    // an answer this page could not read is a failed read too, never "no activity"
    log.warn('Activity load failed:', e)
    if (activityRead.value !== 'ok') activityRead.value = 'failed'
    if (broadcastsRead.value !== 'ok') broadcastsRead.value = 'failed'
  } finally {
    activityLoading.value = false
  }
}

async function markRead(id: number) {
  try {
    await apiClient.post(`/notifications/${id}/read`)
    unreadBroadcasts.value = unreadBroadcasts.value.filter(n => n.id !== id)
  } catch { /* expected */ }
}

function formatTs(ts: string) {
  if (!ts) return ''
  const t = ts.endsWith('Z') ? ts : ts + 'Z'
  return dayjs(t).fromNow()
}

function fmtType(t: string) {
  return (t || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ─── Location (AgentWorld) ───
const locationForm = ref({ latitude: '', longitude: '', location_label: '' })
// §FESUITE (2026-10-05): the coordinates' read has a state; a failed read says so instead of an empty form (which reads
// as "no location set" and invites a save over the one that is set)
const locationRead = ref<'loading' | 'ok' | 'failed'>('loading')
const locationSaving = ref(false)
const locationSaved = ref(false)
const geocodeQuery = ref('')
const geocodeResults = ref<{ label: string; lat: number; lng: number }[]>([])
const geocodeLoading = ref(false)
// §FESUITE V0578: a failed (502) or switched-off (404) search reached .map as an error body, threw and became [], which
// drew what an answered search with no place draws: nothing at all. searchPlaces (agentvault2-b2's, the card editor's)
// says which it was; 'idle' before a search and after a pick.
const geocodeState = ref<'idle' | 'none' | 'off' | 'failed'>('idle')
let geocodeSeq = 0

async function loadLocation() {
  if (locationRead.value !== 'ok') locationRead.value = 'loading'
  try {
    const r = await apiClient.get('/developers/me')
    const d = r.data
    locationForm.value = {
      latitude: d.latitude != null ? String(d.latitude) : '',
      longitude: d.longitude != null ? String(d.longitude) : '',
      location_label: d.location_label || '',
    }
    locationRead.value = 'ok'
  } catch (e) {
    log.warn('Location load failed:', e)
    if (locationRead.value !== 'ok') locationRead.value = 'failed'   // a failed refresh keeps what was shown
  }
}

async function saveLocation() {
  const lat = parseFloat(locationForm.value.latitude)
  const lng = parseFloat(locationForm.value.longitude)
  if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
    uiStore.showError('Invalid Coordinates', 'Check latitude (−90–90) and longitude (−180–180)')
    return
  }
  locationSaving.value = true
  locationSaved.value = false
  try {
    await apiClient.put('/agents/locations/me', { latitude: lat, longitude: lng, location_label: locationForm.value.location_label || null })
    locationSaved.value = true
    setTimeout(() => { locationSaved.value = false }, 4000)
  } catch (e: any) {
    uiStore.showError('Save Failed', e?.response?.data?.detail || 'Failed to save location')
  } finally {
    locationSaving.value = false
  }
}

async function searchGeocode() {
  const q = geocodeQuery.value.trim()
  if (q.length < PLACE_QUERY_MIN) { geocodeResults.value = []; geocodeState.value = 'idle'; return }
  const seq = ++geocodeSeq   // an older search must not land over a newer one
  geocodeLoading.value = true
  try {
    const r = await searchPlaces(q)
    if (seq !== geocodeSeq) return
    geocodeResults.value = r.kind === 'found' ? r.places : []
    geocodeState.value = r.kind === 'found' ? 'idle' : r.kind
  } finally { if (seq === geocodeSeq) geocodeLoading.value = false }
}

function applyGeocode(r: { label: string; lat: number; lng: number }) {
  locationForm.value.latitude = r.lat.toFixed(4)
  locationForm.value.longitude = r.lng.toFixed(4)
  locationForm.value.location_label = r.label.split(', ').slice(0, 2).join(', ')
  geocodeResults.value = []
  geocodeQuery.value = ''
  geocodeState.value = 'idle'
}

// ─── Lifecycle ───
// ─── W2 (2026-05-09) — Account deletion / GDPR Art. 17 erasure ───
// Replaces the old "Account deletion is unavailable during the beta period"
// placeholder with a real flow: typed-confirm + password re-auth + 14-day
// cooling-off. Anonymize-only (legal-hold / § 147 AO 10-year retention for
// fiat purchase records). See routers/account_deletion.py + Privacy § 4.5.

type DeletionUiState = 'idle' | 'confirming' | 'submitting' | 'cancelling' | 'pending'

// §LEGALKIT: the account export (GET /developers/me/export), saved as a file by the browser
const exportingData = ref(false)
const exportError = ref('')
async function exportMyData() {
  exportingData.value = true
  exportError.value = ''
  try {
    const res = await apiClient.get('/developers/me/export', { responseType: 'blob' })
    const blob = res.data instanceof Blob ? res.data : new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'theprotocol-account.json'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  } catch {
    exportError.value = t('settingsView.data.exportFailed', 'The export could not be prepared. Try again in a moment.')
  } finally {
    exportingData.value = false
  }
}
const deletionState = ref<DeletionUiState>('idle')

// §FESUITE (2026-10-04): "Sign out everywhere". The console's sign-out already ends every session of the account
// (POST /auth/logout bumps token_version), so this is the sidebar's Log out with the consequence said first; it lands
// on the login page the same way.
const signOutAllConfirm = ref(false)
const signingOutAll = ref(false)
async function signOutEverywhere() {
  signingOutAll.value = true
  try {
    await authStore.logout()
  } finally {
    signingOutAll.value = false
  }
  router.push('/login')
}
const deletionStatus = ref<DeletionStatusResponse | null>(null)
const deletionPassword = ref('')
const deletionTypedPhrase = ref('')
const deletionReason = ref('')
const deletionError = ref('')

const DELETION_PHRASE = ACCOUNT_DELETE_CONFIRMATION_PHRASE  // 'DELETE MY ACCOUNT'

const isPendingDeletion = computed(
  () => deletionStatus.value?.deletion_status === 'pending_deletion',
)

const deletionAnonymizesAtHuman = computed(() => {
  if (!deletionStatus.value?.anonymizes_at) return ''
  try {
    return dayjs(deletionStatus.value.anonymizes_at).format('MMM D, YYYY [at] HH:mm')
  } catch { return deletionStatus.value.anonymizes_at }
})

const deletionCountdown = computed(() => {
  if (!deletionStatus.value?.anonymizes_at) return ''
  try {
    return dayjs(deletionStatus.value.anonymizes_at).fromNow(true)
  } catch { return '' }
})

const deletionCanConfirm = computed(() => {
  return (
    deletionState.value === 'confirming' &&
    deletionTypedPhrase.value === DELETION_PHRASE &&
    deletionPassword.value.length >= 1
  )
})

async function loadDeletionStatus() {
  try {
    deletionStatus.value = await accountService.getDeletionStatus()
    if (deletionStatus.value?.deletion_status === 'pending_deletion') {
      deletionState.value = 'pending'
    } else {
      deletionState.value = 'idle'
    }
  } catch (e) {
    log.warn('Failed to load deletion status', e)
    // Fall back to authStore data — verify() forwards the same fields.
    const u = authStore.user
    if (u?.deletion_status === 'pending_deletion') {
      deletionStatus.value = {
        deletion_status: 'pending_deletion',
        deletion_requested_at: u.deletion_requested_at || null,
        anonymizes_at: u.deletion_requested_at
          ? dayjs(u.deletion_requested_at).add(14, 'day').toISOString()
          : null,
        cooling_off_days: 14,
      }
      deletionState.value = 'pending'
    }
  }
}

function openDeletionConfirm() {
  deletionError.value = ''
  deletionPassword.value = ''
  deletionTypedPhrase.value = ''
  deletionReason.value = ''
  deletionState.value = 'confirming'
}

function cancelDeletionConfirm() {
  deletionError.value = ''
  deletionPassword.value = ''
  deletionTypedPhrase.value = ''
  deletionReason.value = ''
  deletionState.value = 'idle'
}

async function submitDeletionRequest() {
  if (!deletionCanConfirm.value) return
  deletionError.value = ''
  deletionState.value = 'submitting'
  try {
    const ack = await accountService.requestDeletion({
      password: deletionPassword.value,
      confirmation: deletionTypedPhrase.value,
      reason: deletionReason.value.trim() || undefined,
    })
    deletionPassword.value = ''
    deletionTypedPhrase.value = ''
    deletionReason.value = ''
    uiStore.showSuccess?.('Deletion scheduled', ack.message)
    // §FESUITE: the banner on every page reads the signed-in profile, which only a reload refreshed
    await Promise.all([loadDeletionStatus(), authStore.refreshProfile()])
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.response?.data?.error?.detail || e?.message || 'Failed to schedule deletion.'
    deletionError.value = String(detail).slice(0, 400)
    deletionState.value = 'confirming'
  }
}

async function cancelPendingDeletion() {
  if (!isPendingDeletion.value) return
  deletionError.value = ''
  deletionState.value = 'cancelling'
  try {
    const ack = await accountService.cancelDeletion()
    uiStore.showSuccess?.('Deletion cancelled', ack.message)
    await Promise.all([loadDeletionStatus(), authStore.refreshProfile()])
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.response?.data?.error?.detail || e?.message || 'Failed to cancel deletion.'
    deletionError.value = String(detail).slice(0, 400)
    deletionState.value = 'pending'
  }
}

// ─── Developer Card (§V0064 DevCard v0.1 — transparency + consent) ───
import { devCardService, type DevCardPayload, type Disclosure } from '@/services/api/devCardService'

const dcOptOut = ref(false)
const dcBusy = ref(false)
const dcAgents = ref<{ did: string; name?: string }[]>([])
const dcAgentDid = ref('')
const dcPreview = ref<DevCardPayload | null>(null)
const dcDisclosures = ref<Disclosure[]>([])
const dcPassportOn = ref<boolean | null>(null)
// §FESUITE (2026-10-05): each read on this tab has a state. A consent the page never read was drawn as "opted in" (the
// ref's default), a failed disclosure log as "no one has seen your card" and a failed agent list as "no agents"; and the
// tab never read again after a failure. Now a read that has not answered says so (Loading… / ReadFailedNotice with
// Try again), the consent toggle shows only over a consent that was read, a failed refresh keeps what was shown, and the
// tab reads again each time it opens.
type DcRead = 'loading' | 'ok' | 'failed'
const dcConsentRead = ref<DcRead>('loading')
const dcLogRead = ref<DcRead>('loading')
const dcAgentsRead = ref<DcRead>('loading')
let dcLoading = false

async function dcReadConsent() {
  if (dcConsentRead.value !== 'ok') dcConsentRead.value = 'loading'
  try {
    dcOptOut.value = (await devCardService.getConsent()).passport_opt_out
    dcConsentRead.value = 'ok'
  } catch (e) {
    log.warn('Developer card consent read failed:', e)
    if (dcConsentRead.value !== 'ok') dcConsentRead.value = 'failed'
  }
}

async function dcReadLog() {
  if (dcLogRead.value !== 'ok') dcLogRead.value = 'loading'
  try {
    dcDisclosures.value = (await devCardService.disclosures()).disclosures
    dcLogRead.value = 'ok'
  } catch (e) {
    log.warn('Developer card disclosure log read failed:', e)
    if (dcLogRead.value !== 'ok') dcLogRead.value = 'failed'
  }
}

async function dcReadCorridor() {
  try {
    // the registry card is authoritative for venue/passport capability (§V0064)
    const r = await fetch('/.well-known/registry-card.json')
    const card = await r.json()
    dcPassportOn.value = !!card?.fees?.exchange?.passport_enabled
  } catch { dcPassportOn.value = null }   // unknown: the chip is not drawn
}

async function dcReadAgents() {
  if (dcAgentsRead.value !== 'ok') dcAgentsRead.value = 'loading'
  try {
    const { data } = await apiClient.get('/developers/me/agents', { params: { limit: 100 } })
    const arr = Array.isArray(data) ? data : (data?.agents || [])
    dcAgents.value = arr.map((a: any) => ({ did: a.did, name: a.name || a.card_data?.name }))
    dcAgentsRead.value = 'ok'
    if (dcAgents.value.length === 1 && !dcAgentDid.value) { dcAgentDid.value = dcAgents.value[0].did; void dcLoadPreview() }
  } catch (e) {
    log.warn('Developer card agent list read failed:', e)
    if (dcAgentsRead.value !== 'ok') dcAgentsRead.value = 'failed'
  }
}

async function dcLoad() {
  if (dcLoading) return
  dcLoading = true
  try {
    await Promise.all([dcReadConsent(), dcReadLog(), dcReadCorridor(), dcReadAgents()])
  } finally { dcLoading = false }
}

async function dcLoadPreview() {
  if (!dcAgentDid.value) return
  try {
    const res = await devCardService.preview(dcAgentDid.value)
    dcPreview.value = res.payload
    dcOptOut.value = res.passport_opt_out
    dcConsentRead.value = 'ok'   // the preview answers the consent too
  } catch (e: any) {
    uiStore.showError('Preview failed', e?.response?.data?.detail || e?.message)
  }
}

async function dcToggleConsent() {
  dcBusy.value = true
  try {
    const res = await devCardService.setConsent(!dcOptOut.value)
    dcOptOut.value = res.passport_opt_out
    uiStore.showSuccess(dcOptOut.value
      ? t('settingsView.devcard.optedOut')
      : t('settingsView.devcard.optedIn'))
  } catch (e: any) {
    uiStore.showError('Consent update failed', e?.response?.data?.detail || e?.message)
  } finally { dcBusy.value = false }
}

watch(activeTab, (tab) => { if (tab === 'devcard') void dcLoad() })

// §ENDPOLISH: ?tab= must also switch on SAME-ROUTE query changes (a push from
// /settings?tab=approvals to /settings?tab=notifications never remounts, so the
// onMounted read below alone leaves the old tab active — measured in the #155 survey).
watch(() => route.query.tab, (qt) => applyTabQuery(qt))

onMounted(() => {
  // §FEDEVENTS: honor ?tab= deep links (e.g. /settings?tab=multiframe from the
  // Event Ledger's connect hint) — validated against the tabs this viewer can
  // actually see, so a gated tab can't be activated by URL alone.
  applyTabQuery(route.query.tab)
  loadPushLogin()
  loadProfile()
  loadApiKeys()
  loadDeletionStatus()
  loadInviteVisibility()
})

/**
 * §OPGUIDE-6 — decides whether the Invitations tab exists at all.
 * Public endpoint, so it resolves regardless of admin state; failure is silent and
 * leaves the tab hidden, which is the safe direction (a missing tab is a puzzle,
 * a tab that 403s on every click is a bug report).
 */
async function loadInviteVisibility() {
  try {
    const cfg = await getRegistrationConfig()
    betaInviteRequired.value = !!cfg.beta_invite_required
  } catch (e) {
    log.debug('registration-config unavailable; Invitations tab stays hidden', e)
  } finally {
    // §FESUITE (2026-10-04): a ?tab=invitations deep link waited for this read: it opens now, or gives way to the open tab
    inviteReadDone.value = true
    if (route.query.tab === 'invitations') applyTabQuery('invitations')
  }
}
</script>

<template>
  <div class="st-page hm-module">
    <!-- §SETPOLISH (2026-07-27): no view-local ambient. DashboardLayout already
         mounts the standard ViewAmbient for every routed view; Settings was the
         one page hiding it behind an opaque page background (now transparent). -->

    <div class="st-content-wrap">

    <!-- Hero -->
    <section class="st-hero">
      <div class="st-hero-inner">
        <div class="st-hero-chip"><span class="st-hero-chip-dot"></span>ACCOUNT</div>
        <h1 class="st-hero-h1">
          <Icon name="mdi:tune-variant" />
          <span>{{ t('settingsView.title') }}</span>
        </h1>
        <p class="st-hero-lead">{{ t('settingsView.subtitle') }}</p>
      </div>
    </section>

    <!-- Tab bar -->
    <nav class="st-tab-bar" role="tablist" aria-label="Settings sections">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="st-tab"
        :class="{ active: activeTab === tab.key }"
        role="tab"
        :aria-selected="activeTab === tab.key"
        :data-tour="'set-tab-' + tab.key"
        @click="switchTab(tab.key)"
      >
        <Icon :name="tab.icon" />
        <span class="st-tab-label">{{ tab.label }}</span>
        <!-- §FESUITE (2026-10-04): a count is information, so it gets its own words: the pill is drawn for the eye and
             hidden from the name, which reads "Activity, 3 unread" rather than "Activity3" -->
        <span v-if="tab.key === 'api' && apiKeys.length" class="st-tab-badge" aria-hidden="true">{{ apiKeys.length }}</span>
        <span v-if="tab.key === 'api' && apiKeys.length" class="sr-only">, {{ tp('settingsView.tabs.apiCount', '{n} keys', { n: apiKeys.length }) }}</span>
        <span v-if="tab.key === 'activity' && unreadBroadcasts.length" class="st-tab-badge st-tab-badge-alarm" aria-hidden="true">{{ unreadBroadcasts.length }}</span>
        <span v-if="tab.key === 'activity' && unreadBroadcasts.length" class="sr-only">, {{ tp('settingsView.tabs.activityUnread', '{n} unread', { n: unreadBroadcasts.length }) }}</span>
      </button>
    </nav>

    <!-- Content -->
    <!-- §FESUITE (2026-10-04): the notifications tab keeps his side-by-side design (§FINDFIX F5) and gets the room for it:
         at the page's 860 px the matrix column was ~470 px and every row label wrapped to two or three lines -->
    <div class="st-content" :class="{ 'st-content--wide': activeTab === 'notifications' }">

      <!-- ══════════════════════════════════════ -->
      <!-- PROFILE TAB                           -->
      <!-- ══════════════════════════════════════ -->
      <div v-if="activeTab === 'profile'" class="st-col">

        <!-- §FESUITE (2026-10-05): the form, the account details and the save bar wait for the profile's own read; a failed
             read says so (an empty form here was one Save away from blanking the profile) -->
        <div v-if="profileRead === 'loading'" class="st-card st-read-loading" data-testid="st-profile-loading">{{ t('common.loading') }}</div>
        <div v-else-if="profileRead === 'failed'" class="st-card"><ReadFailedNotice :retry="loadProfile" /></div>
        <template v-else>
        <!-- §pass42 (2026-05-18) — Identity card: 2-col layout (avatar rail
             + form column on desktop, stacks on mobile). Manage-Flare CTA
             uses the new .st-role-flare-cta token class with chevron. -->
        <div class="st-card st-card-accent">
          <div class="st-card-title">{{ t('settingsView.profile.identity') }}</div>
          <div class="st-identity-grid">
            <div class="st-identity-rail">
              <UserAvatar
                :user="authStore.user"
                :avatar-url="profileForm.avatar_url || null"
                :display-name="profileForm.display_name || profileReadOnly.name || profileReadOnly.email"
                :initials="avatarInitials"
                :granted-at="authStore.user?.flare_granted_at || null"
                size="xl"
              />
              <h2 class="st-identity-name">{{ profileForm.display_name || profileReadOnly.name || '—' }}</h2>
              <p class="st-identity-email">{{ profileReadOnly.email }}</p>
              <div class="st-identity-badges">
                <span v-if="profileReadOnly.is_admin" class="st-role-badge st-role-admin">Admin</span>
                <span v-if="profileReadOnly.is_verified" class="st-role-badge st-role-verified"><Icon name="mdi:check-decagram" /> Verified</span>
                <span class="st-role-badge st-role-dev">{{ t('settingsView.profile.roleDeveloper') }}</span>
                <span v-if="authStore.user?.flare_tier" class="st-role-badge st-role-flare">
                  {{ flareTierLabel }} backer
                </span>
              </div>
              <router-link
                v-if="authStore.user?.flare_tier"
                to="/flare-manager"
                class="st-role-badge st-role-flare-cta st-identity-flare-cta"
              >
                {{ t('settingsView.profile.manageFlare') }}
                <Icon name="mdi:chevron-right" />
              </router-link>
            </div>

            <div class="st-identity-form">
              <!-- Editable fields -->
              <div class="st-form-row">
                <div class="st-form-group">
                  <label class="st-label">{{ t('settingsView.profile.displayName') }}</label>
                  <input v-model="profileForm.display_name" class="st-input" :placeholder="t('settingsView.profile.displayNamePlaceholder')" maxlength="100" />
                </div>
                <div class="st-form-group">
                  <label class="st-label">{{ t('settingsView.profile.company') }}</label>
                  <input v-model="profileForm.company" class="st-input" placeholder="TheProtocol" maxlength="255" />
                </div>
              </div>

              <div class="st-form-group">
                <div class="st-label-row">
                  <label class="st-label">{{ t('settingsView.profile.bio') }}</label>
                  <span class="st-char-counter" :class="{ 'st-char-counter-warn': (profileForm.bio?.length || 0) > 900 }">
                    {{ profileForm.bio?.length || 0 }} / 1000
                  </span>
                </div>
                <textarea v-model="profileForm.bio" class="st-textarea" :placeholder="t('settingsView.profile.bioPlaceholder')" rows="3" maxlength="1000"></textarea>
              </div>

              <div class="st-form-row">
                <div class="st-form-group">
                  <label class="st-label">{{ t('settingsView.profile.timezone') }}</label>
                  <select v-model="profileForm.timezone" class="st-select" :aria-label="t('settingsView.profile.timezone')">
                    <option value="">— {{ t('common.select') }} —</option>
                    <optgroup v-for="group in TIMEZONE_GROUPS" :key="group.label" :label="group.label">
                      <option v-for="tz in group.zones" :key="tz" :value="tz">{{ tz }}</option>
                    </optgroup>
                  </select>
                </div>
                <div class="st-form-group">
                  <label class="st-label">{{ t('settingsView.profile.profileVisibility') }}</label>
                  <select v-model="profileForm.profile_visibility" class="st-select" :aria-label="t('settingsView.profile.profileVisibility')">
                    <option value="public">{{ t('settingsView.profile.visibilityPublic') }}</option>
                    <option value="team">{{ t('settingsView.profile.visibilityTeam') }}</option>
                    <option value="private">{{ t('settingsView.profile.visibilityPrivate') }}</option>
                  </select>
                </div>
              </div>

              <!-- Avatar URL field with live preview thumbnail -->
              <div class="st-form-group">
                <label class="st-label">{{ t('settingsView.profile.avatarUrl') }}</label>
                <div class="st-avatar-url-row">
                  <input
                    v-model="profileForm.avatar_url"
                    class="st-input"
                    :placeholder="t('settingsView.profile.avatarUrlPlaceholder')"
                    maxlength="500"
                    @input="scheduleAvatarPreview(profileForm.avatar_url)"
                  />
                  <div v-if="avatarPreviewUrl" class="st-avatar-url-thumb">
                    <img
                      :src="avatarPreviewUrl"
                      alt="Avatar preview"
                      @load="avatarPreviewOk = true"
                      @error="avatarPreviewOk = false"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Social links (Icon-based, replaces emoji) -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.profile.socialLinks') }}</div>

          <div class="st-social-row">
            <div class="st-social-icon st-social-icon-svg"><Icon name="mdi:web" /></div>
            <div class="st-social-input">
              <label class="st-label">{{ t('settingsView.profile.website') }}</label>
              <input v-model="profileForm.website_url" class="st-input" :placeholder="t('settingsView.profile.websiteUrlPlaceholder')" maxlength="500" />
            </div>
          </div>

          <div class="st-social-row">
            <div class="st-social-icon st-social-icon-svg"><Icon name="mdi:github" /></div>
            <div class="st-social-input">
              <label class="st-label">{{ t('settingsView.profile.github') }}</label>
              <input v-model="profileForm.github_url" class="st-input" :placeholder="t('settingsView.profile.githubUrlPlaceholder')" maxlength="200" />
            </div>
          </div>

          <div class="st-social-row">
            <div class="st-social-icon st-social-icon-svg"><Icon name="mdi:twitter" /></div>
            <div class="st-social-input">
              <label class="st-label">{{ t('settingsView.profile.twitter') }}</label>
              <input v-model="profileForm.twitter_handle" class="st-input" :placeholder="t('settingsView.profile.twitterHandlePlaceholder')" maxlength="100" />
            </div>
          </div>
        </div>
        </template>

        <!-- Fleet stats -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.profile.fleetStats') }}</div>
          <div class="st-stats-grid">
            <div class="st-stat-tile">
              <div class="st-stat-value">{{ tegRead ? tegSummary.agent_count : '—' }}</div>
              <div class="st-stat-label">{{ t('settingsView.profile.agents') }}</div>
            </div>
            <div class="st-stat-tile">
              <div class="st-stat-value">{{ tegRead ? tegSummary.active_agent_count : '—' }}</div>
              <div class="st-stat-label">{{ t('settingsView.profile.active') }}</div>
            </div>
            <div class="st-stat-tile">
              <div class="st-stat-value" :title="tegRead ? tegSummary.total_liquid_balance.toLocaleString(appLocale()) : undefined">{{ tegRead ? formatAvt(tegSummary.total_liquid_balance) : '—' }}</div>
              <div class="st-stat-label">{{ t('settingsView.profile.liquidAvt') }}</div>
            </div>
            <div class="st-stat-tile">
              <div class="st-stat-value" :title="tegRead ? tegSummary.total_staked_balance.toLocaleString(appLocale()) : undefined">{{ tegRead ? formatAvt(tegSummary.total_staked_balance) : '—' }}</div>
              <div class="st-stat-label">{{ t('settingsView.profile.stakedAvt') }}</div>
            </div>
          </div>
        </div>

        <template v-if="profileRead === 'ok'">
        <!-- §pass42 (2026-05-18) — Account info as tile grid (was flat rows);
             email + login name are click-to-copy. -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.profile.accountInfo') }}</div>
          <div class="st-info-grid">
            <button class="st-info-tile" type="button" @click="copyText(profileReadOnly.name)" :title="`Copy: ${profileReadOnly.name}`">
              <div class="st-info-label">{{ t('settingsView.profile.loginName') }}</div>
              <div class="st-info-value">{{ profileReadOnly.name || '—' }}</div>
              <Icon name="mdi:content-copy" class="st-info-copy" />
            </button>
            <button class="st-info-tile" type="button" @click="copyText(profileReadOnly.email)" :title="`Copy: ${profileReadOnly.email}`">
              <div class="st-info-label">{{ t('settingsView.profile.email') }}</div>
              <div class="st-info-value">{{ profileReadOnly.email || '—' }}</div>
              <Icon name="mdi:content-copy" class="st-info-copy" />
            </button>
            <div class="st-info-tile st-info-tile-static">
              <div class="st-info-label">{{ t('settingsView.profile.memberSince') }}</div>
              <div class="st-info-value">{{ profileReadOnly.created_at ? dayjs(profileReadOnly.created_at).format('MMMM D, YYYY') : '—' }}</div>
            </div>
            <div class="st-info-tile st-info-tile-static">
              <div class="st-info-label">{{ t('settingsView.profile.lastLogin') }}</div>
              <div class="st-info-value">{{ profileReadOnly.last_login_at ? formatTs(profileReadOnly.last_login_at) : '—' }}</div>
            </div>
          </div>
        </div>

        <!-- §pass42 (2026-05-18) — Sticky save bar with "last saved Xm ago" -->
        <div class="st-save-bar st-save-bar-sticky">
          <span class="st-save-meta">
            <span v-if="profileLastSavedDisplay" class="st-save-meta-ago">
              <Icon name="mdi:check" /> Saved {{ profileLastSavedDisplay }}
            </span>
          </span>
          <span class="st-save-msg" :class="profileSaveOk ? 'st-save-msg-ok' : 'st-save-msg-err'" role="status" data-testid="st-profile-msg">
            {{ profileSaveMsg }}
          </span>
          <button class="st-btn-primary" @click="saveProfile" :disabled="profileSaving">
            {{ profileSaving ? t('settingsView.profile.saving') : t('settingsView.profile.save') }}
          </button>
        </div>
        </template>
      </div>

      <!-- ══════════════════════════════════════ -->
      <!-- SECURITY TAB                          -->
      <!-- ══════════════════════════════════════ -->
      <div v-if="activeTab === 'security'" class="st-col">

        <!-- Password -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.security.password') }}</div>
          <div class="st-banner st-banner-warn">
            <span class="st-banner-icon"><Icon name="mdi:key-variant" /></span>
            <div>
              <strong>{{ t('settingsView.security.recoveryRequired') }}</strong> — {{ t('settingsView.security.recoveryHint') }}
            </div>
          </div>
          <button class="st-btn-ghost" style="margin-top:4px" data-testid="st-change-password" @click="router.push({ path: '/forgot-password', query: { recovery: '1' } })">
            {{ t('settingsView.security.changePasswordBtn') }}
          </button>
        </div>

        <!-- 2FA — keep original component, just wrap in st-card -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.security.twoFactorAuth') }}</div>
          <TwoFactorSettings />
        </div>

        <!-- PUSH LOGIN (2026-07-25): your phone as the second factor. Lives beside 2FA rather
             than replacing it — this is an additional route to the same door. -->
        <div v-if="pushLoginRead !== 'absent'" class="st-card" data-testid="st-pushlogin">
          <div class="st-card-title">Phone approval for sign-in</div>
          <!-- §FESUITE (2026-10-04): st-help, st-row and st-switch were never defined, so this card drew a browser-default
               paragraph and a bare checkbox; it uses the page's own card help and switch row now -->
          <p class="st-card-help">
            Approve sign-ins with your phone's fingerprint instead of typing a code. Stronger than a
            code: the approval is bound to this site and the phone shows where the request came from
            before you confirm it. Your existing two-factor settings are unaffected.
          </p>
          <div v-if="pushLoginRead === 'loading'" class="st-read-loading">{{ t('common.loading') }}</div>
          <ReadFailedNotice v-else-if="pushLoginRead === 'failed'" dense :retry="loadPushLogin" />
          <div v-else class="st-toggle-wrap">
            <div>
              <div class="st-toggle-label">{{ pushLoginEnabled ? 'Enabled' : 'Disabled' }}</div>
              <div v-if="!pushLoginDeviceReady" class="st-toggle-sub">
                Enrol fingerprint signing on your phone first (Pocket → Approvals).
              </div>
            </div>
            <label class="st-toggle">
              <input type="checkbox" :checked="pushLoginEnabled" :disabled="pushLoginBusy"
                     aria-label="Phone approval for sign-in"
                     @change="togglePushLogin(($event.target as HTMLInputElement).checked)" />
              <span class="st-toggle-track"></span>
            </label>
          </div>
          <p v-if="pushLoginMsg" class="st-card-help">{{ pushLoginMsg }}</p>
        </div>

        <!-- Sessions — honest empty state -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.security.activeSessions') }}</div>
          <!-- §FESUITE (2026-10-04): this said session management was "not yet available"; a sign-out already ends every
               session of the account (POST /auth/logout bumps token_version), so the card says so and offers it -->
          <p class="st-card-help">
            {{ t('settingsView.security.sessionsEverywhere', 'Signing out ends every session of this account at once: every browser, the app on your phone, and any login a script holds. API keys keep working until you revoke them on the API Keys tab.') }}
          </p>
          <div v-if="!signOutAllConfirm">
            <button class="nc-btn nc-btn-secondary" data-testid="st-signout-all" @click="signOutAllConfirm = true">
              <Icon name="mdi:logout" />&nbsp; {{ t('settingsView.security.signOutEverywhere', 'Sign out everywhere') }}
            </button>
          </div>
          <div v-else class="st-signout-confirm" role="group" :aria-label="t('settingsView.security.signOutEverywhere', 'Sign out everywhere')">
            <span class="st-card-help">{{ t('settingsView.security.signOutConfirm', 'This signs you out here too. Sign out everywhere?') }}</span>
            <button class="nc-btn nc-btn-danger" data-testid="st-signout-all-confirm" :disabled="signingOutAll" @click="signOutEverywhere">
              {{ signingOutAll ? t('settingsView.security.signingOut', 'Signing out…') : t('settingsView.security.signOutYes', 'Yes, sign out everywhere') }}
            </button>
            <button class="nc-btn nc-btn-ghost" :disabled="signingOutAll" @click="signOutAllConfirm = false">{{ t('common.cancel', 'Cancel') }}</button>
          </div>
        </div>

        <!-- Danger zone — W2 (2026-05-09) GDPR Art. 17 erasure flow.
             Three states render in here based on `deletionState`/`deletionStatus`:
               idle       → "Delete my account" CTA
               confirming → typed-phrase + password panel
               pending    → countdown + Cancel CTA
             Anonymize-only (legal-hold via § 147 AO requires retaining
             financial records). See routers/account_deletion.py. -->
        <!-- §LEGALKIT: Privacy § 6 (Art. 20 GDPR), the account export the policy promises -->
        <div class="st-card" data-testid="st-data-card">
          <div class="st-card-title"><Icon name="mdi:download" /> {{ t('settingsView.data.title', 'Your data') }}</div>
          <p class="st-card-help">{{ t('settingsView.data.body', 'Download everything this account holds as one JSON document. Secrets are never in it.') }}</p>
          <button class="nc-btn nc-btn-secondary" :disabled="exportingData" data-testid="st-export-data" @click="exportMyData">
            {{ exportingData ? t('settingsView.data.exporting', 'Preparing…') : t('settingsView.data.exportButton', 'Download my data') }}
          </button>
          <p v-if="exportError" class="st-danger-error">{{ exportError }}</p>
        </div>

        <div class="st-card st-card-danger">
          <div class="st-card-title-danger"><Icon name="mdi:alert-octagon" /> Danger Zone</div>

          <!-- STATE 1: idle (active account, no pending deletion) -->
          <div v-if="deletionState === 'idle'">
            <p class="st-danger-prose">
              Permanently delete your account. The action runs after a
              <strong>{{ deletionStatus?.cooling_off_days || 14 }}-day cooling-off period</strong> during which you can cancel.
              At the end of the cooling-off:
            </p>
            <ul class="st-danger-list">
              <li>All agents you own are revoked and their secrets wiped.</li>
              <li>The units your agents hold, liquid or locked, go to the frame treasury and are forfeited, because units cannot be redeemed (§ 9.2 of the Terms).</li>
              <li>Your profile (name, email, avatar, bio, flare customization) is anonymized.</li>
              <li>API keys and webhooks are deleted.</li>
              <li>
                Financial records (fiat purchases) are <strong>retained in anonymized form</strong> for 10 years per German tax law
                (§ 147 AO) — see <router-link :to="{ name: 'legal', params: { page: 'privacy' } }" target="_blank" rel="noopener">Privacy Policy § 4.5</router-link>
                and <router-link :to="{ name: 'legal', params: { page: 'terms' } }" target="_blank" rel="noopener">Terms § 13.9</router-link>.
              </li>
            </ul>
            <button class="nc-btn nc-btn-danger st-danger-btn" @click="openDeletionConfirm">
              <Icon name="mdi:trash-can-outline" />&nbsp; I want to delete my account
            </button>
          </div>

          <!-- STATE 2: confirming (typed-phrase + password panel, inline) -->
          <div v-else-if="deletionState === 'confirming' || deletionState === 'submitting'">
            <div class="st-banner st-banner-warn">
              <span class="st-banner-icon"><Icon name="mdi:alert" /></span>
              <span>
                <strong>Final confirmation.</strong> Type the phrase below and re-enter your password.
                You'll have <strong>{{ deletionStatus?.cooling_off_days || 14 }} days</strong> to cancel after submitting.
              </span>
            </div>

            <label class="st-label st-danger-label" for="st-delete-phrase">
              Type <code class="st-danger-code">{{ DELETION_PHRASE }}</code> to confirm:
            </label>
            <input
              id="st-delete-phrase"
              v-model="deletionTypedPhrase"
              class="nc-input st-danger-input"
              :placeholder="DELETION_PHRASE"
              autocomplete="off"
              spellcheck="false"
              :disabled="deletionState === 'submitting'"
            />

            <label class="st-label st-danger-label" for="st-delete-password">Re-enter your password:</label>
            <input
              id="st-delete-password"
              v-model="deletionPassword"
              class="nc-input st-danger-input"
              type="password"
              autocomplete="current-password"
              :disabled="deletionState === 'submitting'"
              @keyup.enter="submitDeletionRequest"
            />

            <label class="st-label st-danger-label" for="st-delete-reason">Reason (optional):</label>
            <input
              id="st-delete-reason"
              v-model="deletionReason"
              class="nc-input st-danger-input"
              maxlength="500"
              placeholder="Tell us why — helps us improve. Skipped is fine."
              :disabled="deletionState === 'submitting'"
            />

            <p v-if="deletionError" class="st-danger-error">{{ deletionError }}</p>

            <div class="st-danger-actions">
              <button
                class="nc-btn nc-btn-secondary"
                @click="cancelDeletionConfirm"
                :disabled="deletionState === 'submitting'"
              >
                Cancel
              </button>
              <button
                class="nc-btn nc-btn-danger"
                :disabled="!deletionCanConfirm || deletionState === 'submitting'"
                @click="submitDeletionRequest"
              >
                <Icon v-if="deletionState === 'submitting'" name="mdi:loading" class="st-danger-spin" />
                <Icon v-else name="mdi:trash-can-outline" />&nbsp;
                {{ deletionState === 'submitting' ? 'Submitting…' : `Confirm — start ${deletionStatus?.cooling_off_days || 14}-day countdown` }}
              </button>
            </div>
          </div>

          <!-- STATE 3: pending_deletion (cooling-off active) -->
          <div v-else-if="deletionState === 'pending' || deletionState === 'cancelling'">
            <div class="st-banner st-banner-warn st-danger-pending-banner">
              <span class="st-banner-icon"><Icon name="mdi:timer-sand" /></span>
              <span>
                <strong>Pending account deletion.</strong>
                Your account is scheduled for anonymization on
                <strong>{{ deletionAnonymizesAtHuman }}</strong>
                <span v-if="deletionCountdown">({{ deletionCountdown }} from now)</span>.
              </span>
            </div>
            <p class="st-danger-prose">
              You can still cancel — nothing irreversible has happened yet.
              After the cooling-off expires, your data will be wiped per the rules listed above.
            </p>
            <p v-if="deletionError" class="st-danger-error">{{ deletionError }}</p>
            <button
              class="nc-btn nc-btn-secondary st-danger-btn"
              :disabled="deletionState === 'cancelling'"
              @click="cancelPendingDeletion"
            >
              <Icon v-if="deletionState === 'cancelling'" name="mdi:loading" class="st-danger-spin" />
              <Icon v-else name="mdi:undo-variant" />&nbsp;
              {{ deletionState === 'cancelling' ? 'Cancelling…' : 'Cancel deletion → keep my account' }}
            </button>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════ -->
      <!-- PREFERENCES TAB                       -->
      <!-- ══════════════════════════════════════ -->
      <div v-if="activeTab === 'preferences'" class="st-col">
        <!-- §SETPOLISH (2026-07-27): three cards, all live-wired, no save bar.
             The dead color-mode/animations/auto-refresh controls and the second
             notification blob that used to sit at the bottom of this tab are
             gone; notifications now have their own tab. -->

        <!-- Brand Theme Studio — accent color via preset, hex, or HSL picker. -->
        <div class="st-card">
          <ThemeStudio />
        </div>

        <!-- Background & surfaces — governs the ViewAmbient layer on every view. -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.preferences.bgTitle') }}</div>
          <label class="st-label" style="margin-bottom:12px">{{ t('settingsView.preferences.bgHint') }}</label>
          <div class="st-theme-grid">
            <button
              v-for="opt in ambientOptions"
              :key="opt.v"
              class="st-theme-btn"
              :class="{ selected: uiStore.ambientMode === opt.v }"
              @click="uiStore.setAmbientMode(opt.v)"
            >
              <span class="st-bg-swatch" :data-level="opt.v" aria-hidden="true">
                <i></i><i></i><i></i>
              </span>
              <span>{{ opt.label }}</span>
              <span class="st-bg-swatch-sub">{{ opt.sub }}</span>
            </button>
          </div>
          <p class="st-hint" style="margin-top:12px">{{ t('settingsView.preferences.bgAccentNote') }}</p>
        </div>

        <!-- §ALERTS header strip: LED ticker (default) or announcement bar -->
        <div class="st-card" data-testid="st-header-strip">
          <div class="st-card-title">{{ t('settingsView.preferences.headerStripTitle', 'Header strip') }}</div>
          <label class="st-label" style="margin-bottom:12px">{{ t('settingsView.preferences.headerStripHint', 'What the strip at the top of every page shows: broadcasts for everyone, and for admins the alerts that are firing.') }}</label>
          <div class="st-theme-grid">
            <button
              v-for="opt in headerStripOptions"
              :key="opt.v"
              type="button"
              class="st-theme-btn"
              :class="{ selected: uiStore.headerStrip === opt.v }"
              :aria-pressed="uiStore.headerStrip === opt.v"
              :data-testid="'st-header-strip-' + opt.v"
              @click="uiStore.setHeaderStrip(opt.v)"
            >
              <span>{{ opt.label }}</span>
              <span class="st-bg-swatch-sub">{{ opt.sub }}</span>
            </button>
          </div>
        </div>

        <!-- Language picker (vue-i18n, 8 locales) -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.preferences.language') }}</div>
          <label for="settings-sel-1320" class="st-label" style="margin-bottom:12px">{{ t('settingsView.preferences.languageSubLabel') }}</label>
          <select id="settings-sel-1320" v-model="i18nLocale" class="st-select" style="max-width:320px">
            <option v-for="(name, code) in availableLocales" :key="code" :value="code">
              {{ name }}
            </option>
          </select>
          <p class="st-hint" style="margin-top:12px">
            {{ t('settingsView.preferences.languageHint') }}
          </p>
        </div>
      </div>

      <!-- ══════════════════════════════════════ -->
      <!-- NOTIFICATIONS TAB (§SETPOLISH)        -->
      <!-- ══════════════════════════════════════ -->
      <!-- §FINDFIX F5 (his design note 2026-08-29): the log and the setup sit
           SIDE BY SIDE on wide viewports — "this would give a better feeling
           then ontop of eachother" — stacking below the breakpoint. One
           component serves both surfaces — no desktop fork to drift. -->
      <div v-if="activeTab === 'notifications'" class="st-col st-nf-grid">
        <div class="st-card st-notif-log" data-testid="st-notif-log">
          <PocketNotificationLog embedded />
        </div>
        <div class="st-card">
          <NotificationsPanel />
        </div>
      </div>

      <!-- ══════════════════════════════════════ -->
      <!-- API KEYS TAB                          -->
      <!-- ══════════════════════════════════════ -->
      <div v-if="activeTab === 'api'" class="st-col">
        <div class="st-card">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
            <div class="st-card-title" style="margin:0">{{ t('settingsView.api.title') }}</div>
            <button class="st-btn-primary" style="padding:7px 16px;font-size:10px" data-tour="set-create-key" @click="showCreateKeyModal = true">+ {{ t('settingsView.api.createKey') }}</button>
          </div>

          <div v-if="apiKeysRead === 'loading'" class="st-read-loading" data-testid="st-keys-loading">{{ t('common.loading') }}</div>
          <ReadFailedNotice v-else-if="apiKeysRead === 'failed'" :retry="loadApiKeys" />
          <div v-else-if="apiKeys.length" data-tour="set-key-list">
            <div v-for="key in apiKeysDisplay" :key="key.id" class="st-key-row">
              <div class="st-key-prefix">{{ (key.key_prefix || 'avreg_') }}***</div>
              <div class="st-key-meta">
                <div class="st-key-desc">{{ key.description || key.name || 'Unnamed Key' }}</div>
                <div class="st-key-date">
                  Created {{ dayjs(key.created_at).format('MMM D, YYYY') }}
                  <span v-if="key.last_used_at"> · Last used {{ dayjs(key.last_used_at).fromNow() }}</span>
                  <!-- §FEPARITY-1: AL-4 fields, previously dropped end-to-end -->
                  · {{ (!key.scopes || key.scopes.includes('*')) ? 'full authority' : key.scopes.join(', ') }}
                  · {{ key.expires_at ? ('expires ' + dayjs(key.expires_at).format('MMM D, YYYY')) : 'never expires' }}
                </div>
              </div>
              <span class="st-key-badge" :class="key.is_active !== false ? 'st-key-badge-active' : 'st-key-badge-revoked'">
                {{ key.is_active !== false ? t('settingsView.api.active') : t('settingsView.api.revoked') }}
              </span>
              <button v-if="key.is_active !== false" class="st-btn-danger" style="padding:5px 12px;font-size:9px" @click="revokeKey(key)">{{ t('settingsView.api.revoke') }}</button>
            </div>

            <!-- 2026-05-24 — page navigation. Hidden when total fits one page. -->
            <div v-if="apiKeysTotalPages > 1" class="st-keys-pager">
              <button
                class="st-keys-pager-btn"
                :disabled="apiKeysPage <= 0"
                @click="apiKeysPrevPage"
                aria-label="Previous page"
              >
                <Icon name="mdi:chevron-left" /> Prev
              </button>
              <span class="st-keys-pager-info">
                <strong>Page {{ apiKeysPage + 1 }} of {{ apiKeysTotalPages }}</strong>
                <span class="st-keys-pager-range">·  keys {{ apiKeysPageRange.from }}–{{ apiKeysPageRange.to }} of {{ apiKeysSorted.length }}</span>
              </span>
              <button
                class="st-keys-pager-btn"
                :disabled="apiKeysPage + 1 >= apiKeysTotalPages"
                @click="apiKeysNextPage"
                aria-label="Next page"
              >
                Next <Icon name="mdi:chevron-right" />
              </button>
            </div>
          </div>

          <div v-else class="st-empty-state">
            <Icon name="mdi:key-outline" />
            <p>{{ t('settingsView.api.noKeys') }}</p>
            <p class="st-empty-hint">{{ t('settingsView.api.noKeysHint') }}</p>
          </div>
        </div>

        <!-- ─── MCP Audit Log section (2026-05-24, §pass68 personal surface) ─── -->
        <!-- Sibling card to the API Keys list above. Every MCP tool call performed
             with the keys above writes a row to security_audit_logs; this is where
             developers see that history without curl. -->
        <div class="st-card st-card-accent">
          <div class="st-card-title">
            <Icon name="mdi:shield-search" />
            MCP Audit Log
            <span class="st-card-title-badge">§pass68</span>
          </div>
          <p class="st-card-help">
            Every MCP tool call performed under your developer identity on this
            registry writes a row to <code>security_audit_logs</code>. The log is
            yours &mdash; admins cannot view it without writing a visible
            <code>admin_read_mcp_audit</code> row into your own history. Each
            registry keeps its own log; an API key created on Frame A only records
            to Frame A's audit table.
          </p>
          <McpAuditLogPanel scope="me" storage-key="settings-mcp" :page-size="15" />
        </div>
      </div>

      <!-- ══════════════════════════════════════ -->
      <!-- ACTIVITY TAB                          -->
      <!-- ══════════════════════════════════════ -->
      <div v-if="activeTab === 'activity'" class="st-col">

        <!-- Admin broadcasts -->
        <div v-if="unreadBroadcasts.length || broadcastsRead === 'failed'" class="st-card" data-testid="st-broadcasts">
          <div class="st-card-title"><Icon name="mdi:bullhorn" /> Admin Broadcasts <span v-if="unreadBroadcasts.length" class="st-tab-badge" style="margin-left:8px">{{ unreadBroadcasts.length }}</span></div>
          <ReadFailedNotice v-if="!unreadBroadcasts.length" dense :retry="loadActivity" />
          <div v-for="n in unreadBroadcasts" :key="n.id" class="st-notif-row st-notif-unread">
            <div class="st-notif-body">
              <div class="st-notif-title" :class="`st-notif-type-${n.notification_type || 'info'}`">{{ n.title }}</div>
              <div class="st-notif-sub">{{ n.message }}</div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px">
              <span class="st-notif-time">{{ formatTs(n.created_at) }}</span>
              <button class="st-btn-ghost" style="padding:4px 10px;font-size:9px" @click="markRead(n.id)">Dismiss</button>
            </div>
          </div>
        </div>

        <!-- Filter pills -->
        <div class="st-filter-pills">
          <button
            v-for="pill in FILTER_PILLS"
            :key="pill"
            class="st-pill"
            :class="{ active: activityFilter === pill }"
            @click="activityFilter = pill"
          >{{ pill }}</button>
          <button class="st-btn-ghost" style="padding:5px 12px;font-size:10px;margin-left:auto;display:inline-flex;gap:6px;align-items:center" @click="loadActivity" :disabled="activityLoading">
            <Icon name="mdi:refresh" :class="{ 'st-spin': activityLoading }" />
            {{ activityLoading ? 'Refreshing…' : 'Refresh' }}
          </button>
        </div>

        <div class="st-card">
          <!-- Loading skeleton -->
          <div v-if="activityLoading && !activityEvents.length">
            <div v-for="i in 6" :key="i" class="st-event-row st-skel-row">
              <div class="st-event-icon st-event-type-system st-skel-tile"></div>
              <div class="st-event-meta">
                <div class="st-skel-line st-skel-line-1"></div>
                <div class="st-skel-line st-skel-line-2"></div>
              </div>
            </div>
          </div>

          <!-- Events -->
          <div v-else-if="filteredEvents.length">
            <div v-for="ev in filteredEvents" :key="ev.id || ev.event_id" class="st-event-row">
              <div class="st-event-icon" :class="EVENT_ICON_CLASS[ev.event_type || ev.type] || 'st-event-type-system'">
                <Icon :name="EVENT_ICON[ev.event_type || ev.type] || 'mdi:flash'" />
              </div>
              <div class="st-event-meta">
                <div class="st-event-title">{{ ev.title || fmtType(ev.event_type || ev.type) }}</div>
                <div class="st-event-sub">{{ ev.description || (ev.data ? JSON.stringify(ev.data).slice(0, 80) : '') }}</div>
              </div>
              <div class="st-event-time">{{ formatTs(ev.created_at || ev.timestamp) }}</div>
            </div>
          </div>

          <ReadFailedNotice v-else-if="activityRead === 'failed'" :retry="loadActivity" />

          <!-- Empty -->
          <div v-else class="st-empty-state st-empty-state-activity">
            <Icon name="mdi:flash-outline" />
            <p>{{ t('settingsView.activity.noActivity') }}</p>
            <p class="st-empty-hint">{{ t('settingsView.activity.noActivityHint') }}</p>
          </div>
        </div>
      </div>

      <!-- ══════════════════════════════════════ -->
      <!-- AGENTWORLD TAB                        -->
      <!-- ══════════════════════════════════════ -->
      <div v-if="activeTab === 'location'" class="st-col">

        <!-- Hero banner -->
        <div class="st-card" style="background:linear-gradient(135deg,rgba(var(--nc-primary-rgb),0.07) 0%,rgba(0,20,50,0.6) 100%);border-color:rgba(var(--nc-primary-rgb),0.18);display:flex;align-items:center;gap:20px">
          <div class="st-location-badge"><Icon name="mdi:earth" /></div>
          <div style="flex:1">
            <div style="font-family:var(--st-mono);font-size:13px;font-weight:700;color:var(--st-cyan);margin-bottom:4px">{{ t('settingsView.location.title') }}</div>
            <div style="font-size:12px;color:var(--st-text-muted)">{{ t('settingsView.location.subtitle') }}</div>
          </div>
          <button class="st-btn-ghost" style="padding:7px 16px;font-size:10px;white-space:nowrap" @click="$router.push('/agentworld')">Open Globe →</button>
        </div>

        <!-- Geocode search -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.location.findLocation') }}</div>
          <div style="display:flex;gap:10px;margin-bottom:10px">
            <input
              v-model="geocodeQuery"
              class="st-input"
              placeholder="e.g. Frankfurt, Germany"
              @keydown.enter.prevent="searchGeocode"
            />
            <button class="st-btn-primary" style="white-space:nowrap;display:inline-flex;gap:6px;align-items:center" @click="searchGeocode" :disabled="geocodeLoading || geocodeQuery.trim().length < PLACE_QUERY_MIN" data-testid="st-geo-search">
              <Icon v-if="!geocodeLoading" name="mdi:magnify" />
              {{ geocodeLoading ? '…' : 'Search' }}
            </button>
          </div>

          <div v-if="geocodeResults.length" style="display:flex;flex-direction:column;gap:6px">
            <button
              v-for="(r, i) in geocodeResults"
              :key="i"
              @click="applyGeocode(r)"
              style="display:flex;align-items:baseline;gap:10px;padding:8px 12px;background:rgba(var(--nc-primary-rgb),0.03);border:1px solid rgba(var(--nc-primary-rgb),0.08);border-radius:6px;cursor:pointer;text-align:left;transition:background 0.15s"
              class="geocode-result-btn"
            >
              <span style="font-family:var(--st-mono);font-size:11px;color:var(--st-cyan);white-space:nowrap">{{ r.lat.toFixed(4) }}, {{ r.lng.toFixed(4) }}</span>
              <span style="font-size:11px;color:var(--st-text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.label }}</span>
            </button>
          </div>
          <p v-else-if="geocodeState === 'none'" class="st-hint" data-testid="st-geo-none">No place found for that name. Try another, or enter the coordinates below.</p>
          <p v-else-if="geocodeState === 'off'" class="st-hint" data-testid="st-geo-off">This frame does not search places. Enter the coordinates below.</p>
          <ReadFailedNotice v-else-if="geocodeState === 'failed'" dense :retry="searchGeocode" data-testid="st-geo-failed" />
          <p class="st-hint">{{ t('settingsView.location.nominatimCredit') }} <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">openstreetmap.org/copyright</a></p>
        </div>

        <!-- Coordinates -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.location.coordinates') }}</div>
          <div v-if="locationRead === 'loading'" style="color:var(--st-text-muted);padding:20px 0">{{ t('common.loading') }}</div>
          <ReadFailedNotice v-else-if="locationRead === 'failed'" dense :retry="loadLocation" />
          <div v-else>
            <div class="st-form-row">
              <div class="st-form-group">
                <label class="st-label">{{ t('settingsView.location.latitude') }} <span style="color:var(--st-red)">*</span></label>
                <input v-model="locationForm.latitude" type="number" step="0.0001" min="-90" max="90" class="st-input" placeholder="50.1109" style="font-family:var(--st-mono)" />
                <p class="st-hint">{{ t('settingsView.location.latitudeHint') }}</p>
              </div>
              <div class="st-form-group">
                <label class="st-label">{{ t('settingsView.location.longitude') }} <span style="color:var(--st-red)">*</span></label>
                <input v-model="locationForm.longitude" type="number" step="0.0001" min="-180" max="180" class="st-input" placeholder="8.6821" style="font-family:var(--st-mono)" />
                <p class="st-hint">{{ t('settingsView.location.longitudeHint') }}</p>
              </div>
            </div>

            <div class="st-form-group">
              <label class="st-label">{{ t('settingsView.location.locationLabel') }}</label>
              <input v-model="locationForm.location_label" class="st-input" placeholder="Frankfurt, Germany" />
              <p class="st-hint">{{ t('settingsView.location.locationLabelHint') }}</p>
            </div>

            <!-- Preview pill -->
            <div v-if="locationForm.latitude && locationForm.longitude" style="display:inline-flex;align-items:center;gap:10px;padding:6px 16px;background:rgba(var(--nc-primary-rgb),0.05);border:1px solid rgba(var(--nc-primary-rgb),0.15);border-radius:20px;font-size:12px;margin-bottom:16px">
              <span style="width:7px;height:7px;border-radius:50%;background:rgba(var(--nc-primary-rgb),0.9);box-shadow:0 0 6px rgba(var(--nc-primary-rgb),0.6);flex-shrink:0"></span>
              <span style="font-family:var(--st-mono);color:var(--st-cyan)">{{ parseFloat(locationForm.latitude).toFixed(4) }}°N · {{ parseFloat(locationForm.longitude).toFixed(4) }}°E</span>
              <span v-if="locationForm.location_label" class="st-coord-label">{{ locationForm.location_label }}</span>
            </div>

            <div class="st-save-bar">
              <button v-if="locationForm.latitude || locationForm.longitude" style="background:none;border:none;color:var(--st-red);font-size:12px;cursor:pointer" @click="locationForm = { latitude:'', longitude:'', location_label:'' }">
                {{ t('settingsView.location.clearCoords') }}
              </button>
              <span v-else></span>
              <div style="display:flex;align-items:center;gap:12px">
                <span v-if="locationSaved" class="st-saved-pill"><Icon name="mdi:check-circle" /> Saved to globe</span>
                <button class="st-btn-primary" @click="saveLocation" :disabled="locationSaving || !locationForm.latitude || !locationForm.longitude">
                  {{ locationSaving ? t('settingsView.profile.saving') : t('settingsView.location.pinToGlobe') }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="st-banner st-banner-info">
          <span class="st-banner-icon"><Icon name="mdi:information" /></span>
          Developer-level default for all your agents. Individual agents without explicit coordinates inherit this position with DID-hash jitter to avoid overlap.
        </div>
      </div>
    </div>

      <!-- Multi-Frame Console — admin-only cross-frame login (additive). -->
      <!-- ═══ INVITATIONS (§OPGUIDE-6) — mint / list / revoke invite codes ═══ -->
      <div v-if="activeTab === 'invitations'" class="st-col">
        <div class="st-card">
          <InvitationsPanel :open-registration="!betaInviteRequired" />
        </div>
      </div>

      <!-- ═══ APPROVALS (B3) — the spend step-up queue ═══ -->
      <div v-if="activeTab === 'approvals'" class="st-col">
        <div class="st-card">
          <SpendApprovalsPanel />
        </div>
      </div>

      <div v-if="activeTab === 'multiframe'" class="st-col">
        <MultiFrameConsole />
      </div>

      <!-- ═══ DEVELOPER CARD (§V0064 DevCard v0.1) — transparency + consent ═══ -->
      <div v-if="activeTab === 'devcard'" class="st-col">
        <!-- consent -->
        <div class="st-card st-card-accent">
          <div class="st-card-title">{{ t('settingsView.devcard.consentTitle') }}</div>
          <div class="st-dc-corridor" v-if="dcPassportOn !== null">
            <span class="st-dc-corridor-chip" :class="dcPassportOn ? 'on' : 'off'">
              <i></i>{{ dcPassportOn ? 'HOME PASSPORT CORRIDOR ACTIVE' : 'HOME PASSPORT CORRIDOR OFF' }}
            </span>
            <span class="st-dc-corridor-sub">{{ dcPassportOn ? 'this registry can relay your agents to foreign markets' : 'relaying is disabled registry-side; your consent below applies when it activates' }}</span>
          </div>
          <p class="st-dc-explain">{{ t('settingsView.devcard.consentExplain') }}</p>
          <div v-if="dcConsentRead === 'loading'" class="st-dc-empty" data-testid="dc-consent-loading">{{ t('common.loading') }}</div>
          <ReadFailedNotice v-else-if="dcConsentRead === 'failed'" dense :retry="dcReadConsent" />
          <div v-else class="st-dc-consent">
            <div class="st-dc-consent-state" :class="dcOptOut ? 'out' : 'in'">
              <Icon :name="dcOptOut ? 'mdi:shield-lock' : 'mdi:shield-check'" />
              <div>
                <b>{{ dcOptOut ? t('settingsView.devcard.optedOut') : t('settingsView.devcard.optedIn') }}</b>
                <span>{{ dcOptOut ? t('settingsView.devcard.optedOutSub') : t('settingsView.devcard.optedInSub') }}</span>
              </div>
            </div>
            <button class="st-btn-primary" :disabled="dcBusy" @click="dcToggleConsent">
              {{ dcOptOut ? t('settingsView.devcard.allowBtn') : t('settingsView.devcard.refuseBtn') }}
            </button>
          </div>
        </div>

        <!-- preview -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.devcard.previewTitle') }}</div>
          <p class="st-dc-explain">{{ t('settingsView.devcard.previewExplain') }}</p>
          <div v-if="dcAgentsRead === 'loading'" class="st-dc-empty">{{ t('common.loading') }}</div>
          <ReadFailedNotice v-else-if="dcAgentsRead === 'failed'" dense :retry="dcReadAgents" />
          <select :aria-label="t('settingsView.devcard.pickAgent', 'Pick an agent')" v-else-if="dcAgents.length" class="st-dc-select" v-model="dcAgentDid" @change="dcLoadPreview">
            <option value="" disabled>{{ t('settingsView.devcard.pickAgent') }}</option>
            <option v-for="a in dcAgents" :key="a.did" :value="a.did">{{ a.name || a.did }}</option>
          </select>
          <div v-else class="st-dc-empty"><Icon name="mdi:robot" /> {{ t('settingsView.devcard.noAgents') }}</div>

          <div v-if="dcPreview" class="st-dc-card">
            <div class="st-dc-card-head">
              <Icon name="mdi:fingerprint" />
              <span class="st-dc-schema">{{ dcPreview.schema }}</span>
              <span class="st-dc-standing" :class="dcPreview.standing">{{ dcPreview.standing.toUpperCase() }}</span>
            </div>
            <div class="st-dc-row"><span>DISPLAY NAME</span><b>{{ dcPreview.display_name }}</b></div>
            <div class="st-dc-row"><span>CONTACT</span><b>{{ dcPreview.contact_email }}</b></div>
            <div class="st-dc-row"><span>HOME REGISTRY</span><b>{{ dcPreview.home_registry }}</b></div>
            <div class="st-dc-row"><span>AGENT</span><b class="st-dc-mono">{{ dcPreview.agent_did }}</b></div>
            <div class="st-dc-row"><span>ORGS</span><b>{{ dcPreview.org_refs.length ? dcPreview.org_refs.join(', ') : '—' }}</b></div>
            <div class="st-dc-row"><span>EMAIL VERIFIED</span><b :class="dcPreview.attestations.email_verified ? 'st-dc-ok' : ''">{{ dcPreview.attestations.email_verified ? 'YES' : 'NO' }}</b></div>
            <p class="st-dc-note">{{ t('settingsView.devcard.previewNote') }}</p>
          </div>
        </div>

        <!-- disclosure audit -->
        <div class="st-card">
          <div class="st-card-title">{{ t('settingsView.devcard.logTitle') }} <span class="st-dc-count" v-if="dcDisclosures.length">{{ dcDisclosures.length }}</span></div>
          <p class="st-dc-explain">{{ t('settingsView.devcard.logExplain') }}</p>
          <div v-if="dcLogRead === 'loading'" class="st-dc-empty">{{ t('common.loading') }}</div>
          <ReadFailedNotice v-else-if="dcLogRead === 'failed'" dense :retry="dcReadLog" />
          <div v-else-if="dcDisclosures.length" class="st-dc-log">
            <div v-for="(d, i) in dcDisclosures" :key="i" class="st-dc-log-row">
              <Icon name="mdi:eye-outline" />
              <span class="st-dc-mono st-dc-peer" :title="d.requested_by">{{ d.requested_by }}</span>
              <span class="st-dc-mono st-dc-agent" :title="d.agent_did">{{ d.agent_did.slice(0, 22) }}…</span>
              <span class="st-dc-purpose">{{ d.purpose }}</span>
              <span class="st-dc-when">{{ d.at ? dayjs(d.at).fromNow() : '—' }}</span>
            </div>
          </div>
          <div v-else class="st-dc-empty"><Icon name="mdi:shield-check" /> {{ t('settingsView.devcard.logEmpty') }}</div>
        </div>
      </div>

    <!-- ══════════════════════════════════════ -->
    <!-- TELEPORT: Create Key Modal            -->
    <!-- ══════════════════════════════════════ -->
    <Teleport to="body">
      <div v-if="showCreateKeyModal" class="st-modal-backdrop" @click.self="showCreateKeyModal = false">
        <div class="st-modal">
          <div class="st-modal-header">
            <span class="st-modal-title"><Icon name="mdi:key-plus" /> Create API Key</span>
            <button class="st-modal-close" @click="showCreateKeyModal = false" aria-label="Close"><Icon name="mdi:close" /></button>
          </div>
          <div class="st-modal-body">
            <div class="st-form-group">
              <label class="st-label">Description</label>
              <input v-model="newKeyDesc" class="st-input" placeholder="e.g. Production Key, CI/CD Pipeline" @keydown.enter.prevent="createApiKey" />
              <p class="st-hint">A label to identify this key later</p>
            </div>
            <!-- §FEPARITY-1: AL-4 narrowing — scopes + forced-rotation expiry -->
            <div class="st-form-group">
              <label class="st-label">Authority</label>
              <div style="display:flex;gap:16px">
                <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                  <input v-model="newKeyScopeMode" type="radio" value="full" :disabled="apiKeySaving" /> Full authority (*)
                </label>
                <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
                  <input v-model="newKeyScopeMode" type="radio" value="scoped" :disabled="apiKeySaving" /> Scoped
                </label>
              </div>
              <template v-if="newKeyScopeMode === 'scoped'">
                <input v-model="newKeyScopes" class="st-input" style="margin-top:8px" placeholder="comma-separated, e.g. read:public, keys:manage" />
                <p class="st-hint">A scoped key cannot create further keys unless it carries <code>keys:manage</code>.</p>
              </template>
            </div>
            <div class="st-form-group">
              <label class="st-label">Expires in (days)</label>
              <input v-model.number="newKeyExpiresDays" class="st-input" type="number" min="0" placeholder="server default (365) — 0 = never" />
            </div>
          </div>
          <div class="st-modal-footer">
            <button class="st-btn-ghost" @click="showCreateKeyModal = false">Cancel</button>
            <button class="st-btn-primary" @click="createApiKey" :disabled="!newKeyDesc.trim() || apiKeySaving">
              {{ apiKeySaving ? 'Creating…' : 'Create Key' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ══════════════════════════════════════ -->
    <!-- TELEPORT: Show Created Key Modal      -->
    <!-- ══════════════════════════════════════ -->
    <Teleport to="body">
      <div v-if="showCreatedKeyModal" class="st-modal-backdrop" @click.self="showCreatedKeyModal = false; createdKeyPlain = ''">
        <div class="st-modal">
          <div class="st-modal-header">
            <span class="st-modal-title"><Icon name="mdi:check-circle" /> Key Created</span>
            <button class="st-modal-close" @click="showCreatedKeyModal = false; createdKeyPlain = ''" aria-label="Close"><Icon name="mdi:close" /></button>
          </div>
          <div class="st-modal-body">
            <div class="st-banner st-banner-warn" style="margin-bottom:16px">
              <span class="st-banner-icon"><Icon name="mdi:alert" /></span>
              Copy this key now — it will not be shown again.
            </div>
            <div class="st-key-reveal">
              <code class="st-key-reveal-code">{{ createdKeyPlain }}</code>
            </div>
          </div>
          <div class="st-modal-footer">
            <button class="st-btn-ghost" @click="copyKey" style="display:inline-flex;gap:6px;align-items:center">
              <Icon name="mdi:content-copy" /> Copy
            </button>
            <button class="st-btn-primary" @click="showCreatedKeyModal = false; createdKeyPlain = ''">Done</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ST1 (audit 2026-05-07): themed revoke-API-key confirm. -->
    <ConfirmActionModal
      :show="showRevokeKeyModal"
      title="// REVOKE API KEY"
      :message="keyToRevoke
        ? `Revoke <strong>${keyToRevoke.description || 'this API key'}</strong> (<code>${keyToRevoke.key_prefix || 'avreg_'}***</code>)? Any external system using it will lose registry access immediately. <strong>This cannot be undone.</strong>`
        : ''"
      tone="danger"
      confirm-text="Revoke Key"
      busy-text="Revoking…"
      :busy="revokeKeyBusy"
      @close="showRevokeKeyModal = false; keyToRevoke = null"
      @confirm="executeRevokeKey"
    />

    </div><!-- /st-content-wrap -->
  </div>
</template>

<style scoped>
.st-page {
  min-height: 100vh;
  /* §SETPOLISH: transparent — the opaque var(--st-bg) fill here was covering
     DashboardLayout's standard ViewAmbient, which is why Settings looked flat
     while every other view got the grid/beam/glow treatment. */
  background: transparent;
  color: var(--st-text, #c8d8f0);
  position: relative;
}
/* 2026-05-07: content above ambient bg layer. */
.st-content-wrap {
  position: relative;
  z-index: 1;
}

.st-page-header {
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.04) 0%, transparent 100%);
  border-bottom: 1px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
  padding: 24px 28px 20px;
}
.st-page-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  color: var(--st-cyan, var(--nc-primary));
  margin: 0 0 4px 0;
}
.st-page-sub {
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
}

.st-content {
  padding: 24px 28px;
  max-width: 860px;
}

.st-col {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.st-content--wide { max-width: 1240px; }

/* §FINDFIX F5 — notifications tab: log beside setup on wide viewports (his
   design note), each column top-aligned; stacked below. minmax(0,…) so the
   prefs matrix wraps inside its column instead of forcing overflow. */
@media (min-width: 1200px) {
  .st-nf-grid {
    display: grid;
    /* matrix (right) gets the wider column — its group labels collide with
       the channel headers below ~500px of width */
    grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
    gap: 16px;
    align-items: start;
  }
}

/* Role badges */
.st-role-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 4px;
}
.st-role-admin    { background: rgba(var(--st-red-rgb, 255, 77, 106), 0.12); color: var(--st-red); border: 1px solid rgba(var(--st-red-rgb, 255, 77, 106), 0.25); }
.st-role-verified { background: rgba(var(--st-green-rgb), 0.12);  color: var(--st-green); border: 1px solid rgba(var(--st-green-rgb), 0.25); }
.st-role-dev      { background: rgba(var(--nc-primary-rgb), 0.10);  color: var(--nc-primary); border: 1px solid rgba(var(--nc-primary-rgb), 0.22); }
.st-role-flare    { background: rgba(167, 139, 250, 0.12); color: #c4b5fd; border: 1px solid rgba(167, 139, 250, 0.32); }

/* §pass42 (2026-05-18) — Manage Flare CTA pill; theme-aware amber */
.st-role-flare-cta {
  background: rgba(var(--st-amber-rgb), 0.10);
  border: 1px solid rgba(var(--st-amber-rgb), 0.32);
  color: var(--st-amber);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: background 0.15s, border-color 0.15s;
}
.st-role-flare-cta:hover {
  background: rgba(var(--st-amber-rgb), 0.18);
  border-color: rgba(var(--st-amber-rgb), 0.55);
}

/* §pass42 (2026-05-18) — Activity skeleton loaders, theme-aware. */
.st-skel-row { opacity: 0.4; }
.st-skel-tile { background: var(--st-skel-low) !important; }
.st-skel-line {
  background: var(--st-skel-mid);
  border-radius: 4px;
}
.st-skel-line-1 { height: 12px; width: 60%; margin-bottom: 6px; }
.st-skel-line-2 { height: 10px; width: 35%; background: var(--st-skel-low); }

/* §pass42 (2026-05-18) — Location preview pill divider */
.st-coord-label {
  color: var(--st-text-muted);
  border-left: 1px solid var(--st-divider);
  padding-left: 10px;
}

/* §pass42 (2026-05-18) — Created API-key reveal box (modal) */
.st-key-reveal {
  background: var(--st-surface-deep);
  border: 1px solid var(--st-border);
  border-radius: 8px;
  padding: 16px;
}
.st-key-reveal-code {
  font-family: var(--st-mono);
  font-size: 12px;
  color: var(--st-cyan);
  word-break: break-all;
  user-select: all;
}

/* Geocode hover */
.geocode-result-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.09) !important;
  border-color: rgba(var(--nc-primary-rgb), 0.22) !important;
}

/* Modal */
.st-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  padding: 20px;
}
.st-modal {
  background: var(--st-surface);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 12px;
  width: 100%;
  max-width: 480px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
}
.st-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--st-divider);
}
.st-modal-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  color: var(--nc-primary);
}
.st-modal-close {
  background: none;
  border: none;
  color: var(--st-text-muted);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: color 0.15s;
}
.st-modal-close:hover { color: var(--st-text); }
.st-modal-body { padding: 20px; }
.st-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px 18px;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.08);
}

/* ── Fleet stats (was missing; caused overflow bug — 2026-04-20) ───── */
.st-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
}
.st-stat-tile {
  background: rgba(var(--nc-primary-rgb), 0.04);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.15);
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0; /* allow truncation inside grid cells */
  overflow: hidden;
}
.st-stat-value {
  font-family: 'IBM Plex Mono', 'JetBrains Mono', ui-monospace, monospace;
  font-size: 20px;
  font-weight: 700;
  color: var(--nc-primary);
  line-height: 1.1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.st-stat-label {
  font-family: 'IBM Plex Mono', 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.1em;
  color: var(--st-text-muted, #8696b8);
  text-transform: uppercase;
}

/* ═══════════════════════════════════════════════════════════════════════════
   §pass42 (2026-05-18) — Profile polish: 2-col identity, social-icon SVGs,
   avatar-URL live thumb, bio char-counter, info-tile grid, sticky save bar.
   ═══════════════════════════════════════════════════════════════════════════ */

/* Identity card 2-col layout — stacks on narrow viewports */
.st-identity-grid {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 28px;
  align-items: start;
}
@media (max-width: 768px) {
  .st-identity-grid { grid-template-columns: 1fr; gap: 20px; }
  .st-identity-rail { text-align: center; align-items: center; }
}
.st-identity-rail {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}
.st-identity-name {
  margin: 12px 0 0 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.st-identity-email {
  margin: 0;
  color: var(--st-text-muted);
  font-size: 13px;
}
.st-identity-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.st-identity-flare-cta {
  margin-top: 6px;
  align-self: flex-start;
}
@media (max-width: 768px) {
  .st-identity-flare-cta { align-self: center; }
}
.st-identity-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Bio char counter */
.st-label-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 6px;
}
.st-char-counter {
  font-family: var(--st-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--st-text-dim);
}
.st-char-counter-warn { color: var(--st-amber); }

/* Avatar URL live preview */
.st-avatar-url-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.st-avatar-url-row .st-input { flex: 1; min-width: 0; }
.st-avatar-url-thumb {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  overflow: hidden;
  background: var(--st-surface-deep);
  border: 1px solid var(--st-border);
  flex-shrink: 0;
}
.st-avatar-url-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* Social rows — promote SVG icons (replace emoji glyphs at 16px) */
.st-social-icon-svg {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 18px;
  color: var(--st-cyan);
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 6px;
  flex-shrink: 0;
}
.st-social-input { flex: 1; min-width: 0; }

/* Account-info tile grid */
.st-info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.st-info-tile {
  position: relative;
  text-align: left;
  background: var(--st-surface-deep);
  border: 1px solid var(--st-border);
  border-radius: 8px;
  padding: 12px 14px;
  color: var(--st-text);
  font: inherit;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.st-info-tile:hover {
  border-color: var(--st-border-hover);
  background: rgba(var(--nc-primary-rgb), 0.06);
}
.st-info-tile:hover .st-info-copy { opacity: 0.7; }
.st-info-tile-static { cursor: default; }
.st-info-tile-static:hover {
  border-color: var(--st-border);
  background: var(--st-surface-deep);
}
.st-info-label {
  font-family: var(--st-mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--st-text-muted);
  margin-bottom: 4px;
}
.st-info-value {
  font-size: 13px;
  word-break: break-word;
  line-height: 1.4;
}
.st-info-copy {
  position: absolute;
  top: 10px;
  right: 10px;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.15s;
  color: var(--st-cyan);
  pointer-events: none;
}

/* Sticky save bar — at-glance "saved Xm ago" + sticky during long scroll */
.st-save-bar-sticky {
  position: sticky;
  bottom: 0;
  background: linear-gradient(180deg, transparent 0%, var(--st-bg) 32%);
  padding: 16px 0 12px;
  margin-top: 8px;
  z-index: 3;
  align-items: center;
  display: flex;
  gap: 14px;
}
.st-save-meta {
  display: inline-flex;
  align-items: center;
  font-family: var(--st-mono);
  font-size: 11px;
  color: var(--st-text-muted);
  margin-right: auto;
}
.st-save-meta-ago {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--st-green);
}

/* Tab badge alarm-pulse — used when unread broadcasts > 0 */
.st-tab-badge-alarm {
  animation: st-tab-badge-pulse 2s ease-in-out infinite;
}
@keyframes st-tab-badge-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(var(--nc-primary-rgb), 0.45); }
  50%      { box-shadow: 0 0 0 4px rgba(var(--nc-primary-rgb), 0); }
}
@media (prefers-reduced-motion: reduce) {
  .st-tab-badge-alarm { animation: none; }
}

/* ──────────────────────────────────────────────────────────────────
   2026-05-24 — AAA+ shell rework (matches AdminEvents / Federation pattern)
   ────────────────────────────────────────────────────────────────── */

/* §SETPOLISH — Background & surfaces swatches. Pure-CSS previews of the
   ViewAmbient level each button selects (three bars at falling intensity;
   'off' shows a flat surface). No icons, no emoji — the preview IS the label. */
.st-bg-swatch {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
  width: 56px;
  height: 30px;
  padding: 5px 8px;
  border-radius: 6px;
  background:
    linear-gradient(rgba(var(--nc-primary-rgb), 0.05) 1px, transparent 1px) 0 0 / 8px 8px,
    rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
}
.st-bg-swatch i {
  width: 10px;
  border-radius: 2px 2px 0 0;
  background: rgba(var(--nc-primary-rgb), 0.85);
}
.st-bg-swatch[data-level='full'] i:nth-child(1)   { height: 18px; }
.st-bg-swatch[data-level='full'] i:nth-child(2)   { height: 12px; opacity: 0.75; }
.st-bg-swatch[data-level='full'] i:nth-child(3)   { height: 7px;  opacity: 0.5; }
.st-bg-swatch[data-level='subtle'] i:nth-child(1) { height: 9px;  opacity: 0.6; }
.st-bg-swatch[data-level='subtle'] i:nth-child(2) { height: 6px;  opacity: 0.42; }
.st-bg-swatch[data-level='subtle'] i:nth-child(3) { height: 4px;  opacity: 0.28; }
.st-bg-swatch[data-level='off'] { background: rgba(0, 0, 0, 0.35); }
.st-bg-swatch[data-level='off'] i { height: 2px; opacity: 0.22; }
.st-bg-swatch-sub {
  display: block;
  font-size: 10px !important;
  letter-spacing: 0.02em !important;
  color: var(--st-text-muted, #8696b8) !important;
  text-transform: none !important;
  font-weight: 400 !important;
  line-height: 1.35;
}

/* Hero — chip + h1 + lead, matches AdminEvents / Federation. */
.st-hero {
  padding: 36px 28px 22px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.04) 0%, transparent 100%);
}
.st-hero-inner {
  max-width: 1200px;
  margin: 0 auto;
}
.st-hero-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: 999px;
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  color: var(--st-cyan, var(--nc-primary));
  font-family: var(--st-mono, 'IBM Plex Mono', monospace);
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 600;
  margin-bottom: 14px;
}
.st-hero-chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--st-cyan, var(--nc-primary));
  box-shadow: 0 0 8px var(--st-cyan, var(--nc-primary));
}
.st-hero-h1 {
  font-family: var(--st-mono, 'IBM Plex Mono', monospace);
  font-size: 28px;
  font-weight: 700;
  color: var(--st-text, #e4ecf4);
  margin: 0 0 6px 0;
  display: flex;
  align-items: center;
  gap: 12px;
  letter-spacing: 0.01em;
}
.st-hero-h1 :deep(svg) {
  width: 26px;
  height: 26px;
  color: var(--st-cyan, var(--nc-primary));
}
.st-hero-lead {
  font-size: 14px;
  color: var(--st-text-muted, #8b9bb4);
  margin: 0;
  line-height: 1.55;
  max-width: 680px;
}

/* Tab strip — keep underline-active but allow Icon children + label wrapper. */
.st-tab :deep(svg) {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
}
.st-tab-label {
  display: inline;
}

/* .st-card-help lives in components/settings/tp-settings.css (§FESUITE 2026-10-04): scoped here it never reached the
   text of a child component (the two-factor panel's lead fell back to the page's larger default size). */

/* Small "§pass68"-style pill that sits inline with a card title. */
.st-card-title-badge {
  display: inline-block;
  padding: 1px 7px;
  margin-left: auto;
  font-family: var(--st-mono, 'IBM Plex Mono', monospace);
  font-size: 9.5px;
  letter-spacing: 0.06em;
  border-radius: 999px;
  background: rgba(120, 210, 130, 0.14);
  color: #a4e6b3;
  border: 1px solid rgba(120, 210, 130, 0.3);
  text-transform: none;
}

/* Modernized empty-state for the API tab (replaces the emoji-only placeholder). */
.st-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 0;
  color: var(--st-text-muted, #8b9bb4);
}
.st-empty-state :deep(svg) {
  width: 44px;
  height: 44px;
  color: var(--st-cyan, var(--nc-primary));
  opacity: 0.6;
  margin-bottom: 6px;
}
.st-empty-state p {
  margin: 0;
  font-size: 13px;
}
.st-empty-hint {
  font-size: 12px;
  color: var(--st-text-muted, #8b9bb4);
  opacity: 0.85;
}

/* Hide the old st-page-header that's no longer rendered. Defensive — even if
   a future refactor reintroduces the element, the new st-hero is canonical. */
.st-page-header { display: none; }

/* 2026-05-24 — emoji-sweep helpers. Each was introduced when an emoji got
   replaced with a proper Icon component; the surrounding context needed a
   small style adjustment to keep the layout balanced. */

/* API keys page navigation — 50 per page, real Prev/Next + range readout. */
.st-keys-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 14px 14px 4px 14px;
  margin-top: 8px;
  border-top: 1px dashed rgba(var(--nc-primary-rgb), 0.18);
  font-family: var(--st-mono, 'IBM Plex Mono', monospace);
}
.st-keys-pager-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--st-cyan, var(--nc-primary));
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.st-keys-pager-btn :deep(svg) { width: 14px; height: 14px; }
.st-keys-pager-btn:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.14);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
}
.st-keys-pager-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.st-keys-pager-info {
  font-size: 11.5px;
  color: var(--st-text-muted, #8b9bb4);
  white-space: nowrap;
}
.st-keys-pager-info strong {
  color: var(--st-text, #e4ecf4);
  font-weight: 600;
}
.st-keys-pager-range {
  margin-left: 6px;
}

/* Spin animation reused by the Activity tab refresh button. */
.st-spin {
  animation: st-spin-anim 1s linear infinite;
}
@keyframes st-spin-anim {
  to { transform: rotate(360deg); }
}

/* Location card hero badge — replaces the inline-emoji circle. */
.st-location-badge {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: rgba(var(--nc-primary-rgb), 0.07);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--st-cyan, var(--nc-primary));
}
.st-location-badge :deep(svg) {
  width: 28px;
  height: 28px;
}

/* "Saved to globe" pill (replaces the ✓ Saved to globe text). */
.st-saved-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--st-mono, 'IBM Plex Mono', monospace);
  font-size: 11px;
  color: var(--st-green, #00d27a);
}
.st-saved-pill :deep(svg) {
  width: 14px;
  height: 14px;
}

/* Activity-tab empty state shares the API-tab empty-state class but lives
   in its own scoped variant for spacing. */
.st-empty-state-activity {
  padding: 48px 0;
}

/* Generic banner-icon sizing — when the banner-icon span contains an Icon
   component, the SVG should align nicely with the body text. */
.st-banner-icon :deep(svg) {
  width: 18px;
  height: 18px;
  vertical-align: -3px;
}

/* st-role-badge children alignment — for "✓ Verified" → Icon + text. */
.st-role-badge :deep(svg) {
  width: 11px;
  height: 11px;
  vertical-align: -1px;
  margin-right: 2px;
}

/* st-modal-title and st-card-title-danger inline-icon alignment. */
.st-modal-title :deep(svg),
.st-card-title-danger :deep(svg) {
  width: 16px;
  height: 16px;
  vertical-align: -3px;
  margin-right: 4px;
}
.st-modal-close :deep(svg) {
  width: 16px;
  height: 16px;
}

/* Event-icon container: SVG centered inside the colored tile (replaces the
   emoji glyph in EVENT_EMOJI dict). */
.st-event-icon :deep(svg) {
  width: 18px;
  height: 18px;
}

/* ─── Developer Card tab (§V0064 DevCard v0.1) ─── */
.st-dc-explain { font-size: 12px; opacity: 0.62; margin: 0 0 14px; line-height: 1.55; max-width: 640px; }
.st-dc-consent { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.st-dc-consent-state { display: flex; align-items: center; gap: 11px; }
.st-dc-consent-state :deep(svg) { width: 26px; height: 26px; flex: none; }
.st-dc-consent-state.in { color: #10b981; }
.st-dc-consent-state.out { color: #f59e0b; }
.st-dc-consent-state div { display: flex; flex-direction: column; gap: 2px; }
.st-dc-consent-state b { font-size: 13px; letter-spacing: 0.04em; }
.st-dc-consent-state span { font-size: 11px; opacity: 0.6; color: rgba(255, 255, 255, 0.8); max-width: 460px; }
.st-dc-select {
  width: 100%; max-width: 420px; margin-bottom: 14px; padding: 9px 11px; border-radius: 8px;
  background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(var(--nc-primary-rgb), 0.22); color: #fff; font-size: 13px;
}
.st-dc-select:focus { outline: none; border-color: rgba(var(--nc-primary-rgb), 0.6); }
.st-dc-card {
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3); border-radius: 12px; padding: 14px 16px;
  background: linear-gradient(160deg, rgba(var(--nc-primary-rgb), 0.07), rgba(0, 0, 0, 0.25));
  max-width: 560px; font-family: ui-monospace, monospace;
}
.st-dc-card-head { display: flex; align-items: center; gap: 9px; margin-bottom: 11px; padding-bottom: 9px; border-bottom: 1px dashed rgba(var(--nc-primary-rgb), 0.25); }
.st-dc-card-head :deep(svg) { width: 17px; height: 17px; color: rgba(var(--nc-primary-rgb), 0.95); }
.st-dc-schema { font-size: 10px; letter-spacing: 0.14em; color: rgba(var(--nc-primary-rgb), 0.9); }
.st-dc-standing { margin-left: auto; font-size: 8.5px; letter-spacing: 0.12em; padding: 2px 9px; border-radius: 99px; border: 1px solid currentColor; }
.st-dc-standing.active { color: #10b981; }
.st-dc-standing.suspended { color: #ef4444; }
.st-dc-row { display: flex; justify-content: space-between; gap: 14px; font-size: 11px; padding: 4px 0; }
/* §FESUITE (2026-10-05): the Developer Card's faint text was opacity 0.5 (3.99:1 at 9-12px, axe needs 4.5:1); it takes
   the tab's muted colour (--st-text-muted, about 6:1) */
.st-dc-row span { color: var(--st-text-muted, #8696b8); letter-spacing: 0.1em; font-size: 9px; padding-top: 2px; flex: none; }
.st-dc-row b { font-weight: 600; text-align: right; word-break: break-all; }
.st-dc-mono { font-family: ui-monospace, monospace; }
.st-dc-ok { color: #10b981; }
.st-dc-note { font-size: 10px; opacity: 0.45; margin: 10px 0 0; line-height: 1.5; }
.st-dc-log { display: flex; flex-direction: column; }
.st-dc-log-row {
  display: grid; grid-template-columns: 18px minmax(0, 1.3fr) minmax(0, 1fr) auto auto; gap: 10px;
  align-items: center; font-size: 11px; font-family: ui-monospace, monospace;
  padding: 7px 4px; border-bottom: 1px dashed rgba(var(--nc-primary-rgb), 0.12);
}
.st-dc-log-row :deep(svg) { width: 13px; height: 13px; opacity: 0.6; }
.st-dc-peer { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: rgba(var(--nc-primary-rgb), 0.9); }
.st-dc-agent { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; opacity: 0.7; }
.st-dc-purpose { font-size: 9px; letter-spacing: 0.08em; color: var(--st-text-muted, #8696b8); }
.st-dc-when { font-size: 10px; color: var(--st-text-muted, #8696b8); white-space: nowrap; }
.st-dc-empty { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--st-text-muted, #8696b8); padding: 14px 4px; font-family: ui-monospace, monospace; }
.st-dc-empty :deep(svg) { width: 17px; height: 17px; }
/* §FESUITE (2026-10-05): the line a card shows while its own read is in flight */
.st-read-loading { font-size: 12px; opacity: 0.6; padding: 14px 4px; font-family: ui-monospace, monospace; }
.st-dc-corridor { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.st-dc-corridor-chip { display: inline-flex; align-items: center; gap: 6px; font-family: ui-monospace, monospace; font-size: 9px; letter-spacing: 0.13em; font-weight: 800; padding: 4px 11px; border-radius: 99px; border: 1px solid currentColor; }
.st-dc-corridor-chip i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.st-dc-corridor-chip.on { color: #10b981; }
.st-dc-corridor-chip.on i { animation: stdc-pulse 1.9s infinite; }
.st-dc-corridor-chip.off { color: #94a3b8; }
.st-dc-corridor-sub { font-size: 10px; color: var(--st-text-muted, #8696b8); font-family: ui-monospace, monospace; }
@keyframes stdc-pulse { 50% { opacity: 0.45; } }
.st-dc-count { display: inline-grid; place-items: center; min-width: 19px; height: 19px; margin-left: 7px; padding: 0 6px; border-radius: 99px; font-size: 10px; font-weight: 800; background: rgba(var(--nc-primary-rgb), 0.16); border: 1px solid rgba(var(--nc-primary-rgb), 0.4); color: rgba(var(--nc-primary-rgb), 1); font-family: ui-monospace, monospace; }
.st-dc-card { box-shadow: 0 0 26px -14px rgba(var(--nc-primary-rgb), 0.55); }
@media (max-width: 639.98px) {
  .st-dc-log-row { grid-template-columns: 16px 1fr auto; }
  .st-dc-log-row .st-dc-agent, .st-dc-log-row .st-dc-purpose { display: none; }
}
</style>
